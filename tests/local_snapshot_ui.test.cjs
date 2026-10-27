const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('frontend/local-ocr.js','utf8');
function load(ctx,name){
 const tail=source.slice(source.search(new RegExp('(?:async )?function '+name+'\\(')));
 const next=tail.slice(1).search(/\n(?:async )?function /);
 vm.runInContext(next<0?tail.replace(/\nsetTimeout\(localTick,150\);[\s\S]*/,''):tail.slice(0,next+1),ctx);
}
function harness(){
 let now=1000,sequence=0;
 const messages=[],shown=[];
 const session={stationId:'station-01',cameraId:'camera-01',streamGeneration:1,deviceId:'usb',unit:'kg',ledRoi:null,
  stream:{},video:{readyState:4,paused:false,videoWidth:640,videoHeight:480,currentTime:1},preview:{},_localSource:'old-source'};
 const ctx=vm.createContext({current:()=>session,performance:{now:()=>now},crypto:{randomUUID:()=> 'source-'+(++sequence)},
  localOcrState:{fixedTwo:true,busy:false,sequence:0},captureStatus:{},panelMode:false,
  blocksCameraChange:()=>false,localEnabled:()=>true,localSetup(){},localRender(){},showVideo:()=>shown.push('live'),
  localShowSnapshot:(_s,image)=>shown.push(image),status:(_el,text)=>messages.push(text),
  api:async()=>({weight_found:true,weight:6.86,stable:false,manual_capture:true,live_token:'snapshot-token',snapshot_ttl_ms:600000}),
  document:{hidden:false,createElement:()=>({getContext:()=>({drawImage(){}}),toDataURL:()=> 'frozen-frame'})},setTimeout(){},$(){return{}},
 });
 for(const name of ['localKey','localSource','localInvalidate','localGetCapture','localTakeSnapshot','localResumeLive'])load(ctx,name);
 return {ctx,session,messages,shown,advance:ms=>{now+=ms}};
}
test('snapshot freezes immediately, before OCR returns, without changing any weight slot',async()=>{
 const {ctx,session,shown}=harness();let finish;
 ctx.api=()=>new Promise(resolve=>{finish=resolve});
 const pending=ctx.localTakeSnapshot();
 assert.equal(session._localSnapshot.image,'frozen-frame');assert.equal(session._localSnapshot.pending,true);
 assert.equal(shown.at(-1),session._localSnapshot);assert.equal(session.localLive,null);assert.equal(session.rounds,undefined);
 finish({weight_found:true,weight:6.86,stable:false,manual_capture:true,snapshot_ttl_ms:600000});await pending;
 assert.equal(ctx.localGetCapture(session).result.weight,6.86);
});
test('manual capture does not require live stability or a new camera frame after freezing',async()=>{
 const {ctx,session,advance}=harness();await ctx.localTakeSnapshot();advance(60000);
 assert.equal(ctx.localGetCapture(session).image,'frozen-frame');
 assert.equal(ctx.localGetCapture(session).result.stable,false);
 for(const change of ['used','roi','expired']){
  const before=session.ledRoi;
  if(change==='used')session._localSnapshot.used=true;
  if(change==='roi')session.ledRoi=[.1,.1,.9,.9];
  if(change==='expired')advance(600001);
  assert.throws(()=>ctx.localGetCapture(session),/chụp lại/);
  session._localSnapshot.used=false;session.ledRoi=before;
 }
});
test('resuming live or changing the camera invalidates a pending snapshot response',async()=>{
 for(const change of ['resume','camera']){
  const {ctx,session}=harness();let finish;
  ctx.api=()=>new Promise(resolve=>{finish=resolve});
  const pending=ctx.localTakeSnapshot();
  if(change==='resume')ctx.localResumeLive();else{session.streamGeneration++;ctx.localInvalidate(session)}
  finish({weight_found:true,weight:9.99});await pending;
  assert.equal(session.localLive,null);assert.equal(session._localSnapshot,null);
 }
});
test('failed OCR leaves the photo frozen for inspection and allows a retake',async()=>{
 const {ctx,session}=harness();ctx.api=async()=>{throw Error('timeout')};await ctx.localTakeSnapshot();
 assert.equal(session._localSnapshot.image,'frozen-frame');assert.equal(session._localSnapshot.pending,false);
 assert.equal(session._localSnapshot.error,'timeout');assert.equal(session.localLive,null);
 ctx.api=async()=>({weight_found:true,weight:13.04,snapshot_ttl_ms:600000});await ctx.localTakeSnapshot();
 assert.equal(ctx.localGetCapture(session).result.weight,13.04);
});
test('late live success or failure cannot replace a manual snapshot',async()=>{
 for(const failure of [false,true]){
  const {ctx,session}=harness();load(ctx,'localTick');let finish;
  ctx.api=()=>new Promise((resolve,reject)=>{finish=()=>failure?reject(Error('old timeout')):resolve({weight_found:true,weight:99})});
  const tick=ctx.localTick();
  const held={manualCapture:true,image:'keep-this-photo',result:{weight:6.86}};
  session._localSnapshot=held;session.localLive=held;session._localSource='new-source';
  finish();await tick;assert.equal(session.localLive,held);
 }
});
