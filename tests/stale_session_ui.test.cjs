const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const functions=['discardCurrent','discardHydratedPending'].map(name=>{
  const line=script.split('\n').find(item=>item.startsWith('async function '+name+'('));
  assert.ok(line,name);
  return line;
}).join('\n');

test('camera stays locked until the recovered binding is cleared',()=>{
  const line=script.split('\n').find(item=>item.startsWith('function blocksCameraChange('));
  assert.ok(line);
  const ctx=vm.createContext({});
  vm.runInContext(line,ctx);
  const session={state:'error',hydratedPending:true,eventId:'old-event'};
  assert.equal(ctx.blocksCameraChange(session),true);
  session.hydratedPending=false;
  session.eventId=null;
  assert.equal(ctx.blocksCameraChange(session),false);
});

test('the Bỏ button is enabled for a recovered analysis with no browser photo',()=>{
  const line=script.split('\n').find(item=>item.startsWith('function renderControls('));
  assert.ok(line);
  const discard={disabled:true,title:'',setAttribute(){},removeAttribute(){}};
  const element={disabled:false,value:'',hidden:false};
  const session={state:'analyzing',hydratedPending:true,eventId:'old-event',rounds:[]};
  const ctx=vm.createContext({
    current:()=>session,
    appStatus:null,
    recognitionProvider:{value:'gemini'},
    recognitionProfile:{},
    sourceReady:()=>false,
    captureSlot:()=>({kind:'core',round:0}),
    document:{querySelectorAll:()=>[]},
    $:id=>id==='discardBtn'?discard:element,
    panelMode:false,
    panelScanBusy:false,
    sourceOrdersLoading:false,
    workflowMode:'production',
    blocksCameraChange:()=>true,
    inventoryState:()=>({}),
    inventoryHasData:()=>false,
    inventoryReady:()=>false,
  });
  vm.runInContext(line,ctx);
  ctx.renderControls();
  assert.equal(discard.disabled,false);
  assert.match(discard.title,/phiên cũ/);
});

function setup(remoteEventId){
  const session={stationId:'station-01',eventId:'old-event',hydratedPending:true,state:'analyzing',_discardLock:false};
  const calls=[];
  const ctx=vm.createContext({
    current:()=>session,
    confirm:()=>true,
    renderControls:()=>{},
    captureStatus:{},
    status:()=>{},
    api:async(path,options)=>{
      calls.push({path,options});
      if(path==='/api/status')return {stations:[{station_id:'station-01',event_id:remoteEventId}]};
      return {discarded:true};
    },
    clearReview:()=>{session.eventId=null;session.hydratedPending=false},
    openPrimaryCamera:async()=>{calls.push({path:'open-camera'})},
  });
  vm.runInContext(functions,ctx);
  return {ctx,session,calls};
}

test('a recovered pending session can be discarded and the camera reopens',async()=>{
  const {ctx,session,calls}=setup('old-event');
  await ctx.discardCurrent();
  const discard=calls.find(call=>call.path==='/api/session/discard');
  assert.ok(discard);
  assert.deepEqual(JSON.parse(discard.options.body),{
    station_id:'station-01',event_id:'old-event',strict_event_id:true,
  });
  assert.equal(session.eventId,null);
  assert.equal(session._discardLock,false);
  assert.equal(calls.at(-1).path,'open-camera');
});

test('discard does not remove a session replaced on the server',async()=>{
  const {ctx,session,calls}=setup('new-event');
  await ctx.discardCurrent();
  assert.equal(session.eventId,'old-event');
  assert.equal(session._discardLock,false);
  assert.equal(calls.some(call=>call.path==='/api/session/discard'),false);
  assert.equal(calls.some(call=>call.path==='open-camera'),false);
});
