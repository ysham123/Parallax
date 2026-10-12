#!/usr/bin/env node
// Actual Workflows handlers, deferred reads and browser-like focus scheduling.
// This harness makes no network requests, starts no tasks and persists no data.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const {webcrypto} = require('node:crypto');
const root = path.resolve(__dirname, '..');
const src = path.join(root, 'studio/src');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const savedLoad = Module._load;
const savedTs = require.extensions['.ts'];
const savedTsx = require.extensions['.tsx'];
let rendering, calls = [], paired = true, passed = 0;
let responder = async () => {throw new Error('No response installed');};
const views = new Set(), listeners = new Map(), timers = new Map(), frames = new Map();
let timerSequence = 0, frameSequence = 0;
const same = (a,b) => a && b && a.length === b.length && a.every((v,i) => Object.is(v,b[i]));
const react = {
  useState(initial) {
    const r=rendering, i=r.index++;
    if (!(i in r.slots)) r.slots[i]=typeof initial==='function'?initial():initial;
    return [r.slots[i],value=>{r.slots[i]=typeof value==='function'?value(r.slots[i]):value;}];
  },
  useRef(initial) {
    const r=rendering, i=r.index++;
    if (!(i in r.slots)) r.slots[i]={current:initial};
    return r.slots[i];
  },
  useEffect(effect,deps) {
    const r=rendering, i=r.index++, old=r.slots[i];
    if (!old || !same(old.deps,deps)) r.effects.push(()=>{
      old?.cleanup?.();r.slots[i]={deps,cleanup:effect()};
    });
  },
  useMemo(fn,deps) {
    const r=rendering, i=r.index++, old=r.slots[i];
    if (!old || !same(old.deps,deps)) r.slots[i]={deps,value:fn()};
    return r.slots[i].value;
  },
  useCallback(fn,deps) {return react.useMemo(()=>fn,deps);},
};
const jsx = (type,props,key) => ({type,props:props||{},key});
const api = {
  api(p,init) {calls.push({path:p,init});return responder(p,init);},
  relayApi(p,init) {calls.push({path:p,init});return responder(p,init);},
  viaMachine:()=>paired, apiUrl:p=>'/api'+p, messageOf:error=>error.message||String(error),
};
Module._load = function(request,parent,...rest) {
  if(request==='react')return react;
  if(request==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:Symbol.for('fragment')};
  if(parent?.filename.startsWith(src)) {
    if(request==='./api')return api;
    if(/\.(css|svg|png)$/.test(request))return {};
    if(request==='./TaskPreflight')return {TaskPreflight:()=>null};
    if(request==='./TaskGraph')return {TaskGraph:()=>null};
    if(request==='./Brand')return {ProviderMark:()=>null};
    if(request==='./Onboarding')return {CopyBlock:()=>null};
    if(request==='./RunWorkspace')return {eventSummary:()=>''};
  }
  return savedLoad.call(this,request,parent,...rest);
};
function compile(module,filename) {
  const result=ts.transpileModule(fs.readFileSync(filename,'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true},
  });module._compile(result.outputText,filename);
}
require.extensions['.ts']=compile;require.extensions['.tsx']=compile;
global.crypto=webcrypto;
class FocusElement {
  constructor(label,visible=()=>true,inside='studio',focusable=true) {
    this.label=label;this.visible=visible;this.inside=inside;this.focusable=focusable;
    this.isConnected=true;this.inert=false;this.focusCalls=0;
  }
  getClientRects(){return this.visible()?[{}]:[];}
  closest(selector) {
    if(selector==='[hidden], [inert]')return this.inert||!this.visible()?{}:null;
    if(selector==='.task-studio')return this.inside==='studio'||this.inside==='queue'?{}:null;
    if(selector==='.task-queue')return this.inside==='queue'?{}:null;
    return null;
  }
  focus(){this.focusCalls++;if(this.focusable&&this.isConnected&&this.visible()&&!this.inert)document.activeElement=this;}
}
global.Element=FocusElement;global.HTMLElement=FocusElement;
const body=new FocusElement('Body',()=>true,'outside',false), storage=new Map();
global.document={hidden:false,body,activeElement:body,documentElement:{dataset:{}},getElementById:()=>null};
global.location={pathname:'/studio',search:'',hash:'',href:'http://localhost/studio'};
const historyUpdates=[];
global.history={replaceState(_state,_unused,url){historyUpdates.push(url);location.hash=url.includes('#')?'#'+url.split('#')[1]:'';}};
global.window={history,
  setInterval:fn=>{const id=++timerSequence;timers.set(id,fn);return id;},clearInterval:id=>timers.delete(id),
  addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn);},
  removeEventListener:(name,fn)=>listeners.get(name)?.delete(fn),
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}};
global.requestAnimationFrame=fn=>{const id=++frameSequence;frames.set(id,fn);return id;};
global.cancelAnimationFrame=id=>frames.delete(id);
global.__PARALLAX_VERSION__='test';
function flushFrames(){const work=[...frames.values()];frames.clear();for(const fn of work)fn();}
function nodes(tree) {
  if(!tree||typeof tree!=='object')return [];
  if(Array.isArray(tree))return tree.flatMap(nodes);
  return [tree,...nodes(tree.props?.children)];
}
function text(tree) {
  if(Array.isArray(tree))return tree.map(text).join('');
  if(tree&&typeof tree==='object')return text(tree.props?.children);
  return tree==null||tree===false?'':String(tree);
}
const button=(tree,label)=>nodes(tree).find(node=>node.type==='button'&&text(node).trim()===label);
const input=(tree,label)=>nodes(tree).find(node=>node.props?.['aria-label']===label);
const byClass=(tree,name)=>nodes(tree).find(node=>node.props.className===name);
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};}
function renderer(component,props) {
  const r={component,props,slots:[],effects:[],index:0,commit:null,render(){
    rendering=this;this.index=0;this.effects=[];this.tree=this.component(this.props);
    this.commit?.();for(const effect of this.effects)effect();return this.tree;
  },unmount(){for(const slot of this.slots)slot?.cleanup?.();views.delete(this);}};
  views.add(r);return r;
}
async function settle(view){for(let i=0;i<8;i++){await new Promise(resolve=>setImmediate(resolve));view.render();}}
function check(label,fn){fn();passed++;console.log('PASS',label);}
function key(view,key,mods={},target=document.activeElement) {
  let prevented=false;const event={key,target,...mods,preventDefault(){prevented=true;}};
  for(const listener of listeners.get('keydown')||[])listener(event);
  view.render();return prevented;
}
function tick(){for(const fn of timers.values())fn();}
const authority=(role='developer')=>({version:'2.0',workspace:'team-a',actor:'viewer',role,team:true,
  projects:['/project','/other'],reviewers_by_project:{'/project':['viewer'], '/other':['viewer']}});
