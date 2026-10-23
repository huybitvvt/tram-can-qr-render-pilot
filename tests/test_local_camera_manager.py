import base64
import time

import cv2
import numpy as np
import pytest

from roll_qr_scale.local_camera_manager import LocalCameraManager


def test_native_bridge_preserves_trial_pixels_and_camera_ownership(monkeypatch):
    pixels = np.random.default_rng(82).integers(0, 256, (40, 60, 3), dtype=np.uint8)
    opened = []

    class Camera:
        sequence = 1
        def __init__(self, index, backend):
            self.index, self.backend, self.closed = index, backend, False
            opened.append(self)
        def latest(self): return pixels, time.monotonic()
        def failed(self): return False
        def close(self): self.closed = True

    monkeypatch.setattr('roll_qr_scale.local_camera_manager.Camera', Camera)
    manager = LocalCameraManager()
    try:
        result = manager.handle('/api/local/camera/open', {'index': 2, 'backend':'Media Foundation'}, 'station-02', 'camera-02')
        assert opened[0].index == 2 and opened[0].backend == cv2.CAP_MSMF
        frame = manager.handle('/api/local/camera/frame', {'source':result['source']}, 'station-02', 'camera-02')
        assert frame['sequence'] == 1 and frame['image'].startswith('data:image/png;base64,')
        decoded = cv2.imdecode(np.frombuffer(base64.b64decode(frame['image'].split(',')[1]), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert np.array_equal(decoded, pixels)  # no extra JPEG degradation before trial OCR
        with pytest.raises(ValueError, match='trạm khác'):
            manager.handle('/api/local/camera/open', {'index':2}, 'station-01', 'camera-01')
        with pytest.raises(ValueError, match='đổi nguồn'):
            manager.handle('/api/local/camera/frame', {'source':'wrong-source'}, 'station-02', 'camera-02')
        manager.handle('/api/local/camera/stop', {'source':result['source']}, 'station-02', 'camera-02')
        assert opened[0].closed and not manager.items
    finally:
        manager.close()


def test_native_camera_rejects_invalid_backend_and_device_before_driver_open(monkeypatch):
    def unexpected(*args): pytest.fail('Must reject before opening a camera')
    monkeypatch.setattr('roll_qr_scale.local_camera_manager.Camera', unexpected)
    manager = LocalCameraManager()
    try:
        for data in ({'index':-1}, {'index':99}, {'backend':'invalid-driver'}):
            with pytest.raises(ValueError, match='không hợp lệ'):
                manager.handle('/api/local/camera/open', data, 'station-01', 'camera-01')
    finally: manager.close()
