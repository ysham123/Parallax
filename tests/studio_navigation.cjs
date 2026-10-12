#!/usr/bin/env node
// Exercise actual component handlers with controlled promises and a tiny hook renderer.
// No browser, network, test accounts, or publication side effects are used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const { webcrypto } = require('node:crypto');
const root = path.resolve(__dirname, '..');
const src = path.join(root, 'studio/src');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const savedLoad = Module._load;
const savedTs = require.extensions['.ts'];
const savedTsx = require.extensions['.tsx'];
let rendering;
let calls = [];
let responder = () => Promise.resolve(null);
let paired = true;
let passed = 0;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const react = {
  useState(initial) {
    const r = rendering, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = typeof initial === 'function' ? initial() : initial;
    return [r.slots[i], value => { r.slots[i] = typeof value === 'function' ? value(r.slots[i]) : value; }];
  },
  useRef(initial) {
    const r = rendering, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = { current: initial };
    return r.slots[i];
  },
  useEffect(effect, deps) {
    const r = rendering, i = r.index++;
    const prior = r.slots[i];
    if (!prior || !same(prior.deps, deps)) {
      r.effects.push(() => { prior?.cleanup?.(); r.slots[i] = { deps, cleanup: effect() }; });
    }
  },
  useMemo(fn, deps) {
    const r = rendering, i = r.index++, prior = r.slots[i];
    if (!prior || !same(prior.deps, deps)) r.slots[i] = { deps, value: fn() };
    return r.slots[i].value;
  },
  useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
};
const jsx = (type, props, key) => ({ type, props: props || {}, key });
const api = {
  api(p, init) { calls.push({ path: p, init }); return responder(p, init); },
  relayApi(p, init) { calls.push({ path: p, init }); return responder(p, init); },
  viaMachine: () => paired,
  messageOf: e => e.message || String(e),
  apiUrl: p => '/api' + p,
  setApiExecutor() {}, onUnauthorized() {},
};
Module._load = function(request, parent, ...rest) {
  if (request === 'react') return react;
  if (request === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: Symbol.for('fragment') };
  if (parent?.filename === path.join(src, 'CloudApp.tsx')) {
    if (request === './App') return function AppPreview() {};
    if (request === './PublicChrome') return { Mark() {}, AccountMenu() {}, DeleteAccountDialog() {}, applyStoredTheme() {} };
    if (['./ExecutionMachines', './OperatorGate', './PublicEntry', './Auth', './Legal', './OAuthConsent', './WorkspaceControls'].includes(request)) return {};
  }
  if (parent?.filename.startsWith(src)) {
    if (request === './api') return api;
    if (/\.(css|svg|png)$/.test(request)) return {};
    if (request === './TaskGraph') return {TaskGraph:()=>null};
    if (['./RunWorkspace', './Brand', './TaskPreflight', './Onboarding'].includes(request)) {
      return { eventSummary: () => '', ProviderMark: () => null, TaskPreflight: () => null, CopyBlock: () => null };
    }
  }
  return savedLoad.call(this, request, parent, ...rest);
};
function compile(module, filename) {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8').replaceAll('import.meta.env.MODE', '"development"'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText;
  module._compile(output, filename);
}
require.extensions['.ts'] = compile;
require.extensions['.tsx'] = compile;
const storage = new Map();
global.crypto = webcrypto;
global.location = { pathname: '/', search: '', hash: '', href: 'http://localhost/' };
global.history = { replaceState() {} };
global.window = {
  sessionStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) },
  setInterval: () => 1, clearInterval() {}, addEventListener() {}, removeEventListener() {},
  history: global.history,
};
global.document = { hidden: false, body: {}, documentElement: { dataset: {} }, getElementById: () => null };
global.localStorage = {getItem: () => null, setItem() {}};
global.requestAnimationFrame = () => 1;
global.cancelAnimationFrame = () => {};
global.__PARALLAX_VERSION__ = 'test';
function renderer(component, props) {
  return { component, props, slots: [], effects: [], index: 0, render() {
    rendering = this; this.index = 0; this.effects = []; this.tree = this.component(this.props);
    for (const effect of this.effects) effect();
    return this.tree;
  }, unmount() { for (const s of this.slots) s?.cleanup?.(); } };
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return [];
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return [tree, ...nodes(tree.props?.children)];
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join('');
  if (tree && typeof tree === 'object') return text(tree.props?.children);
  return tree == null || tree === false ? '' : String(tree);
}
function button(tree, label) { return nodes(tree).find(n => n.type === 'button' && text(n) === label); }
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
async function settle(r) { for (let i = 0; i < 4; i++) { await new Promise(resolve => setImmediate(resolve)); r.render(); } }
function check(label, assertion) { assertion(); passed++; console.log('PASS', label); }

