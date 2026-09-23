const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const countdown=script.split('\n').find(line=>line.startsWith('async function waitBeforeCameraCapture('));

test('camera frame waits three seconds after Space countdown begins',async()=>{
  const timers=[],calls=[],session={box:{}},video={};
  const ctx=vm.createContext({
    current:()=>session,captureVideo:()=>video,sourceReady:()=>true,
    startAiCountdown:(_box,label,seconds)=>calls.push(['start',label,seconds]),
    stopAiCountdown:()=>calls.push(['stop']),
    status:()=>{},captureStatus:{},
    setTimeout:(callback,ms)=>{timers.push({callback,ms});return 1},
  });
  vm.runInContext(countdown,ctx);
  let finished=false;
  const pending=ctx.waitBeforeCameraCapture(session,'cân lõi').then(()=>{finished=true});
  await Promise.resolve();
  assert.equal(finished,false);
  assert.deepEqual(calls[0],['start','cân lõi',3]);
  assert.equal(timers[0].ms,3000);
  timers[0].callback();
  await pending;
  assert.equal(finished,true);
  assert.deepEqual(calls.at(-1),['stop']);
  const production=script.slice(script.indexOf("async function analyzeCurrent(kind='core')"),script.indexOf('async function discardSlot('));
  assert.match(production,/await waitBeforeCameraCapture\(session,weightKindLabel\(kind\)\);await waitForVideoFrame\(video\)\}image=drawSession\(session\)/);
});

test('camera change during countdown aborts capture',async()=>{
  const timers=[],session={box:{},streamGeneration:1},video={};
  let stopped=false;
  const ctx=vm.createContext({
    current:()=>session,captureVideo:()=>video,sourceReady:()=>true,
    startAiCountdown:()=>{},stopAiCountdown:()=>{stopped=true},
    status:()=>{},captureStatus:{},
    setTimeout:(callback,ms)=>{timers.push(callback);return 1},
  });
  vm.runInContext(countdown,ctx);
  const pending=ctx.waitBeforeCameraCapture(session,'cân sản phẩm');
  session.streamGeneration=2;
  timers[0]();
  await assert.rejects(pending,/Đã hủy chụp/);
  assert.equal(stopped,true);
});
