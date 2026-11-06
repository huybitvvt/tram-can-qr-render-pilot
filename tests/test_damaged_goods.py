from decimal import Decimal
from pathlib import Path
import uuid

import numpy as np
import pytest

from tramcan_rapidocr.decision import Reading, Observation
from roll_qr_scale import warehouse
from roll_qr_scale.damaged_goods import DAMAGED_WAREHOUSE, warehouse_for_items
from roll_qr_scale.local_live import LocalLiveReader
from roll_qr_scale.storage import MeasurementStore, EventIdConflictError
from roll_qr_scale.test_ui import StationUIService, _local_measurement_items, _sync_row_has_error


@pytest.fixture
def capture(tmp_path, monkeypatch):
    class Reader:
        fixed_digits = True
        calls = 0
        value = Decimal('13.04')

        def read(self, frame):
            self.calls += 1
            return Reading(self.value, 'complete-reading',
                           [Observation('13.04', .99, 'original', (1, 1, 25, 12))], 20)

        read_crop = read

    store = MeasurementStore(tmp_path/'damaged.db', tmp_path/'captures')
    service = StationUIService(store, None, None, None, weight_engine='rapidocr')
    reader, now = Reader(), [0.]
    service.local_live = LocalLiveReader(Path('unused'), reader=reader, clock=lambda: now[0])
    frame = np.zeros((30, 40, 3), np.uint8)
    result = service.local_live.snapshot(frame, station='station-01', camera='camera-01', source='test')
    payload = dict(station_id='station-01', camera_id='camera-01', source='test',
                   event_id=str(uuid.uuid4()), live_token=result['live_token'], damaged_kind='NKM',
                   machine='TEST-MACHINE', work_date='2026-10-29', shift='HC1', production_order='LSX-1')
    monkeypatch.setattr(service, 'decode_qr', lambda *_: pytest.fail('Must not decode QR'))
    yield service, store, frame, payload, reader, now
    service.close()
    store.close()


@pytest.mark.parametrize('category', ['NKM', 'NC', 'RM'])
def test_one_snapshot_saves_damaged_goods_without_core_or_extra_ocr(capture, category):
    service, store, frame, payload, reader, _ = capture
    payload['damaged_kind'] = category
    receipt = service.capture_damaged(frame, payload)
    assert receipt['local_saved'] and receipt['warehouse'] == DAMAGED_WAREHOUSE
    row = store.get(payload['event_id'])
    assert row.product_weight == 13.04 and row.weight == 0  # no core deduction
    assert row.qr_code == f"{category}_HH_{payload['event_id']}"
    assert not row.weight_stable and 'MANUAL_SNAPSHOT=1' in row.weight_raw
    assert 'CORE_NOT_REQUIRED=1' in row.weight_raw and 'BI_WEIGHT=0' in row.weight_raw
    assert Path(row.image_path).is_file() and not row.product_image_path
    assert not _sync_row_has_error(row)
    assert reader.calls == 1
    displayed = _local_measurement_items(store, 10)[0]
    assert displayed['damaged_kind'] == category
    assert displayed['core_weight'] is None and displayed['net_weight'] == 13.04
    assert not displayed['has_core_image'] and displayed['has_product_image']
    assert service.capture_damaged(frame, payload)['duplicate']
    assert len(store.recent(10)) == 1 and reader.calls == 1


@pytest.mark.parametrize('change', ['category', 'station', 'camera', 'source', 'frame', 'expired', 'unit'])
def test_rejects_invalid_type_or_snapshot_identity_before_write(capture, change):
    service, store, frame, payload, _, now = capture
    if change == 'category': payload['damaged_kind'] = 'OTHER'
    elif change == 'frame': frame = frame + 1
    elif change == 'expired': now[0] = 601
    elif change == 'unit': payload['unit'] = 'g'
    else: payload[{'station': 'station_id', 'camera': 'camera_id'}.get(change, change)] = 'other'
    with pytest.raises(ValueError):
        service.capture_damaged(frame, payload)
    assert not store.recent(10)


def test_new_event_cannot_reuse_snapshot_and_changed_category_cannot_overwrite_event(capture):
    service, store, frame, payload, _, _ = capture
    service.capture_damaged(frame, payload)
    with pytest.raises(ValueError):
        service.capture_damaged(frame, {**payload, 'event_id': str(uuid.uuid4())})
    with pytest.raises(EventIdConflictError):
        service.capture_damaged(frame, {**payload, 'damaged_kind': 'NC'})
    assert store.get(payload['event_id']).qr_code.startswith('NKM_HH_')


def test_repeated_same_category_has_unique_codes_for_warehouse(capture):
    service, store, frame, payload, _, _ = capture
    first = service.capture_damaged(frame, payload)
    result = service.local_live.snapshot(frame, station='station-01', camera='camera-01', source='test')
    second = service.capture_damaged(frame, {**payload, 'event_id': str(uuid.uuid4()), 'live_token': result['live_token']})
    assert first['qr_code'] != second['qr_code']
    assert len(store.recent(10)) == 2


def test_production_still_requires_both_images_even_with_forged_raw_tag(capture):
    service, store, frame, _, _, _ = capture
    with pytest.raises(ValueError, match='ảnh lõi'):
        service.capture('NKM', 0, 'kg', frame, weight_raw='DAMAGED_KIND=NKM', product_weight=13.04)
    assert not store.recent(10)


def test_warehouse_enforces_destination_before_any_cloud_write(capture, monkeypatch):
    service, store, frame, payload, _, _ = capture
    service.capture_damaged(frame, payload)
    item = _local_measurement_items(store, 10)[0]
    written = []
    monkeypatch.setattr(warehouse, 'kho_configured', lambda: True)
    monkeypatch.setattr(warehouse, 'kho_supabase_url', lambda: 'https://test.invalid')
    monkeypatch.setattr(warehouse, 'kho_supabase_key', lambda: 'test')
    def write(*args, **kwargs):
        written.append(kwargs)
        return {'saved': [{'ma_sp_quet': item['qr_code'], 'ma_phieu': 'PN-TEST'}],
                'saved_event_ids': [item['event_id']], 'duplicate_event_ids': [],
                'duplicateCodes': [], 'ma_phieu': 'PN-TEST', 'header': {}}
    monkeypatch.setattr(warehouse, 'write_nhap_kho_batch', write)
    monkeypatch.setattr(warehouse, 'append_nhap_kho_summary_row', lambda entry: {'ok': True, 'rows': [entry]})
    def weigh_request(ids, receipt):
        return {'items': [item], 'confirmed_count': len(ids)}
    result = warehouse.confirm_nhap_kho(items=[item], kho='Kho thành phẩm', ca='HC1',
        may='TEST-MACHINE', ngay='2026-10-29', ma_sp='NKM', so_cuon=1,
        event_ids=[item['event_id']], nguoi='TEST', run_manual_sync=None,
        weigh_request=weigh_request, weigh_supabase_url='', weigh_supabase_key='')
    assert written[0]['kho'] == result['kho'] == DAMAGED_WAREHOUSE
    assert written[0]['items'][0]['ma_sp_quet'] == item['qr_code']
    with pytest.raises(ValueError, match='Đẩy riêng'):
        warehouse_for_items([item, {'qr_code': 'SP_A'}], 'Kho thành phẩm')
