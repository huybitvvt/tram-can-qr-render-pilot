const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const acorn=require('acorn');
const source=fs.readFileSync('frontend/local-ocr.js','utf8');
const tree=acorn.parse(source,{ecmaVersion:'latest'});

function harness(){
 const session={stationId:'station-01',cameraId:'camera-01',ledRoi:null,deviceId:'private-device-id',
  apiToken:'secret-token',rounds:[{qr:'private-ticket'}],localLive:{key:'current',image:'EXACT-OCR-INPUT',
  startedAt:900,roi:'0.1,0.2,0.8,0.9',fixedTwo:true,result:{weight:null,weight_found:false,stable:false,
  app_version:'0.2.0-rc93',reason:'ambiguous-leading-led',live_token:'private-live-token',
  observations:[{text:'110',confidence:.98,variant:'gray'}],secret:'private-result-secret'}}};
 const ctx=vm.createContext({performance:{now:()=>1000},Date,localKey:()=> 'current',
  localOcrState:{fixedTwo:false},current:()=>session});
 const node=tree.body.find(node=>node.type==='FunctionDeclaration'&&node.id.name==='localDiagnosticPayload');
 vm.runInContext(source.slice(node.start,node.end),ctx);
 return {ctx,session};
}

test('diagnostic preserves rejected OCR and its exact input without a ticket or auth data',()=>{
 const {ctx,session}=harness();
 const payload=JSON.parse(JSON.stringify(ctx.localDiagnosticPayload(session)));
 assert.equal(payload.image,'EXACT-OCR-INPUT');
 assert.equal(payload.result.weight,null);
 assert.equal(payload.result.reason,'ambiguous-leading-led');
 assert.deepEqual(payload.result.observations,[{text:'110',confidence:.98,variant:'gray'}]);
 assert.equal(payload.frame_age_ms,100);
 assert.equal(payload.fixed_two,true);
 const serialized=JSON.stringify(payload);
 for(const value of ['secret-token','private-ticket','private-device-id','private-live-token','private-result-secret'])assert.ok(!serialized.includes(value));
 assert.equal(session.rounds.length,1);
});

test('diagnostic refuses an image associated with old camera or ROI settings',()=>{
 const {ctx,session}=harness();session.localLive.key='old-camera';
 assert.throws(()=>ctx.localDiagnosticPayload(session),/khớp cấu hình/);
});

test('held frame is exported even after the live capture age limit',()=>{
 const {ctx,session}=harness();session.localLive.startedAt=-10000;session.localLive.manualCapture=true;
 const payload=ctx.localDiagnosticPayload(session);
 assert.equal(payload.mode,'snapshot');assert.equal(payload.frame_age_ms,11000);
 assert.equal(payload.image,'EXACT-OCR-INPUT');
});
