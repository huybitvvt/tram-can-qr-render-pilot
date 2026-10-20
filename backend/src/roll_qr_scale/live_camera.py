"""Backend-owned live camera, detection snapshots, and MJPEG preview."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parents[3]
_NEW_BACKEND_SRC = _ROOT / "new_system" / "Digit_QRCode_Detection" / "backend" / "src"
if _NEW_BACKEND_SRC.is_dir() and str(_NEW_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_NEW_BACKEND_SRC))

try:
    from backend.camera.source import backend_id, parse_source
    from backend.config import redact_source
    from backend.cv.types import Box
    from backend.recognition.processor import build_recognition
    from backend.recognition.stabilizer import Stabilizer
except ImportError:  # Keep legacy tests importable if the optional local CV tree is absent.
    backend_id = parse_source = redact_source = Box = build_recognition = Stabilizer = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class LiveCamera:
    """Continuously capture frames and run the local QR/digit pipeline."""

    def __init__(
        self,
        source: str,
        detector: Any,
        qr_decoder: Any,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        reconnect_seconds: float = 2.0,
        camera_backend: str | None = None,
        inference_fps: float = 5.0,
        confidence: float = 0.7,
        decimal_places: int = 2,
        stable_frames: int = 3,
        jpeg_quality: int = 80,
        stream_fps: float = 20.0,
        rtsp_transport: str = "tcp",
        inference_lock: Any | None = None,
    ) -> None:
        if parse_source is None or build_recognition is None:
            raise RuntimeError("new_system local camera/CV modules are unavailable")
        self.detector = detector
        self.qr_decoder = qr_decoder
        self.width, self.height, self.fps = width, height, fps
        self.reconnect_seconds = reconnect_seconds
        self.camera_backend = camera_backend
        self.inference_fps = max(0.2, inference_fps)
        self.confidence = confidence
        self.decimal_places = decimal_places
        self.stabilizer = Stabilizer(stable_frames)
        self.jpeg_quality = jpeg_quality
        self.stream_fps = max(1.0, stream_fps)
        self.rtsp_transport = rtsp_transport
        self.inference_lock = inference_lock or threading.Lock()
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()
        self._capture_thread: threading.Thread | None = None
        self._recognition_thread: threading.Thread | None = None
        self._source = source
        self._source_generation = 0
        self._frame_id = 0
        self._raw: np.ndarray | None = None
        self._raw_at = 0.0
        self._raw_captured_at = datetime.now(timezone.utc)
        self._recognized_raw: np.ndarray | None = None
        self._recognized_id = 0
        self._recognized_at = 0.0
        self._annotated: np.ndarray | None = None
        self._event: dict[str, Any] = self._empty_event()
        self._connected = False
        self._jpeg_cache: tuple[int, bytes] | None = None

    @staticmethod
    def _empty_event() -> dict[str, Any]:
        return {
            "type": "recognition", "timestamp": 0, "frame_width": 0,
            "frame_height": 0, "detections": [], "qr": None,
            "raw_digits": None, "numeric_value": None, "confidence": None,
            "status": "WAITING",
        }

    @property
    def source(self) -> str:
        with self._condition:
            return self._source

    @property
    def connected(self) -> bool:
        with self._condition:
            return self._connected

    def start(self) -> None:
        with self._start_lock:
            if self._capture_thread and self._capture_thread.is_alive():
                return
            self._stop.clear()
            self._capture_thread = threading.Thread(target=self._capture_loop, name="live-camera", daemon=True)
            self._recognition_thread = threading.Thread(target=self._recognition_loop, name="live-recognition", daemon=True)
            self._capture_thread.start()
            self._recognition_thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        for thread in (self._capture_thread, self._recognition_thread):
            if thread:
                thread.join(timeout=5)
        with self._condition:
            self._connected = False
            self._recognized_raw = None

    def select_source(self, source: str) -> None:
        source = str(source).strip()
        parse_source(source)
        with self._condition:
            if source == self._source:
                return
            self._source = source
            self._source_generation += 1
            self._raw = self._annotated = None
            self._raw_at = 0.0
            self._recognized_raw = None
            self._recognized_id = 0
            self._recognized_at = 0.0
            self._connected = False
            self._event = self._empty_event()
            self.stabilizer = Stabilizer(self.stabilizer.required_frames)
            if hasattr(self.qr_decoder, "_last_box"):
                self.qr_decoder._last_box = None
            self._frame_id += 1
            self._condition.notify_all()
        logger.info("Live camera source changed to %s", redact_source(source))

    def _open(self, source: int | str) -> cv2.VideoCapture:
        if sys.platform == "win32":
            from .camera_process import IsolatedCapture
            with self._condition:
                generation = self._source_generation

            def cancelled():
                with self._condition:
                    return (self._stop.is_set() or generation != self._source_generation
                            or source != parse_source(self._source))

            return IsolatedCapture(source, self.camera_backend, self.width, self.height, self.fps, self.rtsp_transport,
                                   cancelled=cancelled)
        if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{self.rtsp_transport}"
        is_rtsp = isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://"))
        api = None if is_rtsp else backend_id(self.camera_backend)
        capture = cv2.VideoCapture(source) if api is None else cv2.VideoCapture(source, api)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            capture.set(cv2.CAP_PROP_FPS, self.fps)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def cameras(self, maximum_index: int = 7) -> list[dict[str, Any]]:
        """List selectable indexes without opening drivers from HTTP threads."""
        selected = self.source
        result: list[dict[str, Any]] = [{
            "id": "configured",
            "label": "Configured source from backend .env",
            "selected": not selected.isdecimal(),
        }]
        for index in range(maximum_index + 1):
            source = str(index)
            result.append({"id": source, "label": f"USB camera {index}", "selected": source == selected})
        if selected.isdecimal() and not any(item["id"] == selected for item in result):
            result.insert(0, {"id": selected, "label": f"Configured camera {selected}", "selected": True})
        return result

    @staticmethod
    def _release_capture(capture) -> None:
        if capture is not None:
            try:
                capture.release()
            except Exception:
                logger.exception("Camera release failed")

    def _wait_to_reconnect(self, generation: int) -> None:
        with self._condition:
            self._condition.wait_for(
                lambda: self._stop.is_set() or generation != self._source_generation,
                timeout=self.reconnect_seconds,
            )

    def _capture_loop(self) -> None:
        current_generation = -1
        capture: cv2.VideoCapture | None = None
        while not self._stop.is_set():
            with self._condition:
                source_text = self._source
                generation = self._source_generation
            if generation != current_generation:
                if capture is not None:
                    self._release_capture(capture)
                capture = None
                current_generation = generation
            if capture is None:
                try:
                    source = parse_source(source_text)
                    capture = self._open(source)
                    if not capture.isOpened():
                        logger.warning("Live camera unavailable: %s", redact_source(source_text))
                        self._release_capture(capture)
                        capture = None
                        with self._condition:
                            self._connected = False
                            self._condition.notify_all()
                        self._wait_to_reconnect(generation)
                        continue
                    logger.info("Live camera connected: %s", redact_source(source_text))
                except Exception:
                    with self._condition:
                        changed = generation != self._source_generation or self._stop.is_set()
                    if not changed:
                        logger.exception("Could not open live camera source")
                    self._release_capture(capture)
                    capture = None
                    self._wait_to_reconnect(generation)
                    continue
            try:
                ok, image = capture.read()
            except Exception:
                logger.exception("Could not read live camera frame")
                ok, image = False, None
            if not ok or image is None:
                self._release_capture(capture)
                capture = None
                with self._condition:
                    if generation != self._source_generation:
                        continue
                    self._connected = False
                    self._raw = self._recognized_raw = self._annotated = None
                    self._source_generation += 1
                    generation = self._source_generation
                    self._frame_id += 1
                    self._event = self._empty_event()
                    self.stabilizer = Stabilizer(self.stabilizer.required_frames)
                    self._jpeg_cache = None
                    self._condition.notify_all()
                self._wait_to_reconnect(generation)
                continue
            with self._condition:
                if generation != self._source_generation:
                    continue
                self._frame_id += 1
                self._raw = image
                self._raw_at = getattr(capture, "captured_monotonic", time.monotonic())
                captured_timestamp = getattr(capture, "captured_timestamp", None)
                self._raw_captured_at = (datetime.fromtimestamp(captured_timestamp, timezone.utc)
                                        if captured_timestamp else datetime.now(timezone.utc))
                self._connected = True
                self._condition.notify_all()
        if capture is not None:
            self._release_capture(capture)

    @staticmethod
    def _draw(image: np.ndarray, event: dict[str, Any]) -> np.ndarray:
        output = image.copy()
        height, width = output.shape[:2]
        for item in event.get("detections", []):
            box = item.get("bbox") or {}
            x1, y1 = int(box.get("x", 0)), int(box.get("y", 0))
            x2 = int(x1 + box.get("width", 0))
            y2 = int(y1 + box.get("height", 0))
            x1, x2 = max(0, min(width - 1, x1)), max(0, min(width - 1, x2))
            y1, y2 = max(0, min(height - 1, y1)), max(0, min(height - 1, y2))
            color = (0, 230, 255) if item.get("type") == "qr" else (130, 255, 120)
            label = str(item.get("value") or ("QR" if item.get("type") == "qr" else "DISPLAY"))
            cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
            cv2.putText(output, label, (x1, max(18, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        qr = event.get("qr")
        weight = event.get("numeric_value")
        line = f"QR: {qr['data'] if qr else '--'}  |  KG: {weight if weight is not None else '--'}  |  {event.get('status', 'WAITING')}"
        cv2.rectangle(output, (0, 0), (width, 36), (15, 15, 15), -1)
        cv2.putText(output, line[:120], (12, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (245, 245, 245), 2)
        return output

    def _recognition_loop(self) -> None:
        last_id = -1
        interval = 1.0 / self.inference_fps
        while not self._stop.is_set():
            started = time.monotonic()
            with self._condition:
                self._condition.wait_for(lambda: self._stop.is_set() or (self._raw is not None and self._frame_id != last_id), timeout=0.5)
                if self._stop.is_set():
                    break
                if self._raw is None or self._frame_id == last_id:
                    continue
                frame_id = self._frame_id
                source_generation = self._source_generation
                image = self._raw.copy()
                captured_monotonic = self._raw_at
                captured_at = self._raw_captured_at
                stabilizer = self.stabilizer
            last_id = frame_id
            try:
                qr = self.qr_decoder.decode(image)
                if self.detector:
                    with self.inference_lock:
                        run = self.detector.detect_with_details(image)
                else:
                    run = None
                event = build_recognition(
                    captured_at=captured_at,
                    frame_width=image.shape[1],
                    frame_height=image.shape[0],
                    qr=qr,
                    digits=run.digits if run else [],
                    threshold=self.confidence,
                    decimal_places=self.decimal_places,
                    stabilizer=stabilizer,
                    model_version=getattr(run, "model_version", "model_1"),
                )
                if run and run.display:
                    region = run.display
                    event["detections"].insert(0, {"type": "display", "color": region.color, "confidence": 1.0, "bbox": Box(region.x1, region.y1, region.width, region.height).as_dict()})
                annotated = self._draw(image, event)
                with self._condition:
                    if source_generation != self._source_generation:
                        continue
                    self._event = event
                    self._annotated = annotated
                    self._recognized_raw = image
                    self._recognized_id = frame_id
                    self._recognized_at = captured_monotonic
                    self._jpeg_cache = None
                    self._condition.notify_all()
                if qr or (run and run.digits):
                    logger.info("live frame=%s qr=%s digits=%s value=%s status=%s", frame_id, qr.data if qr else None, event.get("raw_digits"), event.get("numeric_value"), event.get("status"))
            except Exception:
                logger.exception("Live QR/digit recognition failed")
                self.stabilizer.update(None)
                with self._condition:
                    if source_generation != self._source_generation:
                        continue
                    self._event = {**self._empty_event(), "frame_width": image.shape[1], "frame_height": image.shape[0], "status": "ERROR"}
                    self._annotated = image
                    self._recognized_raw = image
                    self._recognized_id = frame_id
                    self._recognized_at = captured_monotonic
                    self._jpeg_cache = None
                    self._condition.notify_all()
            # Leave a real idle window for queued captures and pending sync,
            # including when a slow CPU takes longer than the target interval.
            self._stop.wait(max(0.25, interval - (time.monotonic() - started)))

    def event(self) -> dict[str, Any]:
        with self._condition:
            return dict(self._event)

    def snapshot(self, quality: int = 95) -> tuple[np.ndarray, dict[str, Any], int] | None:
        with self._condition:
            if not self._connected or self._recognized_raw is None or time.monotonic() - self._recognized_at > 10:
                return None
            return self._recognized_raw.copy(), dict(self._event), self._recognized_id

    def capture_snapshot(self) -> tuple[np.ndarray, dict[str, Any], int] | None:
        """Freeze the latest camera frame, without attaching older recognition.

        The capture API will analyze these exact bytes independently. Preview
        results can lag behind the physical camera on a slow CPU.
        """
        with self._condition:
            if not self._connected or self._raw is None or time.monotonic() - self._raw_at > 2:
                return None
            event = {**self._empty_event(), "timestamp": int(self._raw_captured_at.timestamp() * 1000),
                     "frame_width": self._raw.shape[1], "frame_height": self._raw.shape[0], "status": "CAPTURED"}
            return self._raw.copy(), event, self._frame_id

    def wait_jpeg(self, after_id: int, timeout: float = 1.0) -> tuple[int, bytes] | None:
        with self._condition:
            self._condition.wait_for(lambda: self._stop.is_set() or (self._annotated is not None and self._recognized_id > after_id), timeout)
            if self._annotated is None or self._recognized_id <= after_id:
                return None
            frame_id = self._recognized_id
            if self._jpeg_cache is not None and self._jpeg_cache[0] == frame_id:
                return frame_id, self._jpeg_cache[1]
            image = self._annotated.copy()
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if not ok:
            return None
        data = encoded.tobytes()
        with self._condition:
            if self._recognized_id == frame_id:
                self._jpeg_cache = (frame_id, data)
        return frame_id, data
