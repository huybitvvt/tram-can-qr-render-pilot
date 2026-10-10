const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function load(ctx,name){
 const line=script.split('\n').find(item=>item.startsWith('function '+name+'(')||item.startsWith('async function '+name+'('));
 assert.ok(line,name);
 vm.runInContext(line,ctx);
}

function setup(saveRoundEvidence){
 const session={state:'ready',roundCount:2,rounds:[
  {saved:false,coreImage:'core-1',productImage:'product-1',qr:'QR-1',weight:'1',productWeight:'2'},
  {saved:false,coreImage:'core-2',productImage:'',qr:'',weight:'',productWeight:''},
 ]};
 const messages=[];
 const ctx=vm.createContext({
  current:()=>session,persistEditor(){},renderControls(){},status:(_node,message)=>messages.push(message),captureStatus:{},console,newEventId:()=>'event-new',
  MAX_WEIGH_ROUNDS:4,DEFAULT_WEIGH_ROUNDS:2,selectedRoundCount:()=>session.roundCount,
  syncSessionAliases(){},nextCaptureStep:()=>({kind:'core',round:0}),renderEvidence(){},syncCaptureProductCodes(){},
  roundHasDuplicateQr:()=>false,roundQualityReady:()=>true,roundOverWeightLimit:()=>false,
  saveRoundEvidence,
 });
 for(const name of ['roundAiPending','sessionAiPending','emptyWeighRound','roundHasData','roundHasPhoto','roundHasBothImages','roundIsOpen','sessionRoundCount','ensureRounds','roundReadyToSave','roundCanSave','savableRoundIndexes','compactUnsavedRounds'])load(ctx,name);
 const start=script.indexOf('async function saveAllRounds(');
 vm.runInContext(script.slice(start,script.indexOf('\nsaveCapture=saveValidatedCapture;',start)),ctx);
 return {ctx,session,messages};
}

test('Enter saves only rounds with both images and moves the incomplete round to the top',async()=>{
 const calls=[];
 const {ctx,session,messages}=setup(async index=>{
  calls.push(index);
  assert.equal(session._saveAllLock,true);
  session.rounds[index].coreImage='';session.rounds[index].productImage='';session.rounds[index].qr='';
  session.rounds[index].weight='';session.rounds[index].productWeight='';
 });
 await ctx.saveAllRounds();
 assert.deepEqual(calls,[0]);
 assert.equal(session._saveAllLock,false);
 assert.equal(session.rounds[0].coreImage,'core-2');
 assert.equal(session.rounds[0].productImage,'');
 assert.equal(session.rounds[1].coreImage,'');
 assert.equal(session.rounds[1].productImage,'');
 assert.match(messages.at(-1),/ĐÃ LƯU 1 LẦN ĐỦ ẢNH/);
 assert.match(messages.at(-1),/đã dồn lên thành lần 1 và 2/);
});

test('a failed complete round stays at the top and the saved slot becomes empty below',async()=>{
 const calls=[];
 const {ctx,session,messages}=setup(async index=>{
  calls.push(index);
  if(index===1)return;
  session.rounds[index].coreImage='';session.rounds[index].productImage='';
  session.rounds[index].weight='';session.rounds[index].productWeight='';session.rounds[index].qr='';
 });
 session.rounds[1].productImage='product-2';
 await ctx.saveAllRounds();
 assert.deepEqual(calls,[0,1]);
 assert.equal(session.rounds[0].coreImage,'core-2');
 assert.equal(session.rounds[0].productImage,'product-2');
 assert.equal(session.rounds[1].coreImage,'');
 assert.match(messages.at(-1),/CHƯA LƯU ĐỦ: lần 2/);
});

test('unsaved rounds 3 and 4 become rounds 1 and 2',async()=>{
 const calls=[];
 const {ctx,session,messages}=setup(async index=>{
  calls.push(index);
  session.rounds[index].coreImage='';session.rounds[index].productImage='';
  session.rounds[index].weight='';session.rounds[index].productWeight='';session.rounds[index].qr='';
 });
 session.roundCount=4;
 session.rounds=[
  {saved:false,coreImage:'core-1',productImage:'product-1',qr:'QR-1',weight:'1',productWeight:'2'},
  {saved:false,coreImage:'core-2',productImage:'product-2',qr:'QR-2',weight:'1',productWeight:'2'},
  {saved:false,coreImage:'core-3',productImage:'',qr:'QR-3',weight:'3',productWeight:''},
  {saved:false,coreImage:'',productImage:'product-4',qr:'QR-4',weight:'',productWeight:'8'},
 ];
 await ctx.saveAllRounds();
 assert.deepEqual(calls,[0,1]);
 assert.equal(session.roundCount,4);
 assert.equal(session.rounds.length,4);
 assert.equal(session.rounds[0].qr,'QR-3');
 assert.equal(session.rounds[0].coreImage,'core-3');
 assert.equal(session.rounds[1].qr,'QR-4');
 assert.equal(session.rounds[1].productImage,'product-4');
 assert.equal(session.rounds[2].coreImage,'');
 assert.equal(session.rounds[2].productImage,'');
 assert.equal(session.rounds[3].coreImage,'');
 assert.equal(session.rounds[3].productImage,'');
 assert.match(messages.at(-1),/ô trống vẫn hiện ở phía sau/);
 assert.match(messages.at(-1),/Cuộn trong và Cuộn ngoài/);
});

test('Cuộn chờ stays in place while Cuộn ngoài still has data',()=>{
 const {ctx,session}=setup(async()=>{});
 session.roundCount=4;
 session.rounds=[
  {saved:false},
  {saved:false,coreImage:'ngoai',productImage:'',qr:'N',weight:'',productWeight:''},
  {saved:false,coreImage:'cho3',productImage:'',qr:'C3',weight:'',productWeight:''},
  {saved:false,coreImage:'cho4',productImage:'',qr:'C4',weight:'',productWeight:''},
 ];
 ctx.compactUnsavedRounds(session);
 assert.equal(session.rounds[0].coreImage,undefined);
 assert.equal(session.rounds[1].qr,'N');
 assert.equal(session.rounds[2].qr,'C3');
 assert.equal(session.rounds[3].qr,'C4');
});

test('clearing Cuộn trong and Cuộn ngoài promotes Cuộn chờ into those two slots',()=>{
 const {ctx,session}=setup(async()=>{});
 session.roundCount=4;
 session.rounds=[
  {saved:false},
  {saved:false},
  {saved:false,coreImage:'cho3',productImage:'',qr:'C3',weight:'',productWeight:''},
  {saved:false,coreImage:'cho4',productImage:'',qr:'C4',weight:'',productWeight:''},
 ];
 ctx.compactUnsavedRounds(session);
 assert.equal(session.rounds[0].qr,'C3');
 assert.equal(session.rounds[1].qr,'C4');
 assert.equal(session.rounds[2].coreImage,'');
 assert.equal(session.rounds[3].coreImage,'');
 assert.equal(session.roundCount,4);
});
