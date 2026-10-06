"""1.1 project delivery contracts and realistic, fake-agent repository builds."""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from parallax.assessment import assess_project, package_directory
from parallax.engine import Engine, _sandbox_check
from parallax.models import RunSpec, Participant, ProjectProfile, CheckSpec
from parallax.store import Store
from parallax.receipt import get_receipt
from parallax.recovery import AlphaFeedback, save_feedback, export_feedback, recovery_options
from parallax.server import create_app
from test_engine import FakeRegistry, git

FIXTURES=Path(__file__).parent/'fixtures'

class DeliveryAgent(FakeRegistry):
    def __init__(self, files, reject_once=False, concurrent=None):
        super().__init__(); self.files=files;self.reject_once=reject_once;self.review_count=0;self.prompts=[];self.concurrent=concurrent
    async def run(self,provider,**kw):
        self.calls.append((provider,kw['mode']));self.prompts.append(kw['prompt'])
        structured=None
        if kw['mode']=='coordinate':
            actions=[{'id':'plan','action':'plan','tasks':[{'id':'invoice','title':'Repair invoice totals','provider':'claude','prompt':'Fix invoices; preserve tests','files':self.files,'acceptance':['empty=0','[2,3]=5','[10,-3]=7']}]}, {'id':'work1','action':'dispatch','task_ids':['invoice']}]
            if self.reject_once: actions.append({'id':'work2','action':'dispatch','task_ids':['invoice']})
            actions.extend([{'id':'validate','action':'validate'}, {'id':'integrate','action':'request_integration'}, {'id':'finish','action':'finish','summary':'Invoice checks pass'}])
            structured=actions[min(self.turn,len(actions)-1)];self.turn+=1
        elif kw['mode']=='edit':
            for file in self.files:
                path=kw['workspace']/file
                path.write_text(path.read_text().replace('sum(values) - 1','sum(values)').replace('0) - 1','0)'))
            if self.concurrent: self.concurrent();self.concurrent=None
        elif kw.get('schema'):
            self.review_count+=1
            approved=not (self.reject_once and self.review_count==1)
            structured={'approved':approved,'findings':[] if approved else [{'severity':'error','file':self.files[0],'message':'Inspect empty invoices against the original acceptance criteria'}],'summary':'Independent source inspection'}
        return {'ok':True,'answer':json.dumps(structured) if structured else 'Done','structured_output':structured,'session_id':'fixture','effective_settings':{'model':'fake','effort':'high'}}

class DeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/'project';self.project.mkdir();self.store=Store(self.root/'state')
    def fixture(self,kind):
        if kind=='mixed':
            shutil.copytree(FIXTURES/'python-service',self.project/'api');shutil.copytree(FIXTURES/'typescript-app',self.project/'web')
            files=['api/service.py','web/src/totals.ts']
        else:
            shutil.copytree(FIXTURES/kind,self.project,dirs_exist_ok=True)
            files=['service.py'] if kind=='python-service' else ['src/totals.ts']
        (self.project/'.gitignore').write_text('node_modules/\n.test-build/\n__pycache__/\n')
        git(self.project,'init','-q');git(self.project,'config','user.name','Fixture');git(self.project,'config','user.email','fixture@example.com');git(self.project,'add','.');git(self.project,'commit','-qm','starting snapshot')
        return files
    async def build(self,kind,**kwargs):
        files=self.fixture(kind)
        (self.project/'staged.txt').write_text('staged work');git(self.project,'add','staged.txt')
        (self.project/'notes.txt').write_text('untracked work')
        index=(self.project/'.git'/'index').read_bytes()
        registry=DeliveryAgent(files,**kwargs);engine=Engine(self.store,registry)
        spec=RunSpec(workspace=str(self.project),prompt='Correct invoice totals without changing acceptance tests',team=[Participant(provider='claude'),Participant(provider='grok',role='reviewer')])
        result=await engine.start(spec);await asyncio.wait_for(engine.jobs[result['run_id']],90)
        result=self.store.get(result['run_id'])
        self.assertEqual(result['status'],'completed',result['errors'])
        baseline=result['artifacts']['baseline_checks'];final=result['checks']
        self.assertTrue(any(not c['ok'] for c in baseline),baseline)
        self.assertTrue(all(c['ok'] for c in final),final)
        self.assertEqual([(c['argv'],c['cwd']) for c in baseline],[(c['argv'],c['cwd']) for c in final])
        self.assertEqual((self.project/'.git'/'index').read_bytes(),index)
        self.assertEqual((self.project/'notes.txt').read_text(),'untracked work')
        self.assertFalse((self.project/'node_modules').exists());self.assertFalse((self.project/'.venv').exists())
        receipt=get_receipt(self.store,result['run_id']);self.assertTrue(receipt['baseline']['recorded']);self.assertTrue(all(g['status']=='passed' for g in receipt['gates']))
        self.assertTrue(all(c['environment']['private'] for c in receipt['final_checks']))
        return result,registry
    async def test_python_service_baseline_failed_and_repaired_with_review_evidence(self):
        result,registry=await self.build('python-service',reject_once=True)
        self.assertEqual(result['tasks'][0]['attempts'],2)
        edits=[p for (provider,mode),p in zip(registry.calls,registry.prompts) if mode=='edit']
        self.assertIn('Inspect empty invoices',edits[-1]);self.assertIn('empty=0',edits[-1])
    @unittest.skipUnless(shutil.which('npm'),'requires npm')
    async def test_typed_react_app_real_compiler_and_checks(self): await self.build('typescript-app')
    @unittest.skipUnless(shutil.which('npm'),'requires npm')
    async def test_mixed_project_checks_use_explicit_package_roots(self):
        result,_=await self.build('mixed')
        self.assertEqual({c['cwd'] for c in result['checks']},{'api','web'})
        self.assertTrue(all(c['environment']['manifest_sha256'] for c in result['checks']))
    async def test_concurrent_owned_edit_blocks_apply_and_exposes_conflict_recovery(self):
        files=self.fixture('python-service');registry=DeliveryAgent(files,concurrent=lambda:(self.project/'service.py').write_text('USER_CONCURRENT_EDIT = True\n'));engine=Engine(self.store,registry)
        result=await engine.start(RunSpec(workspace=str(self.project),prompt='Fix invoices',team=[Participant(provider='claude'),Participant(provider='grok',role='reviewer')]))
        await asyncio.wait_for(engine.jobs[result['run_id']],30);result=self.store.get(result['run_id'])
        self.assertEqual(result['status'],'needs_attention');self.assertEqual((self.project/'service.py').read_text(),'USER_CONCURRENT_EDIT = True\n')
        self.assertEqual(recovery_options(result)['category'],'destination_conflict')
        self.assertTrue(result['diff']);self.assertFalse(result['artifacts'].get('integration_applied'))
    async def test_assessment_failure_dispatches_nothing(self):
        self.fixture('python-service');registry=DeliveryAgent(['service.py']);engine=Engine(self.store,registry)
        with patch('parallax.assessment.execution_capability',return_value={'enforced':False,'backend':None,'message':'Install isolation'}):
            with self.assertRaisesRegex(ValueError,'Install isolation'): await engine.start(RunSpec(workspace=str(self.project),prompt='Fix'))
        self.assertEqual(registry.calls,[]);self.assertEqual(self.store.runs(),[])
    async def test_configured_checks_cannot_be_removed_or_weakened(self):
        self.fixture('python-service');engine=Engine(self.store,DeliveryAgent(['service.py']))
        spec=RunSpec(workspace=str(self.project),prompt='Fix',team=[Participant(provider='claude')])
        with patch.object(engine,'_launch'):
            run=await engine.start(spec)
        from parallax.workspaces import WorkspaceManager
        manager=WorkspaceManager(self.project,Path(run['artifacts']['directory']));manager.prepare()
        with self.assertRaisesRegex(ValueError,'remains required'): await engine._verify(run['run_id'],spec,manager,[CheckSpec(name='Other',argv=['npm','run','test'])])

class AssessmentContractTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=Store(self.root/'state');self.project=self.root/'project';shutil.copytree(FIXTURES/'python-service',self.project)
        git(self.project,'init','-q');git(self.project,'config','user.name','Test');git(self.project,'config','user.email','test@example.com');git(self.project,'add','.');git(self.project,'commit','-qm','fixture')
    def test_manifest_and_instructions_discovered_without_running_code(self):
        a=assess_project(self.project)
        self.assertEqual(a.status,'ready');self.assertIn('AGENTS.md',a.instructions);self.assertEqual(a.packages[0]['kind'],'python');self.assertEqual(a.proposed_checks[0].cwd,'.')
        self.assertEqual(a.proposed_checks[0].argv[0],'python3')
    def test_symlink_and_escape_package_roots_are_rejected(self):
        (self.project/'link').symlink_to(self.root)
        for root in ('../outside','/tmp','link','missing'):
            with self.assertRaises(ValueError): package_directory(self.project,root)
        with self.assertRaises(ValueError): ProjectProfile(workspace=str(self.project),package_roots=['../outside'])
    def test_unlocked_node_and_poetry_setup_explicitly_blocked(self):
        (self.project/'package.json').write_text('{"name":"unlocked","scripts":{"test":"node test.js"}}')
        (self.project/'pyproject.toml').write_text('[tool.poetry]\nname="fixture"\n')
        a=assess_project(self.project)
        self.assertEqual(a.status,'blocked');self.assertTrue(any('npm lockfile' in i['message'] for i in a.issues));self.assertTrue(any('Poetry' in i['message'] for i in a.issues))
    def test_migration_preserves_old_runs_and_profiles(self):
        old={'schema_version':'1.0','workspace':str(self.project),'prompt':'legacy'}
        self.store.put_profile('legacy',old);self.store.put_project_profile('service',ProjectProfile(workspace=str(self.project)).model_dump());again=Store(self.store.home)
        self.assertEqual(again.profiles()[0]['spec'],old);self.assertEqual(again.project_profiles()[0]['name'],'service');self.assertEqual(RunSpec.model_validate(old).schema_version,'1.0')
    def test_missing_sandbox_fails_closed(self):
        with patch('parallax.engine.sys.platform','linux'),patch('parallax.engine.shutil.which',return_value=None):
            with self.assertRaisesRegex(ValueError,'enforceable'): _sandbox_check(['/bin/true'],self.project)
    def test_linux_sandbox_hides_host_data_before_rebinding_private_tmp_workspace(self):
        (self.project/'.ENV.local').write_text('private')
        with patch('parallax.engine.sys.platform','linux'),patch('parallax.engine.shutil.which',return_value='/usr/bin/bwrap'):
            command=_sandbox_check(['/bin/true'],self.project)
        private_bind=command.index('--bind')
        tmp_mount=next(i for i in range(len(command)-1) if command[i:i+2]==['--tmpfs','/tmp'])
        self.assertLess(tmp_mount,private_bind)
        self.assertIn('--unshare-pid',command)
        secret=command.index(str(self.project/'.ENV.local'))
        self.assertEqual(command[secret-2:secret],['--ro-bind','/dev/null'])
    @unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bwrap'),'requires Linux bubblewrap')
    def test_linux_live_private_workspace_and_host_canary(self):
        outside=self.root/'canary';outside.write_text('private')
        original_host_bytes=outside.read_bytes()
        (self.project/'.ENV.local').write_text('private')
        script=f'''import pathlib
p = pathlib.Path({str(self.project)!r})
outside = pathlib.Path({str(outside)!r})
assert p.exists()
assert not outside.exists(), 'Host canary is visible'
try:
    masked_secret = (p / '.ENV.local').read_text()
except PermissionError:
    pass
else:
    assert masked_secret == '', 'Project secret is readable'
try:
    outside.write_text('escaped')
except (PermissionError, FileNotFoundError):
    pass
# A write may create a new file in the private /tmp namespace. The parent
# verifies that this cannot change the actual host canary.
(p / 'output').write_text('isolated')
'''
        command=_sandbox_check([sys.executable,'-c',script],self.project)
        result=subprocess.run(command,capture_output=True,text=True,timeout=10,cwd=self.project)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((self.project/'output').read_text(),'isolated')
        self.assertEqual(outside.read_bytes(),original_host_bytes)
    def test_assessment_and_profile_shared_api_and_mcp_contracts(self):
        from parallax.cli import mcp_tools
        client=TestClient(create_app(self.store,FakeRegistry(),token='test'));headers={'Authorization':'Bearer test'}
        assessment=client.post('/api/project/assess',json={'workspace':str(self.project)},headers=headers)
        self.assertEqual(assessment.status_code,200);self.assertEqual(assessment.json()['schema_version'],'1.1')
        saved=client.put('/api/project-profiles/service',json={'workspace':str(self.project)},headers=headers);self.assertEqual(saved.status_code,200)
        self.assertEqual(client.get('/api/project-profiles',headers=headers).json()[0]['name'],'service')
        self.assertTrue({'parallax_assess_project','parallax_get_recovery','parallax_record_feedback'} <= {t['name'] for t in mcp_tools()})
    def test_feedback_export_excludes_all_private_run_data(self):
        from parallax.models import RunResult
        spec=RunSpec(workspace=str(self.project),prompt='PRIVATE PROMPT')
        result=RunResult(run_id='private-id',status='completed',spec=spec).model_dump();result['diff']='PRIVATE CODE';result['sessions']=[{'session_id':'PRIVATE SESSION'}];result['errors']=[{'message':'PRIVATE PATH /secret','category':'environment'}];self.store.save(result)
        self.assertEqual(export_feedback(self.store)['opt_in_records'],0)
        save_feedback(self.store,'private-id',AlphaFeedback(accepted=True,setup_unassisted=True,minutes=5,task_number=1))
        exported=json.dumps(export_feedback(self.store))
        for value in ('PRIVATE','private-id',str(self.project),'session_id'): self.assertNotIn(value,exported)
        self.assertEqual(export_feedback(self.store)['groups'][0]['accepted'],1)
        with self.assertRaises(ValueError): AlphaFeedback(accepted=True,setup_unassisted=True,minutes=1,task_number=1,prompt='secret')

