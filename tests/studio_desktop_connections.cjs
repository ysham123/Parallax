#!/usr/bin/env node
// Actual Connections/App handlers with synthetic credentials and no network.
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
let rendering, mode = 'production', passed = 0;
let calls = [], responder = async () => ({});
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
    const r = rendering, i = r.index++, previous = r.slots[i];
    if (!previous || !same(previous.deps, deps)) {
      r.effects.push(() => { previous?.cleanup?.(); r.slots[i] = { deps, cleanup: effect() }; });
    }
  },
  useMemo(fn, deps) {
    const r = rendering, i = r.index++, previous = r.slots[i];
    if (!previous || !same(previous.deps, deps)) r.slots[i] = { deps, value: fn() };
    return r.slots[i].value;
  },
  useCallback(fn, deps) { return react.useMemo(() => fn, deps); },
};
const jsx = (type, props, key) => ({ type, props: props || {}, key });
const api = {
  api(p, init) { calls.push({ path: p, init }); return responder(p, init); },
  messageOf: error => error.message || String(error), viaMachine: () => false,
  apiUrl: value => '/api' + value,
};
Module._load = function(request, parent, ...rest) {
  if (request === 'react') return react;
  if (request === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: Symbol.for('fragment') };
  if (parent?.filename.startsWith(src)) {
    if (request === './api') return api;
    if (request === './Brand') return { ProviderMark() {} };
    if (parent.filename === path.join(src, 'App.tsx') &&
        ['./RunWorkspace', './ProjectReadiness', './ProjectMemory', './Recovery', './Baseline',
          './AlphaFeedback', './Verification', './Exploration', './Workflows'].includes(request)) {
      return new Proxy({}, { get: (_, key) => function Child() {} });
    }
  }
  return savedLoad.call(this, request, parent, ...rest);
};
function compile(module, filename) {
  const source = fs.readFileSync(filename, 'utf8').replaceAll('import.meta.env.MODE', JSON.stringify(mode));
  const result = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS,
      jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  });
  module._compile(result.outputText, filename);
}
require.extensions['.ts'] = compile;
require.extensions['.tsx'] = compile;
const storage = new Map();
global.location = { pathname: '/', search: '?workspace=/project&desktop_runtime=true', hash: '' };
global.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) };
global.window = { addEventListener() {}, removeEventListener() {}, setTimeout: () => 1,
  clearTimeout() {}, setInterval: () => 1, clearInterval() {} };
global.document = { activeElement: null, body: { style: {} }, documentElement: { dataset: {} },
  visibilityState: 'visible', addEventListener() {}, removeEventListener() {} };
