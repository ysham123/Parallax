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
    if (['./RunWorkspace', './Brand', './TaskPreflight', './Onboarding'].includes(request)) {
      return { eventSummary: () => '', ProviderMark: () => null, TaskPreflight: () => null, CopyBlock: () => null };
    }
  }
  return savedLoad.call(this, request, parent, ...rest);
};
function compile(module, filename) {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
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
global.document = { hidden: false, body: {}, getElementById: () => null };
global.requestAnimationFrame = () => 1;
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
  const { Workflows } = require(path.join(src, 'Workflows.tsx'));
  const { TaskWorkspace } = require(path.join(src, 'TaskWorkspace.tsx'));
  let rows = [], assessment = { status: 'ready', issues: [] }, requests = [], timeout = true;
  responder = async (p, init) => {
    if (p === '/context') return { authority: { actor: 'reviewer', role: 'developer', team: false, projects: ['/project'] } };
    if (p === '/workflow-templates') return [structuredClone(recipe)];
    if (p === '/workspaces/members') return taskProps.actorDirectory;
    if (p === '/github/bindings') return [];
    if (p === '/workflows' && !init?.method) return rows;
    if (p === '/project/assess') return assessment;
    if (p === '/workflows' && init?.method === 'POST') {
      const body = JSON.parse(init.body); requests.push(body);
      if (timeout) throw new Error('Timeout');
      rows = [{...base,id:body.request_id,status:'queued'}]; return rows[0];
    }
    if (p.startsWith('/workflows/')) return rows.find(r => p.endsWith(r.id));
    throw new Error('Unexpected request ' + p);
  };
  const compose = renderer(Workflows, workflowProps); compose.render(); await settle(compose);
  button(compose.tree, text(nodes(compose.tree).find(n => n.type === 'button' && n.props.className === 'new-task-button'))).props.onClick();
  compose.render();
  nodes(compose.tree).find(n => n.props.id === 'workflow-prompt').props.onChange({target:{value:'Fix a bounded bug'}}); compose.render();
  field(compose.tree, 'Task instructions').props.onChange({target:{value:'One-off instructions <script>literal</script>'}}); compose.render();
  const editor = nodes(compose.tree).find(n => n.type === 'check-editor');
  editor.props.change({...editor.props.check,name:'one-off',argv:['python','-B','first check.py','a b']}); compose.render();
  check('Unsaved one-off instructions and checks do not require a recipe name', () => {
    assert.equal(field(compose.tree, 'Recipe name').props.value, '');
    assert.equal(button(compose.tree, 'Start task').props.disabled, false);
    assert.doesNotMatch(text(compose.tree), /Save your instructions and checks as a recipe before starting/);
  });
  button(compose.tree, 'Start task').props.onClick(); await settle(compose);
  button(compose.tree, 'Start task').props.onClick(); await settle(compose);
  check('Actual start sends immutable task override payload and reuses its ID after timeout', () => {
    assert.equal(requests.length, 2); assert.equal(requests[0].request_id,requests[1].request_id);
    assert.equal(requests[0].template_id,recipe.id); assert.equal(requests[0].template_version,1);
    assert.equal(requests[0].task_settings.schema_version,'1.0');
    assert.equal(requests[0].task_settings.instructions,'One-off instructions <script>literal</script>');
    assert.deepEqual(requests[0].task_settings.checks[0].argv,['python','-B','first check.py','a b']);
    assert.equal(calls.some(c => c.path.startsWith('/workflow-templates') && c.init?.method),false);
  });
  field(compose.tree, 'Task instructions').props.onChange({target:{value:'A different explicit override'}}); compose.render();
  button(compose.tree, 'Start task').props.onClick(); await settle(compose);
  check('Changing a task override creates a distinct operation rather than mutating the timed-out start', () => assert.notEqual(requests[2].request_id,requests[1].request_id));
  field(compose.tree, 'Task instructions').props.onChange({target:{value:''}}); compose.render();
  nodes(compose.tree).find(n => n.type === 'check-editor').props.remove(); compose.render();
  button(compose.tree, 'Start task').props.onClick(); await settle(compose);
  check('Explicit empty instructions and checks remain in the actual request', () => assert.deepEqual(requests.at(-1).task_settings,{schema_version:'1.0',instructions:'',checks:[]}));
  field(compose.tree, 'Execution time limit, minutes').props.onChange({target:{value:'0'}}); compose.render();
  const priorInvalid = requests.length; button(compose.tree, 'Start task').props.onClick(); await settle(compose);
  check('Actual handler refuses invalid budget even if a disabled button is invoked directly', () => assert.equal(requests.length,priorInvalid));
  field(compose.tree, 'Execution time limit, minutes').props.onChange({target:{value:'7'}}); compose.render();
  assessment = {status:'blocked',issues:[{severity:'error',message:'Independent provider unavailable'}]};
  button(compose.tree,'Check readiness').props.onClick(); await settle(compose);
  const priorBlocked = requests.length; button(compose.tree,'Start task').props.onClick(); await settle(compose);
  check('Known blocked readiness prevents execution in the real handler', () => { assert.equal(requests.length,priorBlocked); assert.equal(button(compose.tree,'Start task').props.disabled,true); });
  const late = deferred(); const originalResponder = responder;
  responder = (p, init) => p === '/project/assess' ? late.promise : originalResponder(p, init);
  button(compose.tree,'Check readiness').props.onClick(); compose.render();
  const empty = nodes(compose.tree).find(n => n.type === 'button' && text(n) === 'Add check'); empty.props.onClick(); compose.render();
  late.resolve({status:'blocked',issues:[{severity:'error',message:'Stale blocker'}]}); await settle(compose);
  check('Late readiness response cannot attach to edited check settings', () => assert.equal(nodes(compose.tree).some(n => n.props.assessment?.issues?.some(i => i.message === 'Stale blocker')),false));
  compose.unmount();
  requests = []; rows = []; timeout = true; responder = originalResponder;
  const unchanged = renderer(Workflows,workflowProps); unchanged.render(); await settle(unchanged);
  nodes(unchanged.tree).find(n => n.type === 'button' && n.props.className === 'new-task-button').props.onClick(); unchanged.render();
  nodes(unchanged.tree).find(n => n.props.id === 'workflow-prompt').props.onChange({target:{value:'An unchanged task'}}); unchanged.render();
  button(unchanged.tree,'Start task').props.onClick(); await settle(unchanged);
  check('Unchanged recipe task omits the new feature field for existing v2 workers', () => assert.equal('task_settings' in requests[0],false));
  unchanged.unmount();

  let reconnects = 0, historyFails = false;
  const teamResponder = async p => {
    if (p === '/context') return {authority:{actor:'reviewer',role:'developer',team:true,projects:['/project']}};
    if (p === '/workflow-templates') return [structuredClone(recipe)];
    if (p === '/workspaces/members') return taskProps.actorDirectory;
    if (p === '/github/bindings') return [];
    if (p === '/workflows') { if (historyFails) throw new Error('Current project permission could not be checked'); return [base]; }
    if (p === '/workflows/'+base.id) return base;
    throw new Error('Unexpected request '+p);
  };
  responder = teamResponder;
  const teamHistory = renderer(Workflows,{...workflowProps,teamWorkspace:true,onReconnect(){reconnects++;}});
  teamHistory.render(); await settle(teamHistory);
  check('Connected team history preserves reviewer handoff and peer approval', () => {
    assert.ok(nodes(teamHistory.tree).some(n => n.type === TaskWorkspace && n.props.ready));
    assert.match(text(teamHistory.tree),/Awaiting your review/);
  });
  teamHistory.props.online = false; teamHistory.render(); await settle(teamHistory);
  check('Offline team history hides prior tasks and reports unknown counts without empty-state success', () => {
    assert.doesNotMatch(text(teamHistory.tree),/Task A|Your tasks will appear here|0 awaiting approval/);
    assert.match(text(teamHistory.tree),/Task counts unavailable/);
    assert.equal(nodes(teamHistory.tree).some(n => n.type === TaskWorkspace),false);
    assert.equal(nodes(teamHistory.tree).filter(n => n.props.className === 'task-availability').length,1);
    assert.equal(nodes(teamHistory.tree).some(n => n.props.role === 'alert'),false);
    button(teamHistory.tree,'Reconnect machine').props.onClick(); assert.equal(reconnects,1);
  });
  const priorOfflineCalls = calls.filter(c=>/^\/(workflows|context|workflow-templates)/.test(c.path)).length;
  const offlineRefresh = nodes(teamHistory.tree).find(n=>n.props['aria-label']==='Refresh task list');
  offlineRefresh.props.onClick(); await settle(teamHistory);
  check('Offline history refresh does not dispatch machine reads', () => assert.equal(calls.filter(c=>/^\/(workflows|context|workflow-templates)/.test(c.path)).length,priorOfflineCalls));
  teamHistory.props.online = true; teamHistory.render(); await settle(teamHistory);
  check('Reconnecting restores authorized history and known counts', () => { assert.match(text(teamHistory.tree),/Task A/); assert.match(text(teamHistory.tree),/1 awaiting approval/); });
  historyFails = true;
  nodes(teamHistory.tree).find(n=>n.props['aria-label']==='Refresh task list').props.onClick(); await settle(teamHistory);
  check('Failed current authorization clears team history instead of retaining an unfiltered cache', () => { assert.doesNotMatch(text(teamHistory.tree),/Task A/); assert.match(text(teamHistory.tree),/Task history unavailable/); assert.match(text(teamHistory.tree),/Task counts unavailable/); });
  const delayedHistory = deferred();
  responder = p => p === '/workflows' ? delayedHistory.promise : teamResponder(p);
  nodes(teamHistory.tree).find(n=>n.props['aria-label']==='Refresh task list').props.onClick(); teamHistory.render();
  responder = teamResponder;
  nodes(teamHistory.tree).find(n=>n.props['aria-label']==='Refresh task list').props.onClick(); await settle(teamHistory);
  delayedHistory.resolve([base]); await settle(teamHistory);
  check('A late older history response cannot restore tasks after a newer authorization failure', () => { assert.doesNotMatch(text(teamHistory.tree),/Task A/); assert.match(text(teamHistory.tree),/Task counts unavailable/); });
  teamHistory.unmount(); historyFails = false;
  const evidenceWarning = renderer(Workflows,{...workflowProps,evidenceTransport:{status:'local_evidence_only',problem_count:1,limit_bytes:8388608}});
  evidenceWarning.render(); await settle(evidenceWarning);
  check('Oversize transport is described as unavailable full evidence with local retention and blocked approval', () => { assert.match(text(evidenceWarning.tree),/Full evidence is retained locally/); assert.match(text(evidenceWarning.tree),/Remote approval is blocked for affected candidates/); });
  evidenceWarning.unmount();

  const { ArchivedHistory } = require(path.join(src,'ArchivedHistory.tsx'));
  const archiveRow = {id:'old-run',kind:'run',worker:'revoked',worker_name:'Old machine',project:'/project',archived_at:1780000000,read_only:true,status:'completed',requester:'requester',checks_passed:2,checks_total:3,reviews_total:1,diff_sha256:'b'.repeat(64)};
  let archiveFails = false;
  responder = async p => { if(archiveFails) throw new Error('Current workspace membership is required'); return p.includes('cursor=0') ? {items:[archiveRow],next_cursor:7,has_more:true} : {items:[{...archiveRow,id:'second'}],next_cursor:null,has_more:false}; };
  const archive = renderer(ArchivedHistory,{}); archive.render(); await settle(archive);
  check('Revoked worker metadata is a read-only archive without consequential controls', () => { assert.match(text(archive.tree),/Old machine/); assert.match(text(archive.tree),/2 passed of 3/); assert.match(text(archive.tree),/cannot be approved/); assert.equal(nodes(archive.tree).some(n=>n.type==='button' && /approve|resume|apply|publish/i.test(text(n))),false); });
  button(archive.tree,'Load more archived records').props.onClick(); await settle(archive);
  check('Archive pagination follows the server cursor only on an explicit action', () => { assert.equal(nodes(archive.tree).filter(n=>n.type==='li').length,2); assert.ok(calls.some(c=>c.path==='/executors/archives?cursor=7&limit=50')); assert.equal(button(archive.tree,'Load more archived records'),undefined); });
  archive.unmount();
  const revokedArchive = renderer(ArchivedHistory,{}); revokedArchive.render(); await settle(revokedArchive);
  archiveFails=true; button(revokedArchive.tree,'Load more archived records').props.onClick(); await settle(revokedArchive);
  check('A lost archive permission removes previously visible receipts and resets retry to the first page', () => { assert.equal(nodes(revokedArchive.tree).filter(n=>n.type==='li').length,0); assert.match(text(revokedArchive.tree),/Archived records are unavailable/); });
  archiveFails=false; button(revokedArchive.tree,'Retry archived records').props.onClick(); await settle(revokedArchive);
  check('Archive retry reloads current permissions without skipping a failed first page', () => assert.equal(calls.at(-1).path,'/executors/archives?cursor=0&limit=50'));
  revokedArchive.unmount();

  const { PublicationPanel } = require(path.join(src,'PublicationPanel.tsx'));
  responder = async p => p.startsWith('/github/publication/') ? null : {url:'https://github.com/example/repository/pull/2',external_change:false,refreshed_at:1780000000,incomplete:true,feedback_errors:{checks:'More checks are available on GitHub.'},checks:[],statuses:[],comments:[],reviews:[]};
  const partial = renderer(PublicationPanel,{workflow:{...base,status:'published',github_target:{id:'binding'},publication:{url:'https://github.com/example/repository/pull/2',pr:2,branch:'parallax/task',commit:'c'.repeat(40),repository:'example/repository'}},canDeliver:true,onChanged(){},onFeedback(){}});
  partial.render(); await settle(partial); button(partial.tree,'Refresh CI and review feedback').props.onClick(); await settle(partial);
  check('Partial GitHub feedback has recorded freshness and a direct full PR link', () => { assert.match(text(partial.tree),/GitHub feedback is incomplete/); assert.match(text(partial.tree),/More checks are available/); assert.ok(nodes(partial.tree).some(n=>n.type==='time' && n.props.dateTime===new Date(1780000000000).toISOString())); assert.ok(nodes(partial.tree).some(n=>n.type==='a' && text(n)==='Open full pull request on GitHub' && n.props.href==='https://github.com/example/repository/pull/2')); });
  partial.unmount();

  let captured, related;
  const identity = renderer(TaskWorkspace,{...taskProps,visible:false,workflow:{...base,status:'approved',
    comments:[{id:'c',actor:'requester',at:'2026-10-10T13:00:00Z',message:'<img src=x onerror=alert(1)>'}],
    decision:{action:'approve',actor:'approver',at:'2026-10-10T14:00:00Z'}},onRelated:id=>{related=id;}});
  identity.render();
  check('Another developer request and comment identify the recorded people', () => {
    assert.doesNotMatch(text(identity.tree),/Your request/); assert.match(text(identity.tree),/Ada/); assert.match(text(identity.tree),/Grace/); assert.match(text(identity.tree),/Linus/);
    assert.ok(nodes(identity.tree).some(n => n.type === 'time' && n.props.dateTime === '2026-10-10T13:00:00Z'));
    assert.ok(nodes(identity.tree).some(n => n.type === 'time' && n.props.dateTime === '2026-10-10T14:00:00Z'));
  });
  check('Untrusted comment and actor names remain text without raw HTML injection', () => {
    assert.match(text(identity.tree),/<img src=x onerror=alert\(1\)>/);
    assert.equal(nodes(identity.tree).some(n => n.props.dangerouslySetInnerHTML),false);
    assert.equal(nodes(identity.tree).some(n => n.type === 'img' && n.props.src === 'x'),false);
  });
  identity.props.workflow = {...base,requester:undefined,reviewer:undefined,decision:{action:'approve'},comments:[{id:'old',message:'Legacy comment'}]}; identity.render();
  check('Legacy records explicitly show missing human attribution and time', () => { assert.match(text(identity.tree),/Unrecorded human/); assert.match(text(identity.tree),/Time unrecorded/); assert.doesNotMatch(text(identity.tree),/Your request/); });
  identity.props.viewerActor = 'requester'; identity.props.workflow = base; identity.render();
  check('Your request requires an exact recorded requester and viewer match', () => assert.match(text(identity.tree),/Your request/));
  const revisionId = '33333333-3333-4333-8333-333333333333', freshId = '44444444-4444-4444-8444-444444444444';
  identity.props.followups = [{...base,id:revisionId,title:'Correction',parent_workflow_id:base.id,revision:{parent:base.id,lineage:base.id}},
    {...base,id:freshId,title:'Fresh outcome',parent_workflow_id:base.id,revision:undefined}]; identity.render();
  check('Related work distinguishes saved-candidate revision from current-project task', () => {
    const children = nodes(identity.tree).filter(n => n.type === 'button');
    const revision = children.find(n => /Candidate revision: Correction/.test(text(n)));
    const fresh = children.find(n => /New task from current project: Fresh outcome/.test(text(n)));
    assert.ok(revision); assert.ok(fresh); revision.props.onClick(); assert.equal(related,revisionId); fresh.props.onClick(); assert.equal(related,freshId);
  });
  identity.unmount();

  const secondFile = ['diff --git a/src/long.py b/src/long.py','--- a/src/long.py','+++ b/src/long.py','@@ -1,500 +1,500 @@',...Array.from({length:500},(_,i)=>' line'+(i+1))].join('\n');
  const run = {id:'run-A',status:'completed',tasks:[],errors:[],reviews:[{provider:'claude',findings:[{title:'Late page finding',body:'Preserve behavior',priority:'P1',code_location:{path:'src/long.py',line_range:{start:470,end:470}}},{title:'Missing file',file:'outside.py',line:2}]}],checks:[],spec:{},
    diff:'diff --git a/first.py b/first.py\n--- a/first.py\n+++ b/first.py\n@@ -1 +1 @@\n-old\n+new\n'+secondFile};
  responder = async p => p === '/runs/run-A' ? run : (()=>{throw new Error('Unexpected request '+p)})();
  const findings = renderer(TaskWorkspace,{...taskProps,workflow:{...base,run_id:'run-A'},onRevise:value=>{captured=value;}}); findings.render(); await settle(findings);
  nodes(findings.tree).find(n => n.type === 'input' && n.props['aria-label'] === 'Filter changed files').props.onChange({target:{value:'first'}}); findings.render();
  const reviewTab = nodes(findings.tree).find(n => n.type === 'button' && /Reviews/.test(text(n))); reviewTab.props.onClick(); findings.render();
  const findingLocation = nodes(findings.tree).find(n => n.type === 'button' && /src\/long.py:470/.test(text(n)));
  assert.ok(findingLocation,'Findings must have an actionable saved location'); findingLocation.props.onClick(); await settle(findings);
  check('Finding location selects the correct diff file and page after effects settle', () => {
    assert.ok(nodes(findings.tree).some(n => n.props['aria-label'] === 'Diff for src/long.py'));
    assert.ok(nodes(findings.tree).some(n => n.type === 'pre' && text(n) === ' line470'));
    assert.ok(nodes(findings.tree).some(n => n.type === 'tr' && n.props.className.includes('finding-target') && text(n).endsWith(' line470')));
    assert.equal(nodes(findings.tree).find(n => n.type === 'input' && n.props['aria-label'] === 'Filter changed files').props.value,'');
    assert.doesNotMatch(text(findings.tree),/Patch rows 1–400/);
  });
  nodes(findings.tree).find(n => n.type === 'button' && /Reviews/.test(text(n))).props.onClick(); findings.render();
  const selectedArticle = nodes(findings.tree).find(n => n.props.className === 'task-review-finding' && text(n).includes('Late page finding'));
  nodes(selectedArticle).find(n => n.type === 'input' && n.props.type === 'checkbox').props.onChange({target:{checked:true}}); findings.render();
  button(findings.tree,'Revise candidate').props.onClick();
  check('Location navigation leaves selected review and finding indexes unchanged', () => assert.deepEqual(captured,[{review:0,finding:0}]));
  const missing = nodes(findings.tree).find(n => n.type === 'button' && /outside.py:2/.test(text(n))); missing.props.onClick(); await settle(findings);
  check('Unknown finding paths show an explicit limitation without fabricated source', () => { assert.match(text(findings.tree),/not in the recorded candidate diff/); assert.equal(nodes(findings.tree).some(n => n.props['aria-label'] === 'Diff for outside.py'),false); });
  findings.unmount();

  const oldRun = deferred(), newRun = deferred();
  responder = p => p === '/runs/old' ? oldRun.promise : p === '/runs/new' ? newRun.promise : Promise.reject(new Error('Unexpected request '+p));
  const stale = renderer(TaskWorkspace,{...taskProps,workflow:{...base,run_id:'old'}}); stale.render();
  stale.props.workflow = {...base,id:'new-workflow',run_id:'new',title:'New selected task'}; stale.render();
  newRun.resolve({...run,id:'new',diff:secondFile}); await settle(stale); oldRun.resolve({...run,id:'old',diff:run.diff}); await settle(stale);
  check('Stale evidence response cannot replace the current task after run selection changes', () => assert.equal(text(stale.tree).includes('first.py'),false));
  stale.unmount();

  const { default: PublicEntry } = require(path.join(src,'PublicEntry.tsx'));
  const { default: HostedApp } = require(path.join(src,'HostedApp.tsx'));
  const { PUBLIC_RELEASE } = require(path.join(src,'public-release.ts'));
  const publicPage = renderer(PublicEntry,{config:null,error:null}); publicPage.render();
  const installNode = nodes(publicPage.tree).find(n => typeof n.type === 'function' && n.type.name === 'Install');
  const install = renderer(installNode.type,installNode.props); install.render();
  location.pathname = '/studio';
  const hostedRoot = renderer(HostedApp,{}); hostedRoot.render();
  const launcher = renderer(hostedRoot.tree.type,hostedRoot.tree.props); launcher.render();
  check('Rendered website and Studio launcher agree on public Claude command and preview boundary', () => {
    const websiteCommands = nodes(install.tree).filter(n => n.type === 'code').map(text);
    const launcherCommands = nodes(launcher.tree).filter(n => n.type === 'code').map(text);
    assert.ok(websiteCommands.includes(PUBLIC_RELEASE.claudeStudio));
    assert.ok(launcherCommands.includes(PUBLIC_RELEASE.claudeStudio));
    const installer = nodes(install.tree).find(n => n.props.label === 'Claude Code install commands');
    assert.ok(installer.props.text.endsWith('/plugin install '+PUBLIC_RELEASE.claudePlugin));
    assert.match(text(install.tree),new RegExp('Pinned public source '+PUBLIC_RELEASE.version.replaceAll('.','\\.')));
    assert.match(text(launcher.tree),/development preview/);
    assert.match(text(launcher.tree),/do not include the saved-candidate workflow/);
  });
  check('Actual source download and terminal checkout resolve to the same immutable public revision', () => {
    const download = nodes(install.tree).find(n => n.type === 'a' && text(n).includes('Download source ZIP'));
    const source = nodes(install.tree).find(n => n.props.label === 'Source install commands');
    const archiveRevision = new URL(download.props.href).pathname.split('/').at(-1).replace(/\.zip$/,'');
    const checkout = source.props.text.match(/^git checkout --detach ([a-f0-9]{40})$/m)?.[1];
    assert.match(archiveRevision,/^[a-f0-9]{40}$/); assert.equal(archiveRevision,checkout);
  });
  let destination = '';
  window.location = {assign:url=>{destination=url;}};
  const localLink = nodes(launcher.tree).find(n => n.props.id === 'studio-link');
  localLink.props.onChange({target:{value:'https://evil.example/?token=private'}}); launcher.render();
  nodes(launcher.tree).find(n => n.type === 'form').props.onSubmit({preventDefault(){}}); launcher.render();
  check('Actual launcher rejects a remote access-link destination', () => { assert.equal(destination,''); assert.match(text(launcher.tree),/local|localhost|127\.0\.0\.1/i); });
  nodes(launcher.tree).find(n => n.props.id === 'studio-link').props.onChange({target:{value:'http://127.0.0.1:8123/?token=private-local-token'}}); launcher.render();
  nodes(launcher.tree).find(n => n.type === 'form').props.onSubmit({preventDefault(){}});
  check('Actual launcher forwards an authorized local link without saving or uploading it', () => { assert.equal(destination,'http://127.0.0.1:8123/?token=private-local-token'); assert.equal(Array.from(storage.values()).includes(destination),false); });
  publicPage.unmount(); launcher.unmount(); hostedRoot.unmount();
  window.location.origin = 'http://127.0.0.1:8123';
  document.addEventListener = () => {};
  document.removeEventListener = () => {};
  const {default: Onboarding} = require(path.join(src,'Onboarding.tsx'));
  const {ExecutionMachines} = require(path.join(src,'ExecutionMachines.tsx'));
  const waitingReviewer = renderer(Onboarding, {workspaceName:'Team',machines:[],loading:false,account:null,onOpen(){},canManageMachines:false});
  waitingReviewer.render();
  check('Team reviewers without a machine get owner handoff instead of unauthorized pairing controls', () => {
    assert.match(text(waitingReviewer.tree),/Ask a workspace owner/);
    assert.equal(nodes(waitingReviewer.tree).some(n => n.type === 'ol'),false);
  });
  const ownerSetup = renderer(Onboarding, {...waitingReviewer.props,canManageMachines:true}); ownerSetup.render();
  check('Authorized owners retain the complete worker setup', () => {
    assert.match(text(ownerSetup.tree),/Connect a machine/);
    assert.equal(nodes(ownerSetup.tree).some(n => n.type === 'ol'),true);
  });
  const reviewerMachines = renderer(ExecutionMachines,{machines:[{id:'one',name:'Team worker',online:false,workspaces:['/project']}],selected:'one',onSelect(){},refresh:async()=>{},hostedExecution:false,canManageMachines:false,reconnectSignal:1});
  reviewerMachines.render(); reviewerMachines.render();
  check('Team members can inspect and recheck an offline machine without disconnecting or pairing it', () => {
    assert.ok(button(reviewerMachines.tree,'Check machine connection'));
    assert.equal(button(reviewerMachines.tree,'Disconnect'),undefined);
    assert.doesNotMatch(text(reviewerMachines.tree),/Connect another machine/);
    assert.match(text(reviewerMachines.tree),/Ask a workspace owner to restart/);
  });
  waitingReviewer.unmount(); ownerSetup.unmount(); reviewerMachines.unmount();
  console.log(`${passed} product behavior checks passed.`);
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => {
  Module._load = savedLoad;
  if (savedTs) require.extensions['.ts'] = savedTs; else delete require.extensions['.ts'];
  if (savedTsx) require.extensions['.tsx'] = savedTsx; else delete require.extensions['.tsx'];
});
