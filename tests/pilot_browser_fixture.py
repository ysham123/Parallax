"""Local browser acceptance fixture; deterministic agents and simulated GitHub.

Run: PYTHONPATH=src:tests .venv/bin/python tests/pilot_browser_fixture.py
Open http://127.0.0.1:8766/demo-session/owner or /demo-session/reviewer.
Uses only loopback and disposable state, never real GitHub.
Optional: --port 8767 --root /tmp/parallax-demo --state-name fresh
"""
import asyncio,json,subprocess,sys,uuid,shutil
from pathlib import Path
from contextlib import asynccontextmanager
import httpx,uvicorn
from fastapi import HTTPException
from fastapi.responses import RedirectResponse,FileResponse,JSONResponse
from parallax.server import create_app
from parallax.store import Store
from parallax.deployment import Deployment
from parallax.worker import WorkerRuntime,WORKER_FEATURES
from parallax.models import CheckSpec,Participant
from parallax.workflows import WorkflowStart,TemplateInput
from parallax import authority
from test_engine import FakeRegistry
from pilot_fixture_support import fixture_options,prepare_fixture_root,fixture_asset,FixtureGitHub
import time
options=fixture_options()
ROOT,PROJECT=prepare_fixture_root(options.root)
STATE_SUFFIX='-'+options.state_name if options.state_name else ''
STUDIO=Path(__file__).resolve().parents[1]/'studio/dist'
if not (STUDIO/'index.html').is_file():raise SystemExit('Build hosted Studio assets before starting the fixture')
# Freeze this build for the fixture; another local build must not change its routes/assets.
SNAPSHOT=ROOT/('studio-assets'+STATE_SUFFIX)
shutil.copytree(STUDIO,SNAPSHOT,dirs_exist_ok=True)
STUDIO=SNAPSHOT
def git(*args):return subprocess.run(['git',*args],cwd=PROJECT,capture_output=True,text=True,check=True).stdout.strip()
if not (PROJECT/'.git').exists():
 git('init','-q');git('config','user.name','Fixture');git('config','user.email','fixture@example.invalid')
 (PROJECT/'maths.py').write_text('def add(a,b):\n    return a-b\n')
 (PROJECT/'check.py').write_text('from maths import add\nassert add(2,3)==5\n')
 git('add','.');git('commit','-qm','Fixture baseline')
class Registry(FakeRegistry):
 def __init__(self):super().__init__();self.turns={}
 async def catalog(self,*args,**kwargs):return {'provider':args[0],'models':[{'id':'fake','label':'Fixture model','efforts':['high'],'default_effort':'high'}],'default_model':'fake'}
 async def connections(self):return []
 async def discover(self,*args,**kwargs):return [{'id':p,'provider':p,'name':p,'label':p.title(),'status':'ready','authenticated':True,'capabilities':{'coordinate':True,'edit':True,'consult':True},'models':[{'id':'fake','label':'Fixture model','efforts':['high'],'default_effort':'high'}],'default_model':'fake'} for p in ['codex','claude']]
 async def run(self,provider,**kwargs):
  if kwargs['mode']=='coordinate':
   key=str(kwargs['workspace']);self.turn=self.turns.get(key,0)
   result=await super().run(provider,**kwargs);self.turns[key]=self.turn;return result
  previous=(kwargs['workspace']/'maths.py').read_text() if kwargs['mode']=='edit' else ''
  result=await super().run(provider,**kwargs)
  if kwargs['mode']=='edit':
   revision=previous.count('# revised')+1 if 'Return the sum.' in previous else 0
   f=kwargs['workspace']/'maths.py'; f.write_text('def add(a,b):\n    \"\"\"Return the sum.\"\"\"\n    return a+b'+('  '+('# revised '*revision).strip() if revision else '')+'\n')
  elif kwargs.get('schema'):
   finding={'title':'Inspect the return expression','body':'Simulated advisory for browser navigation testing, not a live provider assessment.','priority':'P3','code_location':{'path':'maths.py','line_range':{'start':3,'end':3}}}
   result['structured_output']['findings']=[finding]
   result['answer']=json.dumps(result['structured_output'])
  return result
BASE=git('rev-parse','HEAD');TREE=git('rev-parse','HEAD^{tree}')
github_http=FixtureGitHub(BASE,TREE)
remote=github_http.remote
origin=f'http://127.0.0.1:{options.port}'
deployment=Deployment(token='fixture-token-that-is-at-least-32-characters',origins=frozenset({origin}),hosts=frozenset({'localhost','127.0.0.1'}),projects=ROOT,public_origin=origin,pilot_enabled=True)
app=create_app(Store(ROOT/('relay'+STATE_SUFFIX)),Registry(),token=deployment.token,deployment=deployment,http_transport=httpx.MockTransport(github_http))
accounts=app.state.accounts;github=app.state.github_delivery
principals={}
for label,number in [('owner',9001),('reviewer',9002)]:
 account,workspace=accounts._admit({'subject':'github:'+str(number),'provider':'github','github_id':number,'login':label,'name':label.title(),'email':None,'avatar':None})
 cookie,_=accounts.create_session('account',workspace,account);principals[label]=accounts.principal(cookie)