global.__PARALLAX_VERSION__ = 'test';
function renderer(component, props) {
  return { component, props, slots: [], effects: [], index: 0, render() {
    rendering = this; this.index = 0; this.effects = []; this.tree = this.component(this.props);
    for (const effect of this.effects) effect();
    return this.tree;
  }, unmount() { for (const slot of this.slots) slot?.cleanup?.(); } };
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
function field(tree, label) {
  const match = nodes(tree).find(n => n.type === 'label' && text(n).startsWith(label));
  return nodes(match).find(n => n.type === 'input');
}
function check(label, assertion) { assertion(); passed++; console.log('PASS', label); }
async function settle(view) { for (let i = 0; i < 4; i++) { await new Promise(resolve => setImmediate(resolve)); view.render(); } }
function save(view) { nodes(view.tree).find(n => n.type === 'button' && n.props.className === 'primary-button').props.onClick(); }
const saved = { id: 'codex-api', provider: 'codex', transport: 'api', name: 'Existing API', protocol: 'responses',
  endpoint: 'https://example.invalid/v1', api_key_env: 'SYNTHETIC_OLD_API_KEY', models: [{id:'fixture',efforts:[]}],
  default_model: 'fixture', api_configured: false, status: 'credentials_missing' };
const props = { connections: [], onChanged: async () => {}, onClose() {} };
(async () => {
  const { Connections } = require(path.join(src, 'Connections.tsx'));
  const desktop = renderer(Connections, {...props, desktopRuntime:true}); desktop.render();
  check('Desktop disables environment selection and explains Keychain storage', () => {
    assert.equal(button(desktop.tree, 'Environment variable').props.disabled, true);
    assert.equal(field(desktop.tree, 'Environment variable name'), undefined);
    assert.equal(field(desktop.tree, 'API key').props.type, 'password');
    assert.match(text(desktop.tree), /does not inherit shell API keys/);
    assert.match(text(desktop.tree), /macOS Keychain/);
  });
  calls = []; save(desktop); await settle(desktop);
  check('Desktop new connection requires a Keychain API key without sending an empty request', () => {
    assert.equal(calls.length, 0);
    assert.match(text(desktop.tree), /Enter an API key to store in macOS Keychain/);
  });
  field(desktop.tree, 'API key').props.onChange({target:{value:'synthetic-new-api-key'}}); desktop.render();
  save(desktop); await settle(desktop);
  check('Desktop key save sends only the explicit key and clears the password field', () => {
    const body = JSON.parse(calls.at(-1).init.body);
    assert.equal(body.api_key, 'synthetic-new-api-key');
    assert.equal('api_key_env' in body, false);
    assert.equal(field(desktop.tree, 'API key').props.value, '');
  });
  desktop.unmount();
  const editing = renderer(Connections, {...props, connections:[saved], desktopRuntime:true}); editing.render();
  nodes(editing.tree).find(n => n.props.className === 'connection-select').props.onClick(); editing.render();
  check('Desktop legacy environment records explain replacement without claiming a stored key', () => {
    assert.equal(button(editing.tree, 'Environment variable').props.disabled, true);
    assert.match(text(editing.tree), /SYNTHETIC_OLD_API_KEY/);
    assert.match(text(editing.tree), /unavailable in the desktop app/);
    assert.match(field(editing.tree, 'API key').props.placeholder, /replace the environment reference/);
  });
  calls = []; field(editing.tree, 'Connection name').props.onChange({target:{value:'Updated metadata'}}); editing.render();
  save(editing); await settle(editing);
  check('Desktop metadata edits leave both credential fields omitted to preserve the saved reference', () => {
    const body = JSON.parse(calls.at(-1).init.body);
    assert.equal(body.name, 'Updated metadata');
    assert.equal('api_key' in body, false); assert.equal('api_key_env' in body, false);
  });
  field(editing.tree, 'API key').props.onChange({target:{value:'synthetic-replacement-key'}}); editing.render();
  save(editing); await settle(editing);
  check('Desktop replacement key does not resubmit the obsolete environment reference', () => {
    const body = JSON.parse(calls.at(-1).init.body);
    assert.equal(body.api_key, 'synthetic-replacement-key'); assert.equal('api_key_env' in body, false);
  });
  editing.unmount();
  const local = renderer(Connections, props); local.render();
  button(local.tree, 'Environment variable').props.onClick(); local.render();
  field(local.tree, 'Environment variable name').props.onChange({target:{value:'SYNTHETIC_LOCAL_API_KEY'}}); local.render();
  calls = []; save(local); await settle(local);
  check('Default plugin/local connection setup retains environment credentials', () => {
    assert.equal(button(local.tree, 'Environment variable').props.disabled, false);
    const body = JSON.parse(calls.at(-1).init.body);
    assert.equal(body.api_key_env, 'SYNTHETIC_LOCAL_API_KEY'); assert.equal('api_key' in body, false);
  });
  local.props = {...props, desktopRuntime:true}; local.render();
  calls = []; save(local); await settle(local);
  check('Late trusted desktop context overrides previously selected environment mode', () => {
    assert.equal(field(local.tree, 'Environment variable name'), undefined);
    assert.equal(calls.length, 0);
    assert.match(text(local.tree), /Enter an API key to store in macOS Keychain/);
  });
  local.unmount();
  const { default: App } = require(path.join(src, 'App.tsx'));
  for (const runtime of [true, false, undefined, 'true']) {
    responder = async p => p === '/context' ? {workspace:'/project',desktop_runtime:runtime} : [];
    const app = renderer(App, {}); app.render(); await settle(app);
    nodes(app.tree).find(n => n.type === 'button' && /Manage connections/.test(text(n))).props.onClick(); app.render();
    check('App passes only a true server boolean to Connections: ' + String(runtime), () => {
      const panel = nodes(app.tree).find(n => n.type === Connections);
      assert.equal(panel.props.desktopRuntime, runtime === true);
      assert.match(text(app.tree), /Selected for this session/);
      assert.doesNotMatch(text(app.tree), /Linked by the plugin/);
    });
    app.unmount();
  }
  mode = 'cloud'; delete require.cache[require.resolve(path.join(src, 'Connections.tsx'))];
  const HostedConnections = require(path.join(src, 'Connections.tsx')).Connections;
  const hosted = renderer(HostedConnections, props); hosted.render();
  check('Hosted defaults keep environment entry and Railway guidance', () => {
    assert.equal(button(hosted.tree, 'API key').props.disabled, true);
    assert.notEqual(button(hosted.tree, 'Environment variable').props.disabled, true);
    assert.ok(field(hosted.tree, 'Environment variable name'));
    assert.match(text(hosted.tree), /Railway runtime/);
  });
  hosted.unmount();
  const paired = renderer(HostedConnections, {...props, execution:{name:'Worker',paired:true}}); paired.render();
  check('Paired workers retain read-only credential management', () => {
    assert.equal(button(paired.tree, 'Environment variable'), undefined);
    assert.match(text(paired.tree), /Manage API connections locally/);
  });
  paired.unmount();
  console.log(`${passed} desktop connection behavior checks passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => {
  Module._load = savedLoad;
  if (savedTs) require.extensions['.ts'] = savedTs; else delete require.extensions['.ts'];
  if (savedTsx) require.extensions['.tsx'] = savedTsx; else delete require.extensions['.tsx'];
});
