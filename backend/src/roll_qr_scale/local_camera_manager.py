"""Native Windows camera bridge preserving the tested DirectShow/MSMF controls."""
import base64
import threading
import time
import uuid

import cv2

from .local_camera import Camera


class LocalCameraManager:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()
        self.closed = threading.Event()
        threading.Thread(target=self._reap, daemon=True, name='LocalCameraWatchdog').start()

    def _reap(self):
        while not self.closed.wait(2):
            with self.lock:
                for station, item in list(self.items.items()):
                    if time.monotonic()-item['poll'] > 8:
                        item['camera'].close()
                        del self.items[station]

    def close(self):
        self.closed.set()
        with self.lock:
            for item in self.items.values():
                item['camera'].close()
            self.items.clear()

    def handle(self, path, payload, station, camera_id):
        with self.lock:
            if path.endswith('/open'):
                index = int(payload.get('index', 0))
                backend = str(payload.get('backend', 'DirectShow'))
                if not 0 <= index <= 9 or backend not in {'DirectShow', 'Media Foundation'}:
                    raise ValueError('Camera hoặc driver không hợp lệ')
                for owner, item in self.items.items():
                    if owner != station and item['index'] == index:
                        raise ValueError('Camera USB đang được gán cho trạm khác')
                old = self.items.pop(station, None)
                if old:
                    old['camera'].close()
                native = Camera(index, cv2.CAP_DSHOW if backend == 'DirectShow' else cv2.CAP_MSMF)
                self.items[station] = {'camera': native, 'id': str(uuid.uuid4()),
                    'poll': time.monotonic(), 'index': index}
                return {'ok': True, 'source': self.items[station]['id']}
            item = self.items.get(station)
            if not item or item['id'] != payload.get('source'):
                raise ValueError('Camera đã dừng hoặc đã đổi nguồn')
            if path.endswith('/stop'):
                item['camera'].close()
                del self.items[station]
                return {'ok': True}
            if not path.endswith('/frame'):
                raise ValueError('Lệnh camera không hợp lệ')
            item['poll'] = time.monotonic()
            frame = item['camera'].latest()
            if item['camera'].failed():
                raise ValueError('Không mở được camera; thử Camera 1/2 hoặc đổi driver')
            if frame is None:
                return {'ok': True, 'waiting': True}
            image, captured_at = frame
            if time.monotonic()-captured_at > 1:
                return {'ok': True, 'waiting': True}
            # Preserve the exact pixels used by the successful desktop trial.
            # This loopback bridge uses lossless PNG; production evidence is JPEG later.
            ok, encoded = cv2.imencode('.png', image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
            if not ok:
                raise ValueError('Không mã hóa được hình camera')
            return {'ok': True, 'sequence': item['camera'].sequence,
                'image': 'data:image/png;base64,'+base64.b64encode(encoded).decode('ascii')}
