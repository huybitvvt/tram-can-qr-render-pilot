const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const source=script.split('\n').filter(line=>line.startsWith('async function loadStatus(')).at(-1);

test('cloud badge distinguishes automatic, manual, and unconfigured sync',async()=>{
  for(const [enabled,automatic,label] of [
    [true,true,'CLOUD: TỰ ĐẨY 10 PHÚT · AI RẢNH'],
    [true,false,'CLOUD: THỦ CÔNG'],
    [false,false,'CLOUD: CHƯA CẤU HÌNH'],
  ]){
    const nodes={};
    const ctx=vm.createContext({
      api:async()=>({sync_enabled:enabled,auto_sync:{enabled:automatic},stations:[]}),
      $:id=>nodes[id]??={childNodes:[{}],closest:()=>({})},
      stations:[],recognitionProvider:{value:'gemini'},recognitionProfile:{},
      buildStations(){},syncRecognitionSettings(){},wantsInventoryMode:()=>false,
      refreshCameraDevices:async()=>{},status(){},captureStatus:{},
    });
    vm.runInContext('let appStatus=null;'+source,ctx);
    await ctx.loadStatus();
    assert.equal(nodes.syncBadge.textContent,label);
    assert.equal(nodes.syncBadge.className,'mode '+(enabled?'ai':'off'));
  }
});
