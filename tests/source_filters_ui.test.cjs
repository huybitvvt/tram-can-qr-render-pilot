const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const line=name=>script.split('\n').find(value=>value.startsWith(name));

function setup(){
  const nodes={
    sourceShift:{value:'',options:[],replaceChildren(){this.options=[]},add(option){this.options.push(option)}},
    sourceMachine:{value:'CA CHẤN ĐA NĂNG',disabled:true},
    sourceMachineList:{options:[],replaceChildren(){this.options=[]},appendChild(option){this.options.push(option)}},
    sourceDate:{value:'2026-09-23'},sourceOrder:{value:'LSX-01'},biWeight:{value:'0.16'},
  };
  const ctx=vm.createContext({
    stations:[{machineId:'MÁY CẤU HÌNH'}],current:()=>({machineId:'MÁY CẤU HÌNH'}),
    $:id=>nodes[id],Option:function(text,value){this.text=text;this.value=value},
    document:{createElement:()=>({value:''})},todayLocalDate:()=> '2026-09-23',
    sanitizeOrder:value=>String(value||'').trim(),normalizeBiWeight:value=>Number(value),
  });
  for(const declaration of [
    'const SOURCE_SHIFT_LABELS=', 'const FALLBACK_SHIFTS=', 'const FALLBACK_MACHINES=',
    'let SOURCE_SHIFTS=', 'let SOURCE_MACHINES=',
  ])vm.runInContext(line(declaration),ctx);
  for(const name of [
    'function sanitizeMachine(', 'function pickListed(', 'function shiftOptionLabel(',
    'function setSourceShiftOptions(', 'function setSourceMachineOptions(',
    'function readSourceFields(', 'function lockSourceMachine(',
  ])vm.runInContext(line(name),ctx);
  return {ctx,nodes};
}

test('Ca chuẩn Đà Nẵng remains selectable when the database returns other shifts',()=>{
  const {ctx,nodes}=setup();
  ctx.setSourceShiftOptions(['12C1'],'Ca chuẩn Đà Nẵng');
  assert.equal(nodes.sourceShift.value,'Ca chuẩn Đà Nẵng');
  assert.ok(nodes.sourceShift.options.some(option=>option.value==='Ca chuẩn Đà Nẵng'));
});

test('configured station does not lock or replace a manually typed machine',()=>{
  const {ctx,nodes}=setup();
  ctx.setSourceMachineOptions([],nodes.sourceMachine.value);
  ctx.lockSourceMachine({machineId:'MÁY CẤU HÌNH'});
  assert.equal(nodes.sourceMachine.disabled,false);
  assert.equal(nodes.sourceMachine.value,'CA CHẤN ĐA NĂNG');
  assert.equal(ctx.readSourceFields().machine,'CA CHẤN ĐA NĂNG');
});
