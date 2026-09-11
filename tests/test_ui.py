import base64
import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest
import qrcode

import roll_qr_scale.test_ui as test_ui_module
from roll_qr_scale.scale import WeightReading
from roll_qr_scale.gemini_weight import GeminiWeightSuggestion
from roll_qr_scale.storage import MeasurementStore
from roll_qr_scale.sync import OutboxSyncWorker
from roll_qr_scale.test_ui import (
    TEST_UI_HTML,
    StationUIService,
    decode_image,
    decode_session_cookie,
    encode_session_cookie,
    safe_login_next,
)
from roll_qr_scale.weight_ocr import NormalizedROI


def make_qr_frame(value: str) -> np.ndarray:
    qr = qrcode.make(value).convert("RGB").resize((360, 360))
    frame = np.full((600, 800, 3), 245, dtype=np.uint8)
    frame[120:480, 220:580] = cv2.cvtColor(np.asarray(qr), cv2.COLOR_RGB2BGR)
    return frame


def image_data_url(frame: np.ndarray) -> str:
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")


def test_decode_image_accepts_browser_data_url() -> None:
    frame = make_qr_frame("ROLL-WEB-IMAGE")
    decoded = decode_image(image_data_url(frame))
    assert decoded.shape == frame.shape


def test_photo_only_and_factory_buttons_are_removed_from_operator_view() -> None:
    assert "#photoOnlyBtn,#factoryBtn,#inventoryPhoneBtn{display:none!important}" in TEST_UI_HTML
    assert "'/api/photo-capture'" in TEST_UI_HTML
    assert "function persistFailedImage(" in TEST_UI_HTML
    assert "function saveFailedRound(" in TEST_UI_HTML
    assert "function saveMeasurementRound(" in TEST_UI_HTML
    assert "saveCapture=saveCaptureWithFailedImages" in TEST_UI_HTML
    assert "round.eventId=newEventId()" in TEST_UI_HTML
    assert "Nhấn Enter để lưu ảnh với số trống" in TEST_UI_HTML
    assert "ID ảnh sẽ được tự tạo an toàn" in TEST_UI_HTML
    assert "error_saved:true" in TEST_UI_HTML
    assert "row.classList.add('photo-draft-row')" in TEST_UI_HTML


