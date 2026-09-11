import hashlib
import sqlite3
from pathlib import Path

import numpy as np
import pytest

from roll_qr_scale.storage import EventIdConflictError, MeasurementStore


def test_saves_measurement_and_evidence_image(tmp_path) -> None:
    db_path = tmp_path / "measurements.db"
    store = MeasurementStore(db_path, tmp_path / "captures")
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    result = store.save("ROLL-001", 81.25, "kg", frame, "manual")
    store.close()

    assert result.id == 1
    assert result.qr_code == "ROLL-001"
    assert result.weight == 81.25
    assert result.sync_status == "local"
    assert len(result.frame_sha256) == 64
    assert len(result.payload_hash) == 64
    assert len(list((tmp_path / "captures").glob("*.jpg"))) == 1
    assert result.frame_sha256 == hashlib.sha256(Path(result.image_path).read_bytes()).hexdigest()

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT qr_code, weight, unit, weight_source, qr_source FROM measurements"
        ).fetchone()
    assert row == ("ROLL-001", 81.25, "kg", "manual", "camera")


def test_photo_draft_saves_image_without_weight_or_required_qr(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    event_id = "d037931d-089d-44ce-96c5-53d41a95c933"
    draft, duplicate = store.save_photo_draft_idempotent(
        np.zeros((80, 120, 3), dtype=np.uint8),
        event_id=event_id,
        parent_event_id="a5a53a31-3b46-484e-b111-59735657bed7",
        capture_kind="product",
        capture_round=1,
        needs_sync=True,
        gateway_id="gateway-test",
        station_id="station-01",
        camera_id="camera-01",
    )
    again, is_duplicate = store.save_photo_draft_idempotent(
        np.zeros((80, 120, 3), dtype=np.uint8),
        event_id=event_id,
        parent_event_id="a5a53a31-3b46-484e-b111-59735657bed7",
        capture_kind="product",
        capture_round=1,
        needs_sync=True,
        gateway_id="gateway-test",
        station_id="station-01",
        camera_id="camera-01",
    )
    sibling, sibling_duplicate = store.save_photo_draft_idempotent(
        np.full((80, 120, 3), 20, dtype=np.uint8),
        event_id="d7a3f837-20be-43e4-aad1-0ae6c4e6bccf",
        parent_event_id="a5a53a31-3b46-484e-b111-59735657bed7",
        capture_kind="core",
        capture_round=1,
        needs_sync=True,
        gateway_id="gateway-test",
        station_id="station-01",
        camera_id="camera-01",
    )

    columns = {
        str(row["name"])
        for row in store.connection.execute("PRAGMA table_info(photo_drafts)").fetchall()
    }
    assert duplicate is False
    assert is_duplicate is True
    assert again == draft
    assert draft.qr_code == ""
    assert draft.parent_event_id == "a5a53a31-3b46-484e-b111-59735657bed7"
    assert draft.capture_kind == "product"
    assert draft.capture_round == 1
    assert sibling_duplicate is False
    assert sibling.parent_event_id == draft.parent_event_id
    assert store.connection.execute(
        "SELECT COUNT(*) FROM photo_drafts WHERE parent_event_id = ?",
        (draft.parent_event_id,),
    ).fetchone()[0] == 2
    source_rows = store.photo_draft_source_rows()
    assert {row["event_id"] for row in source_rows} == {draft.event_id, sibling.event_id}
    assert {row["parent_event_id"] for row in source_rows} == {draft.parent_event_id}
    assert draft.status == "awaiting_ai"
    assert draft.sync_status == "pending"
    assert "weight" not in columns
    assert "unit" not in columns
    assert Path(draft.image_path).is_file()
    store.close()


def test_delete_photo_drafts_removes_every_image_row_for_parent(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    parent_id = "a5a53a31-3b46-484e-b111-59735657bed7"
    for index, kind in enumerate(("core", "product")):
        store.save_photo_draft_idempotent(
            np.full((32, 48, 3), index, dtype=np.uint8),
            event_id=f"d037931d-089d-44ce-96c5-53d41a95c9{index:02d}",
            parent_event_id=parent_id,
            capture_kind=kind,
            needs_sync=True,
            gateway_id="gateway-test",
        )
    store.save_photo_draft_idempotent(
        np.zeros((32, 48, 3), dtype=np.uint8),
        event_id="d7a3f837-20be-43e4-aad1-0ae6c4e6bccf",
        parent_event_id="other-parent",
        needs_sync=True,
        gateway_id="gateway-test",
    )

    assert store.delete_photo_drafts(parent_id) == 2
    assert {row["parent_event_id"] for row in store.photo_draft_source_rows()} == {
        "other-parent"
    }
    assert store.delete_photo_drafts(parent_id) == 0
    store.close()


def test_idempotent_save_persists_capture_identity_and_returns_duplicate(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    frame = np.full((32, 48, 3), 17, dtype=np.uint8)
    kwargs = {
        "event_id": "capture-event-001",
        "captured_at": "2026-08-02T05:06:07.123+00:00",
        "gateway_id": "gateway-a",
        "station_id": "station-a",
        "camera_id": "camera-2",
        "analysis_id": "analysis-abc",
    }

    first = store.save_idempotent("ROLL-002", 44.5, "kg", frame, "ocr", **kwargs)
    second = store.save_idempotent("ROLL-002", 44.5, "kg", frame, "ocr", **kwargs)

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.existing == first.measurement
    assert store.count() == 1
    assert len(list((tmp_path / "captures").glob("*.jpg"))) == 1
    assert first.measurement.event_id == "capture-event-001"
    assert first.measurement.captured_at == "2026-08-02T05:06:07.123+00:00"
    assert first.measurement.gateway_id == "gateway-a"
    assert first.measurement.station_id == "station-a"
    assert first.measurement.camera_id == "camera-2"
    assert first.measurement.analysis_id == "analysis-abc"
    store.close()


def test_save_keeps_core_and_product_images_in_one_measurement(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    core_frame = np.full((64, 96, 3), 30, dtype=np.uint8)
    product_frame = np.full((80, 120, 3), 220, dtype=np.uint8)

    saved = store.save(
        "PRODUCT-WITH-EVIDENCE-IMAGE",
        1.04,
        "kg",
        core_frame,
        "camera-gemini:test-ui",
        qr_source="camera-product:zxing",
    )
    store.attach_product_weight(saved.event_id, 13.04)
    store.attach_product_image(saved.event_id, product_frame)
    saved = store.get(saved.event_id)

    assert saved is not None
    assert Path(saved.image_path).is_file()
    assert Path(saved.product_image_path).is_file()
    assert saved.image_path != saved.product_image_path
    assert saved.product_weight == pytest.approx(13.04)
    assert len(saved.payload_hash) == 64
    payload = saved.api_payload()
    assert payload["product_weight"] == pytest.approx(13.04)
    assert "product_image_path" not in payload
    store.close()


def test_idempotent_save_rejects_reused_event_id_with_changed_payload(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    frame = np.zeros((24, 24, 3), dtype=np.uint8)
    common = {
        "event_id": "capture-event-conflict",
        "captured_at": "2026-08-02T05:06:07Z",
        "gateway_id": "gateway-a",
        "station_id": "station-a",
        "camera_id": "camera-1",
        "analysis_id": "analysis-1",
    }
    store.save_idempotent("ROLL-003", 10.0, "kg", frame, "ocr", **common)

    with pytest.raises(EventIdConflictError):
        store.save_idempotent("ROLL-003", 10.1, "kg", frame, "ocr", **common)

    assert store.count() == 1
    assert len(list((tmp_path / "captures").glob("*.jpg"))) == 1
    store.close()


def test_existing_database_is_upgraded_without_losing_rows(tmp_path) -> None:
    db_path = tmp_path / "legacy.db"
    capture_dir = tmp_path / "captures"
    capture_dir.mkdir()
    image_path = capture_dir / "legacy.jpg"
    image_path.write_bytes(b"legacy-jpeg-evidence")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                qr_code TEXT NOT NULL,
                weight REAL NOT NULL,
                unit TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image_path TEXT NOT NULL,
                weight_source TEXT NOT NULL,
                sync_status TEXT NOT NULL DEFAULT 'local'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO measurements (
                event_id, qr_code, weight, unit, captured_at, image_path,
                weight_source, sync_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-event",
                "ROLL-LEGACY",
                9.5,
                "kg",
                "2026-08-01T00:00:00Z",
                str(image_path),
                "manual",
                "local",
            ),
        )

    store = MeasurementStore(db_path, capture_dir)
    legacy = store.get("legacy-event")
    assert legacy is not None
    assert legacy.qr_code == "ROLL-LEGACY"
    assert legacy.gateway_id == ""
    assert legacy.frame_sha256 == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert len(legacy.payload_hash) == 64
    assert store.count() == 1
    store.close()


def test_inventory_check_is_idempotent_and_keeps_one_image(tmp_path) -> None:
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    frame = np.full((64, 96, 3), 80, dtype=np.uint8)
    kwargs = {
        "event_id": "7d66d135-7cb0-4f24-8931-2d1c994113f1",
        "captured_at": "2026-08-19T08:00:00.000+00:00",
        "gateway_id": "gateway-a",
        "station_id": "station-01",
        "camera_id": "camera-01",
        "analysis_id": "analysis-inventory",
    }

    first, duplicate_first = store.save_inventory_check_idempotent(
        "SP-KIEM-KHO-001",
        13.04,
        0.5,
        0.16,
        "kg",
        frame,
        "camera-gemini:inventory",
        needs_sync=True,
        **kwargs,
    )
    second, duplicate_second = store.save_inventory_check_idempotent(
        "SP-KIEM-KHO-001",
        13.04,
        0.5,
        0.16,
        "kg",
        frame,
        "camera-gemini:inventory",
        needs_sync=True,
        **kwargs,
    )

    assert duplicate_first is False
    assert duplicate_second is True
    assert second == first
    assert first.product_code == "SP-KIEM-KHO-001"
    assert first.core_weight == pytest.approx(0.5)
    assert first.tare_weight == pytest.approx(0.16)
    assert Path(first.image_path).is_file()
    assert len(list((tmp_path / "captures").glob("*_inventory.jpg"))) == 1
    assert store.inventory_pending_count() == 1
    payload = first.api_payload()
    assert payload["workflow"] == "inventory_check"
    assert payload["qr_code"] == "SP-KIEM-KHO-001"
    assert payload["product_code"] == "SP-KIEM-KHO-001"
    assert "image_path" not in payload
    store.close()
