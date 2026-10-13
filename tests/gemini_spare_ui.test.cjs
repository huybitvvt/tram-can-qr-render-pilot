const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);

function setup(handler){
 const nodes={sourceShift:{value:'12C2'},geminiSpareKeyPanel:{hidden:true},geminiSpareApiKeyInput:{value:'',type:'password',focus(){this.focused=true}},captureStatus:{}};
 const calls=[];let id=0;
 const gemini={switch_enabled:true,spare_configured:true,spare_change_enabled:true,key_revision:'revision-1',day_key_id:'day',night_key_id:'night',spare_key_id:'spare'};
 const ctx=vm.createContext({$:name=>nodes[name]||(nodes[name]={}),sourceContext:{shift:'12C1'},captureStatus:nodes.captureStatus,
  appStatus:{weight_engine:'gemini',gemini},newEventId:()=> 'request-swap-'+String(++id).padStart(8,'0'),
  status:(node,message,tone)=>Object.assign(node,{message,tone}),
  closeSettingsMenu:()=>{},bindActionButton:(name,handler)=>{(nodes[name]||(nodes[name]={})).onclick=handler},
  api:async(url,options)=>{if(url==='/api/status')return ctx.appStatus;const body=JSON.parse(options.body);calls.push({url,body});return handler(url,body,calls.length)},
 });
 vm.runInContext('let geminiSwapBusy=false,geminiSwapPending=null,geminiSpareSaveBusy=false;',ctx);
 const start=script.indexOf('function syncGeminiBackupControls('),end=script.indexOf('\nfunction syncGeminiBackupWhenReady(',start);
 vm.runInContext(script.slice(start,end),ctx);
 const switchStart=script.indexOf('async function switchGeminiKey('),switchEnd=script.indexOf("\n$('geminiBackupKeyBtn').onclick",switchStart);
 vm.runInContext(script.slice(switchStart,switchEnd),ctx);
 const actions=script.split('\n').filter(line=>/^bindActionButton\('(swapGeminiSpareBtn|useGeminiSpareKeyBtn|saveGeminiSpareKeyBtn)'/.test(line)||line.startsWith("$('geminiSpareKeyBtn').onclick="));
 vm.runInContext(actions.join('\n'),ctx);
 ctx.syncGeminiBackupControls();
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
 assert.equal(nodes.useGeminiSpareKeyBtn.disabled,true);assert.equal(nodes.geminiSpareKeyBtn.disabled,true);
 resolve(success(calls[0].body));await first;
});

test('retry after lost response keeps the same request ID and original shift',async()=>{
 const {ctx,calls,nodes}=setup((url,body,count)=>{if(count===1)throw Error('network timeout');return success(body)});
 await ctx.switchGeminiKey();nodes.sourceShift.value='12C1';await ctx.switchGeminiKey();
 assert.deepEqual(calls[0].body,calls[1].body);
 assert.equal(nodes.swapGeminiSpareBtn.textContent,'Dùng key');
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

test('Dùng key applies the stored spare without opening the editor or sending typed replacement text',async()=>{
 const {ctx,calls,nodes}=setup((url,body)=>success(body));
 nodes.geminiSpareApiKeyInput.value='unsaved-replacement-key';
 await nodes.useGeminiSpareKeyBtn.onclick();
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/gemini/key-slot');
 assert.equal('api_key' in calls[0].body,false);
 assert.equal(nodes.geminiSpareKeyPanel.hidden,true);assert.equal(nodes.geminiSpareApiKeyInput.focused,undefined);
 assert.equal(ctx.appStatus.gemini.night_key_id,'spare');
 assert.equal(nodes.geminiSpareSummary.textContent,'Đã lưu · Mã key: old-shift');
});

test('Đổi key only opens and focuses the replacement editor without activating or saving any key',()=>{
 const {calls,nodes}=setup(()=>assert.fail('Editing must not call the API'));
 nodes.geminiSpareKeyBtn.onclick();
 assert.equal(calls.length,0);assert.equal(nodes.geminiSpareKeyPanel.hidden,false);
 assert.equal(nodes.geminiKeyPanel.hidden,true);assert.equal(nodes.geminiBackupKeyPanel.hidden,true);
 assert.equal(nodes.geminiSpareApiKeyInput.focused,true);
});

test('first-time setup disables Dùng key until save succeeds, then uses it without entering it again',async()=>{
 const fixture=setup((url,body)=>{
  if(url==='/api/gemini/spare-key'){
   Object.assign(fixture.ctx.appStatus.gemini,{spare_configured:true,switch_enabled:true,spare_key_id:'first-spare',key_revision:'saved-revision'});
   return{message:'Đã lưu',key_id:'first-spare'};
  }
  return success(body);
 });
 const {ctx,calls,nodes}=fixture;
 Object.assign(ctx.appStatus.gemini,{spare_configured:false,switch_enabled:false,spare_key_id:null});ctx.syncGeminiBackupControls();
 assert.equal(nodes.useGeminiSpareKeyBtn.disabled,true);assert.equal(nodes.geminiSpareKeyBtn.disabled,false);
 nodes.geminiSpareKeyBtn.onclick();nodes.geminiSpareApiKeyInput.value='fake-first-spare-key-123456789';
 await nodes.saveGeminiSpareKeyBtn.onclick();
 assert.equal(nodes.geminiSpareApiKeyInput.value,'');assert.equal(nodes.geminiSpareKeyPanel.hidden,true);
 assert.equal(nodes.useGeminiSpareKeyBtn.disabled,false);assert.match(nodes.captureStatus.message,/Bấm Dùng key/);
 await nodes.useGeminiSpareKeyBtn.onclick();
 assert.deepEqual(calls.map(call=>call.url),['/api/gemini/spare-key','/api/gemini/key-slot']);
 assert.equal(calls[1].body.expected_revision,'saved-revision');assert.equal('api_key' in calls[1].body,false);
});

test('saving a replacement blocks activation and editing until the save finishes',async()=>{
 let resolve;const pending=new Promise(done=>resolve=done);
 const {ctx,calls,nodes}=setup(()=>pending);
 nodes.geminiSpareApiKeyInput.value='fake-replacement-key-123456789';
 const save=ctx.saveGeminiSpareKey();await ctx.switchGeminiKey();
 assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/gemini/spare-key');
 assert.equal(nodes.useGeminiSpareKeyBtn.disabled,true);assert.equal(nodes.swapGeminiSpareBtn.disabled,true);assert.equal(nodes.geminiSpareKeyBtn.disabled,true);
 resolve({message:'Đã lưu',key_id:'new-spare'});await save;
 assert.equal(nodes.useGeminiSpareKeyBtn.disabled,false);assert.equal(nodes.geminiSpareKeyBtn.disabled,false);
});
