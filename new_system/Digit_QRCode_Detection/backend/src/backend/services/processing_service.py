"""Process only the freshest captured frame at a bounded rate."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from backend.camera.capture_service import CaptureService, Frame
from backend.config import Settings
from backend.cv.digit_detector import DigitDetector
from backend.cv.types import Box
from backend.cv.qr_decoder import QrDecoder
from backend.recognition.processor import build_recognition
from backend.recognition.snapshot import RecognitionSnapshot, SnapshotStore
from backend.recognition.stabilizer import Stabilizer

logger = logging.getLogger(__name__)


class ProcessingService:
    def __init__(self, settings: Settings, camera: CaptureService, detector: DigitDetector | None, snapshots: SnapshotStore, publish: Callable[[dict], None], storage_available: bool | Callable[[], bool]):
        self.settings = settings
        self.camera = camera
        self.detector = detector
        self.snapshots = snapshots
        self.publish = publish
        self.storage_available = storage_available
        self.decoder = QrDecoder()
        self.stabilizer = Stabilizer(settings.required_stable_frames)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._saved_key: tuple[str, str] | None = None
        self._saved_lock = threading.Lock()

    def _storage_enabled(self) -> bool:
        return self.storage_available() if callable(self.storage_available) else self.storage_available

    def mark_saved(self, qr_data: str, raw_digits: str) -> None:
        with self._saved_lock:
            self._saved_key = (qr_data, raw_digits)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="recognition", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        after_id = 0
        last_process = 0.0
        camera_was_connected = True
        while not self._stop.is_set():
            frame = self.camera.wait_for_frame(after_id, timeout=0.5)
            if frame is None:
                if not self.camera.connected and camera_was_connected:
                    camera_was_connected = False
                    self.stabilizer.update(None)
                    event = {"type": "recognition", "timestamp": int(time.time() * 1000), "frame_width": 0, "frame_height": 0, "detections": [], "qr": None, "raw_digits": None, "numeric_value": None, "confidence": None, "status": "ERROR", "storage_enabled": self._storage_enabled()}
                    self.snapshots.publish(RecognitionSnapshot(0, datetime.now(timezone.utc), event))
                    self.publish(event)
                continue
            camera_was_connected = True
            after_id = frame.frame_id
            elapsed = time.monotonic() - last_process
            interval = 1 / self.settings.inference_fps
            if elapsed < interval:
                self._stop.wait(interval - elapsed)
                continue
            last_process = time.monotonic()
            self._process(frame)

    def _process(self, frame: Frame) -> None:
        try:
            image = frame.image
            started = time.perf_counter()
            qr = self.decoder.decode(image)
            qr_ms = (time.perf_counter() - started) * 1000
            detection = self.detector.detect_with_details(image) if self.detector else None
            digits = detection.digits if detection else []
            event = build_recognition(
                captured_at=frame.captured_at, frame_width=image.shape[1], frame_height=image.shape[0],
                qr=qr, digits=digits, threshold=self.settings.inference_confidence,
                decimal_places=self.settings.decimal_places, stabilizer=self.stabilizer,
                model_version=getattr(detection, "model_version", "model_1"),
            )
            if self.detector is None:
                event["status"] = "ERROR"
            if detection and detection.display:
                region = detection.display
                event["detections"].insert(0, {"type": "display", "color": region.color, "confidence": 1.0, "bbox": Box(region.x1, region.y1, region.width, region.height).as_dict()})
            event["storage_enabled"] = self._storage_enabled()
            key = (event["qr"]["data"], event["raw_digits"]) if event["qr"] and event["raw_digits"] else None
            with self._saved_lock:
                if key != self._saved_key:
                    self._saved_key = None
                elif event["status"] == "READY_TO_SAVE":
                    event["status"] = "SAVED"
            self.snapshots.publish(RecognitionSnapshot(frame.frame_id, frame.captured_at, event))
            self.publish(event)
            if qr or digits:
                logger.info("frame=%s size=%sx%s qr=%s qr_stage=%s qr_ms=%.1f display=%s candidates=%s passes=%s digit_ms=%.1f digits=%s raw=%s status=%s total_ms=%.1f", frame.frame_id, image.shape[1], image.shape[0], qr.data if qr else None, self.decoder.last_stage, qr_ms, detection.display.bbox if detection and detection.display else None, detection.candidate_count if detection else 0, detection.inference_count if detection else 0, detection.elapsed_ms if detection else 0.0, [(item.value, round(item.confidence, 3)) for item in digits], event["raw_digits"], event["status"], (time.perf_counter() - started) * 1000)
        except Exception:
            logger.exception("Recognition failed")
            self.stabilizer.update(None)
            event = {"type": "recognition", "timestamp": int(frame.captured_at.timestamp() * 1000), "frame_width": frame.image.shape[1], "frame_height": frame.image.shape[0], "detections": [], "qr": None, "raw_digits": None, "numeric_value": None, "confidence": None, "status": "ERROR", "storage_enabled": self._storage_enabled()}
            self.snapshots.publish(RecognitionSnapshot(frame.frame_id, frame.captured_at, event))
            self.publish(event)
