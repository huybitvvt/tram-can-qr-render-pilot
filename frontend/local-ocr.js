/* Local camera/OCR controls. Existing production, inventory and sync flows stay in index.html. */
'use strict';
const localOcrState={fixedTwo:true,roiBySource:new Map(),busy:false,sequence:0};
function localEnabled(){return Boolean(appStatus&&appStatus.weight_engine==='rapidocr')}
function localKey(session){return [session.stationId,session.cameraId,session.streamGeneration,session.deviceId,session._nativeSource||'',JSON.stringify(session.ledRoi||null),localOcrState.fixedTwo,session.unit||'kg'].join('|')}
function localSource(session){return session._localSource|| (session._localSource=crypto.randomUUID())}
function localInvalidate(session){if(!session)return;session.localLive=null;session._localSource=crypto.randomUUID();session._localKey='';session._localVideoTime=-1;localRender(session)}
function localGetCapture(session){const live=session.localLive,now=performance.now();if(!live||live.key!==localKey(session)||!live.result.stable||now-live.startedAt>2300||!session.stream||session.video.readyState<2||session.video.paused||session.unit!=='kg'||(session._nativeSource&&now-session._nativeLastFrame>1500))throw new Error('Chờ số cân ổn định mới rồi nhấn Space. Kiểm tra camera/vùng LED và chọn kg.');return live}
function localCapturePayload(session,capture){return {roi:capture?capture.roi:session.ledRoi?session.ledRoi.join(','):'auto',fixed_two:capture?capture.fixedTwo:localOcrState.fixedTwo,live_token:capture?capture.result.live_token:'',recognition_provider:'rapidocr',recognition_profile:'small'}}
async function localCaptureSlot(session,capture,kind,index,context){
 const round=session.rounds[index],product=kind==='product',prefix=product?'product':'core';
 const retries=round.localCaptures||(round.localCaptures={});
 let job=retries[kind];
 if(!job||job.saved){
  const event=round.eventId||newEventId();round.eventId=event;
  job=retries[kind]={image:capture.image,key:capture.key,saved:false,payload:{image:capture.image,station_id:session.stationId,camera_id:session.cameraId,source:capture.source,live_token:capture.result.live_token,event_id:event,capture_id:newEventId(),kind,round:index,unit:session.unit,work_date:context.date,shift:context.shift,machine:context.machine,production_order:context.order}};
  round[prefix+'Image']=job.image;round[prefix+'Analysis']=null;
  if(product){round.productWeight='';round.productAnalyzedWeight=null}else{round.weight='';round.analyzedWeight=null}
  syncSessionAliases(session);if(session===current())renderEvidence(session);
 }
 session._analyzeLock=true;renderControls();
 status(captureStatus,'Đang ghi số và ảnh '+weighSlotLabel(kind,index)+' trên máy…','warn');
 try{
  const data=await api('/api/local/capture',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(job.payload)});
  if(!data.local_saved||data.event_id!==round.eventId||data.capture_id!==job.payload.capture_id||data.capture_kind!==kind||data.capture_round!==index)throw new Error('Xác nhận lưu local không khớp ô cân.');
  if(session.rounds[index]!==round||round.saved)return;
  job.saved=true;round[prefix+'Image']=job.image;round[prefix+'Analysis']=data;round[prefix+'PhotoCaptureId']=data.capture_id;
  if(product){round.productWeight=Number(data.weight).toFixed(2);round.productAnalyzedWeight=data.weight;round.productAnalyzedRaw=data.weight_raw||''}
  else{round.weight=Number(data.weight).toFixed(2);round.analyzedWeight=data.weight;round.analyzedRaw=data.weight_raw||''}
  session.lastAnalysis=data;syncSessionAliases(session);
  const next=nextCaptureStep(session);if(next)session.selectedSlot={...next};
  session._analyzeLock=false;session.state='awaiting-weight';advanceToNextCapture(session);refreshCompletionState(session);
  if(session===current()){
   renderEvidence(session);renderControls();markWeightThresholdAlerts(session,round,index,{popup:true});
   status(captureStatus,'ĐÃ LƯU LOCAL · '+weighSlotLabel(kind,index)+' · '+Number(data.weight).toFixed(2)+' kg. '+(next?'Sẵn sàng lấy ô tiếp theo. ':'')+'Chưa lưu phiếu; Supabase đồng bộ sau.'+(!data.quality_pass?' Ảnh chưa đạt chất lượng; kiểm tra lại ảnh trước khi lưu phiếu.':''),'ok');
  }
  void localDecodeCapturedQr(session,round,kind,index,job);
 }catch(error){if(session===current())status(captureStatus,'CHƯA XÁC NHẬN LƯU LOCAL: '+error.message+' Nhấn Space để thử lại đúng ảnh và ID; dùng Bỏ nếu muốn lấy ảnh mới.','bad')}
 finally{session._analyzeLock=false;renderControls()}
}
async function localDecodeCapturedQr(session,round,kind,index,job){
 if(round.qr)return;
 try{
  const data=await api('/api/decode',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({image:job.image})});
  if(session.rounds[index]!==round||round.saved||round.localCaptures?.[kind]!==job||round[(kind==='product'?'product':'core')+'Image']!==job.image||round.qr||!data.qr_code)return;
  const code=String(data.qr_code).trim(),duplicate=qrDuplicateMessage(code,index,session);
  if(duplicate){round.qrNotice='Đã đọc QR: '+code+' · '+duplicate}else{round.qr=code;round.qrNotice=''}
  syncSessionAliases(session);if(session===current()){renderEvidence(session);syncCaptureProductCodes(session);renderControls()}
 }catch(error){console.warn('Ảnh và số đã lưu local; quét hoặc nhập QR nếu chưa có:',error.message)}
}
function localRecoverCamera(session,error,generation){
 if(session.streamGeneration!==generation)return;
 const attempts=session._localRecoveryAttempts||0;
 session.stop();session.setState('disconnected','MẤT HÌNH CAMERA','bad');
 if(attempts>=2){status(captureStatus,error.message+'. Đã thử mở lại 2 lần. Kiểm tra USB rồi bấm Mở camera.','bad');return}
 session._localRecoveryAttempts=attempts+1;
 const stoppedGeneration=session.streamGeneration;
 status(captureStatus,error.message+'. Đang mở lại đúng camera ('+(attempts+1)+'/2)…','warn');
 const retry=()=>{if(session.streamGeneration!==stoppedGeneration||session.stream||session!==current()||document.hidden)return;if(blocksCameraChange(session)){setTimeout(retry,500);return}void openDefaultCamera(session,true)};
 setTimeout(retry,700);
}
async function localClaimCapture(session,capture,eventId,kind,round){if(capture.key!==localKey(session))throw new Error('Camera/vùng đọc đã thay đổi; chờ số mới.');await api('/api/local/claim',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:session.stationId,camera_id:session.cameraId,source:capture.source,live_token:capture.result.live_token,event_id:eventId,kind,round})})}
function localRender(session=current()){
 if(!localEnabled()||!session||session!==current()||!$('localWeight'))return;
 const live=session.localLive,fresh=live&&live.key===localKey(session)&&(live.stillImage||performance.now()-live.startedAt<=2300)&&(session.stream||live.stillImage);
 $('localWeight').textContent=fresh&&live.result.weight_found?Number(live.result.weight).toFixed(2)+' kg':'— kg';
 $('localWeightStatus').textContent=fresh&&live.stillImage?'Kết quả ảnh thử · chưa ghi phiếu':!session.stream?'Mở camera để đọc liên tục':!fresh?'Đang chờ kết quả mới…':live.result.stable?'ỔN ĐỊNH · Space lấy số vào ô đang chọn':live.result.weight_found?'Đang kiểm tra ổn định…':'Chưa đọc đủ số · chỉnh vùng/góc camera';
 $('localWeightStatus').style.color=fresh&&live.result.stable?'#166534':'#92400e';
 $('localRegionLabel').textContent=session.ledRoi?'Vùng LED: chọn bằng tay':'Vùng LED: tự tìm màu đỏ';
 localRenderBox(session,fresh?live:null);
 const crop=$('localCrop');if(fresh&&crop._live===live)return;crop._live=live;crop.replaceChildren();
 if(fresh){const image=new Image();image.onload=()=>{if(session.localLive!==live)return;const region=(live.result.regions||[])[0];if(!region)return;const [x1,y1,x2,y2]=region,canvas=document.createElement('canvas');canvas.width=Math.max(1,x2-x1);canvas.height=Math.max(1,y2-y1);canvas.getContext('2d').drawImage(image,x1,y1,x2-x1,y2-y1,0,0,canvas.width,canvas.height);crop.replaceChildren(canvas)};image.src=live.image}
}
function localSetup(){
 if(!localEnabled()||$('localOcrControls'))return;
 const style=document.createElement('style');style.textContent='.local-ocr{display:grid;gap:8px;margin:10px 0;padding:10px;border:1px solid #cbd5e1;border-radius:8px;background:#f8fafc}.local-ocr-row{display:flex;flex-wrap:wrap;align-items:center;gap:6px}.local-ocr button,.local-ocr select{min-height:36px}.local-ocr label{display:flex;gap:5px;align-items:center;font-size:12px}.local-live-value{font-size:34px;font-weight:800;color:#0f172a;font-variant-numeric:tabular-nums}.local-live-note{font-size:12px}.local-crop{height:66px;background:#e2e8f0;display:flex;justify-content:center;align-items:center}.local-crop canvas{display:block;max-width:100%;max-height:66px;object-fit:contain}.local-select-overlay{position:absolute;inset:0;z-index:36;cursor:crosshair;touch-action:none}.local-drag{position:absolute;border:2px solid #38bdf8;pointer-events:none}.local-led-label{font-size:11px;color:#475569}';document.head.append(style);
 const host=document.createElement('section');host.id='localOcrControls';host.className='local-ocr';host.setAttribute('aria-label','Camera và nhận diện cân local');
 host.innerHTML='<div class="local-ocr-row"><label>Camera <select id="localCameraIndex" aria-label="Số thứ tự camera USB"></select></label><select id="localCameraBackend" aria-label="Driver camera"><option>DirectShow</option><option>Media Foundation</option><option>Trình duyệt</option></select><button type="button" id="localOpenCamera">Mở camera</button><button type="button" id="localStopCamera">Dừng</button></div><div class="local-ocr-row"><button type="button" id="localSelectLed">Chọn vùng số cân</button><button type="button" id="localAutoLed">Tự tìm LED đỏ</button></div><label><input type="checkbox" id="localFixedTwo" checked> Cân luôn có 2 số thập phân</label><div id="localRegionLabel" class="local-led-label"></div><div id="localWeight" class="local-live-value">— kg</div><div id="localWeightStatus" class="local-live-note" role="status">Mở camera để đọc liên tục</div><div id="localCrop" class="local-crop" aria-label="Vùng ảnh vừa đọc"></div><div class="local-ocr-row"><button type="button" id="localDetails">Xem chuỗi OCR</button><button type="button" id="localFile">Mở ảnh thử…</button></div><div class="local-live-note">PP-OCRv6 Small · CPU · Space lấy số ổn định. Đối chiếu số trước khi lưu phiếu.</div>';
 $('productionToolbar').after(host);
 for(let index=0;index<10;index++)$('localCameraIndex').add(new Option(String(index),String(index)));
 $('localOpenCamera').onclick=()=>openDefaultCamera(current());
 $('localStopCamera').onclick=()=>{const session=current();session.stop();session.setState('idle','ĐÃ DỪNG CAMERA');localInvalidate(session)};
 $('localCameraIndex').onchange=$('localCameraBackend').onchange=()=>{const session=current();session.stop();localInvalidate(session);status(captureStatus,'Đã đổi camera/driver. Bấm Mở camera.','warn')};
 $('localSelectLed').onclick=localSelectLed;
 $('localAutoLed').onclick=()=>{const session=current();session.ledRoi=null;localInvalidate(session);localSaveRoi(session);localReadStill(session);status(captureStatus,'Đang tự tìm LED đỏ. Space chỉ lấy số khi đã ổn định.','ok')};
 $('localFixedTwo').onchange=()=>{localOcrState.fixedTwo=$('localFixedTwo').checked;for(const session of stations)localInvalidate(session);localReadStill(current());status(captureStatus,localOcrState.fixedTwo?'Cấu hình cân đúng 2 số thập phân: 120 được hiểu là 1,20 kg.':'Cần OCR thấy dấu chấm/phẩy và đủ 2 chữ số sau dấu.','warn')};
 $('localDetails').onclick=()=>{const session=current(),live=session&&session.localLive;alert(live?JSON.stringify({weight:live.result.weight,stable:live.result.stable,elapsed_ms:live.result.elapsed_ms,observations:live.result.observations},null,2):'Chưa có kết quả mới')};
 const fileInput=document.createElement('input');fileInput.type='file';fileInput.accept='image/*';fileInput.hidden=true;host.append(fileInput);$('localFile').onclick=()=>fileInput.click();
 fileInput.onchange=async()=>{const file=fileInput.files[0],session=current();if(!file||!session)return;if(blocksCameraChange(session))return;if(file.size>20*1024*1024){status(captureStatus,'Ảnh thử tối đa 20 MB.','bad');return}try{session.stop();const data=await fileData(file);session._localStill=data;await new Promise((resolve,reject)=>{session.preview.onload=resolve;session.preview.onerror=reject;session.preview.src=data});showPreview(session);localInvalidate(session);await localReadStill(session)}catch(error){status(captureStatus,error.message,'bad')}finally{fileInput.value=''}};
 for(const id of ['geminiKeyBtn','swapGeminiSpareBtn','codexLoginBtn','geminiKeyPanel','codexDevicePanel','geminiQuotaMeter','antigravityQuotaMeter']){const element=$(id);if(element)element.hidden=true}
 $('ocrBadge').textContent='CÂN: PP-OCRv6 SMALL · LOCAL';$('geminiBadge').textContent='OCR OFFLINE';$('geminiBadge').className='mode ai';
}
function localRoiStorageKey(session){const backend=$('localCameraBackend')?.value||'Trình duyệt';return 'tramcan-led-roi-v1:'+session.stationId+':'+session.cameraId+':'+backend+':'+(backend==='Trình duyệt'?session.deviceId:$('localCameraIndex')?.value||'0')}
function localRenderBox(session,live){
 let box=session._ledOutline;if(!box){box=document.createElement('div');box.className='local-led-outline';Object.assign(box.style,{position:'absolute',border:'2px solid #38bdf8',pointerEvents:'none',zIndex:12});session.box.append(box);session._ledOutline=box}
 const geometry=mediaGeometry(session),region=session.ledRoi||(live&&parseBox(live.result.roi)&&Object.values(parseBox(live.result.roi)));
 if(!geometry||!region||session._selectingLed){box.style.display='none';return}
 const level=session.viewZoom||1,ox=(session.viewZoomX??.5)*(1-1/level),oy=(session.viewZoomY??.5)*(1-1/level);
 positionBox(box,{x1:(region[0]-ox)*level,y1:(region[1]-oy)*level,x2:(region[2]-ox)*level,y2:(region[3]-oy)*level},geometry);
 box.style.borderColor=session.ledRoi?'#38bdf8':'#fbbf24';
}
function localSaveRoi(session){try{localStorage.setItem(localRoiStorageKey(session),JSON.stringify(session.ledRoi))}catch{}}
function localLoadRoi(session){try{const raw=localStorage.getItem(localRoiStorageKey(session));if(raw===null)return session.configuredRoi?Object.values(session.configuredRoi):null;const roi=JSON.parse(raw);return Array.isArray(roi)&&roi.length===4&&roi.every(v=>Number.isFinite(v)&&v>=0&&v<=1)&&roi[0]<roi[2]&&roi[1]<roi[3]?roi:null}catch{return null}}
async function localReadStill(session){if(!session||session.stream||!session._localStill)return;const key=localKey(session),image=session._localStill;try{const result=await api('/api/local/still',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:session.stationId,camera_id:session.cameraId,image,roi:session.ledRoi?session.ledRoi.join(','):'auto',fixed_two:localOcrState.fixedTwo})});if(key!==localKey(session)||image!==session._localStill||session.stream)return;session.localLive={key,image,result,stillImage:true,startedAt:performance.now()};localRender(session)}catch(error){status(captureStatus,'Không đọc được ảnh thử: '+error.message,'bad')}}
function localSelectLed(){
 const session=current();if(!session||!sourceReady(session)){status(captureStatus,'Mở camera hoặc ảnh thử trước khi chọn vùng.','warn');return}
 resetViewZoom(session);localInvalidate(session);session._selectingLed=true;
 session.box.scrollIntoView({block:'center'});const overlay=document.createElement('div');overlay.className='local-select-overlay';overlay.tabIndex=0;overlay.setAttribute('role','application');overlay.setAttribute('aria-label','Kéo bao trọn dòng số cân. Escape để hủy.');session.box.append(overlay);overlay.focus();
 let start=null,rectangle=null;
 const finish=()=>{session._selectingLed=false;overlay.remove();localInvalidate(session);localReadStill(session)};
 overlay.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();finish()}};
 overlay.onpointerdown=event=>{event.preventDefault();event.stopPropagation();overlay.setPointerCapture(event.pointerId);const bounds=overlay.getBoundingClientRect();start=[event.clientX-bounds.left,event.clientY-bounds.top];rectangle=document.createElement('div');rectangle.className='local-drag';overlay.replaceChildren(rectangle)};
 overlay.onpointermove=event=>{if(!start)return;const bounds=overlay.getBoundingClientRect(),end=[event.clientX-bounds.left,event.clientY-bounds.top];Object.assign(rectangle.style,{left:Math.min(start[0],end[0])+'px',top:Math.min(start[1],end[1])+'px',width:Math.abs(end[0]-start[0])+'px',height:Math.abs(end[1]-start[1])+'px'})};
 overlay.onpointerup=event=>{if(!start)return;event.preventDefault();event.stopPropagation();const bounds=overlay.getBoundingClientRect(),geometry=mediaGeometry(session),end=[event.clientX-bounds.left,event.clientY-bounds.top],point=p=>[Math.min(1,Math.max(0,(p[0]-geometry.left)/geometry.width)),Math.min(1,Math.max(0,(p[1]-geometry.top)/geometry.height))];if(!geometry){finish();return}const a=point(start),b=point(end),roi=[Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[0],b[0]),Math.max(a[1],b[1])];if(roi[2]-roi[0]<.006||roi[3]-roi[1]<.006){status(captureStatus,'Vùng quá nhỏ; hãy chọn đủ mọi chữ số và dấu thập phân.','warn');return}session.ledRoi=roi.map(value=>Number(value.toFixed(6)));localSaveRoi(session);finish();status(captureStatus,'Đã chọn vùng LED. Bao đủ chữ số đầu/cuối và dấu thập phân.','ok')};
 status(captureStatus,'Kéo chuột bao trọn đúng một dòng số cân; Esc để hủy.','warn');
}

