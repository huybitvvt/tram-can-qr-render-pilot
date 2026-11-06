const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('frontend/roll-counter.js','utf8');
function load(ctx,name){
 const start=source.search(new RegExp('(?:async )?function '+name+'\\('));assert.ok(start>=0,name);
 const tail=source.slice(start),next=tail.slice(1).search(/\n(?:async )?function /);
 vm.runInContext(next<0?tail:tail.slice(0,next+1),ctx);
}
function harness(){
 const active={session_id:'counter-1',station_id:'station-1',camera_id:'camera-1',source:'video-1',settings:{fps:5}};
 const counter={active,running:true,paused:false,generation:1,sequence:0,sourceKind:'video',targetTime:0,job:null};
 const calls=[],messages=[],nodes={counterVideo:{duration:.4,currentTime:0},counterCount:{textContent:'0'},counterSpeed:{}};
 const ctx=vm.createContext({counter,performance:{now:()=>0},document:{hidden:false},$:id=>nodes[id],current:()=>({}),
  setTimeout,console,counterRender(){},counterDraw(){},counterStatus:message=>messages.push(message),
  counterSeek:async(video,time)=>{video.currentTime=time},counterFrameCanvas:()=>({toDataURL:()=> 'exact-image'}),
  api:async(path,options)=>{const payload=JSON.parse(options.body);calls.push({path,payload});return {local_saved:true,session_id:active.session_id,sequence:payload.sequence,count:payload.sequence,elapsed_ms:15,boxes:[],events:[]}},
  counterStop:async()=>{counter.running=false;counter.active=null},
 });
 load(ctx,'counterIdentity');load(ctx,'counterLoop');
 return {ctx,counter,calls,messages,nodes};
}

test('video samples advance only after an acknowledged frame and stop at EOF',async()=>{
 const h=harness();await h.ctx.counterLoop(1);
 assert.equal(h.calls.length,2);assert.deepEqual(h.calls.map(c=>c.payload.timestamp),[0,.2]);
 assert.equal(h.nodes.counterCount.textContent,'2');assert.equal(h.counter.active,null);
});
test('a failed frame stays available for an identical retry before video advances',async()=>{
 const h=harness(),api=h.ctx.api;let original;
 h.ctx.api=async(path,options)=>{original=options.body;throw Error('lost receipt')};
 await h.ctx.counterLoop(1);
 assert.equal(h.counter.targetTime,0);assert.ok(h.counter.job);assert.equal(h.counter.paused,true);
 h.ctx.api=async(path,options)=>{if(!h.calls.length)assert.equal(options.body,original);return api(path,options)};
 h.counter.paused=false;await h.ctx.counterLoop(1);
 assert.equal(h.nodes.counterCount.textContent,'2');assert.equal(h.calls.length,2);
});
test('a late counter response cannot change the screen after stop or a new run',async()=>{
 const h=harness();let finish;
 h.ctx.api=()=>new Promise(resolve=>finish=resolve);
 const pending=h.ctx.counterLoop(1);await new Promise(resolve=>setImmediate(resolve));
 h.counter.generation=2;h.counter.active=null;
 finish({local_saved:true,session_id:'counter-1',sequence:1,count:99,elapsed_ms:5,boxes:[]});await pending;
 assert.equal(h.nodes.counterCount.textContent,'0');
});
test('mismatched or nondurable results cannot populate the count',async()=>{
 for(const receipt of [{local_saved:false,session_id:'counter-1',sequence:1},{local_saved:true,session_id:'other',sequence:1},{local_saved:true,session_id:'counter-1',sequence:9}]){
  const h=harness();h.ctx.api=async()=>({...receipt,count:99});await h.ctx.counterLoop(1);
  assert.equal(h.nodes.counterCount.textContent,'0');assert.equal(h.counter.paused,true);assert.ok(h.counter.job);
 }
});
test('switching back to weighing waits for counter stop; startup cannot be abandoned',async()=>{
 const h=harness();load(h.ctx,'counterBeforeSwitch');let stopped=false;
 h.ctx.counterStop=async()=>{stopped=true;h.counter.active=null};
 assert.equal(await h.ctx.counterBeforeSwitch('production'),true);assert.equal(stopped,true);
 h.counter.starting=true;assert.equal(await h.ctx.counterBeforeSwitch('production'),false);
});
test('the UI identifies the experiment, offers image/video input and excludes automatic warehouse writes',()=>{
 const html=fs.readFileSync('frontend/index.html','utf8');
 assert.ok(html.includes('Đếm cuộn (thử)'));assert.ok(html.includes('id="counterVideoFile"'));
 assert.ok(html.includes('id="counterImageFile"'));assert.ok(html.includes('không tự tạo phiếu cân hoặc đẩy kho'));
 assert.ok(!source.includes('/api/capture'));assert.ok(!source.includes('/api/warehouse/'));
});
