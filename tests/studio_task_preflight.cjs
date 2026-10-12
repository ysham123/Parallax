#!/usr/bin/env node
// Actual preflight rendering/adoption; no browser, network, project commands or agents.
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
let ids = 0, requests = 0, passed = 0;
const jsx = (type, props, key) => ({type, props:props || {}, key});
Module._load = function(request, parent, ...args) {
  if (request === 'react') return {useId:()=>`preflight-${++ids}`};
  if (request === 'react/jsx-runtime') return {jsx, jsxs:jsx};
  if (parent?.filename.startsWith(src)) {
    if (/\.css$/.test(request)) return {};
    if (request === './WorkIcon') return {WorkIcon:()=>null};
    if (request === './api') return new Proxy({}, {get:()=>()=>{requests++;throw new Error('Unexpected preflight request');}});
  }
  return savedLoad.call(this, request, parent, ...args);
};
function compile(module, filename) {
  const result=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});
  module._compile(result.outputText,filename);
}
require.extensions['.ts']=compile;require.extensions['.tsx']=compile;
function nodes(tree) {
  if(!tree||typeof tree!=='object')return[];
  if(Array.isArray(tree))return tree.flatMap(nodes);
  return[tree,...nodes(tree.props?.children)];
}
function text(tree) {
  if(Array.isArray(tree))return tree.map(text).join('');
  if(tree&&typeof tree==='object')return text(tree.props?.children);
  return tree==null||tree===false?'':String(tree);
}
function ancestors(tree,target,parents=[]) {
  if(tree===target)return parents;
  if(!tree||typeof tree!=='object')return null;
  for(const child of Array.isArray(tree)?tree:[tree.props?.children]) {
    const result=ancestors(child,target,Array.isArray(tree)?parents:[...parents,tree]);
    if(result)return result;
  }
  return null;
}
function byClass(tree,name){return nodes(tree).find(n=>n.props.className?.split(' ').includes(name));}
function button(tree,label){return nodes(tree).find(n=>n.type==='button'&&text(n)===label);}
function check(label,fn){fn();passed++;console.log('PASS',label);}
try {
  const {TaskPreflight}=require(path.join(src,'TaskPreflight.tsx'));
  const detected=[{name:'Compatibility tests',argv:['python3','-m','unittest','discover','-s','tests'],timeout:90,cwd:'legacy module'},
    {name:'Quoted argument',argv:['node','-e',`console.log("O'Reilly")`,'--label','multi word'],timeout:45,cwd:'.'}];
  const base={status:'ready',git:true,execution:{enforced:true,backend:'seatbelt'},packages:[{root:'.',kind:'python',setup:'private Python venv',manager:'pip'}],instructions:['AGENTS.md'],proposed_checks:detected,issues:[],assessed_at:'2026-10-11T20:01:00.000Z'};
  let adopted=null;const props={assessment:base,configuredChecks:[],onUseChecks:value=>{adopted=value;},disabled:false};
  const view=TaskPreflight(props);
  check('Positive setup report is scoped inspection rather than execution readiness',()=>{
    assert.equal(text(byClass(view,'preflight-status')),'Setup inspected');assert.doesNotMatch(text(view),/Ready to start|checks passed|inference passed/);
    assert.match(text(byClass(view,'preflight-scope')),/does not run project checks or model inference/);assert.match(text(view),/does not verify provider quota/);
  });
  check('Check source/count stay visible while exact commands remain inspectable',()=>{
    const summary=byClass(view,'preflight-check-summary');assert.match(text(summary),/2 detected checks proposed/);assert.match(text(summary),/Not run by this inspection/);
    assert.equal(ancestors(view,summary).some(n=>n.type==='details'),false);
    const detail=byClass(view,'preflight-command-details');assert.equal(detail.type,'details');assert.equal(detail.props.open,undefined);
    assert.match(text(detail),/python3 -m unittest discover -s tests/);assert.match(text(detail),/90s limit/);assert.match(text(detail),/Working directory: legacy module/);
  });
  check('Detected adoption is available without opening command details',()=>{
    const action=button(view,'Use detected checks');assert.ok(action);assert.equal(ancestors(view,action).some(n=>n.type==='details'),false);
    assert.ok(action.props['aria-describedby']);assert.match(text(view),/saved recipe stays unchanged/);
  });
  button(view,'Use detected checks').props.onClick();
  check('Adoption copies exact argv/cwd/timeouts rather than display strings',()=>{
    assert.deepEqual(adopted,detected);assert.notEqual(adopted,detected);assert.notEqual(adopted[0].argv,detected[0].argv);
    adopted[0].argv.push('LOCAL-EDIT');assert.equal(detected[0].argv.includes('LOCAL-EDIT'),false);
    assert.match(text(byClass(view,'preflight-command-details')),/'multi word'/);
  });
  const configured=[{name:'Explicit regression',argv:['npm','run','regression','--','--seed','99'],cwd:'web',timeout:123}];
  const explicit=TaskPreflight({...props,configuredChecks:configured});
  check('Nonempty configured checks override proposals and expose their true plan',()=>{
    assert.match(text(byClass(explicit,'preflight-check-summary')),/1 configured check for this task/);
    assert.match(text(byClass(explicit,'preflight-command-details')),/Explicit regression/);assert.match(text(explicit),/123s limit/);assert.match(text(explicit),/Working directory: web/);
    assert.doesNotMatch(text(explicit),/Compatibility tests/);assert.equal(button(explicit,'Use detected checks'),undefined);
  });
  check('An explicit empty configured list retains detected-check semantics',()=>{
    const empty=TaskPreflight({...props,configuredChecks:[]});assert.match(text(byClass(empty,'preflight-check-summary')),/2 detected checks proposed/);assert.ok(button(empty,'Use detected checks'));
  });
  adopted=null;const disabled=TaskPreflight({...props,disabled:true});button(disabled,'Use detected checks').props.onClick();
  check('Disabled adoption cannot overwrite task settings even through a direct handler call',()=>{
    assert.equal(button(disabled,'Use detected checks').props.disabled,true);assert.equal(adopted,null);
  });
  const warnings=[{severity:'warning',provider:'codex',category:'configuration',message:'API execution is experimental.'},
    {severity:'warning',root:'packages/core',message:'Discovery stopped at its directory bound.'}];
  const warned=TaskPreflight({...props,assessment:{...base,issues:warnings}});
  check('Every warning stays visible under a scoped positive report',()=>{
    assert.equal(text(byClass(warned,'preflight-status')),'Setup inspected');const list=byClass(warned,'preflight-issues');assert.equal(nodes(list).filter(n=>n.type==='li').length,2);
    assert.equal(ancestors(warned,list).some(n=>n.type==='details'),false);assert.match(text(list),/Provider: codex/);assert.match(text(list),/packages\/core/);
    for(const warning of warnings)assert.ok(text(list).includes(warning.message));
  });
  const blocked=TaskPreflight({...props,assessment:{...base,issues:[{severity:'blocker',message:'Independent provider unavailable.'},...warnings]}});
  check('A blocker dominates contradictory ready status without hiding warnings',()=>{
    assert.equal(text(byClass(blocked,'preflight-status')),'Setup needs attention');assert.equal(nodes(byClass(blocked,'preflight-issues')).filter(n=>n.type==='li').length,3);
    assert.match(text(blocked),/Independent provider unavailable/);assert.match(text(blocked),/API execution is experimental/);
  });
  const parentIssues=TaskPreflight({...props,showIssues:false,assessment:{...base,issues:[{severity:'blocker',message:'Independent provider unavailable.'},...warnings]}});
  check('Composer-owned issues do not duplicate the list or weaken the scoped report status',()=>{
    assert.equal(byClass(parentIssues,'preflight-issues'),undefined);assert.doesNotMatch(text(parentIssues),/Independent provider unavailable|API execution is experimental/);
    assert.equal(text(byClass(parentIssues,'preflight-status')),'Setup needs attention');assert.match(text(parentIssues),/does not verify provider quota/);
  });
  const legacy=TaskPreflight({...props,assessment:{status:'ready'}});
  check('Missing legacy evidence stays unreported rather than empty or successful',()=>{
    assert.match(text(legacy),/Setup issues were not reported/);assert.match(text(legacy),/Check discovery not reported/);assert.match(text(legacy),/did not report detected checks/);
    assert.match(text(legacy),/did not report package discovery/);assert.match(text(legacy),/did not report instruction files/);assert.match(text(legacy),/Inspection time not reported/);
    assert.equal(text(byClass(legacy,'preflight-facts')).match(/Not reported/g).length,2);assert.doesNotMatch(text(legacy),/No checks detected|No setup issues reported|No supported packages detected/);
  });
  const unknown=TaskPreflight({...props,assessment:{}});
  check('Missing inspection status remains unknown',()=>{assert.equal(text(byClass(unknown,'preflight-status')),'Inspection status unknown');});
  const noChecks=TaskPreflight({...props,assessment:{...base,proposed_checks:[]}});
  check('Recorded empty detection directs explicit commands without fabricating a plan',()=>{
    assert.match(text(noChecks),/No checks detected/);assert.match(text(noChecks),/Add explicit check commands in task settings/);assert.equal(button(noChecks,'Use detected checks'),undefined);
    assert.equal(byClass(noChecks,'preflight-command-details'),undefined);
  });
  const incompleteBlocked=TaskPreflight({...props,assessment:{status:'blocked',issues:[]}});
  check('Blocked status with absent issue details does not report no setup problems',()=>{
    assert.match(text(incompleteBlocked),/needs setup attention but did not provide issue details/);assert.doesNotMatch(text(incompleteBlocked),/No setup issues reported/);
  });
  const unsafe=`<img src=x onerror=alert('fixture')>`;
  const untrusted=TaskPreflight({...props,assessment:{...base,issues:[{severity:'warning',message:unsafe,provider:unsafe,root:unsafe}],instructions:[unsafe],proposed_checks:[{name:unsafe,argv:['node','-e',unsafe],timeout:44,cwd:'.'}]}});
  check('Untrusted issues, paths, names and commands remain text without HTML injection',()=>{
    assert.ok(text(untrusted).includes(unsafe));assert.equal(nodes(untrusted).some(n=>n.props.dangerouslySetInnerHTML),false);assert.equal(nodes(untrusted).some(n=>n.type==='img'),false);
  });
  const invalidTime=TaskPreflight({...props,assessment:{...base,assessed_at:'not-a-date'}});
  check('Invalid timestamps are unavailable instead of an invented inspection time',()=>{
    assert.match(text(invalidTime),/Inspection time not reported/);assert.equal(nodes(invalidTime).filter(n=>n.type==='time').length,0);assert.doesNotMatch(text(invalidTime),/Invalid Date/);
    assert.equal(nodes(view).find(n=>n.type==='time').props.dateTime,base.assessed_at);
  });
  check('Inspection rendering and check adoption never invoke an API or inference',()=>{assert.equal(requests,0);});
  console.log(`${passed} task preflight checks passed`);
} catch(error){console.error(error);process.exitCode=1;}
finally{Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;}
