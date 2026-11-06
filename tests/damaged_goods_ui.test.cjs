const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('frontend/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function load(ctx,name){
 const start=script.search(new RegExp('(?:async )?function '+name+'\\('));assert.ok(start>=0,name);
 const tail=script.slice(start),next=tail.slice(1).search(/\n(?:async )?function /);
 vm.runInContext(next<0?tail:tail.slice(0,next+1),ctx);
}
function harness(){
 const session={stream:{},stationId:'station-01',cameraId:'camera-01'};
 const calls=[],messages=[];let id=0,snapshots=0;
 const ctx=vm.createContext({current:()=>session,workflowMode:'damaged',sourceContext:{date:'2026-10-29',shift:'HC1',machine:'TEST',order:''},
  captureStatus:{},localEnabled:()=>true,localKey:()=> 'settings',blocksCameraChange:()=>false,
  persistSourceFromFields(){},renderControls(){},renderDamaged(){},localInvalidate(){session._localSnapshot=null},loadRecords(){},
  newEventId:()=> 'event-'+(++id),status:(_,message)=>messages.push(message),
  localTakeSnapshot:async()=>{snapshots++;session._localSnapshot={key:'settings',image:'exact-image',source:'camera-source',result:{weight_found:true,weight:13.04,live_token:'snapshot-token'}}},
  api:async(path,options)=>{const payload=JSON.parse(options.body);calls.push({path,payload});return {local_saved:true,event_id:payload.event_id,damaged_kind:payload.damaged_kind,warehouse:'Kho hàng hỏng',product_weight:13.04}},
 });
 load(ctx,'damagedState');load(ctx,'captureDamaged');ctx.damagedState().kind='NKM';
 return {ctx,session,calls,messages,snapshots:()=>snapshots};
}

test('one click saves one photo without requesting a core, QR, or production pair',async()=>{
 const h=harness();await h.ctx.captureDamaged();
 assert.equal(h.snapshots(),1);assert.equal(h.calls.length,1);
 assert.equal(h.calls[0].path,'/api/local/damaged-capture');
 assert.equal(h.calls[0].payload.image,'exact-image');assert.equal(h.calls[0].payload.damaged_kind,'NKM');
 assert.equal(h.session.damaged.weight,'13.04');assert.equal(h.session.damaged.job,null);
 assert.ok(h.messages.some(m=>m.startsWith('ĐÃ LƯU LOCAL')));
});
test('network failure retries the same snapshot, category, context and event ID',async()=>{
 const h=harness(),api=h.ctx.api;let body;
 h.ctx.api=async(path,options)=>{body=options.body;throw Error('timeout')};
 await h.ctx.captureDamaged();assert.equal(h.session.damaged.weight,'');assert.ok(h.session.damaged.job);
 h.ctx.sourceContext.machine='DIFFERENT';h.ctx.localTakeSnapshot=()=>assert.fail('Must retry existing photo');
 h.ctx.api=async(path,options)=>{assert.equal(options.body,body);return api(path,options)};
 await h.ctx.captureDamaged();assert.equal(h.session.damaged.weight,'13.04');assert.equal(h.snapshots(),1);
});
test('weight and completion remain blank until a matching durable receipt arrives',async()=>{
 const h=harness();let resolve;
 h.ctx.api=()=>new Promise(yes=>resolve=yes);
 const pending=h.ctx.captureDamaged();await new Promise(yes=>setImmediate(yes));
 assert.equal(h.session.damaged.weight,'');assert.equal(h.session.damaged.saved,false);assert.equal(h.session._damagedBusy,true);
 resolve({local_saved:true,event_id:'wrong',damaged_kind:'NKM',warehouse:'Kho hàng hỏng',product_weight:99});await pending;
 assert.equal(h.session.damaged.weight,'');assert.ok(h.session.damaged.job);assert.equal(h.session._damagedBusy,false);
});
test('unreadable snapshots never create a ticket; camera setting changes never reuse an old job',async()=>{
 const h=harness();h.ctx.localTakeSnapshot=async()=>{h.session._localSnapshot={key:'settings',result:{weight_found:false}}};
 await h.ctx.captureDamaged();assert.equal(h.calls.length,0);assert.equal(h.session.damaged.job,null);
 h.session.damaged.job={key:'old-settings',payload:{image:'old'}};
 await h.ctx.captureDamaged();assert.equal(h.calls.length,0);
});
test('selected damaged rows force the correct warehouse and reject mixed goods',()=>{
 const ctx=vm.createContext({});load(ctx,'recordDamagedKind');load(ctx,'damagedWarehouse');
 const damaged={weight_raw:'DAMAGED_KIND=NKM; WAREHOUSE=Kho hàng hỏng'};
 assert.equal(ctx.damagedWarehouse([damaged]),'Kho hàng hỏng');
 assert.equal(ctx.damagedWarehouse([{qr_code:'SP_1'}]),'');
 assert.throws(()=>ctx.damagedWarehouse([damaged,{qr_code:'NKM_NORMAL'}]),/Đẩy riêng/);
});
test('the damaged mode presents exactly the three categories and the one-photo action',()=>{
 const panel=html.match(/<section id="damagedPanel"[\s\S]*?<\/section>/)[0];
 for(const kind of ['NKM','NC','RM'])assert.ok(panel.includes('<option>'+kind+'</option>'));
 assert.ok(panel.includes('Chụp và lưu hàng hỏng'));assert.ok(panel.includes('Kho hàng hỏng'));
 assert.ok(!panel.includes('analyzeCoreBtn'));
});
