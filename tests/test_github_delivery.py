"""Publication interruption, remote drift, signatures and token scope."""
import base64
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import urlparse,parse_qs
from uuid import uuid4
from unittest.mock import patch
import httpx
from parallax.github_delivery import GitHubDelivery, PublicationRequest, PERMISSIONS
from parallax.store import Store

class GitHubTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'state')
        self.head=None; self.pr=None; self.commits={}; self.mutations=0; self.pr_creations=0
        self.base='a'*40; self.base_tree='b'*40; self.tree='c'*40
        self.fail_after_commit=False; self.expired=False; self.tokens=[]
        self.service=GitHubDelivery(self.store,transport=httpx.MockTransport(self.handle),config={'id':'1','private_key_path':'unused','client_id':'client','client_secret':'secret','webhook_secret':'webhook','slug':'pilot'})
        self.service.app_jwt=lambda: 'server-app-jwt'
        self.binding=str(uuid4()); self.workflow=str(uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO github_bindings VALUES(?,?,?)',(self.binding,'space',json.dumps({'installation':1,'repository':99,'full_name':'test/repo','base':'main','worker':'worker','project':'/project'})))
        self.request=PublicationRequest(request_id=uuid4(),candidate_digest='d'*64,binding=self.binding,workflow=self.workflow,title='Fix addition',description='Reviewed candidate')
        self.package={'digest':'d'*64,'workflow':self.workflow,'binding':self.binding,'tree':self.tree,'baseline':self.base,'baseline_tree':self.base_tree,'additions':[{'path':'binary.bin','contents':base64.b64encode(b'\x00\xff').decode()}],'deletions':[]}

    def handle(self, request):
        path=request.url.path
        if request.url.host=='github.com' and path=='/login/oauth/access_token':
            self.assertIn('code_verifier',parse_qs(request.content.decode()))
            return httpx.Response(200,json={'access_token':'ghu_fixture_authorization'})
        if path=='/user/installations':
            return httpx.Response(200,json={'installations':[{'id':1,'app_id':1},{'id':2,'app_id':2},{'id':3,'app_id':1,'suspended_at':'now'}]})
        data=json.loads(request.content) if request.content else None
        if path=='/app/installations/1/access_tokens':
            self.assertEqual(request.headers['authorization'],'Bearer server-app-jwt')
            self.assertEqual(data['repository_ids'],[99]); self.assertEqual(data['permissions'],PERMISSIONS)
            token='ghs_ephemeral_'+str(len(self.tokens)); self.tokens.append(token)
            return httpx.Response(201,json={'token':token,'expires_at':'future'})
        if self.expired: return httpx.Response(401,json={'message':'expired'})
        if path=='/repos/test/repo/commits/main': return httpx.Response(200,json={'sha':self.base,'commit':{'tree':{'sha':self.base_tree}}})
        if path.startswith('/repos/test/repo/git/matching-refs/'):
            return httpx.Response(200,json=[{'ref':'refs/heads/parallax/'+self.workflow,'object':{'sha':self.head}}] if self.head else [])
        if path=='/repos/test/repo/git/refs': self.head=data['sha']; return httpx.Response(201,json={})
        if path=='/graphql':
            value=data['variables']['input']
            self.assertEqual(value['expectedHeadOid'],self.head)
            self.assertEqual(value['fileChanges']['additions'][0]['contents'],self.package['additions'][0]['contents'])
            self.mutations+=1; self.head=str(self.mutations)*40
            self.commits[self.head]={'tree':{'sha':self.tree},'message':value['message']['body']}
            if self.fail_after_commit:
                self.fail_after_commit=False
                raise httpx.ReadTimeout('simulated network interruption')
            return httpx.Response(200,json={'data':{'createCommitOnBranch':{'commit':{'oid':self.head}}}})
        if path.startswith('/repos/test/repo/git/commits/'):
            return httpx.Response(200,json=self.commits.get(self.head,{'tree':{'sha':'e'*40},'message':'External edit'}))
        if path=='/repos/test/repo/pulls' and request.method=='GET':
            if self.pr: self.pr['head']['sha']=self.head
            return httpx.Response(200,json=[self.pr] if self.pr else [])
        if path=='/repos/test/repo/pulls' and request.method=='POST':
            self.pr_creations+=1; self.pr={'number':8,'html_url':'https://github.com/test/repo/pull/8','state':'open','draft':True,'head':{'sha':self.head,'ref':'parallax/'+self.workflow}}
            return httpx.Response(201,json=self.pr)
        return httpx.Response(404,json={})

    async def test_publish_is_idempotent_and_tokens_never_persist(self):
        first=await self.service.publish('space','actor',self.request,self.package)
        second=await self.service.publish('space','actor',self.request,self.package)
        self.assertEqual(first,second); self.assertEqual((self.mutations,self.pr_creations),(1,1))
        self.assertEqual(first['pr'],8)
        text=self.store.path.read_bytes()
        for token in self.tokens: self.assertNotIn(token.encode(),text)
        with self.assertRaisesRegex(ValueError,'reused'):
            await self.service.publish('space','other-actor',self.request,self.package)

    async def test_interruption_after_commit_reconciles_remote_state(self):
        self.fail_after_commit=True
        with self.assertRaises(httpx.ReadTimeout): await self.service.publish('space','actor',self.request,self.package)
        result=await self.service.publish('space','actor',self.request,self.package)
        self.assertEqual(result['state'],'published'); self.assertEqual((self.mutations,self.pr_creations),(1,1))

    async def test_base_drift_and_external_head_edits_are_refused(self):
        self.base='f'*40
        with self.assertRaisesRegex(ValueError,'drifted'): await self.service.publish('space','actor',self.request,self.package)
        self.assertEqual(self.mutations,0)
        self.base='a'*40; self.head='e'*40
        with self.assertRaisesRegex(ValueError,'outside'): await self.service.publish('space','actor',self.request,self.package)
        self.assertEqual(self.mutations,0)

    async def test_revocation_before_remote_mutation_and_token_expiry(self):
        def revoked(): raise PermissionError('actor removed')
        with self.assertRaises(PermissionError): await self.service.publish('space','actor',self.request,self.package,authorize=revoked)
        self.assertEqual(self.mutations,0); self.assertIsNone(self.head)
        self.expired=True
        with self.assertRaises(Exception): await self.service.publish('space','actor',self.request,self.package)
        self.assertEqual(self.mutations,0)
        self.expired=False
        self.assertEqual((await self.service.publish('space','actor',self.request,self.package))['state'],'published')

    async def test_approved_revision_updates_same_draft_with_expected_head(self):
        first=await self.service.publish('space','actor',self.request,self.package)
        parent=self.head
        request=self.request.model_copy(update={'request_id':uuid4(),'workflow':str(uuid4()),'candidate_digest':'e'*64,'title':'Revised addition'})
        self.tree='f'*40
        package={**self.package,'workflow':request.workflow,'digest':request.candidate_digest,'tree':self.tree,'branch':first['branch'],'parent_head':parent}
        result=await self.service.publish('space','actor',request,package)
        self.assertEqual(result['branch'],first['branch'])
        self.assertEqual(result['pr'],first['pr'])
        self.assertEqual((self.mutations,self.pr_creations),(2,1))
        self.assertNotEqual(result['commit'],parent)
        self.assertEqual(self.service.completed_publication('space','actor',request),result)
        with self.assertRaisesRegex(ValueError,'reused'):
            self.service.completed_publication('space','another',request)

    async def test_closed_or_ready_pr_prevents_update(self):
        first=await self.service.publish('space','actor',self.request,self.package)
        self.pr['draft']=False
        request=self.request.model_copy(update={'request_id':uuid4(),'workflow':str(uuid4()),'candidate_digest':'e'*64})
        package={**self.package,'workflow':request.workflow,'digest':request.candidate_digest,'branch':first['branch'],'parent_head':self.head}
        with self.assertRaisesRegex(ValueError,'open draft'):
            await self.service.publish('space','actor',request,package)
        self.assertEqual(self.mutations,1)

    async def test_app_authorization_is_bound_one_use_and_rechecks_owner(self):
        principal=SimpleNamespace(workspace='space',account={'id':'actor'})
        url,binding=self.service.begin(principal,'https://staging.example')
        state=parse_qs(urlparse(url).query)['state'][0]
        with self.assertRaises(Exception): await self.service.finish('code',state,'foreign','https://staging.example',lambda *args:None)
        owners=[]
        await self.service.finish('code',state,binding,'https://staging.example',lambda *args:owners.append(args))
        self.assertEqual(len(owners),2)
        self.assertEqual(self.service.installations('space'),[1])
        self.assertNotIn(b'ghu_fixture_authorization',self.store.path.read_bytes())
        with self.assertRaises(Exception): await self.service.finish('code',state,binding,'https://staging.example',lambda *args:None)
        url,binding=self.service.begin(principal,'https://staging.example')
        state=parse_qs(urlparse(url).query)['state'][0]
        calls=0
        def revoked(*args):
            nonlocal calls
            calls+=1
            if calls==2: raise PermissionError('Owner removed during authorization')
        with self.assertRaises(PermissionError): await self.service.finish('code',state,binding,'https://staging.example',revoked)

    async def test_signed_webhooks_deduplicate_and_refuse_changed_payload(self):
        body='{"comment":"café"}'.encode()
        signature='sha256='+hmac.new(b'webhook',body,hashlib.sha256).hexdigest()
        identifier=str(uuid4())
        self.assertFalse(self.service.webhook(identifier,signature,body)['duplicate'])
        self.assertTrue(self.service.webhook(identifier,signature,body)['duplicate'])
        with self.assertRaises(Exception): self.service.webhook(identifier,signature,body+b' ')
        with self.assertRaises(Exception): self.service.webhook(identifier,None,body)
