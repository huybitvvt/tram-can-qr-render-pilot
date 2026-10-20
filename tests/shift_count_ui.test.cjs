const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=require('./frontend_fixture.cjs').html();
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const begin=script.indexOf('function renderShiftCount('),end=script.indexOf('\nfunction rollBatchSourceKey(',begin);

function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function setup(){
 const classes=new Set(),requests=[],timers=[],events={};
 const fields={date:'2026-10-13',shift:'12C1',machine:'UPPER',order:'LSX-OPEN',productCode:'MN-BB453',bi:.16};
 const round={eventId:'open',coreImage:'core.jpg',productImage:'sp.jpg',coreAiPending:true,saved:false,weight:'0',qr:'MN-BB453_1'};
 const nodes={shiftCount:{classList:{add(...names){names.forEach(n=>classes.add(n))},remove(...names){names.forEach(n=>classes.delete(n))}},setAttribute(){}},shiftCountValue:{textContent:'--'},shiftCountDetail:{textContent:''}};
 const doc={hidden:false,addEventListener:(name,fn)=>events[name]=fn};
 const ctx=vm.createContext({
  $:id=>nodes[id],readSourceFields:()=>({...fields}),rollBatchSize:()=>30,URLSearchParams,workflowMode:'production',stations:[{rounds:[round]}],
  sourceLabel:value=>[value.date,value.shift,value.machine,value.order].join(' · '),document:doc,window:{addEventListener:(name,fn)=>events[name]=fn},
  api:url=>{const pending=deferred();requests.push({url,...pending});return pending.promise},
  setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearInterval(){},setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearTimeout(){},
 });
 vm.runInContext(script.slice(begin,end),ctx);
 return{ctx,nodes,fields,round,classes,requests,timers,events,doc};
}

test('capture count reads upper source only and leaves pending photos unchanged',async()=>{
 const {ctx,nodes,fields,round,requests}=setup(),before=JSON.stringify({fields,round});
 const result=ctx.refreshShiftCount(true);
 const params=new URL(requests[0].url,'http://localhost').searchParams;
 assert.equal(params.get('work_date'),'2026-10-13');assert.equal(params.get('shift'),'12C1');
 assert.equal(params.get('machine'),'UPPER');assert.equal(params.get('production_order'),'LSX-OPEN');
 assert.equal(params.get('qr_code'),'MN-BB453');assert.equal(params.get('include_drafts'),'0');
 assert.equal(params.get('count_only'),'1');assert.equal(params.get('local_only'),'1');
 requests[0].resolve({measurement_count:6,count_exact:true});
 assert.equal(await result,6);assert.equal(nodes.shiftCountValue.textContent,'6');
 assert.equal(JSON.stringify({fields,round}),before);
 assert.doesNotMatch(html,/id="photoDraftBackups"|id="photoDraftBody"/);
});

test('an older count response cannot overwrite the fresh count after a save',async()=>{
 const {ctx,nodes,requests}=setup();
 const old=ctx.refreshShiftCount();const fresh=ctx.refreshShiftCount(true);
 requests[1].resolve({measurement_count:7});await fresh;
 requests[0].resolve({measurement_count:6});assert.equal(await old,null);
 assert.equal(nodes.shiftCountValue.textContent,'7');
});

test('a response for the old capture source cannot appear after changing source',async()=>{
 const {ctx,nodes,fields,requests}=setup();
 const old=ctx.refreshShiftCount();fields.shift='12C2';fields.machine='NEXT';fields.order='LSX-NEXT';
 requests[0].resolve({measurement_count:99});assert.equal(await old,null);
 assert.equal(nodes.shiftCountValue.textContent,'--');
 const fresh=ctx.refreshShiftCount();assert.equal(new URL(requests[1].url,'http://localhost').searchParams.get('machine'),'NEXT');
 requests[1].resolve({measurement_count:2});await fresh;
 assert.equal(nodes.shiftCountValue.textContent,'2');
});

test('polling skips overlapping requests and retries errors without resetting the count to zero',async()=>{
 const {ctx,nodes,classes,requests}=setup();
 const one=ctx.refreshShiftCount();const same=ctx.refreshShiftCount();assert.equal(requests.length,1);
 requests[0].resolve({measurement_count:8});await Promise.all([one,same]);
 const failed=ctx.refreshShiftCount();requests[1].reject(Error('network'));await failed;
 assert.equal(nodes.shiftCountValue.textContent,'8');assert.equal(classes.has('error'),true);
 const retry=ctx.refreshShiftCount();requests[2].resolve({measurement_count:9});await retry;
 assert.equal(nodes.shiftCountValue.textContent,'9');assert.equal(classes.has('error'),false);
 const missing=ctx.refreshShiftCount();requests[3].resolve({measurement_count:null});await missing;
 assert.equal(nodes.shiftCountValue.textContent,'9');assert.equal(classes.has('error'),true);
});

test('count updates without clicking refresh and stops polling in hidden or unrelated workflows',async()=>{
 const {ctx,nodes,requests,timers,doc}=setup();
 ctx.startShiftCountPolling();assert.equal(requests.length,1);assert.equal(timers[0].ms,2000);
 requests[0].resolve({measurement_count:3});await ctx.refreshShiftCount();
 timers[0].fn();assert.equal(requests.length,2);
 requests[1].resolve({measurement_count:4});await ctx.refreshShiftCount();assert.equal(nodes.shiftCountValue.textContent,'4');
 doc.hidden=true;timers[0].fn();assert.equal(requests.length,2);
 doc.hidden=false;ctx.workflowMode='inventory';timers[0].fn();assert.equal(requests.length,2);
 ctx.stopShiftCountPolling();
});

test('source edits and returning to the tab request a fresh count',async()=>{
 const {ctx,requests,timers,events}=setup();
 ctx.bindShiftCountUpdates();ctx.queueShiftCountRefresh();assert.equal(timers[0].ms,150);
 timers[0].fn();requests[0].resolve({measurement_count:2});await ctx.refreshShiftCount();
 events.visibilitychange();assert.equal(requests.length,2);requests[1].resolve({measurement_count:3});await ctx.refreshShiftCount();
 events.beforeunload();
});
