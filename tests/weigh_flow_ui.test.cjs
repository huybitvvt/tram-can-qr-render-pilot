const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=fs.readFileSync('frontend/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const start=script.indexOf('function roundCoreReady(');
const end=script.indexOf('function extraRoundTags(',start);
const ctx=vm.createContext({
  ensureRounds:session=>session.rounds,
  sessionRoundCount:()=>2,
  validWeightValue:value=>value!==''&&Number.isFinite(Number(value)),
});
vm.runInContext(script.slice(start,end),ctx);

test('default order is core 1, core 2, product 1, product 2',()=>{
  const session={rounds:[{},{}]};
  const next=()=>({...ctx.nextCaptureStep(session)});
  assert.deepEqual(next(),{kind:'core',round:0});
  Object.assign(session.rounds[0],{coreImage:'image',coreAnalysis:{},weight:'10.38'});
  assert.deepEqual(next(),{kind:'core',round:1});
  Object.assign(session.rounds[1],{coreImage:'image',coreAnalysis:{},weight:'11.20'});
  assert.deepEqual(next(),{kind:'product',round:0});
  Object.assign(session.rounds[0],{productImage:'image',productAnalysis:{},productWeight:'12.10'});
  assert.deepEqual(next(),{kind:'product',round:1});
});

test('product without core can be captured and does not block the other pair',()=>{
  const session={rounds:[{},{}]};
  assert.equal(ctx.nextProductRound(session),0);
  Object.assign(session.rounds[0],{productImage:'image',productAnalysis:{},productWeight:'12.10'});
  assert.deepEqual({...ctx.nextCaptureStep(session)},{kind:'core',round:1});
  assert.equal(ctx.nextProductRound(session),1);
});
