const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=require('./frontend_fixture.cjs').html().match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
function deferred(){let resolve;const promise=new Promise(done=>resolve=done);return{promise,resolve}}
function setup(storage=new Map()){
 const nodes={},requests=[],timers=[],fields={date:'2026-10-14',shift:'12C1',machine:'M1',order:'LSX-1',productCode:'SP-001'},round={coreImage:'active-core',qr:'ACTIVE_1',weight:'0.4'},session={rounds:[round]};
 let otherModal=false,focusCount=0;
 const node=()=>({hidden:true,textContent:'',classList:{add(){},remove(){}},setAttribute(){},focus(){focusCount++}});
 for(const id of ['shiftCount','shiftCountValue','shiftCountDetail','warehouseReadyModal','warehouseReadyTitle','warehouseReadyCount','warehouseReadyNote','warehouseReadySource','closeWarehouseReadyBtn'])nodes[id]=node();
 const ctx=vm.createContext({$:id=>nodes[id],readSourceFields:()=>({...fields}),rollBatchSize:()=>ctx.target,URLSearchParams,
  workflowMode:'production',stations:[session],localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
  sourceLabel:value=>[value.date,value.shift,value.machine,value.order].join(' · '),
  document:{hidden:false,activeElement:{focus(){focusCount++}},querySelector:()=>otherModal?{}:null},
  api:url=>{const request={url,...deferred()};requests.push(request);return request.promise},
  setInterval:(fn,ms)=>{timers.push({fn,ms});return timers.length},clearInterval(){},setTimeout(){},clearTimeout(){},
 });
 ctx.target=30;
 const start=script.indexOf('function renderShiftCount('),end=script.indexOf('\nfunction rollBatchSourceKey(',start);
 vm.runInContext(script.slice(start,end),ctx);
 const result=(count,signature='batch-a')=>({measurement_count:74,count_exact:true,warehouse_ready_count:count,warehouse_ready_batch_size:ctx.target,warehouse_ready_signature:count>=ctx.target?signature:''});
 const poll=async(count,signature)=>{const pending=ctx.refreshShiftCount();requests.at(-1).resolve(result(count,signature));await pending};
 return{ctx,nodes,requests,fields,round,session,storage,timers,poll,result,setOtherModal(value){otherModal=value},get focusCount(){return focusCount}};
}

test('the small target controls the popup; 74 local tickets do not trigger it before enough synced waiting tickets',async()=>{
 const f=setup(),before=JSON.stringify(f.round);await f.poll(29);
 assert.equal(f.nodes.shiftCountValue.textContent,'74');assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 await f.poll(30);
 assert.equal(f.nodes.warehouseReadyModal.hidden,false);
 assert.equal(f.nodes.warehouseReadyTitle.textContent,'Đã đủ 30 cuộn, vui lòng đẩy kho');
 assert.match(f.nodes.warehouseReadySource.textContent,/LSX-1.*SP-001/);
 assert.equal(JSON.stringify(f.round),before);
});

test('a packaging machine set to 24 rolls waits for 24 synced tickets instead of 16',async()=>{
 const f=setup();f.fields.shift='HC1';f.fields.machine='MÁY BAO BÌ 16';f.ctx.target=24;
 f.ctx.sourceContext=f.fields;f.ctx.sanitizeMachine=value=>String(value||'').trim();
 vm.runInContext(script.split('\n').find(line=>line.startsWith('const ROLL_BATCH_SIZE_PREFIX=')),f.ctx);
 for(const name of ['function rollBatchSizeKey(','function rollBatchMachineLimit(','function rollBatchSize(']){
  vm.runInContext(script.split('\n').find(line=>line.startsWith(name)),f.ctx);
 }
 f.storage.set(f.ctx.rollBatchSizeKey(f.fields),'24');
 await f.poll(16);assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 await f.poll(23);assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 assert.match(f.requests.at(-1).url,/warehouse_batch_size=24/);
 await f.poll(24);assert.equal(f.nodes.warehouseReadyTitle.textContent,'Đã đủ 24 cuộn, vui lòng đẩy kho');
});

