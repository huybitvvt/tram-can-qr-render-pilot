const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function setup(saveRoundEvidence){
 const session={state:'ready',rounds:[
  {saved:false,coreImage:'core-1',productImage:'product-1',qr:'QR-1'},
  {saved:false,coreImage:'core-2',productImage:'',qr:''},
 ]};
 const messages=[];
 const ctx=vm.createContext({current:()=>session,persistEditor(){},ensureRounds(){},sessionRoundCount:()=>2,
  roundCanSave:(_session,index)=>index===0,roundHasPhoto:round=>Boolean(round.coreImage||round.productImage),
  saveRoundEvidence,renderControls(){},status:(_node,message)=>messages.push(message),captureStatus:{},console});
 const start=script.indexOf('async function saveAllRounds(');
 vm.runInContext(script.slice(start,script.indexOf('\nsaveCapture=saveValidatedCapture;',start)),ctx);
 return {ctx,session,messages};
}

test('Enter save handles each complete or photo-only round once and clears its images',async()=>{
 const calls=[];
 const {ctx,session,messages}=setup(async index=>{
  calls.push(index);
  assert.equal(session._saveAllLock,true);
  session.rounds[index].coreImage='';session.rounds[index].productImage='';session.rounds[index].qr='';
 });
 await ctx.saveAllRounds();
 assert.deepEqual(calls,[0,1]);
 assert.equal(session._saveAllLock,false);
 assert.match(messages.at(-1),/ĐÃ LƯU TẤT CẢ 2 LẦN/);
});

test('a failed round retains its image while the other round is saved',async()=>{
 const calls=[];
 const {ctx,session,messages}=setup(async index=>{
  calls.push(index);
  if(index===1)return;
  session.rounds[index].coreImage='';session.rounds[index].productImage='';
 });
 await ctx.saveAllRounds();
 assert.deepEqual(calls,[0,1]);
 assert.equal(session.rounds[1].coreImage,'core-2');
 assert.match(messages.at(-1),/CHƯA LƯU ĐỦ: lần 2/);
});
