from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from roll_qr_scale.warehouse import (
    NHAP_KHO_DA,
    append_nhap_kho_summary_row,
    filter_waiting_candidates,
    is_finished_goods_warehouse_name,
    is_waiting_nhap_kho,
    load_nhap_kho_summary_rows,
    machine_slip_code_token,
    new_phieu_nhap_code,
    nhap_kho_summary_status,
    product_code_from_qr,
    read_nhap_kho_status,
    save_nhap_kho_summary_rows,
    upsert_local_nhap_kho_tags,
)


def test_machine_slip_and_phieu_code() -> None:
    assert machine_slip_code_token("Máy bao bì 15") == "MBB15"
    assert machine_slip_code_token("MBB15 - Máy bao bì 15") == "MBB15"
    stamp = datetime(2026, 10, 8, 3, 4, 5, tzinfo=timezone.utc)
    assert new_phieu_nhap_code("Máy bao bì 15", now=stamp) == "PN-MBB15-20261008-030405"


def test_product_code_and_finished_goods_filter() -> None:
    assert product_code_from_qr("SP01_ROLL99") == "SP01"
    assert product_code_from_qr("SP01+AA") == "SP01"
    assert is_finished_goods_warehouse_name("Kho thành phẩm 1")
    assert is_finished_goods_warehouse_name("Kho SP ĐN")
    assert not is_finished_goods_warehouse_name("Kho nguyên liệu")


def test_waiting_filter_skips_already_imported_rows() -> None:
    waiting = {
        "event_id": "e1",
        "qr_code": "SP01_A",
        "work_date": "2026-10-08",
        "shift": "HC1",
        "machine": "Máy bao bì 15",
        "weight_raw": "",
    }
    done = {
        **waiting,
        "event_id": "e2",
        "qr_code": "SP01_B",
        "metadata": {"nhap_kho_trang_thai": NHAP_KHO_DA},
    }
    other_sp = {**waiting, "event_id": "e3", "qr_code": "SP02_C"}
    rows = filter_waiting_candidates(
        [waiting, done, other_sp],
        work_date="2026-10-08",
        shift="HC1",
        machine="Máy bao bì 15",
        ma_sp="SP01",
    )
    assert [row["event_id"] for row in rows] == ["e1"]
    assert is_waiting_nhap_kho(waiting)
    assert not is_waiting_nhap_kho(done)


def test_local_nhap_kho_tags_round_trip() -> None:
    raw = upsert_local_nhap_kho_tags(
        "SOURCE_SHIFT=HC1",
        status=NHAP_KHO_DA,
        luc="2026-10-08T01:02:03+00:00",
        boi="Trạm cân",
        ma_phieu="PN-1",
    )
    assert "NHAP_KHO_STATUS=Đã nhập kho" in raw
    assert "NHAP_KHO_MA_PHIEU=PN-1" in raw
    assert read_nhap_kho_status({"weight_raw": raw}) == NHAP_KHO_DA


def test_warehouse_names_fall_back_to_receipts_if_catalog_is_unavailable(monkeypatch):
    from roll_qr_scale import warehouse

    def request(_method, _url, _key, table, **_kwargs):
        if table == "quan_ly_kho":
            raise RuntimeError("Could not find the table 'public.quan_ly_kho' in the schema cache")
        assert table == "phieu_nhap"
        return [{"kho": "Kho thành phẩm 1"}, {"kho": "Kho thành phẩm 1"}, {"kho": "Kho nguyên liệu"}]

    monkeypatch.setattr(warehouse, "_postgrest_request", request)
    assert warehouse.fetch_finished_goods_warehouses("url", "key") == ["Kho thành phẩm 1"]


def test_nhap_kho_summary_writes_csv_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ROLL_SCALE_NHAP_KHO_EXPORT_DIR", str(tmp_path))
    saved = append_nhap_kho_summary_row(
        {
            "ma_phieu": "PN-MBB15-20261008-010203",
            "ma_sp": "SP01",
            "so_luong": 3,
            "ngay": "2026-10-08",
            "ca": "HC1",
            "may": "Máy bao bì 15",
            "kho": "Kho thành phẩm",
            "saved_at": "2026-10-08T01:02:03+00:00",
        }
    )
    assert saved["ok"] is True
    assert saved["count"] == 1
    assert Path(saved["csv_path"]).is_file()
    assert Path(saved["json_path"]).is_file()
    csv_text = Path(saved["csv_path"]).read_text(encoding="utf-8-sig")
    assert "PN-MBB15-20261008-010203" in csv_text
    assert "TỔNG" in csv_text
    rows = load_nhap_kho_summary_rows()
    assert len(rows) == 1
    assert rows[0]["ma_sp"] == "SP01"
    # duplicate append is ignored
    again = append_nhap_kho_summary_row(rows[0])
    assert again["count"] == 1
    cleared = save_nhap_kho_summary_rows([])
    assert cleared["count"] == 0
    status = nhap_kho_summary_status()
    assert status["count"] == 0
    assert status["folder"] == str(tmp_path)
