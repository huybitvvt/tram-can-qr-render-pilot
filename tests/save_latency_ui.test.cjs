const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}}
function setup(){
 const checks=[deferred(),deferred()],history=deferred(),calls=[],messages=[];
 const session={state:'ready',captureCount:0,rounds:[{eventId:'one',qr:'QR1'},{eventId:'two',qr:'QR2'}],stateElement:{},setState(state){this.state=state}};
 const nodes={saveBtn:{disabled:false},autoAdvance:{checked:false}};
 const ctx=vm.createContext({current:()=>session,stations:[session],$:id=>nodes[id]??={},
  persistEditor(){},persistSourceFromFields(){},sessionOverWeightLimit:()=>false,
  savableRoundIndexes:()=>[0,1],sourceContext:{order:'LSX'},sessionRoundCount:()=>2,
  roundCode:(s,i)=>s.rounds[i].qr,qrDuplicateMessage:()=>'',roundQrId:i=>'qr'+i,
  verifyQrAgainstServer:async(code,s,index)=>{calls.push('verify'+index);return checks[index].promise},
  renderControls(){nodes.saveBtn.disabled=!!session._saveLock},captureStatus:{},
  status:(_,message)=>messages.push(message),appStatus:{sync_enabled:true},
  saveMeasurementRound:async(s,r)=>{calls.push('save'+r.eventId);return {event_id:r.eventId,sync_status:'synced'}},
  productionQrByCode:{},normalizeQrKey:code=>code.toLowerCase(),
  loadRecords:()=>{calls.push('history');return history.promise},
  allRoundsSaved:s=>s.rounds.every(r=>r.saved),captureCount:0,
  prepareNextCapture:()=>calls.push('reset'),isAuthenticationRequired:()=>false,
  syncSessionAliases(){},nextCaptureStep:()=>null,savedRoundCount:s=>s.rounds.filter(r=>r.saved).length,
  renderEvidence(){},
 });
 const start=script.indexOf('async function saveValidatedCapture(){');
 vm.runInContext(script.slice(start,script.indexOf('\nsaveCapture=saveValidatedCapture;',start)),ctx);
 return {ctx,session,calls,checks,history,nodes,messages};
}
test('QR checks overlap, duplicate clicks are blocked, and history does not delay the next capture',async()=>{
 const {ctx,session,calls,checks,nodes}=setup();
 const pending=ctx.saveValidatedCapture();
 assert.deepEqual(calls,['verify0','verify1']);assert.equal(nodes.saveBtn.disabled,true);
 await ctx.saveValidatedCapture();assert.equal(calls.length,2);
 checks.forEach(c=>c.resolve(false));await pending;
 assert.deepEqual(calls,['verify0','verify1','saveone','savetwo','history','reset']);
 assert.equal(session._saveLock,false);assert.equal(ctx.productionQrByCode.qr1.eventId,'one');
});
test('a duplicate QR stops all writes and releases save lock',async()=>{
 const {ctx,session,calls,checks}=setup();const pending=ctx.saveValidatedCapture();
 checks[0].resolve(true);checks[1].resolve(false);await pending;
 assert.deepEqual(calls,['verify0','verify1']);assert.equal(session._saveLock,false);
});
test('partial save failure retains the remaining round and releases save lock',async()=>{
 const {ctx,session,calls,checks,messages}=setup();
 ctx.saveMeasurementRound=async(s,r)=>{if(r.eventId==='two')throw Error('Network failure');return {event_id:r.eventId,sync_status:'synced'}};
 const pending=ctx.saveValidatedCapture();checks.forEach(c=>c.resolve(false));await pending;
 assert.equal(session.rounds[0].saved,true);assert.equal(session.rounds[1].saved,undefined);
 assert.equal(session._saveLock,false);assert.equal(calls.includes('reset'),false);
 assert.match(messages.at(-1),/Network failure/);
});
