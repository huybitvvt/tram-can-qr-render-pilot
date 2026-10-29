'use strict';
const counter={active:null,running:false,paused:false,generation:0,sequence:0,sourceKind:'camera',fileUrl:'',image:null,job:null,inFlight:null,targetTime:0,lastFrame:-1,lastResult:null,drawing:false};
function counterCameraKey(session){return [session.stationId,session.cameraId,session.streamGeneration,session.deviceId,session._nativeSource||''].join('|')}
function counterIdentity(){const active=counter.active;return active?{session_id:active.session_id,station_id:active.station_id,camera_id:active.camera_id,source:active.source}:{}}
function counterConfig(){return{detector:$('counterDetector').value,direction:$('counterDirection').value,line:Number($('counterLine').value)/100,roi:['counterX1','counterY1','counterX2','counterY2'].map(id=>Number($(id).value)/100),confidence:Number($('counterConfidence').value),min_area:Number($('counterArea').value)/100,fps:Number($('counterFps').value)}}
function counterStatus(message,kind='warn'){status($('counterStatus'),message,kind)}
function counterRender(){
 if(!$('counterPanel'))return;
 const active=Boolean(counter.active),locked=active||Boolean(counter.starting)||Boolean(counter.loading);
 for(const id of ['counterDetector','counterDirection','counterLine','counterConfidence','counterArea','counterFps','counterX1','counterY1','counterX2','counterY2','counterVideoFile','counterImageFile','counterCameraBtn','counterRoiBtn'])$(id).disabled=locked;
 $('counterStartBtn').disabled=locked||counter.sourceKind==='image';
 $('counterPauseBtn').disabled=!active;$('counterPauseBtn').textContent=counter.paused?'Tiếp tục':'Tạm dừng';
 $('counterStopBtn').disabled=!active;
 for(const id of ['localCameraBackend','localCameraIndex','localStopCamera','localSelectLed','localAutoLed'])if($(id))$(id).disabled=active;
 $('counterSourceLabel').textContent=counter.sourceKind==='video'?'Video đã chọn':counter.sourceKind==='image'?'Ảnh tĩnh · chỉ thử nhận diện':'Camera hiện tại';
 $('counterHint').textContent=$('counterDetector').value==='rfdetr'?'RF-DETR Nano COCO chưa huấn luyện riêng cho cuộn xưởng. Chỉ chọn vùng ra máy có cuộn; kiểm tra khung nhận diện trước khi tin số đếm.':'Camera phải cố định. Để trống vùng ra máy trong khoảng 2 giây đầu cho học nền. Người hoặc vật khác đi qua vùng cũng có thể bị đếm.';
}
function counterDraw(frame,result){
 const canvas=$('counterCanvas');if(!frame)return;
 canvas.width=frame.width||frame.videoWidth;canvas.height=frame.height||frame.videoHeight;
 const context=canvas.getContext('2d');context.drawImage(frame,0,0,canvas.width,canvas.height);
 const config=counter.active?.settings||counterConfig(),[x1,y1,x2,y2]=config.roi,w=canvas.width,h=canvas.height;
 context.lineWidth=3;context.strokeStyle='#eab308';context.strokeRect(x1*w,y1*h,(x2-x1)*w,(y2-y1)*h);
 context.strokeStyle='#38bdf8';context.beginPath();
 if(['right','left'].includes(config.direction)){context.moveTo(config.line*w,y1*h);context.lineTo(config.line*w,y2*h)}
 else{context.moveTo(x1*w,config.line*h);context.lineTo(x2*w,config.line*h)}context.stroke();
 context.font='bold 16px sans-serif';
 for(const item of result?.boxes||[]){const [a,b,c,d]=item.box;context.strokeStyle='#22c55e';context.strokeRect(a*w,b*h,(c-a)*w,(d-b)*h);context.fillStyle='#052e16';context.fillRect(a*w,Math.max(0,b*h-23),120,23);context.fillStyle='#fff';context.fillText('#'+item.id+' · '+Math.round(item.score*100)+'%',a*w+4,Math.max(17,b*h-5))}
}
function counterFrameCanvas(source){
 const width=source.videoWidth||source.naturalWidth||source.width,height=source.videoHeight||source.naturalHeight||source.height;
 if(!width||!height)throw Error('Nguồn chưa có hình.');
 const scale=Math.min(1,768/Math.max(width,height)),canvas=document.createElement('canvas');canvas.width=Math.round(width*scale);canvas.height=Math.round(height*scale);canvas.getContext('2d').drawImage(source,0,0,canvas.width,canvas.height);return canvas;
}
async function counterLoadFile(file,kind){
 if(!file||counter.active||counter.loading)return;
 counter.loading=true;counterRender();
 try{
 const session=current();if(session?.stream){session.stop();session.setState('idle','Đang dùng file thử · camera đã dừng','')}
 if(counter.fileUrl)URL.revokeObjectURL(counter.fileUrl);
 counter.fileUrl=URL.createObjectURL(file);counter.sourceKind=kind;counter.image=null;counter.targetTime=0;counter.lastResult=null;
 if(kind==='video'){
  const video=$('counterVideo');video.pause();video.src=counter.fileUrl;
  await new Promise((resolve,reject)=>{video.onloadeddata=resolve;video.onerror=()=>reject(Error('Không mở được video. Thử MP4 H.264.'));video.load()});
  counterDraw(counterFrameCanvas(video));counterStatus('Đã nạp video. Chọn vùng/hướng ra rồi bấm Bắt đầu. Video được xử lý theo thời gian nguồn, không tua vòng.','ok');
 }else{
  counter.image=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>reject(Error('Không đọc được ảnh.'));image.src=counter.fileUrl});
  const canvas=counterFrameCanvas(counter.image);counterDraw(canvas);counterStatus('Đang thử RF-DETR trên ảnh…');
  const session=current(),result=await api('/api/counter/detect',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({...counterConfig(),station_id:session.stationId,camera_id:session.cameraId,image:canvas.toDataURL('image/jpeg',.92)})});
  counter.lastResult=result;counterDraw(canvas,result);$('counterCount').textContent='0';
  counterStatus('Ảnh tĩnh: '+result.boxes.length+' vùng vật thể · '+result.elapsed_ms+' ms. Số đếm qua vạch = 0; cần video để đếm.','ok');
 }
 }finally{counter.loading=false;counterRender()}
}
async function counterUseCamera(){
 if(counter.active)return;counter.sourceKind='camera';counter.image=null;
 if(counter.fileUrl)URL.revokeObjectURL(counter.fileUrl);counter.fileUrl='';$('counterVideo').pause();$('counterVideo').removeAttribute('src');
 await openDefaultCamera(current());counterRender();counterPreviewCamera();
}
function counterPreviewCamera(){
 if(workflowMode!=='counter'||counter.active||counter.sourceKind!=='camera')return;
 const session=current(),source=session?._nativeCanvas||session?.video;
 if(session?.stream&&source&&(session._nativeCanvas||source.readyState>=2)){try{counterDraw(counterFrameCanvas(source))}catch{}}
}
async function counterStart(){
 const session=current();if(!session||counter.active||counter.starting||workflowMode!=='counter')return;
 try{
  counter.starting=true;counterRender();
  if(counter.sourceKind==='camera'&&!session.stream)await openDefaultCamera(session);
  if(workflowMode!=='counter'||session!==current())return;
  if(counter.sourceKind==='camera'&&(!session.stream||session.video.readyState<2))throw Error('Mở camera và chờ hình trước khi bắt đầu.');
  if(counter.sourceKind==='video'&&!Number.isFinite($('counterVideo').duration))throw Error('Chọn video có thời lượng xác định trước khi bắt đầu.');
  persistSourceFromFields();counter.starting=true;counterRender();counterStatus('Đang mở bộ đếm offline…');
  const source=crypto.randomUUID(),config=counterConfig();
  const payload={...config,station_id:session.stationId,camera_id:session.cameraId,source,source_kind:counter.sourceKind,machine:sourceContext.machine};
  // Starting twice with this same source is idempotent on the backend.
  let active;try{active=await api('/api/counter/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})}catch(first){active=await api('/api/counter/start',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)})}
  counter.active=active;counter.cameraKey=counterCameraKey(session);session._counterRunning=true;
  renderControls();
  counter.sequence=0;counter.targetTime=0;counter.lastFrame=-1;counter.job=null;counter.paused=false;counter.running=true;counter.generation++;
  $('counterCount').textContent=String(active.count);counterStatus('Đang đếm thử. Vật thể phải đi từ phía trước sang phía sau vạch theo hướng đã chọn.');
  void counterLoop(counter.generation);
 }catch(error){counterStatus(error.message,'bad')}
 finally{counter.starting=false;counterRender()}
}
async function counterSeek(video,position){
 if(Math.abs(video.currentTime-position)<.001&&video.readyState>=2)return;
 await new Promise((resolve,reject)=>{const timer=setTimeout(()=>{video.removeEventListener('seeked',done);reject(Error('Video không trả frame mới.'));},5000);function done(){clearTimeout(timer);resolve()}video.addEventListener('seeked',done,{once:true});video.currentTime=position});
}
async function counterLoop(generation){
 while(counter.running&&counter.active&&!counter.paused&&generation===counter.generation){
  const started=performance.now();
  try{
   const session=current();
   if(counter.sourceKind==='camera'&&(counterCameraKey(session)!==counter.cameraKey||!session.stream||session._nativeSource&&performance.now()-session._nativeLastFrame>1800))throw Error('Camera đã đổi hoặc mất hình. Dừng lượt đếm; kiểm tra nguồn rồi mở lượt mới.');
   if(document.hidden&&counter.sourceKind==='camera'){counter.paused=true;counterStatus('Đã tạm dừng khi cửa sổ bị ẩn. Kiểm tra đoạn bỏ lỡ trước khi tiếp tục.');break}
   if(!counter.job){
    let source,timestamp;
    if(counter.sourceKind==='video'){
     source=$('counterVideo');if(counter.targetTime>=source.duration-.001){await counterStop();counterStatus('Đã xử lý hết video. Kết quả lưu trên máy.','ok');return}
     await counterSeek(source,counter.targetTime);timestamp=source.currentTime;
    }else{
     source=session._nativeCanvas||session.video;timestamp=performance.now()/1000;
     const frameKey=session._nativeSource?session._nativeSequence:session.video.currentTime;
     if(frameKey===counter.lastFrame){await new Promise(resolve=>setTimeout(resolve,80));continue}counter.lastFrame=frameKey;
    }
    const canvas=counterFrameCanvas(source);counter.job={canvas,payload:{...counterIdentity(),sequence:++counter.sequence,timestamp,image:canvas.toDataURL('image/jpeg',.92)}};
   }
   const job=counter.job;
   counter.inFlight=api('/api/counter/frame',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(job.payload)});
   const result=await counter.inFlight;
   if(generation!==counter.generation||!counter.active)return;
   if(!result.local_saved||result.session_id!==counter.active.session_id||result.sequence!==job.payload.sequence)throw Error('Xác nhận bộ đếm không khớp frame.');
   counter.lastResult=result;counterDraw(job.canvas,result);$('counterCount').textContent=String(result.count);
   $('counterSpeed').textContent=result.elapsed_ms+' ms/frame';
   counterStatus(result.warmup?'Đang học nền: giữ camera cố định và vùng ra máy trống…':result.interrupted?'Nguồn bị gián đoạn; đã khởi tạo lại theo dõi, giữ tổng cũ. Không tự bù đoạn bỏ lỡ.':'Đang đếm thử · '+result.boxes.length+' vật thể theo dõi. Kiểm tra số thực trước khi sử dụng.',result.warmup||result.interrupted?'warn':'ok');
   counter.job=null;
   if(counter.sourceKind==='video')counter.targetTime+=1/counter.active.settings.fps;
  }catch(error){counter.paused=true;counterStatus(error.message+' Bấm Tiếp tục để thử lại đúng frame; Dừng để kết thúc lượt.','bad')}
  finally{counter.inFlight=null;counterRender()}
  if(counter.sourceKind==='camera')await new Promise(resolve=>setTimeout(resolve,Math.max(0,1000/(counter.active?.settings.fps||5)-(performance.now()-started))));
 }
 counterRender();
}
async function counterPause(){
 if(!counter.active)return;
 counter.paused=!counter.paused;counterRender();
 if(counter.paused){counterStatus('Đã tạm dừng. Tổng đã ghi local được giữ.');return}
 if(counter.inFlight){await counter.inFlight.catch(()=>{});if(!counter.paused)return}
 void counterLoop(counter.generation);
}
async function counterStop(){
 if(!counter.active)return;
 counter.running=false;counter.paused=true;counter.generation++;
 const identity=counterIdentity();
 try{
  if(counter.inFlight)await counter.inFlight.catch(()=>{});
  const result=await api('/api/counter/stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(identity)});
  $('counterCount').textContent=String(result.count);counterStatus('Đã dừng · '+result.count+' lượt qua vạch. Kết quả lưu local.','ok');
 }catch(error){counterStatus('Chưa xác nhận dừng: '+error.message,'bad');throw error}
 finally{
  if(current())current()._counterRunning=false;
  counter.active=null;counter.job=null;counterRender();void counterHistory();renderControls();
 }
}
async function counterBeforeSwitch(mode){
 if(counter.starting||counter.loading)return false;
 if(mode!=='counter'&&counter.active){try{await counterStop()}catch{return false}}
 return true;
}
async function counterHistory(){
 try{
  const data=await api('/api/counter/history'),host=$('counterHistory');host.replaceChildren();
  for(const item of data.items||[]){const row=document.createElement('tr');for(const value of [new Date(item.started_at).toLocaleString('vi-VN'),item.machine||'--',item.count,item.settings.detector==='rfdetr'?'RF-DETR Nano':'Chuyển động']){const cell=document.createElement('td');cell.textContent=String(value);row.appendChild(cell)}const cell=document.createElement('td'),button=document.createElement('button');button.textContent='Tải CSV';button.type='button';button.onclick=()=>counterExport(item.session_id).catch(error=>counterStatus(error.message,'bad'));cell.appendChild(button);row.appendChild(cell);host.appendChild(row)}
 }catch(error){counterStatus('Không đọc được lịch sử đếm: '+error.message,'bad')}
}
async function counterExport(identity){
 const token=readSessionToken(),response=await apiFetch('/api/counter/export?session_id='+encodeURIComponent(identity),{headers:token?{Authorization:'Bearer '+token}:{}});
 if(!response.ok)throw Error('Không xuất được kết quả bộ đếm.');
 const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download='dem-cuon-'+identity+'.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
function counterSelectRoi(){
 if(counter.active)return;counter.drawing=!counter.drawing;$('counterCanvas').style.cursor=counter.drawing?'crosshair':'';counterStatus(counter.drawing?'Kéo trên hình để chọn vùng chỉ có cuộn đi ra.':'Đã hủy chọn vùng.');
}
function counterSetup(){
 bindActionButton('counterModeBtn',()=>switchWorkflow('counter'));
 bindActionButton('counterStartBtn',()=>counterStart());bindActionButton('counterPauseBtn',()=>counterPause());bindActionButton('counterStopBtn',()=>counterStop());bindActionButton('counterCameraBtn',()=>counterUseCamera());bindActionButton('counterRoiBtn',()=>counterSelectRoi());bindActionButton('counterHistoryBtn',()=>counterHistory());
 for(const [id,kind] of [['counterVideoFile','video'],['counterImageFile','image']])$(id).onchange=async event=>{try{await counterLoadFile(event.target.files[0],kind)}catch(error){counterStatus(error.message,'bad')}finally{counterRender()}};
 for(const id of ['counterDetector','counterDirection','counterLine','counterX1','counterY1','counterX2','counterY2'])$(id).onchange=()=>{counterRender();counterPreviewCamera();if(counter.image)counterDraw(counterFrameCanvas(counter.image))};
 let start=null;const canvas=$('counterCanvas');
 const point=event=>{const r=canvas.getBoundingClientRect();return[Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))]};
 canvas.onpointerdown=event=>{if(!counter.drawing||counter.active)return;event.preventDefault();canvas.setPointerCapture(event.pointerId);start=point(event)};
 canvas.onpointerup=event=>{if(!start)return;event.preventDefault();const end=point(event),roi=[Math.min(start[0],end[0]),Math.min(start[1],end[1]),Math.max(start[0],end[0]),Math.max(start[1],end[1])];start=null;if(roi[2]-roi[0]<.05||roi[3]-roi[1]<.05){counterStatus('Vùng quá nhỏ. Kéo lại vùng ra máy.');return}['counterX1','counterY1','counterX2','counterY2'].forEach((id,i)=>$(id).value=Math.round(roi[i]*100));const axis=['right','left'].includes($('counterDirection').value)?0:1;$('counterLine').value=Math.round((roi[axis]+roi[axis+2])*50);counter.drawing=false;canvas.style.cursor='';counterPreviewCamera();if(counter.image)counterDraw(counterFrameCanvas(counter.image));counterStatus('Đã chọn vùng. Kiểm tra hướng ra rồi Bắt đầu.','ok')};
 setInterval(()=>{if(workflowMode==='counter')counterPreviewCamera();if(counter.active&&counter.paused)void api('/api/counter/status',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(counterIdentity())}).catch(error=>counterStatus(error.message,'bad'))},5000);
 counterRender();
}
counterSetup();
