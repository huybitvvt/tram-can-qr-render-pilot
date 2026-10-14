import threading
import urllib.error
import urllib.request
import json
import uuid

import numpy as np
import pytest

from roll_qr_scale import test_ui


FILTERS = dict(work_date="2026-10-14", shift="12C1", machine="M1", production_order="LSX-1", qr_code="SP-001")
RAW = "SOURCE_DATE=2026-10-14; SOURCE_SHIFT=12C1; SOURCE_MACHINE=M1; SOURCE_PRODUCTION_ORDER=LSX-1; PRODUCT_WEIGHT=7.5"


def row(index):
    return dict(event_id=f"event-{index}", qr_code=f"SP-001_{index}", weight=0.4, product_weight=7.5,
                weight_raw=RAW, captured_at="2026-10-14T03:00:00Z", sync_status="synced")


class SnapshotStore:
    def __init__(self, rows):
        self.rows = rows

    def measurement_source_rows(self):
        return self.rows


def test_full_filtered_count_excludes_pending_failed_errors_and_imported_rows():
    rows = [row(i) for i in range(80)]
    for index, changes in enumerate([
        {"sync_status": "pending"}, {"sync_status": "failed"}, {"sync_status": "local"},
        {"weight_raw": RAW + "; ERROR_STATUS=error"}, {"weight_raw": RAW + "; NHAP_KHO_STATUS=Đã nhập kho"},
        {"qr_code": "SP-002_1"}, {"weight_raw": RAW.replace("2026-10-14", "2026-10-13")},
        {"weight_raw": RAW.replace("12C1", "12C2")}, {"weight_raw": RAW.replace("M1", "M2")},
        {"weight_raw": RAW.replace("LSX-1", "LSX-2")},
    ]):
        rows.append({**row(100 + index), **changes})
    summary = test_ui._local_warehouse_ready_summary(SnapshotStore(rows), batch_size=30, **FILTERS)
    assert summary["warehouse_ready_count"] == 80
    assert summary["warehouse_ready_batch_size"] == 30
    assert len(summary["warehouse_ready_signature"]) == 64


@pytest.mark.parametrize("changes", [
    {"weight": None}, {"weight": -1}, {"weight": 8}, {"product_weight": float("inf")},
    {"product_weight": float("nan")}, {"product_weight": None, "weight_raw": RAW.replace("7.5", "unread")},
    {"qr_code": ""}, {"weight_raw": RAW + "; CORE_MISSING=1"},
])
def test_invalid_or_incomplete_ticket_cannot_count_as_ready(changes):
    store = SnapshotStore([{**row(1), **changes}])
    summary = test_ui._local_warehouse_ready_summary(store, batch_size=1, **FILTERS)
    assert summary["warehouse_ready_count"] == 0
    assert summary["warehouse_ready_signature"] == ""


def test_zero_core_and_legacy_product_weight_from_raw_are_counted():
    store = SnapshotStore([{**row(1), "weight": 0, "product_weight": None}])
    assert test_ui._local_warehouse_ready_summary(store, batch_size=1, **FILTERS)["warehouse_ready_count"] == 1


def test_fingerprint_stays_stable_on_new_arrivals_and_changes_after_import():
    rows = [row(i) for i in range(59, -1, -1)]
    store = SnapshotStore(rows)
    first = test_ui._local_warehouse_ready_summary(store, batch_size=30, **FILTERS)
    rows.insert(0, row(60))
    assert test_ui._local_warehouse_ready_summary(store, batch_size=30, **FILTERS)["warehouse_ready_signature"] == first["warehouse_ready_signature"]
    for item in rows[-30:]:
        item["weight_raw"] += "; NHAP_KHO_STATUS=Đã nhập kho"
    next_batch = test_ui._local_warehouse_ready_summary(store, batch_size=30, **FILTERS)
    assert next_batch["warehouse_ready_count"] == 31
    assert next_batch["warehouse_ready_signature"] != first["warehouse_ready_signature"]


def test_late_acknowledgement_for_an_older_ticket_does_not_repeat_the_notice():
    rows = [row(i) for i in range(30, 0, -1)] + [{**row(0), "sync_status": "pending"}]
    store = SnapshotStore(rows)
    first = test_ui._local_warehouse_ready_summary(store, batch_size=30, **FILTERS)
    rows[-1]["sync_status"] = "synced"
    after = test_ui._local_warehouse_ready_summary(store, batch_size=30, **FILTERS)
    assert after["warehouse_ready_count"] == 31
    assert after["warehouse_ready_signature"] == first["warehouse_ready_signature"]


def test_counter_endpoint_observes_sync_and_warehouse_transitions_without_pagination(tmp_path, monkeypatch):
    monkeypatch.setattr(test_ui, "_supabase_project_url", lambda: "")
    monkeypatch.setattr(test_ui, "_ingest_api_url", lambda: "")
    server, service = test_ui.create_server(test_ui.build_parser().parse_args([
        "--db", str(tmp_path / "measurements.db"), "--captures", str(tmp_path / "captures"),
        "--yolo-model", "", "--weight-engine", "local", "--no-auto-sync", "--port", "0",
    ]))
    event_ids = [str(uuid.uuid4()) for _ in range(2)]
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    for index, event_id in enumerate(event_ids):
        service.store.save_idempotent(f"SP-001_{index}", 0.4, "kg", frame, "manual", needs_sync=True,
                                     event_id=event_id, weight_raw=RAW, captured_at="2026-10-14T03:00:00Z")
    service.store.mark_synced(event_ids[0])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    query = "local_only=1&include_drafts=0&count_only=1&limit=1&warehouse_batch_size=2&work_date=2026-10-14&shift=12C1&machine=M1&production_order=LSX-1&qr_code=SP-001"

    def get(suffix=query):
        with urllib.request.urlopen(f"http://{host}:{port}/api/measurements?{suffix}") as response:
            return json.loads(response.read())

    try:
        before = get()
        assert before["measurement_count"] == 2 and before["warehouse_ready_count"] == 1
        assert before["items"] == [] and before["warehouse_ready_signature"] == ""
        service.store.mark_synced(event_ids[1])
        ready = get()
        assert ready["warehouse_ready_count"] == 2 and ready["warehouse_ready_signature"]
        item = service.store.get(event_ids[0])
        service.store.update_measurement_fields(event_ids[0], qr_code=item.qr_code, weight=item.weight,
                                               product_weight=item.product_weight, weight_raw=RAW + "; NHAP_KHO_STATUS=Đã nhập kho")
        assert get()["warehouse_ready_count"] == 1
        for target in ("0", "31", "invalid"):
            with pytest.raises(urllib.error.HTTPError) as error:
                get(query.replace("warehouse_batch_size=2", "warehouse_batch_size=" + target))
            assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()
        service.store.close()
