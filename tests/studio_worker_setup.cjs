#!/usr/bin/env node
// Exercise setup, pairing and role handlers with controlled hooks. No network or tasks.
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
const savedNow = Date.now;
let current, calls = [], respond = async () => ({}), passed = 0, nextId = 0;
let now = 100000;
const timers = new Map();
const listeners = new Map();
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const react = {
  useState(initial) {
    const r = current, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = typeof initial === 'function' ? initial() : initial;
    return [r.slots[i], v => { r.slots[i] = typeof v === 'function' ? v(r.slots[i]) : v; }];
  },
  useRef(initial) {
    const r = current, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = {current: initial};
    return r.slots[i];
  },
  useId() {
    const r = current, i = r.index++;
    if (!(i in r.slots)) r.slots[i] = 'setup-' + ++nextId;
    return r.slots[i];
  },
  useCallback(fn,deps) {
    const r=current,i=r.index++,old=r.slots[i];
    if(!old||!same(old.deps,deps))r.slots[i]={deps,value:fn};
    return r.slots[i].value;
  },
  useEffect(effect, deps) {
    const r = current, i = r.index++, old = r.slots[i];
    if (!old || !same(old.deps, deps)) r.effects.push(() => {
      old?.cleanup?.(); r.slots[i] = {deps, cleanup: effect()};
    });
  },
};
const jsx = (type, props, key) => ({type, props: props || {}, key});
Module._load = function(request, parent, ...args) {
  if (request === 'react') return react;
  if (request === 'react/jsx-runtime') return {jsx, jsxs: jsx, Fragment: Symbol.for('fragment')};
  if (parent?.filename.startsWith(src)) {
    if (/\.css$/.test(request)) return {};
    if (request === './api') return {
      relayApi(p, init) { calls.push({path:p, init}); return respond(p, init); },
      messageOf: error => error.message || String(error),
    };
    if (request === './PublicChrome') return {Mark: () => null, ThemeToggle: () => null};
  }
  return savedLoad.call(this, request, parent, ...args);
};
function compile(module, filename) {
  const result = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop:true},
  });
  module._compile(result.outputText, filename);
}
require.extensions['.ts'] = compile;
require.extensions['.tsx'] = compile;
Date.now = () => now;
global.window = {location:{origin:'https://preview.example.invalid'}, setInterval(fn) {const id=++nextId;timers.set(id,fn);return id;},
  clearInterval(id) {timers.delete(id);}, setTimeout:()=>1};
global.location = window.location;
global.document = {activeElement:null, body:{type:'body',isConnected:true},
  addEventListener(kind,fn){if(!listeners.has(kind))listeners.set(kind,new Set());listeners.get(kind).add(fn);},
  removeEventListener(kind,fn){listeners.get(kind)?.delete(fn);}};
function focus(element){document.activeElement=element;for(const fn of listeners.get('focusin')||[])fn({target:element});}
Object.defineProperty(global,'navigator',{value:{clipboard:{writeText:async()=>{}}},configurable:true});
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
function renderer(component, props) {
  return {component, props, slots:[], effects:[], index:0, render() {
    current=this;this.index=0;this.effects=[];this.tree=this.component(this.props);
    for (const node of nodes(this.tree)) {
      if (typeof node.type !== 'string' || !node.props.ref) continue;
      const prior=typeof node.props.ref==='object'?node.props.ref.current:null;
      const element = prior || {type:node.type,isConnected:true,
        contains(candidate){return candidate?.inside===this;},
        focus(){focus(this);},querySelectorAll(){return[];}};
      element.value=node.props.value;element.text=text(node);element.ariaLabel=node.props['aria-label'];element.disabled=node.props.disabled;
      if (typeof node.props.ref === 'function') node.props.ref(element);
      else node.props.ref.current=element;
    }
    for (const effect of this.effects) effect();
    return this.tree;
  }, unmount(){
    for(const slot of this.slots)slot?.cleanup?.();
    for(const node of nodes(this.tree))if(node.props.ref){
      if(typeof node.props.ref==='function')node.props.ref(null);
      else if(node.props.ref.current){node.props.ref.current.isConnected=false;node.props.ref.current=null;}
    }
  }};
}
const button = (tree,label)=>nodes(tree).find(n=>n.type==='button'&&text(n)===label);
const radio = (tree,value)=>nodes(tree).find(n=>n.type==='input'&&n.props.value===value);
const child = (tree,type)=>nodes(tree).find(n=>n.type===type);
function select(view,value){radio(view.tree,value).props.onChange();view.render();}
function click(view,label){const b=button(view.tree,label);assert.ok(b,label+' exists');assert.notEqual(b.props.disabled,true,label+' enabled');b.props.onClick();view.render();}
function check(label,fn){fn();passed++;console.log('PASS',label);}
async function settle(view){for(let i=0;i<3;i++){await new Promise(resolve=>setImmediate(resolve));view.render();}}
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};}

