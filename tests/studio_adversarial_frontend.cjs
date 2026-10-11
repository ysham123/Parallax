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
(async () => {
  const helpers = require(path.join(src, 'workflow-state.ts'));
  const session = require(path.join(src, 'session.ts'));
  check('Unknown paired-worker authority cannot start/deliver/approve', () => assert.deepEqual(helpers.workflowAccess(null, true), { deliver: false, review: false }));
  check('Legacy personal approval remains available on older paired workers', () => assert.equal(helpers.workflowReviewAccess(null, true, false, '1.0'), true));
  check('Older workers cannot bypass team or v2 approval authority', () => { assert.equal(helpers.workflowReviewAccess(null, true, true, '1.0'), false); assert.equal(helpers.workflowReviewAccess(null, true, false, '2.0'), false); });
  check('Reviewer can review but cannot deliver', () => assert.deepEqual(helpers.workflowAccess({ role: 'reviewer' }, true), { deliver: false, review: true }));
  check('Unknown roles fail closed', () => assert.deepEqual(helpers.workflowAccess({ role: 'admin' }, true), { deliver: false, review: false }));
  check('Legacy local runtime remains compatible', () => assert.deepEqual(helpers.workflowAccess(null, false), { deliver: true, review: true }));
  check('Incomplete candidate gates refuse approval without crashing', () => assert.equal(helpers.canApprove('awaiting_approval', { digest: 'a'.repeat(64) }), false));
  check('Identical project paths on different workers do not share GitHub binding choices', () => assert.deepEqual(helpers.githubBindingsForProject([{ project: '/project', worker: 'A', id: 'one' }, { project: '/project', worker: 'B', id: 'two' }], '/project', 'B').map(b => b.id), ['two']));
  const id = helpers.workflowOperationId('actor/project/workflow', 'apply', 'a'.repeat(64));
  check('Apply retry reuses operation ID', () => assert.equal(helpers.workflowOperationId('actor/project/workflow', 'apply', 'a'.repeat(64)), id));
  delete require.cache[require.resolve(path.join(src, 'workflow-state.ts'))];
  const reloaded = require(path.join(src, 'workflow-state.ts'));
  check('Apply operation survives module/tab reload', () => assert.equal(reloaded.workflowOperationId('actor/project/workflow', 'apply', 'a'.repeat(64)), id));
  check('Operation IDs are isolated by actor and candidate', () => {
    assert.notEqual(reloaded.workflowOperationId('other/project/workflow', 'apply', 'a'.repeat(64)), id);
    assert.notEqual(reloaded.workflowOperationId('actor/project/workflow', 'apply', 'b'.repeat(64)), id);
  });
  Object.defineProperty(window, 'sessionStorage', { configurable: true, get() { throw new Error('blocked'); } });
  check('Invitation parsing works with blocked storage', () => {
    assert.equal(session.invitationToken(''), '');
    assert.equal(session.invitationToken('?invite=' + 'a'.repeat(24)), 'a'.repeat(24));
    session.rememberInvitation('a'.repeat(24)); session.rememberInvitation(null);
  });
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) } });
  const a = { id: '11111111-1111-4111-8111-111111111111', title: 'Task A', status: 'awaiting_approval', schema_version: '2.0', workspace: '/project', requester: 'requester', candidate: { digest: 'a'.repeat(64), gates: [1,2,3].map(() => ({status:'passed'})) }, template: { id: 'recipe', name: 'Recipe', version: 1 }, created_at: '2026-10-09T10:00:00Z', updated_at: '2026-10-09T10:00:00Z' };
  const b = { ...a, id: '22222222-2222-4222-8222-222222222222', title: 'Task B' };
  const authority = deferred();
  let comment = deferred();
  let approvalAttempts = 0;
  responder = async (p, init) => {
    if (p === '/context') return authority.promise;
    if (p === '/workflow-templates' || p === '/github/bindings') return [];
    if (p === '/workspaces/members') return [{ account: 'reviewer', login: 'Allowed' }, { account: 'unauthorized', login: 'Disallowed' }];
    if (p === '/workflows') return [a, b];
    if (p.endsWith('/comment') || p.endsWith('/reviewer')) return comment.promise;
    if (p.endsWith('/approve')) { if (++approvalAttempts === 1) throw new Error('network timeout'); return { ...a, status: 'approved', decision: { action: 'approve' } }; }
    if (p === '/workflows/' + a.id) return a;
    if (p === '/workflows/' + b.id) return b;
    throw new Error('Unexpected request ' + p);
  };
  const { Workflows } = require(path.join(src, 'Workflows.tsx'));
  const { TaskWorkspace } = require(path.join(src, 'TaskWorkspace.tsx'));
  const w = renderer(Workflows, { active: true, workspace: '/project', online: true, knownProjects: ['/project'], onWorkspace() {}, onInspect() {}, onConnections() {}, renderParticipant() {}, renderEvidence() {}, renderCheck() {} });
  w.render(); await settle(w);
  const task = () => nodes(w.tree).find(n => n.type === TaskWorkspace);
  check('Task evidence and measurement form use distinct sibling keys across polling', () => { const parent = nodes(w.tree).find(n => n.props.className === 'task-main'); const siblings = parent.props.children.filter(n => n && typeof n === 'object' && n.key != null); assert.equal(new Set(siblings.map(n => n.key)).size, siblings.length); });
  check('Loaded tasks stay read-only until authority returns', () => { assert.equal(task().props.ready, false); assert.equal(task().props.canDeliver, false); });
  authority.resolve({ authority: { actor: 'reviewer', role: 'developer', team: true, reviewers_by_project: { '/project': ['reviewer'] } } });
  await settle(w);
  check('Reviewer assignment only offers authorized project members', () => assert.deepEqual(task().props.members.map(m => m.account), ['reviewer']));
  task().props.onComment(); w.render();
  nodes(w.tree).find(n => n.type === 'button' && text(n).includes('Task B')).props.onClick();
  await settle(w);
  comment.resolve({ ...a, comments: [{ message: 'Old task response' }] });
  await settle(w);
  check('Late comment response cannot replace the selected task', () => assert.equal(task().props.workflow.id, b.id));
  comment = deferred();
  nodes(w.tree).find(n => n.type === 'button' && text(n).includes('Task A')).props.onClick();
  await settle(w); task().props.onAssign('reviewer'); w.render();
  nodes(w.tree).find(n => n.type === 'button' && text(n).includes('Task B')).props.onClick();
  await settle(w); comment.resolve({ ...a, reviewer: 'reviewer' }); await settle(w);
  check('Late assignment response cannot replace the selected task', () => assert.equal(task().props.workflow.id, b.id));
  nodes(w.tree).find(n => n.type === 'button' && text(n).includes('Task A')).props.onClick(); await settle(w);
  task().props.onFeedback('Saved review comment'); w.render(); comment = deferred(); task().props.onComment(); w.render(); comment.reject(new Error('timeout')); await settle(w); comment = deferred(); task().props.onComment(); w.render(); comment.resolve(a); await settle(w);
  check('Review comment timeout/retry reuses its request ID', () => { const requests = calls.filter(c => c.path.endsWith('/comment')).slice(-2).map(c => JSON.parse(c.init.body)); assert.equal(requests[0].request_id, requests[1].request_id); assert.equal(requests[0].message, 'Saved review comment'); });
  task().props.onAction('approve'); await settle(w); task().props.onAction('approve'); await settle(w);
  check('Actual approval timeout/retry uses the same durable operation', () => {
    const requests = calls.filter(c => c.path.endsWith('/approve')).map(c => JSON.parse(c.init.body));
    assert.equal(requests.length, 2); assert.equal(requests[0].request_id, requests[1].request_id);
  });
  w.unmount();
  let localAction;
  const t = renderer(TaskWorkspace, { visible: false, workflow: { ...a, status: 'needs_attention', decision: { action: 'approve' } }, canDeliver: true, members: [], ready: false, busy: '', online: true, feedback: '', followups: [], onAction: a => { localAction = a; }, onFeedback() {}, renderEvidence() {} });
  t.render();
  check('Failed approved local application exposes apply recovery', () => { button(t.tree, 'Retry local application').props.onClick(); assert.equal(localAction, 'apply'); assert.equal(button(t.tree, 'Resume task'), undefined); });
  t.props.canDeliver = false; t.render();
  check('Reviewers cannot resume or retry filesystem delivery', () => assert.equal(button(t.tree, 'Retry local application'), undefined));
  t.props.canDeliver = true; t.props.workflow = { ...a, status: 'superseded' }; t.props.feedback = 'Retry the saved parent'; t.render();
  check('Superseded parents expose saved-candidate retry after an unsuccessful child', () => assert.ok(button(t.tree, 'Revise candidate')));
  t.unmount();
  const { PublicationPanel } = require(path.join(src, 'PublicationPanel.tsx'));
  const recovery = deferred();
  calls = []; responder = p => p.startsWith('/github/publication/') ? recovery.promise : Promise.reject(new Error('Unexpected request'));
  const publication = renderer(PublicationPanel, { workflow: { ...a, status: 'approved', github_target: { id: 'binding' } }, canDeliver: true, onChanged() {}, onFeedback() {} });
  publication.render();
  check('Publication cannot start before durable recovery lookup', () => assert.equal(button(publication.tree, 'Review publication details').props.disabled, true));
  recovery.resolve({ state: 'pending', can_retry: false, request: { title: 'Recorded title', description: 'Recorded description' } }); await settle(publication);
  check('Saved publication presents recorded inputs and blocks a different actor', () => { assert.match(text(publication.tree), /Recorded title/); assert.equal(button(publication.tree, 'Retry saved publication').props.disabled, true); assert.equal(button(publication.tree, 'Review publication details'), undefined); });
  publication.props.workflow = { ...publication.props.workflow, github_target: { id: 'binding' } }; publication.render(); await settle(publication);
  check('Routine workflow polling does not restart recovery or overwrite edits', () => assert.equal(calls.length, 1));
  publication.unmount();
  const recoveryFailure = renderer(PublicationPanel, { workflow: { ...a, status: 'approved', github_target: { id: 'binding' } }, canDeliver: true });
  responder = () => Promise.reject(new Error('Disconnected'));
  recoveryFailure.render(); await settle(recoveryFailure);
  check('Failed recovery lookup cannot create a competing publication', () => { assert.equal(button(recoveryFailure.tree, 'Review publication details').props.disabled, true); assert.ok(button(recoveryFailure.tree, 'Retry publication recovery check')); });
  recoveryFailure.unmount();
  const { PilotMetrics } = require(path.join(src, 'PilotMetrics.tsx'));
  let measurements = 0; calls = [];
  responder = async () => { if (++measurements === 1) throw new Error('timeout'); return {}; };
  const metrics = renderer(PilotMetrics, { workflow: a }); metrics.render();
  nodes(metrics.tree).find(n => n.type === 'input' && n.props.type === 'number').props.onChange({ target: { value: '42' } }); metrics.render();
  nodes(metrics.tree).find(n => n.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(metrics);
  nodes(metrics.tree).find(n => n.type === 'form').props.onSubmit({ preventDefault() {} }); await settle(metrics);
  check('Comparison recording retries do not duplicate a timed-out measurement', () => {
    const requests = calls.map(c => JSON.parse(c.init.body)); assert.equal(requests[0].request_id, requests[1].request_id); assert.equal(requests[0].duration_seconds, 42);
  }); metrics.unmount();
  const { WorkspaceControls } = require(path.join(src, 'WorkspaceControls.tsx'));
  const keyboard = new Map(); let focusedSummary = 0;
  window.addEventListener = (event, fn) => keyboard.set(event, fn); window.removeEventListener = event => keyboard.delete(event);
  document.addEventListener = () => {}; document.removeEventListener = () => {};
  location.search = '?invite=' + 'a'.repeat(24);
  responder = async p => p === '/workspaces/members' ? [{ account: 'other', name: 'Ada', login: 'ada', role: 'reviewer' }] : p === '/github/config' ? { configured: false } : [];
  const workspace = renderer(WorkspaceControls, { session: { account: { id: 'a' }, workspace: { id: 'one', name: 'Team', kind: 'team', role: 'owner' } }, machines: [], onSwitch() {} });
  workspace.render(); await settle(workspace);
  nodes(workspace.tree).find(n => n.type === 'details').props.ref.current = { querySelector: () => ({ focus: () => focusedSummary++ }) };
  keyboard.get('keydown')({ key: 'Escape', preventDefault() {} }); workspace.render();
  check('Escape dismisses invitation settings and restores summary focus', () => { assert.equal(workspace.tree.props.open, false); assert.equal(focusedSummary, 1); });
  nodes(workspace.tree).find(n => n.type === 'input' && n.props.value === 'a'.repeat(24)).props.onChange({ target: { value: 'b'.repeat(24) } }); workspace.render();
  check('Editing a saved invitation does not force dismissed settings back open', () => assert.equal(workspace.tree.props.open, false));
  check('Membership removal has a unique screen-reader label', () => assert.equal(button(workspace.tree, 'Remove').props['aria-label'], 'Remove Ada from workspace'));
  workspace.unmount(); location.search = '';
  let policyTimeout = true, policies = [];
  const binding = {id:'binding-revoked',worker:'revoked-worker',path:'/legacy-project',members:'["other"]'};
  responder = async (p, init) => {
    if(p === '/workspaces/members') return [{account:'other',name:'Ada',login:'ada',role:'reviewer'}, {account:'second',name:'Grace',login:'grace',role:'developer'}];
    if(p === '/workspaces/projects') return [binding];
    if(p === '/github/config') return {configured:false};
    if(p === '/workspaces/projects/binding-revoked' && init?.method === 'PATCH') { policies.push(JSON.parse(init.body)); if(policyTimeout) throw new Error('Timed out after dispatch'); return {ok:true}; }
    return [];
  };
  const ownerPolicy = renderer(WorkspaceControls,{session:{account:{id:'owner'},workspace:{id:'one',name:'Team',kind:'team',role:'owner'}},machines:[],onSwitch(){}});
  ownerPolicy.render(); await settle(ownerPolicy);
  nodes(ownerPolicy.tree).find(n=>n.props['aria-label']==='Existing project binding').props.onChange({target:{value:binding.id}}); ownerPolicy.render();
  check('Owner can inspect permissions for a revoked machine without a pairing or resurrection control',()=>{assert.match(text(ownerPolicy.tree),/archived receipts only/); assert.equal(nodes(ownerPolicy.tree).find(n=>n.props['aria-label']==='Project access for Ada').props.checked,true);});
  button(ownerPolicy.tree,'Save existing project permissions').props.onClick(); await settle(ownerPolicy);
  button(ownerPolicy.tree,'Save existing project permissions').props.onClick(); await settle(ownerPolicy);
  check('Permission timeout retry binds the same request identity to the exact current-member grants',()=>{assert.equal(policies.length,2); assert.match(policies[0].request_id,/^[0-9a-f-]{36}$/); assert.equal(policies[0].request_id,policies[1].request_id); assert.deepEqual(policies[0].members,['other']); assert.equal('worker' in policies[0],false); assert.equal('path' in policies[0],false);});
  nodes(ownerPolicy.tree).find(n=>n.props['aria-label']==='Project access for Grace').props.onChange({target:{checked:true}}); ownerPolicy.render();
  button(ownerPolicy.tree,'Save existing project permissions').props.onClick(); await settle(ownerPolicy);
  check('Editing existing project grants creates a new operation identity',()=>{assert.notEqual(policies[2].request_id,policies[1].request_id); assert.deepEqual(policies[2].members,['other','second']);});
  for(const label of ['Ada','Grace']) {nodes(ownerPolicy.tree).find(n=>n.props['aria-label']==='Project access for '+label).props.onChange({target:{checked:false}}); ownerPolicy.render();}
  const beforeEmpty = policies.length; button(ownerPolicy.tree,'Save existing project permissions').props.onClick(); await settle(ownerPolicy);
  check('Empty selected-member editing never silently opens a project to all members',()=>{assert.equal(policies.length,beforeEmpty); assert.equal(button(ownerPolicy.tree,'Save existing project permissions').props.disabled,true);});
  nodes(ownerPolicy.tree).find(n=>n.props['aria-label']==='Existing project access').props.onChange({target:{value:'all'}}); ownerPolicy.render();
  policyTimeout=false; button(ownerPolicy.tree,'Save existing project permissions').props.onClick(); await settle(ownerPolicy);
  check('All-member access is explicit and records only membership grants while keeping the worker revoked',()=>{assert.deepEqual(policies.at(-1).members,[]); assert.match(text(ownerPolicy.tree),/disconnected machines remain revoked/);});
  ownerPolicy.unmount();
  for(const role of ['developer','reviewer','unknown']) {
    const readonly = renderer(WorkspaceControls,{session:{account:{id:'other'},workspace:{id:'one',name:'Team',kind:'team',role}},machines:[],onSwitch(){}}); readonly.render(); await settle(readonly);
    check(role+' sees authorized existing project policy without its Owner editor',()=>{assert.match(text(readonly.tree),/legacy-project/); assert.match(text(readonly.tree),/Read-only policy/); assert.equal(button(readonly.tree,'Save existing project permissions'),undefined); assert.equal(nodes(readonly.tree).some(n=>n.props['aria-label']==='Existing project access'),false);}); readonly.unmount();
  }
  location.pathname = '/studio';
  const { default: CloudApp } = require(path.join(src, 'CloudApp.tsx'));
  const focus = new Map(), timers = new Map(); let timer = 0;
  window.addEventListener = (name, handler) => focus.set(name, handler);
  window.removeEventListener = name => focus.delete(name);
  window.setInterval = (handler, ms) => { const id = ++timer; timers.set(id, { handler, ms }); return id; };
  window.clearInterval = id => timers.delete(id);
  document.visibilityState = 'visible'; document.addEventListener = () => {}; document.removeEventListener = () => {};
  const sessionA = { ok: true, auth: 'account', mode: 'hosted', account: { id: 'a', login: 'A' }, workspace: { id: 'same-team', kind: 'team', role: 'owner', hosted_execution: false } };
  const sessionB = { ...sessionA, account: { id: 'b', login: 'B' }, workspace: { ...sessionA.workspace, role: 'reviewer' } };
  const sessionRequests = []; const machineRequests = [];
  global.fetch = (url) => {
    const request = deferred();
    (url === '/api/session' ? sessionRequests : machineRequests).push(request);
    return request.promise;
  };
  const response = data => ({ ok: true, status: 200, headers: { get: () => 'same-team' }, json: async () => data });
  const cloud = renderer(CloudApp().type, {}); cloud.render();
  sessionRequests.shift().resolve(response(sessionA)); await settle(cloud);
  const oldMachineJSON = deferred();
  machineRequests.shift().resolve({ ...response(null), json: () => oldMachineJSON.promise }); await settle(cloud);
  focus.get('focus')(); focus.get('focus')();
  const olderSession = sessionRequests.shift(), newerSession = sessionRequests.shift();
  newerSession.resolve(response(sessionB)); await settle(cloud);
  machineRequests.shift().resolve(response([{ id: 'machine-B', name: 'B machine', online: true, platform: 'linux', workspaces: ['/project'] }])); await settle(cloud);
  olderSession.resolve(response(sessionA));
  oldMachineJSON.resolve([{ id: 'machine-A', name: 'A machine', online: true, platform: 'linux', workspaces: ['/project'] }]); await settle(cloud);
  check('Out-of-order account session responses do not restore prior actor', () => assert.equal(nodes(cloud.tree).find(n => n.props.execution).key, 'b:same-team:reviewer:machine-B'));
  check('Late machine body cannot cross account/role scope', () => assert.equal(nodes(cloud.tree).find(n => n.props.execution).props.execution.name, 'B machine'));
  check('Open Studio rechecks membership without waiting for tab focus', () => assert.ok([...timers.values()].some(t => t.ms === 15000)));
  cloud.unmount();
  location.pathname = '/'; location.search = '';
  document.documentElement = { dataset: {} };
  const publicTimeouts = new Map(); let publicTimer = 0;
  window.setTimeout = (handler, ms) => { const id = ++publicTimer; publicTimeouts.set(id, { handler, ms }); return id; };
  window.clearTimeout = id => publicTimeouts.delete(id);
  const publicRequests = [], optionalConfig = deferred();
  global.fetch = (url, init) => { publicRequests.push({ url, init }); return optionalConfig.promise; };
  const { default: PublicSite } = require(path.join(src, 'PublicSite.tsx'));
  const { default: PublicEntry } = require(path.join(src, 'PublicEntry.tsx'));
  const publicRoot = renderer(CloudApp, {}); publicRoot.render();
  const immediateRequests = publicRequests.length;
  const publicSite = renderer(publicRoot.tree.type, publicRoot.tree.props); publicSite.render();
  check('Public root renders immediately and never requests private session or machine data', () => {
    assert.equal(publicRoot.tree.type, PublicSite);
    assert.equal(publicSite.tree.type, PublicEntry);
    assert.equal(immediateRequests, 0);
    assert.deepEqual(publicRequests.map(r => r.url), ['/api/auth/config']);
  });
  function installationPresent(site) {
    const entry = renderer(site.tree.type, site.tree.props); entry.render();
    const install = nodes(entry.tree).find(n => typeof n.type === 'function' && n.type.name === 'Install');
    assert.ok(install, 'Public entry contains its actual installation component');
    const renderedInstall = renderer(install.type, install.props); renderedInstall.render();
    assert.ok(nodes(renderedInstall.tree).some(n => n.type === 'section' && n.props.id === 'install'));
    assert.ok(nodes(entry.tree).some(n => n.type === 'a' && n.props.href === '#install'));
    renderedInstall.unmount(); entry.unmount();
  }
  installationPresent(publicSite);
  optionalConfig.reject(new Error('Relay is unavailable')); await settle(publicSite);
  installationPresent(publicSite);
  publicSite.unmount(); publicRoot.unmount();
  const timeoutConfig = deferred(); let timeoutSignal;
  global.fetch = (url, init) => {
    publicRequests.push({ url, init }); timeoutSignal = init.signal;
    init.signal.addEventListener('abort', () => timeoutConfig.reject(new Error('Aborted optional config')));
    return timeoutConfig.promise;
  };
  const timeoutSite = renderer(PublicSite, { hosted: true }); timeoutSite.render();
  installationPresent(timeoutSite);
  [...publicTimeouts.values()].find(timer => timer.ms === 5000).handler();
  await settle(timeoutSite);
  check('Failed or timed-out optional auth configuration preserves the working installation view', () => {
    assert.equal(timeoutSignal.aborted, true);
    installationPresent(timeoutSite);
    assert.equal(timeoutSite.tree.props.config.github, false);
    assert.deepEqual(publicRequests.map(r => r.url), ['/api/auth/config', '/api/auth/config']);
    assert.equal(publicTimeouts.size, 0);
  });
  timeoutSite.unmount();
  console.log(`${passed} adversarial frontend behavior checks passed.`);
})().catch(e => { console.error(e); process.exitCode = 1; }).finally(() => {
  Module._load = savedLoad;
  if (savedTs) require.extensions['.ts'] = savedTs; else delete require.extensions['.ts'];
  if (savedTsx) require.extensions['.tsx'] = savedTsx; else delete require.extensions['.tsx'];
});
