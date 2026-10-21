import base64
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from roll_qr_scale import live_camera, test_ui
from roll_qr_scale.live_capture_cache import LiveCaptureCache
from backend.cv.types import Box, Digit, QrResult


def run_for(raw):
    return SimpleNamespace(digits=[Digit(value, .95, Box(50 + index * 20, 50, 15, 30))
                                  for index, value in enumerate(raw)], display=None, crop_scale=None,
                           preprocessing="test", inference_count=1, model_version="model_2")


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(test_ui, "_load_local_dotenv", lambda: None)
    class Detector:
        calls = 0
        def detect_with_details(self, frame):
            self.calls += 1
            return run_for("1111")
    class Decoder:
        def __init__(self, **kwargs): pass
        def decode(self, frame): return None
    detector = Detector()
    monkeypatch.setattr(test_ui, "LocalDigitDetector", lambda *a, **kw: detector)
    monkeypatch.setattr(test_ui, "LocalQrDecoder", Decoder)
    model = tmp_path / "model.pt"
    model.write_bytes(b"test")
    args = test_ui.build_parser().parse_args([
        "--host", "127.0.0.1", "--port", "0", "--db", str(tmp_path / "test.db"),
        "--captures", str(tmp_path / "captures"), "--factory-samples", str(tmp_path / "samples"),
        "--weight-engine", "local-yolo", "--digit-model", str(model),
        "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
    ])
    server, service = test_ui.create_server(args)
    camera = service.live_camera
    # The raw camera is already showing a newer, different frame. A reused
    # value must remain paired with its own recognized image, not this raw one.
    camera._connected = True
    camera._raw = np.full((720, 1280, 3), 30, dtype=np.uint8)
    camera._raw_at = camera._recognized_at = time.monotonic()
    camera._frame_id, camera._recognized_id = 12, 11
    camera._recognized_raw = np.random.default_rng(4).integers(60, 190, (720, 1280, 3), dtype=np.uint8)
    camera._recognized_run = run_for("630")
    camera._recognized_qr = QrResult("TEST-QR", Box(100, 100, 150, 150))
    camera._event = {"raw_digits": "630", "numeric_value": 6.3, "confidence": .95,
                     "qr": {"data": "TEST-QR"}, "status": "READY_TO_SAVE"}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}" + path,
            data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)
    try:
        yield SimpleNamespace(request=request, service=service, camera=camera, detector=detector)
    finally:
        server.shutdown()
        thread.join(3)
        server.server_close()
        service.close()
        service.store.close()


def freeze(case):
    case.camera._raw_at = case.camera._recognized_at = time.monotonic()
    status, capture = case.request("/api/live/snapshot?capture=1&reuse=1&station_id=station-01&camera_id=camera-01")
    assert status == 200
    return capture


def payload_for(capture, kind="core", capture_round=0):
    return {"image": capture["image"], "live_capture_token": capture.get("live_capture_token", ""),
            "event_id": str(uuid.uuid4()), "station_id": "station-01", "camera_id": "camera-01",
            "capture_kind": kind, "capture_round": capture_round, "unit": "kg", "roi": "auto"}


@pytest.mark.parametrize("kind,capture_round", [("core", 0), ("product", 0), ("core", 2), ("inventory", 0)])
def test_capture_reuses_trusted_reading_and_preserves_session_evidence(live_server, kind, capture_round):
    case = live_server
    capture = freeze(case)
    assert capture["frame_id"] == 11 and capture["recognition"]["numeric_value"] == 6.3
    data = base64.b64decode(capture["image"].split(",", 1)[1])
    assert cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR).mean() > 100
    payload = payload_for(capture, kind, capture_round)
    photo = {**payload, "event_id": str(uuid.uuid4()), "parent_event_id": payload["event_id"],
             "machine": "Máy 1", "work_date": "2026-10-21", "shift": "HC1"}
    status, saved = case.request("/api/photo-capture", photo)
    assert status == 201 and saved["qr_code"] == "TEST-QR"
    payload["photo_capture_id"] = saved["capture_id"]
    status, result = case.request("/api/analyze", payload)
    assert status == 200 and result["weight"] == 6.3 and result["qr_code"] == "TEST-QR", result
    assert result["live_capture_reused"] and result["inference_count"] == 0 and result["step_saved"]
    assert case.detector.calls == 0 and case.service.inference.status().submitted == 0
    if kind != "product" and capture_round == 0:
        assert result["analysis_id"] and result["frame_sha256"]


