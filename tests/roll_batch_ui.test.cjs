const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('frontend/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
function setup(api){
 const nodes={},saved=[],messages=[];
 const context={date:'2026-09-15',shift:'A',machine:'1',order:'LSX'};
 const ctx=vm.createContext({sourceContext:context,workflowMode:'production',api,
  $:id=>nodes[id]??={},status:(_,text)=>messages.push(text),
  rollBatchSourceKey:(c=context)=>JSON.stringify(c),sourceQuery:()=>'',
  loadWeighBatches:async()=>{},nextRollBatchMilestone:n=>Math.floor(n/10)*10,
  openRollBatchModal:()=>{ctx.opened=true},
  closeRollBatchModal:()=>{ctx.closed=true},syncRollBatchConfirmButton:()=>{},
  writeRollBatchConfirmed:(...args)=>saved.push(args),
  printWeighBatch:()=>{throw Error('Unexpected automatic print')},
 });
 vm.runInContext('let rollBatchPendingMilestone=10,rollBatchSaving=false;',ctx);
 const start=script.indexOf('async function requestRollBatchConfirm(');
 vm.runInContext(script.slice(start,script.indexOf('\nlet weighBatchRows',start)),ctx);
 const confirm=script.indexOf('async function confirmRollBatchCount(');
 vm.runInContext(script.slice(confirm,script.indexOf('\nlet recordsLoading',confirm)),ctx);
 return {ctx,saved,messages};
}
test('confirmation closes immediately, prevents duplicate requests, and does not print',async()=>{
 let resolve,calls=0;
 const {ctx,saved}=setup(()=>{calls++;return new Promise(r=>resolve=r)});
 const pending=ctx.confirmRollBatchCount();
 assert.equal(ctx.closed,true);
 await ctx.confirmRollBatchCount();assert.equal(calls,1);
 resolve({item:{dot_can:1,so_luong:10}});await pending;
 assert.equal(saved.length,1);assert.equal(ctx.opened,undefined);
});
test('backend failure leaves confirmation closed and permits retry without recording success',async()=>{
 let calls=0;
 const {ctx,saved,messages}=setup(async()=>{calls++;throw Error('Backend unavailable')});
 await ctx.confirmRollBatchCount();await ctx.confirmRollBatchCount();
 assert.equal(ctx.closed,true);assert.equal(ctx.opened,undefined);
 assert.equal(calls,2);assert.equal(saved.length,0);
 assert.match(messages.at(-1),/Backend unavailable/);
});
test('only a manual request opens confirmation for synchronized rolls',async()=>{
 const {ctx}=setup(async()=>({synced_measurement_count:10}));
 assert.equal(ctx.opened,undefined);await ctx.requestRollBatchConfirm();assert.equal(ctx.opened,true);
 const fewer=setup(async()=>({synced_measurement_count:9}));
 await fewer.ctx.requestRollBatchConfirm();assert.equal(fewer.ctx.opened,undefined);
 assert.doesNotMatch(script.slice(script.indexOf('async function loadRecords('),script.indexOf('let inventoryRecordsLoading')),/openRollBatchModal|requestRollBatchConfirm|maybePromptRollBatchConfirm/);
});