const recipe={id:'verified-change',version:2,name:'Verified change',description:'Bounded task',builtin:true,
  instructions:'Current instructions',coordinator:{provider:'codex',role:'coordinator'},team:[{provider:'claude',role:'reviewer'}],
  limits:{minutes:17},checks:[{name:'Regression',argv:['python3','check.py'],cwd:'.',timeout:30}]};
const a={id:'11111111-1111-4111-8111-111111111111',title:'Alpha regression',prompt:'Original task',workspace:'/project',
  status:'awaiting_approval',schema_version:'2.0',requester:'another-human',created_at:'2026-10-11T12:00:00Z',updated_at:'2026-10-11T12:00:00Z',
  template:{id:recipe.id,version:2,name:recipe.name},candidate:{digest:'a'.repeat(64),gates:[{id:'checks',status:'passed'}]},
  spec:{workspace:'/project',coordinator:recipe.coordinator,team:recipe.team,limits:recipe.limits,checks:recipe.checks}};
const b={...a,id:'22222222-2222-4222-8222-222222222222',title:'Beta migration',candidate:{...a.candidate,digest:'b'.repeat(64)}};
let Workflows,TaskWorkspace,ArchivedHistory;
const task=view=>nodes(view.tree).find(node=>node.type===TaskWorkspace);
const queue=view=>byClass(view.tree,'task-queue');
const toggle=view=>input(view.tree,view.props.view==='inbox'?'Review queue':'Task list');
const writes=()=>calls.filter(call=>call.init?.method&&call.init.method!=='GET');
async function fixture(options={}) {
  paired=options.paired!==false;calls=[];frames.clear();historyUpdates.length=0;location.hash=options.hash||'';document.activeElement=body;
  const state={context:{authority:authority()},rows:[a,b],listReader:null,detailReader:null,contextReader:null,...options.state};
  responder=async(p,init)=>{
    if(p==='/context')return state.contextReader?state.contextReader(init):state.context;
    if(p==='/workflow-templates')return [recipe];
    if(p==='/github/bindings'||p==='/workspaces/members')return [];
    if(p==='/workflows')return state.listReader?state.listReader(init):state.rows;
    if(p.startsWith('/workflows/'))return state.detailReader?state.detailReader(p.slice('/workflows/'.length),init):state.rows.find(row=>p==='/workflows/'+row.id);
    throw new Error('Unexpected navigation request '+p);
  };
  const view=renderer(Workflows,{active:true,online:true,view:'tasks',teamWorkspace:paired,executionWorker:'worker-a',
    accountIdentity:{actor:'viewer',workspace:'team-a'},workspace:'/project',knownProjects:['/historical-only'],
    onWorkspace(workspace){view.props={...view.props,workspace};},onInspect(){},onConnections(){},
    renderParticipant:()=>null,renderCheck:()=>null,renderEvidence:()=>null,...options.props});
  const dom={canvasCovered:false};
  dom.toggle=new FocusElement('Task browser toggle');
  dom.search=new FocusElement('Task search',()=>!queue(view)?.props.hidden,'queue');
  dom.dismiss=new FocusElement('Dismiss task browser',()=>!queue(view)?.props.hidden,'queue');
  dom.row=new FocusElement('Task row',()=>!queue(view)?.props.hidden,'queue');
  dom.main=new FocusElement('Task main',()=>!dom.canvasCovered||queue(view)?.props.hidden);
  dom.heading=new FocusElement('Selected task title',()=>!!task(view)&&(!dom.canvasCovered||queue(view)?.props.hidden));
  dom.prompt=new FocusElement('Workflow prompt',()=>!byClass(view.tree,'task-compose-scroll')?.props.hidden&&(!dom.canvasCovered||queue(view)?.props.hidden));
  dom.newTask=new FocusElement('New task toolbar');
  view.commit=()=>{
    toggle(view).props.ref.current=dom.toggle;input(view.tree,'Search tasks').props.ref.current=dom.search;
    byClass(view.tree,'task-main').props.ref.current=dom.main;
    document.getElementById=id=>id==='selected-task-title'?(task(view)?dom.heading:null):id==='workflow-prompt'?dom.prompt:id==='main'?dom.main:null;
    if(document.activeElement!==body&&!document.activeElement.getClientRects().length)document.activeElement=body;
  };
  view.render();await settle(view);return {view,state,dom};
}
function open(view,dom){dom.toggle.focus();toggle(view).props.onClick();view.render();flushFrames();}
function dismiss(view,dom){dom.dismiss.focus();input(view.tree,'Hide task list').props.onClick();view.render();flushFrames();}
function select(view,dom,title){dom.row.focus();nodes(view.tree).find(node=>node.type==='button'&&text(node).includes(title)).props.onClick();view.render();}
function newTask(view,dom){dom.newTask.focus();byClass(view.tree,'new-task-button').props.onClick();view.render();flushFrames();}

