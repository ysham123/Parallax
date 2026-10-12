#!/usr/bin/env node
// Run actual workflow setup handlers with deferred in-memory responses.
// No network, real tasks, provider calls or persisted test state are used.
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
let responder = async () => {throw new Error('No mock response installed');};
const views = new Set();
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
      old?.cleanup?.(); r.slots[i]={deps,cleanup:effect()};
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
const preflight = () => null;
const api = {
  api(p,init) {calls.push({path:p,init});return responder(p,init);},
  relayApi(p,init) {calls.push({path:p,init});return responder(p,init);},
  viaMachine:()=>paired,
  apiUrl:p=>'/api'+p,
  messageOf:error=>error.message||String(error),
};
Module._load = function(request,parent,...rest) {
  if (request==='react') return react;
  if (request==='react/jsx-runtime') return {jsx,jsxs:jsx,Fragment:Symbol.for('fragment')};
  if (parent?.filename.startsWith(src)) {
    if (request==='./api') return api;
    if (/\.(css|svg|png)$/.test(request)) return {};
    if (request==='./TaskPreflight') return {TaskPreflight:preflight};
    if (request==='./TaskGraph') return {TaskGraph:()=>null};
    if (request==='./Brand') return {ProviderMark:()=>null};
    if (request==='./Onboarding') return {CopyBlock:()=>null};
    if (request==='./RunWorkspace') return {eventSummary:()=>''};
  }
  return savedLoad.call(this,request,parent,...rest);
};
function compile(module,filename) {
  const result=ts.transpileModule(fs.readFileSync(filename,'utf8'),{
    compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true},
  });
  module._compile(result.outputText,filename);
}
require.extensions['.ts']=compile;
require.extensions['.tsx']=compile;
const storage=new Map();
global.crypto=webcrypto;
global.location={pathname:'/',search:'',hash:'',href:'http://localhost/'};
global.history={replaceState(){}};
global.window={history:global.history,setInterval:()=>1,clearInterval(){},addEventListener(){},removeEventListener(){},
  sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)}};
let reloads=0;
global.location.reload=()=>{reloads++;};
global.window.location=global.location;
global.document={hidden:false,body:{},documentElement:{dataset:{}},getElementById:()=>null};
const frames=new Map();let frameSequence=0;
global.requestAnimationFrame=callback=>{const id=++frameSequence;frames.set(id,callback);return id;};
global.cancelAnimationFrame=id=>frames.delete(id);
function flushFrames() {
  const scheduled=[...frames.values()];frames.clear();
  for(const callback of scheduled)callback();
}
function focusTarget(label,visible=()=>true) {
  return {label,isConnected:true,focusCalls:0,inert:false,
    getClientRects(){return visible()?[{}]:[];},
    closest(){return this.inert?{}:null;},
    focus(){this.focusCalls++;document.activeElement=this;}};
}
global.__PARALLAX_VERSION__='test';
function nodes(tree) {
  if (!tree || typeof tree!=='object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree,...nodes(tree.props?.children)];
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join('');
  if (tree && typeof tree==='object') return text(tree.props?.children);
  return tree==null || tree===false?'':String(tree);
}
const button=(tree,label)=>nodes(tree).find(node=>node.type==='button'&&text(node)===label);
const input=(tree,label)=>nodes(tree).find(node=>node.props?.['aria-label']===label);
const taskInput=tree=>nodes(tree).find(node=>node.props?.id==='workflow-prompt');
function field(tree,label) {
  const holder=nodes(tree).find(node=>node.type==='label'&&text(node.props.children?.[0])===label);
  return nodes(holder).find(node=>['input','textarea','select'].includes(node.type));
}
function deferred() {
  let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};
}
function renderer(component,props) {
  const r={component,props,slots:[],effects:[],index:0,render(){
    rendering=this;this.index=0;this.effects=[];this.tree=this.component(this.props);
    for (const effect of this.effects) effect();return this.tree;
  },unmount(){for(const slot of this.slots)slot?.cleanup?.();views.delete(this);}};
  views.add(r);return r;
}
async function settle(view) {
  for(let i=0;i<6;i++){await new Promise(resolve=>setImmediate(resolve));view.render();}
}
function check(label,fn){fn();passed++;console.log('PASS',label);}
const authority=(role='developer',projects=['/project'],actor='developer-a')=>({
  version:'2.0',workspace:'team-a',actor,role,team:true,projects,
  reviewers_by_project:Object.fromEntries(projects.map(project=>[project,['developer-a','reviewer-b']])),
});
const recipe={id:'verified-change',version:2,name:'Verified change',description:'A bounded task',builtin:true,
  instructions:'Current recipe instructions',coordinator:{provider:'codex',role:'coordinator'},
  team:[{provider:'claude',role:'reviewer'}],limits:{minutes:17},
  checks:[{name:'Current regression',argv:['python3','-B','check.py'],cwd:'.',timeout:30}]};
