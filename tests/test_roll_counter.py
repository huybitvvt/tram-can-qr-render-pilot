import json
import os
from pathlib import Path
import queue
import uuid

import numpy as np
import pytest

os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parents[1]/'.test-tmp/counter-mpl-tests'))
from roll_qr_scale import roll_counter as counter


class Boxes:
    def __init__(self):
        self.boxes = []
        self.score = .95

    def detect(self, frame, config):
        return np.asarray([list(box)+[self.score, 0] for box in self.boxes], np.float32).reshape(-1, 6)


def run_boxes(positions, *, direction='right', axis='x', gap_at=None):
    detector = Boxes()
    pipeline = counter.CounterPipeline(counter.settings({'direction': direction}), detector)
    results = []
    now = 0
    frame = np.zeros((600, 1000, 3), np.uint8)
    for index, position in enumerate(positions):
        now += 3 if index == gap_at else .2
        if axis == 'x':
            detector.boxes = [(position-70, 150, position+70, 450)]
        else:
            detector.boxes = [(350, position-45, 650, position+45)]
        results.append(pipeline.process(frame, now))
    return pipeline, results


@pytest.mark.parametrize('direction,positions,axis', [
    ('right', list(range(100, 901, 20)), 'x'),
    ('left', list(range(900, 99, -20)), 'x'),
    ('down', list(range(80, 521, 10)), 'y'),
    ('up', list(range(520, 79, -10)), 'y'),
])
def test_real_bytetrack_and_linezone_count_once_in_selected_direction(direction, positions, axis):
    pipeline, results = run_boxes(positions, direction=direction, axis=axis)
    assert pipeline.total == 1
    assert sum(len(result['events']) for result in results) == 1


def test_wrong_direction_still_object_jitter_and_return_do_not_add_rolls():
    assert run_boxes(list(range(900, 99, -20)))[0].total == 0
    assert run_boxes([300]*30)[0].total == 0
    assert run_boxes([490, 510, 495, 505]*10)[0].total == 0
    positions = list(range(100, 801, 20))+list(range(800, 199, -20))+list(range(200, 801, 20))
    assert run_boxes(positions)[0].total == 1


def test_gap_reinitializes_tracking_and_preserves_confirmed_total():
    positions = list(range(100, 801, 20))+list(range(800, 901, 20))
    pipeline, results = run_boxes(positions, gap_at=36)
    assert pipeline.total == 1 and results[36]['interrupted']


def test_two_parallel_objects_count_separately():
    detector = Boxes()
    pipeline = counter.CounterPipeline(counter.settings({}), detector)
    frame = np.zeros((600, 1000, 3), np.uint8)
    for index, x in enumerate(range(100, 901, 20)):
        detector.boxes = [(x-50, 60, x+50, 240), (x-50, 350, x+50, 530)]
        pipeline.process(frame, index*.2)
    assert pipeline.total == 2


def test_selected_ai_threshold_also_controls_track_activation():
    detector = Boxes();detector.score = .20
    pipeline = counter.CounterPipeline(counter.settings({'confidence': .15}), detector)
    frame = np.zeros((600, 1000, 3), np.uint8)
    for index, x in enumerate(range(100, 901, 20)):
        detector.boxes = [(x-70, 150, x+70, 450)]
        result = pipeline.process(frame, index*.2)
    assert pipeline.total == 1
    assert result['boxes'][0]['score'] == pytest.approx(.20)


def test_motion_video_warms_up_then_counts_one_moving_object():
    pipeline = counter.CounterPipeline(counter.settings({'detector': 'motion'}))
    frame = np.zeros((360, 640, 3), np.uint8)
    for index in range(10):
        result = pipeline.process(frame, index*.2)
        assert result['count'] == 0
    for index, x in enumerate(range(40, 601, 10), start=10):
        image = frame.copy()
        image[80:280, max(0, x-30):min(640, x+30)] = 220
        result = pipeline.process(image, index*.2)
    assert result['count'] == 1


