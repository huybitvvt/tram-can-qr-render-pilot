from __future__ import annotations

from roll_qr_scale import warehouse
import pytest


def test_confirm_nhap_kho_writes_and_marks_status(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_write(*_args, **kwargs):
        calls["write"] = kwargs
        return {
            "success": True,
            "saved": [{"ma_sp_quet": "SP01_A", "created_at": "t"}],
            "duplicateCodes": ["SP01_DUP"],
            "source": "kho",
        }

    def fake_update(*_args, **kwargs):
        calls["update"] = kwargs
        return {
            "success": True,
            "updated": 1,
            "requested": 1,
            "confirmed_count": 1,
            "nhap_kho_luc": "2026-10-08T10:00:00+00:00",
            "nhap_kho_boi": "Trạm cân",
        }

    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    monkeypatch.setattr(warehouse, "kho_supabase_url", lambda: "https://kho.example")
    monkeypatch.setattr(warehouse, "kho_supabase_key", lambda: "key")
    monkeypatch.setattr(warehouse, "write_nhap_kho_batch", fake_write)
    monkeypatch.setattr(warehouse, "update_can_tu_dong_nhap_kho", fake_update)
    monkeypatch.setattr(warehouse, "fetch_can_tu_dong_by_event_ids", lambda *_args: [
        {"event_id": "e1", "qr_code": "SP01_A"},
        {"event_id": "e2", "qr_code": "SP01_DUP"},
    ])
    monkeypatch.setattr(
        warehouse,
        "append_nhap_kho_summary_row",
        lambda entry: {
            "ok": True,
            "count": 1,
            "path": "C:/tmp/tong-hop-day-kho.csv",
            "csv_path": "C:/tmp/tong-hop-day-kho.csv",
            "folder": "C:/tmp",
            "rows": [entry],
        },
    )

    local_updates: list[tuple] = []

    result = warehouse.confirm_nhap_kho(
        items=[
            {
                "event_id": "e1",
                "qr_code": "SP01_A",
                "work_date": "2026-10-08",
                "shift": "HC1",
                "machine": "Máy bao bì 15",
            },
            {
                "event_id": "e2",
                "qr_code": "SP01_DUP",
                "work_date": "2026-10-08",
                "shift": "HC1",
                "machine": "Máy bao bì 15",
            },
        ],
        kho="Kho thành phẩm",
        ca="HC1",
        may="Máy bao bì 15",
        ngay="2026-10-08",
        ma_sp="SP01",
        so_cuon=2,
        nguoi="Trạm cân",
        run_manual_sync=lambda: {"state": "complete", "synced": 1, "empty": False},
        weigh_supabase_url="https://weigh.example",
        weigh_supabase_key="weigh-key",
        update_local_row=lambda *args: local_updates.append(args),
    )

    assert result["saved_count"] == 1
    assert result["duplicate_count"] == 1
    assert result["saved"] == ["SP01_A"]
    assert str(result["ma_phieu"]).startswith("PN-MBB15-")
    assert calls["write"]["kho"] == "Kho thành phẩm"
    assert calls["update"]["ma_phieu"] == result["ma_phieu"]
    assert local_updates and local_updates[0][0] == "e1"
    assert local_updates[0][1] == warehouse.NHAP_KHO_DA
    assert result["summary_export"]["ok"] is True
    assert result["summary_export"]["csv_path"].endswith("tong-hop-day-kho.csv")


def confirm_args():
    return dict(
        items=[{"event_id": "e1", "qr_code": "SP01_A", "work_date": "2026-10-08",
                "shift": "HC1", "machine": "Máy 1"}],
        kho="Kho thành phẩm", ca="HC1", may="Máy 1", ngay="2026-10-08", ma_sp="SP01",
        so_cuon=1, nguoi="Trạm cân", run_manual_sync=lambda: {"state": "complete"},
        weigh_supabase_url="", weigh_supabase_key="",
    )


@pytest.mark.parametrize("remote_rows", [[], [{"event_id": "e1", "qr_code": "OTHER_A"}]])
def test_confirm_does_not_write_warehouse_before_weighing_is_verified(monkeypatch, remote_rows):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    monkeypatch.setattr(warehouse, "write_nhap_kho_batch", lambda *_a, **_k: pytest.fail("must not write kho"))
    with pytest.raises(RuntimeError, match="Chưa đồng bộ đủ QR"):
        warehouse.confirm_nhap_kho(**confirm_args(), weigh_request=lambda *_a: {"items": remote_rows})


def test_confirm_requires_weighing_config_before_any_write(monkeypatch):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    with pytest.raises(RuntimeError, match="Chưa cấu hình Supabase cân AI"):
        warehouse.confirm_nhap_kho(**confirm_args())


def test_confirm_blocks_failed_local_sync_even_if_an_old_cloud_row_exists(monkeypatch):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    args = confirm_args()
    args["run_manual_sync"] = lambda: {"state": "complete", "unsynced_event_ids": ["e1"]}
    with pytest.raises(RuntimeError, match="Chưa đồng bộ xong"):
        warehouse.confirm_nhap_kho(**args, weigh_request=lambda *_a: pytest.fail("must stop before warehouse write"))


@pytest.mark.parametrize("failure", ["network", "empty_ack"])
def test_confirm_keeps_local_waiting_when_weighing_status_is_not_confirmed(monkeypatch, failure):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    monkeypatch.setattr(warehouse, "write_nhap_kho_batch", lambda *_a, **_k: {
        "saved": [{"ma_sp_quet": "SP01_A", "ma_phieu": "PN-existing"}],
    })
    calls = []

    def request(_ids, receipt):
        calls.append(receipt)
        if not receipt:
            return {"items": [{"event_id": "e1", "qr_code": "SP01_A"}]}
        if failure == "network":
            raise OSError("network down")
        return {"confirmed_count": 0}

    with pytest.raises(RuntimeError, match="Bấm Nhập kho lại"):
        warehouse.confirm_nhap_kho(**confirm_args(), weigh_request=request,
                                  update_local_row=lambda *_a: pytest.fail("must remain waiting"))
    assert calls == ["", "PN-existing"]


def test_confirm_recovers_receipt_after_status_update_failure(monkeypatch):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    stored = {}
    headers = {}
    requests = []

    def rest(method, _url, _key, table, **kwargs):
        requests.append((method, table))
        if table == "nhap_kho" and method == "GET":
            return list(stored.values())
        if table == "phieu_nhap" and method == "GET":
            receipt = kwargs["params"]["ma_phieu"][3:]
            return [headers[receipt]] if receipt in headers else []
        if table == "phieu_nhap" and method == "POST":
            row = kwargs["body"]
            assert row["status"] == "chua_chot"
            headers[row["ma_phieu"]] = row
            return [row]
        if table == "nhap_kho" and method == "POST":
            for row in kwargs["body"]:
                assert row["trang_thai"] == "Đang chờ"
                stored[row["ma_sp_quet"]] = row
            return None
        pytest.fail(f"unexpected {method} {table}")

    monkeypatch.setattr(warehouse, "_postgrest_request", rest)
    attempts = iter(["PN-first", "PN-second"])
    monkeypatch.setattr(warehouse, "new_phieu_nhap_code", lambda _may: next(attempts))
    failed = True
    receipts = []

    def request(_ids, receipt):
        if not receipt:
            return {"items": [{"event_id": "e1", "qr_code": "SP01_A"}]}
        receipts.append(receipt)
        if failed:
            raise OSError("temporary network error")
        return {"confirmed_count": 1}

    local = []
    with pytest.raises(RuntimeError, match="Bấm Nhập kho lại"):
        warehouse.confirm_nhap_kho(**confirm_args(), weigh_request=request, update_local_row=lambda *a: local.append(a))
    assert not local
    failed = False
    result = warehouse.confirm_nhap_kho(**confirm_args(), weigh_request=request, update_local_row=lambda *a: local.append(a))
    assert result["ma_phieu"] == "PN-first"
    assert result["recovered_count"] == 1
    assert receipts == ["PN-first", "PN-first"]
    assert requests.count(("POST", "phieu_nhap")) == 1
    assert requests.count(("POST", "nhap_kho")) == 1
    assert local[0][-1] == "PN-first"


@pytest.mark.parametrize("patch_response", [None, []])
def test_direct_status_update_does_not_accept_rls_noop(monkeypatch, patch_response):
    monkeypatch.setattr(warehouse, "fetch_can_tu_dong_by_event_ids", lambda *_a, **_k: [
        {"id": 1, "event_id": "e1", "metadata": {}},
    ])
    monkeypatch.setattr(warehouse, "_postgrest_request", lambda *_a, **_k: patch_response)
    with pytest.raises(RuntimeError, match="quyền ghi"):
        warehouse.update_can_tu_dong_nhap_kho("https://weigh.example", "anon", ["e1"], nguoi="Test", ma_phieu="PN1")
