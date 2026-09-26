const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const script=fs.readFileSync('frontend/index.html','utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const line=name=>script.split('\n').find(value=>value.startsWith(name));

test('manual sync previews and sends the complete selected filter',async()=>{
  const nodes={
    listDateFrom:{value:'2026-09-25'},listDateTo:{value:'2026-09-26'},
    listShift:{value:'12C1'},listQrCode:{value:'SP-001'},
    listMachine:{value:'Máy 11'},listProductionOrder:{value:'LSX-1'},
    manualSyncScope:{value:'production'},manualSyncStatus:{},
    manualSyncPreviewBtn:{disabled:false},manualSyncStartBtn:{disabled:false},
  };
  const requests=[];
  const ctx=vm.createContext({
    $:id=>nodes[id],todayLocalDate:()=> '2026-09-26',daysAgoLocalDate:()=> '2026-08-27',
    status:()=>{},confirm:()=>true,clearTimeout:()=>{},setTimeout:()=>1,
    api:async(path,options)=>{
      requests.push([path,JSON.parse(options.body)]);
      return path.endsWith('/preview')
        ?{total:2,counts:{measurements:2}}
        :{total:2,state:'running'};
    },
  });
  for(const name of [
    'function ensureListFilterDefaults(', 'function readListFilters(',
    'function listFilterLabel(', 'function manualSyncFilters(',
    'function manualSyncCounts(', 'function setManualSyncRunning(',
    'async function previewManualSync(', 'async function startManualSync(',
  ])vm.runInContext(line(name),ctx);
  vm.runInContext('let manualSyncTimer=0',ctx);
  await ctx.startManualSync();
  assert.deepEqual(requests.map(([path])=>path),[
    '/api/manual-sync/preview','/api/manual-sync/start',
  ]);
  assert.deepEqual(requests[0][1],{
    date_from:'2026-09-25',date_to:'2026-09-26',shift:'12C1',
    qr_code:'SP-001',machine:'Máy 11',production_order:'LSX-1',scope:'production',
  });
  assert.deepEqual(requests[1][1],requests[0][1]);
  assert.equal(nodes.manualSyncStartBtn.disabled,true);
});
