const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=require('./frontend_fixture.cjs').html().match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);

function load(ctx,name){
 const line=script.split('\n').find(line=>line.startsWith('function '+name+'('));
 assert.ok(line,name);vm.runInContext(line,ctx);
}
function deferred(){let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return{promise,resolve,reject}}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function setup({photoFailure=false,count=2}={}){
 let id=0,image=0;
 const photos=[],jobs=[],messages=[],nodes={},discards=[];
 const session={state:'review',roundCount:count,rounds:[],selectedSlot:{kind:'core',round:0},unit:'kg',stationId:'station-01',cameraId:'camera-01',preview:{},setState(state){this.state=state}};
 const sourceContext={date:'2026-10-10',shift:'12C1',machine:'Máy 1',order:'LSX-1'};
 const ctx=vm.createContext({
  current:()=>session,persistSourceFromFields(){},ensureRounds:()=>session.rounds,sessionRoundCount:()=>session.roundCount,nextCoreRound:()=>0,nextProductRound:()=>0,
  renderControls(){},renderEvidence(){},status:(node,message,tone)=>{node.textContent=message;node.className=tone;messages.push(message)},captureStatus:{},
  captureVideo:()=>null,drawQrSession:()=> 'photo-'+(++image),decodeClientQr:async()=>'',newEventId:()=> 'id-'+(++id),captureWeightBurst:async()=>[],showPreview(){},
  weightKindLabel:kind=>kind==='product'?'cân sản phẩm':'cân lõi',weighSlotLabel:(kind,index)=>kind+' '+index,
  appStatus:{weight_engine:'gemini'},recognitionProfile:{value:'fast'},recognitionProvider:{value:'gemini'},sourceContext,
  api:async(url,options)=>{
   const body=JSON.parse(options.body);
   if(url==='/api/session/discard'){discards.push(body);return{discarded:true}}
   if(url==='/api/photo-capture'){
    if(photoFailure)throw Error('disk full');
    photos.push(body);return {event_id:body.parent_event_id,capture_id:body.event_id,sync_status:'pending'};
   }
   assert.equal(url,'/api/analyze');
   assert.ok(photos.some(photo=>photo.image===body.image),'image must be committed before AI starts');
   const job={...deferred(),body,signal:options.signal};jobs.push(job);return job.promise;
  },
  parseBox:()=>null,qrDuplicateMessage:()=>'',captureQr:{value:''},weight:{value:''},productWeight:{value:''},unit:{value:'kg'},
  $:id=>nodes[id]||null,renderRoundParams(){},updateBoxes(){},syncCaptureProductCodes(){},
  advanceToNextCapture(){},refreshCompletionState(){},weightsReady:()=>false,markWeightThresholdAlerts(){},nextStillCaptureLabel:()=> 'ô tiếp theo',
  roundOverWeightLimit:()=>false,roundHasDuplicateQr:()=>false,roundQualityReady:()=>true,
  performance:{now:()=>1000},console,AbortController,persistEditor(){},selectCaptureSlot(){},showVideo(){},
 });
 for(const name of ['roundQrId','emptyWeighRound','slotAiPending','roundAiPending','sessionAiPending','ownsAiCapture','syncSessionAliases','roundCoreReady','roundProductReady','nextCaptureStep','captureSlot','validWeightValue','aiDetectedWeight','roundHasBothImages','roundReadyToSave','roundCanSave','compactUnsavedRounds'])load(ctx,name);
 session.rounds=Array.from({length:count},()=>ctx.emptyWeighRound());
 const queueStart=script.indexOf('const MAX_CAPTURE_AI_REQUESTS=');
 vm.runInContext(script.slice(queueStart,script.indexOf('\nfunction roundHasData(',queueStart)),ctx);
 for(const [startName,endName] of [['async function persistAiMissPhoto(','\nasync function analyzeCurrent('],["async function analyzeCurrent(kind='core')",'\nasync function discardSlot(']]){
  const start=script.indexOf(startName);vm.runInContext(script.slice(start,script.indexOf(endName,start)),ctx);
 }
 for(const name of ['roundHasData','slotHasData'])load(ctx,name);
 vm.runInContext(script.split('\n').find(line=>line.startsWith('async function discardSlot(')),ctx);
 const finish=(job,weight)=>job.resolve({event_id:job.body.event_id,weight_found:true,weight,quality_pass:true,step_saved:true,unit:'kg',evidence_image:'evidence-'+job.body.image});
 return {ctx,session,photos,jobs,messages,sourceContext,finish,nodes,discards};
}

