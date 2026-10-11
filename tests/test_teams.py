"""Two-account team authorization and queued revocation checks."""
import asyncio
import json
import time
from unittest.mock import AsyncMock
from uuid import uuid4
from test_accounts import HostedFixture, user, ORIGIN
from parallax.executors import encode

class TeamTests(HostedFixture):
    def make_deployment(self, **changes):
        return super().make_deployment(pilot_enabled=True, **changes)

    def setUp(self):
        super().setUp()
        self.owner=self.signed_in(user(701,'owner-person'))
        self.other=self.signed_in(user(702,'developer-person'))
        self.headers={'Origin':ORIGIN}
        result=self.owner.post('/api/workspaces',json={'name':'Test team'},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        self.team=result.json()['id']
        self.switch(self.owner,self.team)

    def switch(self, client, workspace):
        response=client.post('/api/workspaces/'+workspace+'/switch',headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)

    def join(self, role='developer'):
        invite=self.owner.post('/api/workspaces/invitations',json={'role':role},headers=self.headers)
        self.assertEqual(invite.status_code,200,invite.text)
        response=self.other.post('/api/invitations/accept',json={'token':invite.json()['token']},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.switch(self.other,self.team)

    def test_team_is_explicit_and_personal_workers_are_not_shared(self):
        session=self.owner.get('/api/session').json()
        self.assertEqual(session['workspace']['kind'],'team')
        self.assertEqual(session['workspace']['role'],'owner')
        self.assertEqual(self.other.post('/api/workspaces/'+self.team+'/switch',headers=self.headers).status_code,400)
        self.assertEqual(self.owner.get('/api/executors').json(),[])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT kind FROM sessions WHERE workspace=?",(self.team,)).fetchone()[0],'team')
        # Previous servers reject the new session kind instead of treating team data as personal.

    def test_role_permissions_expired_invitation_and_removal(self):
        invite=self.owner.post('/api/workspaces/invitations',json={'role':'reviewer'},headers=self.headers).json()
        with self.store.connect() as db: db.execute('UPDATE invitations SET expires=0')
        self.assertEqual(self.other.post('/api/invitations/accept',json={'token':invite['token']},headers=self.headers).status_code,410)
        self.join('reviewer')
        self.assertEqual(self.other.post('/api/executors/pair',headers=self.headers).status_code,403)
        self.assertEqual(self.other.post('/api/workspaces/invitations',json={'role':'developer'},headers=self.headers).status_code,403)
        actor=self.other.get('/api/session').json()['account']['id']
        self.assertEqual(self.owner.delete('/api/workspaces/members/'+actor,headers=self.headers).status_code,200)
        self.assertEqual(self.other.get('/api/session').status_code,401)

    def test_project_policy_and_queue_reauthorize_after_member_removal(self):
        self.join()
        worker=self.pair(self.owner,workspaces=('/approved',))
        response=self.owner.post('/api/workspaces/projects',json={'worker':worker['id'],'path':'/unapproved'},headers=self.headers)
        self.assertEqual(response.status_code,403)
        response=self.owner.post('/api/workspaces/projects',json={'worker':worker['id'],'path':'/approved'},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.app.state.executors.features(worker['id'],['workflow-v2'])
        principal=self.app.state.accounts.principal(self.other.cookies.get('parallax_session'))
        auth=self.app.state.accounts.teams.context(principal,worker['id'])
        command=str(uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO worker_commands VALUES(?,?,?,NULL,?)',(command,worker['id'],encode({'method':'POST','path':'/api/workflows','query':'','body':{},'authority':auth,'expires_at':time.time()+60}),time.time()))
        self.owner.delete('/api/workspaces/members/'+principal.account['id'],headers=self.headers)
        self.assertEqual(self.app.state.executors.pending(worker['id']),[])
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT response FROM worker_commands WHERE id=?',(command,)).fetchone()[0])['status'],403)

    def test_dispatch_rechecks_remote_base_and_ended_session(self):
        worker=self.pair(self.owner,workspaces=('/approved',))
        self.app.state.executors.features(worker['id'],['workflow-v2'])
        self.owner.post('/api/workspaces/projects',json={'worker':worker['id'],'path':'/approved'},headers=self.headers)
        principal=self.app.state.accounts.principal(self.owner.cookies.get('parallax_session'))
        auth=self.app.state.accounts.teams.context(principal,worker['id'])
        target={'id':str(uuid4()),'base_commit':'a'*40,'base_tree':'b'*40}
        auth['github_target']=target
        command=str(uuid4())
        def queue(identifier):
            with self.store.connect() as db:
                db.execute('INSERT INTO worker_commands VALUES(?,?,?,NULL,?)',(identifier,worker['id'],encode({'method':'POST','path':'/api/workflows','query':'','body':{},'authority':auth,'expires_at':time.time()+60}),time.time()))
        queue(command)
        self.app.state.github_delivery.baseline=AsyncMock(return_value={**target,'base_commit':'c'*40})
        response=self.browser().get('/api/worker/next',headers={'Authorization':'Bearer '+worker['token']})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json(),[])
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT response FROM worker_commands WHERE id=?',(command,)).fetchone()[0])['status'],409)
        pending=str(uuid4());queue(pending)
        with self.store.connect() as db: db.execute('DELETE FROM sessions WHERE hash=?',(principal.session,))
        self.assertEqual(self.app.state.executors.pending(worker['id']),[])
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT response FROM worker_commands WHERE id=?',(pending,)).fetchone()[0])['status'],403)

    def test_reviewer_cannot_start_and_older_worker_requires_update(self):
        self.join('reviewer')
        worker=self.pair(self.owner,workspaces=('/approved',))
        self.owner.post('/api/workspaces/projects',json={'worker':worker['id'],'path':'/approved'},headers=self.headers)
        path='/api/executors/'+worker['id']+'/proxy/workflows'
        self.assertEqual(self.other.post(path,json={},headers=self.headers).status_code,409)
        self.app.state.executors.features(worker['id'],['workflow-v2'])
        self.assertEqual(self.other.post(path,json={},headers=self.headers).status_code,403)
        self.assertEqual(self.other.get('/api/executors/'+str(uuid4())+'/proxy/workflows').status_code,404)

    def test_downgraded_worker_clears_capability_and_refuses_queued_team_data(self):
        worker=self.pair(self.owner,workspaces=('/approved',))
        self.app.state.executors.features(worker['id'],['workflow-v2'])
        self.owner.post('/api/workspaces/projects',json={'worker':worker['id'],'path':'/approved'},headers=self.headers)
        principal=self.app.state.accounts.principal(self.owner.cookies.get('parallax_session'))
        auth=self.app.state.accounts.teams.context(principal,worker['id'])
        command=str(uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO worker_commands VALUES(?,?,?,NULL,?)',(command,worker['id'],encode({'method':'GET','path':'/api/workflows','query':'','body':None,'authority':auth,'expires_at':time.time()+60}),time.time()))
        old=self.browser()
        sync=old.post('/api/worker/sync',headers={'Authorization':'Bearer '+worker['token']},json={'runs':[],'events':[]})
        self.assertEqual(sync.status_code,200,sync.text)
        response=old.get('/api/worker/next',headers={'Authorization':'Bearer '+worker['token']})
        self.assertEqual(response.json(),[])
        with self.store.connect() as db:
            self.assertEqual(json.loads(db.execute('SELECT response FROM worker_commands WHERE id=?',(command,)).fetchone()[0])['status'],409)
        path='/api/executors/'+worker['id']+'/proxy/workflows'
        self.assertEqual(self.owner.get(path).status_code,409)

    def test_team_account_deletion_preserves_other_members(self):
        self.join()
        self.assertEqual(self.owner.delete('/api/account',params={'confirm':'owner-person'},headers=self.headers).status_code,409)
        self.assertEqual(self.other.delete('/api/account',params={'confirm':'developer-person'},headers=self.headers).status_code,200)
        self.assertEqual(len(self.owner.get('/api/workspaces/members').json()),1)
        self.assertEqual(self.owner.get('/api/session').status_code,200)
