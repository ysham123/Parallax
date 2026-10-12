#!/usr/bin/env node
// Actual task placement and measurement handlers with controlled hooks, no network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),Module=require('node:module');
const {webcrypto}=require('node:crypto');
const root=path.resolve(__dirname,'..'),src=path.join(root,'studio/src'),ts=require(path.join(root,'studio/node_modules/typescript'));
const savedLoad=Module._load,savedTs=require.extensions['.ts'],savedTsx=require.extensions['.tsx'];
let current,calls=[],respond=async()=>({}),passed=0;
const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
const react={
  useState(initial){const r=current,i=r.index++;if(!(i in r.slots))r.slots[i]=typeof initial==='function'?initial():initial;return[r.slots[i],v=>{r.slots[i]=typeof v==='function'?v(r.slots[i]):v;}];},
  useRef(initial){const r=current,i=r.index++;if(!(i in r.slots))r.slots[i]={current:initial};return r.slots[i];},
  useEffect(effect,deps){const r=current,i=r.index++,old=r.slots[i];if(!old||!same(old.deps,deps))r.effects.push(()=>{old?.cleanup?.();r.slots[i]={deps,cleanup:effect()};});},
  useMemo(fn,deps){const r=current,i=r.index++,old=r.slots[i];if(!old||!same(old.deps,deps))r.slots[i]={deps,value:fn()};return r.slots[i].value;},
  useCallback(fn,deps){return react.useMemo(()=>fn,deps);},
};
const jsx=(type,props,key)=>({type,props:props||{},key});
Module._load=function(request,parent,...args){
  if(request==='react')return react;
  if(request==='react/jsx-runtime')return{jsx,jsxs:jsx,Fragment:Symbol.for('fragment')};
  if(parent?.filename.startsWith(src)){
    if(/\.css$/.test(request))return{};
    if(request==='./api')return{api(p,init){calls.push({path:p,init});return respond(p,init);},apiUrl:p=>'/api'+p,viaMachine:()=>false,messageOf:e=>e.message||String(e)};
    if(request==='./WorkIcon')return{WorkIcon:()=>null};
    if(request==='./Brand')return{ProviderMark:()=>null};
    if(request==='./RunWorkspace')return{eventSummary:()=>''};
  }
  return savedLoad.call(this,request,parent,...args);
};
function compile(module,filename){const result=ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});module._compile(result.outputText,filename);}
require.extensions['.ts']=compile;require.extensions['.tsx']=compile;
global.crypto=webcrypto;global.location={pathname:'/',search:'',hash:''};
global.window={addEventListener(){},removeEventListener(){},setTimeout:()=>1,clearTimeout(){},setInterval:()=>1,clearInterval(){}};
global.localStorage={getItem:()=>null,setItem(){}};global.document={getElementById:()=>null,activeElement:null,addEventListener(){},removeEventListener(){}};
global.requestAnimationFrame=()=>1;global.cancelAnimationFrame=()=>{};global.EventSource=class{close(){}};
function renderer(component,props){return{component,props,slots:[],effects:[],index:0,render(){current=this;this.index=0;this.effects=[];this.tree=this.component(this.props);for(const effect of this.effects)effect();return this.tree;},unmount(){for(const slot of this.slots)slot?.cleanup?.();}};}
function nodes(tree){if(!tree||typeof tree!=='object')return[];if(Array.isArray(tree))return tree.flatMap(nodes);return[tree,...nodes(tree.props?.children)];}
function text(tree){if(Array.isArray(tree))return tree.map(text).join('');if(tree&&typeof tree==='object')return text(tree.props?.children);return tree==null||tree===false?'':String(tree);}
function byClass(tree,name){return nodes(tree).find(n=>n.props.className?.split(' ').includes(name));}
function child(tree,type){return nodes(tree).find(n=>n.type===type);}
function form(tree,label){return nodes(tree).find(n=>n.type==='form'&&n.props['aria-label']===label);}
function field(tree,label){const n=nodes(tree).find(n=>n.type==='label'&&text(n.props.children[0])===label);return nodes(n).find(v=>['input','select','textarea'].includes(v.type));}
function submit(tree,label){form(tree,label).props.onSubmit({preventDefault(){}});}
async function settle(view){for(let i=0;i<4;i++){await new Promise(resolve=>setImmediate(resolve));view.render();}}
function check(label,fn){fn();passed++;console.log('PASS',label);}
const workflow={id:'11111111-1111-4111-8111-111111111111',title:'Preserve refund behavior',workspace:'/project',status:'needs_attention',schema_version:'2.0',requester:'developer',created_at:'2026-10-11T20:00:00Z',updated_at:'2026-10-11T20:00:00Z',template:{id:'verified-change',version:1,name:'Verified change'},spec:{workspace:'/project',coordinator:{provider:'codex',role:'coordinator'},team:[{provider:'claude',role:'implementer'}],checks:[],limits:{minutes:7,workers:3,repairs:2}}};
const phase='66666666-6666-4666-8666-666666666666',observation={id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',content_sha256:'a'.repeat(64),phase_attempt_id:phase,phase:'final',provenance:{scheme:'readonly-workspace-state-v1',before_sha256:'b'.repeat(64),after_sha256:'b'.repeat(64),unchanged:true}};
const report={evidence_observations:[{workflow_id:workflow.id,kind:'review',provider:'claude',phase:'final',outcome:'failed',observation,findings:[{index:3,title:'Refund defect',summary:'Compare refund settlement.'}]}]};
const taskProps={visible:true,workflow,feedback:'',sending:false,sent:'',onSend(){},followups:[],onRelated(){},onFeedback(){},ready:false,busy:'',online:true,onAction(){},onAgain(){},onRevise(){},canDeliver:true,members:[],onAssign(){},onRefresh(){},onComment(){},onInspect(){},renderEvidence:()=>jsx('saved-details',{})};
(async()=>{
  const {TaskWorkspace}=require(path.join(src,'TaskWorkspace.tsx'));
  const {PilotMetrics}=require(path.join(src,'PilotMetrics.tsx'));
  let attempts=0;
  respond=async(p,init)=>{
    if(p==='/context')return{pilot_features:['pilot-evaluation-v1','pilot-observations-v1']};
    if(p==='/pilot/report')return report;
    if(p==='/pilot/benchmark'){if(++attempts===1)throw new Error('Synthetic timeout');return{comparability:{baseline:'unverified'}};}
    if(p==='/pilot/observations')return{};
    if(p.startsWith('/runs/'))return{run_id:workflow.run_id,status:'failed',spec:workflow.spec,checks:[],reviews:[],errors:[],artifacts:{},metrics:{}};
    throw new Error('Unexpected request '+p);
  };
  const slot=jsx(PilotMetrics,{workflow,allowMeasure:true,allowLabel:true},'task-metrics');
  const task=renderer(TaskWorkspace,{...taskProps,measurements:slot});task.render();await settle(task);
  check('Ordinary task canvas has no mounted measurement component or measurement-only reads',()=>{
    assert.equal(child(task.tree,PilotMetrics),undefined);assert.equal(calls.some(c=>['/context','/pilot/report'].includes(c.path)),false);
    assert.equal(byClass(task.tree,'task-details-pane').props.hidden,true);
  });
  const setTab=id=>{nodes(task.tree).find(n=>n.props.id==='evidence-tab-'+id).props.onClick();task.render();};
  setTab('settings');
  check('Existing Details tab exposes task-named disclosure without loading instrumentation',()=>{
    assert.equal(byClass(task.tree,'task-details-pane').props.hidden,false);const disclosure=byClass(task.tree,'task-measurements');
    assert.match(text(disclosure),/Preserve refund behavior/);assert.equal(child(task.tree,PilotMetrics),undefined);assert.equal(calls.length,0);
  });
  byClass(task.tree,'task-measurements').props.onToggle({currentTarget:{open:true}});task.render();
  check('First explicit disclosure open mounts the exact supplied task slot even with no run ID',()=>{
    assert.equal(child(task.tree,PilotMetrics),slot);assert.match(text(task.tree),/Waiting for run details/);
  });
  const metrics=renderer(PilotMetrics,slot.props);metrics.render();await settle(metrics);
  check('A no-run task retains manual blocked-attempt measurement access',()=>{
    assert.ok(form(metrics.tree,'Participant-reported comparison'));assert.match(text(metrics.tree),/Blank fields mean unknown/);
    assert.equal(calls.some(c=>c.path.startsWith('/runs/')),false);
  });
  field(metrics.tree,'Elapsed attempt time, seconds').props.onChange({target:{value:'120'}});
  field(metrics.tree,'Total active developer time, seconds').props.onChange({target:{value:'60'}});
  field(metrics.tree,'Setup time within that total, seconds').props.onChange({target:{value:'10'}});
  field(metrics.tree,'Human review time within that total, seconds').props.onChange({target:{value:'15'}});metrics.render();
  submit(metrics.tree,'Participant-reported comparison');await settle(metrics);
  const first=JSON.parse(calls.find(c=>c.path==='/pilot/benchmark').init.body),reads=calls.filter(c=>!c.init?.method).length;
  setTab('changes');
  check('Switching away hides a retained measurement slot rather than unmounting it',()=>{
    assert.equal(byClass(task.tree,'task-details-pane').props.hidden,true);assert.equal(child(task.tree,PilotMetrics),slot);
  });
  byClass(task.tree,'task-measurements').props.onToggle({currentTarget:{open:false}});task.render();setTab('settings');
  byClass(task.tree,'task-measurements').props.onToggle({currentTarget:{open:true}});task.render();metrics.render();
  check('Collapse/tab/reopen preserves manual values without new capability/report reads',()=>{
    assert.equal(field(metrics.tree,'Elapsed attempt time, seconds').props.value,'120');assert.equal(field(metrics.tree,'Total active developer time, seconds').props.value,'60');
    assert.equal(calls.filter(c=>!c.init?.method).length,reads);assert.equal(child(task.tree,PilotMetrics),slot);
  });
  submit(metrics.tree,'Participant-reported comparison');await settle(metrics);
  check('Timed-out comparison retries retain request identity and all nullable measurement semantics',()=>{
    const second=JSON.parse(calls.filter(c=>c.path==='/pilot/benchmark')[1].init.body);assert.equal(second.request_id,first.request_id);assert.equal(second.duration_seconds,120);
    assert.equal(second.evaluation.active_human_seconds,60);assert.equal(second.evaluation.setup_seconds,10);assert.equal(second.evaluation.review_seconds,15);assert.equal(second.provider_cost_usd,null);
    assert.equal(second.evaluation.outcome,'blocked');assert.equal(second.accepted,false);assert.equal('actor' in second,false);
  });
  const capturedMeasure=form(metrics.tree,'Participant-reported comparison').props.onSubmit;
  metrics.props={...metrics.props,allowMeasure:false,allowLabel:true};metrics.render();let writes=calls.filter(c=>c.init?.method==='POST').length;
  capturedMeasure({preventDefault(){}});await settle(metrics);
  check('Reviewer/current-access downgrade hides comparisons and guards a captured allowed handler',()=>{
    assert.equal(form(metrics.tree,'Participant-reported comparison'),undefined);assert.ok(form(metrics.tree,'Human observation assessment'));
    assert.equal(calls.filter(c=>c.init?.method==='POST').length,writes);assert.doesNotMatch(text(metrics.tree),/Update the pilot worker/);
  });
  field(metrics.tree,'Observation').props.onChange({target:{value:observation.id}});metrics.render();field(metrics.tree,'Finding to assess').props.onChange({target:{value:'3'}});metrics.render();
  submit(metrics.tree,'Human observation assessment');await settle(metrics);
  check('Permitted labels retain immutable observation hash and original persisted finding index',()=>{
    const body=JSON.parse(calls.find(c=>c.path==='/pilot/observations').init.body);assert.equal(body.workflow_id,workflow.id);assert.equal(body.observation_id,observation.id);assert.equal(body.content_sha256,observation.content_sha256);
    assert.equal(body.finding_index,3);assert.equal(body.classification,'unresolved');assert.equal('actor' in body,false);assert.equal('accepted' in body,false);
  });
  const capturedLabel=form(metrics.tree,'Human observation assessment').props.onSubmit;metrics.props={...metrics.props,allowLabel:false};metrics.render();writes=calls.filter(c=>c.init?.method==='POST').length;
  capturedLabel({preventDefault(){}});await settle(metrics);
  check('Missing/revoked label permission prevents captured handler writes',()=>{assert.equal(form(metrics.tree,'Human observation assessment'),undefined);assert.equal(calls.filter(c=>c.init?.method==='POST').length,writes);});
  const closed=renderer(PilotMetrics,{workflow});closed.render();await settle(closed);
  check('Explicit permissions fail closed by default despite supported worker features',()=>{assert.equal(nodes(closed.tree).filter(n=>n.type==='form').length,0);assert.match(text(closed.tree),/current access/);});
  const reportOnly=renderer(PilotMetrics,{workflow:null});reportOnly.render();await settle(reportOnly);
  check('No-task reader retains explicit worker report export and no task-record forms',()=>{assert.equal(nodes(reportOnly.tree).filter(n=>n.type==='form').length,0);assert.ok(nodes(reportOnly.tree).find(n=>n.type==='button'&&text(n)==='Download worker pilot report'));});
  metrics.props={...metrics.props,allowMeasure:true,allowLabel:true};metrics.render();const previousTaskSubmit=form(metrics.tree,'Participant-reported comparison').props.onSubmit;
  metrics.props={...metrics.props,workflow:{...workflow,id:'22222222-2222-4222-8222-222222222222'}};metrics.render();writes=calls.filter(c=>c.init?.method==='POST').length;
  previousTaskSubmit({preventDefault(){}});await settle(metrics);
  check('A captured prior-task handler cannot record against a new task',()=>{assert.equal(calls.filter(c=>c.init?.method==='POST').length,writes);assert.equal(field(metrics.tree,'Elapsed attempt time, seconds').props.value,'');});
  const removedSubmit=form(metrics.tree,'Participant-reported comparison').props.onSubmit;metrics.unmount();removedSubmit({preventDefault(){}});await new Promise(resolve=>setImmediate(resolve));
  check('Unmounted measurement handlers cannot dispatch after task/scope removal',()=>{assert.equal(calls.filter(c=>c.init?.method==='POST').length,writes);});
  const savedCreate=URL.createObjectURL,savedRevoke=URL.revokeObjectURL,savedCreateElement=document.createElement;
  let exportClicks=0,exportBlobs=0,resolveExport;
  URL.createObjectURL=()=>{exportBlobs++;return'blob:synthetic-report';};URL.revokeObjectURL=()=>{};
  document.createElement=()=>({click(){exportClicks++;}});
  respond=async p=>p==='/context'?{pilot_features:['pilot-evaluation-v1','pilot-observations-v1']}:report;
  const removedExport=renderer(PilotMetrics,{workflow:null});removedExport.render();await settle(removedExport);
  respond=()=>new Promise(resolve=>{resolveExport=resolve;});
  nodes(removedExport.tree).find(n=>n.type==='button'&&text(n)==='Download worker pilot report').props.onClick();removedExport.render();removedExport.unmount();
  resolveExport(report);await new Promise(resolve=>setImmediate(resolve));
  check('A report resolved after task/account/worker removal creates no Blob or download click',()=>{assert.equal(exportBlobs,0);assert.equal(exportClicks,0);});
  respond=async p=>p==='/context'?{pilot_features:['pilot-evaluation-v1','pilot-observations-v1']}:report;
  const changedExport=renderer(PilotMetrics,{workflow});changedExport.render();await settle(changedExport);
  respond=()=>new Promise(resolve=>{resolveExport=resolve;});
  nodes(changedExport.tree).find(n=>n.type==='button'&&text(n)==='Download worker pilot report').props.onClick();changedExport.render();
  const oldExportResolve=resolveExport;respond=async p=>p==='/context'?{pilot_features:['pilot-evaluation-v1','pilot-observations-v1']}:report;
  changedExport.props={workflow:{...workflow,id:'33333333-3333-4333-8333-333333333333'}};changedExport.render();await settle(changedExport);
  oldExportResolve(report);await settle(changedExport);
  check('A same-instance task change suppresses old report export and success notice',()=>{assert.equal(exportBlobs,0);assert.equal(exportClicks,0);assert.doesNotMatch(text(changedExport.tree),/Report downloaded/);});
  nodes(changedExport.tree).find(n=>n.type==='button'&&text(n)==='Download worker pilot report').props.onClick();await settle(changedExport);
  check('An explicit current-task report still exports once after stale-download cleanup',()=>{assert.equal(exportBlobs,1);assert.equal(exportClicks,1);assert.match(text(changedExport.tree),/Report downloaded/);});
  changedExport.unmount();URL.createObjectURL=savedCreate;URL.revokeObjectURL=savedRevoke;document.createElement=savedCreateElement;
  task.unmount();closed.unmount();reportOnly.unmount();
  console.log(`${passed} contextual measurement checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{Module._load=savedLoad;require.extensions['.ts']=savedTs;require.extensions['.tsx']=savedTsx;});
