#!/usr/bin/env node
// Actual TaskWorkspace reads/handlers with deferred GETs and controlled polling.
// No accounts, providers, task writes, deliveries, network or browser are used.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const root = path.resolve(__dirname, '..');
const src = path.join(root, 'studio/src');
const ts = require(path.join(root, 'studio/node_modules/typescript'));
const savedLoad = Module._load;
const savedTs = require.extensions['.ts'];
const savedTsx = require.extensions['.tsx'];
let rendering, respond, passed = 0;
const calls = [], timers = new Map(), sources = [];
let nextTimer = 1;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const react = {
  useState(initial) {
    const r = rendering, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = typeof initial === 'function' ? initial() : initial;
    return [r.slots[i], value => { r.slots[i] = typeof value === 'function' ? value(r.slots[i]) : value; }];
  },
  useRef(initial) {
    const r = rendering, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = {current: initial};
    return r.slots[i];
  },
  useEffect(effect, deps) {
    const r = rendering, i = r.index++, prior = r.slots[i];
    if (!prior || !same(prior.deps, deps)) r.effects.push(() => {
      prior?.cleanup?.(); r.slots[i] = {deps, cleanup: effect()};
    });
  },
  useMemo(fn, deps) {
    const r = rendering, i = r.index++, prior = r.slots[i];
    if (!prior || !same(prior.deps, deps)) r.slots[i] = {deps, value: fn()};
    return r.slots[i].value;
  },
  useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
};
const jsx = (type, props, key) => ({type, props: props || {}, key});
Module._load = function(request, parent, ...args) {
  if (request === 'react') return react;
  if (request === 'react/jsx-runtime') return {jsx, jsxs: jsx, Fragment: Symbol.for('fragment')};
  if (parent?.filename.startsWith(src)) {
    if (/\.css$/.test(request)) return {};
    if (request === './api') return {
      api(p, init) { calls.push({path: p, init}); return respond(p, init); },
      apiUrl: p => '/api' + p, viaMachine: () => true, messageOf: e => e.message || String(e),
    };
    if (request === './WorkIcon') return {WorkIcon: () => null};
    if (request === './Brand') return {ProviderMark: () => null};
    if (request === './RunWorkspace') return {eventSummary: row => row.kind};
  }
  return savedLoad.call(this, request, parent, ...args);
};
function compile(module, filename) {
  const out = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true},
  });
  module._compile(out.outputText, filename);
}
require.extensions['.ts'] = compile;
require.extensions['.tsx'] = compile;
global.window = {
  setInterval(fn) { const id = nextTimer++; timers.set(id, fn); return id; },
  clearInterval(id) { timers.delete(id); }, addEventListener() {}, removeEventListener() {},
};
global.document = {hidden: false, activeElement: null, body: {}, getElementById: () => null};
global.localStorage = {getItem: () => null, setItem() {}};
const frames = new Map();
let nextFrame = 1;
global.requestAnimationFrame = fn => { const id = nextFrame++; frames.set(id, fn); return id; };
global.cancelAnimationFrame = id => frames.delete(id);
global.EventSource = class {
  constructor(url) { this.url = url; sources.push(this); }
  close() { this.closed = true; }
};
function renderer(component, props) {
  return {component, props, slots: [], effects: [], index: 0,
    render(flush = true) {
      rendering = this; this.index = 0; this.effects = []; this.tree = this.component(this.props);
      if (flush) this.flush(); return this.tree;
    },
    flush() { for (const effect of this.effects) effect(); this.effects = []; },
    unmount() { for (const slot of this.slots) slot?.cleanup?.(); },
  };
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
function byClass(tree, name) { return nodes(tree).find(n => n.props.className?.split(' ').includes(name)); }
function button(tree, label) { return nodes(tree).find(n => n.type === 'button' && text(n) === label); }
function approval(tree) {
  const node = nodes(tree).find(n => n.type === 'button' && /^(?:Approve candidate|Approve & apply|Loading final evidence…)$/.test(text(n)));
  assert.ok(node, 'Recorded candidate must retain its decision button'); return node;
}
function fact(tree, label) {
  const dl = byClass(tree, 'candidate-summary-facts');
  const group = nodes(dl).find(n => n.type === 'div' && nodes(n).some(v => v.type === 'dt' && text(v) === label));
  assert.ok(group, 'Missing fact ' + label); return text(nodes(group).find(n => n.type === 'dd'));
}
function deferred() {
  let resolve, reject; const promise = new Promise((a, b) => {resolve = a; reject = b;});
  return {promise, resolve, reject};
}
async function settle(view) { for (let i = 0; i < 4; i++) { await new Promise(resolve => setImmediate(resolve)); view.render(); } }
function poll(view) { assert.equal(timers.size, 1); [...timers.values()][0](); view.render(); }
function flushFrames() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(fn => fn()); }
function check(label, fn) { fn(); passed++; console.log('PASS', label); }
const phase = '66666666-6666-4666-8666-666666666666';
const newerPhase = '77777777-7777-4777-8777-777777777777';
function observation(attempt = phase) {
  return {id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', content_sha256: 'a'.repeat(64), phase: 'final', phase_attempt_id: attempt,
    provenance: {scheme: 'readonly-workspace-state-v1', before_sha256: 'b'.repeat(64), after_sha256: 'b'.repeat(64), unchanged: true}};
}
const patch = 'diff --git a/selected.py b/selected.py\n--- a/selected.py\n+++ b/selected.py\n@@ -1 +1 @@\n-old\n+new\n';
const workflow = {
  id: '11111111-1111-4111-8111-111111111111', run_id: 'run-A', title: 'Preserve compatibility', prompt: 'Preserve behavior',
  workspace: '/project', status: 'awaiting_approval', schema_version: '2.0', requester: 'developer', reviewer: 'reviewer',
  created_at: '2026-10-12T12:00:00Z', updated_at: '2026-10-12T12:00:00Z',
  candidate: {digest: 'c'.repeat(64), gates: [1, 2, 3].map(i => ({id: String(i), label: 'Gate ' + i, status: 'passed'}))},
  template: {id: 'verified-change', version: 1, name: 'Verified change'},
};
function result(overrides = {}) {
  return {schema_version: '1.1', run_id: workflow.run_id, status: 'completed', spec: {workspace: '/project'}, tasks: [], errors: [],
    checks: [{name: 'compatibility', ok: true, exit_code: 0, observation: observation()}],
    reviews: [{provider: 'claude', task_id: 'integration', ok: true, verdict: 'approved', observation: observation()}],
    artifacts: {current_verification_attempt: {phase: 'final', phase_attempt_id: phase}}, changed_files: ['selected.py'],
    diff: patch, summary: 'Preserved behavior', sessions: [], metrics: {}, usage: {reports: []}, ...overrides};
}
const props = {
  visible: true, feedback: '', sending: false, sent: '', onSend() {}, followups: [], onRelated() {}, onFeedback() {}, workflow,
  ready: true, busy: '', online: true, onAction() {}, onAgain() {}, onRevise() {}, canDeliver: true, viewerActor: 'reviewer',
  members: [], onAssign() {}, onRefresh() {}, onComment() {}, onInspect() {}, renderEvidence: () => null,
};
(async () => {
  const {TaskWorkspace} = require(path.join(src, 'TaskWorkspace.tsx'));
  const {runEvidenceRead} = require(path.join(src, 'evidence-presentation.ts'));
  const initial = deferred(); respond = () => initial.promise;
  const pending = renderer(TaskWorkspace, props);
  pending.render(); pending.render();
  check('Initial pending read reports loading without fabricated missing checks or review', () => {
    assert.equal(fact(pending.tree, 'Final checks'), 'Loading check evidence');
    assert.equal(fact(pending.tree, 'Independent review'), 'Loading review evidence');
    assert.doesNotMatch(text(byClass(pending.tree, 'candidate-summary')), /No current final checks recorded|No independent verdict was recorded/);
    assert.equal(approval(pending.tree).props.disabled, true);
    const changes = nodes(pending.tree).find(n => n.props.id === 'evidence-tab-changes');
    assert.equal(nodes(changes).filter(n => n.type === 'small').length, 0, 'Unloaded changes are unknown, not zero');
  });
  const gatePending = renderer(TaskWorkspace, {...props, ready: false, workflow: {...workflow, candidate: {...workflow.candidate,
    gates: [{id: 'checks', label: 'Project checks', status: 'failed', detail: 'Recorded check failure'}]}}});
  gatePending.render();
  check('Saved candidate gate failure remains visible independently of run loading', () => {
    assert.match(text(byClass(gatePending.tree, 'candidate-summary')), /Project checks: Failed.*Recorded check failure/);
    assert.equal(button(gatePending.tree, 'Approve candidate'), undefined);
  }); gatePending.unmount();
  initial.reject(new Error('Synthetic transport failure')); await settle(pending);
  check('Initial failed read reports unavailable outcomes and offers read-only Retry', () => {
    assert.equal(fact(pending.tree, 'Final checks'), 'Check evidence unavailable');
    assert.equal(fact(pending.tree, 'Independent review'), 'Review evidence unavailable');
    assert.match(text(pending.tree), /Evidence unavailable: Synthetic transport failure/);
    assert.ok(button(pending.tree, 'Retry')); assert.equal(approval(pending.tree).props.disabled, true);
  });
  const retry = deferred(); respond = () => retry.promise; button(pending.tree, 'Retry').props.onClick(); pending.render(); pending.render();
  check('Initial retry remains loading and cannot approve before the body returns', () => {
    assert.equal(fact(pending.tree, 'Final checks'), 'Loading check evidence'); assert.equal(approval(pending.tree).props.disabled, true);
    assert.ok(calls.every(call => !call.init?.method || call.init.method === 'GET'));
  });
  retry.resolve(result({checks: [], reviews: [], artifacts: {}, changed_files: [], diff: ''})); await settle(pending);
  check('Successfully loaded missing legacy evidence is unrecorded rather than a read failure', () => {
    assert.equal(fact(pending.tree, 'Final checks'), 'No current final checks recorded');
    assert.equal(fact(pending.tree, 'Independent review'), 'Unrecorded');
    assert.doesNotMatch(text(pending.tree), /Evidence unavailable: Synthetic transport failure/);
    const changes = nodes(pending.tree).find(n => n.props.id === 'evidence-tab-changes');
    assert.equal(text(nodes(changes).find(n => n.type === 'small')), '0', 'A genuinely empty loaded patch has a recorded zero count');
  }); pending.unmount();

  respond = async () => result(); const live = renderer(TaskWorkspace, props); live.render(); await settle(live);
  check('Completed correctly bound body shows current evidence and preserves approval eligibility', () => {
    assert.equal(fact(live.tree, 'Final checks'), '1 passed'); assert.equal(fact(live.tree, 'Independent review'), 'Reviewed');
    assert.equal(approval(live.tree).props.disabled, false); assert.match(text(live.tree), /selected.py/);
    const changes = nodes(live.tree).find(n => n.props.id === 'evidence-tab-changes');
    assert.equal(text(nodes(changes).find(n => n.type === 'small')), '1');
  });
  const refresh = deferred(); respond = () => refresh.promise; poll(live);
  check('Ordinary pending background polling retains stable labels without warning-layout churn', () => {
    assert.equal(fact(live.tree, 'Final checks'), '1 passed'); assert.equal(fact(live.tree, 'Independent review'), 'Reviewed');
    assert.doesNotMatch(text(byClass(live.tree, 'candidate-summary')), /Last loaded:|Checking for updated evidence/);
    assert.match(text(live.tree), /selected.py/);
  });
  refresh.reject(new Error('Synthetic refresh failure')); await settle(live);
  check('Refresh failure keeps inspectable saved evidence with a stale qualifier and blocks approval', () => {
    assert.equal(fact(live.tree, 'Final checks'), 'Last loaded: 1 passed');
    assert.equal(fact(live.tree, 'Independent review'), 'Last loaded: Reviewed');
    assert.match(text(live.tree), /Evidence refresh failed: Synthetic refresh failure/);
    assert.match(text(live.tree), /selected.py/); assert.equal(approval(live.tree).props.disabled, true);
  });
  const refreshRetry = deferred(); respond = () => refreshRetry.promise; button(live.tree, 'Retry').props.onClick(); live.render(); live.render();
  check('Pending retry after refresh failure preserves its stale qualifier and approval block', () => {
    assert.equal(fact(live.tree, 'Final checks'), 'Last loaded: 1 passed');
    assert.equal(fact(live.tree, 'Independent review'), 'Last loaded: Reviewed');
    assert.equal(approval(live.tree).props.disabled, true);
  });
  refreshRetry.resolve(result()); await settle(live);
  check('Successful current retry clears the read error and restores current evidence labels', () => {
    assert.equal(fact(live.tree, 'Final checks'), '1 passed'); assert.equal(fact(live.tree, 'Independent review'), 'Reviewed');
    assert.equal(approval(live.tree).props.disabled, false); assert.equal(button(live.tree, 'Retry'), undefined);
  });
  const digestRead = deferred(); respond = () => digestRead.promise;
  live.props = {...props, workflow: {...workflow, candidate: {...workflow.candidate, digest: 'd'.repeat(64)}}}; live.render(false);
  check('New candidate digest synchronously hides prior run before reset effects execute', () => {
    assert.equal(fact(live.tree, 'Final checks'), 'Loading check evidence');
    assert.equal(fact(live.tree, 'Independent review'), 'Loading review evidence');
    assert.equal(approval(live.tree).props.disabled, true); assert.doesNotMatch(text(live.tree), /selected.py/);
    const changes = nodes(live.tree).find(n => n.props.id === 'evidence-tab-changes');
    assert.equal(nodes(changes).filter(n => n.type === 'small').length, 0, 'A new candidate cannot retain the prior patch count');
  }); live.flush(); live.render(); digestRead.resolve(result({diff: patch.replaceAll('selected.py', 'revised.py'), changed_files: ['revised.py']})); await settle(live);
  const actorRead = deferred(); respond = () => actorRead.promise; live.props = {...live.props, viewerActor: 'different-reviewer'}; live.render(false);
  check('Viewer change synchronously invalidates the prior actor evidence snapshot', () => {
    assert.equal(fact(live.tree, 'Final checks'), 'Loading check evidence'); assert.equal(approval(live.tree).props.disabled, true);
    assert.doesNotMatch(text(live.tree), /revised.py/);
  }); live.flush(); live.render(); actorRead.resolve(result()); await settle(live);
  const identityRead = deferred(); respond = () => identityRead.promise; live.props = {...live.props, workflow: {...workflow, id: '22222222-2222-4222-8222-222222222222'}}; live.render(false);
  check('Different workflow with reused run ID and digest never displays the previous task snapshot', () => {
    assert.equal(fact(live.tree, 'Final checks'), 'Loading check evidence'); assert.equal(approval(live.tree).props.disabled, true);
  }); live.flush(); live.render(); identityRead.resolve(result()); await settle(live); live.unmount();

  const old = deferred(), current = deferred();
  respond = p => p === '/runs/run-A' ? old.promise : current.promise;
  const selected = renderer(TaskWorkspace, props); selected.render(); const oldSource = sources.at(-1);
  selected.props = {...props, workflow: {...workflow, id: '33333333-3333-4333-8333-333333333333', run_id: 'run-B'}}; selected.render();
  current.resolve(result({run_id: 'run-B', diff: patch.replaceAll('selected.py', 'current.py'), changed_files: ['current.py']})); await settle(selected);
  old.resolve(result()); await settle(selected);
  check('An older deferred response cannot replace the newly selected run', () => {
    assert.match(text(selected.tree), /current.py/); assert.doesNotMatch(text(selected.tree), /selected.py/);
    assert.equal(fact(selected.tree, 'Final checks'), '1 passed'); assert.equal(oldSource.closed, true);
  }); selected.unmount();
  respond = async () => result({run_id: 'wrong-run'}); const mismatch = renderer(TaskWorkspace, props); mismatch.render(); await settle(mismatch);
  check('A mismatched returned run ID is unavailable and never supplies approval or patch content', () => {
    assert.match(text(mismatch.tree), /Returned run evidence does not match this task/);
    assert.equal(fact(mismatch.tree, 'Final checks'), 'Check evidence unavailable');
    assert.equal(approval(mismatch.tree).props.disabled, true); assert.doesNotMatch(text(mismatch.tree), /selected.py/);
  }); mismatch.unmount();

  respond = async () => result(); const offline = renderer(TaskWorkspace, props); offline.render(); await settle(offline);
  offline.props = {...props, online: false}; offline.render();
  check('Offline after a loaded body retains qualified inspectable evidence and blocks approval', () => {
    assert.equal(fact(offline.tree, 'Final checks'), 'Last loaded: 1 passed');
    assert.equal(fact(offline.tree, 'Independent review'), 'Last loaded: Reviewed');
    assert.match(text(offline.tree), /worker is offline.*last loaded recorded evidence/i); assert.equal(approval(offline.tree).props.disabled, true);
  }); offline.unmount();
  const beforeOffline = calls.length; const absent = renderer(TaskWorkspace, {...props, online: false}); absent.render();
  check('Offline before the first read is unavailable, never unrecorded, and dispatches no read', () => {
    assert.equal(fact(absent.tree, 'Final checks'), 'Check evidence unavailable');
    assert.equal(fact(absent.tree, 'Independent review'), 'Review evidence unavailable'); assert.equal(calls.length, beforeOffline);
  }); absent.unmount();

  respond = async () => result(); const phases = renderer(TaskWorkspace, props); phases.render(); await settle(phases);
  respond = async () => result({artifacts: {current_verification_attempt: {phase: 'final', phase_attempt_id: newerPhase}}}); poll(phases); await settle(phases);
  check('New current validation marker makes older passed check and review observations historical', () => {
    assert.equal(fact(phases.tree, 'Final checks'), 'No current final checks recorded');
    assert.equal(fact(phases.tree, 'Independent review'), 'Unrecorded');
    assert.match(text(byClass(phases.tree, 'candidate-summary')), /association with this verification attempt is unrecorded or historical/);
  });
  respond = async () => result({checks: [{name: 'compatibility', ok: false, exit_code: 1, observation: observation(newerPhase)}],
    artifacts: {current_verification_attempt: {phase: 'final', phase_attempt_id: newerPhase}}}); poll(phases); await settle(phases);
  check('A failed current check replaces an older pass without reviving the old positive review', () => {
    assert.equal(fact(phases.tree, 'Final checks'), '1 failed'); assert.equal(fact(phases.tree, 'Independent review'), 'Unrecorded');
  }); phases.unmount();

  respond = async () => result({checks: [], reviews: [], artifacts: {}});
  const legacy = renderer(TaskWorkspace, {...props, workflow: {...workflow, schema_version: '1.0'}}); legacy.render(); await settle(legacy);
  check('Completed legacy body retains existing saved-gate approval policy with explicitly unrecorded current provenance', () => {
    assert.equal(fact(legacy.tree, 'Final checks'), 'No current final checks recorded');
    assert.equal(fact(legacy.tree, 'Independent review'), 'Unrecorded'); assert.equal(approval(legacy.tree).props.disabled, false);
    assert.equal(text(approval(legacy.tree)), 'Approve & apply');
  }); legacy.unmount();
  const noRun = renderer(TaskWorkspace, {...props, workflow: {...workflow, run_id: undefined}, ready: false}); noRun.render();
  check('A task without a saved execution run is distinctly unrecorded rather than indefinitely loading', () => {
    assert.equal(fact(noRun.tree, 'Final checks'), 'No run evidence recorded');
    assert.equal(fact(noRun.tree, 'Independent review'), 'Unrecorded');
    assert.match(text(byClass(noRun.tree, 'candidate-summary')), /no saved execution run yet/);
  }); noRun.unmount();

  let focusCount = 0;
  const tabTarget = {getClientRects: () => [{}], closest: () => null, focus() { focusCount++; document.activeElement = this; }};
  document.getElementById = id => id === 'evidence-tab-changes' ? tabTarget : null;
  async function failedView() {
    respond = async () => { throw new Error('Synthetic focus retry failure'); };
    const view = renderer(TaskWorkspace, props); view.render(); await settle(view);
    const retryButton = button(view.tree, 'Retry'); assert.ok(retryButton);
    const opener = {}; retryButton.props.ref.current = opener;
    return {view, opener};
  }
  const focusRetry = await failedView(); const focusRead = deferred(); respond = () => focusRead.promise;
  document.activeElement = focusRetry.opener; button(focusRetry.view.tree, 'Retry').props.onClick(); focusRetry.view.render();
  focusRead.resolve(result()); await settle(focusRetry.view); document.activeElement = document.body; flushFrames();
  check('A successful retry returns lost focused-opener focus to the active evidence tab', () => {
    assert.equal(focusCount, 1); assert.equal(document.activeElement, tabTarget);
  }); focusRetry.view.unmount();

  const deliberate = await failedView(); const deliberateRead = deferred(); respond = () => deliberateRead.promise;
  document.activeElement = deliberate.opener; button(deliberate.view.tree, 'Retry').props.onClick(); deliberate.view.render();
  const accountControl = {}; document.activeElement = accountControl;
  deliberateRead.resolve(result()); await settle(deliberate.view); flushFrames();
  check('Retry completion does not steal deliberate focus moved during the read', () => {
    assert.equal(focusCount, 1); assert.equal(document.activeElement, accountControl);
  }); deliberate.view.unmount();

  const laterMove = await failedView(); const laterRead = deferred(); respond = () => laterRead.promise;
  document.activeElement = laterMove.opener; button(laterMove.view.tree, 'Retry').props.onClick(); laterMove.view.render();
  laterRead.resolve(result()); await settle(laterMove.view); document.activeElement = accountControl; flushFrames();
  check('Scheduled retry focus return respects a deliberate move before its animation frame', () => {
    assert.equal(focusCount, 1); assert.equal(document.activeElement, accountControl);
  }); laterMove.view.unmount();

  const focusChange = await failedView(); const changeRead = deferred(); respond = () => changeRead.promise;
  document.activeElement = focusChange.opener; button(focusChange.view.tree, 'Retry').props.onClick(); focusChange.view.render();
  changeRead.resolve(result()); await settle(focusChange.view);
  respond = () => deferred().promise;
  focusChange.view.props = {...props, workflow: {...workflow, candidate: {...workflow.candidate, digest: 'e'.repeat(64)}}};
  focusChange.view.render(); document.activeElement = document.body; flushFrames();
  check('Candidate identity change cancels a queued retry focus return', () => assert.equal(focusCount, 1)); focusChange.view.unmount();

  const hidden = await failedView(); const hiddenRead = deferred(); respond = () => hiddenRead.promise;
  document.activeElement = hidden.opener; button(hidden.view.tree, 'Retry').props.onClick(); hidden.view.render();
  hiddenRead.resolve(result()); await settle(hidden.view); hidden.view.props = {...props, visible: false}; hidden.view.render();
  document.activeElement = document.body; flushFrames();
  check('Hiding the workspace cancels a queued retry focus return', () => assert.equal(focusCount, 1)); hidden.view.unmount();

  check('Read helper keeps transport availability separate from check/review outcome policy', () => {
    assert.equal(runEvidenceRead({requested: true, online: true, loaded: true, loading: true, error: ''}).state, 'refreshing');
    assert.equal(runEvidenceRead({requested: true, online: true, loaded: false, loading: false, error: 'blocked'}).state, 'unavailable');
    assert.equal(runEvidenceRead({requested: false, online: false, loaded: false, loading: true, error: ''}).state, 'unrecorded');
  });
  assert.ok(calls.every(call => !call.init?.method || call.init.method === 'GET'));
  console.log(`${passed} evidence loading checks passed`);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  Module._load = savedLoad; require.extensions['.ts'] = savedTs; require.extensions['.tsx'] = savedTsx;
});
