import base64
import threading
import time
import uuid
from pathlib import Path

import cv2
import numpy as np
import pytest
import qrcode

import roll_qr_scale.test_ui as test_ui_module
from roll_qr_scale.scale import WeightReading
from roll_qr_scale.station_session import AnalysisBindingMismatch
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


@pytest.mark.parametrize(
    ("shift", "machine", "expected"),
    [
        ("HC1", "MÁY BAO BÌ 16", 16),
        ("HC1", "Máy cách nhiệt 11", 30),
        ("HC1", "May cach-nhiet 11", 30),
        ("Ca chuẩn Đà Nẵng", "Máy cách nhiệt 11", 10),
    ],
)
def test_weigh_batch_limit_per_machine(shift: str, machine: str, expected: int) -> None:
    assert test_ui_module._max_weigh_batch_size(shift, machine) == expected


def test_weigh_batch_can_be_confirmed_and_printed_from_local_db(tmp_path) -> None:
    import json
    import urllib.request

    args = test_ui_module.build_parser().parse_args([
        "--db", str(tmp_path / "measurements.db"),
        "--captures", str(tmp_path / "captures"),
        "--yolo-model", "", "--weight-engine", "local", "--port", "0",
    ])
    server, service = test_ui_module.create_server(args)
    measurement = service.store.save(
        "SP_001", 0.82, "kg", np.zeros((80, 120, 3), dtype=np.uint8),
        "manual", weight_raw=(
            "SOURCE_DATE=2026-09-25; SOURCE_SHIFT=HC1; "
            "SOURCE_MACHINE=Máy 1; SOURCE_PRODUCTION_ORDER=LSX-1; "
            "PRODUCT_WEIGHT=5.92"
        ),
    )
    service.store.attach_product_weight(measurement.event_id, 5.92)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = urllib.request.Request(
            base + "/api/weighing-batches/confirm",
            data=json.dumps({
                "work_date": "2026-09-25", "shift": "HC1", "machine": "Máy 1",
                "production_order": "LSX-1", "milestone": 10, "batch_size": 10,
            }).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request) as response:
            confirmed = json.load(response)
        with urllib.request.urlopen(
            base + "/api/weighing-batches?work_date=2026-09-25&shift=HC1"
            "&machine=M%C3%A1y%201&production_order=LSX-1"
        ) as response:
            listed = json.load(response)
        assert confirmed["item"]["sync_status"] in {"local", "pending"}
        assert confirmed["item"]["so_luong"] == 1
        assert listed["source"] == "local"
        assert listed["items"][0]["danh_sach_san_pham"][0]["event_id"] == measurement.event_id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        service.close()
        service.store.close()


def test_analyze_accepts_fourth_weighing_round(tmp_path, monkeypatch) -> None:
    import json
    import urllib.error
    import urllib.request

    server, service = test_ui_module.create_server(
        test_ui_module.build_parser().parse_args(
            ["--db", str(tmp_path / "measurements.db"), "--captures", str(tmp_path / "captures"),
             "--yolo-model", "", "--port", "0"]
        )
    )
    analyzed = []

    def fake_analyze(*args, **kwargs):
        analyzed.append(kwargs)
        return {"weight_found": False, "quality_pass": False, "weight_raw": ""}

    monkeypatch.setattr(service, "analyze", fake_analyze)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    image = image_data_url(np.full((200, 300, 3), 255, dtype=np.uint8))

    def request(round_index):
        return urllib.request.Request(
            f"http://{host}:{port}/api/analyze",
            data=json.dumps({"image": image, "capture_kind": "core", "capture_round": round_index}).encode(),
            headers={"Content-Type": "application/json"},
        )

    try:
        with urllib.request.urlopen(request(3)) as response:
            assert response.status == 200
        assert len(analyzed) == 1
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request(4))
        assert error.value.code == 422
        assert len(analyzed) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()


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


def test_ai_failures_are_saved_as_independent_photo_drafts() -> None:
    assert "#photoOnlyBtn,#factoryBtn,#inventoryPhoneBtn{display:none!important}" in TEST_UI_HTML
    assert "'/api/photo-capture'" in TEST_UI_HTML
    assert "function saveMeasurementRound(" in TEST_UI_HTML
    assert "saveCapture=saveValidatedCapture" in TEST_UI_HTML
    assert "round.eventId=newEventId()" in TEST_UI_HTML
    assert "round&&!round.saved&&roundReadyToSave(session,index)" in TEST_UI_HTML
    assert "async function persistAiMissPhoto(" in TEST_UI_HTML
    assert "ẢNH ĐÃ ĐƯỢC LƯU ĐỘC LẬP" in TEST_UI_HTML
    assert "Nhấn Enter để lưu ảnh với số trống" not in TEST_UI_HTML
    assert "row.classList.add('photo-draft-row')" in TEST_UI_HTML
    assert "async function persistInventoryAiMissPhoto(" in TEST_UI_HTML
    assert "capture_kind:'inventory'" in TEST_UI_HTML


def test_ui_offers_antigravity_as_third_ai_provider() -> None:
    assert "new Option('Antigravity · Google','antigravity')" in TEST_UI_HTML
    assert "'/api/antigravity/login'" in TEST_UI_HTML
    assert "'/api/antigravity/login/check'" in TEST_UI_HTML
    assert "ANTIGRAVITY ĐÃ ĐĂNG NHẬP" in TEST_UI_HTML
    assert "'/api/antigravity/usage'" in TEST_UI_HTML


def test_ui_hides_quota_meters_and_does_not_poll_them() -> None:
    assert ".gemini-quota-meter,.antigravity-quota-meter{display:none!important}" in TEST_UI_HTML
    assert "setInterval(refreshGeminiQuota" not in TEST_UI_HTML
    assert "setInterval(refreshAntigravityQuota" not in TEST_UI_HTML


def test_ui_can_temporarily_analyze_an_uploaded_scale_image() -> None:
    assert "button.id='testImageBtn'" in TEST_UI_HTML
    assert "button.id='inventoryTestImageBtn'" in TEST_UI_HTML
    assert "async function loadLocalTestImage(file)" in TEST_UI_HTML
    assert "await analyzeCurrent(captureSlot(session).kind)" in TEST_UI_HTML
    assert "if(!sourceReady(session)){await openDefaultCamera(session)" in TEST_UI_HTML