test('two images commit while AI is pending and reverse results update their own slots',async()=>{
 const {ctx,session,photos,jobs,finish,messages}=setup();
 const first=ctx.analyzeCurrent('core');await tick();
 assert.equal(photos.length,1);assert.equal(session.rounds[0].coreAiPending,true);
 assert.equal(session._analyzeLock,false);assert.equal(session.selectedSlot.round,1);
 const second=ctx.analyzeCurrent('core');await tick();
 assert.equal(photos.length,2);assert.equal(jobs.length,2);
 assert.equal(session.rounds[1].coreAiPending,true);assert.equal(session.selectedSlot.kind,'product');
 assert.equal(session.selectedSlot.round,0);
 finish(jobs[1],0.62);await second;
 assert.equal(session.rounds[1].weight,'0.62');assert.equal(session.rounds[0].weight,'');
 assert.equal(session.rounds[0].coreAiPending,true);assert.equal(session.weight,'');
 finish(jobs[0],0.73);await first;
 assert.equal(session.rounds[0].weight,'0.73');assert.equal(session.weight,'0.73');
 assert.equal(session.rounds[1].coreImage,'evidence-photo-2');
 assert.equal(ctx.sessionAiPending(session),false);
 assert.ok(!messages.some(message=>message.startsWith('LỖI NHẬN DIỆN:')),messages.join('\n'));
});

test('a pending slot cannot be captured twice or saved and cannot move during compaction',async()=>{
 const {ctx,session,jobs,photos,finish}=setup();
 const first=ctx.analyzeCurrent('core');await tick();
 const round=session.rounds[0];round.productImage='existing-product';
 assert.equal(ctx.roundCanSave(session,0),false);
 session.selectedSlot={kind:'core',round:0};await ctx.analyzeCurrent('core');
 assert.equal(photos.length,1);assert.equal(jobs.length,1);
 session.rounds[1].saved=true;ctx.compactUnsavedRounds(session);
 assert.equal(session.rounds[0],round);
 finish(jobs[0],0.73);await first;assert.equal(ctx.roundCanSave(session,0),true);
});

test('replacing the round while AI runs makes its late result harmless',async()=>{
 const {ctx,session,jobs,finish}=setup();const first=ctx.analyzeCurrent('core');await tick();
 session.rounds[0]=ctx.emptyWeighRound();finish(jobs[0],0.73);await first;
 assert.equal(session.rounds[0].weight,'');assert.equal(session.rounds[0].coreImage,'');
});

test('AI completion does not release another camera capture lock',async()=>{
 const {ctx,session,jobs,finish,nodes}=setup();nodes.weight={value:''};const first=ctx.analyzeCurrent('core');await tick();
 session._analyzeLock=true;finish(jobs[0],0.73);await first;
 assert.equal(session._analyzeLock,true);assert.equal(session.rounds[0].coreAiPending,false);
 assert.equal(session.rounds[0].weight,'0.73');
 assert.equal(nodes.weight.value,'0.73');
});