class AlphaPreparationTests(unittest.TestCase):
    def test_matched_snapshots_preserve_effective_tree_and_counterbalance(self):
        import importlib.util
        module_spec=importlib.util.spec_from_file_location('prepare_alpha',Path(__file__).parents[1]/'scripts/prepare_alpha.py');module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';shutil.copytree(FIXTURES/'python-service',project)
            git(project,'init','-q');git(project,'config','user.name','Test');git(project,'config','user.email','test@example.com');git(project,'add','.');git(project,'commit','-qm','fixture')
            (project/'staged.txt').write_text('staged');git(project,'add','staged.txt');(project/'service.py').write_text('def total(values): return sum(values)\n');(project/'untracked.txt').write_text('untracked')
            original=(project/'.git'/'index').read_bytes()
            record=module.prepare(project,root/'study',RunSpec(workspace=str(project),prompt='Task',coordinator=Participant(provider='codex',model='chosen',effort='high')),1,1)
            for key in ('parallax_workspace','single_codex_workspace'):
                path=Path(record[key]);self.assertEqual((path/'service.py').read_text(),(project/'service.py').read_text());self.assertEqual((path/'untracked.txt').read_text(),'untracked');self.assertEqual((path/'staged.txt').read_text(),'staged')
            self.assertEqual((project/'.git'/'index').read_bytes(),original);self.assertFalse(record['inference_started']);self.assertEqual(record['order'],['parallax','single_codex'])
            self.assertEqual(record['codex_settings'],{'model':'chosen','effort':'high'})
            with self.assertRaisesRegex(ValueError,'fresh destination'):module.prepare(project,root/'study',RunSpec(workspace=str(project),prompt='Again'),1,1)

class RecoveryEvidenceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = DeliveryTests.asyncSetUp
    fixture = DeliveryTests.fixture
    async def test_completed_baseline_is_reused_after_runtime_restart(self):
        self.fixture('python-service');engine=Engine(self.store,DeliveryAgent(['service.py']));spec=RunSpec(workspace=str(self.project),prompt='Fix',team=[Participant(provider='claude')])
        with patch.object(engine,'_launch'): result=await engine.start(spec)
        from parallax.workspaces import WorkspaceManager
        manager=WorkspaceManager(self.project,Path(result['artifacts']['directory']));manager.prepare();engine.cancel_flags[result['run_id']]=asyncio.Event()
        await engine._baseline(result['run_id'],spec,manager)
        baseline=self.store.get(result['run_id'])['artifacts']['baseline_checks']
        second=Engine(Store(self.store.home),DeliveryAgent(['service.py']))
        from unittest.mock import AsyncMock
        with patch.object(second,'_checks',new=AsyncMock()) as check:
            await second._baseline(result['run_id'],spec,manager)
        check.assert_not_called();self.assertEqual(self.store.get(result['run_id'])['artifacts']['baseline_checks'],baseline)
    async def test_single_codex_metrics_have_no_parallax_telemetry(self):
        from parallax.recovery import save_baseline_feedback
        result=save_baseline_feedback(self.store,AlphaFeedback(accepted=True,setup_unassisted=True,minutes=8,task_number=1,comparison='single_codex'))
        self.assertFalse(result['shared']);groups=export_feedback(self.store)['groups'];self.assertEqual(groups[1]['tasks'],1);self.assertEqual(groups[1]['repair_attempts'],0);self.assertEqual(groups[0]['tasks'],0)

class CrossRuntimeLockTests(unittest.TestCase):
    def test_different_state_directories_cannot_dispatch_in_the_same_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);project=root/'project';project.mkdir();first=Store(root/'one');second=Store(root/'two')
            first.claim(str(project),'one')
            try:
                with self.assertRaisesRegex(ValueError,'another runtime'):second.claim(str(project),'two')
                self.assertEqual(second.runs(),[])
            finally:first.release('one')
            second.claim(str(project),'two');second.release('two')

class StudioWorkspaceTests(unittest.TestCase):
    def test_existing_runtime_opens_the_requested_project_and_exchanges_only_token(self):
        from parallax.cli import invoke
        import urllib.parse
        endpoint={'url':'http://127.0.0.1:1234','token':'private-token','workspace':'/old/project'}
        with patch('parallax.cli.service',return_value=endpoint):url=invoke('studio',{'workspace':'/new/project with spaces'})
        self.assertEqual(url['workspace'],'/new/project with spaces')
        with tempfile.TemporaryDirectory() as temporary:
            client=TestClient(create_app(Store(Path(temporary)),FakeRegistry(),token='private-token'))
            response=client.get('/?'+urllib.parse.urlencode({'token':'private-token','workspace':'/new/project with spaces'}),follow_redirects=False)
            self.assertEqual(response.status_code,303);self.assertNotIn('token',response.headers['location']);self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(response.headers['location']).query),{'workspace':['/new/project with spaces']})
            self.assertEqual(client.get(response.headers['location']).status_code,200)