def test_expired_ai_analysis_falls_back_to_durable_browser_images() -> None:
    assert "function isExpiredAnalysisFailure(error)" in TEST_UI_HTML
    assert "(không tồn tại|hết hạn)" in TEST_UI_HTML
    assert "if(isExpiredAnalysisFailure(error))" in TEST_UI_HTML
    assert "tiếp tục lưu từ ảnh trình duyệt" in TEST_UI_HTML
    assert "captureBodyForRound(session,round,index,false)" in TEST_UI_HTML


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


def test_ui_capture_saves_two_error_rounds_with_four_images_and_unreadable_weights(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    event_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    try:
        for index, event_id in enumerate(event_ids, start=1):
            result = service.capture(
                f"ROLL-ERROR-{index}",
                0.0,
                "kg",
                frame,
                weight_raw=(
                    "CORE_MISSING=1; PRODUCT_WEIGHT=unread; "
                    "ERROR_STATUS=error; ERROR_REASON=AI không đọc được số cân"
                ),
                event_id=event_id,
                product_frame=frame,
            )
            assert result["event_id"] == event_id
            saved = store.get(event_id)
            assert saved is not None
            assert Path(saved.image_path).is_file()
            assert Path(saved.product_image_path).is_file()
            assert "PHOTO_QUALITY_OVERRIDE=1" in saved.weight_raw
            assert "ERROR_STATUS=error" in saved.weight_raw
            assert "ERROR_REASON=AI không đọc được số cân" in saved.weight_raw
        assert store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 2
    finally:
        service.close()
        store.close()


def test_ui_capture_auto_marks_unreadable_weights_as_error(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    try:
        result = service.capture(
            "ROLL-ERROR", None, "kg", frame,
            weight_raw="PRODUCT_WEIGHT=unread", product_frame=frame,
        )
        saved = store.get(result["event_id"])
        assert saved is not None
        assert saved.weight is None
        assert saved.product_weight is None
        assert "ERROR_STATUS=error" in saved.weight_raw
        assert "ERROR_REASON=AI không đọc được cân lõi và cân sản phẩm" in saved.weight_raw
        assert "PHOTO_QUALITY_OVERRIDE=1" in saved.weight_raw
        assert store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 1
    finally:
        service.close()
        store.close()


def test_ui_capture_saves_documented_ai_failure_with_one_photo(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    try:
        result = service.capture(
            "ROLL-AI-MISS",
            None,
            "kg",
            frame,
            event_id=event_id,
            weight_raw=(
                "CORE_MISSING=1; PRODUCT_WEIGHT=unread; "
                "ERROR_STATUS=error; ERROR_REASON=AI không đọc được số cân"
            ),
        )
        saved = store.get(event_id)
        assert result["event_id"] == event_id
        assert saved is not None
        assert saved.weight is None
        assert saved.product_weight is None
        assert Path(saved.image_path).is_file()
        assert not saved.product_image_path
        assert "PHOTO_QUALITY_OVERRIDE=1" in saved.weight_raw
    finally:
        service.close()
        store.close()


def test_ui_capture_without_qr_or_weights_creates_official_local_ticket(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    try:
        result = service.capture(
            "", None, "kg", frame, event_id=event_id,
            weight_raw="PRODUCT_WEIGHT=unread",
        )
        saved = store.get(event_id)
        assert result["event_id"] == event_id
        assert result["qr_code"] == ""
        assert saved is not None
        assert saved.qr_code == ""
        assert saved.weight is None and saved.product_weight is None
        assert saved.qr_source == "none"
        assert saved.sync_status == "local"
        assert Path(saved.image_path).is_file()
        assert not saved.product_image_path
        assert "ERROR_STATUS=error" in saved.weight_raw
        assert "AI không đọc được cân lõi và cân sản phẩm" in saved.weight_raw
        assert "Chưa nhận diện được mã QR" in saved.weight_raw
        assert store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 1
        assert store.connection.execute("SELECT COUNT(*) FROM photo_drafts").fetchone()[0] == 0
    finally:
        service.close()
        store.close()


def test_frontend_saves_photo_backed_rounds_in_separate_requests() -> None:
    assert "Lưu phần đã đủ" in TEST_UI_HTML
    assert "function savableRoundIndexes(session)" in TEST_UI_HTML
    assert "round&&!round.saved&&roundHasPhoto(round)" in TEST_UI_HTML
    assert "for(const index of indexes)" in TEST_UI_HTML
    assert "event_id:round.eventId" in TEST_UI_HTML
    assert "product_weight:productValue" in TEST_UI_HTML
    assert "Bấm Lưu phần đã đủ để thử lại đúng event_id" in TEST_UI_HTML
    assert "if(!weightsReady(session)){status(captureStatus,'Cần đủ" not in TEST_UI_HTML


def test_ui_save_returns_before_background_upload_of_complete_event(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    sent: list[tuple[dict[str, object], bytes]] = []
    send_started = threading.Event()
    release_send = threading.Event()

    def fake_send(url, payload, image_path, token):
        sent.append((dict(payload), Path(image_path).read_bytes()))
        send_started.set()
        if not release_send.wait(5):
            raise TimeoutError("test upload was not released")
        return {
            "ok": True,
            "event_id": payload["event_id"],
            "id": 501,
            "image_url": "https://images.example/evidence.jpg",
            "image_public_id": "roll-captures/event",
            "product_image_url": "https://images.example/product.jpg",
            "product_image_public_id": "roll-captures/product",
        }

    worker = OutboxSyncWorker(
        store,
        "https://example.test/ingest",
        "device-token",
        "gateway-test",
        send=fake_send,
    )
    service = StationUIService(store, worker, None, None)
    worker.start()
    try:
        frame = make_qr_frame("EVIDENCE-QR")
        result = service.capture(
            "PRODUCT-ENTRY-001",
            7.08,
            "kg",
            frame,
            product_frame=frame,
            product_weight=8.12,
        )
        assert result["sync_status"] == "pending"
        assert result["remote_id"] is None
        assert send_started.wait(3)
        assert store.get(str(result["event_id"])).sync_status == "pending"
        release_send.set()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            saved = store.get(str(result["event_id"]))
            if saved is not None and saved.sync_status == "synced":
                break
            time.sleep(0.01)
        assert saved is not None and saved.sync_status == "synced"
        assert saved.remote_id == 501
        assert len(sent) == 1
        assert sent[0][0]["event_id"] == result["event_id"]
        assert sent[0][0]["qr_code"] == "PRODUCT-ENTRY-001"
        assert sent[0][0]["weight"] == pytest.approx(7.08)
        assert sent[0][0]["product_image_base64"]
        assert sent[0][1].startswith(b"\xff\xd8")
    finally:
        release_send.set()
        worker.stop()
        service.close()
        store.close()


def test_ui_save_retries_cloud_failure_from_durable_outbox(tmp_path) -> None:
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
    assert result["sync_status"] == "pending"
    assert saved is not None and saved.sync_status == "pending"
    assert worker.sync_once() == 0
    failed = store.get(str(result["event_id"]))
    assert failed is not None and failed.sync_status == "failed"
    assert "network unavailable" in str(failed.sync_error)
    worker.send = lambda url, payload, image_path, token: {
        "ok": True,
        "event_id": payload["event_id"],
        "id": 502,
        "image_url": "https://images.example/retried.jpg",
        "image_public_id": "roll-captures/retried",
    }
    assert worker.sync_once(include_deferred=True) == 1
    retried = store.get(str(result["event_id"]))
    service.close()
    store.close()
    assert result["pending_count"] == 1
    assert saved is not None
    assert saved.qr_code == "PRODUCT-OFFLINE-001"
    assert saved.weight == pytest.approx(13.04)
    assert Path(saved.image_path).is_file()
    assert retried is not None and retried.sync_status == "synced"
    assert retried.remote_id == 502


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


def test_ui_inventory_capture_queues_cloud_upload(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    sent: list[dict[str, object]] = []

    def fake_send(url, payload, image_path, token):
        sent.append(dict(payload))
        return {
            "ok": True,
            "event_id": payload["event_id"],
            "id": 702,
            "image_url": "https://images.example/inventory.jpg",
            "image_public_id": "roll-captures/inventory",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    service = StationUIService(store, worker, None, None)
    result = service.capture_inventory(
        "SP-KIEM-KHO-BACKGROUND",
        12.75,
        0.5,
        0.16,
        "kg",
        make_qr_frame("INVENTORY-BACKGROUND"),
    )
    assert result["sync_status"] == "pending"
    assert sent == []
    assert worker.sync_once() == 1
    saved = store.get_inventory_check(str(result["event_id"]))
    assert saved is not None and saved.sync_status == "synced"
    assert sent[0]["workflow"] == "inventory_check"
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
    assert result["sync_status"] == "pending"
    assert result["event_id"] == parent_event_id
    assert result["capture_id"] == capture_id
    assert result["capture_kind"] == "product"
    assert result["capture_round"] == 1
    assert saved is not None and saved.status == "awaiting_ai"
    assert saved.parent_event_id == parent_event_id
    assert store.count() == 0
    assert worker.sync_once() == 1
    assert sent[0]["workflow"] == "photo_draft"
    assert sent[0]["parent_event_id"] == parent_event_id
    assert store.get_photo_draft(capture_id).sync_status == "synced"
    service.close()
    store.close()


def test_ui_photo_capture_survives_local_qr_decoder_failure(tmp_path, monkeypatch) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    def failed_qr(_frame):
        raise RuntimeError("QR decoder unavailable")
    monkeypatch.setattr(service, "_decode_qr", failed_qr)
    capture_id = "db9c7561-658f-4f9e-99fc-beb38f469a45"
    result = service.capture_photo_draft(
        make_qr_frame("QR-PHOTO-BACKUP"),
        event_id=capture_id,
        parent_event_id="73558b23-20b3-4590-96d5-67fe50e21390",
        capture_kind="core",
        capture_round=0,
        station_id="station-01",
        camera_id="camera-01",
    )
    saved = store.get_photo_draft(capture_id)
    assert result["ok"] is True
    assert result["ai_requested"] is False
    assert result["qr_code"] == ""
    assert saved is not None
    assert Path(saved.image_path).is_file()
    service.close()
    store.close()


def test_reread_saved_core_photo_keeps_incomplete_row_as_error(tmp_path, monkeypatch) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    parent_id = str(uuid.uuid4())
    capture_id = str(uuid.uuid4())
    store.save_photo_draft_idempotent(
        np.zeros((80, 120, 3), dtype=np.uint8),
        event_id=capture_id, parent_event_id=parent_id, capture_kind="core",
    )
    monkeypatch.setattr(service, "analyze", lambda *_args, **_kwargs: {
        "weight_found": True, "weight": 0.16,
    })

    result = service.reread_photo_drafts(parent_id)
    items = test_ui_module._local_production_items(store, 10)

    assert result["promoted"] is False
    assert result["core_weight"] == pytest.approx(0.16)
    assert store.get(parent_id) is None
    assert items[0]["core_weight"] == pytest.approx(0.16)
    assert items[0]["error_status"] == "error"
    assert "Chưa có ảnh sản phẩm" in items[0]["error_reason"]
    service.close()
    store.close()


def test_reread_weight_stays_bound_to_the_photo_that_was_read() -> None:
    parent_id = str(uuid.uuid4())
    rows = [
        {"event_id": str(uuid.uuid4()), "parent_event_id": parent_id,
         "capture_kind": "core", "captured_at": "2026-09-25T10:00:00Z",
         "image_url": "https://example.test/old.jpg", "reread_weight": 0.16},
        {"event_id": str(uuid.uuid4()), "parent_event_id": parent_id,
         "capture_kind": "core", "captured_at": "2026-09-25T10:01:00Z",
         "image_url": "https://example.test/new.jpg", "reread_weight": None},
    ]

    item = test_ui_module._photo_draft_display_items(rows)[0]

    assert item["core_image_url"] == "https://example.test/new.jpg"
    assert item["core_weight"] == "unread"


def test_reread_saved_photo_pair_promotes_one_measurement(tmp_path, monkeypatch) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    parent_id = str(uuid.uuid4())
    for kind, qr in (("core", ""), ("product", "SP-001")):
        store.save_photo_draft_idempotent(
            np.zeros((80, 120, 3), dtype=np.uint8),
            event_id=str(uuid.uuid4()), parent_event_id=parent_id,
            capture_kind=kind, qr_code=qr,
        )
    monkeypatch.setattr(service, "analyze", lambda *_args, **kwargs: {
        "weight_found": True,
        "weight": 0.16 if kwargs["capture_kind"] == "core" else 0.40,
    })

    result = service.reread_photo_drafts(parent_id)
    saved = store.get(parent_id)
    items = test_ui_module._local_production_items(store, 10)

    assert result["promoted"] is True
    assert saved is not None
    assert saved.weight == pytest.approx(0.16)
    assert saved.product_weight == pytest.approx(0.40)
    assert Path(saved.product_image_path).is_file()
    assert len(items) == 1 and not items[0].get("error_only")
    service.close()
    store.close()


def test_reread_error_measurement_fills_both_missing_weights(tmp_path, monkeypatch) -> None:
    import json
    import urllib.error
    import urllib.request

    server, service = test_ui_module.create_server(
        test_ui_module.build_parser().parse_args([
            "--db", str(tmp_path / "measurements.db"),
            "--captures", str(tmp_path / "captures"),
            "--yolo-model", "", "--port", "0",
        ])
    )
    event_id = str(uuid.uuid4())
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    service.capture(
        "SP-001", None, "kg", frame, True,
        "PRODUCT_WEIGHT=unread", product_frame=frame,
        event_id=event_id,
    )
    monkeypatch.setattr(service, "analyze", lambda *_args, **kwargs: {
        "weight_found": True,
        "weight": 0.16 if kwargs["capture_kind"] == "core" else 0.40,
    })
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        for kind in ("core", "product"):
            request = urllib.request.Request(
                f"http://{host}:{port}/api/measurements/reread",
                data=json.dumps({"event_id": event_id, "kind": kind}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request) as response:
                    assert response.status == 200
            except urllib.error.HTTPError as exc:
                pytest.fail(f"{kind}: {exc.read().decode()}")
        saved = service.store.get(event_id)
        assert saved is not None
        assert saved.weight == pytest.approx(0.16)
        assert saved.product_weight == pytest.approx(0.40)
        assert "ERROR_STATUS=ok" in saved.weight_raw
        assert "REREAD_CORE=0.16" in saved.weight_raw
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()


def test_reread_error_photo_endpoint_returns_partial_result(tmp_path, monkeypatch) -> None:
    import json
    import urllib.request

    server, service = test_ui_module.create_server(
        test_ui_module.build_parser().parse_args([
            "--db", str(tmp_path / "measurements.db"),
            "--captures", str(tmp_path / "captures"),
            "--yolo-model", "", "--port", "0",
        ])
    )
    parent_id = str(uuid.uuid4())
    service.store.save_photo_draft_idempotent(
        np.zeros((80, 120, 3), dtype=np.uint8),
        event_id=str(uuid.uuid4()), parent_event_id=parent_id,
        capture_kind="core",
    )
    monkeypatch.setattr(service, "analyze", lambda *_args, **_kwargs: {
        "weight_found": True, "weight": 0.16,
    })
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        request = urllib.request.Request(
            f"http://{host}:{port}/api/measurements/retry-error",
            data=json.dumps({"event_id": parent_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read())
        assert result["ok"] is True
        assert result["promoted"] is False
        assert result["core_weight"] == pytest.approx(0.16)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()


def test_ui_inventory_ai_miss_photo_is_saved_without_weight(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    capture_id = "64bd5e7b-8718-494e-b4be-94f9ca23739f"
    parent_id = "493a44f5-7330-4507-9773-4837d49be7e4"

    result = service.capture_photo_draft(
        make_qr_frame("INVENTORY-MISS"),
        event_id=capture_id,
        parent_event_id=parent_id,
        capture_kind="inventory",
        station_id="station-01",
        camera_id="camera-01",
    )

    saved = store.get_photo_draft(capture_id)
    assert result["capture_kind"] == "inventory"
    assert saved is not None and Path(saved.image_path).is_file()
    assert store.inventory_pending_count() == 0
    service.close()
    store.close()


def test_each_camera_keeps_identity_while_allowing_operator_machine(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=2,
        station_ids=["station-01", "station-02"],
        camera_ids=["camera-01", "camera-02"],
        machine_ids=["Máy tái chế", "Máy cách nhiệt"],
    )

    assert service.validate_station_source(
        "station-01", "camera-01", "Máy tái chế"
    )["machine_id"] == "Máy tái chế"
    stale = service.validate_station_source(
        "station-01", "camera-01", "Máy cách nhiệt"
    )
    assert stale["machine_id"] == "Máy cách nhiệt"
    assert stale["machine_overridden"] is True
    with pytest.raises(ValueError, match="Trạm hoặc camera không hợp lệ"):
        service.validate_station_source("station-01", "camera-02", "Máy tái chế")
    assert "input.disabled=Boolean(locked)" not in TEST_UI_HTML
    assert "input.disabled=false;return SOURCE_MACHINES" in TEST_UI_HTML
    assert "machine:sanitizeMachine($('sourceMachine').value)" in TEST_UI_HTML
    assert "machine:session.machineId||sourceContext.machine" not in TEST_UI_HTML
    assert "Camera vật lý này đã gắn với máy khác" in TEST_UI_HTML
    assert "Hệ thống không tự đổi sang camera khác" in TEST_UI_HTML
    assert "const machineChanged=lockSourceMachine(session)" in TEST_UI_HTML

    service.close()
    store.close()


def test_each_computer_can_be_persistently_pinned_to_one_station() -> None:
    assert "STATION_ASSIGNMENT_KEY='rollQrScale.stationAssignment.v1'" in TEST_UI_HTML
    assert "new URLSearchParams(location.search).get('station')" in TEST_UI_HTML
    assert "localStorage.setItem(STATION_ASSIGNMENT_KEY,requested)" in TEST_UI_HTML
    assert "buildStations=configs=>buildStationsBase(assignedStationConfigs(configs))" in TEST_UI_HTML
    assert "list.filter(config=>String(config.station_id||'')===assignedStationId)" in TEST_UI_HTML
    assert "auto.disabled=true" in TEST_UI_HTML
    assert "Không thể tự nhảy sang trạm khác" in TEST_UI_HTML


def test_capture_accepts_machine_from_save_endpoint_and_persists_source(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=2,
        station_ids=["station-01", "station-02"],
        camera_ids=["camera-01", "camera-02"],
        machine_ids=["Máy tái chế", "Máy cách nhiệt"],
    )

    result = service.capture(
        "MT-MN008_TEST",
        1.02,
        "kg",
        make_qr_frame("MT-MN008_TEST"),
        station_id="station-01",
        camera_id="camera-01",
        machine="Máy tái chế",
    )
    saved = store.get(str(result["event_id"]))

    assert result["ok"] is True
    assert saved is not None
    assert "SOURCE_MACHINE=Máy tái chế" in saved.weight_raw
    service.close()
    store.close()


def test_capture_canonicalizes_to_operator_selected_machine_before_save(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=2,
        station_ids=["station-01", "station-02"],
        camera_ids=["camera-01", "camera-02"],
        machine_ids=["Máy tái chế", "Máy cách nhiệt"],
    )

    result = service.capture(
        "MT-MN005_STALE",
        1.02,
        "kg",
        make_qr_frame("MT-MN005_STALE"),
        weight_raw="SOURCE_MACHINE=Máy tái chế; HUMAN_CONFIRMED=1.02",
        station_id="station-01",
        camera_id="camera-01",
        machine="Máy cách nhiệt",
    )
    saved = store.get(str(result["event_id"]))

    assert result["ok"] is True
    assert saved is not None
    assert "SOURCE_MACHINE=Máy cách nhiệt" in saved.weight_raw
    assert "SOURCE_MACHINE=Máy tái chế" not in saved.weight_raw
    service.close()
    store.close()


def test_photo_draft_keeps_operator_selected_machine(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=2,
        station_ids=["station-01", "station-02"],
        camera_ids=["camera-01", "camera-02"],
        machine_ids=["Máy tái chế", "Máy cách nhiệt"],
    )
    capture_id = str(uuid.uuid4())

    service.capture_photo_draft(
        make_qr_frame("MT-MN005-DRAFT"),
        event_id=capture_id,
        station_id="station-01",
        camera_id="camera-01",
        machine="Máy cách nhiệt",
    )
    saved = store.get_photo_draft(capture_id)

    assert saved is not None
    assert saved.machine == "Máy cách nhiệt"
    service.close()
    store.close()


def test_inventory_canonicalizes_to_operator_selected_machine(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store,
        None,
        None,
        None,
        station_count=2,
        station_ids=["station-01", "station-02"],
        camera_ids=["camera-01", "camera-02"],
        machine_ids=["Máy tái chế", "Máy cách nhiệt"],
    )

    frame = make_qr_frame("MT-MN005-INVENTORY")
    event_id = str(uuid.uuid4())
    binding = service.sessions.stage(
        frame,
        event_id=event_id,
        station_id="station-01",
        camera_id="camera-01",
    )
    binding = service.sessions.mark_ready(binding.analysis_id)

    result = service.capture_inventory(
        "MT-MN005-INVENTORY",
        6.86,
        1.02,
        0.16,
        "kg",
        frame,
        weight_raw="SOURCE_MACHINE=Máy tái chế",
        event_id=event_id,
        analysis_id=binding.analysis_id,
        station_id="station-01",
        camera_id="camera-01",
        machine="Máy cách nhiệt",
        frame_sha256=binding.frame_sha256,
    )
    saved = store.get_inventory_check(str(result["event_id"]))

    assert saved is not None
    assert "SOURCE_MACHINE=Máy cách nhiệt" in saved.weight_raw
    assert "SOURCE_MACHINE=Máy tái chế" not in saved.weight_raw
    service.close()
    store.close()


def test_shift_codes_route_to_separate_gemini_key_slots() -> None:
    assert StationUIService._gemini_slot_for_shift("12C1") == "day"
    assert StationUIService._gemini_slot_for_shift("12C2") == "night"
    assert StationUIService._gemini_slot_for_shift("HC3") == "night"


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


def test_strict_discard_keeps_a_newer_binding(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None)
    binding = service.sessions.stage(
        make_qr_frame("QR-STRICT-DISCARD"),
        event_id=str(uuid.uuid4()),
        station_id="station-01",
        camera_id="camera-01",
    )

    with pytest.raises(AnalysisBindingMismatch):
        service.discard_session(
            "station-01", event_id=str(uuid.uuid4()), strict_event_id=True
        )

    assert service.sessions.statuses()[0]["event_id"] == binding.event_id
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


def test_render_capture_sends_scale_head_crop_to_gemini(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def __init__(self):
            self.shape = None

        def read(self, frames, *, unit):
            assert len(frames) == 1
            self.shape = frames[0].shape[:2]
            assert 150 < self.shape[0] < 600
            assert 200 < self.shape[1] < 800
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
    assert result["gemini_crop_applied"] is True
    assert result["gemini_attempts"] == 1
    assert result["gemini_fallback_used"] is False
    assert result["roi_method"] == "gemini-scale-head-zoom-red-led"


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
    assert reader.shapes[0][0] < 600
    assert reader.shapes[0][1] < 800
    assert reader.shapes[1][0] > reader.shapes[0][0]
    assert reader.shapes[1][1] > reader.shapes[0][1]
    assert result["weight"] == pytest.approx(13.04)
    assert result["gemini_attempts"] == 2
    assert result["gemini_fallback_used"] is True
    assert result["gemini_latency_seconds"] == pytest.approx(0.5)
    assert result["gemini_input_tokens"] == 300
    assert result["gemini_output_tokens"] == 30
    assert result["gemini_total_tokens"] == 330
    assert result["gemini_crop_applied"] is True
    assert result["roi_method"] == "gemini-scale-head-zoom-red-led+full-frame-retry"
    assert "SCALE HEAD ATTEMPT" in result["weight_raw"]
    assert "FULL FRAME RETRY" in result["weight_raw"]


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


def test_temporary_gemini_failures_do_not_quarantine_either_key(tmp_path, monkeypatch) -> None:
    class Reader:
        def __init__(self, recover=False):
            self.calls = 0
            self.recover = recover

        def read(self, frames, *, unit):
            self.calls += 1
            if self.recover and self.calls > 1:
                return GeminiWeightSuggestion(1.04, unit, True, True, "GEMINI:ok", 0.1)
            return GeminiWeightSuggestion(
                None, unit, False, False, "GEMINI ERROR: 504 DEADLINE_EXCEEDED", 30.0,
                transient_error=True,
            )

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    monkeypatch.setattr(test_ui_module, "detect_weight_roi", lambda frame: None)
    day, night = Reader(recover=True), Reader()
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None, gemini_reader=day,
        gemini_night_readers=(night, None, None, None), weight_engine="gemini")
    frame = np.full((600, 800, 3), 180, dtype=np.uint8)
    try:
        first = service.analyze(frame, "auto", "kg", capture_kind="core")
        assert first["weight_found"] is False
        assert not service._gemini_failed_slots
        second = service.analyze(frame, "auto", "kg", capture_kind="core")
        assert second["weight"] == pytest.approx(1.04)
        assert day.calls == 2 and night.calls == 1
    finally:
        service.close()
        store.close()


def test_gemini_crop_retry_stays_on_healthy_fallback_key(tmp_path, monkeypatch) -> None:
    class FakeGeminiReader:
        def __init__(self, responses):
            self.responses = responses
            self.calls = 0

        def read(self, frames, *, unit):
            result = self.responses[self.calls]
            self.calls += 1
            return GeminiWeightSuggestion(
                result,
                unit,
                result is not None,
                not isinstance(result, str),
                result if isinstance(result, str) else "GEMINI_FULL:weight-unreadable",
                0.2,
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
    failed = FakeGeminiReader(["GEMINI ERROR: timeout"])
    healthy = FakeGeminiReader([None, 13.04])
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store, None, None, None,
        gemini_reader=failed,
        gemini_night_readers=(healthy, None, None, None),
        weight_engine="gemini",
    )

    result = service.analyze(
        np.full((600, 800, 3), 180, dtype=np.uint8),
        "auto", "kg", capture_kind="core",
    )

    service.close()
    store.close()
    assert failed.calls == 1
    assert healthy.calls == 2
    assert result["weight"] == pytest.approx(13.04)
    assert result["gemini_attempts"] == 3
    assert result["gemini_fallback_used"] is True


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
    assert status["recognition_profiles"]["default"] == "fast"


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
    assert '<h1 class="brand-title">Ghi nhận lần cân</h1>' in TEST_UI_HTML
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
    assert 'MÁY CÁCH NHIỆT 11' in TEST_UI_HTML
    assert 'MÁY BAO BÌ 11' in TEST_UI_HTML
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


def test_local_measurement_items_find_older_filtered_rows_after_200_newer_rows(
    tmp_path,
) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    with store._lock:
        for index in range(210):
            old = index < 10
            store.connection.execute(
                """INSERT INTO measurements
                   (event_id, qr_code, weight, unit, captured_at, image_path,
                    weight_source, weight_raw, sync_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"event-{index}",
                    f"{'OLD' if old else 'NEW'}-{index}",
                    1.0,
                    "kg",
                    "2026-08-01T12:00:00+00:00"
                    if old
                    else "2026-09-23T12:00:00+00:00",
                    "",
                    "manual",
                    "SOURCE_DATE=2026-08-01"
                    if old
                    else "SOURCE_DATE=2026-09-23",
                    "synced",
                ),
            )
        store.connection.commit()
    try:
        items = test_ui_module._local_measurement_items(
            store, 50, work_date="2026-08-01", qr_code="OLD"
        )
        assert len(items) == 10
        assert all(str(item["qr_code"]).startswith("OLD-") for item in items)
        assert len(test_ui_module._local_measurement_event_ids(store, qr_code="OLD")) == 10
    finally:
        store.close()


def test_supabase_table_window_fetches_more_than_one_remote_page(monkeypatch) -> None:
    offsets = []

    def fake_table(url, key, *, limit, offset, **filters):
        offsets.append((offset, limit))
        return [{"event_id": f"remote-{index}"} for index in range(offset, offset + limit)]

    monkeypatch.setattr(test_ui_module, "fetch_supabase_table", fake_table)
    items = test_ui_module._fetch_supabase_table_paged(
        "https://example.invalid", "public-key", limit=230, offset=150
    )
    assert offsets == [(150, 200), (350, 30)]
    assert [item["event_id"] for item in items] == [
        f"remote-{index}" for index in range(150, 380)
    ]


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
    assert "data.measurement_count" in TEST_UI_HTML
    assert "data.measurement_count==null?null:Number(data.measurement_count)" in TEST_UI_HTML
    assert "local_only=1" in TEST_UI_HTML
    assert "data.error_count" in TEST_UI_HTML
    assert "ảnh AI lỗi không tính" in TEST_UI_HTML
    assert "maybePromptRollBatchConfirm" not in TEST_UI_HTML
    assert 'id="openRollBatchBtn"' in TEST_UI_HTML
    assert "ẢNH ĐÃ ĐƯỢC LƯU ĐỘC LẬP" in TEST_UI_HTML
    assert 'id="shiftCountDetail"' in TEST_UI_HTML
    assert "Theo Ngày · Ca · Máy · Lệnh sản xuất" in TEST_UI_HTML
    assert "session.captureCount+=savedNow;await loadRecords()" in TEST_UI_HTML
    assert "await loadProductionOrders(fields.date,'');await loadRecords()" in TEST_UI_HTML
    assert "persistSourceFromFields();renderControls();loadRecords()" in TEST_UI_HTML
    assert 'id="rollBatchModal"' in TEST_UI_HTML
    assert 'id="rollBatchSize"' in TEST_UI_HTML
    assert "function saveRollBatchSize()" in TEST_UI_HTML
    assert "function requestRollBatchConfirm" in TEST_UI_HTML
    assert "function confirmRollBatchCount" in TEST_UI_HTML
    assert "rollBatchConfirmActive()" in TEST_UI_HTML
    assert 'id="dismissRollBatchBtn"' in TEST_UI_HTML
    assert "function dismissRollBatchModal" in TEST_UI_HTML
    assert "không bắt buộc" in TEST_UI_HTML.lower()
    assert "function markWeightThresholdAlerts(){return null}" in TEST_UI_HTML
    assert "function coreWeightOverLimit(){return false}" in TEST_UI_HTML
    assert "function productWeightOverLimit(){return false}" in TEST_UI_HTML
    assert 'id="sourceMachine" list="sourceMachineList"' in TEST_UI_HTML
    assert "MÁY CÁCH NHIỆT 11" in TEST_UI_HTML
    assert "MÁY BAO BÌ 16" in TEST_UI_HTML
    assert "Lưu riêng cặp " not in TEST_UI_HTML
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
    monkeypatch.chdir(tmp_path)
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
    assert "$('analyzeProductBtn').disabled=panelMode||busy||!ready" in TEST_UI_HTML
    assert "$('analyzeCoreBtn').disabled=panelMode||busy||!ready||!sourceChosen" not in TEST_UI_HTML
    assert "function coreCaptured(session)" in TEST_UI_HTML
    assert "function sourceReady(session)" in TEST_UI_HTML
    assert "function coreReady(session){return true}" in TEST_UI_HTML
    assert "session._analyzeLock=false;renderControls();status(captureStatus,error.message" in TEST_UI_HTML
    assert "await api('/api/session/discard'" in TEST_UI_HTML
    assert "retryingFailedCore=!isProduct&&targetRound===0&&Boolean(session.eventId)&&!roundCoreReady(session,targetRound)" in TEST_UI_HTML
    assert "if(retryingFailedCore&&round.eventId===discardedEventId)round.eventId=null" in TEST_UI_HTML
    assert "ẢNH ĐÃ ĐƯỢC LƯU ĐỘC LẬP" in TEST_UI_HTML
    assert 'id="analyzeCoreBtn"' in TEST_UI_HTML
    assert 'id="analyzeProductBtn"' in TEST_UI_HTML
    assert 'id="productWeight"' in TEST_UI_HTML
    assert "analyzeCurrent('core')" in TEST_UI_HTML
    assert "analyzeCurrent('product')" in TEST_UI_HTML
    assert "PRODUCT_WEIGHT=" in TEST_UI_HTML
    assert "function productReady(session)" in TEST_UI_HTML
    assert "CHỜ CÂN SẢN PHẨM" in TEST_UI_HTML
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
    assert "#productionToolbar.toolbar{" in TEST_UI_HTML
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
    assert "async function waitBeforeCameraCapture(" in TEST_UI_HTML
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
    assert "if(!session.stream){await openDefaultCamera(session);if(!session.stream)return;" in TEST_UI_HTML
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
    assert "DEFAULT_WEIGH_ROUNDS=2" in TEST_UI_HTML
    assert "4 lần · 8 cân" in TEST_UI_HTML
    assert "MAX_WEIGH_ROUNDS=4" in TEST_UI_HTML
    assert "function nextCaptureStep(" in TEST_UI_HTML
    assert "function extraRoundTags(" in TEST_UI_HTML
    assert "function discardSlot(" in TEST_UI_HTML
    assert "function discardRound(" in TEST_UI_HTML
    assert "function resetWeighRound(" in TEST_UI_HTML
    assert "className='slot-discard'" in TEST_UI_HTML
    assert "Bỏ ảnh, chụp lại" in TEST_UI_HTML
    assert "dataset.discardKind=kind" in TEST_UI_HTML
    assert "dataset.discardRound=String(round)" in TEST_UI_HTML
    assert "Ô còn lại giữ nguyên" in TEST_UI_HTML
    assert "ROUND2_CORE=" in TEST_UI_HTML
    assert "evidence-round split" in TEST_UI_HTML
    assert "evidence-round split" in TEST_UI_HTML
    assert "session.eventId&&(retryingFailedCore||session.coreAnalysis&&session.analysisId)" in TEST_UI_HTML
    assert "if(targetRound===0)" in TEST_UI_HTML
    assert "capture_kind:kind,capture_round:targetRound" in TEST_UI_HTML
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
    assert 'className=\'save round-save-btn\'' in TEST_UI_HTML
    assert "saveRoundEvidence(i)" in TEST_UI_HTML
    assert 'id="paramsPark"' in TEST_UI_HTML
    assert "function selectCaptureSlot(" in TEST_UI_HTML
    assert "function captureSlot(" in TEST_UI_HTML
    assert "dataset.captureKind" in TEST_UI_HTML


def test_ui_records_error_state_and_confirms_printable_ten_roll_batches() -> None:
    assert 'id="errorStatus1"' in TEST_UI_HTML
    assert 'id="errorReason1"' in TEST_UI_HTML
    assert "ERROR_STATUS=" in TEST_UI_HTML
    assert "ERROR_REASON=" in TEST_UI_HTML
    assert "Có lỗi, hãy nhập Lý do lỗi." in TEST_UI_HTML
    assert 'id="weighBatchRecordsCard"' in TEST_UI_HTML
    assert 'id="printSheet"' in TEST_UI_HTML
    assert "function printWeighBatch" in TEST_UI_HTML
    assert "/api/weighing-batches/confirm" in TEST_UI_HTML
    assert "Đang lưu đợt cân trên máy" in TEST_UI_HTML
    assert "writeRollBatchConfirmed(0)" in TEST_UI_HTML
    assert "readRollBatchConfirmed()+rollBatchSize()" in TEST_UI_HTML


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
    assert "if(event.key==='Enter'){if(event.target.closest&&event.target.closest('button'))return;event.preventDefault();saveAllRounds()}" in TEST_UI_HTML
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
    assert args.gemini_timeout == pytest.approx(30.0)
    assert args.gemini_model == "gemini-3.5-flash-lite"
    assert args.gemini_31_model == "gemini-3.1-flash-lite"
    assert args.gemini_31_timeout == pytest.approx(30.0)
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
        "PHIẾU CÂN CÓ ẢNH · ",
        "prepareNextCapture('',session)",
        "'awaiting-code'",
        "'awaiting-weight'",
        "function completionReady(session)",
        "function sourceReady(session)",
        "function productReady(session)",
        "CHỜ CÂN SẢN PHẨM",
        'id="analyzeCoreBtn"',
        'id="analyzeProductBtn"',
        'id="productWeight"',
        "analyzeCurrent('product')",
            "Mặc định · 3.5 Flash-Lite · Free",
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
    assert "new Option('3.1 Flash-Lite · Free','flash31')" in TEST_UI_HTML
    assert "recognitionProfile.value='fast'" in TEST_UI_HTML
    assert "rollQrScale.recognitionProfile.v3" in TEST_UI_HTML
    assert '<option value="gemini">Gemini API</option>' in TEST_UI_HTML
    assert '<option value="codex">Codex · ChatGPT</option>' in TEST_UI_HTML
    assert "$('recognitionProviderOption').hidden=!primary" in TEST_UI_HTML
    assert "recognitionProvider.disabled=!geminiPrimary" in TEST_UI_HTML
    assert "recognition_provider:recognitionProvider.value" in TEST_UI_HTML
    assert "'/api/codex/login'" in TEST_UI_HTML
    assert "body:JSON.stringify({force})" in TEST_UI_HTML
    assert "codexOption.disabled=!Boolean(codex.enabled)" in TEST_UI_HTML
    assert "$('codexLoginBtn').hidden=!primary||!usingCodex" in TEST_UI_HTML
    assert "function pollLocalCodexLogin()" in TEST_UI_HTML
    assert "result.started&&!result.session_id" in TEST_UI_HTML
    assert "codex.available?'Đăng nhập lại Codex':'Đăng nhập Codex'" in TEST_UI_HTML
    assert "Bấm Đăng nhập Codex để đăng nhập hoặc cài Codex CLI." in TEST_UI_HTML
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
    assert "ĐỔI KEY CA NGÀY THÀNH CÔNG" in TEST_UI_HTML
    assert "Key ca ngày · 12C1" in TEST_UI_HTML
    assert "Key ca đêm · 12C2" in TEST_UI_HTML
    assert "shift:sourceContext.shift" in TEST_UI_HTML


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


def test_missing_analysis_binding_falls_back_to_durable_unbound_save(
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
    frame = make_qr_frame("ROLL-LOST-BINDING-001")
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
    state_path = first_service.sessions.staging_dir / ".active-bindings.json"
    first_service.close()
    first_store.close()
    state_path.unlink()

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
        "ROLL-LOST-BINDING-001",
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
    assert result["analysis_id"] == ""
    assert row is not None
    assert row.product_weight == 21.15
    assert Path(row.image_path).is_file()
    assert Path(row.product_image_path).is_file()


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


def test_measurement_pages_do_not_repeat_synced_local_rows(tmp_path, monkeypatch) -> None:
    import json
    import urllib.request

    server, service = test_ui_module.create_server(
        test_ui_module.build_parser().parse_args(
            [
                "--db",
                str(tmp_path / "measurements.db"),
                "--captures",
                str(tmp_path / "captures"),
                "--yolo-model",
                "",
                "--port",
                "0",
            ]
        )
    )
    remote = [
        {
            "event_id": f"remote-{index}",
            "qr_code": f"ROLL-{index:03d}",
            "weight": 1.0,
            "product_weight": 12.0,
            "unit": "kg",
            "captured_at": f"2026-09-23T{23 - index // 60:02d}:{59 - index % 60:02d}:00+00:00",
        }
        for index in range(150)
    ]
    with service.store._lock:
        for item in remote[:3]:
            service.store.connection.execute(
                """INSERT INTO measurements
                   (event_id, qr_code, weight, unit, captured_at, image_path,
                    weight_source, sync_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item["event_id"],
                    item["qr_code"],
                    1.0,
                    "kg",
                    item["captured_at"],
                    "",
                    "manual",
                    "synced",
                ),
            )
        service.store.connection.commit()

    calls = []

    def fake_page(url, token, *, limit, offset, **filters):
        calls.append((offset, limit))
        return remote[offset : offset + limit], len(remote)

    monkeypatch.setattr(test_ui_module, "_supabase_project_url", lambda: "")
    monkeypatch.setattr(test_ui_module, "_supabase_read_key", lambda: "")
    monkeypatch.setattr(test_ui_module, "_ingest_api_url", lambda: "https://example.invalid/ingest")
    monkeypatch.setattr(test_ui_module, "_ingest_api_token", lambda: "device-token")
    monkeypatch.setattr(test_ui_module, "fetch_remote_measurement_page", fake_page)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    def page(offset):
        with urllib.request.urlopen(
            f"http://{host}:{port}/api/measurements?limit=50&offset={offset}"
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        first = page(0)
        second = page(50)
        third = page(100)
        assert [item["event_id"] for item in first["items"]] == [
            f"remote-{index}" for index in range(50)
        ]
        assert [item["event_id"] for item in second["items"]] == [
            f"remote-{index}" for index in range(50, 100)
        ]
        assert [item["event_id"] for item in third["items"]] == [
            f"remote-{index}" for index in range(100, 150)
        ]
        assert calls == [(0, 50), (50, 50), (100, 50)]

        with service.store._lock:
            for index in range(3):
                service.store.connection.execute(
                    """INSERT INTO measurements
                       (event_id, qr_code, weight, unit, captured_at, image_path,
                        weight_source, sync_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"pending-{index}",
                        f"PENDING-{index}",
                        1.0,
                        "kg",
                        f"2026-09-23T23:59:{59 - index:02d}+00:00",
                        "",
                        "manual",
                        "pending",
                    ),
                )
            service.store.connection.commit()
        first = page(0)
        second = page(50)
        assert [item["event_id"] for item in first["items"][:3]] == [
            "pending-0", "pending-1", "pending-2"
        ]
        assert [item["event_id"] for item in second["items"]] == [
            f"remote-{index}" for index in range(47, 97)
        ]
        assert len({item["event_id"] for item in first["items"] + second["items"]}) == 100
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()
        service.store.close()


def test_capture_allows_omitted_core_weight_and_product_image_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(test_ui_module, "_supabase_project_url", lambda: "")
    monkeypatch.setattr(test_ui_module, "_supabase_read_key", lambda: "")
    monkeypatch.setattr(test_ui_module, "_ingest_api_url", lambda: "")
    monkeypatch.setattr(test_ui_module, "_ingest_api_token", lambda: "")
    import json
    import threading
    import urllib.request

    server, service = test_ui_module.create_server(
        test_ui_module.build_parser().parse_args(
            [
                "--db",
                str(tmp_path / "measurements.db"),
                "--captures",
                str(tmp_path / "captures"),
                "--yolo-model",
                "",
                "--port",
                "0",
            ]
        )
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    frame = np.zeros((600, 800, 3), dtype=np.uint8)
    encoded = image_data_url(frame)

    # Send capture without core weight or image, only product_image & product_weight
    req = urllib.request.Request(
        f"http://{host}:{port}/api/capture",
        data=json.dumps(
            {
                "qr_code": "",
                "product_weight": 7.5,
                "unit": "kg",
                "product_image": encoded,
                "work_date": "2026-09-22",
                "shift": "12C1",
                "machine": "MÁY BAO BÌ 11",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        assert res["ok"] is True
        assert res["weight"] is None
        assert res["qr_code"] == ""

    # Verify that GET /api/measurements immediately returns this local record
    list_req = urllib.request.Request(f"http://{host}:{port}/api/measurements?limit=50&work_date=2026-09-22")
    with urllib.request.urlopen(list_req) as resp:
        list_res = json.loads(resp.read().decode("utf-8"))
        assert list_res["ok"] is True
        assert len(list_res["items"]) >= 1
        item = next(i for i in list_res["items"] if i["event_id"] == res["event_id"])
        assert item["core_weight"] is None
        assert item["product_weight"] == 7.5
        assert item["error_status"] == "error"
        assert "Chưa nhận diện được mã QR" in item["error_reason"]
        assert item["has_core_image"] is False
        assert item["has_product_image"] is True

    local_req = urllib.request.Request(
        f"http://{host}:{port}/api/measurements?limit=50&work_date=2026-09-22&local_only=1"
    )
    with urllib.request.urlopen(local_req) as resp:
        local_res = json.loads(resp.read().decode("utf-8"))
        assert local_res["source"] == "local"
        assert any(i["event_id"] == res["event_id"] for i in local_res["items"])

    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)
    if service.sync_worker is not None:
        service.sync_worker.stop()
    service.close()
