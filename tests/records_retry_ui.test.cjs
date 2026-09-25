const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(response){
  const calls=[],messages=[];
  const host={hidden:true};
  let reloads=0;
  const ctx=vm.createContext({
    $:()=>host,
    document:{createElement:tag=>({tag,children:[],appendChild(child){this.children.push(child)},addEventListener(_name,handler){this.click=handler}})},
    recordErrorStatus:()=> 'error',
    api:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return response(calls.length)},
    status:(_host,message,tone)=>messages.push({message,tone}),
    startAiCountdown(){},stopAiCountdown(){},
    loadRecords:async()=>{reloads++},
    optionalRecordWeight:value=>value==null?NaN:Number(value),
    formatRecordWeight:value=>Number.isFinite(value)?`${value} kg`:'--',
  });
  const retryStart=script.indexOf('async function retryProductionErrorRecord(');
  const retryEnd=script.indexOf('\nfunction appendProductionDeleteAction(',retryStart);
  assert.ok(retryStart>=0&&retryEnd>retryStart);
  vm.runInContext(script.slice(retryStart,retryEnd),ctx);
  for(const name of ['productionDeleteDetails','appendProductionDeleteAction']){
    const line=script.split('\n').find(value=>value.startsWith('function '+name+'(')||value.startsWith('async function '+name+'('));
    assert.ok(line,name);
    vm.runInContext(line,ctx);
  }
  return {ctx,calls,messages,get reloads(){return reloads}};
}

test('retry button rereads a saved photo and leaves an incomplete row marked as error',async()=>{
  const fixture=setup(()=>({promoted:false,core_weight:0.16,product_weight:null,qr_code:'',errors:{}}));
  const item={event_id:'draft-1',captured_at:'2026-09-25T03:31:12Z',error_only:true,reread_available:true,core_image_url:'/api/photo-draft-image?event_id=photo-1'};
  const row={children:[],appendChild(child){this.children.push(child)}};
  fixture.ctx.appendProductionDeleteAction(row,item,'error');
  const retry=row.children[0].children[0].children[0];
  assert.equal(retry.textContent,'Đọc lại');
  await retry.click();
  assert.equal(fixture.calls[0].url,'/api/measurements/retry-error');
  assert.equal(fixture.calls[0].body.event_id,'draft-1');
  assert.equal(fixture.reloads,1);
  assert.equal(fixture.messages.at(-1).tone,'warn');
  assert.equal(retry.disabled,false);
});

test('retry button reads both missing weights on an existing measurement',async()=>{
  const fixture=setup(call=>({item:{core_weight:0.16,product_weight:call===1?null:0.40,qr_code:'SP-001'}}));
  const item={event_id:'measurement-1',captured_at:'2026-09-25T03:31:12Z',error_only:false,qr_code:'SP-001',core_weight:null,product_weight:null,core_image_url:'/core',product_image_url:'/product',unit:'kg'};
  const row={children:[],appendChild(child){this.children.push(child)}};
  fixture.ctx.appendProductionDeleteAction(row,item,'error');
  await row.children[0].children[0].children[0].click();
  assert.deepEqual(fixture.calls.map(call=>call.body.kind),['core','product']);
  assert.equal(fixture.reloads,1);
  assert.equal(fixture.messages.at(-1).tone,'ok');
});
