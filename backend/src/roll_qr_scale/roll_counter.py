"""Isolated, offline experimental video counter. Never writes weighing tickets."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import multiprocessing as mp
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np


MODEL = json.loads(Path(__file__).with_name('counter_model.json').read_text(encoding='utf-8'))


def model_path() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)/'assets/models/roll-counter'/MODEL['file']
    return Path(__file__).resolve().parents[3]/'models/roll-counter'/MODEL['file']


def number(value, low, high, name):
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} không hợp lệ') from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f'{name} phải từ {low} đến {high}')
    return result


def validate_frame(frame):
    if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
        or frame.shape[2] != 3 or min(frame.shape[:2]) < 16
        or max(frame.shape[:2]) > 1920 or frame.shape[0]*frame.shape[1] > 1920*1080):
        raise ValueError('Frame bộ đếm phải là ảnh màu, tối đa 1920×1080 pixel')


def settings(payload):
    mode = str(payload.get('detector', 'motion'))
    if mode not in {'motion', 'rfdetr'}:
        raise ValueError('Chọn detector chuyển động hoặc RF-DETR Nano')
    roi = payload.get('roi', [0, 0, 1, 1])
    if not isinstance(roi, list) or len(roi) != 4:
        raise ValueError('Vùng đếm phải có bốn tọa độ')
    roi = [number(v, 0, 1, 'Vùng đếm') for v in roi]
    if roi[2]-roi[0] < .05 or roi[3]-roi[1] < .05:
        raise ValueError('Vùng đếm quá nhỏ hoặc đảo tọa độ')
    direction = str(payload.get('direction', 'right'))
    if direction not in {'right', 'left', 'down', 'up'}:
        raise ValueError('Hướng ra máy không hợp lệ')
    axis = 0 if direction in {'right', 'left'} else 1
    line = number(payload.get('line', .5), .02, .98, 'Vị trí vạch')
    if not roi[axis]+.02 <= line <= roi[axis+2]-.02:
        raise ValueError('Vạch đếm phải nằm trong vùng đếm')
    return {'detector': mode, 'roi': roi, 'direction': direction, 'line': line,
            'confidence': number(payload.get('confidence', .15), .05, .95, 'Ngưỡng AI'),
            'min_area': number(payload.get('min_area', .01), .001, .4, 'Diện tích tối thiểu'),
            'fps': number(payload.get('fps', 5), 1, 15, 'FPS lấy mẫu')}


class RFDetector:
    def __init__(self, path=None):
        import onnxruntime as ort
        path = Path(path or model_path())
        if not path.is_file():
            raise ValueError('Thiếu model đếm cuộn. Cài lại bộ cài đầy đủ.')
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != MODEL['sha256']:
                raise ValueError('Checksum model đếm cuộn không khớp')
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.model = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])
        self.mean = np.array([.485, .456, .406], np.float32)
        self.std = np.array([.229, .224, .225], np.float32)

    def detect(self, frame, config):
        h, w = frame.shape[:2]
        image = cv2.cvtColor(cv2.resize(frame, (384, 384)), cv2.COLOR_BGR2RGB).astype(np.float32)/255
        tensor = ((image-self.mean)/self.std).transpose(2, 0, 1)[None]
        boxes, logits = self.model.run(['dets', 'labels'], {'input': tensor})
        probabilities = 1/(1+np.exp(-np.clip(logits[0], -60, 60)))
        classes = probabilities.argmax(1)
        scores = probabilities.max(1)
        output = []
        for box, score, category in zip(boxes[0], scores, classes):
            # COCO has no factory-roll class. These are object proposals within
            # an operator-selected exclusive exit ROI, not semantic roll labels.
            if score < config['confidence'] or category in {0, 1}:
                continue
            cx, cy, bw, bh = box
            x1, y1, x2, y2 = np.clip([cx-bw/2, cy-bh/2, cx+bw/2, cy+bh/2], 0, 1)
            if config['min_area'] <= (x2-x1)*(y2-y1) <= .95:
                output.append([x1*w, y1*h, x2*w, y2*h, float(score), int(category)])
        if not output:
            return np.empty((0, 6), np.float32)
        # Low-confidence COCO proposals can overlap; deduplicate independent of
        # the original semantic class before handing them to the tracker.
        rects = [[r[0], r[1], r[2]-r[0], r[3]-r[1]] for r in output]
        keep = cv2.dnn.NMSBoxes(rects, [r[4] for r in output], config['confidence'], .5)
        return np.asarray([output[int(i)] for i in np.asarray(keep).ravel()], np.float32).reshape(-1, 6)


class MotionDetector:
    def __init__(self):
        self.background = cv2.createBackgroundSubtractorMOG2(history=120, varThreshold=30, detectShadows=False)
        self.frames = 0

    def detect(self, frame, config):
        self.frames += 1
        mask = self.background.apply(frame, learningRate=.15 if self.frames <= 8 else .008)
        if self.frames <= 8:
            return np.empty((0, 6), np.float32)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        area = frame.shape[0]*frame.shape[1]
        output = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if config['min_area'] <= w*h/area <= .85 and cv2.contourArea(contour) > w*h*.2:
                output.append([x, y, x+w, y+h, .95, 0])
        return np.asarray(output, np.float32).reshape(-1, 6)


class CounterPipeline:
    def __init__(self, config, detector=None):
        import supervision as sv
        self.sv = sv
        self.config = config
        self.detector = detector or (RFDetector() if config['detector'] == 'rfdetr' else MotionDetector())
        self.total = 0
        self.epoch = 0
        self.states = {}
        self.last_time = None
        self.shape = None
        self.reset_tracking()

    def reset_tracking(self):
        sv, config = self.sv, self.config
        self.epoch += 1
        self.tracker = sv.ByteTrack(track_activation_threshold=.25,
                                    minimum_consecutive_frames=2,
                                    frame_rate=round(config['fps']), lost_track_buffer=60)
        x1, y1, x2, y2 = config['roi']
        p = config['line']
        start, end = ((p, y1), (p, y2)) if config['direction'] in {'right', 'left'} else ((x1, p), (x2, p))
        self.line = sv.LineZone(start=sv.Point(*start), end=sv.Point(*end), triggering_anchors=(sv.Position.CENTER,))
        self.states.clear()

    def process(self, frame, timestamp, *, detect_only=False):
        start = time.perf_counter()
        h, w = frame.shape[:2]
        if self.shape is not None and self.shape != (h, w):
            raise ValueError('Độ phân giải nguồn đã đổi. Dừng và mở lượt đếm mới.')
        self.shape = (h, w)
        interrupted = False
        if self.last_time is not None:
            if timestamp <= self.last_time:
                raise ValueError('Thời gian frame phải tăng; mở lượt mới khi tua lại video')
            if timestamp-self.last_time > 2:
                self.reset_tracking()
                interrupted = True
        self.last_time = timestamp
        x1, y1, x2, y2 = self.config['roi']
        left, top, right, bottom = int(x1*w), int(y1*h), int(x2*w), int(y2*h)
        crop = frame[top:bottom, left:right]
        found = self.detector.detect(crop, self.config)
        if len(found):
            found[:, [0, 2]] += left
            found[:, [1, 3]] += top
        sv = self.sv
        detections = sv.Detections(xyxy=found[:, :4], confidence=found[:, 4], class_id=found[:, 5].astype(int))
        events, boxes = [], []
        if detect_only:
            tracks = detections
        else:
            # COCO class confidence is not calibrated for unknown factory rolls.
            # The detector already applies the operator's threshold. Give these
            # accepted proposals a tracking score >= 0.5 so ByteTrack's fixed
            # unconfirmed-track gate does not silently discard the chosen range.
            # Preserve and restore the real model confidence for UI/evidence.
            tracking = sv.Detections(xyxy=found[:, :4], confidence=np.maximum(found[:, 4], .5),
                                     class_id=found[:, 5].astype(int), data={'model_score': found[:, 4]})
            tracks = self.tracker.update_with_detections(tracking)
            if len(tracks):
                tracks.confidence = tracks.data['model_score']
        for i, box in enumerate(tracks.xyxy):
            normalized = box/np.array([w, h, w, h])
            tid = int(tracks.tracker_id[i]) if tracks.tracker_id is not None else 0
            boxes.append({'box': normalized.tolist(), 'id': tid, 'score': float(tracks.confidence[i]),
                          'class_id': int(tracks.class_id[i])})
            if detect_only:
                continue
            axis = 0 if self.config['direction'] in {'right', 'left'} else 1
            center = float((normalized[axis]+normalized[axis+2])/2)
            distance = center-self.config['line']
            state = self.states.setdefault(tid, {'candidate': 0, 'streak': 0, 'side': 0, 'counted': False, 'seen': timestamp})
            state['seen'] = timestamp
            if abs(distance) < .025:
                state['streak'] = 0
                continue
            side = 1 if distance > 0 else -1
            state['streak'] = state['streak']+1 if state['candidate'] == side else 1
            state['candidate'] = side
            if state['streak'] < 2:
                continue
            previous = state['side']
            state['side'] = side
            # LineZone operates in normalized coordinates, with confirmed
            # centers outside the hysteresis band. It never sees warmup frames.
            accepted = sv.Detections(xyxy=normalized[None], confidence=np.array([1.]),
                                     class_id=np.array([0]), tracker_id=np.array([tid]))
            incoming, outgoing = self.line.trigger(accepted)
            destination = 1 if self.config['direction'] in {'right', 'down'} else -1
            if previous == -destination and side == destination and not state['counted'] and bool(incoming[0] or outgoing[0]):
                state['counted'] = True
                self.total += 1
                events.append({'number': self.total, 'track_id': f'{self.epoch}:{tid}',
                               'video_time': timestamp, 'box': normalized.tolist()})
        # Bound memory on a long shift, including LineZone's per-ID dictionary.
        expired = [tid for tid, state in self.states.items() if timestamp-state['seen'] > 30]
        for tid in expired:
            del self.states[tid]
            self.line.tracker_state.pop(tid, None)
        return {'count': self.total, 'boxes': boxes, 'events': events,
                'warmup': isinstance(self.detector, MotionDetector) and self.detector.frames <= 8,
                'interrupted': interrupted, 'elapsed_ms': round((time.perf_counter()-start)*1000, 1),
                'timestamp': timestamp}


def _worker(config, incoming, outgoing, cache_dir):
    os.environ['MPLBACKEND'] = 'Agg'
    os.environ['MPLCONFIGDIR'] = cache_dir
    cv2.setNumThreads(1)
    try:
        pipeline = CounterPipeline(config)
        outgoing.put({'ready': True})
        while True:
            job = incoming.get()
            if job is None:
                return
            try:
                outgoing.put({'ok': True, **pipeline.process(job['frame'], job['timestamp'], detect_only=job.get('detect_only', False))})
            except Exception as exc:
                outgoing.put({'ok': False, 'error': str(exc)})
    except Exception as exc:
        outgoing.put({'ok': False, 'error': str(exc)})


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class RollCounterManager:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()
        self.active = None
        self.closed = threading.Event()
        threading.Thread(target=self._watch, daemon=True, name='RollCounterWatchdog').start()

    def _watch(self):
        while not self.closed.wait(5):
            with self.lock:
                if self.active and time.monotonic()-self.active['seen'] > 90:
                    self._stop('idle_timeout')

    def _launch(self, config):
        ctx = mp.get_context('spawn')
        incoming, outgoing = ctx.Queue(1), ctx.Queue(1)
        cache = self.directory/'.cache'
        cache.mkdir(parents=True, exist_ok=True)
        process = ctx.Process(target=_worker, args=(config, incoming, outgoing, str(cache)), daemon=True, name='RollCounter')
        process.start()
        worker = {'process': process, 'in': incoming, 'out': outgoing}
        try:
            result = outgoing.get(timeout=25)
            if not result.get('ready'):
                raise ValueError(result.get('error', 'Không khởi tạo được bộ đếm'))
        except Exception:
            self._dispose(worker)
            raise
        return worker

    @staticmethod
    def _dispose(worker):
        process = worker['process']
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
        process.close()
        for name in ('in', 'out'):
            worker[name].cancel_join_thread()
            worker[name].close()

    def start(self, payload):
        config = settings(payload)
        source = str(payload.get('source') or '')
        if not source or len(source) > 128:
            raise ValueError('Nguồn video không hợp lệ')
        with self.lock:
            if self.active:
                summary = self.active['summary']
                if (summary['source'] == source and summary['settings'] == config
                    and all(summary[name] == str(payload.get(name) or '') for name in ('station_id', 'camera_id'))):
                    return {'ok': True, **summary}
                raise ValueError('Dừng lượt đếm đang chạy trước khi mở lượt mới')
            worker = self._launch(config)
            identity = str(uuid.uuid4())
            folder = self.directory/identity
            try:
                folder.mkdir(parents=True)
                summary = {'session_id': identity, 'station_id': str(payload.get('station_id') or ''),
                           'camera_id': str(payload.get('camera_id') or ''),
                           'machine': str(payload.get('machine') or '')[:80],
                           'source_kind': str(payload.get('source_kind') or 'camera')[:20],
                           'source': source, 'settings': config, 'count': 0, 'state': 'running',
                           'started_at': datetime.now(timezone.utc).isoformat(), 'model_sha256': MODEL['sha256'] if config['detector'] == 'rfdetr' else ''}
                atomic_json(folder/'summary.json', summary)
            except Exception:
                self._dispose(worker)
                raise
            self.active = {**worker, 'summary': summary, 'folder': folder, 'seen': time.monotonic(),
                           'sequence': -1, 'last_hash': '', 'last_result': None, 'pending': None}
            return {'ok': True, **summary}

    def _owned(self, payload):
        active = self.active
        if active is None:
            raise ValueError('Lượt đếm đã dừng. Mở lượt mới để tiếp tục.')
        summary = active['summary']
        for field in ('session_id', 'station_id', 'camera_id', 'source'):
            if str(payload.get(field) or '') != summary[field]:
                raise ValueError('Lượt đếm không thuộc nguồn/camera/trạm hiện tại')
        active['seen'] = time.monotonic()
        return active

    def frame(self, frame, payload):
        validate_frame(frame)
        sequence = number(payload.get('sequence'), 0, 10**9, 'Số thứ tự frame')
        if int(sequence) != sequence:
            raise ValueError('Số thứ tự frame phải là số nguyên')
        timestamp = number(payload.get('timestamp'), 0, 10**12, 'Thời gian video')
        digest = hashlib.sha256(frame.tobytes()+str(frame.shape).encode()+str(timestamp).encode()).hexdigest()
        with self.lock:
            active = self._owned(payload)
            if sequence == active['sequence']:
                if digest != active['last_hash']:
                    raise ValueError('Frame thử lại không khớp ảnh/thời gian cũ')
                return active['last_result']
            if sequence < active['sequence']:
                raise ValueError('Frame đến muộn đã bị bỏ')
            # Exactly one inference in flight. There is no shared OCR FIFO and
            # no unbounded video queue. A hung detector is disposable.
            if active['pending']:
                pending_sequence, pending_hash, result = active['pending']
                if (sequence, digest) != (pending_sequence, pending_hash):
                    raise ValueError('Thử lưu lại đúng frame chưa được xác nhận trước')
            else:
                try:
                    active['in'].put({'frame': frame, 'timestamp': timestamp}, timeout=1)
                    result = active['out'].get(timeout=12)
                except (queue.Empty, queue.Full):
                    self._stop('detector_timeout')
                    raise ValueError('Bộ nhận diện quá thời gian; lượt đếm đã dừng')
                active['pending'] = (sequence, digest, result)
            if not result.get('ok'):
                self._stop('detector_error')
                raise ValueError(result.get('error', 'Bộ nhận diện lỗi'))
            for event in result['events']:
                event.setdefault('recorded_at', datetime.now(timezone.utc).isoformat())
                target = active['folder']/f"event-{event['number']:08d}.json"
                # Retry writes the same numbered event. Evidence is a thumbnail
                # in this counter's own folder, never a scale capture or ticket.
                scale = min(1, 480/frame.shape[1])
                thumbnail = cv2.resize(frame, (round(frame.shape[1]*scale), round(frame.shape[0]*scale)))
                ok, encoded = cv2.imencode('.jpg', thumbnail, [cv2.IMWRITE_JPEG_QUALITY, 75])
                if not ok:
                    raise OSError('Không mã hóa được ảnh bằng chứng bộ đếm')
                image = target.with_suffix('.jpg')
                with image.open('wb') as stream:
                    stream.write(encoded.tobytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                atomic_json(target, event)
            summary = {**active['summary'], 'count': result['count']}
            if result['events']:
                atomic_json(active['folder']/'summary.json', summary)
            active['summary'] = summary
            response = {**result, 'local_saved': True, 'session_id': active['summary']['session_id'], 'sequence': sequence}
            active.update(sequence=sequence, last_hash=digest, last_result=response, pending=None)
            return response

    def detect(self, frame, payload):
        validate_frame(frame)
        config = settings({**payload, 'detector': 'rfdetr'})
        with self.lock:
            if self.active:
                raise ValueError('Dừng đếm trước khi thử ảnh tĩnh')
            worker = self._launch(config)
            try:
                worker['in'].put({'frame': frame, 'timestamp': 0, 'detect_only': True}, timeout=1)
                result = worker['out'].get(timeout=12)
                if not result.get('ok'):
                    raise ValueError(result.get('error'))
                return {**result, 'still_image': True, 'count': 0}
            finally:
                self._dispose(worker)

    def status(self, payload):
        with self.lock:
            active = self._owned(payload)
            return {'ok': True, **active['summary']}

    def _stop(self, reason='stopped'):
        active, self.active = self.active, None
        if not active:
            return {'ok': True, 'state': 'stopped'}
        self._dispose(active)
        active['summary']['count'] = self._durable_count(active['folder'])
        active['summary'].update(state=reason, stopped_at=datetime.now(timezone.utc).isoformat())
        atomic_json(active['folder']/'summary.json', active['summary'])
        return {'ok': True, **active['summary']}

    def stop(self, payload):
        with self.lock:
            self._owned(payload)
            return self._stop()

    def history(self):
        summaries = []
        if self.directory.is_dir():
            for path in self.directory.glob('*/summary.json'):
                try:
                    row = json.loads(path.read_text(encoding='utf-8'))
                    if row['session_id'] == path.parent.name:
                        row['count'] = self._durable_count(path.parent)
                        if row['state'] == 'running' and (not self.active or row['session_id'] != self.active['summary']['session_id']):
                            row['state'] = 'app_restarted'
                        summaries.append(row)
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(summaries, key=lambda item: item['started_at'], reverse=True)[:30]

    @staticmethod
    def _durable_count(folder):
        total = 0
        for path in sorted(folder.glob('event-*.json')):
            event = json.loads(path.read_text(encoding='utf-8'))
            if event['number'] != total+1 or not path.with_suffix('.jpg').is_file():
                break
            total += 1
        return total

    def export(self, identity):
        if str(uuid.UUID(identity)) != identity:
            raise ValueError('Lượt đếm không hợp lệ')
        folder = self.directory/identity
        summary = json.loads((folder/'summary.json').read_text(encoding='utf-8'))
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Lượt đếm', 'Máy', 'Trạm', 'Số thứ tự', 'ID theo dõi', 'Giây video', 'Thời gian UTC'])
        for path in sorted(folder.glob('event-*.json')):
            event = json.loads(path.read_text(encoding='utf-8'))
            # Prevent spreadsheet formulas in operator-supplied labels.
            label = summary['machine']
            if label.startswith(('=', '+', '-', '@')):
                label = "'"+label
            writer.writerow([identity, label, summary['station_id'], event['number'], event['track_id'], event['video_time'], event['recorded_at']])
        return ('\ufeff'+output.getvalue()).encode('utf-8')

    def close(self):
        self.closed.set()
        with self.lock:
            self._stop('app_closed')
