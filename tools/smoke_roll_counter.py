"""Counter UI smoke using real ONNX and a clearly synthetic known-count video."""
import csv
import io
import json
import sqlite3

import cv2
import numpy as np


def make_video(path, reference):
    source = cv2.imread(str(reference))
    assert source is not None
    h, w = source.shape[:2]
    patch = source[:int(h*.77), int(w*.23):int(w*.80)]
    patch = cv2.resize(patch, (100, 220))
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), 10, (640, 360))
    assert writer.isOpened(), 'VP8 writer unavailable'
    try:
        for index in range(140):
            image = np.zeros((360, 640, 3), np.uint8)
            if 25 <= index < 105:
                center = round(50+(index-25)*7)
                left = center-50
                if left < 640:
                    right = min(640, left+100)
                    image[70:290, max(0, left):right] = patch[:, max(0, -left):right-left]
            writer.write(image)
    finally:
        writer.release()


def verify_counter(page, base, root, out, project, image):
    page.locator('#counterModeBtn').click()
    assert page.locator('#counterPanel').is_visible()
    assert not page.locator('#evidenceRounds').is_visible()
    images = []
    for filename in ['factory_scale_13_04_reference.jpg', 'factory_scale_7_02_full_reference.jpg',
                     'factory_scale_diagnostic_station-01.jpg']:
        with page.expect_response(lambda response: response.url.endswith('/api/counter/detect'), timeout=45000) as pending:
            page.locator('#counterImageFile').set_input_files(str(project/'data'/filename))
        response = pending.value
        result = response.json()
        assert response.ok, result
        assert result['still_image'] and result['count'] == 0
        page.wait_for_function("$('counterStatus').textContent.startsWith('Ảnh tĩnh:')")
        images.append({'file': filename, 'object_proposals': len(result['boxes']), 'elapsed_ms': result['elapsed_ms'], 'count': 0})
        page.screenshot(path=str(out/(filename+'.png')), full_page=True)
    video = out/'synthetic-one-roll.webm'
    make_video(video, project/'data/factory_scale_13_04_reference.jpg')
    page.locator('#counterVideoFile').set_input_files(str(video))
    page.wait_for_function("$('counterStatus').textContent.startsWith('Đã nạp video')")
    page.locator('#counterDetector').select_option('motion')
    page.locator('#counterStartBtn').click()
    page.wait_for_function('counter.active&&counter.targetTime>=1', timeout=30000)
    session_id = page.evaluate('counter.active.session_id')
    page.locator('#counterPauseBtn').click()
    page.wait_for_function('counter.paused&&!counter.inFlight')
    position = page.evaluate('counter.targetTime')
    page.wait_for_timeout(300)
    assert page.evaluate('counter.targetTime') == position
    page.locator('#counterPauseBtn').click()
    page.wait_for_function("!counter.active&&$('counterStatus').textContent.includes('hết video')", timeout=45000)
    assert page.locator('#counterCount').inner_text() == '1'
    page.wait_for_function("$('counterHistory').children.length>=1")
    folder = root/'data/roll-counter'/session_id
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    assert summary['count'] == 1 and summary['state'] == 'stopped'
    assert len(list(folder.glob('event-*.json'))) == 1
    assert len(list(folder.glob('event-*.jpg'))) == 1
    with page.expect_download() as downloaded:
        page.locator('#counterHistory button').first.click()
    csv_path = out/'counter.csv'
    downloaded.value.save_as(str(csv_path))
    rows = list(csv.reader(io.StringIO(csv_path.read_text(encoding='utf-8-sig'))))
    assert len(rows) == 2 and rows[1][3] == '1'
    page.screenshot(path=str(out/'video-counted.png'), full_page=True)
    # Exercise the existing native-camera bridge without opening a physical USB
    # camera. The unchanged factory scene must never increase the counter.
    native = {'sequence': 0}
    def bridge(route):
        action = route.request.url.rsplit('/', 1)[-1]
        if action == 'open':
            result = {'ok': True, 'source': 'counter-native-test'}
        elif action == 'stop':
            result = {'ok': True}
        else:
            native['sequence'] += 1
            result = {'ok': True, 'sequence': native['sequence'], 'image': image}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
    page.route(base+'/api/local/camera/*', bridge)
    page.locator('#localCameraBackend').select_option(label='DirectShow')
    page.locator('#counterCameraBtn').click()
    page.wait_for_function('current().stream&&current().video.readyState>=2&&current()._nativeImage')
    page.locator('#counterStartBtn').click()
    page.wait_for_function('counter.active&&counter.sequence>=12', timeout=30000)
    assert page.locator('#counterCount').inner_text() == '0'
    assert page.locator('#localCameraBackend').is_disabled()
    page.locator('#counterStopBtn').click()
    page.wait_for_function('!counter.active')
    page.set_viewport_size({'width': 375, 'height': 812})
    page.emulate_media(reduced_motion='reduce')
    page.screenshot(path=str(out/'counter-mobile.png'), full_page=True)
    page.locator('#productionModeBtn').click()
    assert page.locator('#evidenceRounds').is_visible()
    assert not page.locator('#counterPanel').is_visible()
    with sqlite3.connect(root/'data/measurements.db') as db:
        assert db.execute('SELECT COUNT(*) FROM measurements').fetchone() == (1,)
        assert db.execute('SELECT COUNT(*) FROM photo_drafts').fetchone() == (1,)
    return {'image_trials': images, 'video_is_synthetic': True, 'expected_video_count': 1,
            'actual_video_count': summary['count'], 'pause_resume': True, 'csv_export': True,
            'stationary_native_bridge_count': 0, 'no_weighing_or_warehouse_writes': True}
