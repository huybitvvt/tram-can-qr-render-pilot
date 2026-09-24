const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script);
function setup(items=[]){
 const nodes={},messages=[];
 const session={state:'review',roundCount:1,unit:'kg',stateElement:{},rounds:[{eventId:'current',coreImage:'core',productImage:'product',coreAnalysis:{},productAnalysis:{},weight:'1.18',productWeight:'12.96',qr:'MT-TCN0013_D5NW9YJHA2T',errorStatus:'ok'}]};
 const ctx=vm.createContext({stations:[session],current:()=>session,MAX_WEIGH_ROUNDS:3,
  selectedRoundCount:()=>1,coreWeightOverLimit:()=>false,productWeightOverLimit:()=>false,
  $:id=>nodes[id]??=( {classList:{toggle(){}},setAttribute(){}} ),
  status:(_,message,tone)=>messages.push({message,tone}),captureStatus:{},
  syncCameraStatusPill:()=>{},
  sourceQuery:()=>'',api:async()=>({items}),syncCaptureProductCodes:()=>{},
  statusForPartialWeights:()=> 'Continue capturing',
 });
 const names=['sessionRoundCount','ensureRounds','validWeightValue','roundHasPhoto','roundCoreReady','roundProductReady','nextCaptureStep','roundQrId','roundCode','normalizeQrKey','rebuildProductionQrIndex','qrDuplicateMessage','markQrInputDuplicate','clearRoundQr','rejectDuplicateQr','verifyQrAgainstServer','roundHasDuplicateQr','roundReadyToSave','roundQualityReady','roundOverWeightLimit','sessionOverWeightLimit','roundCanSave','savableRoundIndexes','savedRoundCount'];
 vm.runInContext('let productionQrByCode={};',ctx);
 for(const name of names){const line=script.split('\n').find(line=>line.startsWith('function '+name+'(')||line.startsWith('async function '+name+'('));assert.ok(line,name);vm.runInContext(line,ctx)}
 ctx.renderControls=()=>{nodes.saveBtn={disabled:!ctx.savableRoundIndexes(session).length}};
 const start=script.indexOf('function refreshCompletionState(');
 vm.runInContext(script.slice(start,script.indexOf('\nfunction applyMappings(',start)),ctx);
 return {ctx,session,nodes,messages};
}
test('complete weights and QR enable save despite an unreadable photo draft',async()=>{
 const fixture=setup();const {ctx,session,nodes,messages}=fixture;
 const draft={event_id:'current',qr_code:session.rounds[0].qr,error_only:true};
 ctx.rebuildProductionQrIndex([draft]);ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);assert.equal(messages.at(-1).tone,'ok');
 ctx.api=async()=>({items:[draft]});
 assert.equal(await ctx.verifyQrAgainstServer(draft.qr_code,session,0),false);
 assert.equal(session.rounds[0].qr,draft.qr_code);
});
test('captured images and QR enable save when AI cannot read either weight',()=>{
 const {ctx,session,nodes,messages}=setup();const round=session.rounds[0];
 round.weight='';round.productWeight='';round.coreAnalysis=null;round.productAnalysis=null;
 ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);
 assert.equal(messages.at(-1).tone,'ok');
});
test('four captured images and defect reasons enable saving both unreadable rounds',()=>{
 const {ctx,session,nodes,messages}=setup();
 session.roundCount=2;
 session.rounds.push({...session.rounds[0],eventId:'second',coreImage:'core-2',productImage:'product-2',qr:'MT-TCN0013_SECOND'});
 for(const round of session.rounds){
  round.weight='';round.productWeight='';round.coreAnalysis=null;round.productAnalysis=null;
  round.errorStatus='error';round.errorReason='AI không đọc được số cân';
 }
 assert.equal(session.rounds.filter(round=>round.coreImage&&round.productImage).length,2);
 ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);
 assert.deepEqual(Array.from(ctx.savableRoundIndexes(session)),[0,1]);
 assert.equal(messages.at(-1).tone,'ok');
});
test('a completed measurement still blocks duplicate QR and explains why',()=>{
 const {ctx,session,nodes,messages}=setup();
 ctx.rebuildProductionQrIndex([{event_id:'saved',qr_code:session.rounds[0].qr}]);ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,true);assert.match(messages.at(-1).message,/TRÙNG MÃ QR/);
 assert.doesNotMatch(messages.at(-1).message,/Nhấn Enter|Đã chụp đủ 0/);
});
test('server duplicate rejection clears QR but still permits photo-backed save',async()=>{
 const {ctx,session,nodes,messages}=setup();const code=session.rounds[0].qr;
 ctx.api=async()=>({items:[{event_id:'saved',qr_code:code}]});
 assert.equal(await ctx.verifyQrAgainstServer(code,session,0),true);
 assert.equal(session.rounds[0].qr,'');
 assert.equal(nodes.saveBtn.disabled,false);assert.match(messages.at(-1).message,/TRÙNG MÃ QR/);
});
test('one photo with no QR or readable weights enables official save',()=>{
 const {ctx,session,nodes,messages}=setup();const round=session.rounds[0],code=round.qr;
 round.qr='';round.productImage='';round.weight='';round.productWeight='';round.errorStatus='error';
 ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);assert.deepEqual(Array.from(ctx.savableRoundIndexes(session)),[0]);
 assert.match(messages.at(-1).message,/phiếu cân chính thức/);
 round.coreImage='';ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,true);
 round.coreImage='core';round.productImage='product';round.qr=code;round.weight='1.18';round.productWeight='12.96';ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,true);assert.match(messages.at(-1).message,/Lý do lỗi/);
 round.errorReason='Damaged';ctx.refreshCompletionState(session);assert.equal(nodes.saveBtn.disabled,false);
});
test('official request keeps one photo and null weights with automatic error reason',()=>{
 const ctx=vm.createContext({validWeightValue:value=>String(value??'').trim()!==''&&Number(value)>=0,
  sourceRawTags:()=> 'SOURCE_DATE=2026-09-24',sourceContext:{date:'2026-09-24',shift:'HC1',machine:'M1',order:'',bi:'0.16'},
  normalizeBiWeight:()=>0.16,newEventId:()=> 'event-1',roundOwnsSessionBinding:()=>false});
 const start=script.indexOf('function captureBodyForRound(');
 vm.runInContext(script.slice(start,script.indexOf('\nasync function saveUnboundRound(',start)),ctx);
 const session={unit:'kg',stationId:'station-01',cameraId:'camera-01'};
 const round={eventId:'event-1',coreImage:'core-photo',productImage:'',weight:'',productWeight:'',qr:'',errorStatus:'ok',errorReason:''};
 const body=ctx.captureBodyForRound(session,round,0,false);
 assert.equal(body.image,'core-photo');assert.equal(body.product_image,'');
 assert.equal(body.qr_code,'');assert.equal(body.weight,null);assert.equal(body.product_weight,null);
 assert.equal(body.error_status,'error');assert.match(body.error_reason,/AI không đọc được cân lõi và cân sản phẩm/);
 assert.match(body.error_reason,/Chưa có ảnh cân sản phẩm/);
 assert.equal(body.require_complete_evidence,undefined);
 round.coreImage='';round.productImage='product-photo';round.productWeight='8.25';
 const productOnly=ctx.captureBodyForRound(session,round,0,false);
 assert.equal(productOnly.image,'');assert.equal(productOnly.product_image,'product-photo');
 assert.equal(productOnly.weight,null);assert.equal(productOnly.product_weight,8.25);
 assert.match(productOnly.weight_raw,/CORE_IMAGE_MISSING=1/);
});
test('an AI reading from a poor image may save when the weights are known',()=>{
 const {ctx,session,nodes,messages}=setup();const round=session.rounds[0];
 round.coreAnalysis={weight_found:true,weight:7.03,quality_pass:false};
 round.weight='7.03';ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);
 round.errorStatus='error';round.errorReason='Màn hình cân bị lóa';ctx.refreshCompletionState(session);
 assert.equal(nodes.saveBtn.disabled,false);
});
test('only one station is selected even with legacy multi-station configuration',()=>{
 const ctx=vm.createContext({assignedStationId:'',localStorage:{removeItem(){}},STATION_ASSIGNMENT_KEY:'station'});
 vm.runInContext(script.split('\n').find(line=>line.trim().startsWith('function assignedStationConfigs(')),ctx);
 const configs=[{station_id:'station-01'},{station_id:'station-02'}];
 assert.equal(ctx.assignedStationConfigs(configs).length,1);
 assert.equal(ctx.assignedStationConfigs(configs)[0].station_id,'station-01');
 ctx.assignedStationId='station-02';assert.equal(ctx.assignedStationConfigs(configs).length,1);
 ctx.assignedStationId='removed';assert.equal(ctx.assignedStationConfigs(configs)[0].station_id,'station-01');
});
test('clicking round status opens and focuses the reason, and toggling back clears it',()=>{
 const {ctx,session,nodes}=setup();let focused=0,scrolled=0,rendered=0;
 nodes.errorReason1={focus(){focused++},scrollIntoView(){scrolled++}};
 nodes.evidenceRounds={querySelector:()=>({focus(){}})};
 ctx.persistEditor=()=>{};ctx.renderEvidence=()=>{rendered++};
 const start=script.indexOf('function setRoundErrorStatus(');
 vm.runInContext(script.slice(start,script.indexOf('\nfunction fillInput(',start)),ctx);
 ctx.setRoundErrorStatus(0);
 assert.equal(session.rounds[0].errorStatus,'error');assert.equal(focused,1);assert.equal(scrolled,1);
 assert.equal(nodes.saveBtn.disabled,true);
 session.rounds[0].errorReason='Damaged';ctx.setRoundErrorStatus(0);
 assert.equal(session.rounds[0].errorStatus,'ok');assert.equal(session.rounds[0].errorReason,'');
 assert.equal(nodes.saveBtn.disabled,false);assert.equal(rendered,2);
 session.rounds[0].saved=true;ctx.setRoundErrorStatus(0);assert.equal(rendered,2);
 session.rounds[0].saved=false;session._saveLock=true;ctx.setRoundErrorStatus(0);assert.equal(rendered,2);
});
test('discarding a failed image preserves the other image and selects the discarded slot for retry',async()=>{
 const {ctx,session}=setup();const round=session.rounds[0],requests=[];
 Object.assign(ctx,{persistEditor(){},syncSessionAliases(){},renderEvidence(){},showVideo(){},console,
  api:async(path)=>{requests.push(path)},selectCaptureSlot(){},confirm:()=>true});
 for(const name of ['roundHasData','slotHasData','discardSlot'])vm.runInContext(script.split('\n').find(line=>line.startsWith('function '+name+'(')||line.startsWith('async function '+name+'(')),ctx);
 session.setState=(state)=>{session.state=state};session.eventId='current';
 round.weight='';round.coreAnalysis=null;round.corePhotoCaptureId='failed-core';round.errorStatus='error';round.errorReason='Cân lõi lỗi';
 await ctx.discardSlot('core',0);
 assert.equal(round.coreImage,'');assert.equal(round.corePhotoCaptureId,'');
 assert.equal(round.productImage,'product');assert.equal(round.productWeight,'12.96');
 assert.equal(round.errorStatus,'ok');assert.equal(round.errorReason,'');
 assert.equal(session.selectedSlot.kind,'core');assert.equal(session.selectedSlot.round,0);
 assert.equal(session.eventId,null);assert.equal(session._discardLock,false);
 assert.deepEqual(requests,['/api/session/discard']);
 round.errorStatus='error';round.errorReason='Cân sản phẩm lỗi';round.productPhotoCaptureId='failed-product';await ctx.discardSlot('product',0);
 assert.equal(round.productImage,'');assert.equal(round.productPhotoCaptureId,'');
 assert.equal(round.errorStatus,'ok');assert.equal(round.errorReason,'');
 assert.equal(session.selectedSlot.kind,'product');
});
