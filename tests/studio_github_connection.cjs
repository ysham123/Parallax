#!/usr/bin/env node
// Actual contextual connection handlers with controlled reads and writes.
// No network, GitHub accounts/tokens, repository mutations or tasks are used.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const {webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'),src=path.join(root,'studio/src'),ts=require(path.join(root,'studio/node_modules/typescript'));
const savedLoad=Module._load,savedTs=require.extensions['.ts'],savedTsx=require.extensions['.tsx'];
let rendering,calls=[],respond=async()=>{throw new Error('No response installed');},passed=0;
const views=new Set(),storage=new Map(),assignments=[];
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
const react={
  useState(initial){const r=rendering,i=r.index++;if(!(i in r.slots))r.slots[i]=typeof initial==='function'?initial():initial;return[r.slots[i],value=>{r.slots[i]=typeof value==='function'?value(r.slots[i]):value;}];},
  useRef(initial){const r=rendering,i=r.index++;if(!(i in r.slots))r.slots[i]={current:initial};return r.slots[i];},
  useEffect(effect,deps){const r=rendering,i=r.index++,old=r.slots[i];if(!old||!same(old.deps,deps))r.effects.push(()=>{old?.cleanup?.();r.slots[i]={deps,cleanup:effect()};});},
  useMemo(fn,deps){const r=rendering,i=r.index++,old=r.slots[i];if(!old||!same(old.deps,deps))r.slots[i]={deps,value:fn()};return r.slots[i].value;},
  useCallback(fn,deps){return react.useMemo(()=>fn,deps);},
};
const jsx=(type,props,key)=>({type,props:props||{},key});
Module._load=function(request,parent,...args){
  if(request==='react')return react;
  if(request==='react/jsx-runtime')return{jsx,jsxs:jsx,Fragment:Symbol.for('fragment')};
  if(parent?.filename.startsWith(src)&&request==='./api')return{
    relayApi(p,init){calls.push({path:p,init});return respond(p,init);},messageOf:e=>e.message||String(e),
  };
  return savedLoad.call(this,request,parent,...args);
};
function compile(module,filename){const result=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});module._compile(result.outputText,filename);}
require.extensions['.ts']=compile;require.extensions['.tsx']=compile;
global.crypto=webcrypto;
const sessionStorage={getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
global.window={sessionStorage};global.location={assign:url=>assignments.push(url)};
function renderer(component,props){const view={component,props,slots:[],effects:[],index:0,render(){rendering=this;this.index=0;this.effects=[];this.tree=this.component(this.props);for(const effect of this.effects)effect();return this.tree;},unmount(){for(const slot of this.slots)slot?.cleanup?.();views.delete(this);}};views.add(view);return view;}
function nodes(tree){if(!tree||typeof tree!=='object')return[];if(Array.isArray(tree))return tree.flatMap(nodes);return[tree,...nodes(tree.props?.children)];}
function text(tree){if(Array.isArray(tree))return tree.map(text).join('');if(tree&&typeof tree==='object')return text(tree.props?.children);return tree==null||tree===false?'':String(tree);}
const button=(tree,label)=>nodes(tree).find(node=>node.type==='button'&&text(node)===label);
function field(tree,label){const holder=nodes(tree).find(node=>node.type==='label'&&text(node.props.children?.[0])===label);return nodes(holder).find(node=>['input','select'].includes(node.type));}
function options(tree,label){return nodes(field(tree,label)).filter(node=>node.type==='option').map(node=>text(node));}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}
async function settle(view){for(let i=0;i<6;i++){await new Promise(resolve=>setImmediate(resolve));view.render();}}
function check(label,fn){fn();passed++;console.log('PASS',label);}
const identity={actor:'owner-a',workspace:'team-a'},target={worker:'worker-a',path:'/project',machineName:'Team Mac'};
const config={configured:true,installation_url:'https://github.com/apps/parallax-test/installations/new',features:['github-binding-idempotency-v1']};
const session={account:{id:identity.actor},workspace:{id:identity.workspace,kind:'team',role:'owner'}};
const context={authority:{version:'2.0',actor:identity.actor,workspace:identity.workspace,role:'owner',team:true,projects:['/project','/other']}};
const repoA={id:11,full_name:'example/alpha',default_branch:'main'},repoB={id:22,full_name:'example/beta',default_branch:'release'};
let GitHubConnection,rememberGitHubReturn,githubReturn,clearGitHubReturn;
const writes=()=>calls.filter(call=>call.init?.method&&call.init.method!=='GET');
const bindings=()=>writes().filter(call=>call.path==='/github/bindings');
async function fixture(settings={}){
  calls=[];assignments.length=0;storage.clear();
  const state={config,installations:[1,2],repos:{1:[repoA],2:[repoB]},session:structuredClone(session),context:structuredClone(context),
    configReader:null,installationReader:null,repoReader:null,sessionReader:null,contextReader:null,bindReader:null,
    authorization:{url:'https://github.com/login/oauth/authorize?client_id=synthetic-public-id'},connected:[],...settings.state};
  respond=async(p,init)=>{
    if(p==='/github/config')return state.configReader?state.configReader(init):state.config;
    if(p==='/github/installations')return state.installationReader?state.installationReader(init):state.installations;
    const match=p.match(/^\/github\/installations\/(\d+)\/repositories$/);
    if(match)return state.repoReader?state.repoReader(Number(match[1]),init):state.repos[Number(match[1])];
    if(p==='/session')return state.sessionReader?state.sessionReader(init):state.session;
    if(p.startsWith('/executors/')&&p.endsWith('/proxy/context'))return state.contextReader?state.contextReader(p,init):state.context;
    if(p==='/github/connect/start')return state.authorization;
    if(p==='/github/bindings'){
      const body=JSON.parse(init.body);
      return state.bindReader?state.bindReader(body):{id:'synthetic-binding',...body,full_name:(state.repos[body.installation]||[]).find(repo=>repo.id===body.repository)?.full_name};
    }
    throw new Error('Unexpected request '+p);
  };
  const view=renderer(GitHubConnection,{identity,target,online:true,canManage:true,onConnected:value=>state.connected.push(value),...settings.props});
  view.render();await settle(view);return{view,state};
}
async function choose(view,installation=1,repository=11){field(view.tree,'Installation').props.onChange({target:{value:String(installation)}});view.render();await settle(view);field(view.tree,'Repository').props.onChange({target:{value:String(repository)}});view.render();}
const change=(props,kind)=>kind==='actor'?{...props,identity:{...props.identity,actor:'owner-b'}}:kind==='workspace'?{...props,identity:{...props.identity,workspace:'team-b'}}:kind==='worker'?{...props,target:{...props.target,worker:'worker-b'}}:kind==='project'?{...props,target:{...props.target,path:'/other'}}:kind==='offline'?{...props,online:false}:{...props,canManage:false};

