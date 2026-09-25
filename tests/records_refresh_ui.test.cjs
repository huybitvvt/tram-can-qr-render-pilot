const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=fs.readFileSync('frontend/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const start=script.indexOf('let recordsLoading=false,recordsRequestId=0;');
const end=script.indexOf('\nlet inventoryRecordsLoading=false;',start);

function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
function setup(){
  const pending={remote:deferred(),local:deferred()},calls=[];
  const body={children:[],replaceChildren(){this.children=[]},appendChild(row){this.children.push(row)},querySelector(){return null}};
  const count={classList:{add(){},remove(){}},setAttribute(){}};
  const nodes={recordsBody:body,shiftCount:count,productionRecordsStatus:{hidden:true}};
  const ctx=vm.createContext({
    $:id=>nodes[id],sourceQuery:()=>'',sourceLabel:()=>'',
    api:url=>{calls.push(url);return url.includes('local_only=1')?pending.local.promise:pending.remote.promise},
    document:{createElement:tag=>({tag,cells:[],appendChild(child){this.cells.push(child)}})},
    recordCell:(row,value)=>{row.cells.push(value);return {}},
    renderShiftCount(){},rebuildProductionQrIndex(){},
    productWeightFromRaw:()=>NaN,biWeightFromRaw:()=>0,nvlWeight:(p,c,b)=>p-c-b,
    optionalRecordWeight:value=>value==null?NaN:Number(value),
    recordErrorStatus:()=>'',recordErrorReason:()=>'',recordImages(){},
    formatRecordWeight:n=>Number.isFinite(n)?String(n):'--',productCodeFromQr:()=>'',
    appendProductionDeleteAction(){},extraRoundsFromRaw:()=>'',loadWeighBatches:async()=>{},
    status(){},
  });
  vm.runInContext(script.slice(start,end),ctx);
  return {ctx,body,pending,calls};
}

test('fresh local row wins over an older history request after save',async()=>{
  const {ctx,body,pending,calls}=setup();
  const old=ctx.loadRecords();
  const fresh=ctx.loadRecords({localOnly:true});
  assert.equal(calls.length,2);
  assert.match(calls[1],/local_only=1/);
  pending.local.resolve({items:[{event_id:'saved',qr_code:'QR-SAVED',captured_at:'2026-09-22T12:00:00',core_weight:null,product_weight:7.5,unit:'kg'}]});
  await fresh;
  assert.equal(body.children.length,1);
  assert.equal(body.children[0].cells[1],'QR-SAVED');
  assert.equal(body.children[0].cells[3],'--');
  pending.remote.resolve({items:[]});
  await old;
  assert.equal(body.children[0].cells[1],'QR-SAVED');
});
