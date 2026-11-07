const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(selected,fail=false){
  const calls=[],messages=[],busy=[];
  let reloads=0;
  const ctx=vm.createContext({
    $:()=>({hidden:true}),
    selectedNhapKhoIds:new Set(selected),
    productionRowsByEvent:{one:{event_id:'one'},two:{event_id:'two'},error:{error_only:true}},
    canSelectProductionRecord:item=>Boolean(item&&!item.error_only),
    api:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});if(fail)throw new Error('Mất kết nối');return {updated:1}},
    status:(_host,message,tone)=>messages.push({message,tone}),
    setManualSyncRunning:value=>busy.push(value),
    loadRecords:async()=>{reloads++},
  });
  const start=script.indexOf('async function resetSelectedSupabase(');
  const end=script.indexOf('\nasync function ',start+1);
  assert.ok(start>=0&&end>start);
  vm.runInContext(script.slice(start,end),ctx);
  return {ctx,calls,messages,busy,get reloads(){return reloads}};
}

test('reset sends only selected valid tickets and refreshes the list',async()=>{
  const f=setup(['one','error','missing']);
  await f.ctx.resetSelectedSupabase();
  assert.deepEqual(f.calls,[{url:'/api/manual-sync/reset',body:{event_ids:['one']}}]);
  assert.equal(f.reloads,1);
  assert.deepEqual(f.busy,[true,false]);
  assert.match(f.messages.at(-1).message,/1 phiếu về Chưa đẩy/);
});

test('empty selection never resets tickets using the current filter',async()=>{
  const f=setup([]);
  await f.ctx.resetSelectedSupabase();
  assert.equal(f.calls.length,0);
  assert.equal(f.messages.at(-1).tone,'warn');
});

test('failed reset restores controls and reports the error',async()=>{
  const f=setup(['one'],true);
  await f.ctx.resetSelectedSupabase();
  assert.equal(f.reloads,0);
  assert.deepEqual(f.busy,[true,false]);
  assert.equal(f.messages.at(-1).tone,'bad');
  assert.match(f.messages.at(-1).message,/Mất kết nối/);
});