(async()=>{
  const {WorkerSetupGuide}=require(path.join(src,'WorkerSetupGuide.tsx'));
  const {default:Onboarding,CopyBlock,PairingCode}=require(path.join(src,'Onboarding.tsx'));
  const {ExecutionMachines}=require(path.join(src,'ExecutionMachines.tsx'));
  const {workerCommands}=require(path.join(src,'session.ts'));
  const command=workerCommands(window.location.origin).start;
  const props={command:jsx(CopyBlock,{label:'Worker command',text:command}),pairing:jsx(PairingCode,{}),access:'Only your account can operate these machines.'};
  const guide=renderer(WorkerSetupGuide,props);guide.render();
  check('No platform inference, command or pairing on first inspection',()=>{
    assert.equal(nodes(guide.tree).filter(n=>n.type==='input'&&n.props.checked).length,0);
    assert.equal(child(guide.tree,CopyBlock),undefined);assert.equal(child(guide.tree,PairingCode),undefined);
    assert.equal(button(guide.tree,'Continue to connect').props.disabled,true);assert.equal(calls.length,0);
  });
  check('Matched preview requirement is visible before command and does not masquerade as public install',()=>{
    assert.match(text(guide.tree),/supplied preview/);assert.match(text(guide.tree),/build approved by your pilot operator/);
    assert.match(text(guide.tree),/Public source availability does not establish/);
    assert.match(text(guide.tree),/archive digest/);assert.equal(nodes(guide.tree).find(n=>n.type==='a'&&n.props.href==='/#install')!==undefined,true);
  });
  select(guide,'windows');
  check('Native Windows has no pairing path',()=>{
    assert.match(text(guide.tree),/Native Windows execution is unsupported/);
    assert.equal(button(guide.tree,'Continue to connect'),undefined);assert.equal(child(guide.tree,PairingCode),undefined);assert.equal(child(guide.tree,CopyBlock),undefined);
  });
  select(guide,'wsl2');
  check('WSL2 is guide-only and remains explicitly experimental/unverified',()=>{
    assert.match(text(guide.tree),/WSL2 is experimental/);assert.match(text(guide.tree),/remains unverified/);
    assert.equal(button(guide.tree,'Continue to connect'),undefined);assert.equal(child(guide.tree,CopyBlock),undefined);assert.equal(child(guide.tree,PairingCode),undefined);
    const link=nodes(guide.tree).find(n=>n.type==='a'&&text(n)==='Read the Windows and WSL2 guide');
    assert.match(link.props.href,/\/blob\/[a-f0-9]{40}\/docs\/WINDOWS\.md$/);
  });
  select(guide,'macos');
  check('macOS source requirements remain separate from a desktop download claim',()=>{
    assert.match(text(guide.tree),/Python 3\.10/);assert.match(text(guide.tree),/Git 2\.38/);assert.match(text(guide.tree),/two usable independent providers/);
    assert.match(text(guide.tree),/does not establish remaining quota/);assert.match(text(guide.tree),/Native Grok is unavailable/);
    assert.doesNotMatch(text(guide.tree),/Download.*DMG|signed.*notarized|macOS 15/);
  });
  const focusBefore=document.activeElement;
  click(guide,'Continue to connect');
  check('Continue opens the exact current command and focuses its new heading without requests',()=>{
    assert.equal(child(guide.tree,CopyBlock).props.text,command);assert.ok(child(guide.tree,PairingCode));
    assert.equal(document.activeElement.type,'h2');assert.equal(document.activeElement.text,'Connect it');assert.notEqual(document.activeElement,focusBefore);
    assert.equal(calls.length,0);
  });
  check('Process lifetime, editable machine label and mirrored-source boundary precede pairing',()=>{
    const copy=text(guide.tree);assert.match(copy,/Keep this terminal running and the machine awake/);
    assert.match(copy,/Replace \/absolute\/path\/to\/project with its path/);assert.match(copy,/"My Mac" with your machine's label/);assert.match(copy,/keep the --workspace and --name flags/);
    assert.match(copy,/Provider credentials, private checkouts and complete session files stay on the machine/);
    assert.match(copy,/Task prompts and mirrored results may contain source code/);
    const list=nodes(guide.tree);const pairIndex=list.findIndex(n=>n.type===PairingCode);
    assert.ok(list.findIndex(n=>n.type==='p'&&text(n).includes('mirrored results'))<pairIndex);
    assert.ok(list.findIndex(n=>n.type==='p'&&text(n).includes('terminal running'))<pairIndex);
    assert.equal(list.some(n=>n.type==='input'&&n.props.type==='password'),false);
  });
  click(guide,'Back to preparation');
  check('Back restores the selected platform control focus and removes pairing',()=>{
    assert.equal(document.activeElement.type,'input');assert.equal(document.activeElement.value,'macos');
    assert.equal(radio(guide.tree,'macos').props.checked,true);assert.equal(child(guide.tree,PairingCode),undefined);
  });
  select(guide,'linux');
  check('Linux requirements retain namespace and live acceptance scope',()=>{
    assert.match(text(guide.tree),/bubblewrap and user namespaces/);assert.match(text(guide.tree),/separate live acceptance gate/);
  });
  click(guide,'Continue to connect');click(guide,'Back to preparation');select(guide,'wsl2');
  check('Changing to an experimental platform cannot retain the previous supported pairing stage',()=>{
    assert.equal(child(guide.tree,PairingCode),undefined);assert.equal(child(guide.tree,CopyBlock),undefined);assert.equal(calls.length,0);
  });
  const reviewer=renderer(Onboarding,{workspaceName:'Team',machines:[],loading:false,account:null,onOpen(){},canManageMachines:false});reviewer.render();
  check('Reviewer/Developer handoff contains no setup or pairing even without a machine',()=>{
    assert.match(text(reviewer.tree),/Ask a workspace owner/);assert.equal(child(reviewer.tree,WorkerSetupGuide),undefined);assert.equal(child(reviewer.tree,PairingCode),undefined);
  });
  const owner=renderer(Onboarding,{...reviewer.props,canManageMachines:true});owner.render();
  check('Owner/personal onboarding routes into the real shared guide with unchanged command',()=>{
    const setup=child(owner.tree,WorkerSetupGuide);assert.ok(setup);assert.equal(setup.props.command.type,CopyBlock);assert.equal(setup.props.command.props.text,command);
  });
  let opened='';const machine={id:'paired-one',name:'Project machine',platform:'darwin',online:true,workspaces:['/project']};
  const setupWrapper=nodes(owner.tree).find(n=>n.type==='div'&&n.props.ref&&child(n,WorkerSetupGuide));
  const focusedRegion={contains:target=>target?.insideSetup===true};setupWrapper.props.ref(focusedRegion);document.activeElement={insideSetup:true};setupWrapper.props.ref(null);
  owner.props={...owner.props,machines:[machine],onOpen:id=>{opened=id;}};owner.render();
  check('Connection discovery transfers focus from removed setup to the real Open Studio action',()=>{
    assert.equal(document.activeElement.type,'button');assert.equal(document.activeElement.text,'Open Studio');
  });
  check('A real connected machine bypasses setup and retains explicit Open Studio',()=>{
    assert.equal(child(owner.tree,WorkerSetupGuide),undefined);assert.match(text(owner.tree),/authorized project/);assert.match(text(owner.tree),/does not establish provider quota/);
    click(owner,'Open Studio');assert.equal(opened,machine.id);
  });
  reviewer.props={...reviewer.props,machines:[machine]};reviewer.render();
  check('A connected Reviewer gets permitted tasks/reviews rather than instructions to start work',()=>{
    assert.equal(child(reviewer.tree,WorkerSetupGuide),undefined);assert.match(text(reviewer.tree),/permitted tasks and reviews/);assert.doesNotMatch(text(reviewer.tree),/then start a task/);
  });
  owner.props={...owner.props,machines:[{...machine,online:false}]};owner.render();
  check('Existing offline machine is not forced through a fresh pairing',()=>{
    assert.equal(child(owner.tree,WorkerSetupGuide),undefined);assert.match(text(owner.tree),/existing worker state/);assert.ok(button(owner.tree,'Open Studio'));
  });
  const outside=renderer(Onboarding,{...owner.props,machines:[]});outside.render();
  const outsideWrapper=nodes(outside.tree).find(n=>n.type==='div'&&n.props.ref&&child(n,WorkerSetupGuide));
  outsideWrapper.props.ref(focusedRegion);const accountFocus={type:'account-link',isConnected:true,focus(){focus(this);}};document.activeElement=accountFocus;outsideWrapper.props.ref(null);
  outside.props={...outside.props,machines:[machine]};outside.render();
  check('Connection discovery does not steal focus from account/navigation outside setup',()=>{assert.equal(document.activeElement,accountFocus);});
  check('Connected and non-manager users retain concise local/relay/provider disclosure without setup repetition',()=>{
    assert.match(text(outside.tree),/workspace receives task evidence that can contain source code/);assert.match(text(outside.tree),/Chosen model providers receive relevant project context/);
    assert.equal(child(outside.tree,WorkerSetupGuide),undefined);
  });
  let refreshes=0;const dialog=renderer(ExecutionMachines,{machines:[{...machine,online:false}],selected:machine.id,onSelect(){},refresh:async()=>{refreshes++;},hostedExecution:false,teamWorkspace:true,canManageMachines:false,reconnectSignal:1});dialog.render();dialog.render();
  check('Non-owner machine dialog preserves original-state reconnect and no management controls',()=>{
    assert.match(text(dialog.tree),/original state directory, relay URL and approved project paths/);assert.match(text(dialog.tree),/Ask a workspace owner to restart/);
    assert.equal(child(dialog.tree,WorkerSetupGuide),undefined);assert.equal(button(dialog.tree,'Disconnect'),undefined);
  });
  click(dialog,'Check machine connection');await settle(dialog);
  check('Existing reconnect handler still refreshes without generating a code',()=>{assert.equal(refreshes,1);assert.equal(calls.length,0);});
  dialog.props={...dialog.props,canManageMachines:true};dialog.render();
  check('Manager new-machine section reuses the guide without replacing offline recovery',()=>{
    const setup=child(dialog.tree,WorkerSetupGuide);assert.ok(setup);assert.equal(setup.props.headingLevel,3);assert.equal(setup.props.command.props.text,command);
    assert.match(setup.props.access,/role and project permissions/);assert.ok(button(dialog.tree,'Check machine connection'));
  });
  const offlineRegion=nodes(dialog.tree).find(n=>n.type==='section'&&n.props.ref&&button(n,'Check machine connection'));
  const focusedOffline={contains:target=>target?.insideReconnect===true};offlineRegion.props.ref(focusedOffline);document.activeElement={insideReconnect:true};offlineRegion.props.ref(null);
  document.activeElement=document.body;dialog.props={...dialog.props,machines:[machine]};dialog.render();
  check('Reconnection removal transfers lost offline-control focus to stable modal Close',()=>{
    assert.equal(document.activeElement.ariaLabel,'Close machines');assert.equal(button(dialog.tree,'Check machine connection'),undefined);
  });
  dialog.props={...dialog.props,machines:[{...machine,online:false}]};dialog.render();
  const quietOffline=nodes(dialog.tree).find(n=>n.type==='section'&&n.props.ref&&button(n,'Check machine connection'));
  quietOffline.props.ref(focusedOffline);accountFocus.focus();quietOffline.props.ref(null);dialog.props={...dialog.props,machines:[machine]};dialog.render();
  check('Reconnection does not hijack account/navigation focus outside removed controls',()=>{assert.equal(document.activeElement,accountFocus);});
  const pair=renderer(PairingCode,{});pair.render();respond=async()=>({code:'SYNTHETIC-CODE',expires_in:300});
  button(pair.tree,'Generate pairing code').props.onClick();await settle(pair);
  check('Pairing retains the existing sole mutation and server expiry',()=>{
    assert.deepEqual(calls,[{path:'/executors/pair',init:{method:'POST'}}]);assert.match(text(pair.tree),/SYNTHETIC-CODE/);assert.match(text(pair.tree),/Expires in 5:00/);
  });
  now+=301000;for(const tick of timers.values())tick();pair.render();
  check('An expired code is removed and offers an explicit fresh-code action',()=>{
    assert.doesNotMatch(text(pair.tree),/SYNTHETIC-CODE/);assert.match(text(pair.tree),/code expired/);assert.ok(button(pair.tree,'Generate a new code'));
  });
  respond=async()=>{throw new Error('Pairing temporarily unavailable');};button(pair.tree,'Generate a new code').props.onClick();await settle(pair);
  check('Pairing failure remains inspectable and is not a connection/readiness success',()=>{
    assert.match(text(pair.tree),/Pairing temporarily unavailable/);assert.ok(nodes(pair.tree).find(n=>n.props.role==='alert'));assert.doesNotMatch(text(pair.tree),/Connected|Ready to start/);
  });
  const focusedPair=renderer(PairingCode,{});focusedPair.render();let pending=deferred();respond=()=>pending.promise;
  const focusedTrigger=button(focusedPair.tree,'Generate pairing code');focusedTrigger.props.ref.current.focus();const priorCalls=calls.length;
  focusedTrigger.props.onClick();focusedPair.render();
  check('Pending pairing keeps its keyboard control focusable and guards duplicate requests',()=>{
    const trigger=button(focusedPair.tree,'Generating…');assert.equal(trigger.props['aria-disabled'],true);assert.notEqual(trigger.props.disabled,true);
    assert.equal(document.activeElement,trigger.props.ref.current);trigger.props.onClick();assert.equal(calls.length,priorCalls+1);
  });
  document.activeElement=document.body;pending.reject(new Error('Guarded 403 pairing denied'));await settle(focusedPair);
  check('Guarded failed pairing restores a lost focused trigger and preserves the failure',()=>{
    assert.equal(document.activeElement,button(focusedPair.tree,'Generate pairing code').props.ref.current);assert.match(text(focusedPair.tree),/Guarded 403 pairing denied/);
  });
  pending=deferred();respond=()=>pending.promise;button(focusedPair.tree,'Generate pairing code').props.onClick();focusedPair.render();
  pending.resolve({code:'SYNTHETIC-FOCUS-CODE',expires_in:300});await settle(focusedPair);
  check('Successful pairing keeps the focused trigger without focusing the secret code',()=>{
    assert.equal(document.activeElement,button(focusedPair.tree,'Generate a new code').props.ref.current);assert.match(text(focusedPair.tree),/SYNTHETIC-FOCUS-CODE/);
  });
  pending=deferred();respond=()=>pending.promise;button(focusedPair.tree,'Generate a new code').props.onClick();focusedPair.render();
  accountFocus.focus();document.activeElement=document.body;pending.reject(new Error('Synthetic second denial'));await settle(focusedPair);
  check('Pairing completion never reclaims focus after the user focused elsewhere',()=>{assert.equal(document.activeElement,document.body);});
  const removedPair=renderer(PairingCode,{});removedPair.render();pending=deferred();respond=()=>pending.promise;
  button(removedPair.tree,'Generate pairing code').props.ref.current.focus();button(removedPair.tree,'Generate pairing code').props.onClick();removedPair.render();removedPair.unmount();accountFocus.focus();
  pending.resolve({code:'SYNTHETIC-REMOVED-CODE',expires_in:300});await new Promise(resolve=>setImmediate(resolve));
  check('A pending pairing resolved after unmount cannot restore a removed control',()=>{assert.equal(document.activeElement,accountFocus);});
  let copied='';navigator.clipboard.writeText=async value=>{copied=value;};const copy=renderer(CopyBlock,{label:'Worker command',text:command});copy.render();await button(copy.tree,'Copy').props.onClick();copy.render();
  check('Command copy remains literal and unchanged',()=>{assert.equal(copied,command);assert.ok(button(copy.tree,'Copied'));});
  navigator.clipboard.writeText=async()=>{throw new Error('Clipboard denied');};await button(copy.tree,'Copied').props.onClick();copy.render();
  check('Copy failure retains selectable text and retry',()=>{assert.ok(button(copy.tree,'Retry copy'));assert.match(text(copy.tree),/Copy failed\. Select the text instead/);assert.match(text(copy.tree),/--workspace \/absolute\/path\/to\/project/);});
  [guide,owner,reviewer,outside,dialog,pair,focusedPair,copy].forEach(v=>v.unmount());
  console.log(`${passed} worker setup checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
  Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;Date.now=savedNow;
});
