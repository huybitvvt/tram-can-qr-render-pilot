"""Real model + Edge integration, isolated from installed customer data."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

import cv2
from playwright.sync_api import sync_playwright
from roll_qr_scale.storage import MeasurementStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--expect', type=float, default=6.86)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--station', type=int, choices=range(1, 11), default=2)
    parser.add_argument('--offline', action='store_true', help='Configure unavailable cloud and reject external browser traffic')
    parser.add_argument('--next-image', type=Path, help='Second real scene for live value transition and another slot')
    parser.add_argument('--next-expect', type=float, default=13.04)
    parser.add_argument('--native-recovery', action='store_true', help='Simulate a native camera stall through the real UI')
    parser.add_argument('--snapshot', action='store_true', help='Freeze one real frame and take its weight without live stability')
    parser.add_argument('--damaged', action='store_true', help='One-photo NKM/NC/RM workflow and warehouse routing')
    args = parser.parse_args()
    suffix = f'{args.station:02d}'
    station_id, camera_id, gateway_id = f'station-{suffix}', f'camera-{suffix}', f'gateway-{suffix}'
    project = Path(__file__).resolve().parents[1]
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    sandbox = args.out/'user'
    root = sandbox/'TramCanQR'
    root.mkdir(parents=True, exist_ok=True)
    remote_calls = []
    class UnavailableCloud(BaseHTTPRequestHandler):
        def do_GET(self):
            remote_calls.append(self.path)
            self.send_error(503, 'Simulated Internet outage')
        do_POST = do_GET
        def log_message(self, *args): pass
    remote = ThreadingHTTPServer(('127.0.0.1', 0), UnavailableCloud)
    threading.Thread(target=remote.serve_forever, daemon=True).start()
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0)); port = port_socket.getsockname()[1]
    config = root/'config.env'
    config.write_text('\n'.join(['ROLL_SCALE_STATION_COUNT=1', f'ROLL_SCALE_GATEWAY_ID={gateway_id}',
        f'ROLL_SCALE_STATION_IDS={station_id}', f'ROLL_SCALE_CAMERA_IDS={camera_id}',
        'ROLL_SCALE_WEIGHT_ENGINE=gemini', 'ROLL_SCALE_GEMINI_API_KEY=invalid-unused-key',
        f'ROLL_SCALE_PORT={port}', 'ROLL_SCALE_OPEN_BROWSER=0', 'ROLL_SCALE_AUTO_SYNC=0'])+'\n', encoding='utf-8')
    if args.offline:
        with config.open('a', encoding='utf-8') as stream:
            endpoint = f'http://127.0.0.1:{remote.server_port}'
            stream.write(f'ROLL_SCALE_API_URL={endpoint}/ingest\nROLL_SCALE_DEVICE_TOKEN=offline-test\n'
                f'ROLL_SCALE_SUPABASE_URL={endpoint}\nROLL_SCALE_SUPABASE_PUBLISHABLE_KEY=offline-test\n')
    config_bytes = config.read_bytes()
    frame = cv2.imdecode(__import__('numpy').fromfile(args.image, dtype='uint8'), cv2.IMREAD_COLOR)
    assert frame is not None
    # Use the original scene only; discard the archive's duplicate zoom panel.
    if frame.shape[:2] == (1266,1600): frame = frame[:900]
    encoded, image_bytes = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 96])
    assert encoded
    image = 'data:image/jpeg;base64,'+base64.b64encode(image_bytes).decode()
    store = MeasurementStore(root/'data'/'measurements.db', root/'data'/'captures')
    previous = store.save('KEEP-RC80-RECORD', .75, 'kg', frame, 'manual')
    previous_photo = Path(previous.image_path)
    previous_hash = hashlib.sha256(previous_photo.read_bytes()).hexdigest()
    draft, _ = store.save_photo_draft_idempotent(frame, capture_kind='product',
        event_id=str(uuid.uuid4()), parent_event_id=str(uuid.uuid4()), station_id=station_id, camera_id=camera_id)
    store.close()
    env = {key:value for key,value in os.environ.items() if not key.startswith(('ROLL_SCALE_','SUPABASE_KHO_','GOOGLE_','GEMINI_'))}
    env.update(LOCALAPPDATA=str(sandbox), ROLL_SCALE_OPEN_BROWSER='0', ROLL_SCALE_AUTO_SYNC='0')
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, '-m', 'roll_qr_scale.windows_app']
    process = subprocess.Popen(command, cwd=project, env=env,
        stdout=(args.out/'process.log').open('wb'), stderr=subprocess.STDOUT,
        creationflags=subprocess.CREATE_NO_WINDOW)
    base = f'http://127.0.0.1:{port}'
    def request(path, payload=None):
        req = urllib.request.Request(base+path, data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=45) as response: return json.load(response)
    try:
        deadline = time.monotonic()+35
        while time.monotonic()<deadline:
            assert process.poll() is None, (args.out/'process.log').read_text(errors='replace')[-2000:]
            try:
                status = request('/api/status')
                if status.get('ocr_ready'): break
            except OSError: pass
            time.sleep(.25)
        assert status['weight_engine']=='rapidocr' and not status['gemini']['enabled'],status
        assert status['gateway_id']==gateway_id and status['stations'][0]['station_id']==station_id
        assert status['stations'][0]['camera_id']==camera_id
        assert config.read_bytes()==config_bytes
        with sqlite3.connect(root/'backups'/json.loads((root/'backups'/'rapidocr-rc82.json').read_text())['directory']/'measurements.db') as db:
            assert db.execute('SELECT weight FROM measurements').fetchone()==(.75,)
        errors, network, analyses, previews = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width':1600,'height':1080})
            if args.offline:
                page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:network.append(req.url))
            page.on('dialog',lambda dialog:dialog.dismiss())
            def record_response(response):
                if response.url.endswith(('/api/analyze', '/api/local/capture')):
                    analyses.append({'status':response.status})
                if response.url.endswith('/api/local/live'):
                    previews.append({'status':response.status})
            page.on('response', record_response)
            page.goto(base)
            page.wait_for_selector('#localOcrControls')
            assert page.get_by_text('Chọn vùng số cân',exact=True).count()==1
            # Canvas stream drives the same HTML video and OCR as a live camera.
            page.evaluate('''async image=>{
                const session=current();session.stop();const canvas=document.createElement('canvas');
                const img=await new Promise(resolve=>{const i=new Image();i.onload=()=>resolve(i);i.src=image});
                canvas.width=img.width;canvas.height=img.height;canvas.getContext('2d').drawImage(img,0,0);
                window.smokeCanvas=canvas;window.smokeTimer=setInterval(()=>canvas.getContext('2d').drawImage(img,0,0),100);
                await bindOpenedStream(session,canvas.captureStream(10),session.streamGeneration);
                selectCaptureSlot('product',0,true);
                sourceContext={...sourceContext,machine:'MÁY BAO BÌ 5',order:'TEST-LOCAL',shift:'HC1'};
                $('sourceMachine').value=sourceContext.machine;selectSourceOrder('TEST-LOCAL');
            }''', image)
            if args.damaged:
                from smoke_damaged_goods import verify_damaged
                summary = verify_damaged(page, base, root, args.out, image, args.expect)
                assert config.read_bytes() == config_bytes
                assert hashlib.sha256(previous_photo.read_bytes()).hexdigest() == previous_hash
                assert not errors, errors
                summary.update(ok=True, real_model=True, browser='Edge', browser_errors=errors,
                               offline_with_cloud_configured=args.offline,
                               existing_data_config_photo_draft_preserved=True)
                (args.out/'result.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
                print(json.dumps(summary), flush=True)
                browser.close()
                return
            try:
                if args.snapshot:
                    page.locator('#localSnapshot').click()
                    page.wait_for_function('current()._localSnapshot?.result?.weight_found',timeout=30000)
                    assert page.evaluate('current().localLive.result.stable') is False
                    live_requests = sum(url.endswith('/api/local/live') for url in network)
                    # An operator may inspect a frozen image beyond the live TTL.
                    page.wait_for_timeout(3000)
                    assert sum(url.endswith('/api/local/live') for url in network) == live_requests
                    assert page.evaluate('current().preview.style.display') == 'block'
                    page.screenshot(path=str(args.out/'held.png'),full_page=True)
                else:
                    page.wait_for_function('current().localLive&&current().localLive.result.stable',timeout=30000)
            except Exception:
                page.screenshot(path=str(args.out/'failure.png'),full_page=True)
                print(json.dumps({'errors':errors,'previews':previews[-3:],'state':page.evaluate('({text:$("localWeightStatus").textContent,stream:!!current().stream,ready:current().video.readyState,paused:current().video.paused,time:current().video.currentTime,hidden:document.hidden,busy:localOcrState.busy})')},ensure_ascii=False),flush=True)
                raise
            assert page.evaluate('current().localLive.result.weight')==args.expect
            page.screenshot(path=str(args.out/'live.png'),full_page=True)
            # Preview does not create production records or photo drafts.
            with sqlite3.connect(root/'data'/'measurements.db') as db:
                assert db.execute('SELECT COUNT(*) FROM measurements').fetchone()==(1,)
                assert db.execute('SELECT COUNT(*) FROM photo_drafts').fetchone()==(1,)
            page.locator('#localWeight').click()
            expected_image=page.evaluate('current().localLive.image')
            page.keyboard.press('Space')
            page.wait_for_function('(expected)=>Number(current().rounds[0].productWeight)===expected',arg=args.expect,timeout=1500)
            page.wait_for_function('current().rounds[0].productAnalysis&&current().rounds[0].productAnalysis.local_saved',timeout=20000)
            actual_analysis=page.evaluate('current().rounds[0].productAnalysis')
            assert actual_analysis['live_reused'] and not actual_analysis['gemini_used'],actual_analysis
            assert page.evaluate('current().rounds[0].productImage')==expected_image
            assert page.evaluate('current().selectedSlot.kind')=='core'
            if args.snapshot:
                assert actual_analysis['manual_capture']
                assert 'MANUAL_SNAPSHOT=1' in actual_analysis['weight_raw']
                assert page.evaluate('current()._localSnapshot.used')
                page.keyboard.press('Space')
                assert page.evaluate('Boolean(current().rounds[0].coreImage)') is False
                page.locator('#localResumeLive').click()
                assert page.evaluate('current()._localSnapshot===null&&current().preview.style.display!=="block"')
            transition_ms = None
            if args.next_image:
                next_frame = cv2.imdecode(__import__('numpy').fromfile(args.next_image, dtype='uint8'), cv2.IMREAD_COLOR)
                assert next_frame is not None
                ok, next_bytes = cv2.imencode('.jpg', next_frame, [cv2.IMWRITE_JPEG_QUALITY, 96]);assert ok
                next_image = 'data:image/jpeg;base64,'+base64.b64encode(next_bytes).decode()
                changed_at = time.monotonic()
                page.evaluate('''async image=>{
                    clearInterval(window.smokeTimer);
                    const img=await new Promise(resolve=>{const i=new Image();i.onload=()=>resolve(i);i.src=image});
                    const canvas=window.smokeCanvas;canvas.width=img.width;canvas.height=img.height;
                    const draw=()=>{canvas.getContext('2d').fillRect(0,0,canvas.width,canvas.height);canvas.getContext('2d').drawImage(img,0,0,canvas.width,canvas.height)};
                    draw();window.smokeTimer=setInterval(draw,100);
                    selectCaptureSlot('product',1,true);
                }''', next_image)
                page.wait_for_function('(expected)=>current().localLive?.result.stable&&current().localLive.result.weight===expected',arg=args.next_expect,timeout=15000)
                transition_ms = round((time.monotonic()-changed_at)*1000)
                page.locator('#localWeight').click();page.keyboard.press('Space')
                page.wait_for_function('(expected)=>Number(current().rounds[1].productWeight)===expected',arg=args.next_expect,timeout=3000)
                assert page.evaluate('Number(current().rounds[0].productWeight)') == args.expect
                page.screenshot(path=str(args.out/'changed-live.png'),full_page=True)
            # Final save uses the real UI, including duplicate-QR checking. Supply
            # an operator-reviewed core so this test isolates local persistence.
            cloud_before_save = len(remote_calls)
            saved_event = page.evaluate('current().rounds[0].eventId')
            page.evaluate('''image=>{
                const session=current(),round=session.rounds[0];
                round.coreImage=image;round.weight='0.50';round.qr='OFFLINE-LOCAL-QR';
                syncSessionAliases(session);renderEvidence(session);renderControls();
            }''', image)
            page.evaluate('saveRoundEvidence(0)')
            with sqlite3.connect(root/'data'/'measurements.db') as db:
                assert db.execute('SELECT weight FROM measurements WHERE event_id=?',(saved_event,)).fetchone()==(.5,)
                assert db.execute('SELECT product_weight FROM measurements WHERE event_id=?',(saved_event,)).fetchone()==(args.expect,)
            # Background production-order requests may already be in flight;
            # capture/save must never issue a remote measurement lookup.
            assert not [path for path in remote_calls[cloud_before_save:] if 'can_tu_dong' in path], remote_calls
            # Manual ROI selection must work with letterboxing.
            page.locator('#localSelectLed').click()
            overlay=page.locator('.local-select-overlay')
            bounds=overlay.bounding_box()
            page.mouse.move(bounds['x']+bounds['width']*.35,bounds['y']+bounds['height']*.55)
            page.mouse.down();page.mouse.move(bounds['x']+bounds['width']*.65,bounds['y']+bounds['height']*.8);page.mouse.up()
            assert page.evaluate('current().ledRoi!==null')
            page.locator('#localAutoLed').click()
            assert page.evaluate('current().ledRoi===null')
            page.locator('#localFixedTwo').uncheck()
            assert page.evaluate('localOcrState.fixedTwo===false&&current().localLive===null')
            page.locator('#localStopCamera').click()
            assert page.evaluate('current().stream===null&&current().localLive===null')
            native_recovery = False
            if args.native_recovery:
                pending_weights = page.evaluate('current().rounds.map(round=>[round.weight,round.productWeight])')
                native = {'opens': 0, 'sequence': 0, 'stall': False}
                def native_bridge(route):
                    path = route.request.url.rsplit('/', 1)[-1]
                    if path == 'open':
                        native['opens'] += 1
                        data = {'ok': True, 'source': 'native-test-'+str(native['opens'])}
                    elif path == 'stop': data = {'ok': True}
                    elif native['stall'] and native['opens'] == 1: data = {'ok': True, 'waiting': True}
                    else:
                        native['sequence'] += 1
                        data = {'ok': True, 'sequence': native['sequence'], 'image': image}
                    route.fulfill(status=200, content_type='application/json', body=json.dumps(data))
                page.route(base+'/api/local/camera/*', native_bridge)
                page.locator('#localFixedTwo').check()
                page.locator('#localCameraBackend').select_option(label='DirectShow')
                page.locator('#localOpenCamera').click()
                page.wait_for_function('current().localLive?.result.stable', timeout=20000)
                if args.snapshot:
                    page.locator('#localSnapshot').click()
                    page.wait_for_function('current()._localSnapshot?.result?.weight_found',timeout=20000)
                    assert page.evaluate('current()._localSnapshot.image===current()._nativeImage')
                    assert page.evaluate('current().localLive.result.stable') is False
                    page.locator('#localResumeLive').click()
                    page.wait_for_function('current().localLive?.result.stable',timeout=20000)
                original_source = page.evaluate('current()._nativeSource')
                native['stall'] = True
                page.wait_for_function('(old)=>current()._nativeSource&&current()._nativeSource!==old', arg=original_source, timeout=15000)
                page.wait_for_function('current().localLive?.result.stable', timeout=15000)
                assert native['opens'] == 2, native
                assert page.evaluate('current().rounds.map(round=>[round.weight,round.productWeight])') == pending_weights
                page.locator('#localStopCamera').click()
                native_recovery = True
            page.screenshot(path=str(args.out/'capture.png'),full_page=True)
            # Printing uses a synthetic receipt, never the warehouse production DB.
            page.evaluate('''()=>{
                nhapKhoSummaryCache=[{ma_phieu:'PN-TEST-AI',ma_sp:'SP01',so_luong:3,ngay:'2026-10-27',
                    ca:'HC1',may:'Máy bao bì 5',kho:'Kho thành phẩm',saved_at:'2026-10-27T01:02:03Z'}];
                $('nhapKhoSummaryDate').value='2026-10-27';$('nhapKhoSummaryCa').value='';
                window.print=()=>{};renderNhapKhoSummary();printNhapKhoSummary();
            }''')
            printed = page.locator('#printSheet').inner_text()
            assert 'Phiếu đẩy kho từ trạm cân AI' in printed
            assert 'Công nhân SX' in printed and 'Người đẩy kho' not in printed
            assert 'Giờ đẩy' in printed and '08:02:03' in printed
            page.pdf(path=str(args.out/'phieu-day-kho.pdf'),format='A4',print_background=True)
            page.emulate_media(media='print')
            page.screenshot(path=str(args.out/'phieu-day-kho.png'),full_page=True)
            assert not [url for url in network if any(s in url for s in ('generativelanguage.googleapis','/api/gemini/','/api/codex/','/api/antigravity/'))], network
            assert not errors, errors
            browser.close()
        # Confirming a new operator-reviewed record still uses the rc80 storage flow.
        saved_event=str(uuid.uuid4())
        saved=request('/api/capture', {'event_id':saved_event,'station_id':station_id,
            'camera_id':camera_id,'qr_code':actual_analysis.get('qr_code') or 'TEST-LOCAL-QR',
            'weight':.5,'product_weight':args.expect,'image':image,'product_image':image,
            'unit':'kg','vision_confirmed':False,'machine':'MÁY BAO BÌ 5',
            'weight_raw':'SOURCE_MACHINE=MÁY BAO BÌ 5; HUMAN_CONFIRMED=0.5'})
        assert saved['event_id']==saved_event
        with sqlite3.connect(root/'data'/'measurements.db') as db:
            assert db.execute('SELECT COUNT(*) FROM measurements').fetchone()==(3,)
            assert db.execute('SELECT weight FROM measurements WHERE event_id=?',(previous.event_id,)).fetchone()==(.75,)
        assert config.read_bytes()==config_bytes
        assert hashlib.sha256(previous_photo.read_bytes()).hexdigest()==previous_hash
        summary={'ok':True,'real_model':True,'browser':'Edge','live_weight':args.expect,
            'space_reused_without_ocr':True,'manual_roi':True,'auto_led':True,'decimal_switch':True,
            'existing_data_config_photo_draft_preserved':True,'preview_no_writes':True,'browser_errors':errors}
        summary['new_record_saved_alongside_rc80_data']=True
        summary['station_identity']={'gateway':gateway_id,'station':station_id,'camera':camera_id}
        summary['offline_with_cloud_configured']=args.offline
        summary['final_save_through_ui']=True
        summary['live_transition_ms']=transition_ms
        summary['native_camera_stall_recovery_simulated']=native_recovery
        summary['manual_snapshot']=args.snapshot
        summary['warehouse_print_title_signature_time']=True
        (args.out/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary),flush=True)
    finally:
        process.terminate();process.wait(timeout=15)
        remote.shutdown();remote.server_close()


if __name__=='__main__': main()