def test_reused_capture_bypasses_busy_model_and_fifo(live_server):
    case = live_server
    capture = freeze(case)
    entered, resume = threading.Event(), threading.Event()
    def busy():
        entered.set()
        resume.wait(5)
    future = case.service.inference.submit(busy)
    assert entered.wait(1)
    case.service.digit_inference_lock.acquire()
    try:
        status, result = case.request("/api/analyze", payload_for(capture))
        assert status == 200 and result["live_capture_reused"]
        assert case.service.inference.status().submitted == 1
        assert case.detector.calls == 0
    finally:
        case.service.digit_inference_lock.release()
        resume.set()
        future.result(timeout=2)


@pytest.mark.parametrize("kind", ["core", "product", "inventory"])
def test_live_missing_qr_reacquires_product_label_without_rerunning_yolo(live_server, monkeypatch, kind):
    case = live_server
    case.camera._recognized_qr = None
    calls = []
    def decode(frame, decoder=None):
        calls.append(frame)
        return {"found": True, "qr_code": "SMALL-LABEL", "decoder": "opencv-tiled_crop", "qr_roi": None}
    monkeypatch.setattr(case.service, "_decode_local_qr", decode)
    capture = freeze(case)
    status, result = case.request("/api/analyze", payload_for(capture, kind))
    assert status == 200 and result["weight"] == 6.3 and result["live_capture_reused"]
    assert case.detector.calls == 0 and case.service.inference.status().submitted == 0
    assert len(calls) == (0 if kind == "core" else 1)
    assert result["qr_code"] == (None if kind == "core" else "SMALL-LABEL")


def test_changed_image_never_reuses_another_frames_weight(live_server):
    case = live_server
    capture = freeze(case)
    payload = payload_for(capture)
    replacement = np.random.default_rng(5).integers(60, 190, (720, 1280, 3), dtype=np.uint8)
    ok, jpeg = cv2.imencode(".jpg", replacement)
    assert ok
    payload["image"] = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    status, result = case.request("/api/analyze", payload)
    assert status == 200 and result["weight"] == 11.11
    assert not result["live_capture_reused"] and case.detector.calls == 1


@pytest.mark.parametrize("change", ["stale", "weak", "source", "disconnected"])
def test_old_weak_or_different_source_readings_are_not_offered(live_server, change):
    case = live_server
    if change == "stale": case.camera._recognized_at = time.monotonic() - 2.2
    elif change == "weak": case.camera._event["confidence"] = .01
    elif change == "source": case.camera.select_source("1")
    else: case.camera._connected = False
    status, result = case.request("/api/live/snapshot?capture=1&reuse=1&station_id=station-01&camera_id=camera-01")
    assert "live_capture_token" not in result
    assert status == (200 if change in {"stale", "weak"} else 503)
    if status == 200:
        assert result["frame_id"] == 12 and result["recognition"]["numeric_value"] is None


def test_tokens_are_bounded_expire_and_are_bound_to_identity(monkeypatch):
    from roll_qr_scale import live_capture_cache
    now = [10.0]
    monkeypatch.setattr(live_capture_cache.time, "monotonic", lambda: now[0])
    cache = LiveCaptureCache(maximum=2, ttl=60)
    first = cache.put("image-1", "station-01", "camera-01", "run-1", {})
    second = cache.put("image-2", "station-01", "camera-01", "run-2", {})
    assert cache.get(second, "image-2", "station-02", "camera-01") is None
    assert cache.get(second, "image-1", "station-01", "camera-01") is None
    cache.put("image-3", "station-01", "camera-01", "run-3", {})
    assert cache.get(first, "image-1", "station-01", "camera-01") is None
    assert cache.get(second, "image-2", "station-01", "camera-01")[0] == "run-2"
    now[0] += 61
    assert cache.get(second, "image-2", "station-01", "camera-01") is None
