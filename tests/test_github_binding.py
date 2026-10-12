"""Repository binding identity, atomicity and live endpoint authorization.

All GitHub replies and account identities are fixtures. No credentials or real
repositories are accessed, cloned, mutated or published by these tests.
"""
import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from fastapi import HTTPException
import httpx
from pydantic import ValidationError

from parallax.github_delivery import GitHubDelivery, RepositoryBinding
from parallax.store import Store
from test_accounts import HostedFixture, ORIGIN, user


class BindingServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'state')
        self.addCleanup(self.store.close)
        self.calls = []
        self.selected = True
        self.fail_list = False
        self.token_value = 'ghs_fixture_binding_ephemeral_canary'
        self.config = {'id': '1', 'private_key_path': 'unused-fixture-key',
                       'client_id': 'client', 'client_secret': 'fixture',
                       'webhook_secret': 'fixture', 'slug': 'pilot'}
        self.service = self.new_service(self.store)
        with self.store.connect() as db:
            db.execute('INSERT INTO github_installations VALUES(?,?,?)', ('space', 1, 'actor'))
        self.body = RepositoryBinding(request_id=uuid4(), installation=1, repository=99,
                                      worker=str(uuid4()), project='/approved', base='main')

    def new_service(self, store):
        service = GitHubDelivery(store, transport=httpx.MockTransport(self.handle), config=self.config)
        service.app_jwt = lambda: 'fixture-server-jwt'
        return service

    def handle(self, request):
        self.calls.append((request.method, request.url.path))
        if request.url.path == '/app/installations/1/access_tokens':
            self.assertEqual(json.loads(request.content), {'permissions': {'metadata': 'read'}})
            return httpx.Response(201, json={'token': self.token_value})
        if request.url.path == '/installation/repositories':
            self.assertEqual(request.headers['authorization'], 'Bearer ' + self.token_value)
            if self.fail_list:
                raise httpx.ReadTimeout('Fixture interrupted repository lookup')
            repos = [{'id': 99, 'full_name': 'fixture/repository', 'default_branch': 'main'}] if self.selected else []
            return httpx.Response(200, json={'repositories': repos})
        self.fail('Unexpected GitHub operation: ' + request.method + ' ' + request.url.path)

    def counts(self):
        with self.store.connect() as db:
            return tuple(db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                         for name in ('github_bindings', 'github_binding_operations'))

    async def test_same_request_replays_one_binding_and_rechecks_repository(self):
        authorized = []
        first = await self.service.bind('space', self.body, actor='actor', authorize=lambda: authorized.append(True))
        second = await self.service.bind('space', self.body, actor='actor', authorize=lambda: authorized.append(True))
        self.assertEqual(first, second)
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.calls.count(('GET', '/installation/repositories')), 2)
        self.assertEqual(len(authorized), 6)  # Initial, after await, and under writer lock.
        self.assertNotIn('request_id', first)
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM github_binding_operations').fetchone()
            self.assertEqual((row['workspace'], row['actor'], row['binding']), ('space', 'actor', first['id']))
            self.assertEqual(len(row['signature']), 64)
        for file in self.store.home.iterdir():
            if file.is_file():
                self.assertNotIn(self.token_value.encode(), file.read_bytes())
        self.assertTrue(all(path in ('/app/installations/1/access_tokens', '/installation/repositories')
                            for _, path in self.calls))

    async def test_restart_returns_same_saved_binding(self):
        first = await self.service.bind('space', self.body, actor='actor')
        self.store.close()
        restarted = Store(self.store.home)
        self.addCleanup(restarted.close)
        service = self.new_service(restarted)
        second = await service.bind('space', RepositoryBinding.model_validate_json(self.body.model_dump_json()), actor='actor')
        self.assertEqual(second, first)
        self.assertEqual(self.counts(), (1, 1))

    async def test_legacy_no_id_keeps_response_and_creates_without_journal(self):
        body = RepositoryBinding.model_validate(self.body.model_dump(exclude={'request_id'}))
        first = await self.service.bind('space', body)
        second = await self.service.bind('space', body)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(set(first), {'id', 'installation', 'repository', 'worker', 'project', 'base', 'full_name'})
        self.assertEqual(self.counts(), (2, 0))
        with self.store.connect() as db:
            for row in db.execute('SELECT body FROM github_bindings'):
                self.assertNotIn('request_id', json.loads(row[0]))

    async def test_same_id_cannot_cross_actor_workspace_or_change_request(self):
        await self.service.bind('space', self.body, actor='actor')
        before = len(self.calls)
        changes = [{'base': 'release'}, {'project': '/different'}, {'worker': str(uuid4())},
                   {'installation': 2}, {'repository': 100}]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(HTTPException) as raised:
                await self.service.bind('space', self.body.model_copy(update=changed), actor='actor')
            self.assertEqual(raised.exception.status_code, 409)
        for workspace, actor in [('space', 'different-actor'), ('other-space', 'actor')]:
            with self.subTest(scope=(workspace, actor)), self.assertRaises(HTTPException) as raised:
                await self.service.bind(workspace, self.body, actor=actor)
            self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(self.calls), before)
        self.assertEqual(self.counts(), (1, 1))

    async def test_saved_retry_refuses_removed_repository_or_installation(self):
        await self.service.bind('space', self.body, actor='actor')
        self.selected = False
        with self.assertRaises(HTTPException) as raised:
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(raised.exception.status_code, 403)
        self.selected = True
        with self.store.connect() as db:
            db.execute('DELETE FROM github_installations')
        with self.assertRaises(HTTPException) as raised:
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.counts(), (1, 1))

    async def test_timeout_before_persistence_retries_without_duplicate_binding(self):
        self.fail_list = True
        with self.assertRaises(httpx.ReadTimeout):
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(self.counts(), (0, 0))
        self.fail_list = False
        first = await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(await self.service.bind('space', self.body, actor='actor'), first)
        self.assertEqual(self.counts(), (1, 1))

    async def test_concurrent_identical_requests_reconcile_under_writer_lock(self):
        entered = 0
        both_entered = asyncio.Event()
        original = self.service.repositories
        async def barrier(*args):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), 2)
            return await original(*args)
        self.service.repositories = barrier
        first, second = await asyncio.gather(*(self.service.bind('space', self.body, actor='actor') for _ in range(2)))
        self.assertEqual(first, second)
        self.assertEqual(self.counts(), (1, 1))

    async def test_operation_insert_failure_rolls_back_binding_too(self):
        with self.store.connect() as db:
            db.executescript("CREATE TRIGGER binding_journal_failure BEFORE INSERT ON github_binding_operations "
                             "BEGIN SELECT RAISE(ABORT,'fixture journal failure'); END;")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(self.counts(), (0, 0))
        with self.store.connect() as db:
            db.execute('DROP TRIGGER binding_journal_failure')
        await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(self.counts(), (1, 1))

    async def test_local_installation_removed_during_lookup_prevents_commit(self):
        async def removed(*args):
            await asyncio.sleep(0)
            with self.store.connect() as db:
                db.execute('DELETE FROM github_installations')
            return [{'id': 99, 'full_name': 'fixture/repository', 'default_branch': 'main'}]
        self.service.repositories = removed
        with self.assertRaises(HTTPException) as raised:
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(self.counts(), (0, 0))

    async def test_authorization_is_checked_again_under_commit_lock(self):
        calls = 0
        def authorize():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise HTTPException(403, 'Fixture revocation at commit')
        with self.assertRaises(HTTPException):
            await self.service.bind('space', self.body, actor='actor', authorize=authorize)
        self.assertEqual(calls, 3)
        self.assertEqual(self.counts(), (0, 0))

    async def test_missing_journal_binding_refuses_silent_recreation(self):
        first = await self.service.bind('space', self.body, actor='actor')
        with self.store.connect() as db:
            db.execute('DELETE FROM github_bindings WHERE id=?', (first['id'],))
        with self.assertRaises(HTTPException) as raised:
            await self.service.bind('space', self.body, actor='actor')
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(self.counts(), (0, 1))

    async def test_schema_requires_uuid_and_cannot_receive_actor_or_scope(self):
        for change in ({'request_id': 'bad'}, {'actor': 'spoof'}, {'workspace': 'spoof'}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                RepositoryBinding.model_validate({**self.body.model_dump(mode='json'), **change})
        with self.assertRaisesRegex(ValueError, 'authenticated actor'):
            await self.service.bind('space', self.body)
        self.assertEqual(self.counts(), (0, 0))

    async def test_additive_startup_preserves_preexisting_binding_body(self):
        legacy = {'installation': 1, 'repository': 99, 'worker': self.body.worker,
                  'project': '/approved', 'base': 'main', 'full_name': 'fixture/repository'}
        raw = json.dumps(legacy, indent=2)
        identifier = str(uuid4())
        with self.store.connect() as db:
            db.execute('DROP TABLE github_binding_operations')
            db.execute('INSERT INTO github_bindings VALUES(?,?,?)', (identifier, 'space', raw))
        self.new_service(self.store)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT body FROM github_bindings WHERE id=?', (identifier,)).fetchone()[0], raw)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM github_binding_operations').fetchone()[0], 0)


class BindingEndpointTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.owner = self.signed_in(user(9701, 'binding-owner'))
        self.headers = {'Origin': ORIGIN}
        self.session = self.owner.get('/api/session').json()
        self.workspace = self.session['workspace']['id']
        self.actor = self.session['account']['id']
        self.worker = self.pair(self.owner, workspaces=('/approved',))
        self.service = self.app.state.github_delivery
        self.seed_installation()
        self.repository_reads = 0
        self.on_lookup = lambda: None
        async def repositories(workspace, installation):
            self.repository_reads += 1
            self.assertEqual((workspace, installation), (self.workspace, 1))
            await asyncio.sleep(0)
            self.on_lookup()
            return [{'id': 99, 'full_name': 'fixture/repository', 'default_branch': 'main'}]
        self.service.repositories = repositories
        self.body = {'request_id': str(uuid4()), 'installation': 1, 'repository': 99,
                     'worker': self.worker['id'], 'project': '/approved', 'base': 'main'}

    def seed_installation(self):
        with self.store.connect() as db:
            db.execute('INSERT INTO github_installations VALUES(?,?,?)', (self.workspace, 1, self.actor))

    def post(self, body=None, client=None):
        return (client or self.owner).post('/api/github/bindings', json=body or self.body, headers=self.headers)

    def counts(self):
        with self.store.connect() as db:
            return tuple(db.execute('SELECT COUNT(*) FROM ' + name).fetchone()[0]
                         for name in ('github_bindings', 'github_binding_operations'))

    def team(self):
        response = self.owner.post('/api/workspaces', json={'name': 'Binding team'}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.workspace = response.json()['id']
        self.assertEqual(self.owner.post('/api/workspaces/' + self.workspace + '/switch', headers=self.headers).status_code, 200)
        self.worker = self.pair(self.owner, workspaces=('/approved',))
        self.body['worker'] = self.worker['id']
        bound = self.owner.post('/api/workspaces/projects', json={'worker': self.worker['id'], 'path': '/approved'}, headers=self.headers)
        self.assertEqual(bound.status_code, 200, bound.text)
        self.seed_installation()

    def test_feature_and_endpoint_safe_retry_and_legacy_shape(self):
        feature = self.owner.get('/api/github/config')
        self.assertEqual(feature.status_code, 200, feature.text)
        self.assertIn('github-binding-idempotency-v1', feature.json()['features'])
        first, retry = self.post(), self.post()
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.repository_reads, 2)
        legacy = self.post({k: v for k, v in self.body.items() if k != 'request_id'})
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(set(legacy.json()), set(first.json()))
        self.assertNotIn('request_id', legacy.json())
        self.assertEqual(self.counts(), (2, 1))

    def test_owner_session_ended_during_lookup_refuses_commit(self):
        principal = self.app.state.accounts.principal(self.owner.cookies.get('parallax_session'))
        def ended():
            with self.store.connect() as db:
                db.execute('DELETE FROM sessions WHERE hash=?', (principal.session,))
        self.on_lookup = ended
        response = self.post()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.counts(), (0, 0))

    def test_worker_revoked_during_lookup_refuses_commit(self):
        self.on_lookup = lambda: self.app.state.executors.revoke(self.worker['id'], self.workspace)
        response = self.post()
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.counts(), (0, 0))

    def test_owner_role_changed_during_lookup_refuses_commit(self):
        self.team()
        def demoted():
            with self.store.connect() as db:
                db.execute("UPDATE memberships SET role='developer' WHERE workspace=? AND account=?", (self.workspace, self.actor))
        self.on_lookup = demoted
        response = self.post()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.counts(), (0, 0))

    def test_team_project_removed_during_lookup_refuses_commit(self):
        self.team()
        def removed():
            with self.store.connect() as db:
                db.execute('DELETE FROM project_bindings WHERE workspace=?', (self.workspace,))
        self.on_lookup = removed
        response = self.post()
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.counts(), (0, 0))

    def test_saved_retry_does_not_bypass_removed_team_project(self):
        self.team()
        first = self.post()
        self.assertEqual(first.status_code, 200, first.text)
        with self.store.connect() as db:
            db.execute('DELETE FROM project_bindings WHERE workspace=?', (self.workspace,))
        second = self.post()
        self.assertEqual(second.status_code, 403, second.text)
        self.assertEqual(self.counts(), (1, 1))
        self.assertEqual(self.repository_reads, 1)

    def test_endpoint_refuses_unapproved_path_wrong_worker_and_body_actor(self):
        for change, expected in [({'project': '/unapproved'}, 403), ({'worker': str(uuid4())}, 404), ({'actor': 'spoof'}, 422)]:
            with self.subTest(change=change):
                response = self.post({**self.body, **change})
                self.assertEqual(response.status_code, expected, response.text)
        self.assertEqual(self.repository_reads, 0)
        self.assertEqual(self.counts(), (0, 0))

    def test_account_deletion_purges_personal_binding_operations_only(self):
        created = self.post()
        self.assertEqual(created.status_code, 200, created.text)
        other_workspace = str(uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO github_binding_operations VALUES(?,?,?,?,?,?)',
                       (str(uuid4()), other_workspace, 'fixture-other', 'a' * 64, str(uuid4()), 1))
        response = self.owner.delete('/api/account?confirm=binding-owner', headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM github_binding_operations WHERE workspace=?', (self.workspace,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM github_binding_operations WHERE workspace=?', (other_workspace,)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM github_bindings WHERE workspace=?', (self.workspace,)).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
