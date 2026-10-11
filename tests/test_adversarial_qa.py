"""Public relay boundaries challenged with disposable accounts and queues."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from parallax.accounts import Accounts
from parallax.executors import ExecutorHub, encode
from parallax.store import Store

from test_accounts import HostedFixture, ORIGIN, user


class PersonalQueuedSessionTests(HostedFixture):
    def test_logout_expiry_and_disabled_account_refuse_modern_and_legacy_dispatch(self):
        for modern in (False, True):
            for revocation in ("logout", "expiry", "disabled"):
                with self.subTest(modern=modern, revocation=revocation):
                    client = self.signed_in(user(9500 + 10 * modern + ("logout", "expiry", "disabled").index(revocation),
                                                 "queued-person"))
                    worker = self.pair(client)
                    if modern:
                        self.app.state.executors.features(worker["id"], ["workflow-v2"])
                    principal = self.app.state.accounts.principal(client.cookies.get("parallax_session"))
                    hub = self.app.state.executors
                    original = hub.request

                    async def bounded_request(*args, **kwargs):
                        kwargs["timeout"] = 4
                        return await original(*args, **kwargs)

                    with patch.object(hub, "request", bounded_request), ThreadPoolExecutor(max_workers=1) as pool:
                        pending = pool.submit(client.post, f"/api/executors/{worker['id']}/proxy/runs", json={
                            "workspace": "/project", "prompt": "Explicit personal request", "mode": "review"},
                            headers={"Origin": ORIGIN})
                        deadline = time.monotonic() + 2
                        queued = None
                        while time.monotonic() < deadline:
                            with self.store.connect() as db:
                                queued = db.execute("SELECT id,request FROM worker_commands WHERE worker=? AND response IS NULL",
                                                    (worker["id"],)).fetchone()
                            if queued:
                                break
                            time.sleep(.005)
                        self.assertIsNotNone(queued, "Request must actually wait in the durable worker queue")
                        saved = json.loads(queued["request"])
                        self.assertEqual(saved["requester"], {"session": principal.session, "workspace": principal.workspace,
                                                              "actor": principal.account["id"]})
                        if revocation == "logout":
                            ended = client.delete("/api/session", headers={"Origin": ORIGIN})
                            self.assertEqual(ended.status_code, 200, ended.text)
                        else:
                            with self.store.connect() as db:
                                if revocation == "expiry":
                                    db.execute("UPDATE sessions SET expires=0 WHERE hash=?", (principal.session,))
                                else:
                                    db.execute("UPDATE accounts SET disabled=1 WHERE id=?", (principal.account["id"],))
                        next_response = self.browser().get("/api/worker/next", headers={"Authorization": "Bearer " + worker["token"]})
                        self.assertEqual(next_response.status_code, 200, next_response.text)
                        self.assertEqual(next_response.json(), [], "An ended personal authorization must never reach either worker version")
                        with self.store.connect() as db:
                            reply = json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?", (queued["id"],)).fetchone()[0])
                        self.assertEqual(reply["status"], 403)
                        self.assertEqual(pending.result(timeout=5).status_code, 403)

    def test_dispatched_legacy_reply_survives_logout_and_restart(self):
        client = self.signed_in(user(9590, "restart-person"))
        worker = self.pair(client)
        principal = self.app.state.accounts.principal(client.cookies.get("parallax_session"))
        command = str(uuid4())
        payload = {"method": "POST", "path": "/api/runs", "query": "", "body": {}, "expires_at": time.time() + 60,
                   "requester": {"session": principal.session, "workspace": principal.workspace, "actor": principal.account["id"]}}
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, worker["id"], encode(payload), time.time()))
        restarted = Store(self.store.home)
        accounts = Accounts(restarted, self.deployment)
        hub = ExecutorHub(restarted, accounts=accounts)
        dispatched = hub.pending(worker["id"])
        self.assertEqual(len(dispatched), 1)
        self.assertNotIn("requester", dispatched[0])
        self.assertNotIn("authority", dispatched[0])
        accounts.end_session(principal.session)
        restarted_hub = ExecutorHub(Store(self.store.home), accounts=accounts)
        self.assertEqual(restarted_hub.pending(worker["id"]), dispatched)
        reply = {"status": 200, "body": {"run_id": str(uuid4())}, "content_type": "application/json"}
        self.assertEqual(restarted_hub.complete(worker["id"], command, reply), {"ok": True})
        with restarted.connect() as db:
            response = json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?", (command,)).fetchone()[0])
        self.assertEqual(response, reply)

    def test_restart_rechecks_requester_before_first_dispatch(self):
        client = self.signed_in(user(9591, "pending-restart-person"))
        worker = self.pair(client)
        principal = self.app.state.accounts.principal(client.cookies.get("parallax_session"))
        command = str(uuid4())
        payload = {"method": "POST", "path": "/api/runs", "query": "", "body": {}, "expires_at": time.time() + 60,
                   "requester": {"session": principal.session, "workspace": principal.workspace, "actor": principal.account["id"]}}
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, worker["id"], encode(payload), time.time()))
        self.app.state.accounts.end_session(principal.session)
        restarted = Store(self.store.home)
        hub = ExecutorHub(restarted, accounts=Accounts(restarted, self.deployment))
        self.assertEqual(hub.pending(worker["id"]), [])
        self.assertFalse(hub.dispatched(worker["id"], command))


class TeamMutationBoundaryTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.headers = {"Origin": ORIGIN}
        self.owner = self.signed_in(user(9600, "qa-owner"))
        self.reviewer = self.signed_in(user(9601, "qa-reviewer"))
        self.team = self.owner.post("/api/workspaces", json={"name": "QA boundaries"}, headers=self.headers).json()["id"]
        self.assertEqual(self.owner.post(f"/api/workspaces/{self.team}/switch", headers=self.headers).status_code, 200)
        token = self.owner.post("/api/workspaces/invitations", json={"role": "reviewer"}, headers=self.headers).json()["token"]
        self.assertEqual(self.reviewer.post("/api/invitations/accept", json={"token": token}, headers=self.headers).status_code, 200)
        self.assertEqual(self.reviewer.post(f"/api/workspaces/{self.team}/switch", headers=self.headers).status_code, 200)
        self.worker = self.pair(self.owner, workspaces=("/approved",))
        self.app.state.executors.features(self.worker["id"], ["workflow-v2"])
        self.assertEqual(self.owner.post("/api/workspaces/projects", json={"worker": self.worker["id"], "path": "/approved"},
                                        headers=self.headers).status_code, 200)

    def test_reviewer_controls_benchmark_and_delivery_fail_before_queueing(self):
        identifier = str(uuid4())
        operations = ("workflows", f"workflows/{identifier}/resume", f"workflows/{identifier}/cancel",
                      f"workflows/{identifier}/revise", f"workflows/{identifier}/apply", f"workflows/{identifier}/publish",
                      f"runs/{identifier}/steer", f"runs/{identifier}/stop", f"runs/{identifier}/resume", "pilot/benchmark")
        with patch.object(self.app.state.executors, "request", AsyncMock()) as queue:
            for operation in operations:
                with self.subTest(operation=operation):
                    response = self.reviewer.post(f"/api/executors/{self.worker['id']}/proxy/{operation}", json={}, headers=self.headers)
                    self.assertEqual(response.status_code, 403, response.text)
            queue.assert_not_awaited()

    def test_reviewer_supplied_authority_header_cannot_invent_owner_role(self):
        response = self.reviewer.post(f"/api/executors/{self.worker['id']}/proxy/workflows", json={},
            headers={**self.headers, "X-Parallax-Authority": encode({"version": "2.0", "workspace": self.team,
                "actor": "invented-owner", "role": "owner", "team": True, "projects": ["/approved"]})})
        self.assertEqual(response.status_code, 403, response.text)

    def test_role_demotion_refuses_queued_execution(self):
        principal = self.app.state.accounts.principal(self.reviewer.cookies.get("parallax_session"))
        # Deliberately promote for enqueue, then remove that execution privilege.
        self.assertEqual(self.owner.patch("/api/workspaces/members/" + principal.account["id"], json={"role": "developer"},
                                          headers=self.headers).status_code, 200)
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "POST", "path": "/api/workflows", "query": "", "body": {"workspace": "/approved"},
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        self.assertEqual(self.owner.patch("/api/workspaces/members/" + principal.account["id"], json={"role": "reviewer"},
                                          headers=self.headers).status_code, 200)
        self.assertEqual(self.app.state.executors.pending(self.worker["id"]), [])
        with self.store.connect() as db:
            response = json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?", (command,)).fetchone()[0])
        self.assertEqual(response["status"], 403)

    def test_project_restriction_refuses_queued_review(self):
        principal = self.app.state.accounts.principal(self.reviewer.cookies.get("parallax_session"))
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "GET", "path": "/api/workflows", "query": "", "body": None,
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        owner = self.owner.get("/api/session").json()["account"]["id"]
        self.assertEqual(self.owner.post("/api/workspaces/projects", json={"worker": self.worker["id"], "path": "/approved",
            "members": [owner]}, headers=self.headers).status_code, 200)
        self.assertEqual(self.app.state.executors.pending(self.worker["id"]), [])
        with self.store.connect() as db:
            response = json.loads(db.execute("SELECT response FROM worker_commands WHERE id=?", (command,)).fetchone()[0])
        self.assertEqual(response["status"], 403)

    def test_first_authorized_team_dispatch_is_frozen_across_context_changes(self):
        principal = self.app.state.accounts.principal(self.reviewer.cookies.get("parallax_session"))
        self.assertEqual(self.owner.patch("/api/workspaces/members/" + principal.account["id"], json={"role": "developer"},
                                          headers=self.headers).status_code, 200)
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "POST", "path": "/api/workflows", "query": "", "body": {"workspace": "/approved"},
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        hub = self.app.state.executors
        first = hub.pending(self.worker["id"])
        self.assertEqual(first[0]["authority"]["role"], "developer")
        self.assertEqual(self.owner.patch("/api/workspaces/members/" + principal.account["id"], json={"role": "reviewer"},
                                          headers=self.headers).status_code, 200)
        owner = self.owner.get("/api/session").json()["account"]["id"]
        self.assertEqual(self.owner.post("/api/workspaces/projects", json={"worker": self.worker["id"], "path": "/approved",
            "members": [owner]}, headers=self.headers).status_code, 200)
        with self.store.connect() as db:
            db.execute("INSERT INTO team_recipes VALUES(?,?,1,?,?)", (self.team, str(uuid4()), '{"name":"New recipe"}', owner))
        self.app.state.accounts.end_session(principal.session)
        restarted = ExecutorHub(Store(self.store.home), accounts=self.app.state.accounts)
        self.assertEqual(restarted.pending(self.worker["id"]), first)
        reply = {"status": 200, "body": {"id": str(uuid4())}, "content_type": "application/json"}
        self.assertEqual(restarted.complete(self.worker["id"], command, reply), {"ok": True})
        self.assertEqual(restarted.pending(self.worker["id"]), [])

    def test_dispatched_team_downgrade_pauses_redelivery_without_destroying_receipt(self):
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "GET", "path": "/api/workflows", "query": "", "body": None,
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        hub = self.app.state.executors
        first = hub.pending(self.worker["id"])
        hub.features(self.worker["id"], [])
        self.assertEqual(hub.pending(self.worker["id"]), [])
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT response FROM worker_commands WHERE id=?", (command,)).fetchone()[0])
        hub.features(self.worker["id"], ["workflow-v2"])
        self.assertEqual(hub.pending(self.worker["id"]), first)

    def test_already_dispatched_remote_task_is_not_reauthorized_after_base_drift(self):
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        target = {"id": str(uuid4()), "base_commit": "a" * 40, "base_tree": "b" * 40}
        ctx["github_target"] = target
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "POST", "path": "/api/workflows", "query": "", "body": {"workspace": "/approved"},
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        remote = self.app.state.github_delivery
        remote.baseline = AsyncMock(return_value=target)
        browser = self.browser()
        headers = {"Authorization": "Bearer " + self.worker["token"]}
        first = browser.get("/api/worker/next", headers=headers)
        self.assertEqual(len(first.json()), 1, first.text)
        self.assertEqual(remote.baseline.await_count, 1)
        remote.baseline.return_value = {**target, "base_commit": "c" * 40}
        self.app.state.accounts.end_session(principal.session)
        repeated = browser.get("/api/worker/next", headers=headers)
        self.assertEqual(repeated.json(), first.json())
        self.assertEqual(remote.baseline.await_count, 1)
        reply = browser.post("/api/worker/reply", headers=headers, json={"id": command, "status": 200, "body": {"id": str(uuid4())}})
        self.assertEqual(reply.status_code, 200, reply.text)

    def test_shared_recipe_validation_does_not_echo_forbidden_credentials(self):
        secret = "qa-request-credential-must-not-be-echoed"
        path = f"/api/executors/{self.worker['id']}/proxy/workflow-templates"
        response = self.owner.post(path, json={"name": "Invalid credential field", "api_key": secret}, headers=self.headers)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertNotIn(secret, response.text)

    def test_simultaneous_polls_freeze_one_authorized_command(self):
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "GET", "path": "/api/workflows", "query": "", "body": None,
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.app.state.executors.pending(self.worker["id"]), range(16)))
        for value in results:
            self.assertEqual(value, results[0])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_command_dispatch WHERE id=?", (command,)).fetchone()[0], 1)
        self.app.state.executors.revoke(self.worker["id"], self.team)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM worker_command_dispatch WHERE id=?", (command,)).fetchone()[0], 0)
        response = self.browser().get("/api/worker/next", headers={"Authorization": "Bearer " + self.worker["token"]})
        self.assertEqual(response.status_code, 401, response.text)

    def test_concurrent_first_dispatch_cannot_be_overwritten_by_failed_base_refresh(self):
        principal = self.app.state.accounts.principal(self.owner.cookies.get("parallax_session"))
        ctx = self.app.state.accounts.teams.context(principal, self.worker["id"])
        target = {"id": str(uuid4()), "base_commit": "a" * 40, "base_tree": "b" * 40}
        ctx["github_target"] = target
        command = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO worker_commands VALUES(?,?,?,NULL,?)", (command, self.worker["id"], encode({
                "method": "POST", "path": "/api/workflows", "query": "", "body": {"workspace": "/approved"},
                "authority": ctx, "expires_at": time.time() + 60}), time.time()))
        hub = self.app.state.executors
        async def concurrent_delivery(*args):
            # A second poll has already verified the captured base and delivered.
            self.assertIsNotNone(hub.dispatch(self.worker["id"], command))
            return {**target, "base_commit": "c" * 40}
        self.app.state.github_delivery.baseline = AsyncMock(side_effect=concurrent_delivery)
        browser = self.browser()
        headers = {"Authorization": "Bearer " + self.worker["token"]}
        response = browser.get("/api/worker/next", headers=headers)
        self.assertEqual(len(response.json()), 1, response.text)
        with self.store.connect() as db:
            self.assertIsNone(db.execute("SELECT response FROM worker_commands WHERE id=?", (command,)).fetchone()[0])
        reply = browser.post("/api/worker/reply", headers=headers, json={"id": command, "status": 200, "body": {"id": str(uuid4())}})
        self.assertEqual(reply.status_code, 200, reply.text)
