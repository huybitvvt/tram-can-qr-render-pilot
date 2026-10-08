from roll_qr_scale import test_ui
from roll_qr_scale.storage import MeasurementStore


def configure_api(monkeypatch):
    monkeypatch.setenv("ROLL_SCALE_API_URL", "https://weigh.example/functions/v1/ingest-measurement")
    monkeypatch.setenv("ROLL_SCALE_DEVICE_TOKEN", "device-token")
    monkeypatch.delenv("ROLL_SCALE_SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.delenv("ROLL_SCALE_SUPABASE_PUBLISHABLE_KEY", raising=False)


def test_warehouse_pool_reads_all_pages_with_device_token(tmp_path, monkeypatch):
    configure_api(monkeypatch)
    rows = [{"id": i, "event_id": f"e{i}", "qr_code": f"SP01_{i}",
             "metadata": {"work_date": "2026-10-08", "shift": "HC1", "machine": "Máy 1"}}
            for i in range(205)]
    offsets = []

    def page(url, token, **kwargs):
        assert token == "device-token"
        offsets.append(kwargs["offset"])
        return rows[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]], len(rows)

    monkeypatch.setattr(test_ui, "fetch_remote_measurement_page", page)
    store = MeasurementStore(tmp_path / "db.sqlite", tmp_path / "captures")
    service = test_ui.StationUIService(store, None, None, None)
    try:
        result = service.warehouse_measurement_pool(work_date="2026-10-08", shift="HC1", machine="Máy 1")
        assert len(result) == 205
        assert offsets == [0, 200]
        assert result[-1]["event_id"] == "e204"
    finally:
        service.close()
        store.close()


def test_warehouse_confirm_uses_ingest_token_without_ai_service_key(tmp_path, monkeypatch):
    configure_api(monkeypatch)
    calls = []

    def action(url, token, **kwargs):
        assert url == "https://weigh.example/functions/v1/ingest-measurement"
        assert token == "device-token"
        calls.append(kwargs["body"])
        return {"ok": True, "confirmed_count": 1}

    def confirm(**kwargs):
        assert kwargs["weigh_supabase_key"] == ""
        kwargs["weigh_request"](["e1"], "")
        return kwargs["weigh_request"](["e1"], "PN1")

    monkeypatch.setattr(test_ui, "post_remote_action", action)
    monkeypatch.setattr(test_ui, "confirm_nhap_kho", confirm)
    monkeypatch.setattr(test_ui.StationUIService, "warehouse_measurement_pool", lambda *_a, **_k: [])
    store = MeasurementStore(tmp_path / "db.sqlite", tmp_path / "captures")
    service = test_ui.StationUIService(store, None, None, None)
    try:
        result = service.warehouse_confirm({"ngay": "2026-10-08", "ca": "HC1", "may": "Máy 1",
                                            "ma_sp": "SP01", "kho": "Kho thành phẩm", "so_cuon": 1})
        assert result["confirmed_count"] == 1
        assert calls[0]["action"] == "warehouse_import_status"
        assert calls[0]["check_only"] is True
        assert calls[1]["check_only"] is False
        assert calls[1]["ma_phieu"] == "PN1"
    finally:
        service.close()
        store.close()


def test_manual_sync_reports_final_pending_events_after_retries(tmp_path):
    import numpy as np
    from roll_qr_scale.sync import OutboxSyncWorker

    store = MeasurementStore(tmp_path / "db.sqlite", tmp_path / "captures")
    row = store.save("SP01_A", 1, "kg", np.zeros((20, 20, 3), dtype=np.uint8), "manual",
                     needs_sync=True, weight_raw="SOURCE_DATE=2026-10-08; SOURCE_SHIFT=HC1; SOURCE_MACHINE=Máy 1")
    failing = True

    def send(_url, payload, _image, _token):
        if failing:
            raise OSError("network down")
        return {"ok": True, "event_id": payload["event_id"], "id": 1,
                "image_url": "https://images.example/1.jpg", "image_public_id": "image-1"}

    worker = OutboxSyncWorker(store, "https://weigh.example/ingest", "token", send=send)
    controller = test_ui.ManualSyncController(store, worker)
    filters = {"scope": "production", "date_from": "2026-10-08", "date_to": "2026-10-08",
               "shift": "HC1", "machine": "Máy 1", "skip_cloudinary": True}
    try:
        result = controller.run_now(filters)
        assert result["unsynced_event_ids"] == [row.event_id]
        failing = False
        result = controller.run_now(filters)
        assert result["unsynced_event_ids"] == []
    finally:
        store.close()