test('controls allow the next capture while disabling only the pending slot and shared metadata',()=>{
 const {ctx,session,nodes}=setup();
 Object.assign(ctx,{
  $:id=>nodes[id]??={value:'',setAttribute(){},removeAttribute(){}},document:{querySelectorAll:()=>[]},
  sourceReady:()=>true,panelMode:false,panelScanBusy:false,sourceOrdersLoading:false,workflowMode:'production',
  blocksCameraChange:()=>false,inventoryState:()=>({}),inventoryHasData:()=>false,inventoryReady:()=>false,
 });
 load(ctx,'slotHasData');load(ctx,'renderControls');
 session.state='awaiting-weight';session.rounds[0].coreAiPending=true;session.rounds[0].coreImage='saved-photo';
 session.selectedSlot={kind:'core',round:1};ctx.renderControls();
 assert.equal(nodes.analyzeCoreBtn.disabled,false);assert.equal(nodes.photoOnlyBtn.disabled,false);
 assert.equal(nodes.testImageBtn.disabled,false);
 assert.equal(nodes.sourceShift.disabled,true);assert.equal(nodes.roundCount.disabled,true);
 assert.equal(nodes.weight.disabled,true);assert.equal(nodes.productWeight.disabled,false);
 session.selectedSlot={kind:'core',round:0};ctx.renderControls();
 assert.equal(nodes.analyzeCoreBtn.disabled,true);assert.equal(nodes.analyzeProductBtn.disabled,false);
 assert.equal(nodes.discardBtn.disabled,false);assert.equal(nodes.photoOnlyBtn.disabled,true);
 assert.equal(nodes.testImageBtn.disabled,true);
 session.rounds[0].coreAiPending=false;session.rounds[0].saved=true;ctx.renderControls();
 assert.equal(nodes.testImageBtn.disabled,true);
});

test('a running product can be discarded without waiting for AI or removing its core',async()=>{
 const {ctx,session,jobs,finish}=setup();
 const round=session.rounds[0];round.coreImage='keep-core';round.weight='0';
 const task=ctx.analyzeCurrent('product');await tick();
 assert.equal(round.productAiPending,true);await ctx.discardSlot('product',0);await task;
 assert.equal(jobs[0].signal.aborted,true);assert.equal(round.productAiPending,false);
 assert.equal(round.productAiRequestId,'');assert.equal(round.productImage,'');assert.equal(round.productWeight,'');
 assert.equal(round.coreImage,'keep-core');assert.equal(round.weight,'0');
 assert.equal(session.selectedSlot.kind,'product');assert.equal(session._discardLock,false);
 finish(jobs[0],99);await tick();assert.equal(round.productImage,'');assert.equal(round.productWeight,'');
});

test('an aborted core cannot overwrite its replacement or clear the other pending slot',async()=>{
 const {ctx,session,jobs,finish,discards}=setup();
 const old=ctx.analyzeCurrent('core');await tick();
 const round=session.rounds[0];const other=ctx.analyzeCurrent('core');await tick();
 await ctx.discardSlot('core',0);await old;
 assert.equal(round.coreAiPending,false);assert.equal(session.rounds[1].coreAiPending,true);
 assert.equal(discards[0].strict_event_id,true);
 assert.equal(round.coreImage,'');assert.equal(round.coreAiRequestId,'');
 const replacement=ctx.analyzeCurrent('core');await tick();
 finish(jobs[2],0.42);await replacement;const image=round.coreImage;
 jobs[0].reject(Error('late failure'));await tick();
 assert.equal(round.coreImage,image);assert.equal(round.weight,'0.42');
 finish(jobs[1],0.63);await other;assert.equal(session.rounds[1].weight,'0.63');
});

test('aborting a running request frees an HTTP slot even when its provider never replies',async()=>{
 const {ctx,session,jobs,finish}=setup({count:4}),tasks=[];
 for(let i=0;i<4;i++){tasks.push(ctx.analyzeCurrent('core'));await tick()}
 tasks.push(ctx.analyzeCurrent('product'));await tick();assert.equal(jobs.length,4);
 await ctx.discardSlot('core',0);await tasks[0];await tick();
 assert.equal(jobs[0].signal.aborted,true);assert.equal(jobs.length,5);
 assert.equal(session.rounds[0].productAiPending,true);
 for(let i=1;i<5;i++)finish(jobs[i],i+0.1);
 await Promise.all(tasks);assert.equal(vm.runInContext('captureAiActive',ctx),0);
});

