import json
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np
import pytest
import qrcode

from roll_qr_scale import test_ui


@pytest.fixture
def recovery_server(tmp_path, monkeypatch):
    monkeypatch.setattr(test_ui, "_ingest_api_url", lambda: "")
    monkeypatch.setattr(test_ui, "_supabase_project_url", lambda: "")
    server, service = test_ui.create_server(test_ui.build_parser().parse_args([
        "--db", str(tmp_path / "measurements.db"),
        "--captures", str(tmp_path / "captures"), "--yolo-model", "",
        "--weight-engine", "local", "--no-auto-sync", "--port", "0",
    ]))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address

    def post(path, body):
        request = urllib.request.Request(
            f"http://{host}:{port}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    yield service, post
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    if service.sync_worker is not None:
        service.sync_worker.stop()
    service.close()
    service.store.close()


def qr_frame(value):
    return np.asarray(qrcode.make(value).convert("RGB"))[:, :, ::-1].copy()


def test_saved_qr_recovery_uses_the_capture_decoder_and_only_updates_its_event(recovery_server, monkeypatch):
    service, post = recovery_server
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event_id, other_id = str(uuid.uuid4()), str(uuid.uuid4())
    product = qr_frame("SP_123")
    service.capture("", None, "kg", frame, product_frame=product, product_weight=7.5, event_id=event_id)
    service.capture("OTHER_123", 0.4, "kg", frame, product_frame=frame, product_weight=8, event_id=other_id)
    original = service.store.get(event_id)
    images = [Path(original.image_path).read_bytes(), Path(original.product_image_path).read_bytes()]
    assert original.weight == 0 and "CORE_AUTO_ZERO=1" in original.weight_raw
    assert "ERROR_STATUS=error" in original.weight_raw
    assert service._decode_qr(product)["qr_code"] == "SP_123"
    monkeypatch.setattr(service, "analyze", lambda *_args, **_kwargs: pytest.fail("QR reread must not run weight AI"))
    result = post("/api/measurements/reread", {"event_id": event_id, "kind": "qr"})
    saved = service.store.get(event_id)
    assert result["read_qr_code"] == "SP_123"
    assert saved.qr_code == "SP_123" and saved.weight == 0 and saved.product_weight == 7.5
    assert "ERROR_STATUS=ok" in saved.weight_raw
    assert [Path(saved.image_path).read_bytes(), Path(saved.product_image_path).read_bytes()] == images
    assert service.store.get(other_id).qr_code == "OTHER_123"
    assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 2


def test_manual_edit_preserves_images_metadata_and_one_row(recovery_server):
    service, post = recovery_server
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    service.capture("", None, "kg", frame, product_frame=frame, event_id=event_id,
                    weight_raw="PRODUCT_WEIGHT=unread; SOURCE_BI=0.25; WEIGH_ROUND=2; SOURCE_DATE=2026-10-14; SOURCE_SHIFT=12C1; SOURCE_MACHINE=M1; SOURCE_PRODUCTION_ORDER=LSX-1")
    before = service.store.get(event_id)
    images = [Path(before.image_path).read_bytes(), Path(before.product_image_path).read_bytes()]
    result = post("/api/measurements/update", {
        "event_id": event_id, "qr_code": "SP_123", "core_weight": 0.4, "product_weight": 7.5,
        "work_date": "2026-10-14", "shift": "12C1", "machine": "M1", "production_order": "LSX-1",
        "error_status": "ok",
    })
    saved = service.store.get(event_id)
    assert result["local_updated"] is True
    assert saved.id == before.id and saved.captured_at == before.captured_at
    assert saved.qr_code == "SP_123" and saved.weight == 0.4 and saved.product_weight == 7.5
    for tag in ("SOURCE_BI=0.25", "WEIGH_ROUND=2", "SOURCE_PRODUCTION_ORDER=LSX-1", "CORE_AUTO_ZERO=0", "ERROR_STATUS=ok", "HUMAN_CONFIRMED_CORE=0.4"):
        assert tag in saved.weight_raw
    assert [Path(saved.image_path).read_bytes(), Path(saved.product_image_path).read_bytes()] == images
    assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 1


@pytest.mark.parametrize("values", [
    {"product_weight": ""}, {"product_weight": None}, {"product_weight": float("nan")},
    {"core_weight": float("inf")}, {"core_weight": -1}, {"core_weight": 10}, {"qr_code": ""},
])
def test_manual_invalid_values_do_not_modify_the_saved_ticket(recovery_server, values):
    service, post = recovery_server
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    service.capture("ORIGINAL_123", 0.4, "kg", frame, product_frame=frame, product_weight=7.5, event_id=event_id)
    with pytest.raises(urllib.error.HTTPError) as error:
        post("/api/measurements/update", {"event_id": event_id, "qr_code": "SP_123", "core_weight": 0.4, "product_weight": 7.5, **values})
    assert error.value.code == 422
    saved = service.store.get(event_id)
    assert saved.qr_code == "ORIGINAL_123" and saved.weight == 0.4 and saved.product_weight == 7.5


def test_separate_weight_and_qr_retries_promote_the_same_photo_pair(recovery_server, monkeypatch):
    service, post = recovery_server
    event_id = str(uuid.uuid4())
    captures = {}
    for kind, frame in (("core", np.zeros((120, 160, 3), dtype=np.uint8)), ("product", qr_frame("SP_123"))):
        capture_id = str(uuid.uuid4())
        captures[kind], _ = service.store.save_photo_draft_idempotent(
            frame, event_id=capture_id, parent_event_id=event_id, capture_kind=kind,
        )
    calls = []

    def analyze(_frame, *_args, **kwargs):
        calls.append(kwargs["capture_kind"])
        return {"weight_found": kwargs["capture_kind"] == "product", "weight": 7.5}

    monkeypatch.setattr(service, "analyze", analyze)
    assert post("/api/measurements/retry-error", {"event_id": event_id, "only": "core"})["core_weight"] == 0
    assert post("/api/measurements/retry-error", {"event_id": event_id, "only": "product"})["promoted"] is False
    result = post("/api/measurements/retry-error", {"event_id": event_id, "only": "qr"})
    assert result["promoted"] is True and result["qr_code"] == "SP_123"
    assert calls == ["core", "product"]
    saved = service.store.get(event_id)
    assert saved.weight == 0 and saved.product_weight == 7.5
    assert Path(saved.product_image_path).is_file()
    assert len(test_ui._local_production_items(service.store, 10)) == 1


def test_failed_core_reread_does_not_erase_a_valid_previous_weight(recovery_server, monkeypatch):
    service, post = recovery_server
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    service.capture("SP_123", 0.4, "kg", frame, product_frame=frame, product_weight=7.5, event_id=event_id)
    monkeypatch.setattr(service, "analyze", lambda *_args, **_kwargs: {"weight_found": False})
    with pytest.raises(urllib.error.HTTPError) as error:
        post("/api/measurements/reread", {"event_id": event_id, "kind": "core"})
    assert error.value.code == 422
    assert service.store.get(event_id).weight == 0.4


def test_cloud_update_failure_keeps_manual_correction_and_flags_resync(recovery_server, monkeypatch):
    service, post = recovery_server
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    event_id = str(uuid.uuid4())
    service.capture("SP_OLD", 0.4, "kg", frame, product_frame=frame, product_weight=7.5, event_id=event_id)
    service.store.mark_synced(event_id)
    monkeypatch.setattr(test_ui, "_ingest_api_url", lambda: "https://example.test/ingest")
    monkeypatch.setattr(test_ui, "_ingest_api_token", lambda: "test-only-token")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("test cloud unavailable")

    monkeypatch.setattr(test_ui, "mutate_remote_measurement", unavailable)
    result = post("/api/measurements/update", {
        "event_id": event_id, "qr_code": "SP_123", "core_weight": 0.5, "product_weight": 7.6,
    })
    saved = service.store.get(event_id)
    assert result["local_updated"] is True and result["cloud_updated"] is False
    assert result["cloud_error"] == "test cloud unavailable"
    assert saved.qr_code == "SP_123" and saved.weight == 0.5 and saved.product_weight == 7.6
    assert saved.sync_status == "failed" and saved.sync_error == "test cloud unavailable"


def test_draft_recovery_prefers_product_qr_over_core_qr(recovery_server, monkeypatch):
    service, post = recovery_server
    event_id = str(uuid.uuid4())
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    for kind, code in (("core", "CORE_OLD"), ("product", "SP_123")):
        service.store.save_photo_draft_idempotent(
            frame, event_id=str(uuid.uuid4()), parent_event_id=event_id, capture_kind=kind, qr_code=code,
        )
    monkeypatch.setattr(service, "analyze", lambda *_args, **kwargs: {
        "weight_found": True, "weight": 0.4 if kwargs["capture_kind"] == "core" else 7.5,
    })
    result = post("/api/measurements/retry-error", {"event_id": event_id})
    assert result["promoted"] is True
    assert service.store.get(event_id).qr_code == "SP_123"
