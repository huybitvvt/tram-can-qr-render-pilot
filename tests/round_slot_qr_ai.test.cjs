const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const line=script.split('\n').find(item=>item.startsWith('function targetQrInput('));

test('scanner targets the selected round 3 or 4 instead of the first empty QR',()=>{
 const nodes={captureQr:{id:'captureQr'},captureQr2:{id:'captureQr2'},captureQr3:{id:'captureQr3'},captureQr4:{id:'captureQr4'}};
 const session={roundCount:4,selectedSlot:{kind:'product',round:3},rounds:[{qr:'QR-1'},{qr:'QR-2'},{qr:''},{qr:''}]};
 const ctx=vm.createContext({
  $:id=>nodes[id]||null,
  ensureRounds:item=>item.rounds,
  captureSlot:()=>session.selectedSlot,
  roundQrId:index=>index===0?'captureQr':'captureQr'+(index+1),
  roundCode:(item,index)=>String(item.rounds[index].qr||''),
  firstMissingCodeInput:()=>nodes.captureQr3,
 });
 vm.runInContext(line,ctx);
 assert.equal(ctx.targetQrInput(session),nodes.captureQr4);
 session.selectedSlot={kind:'core',round:2};
 assert.equal(ctx.targetQrInput(session),nodes.captureQr3);
 session.rounds[3].qr='QR-4';
 session.selectedSlot={kind:'product',round:3};
 assert.equal(ctx.targetQrInput(session),nodes.captureQr3);
});

test('AI capture stays on the selected round even when the button kind differs',()=>{
 assert.match(script,/selectedIndex>=0\?selectedIndex/);
});