const saved={id:'11111111-1111-4111-8111-111111111111',title:'Saved change',prompt:'Original request',
  workspace:'/project',status:'awaiting_approval',schema_version:'2.0',requester:'developer-a',
  created_at:'2026-10-11T12:00:00Z',updated_at:'2026-10-11T12:00:00Z',
  template:{id:recipe.id,version:1,name:'Historical recipe'},
  template_details:{id:recipe.id,version:1,name:'Historical recipe',description:'Original',instructions:'Original instructions'},
  spec:{workspace:'/project',coordinator:{provider:'codex',role:'coordinator'},team:[{provider:'claude',role:'reviewer'}],
    limits:{minutes:9},checks:[{name:'Historical regression',argv:['python3','old.py'],cwd:'.',timeout:30}]},
  candidate:{digest:'a'.repeat(64),gates:[1,2,3].map(i=>({id:String(i),label:'Gate '+i,status:'passed'}))}};
let Workflows,TaskWorkspace;
async function fixture(options={}) {
  paired=options.paired!==false;calls=[];frames.clear();document.activeElement=document.body;
  const state={context:{authority:authority()},contextReader:null,contextReads:0,rows:[],recipes:[structuredClone(recipe)],
    assessment:{status:'ready',issues:[]},assessmentReader:null,startRequests:[],assessmentRequests:[],failStart:true,
    ...options.state};
  responder=async(p,init)=>{
    if(p==='/context'){state.contextReads++;return state.contextReader?state.contextReader(init):state.context;}
    if(p==='/workflow-templates')return state.recipes;
    if(p==='/workspaces/members'||p==='/github/bindings')return [];
    if(p==='/workflows'&&init?.method!=='POST')return state.rows;
    if(p.startsWith('/workflows/')&&init?.method!=='POST')return state.rows.find(row=>p==='/workflows/'+row.id);
    if(p==='/project/assess'){
      state.assessmentRequests.push(JSON.parse(init.body));
      return state.assessmentReader?state.assessmentReader(init):state.assessment;
    }
    if(p==='/workflows'&&init?.method==='POST'){
      const body=JSON.parse(init.body);state.startRequests.push(body);
      if(state.failStart)throw new Error('Controlled uncertain start response');
      const value={...saved,id:body.request_id,workspace:body.workspace,status:'queued'};state.rows=[value];return value;
    }
    throw new Error('Unexpected mock request '+p);
  };
  const view=renderer(Workflows,{
    active:true,online:true,teamWorkspace:paired,executionWorker:paired?'worker-a':undefined,
    workspace:'/project',knownProjects:['/historical-only'],onInspect(){},onConnections(){},
    renderParticipant:(participant,change,coordinator)=>jsx('participant-editor',{participant,change,coordinator}),
    renderCheck:(value,index,change,remove,valid)=>jsx('check-editor',{value,index,change,remove,valid}),
    renderEvidence:()=>null,...options.props,
  });
  view.props.onWorkspace=workspace=>{view.props={...view.props,workspace};};
  view.render();await settle(view);return {view,state};
}
function compose(view,prompt='Fix one bounded regression') {
  const trigger=nodes(view.tree).find(node=>node.type==='button'&&node.props.className==='new-task-button');
  assert.ok(trigger,'New task control exists');trigger.props.onClick();view.render();
  taskInput(view.tree).props.onChange({target:{value:prompt}});view.render();
}
const assessmentNode=view=>nodes(view.tree).find(node=>node.type===preflight);
const writes=()=>calls.filter(call=>call.init?.method&&call.init.method!=='GET');
function focusContext(view) {
  const main=focusTarget('Task main');
  nodes(view.tree).find(node=>node.props.className==='task-main').props.ref.current=main;
  const opener=focusTarget('Manage provider connections',()=>
    !nodes(view.tree).find(node=>node.props.className==='task-compose-scroll').props.hidden);
  let opened=0;
  view.props={...view.props,onConnections(){opened++;view.props={...view.props,active:false};}};
  view.render();flushFrames();
  return {main,opener,get opened(){return opened;}};
}
async function openProviderSettings(view,focus,label='Manage provider connections') {
  focus.opener.focus();
  const trigger=label==='Provider connections'?input(view.tree,label):button(view.tree,label);
  trigger.props.onClick({currentTarget:focus.opener});view.render();await settle(view);
  // Dialog removal loses focus when the refreshed composer temporarily hides
  // its original opener. DOM visibility/ref stubs model that browser condition.
  document.activeElement=document.body;flushFrames();
}
async function closeProviderSettings(view,state) {
  const refreshed=deferred();state.contextReader=()=>refreshed.promise;
  view.props={...view.props,active:true};view.render();await settle(view);
  return refreshed;
}

