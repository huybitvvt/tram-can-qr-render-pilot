from __future__ import annotations

import json

import pytest

from roll_qr_scale import warehouse


@pytest.mark.parametrize("codes", [["SP_DUP", "SP_NEW"], ["SP_DUP"], ["SP_NEW", "SP_NEW"]])
def test_duplicate_qrs_still_count_in_report_without_another_warehouse_line(monkeypatch, codes):
    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    monkeypatch.setattr(warehouse, "kho_supabase_url", lambda: "https://kho.example")
    monkeypatch.setattr(warehouse, "kho_supabase_key", lambda: "test-key")
    headers = {"PN-OLD": {"ma_phieu": "PN-OLD", "status": "chua_chot", "ghi_chu": ""}}
    stored = {"SP_DUP": {"ma_sp_quet": "SP_DUP", "ma_phieu": "PN-OLD", "created_at": "old"}}
    inserts, summaries, updates = [], [], []

    def rest(method, _url, _key, table, **kwargs):
        if table == "nhap_kho" and method == "GET":
            return list(stored.values())
        if table == "phieu_nhap" and method == "GET":
            receipt_filter = kwargs["params"].get("ma_phieu")
            if receipt_filter:
                return [headers[receipt_filter[3:]]] if receipt_filter[3:] in headers else []
            return list(headers.values())
        if table == "phieu_nhap" and method in {"POST", "PATCH"}:
            receipt = kwargs["body"].get("ma_phieu") or kwargs["params"]["ma_phieu"][3:]
            headers.setdefault(receipt, {}).update(kwargs["body"])
            return [headers[receipt]]
        assert table == "nhap_kho" and method == "POST"
        for row in kwargs["body"]:
            assert row["ma_sp_quet"] not in stored
            inserts.append(row)
            stored[row["ma_sp_quet"]] = row

    monkeypatch.setattr(warehouse, "_postgrest_request", rest)
    monkeypatch.setattr(warehouse, "append_nhap_kho_summary_row", lambda row: summaries.append(row) or {"ok": True})
    attempts = iter(["PN-FIRST", "PN-RETRY"])
    monkeypatch.setattr(warehouse, "new_phieu_nhap_code", lambda _may: next(attempts))
    items = [{"event_id": f"e{index}", "qr_code": code, "work_date": "2026-10-12", "shift": "HC1", "machine": "M1"}
             for index, code in enumerate(codes)]
    failed = True

    def weigh(event_ids, receipt):
        if not receipt:
            return {"items": items}
        updates.append((event_ids, receipt))
        if failed:
            raise OSError("temporary cloud failure")
        return {"confirmed_count": len(event_ids), "nhap_kho_luc": "2026-10-12T00:00:00Z"}

    args = dict(items=items, kho="Kho thành phẩm", ca="HC1", may="M1", ngay="2026-10-12", ma_sp="SP",
                so_cuon=len(items), nguoi="Test", run_manual_sync=None, weigh_supabase_url="", weigh_supabase_key="",
                event_ids=[row["event_id"] for row in items], weigh_request=weigh)
    with pytest.raises(RuntimeError, match="Bấm Nhập kho lại"):
        warehouse.confirm_nhap_kho(**args)
    assert not summaries
    failed = False
    result = warehouse.confirm_nhap_kho(**args)
    assert result["report_count"] == len(items)
    assert result["duplicate_count"] == len(items) - int("SP_NEW" in codes)
    assert result["saved_count"] == int("SP_NEW" in codes)
    assert len(inserts) == int("SP_NEW" in codes)
    assert result["ma_phieu"] == "PN-FIRST"
    assert summaries[0]["so_luong"] == len(items)
    assert len(headers) == 2, "retry must not create an extra receipt"
    assert stored["SP_DUP"]["ma_phieu"] == "PN-OLD"
    note = json.loads(headers["PN-FIRST"]["ghi_chu"])
    assert note["so_cuon"] == len(items)
    assert set(note["event_qrs"]) == {row["event_id"] for row in items}
    assert updates[-1][1] == "PN-FIRST"
