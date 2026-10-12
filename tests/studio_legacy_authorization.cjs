#!/usr/bin/env node
// Actual legacy App handlers and graph controls; role transitions, no network or live actions.
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
    if (/\.css$/.test(request)) return {};
    if (request === './api') return api;
    if (request === './Brand') return { ProviderMark() {} };
    if (request === './TaskGraph') return { TaskGraph() {} };
    if (parent.filename === path.join(src, 'App.tsx') &&
        ['./RunWorkspace', './ProjectReadiness', './ProjectMemory', './Recovery', './Baseline',
          './AlphaFeedback', './Verification', './Exploration', './Workflows'].includes(request)) {
      return new Proxy({}, { get: (_, key) => { const child = function Child() {}; Object.defineProperty(child, 'name', {value:String(key)}); return child; } });
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

const listeners = new Map();
window.addEventListener = (name, listener) => { const set=listeners.get(name)||new Set(); set.add(listener); listeners.set(name,set); };
window.removeEventListener = (name, listener) => listeners.get(name)?.delete(listener);
window.matchMedia = () => ({ matches:false, addEventListener(){}, removeEventListener(){} });
global.requestAnimationFrame = () => 1;
global.EventSource = class EventSource { close() {} };
const { INITIAL_SPEC, PROVIDERS } = require(path.join(src,'types.ts'));
const catalog=PROVIDERS.map(provider=>({id:provider,provider,label:provider,status:'ready',authenticated:true,executable:'/fixture/agent',
  default_model:'fixture',models:[{id:'fixture',efforts:['high'],default_effort:'high'}]}));
const sample={run_id:'11111111-1111-4111-8111-111111111111',status:'needs_attention',tasks:[],errors:[],reviews:[],checks:[],
  changed_files:[],spec:{...structuredClone(INITIAL_SPEC),workspace:'/project',prompt:'Preserve existing behavior'},
  sessions:[],usage:{},artifacts:{},diff:''};
responder=async (p,init)=>{
  if(p==='/providers')return catalog;
  if(p==='/context')return {workspace:'/project'};
  if(p==='/profiles')return [{name:'Quality first',spec:structuredClone(INITIAL_SPEC)}];
  if(p==='/runs')return init?.method==='POST'?sample:[sample];
  if(p.startsWith('/runs/'))return sample;
  return [];
};
const writes=()=>calls.filter(c=>c.init?.method && !['GET','HEAD'].includes(c.init.method));
const child=(tree,name)=>nodes(tree).find(n=>n.type?.name===name);
const graphProps=tree=>nodes(tree).find(n=>n.props.onSteer && n.props.renderTask)?.props;
(async()=>{
  const {default:App}=require(path.join(src,'App.tsx'));
  for(const role of ['owner','developer','reviewer',undefined,'unknown']) {
    const app=renderer(App,{}); app.render(); await settle(app);
    button(app.tree,'Advanced run1').props.onClick(); app.render(); await settle(app);
    nodes(app.tree).find(n=>n.type==='textarea').props.onChange({target:{value:'Preserve behavior with an explicit check'}}); app.render();
    const start=button(app.tree,'Start team run').props.onClick;
    const save=nodes(app.tree).find(n=>n.props['aria-label']==='Save profile').props.onClick;
    const remove=nodes(app.tree).find(n=>n.props['aria-label']==='Delete saved profile').props.onClick;
    calls=[]; start(); await settle(app);
    check('Personal legacy start remains functional before '+String(role)+' transition',()=>{
      assert.equal(writes().filter(c=>c.path==='/runs' && c.init.method==='POST').length,1,text(app.tree));
    });
    const personalGraph=graphProps(app.tree); assert.ok(personalGraph);
    personalGraph.onSteering('Preserve the captured acceptance criteria'); app.render();
    const staleGraph=graphProps(app.tree);
    app.props={teamWorkspace:true,workspaceRole:role}; app.render(); await settle(app);
    calls=[]; start(); save(); remove();
    for(const action of ['pause','cancel','resume'])staleGraph.onAction(action);
    staleGraph.onSteer(); await settle(app);
    check('Captured personal handlers cannot write after transition to team '+String(role),()=>{
      assert.equal(writes().length,0);
      assert.match(text(app.tree),/Manage shared work in Tasks or Review inbox/);
    });
    button(app.tree,'Advanced run1').props.onClick(); app.render();
    check('Team '+String(role)+' advanced entry has handoff and no personal execution mounts',()=>{
      assert.equal(button(app.tree,'Start team run'),undefined);
      assert.equal(nodes(app.tree).some(n=>n.type==='input' && n.props.type==='checkbox'),false);
      for(const name of ['ProjectReadiness','ProjectMemory','Recovery','AlphaFeedback'])assert.equal(child(app.tree,name),undefined);
      assert.equal(nodes(app.tree).some(n=>n.props['aria-label']==='Save profile'),false);
      assert.ok(button(app.tree,role==='reviewer'?'Open review inbox':'Open tasks'));
    });
    button(app.tree,role==='reviewer'?'Open review inbox':'Open tasks').props.onClick(); app.render();
    check('Team '+String(role)+' handoff selects the existing task client',()=>{
      const client=nodes(app.tree).find(n=>n.props.view && n.props.knownProjects);
      assert.equal(client.props.view,role==='reviewer'?'inbox':'tasks');
      assert.equal(client.props.active,true);
    });
    button(app.tree,'Agent graph2').props.onClick(); app.render();
    check('Team '+String(role)+' graph is inspection-only without legacy recovery',()=>{
      assert.equal(graphProps(app.tree).readOnly,true); assert.equal(graphProps(app.tree).recovery,null);
    });
    button(app.tree,'Run evidence3').props.onClick(); app.render();
    check('Team '+String(role)+' evidence omits legacy feedback submission',()=>assert.equal(child(app.tree,'AlphaFeedback'),undefined));
    app.props={}; app.render(); await settle(app);
    calls=[]; start(); await settle(app);
    check('Returning from team '+String(role)+' restores personal legacy handler compatibility',()=>assert.equal(writes().filter(c=>c.path==='/runs').length,1));
    app.unmount();
  }
  const team=renderer(App,{teamWorkspace:true,workspaceRole:'reviewer'}); team.render(); await settle(team);
  for(const listener of listeners.get('keydown')||[])listener({key:'1',altKey:true,preventDefault(){}});
  team.render();
  check('Reviewer Alt+1 reaches the handoff without mounting assessment or local profiles',()=>{
    assert.ok(button(team.tree,'Open review inbox')); assert.equal(button(team.tree,'Start team run'),undefined);
    assert.equal(child(team.tree,'ProjectReadiness'),undefined); assert.equal(child(team.tree,'ProjectMemory'),undefined);
  }); team.unmount();
  const {RunWorkspace}=require(path.join(src,'RunWorkspace.tsx'));
  const props={run:sample,runs:[sample],events:[],loading:false,busy:'',streamStatus:'idle',selected:null,
    onSelect(){},onChoose(){},onOverlayChange(){},onNew(){},onReload(){},onReview(){},onAction(){},
    steering:'Guidance',onSteering(){},onSteer(){},recovery:jsx('legacy-recovery',{}),renderTask(){}};
  const readOnly=renderer(RunWorkspace,{...props,readOnly:true}); readOnly.render();
  check('Actual read-only graph hides execution controls while keeping inspection',()=>{
    for(const label of ['Steer','Resume','Pause','Stop'])assert.equal(button(readOnly.tree,label),undefined);
    assert.ok(button(readOnly.tree,'Details')); assert.ok(button(readOnly.tree,'Review ↗'));
    assert.ok(nodes(readOnly.tree).find(n=>n.props['aria-label']==='Open tasks'));
    assert.equal(nodes(readOnly.tree).some(n=>n.type==='form' && n.props.className==='work-steering'),false);
    assert.equal(nodes(readOnly.tree).some(n=>n.type==='legacy-recovery'),false);
  });readOnly.unmount();
  const legacy=renderer(RunWorkspace,props);legacy.render();
  check('Actual graph defaults preserve personal legacy execution controls',()=>{
    for(const label of ['Steer','Resume','Stop'])assert.ok(button(legacy.tree,label));
    assert.equal(nodes(legacy.tree).some(n=>n.type==='legacy-recovery'),true);
  });legacy.unmount();
  console.log(`${passed} legacy authorization UI checks passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  Module._load=savedLoad;
  if(savedTs)require.extensions['.ts']=savedTs;else delete require.extensions['.ts'];
  if(savedTsx)require.extensions['.tsx']=savedTsx;else delete require.extensions['.tsx'];
});
