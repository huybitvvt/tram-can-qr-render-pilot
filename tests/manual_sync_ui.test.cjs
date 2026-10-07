const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const html=fs.readFileSync('frontend/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
const line=name=>script.split('\n').find(value=>value.startsWith(name));

test('production list exposes date/shift/machine filters and push button',()=>{
  assert.match(html,/id="recordsFilterDate"/);
  assert.match(html,/id="recordsFilterShift"/);
  assert.match(html,/id="recordsFilterMachine"/);
  assert.match(html,/id="pushSupabaseBtn"/);
  assert.match(html,/Đẩy lên Supabase \(không Cloudinary\)/);
  assert.doesNotMatch(html,/Đồng bộ local → Supabase \/ Cloudinary/);
});

test('manual sync previews and sends the complete selected filter without Cloudinary',async()=>{
  const nodes={
    listDateFrom:{value:'2026-09-25'},listDateTo:{value:'2026-09-26'},
    listShift:{value:'12C1'},listQrCode:{value:'SP-001'},
    listMachine:{value:'Máy 11'},listProductionOrder:{value:'LSX-1'},
    manualSyncScope:{value:'production'},manualSyncStatus:{},
    manualSyncPreviewBtn:{disabled:false},manualSyncStartBtn:{disabled:false},
    pushSupabaseBtn:{disabled:false},recordsFilterBtn:{disabled:false},
    productionRecordsStatus:{hidden:true},
  };
  const requests=[];
  let confirmText='';
  const ctx=vm.createContext({
    $:id=>nodes[id],todayLocalDate:()=> '2026-09-26',daysAgoLocalDate:()=> '2026-08-27',
    status:()=>{},confirm:(message)=>{confirmText=String(message||'');return true},clearTimeout:()=>{},setTimeout:()=>1,
    workflowMode:'list',
    sourceContext:{date:'2026-09-26',shift:'12C1',machine:'Máy 11',order:'',bi:0.16},
    sourceLabel:()=>'label',
    api:async(path,options)=>{
      requests.push([path,JSON.parse(options.body)]);
      return path.endsWith('/preview')
        ?{total:2,counts:{measurements:2}}
        :{total:2,state:'running'};
    },
  });
  for(const name of [
    'function ensureListFilterDefaults(', 'function readListFilters(',
    'function listFilterLabel(', 'function productionSyncFilters(',
    'function manualSyncFilters(', 'function activeManualSyncFilters(',
    'function manualSyncCounts(', 'function setManualSyncRunning(',
    'function manualSyncStatusEl(',
    'async function previewManualSync(', 'async function startManualSync(',
  ]){
    const source=line(name);
    assert.ok(source,name);
    vm.runInContext(source,ctx);
  }
  vm.runInContext('let manualSyncTimer=0,manualSyncStatusHost="manualSyncStatus"',ctx);
  await ctx.startManualSync(false);
  assert.deepEqual(requests.map(([path])=>path),[
    '/api/manual-sync/preview','/api/manual-sync/start',
  ]);
  assert.deepEqual(requests[0][1],{
    date_from:'2026-09-25',date_to:'2026-09-26',shift:'12C1',
    qr_code:'SP-001',machine:'Máy 11',production_order:'LSX-1',scope:'production',
    skip_cloudinary:true,
  });
  assert.deepEqual(requests[1][1],requests[0][1]);
  assert.equal(nodes.manualSyncStartBtn.disabled,true);
  assert.match(confirmText,/Supabase/);
  assert.match(confirmText,/Dòng lỗi không được đẩy/);
  assert.match(confirmText,/Đang chờ theo bộ lọc/);
  assert.match(confirmText,/Không đẩy ảnh lên Cloudinary/);
  assert.doesNotMatch(confirmText,/Supabase \/ Cloudinary/);
});