(async()=>{
  ({Workflows}=require(path.join(src,'Workflows.tsx')));
  ({TaskWorkspace}=require(path.join(src,'TaskWorkspace.tsx')));
  ({ArchivedHistory}=require(path.join(src,'ArchivedHistory.tsx')));
  let {view,state,dom}=await fixture();const original=task(view);
  check('Candidate opens with a natively hidden browser and one visible New task entry',()=>{
    assert.equal(queue(view).props.hidden,true);assert.equal(toggle(view).props['aria-expanded'],false);
    assert.equal(toggle(view).props['aria-controls'],queue(view).props.id);
    assert.equal(nodes(view.tree).filter(node=>node.props.className==='new-task-button').length,1);
    assert.equal(original.props.workflow.id,a.id);assert.equal(writes().length,0);
  });open(view,dom);
  check('Visible Task list control opens search without replacing or hiding the mounted candidate',()=>{
    assert.equal(queue(view).props.hidden,false);assert.equal(toggle(view).props['aria-expanded'],true);
    assert.equal(document.activeElement,dom.search);assert.equal(task(view).key,original.key);
    assert.equal(task(view).props.visible,true);assert.equal(task(view).props.workflow.candidate.digest,a.candidate.digest);
    assert.equal(writes().length,0);
  });
  input(view.tree,'Search tasks').props.onChange({target:{value:'Beta'}});view.render();
  input(view.tree,'Filter by project').props.onChange({target:{value:'/project'}});view.render();
  button(view.tree,'Awaiting approval2').props.onClick();view.render();dismiss(view,dom);open(view,dom);
  check('Closing and reopening preserves search, project and status filters without changing the selected task',()=>{
    assert.equal(input(view.tree,'Search tasks').props.value,'Beta');assert.equal(input(view.tree,'Filter by project').props.value,'/project');
    assert.equal(button(view.tree,'Awaiting approval2').props['aria-pressed'],true);
    assert.doesNotMatch(text(byClass(view.tree,'task-list')),/Alpha/);assert.match(text(byClass(view.tree,'task-list')),/Beta/);
    assert.equal(task(view).key,original.key);assert.equal(task(view).props.workflow.id,a.id);assert.equal(writes().length,0);
  });dismiss(view,dom);
  check('Explicit browser dismissal restores its visible opener after the list hides',()=>{
    assert.equal(document.activeElement,dom.toggle);assert.equal(queue(view).props.hidden,true);assert.equal(writes().length,0);
  });view.unmount();

  for(const modifier of ['metaKey','ctrlKey']) {
    ({view,state,dom}=await fixture());document.activeElement=body;
    const prevented=key(view,'k',{[modifier]:true},body);flushFrames();
    check(modifier+' search shortcut opens and focuses the task search from BODY',()=>{
      assert.equal(prevented,true);assert.equal(queue(view).props.hidden,false);assert.equal(document.activeElement,dom.search);
    });const escaped=key(view,'Escape',{},dom.search);flushFrames();
    check(modifier+' shortcut Escape falls back to the task-browser toggle instead of BODY',()=>{
      assert.equal(escaped,true);assert.equal(queue(view).props.hidden,true);assert.equal(document.activeElement,dom.toggle);
      assert.equal(writes().length,0);
    });view.unmount();
  }

  for(const unavailable of ['detached','hidden','inert']) {
    ({view,state,dom}=await fixture());const opener=new FocusElement('Prior keyboard opener');opener.focus();
    key(view,'k',{ctrlKey:true},opener);flushFrames();
    if(unavailable==='detached')opener.isConnected=false;
    else if(unavailable==='hidden')opener.visible=()=>false;else opener.inert=true;
    key(view,'Escape',{},dom.search);flushFrames();
    check('Escape uses a visible toggle when the captured opener is '+unavailable,()=>{
      assert.equal(document.activeElement,dom.toggle);assert.equal(opener.focusCalls,1);assert.equal(writes().length,0);
    });view.unmount();
  }

  ({view,state,dom}=await fixture());newTask(view,dom);dom.canvasCovered=true;dom.prompt.focus();
  key(view,'k',{ctrlKey:true},dom.prompt);flushFrames();key(view,'Escape',{},dom.search);flushFrames();
  check('Shortcut cancellation restores a connected composer opener after the covered canvas becomes visible',()=>{
    assert.equal(document.activeElement,dom.prompt);assert.equal(queue(view).props.hidden,true);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());dom.toggle.focus();toggle(view).props.onClick();view.render();
  input(view.tree,'Hide task list').props.onClick();view.render();
  check('Rapid open then close keeps only the latest focus intent',()=>assert.equal(frames.size,1));flushFrames();
  check('Rapid browser cancellation cannot focus its now hidden search',()=>{
    assert.equal(queue(view).props.hidden,true);assert.equal(document.activeElement,dom.toggle);assert.equal(dom.search.focusCalls,0);
  });open(view,dom);input(view.tree,'Hide task list').props.onClick();view.render();
  toggle(view).props.onClick();view.render();flushFrames();
  check('Reopening before a pending close frame keeps search focus in the current open browser',()=>{
    assert.equal(queue(view).props.hidden,false);assert.equal(document.activeElement,dom.search);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());newTask(view,dom);
  const promptNode=nodes(view.tree).find(node=>node.props.id==='workflow-prompt');promptNode.props.onChange({target:{value:'Keep the draft while browsing'}});view.render();
  const draftRecipe=input(view.tree,'Task workflow').props.value;open(view,dom);dismiss(view,dom);
  check('Browser presentation preserves an editable standalone draft and its chosen recipe',()=>{
    assert.equal(nodes(view.tree).find(node=>node.props.id==='workflow-prompt').props.value,'Keep the draft while browsing');
    assert.equal(input(view.tree,'Task workflow').props.value,draftRecipe);assert.equal(byClass(view.tree,'task-compose-scroll').props.hidden,false);
    assert.equal(writes().length,0);
  });button(view.tree,'Back to task').props.onClick();view.render();flushFrames();
  check('Back to task restores the prior selected candidate after browser use',()=>{
    assert.equal(task(view).props.workflow.id,a.id);assert.equal(document.activeElement,dom.heading);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());dom.canvasCovered=true;open(view,dom);select(view,dom,b.title);await settle(view);flushFrames();
  check('Explicit task selection hides browser and focuses the current task title after a covered-canvas render',()=>{
    assert.equal(queue(view).props.hidden,true);assert.equal(task(view).props.workflow.id,b.id);assert.equal(document.activeElement,dom.heading);
    assert.equal(location.hash,'#task='+b.id);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());open(view,dom);newTask(view,dom);
  check('New task from the shared toolbar closes navigation and focuses the visible composer without starting work',()=>{
    assert.equal(queue(view).props.hidden,true);assert.equal(byClass(view.tree,'task-compose-scroll').props.hidden,false);
    assert.equal(document.activeElement,dom.prompt);assert.equal(writes().length,0);
  });view.unmount();

  for(const role of ['reviewer','unknown']) {
    ({view,state,dom}=await fixture({state:{context:{authority:authority(role)}}}));open(view,dom);
    check(role+' task browser exposes inspection without New task or delivery queue',()=>{
      assert.equal(byClass(view.tree,'new-task-button'),undefined);assert.doesNotMatch(text(byClass(view.tree,'queue-views')),/Ready for delivery/);
      assert.equal(byClass(view.tree,'task-compose-scroll').props.hidden,true);
      button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();assert.equal(writes().length,0);
    });view.unmount();
  }

  ({view,state,dom}=await fixture({props:{view:'inbox'},state:{context:{authority:authority('reviewer')}}}));open(view,dom);
  input(view.tree,'Search tasks').props.onChange({target:{value:'migration'}});view.render();dom.search.focus();
  state.rows=[{...a,status:'approved'},b];tick();await settle(view);flushFrames();
  check('Passive inbox reconciliation selects eligible work without dismissing search or seizing focus',()=>{
    assert.equal(task(view).props.workflow.id,b.id);assert.equal(queue(view).props.hidden,false);assert.equal(document.activeElement,dom.search);
    assert.equal(input(view.tree,'Search tasks').props.value,'migration');assert.equal(toggle(view).props['aria-expanded'],true);
    assert.equal(writes().length,0);
  });state.rows=[{...a,status:'approved'},{...b,status:'approved'}];tick();await settle(view);flushFrames();
  check('An emptied review inbox leaves its open queue usable and does not invent an eligible candidate',()=>{
    assert.equal(task(view),undefined);assert.equal(queue(view).props.hidden,false);assert.equal(document.activeElement,dom.search);
    assert.match(text(view.tree),/No tasks awaiting your review/);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());open(view,dom);const delayedA=deferred();state.detailReader=id=>id===a.id?delayedA.promise:b;
  select(view,dom,a.title);await settle(view);select(view,dom,b.title);await settle(view);flushFrames();
  delayedA.resolve({...a,title:'Late obsolete Alpha'});await settle(view);flushFrames();
  check('A late old-task detail cannot replace the newer explicit selection or its destination focus',()=>{
    assert.equal(calls.filter(call=>call.path==='/workflows/'+a.id).length,2);
    assert.equal(task(view).props.workflow.id,b.id);assert.doesNotMatch(text(view.tree),/Late obsolete Alpha/);
    assert.equal(document.activeElement,dom.heading);assert.equal(writes().length,0);
  });view.unmount();

  const relatedId='33333333-3333-4333-8333-333333333333';
  const nextRelatedId='44444444-4444-4444-8444-444444444444';
  ({view,state,dom}=await fixture());open(view,dom);const failedRelated=deferred();
  state.detailReader=id=>id===relatedId?failedRelated.promise:state.rows.find(row=>row.id===id);
  task(view).props.onRelated(relatedId);view.render();await settle(view);
  select(view,dom,b.title);await settle(view);flushFrames();failedRelated.reject(new Error('Obsolete related-task failure'));
  await settle(view);
  check('Late related-task failure cannot annotate the newer explicitly selected candidate',()=>{
    assert.equal(task(view).props.workflow.id,b.id);assert.doesNotMatch(text(view.tree),/Obsolete related-task failure/);
    assert.equal(task(view).props.busy,'');assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());const priorRelated=deferred(), currentRelated=deferred();
  state.detailReader=id=>id===relatedId?priorRelated.promise:id===nextRelatedId?currentRelated.promise:state.rows.find(row=>row.id===id);
  task(view).props.onRelated(relatedId);view.render();task(view).props.onRelated(nextRelatedId);view.render();
  priorRelated.reject(new Error('Earlier related lookup failed'));await settle(view);
  check('An old related lookup cannot clear a newer pending navigation busy state or attach its error',()=>{
    assert.equal(task(view).props.busy,'open');assert.doesNotMatch(text(view.tree),/Earlier related lookup failed/);
    assert.equal(writes().length,0);
  });currentRelated.resolve({...b,id:nextRelatedId,title:'Current related task'});await settle(view);flushFrames();
  check('Only the current related lookup can select its candidate and finish navigation',()=>{
    assert.equal(task(view).props.workflow.id,nextRelatedId);assert.equal(task(view).props.busy,'');
    assert.equal(document.activeElement,dom.heading);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());const currentRelatedFailure=deferred();
  state.detailReader=id=>id===relatedId?currentRelatedFailure.promise:state.rows.find(row=>row.id===id);
  task(view).props.onRelated(relatedId);view.render();currentRelatedFailure.reject(new Error('Current related lookup unavailable'));await settle(view);
  check('Current related lookup failure remains visible and finishes only its own pending navigation',()=>{
    assert.match(text(view.tree),/Current related lookup unavailable/);assert.equal(task(view).props.busy,'');assert.equal(writes().length,0);
  });view.unmount();

  for(const outcome of ['success','failure']) {
    ({view,state,dom}=await fixture());const oldScopeRelated=deferred();
    state.detailReader=id=>id===relatedId?oldScopeRelated.promise:state.rows.find(row=>row.id===id);
    task(view).props.onRelated(relatedId);view.render();view.props={...view.props,executionWorker:'worker-b'};
    view.render();await settle(view);
    if(outcome==='success')oldScopeRelated.resolve({...b,id:relatedId,title:'Old worker related candidate'});
    else oldScopeRelated.reject(new Error('Old worker related lookup failed'));
    await settle(view);flushFrames();
    check('Related-task '+outcome+' from the old worker cannot update current navigation or focus',()=>{
      assert.notEqual(task(view)?.props.workflow.id,relatedId);
      assert.doesNotMatch(text(view.tree),/Old worker related/);assert.equal(dom.heading.focusCalls,0);assert.equal(writes().length,0);
    });view.unmount();
  }

  ({view,state,dom}=await fixture());open(view,dom);const failedOldSelection=deferred();
  state.detailReader=id=>id===a.id?failedOldSelection.promise:state.rows.find(row=>row.id===id);
  select(view,dom,a.title);await settle(view);select(view,dom,b.title);await settle(view);flushFrames();
  failedOldSelection.reject(new Error('Obsolete selected-task refresh failed'));await settle(view);
  check('An older explicit-selection refresh failure cannot overwrite the newer candidate navigation notice',()=>{
    assert.equal(calls.filter(call=>call.path==='/workflows/'+a.id).length,2);
    assert.equal(task(view).props.workflow.id,b.id);assert.doesNotMatch(text(view.tree),/Obsolete selected-task refresh failed/);
    assert.equal(writes().length,0);
  });view.unmount();

  for(const interrupted of ['inactive','worker switch','account switch','unmount']) {
    ({view,state,dom}=await fixture());dom.toggle.focus();toggle(view).props.onClick();view.render();
    if(interrupted==='unmount')view.unmount();else {
      view.props={...view.props,...(interrupted==='inactive'?{active:false}:interrupted==='worker switch'?{executionWorker:'worker-b'}:{accountIdentity:{actor:'other-actor',workspace:'other-space'}})};
      view.render();await settle(view);
    }flushFrames();
    check('Pending task-search focus is cancelled after '+interrupted,()=>{
      assert.notEqual(document.activeElement,dom.search);assert.equal(dom.search.focusCalls,0);assert.equal(writes().length,0);
    });if(interrupted!=='unmount')view.unmount();
  }

  for(const closed of [true,false]) {
    ({view,state,dom}=await fixture());if(!closed)open(view,dom);
    const retained=closed?toggle(view).props.onClick:input(view.tree,'Hide task list').props.onClick;
    view.unmount();document.activeElement=body;retained();flushFrames();
    check('Retained '+(closed?'open':'close')+' browser handler after unmount schedules no focus or API work',()=>{
      assert.equal(frames.size,0);assert.equal(document.activeElement,body);assert.equal(writes().length,0);
    });
  }
  ({view,state,dom}=await fixture());const retainedOpen=toggle(view).props.onClick;
  view.props={...view.props,active:false};view.render();await settle(view);document.activeElement=body;
  retainedOpen();view.render();flushFrames();
  check('A directly invoked captured browser opener cannot open navigation while Tasks is inactive',()=>{
    assert.equal(queue(view).props.hidden,true);assert.equal(document.activeElement,body);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());dom.toggle.focus();toggle(view).props.onClick();view.render();
  const elsewhere=new FocusElement('Deliberate navigation elsewhere');elsewhere.focus();flushFrames();
  check('Scheduled search focus preserves deliberate navigation elsewhere',()=>{
    assert.equal(document.activeElement,elsewhere);assert.equal(dom.search.focusCalls,0);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());const modalTarget=new FocusElement('Provider settings input',()=>true,'outside');modalTarget.focus();
  const prevented=key(view,'k',{metaKey:true},modalTarget);flushFrames();
  check('Search shortcut does not steal keys or focus from settings outside task navigation',()=>{
    assert.equal(prevented,false);assert.equal(queue(view).props.hidden,true);assert.equal(document.activeElement,modalTarget);
  });view.unmount();

  ({view,state,dom}=await fixture());open(view,dom);button(view.tree,'Archived records').props.onClick();view.render();flushFrames();
  check('Archive entry closes browser and focuses its read-only destination without workflow operations',()=>{
    assert.equal(queue(view).props.hidden,true);assert.ok(nodes(view.tree).find(node=>node.type===ArchivedHistory));
    assert.equal(task(view),undefined);assert.equal(document.activeElement,dom.main);assert.equal(writes().length,0);
  });open(view,dom);button(view.tree,'All tasks2').props.onClick();view.render();
  check('Returning from archived records restores the selected live task without changing its identity',()=>{
    assert.equal(nodes(view.tree).find(node=>node.type===ArchivedHistory),undefined);assert.equal(task(view).props.workflow.id,a.id);
    assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture());input(view.tree,'Search tasks').props.onChange({target:{value:'No matching result'}});view.render();
  input(view.tree,'Filter by project').props.onChange({target:{value:'/other'}});view.render();button(view.tree,'Clear filters').props.onClick();view.render();
  check('Clear filters removes browser constraints without selecting another task or broadening setup authority',()=>{
    assert.equal(input(view.tree,'Search tasks').props.value,'');assert.equal(input(view.tree,'Filter by project').props.value,'');
    assert.equal(task(view).props.workflow.id,a.id);assert.equal(input(view.tree,'Workflow project').props.value,'/project');
    assert.equal(writes().length,0);
  });view.props={...view.props,online:false};view.render();await settle(view);
  check('Offline team navigation shows unknown counts and clears the current live candidate',()=>{
    assert.match(text(toggle(view)),/—/);assert.match(text(view.tree),/Task counts unavailable/);
    assert.equal(task(view),undefined);assert.equal(writes().length,0);
  });view.unmount();

  ({view,state,dom}=await fixture({hash:'#task='+b.id}));
  check('A valid initial deep link selects its exact candidate while navigation remains collapsed',()=>{
    assert.equal(task(view).props.workflow.id,b.id);assert.equal(queue(view).props.hidden,true);assert.equal(writes().length,0);
  });view.unmount();

  console.log(`${passed} task browser handler checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const view of [...views])view.unmount();
  Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;
});