test('discarding a queued request removes it without sending its photo to AI',async()=>{
 const {ctx,session,jobs,finish}=setup({count:4}),tasks=[];
 for(const kind of ['core','product'])for(let i=0;i<4;i++){tasks.push(ctx.analyzeCurrent(kind));await tick()}
 const cancelledImage=session.rounds[2].productImage;
 await ctx.discardSlot('product',2);await tasks[6];
 assert.equal(vm.runInContext('captureAiWaiters.length',ctx),3);
 for(let i=0;i<7;i++){assert.ok(jobs[i]);finish(jobs[i],i+0.1);await tick()}
 await Promise.all(tasks);
 assert.equal(jobs.length,7);assert.equal(jobs.some(job=>job.body.image===cancelledImage),false);
 assert.equal(session.rounds[2].productImage,'');assert.equal(vm.runInContext('captureAiActive',ctx),0);
});

test('trusted live captures bypass a busy local AI request queue',async()=>{
 const {ctx,jobs,photos,finish}=setup({count:4}), tasks=[];
 ctx.appStatus.weight_engine='local-yolo';
 for(let i=0;i<4;i++){tasks.push(ctx.analyzeCurrent('core'));await tick()}
 assert.equal(jobs.length,2);
 const fast=ctx.requestCaptureAi({...jobs[0].body,image:photos[0].image,live_capture_token:'server-token'},()=>true,'live-request');
 await tick();assert.equal(jobs.length,3);
 finish(jobs[2],0.42);await fast;
 assert.equal(vm.runInContext('captureAiActive',ctx),2);
 for(const index of [0,1,3,4]){finish(jobs[index],0.42);await tick()}
 await Promise.all(tasks);
 assert.equal(vm.runInContext('captureAiActive',ctx),0);
});

test('Space capture carries the image-bound token through photo save and result finalization',async()=>{
 const {ctx,session,jobs,photos,messages,finish}=setup();
 ctx.appStatus.weight_engine='local-yolo';session.backendMode=true;session.streamGeneration=3;
 const originalApi=ctx.api;
 ctx.api=async(path,options)=>path.startsWith('/api/live/snapshot?capture=1&reuse=1')
  ? {image:'live-image',recognition:{numeric_value:0.42},live_capture_token:'server-token'}
  : originalApi(path,options);
 ctx.captureWeightBurst=async()=>{throw Error('Live capture should not collect another burst')};
 const pending=ctx.analyzeCurrent('core');await tick();
 assert.equal(photos[0].image,'live-image');
 assert.equal(photos[0].live_capture_token,'server-token');
 assert.equal(jobs[0].body.live_capture_token,'server-token');
 assert.ok(!messages.some(message=>message.includes('đang chờ AI')),messages.join('\n'));
 finish(jobs[0],0.42);await pending;
 assert.equal(session.rounds[0].weight,'0.42');
});

test('live product captures needing a QR scan leave camera HTTP connections available',async()=>{
 const {ctx,jobs,photos,finish}=setup();
 ctx.appStatus.weight_engine='local-yolo';
 const tasks=Array.from({length:4},(_,index)=>{
  const image='pinned-'+index;photos.push({image});
  return ctx.requestCaptureAi({image,live_capture_token:'token-'+index,capture_kind:'product',client_qr_code:''},()=>true,'qr-'+index);
 });
 await tick();assert.equal(jobs.length,2);
 for(let index=0;index<4;index++){finish(jobs[index],13.04);await tick()}
 await Promise.all(tasks);
 assert.equal(vm.runInContext('captureAiActive',ctx),0);
});

