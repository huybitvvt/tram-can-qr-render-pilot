const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=require('./frontend_fixture.cjs').html();
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const start=script.indexOf('async function loadRecords(');
const end=script.indexOf('\nlet inventoryRecordsLoading=false;',start);
assert.ok(start>=0&&end>start,'loadRecords must be present in the production script');

function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
function setup(){
  const pending={older:deferred(),fresh:deferred()},calls=[];
  const body={children:[],replaceChildren(){this.children=[]},appendChild(row){this.children.push(row)},querySelector(){return null}};
  const count={classList:{add(){},remove(){}},setAttribute(){}};
  const nodes={recordsBody:body,shiftCount:count,productionRecordsStatus:{hidden:true}};
  const ctx=vm.createContext({
    $:id=>nodes[id],recordsListQuery:()=>'',sourceLabel:()=>'',readRecordsFilterFields:()=>({}),
    api:url=>{calls.push(url);return calls.length===1?pending.older.promise:pending.fresh.promise},
    document:{createElement:tag=>({tag,cells:[],dataset:{},addEventListener(){},appendChild(child){this.cells.push(child)}})},
    recordCell:(row,value)=>{row.cells.push(value);return {}},
    renderShiftCount(){throw new Error('List filters must not render the capture count')},refreshShiftCount:async()=>1,rebuildProductionQrIndex(){},
    productWeightFromRaw:()=>NaN,biWeightFromRaw:()=>0,nvlWeight:(p,c,b)=>p-c-b,
    optionalRecordWeight:value=>value==null?NaN:Number(value),
    recordErrorStatus:()=>'',recordErrorReason:()=>'',recordImages(){},
    formatRecordWeight:n=>Number.isFinite(n)?String(n):'--',productCodeFromQr:()=>'',
    appendProductionDeleteAction(){},extraRoundsFromRaw:()=>'',loadWeighBatches:async()=>{},
    matchesRecordsStatusFilters:()=>true,canSelectForNhapKho:()=>true,
    canSelectProductionRecord:()=>true,recordsSelectionKey:()=>'',
    paintNhapKhoSelectBtn(){},appendNhapKhoStatusCell(){},syncSelectAllNhapKho(){},
    status(){},
  });
  vm.runInContext('let recordsLoading=false,recordsRequestId=0,productionRowsByEvent={},selectedNhapKhoIds=new Set(),nhapKhoSelectedEventIds=[],productionSelectionFilter="",productionAllSelectedFilter="",recordsSelectionBusy=false;\n'+script.slice(start,end),ctx);
  return {ctx,body,pending,calls};
}

test('fresh local row wins over an older list request after save',async()=>{
  const {ctx,body,pending,calls}=setup();
  const old=ctx.loadRecords();
  const fresh=ctx.loadRecords({localOnly:true});
  assert.equal(calls.length,2);
  assert.match(calls[0],/local_only=1/);
  assert.match(calls[1],/local_only=1/);
  pending.fresh.resolve({items:[{event_id:'saved',qr_code:'QR-SAVED',captured_at:'2026-09-22T12:00:00',core_weight:null,product_weight:7.5,unit:'kg'}]});
  await fresh;
  assert.equal(body.children.length,1);
  assert.equal(body.children[0].cells[4],'QR-SAVED');
  assert.equal(body.children[0].cells[6],'--');
  pending.older.resolve({items:[]});
  await old;
  assert.equal(body.children[0].cells[4],'QR-SAVED');
});

test('refresh keeps selected rows beyond the visible page',async()=>{
  const {ctx,pending}=setup();
  vm.runInContext("productionRowsByEvent={offpage:{event_id:'offpage',qr_code:'SP_204'}};selectedNhapKhoIds.add('offpage');",ctx);
  const loading=ctx.loadRecords();
  pending.older.resolve({items:[]});
  await loading;
  assert.equal(vm.runInContext("selectedNhapKhoIds.has('offpage')",ctx),true);
  assert.equal(vm.runInContext("productionRowsByEvent.offpage.qr_code",ctx),'SP_204');
});

test('refresh never inserts an unsaved photo backup into the saved records table',async()=>{
  const {ctx,body,pending}=setup();
  const loading=ctx.loadRecords();
  pending.older.resolve({measurement_count:1,error_count:1,total_count:2,items:[
    {event_id:'draft',qr_code:'QR-DRAFT',error_only:true,captured_at:'2026-10-12T13:00:00'},
    {event_id:'saved',qr_code:'QR-SAVED',core_weight:0,product_weight:7.5,captured_at:'2026-10-12T12:00:00'},
  ]});
  await loading;
  assert.equal(body.children.length,1);
  assert.equal(body.children[0].cells[4],'QR-SAVED');
  assert.equal(vm.runInContext('Boolean(productionRowsByEvent.draft)',ctx),false);
});
