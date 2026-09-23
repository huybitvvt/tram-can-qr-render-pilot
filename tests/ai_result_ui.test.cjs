const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

async function analyzeWith(result){
 const messages=[],round={saved:false,weight:'',coreImage:''};
 const session={state:'review',rounds:[round],selectedSlot:{kind:'core',round:0},unit:'kg',stationId:'station-01',cameraId:'camera-01',preview:{},setState(state){this.state=state}};
 const ctx=vm.createContext({
  current:()=>session,persistSourceFromFields(){},ensureRounds:()=>session.rounds,nextCoreRound:()=>0,nextProductRound:()=>0,captureSlot:()=>session.selectedSlot,
  roundCoreReady:()=>false,renderControls(){},status:(_node,message)=>messages.push(message),captureStatus:{},
  captureVideo:()=>null,drawSession:()=> 'image',newEventId:()=> 'event-01',captureWeightBurst:async()=>[],showPreview(){},
  weightKindLabel:()=> 'cân lõi',appStatus:{weight_engine:'gemini'},recognitionProfile:{value:'fast'},recognitionProvider:{value:'gemini'},sourceContext:{shift:'HC1'},
  api:async()=>({...result,event_id:'event-01'}),parseBox:()=>null,qrDuplicateMessage:()=>'',captureQr:{value:''},weight:{value:''},productWeight:{value:''},unit:{value:'kg'},
  $:()=>null,renderRoundParams(){},updateBoxes(){},syncCaptureProductCodes(){},persistAiMissPhoto:async()=>({saved:true,synced:false}),
  advanceToNextCapture:()=>null,refreshCompletionState(){messages.push('Trạng thái hoàn tất')},weightsReady:()=>false,
  stopAiCountdown(){},performance:{now:()=>1000},
 });
 for(const name of ['validWeightValue','aiDetectedWeight']){
  const line=script.split('\n').find(line=>line.startsWith('function '+name+'('));
  assert.ok(line,name);vm.runInContext(line,ctx);
 }
 const start=script.indexOf("async function analyzeCurrent(kind='core')");
 vm.runInContext(script.slice(start,script.indexOf('\nasync function discardSlot(',start)),ctx);
 await ctx.analyzeCurrent('core');
 return{session,round,messages};
}

test('an AI weight remains visible when image quality fails',async()=>{
 const {session,round,messages}=await analyzeWith({weight_found:true,weight:7.03,quality_pass:false,step_saved:false,quality:{issues:['ảnh tối']},unit:'kg'});
 assert.equal(round.weight,'7.03');
 assert.equal(session.weight,'7.03');
 assert.match(messages.at(-1),/AI ĐÃ ĐỌC ĐƯỢC CÂN LÕI · 7.03 kg/);
 assert.match(messages.at(-1),/ảnh tối/);
});

test('an unreadable AI response leaves the weight empty',async()=>{
 const {round}=await analyzeWith({weight_found:false,weight:null,quality_pass:true,step_saved:false,quality:{issues:[]},unit:'kg'});
 assert.equal(round.weight,'');
});
