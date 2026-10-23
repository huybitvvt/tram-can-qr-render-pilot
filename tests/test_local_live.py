from decimal import Decimal
from pathlib import Path
import sqlite3
import uuid

import numpy as np
import pytest

from tramcan_rapidocr.decision import Reading, Observation
from roll_qr_scale.local_live import LocalLiveReader
from roll_qr_scale.test_ui import StationUIService, build_parser, create_server
from roll_qr_scale.storage import MeasurementStore
from roll_qr_scale.windows_app import build_rapidocr_argv, backup_before_rapidocr_upgrade


class Reader:
    def __init__(self):
        self.value = Decimal('6.33')
        self.calls = []
        self.fixed_digits = True

    def read(self, image):
        self.calls.append((image.copy(), self.fixed_digits))
        return Reading(self.value, 'complete-reading', [Observation('6.33', .99, 'original', (1, 1, 25, 12))], 20)

    read_crop = read


def setup_reader():
    clock = [0.]
    reader = Reader()
    live = LocalLiveReader(Path('not-used'), reader=reader, clock=lambda: clock[0])
    frame = np.zeros((30, 40, 3), np.uint8)
    return live, reader, frame, clock


def preview(live, frame, seq, **kwargs):
    return live.preview(frame, station='station-01', camera='camera-01', source='source-1', sequence=seq, **kwargs)


def stable_frame(live, frame, clock):
    result = None
    for i in range(1, 4):
        clock[0] = i*.4
        result = preview(live, frame, i)
        assert result['stable'] == (i == 3)
    return result


def claim(live, token, **kwargs):
    return live.claim(token, station='station-01', camera='camera-01', source='source-1',
                      event='event-1', kind='product', round_index=1, **kwargs)


def test_space_claim_reuses_exact_frame_without_another_ocr_call():
    live, reader, frame, clock = setup_reader()
    result = stable_frame(live, frame, clock)
    claim(live, result['live_token'])
    # Replace OCR with a failure: a capture must still resolve the already-read frame.
    reader.read = lambda _: pytest.fail('Space must never rerun OCR')
    reused = live.resolve(result['live_token'], frame, station='station-01', camera='camera-01',
                          event='event-1', kind='product', round_index=1)
    assert reused['live_reused'] and reused['weight'] == 6.33 and len(reader.calls) == 3
    with pytest.raises(ValueError, match='khớp'):
        live.resolve(result['live_token'], frame+1, station='station-01', camera='camera-01',
                     event='event-1', kind='product', round_index=1)


@pytest.mark.parametrize('change', ['age', 'value', 'roi', 'decimal', 'missing'])
def test_stale_or_reconfigured_live_weight_is_never_claimed(change):
    live, reader, frame, clock = setup_reader()
    result = stable_frame(live, frame, clock)
    if change == 'age':
        clock[0] += 3
    else:
        if change == 'value': reader.value = Decimal('7.00')
        if change == 'missing': reader.value = None
        preview(live, frame, 4, **({'roi': '.1,.1,.9,.9'} if change == 'roi' else
                                  {'fixed_two': False} if change == 'decimal' else {}))
    with pytest.raises(ValueError): claim(live, result['live_token'])


def test_previous_frame_of_same_stable_value_can_be_claimed_while_new_preview_completes():
    live, reader, frame, clock = setup_reader()
    result = stable_frame(live, frame, clock)
    clock[0] += .4
    preview(live, frame, 4)
    assert claim(live, result['live_token'])['weight'] == 6.33


def test_claim_cannot_be_used_for_another_round_camera_or_station():
    live, reader, frame, clock = setup_reader()
    result = stable_frame(live, frame, clock)
    claim(live, result['live_token'])
    for field, value in [('station', 'station-02'), ('camera', 'camera-02'),
                         ('round_index', 2), ('kind', 'core'), ('event', 'event-2')]:
        args = dict(station='station-01', camera='camera-01', event='event-1', kind='product', round_index=1)
        args[field] = value
        with pytest.raises(ValueError): live.resolve(result['live_token'], frame, **args)