(async()=>{
  ({GitHubConnection}=require(path.join(src,'GitHubConnection.tsx')));
  ({rememberGitHubReturn,githubReturn,clearGitHubReturn}=require(path.join(src,'github-connection-state.ts')));
  const configPending=deferred();let{view,state}=await fixture({state:{configReader:()=>configPending.promise}});
  check('Initial unknown configuration is loading, never disabled deployment or automatic authorization',()=>{
    assert.match(text(view.tree),/Loading GitHub connection/);assert.doesNotMatch(text(view.tree),/not enabled on this deployment/);
    assert.equal(writes().length,0);assert.equal(assignments.length,0);
  });configPending.reject(new Error('Configuration temporarily unavailable'));await settle(view);
  check('Failed configuration is visible with explicit Retry instead of a fabricated unconfigured state',()=>{
    assert.match(text(view.tree),/Configuration temporarily unavailable/);assert.ok(button(view.tree,'Retry connection setup'));
    assert.doesNotMatch(text(view.tree),/not enabled on this deployment/);assert.equal(writes().length,0);
  });state.configReader=null;button(view.tree,'Retry connection setup').props.onClick();view.render();await settle(view);
  check('Setup Retry loads real installation choices without creating a connection',()=>{
    assert.deepEqual(options(view.tree,'Installation'),['Choose installation','1','2']);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture({state:{config:{...config,configured:false}}}));
  check('Unconfigured deployment preserves local delivery guidance and makes no installation or mutation request',()=>{
    assert.match(text(view.tree),/not enabled on this deployment/);assert.match(text(view.tree),/local delivery/);
    assert.equal(calls.some(call=>call.path==='/github/installations'),false);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture());const oldRepos=deferred();state.repoReader=id=>id===1?oldRepos.promise:[repoB];
  field(view.tree,'Installation').props.onChange({target:{value:'1'}});view.render();field(view.tree,'Installation').props.onChange({target:{value:'2'}});view.render();await settle(view);
  oldRepos.resolve([repoA]);await settle(view);
  check('Late repositories from an older installation cannot replace current choices',()=>{
    assert.equal(field(view.tree,'Installation').props.value,2);assert.deepEqual(options(view.tree,'Repository'),['Choose repository','example/beta']);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture());const oldFailure=deferred();state.repoReader=id=>id===1?oldFailure.promise:[repoB];
  field(view.tree,'Installation').props.onChange({target:{value:'1'}});view.render();field(view.tree,'Installation').props.onChange({target:{value:'2'}});view.render();await settle(view);
  oldFailure.reject(new Error('Obsolete installation failure'));await settle(view);
  check('Late installation failure cannot annotate the newly selected installation',()=>assert.doesNotMatch(text(view.tree),/Obsolete installation failure/));view.unmount();

  ({view,state}=await fixture());state.repoReader=()=>Promise.reject(new Error('Selected repository read failed'));
  field(view.tree,'Installation').props.onChange({target:{value:'1'}});view.render();await settle(view);
  check('Current repository read failure blocks binding and offers a read-only retry',()=>{
    assert.match(text(view.tree),/Selected repository read failed/);assert.equal(button(view.tree,'Connect repository').props.disabled,true);assert.ok(button(view.tree,'Retry repositories'));assert.equal(writes().length,0);
  });state.repoReader=null;button(view.tree,'Retry repositories').props.onClick();view.render();await settle(view);
  check('Retry repositories recovers current choices without authorizing or binding automatically',()=>{
    assert.deepEqual(options(view.tree,'Repository'),['Choose repository','example/alpha']);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture({state:{repos:{1:[],2:[repoB]}}}));field(view.tree,'Installation').props.onChange({target:{value:'1'}});view.render();await settle(view);
  check('Successful empty repository list is distinct from failed or pending reads',()=>{
    assert.match(text(view.tree),/No repositories are available/);assert.ok(button(view.tree,'Refresh repositories'));
    assert.doesNotMatch(text(view.tree),/Repositories could not load|Loading selected repositories/);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture({state:{config:{...config,features:[]}}}));await choose(view);
  button(view.tree,'Connect repository').props.onClick();await settle(view);
  check('Older relay capability refuses binding even through the disabled handler',()=>{
    assert.match(text(view.tree),/safe retry support/);assert.equal(button(view.tree,'Connect repository').props.disabled,true);assert.equal(bindings().length,0);
  });view.unmount();

  for(const denied of ['session actor','session workspace','session role','context actor','context workspace','context role','project grant','missing authority']){
    ({view,state}=await fixture());await choose(view);
    if(denied==='session actor')state.session.account.id='other-actor';
    if(denied==='session workspace')state.session.workspace.id='other-workspace';
    if(denied==='session role')state.session.workspace.role='developer';
    if(denied==='context actor')state.context.authority.actor='other-actor';
    if(denied==='context workspace')state.context.authority.workspace='other-workspace';
    if(denied==='context role')state.context.authority.role='reviewer';
    if(denied==='project grant')state.context.authority.projects=['/other'];
    if(denied==='missing authority')state.context.authority=null;
    button(view.tree,'Connect repository').props.onClick();await settle(view);
    check('Fresh '+denied+' mismatch refuses consequential repository binding',()=>{
      assert.equal(bindings().length,0);assert.equal(state.connected.length,0);assert.match(text(view.tree),/access changed|no longer available/);
    });view.unmount();
  }

  for(const altered of ['actor','workspace','worker','project','offline','Owner downgrade','unmount']){
    ({view,state}=await fixture());await choose(view);const capturedBind=button(view.tree,'Connect repository').props.onClick;
    const capturedAuthorize=button(view.tree,'Authorize another installation').props.onClick;
    if(altered==='unmount')view.unmount();else{view.props=change(view.props,altered);view.render();await settle(view);}
    capturedBind();capturedAuthorize();await new Promise(resolve=>setImmediate(resolve));
    check('Captured allowed callbacks cannot write after '+altered,()=>{
      assert.equal(writes().length,0);assert.equal(state.connected.length,0);assert.equal(assignments.length,0);
    });if(altered!=='unmount')view.unmount();
  }

  ({view,state}=await fixture());await choose(view);const deferredSession=deferred();state.sessionReader=()=>deferredSession.promise;
  button(view.tree,'Connect repository').props.onClick();view.render();view.props={...view.props,target:{...target,worker:'worker-b'}};view.render();await settle(view);
  deferredSession.resolve(session);await settle(view);
  check('Worker change while session preflight is pending dispatches no old binding',()=>{assert.equal(bindings().length,0);assert.equal(state.connected.length,0);});view.unmount();

  for(const action of ['bind','authorize']){
    ({view,state}=await fixture());if(action==='bind')await choose(view);const preflight=deferred();state.sessionReader=()=>preflight.promise;
    button(view.tree,action==='bind'?'Connect repository':'Authorize another installation').props.onClick();view.render();
    view.props={...view.props,online:false};view.render();await settle(view);view.props={...view.props,online:true};view.render();await settle(view);
    preflight.resolve(session);await settle(view);
    check('Offline/reconnect cannot revive an older pending '+action+' intent in the same scope',()=>{
      assert.equal(writes().length,0);assert.equal(assignments.length,0);assert.equal(state.connected.length,0);
    });view.unmount();
  }

  for(const cycle of ['Owner downgrade','project']){
    ({view,state}=await fixture());await choose(view);const original=view.props,preflight=deferred();state.sessionReader=()=>preflight.promise;
    button(view.tree,'Connect repository').props.onClick();view.render();view.props=change(view.props,cycle);view.render();await settle(view);
    view.props=original;view.render();await settle(view);preflight.resolve(session);await settle(view);
    check('Returning from '+cycle+' change cannot revive an old binding intent with matching final props',()=>{
      assert.equal(bindings().length,0);assert.equal(state.connected.length,0);
    });view.unmount();
  }

  ({view,state}=await fixture());await choose(view);const capturedOldForm=button(view.tree,'Connect repository').props.onClick;
  field(view.tree,'Remote base branch').props.onChange({target:{value:'release'}});view.render();capturedOldForm();await settle(view);
  check('Captured binding for an older form selection cannot dispatch after the branch changed',()=>assert.equal(bindings().length,0));view.unmount();

  ({view,state}=await fixture());await choose(view);const oldFormPermission=deferred();state.contextReader=()=>oldFormPermission.promise;
  button(view.tree,'Connect repository').props.onClick();view.render();await settle(view);
  field(view.tree,'Remote base branch').props.onChange({target:{value:'release'}});view.render();oldFormPermission.resolve(context);await settle(view);
  check('Changed form while permission is pending refuses the older captured destination',()=>assert.equal(bindings().length,0));view.unmount();

  ({view,state}=await fixture());await choose(view);let attempts=0;
  state.bindReader=body=>{attempts++;return Promise.reject(new Error('Synthetic uncertain binding timeout'));};
  const bind=button(view.tree,'Connect repository').props.onClick;bind();bind();await settle(view);
  check('Two immediate binding invocations produce one in-flight preflight and mutation',()=>assert.equal(bindings().length,1));
  button(view.tree,'Connect repository').props.onClick();await settle(view);
  check('Unchanged uncertain binding retry retains the exact request identity and target without client roles',()=>{
    const bodies=bindings().map(call=>JSON.parse(call.init.body));assert.equal(bodies.length,2);assert.equal(bodies[0].request_id,bodies[1].request_id);
    assert.equal(bodies[0].worker,target.worker);assert.equal(bodies[0].project,target.path);assert.equal(bodies[0].installation,1);assert.equal(bodies[0].repository,11);
    assert.equal('actor' in bodies[0],false);assert.equal('role' in bodies[0],false);
  });field(view.tree,'Remote base branch').props.onChange({target:{value:'release'}});view.render();button(view.tree,'Connect repository').props.onClick();await settle(view);
  check('Explicitly changed destination gets a different binding operation identity',()=>{
    const bodies=bindings().map(call=>JSON.parse(call.init.body));assert.notEqual(bodies[1].request_id,bodies[2].request_id);assert.equal(bodies[2].base,'release');
  });view.unmount();

  ({view,state}=await fixture());await choose(view);button(view.tree,'Connect repository').props.onClick();await settle(view);
  check('Successful binding reports only the exact approved folder destination after fresh session and context',()=>{
    assert.equal(state.connected.length,1);assert.match(text(view.tree),/Repository connected/);assert.match(text(view.tree),/example\/alpha.*main/);
    const paths=calls.map(call=>call.path);assert.ok(paths.indexOf('/session')<paths.indexOf('/executors/worker-a/proxy/context'));
    assert.ok(paths.indexOf('/executors/worker-a/proxy/context')<paths.indexOf('/github/bindings'));assert.equal(assignments.length,0);
  });view.unmount();

  ({view,state}=await fixture());await choose(view);state.bindReader=body=>({...body,id:'wrong-binding',worker:'another-worker',full_name:'example/alpha'});
  button(view.tree,'Connect repository').props.onClick();await settle(view);
  check('Mismatched returned binding is an error and never reports a connection for the requested project',()=>{
    assert.match(text(view.tree),/returned connection does not match/);assert.equal(state.connected.length,0);assert.doesNotMatch(text(view.tree),/Repository connected/);
  });view.unmount();

  ({view,state}=await fixture());await choose(view);const lateBinding=deferred();state.bindReader=()=>lateBinding.promise;
  button(view.tree,'Connect repository').props.onClick();view.render();await settle(view);assert.equal(bindings().length,1);view.unmount();
  lateBinding.resolve({id:'old-scope-binding',worker:target.worker,project:target.path,installation:1,repository:11,full_name:repoA.full_name,base:'main'});
  await new Promise(resolve=>setImmediate(resolve));
  check('A dispatched binding response after unmount cannot announce a new-scope connection',()=>assert.equal(state.connected.length,0));

  ({view,state}=await fixture());const lateAuthorization=deferred();state.authorization=lateAuthorization.promise;
  button(view.tree,'Authorize another installation').props.onClick();view.render();await settle(view);
  assert.equal(writes().filter(call=>call.path==='/github/connect/start').length,1);view.unmount();
  lateAuthorization.resolve({url:'https://github.com/login/oauth/authorize?client_id=synthetic-public-id'});
  await new Promise(resolve=>setImmediate(resolve));
  check('Authorization response after scope removal cannot redirect or retain an old return target',()=>{
    assert.equal(assignments.length,0);assert.equal(githubReturn(identity),null);
  });

  ({view,state}=await fixture());button(view.tree,'Authorize another installation').props.onClick();await settle(view);
  check('Explicit authorization preserves only navigation target before a valid GitHub redirect',()=>{
    assert.equal(assignments.length,1);assert.match(assignments[0],/^https:\/\/github\.com\/login\/oauth\/authorize/);
    assert.deepEqual(githubReturn(identity).target,target);assert.equal(bindings().length,0);
  });view.unmount();
  ({view,state}=await fixture({state:{authorization:{url:'https://not-github.example/login/oauth/authorize'}}}));
  button(view.tree,'Authorize another installation').props.onClick();await settle(view);
  check('Unexpected authorization origin cannot redirect or store a resumable return target',()=>{
    assert.equal(assignments.length,0);assert.equal(githubReturn(identity),null);assert.match(text(view.tree),/unexpected authorization address/);
  });view.unmount();

  storage.clear();const realNow=Date.now,now=1700000000000;Date.now=()=>now;
  check('Optional return state matches only its original actor and workspace',()=>{
    assert.equal(rememberGitHubReturn(identity,target),true);assert.deepEqual(githubReturn(identity).target,target);
    assert.equal(githubReturn({...identity,actor:'other-actor'}),null);assert.equal(githubReturn({...identity,workspace:'other-workspace'}),null);
  });const returnKey=[...storage.keys()][0];
  for(const expiry of [now-1,now+15*60*1000+1,undefined,'invalid']){
    storage.set(returnKey,JSON.stringify({identity,target,expires:expiry}));
    check('Return target refuses '+(expiry===undefined?'missing':expiry==='invalid'?'nonnumeric':expiry<now?'expired':'excessive future')+' expiry',()=>assert.equal(githubReturn(identity),null));
  }
  storage.set(returnKey,'malformed');check('Malformed return JSON fails closed',()=>assert.equal(githubReturn(identity),null));
  rememberGitHubReturn(identity,target);clearGitHubReturn();check('Explicit return clearing removes optional context',()=>assert.equal(githubReturn(identity),null));
  const originalStorage=window.sessionStorage;window.sessionStorage={getItem(){throw new Error('Storage denied');},setItem(){throw new Error('Storage denied');},removeItem(){throw new Error('Storage denied');}};
  check('Unavailable browser storage cannot break optional navigation or fabricate a return target',()=>{
    assert.equal(rememberGitHubReturn(identity,target),false);assert.equal(githubReturn(identity),null);assert.doesNotThrow(()=>clearGitHubReturn());
  });window.sessionStorage=originalStorage;Date.now=realNow;
  console.log(`${passed} contextual GitHub connection checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const view of [...views])view.unmount();Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;
});