(async()=>{
  ({Workflows}=require(path.join(src,'Workflows.tsx')));
  ({TaskWorkspace}=require(path.join(src,'TaskWorkspace.tsx')));

  const pending=deferred();
  let {view,state}=await fixture({state:{contextReader:()=>pending.promise}});
  check('Unresolved paired context cannot infer authority from historical project paths',()=>{
    assert.equal(nodes(view.tree).some(node=>node.props.className==='new-task-button'),false);
    assert.deepEqual(nodes(input(view.tree,'Workflow project')).filter(node=>node.type==='option').map(node=>node.props.value),['']);
    button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();assert.equal(writes().length,0);
  });
  pending.resolve({authority:authority()});await settle(view);view.unmount();

  ({view,state}=await fixture({state:{context:{authority:null}}}));
  check('Missing paired authority produces update/reconnect guidance and no setup writes',()=>{
    assert.match(text(view.tree),/permissions are unavailable|Update or reconnect/);
    assert.equal(button(view.tree,'Start task').props.disabled,true);
    button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();assert.equal(writes().length,0);
  });view.unmount();

  for(const identity of [
    {actor:'other-actor',workspace:'team-a'},
    {actor:'developer-a',workspace:'other-workspace'},
  ]) {
    ({view,state}=await fixture({props:{accountIdentity:identity}}));
    check('Initial worker context must match rendered authenticated '+(identity.actor==='other-actor'?'actor':'workspace'),()=>{
      assert.ok(button(view.tree,'Reload Studio'));assert.equal(button(view.tree,'Start task').props.disabled,true);
      button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();
      assert.equal(writes().length,0);
    });view.unmount();
  }
  ({view,state}=await fixture({props:{accountIdentity:{actor:'developer-a',workspace:'team-a'}}}));
  check('Matching rendered identity permits only its freshly authorized project choices',()=>{
    assert.ok(nodes(view.tree).find(node=>node.props.className==='new-task-button'));
    assert.deepEqual(nodes(input(view.tree,'Workflow project')).filter(node=>node.type==='option').map(node=>node.props.value),['','/project']);
    assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture({props:{workspace:'/historical-only'},state:{rows:[{...saved,workspace:'/historical-only'}]}}));
  check('Paired project selector includes only current server grants, not history or current free text',()=>{
    const picker=input(view.tree,'Workflow project');assert.equal(picker.type,'select');assert.equal(picker.props.value,'');
    assert.deepEqual(nodes(picker).filter(node=>node.type==='option').map(node=>node.props.value),['','/project']);
    button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();assert.equal(writes().length,0);
  });view.unmount();

  ({view,state}=await fixture({state:{context:{authority:authority('reviewer')}}}));
  check('Reviewer has no New task control and the composer remains hidden',()=>{
    assert.equal(nodes(view.tree).some(node=>node.props.className==='new-task-button'),false);
    assert.equal(nodes(view.tree).find(node=>node.props.className==='task-compose-scroll').props.hidden,true);
    button(view.tree,'Start task').props.onClick();button(view.tree,'Check readiness').props.onClick();assert.equal(writes().length,0);
  });view.unmount();

  for(const role of ['owner','developer']) {
    ({view,state}=await fixture({state:{context:{authority:authority(role)}}}));compose(view);
    const start=button(view.tree,'Start task').props.onClick;state.context={authority:authority('reviewer')};
    start();await settle(view);
    check(role+' cannot start after fresh context reports Reviewer, including a directly invoked handler',()=>{
      assert.equal(state.contextReads,2);assert.equal(state.startRequests.length,0);assert.match(text(view.tree),/current permissions/);
    });view.unmount();
  }
  ({view,state}=await fixture());compose(view);
  state.context={authority:authority('developer',['/project'],'different-actor')};
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('Fresh context for another actor cannot consume the old actor\'s Start intent even with equal grants',()=>{
    assert.equal(state.startRequests.length,0);
  });view.unmount();

  for(const replacement of [
    {...authority(),workspace:'another-account-workspace'},
    {...authority(),team:false},
  ]) {
    ({view,state}=await fixture());compose(view);
    state.context={authority:replacement};button(view.tree,'Start task').props.onClick();await settle(view);
    view.props={...view.props,active:false};view.render();await settle(view);
    view.props={...view.props,active:true};view.render();await settle(view);
    check('Changed '+(replacement.team?'account workspace':'team identity')+' cannot become approved by a second context response',()=>{
      assert.equal(state.startRequests.length,0);assert.ok(button(view.tree,'Reload Studio'));
      assert.equal(button(view.tree,'Start task').props.disabled,true);
    });view.unmount();
  }

  ({view,state}=await fixture({state:{contextReader:()=>Promise.reject(new Error('Transient permissions lookup failure'))}}));
  const oldRefresh=button(view.tree,'Refresh project access').props.onClick;
  state.contextReader=null;oldRefresh();await settle(view);compose(view);
  state.context={authority:authority('developer',['/project'],'replacement-actor')};
  button(view.tree,'Start task').props.onClick();await settle(view);
  oldRefresh();await settle(view);oldRefresh();await settle(view);
  check('A previously captured Refresh handler cannot erase the identity-change Reload requirement',()=>{
    assert.equal(state.startRequests.length,0);assert.ok(button(view.tree,'Reload Studio'));
    assert.equal(button(view.tree,'Start task').props.disabled,true);
  });
  const reloadBefore=reloads;button(view.tree,'Reload Studio').props.onClick();
  check('Identity-change recovery requests an actual page reload without issuing a workflow write',()=>{
    assert.equal(reloads,reloadBefore+1);assert.equal(writes().length,0);
  });view.unmount();
  ({view,state}=await fixture());compose(view);
  state.context={authority:authority('developer',['/another-project'])};button(view.tree,'Check readiness').props.onClick();await settle(view);
  check('A revoked project grant blocks the explicit assessment POST after fresh context',()=>{
    assert.equal(state.contextReads,2);assert.equal(state.assessmentRequests.length,0);
    assert.equal(input(view.tree,'Workflow project').props.value,'');
  });view.unmount();

  ({view,state}=await fixture());compose(view,'Keep this draft after a permission outage');
  state.contextReader=()=>Promise.reject(new Error('Project authorization was revoked'));
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('A failed current permission lookup sends no start and preserves the editable draft',()=>{
    assert.equal(state.startRequests.length,0);assert.match(text(view.tree),/Project authorization was revoked/);
    assert.equal(taskInput(view.tree).props.value,'Keep this draft after a permission outage');
  });view.unmount();

  for(const change of ['offline','inactive']) {
    ({view,state}=await fixture());compose(view);const start=button(view.tree,'Start task').props.onClick;
    view.props={...view.props,...(change==='offline'?{online:false}:{active:false})};view.render();await settle(view);
    start();await settle(view);
    check('Captured Start handler cannot dispatch after the current view becomes '+change,()=>assert.equal(state.startRequests.length,0));
    view.unmount();
  }

  ({view,state}=await fixture({state:{context:{authority:authority('developer',['/project','/other'])}}}));compose(view);
  const lateContext=deferred();state.contextReader=init=>init?.signal?state.context:lateContext.promise;
  button(view.tree,'Start task').props.onClick();view.render();
  input(view.tree,'Workflow project').props.onChange({target:{value:'/other'}});view.render();
  lateContext.resolve(state.context);await settle(view);
  check('A deferred permission response cannot start the prior project after the project changed',()=>{
    assert.equal(state.startRequests.length,0);assert.equal(input(view.tree,'Workflow project').props.value,'/other');
  });view.unmount();

  ({view,state}=await fixture());compose(view);const oldWorkerContext=deferred();
  state.contextReader=init=>init?.signal?state.context:oldWorkerContext.promise;
  button(view.tree,'Start task').props.onClick();view.render();
  view.props={...view.props,executionWorker:'worker-b'};view.render();await settle(view);
  oldWorkerContext.resolve(state.context);await settle(view);
  check('A delayed old-worker response cannot dispatch even when both workers expose the same path',()=>assert.equal(state.startRequests.length,0));
  view.unmount();

  ({view,state}=await fixture());compose(view);const lateAssessment=deferred();state.assessmentReader=()=>lateAssessment.promise;
  button(view.tree,'Check readiness').props.onClick();await settle(view);assert.equal(state.assessmentRequests.length,1);
  view.props={...view.props,online:false};view.render();await settle(view);
  state.contextReader=()=>Promise.reject(new Error('Reconnect project permission unavailable'));
  view.props={...view.props,online:true};view.render();await settle(view);
  lateAssessment.resolve({status:'ready',issues:[]});await settle(view);
  check('Offline then same-settings reconnect cannot revive old ready evidence or old authority',()=>{
    assert.equal(assessmentNode(view),undefined);assert.equal(button(view.tree,'Start task').props.disabled,true);
    assert.match(text(view.tree),/Reconnect project permission unavailable/);
  });view.unmount();

  ({view,state}=await fixture());compose(view);const changedChecks=deferred();state.assessmentReader=()=>changedChecks.promise;
  button(view.tree,'Check readiness').props.onClick();await settle(view);
  const editor=nodes(view.tree).find(node=>node.type==='check-editor');editor.props.change({...editor.props.value,argv:['python3','new-check.py']});view.render();
  changedChecks.resolve({status:'ready',issues:[]});await settle(view);
  check('Late readiness is rejected after editing the actual check contract',()=>assert.equal(assessmentNode(view),undefined));view.unmount();

  ({view,state}=await fixture());compose(view);const duplicateAssessment=deferred();state.assessmentReader=()=>duplicateAssessment.promise;
  const checkReadiness=button(view.tree,'Check readiness').props.onClick;
  checkReadiness();checkReadiness();await settle(view);
  check('Two direct readiness invocations produce only one context refresh and one pending assessment',()=>{
    assert.equal(state.contextReads,2);assert.equal(state.assessmentRequests.length,1);
  });
  duplicateAssessment.resolve({status:'ready',issues:[]});await settle(view);
  check('The single current assessment can become visible without starting work',()=>{
    assert.equal(assessmentNode(view).props.assessment.status,'ready');assert.equal(state.startRequests.length,0);
  });view.unmount();

  ({view,state}=await fixture());compose(view,'Preserve the user outcome');
  field(view.tree,'Task instructions').props.onChange({target:{value:'Preserve custom instructions'}});view.render();
  field(view.tree,'Execution time limit, minutes').props.onChange({target:{value:'23'}});view.render();
  nodes(view.tree).find(node=>node.type==='check-editor').props.change({name:'Custom check',argv:['python3','custom.py'],cwd:'.',timeout:47});view.render();
  nodes(view.tree).find(node=>node.type==='participant-editor'&&!node.props.coordinator).props.change({provider:'antigravity',role:'reviewer',model:'explicit-model'});view.render();
  view.props={...view.props,online:false};view.render();await settle(view);view.props={...view.props,online:true};view.render();await settle(view);
  check('Recipe reload on reconnect preserves prompt, instructions, budget, participant and checks',()=>{
    assert.equal(taskInput(view.tree).props.value,'Preserve the user outcome');
    assert.equal(field(view.tree,'Task instructions').props.value,'Preserve custom instructions');
    assert.equal(field(view.tree,'Execution time limit, minutes').props.value,23);
    assert.deepEqual(nodes(view.tree).find(node=>node.type==='check-editor').props.value.argv,['python3','custom.py']);
    assert.equal(nodes(view.tree).find(node=>node.type==='participant-editor'&&!node.props.coordinator).props.participant.model,'explicit-model');
  });
  const reentryReads=state.contextReads;view.props={...view.props,active:false};view.render();await settle(view);
  state.context={authority:authority('developer',['/project','/newly-authorized'])};
  view.props={...view.props,active:true};view.render();await settle(view);
  check('Returning from setup refreshes project access and preserves the draft without automatic assessment',()=>{
    assert.ok(state.contextReads>reentryReads);assert.equal(taskInput(view.tree).props.value,'Preserve the user outcome');
    assert.ok(nodes(input(view.tree,'Workflow project')).some(node=>node.props.value==='/newly-authorized'));
    assert.equal(state.assessmentRequests.length,0);assert.equal(state.startRequests.length,0);
  });view.unmount();

  ({view,state}=await fixture());compose(view,'Keep the chosen recipe version');
  state.recipes=[{...structuredClone(recipe),version:3,name:'New catalog recipe',instructions:'New recipe instructions',limits:{minutes:31}}];
  view.props={...view.props,online:false};view.render();await settle(view);view.props={...view.props,online:true};view.render();await settle(view);
  check('Catalog advancement preserves an explicitly visible draft version and its immutable settings',()=>{
    const picker=input(view.tree,'Task workflow');assert.equal(picker.props.value,recipe.id+':2');
    const draft=nodes(picker).find(node=>node.type==='option'&&node.props.value===recipe.id+':2');
    assert.ok(draft);assert.match(text(draft),/v2/);
    assert.equal(field(view.tree,'Execution time limit, minutes').props.value,17);
    assert.equal(field(view.tree,'Task instructions').props.value,'Current recipe instructions');
  });
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('Preserved draft actually sends its chosen version rather than the newer catalog version',()=>{
    assert.equal(state.startRequests[0].template_version,2);assert.equal(state.startRequests[0].minutes,17);
  });
  input(view.tree,'Task workflow').props.onChange({target:{value:recipe.id+':3'}});view.render();
  check('Choosing the newer version explicitly updates the draft recipe contract',()=>{
    assert.equal(field(view.tree,'Execution time limit, minutes').props.value,31);
    assert.equal(field(view.tree,'Task instructions').props.value,'New recipe instructions');
  });view.unmount();

  ({view,state}=await fixture({state:{rows:[structuredClone(saved)]}}));
  nodes(view.tree).find(node=>node.type===TaskWorkspace).props.onAgain();view.render();
  check('Explicit linked follow-up preserves original recorded contract',()=>{
    assert.match(text(view.tree),/Linked follow-up/);assert.equal(field(view.tree,'Execution time limit, minutes').props.value,9);
    assert.deepEqual(nodes(view.tree).find(node=>node.type==='check-editor').props.value.argv,['python3','old.py']);
  });
  nodes(view.tree).find(node=>node.type==='button'&&node.props.className==='new-task-button').props.onClick();view.render();
  taskInput(view.tree).props.onChange({target:{value:'A new independent task'}});view.render();
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('Generic New task after follow-up drops the parent and uses the current recipe contract',()=>{
    assert.doesNotMatch(text(view.tree),/Linked follow-up/);assert.equal(state.startRequests.length,1);
    assert.equal('parent_workflow_id' in state.startRequests[0],false);assert.equal(state.startRequests[0].template_version,2);
    assert.equal(state.startRequests[0].minutes,17);assert.equal(state.startRequests[0].prompt,'A new independent task');
  });view.unmount();

  const removedRecipeParent={...structuredClone(saved),template:{...saved.template,id:'old-shared-recipe'},
    template_details:{...saved.template_details,id:'old-shared-recipe'}};
  ({view,state}=await fixture({state:{rows:[removedRecipeParent]}}));
  nodes(view.tree).find(node=>node.type===TaskWorkspace).props.onAgain();view.render();
  nodes(view.tree).find(node=>node.type==='button'&&node.props.className==='new-task-button').props.onClick();view.render();
  taskInput(view.tree).props.onChange({target:{value:'Independent after an old recipe'}});view.render();
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('Standalone handoff after a removed parent recipe selects an available current recipe',()=>{
    assert.equal(state.startRequests[0].template_id,recipe.id);assert.equal(state.startRequests[0].template_version,2);
    assert.equal('parent_workflow_id' in state.startRequests[0],false);
  });view.unmount();

  ({view,state}=await fixture());compose(view);button(view.tree,'Start task').props.onClick();await settle(view);
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('Permission refresh preserves unchanged uncertain-start retry identity',()=>{
    assert.equal(state.startRequests.length,2);assert.equal(state.startRequests[0].request_id,state.startRequests[1].request_id);
    assert.equal(state.contextReads,3);assert.equal(state.assessmentRequests.length,0);
  });
  taskInput(view.tree).props.onChange({target:{value:'A changed task contract'}});view.render();button(view.tree,'Start task').props.onClick();await settle(view);
  check('Changed task contract gets a new request identity rather than reusing the uncertain request',()=>assert.notEqual(state.startRequests[1].request_id,state.startRequests[2].request_id));view.unmount();

  ({view,state}=await fixture({paired:false,props:{teamWorkspace:false,executionWorker:undefined,workspace:'/local-project'},state:{context:{authority:null}}}));compose(view);
  check('Local Studio keeps project path entry without a Parallax account',()=>assert.equal(input(view.tree,'Workflow project').type,'input'));
  button(view.tree,'Start task').props.onClick();await settle(view);
  check('A local task can start explicitly without a prior optional assessment',()=>{
    assert.equal(state.startRequests.length,1);assert.equal(state.startRequests[0].workspace,'/local-project');assert.equal(state.assessmentRequests.length,0);
  });view.unmount();

  ({view,state}=await fixture());compose(view,'Keep this provider settings draft');
  let focus=focusContext(view);await openProviderSettings(view,focus);
  let refresh=await closeProviderSettings(view,state);flushFrames();
  check('Provider settings close waits for delayed current permissions before restoring the draft opener',()=>{
    assert.equal(focus.opened,1);assert.equal(document.activeElement,document.body);
    assert.equal(focus.opener.focusCalls,1);assert.equal(focus.main.focusCalls,0);
    assert.equal(state.contextReads,2);assert.equal(writes().length,0);
  });
  refresh.resolve(state.context);await settle(view);flushFrames();
  check('Same permitted draft restores its actual provider settings opener after refresh',()=>{
    assert.equal(document.activeElement,focus.opener);assert.equal(focus.opener.focusCalls,2);
    assert.equal(taskInput(view.tree).props.value,'Keep this provider settings draft');assert.equal(writes().length,0);
  });view.unmount();

  for(const when of ['while permissions are pending','after the restore frame is scheduled']) {
    ({view,state}=await fixture());compose(view);focus=focusContext(view);await openProviderSettings(view,focus);
    refresh=await closeProviderSettings(view,state);const elsewhere=focusTarget('Deliberate navigation elsewhere');
    if(when==='while permissions are pending')elsewhere.focus();
    refresh.resolve(state.context);await settle(view);
    if(when==='after the restore frame is scheduled')elsewhere.focus();
    flushFrames();
    check('Provider settings return does not steal focus moved '+when,()=>{
      assert.equal(document.activeElement,elsewhere);assert.equal(focus.opener.focusCalls,1);
      assert.equal(focus.main.focusCalls,0);assert.equal(writes().length,0);
    });view.unmount();
  }

  for(const change of ['Reviewer role','revoked project','different current project','changed actor','permission lookup failure']) {
    ({view,state}=await fixture({state:{context:{authority:authority('developer',['/project','/other'])}}}));
    compose(view);focus=focusContext(view);await openProviderSettings(view,focus);
    if(change==='different current project')view.props={...view.props,workspace:'/other'};
    refresh=await closeProviderSettings(view,state);
    if(change==='permission lookup failure')refresh.reject(new Error('Current access unavailable'));
    else refresh.resolve({authority:
      change==='Reviewer role'?authority('reviewer',['/project','/other']):
      change==='revoked project'?authority('developer',['/other']):
      change==='changed actor'?authority('developer',['/project','/other'],'another-actor'):
      authority('developer',['/project','/other'])});
    await settle(view);flushFrames();
    check('Provider settings return focuses task main for '+change+' instead of the old draft opener',()=>{
      assert.equal(document.activeElement,focus.main);assert.equal(focus.main.focusCalls,1);
      assert.equal(focus.opener.focusCalls,1);assert.equal(writes().length,0);
      if(change==='changed actor')assert.ok(button(view.tree,'Reload Studio'));
    });view.unmount();
  }

  for(const unavailable of ['detached','hidden or inert']) {
    ({view,state}=await fixture());compose(view);focus=focusContext(view);await openProviderSettings(view,focus);
    refresh=await closeProviderSettings(view,state);
    if(unavailable==='detached')focus.opener.isConnected=false;else focus.opener.inert=true;
    refresh.resolve(state.context);await settle(view);flushFrames();
    check('Provider settings return uses task main when its opener is '+unavailable,()=>{
      assert.equal(document.activeElement,focus.main);assert.equal(focus.opener.focusCalls,1);
      assert.equal(writes().length,0);
    });view.unmount();
  }

  ({view,state}=await fixture({state:{context:{authority:authority('reviewer')}}}));focus=focusContext(view);
  focus.opener=focusTarget('Provider connections utility');
  await openProviderSettings(view,focus,'Provider connections');refresh=await closeProviderSettings(view,state);
  refresh.resolve(state.context);await settle(view);flushFrames();
  check('Reviewer can return to the visible connections utility without acquiring task delivery permission',()=>{
    assert.equal(document.activeElement,focus.opener);assert.equal(focus.main.focusCalls,0);
    assert.equal(nodes(view.tree).find(node=>node.props.className==='task-compose-scroll').props.hidden,true);
    assert.equal(writes().length,0);
  });view.unmount();

  for(const interrupted of ['leaving Tasks','unmount']) {
    ({view,state}=await fixture());compose(view);focus=focusContext(view);await openProviderSettings(view,focus);
    refresh=await closeProviderSettings(view,state);refresh.resolve(state.context);await settle(view);
    assert.ok(frames.size,'A focus return frame is scheduled');
    if(interrupted==='unmount')view.unmount();
    else {view.props={...view.props,active:false};view.render();await settle(view);}
    flushFrames();
    check('Scheduled provider focus return is cancelled after '+interrupted,()=>{
      assert.equal(document.activeElement,document.body);assert.equal(focus.opener.focusCalls,1);
      assert.equal(focus.main.focusCalls,0);assert.equal(writes().length,0);
    });if(interrupted!=='unmount')view.unmount();
  }

  console.log(`${passed} workflow setup checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  for(const view of [...views])view.unmount();
  Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;
});