global.EventSource = class EventSource {
  constructor() { this.closed = false; }
  close() { this.closed = true; }
};
function field(tree, label) {
  const match = nodes(tree).find(n => n.type === 'label' && text(n.props.children?.[0]) === label);
  return nodes(match).find(n => n.type === 'textarea' || n.type === 'input');
}
const providers = [{ provider: 'codex', role: 'coordinator' }, { provider: 'claude', role: 'reviewer' }];
const recipe = { id: 'verified-change', version: 1, name: 'Verified change', builtin: true,
  description: 'Saved recipe', instructions: 'Saved instructions', checks: [{ name: 'saved', argv: ['python', '-B', 'check.py'], timeout: 30, cwd: '.' }],
  coordinator: providers[0], team: providers.slice(1), limits: { minutes: 7 } };
const base = { id: '11111111-1111-4111-8111-111111111111', title: 'Task A', prompt: 'Fix addition',
  status: 'awaiting_approval', schema_version: '2.0', workspace: '/project', requester: 'requester', reviewer: 'reviewer',
  candidate: { digest: 'a'.repeat(64), gates: [1,2,3].map(i => ({id:String(i),label:'Gate '+i,status:'passed'})) },
  template: { id: recipe.id, name: recipe.name, version: recipe.version }, created_at: '2026-10-10T12:00:00Z', updated_at: '2026-10-10T12:00:00Z' };
const workflowProps = {
  active: true, workspace: '/project', online: true, knownProjects: ['/project'], onWorkspace() {}, onInspect() {}, onConnections() {},
  renderParticipant: () => null, renderEvidence: () => null,
  renderCheck: (check, index, change, remove, valid) => jsx('check-editor', {check,index,change,remove,valid}),
};
const taskProps = {
  visible: true, feedback: 'Please correct the selected finding', sending: false, sent: '', onSend() {}, followups: [], onRelated() {}, onFeedback() {},
  workflow: base, ready: true, busy: '', online: true, onAction() {}, onAgain() {}, onRevise() {}, canDeliver: true,
  members: [], actorDirectory: [{ account: 'requester', name: 'Ada' }, { account: 'reviewer', name: 'Grace' }, { account: 'approver', name: 'Linus' }],
  viewerActor: 'reviewer', onAssign() {}, onRefresh() {}, onComment() {}, onInspect() {}, renderEvidence: () => null,
};

