const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/local-ocr.js','utf8');

function harness(){
 const ctx=vm.createContext({performance:{now:()=>1000},localOcrState:{fixedTwo:true},crypto:{randomUUID:()=> 'source'},current(){},api:async()=>{}});
 for(const name of ['localKey','localGetCapture','localCapturePayload','localClaimCapture']){
  const line=script.split('\n').find(line=>line.startsWith('function '+name+'(')||line.startsWith('async function '+name+'('));
  assert.ok(line,name);vm.runInContext(line,ctx);
 }
 const session={stationId:'station-01',cameraId:'camera-01',streamGeneration:1,deviceId:'usb',ledRoi:null,unit:'kg',stream:{},video:{readyState:4,paused:false}};
 session.localLive={key:ctx.localKey(session),image:'EXACT-READ-FRAME',startedAt:900,source:'source',roi:'auto',fixedTwo:true,result:{stable:true,weight:6.33,live_token:'frame-token'}};
 return{ctx,session};
}

test('Space returns the already-read frame and value with no image capture or OCR request',()=>{
 const {ctx,session}=harness();const live=ctx.localGetCapture(session);
 assert.equal(live.image,'EXACT-READ-FRAME');assert.equal(live.result.weight,6.33);
 const payload=ctx.localCapturePayload(session,live);
 assert.equal(payload.live_token,'frame-token');assert.equal(payload.recognition_provider,'rapidocr');
});

for(const kind of ['stale','camera','roi','decimal','stopped','paused','unstable'])test('Space refuses '+kind+' readings',()=>{
 const {ctx,session}=harness();
 if(kind==='stale')session.localLive.startedAt=-2000;
 if(kind==='camera')session.streamGeneration++;
 if(kind==='roi')session.ledRoi=[.1,.2,.3,.4];
 if(kind==='decimal')ctx.localOcrState.fixedTwo=false;
 if(kind==='stopped')session.stream=null;
 if(kind==='paused')session.video.paused=true;
 if(kind==='unstable')session.localLive.result.stable=false;
 assert.throws(()=>ctx.localGetCapture(session),/ổn định/);
});

test('capture lease carries the exact station camera round and frame token',async()=>{
 const {ctx,session}=harness();let request;
 ctx.api=async(path,options)=>{request={path,payload:JSON.parse(options.body)}};
 await ctx.localClaimCapture(session,session.localLive,'event','product',2);
 assert.deepEqual(request,{path:'/api/local/claim',payload:{station_id:'station-01',camera_id:'camera-01',source:'source',live_token:'frame-token',event_id:'event',kind:'product',round:2}});
});
