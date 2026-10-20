"""Tests for recognition, persistence, and the HTTP contract."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

from backend.config import load_settings
from backend.config import redact_source
from backend.camera.capture_service import Frame, _open_capture
from backend.camera.source import backend_id, parse_source
from backend.cv.types import Box, Digit, QrResult
from backend.cv.digit_detector import DigitDetector
from backend.cv.digit_detector import _filter_row
from backend.cv.digit_detector import _refine_ambiguous_digit
from backend.cv.display_locator import DisplayRegion, locate_display_candidates
from backend.cv.qr_decoder import QrDecoder
from backend.main import create_app
from backend.api.schemas import MeasurementCreate
from backend.recognition.processor import build_recognition
from backend.recognition.snapshot import RecognitionSnapshot
from backend.recognition.snapshot import SnapshotStore
from backend.recognition.stabilizer import Stabilizer
from backend.services.processing_service import ProcessingService
from backend.services.measurement_service import MeasurementService
from backend.storage.csv_exporter import export_recent_csv
from backend.storage.csv_repository import CsvRepository
from backend.storage.sqlite_repository import SqliteRepository


class FakeCamera:
    def __init__(self, settings):
        self.connected = True

    def start(self):
        pass

    def stop(self):
        pass

    def wait_for_frame(self, after_id, timeout=1):
        return None


class FakeDetector:
    def __init__(self, model_path, confidence, **kwargs):
        pass

    def detect_with_details(self, image):
        return SimpleNamespace(digits=[], display=None, candidate_count=0, inference_count=0, elapsed_ms=0.0)


class BackendTests(unittest.TestCase):
    def test_fastapi_serves_frontend_build_and_spa_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            frontend = Path(directory)
            (frontend / "assets").mkdir()
            (frontend / "index.html").write_text("<html>portable frontend</html>", encoding="utf-8")
            (frontend / "assets" / "app.js").write_text("window.packaged = true", encoding="utf-8")
            with patch("backend.main.frontend_dist_path", return_value=frontend):
                client = TestClient(create_app(load_settings()))
                self.assertIn("portable frontend", client.get("/").text)
                self.assertIn("portable frontend", client.get("/client/route").text)
                self.assertIn("window.packaged", client.get("/assets/app.js").text)

    def test_segment_geometry_refines_ambiguous_model_classes(self):
        image = np.zeros((100, 80, 3), dtype=np.uint8)
        # Bright upper-left and lower-right strokes describe a seven-segment 5.
        image[20:45, 10:20] = 255
        image[55:82, 60:70] = 255
        detected = Digit("2", 0.9, Box(0, 0, 80, 100), 4)
        refined = _refine_ambiguous_digit(image, detected)
        self.assertEqual(refined.value, "5")
        self.assertEqual(refined.class_id, 7)

    def test_new_model_maps_sign_and_digits_but_ignores_point(self):
        class FakeBoxes:
            xyxy = np.array([[0, 20, 8, 35], [12, 30, 16, 35], [20, 20, 30, 50], [35, 20, 45, 50], [50, 20, 60, 50]])
            cls = np.array([0, 1, 2, 10, 11])
            conf = np.array([0.8, 0.7, 0.9, 0.95, 0.92])

        class FakeModel:
            names = {0: "-", 1: ".", **{index + 2: str(index) for index in range(10)}}

            def predict(self, **kwargs):
                return [SimpleNamespace(boxes=FakeBoxes())]

        with patch("backend.cv.digit_detector.YOLO", return_value=FakeModel()):
            detector = DigitDetector(Path("best.pt"), 0.25)
            symbols, ignored_none = detector._predict_crop(
                np.zeros((100, 100, 3), dtype=np.uint8),
                DisplayRegion(10, 10, 90, 90, "red", 1.0), "original",
            )
        self.assertEqual(detector.model_version, "model_2")
        self.assertEqual(ignored_none, 0)
        self.assertEqual([item.value for item in symbols], ["-", "0", "8", "9"])
        self.assertEqual([item.class_id for item in symbols], [0, 2, 10, 11])
        self.assertEqual(symbols[-1].box.x, 60)

    def test_new_model_keeps_small_minus_sign(self):
        symbols = [
            Digit("-", 0.8, Box(0, 30, 5, 8), 0),
            Digit("1", 0.9, Box(10, 20, 15, 40), 3),
            Digit("2", 0.9, Box(30, 20, 15, 40), 4),
            Digit("5", 0.9, Box(55, 20, 15, 40), 7),
        ]
        self.assertEqual([item.value for item in _filter_row(symbols)], ["-", "1", "2", "5"])

    def test_new_model_uses_implied_decimal_and_rejects_misplaced_minus(self):
        qr = QrResult("DEVICE-001", Box(0, 0, 10, 10))
        raw = ["-", "1", "2", ".", "5", "0"]
        symbols = [Digit(symbol, 0.9, Box(index * 20, 20, 15, 30), index) for index, symbol in enumerate(raw)]
        options = dict(captured_at=datetime.now(timezone.utc), frame_width=200, frame_height=100, qr=qr, digits=symbols, threshold=0.7, decimal_places=2, stabilizer=Stabilizer(2), model_version="model_2")
        first = build_recognition(**options)
        second = build_recognition(**options)
        self.assertEqual(first["status"], "DETECTING")
        self.assertEqual(second["status"], "READY_TO_SAVE")
        self.assertEqual(second["raw_digits"], "-1250")
        self.assertEqual(second["numeric_value"], -12.5)
        self.assertEqual([item["value"] for item in second["detections"][1:]], ["-", "1", "2", "5", "0"])

        invalid = [Digit(symbol, 0.9, Box(index * 20, 20, 15, 30)) for index, symbol in enumerate("1-2")]
        event = build_recognition(**(options | {"digits": invalid, "stabilizer": Stabilizer(1)}))
        self.assertEqual(event["status"], "INCOMPLETE")
        self.assertIsNone(event["numeric_value"])

    def test_fixed_two_decimal_scale_examples(self):
        for raw, expected in (("040", 0.40), ("643", 6.43), ("1300", 13.00)):
            with self.subTest(raw=raw):
                symbols = [Digit(symbol, 0.9, Box(index * 20, 20, 15, 30), int(symbol) + 2) for index, symbol in enumerate(raw)]
                event = build_recognition(
                    captured_at=datetime.now(timezone.utc), frame_width=200, frame_height=100,
                    qr=None, digits=symbols, threshold=0.7, decimal_places=2,
                    stabilizer=Stabilizer(1), model_version="model_2",
                )
                self.assertEqual(event["raw_digits"], raw)
                self.assertEqual(event["numeric_value"], expected)

    def test_negative_decimal_reading_can_be_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = replace(load_settings(), storage_enable=True, database_path=Path(directory) / "measurements.db")
            repository = SqliteRepository(settings.database_path)
            repository.open()
            try:
                timestamp = datetime.now(timezone.utc)
                event = build_recognition(
                    captured_at=timestamp, frame_width=200, frame_height=100,
                    qr=QrResult("DEVICE-001", Box(0, 0, 10, 10)),
                    digits=[Digit(symbol, 0.9, Box(index * 20, 20, 15, 30)) for index, symbol in enumerate("-12.50")],
                    threshold=0.7, decimal_places=2, stabilizer=Stabilizer(1), model_version="model_2",
                )
                snapshots = SnapshotStore()
                snapshots.publish(RecognitionSnapshot(1, timestamp, event))
                payload = MeasurementCreate(qr_data="DEVICE-001", raw_digits="-1250", numeric_value=-12.5, confidence=0.9)
                saved, _ = MeasurementService(settings, snapshots, repository).save(payload)
                self.assertEqual(saved["numeric_value"], -12.5)
                self.assertEqual(saved["raw_digits"], "-1250")
            finally:
                repository.close()

    def test_api_accepts_negative_decimal_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "best.pt"
            model_path.touch()
            settings = replace(load_settings(), model_path=model_path, database_path=Path(directory) / "measurements.db", storage_enable=True, storage_type="sqlite")
            with patch("backend.main.CaptureService", FakeCamera), patch("backend.main.DigitDetector", FakeDetector):
                with TestClient(create_app(settings)) as client:
                    now = datetime.now(timezone.utc)
                    event = {
                        "type": "recognition", "timestamp": int(now.timestamp() * 1000),
                        "frame_width": 200, "frame_height": 100, "detections": [],
                        "qr": {"data": "DEVICE-001"}, "raw_digits": "-1250",
                        "numeric_value": -12.5, "confidence": 0.91,
                        "status": "READY_TO_SAVE", "storage_enabled": True,
                    }
                    client.app.state.services.snapshots.publish(RecognitionSnapshot(1, now, event))
                    response = client.post("/measurements", json={"qr_data": "DEVICE-001", "raw_digits": "-1250", "numeric_value": -12.5, "confidence": 0.91})
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(response.json()["numeric_value"], -12.5)
                    self.assertEqual(response.json()["raw_digits"], "-1250")

    def test_empty_frame_does_not_log_detection(self):
        settings = load_settings()
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        events = []
        service = ProcessingService(settings, FakeCamera(settings), FakeDetector(None, 0.25), SnapshotStore(), events.append, storage_available=False)
        with patch("backend.services.processing_service.logger.info") as log_info:
            service._process(Frame(1, datetime.now(timezone.utc), image))
        log_info.assert_not_called()
        self.assertEqual(events[0]["detections"], [])

    def test_display_locator_finds_red_digit_row(self):
        image = np.zeros((300, 500, 3), dtype=np.uint8)
        for x in (185, 208, 231):
            cv2.rectangle(image, (x, 130), (x + 17, 160), (0, 0, 255), -1)
        regions = locate_display_candidates(image)
        self.assertTrue(regions)
        self.assertLess(regions[0].x1, 185)
        self.assertGreater(regions[0].x2, 248)

    def test_processing_publishes_full_frame_digit_and_display_boxes(self):
        settings = load_settings()
        image = np.zeros((300, 500, 3), dtype=np.uint8)
        region = DisplayRegion(180, 115, 275, 175, "red", 0.8)
        digits = [Digit(4, 0.9, Box(195, 132, 18, 30))]
        detector = SimpleNamespace(detect_with_details=lambda _: SimpleNamespace(digits=digits, display=region, candidate_count=1, inference_count=5, elapsed_ms=20.0))
        events = []
        service = ProcessingService(settings, FakeCamera(settings), detector, SnapshotStore(), events.append, storage_available=False)
        service._process(Frame(7, datetime.now(timezone.utc), image))
        event = events[0]
        self.assertEqual(event["raw_digits"], "4")
        self.assertEqual(event["frame_width"], 500)
        self.assertEqual(event["detections"][0]["type"], "display")
        self.assertEqual(event["detections"][0]["bbox"], {"x": 180, "y": 115, "width": 95, "height": 60})
        self.assertEqual(event["detections"][1]["bbox"], {"x": 195, "y": 132, "width": 18, "height": 30})

    def test_digit_detector_accepts_and_filters_optional_none_class(self):
        class FakeBoxes:
            xyxy = np.array([[10, 20, 30, 50], [40, 20, 60, 50]])
            cls = np.array([7, 10])
            conf = np.array([0.91, 0.99])

        class FakeModel:
            names = {**{index: str(index) for index in range(10)}, 10: "none"}

            def predict(self, **kwargs):
                return [SimpleNamespace(boxes=FakeBoxes())]

        with patch("backend.cv.digit_detector.YOLO", return_value=FakeModel()):
            detector = DigitDetector(Path("best.pt"), 0.25)
            from backend.cv.display_locator import DisplayRegion
            detections, ignored_none = detector._predict_crop(np.zeros((100, 100, 3), dtype=np.uint8), DisplayRegion(0, 0, 100, 100, "red", 1.0), "original")

        self.assertEqual(len(detections), 1)
        self.assertEqual(ignored_none, 1)
        self.assertEqual(detections[0].value, 7)
        self.assertEqual(detections[0].confidence, 0.91)

    def test_usb_and_wireless_camera_sources(self):
        self.assertEqual(parse_source("0"), 0)
        url = "rtsp://user:password@192.168.1.50:554/stream1"
        self.assertEqual(parse_source(url), url)
        self.assertNotIn("password", redact_source(url))
        self.assertIsNone(backend_id(None))
        self.assertIsNone(backend_id("AUTO"))
        self.assertEqual(backend_id("DSHOW"), cv2.CAP_DSHOW)
        self.assertEqual(backend_id("MSMF"), cv2.CAP_MSMF)
        with patch("backend.camera.capture_service.cv2.VideoCapture") as video_capture:
            _open_capture(0, None)
            video_capture.assert_called_once_with(0)
        with patch("backend.camera.capture_service.cv2.VideoCapture") as video_capture:
            _open_capture(1, "DSHOW")
            video_capture.assert_called_once_with(1, cv2.CAP_DSHOW)

    def test_digit_order_decimal_and_stability(self):
        stabilizer = Stabilizer(2)
        digits = [Digit(5, 0.92, Box(80, 20, 15, 30)), Digit(1, 0.98, Box(10, 20, 15, 30)), Digit(2, 0.97, Box(40, 20, 15, 30)), Digit(0, 0.94, Box(110, 20, 15, 30))]
        options = dict(captured_at=datetime.now(timezone.utc), frame_width=200, frame_height=100, qr=QrResult("DEVICE-001", Box(0, 0, 10, 10)), digits=digits, threshold=0.7, decimal_places=2, stabilizer=stabilizer)
        first = build_recognition(**options)
        second = build_recognition(**options)
        self.assertEqual(first["status"], "DETECTING")
        self.assertEqual(second["status"], "READY_TO_SAVE")
        self.assertEqual(second["raw_digits"], "1250")
        self.assertEqual(second["numeric_value"], 12.5)
        self.assertEqual(second["confidence"], 0.92)
        self.assertEqual([item["class"] for item in second["detections"][1:]], [1, 2, 5, 0])

    def test_low_confidence_result_is_visible_but_not_ready(self):
        event = build_recognition(
            captured_at=datetime.now(timezone.utc), frame_width=200, frame_height=100,
            qr=QrResult("DEVICE-001", Box(0, 0, 10, 10)),
            digits=[Digit(5, 0.42, Box(50, 20, 15, 30))],
            threshold=0.7, decimal_places=2, stabilizer=Stabilizer(1),
        )
        self.assertEqual(event["status"], "LOW_CONFIDENCE")
        self.assertEqual(event["raw_digits"], "5")

    def test_qr_decoder_reads_camera_image(self):
        qr = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        qr = cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST)
        image = cv2.copyMakeBorder(qr, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        result = QrDecoder().decode(image)
        self.assertIsNotNone(result)
        self.assertEqual(result.data, "DEVICE-001")
        self.assertGreater(result.box.width, 0)

    def test_qr_decoder_uses_crop_and_maps_boxes_to_full_frame(self):
        qr = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        qr = cv2.copyMakeBorder(cv2.resize(qr, (160, 160), interpolation=cv2.INTER_NEAREST), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

        def frame(x: int) -> np.ndarray:
            image = np.full((720, 1280), 255, dtype=np.uint8)
            image[200:400, x:x + 200] = qr
            return image

        decoder = QrDecoder()
        first = decoder.decode(frame(300))
        self.assertIsNotNone(first)
        self.assertIn(decoder.last_stage, {"localized_crop", "full_frame"})
        self.assertGreater(first.box.x, 300)

        second = decoder.decode(frame(310))
        self.assertIsNotNone(second)
        self.assertEqual(decoder.last_stage, "cached_crop")
        self.assertGreater(second.box.x, first.box.x)

        moved = decoder.decode(frame(800))
        self.assertIsNotNone(moved)
        self.assertIn(decoder.last_stage, {"localized_crop", "full_frame"})
        self.assertGreater(moved.box.x, 800)

        self.assertIsNone(decoder.decode(np.full((720, 1280), 255, dtype=np.uint8)))
        self.assertEqual(decoder.last_stage, "none")

    def test_qr_decoder_full_frame_fallback_when_preview_misses(self):
        qr = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        qr = cv2.copyMakeBorder(cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        first_image = np.full((720, 1280), 255, dtype=np.uint8)
        first_image[100:440, 100:440] = qr
        moved_image = np.full((720, 1280), 255, dtype=np.uint8)
        moved_image[300:640, 800:1140] = qr
        decoder = QrDecoder()
        self.assertIsNotNone(decoder.decode(first_image))
        with patch.object(decoder, "_candidates", return_value=iter(())):
            result = decoder.decode(moved_image)
        self.assertIsNotNone(result)
        self.assertEqual(result.data, "DEVICE-001")
        self.assertEqual(decoder.last_stage, "full_frame")
        self.assertGreater(result.box.x, 800)

    def test_qr_decoder_recovers_small_qr_from_training_image(self):
        image_path = Path(__file__).resolve().parents[2] / "model_training/ssd/test_2/0d46b13160adc60a01ecbb8bbe467b1e.jpg"
        if not image_path.is_file():
            self.skipTest("training test image is unavailable")
        image = cv2.imread(str(image_path))
        self.assertIsNotNone(image)
        decoder = QrDecoder()
        result = decoder.decode(image)
        self.assertIsNotNone(result)
        self.assertEqual(result.data, "MN-BB414_DYY6WM97H6K")
        self.assertEqual(decoder.last_stage, "localized_crop")
        self.assertGreater(result.box.x, 700)
        self.assertGreater(result.box.y, 300)
        self.assertLess(result.box.x + result.box.width, image.shape[1])
        self.assertLess(result.box.y + result.box.height, image.shape[0])

    def test_qr_still_streams_without_digit_model(self):
        qr = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        image = cv2.copyMakeBorder(cv2.resize(qr, (300, 300), interpolation=cv2.INTER_NEAREST), 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
        events = []
        settings = load_settings()
        service = ProcessingService(settings, FakeCamera(settings), None, SnapshotStore(), events.append, storage_available=False)
        service._process(Frame(1, datetime.now(timezone.utc), image))
        self.assertEqual(events[0]["qr"], {"data": "DEVICE-001"})
        self.assertEqual(events[0]["status"], "ERROR")
        self.assertFalse(events[0]["storage_enabled"])

    def test_sqlite_persists_and_rejects_recent_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "measurements.db"
            payload = {"qr_data": "DEVICE-001", "raw_digits": "1250", "numeric_value": 12.5, "confidence": 0.91}
            repository = SqliteRepository(path)
            repository.open()
            first = repository.insert_if_new(payload, datetime.now(timezone.utc), 60)
            self.assertIsNotNone(first)
            self.assertIsNone(repository.insert_if_new(payload, datetime.now(timezone.utc), 60))
            repository.close()
            reopened = SqliteRepository(path)
            reopened.open()
            self.assertEqual(len(reopened.list_recent()), 1)
            export_path = Path(directory) / "measurements.csv"
            export_recent_csv(reopened, export_path)
            self.assertIn("DEVICE-001", export_path.read_text(encoding="utf-8"))
            reopened.close()

    def test_csv_persists_qr_and_digits_and_rejects_recent_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "measurements.csv"
            repository = CsvRepository(path)
            repository.open()
            payload = {"qr_data": "DEVICE-CSV", "raw_digits": "0643", "numeric_value": 6.43, "confidence": 0.92}
            first = repository.insert_if_new(payload, datetime.now(timezone.utc), 60)
            self.assertIsNotNone(first)
            self.assertEqual(first["qr_data"], "DEVICE-CSV")
            self.assertEqual(first["raw_digits"], "0643")
            self.assertIsNone(repository.insert_if_new(payload, datetime.now(timezone.utc), 60))
            repository.close()

            reopened = CsvRepository(path)
            reopened.open()
            records = reopened.list_recent()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["numeric_value"], 6.43)
            self.assertIn("qr_data,raw_digits,numeric_value", path.read_text(encoding="utf-8"))
            reopened.close()

    def test_api_storage_modes_and_websocket(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "best.pt"
            model_path.touch()
            original = load_settings()
            settings = replace(original, model_path=model_path, database_path=Path(directory) / "measurements.db", storage_enable=False, storage_type="sqlite")
            with patch("backend.main.CaptureService", FakeCamera), patch("backend.main.DigitDetector", FakeDetector):
                with TestClient(create_app(settings)) as client:
                    self.assertEqual(client.get("/health").status_code, 200)
                    self.assertEqual(client.get("/measurements").json(), [])
                    self.assertEqual(client.post("/measurements", json={"qr_data": "DEVICE-001", "raw_digits": "1250", "numeric_value": 12.5, "confidence": 0.91}).status_code, 503)
                    with client.websocket_connect("/ws/detections") as socket:
                        self.assertEqual(socket.receive_json()["type"], "recognition")
                self.assertFalse(settings.database_path.exists())

                enabled = replace(settings, storage_enable=True)
                with TestClient(create_app(enabled)) as client:
                    now = datetime.now(timezone.utc)
                    event = {"type": "recognition", "timestamp": int(now.timestamp() * 1000), "frame_width": 200, "frame_height": 100, "detections": [], "qr": {"data": "DEVICE-001"}, "raw_digits": "1250", "numeric_value": 12.5, "confidence": 0.91, "status": "READY_TO_SAVE"}
                    client.app.state.services.snapshots.publish(RecognitionSnapshot(1, now, event))
                    request = {"qr_data": "DEVICE-001", "raw_digits": "1250", "numeric_value": 12.5, "confidence": 0.90}
                    response = client.post("/measurements", json=request)
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(response.json()["confidence"], 0.91)
                    self.assertEqual(client.get("/measurements").json()[0]["qr_data"], "DEVICE-001")
                    self.assertEqual(client.post("/measurements", json=request).status_code, 409)
                    client.app.state.services.repository._healthy = False
                    self.assertEqual(client.get("/health").json()["detail"]["code"], "DATABASE_UNAVAILABLE")
                    self.assertEqual(client.get("/measurements").status_code, 503)

    def test_api_saves_current_recognition_to_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            model_path = root / "best.pt"
            model_path.touch()
            csv_path = root / "data" / "measurements.csv"
            settings = replace(load_settings(), model_path=model_path, storage_enable=True, storage_type="csv", csv_path=csv_path)
            with patch("backend.main.CaptureService", FakeCamera), patch("backend.main.DigitDetector", FakeDetector):
                with TestClient(create_app(settings)) as client:
                    now = datetime.now(timezone.utc)
                    event = {"type": "recognition", "timestamp": int(now.timestamp() * 1000), "frame_width": 200, "frame_height": 100, "detections": [], "qr": {"data": "DEVICE-CSV"}, "raw_digits": "0643", "numeric_value": 6.43, "confidence": 0.91, "status": "READY_TO_SAVE"}
                    client.app.state.services.snapshots.publish(RecognitionSnapshot(1, now, event))
                    response = client.post("/measurements", json={"qr_data": "DEVICE-CSV", "raw_digits": "0643", "numeric_value": 6.43, "confidence": 0.90})
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(client.get("/health").json()["storage_type"], "csv")
                    self.assertEqual(client.get("/measurements").json()[0]["raw_digits"], "0643")
            self.assertIn("DEVICE-CSV", csv_path.read_text(encoding="utf-8"))

    def test_mjpeg_stream_contains_jpeg_frame(self):
        image = cv2.QRCodeEncoder_create().encode("DEVICE-001")
        frame = Frame(1, datetime.now(timezone.utc), image)

        class OneFrameCamera:
            connected = True

            def wait_for_frame(self, after_id, timeout=1):
                if after_id == 0:
                    return frame
                self.connected = False
                return None

            def encode_jpeg(self, current, quality):
                ok, data = cv2.imencode(".jpg", current.image, [cv2.IMWRITE_JPEG_QUALITY, quality])
                return data.tobytes() if ok else None

        app = create_app(load_settings())
        app.state.services = SimpleNamespace(camera=OneFrameCamera(), settings=load_settings())
        response = TestClient(app).get("/stream")
        self.assertEqual(response.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", response.headers["content-type"])
        self.assertIn(b"\xff\xd8", response.content)


if __name__ == "__main__":
    unittest.main()