team=accounts.teams.create(principals['owner'],'Acceptance team')['id']
invite=accounts.teams.invite(type(principals['owner'])(**{**principals['owner'].__dict__,'workspace':team,'workspace_kind':'team'}),'reviewer')
accounts.teams.accept(principals['reviewer'],invite['token'])
cookies={label:accounts.create_session('team',team,p.account['id'])[0] for label,p in principals.items()}
owner=accounts.principal(cookies['owner'])
hub=app.state.executors
pair=hub.pair(team,authority={'actor':owner.account['id'],'session':owner.session});worker=hub.connect(pair['code'],'Fixture Mac',{'platform':'darwin','workspaces':[str(PROJECT)],'features':WORKER_FEATURES})
from parallax.teams import ProjectBinding
accounts.teams.bind(owner,ProjectBinding(worker=worker['id'],path=str(PROJECT)),hub)
github.config={'id':'1','private_key_path':'fixture','client_id':'fixture','client_secret':'fixture','webhook_secret':'fixture','slug':'fixture'};github.app_jwt=lambda:'fixture-app-jwt'
binding=str(uuid.uuid4())
with app.state.store.connect() as db:
 db.execute('INSERT INTO github_bindings VALUES(?,?,?)',(binding,team,json.dumps({'installation':1,'repository':1,'worker':worker['id'],'project':str(PROJECT),'base':'main','full_name':'fixture/repo'})))
 db.execute('INSERT INTO github_installations VALUES(?,?,?)',(team,1,owner.account['id']))
original_publish=github.publish
worker_fixture_state={"mode":"online"}
async def publish(*args,**kwargs):remote['tree']=args[3]['tree'];return await original_publish(*args,**kwargs)
github.publish=publish
@app.middleware('http')
async def fixture_routes(request,next):
 if request.method=='POST' and request.url.path.startswith('/demo-worker/'):
  mode=request.url.path.rsplit('/',1)[-1]
  if mode not in {'online','offline','oversized'}:return JSONResponse({'detail':'Unknown fixture state'},status_code=404)
  worker_fixture_state['mode']=mode
  with app.state.store.connect() as db:
   db.execute('UPDATE workers SET seen=? WHERE id=?',(0 if mode=='offline' else time.time(),worker['id']))
  return JSONResponse({'fixture':True,'mode':mode})
 if request.url.path.startswith('/demo-session/'):
  label=request.url.path.split('/')[-1]
  if label not in {*cookies,'public'}:return JSONResponse({'detail':'Unknown fixture account'},status_code=404)
  response=RedirectResponse('/' if label=='public' else '/studio',status_code=303)
  if label=='public':response.delete_cookie('parallax_session')
  else:response.set_cookie('parallax_session',cookies[label],httponly=True,samesite='strict')
  return response
 if request.url.path in {'/','/studio','/studio/'}:return FileResponse(STUDIO/'index.html')
 if request.url.path.startswith('/assets/'):
  asset=fixture_asset(STUDIO,request.url.path)
  return FileResponse(asset) if asset else JSONResponse({'detail':'Asset not found'},status_code=404)
 return await next(request)
original_lifespan=app.router.lifespan_context
@asynccontextmanager
async def lifespan(app):
 async with original_lifespan(app), WorkerRuntime(Store(ROOT/('worker'+STATE_SUFFIX)),[PROJECT],registry=Registry()) as runtime:
  svc=runtime.app.state.workflows
  ctx=accounts.teams.context(owner,worker['id']);ctx['github_target']=await github.baseline(team,binding)
  token=authority.current.set(ctx)
  # Built-in recipe with explicit checks inherited from a server-owned shared recipe.
  recipe=accounts.teams.save_recipe(owner,TemplateInput(name='Fixture fix',coordinator=Participant(provider='codex'),team=[Participant(provider='claude')],checks=[CheckSpec(name='Addition check',argv=[sys.executable,'-B','check.py'])]))
  ctx['recipes']=accounts.teams.recipe_versions(team);authority.current.set(ctx)
  value=await svc.start(WorkflowStart(request_id=uuid.uuid4(),schema_version='2.0',github_binding=binding,workspace=str(PROJECT),prompt='Fix addition and keep the test unchanged.',template_id=recipe['id'],template_version=recipe['version']))
  await svc.jobs[value['id']];value=svc.get(value['id']);authority.current.reset(token)
  assert value['status']=='awaiting_approval',value.get('error')
  async def pump():
   while True:
    if worker_fixture_state['mode']=='offline':
     await asyncio.sleep(.05);continue
    try:
     hub.heartbeat(worker['id'],WORKER_FEATURES,{'status':'local_evidence_only','problem_count':1,'limit_bytes':8388608,'detail':'Synthetic oversized evidence is retained on this worker.'} if worker_fixture_state['mode']=='oversized' else {'status':'ok','problem_count':0,'limit_bytes':8388608,'detail':''})
     for command in hub.pending(worker['id']):
      hub.complete(worker['id'],command['id'],await runtime.dispatch(command))
     runs,events=runtime.snapshot({},0);hub.sync(worker['id'],runs,events)
    except HTTPException as exc:
     if exc.status_code in {401,404}:return  # Expected after explicit fixture worker revocation.
     raise
    await asyncio.sleep(.05)
  task=asyncio.create_task(pump())
  print(json.dumps({'fixture':'ready','workflow':value['id'],'status':value['status'],'origin':origin,'root':str(ROOT)}),flush=True)
  try:yield
  finally:task.cancel();await asyncio.gather(task,return_exceptions=True)
app.router.lifespan_context=lifespan
uvicorn.run(app,host='127.0.0.1',port=options.port,log_level='warning')