def test_ui_capture_decodes_qr_and_saves_stable_manual_weight(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    result = service.capture("", 125.4, "kg", make_qr_frame("ROLL-WEB-001"))
    row = store.connection.execute(
        "SELECT qr_code,weight,unit,weight_source,qr_source,weight_stable,sync_status "
        "FROM measurements"
    ).fetchone()
    store.close()

    assert result["qr_code"] == "ROLL-WEB-001"
    assert result["sync_status"] == "local"
    assert tuple(row) == (
        "ROLL-WEB-001",
        125.4,
        "kg",
        "manual-test-ui",
        "camera:zxing",
        1,
        "local",
    )


def test_ui_capture_accepts_event_id_alone_and_retries_idempotently(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    event_id = str(uuid.uuid4())
    frame = make_qr_frame("ROLL-PARTIAL-001")

    first = service.capture(
        "ROLL-PARTIAL-001",
        1.15,
        "kg",
        frame,
        event_id=event_id,
        product_frame=frame,
        product_weight=13.04,
    )
    retry = service.capture(
        "ROLL-PARTIAL-001",
        1.15,
        "kg",
        frame,
        event_id=event_id,
        product_frame=frame,
        product_weight=13.04,
    )
    count = store.connection.execute(
        "SELECT COUNT(*) FROM measurements WHERE event_id = ?", (event_id,)
    ).fetchone()[0]
    saved = store.get(event_id)
    service.close()
    store.close()

    assert first["duplicate"] is False
    assert retry["duplicate"] is True
    assert first["event_id"] == retry["event_id"] == event_id
    assert count == 1
    assert saved is not None and saved.product_weight == pytest.approx(13.04)


def test_frontend_saves_only_complete_unsaved_rounds_in_separate_requests() -> None:
    assert "Lưu phần đã đủ" in TEST_UI_HTML
    assert "function savableRoundIndexes(session)" in TEST_UI_HTML
    assert "round&&!round.saved&&roundCoreReady" in TEST_UI_HTML
    assert "for(const index of indexes)" in TEST_UI_HTML
    assert "event_id:round.eventId" in TEST_UI_HTML
    assert "product_weight:productValue" in TEST_UI_HTML
    assert "Bấm Lưu phần đã đủ để thử lại đúng event_id" in TEST_UI_HTML
    assert "if(!weightsReady(session)){status(captureStatus,'Cần đủ" not in TEST_UI_HTML


def test_ui_save_waits_for_same_event_code_weight_and_image_cloud_ack(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    sent: list[tuple[dict[str, object], bytes]] = []

    def fake_send(url, payload, image_path, token):
        sent.append((dict(payload), Path(image_path).read_bytes()))
        return {
            "ok": True,
            "event_id": payload["event_id"],
            "id": 501,
            "image_url": "https://images.example/evidence.jpg",
            "image_public_id": "roll-captures/event",
        }

    worker = OutboxSyncWorker(
        store,
        "https://example.test/ingest",
        "device-token",
        "gateway-test",
        send=fake_send,
    )
    service = StationUIService(store, worker, None, None)

    result = service.capture(
        "PRODUCT-ENTRY-001",
        7.08,
        "kg",
        make_qr_frame("EVIDENCE-QR"),
    )

    service.close()
    store.close()
    assert result["sync_status"] == "synced"
    assert result["remote_id"] == 501
    assert result["remote_image_url"] == "https://images.example/evidence.jpg"
    assert len(sent) == 1
    assert sent[0][0]["event_id"] == result["event_id"]
    assert sent[0][0]["qr_code"] == "PRODUCT-ENTRY-001"
    assert sent[0][0]["weight"] == pytest.approx(7.08)
    assert sent[0][1].startswith(b"\xff\xd8")


def test_ui_save_reports_cloud_failure_but_keeps_complete_local_event(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")

    def fail_send(*args):
        raise OSError("network unavailable")

    worker = OutboxSyncWorker(
        store,
        "https://offline.test/ingest",
        "device-token",
        "gateway-test",
        send=fail_send,
    )
    service = StationUIService(store, worker, None, None)

    result = service.capture(
        "PRODUCT-OFFLINE-001",
        13.04,
        "kg",
        make_qr_frame("EVIDENCE-OFFLINE"),
    )
    saved = store.get(str(result["event_id"]))

    service.close()
    store.close()
    assert result["sync_status"] == "failed"
    assert "network unavailable" in str(result["sync_error"])
    assert result["pending_count"] == 1
    assert saved is not None
    assert saved.qr_code == "PRODUCT-OFFLINE-001"
    assert saved.weight == pytest.approx(13.04)
    assert Path(saved.image_path).is_file()


def test_ui_inventory_capture_uses_one_image_without_core_capture(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    frame = make_qr_frame("INVENTORY-EVIDENCE")

    result = service.capture_inventory(
        "SP-KIEM-KHO-HTTP",
        12.75,
        0.5,
        0.16,
        "kg",
        frame,
        vision_confirmed=True,
        weight_raw="GEMINI PRIMARY: 12.75",
    )
    saved = store.get_inventory_check(str(result["event_id"]))

    assert result["workflow"] == "inventory_check"
    assert result["product_code"] == "SP-KIEM-KHO-HTTP"
    assert result["weight"] == pytest.approx(12.75)
    assert saved is not None
    assert saved.core_weight == pytest.approx(0.5)
    assert saved.tare_weight == pytest.approx(0.16)
    assert Path(saved.image_path).is_file()
    assert store.count() == 0
    service.close()
    store.close()


def test_ui_photo_capture_decodes_qr_without_calling_weight_ai(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    sent: list[dict[str, object]] = []

    def fake_send(url, payload, image_path, token):
        sent.append(dict(payload))
        return {
            "ok": True,
            "event_id": payload["event_id"],
            "id": 801,
            "image_url": "https://images.example/photo-only.jpg",
            "image_public_id": "roll-captures/photo-draft/photo-only",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    service = StationUIService(store, worker, None, None)
    parent_event_id = "31c3db88-2c7d-4a35-b5f0-3a83e9a6745a"
    capture_id = "6a60273c-ea0c-44e8-9599-1ae4c8e597ce"
    result = service.capture_photo_draft(
        make_qr_frame("QR-PHOTO-ONLY-UI"),
        event_id=capture_id,
        parent_event_id=parent_event_id,
        capture_kind="product",
        capture_round=1,
        station_id="station-01",
        camera_id="camera-01",
    )
    saved = store.get_photo_draft(capture_id)

    assert result["ai_requested"] is False
    assert result["qr_code"] == "QR-PHOTO-ONLY-UI"
    assert result["sync_status"] == "synced"
    assert result["event_id"] == parent_event_id
    assert result["capture_id"] == capture_id
    assert result["capture_kind"] == "product"
    assert result["capture_round"] == 1
    assert saved is not None and saved.status == "awaiting_ai"
    assert saved.parent_event_id == parent_event_id
    assert store.count() == 0
    assert sent[0]["workflow"] == "photo_draft"
    assert sent[0]["parent_event_id"] == parent_event_id
    service.close()
    store.close()


def test_discard_session_clears_failed_binding_even_if_browser_event_is_stale(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    actual_event_id = str(uuid.uuid4())
    binding = service.sessions.stage(
        make_qr_frame("QR-FAILED-DISCARD"),
        event_id=actual_event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    service.sessions.mark_failed(binding.analysis_id, RuntimeError("AI failed"))

    assert service.discard_session("station-01", event_id=str(uuid.uuid4())) is True
    status_row = service.sessions.statuses()[0]
    assert status_row["state"] == "idle"
    assert status_row["event_id"] is None
    service.close()
    store.close()


def test_ui_save_keeps_both_weights_and_both_images_in_one_event(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    core_frame = make_qr_frame("CORE-EVIDENCE")
    product_frame = make_qr_frame("PRODUCT-EVIDENCE")

    result = service.capture(
        "PRODUCT-001",
        1.04,
        "kg",
        core_frame,
        product_frame=product_frame,
        product_weight=13.04,
    )
    saved = store.get(str(result["event_id"]))

    service.close()
    store.close()
    assert saved is not None
    assert saved.qr_code == "PRODUCT-001"
    assert saved.weight == pytest.approx(1.04)
    assert saved.product_weight == pytest.approx(13.04)
    assert Path(saved.image_path).is_file()
    assert Path(saved.product_image_path).is_file()
    assert saved.image_path != saved.product_image_path


def test_ui_analyzes_qr_and_camera_weight_together(tmp_path, monkeypatch) -> None:
    class FakeOCRSource:
        def __init__(self, *args, reader=None, **kwargs):
            self._reader = reader or object()

        def capture(self, frame):
            return WeightReading(20.15, "kg", True, "OCR: 20.15@0.96", 0.96)

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)

    result = service.analyze(
        make_qr_frame("ROLL-CAMERA-001"),
        "0.4,0.7,0.6,0.9",
        "kg",
    )
    store.close()

    assert result["qr_code"] == "ROLL-CAMERA-001"
    assert result["qr_roi"] is not None
    assert result["weight"] == 20.15
    assert result["confidence"] == 0.96
    assert result["quality_pass"] is True


def test_ui_uses_camera_calibration_and_temporal_burst(tmp_path, monkeypatch) -> None:
    observed = {}

    class FakeOCRSource:
        def __init__(self, roi, *args, reader=None, **kwargs):
            observed["roi"] = roi
            self._reader = reader or object()

        def capture_many(self, frames):
            observed["frames"] = len(frames)
            return WeightReading(
                7.84,
                "kg",
                True,
                "TEMPORAL: agreement=7/9",
                0.88,
            )

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
        weight_rois=["0.40,0.70,0.60,0.90"],
    )
    frame = make_qr_frame("ROLL-BURST-001")

    result = service.analyze(
        frame,
        "auto",
        "kg",
        event_id="event-burst-001",
        station_id="station-01",
        camera_id="camera-01",
        weight_frames=[frame.copy(), frame.copy()],
    )
    service.close()
    store.close()

    assert observed["frames"] == 3
    assert observed["roi"].x1 == pytest.approx(0.40)
    assert result["roi_method"] == "camera-calibrated"
    assert result["burst_frames"] == 3
    assert result["weight"] == pytest.approx(7.84)


@pytest.mark.parametrize(
    ("gemini_value", "expected_weight", "human_review"),
    ((7.84, 7.84, False), (1.84, None, True)),
)
def test_hybrid_accepts_only_independent_local_cloud_agreement(
    tmp_path,
    monkeypatch,
    gemini_value,
    expected_weight,
    human_review,
) -> None:
    class FakeOCRSource:
        def __init__(self, *args, reader=None, **kwargs):
            self._reader = reader or object()

        def capture_many(self, frames):
            return WeightReading(None, "kg", False, "LOCAL: strict consensus rejected")

        def candidate_reading(self):
            return WeightReading(
                7.84,
                "kg",
                False,
                "LOCAL CANDIDATE: 7.84kg; votes=2/3",
                0.91,
            )

        def crop(self, frame):
            return frame[10:30, 10:70]

    class FakeGeminiReader:
        def __init__(self):
            self.calls = 0

        def read(self, frames, *, unit):
            self.calls += 1
            assert len(frames) == 3
            return GeminiWeightSuggestion(
                gemini_value,
                unit,
                True,
                True,
                f"GEMINI:{gemini_value}",
                0.2,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    gemini = FakeGeminiReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=gemini,
        weight_engine="hybrid",
    )
    frame = make_qr_frame("ROLL-HYBRID-001")

    result = service.analyze(
        frame,
        "0,0,1,1",
        "kg",
        weight_frames=[frame.copy(), frame.copy()],
    )
    service.close()
    store.close()

    assert gemini.calls == 1
    assert result["weight"] == expected_weight
    assert result["requires_human_review"] is human_review
    assert result["recognition_source"] == (
        "paddle-local+gemini" if expected_weight is not None else "none"
    )


def test_hybrid_skips_gemini_when_local_consensus_passes(tmp_path, monkeypatch) -> None:
    class FakeOCRSource:
        def __init__(self, *args, reader=None, **kwargs):
            self._reader = reader or object()

        def capture_many(self, frames):
            return WeightReading(7.84, "kg", True, "LOCAL: accepted", 0.96)

        def candidate_reading(self):
            return WeightReading(7.84, "kg", True, "LOCAL: accepted", 0.96)

    class ForbiddenGeminiReader:
        def read(self, frames, *, unit):
            raise AssertionError("Gemini must not run after local acceptance")

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=ForbiddenGeminiReader(),
        weight_engine="hybrid",
    )
    frame = make_qr_frame("ROLL-LOCAL-001")

    result = service.analyze(
        frame,
        "0,0,1,1",
        "kg",
        weight_frames=[frame.copy(), frame.copy()],
    )
    service.close()
    store.close()

    assert result["weight"] == pytest.approx(7.84)
    assert result["gemini_used"] is False
    assert result["recognition_source"] == "paddle-local"


@pytest.mark.parametrize(("gemini_value", "expected_weight"), ((7.84, 7.84), (None, None)))
def test_gemini_primary_reads_same_camera_burst_without_paddle(
    tmp_path,
    monkeypatch,
    gemini_value,
    expected_weight,
) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.calls = 0

        def read(self, frames, *, unit):
            self.calls += 1
            assert len(frames) == 3
            assert all(frame.shape[:2] == (600, 800) for frame in frames)
            return GeminiWeightSuggestion(
                gemini_value,
                unit,
                gemini_value is not None,
                gemini_value is not None,
                "GEMINI:test",
                0.25,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(
        test_ui_module.PaddleOCRTextReader,
        "create",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("Paddle must not load")),
    )
    gemini = FakeGeminiReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=gemini,
        weight_engine="gemini",
    )
    service.start_ocr_preload()
    frame = make_qr_frame("ROLL-GEMINI-PRIMARY")

    result = service.analyze(
        frame,
        "0,0,0.1,0.1",
        "kg",
        weight_frames=[frame.copy(), frame.copy()],
    )
    service.close()
    store.close()

    assert gemini.calls == 1
    assert result["weight"] == expected_weight
    assert result["recognition_source"] == (
        "gemini-primary" if expected_weight is not None else "none"
    )
    assert result["gemini_used"] is True
    assert result["confidence"] is None
    assert result["gemini_input_tokens"] == 0
    assert result["gemini_output_tokens"] == 0
    assert result["gemini_thinking_tokens"] == 0
    assert result["gemini_total_tokens"] == 0
    assert result["roi"] is None
    assert result["roi_method"] == "gemini-full-frame"
    assert service.status()["weight_engine"] == "gemini"
    assert service.status()["ocr_ready"] is False


def test_codex_can_be_selected_without_replacing_gemini(tmp_path) -> None:
    class FakeGeminiReader:
        model = "gemini-test"

        def read(self, frames, *, unit):
            raise AssertionError("Gemini must not run when Codex is selected")

        def status(self):
            return {"enabled": True, "model": self.model}

        def close(self):
            pass

    class FakeCodexReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(
                13.04,
                unit,
                True,
                True,
                "CODEX:13.04; auth=ChatGPT",
                0.5,
            )

        def status(self):
            return {
                "enabled": True,
                "installed": True,
                "authenticated": True,
                "available": True,
            }

        def close(self):
            pass

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    gemini = FakeGeminiReader()
    codex = FakeCodexReader()
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=gemini,
        codex_reader=codex,
        weight_engine="gemini",
    )

    result = service.analyze(
        make_qr_frame("ROLL-CODEX-001"),
        "auto",
        "kg",
        recognition_provider="codex",
    )
    status = service.status()
    service.close()
    store.close()

    assert result["weight"] == pytest.approx(13.04)
    assert result["recognition_provider"] == "codex"
    assert result["recognition_source"] == "codex-primary"
    assert result["codex_used"] is True
    assert result["gemini_used"] is False
    assert status["recognition_providers"]["gemini"]["available"] is True
    assert status["recognition_providers"]["codex"]["available"] is True


def test_gemini_primary_uses_one_full_image_for_file_and_camera(
    tmp_path,
) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.calls = 0

        def read(self, frames, *, unit):
            self.calls += 1
            assert len(frames) == 1
            assert frames[0].shape[:2] == (600, 800)
            return GeminiWeightSuggestion(7.84, unit, True, True, "GEMINI:test", 0.2)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    gemini = FakeGeminiReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=gemini,
        weight_engine="gemini",
    )
    frame = make_qr_frame("ROLL-GEMINI-STILL")

    result = service.analyze(frame, "0,0,0.1,0.1", "kg")
    assert result["weight"] == pytest.approx(7.84)
    assert result["burst_frames"] == 1
    assert "single full-image accepted" in result["weight_raw"]

    camera_result = service.analyze(
        frame,
        "0,0,0.1,0.1",
        "kg",
        require_temporal=True,
    )
    assert camera_result["weight"] == pytest.approx(7.84)
    assert camera_result["burst_frames"] == 1
    assert "single full-image accepted" in camera_result["weight_raw"]

    service.close()
    store.close()
    assert gemini.calls == 2


def test_gemini_allows_successful_low_resolution_full_image(tmp_path) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            assert len(frames) == 1
            assert frames[0].shape[:2] == (240, 320)
            return GeminiWeightSuggestion(
                7.02,
                unit,
                True,
                True,
                "GEMINI_FULL:test",
                0.2,
                qr_code="ROLL-LOW-RES",
                qr_readable=True,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    frame = np.full((240, 320, 3), 150, dtype=np.uint8)
    cv2.putText(frame, "7.02", (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 5)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )

    result = service.analyze(frame, "auto", "kg")
    saved = service.capture(
        "ROLL-LOW-RES",
        7.02,
        "kg",
        frame,
        vision_confirmed=True,
        weight_raw="GEMINI_FULL:test",
    )

    service.close()
    store.close()
    assert result["qr_code"] == "ROLL-LOW-RES"
    assert result["weight"] == pytest.approx(7.02)
    assert result["quality_pass"] is True
    assert result["quality"]["issues"] == []
    assert result["quality"]["low_resolution_ignored"] is True
    assert saved["qr_code"] == "ROLL-LOW-RES"


def test_gemini_full_frame_supplies_qr_when_local_decoder_misses(tmp_path) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(
                9.34,
                unit,
                True,
                True,
                "GEMINI_FULL:test",
                0.2,
                qr_code="ROLL-CLOUD-QR",
                qr_readable=True,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )

    result = service.analyze(np.full((600, 800, 3), 180, dtype=np.uint8), "auto", "kg")

    service.close()
    store.close()
    assert result["qr_found"] is True
    assert result["qr_code"] == "ROLL-CLOUD-QR"
    assert result["qr_decoder"] == "gemini-full-frame"
    assert result["weight"] == pytest.approx(9.34)


def test_gemini_full_frame_keeps_local_qr_on_cloud_conflict(tmp_path) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(
                9.34,
                unit,
                True,
                True,
                "GEMINI_FULL:test",
                0.2,
                qr_code="ROLL-DIFFERENT",
                qr_readable=True,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )

    result = service.analyze(make_qr_frame("ROLL-LOCAL"), "auto", "kg")

    service.close()
    store.close()
    assert result["qr_found"] is True
    assert result["qr_code"] == "ROLL-LOCAL"
    assert result["qr_decoder"].endswith("+gemini-conflict-local-kept")
    assert "kept checksum-validated local QR" in result["weight_raw"]


def test_render_capture_sends_full_frame_with_scale_zoom_to_gemini(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.shape = None

        def read(self, frames, *, unit):
            assert len(frames) == 1
            self.shape = frames[0].shape[:2]
            assert self.shape[0] > 600
            assert self.shape[1] == 800
            return GeminiWeightSuggestion(13.04, unit, True, True, "GEMINI:test", 0.2)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(
        test_ui_module,
        "detect_weight_roi",
        lambda frame: (NormalizedROI(0.4, 0.7, 0.6, 0.8), "red-led"),
    )
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    reader = FakeGeminiReader()
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=reader,
        weight_engine="gemini",
    )

    result = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto",
        "kg",
        capture_kind="core",
    )

    service.close()
    store.close()
    assert result["weight"] == pytest.approx(13.04)
    assert reader.shape is not None
    assert result["evidence_zoom_applied"] is True
    assert result["evidence_zoom_method"] == "red-led"
    assert str(result["evidence_image"]).startswith("data:image/jpeg;base64,")
    assert result["gemini_crop_applied"] is False
    assert result["gemini_attempts"] == 1
    assert result["gemini_fallback_used"] is False
    assert result["roi_method"] == "gemini-full-frame+zoom-red-led"


def test_zoomed_core_evidence_keeps_analysis_binding_for_final_save(
    tmp_path, monkeypatch
) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(13.04, unit, True, True, "GEMINI:test", 0.2)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(
        test_ui_module,
        "detect_weight_roi",
        lambda frame: (NormalizedROI(0.4, 0.7, 0.6, 0.8), "red-led"),
    )
    frame = np.random.default_rng(7).integers(
        60, 220, size=(600, 800, 3), dtype=np.uint8
    )
    event_id = str(uuid.uuid4())
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )

    analysis = service.analyze(
        frame,
        "auto",
        "kg",
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
        capture_kind="core",
    )
    evidence = decode_image(str(analysis["evidence_image"]))
    saved = service.capture(
        "ROLL-ZOOM-001",
        13.04,
        "kg",
        evidence,
        True,
        "GEMINI:test",
        event_id=event_id,
        analysis_id=str(analysis["analysis_id"]),
        station_id="station-01",
        camera_id="camera-01",
        frame_sha256=str(analysis["frame_sha256"]),
    )
    row = store.get(event_id)

    service.close()
    store.close()
    assert saved["frame_sha256"] == analysis["frame_sha256"]
    assert row is not None
    stored_frame = cv2.imread(row.image_path)
    assert stored_frame is not None
    assert stored_frame.shape[0] > frame.shape[0]


def test_distant_portrait_scale_gets_side_by_side_context_zoom() -> None:
    frame = np.full((1280, 592, 3), 140, dtype=np.uint8)
    cv2.rectangle(frame, (210, 347), (286, 396), (0, 0, 230), -1)
    cv2.rectangle(frame, (218, 396), (279, 408), (0, 0, 230), -1)
    cv2.rectangle(frame, (131, 461), (139, 478), (0, 0, 230), -1)
    cv2.rectangle(frame, (306, 488), (319, 498), (0, 0, 255), -1)

    located = StationUIService._distant_weight_roi(frame)

    assert located is not None
    roi, method = located
    assert method == "distant-red-led"
    assert roi.x1 == pytest.approx(306 / 592, abs=0.01)
    assert roi.y1 == pytest.approx(488 / 1280, abs=0.01)
    composite, zoom_roi = StationUIService._zoomed_evidence(frame, roi)
    assert composite.shape[:2] == (1280, 1184)
    assert zoom_roi.x1 >= 0.5
    assert zoom_roi.x2 > zoom_roi.x1


def test_core_capture_skips_unrelated_qr_decode(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(7.02, unit, True, True, "GEMINI:test", 0.1)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(test_ui_module, "detect_weight_roi", lambda frame: None)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )
    monkeypatch.setattr(
        service,
        "_decode_qr",
        lambda frame: (_ for _ in ()).throw(AssertionError("core must not decode QR")),
    )

    result = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto",
        "kg",
        capture_kind="core",
    )

    service.close()
    store.close()
    assert result["weight"] == pytest.approx(7.02)
    assert result["qr_found"] is False
    assert result["qr_decoder"] == "not-requested-core-step"


def test_unreadable_gemini_full_frame_retries_one_led_crop(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.shapes = []

        def read(self, frames, *, unit):
            self.shapes.append(frames[0].shape[:2])
            if len(self.shapes) == 1:
                return GeminiWeightSuggestion(
                    None,
                    unit,
                    False,
                    True,
                    "GEMINI_FULL:weight-unreadable",
                    0.2,
                    input_tokens=100,
                    output_tokens=10,
                    total_tokens=110,
                )
            return GeminiWeightSuggestion(
                13.04,
                unit,
                True,
                True,
                "GEMINI_FULL:13.04",
                0.3,
                input_tokens=200,
                output_tokens=20,
                total_tokens=220,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(
        test_ui_module,
        "detect_weight_roi",
        lambda frame: (NormalizedROI(0.4, 0.7, 0.6, 0.8), "red-led"),
    )
    reader = FakeGeminiReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=reader,
        weight_engine="gemini",
    )

    result = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto",
        "kg",
        capture_kind="core",
    )

    service.close()
    store.close()
    assert reader.shapes[0][0] > 600
    assert reader.shapes[0][1] == 800
    assert reader.shapes[1][0] < reader.shapes[0][0]
    assert reader.shapes[1][1] < reader.shapes[0][1]
    assert result["weight"] == pytest.approx(13.04)
    assert result["gemini_attempts"] == 2
    assert result["gemini_fallback_used"] is True
    assert result["gemini_latency_seconds"] == pytest.approx(0.5)
    assert result["gemini_input_tokens"] == 300
    assert result["gemini_output_tokens"] == 30
    assert result["gemini_total_tokens"] == 330
    assert result["gemini_crop_applied"] is True
    assert result["roi_method"] == "gemini-full-frame+crop-zoom-red-led-retry"
    assert "FULL FRAME ATTEMPT" in result["weight_raw"]
    assert "CROP RETRY" in result["weight_raw"]


def test_gemini_full_frame_does_not_retry_network_error(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.calls = 0

        def read(self, frames, *, unit):
            self.calls += 1
            return GeminiWeightSuggestion(
                None,
                unit,
                False,
                False,
                "GEMINI ERROR: timeout",
                10.0,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(
        test_ui_module,
        "detect_weight_roi",
        lambda frame: (NormalizedROI(0.4, 0.7, 0.6, 0.8), "red-led"),
    )
    reader = FakeGeminiReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=reader,
        weight_engine="gemini",
    )

    result = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto",
        "kg",
        capture_kind="core",
    )

    service.close()
    store.close()
    assert reader.calls == 1
    assert result["weight_found"] is False
    assert result["gemini_attempts"] == 1
    assert result["gemini_fallback_used"] is False


def test_browser_qr_is_accepted_but_decoder_conflict_requires_manual_code(tmp_path) -> None:
    class FakeGeminiReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(9.34, unit, True, True, "GEMINI:test", 0.2)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakeGeminiReader(),
        weight_engine="gemini",
    )

    browser_only = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto",
        "kg",
        capture_kind="product",
        client_qr_code="SP-BROWSER-001",
    )
    conflict = service.analyze(
        make_qr_frame("SP-SERVER-001"),
        "auto",
        "kg",
        capture_kind="product",
        client_qr_code="SP-BROWSER-002",
    )

    service.close()
    store.close()
    assert browser_only["qr_code"] == "SP-BROWSER-001"
    assert browser_only["qr_decoder"] == "browser-barcode-detector"
    assert browser_only["qr_conflict"] is False
    assert conflict["qr_found"] is False
    assert conflict["qr_code"] is None
    assert conflict["qr_conflict"] is True