const localOriginalOpenDefault=openDefaultCamera;
const localOriginalPrimary=openPrimaryCamera;
openPrimaryCamera=function(){if(localEnabled()&&$('localCameraBackend')?.value!=='Trình duyệt')return openDefaultCamera(current());return localOriginalPrimary()};
const localOriginalMap=mapCamera;
mapCamera=async function(session,deviceId){if(localEnabled()&&$('localCameraBackend'))$('localCameraBackend').value='Trình duyệt';session._localStill=null;localInvalidate(session);await localOriginalMap(session,deviceId);if(localEnabled()){session.ledRoi=localLoadRoi(session);localInvalidate(session)}};
openDefaultCamera=async function(session=current(),recovering=false){
 if(!localEnabled()||!$('localCameraBackend'))return localOriginalOpenDefault(session);
 if($('localCameraBackend').value==='Trình duyệt'){session._localStill=null;await localOriginalOpenDefault(session);session.ledRoi=localLoadRoi(session);localInvalidate(session);return}
 if(!session||blocksCameraChange(session))return;
 if(!recovering)session._localRecoveryAttempts=0;
 session.stop();session._localStill=null;localInvalidate(session);const generation=session.streamGeneration;
 try{
  const opened=await api('/api/local/camera/open',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:session.stationId,camera_id:session.cameraId,index:Number($('localCameraIndex').value),backend:$('localCameraBackend').value})});
  if(session.streamGeneration!==generation){api('/api/local/camera/stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:session.stationId,camera_id:session.cameraId,source:opened.source})}).catch(()=>{});return}
  session._nativeSource=opened.source;session._nativeCanvas=document.createElement('canvas');session._nativeStarted=performance.now();session._nativeLastFrame=0;session._nativeSequence=0;
  const poll=async()=>{
   if(session._nativeSource!==opened.source||session.streamGeneration!==generation)return;
   try{
    const data=await api('/api/local/camera/frame',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:session.stationId,camera_id:session.cameraId,source:opened.source})});
    if(session._nativeSource!==opened.source||session.streamGeneration!==generation)return;
    if(data.image){const image=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('Không giải mã được hình camera'));img.src=data.image});if(session.streamGeneration!==generation)return;const canvas=session._nativeCanvas;canvas.width=image.naturalWidth;canvas.height=image.naturalHeight;canvas.getContext('2d').drawImage(image,0,0);session._nativeLastFrame=performance.now();session._nativeSequence=data.sequence;session._nativeImage=data.image;if(performance.now()-session._nativeStarted>10000)session._localRecoveryAttempts=0;if(!session.stream){const stream=canvas.captureStream(12);await bindOpenedStream(session,stream,generation);if(session.streamGeneration!==generation){stream.getTracks().forEach(track=>track.stop());return}session.ledRoi=localLoadRoi(session);localInvalidate(session)}}
    if(performance.now()-(session._nativeLastFrame||session._nativeStarted)>(session.stream?2500:12000))throw new Error('Không có hình camera; thử camera khác hoặc đổi driver');
    setTimeout(poll,70);
   }catch(error){localRecoverCamera(session,error,generation)}
  };poll();status(captureStatus,'Đang mở camera USB qua '+$('localCameraBackend').value+'…','warn');
 }catch(error){localRecoverCamera(session,error,generation)}
};
const localOriginalStop=StationSession.prototype.stop;
StationSession.prototype.stop=function(){const source=this._nativeSource;this._nativeSource=null;this._nativeCanvas=null;this.localLive=null;this._localSource=crypto.randomUUID();if(source)api('/api/local/camera/stop',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({station_id:this.stationId,camera_id:this.cameraId,source})}).catch(()=>{});localOriginalStop.call(this);if(localEnabled())localRender(this)};

