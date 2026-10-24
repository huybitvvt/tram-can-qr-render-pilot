"""PP-OCRv6 trial-compatible reading and frame-bound live capture leases.

Preview frames and readings stay in RAM. Only a claimed Space/button capture
enters the existing durable photo/measurement workflow.
"""
from collections import deque
from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
import time
import uuid

import numpy as np

from tramcan_rapidocr.engine import ScaleReader
from tramcan_rapidocr.parsing import parse_weight
from .weight_ocr import parse_normalized_roi


def frame_digest(frame):
    return hashlib.sha256(str(frame.shape).encode()+frame.tobytes()).hexdigest()


@dataclass
class LiveFrame:
    station: str
    camera: str
    source: str
    settings: tuple
    frame_hash: str
    result: dict
    created: float
    stable: bool
    lease: tuple | None = None
    claimed_at: float = 0


class LocalLiveReader:
    def __init__(self, models: Path, *, reader=None, clock=time.monotonic):
        self.models = models
        self.reader = reader
        self.clock = clock
        self.model_lock = threading.Lock()
        self.lock = threading.RLock()
        self.states = {}
        self.frames = {}

    def preload(self):
        with self.model_lock:
            if self.reader is None:
                self.reader = ScaleReader(self.models, decimal_policy='fixed-2')

    def read(self, frame, roi='auto', fixed_two=True):
        self.preload()
        selected = None
        with self.model_lock:
            self.reader.fixed_digits = fixed_two
            if roi and roi != 'auto':
                selected = parse_normalized_roi(roi)
                h, w = frame.shape[:2]
                pixels = (round(selected.x1*w), round(selected.y1*h),
                          round(selected.x2*w), round(selected.y2*h))
                x1, y1, x2, y2 = pixels
                if x2-x1 < 12 or y2-y1 < 8:
                    raise ValueError('Vùng LED quá nhỏ; hãy chọn lại đủ dòng số cân')
                reading = self.reader.read_crop(frame[y1:y2, x1:x2])
            else:
                pixels = None
                reading = self.reader.read(frame)
        h, w = frame.shape[:2]
        regions = [pixels] if pixels else list(dict.fromkeys(
            o.region for o in reading.observations if o.region))
        if not pixels and reading.value is not None:
            matches = sorted((o for o in reading.observations if o.region and
                parse_weight(o.text, fixed_digits=fixed_two) == reading.value),
                key=lambda o: o.confidence, reverse=True)
            regions = list(dict.fromkeys([o.region for o in matches] + regions))
        raw = '; '.join(f'{o.variant}:{o.text!r}@{o.confidence:.3f}' for o in reading.observations)
        roi_text = roi if selected else (
            ','.join(str(round(v, 6)) for v in (regions[0][0]/w, regions[0][1]/h,
                                               regions[0][2]/w, regions[0][3]/h)) if regions else None)
        return {'ok': True, 'weight_found': reading.value is not None,
                'weight': float(reading.value) if reading.value is not None else None,
                'unit': 'kg', 'weight_raw': f'PP-OCRv6 small; {reading.reason}; {raw}',
                'confidence': max((o.confidence for o in reading.observations), default=0),
                'recognition_source': 'rapidocr-local', 'recognition_provider': 'rapidocr',
                'recognition_profile': 'small', 'roi': roi_text,
                'roi_method': 'manual-led' if selected else 'red-led',
                'regions': regions, 'elapsed_ms': reading.elapsed_ms,
                'observations': reading.as_dict()['observations'], 'reason': reading.reason,
                'gemini_used': False, 'codex_used': False, 'antigravity_used': False,
                'burst_frames': 1}

    def preview(self, frame, *, station, camera, source, sequence, roi='auto', fixed_two=True):
        if not source or len(source) > 128 or sequence < 1:
            raise ValueError('Nguồn camera/khung hình không hợp lệ')
        settings = (camera, source, roi, bool(fixed_two), frame.shape)
        with self.lock:
            state = self.states.get(station)
            if not state or state['settings'] != settings:
                state = self.states[station] = {'settings': settings, 'sequence': 0,
                    'history': deque(maxlen=3), 'since': None, 'count': 0, 'stable': False}
            if sequence <= state['sequence']:
                raise ValueError('Bỏ khung hình cũ của camera')
            state['sequence'] = sequence
        started = self.clock()
        result = self.read(frame, roi, fixed_two)
        now = self.clock()
        with self.lock:
            if self.states.get(station) is not state or state['sequence'] != sequence:
                raise ValueError('Camera hoặc vùng LED đã thay đổi; bỏ kết quả cũ')
            value = result['weight']
            history = state['history']
            if value is None or (history and (history[-1][0] != value or now-history[-1][1] > 2.5)):
                history.clear()
                state['since'], state['count'] = None, 0
            if value is not None:
                if state['since'] is None:
                    state['since'] = now
                state['count'] += 1
                history.append((value, now))
            # The duration belongs to the entire unchanged run, not the last
            # three samples: faster OCR must never prevent stability.
            stable = state['count'] >= 3 and now-state['since'] >= .45 and now-started <= 2.5
            state['stable'] = stable
            token = str(uuid.uuid4())
            recent = [key for key, item in self.frames.items() if item.station == station and not item.lease][-2:]
            self.frames = {key: item for key, item in self.frames.items()
                if now-(item.claimed_at or item.created) < (90 if item.lease else 3)
                and (item.lease or item.station != station or key in recent)}
            if len(self.frames) >= 128:
                raise ValueError('Có quá nhiều lượt cân đang chờ; hãy lưu hoặc bỏ lượt cũ')
            self.frames[token] = LiveFrame(station, camera, source, settings,
                frame_digest(frame), result, started, stable)
            return {**result, 'stable': stable, 'live_token': token,
                    'stable_frames': state['count'], 'stable_ms': round((now-state['since'])*1000) if state['since'] is not None else 0,
                    'sequence': sequence}

    def claim(self, token, *, station, camera, source, event, kind, round_index):
        now = self.clock()
        with self.lock:
            item = self.frames.get(token)
            if item is None or (item.station, item.camera, item.source) != (station, camera, source):
                raise ValueError('Kết quả không thuộc camera hiện tại; chờ số mới')
            lease = (event, kind, round_index)
            if item.lease:
                if item.lease != lease or now-item.claimed_at > 90:
                    raise ValueError('Số live đã được lấy cho ô khác hoặc đã hết hạn')
                return dict(item.result)
            state = self.states.get(station)
            if (not item.stable or now-item.created > 2.5 or not state or not state['stable'] or item.settings != state['settings']
                    or not state['history'] or state['history'][-1][0] != item.result['weight']):
                raise ValueError('Số cân chưa ổn định hoặc đã cũ; chờ số mới rồi nhấn Space')
            item.lease, item.claimed_at = lease, now
            return dict(item.result)

    def resolve(self, token, frame, *, station, camera, event, kind, round_index):
        with self.lock:
            item = self.frames.get(token)
            if (item is None or item.lease != (event, kind, round_index)
                    or (item.station, item.camera) != (station, camera)
                    or self.clock()-item.claimed_at > 90):
                raise ValueError('Lượt lấy số live không hợp lệ hoặc đã hết hạn')
            if item.frame_hash != frame_digest(frame):
                raise ValueError('Ảnh không khớp khung hình đã đọc cân; không ghép số cũ vào ảnh mới')
            return {**item.result, 'live_reused': True}
