const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(api){
 const round={eventId:'parent-1',saved:false,coreImage:'data:image/jpeg;base64,Y29yZQ==',productImage:'',corePhotoCaptureId:'',productPhotoCaptureId:'',qr:''};
 const session={state:'awaiting-weight',stateElement:{},rounds:[round,{eventId:'parent-2',saved:false,coreImage:'other-photo',productImage:'',qr:'QR-2'}],stationId:'station-01',cameraId:'camera-01'};
 const messages=[];let nextId=0;
 const ctx=vm.createContext({current:()=>session,ensureRounds:()=>session.rounds,sessionRoundCount:()=>2,
  persistEditor(){},persistSourceFromFields(){},roundCanSave:()=>false,renderControls(){},renderEvidence(){},refreshCompletionState(){},syncSessionAliases(){},showPostCaptureSource(){},syncCaptureProductCodes(){},syncCameraStatusPill(){},
  status:(_node,message)=>messages.push(message),captureStatus:{},api,loadRecords:async()=>{},console,
  newEventId:()=> `capture-${++nextId}`,sourceContext:{date:'2026-09-24',shift:'HC1',machine:'MÁY BAO BÌ 16',order:'LSX-1'},
 });
 let start=script.indexOf('async function persistAiMissPhoto(');
 vm.runInContext(script.slice(start,script.indexOf('\nasync function analyzeCurrent(',start)),ctx);
 for(const name of ['emptyWeighRound','resetWeighRound']){
  const line=script.split('\n').find(line=>line.startsWith('function '+name+'('));
  assert.ok(line,name);vm.runInContext(line,ctx);
 }
 start=script.indexOf('function clearSavedRoundAfterLocalWrite(');
 vm.runInContext(script.slice(start,script.indexOf('\nasync function saveValidatedCapture(',start)),ctx);
 start=script.indexOf('async function saveRoundEvidence(');
 vm.runInContext(script.slice(start,script.indexOf('\nsaveCapture=saveValidatedCapture;',start)),ctx);
 return {ctx,session,round,messages};
}

test('one core image saves independently while product image and AI result are empty',async()=>{
 const requests=[];
 const {ctx,session,round,messages}=setup(async(url,options)=>{
  requests.push({url,body:JSON.parse(options.body)});
  return {capture_id:'capture-1',sync_status:'pending'};
 });
 await ctx.saveRoundEvidence(0);
 assert.equal(requests.length,1);
 assert.equal(requests[0].url,'/api/photo-capture');
 assert.equal(requests[0].body.capture_kind,'core');
 assert.equal(requests[0].body.capture_round,0);
 assert.equal(requests[0].body.parent_event_id,'parent-1');
 assert.equal(round.corePhotoCaptureId,'');
 assert.equal(round.coreImage,'');
 assert.equal(round.eventId,'capture-2');
 assert.equal(round.saved,false);
 assert.equal(session.rounds[1].coreImage,'other-photo');
 assert.equal(session.rounds[1].qr,'QR-2');
 assert.match(messages.at(-1),/ĐÃ LƯU 1 ẢNH CHỜ/);
 await ctx.saveRoundEvidence(0);
 assert.equal(requests.length,1);
});

test('a failed photo write keeps the image and retries with the same capture ID',async()=>{
 const requestIds=[];
 const {ctx,round,messages}=setup(async(_url,options)=>{
  requestIds.push(JSON.parse(options.body).event_id);
  if(requestIds.length===1)throw Error('Disk temporarily unavailable');
  return {capture_id:'capture-1',sync_status:'pending'};
 });
 await ctx.saveRoundEvidence(0);
 assert.equal(round.corePhotoCaptureId,'');
 assert.equal(round.corePhotoRequestId,'capture-1');
 assert.ok(round.coreImage);
 assert.match(messages.at(-1),/CHƯA LƯU ĐỦ ẢNH/);
 await ctx.saveRoundEvidence(0);
 assert.deepEqual(requestIds,['capture-1','capture-1']);
 assert.equal(round.corePhotoCaptureId,'');
 assert.equal(round.coreImage,'');
});