async function localTick(){
 try{
  if(!localEnabled())return;
  localSetup();const session=current();if(!session)return;
  if(!Object.hasOwn(session,'ledRoi'))session.ledRoi=session.configuredRoi?Object.values(session.configuredRoi):null;
  localRender(session);
  if(localOcrState.busy||!session.stream||session._selectingLed||session.video.readyState<2||session.video.paused||panelMode||document.hidden)return;
  const videoTime=session._nativeSource?session._nativeSequence:session.video.currentTime;
  if(session._localVideoTime===videoTime){if(session._localFrameAt&&performance.now()-session._localFrameAt>2500){session.localLive=null;localRender(session);$('localWeightStatus').textContent='Camera chưa có khung hình mới. Kiểm tra USB hoặc bấm Mở camera.'}return}
  session._localFrameAt=performance.now();
  session._localVideoTime=videoTime;
  if(session._nativeSource&&performance.now()-session._nativeLastFrame>1200){localInvalidate(session);return}
  const key=localKey(session);if(session._localKey!==key){localInvalidate(session);session._localKey=key}
  const canvas=document.createElement('canvas'),video=session._nativeCanvas||session.video;canvas.width=session.video.videoWidth;canvas.height=session.video.videoHeight;if(!canvas.width||!canvas.height)return;canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
  const image=session._nativeSource?session._nativeImage:canvas.toDataURL('image/jpeg',.96),source=localSource(session),roi=session.ledRoi?session.ledRoi.join(','):'auto',fixedTwo=localOcrState.fixedTwo,startedAt=performance.now();
  localOcrState.busy=true;
  try{const result=await api('/api/local/live',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({image,station_id:session.stationId,camera_id:session.cameraId,source,sequence:++localOcrState.sequence,roi,fixed_two:fixedTwo})});if(!session.stream||key!==localKey(session)||source!==localSource(session))return;session.localLive={key,image,source,roi,fixedTwo,result,startedAt};localRender(session)}catch(error){if(key===localKey(session)){session.localLive=null;if(session===current())$('localWeightStatus').textContent='Chưa đọc được: '+error.message}}finally{localOcrState.busy=false}
 }finally{setTimeout(localTick,180)}
}
setTimeout(localTick,150);