def test_manual_roi_reads_only_selected_pixels_and_obeys_decimal_switch():
    live, reader, frame, clock = setup_reader()
    frame[:] = np.arange(40, dtype=np.uint8)[None, :, None]
    result = live.read(frame, '.1,.1,.9,.9', False)
    assert reader.calls[0][0].shape == (24, 32, 3)
    assert np.array_equal(reader.calls[0][0], frame[3:27, 4:36])
    assert reader.calls[0][1] is False and result['roi_method'] == 'manual-led'


@pytest.mark.parametrize('engine', ['gemini', 'local-yolo', 'local', 'rapidocr'])
def test_upgrade_uses_old_config_and_data_paths_without_gemini(tmp_path, monkeypatch, engine):
    for key in list(__import__('os').environ):
        if key.startswith('ROLL_SCALE_'): monkeypatch.delenv(key)
    monkeypatch.setenv('ROLL_SCALE_WEIGHT_ENGINE', engine)
    monkeypatch.setenv('ROLL_SCALE_GEMINI_API_KEY', 'invalid-old-key-never-used')
    args = build_parser().parse_args(build_rapidocr_argv(tmp_path, tmp_path))
    assert args.weight_engine == 'rapidocr' and not args.gemini_fallback
    assert Path(args.db) == tmp_path/'data'/'measurements.db'
    assert Path(args.captures) == tmp_path/'data'/'captures'


def test_upgrade_snapshot_contains_latest_wal_and_does_not_restore_older_data(tmp_path):
    data = tmp_path/'data';data.mkdir()
    config = tmp_path/'config.env';config.write_bytes(b'ROLL_SCALE_WEIGHT_ENGINE=gemini\r\n')
    with sqlite3.connect(data/'measurements.db') as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute('CREATE TABLE customer_data (value TEXT)')
        connection.execute("INSERT INTO customer_data VALUES ('latest-rc80')")
        connection.commit()
        backup = backup_before_rapidocr_upgrade(tmp_path, config)
        with sqlite3.connect(backup/'measurements.db') as snapshot:
            assert snapshot.execute('SELECT value FROM customer_data').fetchone() == ('latest-rc80',)
        assert backup_before_rapidocr_upgrade(tmp_path, config) == backup
        assert connection.execute('SELECT value FROM customer_data').fetchone() == ('latest-rc80',)
    assert config.read_bytes() == (backup/'config.env').read_bytes()


def test_upgrade_does_not_mark_corrupt_database_backed_up(tmp_path):
    data = tmp_path/'data';data.mkdir()
    (data/'measurements.db').write_bytes(b'corrupt sqlite')
    with pytest.raises(sqlite3.DatabaseError):
        backup_before_rapidocr_upgrade(tmp_path, None)
    assert not (tmp_path/'backups'/'rapidocr-rc82.json').exists()


def test_claimed_product_uses_local_reader_without_gemini_or_ocr_again(tmp_path, monkeypatch):
    store = MeasurementStore(tmp_path/'existing.db', tmp_path/'captures')
    service = StationUIService(store, None, None, None, weight_engine='rapidocr')
    live, reader, frame, clock = setup_reader()
    service.local_live = live
    monkeypatch.setattr(service, '_decode_qr', lambda image: {'found': True, 'qr_code': 'QR-LIVE', 'decoder': 'zxing'})
    try:
        result = stable_frame(live, frame, clock)
        event = str(uuid.uuid4())
        live.claim(result['live_token'], station='station-01', camera='camera-01', source='source-1',
                   event=event, kind='product', round_index=1)
        monkeypatch.setattr(live, 'read', lambda *a, **k: pytest.fail('Must reuse live result'))
        analysis = service.analyze(frame, 'auto', 'kg', context_station_id='station-01',
            context_camera_id='camera-01', live_event_id=event, capture_kind='product',
            capture_round=1, live_token=result['live_token'])
        assert analysis['weight'] == 6.33 and analysis['live_reused']
        assert analysis['qr_code'] == 'QR-LIVE' and not analysis['gemini_used']
    finally:
        service.close(); store.close()
