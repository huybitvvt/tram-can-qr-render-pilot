const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function load(ctx,names){
 for(const name of names){
  const line=script.split('\n').find(line=>line.startsWith('function '+name+'('));
  assert.ok(line,name);vm.runInContext(line,ctx);
 }
}

for(const [width,height] of [[1920,1080],[2560,1440],[3840,2160]]){
 test(`QR capture preserves camera detail at ${width}x${height}`,()=>{
  const draws=[],encodes=[],source={};
  const canvas={getContext:()=>({drawImage:(...args)=>draws.push(args)}),toDataURL:(...args)=>{encodes.push(args);return'image'}};
  const ctx=vm.createContext({captureSource:()=>source,sourceSize:()=>[width,height],CAPTURE_JPEG_QUALITY:.9,CAPTURE_MAX_EDGE:1600});
  load(ctx,['drawSession','drawQrSession']);
  ctx.drawQrSession({canvas});
  assert.equal(canvas.width,Math.min(width,2560));
  assert.equal(canvas.height,Math.round(height*Math.min(1,2560/width)));
  assert.deepEqual(encodes,[['image/jpeg',.96]]);
  assert.deepEqual(draws[0],[source,0,0,canvas.width,canvas.height]);
 });
}

test('live camera hides boxes measured on previous composite evidence',()=>{
 const positions=[],session={preview:{},video:{},qrBox:{},roiBox:{},roi:{inset:true},qrRoi:{old:true},configuredRoi:null};
 let source=session.video;
 const ctx=vm.createContext({current:()=>null,mediaGeometry:()=>({}),visibleSource:()=>source,panelMode:false,renderPanelOverlays(){},positionBox:(element,roi)=>positions.push([element,roi])});
 load(ctx,['updateBoxes']);
 ctx.updateBoxes(session);
 assert.equal(positions[0][1],null);
 assert.equal(positions[1][1],null);
 positions.length=0;source=session.preview;ctx.updateBoxes(session);
 assert.equal(positions[0][1],session.roi);
 assert.equal(positions[1][1],session.qrRoi);
 positions.length=0;source=session.video;session.configuredRoi={fixed:true};ctx.updateBoxes(session);
 assert.equal(positions[0][1],session.configuredRoi);
 assert.equal(positions[1][1],null);
});

test('a decoded duplicate remains distinguishable from an unreadable QR',()=>{
 const ctx=vm.createContext({qrDuplicateMessage:()=> 'TRÙNG MÃ QR · đã có trong danh sách'});
 load(ctx,['roundCode','roundQrNotice']);
 const round={qr:'',productAnalysis:{qr_found:true,qr_code:'MT-001',qr_decoder:'zxing'}},session={rounds:[round]};
 assert.match(ctx.roundQrNotice(session,0),/Đã đọc QR: MT-001.*TRÙNG MÃ QR/);
 round.productAnalysis={qr_found:false};
 assert.equal(ctx.roundQrNotice(session,0),'');
 round.productAnalysis={qr_conflict:true};
 assert.match(ctx.roundQrNotice(session,0),/xung đột/);
 round.qr='MANUAL-CORRECT';
 assert.equal(ctx.roundQrNotice(session,0),'');
});
