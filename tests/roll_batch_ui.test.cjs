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
  loadWeighBatches:async()=>{},nextRollBatchMilestone:()=>10,
  openRollBatchModal:()=>{ctx.opened=true},
  closeRollBatchModal:()=>{ctx.closed=true},syncRollBatchConfirmButton:()=>{},
  writeRollBatchConfirmed:(...args)=>saved.push(args),
  printWeighBatch:()=>{throw Error('Unexpected automatic print')},
 });
 vm.runInContext('let rollBatchPendingMilestone=10,rollBatchPendingCount=9,rollBatchPendingSize=10,rollBatchSaving=false;',ctx);
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
test('manual request opens confirmation without requiring enough synchronized rolls',async()=>{
 const {ctx}=setup(async()=>({synced_measurement_count:10}));
 assert.equal(ctx.opened,undefined);await ctx.requestRollBatchConfirm();assert.equal(ctx.opened,true);
 const fewer=setup(async()=>({synced_measurement_count:9}));
 await fewer.ctx.requestRollBatchConfirm();assert.equal(fewer.ctx.opened,true);
 const empty=setup(async()=>({synced_measurement_count:0}));
 await empty.ctx.requestRollBatchConfirm();assert.equal(empty.ctx.opened,true);
 assert.doesNotMatch(script.slice(script.indexOf('async function loadRecords('),script.indexOf('let inventoryRecordsLoading')),/openRollBatchModal|requestRollBatchConfirm|maybePromptRollBatchConfirm/);
});

test('confirmation permits a partial batch while retaining the configured target',async()=>{
 let sent;
 const {ctx}=setup(async(_url,options)=>{sent=JSON.parse(options.body);return{item:{dot_can:2,so_luong:7}}});
 vm.runInContext('rollBatchPendingMilestone=17;rollBatchPendingCount=14;rollBatchPendingSize=10;',ctx);
 await ctx.confirmRollBatchCount();
 assert.equal(sent.milestone,17);
 assert.equal(sent.batch_size,10);
 assert.equal(sent.allow_partial,true);
});

test('machine limits default to thermal 30, packaging 16, Da Nang 10 and can be changed separately',()=>{
 const saved=new Map(),nodes={sourceShift:{value:'HC1'},sourceMachine:{value:'MÁY CÁCH NHIỆT 11'},rollBatchSize:{value:'24'}},context={shift:'HC1',machine:'MÁY CÁCH NHIỆT 11'};
 const ctx=vm.createContext({sourceContext:context,sanitizeMachine:value=>String(value||'').trim(),
  localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},
  $:id=>nodes[id],status:()=>{},captureStatus:{},readRollBatchConfirmed:()=>ctx.confirmed});
 ctx.confirmed=0;
 vm.runInContext(script.split('\n').find(line=>line.startsWith('const ROLL_BATCH_SIZE_PREFIX=')),ctx);
 for(const name of ['function rollBatchSizeKey(','function rollBatchMachineLimit(','function rollBatchSize(','function saveRollBatchSize(','function nextRollBatchMilestone(']){
  vm.runInContext(script.split('\n').find(line=>line.startsWith(name)),ctx);
 }
 assert.equal(ctx.rollBatchSize(),30);
 assert.equal(ctx.rollBatchMachineLimit({shift:'HC1',machine:'May cach-nhiet 11'}),30);
 assert.equal(ctx.nextRollBatchMilestone(7),30);
 assert.equal(ctx.nextRollBatchMilestone(45),30);
 ctx.saveRollBatchSize();
 assert.equal(ctx.rollBatchSize(),24);
 context.machine='MÁY BAO BÌ 16';nodes.sourceMachine.value=context.machine;
 assert.equal(ctx.rollBatchSize(),16);
 saved.set(ctx.rollBatchSizeKey(context),'30');
 assert.equal(ctx.rollBatchSize(),16);
 ctx.saveRollBatchSize();
 assert.equal(nodes.rollBatchSize.value,'16');
 assert.equal(nodes.rollBatchSize.max,'16');
 context.shift='Ca chuẩn Đà Nẵng';
 assert.equal(ctx.rollBatchSize(),10);
 context.machine='MÁY CÁCH NHIỆT 11';
 assert.equal(ctx.rollBatchSize(),10);
 ctx.confirmed=7;
 assert.equal(ctx.nextRollBatchMilestone(40),17);
});

test('cloud batch limit agrees with the station limit',()=>{
 const edge=fs.readFileSync('backend/supabase/functions/ingest-measurement/index.ts','utf8');
 const match=edge.match(/function maxWeighBatchSize\([^\n]+\n[\s\S]*?\n}/);
 assert.ok(match);
 const ctx=vm.createContext({});
 vm.runInContext(match[0].replace(/: string|: number/g,''),ctx);
 assert.equal(ctx.maxWeighBatchSize('HC1','MÁY BAO BÌ 16'),16);
 assert.equal(ctx.maxWeighBatchSize('HC1','Máy cách nhiệt 11'),30);
 assert.equal(ctx.maxWeighBatchSize('Ca chuẩn Đà Nẵng','Máy cách nhiệt 11'),10);
});
