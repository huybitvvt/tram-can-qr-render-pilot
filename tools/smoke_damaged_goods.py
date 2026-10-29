"""Real Edge/ONNX smoke, called by smoke_rapidocr_workflow.py --damaged."""
import json
import sqlite3


def verify_damaged(page, base, root, out, image, expected):
    requests, snapshots = [], []
    page.on('request', lambda request: snapshots.append(request.url)
            if request.url.endswith('/api/local/snapshot') else None)
    page.locator('#damagedModeBtn').click()
    assert page.locator('#damagedPanel').is_visible()
    assert not page.locator('#analyzeCoreBtn').is_visible()
    # Simulate a lost acknowledgement AFTER the server has committed the first
    # ticket. The retry must reuse that exact event/image rather than duplicate it.
    lose_ack = [True]
    def save_route(route):
        requests.append(route.request.post_data_json)
        if lose_ack[0]:
            lose_ack[0] = False
            response = route.fetch()
            assert response.ok, response.text()
            route.abort()
        else:
            route.continue_()
    page.route(base+'/api/local/damaged-capture', save_route)
    native = {'sequence': 0, 'opens': 0}
    def native_route(route):
        action = route.request.url.rsplit('/', 1)[-1]
        if action == 'open':
            native['opens'] += 1
            result = {'ok': True, 'source': f"native-damaged-{native['opens']}"}
        elif action == 'stop':
            result = {'ok': True}
        else:
            native['sequence'] += 1
            result = {'ok': True, 'sequence': native['sequence'], 'image': image}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(result))
    page.route(base+'/api/local/camera/*', native_route)
    events = []
    for index, (category, backend) in enumerate([
        ('NKM', None), ('NKM', None), ('NC', 'DirectShow'), ('RM', 'Media Foundation')
    ]):
        if backend:
            page.locator('#localCameraBackend').select_option(label=backend)
            page.locator('#localOpenCamera').click()
            page.wait_for_function('current().stream&&current()._nativeImage&&current().video.readyState>=2')
        page.locator('#damagedKind').select_option(category)
        before = len(snapshots)
        page.locator('#damagedCaptureBtn').click()
        if index == 0:
            page.wait_for_function('current().damaged.job&&!current()._damagedBusy', timeout=30000)
            assert page.locator('#damagedWeight').input_value() == ''
            assert page.locator('#damagedKind').is_disabled()
            page.locator('#productionModeBtn').click()
            assert page.evaluate('workflowMode') == 'damaged'
            page.locator('#damagedCaptureBtn').click()
            assert requests[0] == requests[1]
        page.wait_for_function('current().damaged.saved&&!current().damaged.job&&!current()._damagedBusy', timeout=30000)
        assert float(page.locator('#damagedWeight').input_value()) == expected
        assert not page.locator('#evidenceRounds').is_visible()
        assert len(snapshots) == before+1
        event = requests[-1]['event_id']
        assert event not in events
        events.append(event)
        if backend:
            assert requests[-1]['image'] == image
        with sqlite3.connect(root/'data'/'measurements.db') as db:
            row = db.execute('SELECT qr_code,weight,product_weight,weight_stable,image_path,product_image_path,weight_raw FROM measurements WHERE event_id=?', (event,)).fetchone()
            assert row[:4] == (f'{category}_HH_{event}', 0, expected, 0), row
            assert row[4] and not row[5] and 'CORE_NOT_REQUIRED=1' in row[6]
            assert db.execute('SELECT COUNT(*) FROM measurements').fetchone() == (index+2,)
    # Verify the real list and intake selector. Only the warehouse catalogue is
    # simulated; no real warehouse or production account is touched.
    page.evaluate("async()=>{$('recordsFilterProductCode').value='';$('recordsFilterOrder').value='';await loadRecords()}")
    page.locator(f'button.nhap-kho-select[data-event-id="{events[0]}"]').click()
    page.route(base+'/api/warehouse/kho-thanh-pham', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({
            'ok': True, 'configured': True, 'warehouses': ['Kho thành phẩm'], 'selected': 'Kho thành phẩm'})))
    page.locator('#nhapKhoBtn').click()
    page.wait_for_function("$('nhapKhoWarehouse').value==='Kho hàng hỏng'")
    assert page.locator('#nhapKhoWarehouse').is_disabled()
    page.wait_for_function("$('nhapKhoMaSp').value==='NKM'")
    assert page.locator('#nhapKhoMaSp').input_value() == 'NKM'
    page.screenshot(path=str(out/'warehouse.png'), full_page=True)
    page.locator('#closeNhapKhoBtn').click()
    page.screenshot(path=str(out/'damaged.png'), full_page=True)
    page.set_viewport_size({'width': 375, 'height': 812})
    page.emulate_media(reduced_motion='reduce')
    assert page.locator('#damagedCaptureBtn').is_visible()
    assert not page.locator('#evidenceRounds').is_visible()
    page.screenshot(path=str(out/'damaged-mobile.png'), full_page=True)
    with sqlite3.connect(root/'data'/'measurements.db') as db:
        assert db.execute('SELECT COUNT(*) FROM photo_drafts').fetchone() == (1,)
        assert db.execute("SELECT weight FROM measurements WHERE qr_code='KEEP-RC80-RECORD'").fetchone() == (.75,)
    return {'categories': ['NKM', 'NKM', 'NC', 'RM'], 'weights': [expected]*4,
            'one_image_no_core': True, 'lost_ack_retry_idempotent': True,
            'warehouse_forced_in_ui': True, 'native_bridges_simulated': ['DirectShow', 'Media Foundation'],
            'new_records': len(events)}
