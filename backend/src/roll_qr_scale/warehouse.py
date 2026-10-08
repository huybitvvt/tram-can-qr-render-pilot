"""Warehouse intake (nhap_kho) against the separate Supabase kho project."""

from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable

NHAP_KHO_CHO = "Chờ nhập kho"
NHAP_KHO_DA = "Đã nhập kho"


def kho_supabase_url() -> str:
    return (
        os.environ.get("ROLL_SCALE_KHO_SUPABASE_URL", "").strip().rstrip("/")
        or os.environ.get("SUPABASE_KHO_URL", "").strip().rstrip("/")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_KHO_URL", "").strip().rstrip("/")
    )


def kho_supabase_key() -> str:
    return (
        os.environ.get("ROLL_SCALE_KHO_SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("SUPABASE_KHO_SERVICE_KEY", "").strip()
        or os.environ.get("SUPABASE_KHO_KEY", "").strip()
        or os.environ.get("SUPABASE_KHO_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("NEXT_PUBLIC_SUPABASE_KHO_PUBLISHABLE_KEY", "").strip()
    )


def kho_db_label() -> str:
    return (
        os.environ.get("ROLL_SCALE_KHO_DB_LABEL", "").strip()
        or os.environ.get("SUPABASE_KHO_DB_LABEL", "").strip()
        or "kho"
    )


def default_finished_goods_warehouse_name() -> str:
    return (
        os.environ.get("ROLL_SCALE_KHO_THANH_PHAM_NAME", "").strip()
        or "Kho thành phẩm"
    )


def kho_configured() -> bool:
    return bool(kho_supabase_url() and kho_supabase_key())


def fold_ascii(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text.replace("đ", "d").replace("Đ", "d")


def is_finished_goods_warehouse_name(value: str) -> bool:
    key = fold_ascii(value).lower()
    return (
        "thanh pham" in key
        or "san pham" in key
        or "finished" in key
        or "kho sp" in key
    )


def machine_slip_code_token(machine_name: str) -> str:
    raw = str(machine_name or "").strip()
    if not raw:
        return ""
    labeled = re.split(r"\s+-\s+", raw)
    if len(labeled) > 1:
        head = re.sub(r"[^A-Z0-9]", "", fold_ascii(labeled[0]).upper())
        if head:
            return head
    folded = fold_ascii(raw).upper().strip()
    if re.fullmatch(r"[A-Z0-9]+", folded):
        return folded
    tokens = re.findall(r"[A-Z]+|\d+", folded)
    return "".join(token if token.isdigit() else token[0] for token in tokens)


def new_phieu_nhap_code(machine_name: str, *, now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    date = stamp.strftime("%Y%m%d")
    time = stamp.strftime("%H%M%S")
    token = machine_slip_code_token(machine_name)
    return f"PN-{token}-{date}-{time}" if token else f"PN-{date}-{time}"


def product_code_from_qr(qr_code: str) -> str:
    full = str(qr_code or "").strip()
    if not full:
        return ""
    separators = [index for sep in ("_", "+") if (index := full.find(sep)) > 0]
    if not separators:
        return full
    return full[: min(separators)].strip()


def normalize_product_code_key(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_qr_key(value: str) -> str:
    return str(value or "").strip().upper()


def read_nhap_kho_status(item: dict[str, object]) -> str:
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        status = str(metadata.get("nhap_kho_trang_thai") or "").strip()
        if status:
            return status
    raw = str(item.get("weight_raw") or "")
    tagged = ""
    match = re.search(r"(?:^|; )NHAP_KHO_STATUS=([^;]*)", raw)
    if match:
        tagged = match.group(1).strip()
    return tagged or NHAP_KHO_CHO


def is_waiting_nhap_kho(item: dict[str, object]) -> bool:
    return read_nhap_kho_status(item) != NHAP_KHO_DA


def _postgrest_request(
    method: str,
    supabase_url: str,
    api_key: str,
    table: str,
    *,
    params: dict[str, object] | None = None,
    body: object | None = None,
    prefer: str = "",
    timeout: float = 30.0,
) -> object:
    encoded_table = urllib.parse.quote(table, safe="")
    query = urllib.parse.urlencode(params or {})
    url = f"{supabase_url.rstrip('/')}/rest/v1/{encoded_table}"
    if query:
        url = f"{url}?{query}"
    headers = {
        "Accept": "application/json",
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if prefer:
        headers["Prefer"] = prefer
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = (
                str(parsed.get("message") or parsed.get("error") or detail).strip()
            )
        except json.JSONDecodeError:
            message = detail.strip() or str(exc)
        raise RuntimeError(message or f"Supabase {table} HTTP {exc.code}") from exc


def fetch_finished_goods_warehouses(
    supabase_url: str,
    api_key: str,
    *,
    timeout: float = 15.0,
) -> list[str]:
    name_field = "ten_kho"
    try:
        rows = _postgrest_request(
            "GET", supabase_url, api_key, "quan_ly_kho",
            params={"select": "ten_kho", "order": "ten_kho.asc", "limit": 1000},
            timeout=timeout,
        )
    except RuntimeError as exc:
        if "quan_ly_kho" not in str(exc) or "schema cache" not in str(exc):
            raise
        # Some warehouse projects only expose intake tables to the desktop key.
        name_field = "kho"
        rows = _postgrest_request(
            "GET", supabase_url, api_key, "phieu_nhap",
            params={"select": "kho", "order": "created_at.desc", "limit": 1000},
            timeout=timeout,
        )
    if not isinstance(rows, list):
        raise RuntimeError("Không đọc được danh sách kho")
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get(name_field) or "").strip()
        if not name or not is_finished_goods_warehouse_name(name):
            continue
        key = normalize_product_code_key(name)
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    names.sort(key=lambda value: value.lower())
    return names


def _postgrest_in_filter(values: list[str]) -> str:
    quoted = []
    for value in values:
        safe = str(value).replace("\\", "\\\\").replace('"', '\\"')
        quoted.append(f'"{safe}"')
    return f"in.({','.join(quoted)})"


def check_nhap_kho_codes(
    supabase_url: str,
    api_key: str,
    codes: list[str],
    *,
    timeout: float = 30.0,
) -> list[dict[str, str]]:
    cleaned = [
        code
        for code in dict.fromkeys(str(item or "").strip() for item in codes)
        if code
    ]
    matches: list[dict[str, str]] = []
    for offset in range(0, len(cleaned), 100):
        chunk = cleaned[offset : offset + 100]
        rows = _postgrest_request(
            "GET",
            supabase_url,
            api_key,
            "nhap_kho",
            params={
                "select": "ma_sp_quet,ma_phieu",
                "ma_sp_quet": _postgrest_in_filter(chunk),
                "limit": 1000,
            },
            timeout=timeout,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Không kiểm tra được mã trong nhap_kho")
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("ma_sp_quet") or "").strip()
            if not code:
                continue
            matches.append(
                {
                    "ma_sp_quet": code,
                    "ma_phieu": str(row.get("ma_phieu") or "").strip(),
                }
            )
    return matches


def _load_existing_nhap_kho(
    supabase_url: str,
    api_key: str,
    codes: list[str],
    *,
    timeout: float = 30.0,
) -> dict[str, dict[str, str]]:
    existing: dict[str, dict[str, str]] = {}
    for offset in range(0, len(codes), 100):
        chunk = codes[offset : offset + 100]
        rows = _postgrest_request(
            "GET",
            supabase_url,
            api_key,
            "nhap_kho",
            params={
                "select": "ma_sp_quet,ma_phieu,created_at",
                "loai": "eq.san_pham",
                "ma_sp_quet": _postgrest_in_filter(chunk),
                "limit": 1000,
            },
            timeout=timeout,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Không thể kiểm tra mã QR đã lưu")
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("ma_sp_quet") or "").strip()
            if not code:
                continue
            previous = existing.get(code)
            ma_phieu = str(row.get("ma_phieu") or "")
            if previous is None or previous.get("ma_phieu") == ma_phieu:
                existing[code] = {
                    "ma_phieu": ma_phieu,
                    "created_at": str(row.get("created_at") or ""),
                }
    return existing


def write_nhap_kho_batch(
    supabase_url: str,
    api_key: str,
    *,
    ma_phieu: str,
    ngay: str,
    nhan_su: str,
    nguoi_lap: str,
    kho: str,
    ca: str,
    may: str,
    items: list[dict[str, str]],
    timeout: float = 60.0,
) -> dict[str, object]:
    """Mirror /api/kho/quet-dot nhap flow: create chua_chot slip and insert lines."""

    items_by_code: dict[str, dict[str, str]] = {}
    for raw in items:
        full_code = str(raw.get("ma_sp_quet") or "").strip()
        if not full_code:
            continue
        key = normalize_qr_key(full_code)
        if key in items_by_code:
            continue
        items_by_code[key] = {
            "fullCode": full_code,
            "tenSp": str(raw.get("ten_sp") or "").strip(),
            "donVi": str(raw.get("don_vi") or "").strip(),
            "eventId": str(raw.get("event_id") or "").strip(),
        }
    unique_items = list(items_by_code.values())
    if not ma_phieu or not unique_items:
        raise ValueError("Cần ma_phieu và danh sách mã QR hợp lệ")
    if len(unique_items) > 2000:
        raise ValueError("Mỗi đợt chỉ hỗ trợ tối đa 2000 mã QR")

    saved_by_code: dict[str, dict[str, object]] = {}
    duplicate_codes: set[str] = set()
    codes = [item["fullCode"] for item in unique_items]
    existing = _load_existing_nhap_kho(
        supabase_url, api_key, codes, timeout=timeout
    )
    receipts: dict[str, dict[str, str]] = {}

    def recover(item: dict[str, str], row: dict[str, str]) -> bool:
        """Resume only receipts belonging to this exact weighing event."""
        receipt = row.get("ma_phieu") or ""
        if not receipt or not item["eventId"]:
            return False
        if receipt not in receipts:
            headers = _postgrest_request(
                "GET", supabase_url, api_key, "phieu_nhap",
                params={"select": "ghi_chu", "ma_phieu": f"eq.{receipt}", "limit": 1},
                timeout=timeout,
            )
            events: dict[str, str] = {}
            if isinstance(headers, list) and headers and isinstance(headers[0], dict):
                try:
                    note = json.loads(str(headers[0].get("ghi_chu") or ""))
                    if isinstance(note, dict) and note.get("source") == "TramCanQR":
                        tagged = note.get("events")
                        if isinstance(tagged, dict):
                            events = tagged
                except (ValueError, TypeError):
                    pass
            receipts[receipt] = events
        if receipts[receipt].get(item["fullCode"]) != item["eventId"]:
            return False
        saved_by_code[item["fullCode"]] = {
            "ma_sp_quet": item["fullCode"],
            "ma_phieu": receipt,
            "created_at": row.get("created_at") or "",
            "recovered": True,
        }
        return True

    pending: list[dict[str, str]] = []
    for item in unique_items:
        row = existing.get(item["fullCode"])
        if not row:
            pending.append(item)
            continue
        if row.get("ma_phieu") == ma_phieu:
            saved_by_code[item["fullCode"]] = {
                "ma_sp_quet": item["fullCode"],
                "ma_phieu": ma_phieu,
                "created_at": row.get("created_at") or datetime.now(timezone.utc).isoformat(),
            }
        elif not recover(item, row):
            duplicate_codes.add(item["fullCode"])

    header: dict[str, object] | None = None
    header_fields: dict[str, object] = {
        "ngay": ngay or None,
        "nhan_su": nhan_su or None,
        "kho": kho or None,
        "ghi_chu": json.dumps({
            "source": "TramCanQR",
            "events": {item["fullCode"]: item["eventId"] for item in unique_items if item["eventId"]},
        }, ensure_ascii=False),
    }
    if ca:
        header_fields["ca"] = ca
    if may:
        header_fields["may"] = may
    if nguoi_lap:
        header_fields["nguoi_lap"] = nguoi_lap

    if pending or any(row.get("ma_phieu") == ma_phieu for row in saved_by_code.values()):
        existing_header = _postgrest_request(
            "GET",
            supabase_url,
            api_key,
            "phieu_nhap",
            params={
                "select": "ma_phieu,ngay,nhan_su,kho,ghi_chu,status,created_at",
                "ma_phieu": f"eq.{ma_phieu}",
                "limit": 1,
            },
            prefer="return=representation",
            timeout=timeout,
        )
        header_row = None
        if isinstance(existing_header, list) and existing_header:
            header_row = existing_header[0] if isinstance(existing_header[0], dict) else None
        if header_row and str(header_row.get("status") or "") not in {"", "chua_chot"}:
            raise RuntimeError("Phiếu đã chốt; không thể lưu thêm mã ở bước nhập kho")
        if header_row:
            updated = _postgrest_request(
                "PATCH",
                supabase_url,
                api_key,
                "phieu_nhap",
                params={
                    "ma_phieu": f"eq.{ma_phieu}",
                    "status": "eq.chua_chot",
                    "select": "ma_phieu,ngay,nhan_su,kho,ghi_chu,status,created_at",
                },
                body=header_fields,
                prefer="return=representation",
                timeout=timeout,
            )
            if not isinstance(updated, list) or not updated:
                raise RuntimeError("Phiếu vừa được chốt; không thể lưu thêm mã")
            header = updated[0] if isinstance(updated[0], dict) else None
        elif pending:
            inserted = _postgrest_request(
                "POST",
                supabase_url,
                api_key,
                "phieu_nhap",
                params={
                    "select": "ma_phieu,ngay,nhan_su,kho,ghi_chu,status,created_at",
                },
                body={"ma_phieu": ma_phieu, **header_fields, "status": "chua_chot"},
                prefer="return=representation",
                timeout=timeout,
            )
            if not isinstance(inserted, list) or not inserted:
                raise RuntimeError("Không thể tạo phiếu chưa chốt")
            header = inserted[0] if isinstance(inserted[0], dict) else None

    for attempt in range(3):
        if not pending:
            break
        rows = []
        for item in pending:
            rows.append(
                {
                    "ma_sp": product_code_from_qr(item["fullCode"]) or item["fullCode"],
                    "ma_sp_quet": item["fullCode"],
                    "ten_sp": item["tenSp"] or None,
                    "don_vi": item["donVi"] or None,
                    "loai": "san_pham",
                    "so_luong": 1,
                    "ma_phieu": ma_phieu,
                    "ca": ca or None,
                    "may": may or None,
                    "ngay": ngay or None,
                    "nguoi_thao_tac": nhan_su or nguoi_lap or None,
                    "trang_thai": "Đang chờ",
                }
            )
        try:
            _postgrest_request(
                "POST",
                supabase_url,
                api_key,
                "nhap_kho",
                body=rows,
                prefer="return=minimal",
                timeout=timeout,
            )
            saved_at = datetime.now(timezone.utc).isoformat()
            for item in pending:
                saved_by_code[item["fullCode"]] = {
                    "ma_sp_quet": item["fullCode"],
                    "ma_phieu": ma_phieu,
                    "created_at": saved_at,
                }
            pending = []
            break
        except RuntimeError as exc:
            if "duplicate" not in str(exc).lower() and "23505" not in str(exc):
                raise
            if attempt >= 2:
                raise
            raced = _load_existing_nhap_kho(
                supabase_url,
                api_key,
                [item["fullCode"] for item in pending],
                timeout=timeout,
            )
            next_pending: list[dict[str, str]] = []
            for item in pending:
                row = raced.get(item["fullCode"])
                if not row:
                    next_pending.append(item)
                    continue
                if row.get("ma_phieu") == ma_phieu:
                    saved_by_code[item["fullCode"]] = {
                        "ma_sp_quet": item["fullCode"],
                        "ma_phieu": ma_phieu,
                        "created_at": row.get("created_at")
                        or datetime.now(timezone.utc).isoformat(),
                    }
                elif not recover(item, row):
                    duplicate_codes.add(item["fullCode"])
            pending = next_pending

    return {
        "success": True,
        "header": header,
        "saved": list(saved_by_code.values()),
        "duplicateCodes": sorted(duplicate_codes),
        "source": kho_db_label(),
    }


def fetch_can_tu_dong_by_event_ids(
    supabase_url: str,
    api_key: str,
    event_ids: list[str],
    *,
    timeout: float = 30.0,
) -> list[dict[str, object]]:
    cleaned = [
        event_id
        for event_id in dict.fromkeys(str(item or "").strip() for item in event_ids)
        if event_id and not any(ch in event_id for ch in ",()")
    ]
    rows: list[dict[str, object]] = []
    for offset in range(0, len(cleaned), 50):
        chunk = cleaned[offset : offset + 50]
        parsed = _postgrest_request(
            "GET",
            supabase_url,
            api_key,
            "can_tu_dong",
            params={
                "select": "id,event_id,qr_code,metadata",
                "event_id": _postgrest_in_filter(chunk),
                "limit": 200,
            },
            timeout=timeout,
        )
        if not isinstance(parsed, list):
            raise RuntimeError("Không đọc được can_tu_dong")
        rows.extend(item for item in parsed if isinstance(item, dict))
    return rows


def update_can_tu_dong_nhap_kho(
    supabase_url: str,
    api_key: str,
    event_ids: list[str],
    *,
    nguoi: str,
    ma_phieu: str,
    trang_thai: str = NHAP_KHO_DA,
    timeout: float = 60.0,
) -> dict[str, object]:
    luc = datetime.now(timezone.utc).isoformat()
    rows = fetch_can_tu_dong_by_event_ids(
        supabase_url, api_key, event_ids, timeout=timeout
    )
    found = {str(row.get("event_id") or "") for row in rows}
    if set(event_ids) - found:
        raise RuntimeError("Chưa đủ phiếu trên Supabase cân AI; hãy đồng bộ rồi nhập kho lại")
    updated = 0
    for row in rows:
        metadata = row.get("metadata")
        current = dict(metadata) if isinstance(metadata, dict) else {}
        current_status = str(current.get("nhap_kho_trang_thai") or "").strip() or NHAP_KHO_CHO
        if current_status == trang_thai and trang_thai == NHAP_KHO_DA:
            if ma_phieu and str(current.get("nhap_kho_ma_phieu") or "") == ma_phieu:
                continue
        next_meta = dict(current)
        next_meta["nhap_kho_trang_thai"] = trang_thai
        if trang_thai == NHAP_KHO_DA:
            next_meta["nhap_kho_luc"] = luc
            next_meta["nhap_kho_boi"] = nguoi
            if ma_phieu:
                next_meta["nhap_kho_ma_phieu"] = ma_phieu
        row_id = row.get("id")
        event_id = str(row.get("event_id") or "").strip()
        params: dict[str, object]
        if row_id is not None and str(row_id).strip():
            params = {"id": f"eq.{row_id}"}
        elif event_id:
            params = {"event_id": f"eq.{event_id}"}
        else:
            continue
        result = _postgrest_request(
            "PATCH",
            supabase_url,
            api_key,
            "can_tu_dong",
            params=params,
            body={"metadata": next_meta},
            prefer="return=representation",
            timeout=timeout,
        )
        if not isinstance(result, list) or not result:
            raise RuntimeError("Không cập nhật được trạng thái cân AI; kiểm tra quyền ghi Supabase")
        updated += 1
    return {
        "success": True,
        "updated": updated,
        "requested": len(event_ids),
        "confirmed_count": len(found),
        "nhap_kho_trang_thai": trang_thai,
        "nhap_kho_luc": luc,
        "nhap_kho_boi": nguoi,
    }


def _upsert_raw_tag(raw: str, name: str, value: str) -> str:
    raw = str(raw or "").strip()
    token = f"{name}={value}"
    pattern = rf"(?:^|; )\s*{re.escape(name)}=[^;]*"
    if re.search(pattern, raw):
        return re.sub(pattern, f"; {token}", raw).lstrip("; ").strip()
    if not raw:
        return token
    return f"{raw}; {token}"


def upsert_local_nhap_kho_tags(
    weight_raw: str, *, status: str, luc: str, boi: str, ma_phieu: str
) -> str:
    raw = str(weight_raw or "")
    raw = _upsert_raw_tag(raw, "NHAP_KHO_STATUS", status)
    if luc:
        raw = _upsert_raw_tag(raw, "NHAP_KHO_LUC", luc)
    if boi:
        raw = _upsert_raw_tag(raw, "NHAP_KHO_BOI", boi)
    if ma_phieu:
        raw = _upsert_raw_tag(raw, "NHAP_KHO_MA_PHIEU", ma_phieu)
    return raw


def filter_waiting_candidates(
    items: list[dict[str, object]],
    *,
    work_date: str,
    shift: str,
    machine: str,
    ma_sp: str,
) -> list[dict[str, object]]:
    ma_sp_key = normalize_product_code_key(ma_sp)
    if not work_date or not shift.strip() or not machine.strip() or not ma_sp_key:
        return []
    selected: list[dict[str, object]] = []
    for item in items:
        qr = str(item.get("qr_code") or "").strip()
        if not qr or not is_waiting_nhap_kho(item):
            continue
        item_date = str(item.get("work_date") or "").strip()
        if item_date != work_date:
            continue
        if str(item.get("shift") or "").strip() != shift.strip():
            continue
        if str(item.get("machine") or "").strip() != machine.strip():
            continue
        if normalize_product_code_key(product_code_from_qr(qr)) != ma_sp_key:
            continue
        selected.append(item)
    selected.sort(
        key=lambda row: (
            str(row.get("captured_at") or ""),
            str(row.get("event_id") or row.get("id") or ""),
        ),
        reverse=True,
    )
    return selected


def confirm_nhap_kho(
    *,
    items: list[dict[str, object]],
    kho: str,
    ca: str,
    may: str,
    ngay: str,
    ma_sp: str,
    so_cuon: int,
    nguoi: str,
    run_manual_sync: Callable[[], dict[str, object]] | None,
    weigh_supabase_url: str,
    weigh_supabase_key: str,
    update_local_row: Callable[[str, str, str, str, str], None] | None = None,
    weigh_request: Callable[[list[str], str], dict[str, object]] | None = None,
) -> dict[str, object]:
    if not kho_configured():
        raise RuntimeError(f"Chưa cấu hình DB kho ({kho_db_label()})")
    if so_cuon < 1:
        raise ValueError("Nhập số cuộn để hiện mã QR chờ nhập kho")
    if not kho.strip():
        raise ValueError("Chưa có kho thành phẩm để lập phiếu nhập")
    if not ca.strip() or not may.strip() or not ma_sp.strip():
        raise ValueError("Chọn ca, máy và Mã SP để lọc mã QR nhập kho")
    if weigh_request is None and not (weigh_supabase_url and weigh_supabase_key):
        raise RuntimeError("Chưa cấu hình Supabase cân AI; cần ROLL_SCALE_API_URL và ROLL_SCALE_DEVICE_TOKEN")

    waiting = filter_waiting_candidates(
        items, work_date=ngay, shift=ca, machine=may, ma_sp=ma_sp
    )
    preview = waiting[:so_cuon]
    if not preview:
        raise ValueError("Không còn mã QR chờ nhập kho cho Mã SP này")
    event_ids = [str(row.get("event_id") or "").strip() for row in preview]
    if not all(event_ids):
        raise ValueError("Phiếu cân thiếu event_id; chưa thể đẩy kho")

    sync_summary: dict[str, object] = {"skipped": True}
    if run_manual_sync is not None:
        sync_summary = run_manual_sync()
    if sync_summary.get("state") == "error":
        raise RuntimeError("Đồng bộ cân AI lỗi: " + str(sync_summary.get("last_error") or "Hãy thử lại"))
    if set(event_ids).intersection(sync_summary.get("unsynced_event_ids") or []):
        raise RuntimeError("Chưa đồng bộ xong phiếu cân AI; chưa ghi kho. " + str(sync_summary.get("last_error") or "Hãy thử lại"))

    if weigh_request is not None:
        checked = weigh_request(event_ids, "")
        remote_rows = checked.get("items") or []
    else:
        remote_rows = fetch_can_tu_dong_by_event_ids(weigh_supabase_url, weigh_supabase_key, event_ids)
    remote_qrs = {
        str(row.get("event_id") or ""): normalize_qr_key(str(row.get("qr_code") or ""))
        for row in remote_rows if isinstance(row, dict)
    }
    if any(remote_qrs.get(event_id) != normalize_qr_key(str(row.get("qr_code") or ""))
           for event_id, row in zip(event_ids, preview)):
        raise RuntimeError("Chưa đồng bộ đủ QR lên Supabase cân AI; chưa ghi kho. Hãy kiểm tra kết nối và bấm lại")

    ma_phieu = new_phieu_nhap_code(may)
    warehouse_items = [
        {
            "ma_sp_quet": str(row.get("qr_code") or "").strip(),
            "ten_sp": str(row.get("ten_sp") or "").strip(),
            "don_vi": str(row.get("don_vi") or row.get("unit") or "").strip(),
            "event_id": str(row.get("event_id") or "").strip(),
        }
        for row in preview
        if str(row.get("qr_code") or "").strip()
    ]
    batch = write_nhap_kho_batch(
        kho_supabase_url(),
        kho_supabase_key(),
        ma_phieu=ma_phieu,
        ngay=ngay,
        nhan_su=nguoi or "Không rõ",
        nguoi_lap=may.strip(),
        kho=kho.strip(),
        ca=ca.strip(),
        may=may.strip(),
        items=warehouse_items,
    )
    saved_codes = {
        normalize_qr_key(str(row.get("ma_sp_quet") or ""))
        for row in (batch.get("saved") or [])
        if isinstance(row, dict)
    }
    duplicates = [
        str(code)
        for code in (batch.get("duplicateCodes") or [])
        if str(code or "").strip()
    ]
    saved_rows = [
        row
        for row in preview
        if normalize_qr_key(str(row.get("qr_code") or "")) in saved_codes
    ]
    if not saved_rows:
        raise RuntimeError(
            f"Không ghi được mã mới. {len(duplicates)} mã QR đã có trong nhap_kho."
            if duplicates
            else "Không ghi được mã QR vào nhap_kho."
        )

    receipts_by_code = {
        normalize_qr_key(str(row.get("ma_sp_quet") or "")): str(row.get("ma_phieu") or ma_phieu)
        for row in (batch.get("saved") or []) if isinstance(row, dict)
    }
    groups: dict[str, list[dict[str, object]]] = {}
    for row in saved_rows:
        receipt = receipts_by_code[normalize_qr_key(str(row.get("qr_code") or ""))]
        groups.setdefault(receipt, []).append(row)
    status_update: dict[str, object] = {}
    for receipt, group in groups.items():
        group_ids = [str(row["event_id"]) for row in group]
        try:
            if weigh_request is not None:
                status_update = weigh_request(group_ids, receipt)
            else:
                status_update = update_can_tu_dong_nhap_kho(
                    weigh_supabase_url, weigh_supabase_key, group_ids,
                    nguoi=nguoi or "Không rõ", ma_phieu=receipt,
                )
            if status_update.get("confirmed_count") != len(set(group_ids)):
                raise RuntimeError("Supabase cân AI chưa xác nhận đủ trạng thái nhập kho")
        except Exception as exc:
            raise RuntimeError(
                f"Đã ghi kho chờ, phiếu {receipt}, nhưng cập nhật cân AI lỗi: {exc}. "
                "Bấm Nhập kho lại để hoàn tất; QR đã ghi sẽ được dùng lại, không tạo trùng"
            ) from exc
        luc = str(status_update.get("nhap_kho_luc") or datetime.now(timezone.utc).isoformat())
        boi = str(status_update.get("nhap_kho_boi") or nguoi or "Không rõ")
        if update_local_row is not None:
            for row in group:
                update_local_row(str(row["event_id"]), NHAP_KHO_DA, luc, boi, receipt)

    return {
        "ok": True,
        "ma_phieu": next(iter(groups)),
        "ma_phieu_list": list(groups),
        "saved": [str(row.get("qr_code") or "") for row in saved_rows],
        "saved_count": len(saved_rows),
        "duplicateCodes": duplicates,
        "duplicate_count": len(duplicates),
        "recovered_count": sum(bool(row.get("recovered")) for row in (batch.get("saved") or []) if isinstance(row, dict)),
        "nhap_kho_trang_thai": NHAP_KHO_DA,
        "nhap_kho_luc": luc,
        "nhap_kho_boi": boi,
        "sync": sync_summary,
        "status_update": status_update,
        "kho": kho.strip(),
        "source": kho_db_label(),
    }
