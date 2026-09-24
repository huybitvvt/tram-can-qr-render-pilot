const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(api){
 const round={eventId:'parent-1',corePhotoCaptureId:'',corePhotoRequestId:'',coreImage:'core-photo'};
 const session={stationId:'station-01',cameraId:'camera-01'};
 const ctx=vm.createContext({persistSourceFromFields(){},api,newEventId:()=> 'capture-1',sourceContext:{date:'2026-09-24',shift:'HC1',machine:'MÁY BAO BÌ 16',order:'LSX-1'}});
 const start=script.indexOf('async function persistAiMissPhoto(');
 vm.runInContext(script.slice(start,script.indexOf('\nasync function analyzeCurrent(',start)),ctx);
 return {ctx,round,session};
}

test('AI failure keeps an independent photo draft before the official save',async()=>{
 const requests=[];
 const {ctx,round,session}=setup(async(url,options)=>{
  requests.push({url,body:JSON.parse(options.body)});
  return {capture_id:'capture-1',sync_status:'pending'};
 });
 const result=await ctx.persistAiMissPhoto(session,round,'core',0,round.coreImage,'','parent-1');
 assert.equal(result.saved,true);
 assert.equal(requests.length,1);
 assert.equal(requests[0].url,'/api/photo-capture');
 assert.equal(requests[0].body.parent_event_id,'parent-1');
 assert.equal(requests[0].body.capture_kind,'core');
 assert.equal(round.corePhotoCaptureId,'capture-1');
 assert.equal(round.coreImage,'core-photo');
});

test('failed photo draft write retains its capture ID and image for retry',async()=>{
 const requestIds=[];
 const {ctx,round,session}=setup(async(_url,options)=>{
  requestIds.push(JSON.parse(options.body).event_id);
  if(requestIds.length===1)throw Error('Disk temporarily unavailable');
  return {capture_id:'capture-1',sync_status:'pending'};
 });
 const first=await ctx.persistAiMissPhoto(session,round,'core',0,round.coreImage,'','parent-1');
 assert.equal(first.saved,false);
 assert.equal(round.corePhotoCaptureId,'');
 assert.equal(round.corePhotoRequestId,'capture-1');
 assert.equal(round.coreImage,'core-photo');
 const second=await ctx.persistAiMissPhoto(session,round,'core',0,round.coreImage,'','parent-1');
 assert.equal(second.saved,true);
 assert.deepEqual(requestIds,['capture-1','capture-1']);
 assert.equal(round.corePhotoCaptureId,'capture-1');
});
