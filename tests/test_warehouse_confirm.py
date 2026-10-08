from __future__ import annotations

from roll_qr_scale import warehouse


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
            "nhap_kho_luc": "2026-10-08T10:00:00+00:00",
            "nhap_kho_boi": "Trạm cân",
        }

    monkeypatch.setattr(warehouse, "kho_configured", lambda: True)
    monkeypatch.setattr(warehouse, "kho_supabase_url", lambda: "https://kho.example")
    monkeypatch.setattr(warehouse, "kho_supabase_key", lambda: "key")
    monkeypatch.setattr(warehouse, "write_nhap_kho_batch", fake_write)
    monkeypatch.setattr(warehouse, "update_can_tu_dong_nhap_kho", fake_update)

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
