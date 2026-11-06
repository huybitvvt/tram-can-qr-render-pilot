const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const local=fs.readFileSync('frontend/local-ocr.js','utf8');
const main=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
function load(ctx,source,name){
 const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert.ok(start>=0,name);
 const tail=source.slice(start),next=tail.slice(1).search(/\n(?:async )?function /);
 vm.runInContext(next<0?tail:tail.slice(0,next+1),ctx);
}
function harness(){
 let id=0;const calls=[],messages=[],round={eventId:'roll-1',qr:''};
 const session={stationId:'station-01',cameraId:'camera-01',unit:'kg',rounds:[round]};
 const ctx=vm.createContext({
  current:()=>session,newEventId:()=> 'capture-'+(++id),captureStatus:{},
  renderControls(){},renderEvidence(){},syncSessionAliases(){},advanceToNextCapture(){},refreshCompletionState(){},
  nextCaptureStep:()=>({kind:'product',round:0}),markWeightThresholdAlerts(){},weighSlotLabel:(kind,index)=>kind+index,
  syncCaptureProductCodes(){},qrDuplicateMessage:()=>'',console:{warn(){}},
  status:(_node,message)=>messages.push(message),
  api:async(path,options)=>{const body=JSON.parse(options.body);calls.push({path,body});
   if(path==='/api/decode')return new Promise(()=>{});
   return {local_saved:true,event_id:body.event_id,capture_id:body.capture_id,capture_kind:body.kind,capture_round:body.round,weight:6.86,quality_pass:true};
  },
 });
 load(ctx,local,'localCaptureSlot');load(ctx,local,'localDecodeCapturedQr');
 const capture={image:'exact-frame',source:'camera-source',key:'settings',result:{live_token:'stable-token',weight:6.86}};
 const context={date:'2026-10-24',machine:'MAY-1',order:'LSX-1',shift:'HC1'};
 return {ctx,session,round,calls,messages,capture,context};
}
test('local capture advances only after a durable local receipt and does not wait for QR',async()=>{
 const {ctx,session,round,calls,capture,context,messages}=harness();
 let resolve;ctx.api=async(path,options)=>{const body=JSON.parse(options.body);calls.push({path,body});if(path==='/api/decode')return new Promise(()=>{});return new Promise(yes=>{resolve=()=>yes({local_saved:true,event_id:body.event_id,capture_id:body.capture_id,capture_kind:body.kind,capture_round:body.round,weight:6.86,quality_pass:true})})};
 const pending=ctx.localCaptureSlot(session,capture,'core',0,context);
 assert.equal(round.weight,'');assert.equal(session._analyzeLock,true);assert.equal(session.selectedSlot,undefined);
 resolve();await pending;
 assert.equal(round.weight,'6.86');assert.equal(round.coreImage,'exact-frame');
 assert.equal(session.selectedSlot.kind,'product');assert.equal(session._analyzeLock,false);
 assert.deepEqual(calls.map(c=>c.path),['/api/local/capture','/api/decode']);
 assert.ok(messages.some(m=>m.startsWith('ĐÃ LƯU LOCAL')));
});
test('timeout retains the exact image and event ID for retry even when the live number changes',async()=>{
 const {ctx,session,round,calls,capture,context}=harness();
 const api=ctx.api;ctx.api=async(path,options)=>{calls.push({path,body:JSON.parse(options.body)});throw Error('timeout')};
 await ctx.localCaptureSlot(session,capture,'product',0,context);
 assert.equal(round.productWeight,'');assert.equal(session._analyzeLock,false);
 const first=calls[0].body;ctx.api=api;
 await ctx.localCaptureSlot(session,{...capture,image:'new-frame',result:{live_token:'different',weight:9}},'product',0,context);
 assert.deepEqual(calls[1].body,first);assert.equal(round.productImage,'exact-frame');
});
test('a mismatched local receipt never populates the weight or advances the selected slot',async()=>{
 const {ctx,session,round,capture,context}=harness();
 ctx.api=async()=>({local_saved:true,event_id:'another-roll'});
 await ctx.localCaptureSlot(session,capture,'core',0,context);
 assert.equal(round.weight,'');assert.equal(session.selectedSlot,undefined);assert.equal(session._analyzeLock,false);
});
test('late QR results cannot overwrite a replaced capture or an operator-entered code',async()=>{
 const {ctx,session,round}=harness();let resolve;
 ctx.api=()=>new Promise(yes=>resolve=yes);
 const job={image:'old-frame'};round.localCaptures={product:job};round.productImage='old-frame';
 const pending=ctx.localDecodeCapturedQr(session,round,'product',0,job);
 round.qr='MANUAL-QR';resolve({qr_code:'AUTO-QR'});await pending;assert.equal(round.qr,'MANUAL-QR');
 round.qr='';const replaced=ctx.localDecodeCapturedQr(session,round,'product',0,job);
 round.localCaptures.product={image:'replacement'};resolve({qr_code:'OLD-QR'});await replaced;assert.equal(round.qr,'');
});
test('a stalled OCR request times out and releases its HTTP request',async()=>{
 const ctx=vm.createContext({AbortController,fetch:()=>new Promise(()=>{}),setTimeout:fn=>setTimeout(fn,5),clearTimeout});
 load(ctx,main,'apiFetch');
 await assert.rejects(ctx.apiFetch('/api/local/live',{}),error=>error.code==='request_timeout');
});
test('QR validation before final save queries only the local database',()=>{
 const line=main.split('\n').find(l=>l.startsWith('async function verifyQrAgainstServer('));
 assert.match(line,/local_only=1&include_drafts=0/);
});
test('manual stop cancels a scheduled native camera recovery',()=>{
 const timers=[];let opened=0;
 const session={streamGeneration:1,stop(){this.streamGeneration++},setState(){}};
 const ctx=vm.createContext({current:()=>session,status(){},captureStatus:{},document:{hidden:false},
  blocksCameraChange:()=>false,openDefaultCamera:()=>opened++,setTimeout:fn=>timers.push(fn)});
 load(ctx,local,'localRecoverCamera');ctx.localRecoverCamera(session,Error('driver stalled'),1);
 session.stop();timers[0]();assert.equal(opened,0);
});