test('the polling timer notices a completed sync without saving another roll or refreshing the table',async()=>{
 const f=setup();f.ctx.startShiftCountPolling();
 f.requests[0].resolve(f.result(29));await f.ctx.refreshShiftCount();
 assert.equal(f.timers[0].ms,2000);f.timers[0].fn();
 f.requests.at(-1).resolve(f.result(35));await f.ctx.refreshShiftCount();
 assert.equal(f.nodes.warehouseReadyModal.hidden,false);
 assert.equal(f.nodes.warehouseReadyCount.textContent,'35 cuộn chờ đẩy kho');
});

test('repeated polls and page reloads do not notify the same batch again',async()=>{
 const f=setup();await f.poll(30);const focused=f.focusCount;
 await f.poll(35);assert.equal(f.focusCount,focused);
 f.ctx.closeWarehouseReadyModal();await f.poll(40);assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 const reload=setup(f.storage);await reload.poll(40);assert.equal(reload.nodes.warehouseReadyModal.hidden,true);
 await reload.poll(30,'batch-b');assert.equal(reload.nodes.warehouseReadyModal.hidden,false);
});

test('warehouse import closes the obsolete popup and the next full batch can notify again',async()=>{
 const f=setup();await f.poll(30);await f.poll(0);
 assert.equal(f.nodes.warehouseReadyModal.hidden,true);assert.equal(f.storage.size,0);
 await f.poll(30,'next-batch');assert.equal(f.nodes.warehouseReadyModal.hidden,false);
});

test('hidden tabs, existing dialogs and camera writes defer the popup until they finish',async()=>{
 const f=setup();f.ctx.document.hidden=true;await f.poll(30);assert.equal(f.storage.size,0);
 f.ctx.document.hidden=false;f.setOtherModal(true);await f.poll(30);assert.equal(f.storage.size,0);
 f.setOtherModal(false);f.session._analyzeLock=true;await f.poll(30);assert.equal(f.storage.size,0);
 f.session._analyzeLock=false;await f.poll(30);assert.equal(f.nodes.warehouseReadyModal.hidden,false);
});

test('a late response for another machine or target cannot open a popup',async()=>{
 const f=setup(),old=f.ctx.refreshShiftCount();f.fields.machine='M2';
 f.requests[0].resolve(f.result(30));await old;assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 const stale=f.ctx.refreshShiftCount();const oldData=f.result(30);f.ctx.target=16;
 f.requests.at(-1).resolve(oldData);await stale;assert.equal(f.nodes.warehouseReadyModal.hidden,true);
 await f.poll(16);assert.equal(f.nodes.warehouseReadyTitle.textContent,'Đã đủ 16 cuộn, vui lòng đẩy kho');
});

test('older or inexact counter responses cannot trigger a warehouse reminder',()=>{
 const f=setup();f.ctx.maybePromptWarehouseReady({measurement_count:74},f.fields);
 f.ctx.maybePromptWarehouseReady({...f.result(30),count_exact:false},f.fields);
 assert.equal(f.nodes.warehouseReadyModal.hidden,true);
});

test('capture shortcuts stay inactive and Tab stays inside the warehouse popup',()=>{
 let handler,captured=false,focused=false;
 const ctx=vm.createContext({$:id=>id==='warehouseReadyModal'?{hidden:false}:{focus(){focused=true}},document:{addEventListener:(_name,fn)=>{handler=fn}},current:()=>{captured=true}});
 const line=script.split('\n').find(line=>line.startsWith("document.addEventListener('keydown',event=>{")&&line.includes('const editing=isTextEditingTarget'));
 vm.runInContext(line,ctx);
 for(const key of ['Backspace','Enter',' ','Tab'])handler({key,preventDefault(){}});
 assert.equal(captured,false);assert.equal(focused,true);
});
