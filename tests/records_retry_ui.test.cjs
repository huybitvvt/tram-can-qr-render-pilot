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
    document:{createElement(){return {children:[],hidden:false,dataset:{},classList:{toggle(){}},appendChild(child){this.children.push(child)},addEventListener(_name,handler){this.click=handler}}}},
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

function rereadButtons(row){
  const wrap=row.children[0].children[0];
  return {
    core:wrap.children[0].children[0],
    product:wrap.children[0].children[1],
    qr:wrap.children[1].children[0],
    weight:wrap.children[1].children[1],
    panel:wrap.children[1],
  };
}

test('core reread uses the saved core photo and leaves an incomplete row as an error',async()=>{
  const fixture=setup(()=>({promoted:false,core_weight:0.16,product_weight:null,qr_code:'',errors:{}}));
  const item={event_id:'draft-1',captured_at:'2026-09-25T03:31:12Z',error_only:true,reread_available:true,core_image_url:'/api/photo-draft-image?event_id=photo-1'};
  const row={children:[],appendChild(child){this.children.push(child)}};
  fixture.ctx.appendProductionDeleteAction(row,item,'error');
  const buttons=rereadButtons(row);
  assert.equal(buttons.core.textContent,'Ảnh lõi');
  assert.equal(buttons.product.textContent,'Ảnh SP');
  assert.equal(buttons.product.disabled,true);
  assert.equal(buttons.panel.hidden,true);
  await buttons.core.click();
  assert.equal(fixture.calls[0].url,'/api/measurements/retry-error');
  assert.equal(fixture.calls[0].body.event_id,'draft-1');
  assert.equal(fixture.calls[0].body.only,'core');
  assert.equal(fixture.reloads,1);
  assert.equal(fixture.messages.at(-1).tone,'warn');
  assert.equal(buttons.core.disabled,false);
  assert.equal(buttons.core.textContent,'Ảnh lõi');
});

test('product image opens QR or weight choices and each choice rereads only that field',async()=>{
  const fixture=setup(()=>({item:{core_weight:0.16,product_weight:0.40,qr_code:'SP-001'},read_qr_code:'ROLL-9'}));
  const item={event_id:'measurement-1',captured_at:'2026-09-25T03:31:12Z',error_only:false,qr_code:'SP-001',core_weight:0.16,product_weight:0.40,core_image_url:'/core',product_image_url:'/product',unit:'kg'};
  const row={children:[],appendChild(child){this.children.push(child)}};
  fixture.ctx.appendProductionDeleteAction(row,item,'error');
  const buttons=rereadButtons(row);
  assert.equal(buttons.qr.textContent,'Quét QR');
  assert.equal(buttons.weight.textContent,'Đọc số cân');
  assert.equal(buttons.panel.hidden,true);
  await buttons.product.click();
  assert.equal(fixture.calls.length,0);
  assert.equal(buttons.panel.hidden,false);
  await buttons.weight.click();
  await buttons.qr.click();
  assert.deepEqual(fixture.calls.map(call=>call.body.kind),['product','qr']);
  assert.equal(fixture.calls[0].body.image_url,'/product');
  assert.equal(fixture.calls[1].body.image_url,'/product');
  assert.equal(fixture.reloads,2);
});
