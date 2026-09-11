import base64
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pytest

from roll_qr_scale.api_client import post_measurement
from roll_qr_scale.storage import MeasurementStore
from roll_qr_scale.sync import OutboxSyncWorker


def test_outbox_syncs_committed_measurement(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-OUTBOX-001",
        125.4,
        "kg",
        np.zeros((80, 100, 3), dtype=np.uint8),
        "serial",
        needs_sync=True,
        gateway_id="gateway-row",
        station_id="station-01",
        camera_id="camera-1",
        analysis_id="analysis-1",
    )
    sent: list[tuple] = []

    def fake_send(url, payload, image_path, token, qr_image_path=None):
        sent.append((url, payload, image_path, token, qr_image_path))
        return {
            "ok": True,
            "event_id": measurement.event_id,
            "id": 99,
            "image_url": "https://res.cloudinary.com/demo/image/upload/event.jpg",
            "image_public_id": "roll-captures/station-01/event",
        }

    worker = OutboxSyncWorker(
        store,
        "https://example.test/ingest",
        "device-secret",
        "station-01",
        send=fake_send,
    )
    assert worker.sync_once() == 1
    saved = store.get(measurement.event_id)
    store.close()

    assert saved is not None
    assert saved.sync_status == "synced"
    assert saved.remote_id == 99
    assert saved.remote_image_url == "https://res.cloudinary.com/demo/image/upload/event.jpg"
    assert saved.remote_image_public_id == "roll-captures/station-01/event"
    assert sent[0][1]["gateway_id"] == "gateway-row"
    assert sent[0][1]["device_id"] == "gateway-row"
    assert sent[0][1]["station_id"] == "station-01"
    assert sent[0][1]["camera_id"] == "camera-1"
    assert sent[0][1]["analysis_id"] == "analysis-1"
    assert len(sent[0][1]["frame_sha256"]) == 64
    assert len(sent[0][1]["payload_hash"]) == 64
    assert sent[0][1]["qr_code"] == "ROLL-OUTBOX-001"
    assert "image_path" not in sent[0][1]


