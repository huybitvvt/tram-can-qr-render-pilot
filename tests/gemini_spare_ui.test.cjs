const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);

function setup(handler){
 const nodes={sourceShift:{value:'12C2'},geminiSpareApiKeyInput:{value:'',type:'password',focus(){}},captureStatus:{}};
 const calls=[];let id=0;
 const gemini={switch_enabled:true,spare_configured:true,key_revision:'revision-1',day_key_id:'day',night_key_id:'night',spare_key_id:'spare'};
 const ctx=vm.createContext({$:name=>nodes[name]||(nodes[name]={}),sourceContext:{shift:'12C1'},captureStatus:nodes.captureStatus,
  appStatus:{weight_engine:'gemini',gemini},newEventId:()=> 'request-swap-'+String(++id).padStart(8,'0'),
  status:(node,message,tone)=>Object.assign(node,{message,tone}),
  api:async(url,options)=>{if(url==='/api/status')return ctx.appStatus;const body=JSON.parse(options.body);calls.push({url,body});return handler(url,body,calls.length)},
 });
 vm.runInContext('let geminiSwapBusy=false,geminiSwapPending=null,geminiSpareSaveBusy=false;',ctx);
 const start=script.indexOf('function syncGeminiBackupControls('),end=script.indexOf('\nfunction syncGeminiBackupWhenReady(',start);
 vm.runInContext(script.slice(start,end),ctx);
 const switchStart=script.indexOf('async function switchGeminiKey('),switchEnd=script.indexOf("\n$('geminiBackupKeyBtn').onclick",switchStart);
 vm.runInContext(script.slice(switchStart,switchEnd),ctx);
 return{ctx,nodes,calls,gemini};
}
const success=body=>({slot:body.shift==='12C2'?'night':'day',key_id:'spare',spare_key_id:'old-shift',key_revision:'revision-2',message:'Đã đổi key'});

test('swap uses the selected capture shift and updates role IDs',async()=>{
 const {ctx,calls,gemini,nodes}=setup((url,body)=>success(body));
 await ctx.switchGeminiKey();
 assert.equal(calls[0].body.shift,'12C2');assert.equal(calls[0].body.expected_revision,'revision-1');
 assert.equal(ctx.appStatus.gemini.night_key_id,'spare');assert.equal(ctx.appStatus.gemini.day_key_id,gemini.day_key_id);
 assert.equal(ctx.appStatus.gemini.spare_key_id,'old-shift');assert.equal(nodes.swapGeminiSpareBtn.disabled,false);
});

test('double click during a pending swap sends only one request',async()=>{
 let resolve;const pending=new Promise(done=>resolve=done);
 const {ctx,calls,nodes}=setup(()=>pending);
 const first=ctx.switchGeminiKey();await ctx.switchGeminiKey();
 assert.equal(calls.length,1);assert.equal(nodes.swapGeminiSpareBtn.disabled,true);
 resolve(success(calls[0].body));await first;
});

test('retry after lost response keeps the same request ID and original shift',async()=>{
 const {ctx,calls,nodes}=setup((url,body,count)=>{if(count===1)throw Error('network timeout');return success(body)});
 await ctx.switchGeminiKey();nodes.sourceShift.value='12C1';await ctx.switchGeminiKey();
 assert.deepEqual(calls[0].body,calls[1].body);
 assert.equal(nodes.swapGeminiSpareBtn.textContent,'Đổi sang key phụ');
});

test('stale revision ends pending request so the next click uses refreshed status',async()=>{
 const {ctx,calls}=setup((url,body,count)=>{if(count===1)throw Error('Cấu hình key đã thay đổi. Tải lại trang rồi thử lại.');return success(body)});
 await ctx.switchGeminiKey();ctx.appStatus.gemini.key_revision='revision-new';await ctx.switchGeminiKey();
 assert.notEqual(calls[0].body.swap_id,calls[1].body.swap_id);
 assert.equal(calls[1].body.expected_revision,'revision-new');
});

test('unconfigured spare prevents swap and tells the operator where to save it',async()=>{
 const {ctx,calls,nodes}=setup(()=>assert.fail('API should not be called'));
 ctx.appStatus.gemini.switch_enabled=false;await ctx.switchGeminiKey();
 assert.equal(calls.length,0);assert.match(nodes.captureStatus.message,/Cài đặt/);
});

test('saving spare clears the password field and never sends a shift key slot',async()=>{
 const {ctx,calls,nodes}=setup(()=>({message:'Đã lưu',key_id:'safe-id'}));
 nodes.geminiSpareApiKeyInput.value='fake-key-for-test-123456789';await ctx.saveGeminiSpareKey();
 assert.equal(calls[0].url,'/api/gemini/spare-key');
 assert.deepEqual(calls[0].body,{api_key:'fake-key-for-test-123456789'});
 assert.equal(nodes.geminiSpareApiKeyInput.value,'');assert.equal(nodes.geminiSpareApiKeyInput.type,'password');
 assert.equal(nodes.saveGeminiSpareKeyBtn.disabled,false);
});
