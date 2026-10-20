const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=require('./frontend_fixture.cjs').html().match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(){
 const nodes={},calls=[],messages=[],opened=[];let productionReloads=0,listReloads=0;
 const node=()=>({value:'',hidden:true,children:[],dataset:{},classList:{add(){},remove(){}},setAttribute(){},focus(){this.focused=true},appendChild(child){this.children.push(child)},addEventListener(_event,handler){this.click=handler}});
 const item={event_id:'production-1',qr_code:'',core_weight:null,product_weight:7.5,weight_raw:'',work_date:'2026-10-14',shift:'12C1',machine:'Máy 1',production_order:'LSX-1',error_status:'error',error_reason:'Chưa nhận diện được mã QR'};
 const ctx=vm.createContext({
  $:id=>nodes[id]??=node(),productionRowsByEvent:{'production-1':item},listRowsByEvent:{},
  document:{createElement:node},productWeightFromRaw:()=>NaN,optionalRecordWeight:value=>value==null?NaN:Number(value),
  recordErrorStatus:item=>item.error_status,recordErrorReason:item=>item.error_reason||'',syncEditProductCode(){},productCodeFromQr:code=>code.split('_')[0],
  api:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {local_updated:true}},
  status:(_host,message,tone)=>messages.push({message,tone}),flashListStatus:(message,tone)=>messages.push({message,tone}),
  loadRecords:async()=>{productionReloads++},loadListRecords:async()=>{listReloads++},
 });
 vm.runInContext("let listEditSource='list';",ctx);
 for(const name of ['openListEditModal','closeListEditModal','appendProductionEditAction']){
  vm.runInContext(script.split('\n').find(line=>line.startsWith('function '+name+'(')),ctx);
 }
 const start=script.indexOf('async function saveListEdit('),end=script.indexOf('\nasync function deleteListRecord(',start);
 assert.ok(start>=0&&end>start);vm.runInContext(script.slice(start,end),ctx);
 return {ctx,nodes,calls,messages,item,opened,get productionReloads(){return productionReloads},get listReloads(){return listReloads}};
}

test('manual edit button opens the correct production row without requiring list data',async()=>{
 const f=setup(),host={children:[],appendChild(child){this.children.push(child)}};
 f.ctx.appendProductionEditAction(host,f.item);
 assert.equal(host.children[0].textContent,'Sửa tay');
 await host.children[0].click();
 assert.equal(f.nodes.editEventId.value,'production-1');
 assert.equal(f.nodes.editCoreWeight.value,'0');
 assert.equal(f.nodes.editProductWeight.value,'7.5');
 assert.equal(f.nodes.editErrorStatus.value,'ok');
 assert.equal(f.nodes.listEditModal.hidden,false);
 f.nodes.editQrCode.value='SP_123';await f.ctx.saveListEdit();
 assert.equal(f.calls[0].url,'/api/measurements/update');
 assert.equal(f.calls[0].body.event_id,'production-1');
 assert.equal(f.calls[0].body.core_weight,0);
 assert.equal(f.calls[0].body.product_weight,7.5);
 assert.equal(f.calls[0].body.error_status,'ok');
 assert.equal(f.calls[0].body.machine,'Máy 1');
 assert.equal(f.productionReloads,1);assert.equal(f.listReloads,0);
 assert.match(f.messages.at(-1).message,/ĐÃ SỬA dòng production-1/);
});

test('blank product weight and an empty QR cannot be accepted as repaired',async()=>{
 const f=setup();f.ctx.openListEditModal('production-1','production');
 await f.ctx.saveListEdit();assert.equal(f.calls.length,0);assert.equal(f.nodes.editQrCode.focused,true);
 f.nodes.editQrCode.value='SP_123';f.nodes.editProductWeight.value='';
 await f.ctx.saveListEdit();assert.equal(f.calls.length,0);assert.equal(f.nodes.editProductWeight.focused,true);
 assert.equal(f.nodes.listEditModal.hidden,false);
});

test('manual quality defects remain selected while automatic QR errors can be repaired',()=>{
 const f=setup();f.item.error_reason='AI không đọc được cân lõi · Lõi bị hỏng';
 f.ctx.openListEditModal('production-1','production');
 assert.equal(f.nodes.editErrorStatus.value,'error');assert.equal(f.nodes.editErrorReason.value,f.item.error_reason);
});

test('list editing still reloads the list and uses its own row',async()=>{
 const f=setup();f.ctx.listRowsByEvent.list={...f.item,event_id:'list',qr_code:'SP_999',error_status:'ok',error_reason:''};
 f.ctx.openListEditModal('list');await f.ctx.saveListEdit();
 assert.equal(f.calls[0].body.event_id,'list');assert.equal(f.listReloads,1);assert.equal(f.productionReloads,0);
});

test('the capture keyboard handler stays inactive while a row editor is open',()=>{
 let handler,usedCapture=false;
 const ctx=vm.createContext({$:id=>({hidden:id==='warehouseReadyModal'}),document:{addEventListener:(_event,callback)=>{handler=callback}},current:()=>{usedCapture=true}});
 const line=script.split('\n').find(line=>line.startsWith("document.addEventListener('keydown',event=>{")&&line.includes('const editing=isTextEditingTarget'));
 assert.ok(line);vm.runInContext(line,ctx);
 for(const key of ['Backspace','Enter',' '])handler({key,code:key===' '?'Space':key,target:{}});
 assert.equal(usedCapture,false);
});
