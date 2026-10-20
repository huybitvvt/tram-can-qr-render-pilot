"""A single capture worker shared by video and recognition clients."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import cv2
import numpy as np

from backend.camera.source import backend_id, parse_source
from backend.config import Settings, redact_source

logger = logging.getLogger(__name__)


def _open_capture(source: int | str, camera_backend: str | None) -> cv2.VideoCapture:
    api = backend_id(camera_backend)
    return cv2.VideoCapture(source) if api is None else cv2.VideoCapture(source, api)


@dataclass(frozen=True)
class Frame:
    frame_id: int
    captured_at: datetime
    image: np.ndarray


class CaptureService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: Frame | None = None
        self._connected = False
        self._frame_id = 0
        self._jpeg_lock = threading.Lock()
        self._jpeg_cache: tuple[int, int, bytes] | None = None

    @property
    def connected(self) -> bool:
        with self._condition:
            return self._connected

    def latest(self) -> Frame | None:
        with self._condition:
            return self._latest

    def wait_for_frame(self, after_id: int, timeout: float = 1) -> Frame | None:
        with self._condition:
            self._condition.wait_for(lambda: self._stop.is_set() or (self._latest is not None and self._latest.frame_id > after_id), timeout)
            return self._latest if self._latest is not None and self._latest.frame_id > after_id else None

    def encode_jpeg(self, frame: Frame, quality: int) -> bytes | None:
        with self._jpeg_lock:
            if self._jpeg_cache is not None and self._jpeg_cache[:2] == (frame.frame_id, quality):
                return self._jpeg_cache[2]
            ok, encoded = cv2.imencode(".jpg", frame.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                return None
            data = encoded.tobytes()
            self._jpeg_cache = (frame.frame_id, quality, data)
            return data

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        source = parse_source(self.settings.camera_source)
        while not self._stop.is_set():
            capture = None
            try:
                capture = _open_capture(source, self.settings.camera_backend)
                if not capture.isOpened():
                    logger.warning("Camera unavailable: %s", redact_source(str(source)))
                    self._mark_disconnected()
                    self._stop.wait(self.settings.camera_reconnect_seconds)
                    continue
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.settings.frame_width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.settings.frame_height)
                capture.set(cv2.CAP_PROP_FPS, self.settings.camera_fps)
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                logger.info("Camera connected: %s", redact_source(str(source)))
                while not self._stop.is_set():
                    ok, image = capture.read()
                    if not ok or image is None:
                        logger.warning("Camera read failed; reconnecting")
                        break
                    with self._condition:
                        self._frame_id += 1
                        self._latest = Frame(self._frame_id, datetime.now(timezone.utc), image)
                        self._connected = True
                        self._condition.notify_all()
            except Exception as error:
                logger.error("Camera capture failed: %s", type(error).__name__)
            finally:
                if capture is not None:
                    capture.release()
                self._mark_disconnected()
            self._stop.wait(self.settings.camera_reconnect_seconds)

    def _mark_disconnected(self) -> None:
        with self._condition:
            self._connected = False
            self._latest = None
            self._condition.notify_all()