def test_gemini_profiles_use_their_configured_readers(tmp_path) -> None:
    class FakeGeminiReader:
        def __init__(self, model, value):
            self.model = model
            self.value = value
            self.calls = 0

        def read(self, frames, *, unit):
            self.calls += 1
            return GeminiWeightSuggestion(
                self.value,
                unit,
                True,
                True,
                f"GEMINI_FULL:{self.model}",
                0.2,
                qr_code="ROLL-PROFILE",
                qr_readable=True,
            )

        def status(self):
            return {"enabled": True, "model": self.model}

        def close(self):
            pass

    fast = FakeGeminiReader("gemini-3.5-flash-lite", 7.02)
    flash31 = FakeGeminiReader("gemini-3.1-flash-lite", 6.94)
    flash37 = FakeGeminiReader("gemini-3.7-flash", 9.03)
    accurate = FakeGeminiReader("gemini-3.1-pro-preview", 13.04)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=fast,
        gemini_flash31_reader=flash31,
        gemini_flash37_reader=flash37,
        gemini_accurate_reader=accurate,
        weight_engine="gemini",
    )

    flash31_result = service.analyze(
        make_qr_frame("ROLL-PROFILE-31"),
        "auto",
        "kg",
        recognition_profile="flash31",
    )
    flash37_result = service.analyze(
        make_qr_frame("ROLL-PROFILE-37"),
        "auto",
        "kg",
        recognition_profile="flash37",
    )
    result = service.analyze(
        make_qr_frame("ROLL-PROFILE"),
        "auto",
        "kg",
        recognition_profile="accurate",
    )

    status = service.status()
    service.close()
    store.close()
    assert flash31_result["weight"] == pytest.approx(6.94)
    assert flash31_result["recognition_profile"] == "flash31"
    assert flash37_result["weight"] == pytest.approx(9.03)
    assert flash37_result["recognition_profile"] == "flash37"
    assert result["weight"] == pytest.approx(13.04)
    assert result["recognition_profile"] == "accurate"
    assert fast.calls == 0
    assert flash31.calls == 1
    assert flash37.calls == 1
    assert accurate.calls == 1
    assert status["recognition_profiles"]["fast"]["model"] == "gemini-3.5-flash-lite"
    assert status["recognition_profiles"]["flash31"]["model"] == "gemini-3.1-flash-lite"
    assert status["recognition_profiles"]["flash37"]["model"] == "gemini-3.7-flash"
    assert status["recognition_profiles"]["accurate"]["model"] == "gemini-3.1-pro-preview"
    assert status["recognition_profiles"]["default"] == "flash31"


def test_ui_capture_blocks_same_frame_but_allows_consecutive_new_frames(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None, duplicate_window=5)
    frame = make_qr_frame("ROLL-WEB-DUPLICATE")
    service.capture("ROLL-WEB-DUPLICATE", 20, "kg", frame)
    with pytest.raises(ValueError, match="khung hình mới"):
        service.capture("ROLL-WEB-DUPLICATE", 20, "kg", frame)
    next_frame = frame.copy()
    next_frame[0, 0] = 0
    result = service.capture("ROLL-WEB-DUPLICATE", 20, "kg", next_frame)
    assert result["event_id"]
    assert store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 2
    store.close()