(async () => {
  const state = require(path.join(src, 'workflow-state.ts'));
  const { Repositories, authorizedProjects, repositoryBindings } = require(path.join(src, 'Repositories.tsx'));
  const { Workflows } = require(path.join(src, 'Workflows.tsx'));
  const { TaskWorkspace, collapsiblePatchHeaders } = require(path.join(src, 'TaskWorkspace.tsx'));
  const { parseDiff } = require(path.join(src, 'diff-model.ts'));
  const { WorkspaceControls } = require(path.join(src, 'WorkspaceControls.tsx'));
  check('Approval remains actionable until delivery; published and applied are delivery outcomes', () => {
    assert.equal(state.workflowGroup('approved'), 'delivery');
    assert.equal(state.workflowGroup('needs_attention', 'approve'), 'delivery');
    assert.equal(state.workflowGroup('needs_attention'), 'attention');
    assert.equal(state.workflowGroup('published'), 'finished');
    assert.equal(state.workflowGroup('applied'), 'finished');
    assert.equal(state.workflowStep('approved'), 2);
    assert.equal(state.workflowStep('published'), 3);
    assert.equal(state.workflowStep('applied'), 3);
  });
  check('Inbox respects personal self approval, team peers, assignments and missing authority', () => {
    const own = {...base, requester:'me', reviewer:undefined};
    assert.equal(state.workflowInReviewInbox(own, {actor:'me', role:'developer', team:false}, true, false), true);
    assert.equal(state.workflowInReviewInbox(own, {actor:'me', role:'owner', team:true}, true, true), false);
    assert.equal(state.workflowInReviewInbox({...base,reviewer:'other'}, {actor:'me',role:'reviewer',team:true}, true, true), false);
    assert.equal(state.workflowInReviewInbox({...base,reviewer:'me'}, {actor:'me',role:'reviewer',team:true}, true, true), true);
    assert.equal(state.workflowInReviewInbox(base, null, true, true), false);
    assert.equal(state.workflowInReviewInbox({...base,requester:undefined,reviewer:'me'}, {actor:'me',role:'reviewer',team:true}, true, true), false);
    assert.equal(state.workflowInReviewInbox({...base,schema_version:'1.0'}, null, true, false), true);
  });
  check('Known failed and cancelled executions do not offer unsupported resume', () => {
    assert.equal(state.workflowCanResume('needs_attention','failed'),false);
    assert.equal(state.workflowCanResume('needs_attention','cancelled'),false);
    assert.equal(state.workflowCanResume('interrupted','interrupted'),true);
    assert.equal(state.workflowCanResume('needs_attention','completed'),true);
    assert.equal(state.workflowCanResume('needs_attention','completed',true),false);
    assert.equal(state.workflowCanResume('interrupted'),true);
  });
  check('Only current server project permission, never a history path or another worker binding, supplies repositories', () => {
    assert.deepEqual(authorizedProjects({workspace:'/history',authority:{projects:['/approved','/approved']}},true),['/approved']);
    assert.deepEqual(authorizedProjects({workspace:'/history',authority:null},true),[]);
    assert.deepEqual(authorizedProjects({workspace:'/local',authority:null},false),['/local']);
    assert.deepEqual(repositoryBindings([{id:'wrong',project:'/approved',worker:'other'},{id:'right',project:'/approved',worker:'current'},{id:'history',project:'/history',worker:'current'}],['/approved'],'current').map(b=>b.id),['right']);
  });
  const repoProps = {active:true, worker:'current', paired:true, online:true, workspace:'/history', machineName:'Worker A', canManage:true, onNewTask() {}, onManage() {}};
  let chosen='', managed='';
  responder = async p => p === '/context' ? {workspace:'/history',authority:{actor:'me',role:'owner',team:true,projects:['/approved']}}
    : p === '/github/bindings' ? [{id:'wrong',project:'/approved',worker:'other',full_name:'wrong/repo',base:'main'},{id:'right',project:'/approved',worker:'current',full_name:'right/repo',base:'main'}]
      : Promise.reject(new Error('Unexpected read '+p));
  const repos = renderer(Repositories,{...repoProps,onNewTask:p=>{chosen=p;},onManage:s=>{managed=s;}});
  repos.render();
  check('Repository setup actions wait for current authority, even with an Owner session prop', () => {
    assert.equal(button(repos.tree,'Add repository'),undefined);
    assert.equal(button(repos.tree,'New task'),undefined);
  });
  await settle(repos);
  check('Repository view projects current worker paths and reuses explicit setup entry points', () => {
    assert.match(text(repos.tree),/\/approved|right\/repo/); assert.doesNotMatch(text(repos.tree),/\/history|wrong\/repo/);
    button(repos.tree,'New task').props.onClick(); assert.equal(chosen,'/approved');
    button(repos.tree,'Add repository').props.onClick(); assert.equal(managed,'projects');
    button(repos.tree,'Connect GitHub delivery').props.onClick(); assert.equal(managed,'github');
    assert.equal(calls.some(c=>c.init?.method && c.init.method !== 'GET'),false);
  });
  repos.props.online=false; repos.render(); await settle(repos);
  check('An offline worker exposes neither stale repository paths nor setup/delivery actions', () => {
    assert.match(text(repos.tree),/Worker offline/); assert.doesNotMatch(text(repos.tree),/\/approved|right\/repo/);
    assert.equal(button(repos.tree,'Add repository'),undefined); assert.equal(button(repos.tree,'New task'),undefined);
  }); repos.unmount();
  responder = async p => p === '/context' ? {authority:{actor:'me',role:'developer',team:true,projects:['/approved']}} : [];
  const downgraded = renderer(Repositories,repoProps); downgraded.render(); await settle(downgraded);
  check('Current Developer permission cannot inherit repository administration from an older Owner prop', () => {
    assert.ok(button(downgraded.tree,'New task')); assert.equal(button(downgraded.tree,'Add repository'),undefined);
    assert.equal(button(downgraded.tree,'Connect GitHub delivery'),undefined);
  }); downgraded.unmount();
  responder = async p => p === '/context' ? {authority:{actor:'me',role:'owner',team:true,projects:['/approved']}} : Promise.reject(new Error('Installation was removed'));
  const githubFail = renderer(Repositories,repoProps); githubFail.render(); await settle(githubFail);
  check('Failed GitHub lookup keeps local project access and preserves an inspectable reason', () => {
    assert.ok(button(githubFail.tree,'New task')); assert.match(text(githubFail.tree),/Connection status unavailable/);
    const detail=nodes(githubFail.tree).find(n=>n.type==='details'); assert.match(text(detail),/Installation was removed/);
  }); githubFail.unmount();
  const old=deferred(), newer=deferred(); let contextReads=0;
  responder = p => p === '/context' ? (++contextReads === 1 ? old.promise : newer.promise) : Promise.resolve([]);
  const crossing=renderer(Repositories,{...repoProps,worker:'old'}); crossing.render();
  crossing.props={...repoProps,worker:'new',machineName:'Worker B'}; crossing.render();
  newer.resolve({authority:{actor:'me',role:'owner',team:true,projects:['/new-project']}}); await settle(crossing);
  old.resolve({authority:{actor:'me',role:'owner',team:true,projects:['/old-project']}}); await settle(crossing);
  check('Late repository permission cannot cross the selected worker boundary', () => {
    assert.match(text(crossing.tree),/\/new-project/); assert.doesNotMatch(text(crossing.tree),/\/old-project/);
  }); crossing.unmount();
  responder=async()=>({workspace:'/local',authority:null});
  const local=renderer(Repositories,{...repoProps,paired:false,worker:undefined,onManage:undefined}); local.render(); await settle(local);
  check('Plain local Studio uses its actual folder and explains launcher selection without a fake picker', () => {
    assert.match(text(local.tree),/\/local|Parallax launcher/); assert.ok(button(local.tree,'New task'));
    assert.equal(button(local.tree,'Add repository'),undefined);
  }); local.unmount();
  responder=async()=>({workspace:'/leaked',authority:null});
  const noAuthority=renderer(Repositories,repoProps); noAuthority.render(); await settle(noAuthority);
  check('Missing paired authority fails closed rather than falling back to the context folder', () => {
    assert.match(text(noAuthority.tree),/permissions are unavailable/); assert.doesNotMatch(text(noAuthority.tree),/\/leaked/);
    assert.equal(button(noAuthority.tree,'New task'),undefined); assert.equal(button(noAuthority.tree,'Add repository'),undefined);
  }); noAuthority.unmount();
  let openerFocus=0, headingFocus=0;
  global.HTMLElement=class {isConnected=true;focus(){openerFocus++;}};
  document.activeElement=new HTMLElement(); document.addEventListener=()=>{}; document.removeEventListener=()=>{};
  responder=async p=>p==='/github/config'?{configured:false}:[];
  const admin=renderer(WorkspaceControls,{session:{account:{id:'me'},workspace:{id:'space',name:'Team',kind:'team',role:'owner'}},machines:[],onSwitch(){}});
  admin.render(); await settle(admin);
  nodes(admin.tree).find(n=>n.type==='details').props.ref.current={querySelector:()=>({focus(){headingFocus++;},scrollIntoView(){}})};
  admin.props.openRequest={sequence:1,section:'projects'}; admin.render(); await settle(admin);
  check('External repository setup focuses its section and closes back to the connected initiating button',()=>{
    assert.equal(admin.tree.props.open,true); assert.ok(headingFocus>0);
    button(admin.tree,'Close workspace settings').props.onClick(); admin.render();
    assert.equal(admin.tree.props.open,false); assert.equal(openerFocus,1);
  }); admin.unmount();
  let authority={actor:'me',role:'developer',team:true,projects:['/project']};
  let rows=[base,{...base,id:'approved',title:'Delivery pending',status:'approved',decision:{action:'approve'}},{...base,id:'retry',title:'Retry delivery',status:'needs_attention',decision:{action:'approve'}},{...base,id:'published',title:'Published task',status:'published'},{...base,id:'applied',title:'Applied task',status:'applied'}];
  responder=async p => p==='/context'?{authority}:p==='/workflow-templates'?[recipe]:p==='/workflows'?rows:p.startsWith('/workflows/')?rows.find(r=>p.endsWith(r.id)):[];
  const queue=renderer(Workflows,workflowProps); queue.render(); await settle(queue);
  button(queue.tree,'Ready for delivery2').props.onClick(); queue.render();
  check('Ready for delivery contains approved/retry candidates and excludes already delivered tasks', () => {
    const list=nodes(queue.tree).find(n=>n.props.className==='task-list');
    assert.match(text(list),/Delivery pending|Retry delivery/); assert.doesNotMatch(text(list),/Published task|Applied task|Task A/);
  }); queue.unmount();
  authority={...authority,projects:['/project','/new-authorized-folder']};
  const composing=renderer(Workflows,workflowProps); composing.render(); await settle(composing);
  nodes(composing.tree).find(n=>n.type==='select' && n.props['aria-label']==='Filter by project').props.onChange({target:{value:'/project'}}); composing.render();
  composing.props={...workflowProps,workspace:'/new-authorized-folder',newTaskRequest:{sequence:1,workspace:'/new-authorized-folder'}};
  composing.render(); await settle(composing);
  check('Repository composer request overrides a historical queue filter without inheriting a saved-candidate parent', () => {
    const field=nodes(composing.tree).find(n=>n.type==='select' && n.props['aria-label']==='Workflow project');
    assert.equal(field.props.value,'/new-authorized-folder'); assert.equal(field.props.disabled,false);
    const composer=nodes(composing.tree).find(n=>n.props.className==='task-compose-scroll'); assert.equal(composer.props.hidden,false);
  });
  let returnFocus=0, nextFrame;
  const priorFrame=requestAnimationFrame, priorGet=document.getElementById;
  global.requestAnimationFrame=callback=>{nextFrame=callback;return 1;};
  document.getElementById=id=>id==='selected-task-title'?{focus(){returnFocus++;}}:null;
  nodes(composing.tree).find(n=>n.type==='button' && text(n).trim()==='Back to task').props.onClick(); composing.render(); nextFrame();
  check('Closing composition restores the selected result and focuses its task title after render',()=>{
    assert.equal(nodes(composing.tree).find(n=>n.props.className==='task-compose-scroll').props.hidden,true);
    assert.ok(nodes(composing.tree).some(n=>n.type===TaskWorkspace)); assert.equal(returnFocus,1);
  });
  global.requestAnimationFrame=priorFrame;document.getElementById=priorGet;
  composing.unmount();
  authority={actor:'me',role:'reviewer',team:true,projects:['/project']};
  rows=[{...base,requester:'me',reviewer:undefined}];
  const ownInbox=renderer(Workflows,{...workflowProps,teamWorkspace:true,view:'inbox'}); ownInbox.render(); await settle(ownInbox);
  check('Team inbox does not auto-open the requester own candidate or expose delivery queue', () => {
    assert.equal(nodes(ownInbox.tree).some(n=>n.type===TaskWorkspace),false);
    assert.match(text(ownInbox.tree),/No tasks awaiting your review/); assert.doesNotMatch(text(ownInbox.tree),/Ready for delivery/);
    assert.ok(nodes(ownInbox.tree).find(n=>n.props.className==='task-compose-scroll').props.hidden);
  }); ownInbox.unmount();
  const completed={run_id:'run',status:'completed',tasks:[],errors:[],reviews:[],checks:[],changed_files:[],spec:{},diff:'',sessions:[],usage:{},artifacts:{}};
  responder=async()=>completed;
  const task=renderer(TaskWorkspace,{...taskProps,workflow:{...base,run_id:'run'}}); task.render(); await settle(task);
  check('Next action precedes candidate summary and activity while approval retains its completed-run gate', () => {
    const order=nodes(task.tree);
    assert.ok(order.findIndex(n=>n.props.className==='task-decision') < order.findIndex(n=>n.props.className==='candidate-summary'));
    assert.ok(order.findIndex(n=>n.props.className==='candidate-summary') < order.findIndex(n=>String(n.props.className||'').startsWith('task-panels')));
    const approve=nodes(task.tree).find(n=>n.type==='button' && /Approve candidate/.test(text(n))); assert.equal(approve.props.disabled,false);
    assert.equal(nodes(task.tree).some(n=>n.props.className==='task-conversation'),false);
    assert.ok(nodes(task.tree).some(n=>n.props['aria-label']==='Show task activity'));
    task.props.workflow={...base,run_id:'run',status:'needs_attention',run_status:'failed'}; completed.status='failed'; task.props.ready=false; task.render();
    assert.equal(button(task.tree,'Resume task'),undefined); assert.match(text(task.tree),/cannot resume/);
    assert.ok(button(task.tree,'New task from current project'));
  }); task.unmount();
  const plainPatch=['diff --git a/m.py b/m.py','index aaaaaaa..bbbbbbb 100644','--- a/m.py','+++ b/m.py','@@ -1 +1 @@','-old','+new'].join('\n');
  check('Only an ordinary complete textual Git preamble can collapse; binary and metadata-only data stay visible',()=>{
    assert.deepEqual(collapsiblePatchHeaders(parseDiff(plainPatch)[0]),[0,1,2,3]);
    assert.deepEqual(collapsiblePatchHeaders(parseDiff('diff --git a/icon.png b/icon.png\nindex aaa..bbb 100644\nBinary files a/icon.png and b/icon.png differ')[0]),[]);
    assert.deepEqual(collapsiblePatchHeaders(parseDiff('diff --git a/icon.png b/icon.png\nGIT binary patch\nliteral 4\nLc$@<O00001')[0]),[]);
    assert.deepEqual(collapsiblePatchHeaders(parseDiff('diff --git a/tool b/tool\nold mode 100644\nnew mode 100755')[0]),[]);
    assert.deepEqual(collapsiblePatchHeaders(parseDiff('diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-old\n+new')[0]),[]);
  });
  check('Malformed, incomplete and unknown patch data never lose their metadata',()=>{
    for(const patch of [plainPatch.replace('@@ -1 +1 @@','@@ malformed @@'),plainPatch.replace('@@ -1 +1 @@','@@ -1,2 +1 @@'),plainPatch+'\nUnexpected recorded metadata',plainPatch.replace('+++ b/m.py','+++ b/m.py\n+++ b/other.py'),plainPatch.replace('--- a/m.py','--- ')]) assert.deepEqual(collapsiblePatchHeaders(parseDiff(patch)[0]),[]);
  });
  const patchRun={...completed,run_id:'patch-run',status:'completed',diff:plainPatch,changed_files:['m.py'],reviews:[{provider:'claude',findings:[{title:'Inspect replacement',file:'m.py',line:1,body:'Recorded finding'}]}]};
  responder=async()=>patchRun;
  const patchView=renderer(TaskWorkspace,{...taskProps,workflow:{...base,run_id:'patch-run',candidate:{...base.candidate,changed_files:['m.py']}}}); patchView.render(); await settle(patchView);
  check('Text patch opens on its hunk, retains original row identities and names a single changed file correctly',()=>{
    assert.equal(nodes(patchView.tree).filter(n=>n.type==='tr' && n.props.className==='patch-meta').length,0);
    const addition=nodes(patchView.tree).find(n=>n.type==='tr' && n.props.className==='patch-addition'); assert.equal(addition.props['data-patch-row'],6);
    const summary=nodes(patchView.tree).find(n=>n.props.className==='candidate-summary'); assert.match(text(summary),/Changes1 fileCurrent/); assert.doesNotMatch(text(summary),/1 files/);
    assert.equal(button(patchView.tree,'Show patch headers').props['aria-expanded'],false);
    assert.ok(nodes(patchView.tree).some(n=>n.props.className==='diff-workspace single-file'));
  });
  button(patchView.tree,'Show patch headers').props.onClick(); patchView.render();
  check('Showing headers restores exact recorded metadata without changing the saved patch download or content row',()=>{
    const rows=nodes(patchView.tree).filter(n=>n.type==='tr'); assert.deepEqual(rows.map(n=>n.props['data-patch-row']),[0,1,2,3,4,5,6]);
    assert.deepEqual(rows.map(n=>text(n.props.children[2])),plainPatch.split('\n'));
    assert.equal(button(patchView.tree,'Hide patch headers').props['aria-expanded'],true);
    assert.ok(nodes(patchView.tree).some(n=>n.props['aria-label']==='Download exact patch' && n.props.href==='/api/runs/patch-run/patch'));
  });
  button(patchView.tree,'Hide patch headers').props.onClick(); patchView.render();
  nodes(patchView.tree).find(n=>n.type==='button' && /Reviews/.test(text(n))).props.onClick(); patchView.render();
  nodes(patchView.tree).find(n=>n.type==='button' && /m\.py:1/.test(text(n))).props.onClick(); await settle(patchView);
  check('Finding navigation targets the original candidate row with headers collapsed',()=>{
    const target=nodes(patchView.tree).find(n=>n.type==='tr' && n.props.className.includes('finding-target'));
    assert.equal(target.props['data-patch-row'],6); assert.equal(target.props.tabIndex,-1); assert.ok(text(target).endsWith('+new'));
    assert.equal(button(patchView.tree,'Show patch headers').props['aria-expanded'],false);
  });
  patchRun.diff='diff --git a/icon.png b/icon.png\nindex aaaaaaa..bbbbbbb 100644\nBinary files a/icon.png and b/icon.png differ'; patchView.render();
  check('Actual binary patch view shows every metadata row and offers no misleading text-header toggle',()=>{
    assert.equal(button(patchView.tree,'Show patch headers'),undefined);
    assert.equal(nodes(patchView.tree).filter(n=>n.type==='tr').length,3);
    assert.match(text(patchView.tree),/Binary files a\/icon.png and b\/icon.png differ/);
  }); patchView.unmount();
  console.log(`${passed} Studio navigation, repository and decision behavior checks passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  Module._load=savedLoad;
  if(savedTs)require.extensions['.ts']=savedTs;else delete require.extensions['.ts'];
  if(savedTsx)require.extensions['.tsx']=savedTsx;else delete require.extensions['.tsx'];
});