test('discard invalidates pending results before waiting for backend cleanup',async()=>{
 const {ctx,session,jobs,finish}=setup(),cleanup=deferred(),original=ctx.api;
 ctx.api=(url,options)=>url==='/api/session/discard'?cleanup.promise:original(url,options);
 const task=ctx.analyzeCurrent('core');await tick();const discard=ctx.discardSlot('core',0);
 finish(jobs[0],0.8);await task;
 assert.equal(session.rounds[0].weight,'');assert.equal(session.rounds[0].coreAiPending,false);
 assert.equal(session._discardLock,true);
 cleanup.resolve({discarded:true});await discard;assert.equal(session.rounds[0].coreImage,'');
});

test('discard never cancels a saved roll or a database write',async()=>{
 const {ctx,session,jobs,finish}=setup();const task=ctx.analyzeCurrent('core');await tick();
 const round=session.rounds[0];round.saved=true;await ctx.discardSlot('core',0);
 assert.equal(jobs[0].signal.aborted,false);assert.equal(round.coreAiPending,true);
 round.saved=false;session._saveLock=true;await ctx.discardSlot('core',0);
 assert.equal(jobs[0].signal.aborted,false);session._saveLock=false;
 session._saveAllLock=true;await ctx.discardSlot('core',0);assert.equal(jobs[0].signal.aborted,false);
 session._saveAllLock=false;finish(jobs[0],0.4);await task;
});

test('failure to save the photo leaves it visible and never calls AI',async()=>{
 const {ctx,session,jobs,messages}=setup({photoFailure:true});
 session.rounds[0].weight='1.1';await ctx.analyzeCurrent('core');
 assert.equal(jobs.length,0);assert.equal(session._analyzeLock,false);
 assert.equal(session.rounds[0].coreImage,'photo-1');assert.equal(session.rounds[0].weight,'');
 assert.match(messages.at(-1),/CHƯA LƯU ĐƯỢC ẢNH: disk full/);
});

test('failed AI keeps its durable photo and capture metadata',async()=>{
 const {ctx,session,jobs,photos,messages,sourceContext}=setup();
 const first=ctx.analyzeCurrent('core');await tick();sourceContext.shift='12C2';
 jobs[0].reject(Error('provider unavailable'));await first;
 assert.equal(photos.length,1);assert.equal(photos[0].shift,'12C1');assert.equal(jobs[0].body.shift,'12C1');
 assert.equal(session.rounds[0].coreImage,'photo-1');assert.ok(session.rounds[0].corePhotoCaptureId);
 assert.equal(session.rounds[0].weight,'0');assert.match(session.rounds[0].analyzedRaw,/CORE_AUTO_ZERO=1/);
 assert.equal(session.rounds[0].coreAiPending,false);assert.match(messages.at(-1),/ẢNH ĐÃ ĐƯỢC LƯU ĐỘC LẬP/);
 assert.equal(session.rounds[0].saved,false);assert.match(messages.at(-1),/CHƯA LƯU PHIẾU/);
 assert.match(messages.at(-1),/Ảnh giữ ở ô cân phía trên/);assert.doesNotMatch(messages.at(-1),/vào Danh sách/);
});

test('all eight photos can save while only four AI HTTP requests remain open',async()=>{
 const {ctx,session,jobs,photos,finish,messages}=setup({count:4}),tasks=[];
 for(const kind of ['core','product'])for(let i=0;i<4;i++){tasks.push(ctx.analyzeCurrent(kind));await tick()}
 assert.equal(photos.length,8);assert.equal(jobs.length,4);
 assert.equal(session.rounds.filter(round=>round.coreAiPending&&round.productAiPending).length,4);
 for(let i=0;i<8;i++){
  assert.ok(jobs[i],'queued AI should start after a connection is released');
  finish(jobs[i],i+0.1);await tick();
 }
 await Promise.all(tasks);
 assert.equal(ctx.sessionAiPending(session),false);
 assert.ok(!messages.some(message=>message.startsWith('LỖI NHẬN DIỆN:')),messages.join('\n'));
});
