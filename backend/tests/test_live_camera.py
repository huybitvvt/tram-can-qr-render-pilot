from __future__ import annotations

import time
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from roll_qr_scale.live_camera import LiveCamera


class _FakeCapture:
    def __init__(self) -> None:
        self.opened = True

    def isOpened(self) -> bool:
        return self.opened

    def set(self, *_args: object) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray]:
        time.sleep(0.01)
        return True, np.zeros((80, 120, 3), dtype=np.uint8)

    def release(self) -> None:
        self.opened = False


class _FakeDetector:
    model_version = "model_2"

    def detect_with_details(self, _image: np.ndarray) -> SimpleNamespace:
        return SimpleNamespace(digits=[], display=None)


class _FakeQrDecoder:
    def decode(self, _image: np.ndarray) -> None:
        return None


class LiveCameraTests(unittest.TestCase):
    def test_recognition_loop_publishes_snapshot_without_hardware(self) -> None:
        camera = LiveCamera(
            "0", _FakeDetector(), _FakeQrDecoder(), inference_fps=20,
        )
        with patch.object(camera, "_open", side_effect=lambda _source: _FakeCapture()):
            camera.start()
            deadline = time.monotonic() + 3
            snapshot = None
            while time.monotonic() < deadline:
                snapshot = camera.snapshot()
                if snapshot is not None:
                    break
                time.sleep(0.02)
            camera.stop()
        self.assertIsNotNone(snapshot)
        frame, event, frame_id = snapshot  # type: ignore[misc]
        self.assertEqual(frame.shape, (80, 120, 3))
        self.assertGreater(frame_id, 0)
        self.assertEqual(event["status"], "WAITING")

    def test_switching_source_clears_old_snapshot(self) -> None:
        camera = LiveCamera("0", _FakeDetector(), _FakeQrDecoder())
        camera._raw = np.zeros((2, 2, 3), dtype=np.uint8)
        camera._recognized_raw = camera._raw
        camera._recognized_id = 1
        camera.select_source("1")
        self.assertIsNone(camera.snapshot())
        self.assertEqual(camera.source, "1")

    def test_capture_uses_newest_frame_and_never_reuses_preview_recognition(self) -> None:
        camera = LiveCamera("0", _FakeDetector(), _FakeQrDecoder())
        camera._connected = True
        camera._raw = np.full((2, 2, 3), 90, dtype=np.uint8)
        camera._frame_id = 12
        camera._raw_at = time.monotonic()
        camera._event = {"qr": {"data": "OLD-QR"}, "numeric_value": 99}
        frame, event, frame_id = camera.capture_snapshot()
        self.assertEqual(frame_id, 12)
        self.assertEqual(int(frame[0, 0, 0]), 90)
        self.assertIsNone(event["qr"])
        self.assertIsNone(event["numeric_value"])
        camera._raw_at = time.monotonic() - 3
        self.assertIsNone(camera.capture_snapshot())

    def test_preview_frames_advance_while_model_is_blocked(self) -> None:
        entered, unblock = threading.Event(), threading.Event()
        detector = _FakeDetector()
        def blocked_detect(image):
            entered.set()
            unblock.wait(3)
            return SimpleNamespace(digits=[], display=None)
        detector.detect_with_details = blocked_detect
        camera = LiveCamera("0", detector, _FakeQrDecoder())
        with patch.object(camera, "_open", side_effect=lambda _: _FakeCapture()):
            camera.start()
            try:
                self.assertTrue(entered.wait(2))
                first = camera.capture_snapshot()
                self.assertIsNotNone(first)
                self.assertIsNone(camera.snapshot())
                with camera._condition:
                    advanced = camera._condition.wait_for(lambda: camera._frame_id > first[2], timeout=1)
                self.assertTrue(advanced)
                self.assertGreater(camera.capture_snapshot()[2], first[2])
            finally:
                unblock.set()
                camera.stop()

    def test_selecting_new_source_interrupts_reconnect_backoff(self) -> None:
        failed = threading.Event()
        camera = LiveCamera("0", _FakeDetector(), _FakeQrDecoder(), reconnect_seconds=30)
        def open_camera(source):
            if source == 0:
                failed.set()
                raise OSError("Unplugged")
            return _FakeCapture()
        with patch.object(camera, "_open", side_effect=open_camera):
            camera.start()
            try:
                self.assertTrue(failed.wait(2))
                camera.select_source("1")
                with camera._condition:
                    connected = camera._condition.wait_for(lambda: camera._connected, timeout=1)
                self.assertTrue(connected)
            finally:
                camera.stop()


if __name__ == "__main__":
    unittest.main()