@pytest.mark.parametrize('payload', [
    {'roi': [0, 0, .01, 1]}, {'roi': [0, 0, 1]}, {'roi': [0, 0, float('nan'), 1]},
    {'line': .95, 'roi': [0, 0, .5, 1]}, {'direction': 'elsewhere'},
    {'fps': 0}, {'fps': float('inf')}, {'detector': 'unknown'}, {'confidence': .99},
])
def test_rejects_invalid_settings(payload):
    with pytest.raises(ValueError):
        counter.settings(payload)


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = counter.RollCounterManager(tmp_path/'counter')
    calls = []
    class Input:
        def put(self, job, timeout=1):
            calls.append(job)
    class Output:
        def get(self, timeout=12):
            number = len(calls)
            return {'ok': True, 'count': number, 'events': [{'number': number, 'track_id': f'1:{number}', 'video_time': calls[-1]['timestamp'], 'box': [.1, .1, .3, .5]}], 'boxes': []}
    monkeypatch.setattr(manager, '_launch', lambda config: {'in': Input(), 'out': Output()})
    monkeypatch.setattr(manager, '_dispose', lambda worker: None)
    payload = {'station_id': 'station-01', 'camera_id': 'camera-01', 'machine': '=TEST', 'source': str(uuid.uuid4())}
    result = manager.start(payload)
    identity = {name: result[name] for name in ('station_id', 'camera_id', 'source', 'session_id')}
    yield manager, calls, payload, identity
    manager.close()


def test_start_and_frame_retries_are_idempotent_and_saved_separately_from_weighing(manager):
    manager, calls, start, identity = manager
    assert manager.start(start)['session_id'] == identity['session_id']
    frame = np.zeros((80, 100, 3), np.uint8)
    payload = {**identity, 'sequence': 1, 'timestamp': 1.0}
    first = manager.frame(frame, payload)
    assert first['local_saved'] and first['count'] == 1
    assert manager.frame(frame, payload) == first and len(calls) == 1
    assert len(list(manager.directory.glob('*/event-*.json'))) == 1
    assert manager.history()[0]['count'] == 1
    exported = manager.export(identity['session_id']).decode('utf-8-sig')
    assert "'=TEST" in exported and '1:1' in exported
    assert manager.stop(identity)['count'] == 1
    assert manager.active is None


@pytest.mark.parametrize('field', ['station_id', 'camera_id', 'source', 'session_id'])
def test_manager_rejects_frames_from_another_owner_before_inference(manager, field):
    manager, calls, _, identity = manager
    with pytest.raises(ValueError, match='không thuộc'):
        manager.frame(np.zeros((40, 40, 3), np.uint8), {**identity, field: 'other', 'sequence': 1, 'timestamp': 0})
    assert calls == []


def test_retry_cannot_replace_image_or_time_and_late_frames_cannot_advance_count(manager):
    manager, calls, _, identity = manager
    frame = np.zeros((40, 40, 3), np.uint8)
    payload = {**identity, 'sequence': 2, 'timestamp': 1}
    manager.frame(frame, payload)
    for image, body in [(frame+1, payload), (frame, {**payload, 'timestamp': 2}), (frame, {**payload, 'sequence': 1})]:
        with pytest.raises(ValueError):
            manager.frame(image, body)
    assert len(calls) == 1


def test_disk_failure_retains_exact_pending_result_and_does_not_rerun_tracker(manager, monkeypatch):
    manager, calls, _, identity = manager
    frame = np.zeros((40, 40, 3), np.uint8)
    payload = {**identity, 'sequence': 1, 'timestamp': 1}
    original = counter.atomic_json
    def fail_summary(path, value):
        if path.name == 'summary.json':
            raise OSError('disk full')
        original(path, value)
    monkeypatch.setattr(counter, 'atomic_json', fail_summary)
    with pytest.raises(OSError):
        manager.frame(frame, payload)
    assert manager.active['summary']['count'] == 0
    monkeypatch.setattr(counter, 'atomic_json', original)
    assert manager.frame(frame, payload)['count'] == 1 and len(calls) == 1


def test_hung_detector_stops_worker_and_preserves_previous_count(manager):
    manager, calls, _, identity = manager
    class Timeout:
        def get(self, timeout):
            raise queue.Empty
    manager.active['out'] = Timeout()
    with pytest.raises(ValueError, match='quá thời gian'):
        manager.frame(np.zeros((40, 40, 3), np.uint8), {**identity, 'sequence': 1, 'timestamp': 1})
    assert manager.active is None and manager.history()[0]['count'] == 0
    assert manager.history()[0]['state'] == 'detector_timeout'


def test_history_recovers_saved_events_after_restart_without_resetting_them(manager):
    manager, _, _, identity = manager
    manager.frame(np.zeros((40, 40, 3), np.uint8), {**identity, 'sequence': 1, 'timestamp': 1})
    path = manager.directory/identity['session_id']/'summary.json'
    summary = json.loads(path.read_text(encoding='utf-8'));summary['count'] = 0
    counter.atomic_json(path, summary)
    restarted = counter.RollCounterManager(manager.directory)
    try:
        assert restarted.history()[0]['count'] == 1
        assert restarted.history()[0]['state'] == 'app_restarted'
    finally:
        restarted.close()
