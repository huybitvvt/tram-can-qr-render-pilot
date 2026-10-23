"""Real model + Edge integration, isolated from installed customer data."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
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
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    sandbox = args.out/'user'
    root = sandbox/'TramCanQR'
    root.mkdir(parents=True, exist_ok=True)
    with socket.socket() as port_socket:
        port_socket.bind(('127.0.0.1', 0)); port = port_socket.getsockname()[1]
    config = root/'config.env'
    config.write_text('\n'.join(['ROLL_SCALE_STATION_COUNT=1', 'ROLL_SCALE_GATEWAY_ID=gateway-02',
        'ROLL_SCALE_STATION_IDS=station-02', 'ROLL_SCALE_CAMERA_IDS=camera-02',
        'ROLL_SCALE_WEIGHT_ENGINE=gemini', 'ROLL_SCALE_GEMINI_API_KEY=invalid-unused-key',
        f'ROLL_SCALE_PORT={port}', 'ROLL_SCALE_OPEN_BROWSER=0', 'ROLL_SCALE_AUTO_SYNC=0'])+'\n', encoding='utf-8')
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
        event_id=str(uuid.uuid4()), parent_event_id=str(uuid.uuid4()), station_id='station-02', camera_id='camera-02')
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
        assert config.read_bytes()==config_bytes
        with sqlite3.connect(root/'backups'/json.loads((root/'backups'/'rapidocr-rc82.json').read_text())['directory']/'measurements.db') as db:
            assert db.execute('SELECT weight FROM measurements').fetchone()==(.75,)
        errors, network, analyses, previews = [], [], [], []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width':1600,'height':1080})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:network.append(req.url))
            page.on('dialog',lambda dialog:dialog.dismiss())
            def record_response(response):
                if response.url.endswith('/api/analyze'):
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
            try:
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
            page.wait_for_function('current().rounds[0].productAnalysis&&current().rounds[0].productAnalysis.live_reused',timeout=20000)
            actual_analysis=page.evaluate('current().rounds[0].productAnalysis')
            assert actual_analysis['live_reused'] and not actual_analysis['gemini_used'],actual_analysis
            assert page.evaluate('current().rounds[0].productImage')==expected_image
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
            page.screenshot(path=str(args.out/'capture.png'),full_page=True)
            assert not [url for url in network if any(s in url for s in ('generativelanguage.googleapis','/api/gemini/','/api/codex/','/api/antigravity/'))], network
            assert not errors, errors
            browser.close()
        # Confirming a new operator-reviewed record still uses the rc80 storage flow.
        saved_event=str(uuid.uuid4())
        saved=request('/api/capture', {'event_id':saved_event,'station_id':'station-02',
            'camera_id':'camera-02','qr_code':actual_analysis.get('qr_code') or 'TEST-LOCAL-QR',
            'weight':.5,'product_weight':args.expect,'image':image,'product_image':image,
            'unit':'kg','vision_confirmed':False,'machine':'MÁY BAO BÌ 5',
            'weight_raw':'SOURCE_MACHINE=MÁY BAO BÌ 5; HUMAN_CONFIRMED=0.5'})
        assert saved['event_id']==saved_event
        with sqlite3.connect(root/'data'/'measurements.db') as db:
            assert db.execute('SELECT COUNT(*) FROM measurements').fetchone()==(2,)
            assert db.execute('SELECT weight FROM measurements WHERE event_id=?',(previous.event_id,)).fetchone()==(.75,)
        assert config.read_bytes()==config_bytes
        assert hashlib.sha256(previous_photo.read_bytes()).hexdigest()==previous_hash
        summary={'ok':True,'real_model':True,'browser':'Edge','live_weight':args.expect,
            'space_reused_without_ocr':True,'manual_roi':True,'auto_led':True,'decimal_switch':True,
            'existing_data_config_photo_draft_preserved':True,'preview_no_writes':True,'browser_errors':errors}
        summary['new_record_saved_alongside_rc80_data']=True
        (args.out/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary),flush=True)
    finally:
        process.terminate();process.wait(timeout=15)


if __name__=='__main__': main()