def test_ui_rejects_invalid_weight_and_image(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    with pytest.raises(ValueError, match="không âm"):
        service.capture("ROLL-WEB-BAD", -1, "kg", make_qr_frame("ROLL-WEB-BAD"))
    with pytest.raises(ValueError, match="base64"):
        decode_image("not-base64")
    store.close()


def test_session_cookie_authenticates_phone_without_basic_header() -> None:
    expires_at = 4_000_000_000
    cookie = encode_session_cookie("pilot", "secret", expires_at)
    assert decode_session_cookie(cookie, "pilot", "secret")
    assert not decode_session_cookie(cookie, "pilot", "other")
    assert not decode_session_cookie(cookie, "other", "secret")
    assert not decode_session_cookie(encode_session_cookie("pilot", "secret", 1), "pilot", "secret")
    assert safe_login_next("https://evil.example/steal") == "/kiem-kho"
    assert safe_login_next("/kiem-kho") == "/kiem-kho"
    assert safe_login_next("/?mode=inventory") == "/?mode=inventory"


def test_ui_has_capture_controls_without_lookup_panel() -> None:
    for control_id in (
        'id="analyzeCoreBtn"',
        'id="analyzeProductBtn"',
        'id="roiBox"',
        'id="qrBox"',
        'id="roiValue"',
        'id="syncBadge"',
        'id="geminiBadge"',
        'id="weightModeBadge"',
        'id="factoryBtn"',
    ):
        assert control_id in TEST_UI_HTML
    for removed_control in (
        'id="captureFile"',
        'id="captureFileBtn"',
        'id="lookupQr"',
        'id="lookupFile"',
        'id="lookupCameraBtn"',
        '<aside class="card lookup-card">',
        '2. Quét lại QR để tra cứu',
    ):
        assert removed_control not in TEST_UI_HTML
    assert "MỘT CAMERA · QR + CÂN" in TEST_UI_HTML
    assert "ĐÃ LƯU LẦN " in TEST_UI_HTML
    assert "ĐỒNG BỘ SUPABASE: BẬT" in TEST_UI_HTML
    assert "analyzeCurrent()" in TEST_UI_HTML
    assert "SẴN SÀNG CHỤP TIẾP" in TEST_UI_HTML
    assert "prepareNextCapture(data.qr_code)" in TEST_UI_HTML


def test_ui_uses_viet_nhat_red_black_roboto_branding() -> None:
    assert "Trạm cân <span>Ai</span> Việt Nhật IPT" in TEST_UI_HTML
    assert '<img class="brand-mark" src="/logo.jpg" alt="Việt Nhật IPT">' in TEST_UI_HTML
    assert "font-family:Roboto" in TEST_UI_HTML
    assert 'local("Roboto Regular")' in TEST_UI_HTML
    assert 'url("/fonts/roboto-vietnamese-wght-normal.woff2")' in TEST_UI_HTML
    assert 'url("/fonts/roboto-latin-wght-normal.woff2")' in TEST_UI_HTML
    assert "--primary:#d71920" in TEST_UI_HTML
    assert "fonts.googleapis.com" not in TEST_UI_HTML


def test_ui_uses_camera_left_params_right_capture_layout() -> None:
    assert "main{width:100%;margin:18px 0;padding:0 18px 24px;display:block}" in TEST_UI_HTML
    assert "grid-template-columns:minmax(460px,500px) minmax(0,1fr)" in TEST_UI_HTML
    assert "aspect-ratio:1/1" in TEST_UI_HTML
    assert "width:min(100%,480px)" in TEST_UI_HTML
    assert 'class="capture-left"' in TEST_UI_HTML
    assert 'class="capture-right"' in TEST_UI_HTML
    assert '<aside class="card lookup-card">' not in TEST_UI_HTML
    assert "main{width:100%" in TEST_UI_HTML


def test_ui_records_table_shows_bi_and_nvl_weights() -> None:
    assert "Trọng lượng bì" in TEST_UI_HTML
    assert "Trọng lượng NVL" in TEST_UI_HTML
    assert "function biWeightFromRaw(" in TEST_UI_HTML
    assert "function nvlWeight(" in TEST_UI_HTML
    assert "product-core-bi" in TEST_UI_HTML
    assert 'colspan="10"' in TEST_UI_HTML
    assert ">Mã QR</th>" in TEST_UI_HTML or "<th>Mã QR</th>" in TEST_UI_HTML
    assert "function productCodeFromQr(" in TEST_UI_HTML
    assert "productCodeFromQr(item.qr_code)" in TEST_UI_HTML
    assert "text.indexOf('_')" in TEST_UI_HTML
    assert "syncCaptureProductCodes(session)" in TEST_UI_HTML
    assert 'id="editProductCode"' in TEST_UI_HTML
    assert 'id="captureProductCode"' in TEST_UI_HTML
    assert "Mã QR lần 1" in TEST_UI_HTML
    assert "Mã QR lần 2" in TEST_UI_HTML
    assert "Mã nhập SP lần 1" not in TEST_UI_HTML
    assert "Mã nhập SP lần 2" not in TEST_UI_HTML
    assert 'id="sourceShift"' in TEST_UI_HTML
    assert 'HC1 · 06:00–14:00' in TEST_UI_HTML
    assert '12C2 · 18:00–06:00' in TEST_UI_HTML
    assert 'id="sourceMachine"' in TEST_UI_HTML
    assert 'Máy tái chế' in TEST_UI_HTML
    assert 'Máy cách nhiệt' in TEST_UI_HTML
    assert 'id="sourceOrder"' in TEST_UI_HTML
    assert 'list="sourceOrderList"' in TEST_UI_HTML
    assert "Chọn hoặc nhập LSX" in TEST_UI_HTML
    assert "setSourceOrderOptions" in TEST_UI_HTML
    assert "sanitizeOrder" in TEST_UI_HTML
    assert 'placeholder="Nhập lệnh SX"' not in TEST_UI_HTML
    assert "function productionOrdersQuery(" in TEST_UI_HTML
    assert "params.set('shift'" in TEST_UI_HTML
    assert "params.set('machine'" in TEST_UI_HTML
    assert "reloadProductionOrdersForFilters" in TEST_UI_HTML
    assert "$('sourceDate').addEventListener('change'" in TEST_UI_HTML
    assert 'id="biWeight"' in TEST_UI_HTML
    assert 'value="0.16"' in TEST_UI_HTML
    assert "Lệnh sản xuất" in TEST_UI_HTML
    assert "SOURCE_PRODUCTION_ORDER=" in TEST_UI_HTML
    assert "BI_WEIGHT=" in TEST_UI_HTML
    assert "production_order:sourceContext.order" in TEST_UI_HTML
    from roll_qr_scale.test_ui import _merge_source_tags
    merged = _merge_source_tags(
        "PRODUCT_WEIGHT=1.2",
        {
            "work_date": "2026-08-08",
            "shift": "HC1",
            "machine": "Máy Bao Bì",
            "production_order": "LSX-01",
            "bi_weight": 0.16,
        },
    )
    assert "SOURCE_SHIFT=HC1" in merged
    assert "SOURCE_MACHINE=Máy Bao Bì" in merged
    assert "SOURCE_PRODUCTION_ORDER=LSX-01" in merged
    assert "BI_WEIGHT=0.16" in merged


def test_production_orders_follow_selected_date() -> None:
    items = [
        {
            "work_date": "2026-08-13",
            "production_order": "LSX-02",
        },
        {
            "metadata": {
                "work_date": "2026-08-13",
                "production_order": "LSX-01",
            }
        },
        {
            "metadata": {
                "weight_raw": (
                    "SOURCE_DATE=2026-08-13; "
                    "SOURCE_PRODUCTION_ORDER=LSX-01"
                )
            }
        },
        {
            "work_date": "2026-08-14",
            "production_order": "LSX-03",
        },
    ]

    assert test_ui_module._production_orders_for_date(items, "2026-08-13") == [
        "LSX-01",
        "LSX-02",
    ]
    assert test_ui_module._matches_source_filters(
        items[0], work_date="2026-08-13", production_order="LSX-02"
    )


def test_matches_source_filters_supports_date_range_and_qr_code() -> None:
    item = {
        "qr_code": "SP-ABC-001",
        "work_date": "2026-08-20",
        "shift": "HC1",
        "weight_raw": "SOURCE_DATE=2026-08-20; SOURCE_SHIFT=HC1",
        "captured_at": "2026-08-20T10:00:00+07:00",
    }
    assert test_ui_module._matches_source_filters(
        item, date_from="2026-08-19", date_to="2026-08-21"
    )
    assert not test_ui_module._matches_source_filters(
        item, date_from="2026-08-21", date_to="2026-08-22"
    )
    assert test_ui_module._matches_source_filters(item, shift="HC1", qr_code="abc")
    assert not test_ui_module._matches_source_filters(item, shift="HC2")
    assert not test_ui_module._matches_source_filters(item, qr_code="XYZ")


def test_local_measurement_count_uses_all_source_filters_without_display_limit() -> None:
    matching_raw = (
        "SOURCE_DATE=2026-08-24; SOURCE_SHIFT=12C2; "
        "SOURCE_MACHINE=Máy cách nhiệt; SOURCE_PRODUCTION_ORDER=LSX-DH061"
    )
    rows = [
        {
            "event_id": f"synced-{index}",
            "captured_at": "2026-08-24T18:00:00+07:00",
            "weight_raw": matching_raw,
            "sync_status": "synced",
        }
        for index in range(205)
    ]
    rows.extend(
        {
            "event_id": f"pending-{index}",
            "captured_at": "2026-08-24T18:01:00+07:00",
            "weight_raw": matching_raw,
            "sync_status": "pending",
        }
        for index in range(3)
    )
    rows.append(
        {
            "event_id": "wrong-machine",
            "captured_at": "2026-08-24T18:02:00+07:00",
            "weight_raw": matching_raw.replace("Máy cách nhiệt", "Máy tái chế"),
            "sync_status": "pending",
        }
    )

    class FakeStore:
        def measurement_source_rows(self) -> list[dict[str, object]]:
            return rows

        def photo_draft_source_rows(self) -> list[dict[str, object]]:
            return [
                {
                    "event_id": "error-core",
                    "parent_event_id": "error-parent",
                    "captured_at": "2026-08-24T18:03:00+07:00",
                    "work_date": "2026-08-24",
                    "shift": "12C2",
                    "machine": "Máy cách nhiệt",
                    "production_order": "LSX-DH061",
                    "sync_status": "pending",
                },
                {
                    "event_id": "error-product",
                    "parent_event_id": "error-parent",
                    "captured_at": "2026-08-24T18:03:01+07:00",
                    "work_date": "2026-08-24",
                    "shift": "12C2",
                    "machine": "Máy cách nhiệt",
                    "production_order": "LSX-DH061",
                    "sync_status": "pending",
                },
                {
                    "event_id": "already-counted-photo",
                    "parent_event_id": "synced-0",
                    "captured_at": "2026-08-24T18:03:02+07:00",
                    "work_date": "2026-08-24",
                    "shift": "12C2",
                    "machine": "Máy cách nhiệt",
                    "production_order": "LSX-DH061",
                    "sync_status": "synced",
                },
            ]

    filters = {
        "work_date": "2026-08-24",
        "shift": "12C2",
        "machine": "Máy cách nhiệt",
        "production_order": "LSX-DH061",
    }
    assert test_ui_module._local_measurement_count(FakeStore(), **filters) == 208
    assert (
        test_ui_module._local_measurement_count(
            FakeStore(), **filters, unsynced_only=True
        )
        == 3
    )
    assert test_ui_module._local_production_counts(FakeStore(), **filters) == (209, 1)


def test_local_production_items_show_unread_photos_as_one_visible_row(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    parent_id = "31c3db88-2c7d-4a35-b5f0-3a83e9a6745a"
    core_id = "a5a53a31-3b46-484e-b111-59735657bed7"
    product_id = "d037931d-089d-44ce-96c5-53d41a95c933"
    common = {
        "parent_event_id": parent_id,
        "capture_round": 0,
        "needs_sync": True,
        "work_date": "2026-09-04",
        "shift": "12C2",
        "machine": "Máy Bao Bì",
        "production_order": "LSX-DH067",
    }
    store.save_photo_draft_idempotent(
        np.zeros((80, 120, 3), dtype=np.uint8),
        event_id=core_id,
        capture_kind="core",
        captured_at="2026-09-04T12:00:00+00:00",
        **common,
    )
    store.save_photo_draft_idempotent(
        np.full((80, 120, 3), 20, dtype=np.uint8),
        event_id=product_id,
        capture_kind="product",
        qr_code="SP-001",
        captured_at="2026-09-04T12:00:01+00:00",
        **common,
    )

    items = test_ui_module._local_production_items(
        store,
        100,
        work_date="2026-09-04",
        shift="12C2",
        machine="Máy Bao Bì",
        production_order="LSX-DH067",
    )
    store.close()

    assert len(items) == 1
    assert items[0]["event_id"] == parent_id
    assert items[0]["qr_code"] == "SP-001"
    assert items[0]["core_weight"] == "unread"
    assert items[0]["product_weight"] == "unread"
    assert items[0]["sync_status"] == "pending"
    assert items[0]["has_core_image"] is True
    assert items[0]["has_product_image"] is True
    assert core_id in str(items[0]["core_image_url"])
    assert product_id in str(items[0]["product_image_url"])
    assert "AI chưa đọc được số cân" in str(items[0]["sync_error"])

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    store.mark_photo_draft_synced(core_id, remote_id=1, remote_image_url="https://img/core.jpg")
    store.mark_photo_draft_synced(
        product_id,
        remote_id=2,
        remote_image_url="https://img/product.jpg",
    )
    synced_items = test_ui_module._local_production_items(
        store,
        100,
        work_date="2026-09-04",
        production_order="LSX-DH067",
    )
    store.close()

    assert len(synced_items) == 1
    assert synced_items[0]["sync_status"] == "synced"
    assert "AI chưa đọc được số cân" in str(synced_items[0]["sync_error"])


def test_shift_count_is_visible_and_refreshes_after_save_and_filter_changes() -> None:
    assert 'id="shiftCount"' in TEST_UI_HTML
    assert 'id="shiftCountValue"' in TEST_UI_HTML
    assert "Số lượng trong ca" in TEST_UI_HTML
    assert "data.total_count" in TEST_UI_HTML
    assert "data.error_count" in TEST_UI_HTML
    assert "ảnh đã hiện ở danh sách bên dưới" in TEST_UI_HTML
    assert 'id="shiftCountDetail"' in TEST_UI_HTML
    assert "Theo Ngày · Ca · Máy · Lệnh sản xuất" in TEST_UI_HTML
    assert "session.captureCount+=savedNow;await loadRecords()" in TEST_UI_HTML
    assert "await loadProductionOrders(fields.date,'');await loadRecords()" in TEST_UI_HTML
    assert "persistSourceFromFields();renderControls();loadRecords()" in TEST_UI_HTML
    assert 'id="rollBatchModal"' in TEST_UI_HTML
    assert "ROLL_BATCH_SIZE=10" in TEST_UI_HTML
    assert "function maybePromptRollBatchConfirm" in TEST_UI_HTML
    assert "function confirmRollBatchCount" in TEST_UI_HTML
    assert "rollBatchConfirmActive()" in TEST_UI_HTML
    assert 'id="weightAlertModal"' in TEST_UI_HTML
    assert "CORE_WEIGHT_ALERT_KG=1.2" in TEST_UI_HTML
    assert "function markWeightThresholdAlerts" in TEST_UI_HTML
    assert "PRODUCT_WEIGHT_ALERT_KG" in TEST_UI_HTML
    assert "function qrDuplicateMessage" in TEST_UI_HTML
    assert "function rejectDuplicateQr" in TEST_UI_HTML
    assert "function verifyQrAgainstServer" in TEST_UI_HTML
    assert "TRÙNG MÃ QR" in TEST_UI_HTML
    assert "rebuildProductionQrIndex" in TEST_UI_HTML
    assert "!roundHasDuplicateQr(session,index)" in TEST_UI_HTML


def test_production_orders_read_master_table_rows() -> None:
    rows = [
        {"ma_lsx": "LSX-A", "ngay": "01/07/2026", "ca": "12C1"},
        {"so_lenh": "LSX-B", "work_date": "2026-07-01", "ca": "12C1"},
        {"ma_lsx": "LSX-C", "ngay": "2026-07-02", "ca": "12C2"},
        {"ma_lsx": "LSX-D", "ngay": "01/07/2026", "ca": "12C2"},
    ]
    assert test_ui_module._production_orders_from_master(rows, "2026-07-01") == [
        "LSX-A",
        "LSX-B",
        "LSX-D",
    ]
    assert test_ui_module._production_orders_from_master(
        rows, "2026-07-01", shift="12C1"
    ) == ["LSX-A", "LSX-B"]
    assert test_ui_module._production_orders_from_master(
        rows, "2026-07-01", shift="12C1", machine="Máy cách nhiệt"
    ) == ["LSX-A", "LSX-B"]
    assert test_ui_module._production_orders_from_master(
        rows, "2026-07-01", shift="12C2"
    ) == ["LSX-D"]
    assert test_ui_module._normalize_source_date("01/07/2026") == "2026-07-01"
    assert test_ui_module._production_order_code({"Lenh_SX": "  PO-9  "}) == "PO-9"
    assert test_ui_module._production_order_code({"MÃ LỆNH": "LSX-DH048"}) == "LSX-DH048"
    assert test_ui_module._normalize_source_date("18/08/2026") == "2026-08-18"


def test_production_orders_match_machine_by_product_name() -> None:
    rows = [
        {
            "MÃ LỆNH": "LSX-DH048",
            "CA": "12C1",
            "BẮT ĐẦU": "18/08/2026",
            "TÊN HÀNG": "Tấm cách nhiệt Ranko P02",
        },
        {
            "MÃ LỆNH": "LSX-BB01",
            "CA": "12C1",
            "BẮT ĐẦU": "18/08/2026",
            "TÊN HÀNG": "Bao bì PE 50kg",
        },
    ]
    assert test_ui_module._production_orders_from_master(
        rows,
        "2026-08-18",
        shift="12C1",
        machine="Máy cách nhiệt",
    ) == ["LSX-DH048"]
    assert test_ui_module._production_orders_from_master(
        rows,
        "2026-08-18",
        shift="12C1",
        machine="Máy Bao Bì",
    ) == ["LSX-BB01"]


def test_master_supabase_table_filters_by_machine(monkeypatch) -> None:
    monkeypatch.setenv(
        "ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL",
        "https://example-master.supabase.co",
    )
    monkeypatch.setenv(
        "ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_SERVICE_KEY",
        "master-key",
    )

    rows = [
        {
            "MÃ LỆNH": "LSX-DH048",
            "CA": "12C1",
            "BẮT ĐẦU": "18/08/2026",
            "TÊN HÀNG": "Tấm cách nhiệt Ranko P02",
        },
        {
            "MÃ LỆNH": "LSX-BB01",
            "CA": "12C1",
            "BẮT ĐẦU": "18/08/2026",
            "TÊN HÀNG": "Bao bì PE 50kg",
        },
    ]

    def fake_fetch(url: str, key: str, table: str, **kwargs: object) -> list[dict[str, object]]:
        assert url == "https://example-master.supabase.co"
        assert key == "master-key"
        assert table == "lenh_sx"
        return rows

    monkeypatch.setattr(test_ui_module, "fetch_supabase_rows", fake_fetch)
    monkeypatch.setattr(
        test_ui_module,
        "_configured_production_order_tables",
        lambda: ["lenh_sx"],
    )

    orders, source, error, relaxed = test_ui_module._load_production_orders(
        "2026-08-18",
        shift="12C1",
        machine="Máy Bao Bì",
    )
    assert orders == ["LSX-BB01"]
    assert source == "master:lenh_sx"
    assert error == ""
    assert relaxed is None

    insulation, _, _, _ = test_ui_module._load_production_orders(
        "2026-08-18",
        shift="12C1",
        machine="Máy cách nhiệt",
    )
    assert insulation == ["LSX-DH048"]


def test_load_production_orders_reads_dotenv_before_master_check(
    monkeypatch, tmp_path: Path
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL=https://example-master.supabase.co",
                "ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_SERVICE_KEY=master-key",
                "ROLL_SCALE_PRODUCTION_ORDER_TABLE=lenh_sx",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL", raising=False)
    monkeypatch.delenv("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(test_ui_module, "_project_root", lambda: tmp_path)

    def fake_fetch(url: str, key: str, table: str, **kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "MÃ LỆNH": "LSX-DH048",
                "CA": "12C1",
                "BẮT ĐẦU": "18/08/2026",
                "TÊN HÀNG": "Tấm cách nhiệt Ranko P02",
            }
        ]

    monkeypatch.setattr(test_ui_module, "fetch_supabase_rows", fake_fetch)
    monkeypatch.setattr(
        test_ui_module,
        "_configured_production_order_tables",
        lambda: ["lenh_sx"],
    )

    orders, source, error, relaxed = test_ui_module._load_production_orders(
        "2026-08-18",
        shift="12C1",
        machine="Máy cách nhiệt",
    )
    assert orders == ["LSX-DH048"]
    assert source == "master:lenh_sx"
    assert error == ""
    assert relaxed is None


def test_production_orders_exclude_mismatched_measurement_tags() -> None:
    rows = [
        {
            "weight_raw": (
                "SOURCE_DATE=2026-08-18; SOURCE_SHIFT=12C1; "
                "SOURCE_MACHINE=Máy cách nhiệt; SOURCE_PRODUCTION_ORDER=LSX-DH048"
            )
        },
        {
            "weight_raw": (
                "SOURCE_DATE=2026-08-18; SOURCE_SHIFT=12C1; "
                "SOURCE_MACHINE=Máy tái chế; SOURCE_PRODUCTION_ORDER=LSX-DH039"
            )
        },
        {
            "weight_raw": (
                "SOURCE_DATE=2026-08-18; SOURCE_SHIFT=12C1; "
                "SOURCE_MACHINE=Máy tái chế; SOURCE_PRODUCTION_ORDER=fgfgfgfgfgfgfg"
            )
        },
    ]
    assert test_ui_module._production_orders_from_master(
        rows,
        "2026-08-18",
        shift="12C1",
        machine="Máy cách nhiệt",
    ) == ["LSX-DH048"]


def test_remote_product_image_does_not_request_redundant_signed_url() -> None:
    source = Path(test_ui_module.__file__).read_text(encoding="utf-8")
    assert "if not product_url and isinstance(product_path, str) and product_path:" in source


def test_panel_region_configuration_is_persisted_and_validated(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
    )
    regions = [
        {"label": "TEMP 1", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
        {"label": "HEAD 1", "x1": 0.5, "y1": 0.2, "x2": 0.7, "y2": 0.4},
    ]

    assert service.save_panel_regions("station-01", regions) == regions
    assert service.panel_regions("station-01") == regions
    with pytest.raises(ValueError, match="Tên vùng"):
        service.save_panel_regions("station-01", [regions[0], {**regions[1], "label": "temp 1"}])
    service.close()
    store.close()


def test_panel_analysis_crops_all_regions_and_calls_gemini_once(tmp_path) -> None:
    class FakePanelReader:
        def __init__(self):
            self.calls = []

        def read_panel_regions(self, regions):
            self.calls.append(regions)
            return {
                "ok": True,
                "readings": [
                    {"label": label, "readable": True, "value": str(index + 1)}
                    for index, (label, _) in enumerate(regions)
                ],
            }

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    reader = FakePanelReader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=reader,
        weight_engine="gemini",
    )
    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    result = service.analyze_panel_regions(
        frame,
        [
            {"label": "A", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
            {"label": "B", "x1": 0.5, "y1": 0.5, "x2": 0.9, "y2": 0.8},
        ],
    )

    assert result["readings"][0]["label"] == "A"
    assert len(reader.calls) == 1
    assert reader.calls[0][0][1].shape[:2] == (40, 80)
    assert reader.calls[0][1][1].shape[:2] == (60, 160)
    service.close()
    store.close()


def test_panel_analysis_keeps_fast_reader_for_many_regions(tmp_path) -> None:
    class FakePanelReader:
        def __init__(self, model):
            self.model = model
            self.calls = []

        def read_panel_regions(self, regions):
            self.calls.append(regions)
            return {"ok": True, "model": self.model, "readings": []}

        def status(self):
            return {"enabled": True, "model": self.model}

        def close(self):
            pass

    fast = FakePanelReader("fast-10s")
    accurate = FakePanelReader("accurate-30s")
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=fast,
        gemini_accurate_reader=accurate,
        weight_engine="gemini",
    )
    frame = np.zeros((200, 500, 3), dtype=np.uint8)
    regions = [
        {
            "label": f"Chỉ số {index + 1:02d}",
            "x1": index * 0.18,
            "y1": 0.2,
            "x2": index * 0.18 + 0.15,
            "y2": 0.5,
        }
        for index in range(5)
    ]

    result = service.analyze_panel_regions(
        frame,
        regions,
        recognition_profile="fast",
    )

    assert result["recognition_profile"] == "fast"
    assert result["model"] == "fast-10s"
    assert len(fast.calls) == 1
    assert len(fast.calls[0]) == 5
    assert accurate.calls == []
    service.close()
    store.close()


def test_panel_detection_normalizes_regions_for_operator_review(tmp_path) -> None:
    class FakePanelDetector:
        def detect_panel_regions(self, frame):
            assert frame.shape == (200, 400, 3)
            return {
                "ok": True,
                "method": "fake-detection",
                "regions": [
                    {
                        "label": "TEMP",
                        "x1": 0.1,
                        "y1": 0.2,
                        "x2": 0.3,
                        "y2": 0.4,
                    },
                    {
                        "label": "outside",
                        "x1": -0.1,
                        "y1": 0.2,
                        "x2": 0.3,
                        "y2": 0.4,
                    },
                    {
                        "label": "TEMP",
                        "x1": 0.5,
                        "y1": 0.6,
                        "x2": 0.7,
                        "y2": 0.8,
                    },
                ],
            }

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gemini_reader=FakePanelDetector(),
        weight_engine="gemini",
    )

    result = service.detect_panel_regions(np.zeros((200, 400, 3), dtype=np.uint8))

    assert result["method"] == "fake-detection"
    assert result["regions"] == [
        {"label": "TEMP", "x1": 0.1, "y1": 0.2, "x2": 0.3, "y2": 0.4},
        {
            "label": "Chỉ số 03",
            "x1": 0.5,
            "y1": 0.6,
            "x2": 0.7,
            "y2": 0.8,
        },
    ]
    service.close()
    store.close()


def test_product_capture_uses_detected_qr_as_product_code() -> None:
    assert "session.qr=data.qr_code||''" not in TEST_UI_HTML
    assert "if(isProduct){session.productAnalysis=data" in TEST_UI_HTML
    assert "reliableQr=Boolean(data.qr_found&&!data.qr_conflict&&!qrDecoder.startsWith('gemini'))" in TEST_UI_HTML
    assert "if(reliableQr&&String(data.qr_code||'').trim()&&!String(session.qr||'').trim())" in TEST_UI_HTML
    assert "$('analyzeCoreBtn').disabled=panelMode||busy||!ready" in TEST_UI_HTML
    assert "$('analyzeProductBtn').disabled=panelMode||busy||!ready||!coreReady(session)" in TEST_UI_HTML
    assert "$('analyzeCoreBtn').disabled=panelMode||busy||!ready||!sourceChosen" not in TEST_UI_HTML
    assert "function coreCaptured(session)" in TEST_UI_HTML
    assert "function sourceReady(session)" in TEST_UI_HTML
    assert "if(isProduct&&!coreReady(session))" in TEST_UI_HTML
    assert "session._analyzeLock=false;renderControls();status(captureStatus,error.message" in TEST_UI_HTML
    assert "await api('/api/session/discard'" in TEST_UI_HTML
    assert "retryingFailedCore=!isProduct&&targetRound===0&&session.state==='error'&&Boolean(session.eventId)" in TEST_UI_HTML
    assert "if(retryingFailedCore&&round.eventId===discardedEventId)round.eventId=null" in TEST_UI_HTML
    assert "Nhấn Enter để lưu ảnh với số trống" in TEST_UI_HTML
    assert "ID ảnh sẽ được tự tạo an toàn" in TEST_UI_HTML
    assert 'id="analyzeCoreBtn"' in TEST_UI_HTML
    assert 'id="analyzeProductBtn"' in TEST_UI_HTML
    assert 'id="productWeight"' in TEST_UI_HTML
    assert "analyzeCurrent('core')" in TEST_UI_HTML
    assert "analyzeCurrent('product')" in TEST_UI_HTML
    assert "PRODUCT_WEIGHT=" in TEST_UI_HTML
    assert "function productReady(session)" in TEST_UI_HTML
    assert "ĐÃ CÂN LÕI · CHỜ CÂN SẢN PHẨM" in TEST_UI_HTML
    assert 'id="weight" type="number" min="0" step="0.001" placeholder="AI tự đọc" readonly' in TEST_UI_HTML
    assert 'id="productWeight" type="number" min="0" step="0.001" placeholder="AI tự đọc" readonly' in TEST_UI_HTML
    assert TEST_UI_HTML.count('<span class="kbd">Space</span>') == 3
    assert 'id="inventoryCaptureBtn"' in TEST_UI_HTML
    assert 'class="workflow-tabs" role="tablist"' in TEST_UI_HTML
    assert "viewport-fit=cover" in TEST_UI_HTML
    assert "@media(max-width:768px)" in TEST_UI_HTML
    assert "source-fields{grid-template-columns:repeat(2,minmax(0,1fr))" in TEST_UI_HTML
    assert "source-fields .apply{grid-column:1/-1" in TEST_UI_HTML
    assert "safe-area-inset-bottom" in TEST_UI_HTML
    assert "#productionToolbar{position:sticky" in TEST_UI_HTML
    assert 'id="productionModeBtn" role="tab"' in TEST_UI_HTML
    assert 'id="inventoryModeBtn" role="tab"' in TEST_UI_HTML
    assert 'id="listModeBtn" role="tab"' in TEST_UI_HTML
    assert 'id="listFilters"' in TEST_UI_HTML
    assert 'id="listDateFrom"' in TEST_UI_HTML
    assert 'id="listDateTo"' in TEST_UI_HTML
    assert 'id="listShift"' in TEST_UI_HTML
    assert 'id="listQrCode"' in TEST_UI_HTML
    assert 'id="listRecordsCard"' in TEST_UI_HTML
    assert "loadListRecords()" in TEST_UI_HTML
    assert "function cloudinaryDisplayUrl(" in TEST_UI_HTML
    assert "c_limit,w_'+safeWidth+'/q_auto:" in TEST_UI_HTML
    assert "image.src=cloudinaryDisplayUrl(url,240,'eco')" in TEST_UI_HTML
    assert "img.src=cloudinaryDisplayUrl(url,1280,'good')" in TEST_UI_HTML
    assert "link.href=url" in TEST_UI_HTML
    assert "const LIST_PAGE_SIZE=50" in TEST_UI_HTML
    assert 'id="listPrevPageBtn"' in TEST_UI_HTML
    assert 'id="listNextPageBtn"' in TEST_UI_HTML
    assert "offset='+offset+'&'+listQuery()" in TEST_UI_HTML
    assert "await loadListRecords(false)" in TEST_UI_HTML
    assert "'/api/measurements?limit=50&'" in TEST_UI_HTML
    assert "'/api/inventory-checks?limit=50'" in TEST_UI_HTML
    assert "function startAiCountdown(" in TEST_UI_HTML
    assert "function stopAiCountdown(" in TEST_UI_HTML
    assert "startAiCountdown(session.box," in TEST_UI_HTML
    assert "stopAiCountdown()" in TEST_UI_HTML
    assert "function rereadListRecord(" in TEST_UI_HTML
    assert "'/api/measurements/reread'" in TEST_UI_HTML
    assert "reread-core" in TEST_UI_HTML
    assert "reread-product" in TEST_UI_HTML
    assert "function decodeQrFromImageUrl(" in TEST_UI_HTML
    assert "client_qr_code:clientQr" in TEST_UI_HTML
    assert "QR local" in TEST_UI_HTML or "decoder local" in TEST_UI_HTML
    assert "Đọc lõi" in TEST_UI_HTML
    assert "Đọc SP" in TEST_UI_HTML
    assert "date_from=" in TEST_UI_HTML
    assert "qr_code=" in TEST_UI_HTML
    assert 'id="inventoryWeight" class="weight" type="number" min="0" step="0.001" placeholder="Auto" readonly' in TEST_UI_HTML
    assert 'id="inventoryCoreWeight" class="weight" type="number" min="0" step="0.001" value="1"' in TEST_UI_HTML
    assert 'id="inventoryTareWeight" class="weight" type="number" min="0" step="0.001" value="0.16"' in TEST_UI_HTML
    assert "DEFAULT_INVENTORY_CORE_WEIGHT=1" in TEST_UI_HTML
    assert "coreWeight:String(DEFAULT_INVENTORY_CORE_WEIGHT)" in TEST_UI_HTML
    assert "capture_kind:'inventory'" in TEST_UI_HTML
    assert "'/api/inventory-capture'" in TEST_UI_HTML
    assert 'id="inventoryPhoneBtn"' in TEST_UI_HTML
    assert '>Chụp ảnh</button>' in TEST_UI_HTML
    assert "function captureInventoryPhoto(" in TEST_UI_HTML
    assert "bindActionButton('inventoryPhoneBtn',()=>captureInventoryPhoto())" in TEST_UI_HTML
    assert "function applyWorkflowLayout(" in TEST_UI_HTML
    assert "function wantsInventoryMode(" in TEST_UI_HTML
    assert "window.parent!==window" in TEST_UI_HTML
    assert "applyWorkflowLayout(workflowMode)" in TEST_UI_HTML
    assert "session.eventId&&!wantsInventoryMode()" in TEST_UI_HTML
    assert "function readSessionToken(" in TEST_UI_HTML
    assert "Authorization='Bearer '" in TEST_UI_HTML
    assert "X-Tram-Can-Session" in TEST_UI_HTML
    assert "window.name='tram_can_session='" in TEST_UI_HTML
    assert "function redirectToLogin(" in TEST_UI_HTML
    assert "error.code='authentication_required'" in TEST_UI_HTML
    assert "isAuthenticationRequired(failed.error)" in TEST_UI_HTML
    assert "function wantsInventoryMode(" in TEST_UI_HTML
    assert "/kiem-kho" in TEST_UI_HTML
    assert "analyzeInventory()" in TEST_UI_HTML
    assert "if(!session.stream){await openDefaultCamera(session);if(!session.stream)return}" in TEST_UI_HTML
    assert "function captureInventoryPhoto(" in TEST_UI_HTML
    assert "function nextCaptureKind(" in TEST_UI_HTML
    assert "captureNextWeight()" in TEST_UI_HTML
    assert "event.key==='p'" not in TEST_UI_HTML
    assert "event.key==='P'" not in TEST_UI_HTML
    assert "recognitionProvider.value==='codex'?'Codex':'AI'" in TEST_UI_HTML
    assert "function showPostCaptureSource(session,next=nextCaptureStep(session))" in TEST_UI_HTML
    assert "session.preview.onload=null;if(session.stream){showVideo(session);return}" in TEST_UI_HTML
    assert "session.preview.removeAttribute('src')" in TEST_UI_HTML
    assert "session.placeholder.textContent='Mở camera để chụp '+nextStillCaptureLabel(next)" in TEST_UI_HTML
    assert "function advanceToNextCapture(session)" in TEST_UI_HTML
    assert "const next=nextCaptureStep(session);if(next)session.selectedSlot=next" in TEST_UI_HTML
    assert "const next=advanceToNextCapture(session);" in TEST_UI_HTML
    assert "scrollIntoView({behavior:'smooth',block:'nearest'})" in TEST_UI_HTML
    assert "Ảnh cũ đã khóa. Bấm Mở camera" in TEST_UI_HTML
    assert "bindActionButton('inventoryPhoneBtn',()=>captureInventoryPhoto())" in TEST_UI_HTML
    assert "$('captureFileBtn').onclick=()=>$('captureFile').click();$('captureFile').onchange=event=>{const file=event.target.files[0];event.target.value='';loadCaptureFile(file)}" not in TEST_UI_HTML
    assert "session.selectedSlot={kind:'core',round:0};ensureRounds(session)" in TEST_UI_HTML
    assert "showCapturedBlank" not in TEST_UI_HTML
    assert "function cameraVideoConstraints()" in TEST_UI_HTML
    assert "facingMode:{ideal:'environment'}" in TEST_UI_HTML
    assert "function prefersDirectMobileCamera()" in TEST_UI_HTML
    assert "function openPrimaryCamera()" in TEST_UI_HTML
    assert "bindActionButton('openDefaultCamBtn',()=>openPrimaryCamera())" in TEST_UI_HTML
    assert '<meta name="theme-color" content="#0d0d0f">' in TEST_UI_HTML
    assert '@media(hover:none)' in TEST_UI_HTML
    assert 'id="captureQr" autocomplete="off" autofocus' not in TEST_UI_HTML
    assert "function openPrimaryCamera()" in TEST_UI_HTML
    assert "bindActionButton('openDefaultCamBtn',()=>openPrimaryCamera())" in TEST_UI_HTML
    assert "function ensureStationsReady()" in TEST_UI_HTML
    assert "function cameraErrorHint(error)" in TEST_UI_HTML
    assert "Chưa thấy camera — bấm Làm mới / Mở camera" in TEST_UI_HTML
    assert "{video:true,audio:false}" in TEST_UI_HTML
    assert "function decodeClientQr(canvas)" in TEST_UI_HTML
    assert "client_qr_code:clientQr" in TEST_UI_HTML
    assert "const evidenceImage=data.evidence_image||image" in TEST_UI_HTML
    assert "session.productImage=evidenceImage" in TEST_UI_HTML
    assert "session.capturedImage=evidenceImage" in TEST_UI_HTML
    assert "AI đọc toàn ảnh + zoom cân" in TEST_UI_HTML
    assert "CAPTURE_MAX_EDGE=1600" in TEST_UI_HTML
    assert "width:{ideal:1920}" in TEST_UI_HTML
    assert "height:{ideal:1080}" in TEST_UI_HTML
    assert "AI đọc toàn ảnh" in TEST_UI_HTML
    assert "setInterval(()=>workflowMode==='inventory'?loadInventoryRecords():loadRecords(),15000)" not in TEST_UI_HTML
    assert "appStatus.release||'local'" in TEST_UI_HTML
    assert 'id="panelModeBtn"' in TEST_UI_HTML
    assert 'id="autoDetectPanelBtn"' in TEST_UI_HTML
    assert 'id="drawPanelRegionBtn"' in TEST_UI_HTML
    assert 'id="scanPanelBtn"' in TEST_UI_HTML
    assert "'/api/panel/detect'" in TEST_UI_HTML
    assert "'/api/panel/analyze'" in TEST_UI_HTML
    assert "'/api/panel/regions'" in TEST_UI_HTML
    assert "function autoDetectPanelRegions(" in TEST_UI_HTML
    assert "function mergeDetectedPanelRegions(" in TEST_UI_HTML
    assert "function panelPointerDown(" in TEST_UI_HTML
    assert "function scanPanelRegions(" in TEST_UI_HTML
    assert "Tự tìm sẽ khoanh từng hàng số LED đang sáng" in TEST_UI_HTML
    assert "loadPanelRegions(session).then" in TEST_UI_HTML
    assert 'id="panelCameraSelect"' in TEST_UI_HTML
    assert 'id="openPanelCameraBtn"' in TEST_UI_HTML
    assert 'id="closePanelCameraBtn"' in TEST_UI_HTML
    assert "PANEL_CAMERA_MAP_PREFIX" in TEST_UI_HTML
    assert "function openPanelCamera(" in TEST_UI_HTML
    assert "function useMainCameraForPanel(" in TEST_UI_HTML
    assert "function captureSource(" in TEST_UI_HTML
    assert "session.panelStream&&session.panelVideo.videoWidth" in TEST_UI_HTML
    assert "URL và mã xác thực không được gửi lên Render" in TEST_UI_HTML
    assert 'id="cameraSetupModal"' in TEST_UI_HTML
    assert 'id="cameraSetupDevice"' in TEST_UI_HTML
    assert 'id="cameraSetupTarget"' in TEST_UI_HTML
    assert 'id="ipCameraHost"' in TEST_UI_HTML
    assert 'id="ipCameraVerification" type="password"' in TEST_UI_HTML
    assert 'id="copyIpCameraUrlBtn"' in TEST_UI_HTML
    assert 'id="connectConfiguredCameraBtn"' in TEST_UI_HTML
    assert "function normalizeIpCameraHost(" in TEST_UI_HTML
    assert "function copyIpCameraUrl(" in TEST_UI_HTML
    assert "function connectConfiguredCamera(" in TEST_UI_HTML
    assert "IP_CAMERA_HOST_KEY" in TEST_UI_HTML
    assert "localStorage.setItem(IP_CAMERA_HOST_KEY,values.host)" in TEST_UI_HTML
    assert "localStorage.setItem(IP_CAMERA_HOST_KEY,url)" not in TEST_UI_HTML
    assert "cameraSetupTarget').value='shared'" in TEST_UI_HTML
    assert "Đã kết nối camera dùng chung cho cân, QR và bảng nhiều chỉ số" in TEST_UI_HTML


def test_ui_confirms_the_exact_row_before_deleting_saved_error_photos() -> None:
    assert "CHỈ XÓA DÒNG NÀY?\\nMã QR:" in TEST_UI_HTML
    assert "Hai ảnh cùng lượt sẽ được xóa khỏi danh sách/DB." in TEST_UI_HTML
    assert "cloud_photo_drafts_deleted" in TEST_UI_HTML


def test_production_history_only_offers_delete_for_error_rows() -> None:
    assert 'class="record-actions-col">Thao tác</th>' in TEST_UI_HTML
    assert 'id="productionRecordsStatus"' in TEST_UI_HTML
    assert "function appendProductionDeleteAction(" in TEST_UI_HTML
    assert "if(errorState==='error')" in TEST_UI_HTML
    assert "button.textContent='Xóa dòng lỗi'" in TEST_UI_HTML
    assert "CHỈ XÓA DÒNG LỖI NÀY?\\nMã QR:" in TEST_UI_HTML
    assert "recordErrorStatus(item)!=='error'" in TEST_UI_HTML


def test_ui_weighs_multiple_rounds_with_split_second_table() -> None:
    assert 'id="roundCount"' in TEST_UI_HTML
    assert 'id="evidenceRounds"' in TEST_UI_HTML
    assert 'id="weight2"' in TEST_UI_HTML
    assert 'id="productWeight2"' in TEST_UI_HTML
    assert "DEFAULT_WEIGH_ROUNDS=3" in TEST_UI_HTML
    assert "MAX_WEIGH_ROUNDS=3" in TEST_UI_HTML
    assert "function nextCaptureStep(" in TEST_UI_HTML
    assert "function extraRoundTags(" in TEST_UI_HTML
    assert "function discardSlot(" in TEST_UI_HTML
    assert "function discardRound(" in TEST_UI_HTML
    assert "function resetWeighRound(" in TEST_UI_HTML
    assert "className='slot-discard'" in TEST_UI_HTML
    assert "Bỏ từng ô để đọc lại" in TEST_UI_HTML
    assert "dataset.discardKind=kind" in TEST_UI_HTML
    assert "dataset.discardRound=String(round)" in TEST_UI_HTML
    assert "Ô còn lại giữ nguyên" in TEST_UI_HTML
    assert "ROUND2_CORE=" in TEST_UI_HTML
    assert "evidence-round split" in TEST_UI_HTML
    assert "evidence-round split" in TEST_UI_HTML
    assert "session.eventId&&(retryingFailedCore||session.coreAnalysis&&session.analysisId)" in TEST_UI_HTML
    assert "if(targetRound===0)" in TEST_UI_HTML
    assert "capture_kind:targetRound>0?'product':kind" in TEST_UI_HTML
    assert 'id="captureQr2"' in TEST_UI_HTML
    assert "Mã QR lần 1" in TEST_UI_HTML
    assert "Mã QR lần 2" in TEST_UI_HTML
    assert "ROUND2_QR=" in TEST_UI_HTML
    assert "function codesReady(" in TEST_UI_HTML
    assert "function applyScannedQr(" in TEST_UI_HTML
    assert "function targetQrInput(" in TEST_UI_HTML
    assert "function flushQrScanBuffer(" in TEST_UI_HTML
    assert "Đã nhận QR " in TEST_UI_HTML
    assert "persistEditor(session);refreshCompletionState(session)}" in TEST_UI_HTML
    assert "function attachRoundParams(" in TEST_UI_HTML
    assert 'id="paramsPark"' in TEST_UI_HTML
    assert "function selectCaptureSlot(" in TEST_UI_HTML
    assert "function captureSlot(" in TEST_UI_HTML
    assert "dataset.captureKind" in TEST_UI_HTML


def test_ui_records_error_state_and_confirms_printable_ten_roll_batches() -> None:
    assert 'id="errorStatus1"' in TEST_UI_HTML
    assert 'id="errorReason1"' in TEST_UI_HTML
    assert "ERROR_STATUS=" in TEST_UI_HTML
    assert "ERROR_REASON=" in TEST_UI_HTML
    assert "Lý do lỗi trước khi lưu" in TEST_UI_HTML
    assert 'id="weighBatchRecordsCard"' in TEST_UI_HTML
    assert 'id="printSheet"' in TEST_UI_HTML
    assert "function printWeighBatch" in TEST_UI_HTML
    assert "/api/weighing-batches/confirm" in TEST_UI_HTML
    assert "Đang tạo đợt cân trong bảng ca_can" in TEST_UI_HTML
    assert "writeRollBatchConfirmed(0)" in TEST_UI_HTML
    assert "confirmed+ROLL_BATCH_SIZE" in TEST_UI_HTML


def test_ui_buttons_start_once_and_show_immediate_press_feedback() -> None:
    assert "function pulseButton(btn)" in TEST_UI_HTML
    assert "btn.dataset.busy==='1'" in TEST_UI_HTML
    assert "btn.setAttribute('aria-busy','true')" in TEST_UI_HTML
    assert "document.querySelectorAll('button:not([type])')" in TEST_UI_HTML
    assert "document.addEventListener('pointerdown'" in TEST_UI_HTML
    assert "bindActionButton('openDefaultCamBtn'" in TEST_UI_HTML
    assert "bindActionButton('panelModeBtn'" in TEST_UI_HTML
    assert "function captureNextWeight()" in TEST_UI_HTML
    assert "if(!button.disabled)button.click()" in TEST_UI_HTML
    assert "$('discardBtn').click()" in TEST_UI_HTML
    assert "$('saveBtn').click()" in TEST_UI_HTML
    assert "Chụp lại cân lõi?" not in TEST_UI_HTML


def test_ui_zooms_scale_view_without_cropping_capture_frame() -> None:
    assert 'class="media-layer"' in TEST_UI_HTML
    assert 'class="view-zoom-controls"' in TEST_UI_HTML
    assert "const VIEW_ZOOM_LEVELS=[1,1.5,2,3,4]" in TEST_UI_HTML
    assert "function setupViewZoom(session)" in TEST_UI_HTML
    assert "function focusViewZoom(session,event)" in TEST_UI_HTML
    assert "session.box.addEventListener('wheel'" in TEST_UI_HTML
    assert "session.box.addEventListener('dblclick'" in TEST_UI_HTML
    assert "session.zoomLayer.style.transform='scale('+level+')'" in TEST_UI_HTML
    assert "drawImage(source,0,0,targetWidth,targetHeight)" in TEST_UI_HTML


def test_ui_enables_local_yolo_model_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    assert test_ui_module.build_parser().parse_args([]).yolo_model is None
    model = tmp_path / "models" / "qr_demo_synthetic.pt"
    model.parent.mkdir()
    model.write_bytes(b"test")
    args = test_ui_module.build_parser().parse_args([])
    assert args.yolo_model == "models/qr_demo_synthetic.pt"
    assert args.yolo_mode == "fallback"
    assert args.ocr_min_confidence == pytest.approx(0.60)
    assert args.diagnostic_image is None


def test_multistation_defaults_and_html_controls(monkeypatch) -> None:
    monkeypatch.delenv("ROLL_SCALE_GATEWAY_ID", raising=False)
    monkeypatch.delenv("ROLL_SCALE_DEVICE_ID", raising=False)
    monkeypatch.delenv("ROLL_SCALE_WEIGHT_ENGINE", raising=False)
    monkeypatch.delenv("ROLL_SCALE_GEMINI_API_KEY", raising=False)
    args = test_ui_module.build_parser().parse_args([])
    assert args.station_count == 1
    assert args.gateway_id == "gateway-01"
    assert args.station_ids is None
    assert args.camera_ids is None
    assert args.weight_rois is None
    assert args.weight_burst_frames == 5
    assert args.weight_engine == "local"
    assert args.gemini_fallback is False
    assert args.gemini_timeout == pytest.approx(10.0)
    assert args.gemini_model == "gemini-3.5-flash-lite"
    assert args.gemini_31_model == "gemini-3.1-flash-lite"
    assert args.gemini_31_timeout == pytest.approx(15.0)
    assert args.gemini_37_model == "gemini-3.7-flash"
    assert args.gemini_37_timeout == pytest.approx(30.0)
    assert args.gemini_accurate_model == "gemini-3.1-pro-preview"
    assert args.gemini_accurate_timeout == pytest.approx(30.0)
    assert args.codex_enabled is True
    assert args.codex_mode == "auto"
    assert args.codex_command == "codex"
    assert args.codex_model == ""
    assert args.codex_timeout == pytest.approx(60.0)
    assert args.auto_advance is True
    for marker in (
        'id="stationGrid"',
        'id="cameraSelect1"',
        'id="autoAdvance"',
        'id="discardBtn"',
        "class CameraSession extends StationSession",
        "navigator.mediaDevices.enumerateDevices()",
        "deviceId:{exact:requested}",
        "localStorage.getItem",
        "crypto.randomUUID",
        "data.event_id!==requestEventId",
        "event.key==='Enter'",
        "['1','2','3']",
        "refreshCameraDevices(true)",
        "ensureCamerasForSelect()",
        "ensureCameraPermission()",
        "session.stream!==stream||session.streamGeneration!==generation",
        "ĐỦ DỮ LIỆU · ",
        "prepareNextCapture('',session)",
        "'awaiting-code'",
        "'awaiting-weight'",
        "function completionReady(session)",
        "function sourceReady(session)",
        "function productReady(session)",
        "ĐÃ CÂN LÕI · CHỜ CÂN SẢN PHẨM",
        'id="analyzeCoreBtn"',
        'id="analyzeProductBtn"',
        'id="productWeight"',
        "analyzeCurrent('product')",
        "Nhanh · 3.5 Flash-Lite · Free",
        "Cân bằng · 3.7 Flash · Low · Free",
        "Chính xác · Pro · cần trả phí",
        "savedStationIndex=stations.indexOf(session)",
        "captureEditor=isQrField(event.target)||event.target===$('biWeight')",
        "scheduleReconnect(session,session.deviceId)",
        "this.hydratedPending=Boolean(config.event_id)",
        "function pollPendingSessions()",
            "Mở camera rồi chụp cân lõi / cân sản phẩm.",
        "session.deviceId&&!session.hasUnsavedReview()",
        "weight_frames:weightFrames",
        "captureWeightBurst(session)",
        "function isTextEditingTarget(target)",
        "function discardSlot(",
        "function discardRound(",
        "discardCurrent(requireConfirmation=false)",
        "session._discardLock=true;renderControls()",
        "discardCurrent(false)",
        "className='slot-discard'",
    ):
        assert marker in TEST_UI_HTML


def test_parser_auto_selects_gemini_only_when_key_exists_and_engine_is_omitted(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ROLL_SCALE_WEIGHT_ENGINE", raising=False)
    monkeypatch.setenv("ROLL_SCALE_GEMINI_API_KEY", "configured-test-key")
    assert test_ui_module.build_parser().parse_args([]).weight_engine == "gemini"

    monkeypatch.setenv("ROLL_SCALE_WEIGHT_ENGINE", "local")
    assert test_ui_module.build_parser().parse_args([]).weight_engine == "local"


def test_ui_does_not_offer_fake_gemini_profile_when_backend_is_local() -> None:
    assert 'id="recognitionProfileOption"' in TEST_UI_HTML
    assert 'id="recognitionProvider"' in TEST_UI_HTML
    assert 'id="recognitionHint"' in TEST_UI_HTML
    assert "function syncRecognitionSettings" in TEST_UI_HTML
    assert "new Option('Mặc định · 3.1 Flash-Lite · Free','flash31')" in TEST_UI_HTML
    assert "recognitionProfile.value='flash31'" in TEST_UI_HTML
    assert '<option value="gemini">Gemini API</option>' in TEST_UI_HTML
    assert '<option value="codex">Codex · ChatGPT</option>' in TEST_UI_HTML
    assert "$('recognitionProviderOption').hidden=!primary" in TEST_UI_HTML
    assert "recognitionProvider.disabled=!geminiPrimary" in TEST_UI_HTML
    assert "recognition_provider:recognitionProvider.value" in TEST_UI_HTML
    assert "'/api/codex/login'" in TEST_UI_HTML
    assert "body:JSON.stringify({force})" in TEST_UI_HTML
    assert "codex.available?'Đăng nhập lại Codex':'Đăng nhập Codex'" in TEST_UI_HTML
    assert ".codex-login{align-self:flex-start;width:auto!important" in TEST_UI_HTML
    assert "'/api/gemini/key'" in TEST_UI_HTML
    assert "'/api/gemini/backup-key'" in TEST_UI_HTML
    assert "'/api/gemini/key-slot'" in TEST_UI_HTML
    assert 'id="geminiKeyBtn"' in TEST_UI_HTML
    assert 'id="geminiBackupKeyBtn"' in TEST_UI_HTML
    assert 'id="geminiBackupApiKeyInput" type="password"' in TEST_UI_HTML
    assert 'id="useGeminiBackupBtn"' in TEST_UI_HTML
    assert 'id="useGeminiPrimaryBtn"' in TEST_UI_HTML
    assert 'id="settingsBtn"' in TEST_UI_HTML
    assert 'id="settingsPanel"' in TEST_UI_HTML
    assert "function syncSettingsHint()" in TEST_UI_HTML
    assert "AI Gemini chưa bật trên gateway (đang dùng OCR cục bộ)." in TEST_UI_HTML
    assert 'className=\'settings-empty-hint\'' in TEST_UI_HTML
    assert "function clearSessionToken()" in TEST_UI_HTML
    assert '.settings-btn::after{content:"Cài đặt"' in TEST_UI_HTML
    assert "Đăng nhập để mở cài đặt" in TEST_UI_HTML
    assert 'id="geminiApiKeyInput" type="password"' in TEST_UI_HTML
    assert 'id="geminiKeyStatus"' in TEST_UI_HTML
    assert "ĐỔI GEMINI KEY THÀNH CÔNG" in TEST_UI_HTML


def test_ui_redirects_expired_session_without_showing_save_zero_retry() -> None:
    assert "function redirectToLogin(" in TEST_UI_HTML
    assert "function loginReturnPath(" in TEST_UI_HTML
    assert "error.code='authentication_required'" in TEST_UI_HTML
    assert "if(failed&&isAuthenticationRequired(failed.error))" in TEST_UI_HTML
    assert "Phiên đăng nhập đã hết hạn. Đang mở trang đăng nhập" in TEST_UI_HTML
    assert "window.open('about:blank'" not in TEST_UI_HTML
    assert "BACKEND ĐANG DÙNG OCR LOCAL" in TEST_UI_HTML


def test_gemini_key_store_uses_supabase_legacy_compatible_action() -> None:
    source = Path(test_ui_module.__file__).read_text(encoding="utf-8")
    assert 'secret_name=f"gemini-api-key:{args.gateway_id}"' in source
    assert 'secret_name=f"gemini-api-key-backup:{args.gateway_id}"' in source
    assert 'secret_action="codex-auth"' in source


def test_frozen_ui_does_not_auto_load_workspace_yolo_model(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    model = tmp_path / "models" / "qr_demo_synthetic.pt"
    model.parent.mkdir()
    model.write_bytes(b"test")
    monkeypatch.setattr(test_ui_module.sys, "frozen", True, raising=False)

    assert test_ui_module.build_parser().parse_args([]).yolo_model is None


def test_bound_capture_is_idempotent_and_keeps_analysis_id(tmp_path, monkeypatch) -> None:
    class FakeOCRSource:
        def __init__(self, *args, reader=None, **kwargs):
            self._reader = reader or object()

        def capture(self, frame):
            return WeightReading(1.15, "kg", True, "OCR: 1.15@0.96", 0.96)

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        gateway_id="gateway-test",
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
    )
    frame = make_qr_frame("ROLL-BOUND-001")
    event_id = str(uuid.uuid4())
    analysis = service.analyze(
        frame,
        "0.4,0.7,0.6,0.9",
        "kg",
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    kwargs = dict(
        event_id=event_id,
        analysis_id=str(analysis["analysis_id"]),
        station_id="station-01",
        camera_id="camera-01",
        frame_sha256=str(analysis["frame_sha256"]),
    )
    staged_core = service.stage_evidence_step(
        frame,
        event_id=event_id,
        station_id="station-01",
        kind="core",
        weight=1.15,
        unit="kg",
    )
    staged_product = service.stage_evidence_step(
        frame,
        event_id=event_id,
        station_id="station-01",
        kind="product",
        weight=21.15,
        unit="kg",
        qr_code="ROLL-BOUND-001",
    )
    first = service.capture(
        "ROLL-BOUND-001",
        1.15,
        "kg",
        frame,
        True,
        "OCR",
        product_frame=frame,
        product_weight=21.15,
        **kwargs,
    )
    retry = service.capture("ROLL-BOUND-001", 1.15, "kg", frame, True, "OCR", **kwargs)
    row = store.get(event_id)
    service.close()
    store.close()

    assert first["duplicate"] is False
    assert retry["duplicate"] is True
    assert first["event_id"] == retry["event_id"] == event_id
    assert first["analysis_id"] == analysis["analysis_id"]
    assert first["station_id"] == "station-01"
    assert first["camera_id"] == "camera-01"
    assert first["frame_sha256"] == analysis["frame_sha256"]
    assert row is not None and row.captured_at == analysis["captured_at"]
    assert not Path(str(staged_core["image_path"])).exists()
    assert not Path(str(staged_product["image_path"])).exists()
    assert not Path(str(staged_product["metadata_path"])).exists()


def test_bound_capture_survives_service_restart_before_product_save(
    tmp_path, monkeypatch
) -> None:
    class FakeOCRSource:
        def __init__(self, *args, reader=None, **kwargs):
            self._reader = reader or object()

        def capture(self, frame):
            return WeightReading(1.15, "kg", True, "OCR: 1.15@0.96", 0.96)

    monkeypatch.setattr(test_ui_module, "CameraOCRWeightSource", FakeOCRSource)
    database = tmp_path / "measurements.db"
    captures = tmp_path / "captures"
    frame = make_qr_frame("ROLL-RESTART-001")
    event_id = str(uuid.uuid4())

    first_store = MeasurementStore(database, captures)
    first_service = StationUIService(
        first_store,
        None,
        None,
        None,
        gateway_id="gateway-test",
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
    )
    analysis = first_service.analyze(
        frame,
        "0.4,0.7,0.6,0.9",
        "kg",
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    first_service.close()
    first_store.close()

    restarted_store = MeasurementStore(database, captures)
    restarted_service = StationUIService(
        restarted_store,
        None,
        None,
        None,
        gateway_id="gateway-test",
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
    )
    result = restarted_service.capture(
        "ROLL-RESTART-001",
        1.15,
        "kg",
        frame,
        True,
        "OCR",
        product_frame=frame,
        product_weight=21.15,
        event_id=event_id,
        analysis_id=str(analysis["analysis_id"]),
        station_id="station-01",
        camera_id="camera-01",
        frame_sha256=str(analysis["frame_sha256"]),
    )
    row = restarted_store.get(event_id)
    restarted_service.close()
    restarted_store.close()

    assert result["ok"] is True
    assert result["event_id"] == event_id
    assert result["analysis_id"] == analysis["analysis_id"]
    assert row is not None and row.product_weight == 21.15


def test_discard_session_removes_transient_step_evidence(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=1,
        station_ids=["station-01"],
        camera_ids=["camera-01"],
    )
    event_id = str(uuid.uuid4())
    frame = make_qr_frame("ROLL-DISCARD-001")
    service.sessions.stage(
        frame,
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    staged = service.stage_evidence_step(
        frame,
        event_id=event_id,
        station_id="station-01",
        kind="core",
        weight=13.04,
        unit="kg",
    )

    assert service.discard_session("station-01", event_id=event_id) is True
    service.close()
    store.close()
    assert not Path(str(staged["image_path"])).exists()
    assert not Path(str(staged["metadata_path"])).exists()


def test_service_rejects_duplicate_logical_camera_ids(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    with pytest.raises(ValueError, match="camera_id values must be unique"):
        StationUIService(
            store,
            None,
            None,
            None,
            station_count=2,
            camera_ids=["camera-same", "camera-same"],
        )
    store.close()
