const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const line=name=>script.split('\n').find(value=>value.startsWith(name));

function setup(){
  const storage=new Map();
  const stations=[
    {stationId:'station-01',cameraId:'camera-01',machineId:'MÁY CẤU HÌNH'},
    {stationId:'station-02',cameraId:'camera-02',machineId:'MÁY TRẠM 02'},
  ];
  let selected=0;
  const nodes={
    sourceShift:{value:'',options:[],replaceChildren(){this.options=[]},add(option){this.options.push(option)}},
    sourceMachine:{value:'MÁY CÁCH NHIỆT 11',disabled:true},
    sourceMachineList:{options:[],replaceChildren(){this.options=[]},appendChild(option){this.options.push(option)}},
    sourceDate:{value:'2026-09-23'},sourceOrder:{value:''},biWeight:{value:'0.16'},
  };
  const ctx=vm.createContext({
    stations,current:()=>stations[selected],
    $:id=>nodes[id],Option:function(text,value){this.text=text;this.value=value},
    document:{createElement:()=>({value:''})},todayLocalDate:()=> '2026-09-23',
    sanitizeOrder:value=>String(value||'').trim(),normalizeBiWeight:value=>Number(value),
    localStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value)},
    SOURCE_CONTEXT_KEY:'rollQrScale.sourceContext.v1',
    stationSourceContexts:{},activeSourceStationKey:'',
    sourceContext:{date:'2026-09-23',shift:'HC1',machine:'MÁY CÁCH NHIỆT 11',order:'',bi:0.16},
  });
  for(const declaration of [
    'const SOURCE_STATION_CONTEXT_KEY=',
    'const SOURCE_SHIFT_LABELS=', 'const FALLBACK_SHIFTS=', 'const FALLBACK_MACHINES=',
    'let SOURCE_SHIFTS=', 'let SOURCE_MACHINES=',
  ])vm.runInContext(line(declaration),ctx);
  for(const name of [
    'function sanitizeMachine(', 'function pickListed(', 'function shiftOptionLabel(',
    'function setSourceShiftOptions(', 'function setSourceMachineOptions(',
    'function readSourceFields(', 'function selectSourceOrder(', 'function fillSourceFields(',
    'function saveSourceContext(', 'function stationSourceKey(', 'function lockSourceMachine(',
  ])vm.runInContext(line(name),ctx);
  return {ctx,nodes,stations,storage,select:index=>{selected=index}};
}

test('Ca chuẩn Đà Nẵng remains selectable when the database returns other shifts',()=>{
  const {ctx,nodes}=setup();
  ctx.setSourceShiftOptions(['12C1'],'Ca chuẩn Đà Nẵng');
  assert.equal(nodes.sourceShift.value,'Ca chuẩn Đà Nẵng');
  assert.ok(nodes.sourceShift.options.some(option=>option.value==='Ca chuẩn Đà Nẵng'));
});

test('configured machine is the first default, while manual names stay editable per station',()=>{
  const {ctx,nodes,stations,select}=setup();
  assert.equal(ctx.lockSourceMachine(stations[0]),true);
  assert.equal(nodes.sourceMachine.value,'MÁY CẤU HÌNH');
  nodes.sourceMachine.value='CA CHẤN ĐA NĂNG';
  nodes.sourceOrder.value='LSX-01';
  ctx.saveSourceContext(ctx.readSourceFields());
  assert.equal(nodes.sourceMachine.disabled,false);
  assert.equal(nodes.sourceMachine.value,'CA CHẤN ĐA NĂNG');
  select(1);
  assert.equal(ctx.lockSourceMachine(stations[1]),true);
  assert.equal(nodes.sourceMachine.value,'MÁY TRẠM 02');
  assert.equal(nodes.sourceOrder.value,'');
  select(0);
  assert.equal(ctx.lockSourceMachine(stations[0]),true);
  assert.equal(nodes.sourceMachine.value,'CA CHẤN ĐA NĂNG');
  assert.equal(nodes.sourceOrder.value,'LSX-01');
});

test('a changed station configuration replaces its old default machine',()=>{
  const {ctx,nodes,stations,select}=setup();
  ctx.lockSourceMachine(stations[0]);
  nodes.sourceOrder.value='LSX-OLD';
  ctx.saveSourceContext(ctx.readSourceFields());
  select(1);
  ctx.lockSourceMachine(stations[1]);
  stations[0].machineId='MÁY CẤU HÌNH MỚI';
  select(0);
  ctx.lockSourceMachine(stations[0]);
  assert.equal(nodes.sourceMachine.value,'MÁY CẤU HÌNH MỚI');
  assert.equal(nodes.sourceOrder.value,'');
});

test('switching back after a date change keeps the machine but clears the old LSX',()=>{
  const {ctx,nodes,stations,select}=setup();
  ctx.lockSourceMachine(stations[0]);
  nodes.sourceMachine.value='CA CHẤN ĐA NĂNG';
  nodes.sourceOrder.value='LSX-OLD';
  ctx.saveSourceContext(ctx.readSourceFields());
  select(1);
  ctx.lockSourceMachine(stations[1]);
  nodes.sourceDate.value='2026-09-24';
  ctx.saveSourceContext(ctx.readSourceFields());
  select(0);
  ctx.lockSourceMachine(stations[0]);
  assert.equal(nodes.sourceMachine.value,'CA CHẤN ĐA NĂNG');
  assert.equal(nodes.sourceOrder.value,'');
});

test('a single LSX suggestion cannot replace a selected shift',async()=>{
  const {ctx,nodes,storage}=setup();
  nodes.sourceShift.value='Ca chuẩn Đà Nẵng';
  ctx.sourceOrdersRequest=0;
  ctx.sourceOrdersLoading=false;
  ctx.captureStatus={};
  ctx.renderControls=()=>{};
  ctx.status=()=>{};
  ctx.productionOrdersQuery=()=>'';
  ctx.api=async()=>({suggestions:[{shift:'HC1',machine:'MÁY CẤU HÌNH'}],shifts:['HC1'],machines:['MÁY CẤU HÌNH'],orders:['LSX-01'],source:'local'});
  ctx.setSourceOrderOptions=(orders,selected)=>{nodes.sourceOrder.value=selected||orders[0]||'';return orders};
  ctx.applySourceFilterOptions=(data,preferred)=>{nodes.sourceShift.value=preferred.shift;nodes.sourceMachine.value=preferred.machine;return preferred};
  vm.runInContext(line('async function loadProductionOrders('),ctx);
  await ctx.loadProductionOrders('2026-09-23');
  assert.equal(nodes.sourceShift.value,'Ca chuẩn Đà Nẵng');
  assert.equal(JSON.parse(storage.get('rollQrScale.sourceContext.v1')).shift,'Ca chuẩn Đà Nẵng');
});