def test_outbox_accepts_core_image_ack_and_persists_it(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-CORE-IMAGE-001",
        1.0,
        "kg",
        np.zeros((20, 20, 3), dtype=np.uint8),
        "camera-gemini:test-ui",
        needs_sync=True,
    )

    def fake_send(*args):
        return {
            "ok": True,
            "event_id": measurement.event_id,
            "id": 101,
            "core_image_url": "https://images.example/core.jpg",
            "core_image_public_id": "roll-captures/core-weight/event",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    assert worker.sync_once() == 1
    saved = store.get(measurement.event_id)
    store.close()

    assert saved is not None
    assert saved.remote_image_url == "https://images.example/core.jpg"
    assert saved.remote_image_public_id == "roll-captures/core-weight/event"


def test_outbox_syncs_inventory_check_to_parallel_workflow(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    check, _ = store.save_inventory_check_idempotent(
        "SP-INVENTORY-SYNC",
        8.25,
        0.4,
        0.16,
        "kg",
        np.zeros((40, 60, 3), dtype=np.uint8),
        "camera-gemini:inventory",
        needs_sync=True,
        event_id="3b673ed9-333c-4cab-a85b-a7987c452d80",
        gateway_id="gateway-row",
        station_id="station-01",
        camera_id="camera-01",
        analysis_id="analysis-inventory",
    )
    sent: list[dict[str, object]] = []

    def fake_send(url, payload, image_path, token):
        sent.append(dict(payload))
        return {
            "ok": True,
            "event_id": check.event_id,
            "id": 700,
            "image_url": "https://images.example/inventory.jpg",
            "image_public_id": "roll-captures/inventory-check/event",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    assert worker.sync_inventory_event(check.event_id) is True
    saved = store.get_inventory_check(check.event_id)

    assert saved is not None
    assert saved.sync_status == "synced"
    assert saved.remote_id == 700
    assert sent[0]["workflow"] == "inventory_check"
    assert sent[0]["product_code"] == "SP-INVENTORY-SYNC"
    assert sent[0]["core_weight"] == pytest.approx(0.4)
    assert sent[0]["tare_weight"] == pytest.approx(0.16)
    store.close()


def test_outbox_syncs_photo_draft_without_weight_fields(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    draft, _ = store.save_photo_draft_idempotent(
        np.zeros((40, 60, 3), dtype=np.uint8),
        qr_code="QR-PHOTO-ONLY",
        qr_source="camera:zxing",
        needs_sync=True,
        event_id="2ab71440-c330-41e8-9682-c940debf74d1",
        gateway_id="gateway-row",
        station_id="station-01",
        camera_id="camera-01",
    )
    sent: list[dict[str, object]] = []

    def fake_send(url, payload, image_path, token):
        sent.append(dict(payload))
        return {
            "ok": True,
            "event_id": draft.event_id,
            "id": 701,
            "image_url": "https://images.example/photo-draft.jpg",
            "image_public_id": "roll-captures/photo-draft/event",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    assert worker.sync_photo_draft_event(draft.event_id) is True
    saved = store.get_photo_draft(draft.event_id)

    assert saved is not None and saved.sync_status == "synced"
    assert sent[0]["workflow"] == "photo_draft"
    assert sent[0]["status"] == "awaiting_ai"
    assert sent[0]["qr_code"] == "QR-PHOTO-ONLY"
    assert "weight" not in sent[0]
    assert "unit" not in sent[0]
    store.close()


def test_outbox_requires_product_image_ack_for_two_image_event(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-TWO-IMAGES-001",
        1.04,
        "kg",
        np.zeros((40, 60, 3), dtype=np.uint8),
        "camera-gemini:test-ui",
        needs_sync=True,
        qr_source="camera-product:zxing",
    )
    store.attach_product_weight(measurement.event_id, 13.04)
    product_frame = np.full((50, 70, 3), 240, dtype=np.uint8)
    store.attach_product_image(measurement.event_id, product_frame)
    measurement = store.get(measurement.event_id)
    assert measurement is not None
    sent_product_images: list[bytes] = []

    def fake_send(url, payload, image_path, token):
        sent_product_images.append(base64.b64decode(payload["product_image_base64"]))
        return {
            "ok": True,
            "event_id": measurement.event_id,
            "id": 202,
            "core_image_url": "https://images.example/core.jpg",
            "core_image_public_id": "roll-captures/core-weight/event",
            "product_image_url": "https://images.example/product.jpg",
            "product_image_public_id": "roll-captures/product-weight/event",
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    assert worker.sync_once() == 1
    saved = store.get(measurement.event_id)

    assert sent_product_images == [
        Path(measurement.product_image_path).read_bytes()
    ]
    assert saved is not None
    assert saved.sync_status == "synced"
    store.close()


def test_outbox_keeps_failed_event_for_retry(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-RETRY-001",
        75,
        "kg",
        np.zeros((40, 40, 3), dtype=np.uint8),
        "manual",
        needs_sync=True,
    )

    def fail(*args):
        raise OSError("network offline")

    worker = OutboxSyncWorker(store, "https://offline.test", "token", "station-01", send=fail)
    assert worker.sync_once() == 0
    saved = store.get(measurement.event_id)
    assert saved is not None
    assert saved.sync_status == "failed"
    assert saved.retry_count == 1
    assert store.pending_count() == 1
    store.close()


def test_background_worker_includes_failed_events_for_scheduled_retry(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    worker = OutboxSyncWorker(store, "https://example.test", "token", interval=0.01)
    called = threading.Event()
    retry_flags: list[bool] = []

    def observe(*args, **kwargs):
        retry_flags.append(bool(kwargs.get("retry_failed")))
        called.set()
        return 0

    worker.sync_once = observe  # type: ignore[method-assign]
    worker.start()
    assert called.wait(1.0)
    worker.stop()
    store.close()

    assert retry_flags and retry_flags[0] is True


def test_backup_maintenance_is_opt_in_and_records_daily_result(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    calls: list[tuple[str, str]] = []

    def maintain(url, token):
        calls.append((url, token))
        return {"ok": True, "verified": 3, "cloudinary_deleted": 2}

    worker = OutboxSyncWorker(
        store,
        "https://example.test",
        "token",
        maintenance_enabled=True,
        maintenance_interval=86400,
        maintenance=maintain,
    )

    assert worker.run_maintenance() is True
    status = worker.maintenance_status()
    assert calls == [("https://example.test", "token")]
    assert status["enabled"] is True
    assert status["last_success"] is not None
    assert status["last_error"] is None
    assert status["result"]["cloudinary_deleted"] == 2
    store.close()


def test_backup_maintenance_runs_immediately_when_worker_starts(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    called = threading.Event()

    def maintain(url, token):
        called.set()
        return {"ok": True}

    worker = OutboxSyncWorker(
        store,
        "https://example.test",
        "token",
        interval=0.01,
        maintenance_enabled=True,
        maintenance=maintain,
    )
    worker.start()
    assert called.wait(1.0)
    worker.stop()
    store.close()


def test_backup_maintenance_sends_local_checksum_and_prunes_after_release(tmp_path) -> None:
    now = datetime.now(timezone.utc)
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-RETENTION-SYNC",
        2.5,
        "kg",
        np.zeros((24, 24, 3), dtype=np.uint8),
        "manual",
        needs_sync=True,
        event_id="33333333-3333-4333-8333-333333333333",
        captured_at=(now - timedelta(days=8)).isoformat(),
    )
    store.mark_synced(
        measurement.event_id,
        301,
        "https://res.cloudinary.com/demo/retention.jpg",
        "retention",
    )
    reports: list[dict[str, object]] = []

    def maintain(url, token, report):
        reports.append(report)
        item = report["items"][0]
        return {
            "ok": True,
            "released": [
                {
                    "table": item["table"],
                    "event_id": item["event_id"],
                    "role": "core",
                    "sha256": item["roles"]["core"]["sha256"],
                }
            ],
        }

    worker = OutboxSyncWorker(
        store,
        "https://example.test",
        "token",
        maintenance_enabled=True,
        maintenance=maintain,
    )
    assert worker.run_maintenance() is True
    assert reports and reports[0]["provider"] == "render_persistent_disk"
    assert reports[0]["items"][0]["roles"]["core"]["bytes"] > 0
    assert not Path(measurement.image_path).exists()
    assert store.get(measurement.event_id) is not None
    status = worker.maintenance_status()
    assert status["result"]["local_prune"]["deleted"] == 1
    store.close()


@pytest.mark.parametrize(
    "response_factory",
    [
        lambda event_id: {"ok": False, "event_id": event_id},
        lambda event_id: {"ok": True, "event_id": "different-event", "id": 1},
        lambda event_id: {"event_id": event_id},
        lambda event_id: {"ok": True, "event_id": event_id},
        lambda event_id: {"ok": True, "event_id": event_id, "id": 0},
        lambda event_id: {"ok": True, "event_id": event_id, "id": 1},
    ],
)
def test_outbox_does_not_mark_unacknowledged_event_synced(tmp_path, response_factory) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-ACK-001",
        22,
        "kg",
        np.zeros((20, 20, 3), dtype=np.uint8),
        "manual",
        needs_sync=True,
    )

    def fake_send(*args):
        return response_factory(measurement.event_id)

    worker = OutboxSyncWorker(store, "https://example.test", "token", "legacy-gateway", send=fake_send)
    assert worker.sync_once() == 0
    saved = store.get(measurement.event_id)
    assert saved is not None
    assert saved.sync_status == "failed"
    assert saved.retry_count == 1
    store.close()


def test_outbox_can_allow_legacy_ack_without_image_when_explicitly_configured(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-LEGACY-ACK",
        3,
        "kg",
        np.zeros((20, 20, 3), dtype=np.uint8),
        "manual",
        needs_sync=True,
    )

    def fake_send(*args):
        return {
            "ok": True,
            "event_id": measurement.event_id,
            "id": "7",
            "local_backup_committed": True,
        }

    worker = OutboxSyncWorker(
        store,
        "https://example.test",
        "token",
        "legacy-gateway",
        send=fake_send,
        require_remote_image=False,
    )
    assert worker.sync_once() == 1
    saved = store.get(measurement.event_id)
    assert saved is not None
    assert saved.sync_status == "synced"
    assert saved.remote_id == 7
    store.close()


def test_outbox_keeps_local_ack_cloudinary_pending_for_retry(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    measurement = store.save(
        "ROLL-CLOUDINARY-PENDING",
        3,
        "kg",
        np.zeros((20, 20, 3), dtype=np.uint8),
        "manual",
        needs_sync=True,
    )

    def fake_send(*args):
        return {
            "ok": True,
            "event_id": measurement.event_id,
            "id": 9,
            "local_backup_committed": True,
            "cloudinary_pending": True,
        }

    worker = OutboxSyncWorker(store, "https://example.test", "token", send=fake_send)
    assert worker.sync_once() == 1
    saved = store.get(measurement.event_id)
    assert saved is not None
    assert saved.sync_status == "synced"
    assert saved.sync_error == "cloudinary_pending"
    assert store.pending_count() == 1
    store.close()


def test_http_client_sends_image_and_device_token(tmp_path) -> None:
    received: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["content-length"])
            received["token"] = self.headers["x-device-token"]
            received["body"] = json.loads(self.rfile.read(length))
            response = json.dumps(
                {"ok": True, "event_id": "test-event", "id": 321}
            ).encode()
            self.send_response(201)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    image_path = tmp_path / "capture.jpg"
    image_path.write_bytes(b"\xff\xd8test-jpeg\xff\xd9")
    product_image = b"\xff\xd8test-product-jpeg\xff\xd9"
    try:
        response = post_measurement(
            f"http://127.0.0.1:{server.server_port}/ingest",
            {
                "event_id": "test-event",
                "qr_code": "ROLL-HTTP-001",
                "product_image_base64": base64.b64encode(product_image).decode("ascii"),
                "product_weight": 13.04,
            },
            image_path,
            "secret-token",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response["id"] == 321
    assert received["token"] == "secret-token"
    assert base64.b64decode(received["body"]["image_base64"]) == image_path.read_bytes()
    assert received["body"]["image_role"] == "core_weight"
    assert base64.b64decode(received["body"]["product_image_base64"]) == product_image
    assert received["body"]["product_weight"] == pytest.approx(13.04)
