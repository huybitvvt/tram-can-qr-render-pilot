from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import inspect
import sys
import threading
import time
import unicodedata
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from .factory_dataset import FactorySampleStore
from .gemini_weight import (
    DEFAULT_GEMINI_31_MODEL,
    DEFAULT_GEMINI_31_TIMEOUT_SECONDS,
    DEFAULT_GEMINI_37_MODEL,
    DEFAULT_GEMINI_37_TIMEOUT_SECONDS,
    DEFAULT_GEMINI_ACCURATE_MODEL,
    DEFAULT_GEMINI_ACCURATE_TIMEOUT_SECONDS,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GEMINI_TIMEOUT_SECONDS,
    GeminiWeightReader,
)
from .gemini_key_manager import GeminiKeyManager
from .codex_weight import DEFAULT_CODEX_TIMEOUT_SECONDS, CodexWeightReader
from .codex_oauth import CodexOAuthClient, EncryptedCodexTokenStore
from .codex_oauth_weight import CodexOAuthWeightReader
from .capture_gate import frame_fingerprint
from .api_client import (
    fetch_remote_json,
    fetch_remote_measurement_page,
    fetch_remote_weigh_batches,
    fetch_supabase_photo_drafts,
    fetch_supabase_rows,
    fetch_supabase_table,
    fetch_supabase_table_count,
    mutate_remote_measurement,
    post_remote_action,
    persist_product_evidence,
    sign_storage_image,
)
from .inference_queue import InferenceCoordinator, InferenceQueueFull
from .lookup_client import lookup_roll
from .quality import FrameQuality, assess_frame_quality
from .qr_reader import QRReader
from .scale import WeightReading
from .weight_limits import validate_production_weights
from .station_session import (
    AnalysisBindingMismatch,
    AnalysisBindingNotFound,
    SessionConflictError,
    StationSessionRegistry,
    encode_staged_jpeg,
    jpeg_sha256,
)
from .storage import EventIdConflictError, MeasurementStore
from .sync import OutboxSyncWorker
from .weight_ocr import (
    CameraOCRWeightSource,
    NormalizedROI,
    PADDLE_OCR_MODEL_NAME,
    PaddleOCRTextReader,
    detect_weight_roi,
    detect_weight_roi_consensus,
    parse_normalized_roi,
)


MAX_REQUEST_BYTES = 24 * 1024 * 1024
SESSION_COOKIE_NAME = "tram_can_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600
LOGIN_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Đăng nhập · Cân kiểm kho</title>
<style>
body{margin:0;font:16px/1.45 Roboto,sans-serif;background:#f1f2f4;color:#151517;padding:24px 16px calc(24px + env(safe-area-inset-bottom))}
.card{max-width:420px;margin:12vh auto 0;background:#fff;border:1px solid #d9dadd;border-radius:14px;padding:22px;box-shadow:0 8px 28px #15151712}
h1{margin:0 0 8px;font-size:22px}p{margin:0 0 16px;color:#666a73}
label{display:block;font-size:12px;font-weight:700;color:#666a73;margin:10px 0 5px}
input{width:100%;box-sizing:border-box;padding:12px 10px;border:1px solid #b8bac0;border-radius:8px;font:inherit}
button{width:100%;margin-top:16px;min-height:48px;border:0;border-radius:8px;background:#d71920;color:#fff;font-weight:800;font-size:16px}
.status{margin-top:12px;min-height:1.4em;color:#8d1420}
</style></head><body>
<form class="card" id="loginForm">
<h1>Cân kiểm kho</h1>
<p>Dùng được khi web khác nhúng (iframe). Đăng nhập xong giữ phiên trong trang nhúng, không cần cookie bên thứ ba.</p>
<label for="username">Tên đăng nhập</label>
<input id="username" name="username" autocomplete="username" required>
<label for="password">Mật khẩu</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Vào cân kiểm kho</button>
<div id="status" class="status"></div>
</form>
<script>
const params=new URLSearchParams(location.search),next=params.get('next')||'/kiem-kho';
document.getElementById('loginForm').addEventListener('submit',async event=>{
 event.preventDefault();
 const status=document.getElementById('status');
 status.textContent='Đang đăng nhập…';
 try{
  const response=await fetch('/api/login',{method:'POST',credentials:'include',headers:{'content-type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value.trim(),password:document.getElementById('password').value,next})});
  const data=await response.json();
  if(!response.ok)throw new Error(data.message||data.error||'Đăng nhập thất bại');
  if(data.session){
   try{localStorage.setItem('tram_can_session',data.session)}catch{}
   try{sessionStorage.setItem('tram_can_session',data.session)}catch{}
   try{window.name='tram_can_session='+data.session}catch{}
  }
  try{if(window.parent!==window&&data.session)window.parent.postMessage({source:'tram-can',type:'session',session:data.session},'*')}catch{}
  const target=new URL(data.next||'/kiem-kho',location.origin);
  if(data.session){target.searchParams.set('session',data.session);target.hash='session='+encodeURIComponent(data.session)}
  location.replace(target.pathname+target.search+target.hash);
 }catch(error){status.textContent=error.message}
});
</script>
</body></html>
"""


def _session_secret(password: str) -> bytes:
    return hashlib.sha256(f"tram-can-session|{password}".encode("utf-8")).digest()


def encode_session_cookie(username: str, password: str, expires_at: int) -> str:
    payload = f"{username}|{expires_at}"
    digest = hmac.new(_session_secret(password), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{digest}".encode("utf-8")).decode("ascii").rstrip("=")


def decode_session_cookie(value: str, username: str, password: str) -> bool:
    if not value or not username or not password:
        return False
    padded = value + "=" * ((4 - len(value) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        stored_user, expires_text, digest = decoded.split("|", 2)
        expires_at = int(expires_text)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    if stored_user != username or expires_at < int(time.time()):
        return False
    expected = hmac.new(
        _session_secret(password),
        f"{stored_user}|{expires_at}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, expected)


def _secrets_match(left: str, right: str) -> bool:
    try:
        return hmac.compare_digest(left, right)
    except (TypeError, ValueError):
        return False


def safe_login_next(value: str) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    if parsed.scheme or parsed.netloc:
        return "/kiem-kho"
    path = parsed.path or "/kiem-kho"
    if path not in {"/", "/kiem-kho"}:
        return "/kiem-kho"
    query = f"?{parsed.query}" if parsed.query else ""
    return path + query


def allowed_embed_origins() -> list[str]:
    raw = os.environ.get("ROLL_SCALE_EMBED_ORIGINS", "*").strip() or "*"
    return [item.strip() for item in raw.split(",") if item.strip()]


MAX_BURST_FRAMES = 9
DEFAULT_WEIGHT_BURST_FRAMES = 5
UNITS = {"kg", "g", "lb"}
WEIGHT_ENGINES = {"local", "hybrid", "gemini"}
GEMINI_RECOGNITION_PROFILES = {"flash31", "fast", "flash37", "accurate"}
AI_RECOGNITION_PROVIDERS = {"gemini", "codex"}
PRODUCTION_ORDER_TABLES = (
    "lenh_san_xuat",
    "Lenh_San_Xuat",
    "Lệnh Sản xuất",
    "Lệnh sản xuất",
    "lenh_sx",
    "production_orders",
    "lsx",
)
PRODUCTION_ORDER_FIELDS = (
    "production_order",
    "ma_lsx",
    "ma_lenh_sx",
    "mã lệnh",
    "ma lenh",
    "so_lsx",
    "so_lenh",
    "lenh_sx",
    "ma_lenh",
    "ten_lsx",
    "ten_lenh_sx",
    "order_code",
    "order_no",
    "lsx",
    "ma",
    "code",
)
PRODUCTION_ORDER_DATE_FIELDS = (
    "work_date",
    "ngay",
    "ngay_lsx",
    "ngay_san_xuat",
    "ngay_sx",
    "date",
    "bat_dau",
    "ngay_bat_dau",
    "bắt đầu",
    "bat dau",
)
PRODUCTION_ORDER_SHIFT_FIELDS = (
    "shift",
    "ca",
    "ca_lam_viec",
    "ca_sx",
    "shift_code",
)
PRODUCTION_ORDER_PRODUCT_FIELDS = (
    "ten_hang",
    "tên hàng",
    "ten_hang_sp",
    "ma_hang",
    "mã hàng",
    "product_name",
    "ten_sp",
)
MACHINE_PRODUCT_HINTS: dict[str, tuple[str, ...]] = {
    "Máy cách nhiệt": ("cach nhiet", "ranko", "tam cach"),
    "Máy Bao Bì": ("bao bi", "bao goi", "dong goi"),
    "Máy tái chế": ("tai che", "tai che"),
}
PRODUCTION_ORDER_MACHINE_FIELDS = (
    "machine",
    "may",
    "máy",
    "ten_may",
    "ma_may",
    "loai_may",
    "machine_name",
)


def _production_order_product_text(row: dict[str, object]) -> str:
    return _row_field(row, PRODUCTION_ORDER_PRODUCT_FIELDS)


def _shifts_match(row_shift: str, wanted: str) -> bool:
    if not wanted:
        return True
    if not row_shift:
        return True
    left = _normalize_field_key(row_shift).replace(" ", "")
    right = _normalize_field_key(wanted).replace(" ", "")
    return left == right or left in right or right in left


def _machine_labels_match(row_machine: str, wanted: str) -> bool:
    if not wanted:
        return True
    if not row_machine:
        return False
    left = _normalize_field_key(row_machine)
    right = _normalize_field_key(wanted)
    if left == right or left in right or right in left:
        return True
    left_compact = left.replace(" ", "")
    right_compact = right.replace(" ", "")
    return left_compact == right_compact or left_compact in right_compact or right_compact in left_compact


def _machine_matches_row(row: dict[str, object], machine: str) -> bool:
    if not machine:
        return True
    row_machine = _production_order_machine(row)
    if row_machine:
        return _machine_labels_match(row_machine, machine)
    product = _normalize_field_key(_production_order_product_text(row))
    if not product:
        return True
    hints = MACHINE_PRODUCT_HINTS.get(machine, ())
    if not hints:
        return True
    return any(hint in product for hint in hints)


def _supabase_project_url() -> str:
    configured = os.environ.get("ROLL_SCALE_SUPABASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    api_url = os.environ.get("ROLL_SCALE_API_URL", "").strip()
    marker = "/functions/v1/"
    if marker in api_url:
        return api_url.split(marker, 1)[0].rstrip("/")
    for candidate in (
        Path(__file__).resolve().parents[3] / "supabase" / ".temp" / "linked-project.json",
        Path(__file__).resolve().parents[3] / "backend" / "supabase" / ".temp" / "linked-project.json",
    ):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        project_ref = str(payload.get("ref") or "").strip()
        if project_ref:
            return f"https://{project_ref}.supabase.co"
    return ""


def _supabase_read_key() -> str:
    return (
        os.environ.get("ROLL_SCALE_SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("ROLL_SCALE_SUPABASE_PUBLISHABLE_KEY", "").strip()
    )


def _production_order_supabase_url() -> str:
    return (
        os.environ.get("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL", "").strip().rstrip("/")
        or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").strip().rstrip("/")
    )


def _production_order_supabase_key() -> str:
    return (
        os.environ.get("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_KEY", "").strip()
        or os.environ.get("ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "").strip()
    )


def _production_orders_from_supabase_tables(
    supabase_url: str,
    supabase_key: str,
    work_date: str,
    *,
    shift: str = "",
    machine: str = "",
    source_prefix: str = "master",
) -> tuple[list[str], str, str]:
    fallback_error = ""
    queried_ok = False
    last_table = ""
    for table in _configured_production_order_tables():
        try:
            rows = fetch_supabase_rows(supabase_url, supabase_key, table)
            queried_ok = True
            last_table = table
            orders = _production_orders_from_master(
                rows, work_date, shift=shift, machine=machine
            )
            if orders:
                return orders, f"{source_prefix}:{table}", ""
        except Exception as exc:
            fallback_error = fallback_error or str(exc)
    if queried_ok:
        detail = f"ngày {work_date}"
        if shift:
            detail += f", ca {shift}"
        if machine:
            detail += f", máy {machine}"
        return [], f"{source_prefix}:{last_table}", f"Không có LSX cho {detail}"
    return [], source_prefix, fallback_error


def _master_production_orders_configured() -> bool:
    return bool(_production_order_supabase_url() and _production_order_supabase_key())


def _raw_tag(raw: str, name: str) -> str:
    match = re.search(rf"(?:^|; )\s*{re.escape(name)}=([^;]+)", raw or "")
    return match.group(1).strip() if match else ""


def _item_work_date(captured_at: str, weight_raw: str = "") -> str:
    tagged = _raw_tag(weight_raw, "SOURCE_DATE")
    if tagged:
        return tagged
    text = str(captured_at or "")
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def _item_source_value(item: dict[str, object], field: str, tag: str) -> str:
    direct = str(item.get(field) or "").strip()
    if direct:
        return direct
    metadata = item.get("metadata")
    if isinstance(metadata, dict):
        metadata_value = str(metadata.get(field) or "").strip()
        if metadata_value:
            return metadata_value
        raw = str(metadata.get("weight_raw") or item.get("weight_raw") or "")
    else:
        raw = str(item.get("weight_raw") or "")
    return _raw_tag(raw, tag)


def _item_source_date(item: dict[str, object]) -> str:
    selected = _item_source_value(item, "work_date", "SOURCE_DATE")
    if selected:
        return selected
    metadata = item.get("metadata")
    raw = (
        str(metadata.get("weight_raw") or "")
        if isinstance(metadata, dict)
        else str(item.get("weight_raw") or "")
    )
    return _item_work_date(str(item.get("captured_at") or ""), raw)


def _item_error_status(item: dict[str, object]) -> str:
    value = _item_source_value(item, "error_status", "ERROR_STATUS").lower()
    return "error" if value == "error" else "ok"


def _item_error_reason(item: dict[str, object]) -> str:
    if _item_error_status(item) != "error":
        return ""
    return _item_source_value(item, "error_reason", "ERROR_REASON")[:500]


def _project_root() -> Path:
    candidate = Path(__file__).resolve().parents[3]
    if (candidate / ".env").is_file() or (candidate / "frontend" / "index.html").is_file():
        return candidate
    cwd = Path.cwd()
    if (cwd / ".env").is_file() or (cwd / "frontend" / "index.html").is_file():
        return cwd
    return candidate


def _load_local_dotenv() -> None:
    env_path = _project_root() / ".env"
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (key not in os.environ or not str(os.environ.get(key, "")).strip()):
            os.environ[key] = value


def _ingest_api_url() -> str:
    return os.environ.get("ROLL_SCALE_API_URL", "").strip()


def _ingest_api_token() -> str:
    return (
        os.environ.get("ROLL_SCALE_DEVICE_TOKEN", "").strip()
        or os.environ.get("ROLL_SCALE_LOOKUP_TOKEN", "").strip()
    )


def _fetch_ingest_measurements_paged(
    api_url: str,
    api_token: str,
    *,
    limit: int,
    offset: int = 0,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
) -> tuple[list[dict[str, object]], int | None]:
    """Pull cloud rows in pages until the requested window is filled."""

    wanted = max(1, min(int(limit), 2000))
    page_size = min(200, wanted)
    items: list[dict[str, object]] = []
    next_offset = max(0, int(offset))
    total_count: int | None = None
    for _ in range(25):
        batch, batch_total = fetch_remote_measurement_page(
            api_url,
            api_token,
            limit=page_size,
            offset=next_offset,
            work_date=work_date,
            date_from=date_from,
            date_to=date_to,
            shift=shift,
            machine=machine,
            production_order=production_order,
            qr_code=qr_code,
        )
        if total_count is None:
            total_count = batch_total
        if not batch:
            break
        items.extend(batch)
        if len(batch) < page_size or len(items) >= wanted:
            break
        next_offset += len(batch)
    return items[:wanted], total_count


def _looks_like_measurement_items(items: list[dict[str, object]]) -> bool:
    if not items:
        return False
    sample = items[: min(3, len(items))]
    return all(
        "weight" in item or "qr_code" in item or "event_id" in item for item in sample
    )


def _load_production_orders_once(
    work_date: str,
    shift: str = "",
    machine: str = "",
) -> tuple[list[str], str, str]:
    _load_local_dotenv()
    fallback_error = ""
    master_url = _production_order_supabase_url()
    master_key = _production_order_supabase_key()
    if master_url and master_key:
        orders, source, master_error = _production_orders_from_supabase_tables(
            master_url,
            master_key,
            work_date,
            shift=shift,
            machine=machine,
            source_prefix="master",
        )
        if orders:
            return orders, source, ""
        fallback_error = master_error
        return [], source, fallback_error or (
            f"Không có LSX cho ngày {work_date}, ca {shift}, máy {machine}"
            if machine
            else f"Không có LSX cho ngày {work_date}, ca {shift}"
        )
    api_url = _ingest_api_url()
    api_token = _ingest_api_token()
    query_params: dict[str, object] = {
        "action": "production-orders",
        "work_date": work_date,
    }
    if shift:
        query_params["shift"] = shift
    if machine:
        query_params["machine"] = machine
    if api_url and api_token:
        try:
            remote = fetch_remote_json(
                api_url,
                api_token,
                params=query_params,
            )
            if remote.get("ok") is True and isinstance(remote.get("orders"), list):
                orders = [
                    str(item).strip()
                    for item in remote["orders"]
                    if str(item).strip()
                ]
                if orders:
                    return orders, str(remote.get("source") or "lenh_san_xuat"), ""
            if remote.get("ok") is True and isinstance(remote.get("items"), list):
                items = [item for item in remote["items"] if isinstance(item, dict)]
                if _looks_like_measurement_items(items):
                    fallback_error = (
                        "Cloud chưa trả bảng lệnh SX; cần deploy ingest-measurement "
                        "hoặc thêm ROLL_SCALE_SUPABASE_SERVICE_KEY vào .env"
                    )
                else:
                    orders = _production_orders_from_master(
                        items, work_date, shift=shift, machine=machine
                    )
                    if orders:
                        return orders, str(remote.get("source") or "lenh_san_xuat"), ""
        except Exception as exc:
            fallback_error = str(exc)
    supabase_url = _supabase_project_url()
    publishable_key = _supabase_read_key()
    if supabase_url and publishable_key and (
        not master_url or supabase_url.rstrip("/") != master_url.rstrip("/")
    ):
        orders, source, table_error = _production_orders_from_supabase_tables(
            supabase_url,
            publishable_key,
            work_date,
            shift=shift,
            machine=machine,
            source_prefix="ingest",
        )
        if orders:
            return orders, source, fallback_error or table_error
        fallback_error = fallback_error or table_error
    elif supabase_url and not publishable_key and not master_key:
        fallback_error = fallback_error or (
            "Thiếu key LSX: đặt ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL + "
            "ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_SERVICE_KEY "
            "(hoặc ROLL_SCALE_SUPABASE_PUBLISHABLE_KEY nếu dùng cùng project ingest)"
        )
    elif not master_url and not supabase_url:
        fallback_error = fallback_error or (
            "Thiếu ROLL_SCALE_PRODUCTION_ORDER_SUPABASE_URL trong .env / Render"
        )
    return [], "local", fallback_error


def _load_production_orders(
    work_date: str,
    shift: str = "",
    machine: str = "",
) -> tuple[list[str], str, str, str | None]:
    _load_local_dotenv()
    orders, source, fallback_error = _load_production_orders_once(
        work_date, shift=shift, machine=machine
    )
    if orders:
        return orders, source, fallback_error, None
    # Nới dần bộ lọc để vẫn hiện LSX trong ngày khi ca/máy lệch nhẹ.
    if machine:
        relaxed_orders, relaxed_source, relaxed_error = _load_production_orders_once(
            work_date, shift=shift, machine=""
        )
        if relaxed_orders:
            return (
                relaxed_orders,
                relaxed_source,
                relaxed_error or fallback_error,
                "machine",
            )
    if shift or machine:
        day_orders, day_source, day_error = _load_production_orders_once(
            work_date, shift="", machine=""
        )
        if day_orders:
            return (
                day_orders,
                day_source,
                day_error or fallback_error,
                "shift" if shift and not machine else "shift+machine",
            )
    return orders, source, fallback_error, None


def _master_production_order_rows() -> tuple[list[dict[str, object]], str]:
    """Đọc toàn bộ dòng LSX master (để gợi ý ca/máy theo ngày)."""
    _load_local_dotenv()
    master_url = _production_order_supabase_url()
    master_key = _production_order_supabase_key()
    if not (master_url and master_key):
        return [], ""
    last_table = ""
    for table in _configured_production_order_tables():
        try:
            rows = fetch_supabase_rows(master_url, master_key, table)
            last_table = table
            if rows:
                return rows, table
        except Exception:
            continue
    return [], last_table


def _production_order_suggestions(work_date: str) -> list[dict[str, object]]:
    rows, _table = _master_production_order_rows()
    if not rows:
        return []
    return _production_order_suggestions_from_rows(rows, work_date)


def _production_order_filter_options(
    work_date: str = "",
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Ca / máy / gợi ý lấy từ bảng LSX (DB), không hardcode."""
    rows, _table = _master_production_order_rows()
    if not rows:
        return [], [], []
    suggestions = (
        _production_order_suggestions_from_rows(rows, work_date) if work_date else []
    )
    day_shifts: set[str] = set()
    day_machines: set[str] = set()
    all_shifts: set[str] = set()
    all_machines: set[str] = set()
    for row in rows:
        shift = _production_order_shift(row).strip()
        machine = _production_order_machine(row).strip()
        if shift:
            all_shifts.add(shift)
        if machine:
            all_machines.add(machine)
        if work_date and _row_matches_production_filters(row, work_date=work_date):
            if shift:
                day_shifts.add(shift)
            if machine:
                day_machines.add(machine)
    shifts = sorted(day_shifts or all_shifts, key=str.casefold)
    machines = sorted(day_machines or all_machines, key=str.casefold)
    return shifts, machines, suggestions


def _production_orders_for_date(
    items: list[dict[str, object]], work_date: str
) -> list[str]:
    orders = {
        _item_source_value(item, "production_order", "SOURCE_PRODUCTION_ORDER")
        for item in items
        if _item_source_date(item) == work_date
    }
    return sorted((order for order in orders if order), key=str.casefold)


def _normalize_source_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    match = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", text)
    if not match:
        return ""
    first, second, year = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if first > 12 and second <= 12:
        day, month = first, second
    elif second > 12 and first <= 12:
        day, month = second, first
    else:
        day, month = first, second
    if month > 12 or day > 31:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _normalize_field_key(key: object) -> str:
    text = unicodedata.normalize("NFD", str(key or "").strip().lower())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _row_field(
    row: dict[str, object],
    names: tuple[str, ...],
    *,
    fuzzy: bool = False,
    fuzzy_tokens: tuple[str, ...] = ("lsx", "lenh", "order"),
) -> str:
    lowered = {
        _normalize_field_key(key): value for key, value in row.items()
    }
    for name in names:
        value = lowered.get(_normalize_field_key(name))
        text = str(value or "").strip()
        if text:
            return text[:80]
    if fuzzy:
        for key, value in lowered.items():
            if any(token in key for token in fuzzy_tokens):
                text = str(value or "").strip()
                if text:
                    return text[:80]
    return ""


def _production_order_code(row: dict[str, object]) -> str:
    direct = _item_source_value(row, "production_order", "SOURCE_PRODUCTION_ORDER")
    if direct:
        return direct[:80]
    return _row_field(row, PRODUCTION_ORDER_FIELDS, fuzzy=True)


def _production_order_date(row: dict[str, object]) -> str:
    selected = _item_source_date(row)
    if selected:
        return selected
    return _normalize_source_date(_row_field(row, PRODUCTION_ORDER_DATE_FIELDS))


def _production_order_shift(row: dict[str, object]) -> str:
    direct = _item_source_value(row, "shift", "SOURCE_SHIFT")
    if direct:
        return direct
    return _row_field(row, PRODUCTION_ORDER_SHIFT_FIELDS)


def _production_order_machine(row: dict[str, object]) -> str:
    direct = _item_source_value(row, "machine", "SOURCE_MACHINE")
    if direct:
        return direct
    return _row_field(row, PRODUCTION_ORDER_MACHINE_FIELDS)


def _row_matches_production_filters(
    row: dict[str, object],
    *,
    work_date: str = "",
    shift: str = "",
    machine: str = "",
) -> bool:
    if work_date:
        row_date = _production_order_date(row)
        if row_date and row_date != work_date:
            return False
    if shift:
        row_shift = _production_order_shift(row)
        if not _shifts_match(row_shift, shift):
            return False
    if machine:
        if not _machine_matches_row(row, machine):
            return False
    return True


def _production_orders_from_master(
    rows: list[dict[str, object]],
    work_date: str = "",
    *,
    shift: str = "",
    machine: str = "",
) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for row in rows:
        code = _production_order_code(row)
        if not code:
            continue
        if not _row_matches_production_filters(
            row, work_date=work_date, shift=shift, machine=machine
        ):
            continue
        key = code.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(code)
    return sorted(unique, key=str.casefold)


def _production_order_suggestions_from_rows(
    rows: list[dict[str, object]],
    work_date: str,
) -> list[dict[str, object]]:
    """Gợi ý ca · máy · LSX còn trong ngày khi bộ lọc hiện tại trống."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if not _row_matches_production_filters(row, work_date=work_date):
            continue
        code = _production_order_code(row)
        if not code:
            continue
        shift = _production_order_shift(row) or "—"
        machine = _production_order_machine(row) or "—"
        bucket = grouped.setdefault((shift, machine), [])
        if code not in bucket:
            bucket.append(code)
    suggestions: list[dict[str, object]] = []
    for (shift, machine), orders in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1])
    ):
        suggestions.append(
            {
                "shift": shift,
                "machine": machine,
                "orders": sorted(orders, key=str.casefold),
            }
        )
    return suggestions


def _configured_production_order_tables() -> list[str]:
    configured = os.environ.get("ROLL_SCALE_PRODUCTION_ORDER_TABLE", "").strip()
    tables = [configured] if configured else []
    tables.extend(PRODUCTION_ORDER_TABLES)
    unique: list[str] = []
    seen: set[str] = set()
    for table in tables:
        if not table or table in seen:
            continue
        seen.add(table)
        unique.append(table)
    return unique


def _matches_source_filters(
    item: dict[str, object],
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
) -> bool:
    needs_date = bool(work_date or date_from or date_to)
    item_date = _item_source_date(item) if needs_date else ""
    if work_date:
        if item_date != work_date:
            return False
    else:
        if date_from and (not item_date or item_date < date_from):
            return False
        if date_to and (not item_date or item_date > date_to):
            return False
    if shift:
        item_shift = _item_source_value(item, "shift", "SOURCE_SHIFT")
        if item_shift and item_shift != shift:
            return False
        if not item_shift:
            # Legacy rows without source tags still show for the selected day.
            pass
    if machine:
        item_machine = _item_source_value(item, "machine", "SOURCE_MACHINE")
        if item_machine and item_machine != machine:
            return False
    if production_order:
        item_order = _item_source_value(
            item, "production_order", "SOURCE_PRODUCTION_ORDER"
        )
        if item_order and item_order != production_order:
            return False
    if qr_code:
        needle = str(qr_code).strip().casefold()
        haystack = str(item.get("qr_code") or "").strip().casefold()
        if not needle or needle not in haystack:
            return False
    return True


def _merge_source_tags(weight_raw: str, payload: dict[str, object]) -> str:
    """Ensure Ca / Máy / Lệnh sản xuất tags are present for Supabase metadata."""

    raw = str(weight_raw or "").strip()
    extras: list[str] = []
    mapping = (
        ("work_date", "SOURCE_DATE"),
        ("shift", "SOURCE_SHIFT"),
        ("machine", "SOURCE_MACHINE"),
        ("production_order", "SOURCE_PRODUCTION_ORDER"),
    )
    for field, tag in mapping:
        value = re.sub(r"[;\r\n]+", " ", str(payload.get(field, "") or "")).strip()
        if not value or _raw_tag(raw, tag):
            continue
        extras.append(f"{tag}={value[:80]}")
    if not _raw_tag(raw, "BI_WEIGHT"):
        bi_value = payload.get("bi_weight", payload.get("bi"))
        try:
            bi_number = float(bi_value) if bi_value is not None and bi_value != "" else 0.16
        except (TypeError, ValueError):
            bi_number = 0.16
        if bi_number < 0:
            bi_number = 0.16
        extras.append(f"BI_WEIGHT={bi_number:g}")
    if not extras:
        return raw
    prefix = "; ".join(extras)
    return f"{prefix}; {raw}" if raw else prefix


def _persistable_weight_raw(
    weight_raw: str,
    *,
    weight: float,
    vision_confirmed: bool,
) -> str:
    raw = str(weight_raw or "").strip()
    if not vision_confirmed:
        if not raw.startswith("MANUAL:"):
            raw = f"MANUAL:{weight}" + (f"; {raw}" if raw else "")
    return raw[:1000]


def _local_measurement_items(
    store: MeasurementStore,
    limit: int,
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in store.recent(max(limit, 200)):
        product_weight = item.product_weight
        if product_weight is None:
            match = re.search(
                r"(?:^|; )PRODUCT_WEIGHT=([0-9]+(?:\.[0-9]+)?)",
                item.weight_raw or "",
            )
            product_weight = float(match.group(1)) if match else None
        has_core = bool(item.image_path and Path(item.image_path).is_file())
        has_product = bool(
            item.product_image_path and Path(item.product_image_path).is_file()
        )
        core_url = (
            f"/api/measurement-image?event_id={urllib.parse.quote(item.event_id)}&kind=core"
            if has_core
            else item.remote_image_url
        )
        product_url = (
            f"/api/measurement-image?event_id={urllib.parse.quote(item.event_id)}&kind=product"
            if has_product
            else None
        )
        source_item = {
            "captured_at": item.captured_at,
            "weight_raw": item.weight_raw or "",
            "qr_code": item.qr_code,
        }
        payload = {
            "event_id": item.event_id,
            "qr_code": item.qr_code,
            "core_weight": item.weight,
            "product_weight": product_weight,
            "weight_raw": item.weight_raw
            or (
                f"PRODUCT_WEIGHT={product_weight}"
                if product_weight is not None
                else ""
            ),
            "unit": item.unit,
            "captured_at": item.captured_at,
            "work_date": _item_source_date(source_item),
            "shift": _item_source_value(source_item, "shift", "SOURCE_SHIFT"),
            "machine": _item_source_value(source_item, "machine", "SOURCE_MACHINE"),
            "production_order": _item_source_value(
                source_item, "production_order", "SOURCE_PRODUCTION_ORDER"
            ),
            "error_status": _item_error_status(source_item),
            "error_reason": _item_error_reason(source_item),
            "sync_status": item.sync_status,
            "sync_error": item.sync_error,
            "core_image_url": core_url,
            "product_image_url": product_url,
            "has_core_image": bool(core_url),
            "has_product_image": bool(product_url),
        }
        if _matches_source_filters(
            payload,
            work_date=work_date,
            date_from=date_from,
            date_to=date_to,
            shift=shift,
            machine=machine,
            production_order=production_order,
            qr_code=qr_code,
        ):
            items.append(payload)
        if len(items) >= limit:
            break
    return items


def _photo_draft_display_items(
    rows: list[dict[str, object]],
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
) -> list[dict[str, object]]:
    """Group saved unreadable core/product photos into visible production rows."""

    grouped: dict[str, dict[str, object]] = {}
    image_times: dict[tuple[str, str], str] = {}
    sync_states: dict[str, set[str]] = {}
    sync_errors: dict[str, set[str]] = {}
    for item in rows:
        parent_id = str(
            item.get("parent_event_id") or item.get("event_id") or ""
        ).strip()
        if not parent_id:
            continue
        captured_at = str(item.get("captured_at") or "")
        payload = grouped.setdefault(
            parent_id,
            {
                "event_id": parent_id,
                "qr_code": "",
                "core_weight": "unread",
                "product_weight": "unread",
                "weight_raw": "",
                "unit": "kg",
                "captured_at": captured_at,
                "work_date": str(item.get("work_date") or ""),
                "shift": str(item.get("shift") or ""),
                "machine": str(item.get("machine") or ""),
                "production_order": str(item.get("production_order") or ""),
                "core_image_url": None,
                "product_image_url": None,
                "has_core_image": False,
                "has_product_image": False,
                "error_only": True,
                "error_status": "error",
                "error_reason": "AI chưa đọc được số cân",
                "record_note": "Ảnh đã lưu · AI chưa đọc được số cân",
            },
        )
        if captured_at > str(payload.get("captured_at") or ""):
            payload["captured_at"] = captured_at
        detected_qr = str(item.get("qr_code") or "").strip()
        if detected_qr and not payload["qr_code"]:
            payload["qr_code"] = detected_qr
        for field in ("work_date", "shift", "machine", "production_order"):
            value = str(item.get(field) or "").strip()
            if value and not payload[field]:
                payload[field] = value

        capture_id = str(item.get("event_id") or "").strip()
        image_path = str(item.get("image_path") or "").strip()
        remote_url = str(
            item.get("image_url") or item.get("remote_image_url") or ""
        ).strip()
        if image_path and Path(image_path).is_file() and capture_id:
            image_url = (
                "/api/photo-draft-image?event_id="
                + urllib.parse.quote(capture_id)
            )
        else:
            image_url = remote_url
        kind = str(item.get("capture_kind") or "core").strip().lower()
        if kind not in {"core", "product"}:
            kind = "core"
        image_key = (parent_id, kind)
        if image_url and captured_at >= image_times.get(image_key, ""):
            payload[f"{kind}_image_url"] = image_url
            payload[f"has_{kind}_image"] = True
            image_times[image_key] = captured_at

        state = str(item.get("sync_status") or "synced").strip().lower()
        sync_states.setdefault(parent_id, set()).add(state)
        error = str(item.get("sync_error") or "").strip()
        if error:
            sync_errors.setdefault(parent_id, set()).add(error)

    items: list[dict[str, object]] = []
    for parent_id, payload in grouped.items():
        states = sync_states.get(parent_id, {"synced"})
        storage_sync_status = (
            "failed"
            if "failed" in states
            else "pending"
            if "pending" in states
            else "local"
            if "local" in states
            else "synced"
        )
        payload["storage_sync_status"] = storage_sync_status
        payload["sync_status"] = storage_sync_status
        details = ["AI chưa đọc được số cân"]
        details.extend(sorted(sync_errors.get(parent_id, set())))
        payload["sync_error"] = " · ".join(details)
        if _matches_source_filters(
            payload,
            work_date=work_date,
            date_from=date_from,
            date_to=date_to,
            shift=shift,
            machine=machine,
            production_order=production_order,
            qr_code=qr_code,
        ):
            items.append(payload)
    return items


def _local_production_items(
    store: MeasurementStore,
    limit: int,
    **filters: object,
) -> list[dict[str, object]]:
    measurements = _local_measurement_items(store, max(limit, 200), **filters)
    measurement_ids = {
        str(item.get("event_id") or "").strip() for item in measurements
    }
    photo_items = [
        item
        for item in _photo_draft_display_items(
            store.photo_draft_source_rows(), **filters
        )
        if str(item.get("event_id") or "").strip() not in measurement_ids
    ]
    items = measurements + photo_items
    items.sort(key=lambda item: str(item.get("captured_at") or ""), reverse=True)
    return items[:limit]


def _local_measurement_event_ids(
    store: MeasurementStore,
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
    unsynced_only: bool = False,
) -> set[str]:
    event_ids: set[str] = set()
    for item in store.measurement_source_rows():
        if unsynced_only and str(item.get("sync_status") or "") == "synced":
            continue
        if _matches_source_filters(
            item,
            work_date=work_date,
            date_from=date_from,
            date_to=date_to,
            shift=shift,
            machine=machine,
            production_order=production_order,
            qr_code=qr_code,
        ):
            event_id = str(item.get("event_id") or "").strip()
            if event_id:
                event_ids.add(event_id)
    return event_ids


def _local_measurement_count(
    store: MeasurementStore,
    **filters: object,
) -> int:
    return len(_local_measurement_event_ids(store, **filters))


def _local_error_parent_ids(
    store: MeasurementStore,
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
    unsynced_only: bool = False,
) -> set[str]:
    parent_ids: set[str] = set()
    for item in store.photo_draft_source_rows():
        if unsynced_only and str(item.get("sync_status") or "") == "synced":
            continue
        if _matches_source_filters(
            item,
            work_date=work_date,
            date_from=date_from,
            date_to=date_to,
            shift=shift,
            machine=machine,
            production_order=production_order,
            qr_code=qr_code,
        ):
            parent_id = str(
                item.get("parent_event_id") or item.get("event_id") or ""
            ).strip()
            if parent_id:
                parent_ids.add(parent_id)
    return parent_ids


def _local_production_counts(
    store: MeasurementStore,
    **filters: object,
) -> tuple[int, int]:
    measurement_ids = _local_measurement_event_ids(store, **filters)
    error_ids = _local_error_parent_ids(store, **filters) - measurement_ids
    return len(measurement_ids | error_ids), len(error_ids)


def _local_inventory_items(
    store: MeasurementStore,
    limit: int,
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for item in store.recent_inventory_checks(limit):
        has_image = bool(item.image_path and Path(item.image_path).is_file())
        image_url = (
            f"/api/inventory-image?event_id={urllib.parse.quote(item.event_id)}"
            if has_image
            else item.remote_image_url
        )
        items.append(
            {
                "id": item.remote_id or item.id,
                "event_id": item.event_id,
                "ma_san_pham": item.product_code,
                "khoi_luong": item.weight,
                "khoi_luong_loi": item.core_weight,
                "khoi_luong_bi": item.tare_weight,
                "don_vi": item.unit,
                "captured_at": item.captured_at,
                "image_url": image_url,
                "sync_status": item.sync_status,
                "sync_error": item.sync_error,
            }
        )
    return items


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} phải là true hoặc false")


def decode_image(value: str) -> np.ndarray:
    encoded = value.split(",", 1)[1] if value.startswith("data:") and "," in value else value
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("Ảnh quá lớn")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Ảnh base64 không hợp lệ") from exc
    return decode_image_bytes(raw)


def decode_image_bytes(raw: bytes) -> np.ndarray:
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("Ảnh quá lớn")
    frame = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Không giải mã được ảnh")
    return frame


def _upsert_raw_tag(raw: str, name: str, value: str) -> str:
    raw = str(raw or "").strip()
    token = f"{name}={value}"
    pattern = rf"(?:^|; )\s*{re.escape(name)}=[^;]*"
    if re.search(pattern, raw):
        return re.sub(pattern, f"; {token}", raw).lstrip("; ").strip()
    if not raw:
        return token
    return f"{raw}; {token}"


def _download_image_bytes(url: str, *, timeout: float = 45.0) -> bytes:
    url = str(url or "").strip()
    if not url:
        raise ValueError("Thiếu URL ảnh")
    if url.startswith("/") or "://" not in url:
        raise ValueError("URL ảnh không hợp lệ")
    request = urllib.request.Request(
        url,
        headers={"Accept": "image/*,*/*", "User-Agent": "roll-qr-scale-reread/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Không tải được ảnh (HTTP {exc.code})") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Không tải được ảnh: {exc.reason}") from exc
    if not data:
        raise ValueError("Ảnh trống")
    if len(data) > MAX_REQUEST_BYTES:
        raise ValueError("Ảnh quá lớn")
    return data


def _resolve_measurement_image_bytes(
    store: MeasurementStore,
    *,
    event_id: str,
    kind: str,
    image_url: str = "",
) -> tuple[bytes, str]:
    kind = kind if kind in {"core", "product"} else ""
    if not kind:
        raise ValueError("kind phải là core hoặc product")
    local = store.get(event_id)
    if local is not None:
        local_path = Path(
            local.image_path if kind == "core" else local.product_image_path
        )
        if local_path.is_file():
            return local_path.read_bytes(), f"local:{local_path.name}"
        if kind == "core" and local.remote_image_url:
            image_url = image_url or local.remote_image_url
    image_url = str(image_url or "").strip()
    if image_url.startswith("/api/measurement-image"):
        if local is None:
            raise ValueError("Không có ảnh local cho event này")
        local_path = Path(
            local.image_path if kind == "core" else local.product_image_path
        )
        if not local_path.is_file():
            raise ValueError("Không tìm thấy file ảnh local")
        return local_path.read_bytes(), f"local:{local_path.name}"
    if image_url:
        return _download_image_bytes(image_url), image_url
    raise ValueError(
        "Không có ảnh "
        + ("lõi" if kind == "core" else "SP")
        + " để AI đọc lại"
    )


def _decode_product_qr_for_reread(
    service: object,
    frame: np.ndarray,
    client_qr: str = "",
) -> dict[str, object]:
    """Decode a saved product QR independently from weight AI/Gemini."""

    client_qr = str(client_qr or "").strip()
    if len(client_qr) > 512 or any(ord(character) < 32 for character in client_qr):
        raise ValueError("Mã QR từ trình duyệt không hợp lệ")
    decode = getattr(service, "_decode_qr")
    decoded = decode(frame)
    local_qr = (
        str(decoded.get("qr_code") or "").strip()
        if decoded.get("found")
        else ""
    )
    if client_qr and local_qr and client_qr != local_qr:
        return {
            "qr_code": "",
            "qr_found": False,
            "qr_conflict": True,
            "qr_decoder": "browser+backend-conflict",
        }
    if local_qr:
        decoder = f"camera:{decoded.get('decoder', 'local')}"
        if client_qr:
            decoder += "+browser-confirmed"
        return {
            "qr_code": local_qr,
            "qr_found": True,
            "qr_conflict": False,
            "qr_decoder": decoder,
        }
    if client_qr:
        return {
            "qr_code": client_qr,
            "qr_found": True,
            "qr_conflict": False,
            "qr_decoder": "browser-barcode-detector",
        }
    return {
        "qr_code": "",
        "qr_found": False,
        "qr_conflict": False,
        "qr_decoder": "",
    }


def _persist_measurement_edit(
    store: MeasurementStore,
    *,
    event_id: str,
    qr_code: str,
    core_weight: float,
    product_weight: float,
    work_date: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    error_status: str = "",
    error_reason: str = "",
    weight_raw: str = "",
) -> dict[str, object]:
    existing = store.get(event_id)
    existing_raw = str(getattr(existing, "weight_raw", "") or "")
    validate_production_weights(
        core_weight, product_weight, str(getattr(existing, "unit", "kg") or "kg"),
        machine or _raw_tag(weight_raw or existing_raw, "SOURCE_MACHINE"),
    )
    selected_error_status = str(error_status or "").strip().lower()
    if selected_error_status not in {"ok", "error"}:
        selected_error_status = (
            "error" if _raw_tag(weight_raw, "ERROR_STATUS").lower() == "error" else "ok"
        )
    selected_error_reason = (
        str(error_reason or _raw_tag(weight_raw, "ERROR_REASON")).strip()[:500]
        if selected_error_status == "error"
        else ""
    )
    error_status = selected_error_status
    error_reason = selected_error_reason
    remote_item: dict[str, object] | None = None
    cloud_error = ""
    ingest_url = _ingest_api_url()
    ingest_token = _ingest_api_token()
    if ingest_url and ingest_token:
        try:
            remote = mutate_remote_measurement(
                ingest_url,
                ingest_token,
                action="update_measurement",
                event_id=event_id,
                payload={
                    "qr_code": qr_code,
                    "core_weight": core_weight,
                    "product_weight": product_weight,
                    "work_date": work_date,
                    "shift": shift,
                    "machine": machine,
                    "production_order": production_order,
                    "error_status": error_status,
                    "error_reason": error_reason,
                },
            )
            item = remote.get("item")
            if isinstance(item, dict):
                remote_item = item
        except Exception as exc:
            cloud_error = str(exc)
    persist_raw = str(weight_raw or "").strip()
    if not persist_raw:
        if work_date:
            persist_raw = _upsert_raw_tag(persist_raw, "SOURCE_DATE", work_date)
        if shift:
            persist_raw = _upsert_raw_tag(persist_raw, "SOURCE_SHIFT", shift)
        if machine:
            persist_raw = _upsert_raw_tag(persist_raw, "SOURCE_MACHINE", machine)
        if production_order:
            persist_raw = _upsert_raw_tag(
                persist_raw, "SOURCE_PRODUCTION_ORDER", production_order
            )
        persist_raw = _upsert_raw_tag(persist_raw, "PRODUCT_WEIGHT", f"{product_weight:g}")
    persist_raw = _upsert_raw_tag(persist_raw, "ERROR_STATUS", error_status)
    persist_raw = _upsert_raw_tag(
        persist_raw,
        "ERROR_REASON",
        error_reason if error_status == "error" else "",
    )
    local_item = None
    try:
        local_item = store.update_measurement_fields(
            event_id,
            qr_code=qr_code,
            weight=core_weight,
            product_weight=product_weight,
            weight_raw=persist_raw,
        )
    except KeyError:
        if remote_item is None:
            raise ValueError(
                cloud_error or "Không tìm thấy dòng để sửa trên cloud/local"
            ) from None
    return {
        "ok": True,
        "updated": True,
        "event_id": event_id,
        "cloud_updated": remote_item is not None,
        "local_updated": local_item is not None,
        "cloud_error": cloud_error or None,
        "item": {
            "event_id": event_id,
            "qr_code": qr_code,
            "core_weight": core_weight,
            "product_weight": product_weight,
            "work_date": work_date,
            "shift": shift,
            "machine": machine,
            "production_order": production_order,
            "error_status": error_status,
            "error_reason": error_reason,
            "weight_raw": persist_raw,
        },
    }


class StationUIService:
    def __init__(
        self,
        store: MeasurementStore,
        sync_worker: OutboxSyncWorker | None,
        lookup_url: str | None,
        lookup_token: str | None,
        duplicate_window: float = 5.0,
        reader: QRReader | None = None,
        ocr_min_confidence: float = 0.60,
        ocr_download: bool = False,
        sample_store: FactorySampleStore | None = None,
        min_frame_width: int = 640,
        min_frame_height: int = 480,
        min_brightness: float = 30.0,
        max_brightness: float = 250.0,
        min_sharpness: float = 35.0,
        *,
        gateway_id: str = "gateway-01",
        station_count: int = 1,
        station_ids: list[str] | tuple[str, ...] | None = None,
        camera_ids: list[str] | tuple[str, ...] | None = None,
        staging_dir: str | Path | None = None,
        diagnostic_image: str | Path | None = None,
        inference_queue_size: int = 8,
        inference_coordinator: InferenceCoordinator | None = None,
        auto_advance: bool = True,
        weight_rois: list[str] | tuple[str, ...] | None = None,
        weight_burst_frames: int = DEFAULT_WEIGHT_BURST_FRAMES,
        gemini_reader: GeminiWeightReader | None = None,
        gemini_flash31_reader: GeminiWeightReader | None = None,
        gemini_flash37_reader: GeminiWeightReader | None = None,
        gemini_accurate_reader: GeminiWeightReader | None = None,
        gemini_key_manager: GeminiKeyManager | None = None,
        codex_reader: CodexWeightReader | CodexOAuthWeightReader | None = None,
        weight_engine: str = "local",
    ):
        if not 1 <= int(station_count) <= 3:
            raise ValueError("station_count phải từ 1 đến 3")
        configured_station_ids = list(station_ids or ())
        if configured_station_ids and len(configured_station_ids) != int(station_count):
            raise ValueError("Số station_id phải bằng station_count")
        if not configured_station_ids:
            configured_station_ids = [f"station-{index:02d}" for index in range(1, station_count + 1)]
        configured_camera_ids = list(camera_ids or ())
        if configured_camera_ids and len(configured_camera_ids) != int(station_count):
            raise ValueError("Số camera_id phải bằng station_count")
        if not configured_camera_ids:
            configured_camera_ids = [f"camera-{index:02d}" for index in range(1, station_count + 1)]
        if len(set(configured_camera_ids)) != len(configured_camera_ids):
            raise ValueError("camera_id values must be unique")
        configured_weight_rois = list(weight_rois or ())
        if configured_weight_rois and len(configured_weight_rois) != int(station_count):
            raise ValueError("Số weight ROI phải bằng station_count")
        if not 1 <= int(weight_burst_frames) <= MAX_BURST_FRAMES:
            raise ValueError(f"weight_burst_frames phải từ 1 đến {MAX_BURST_FRAMES}")
        if weight_engine not in WEIGHT_ENGINES:
            raise ValueError("weight_engine phải là local, hybrid hoặc gemini")
        if weight_engine in {"hybrid", "gemini"} and gemini_reader is None:
            raise ValueError(f"weight_engine={weight_engine} cần Gemini reader")
        parsed_weight_rois = [parse_normalized_roi(value) for value in configured_weight_rois]
        self.store = store
        self.sync_worker = sync_worker
        self.lookup_url = lookup_url
        self.lookup_token = lookup_token
        self.duplicate_window = duplicate_window
        self.reader = reader or QRReader()
        self.ocr_min_confidence = ocr_min_confidence
        self.ocr_download = ocr_download
        self.sample_store = sample_store
        self.gateway_id = gateway_id
        self.auto_advance = bool(auto_advance)
        self.weight_burst_frames = int(weight_burst_frames)
        self.gemini_reader = gemini_reader
        self.gemini_flash31_reader = gemini_flash31_reader
        self.gemini_flash37_reader = gemini_flash37_reader
        self.gemini_accurate_reader = gemini_accurate_reader
        self.gemini_key_manager = gemini_key_manager
        self._retired_gemini_readers: list[GeminiWeightReader] = []
        self.codex_reader = codex_reader
        self.weight_engine = weight_engine
        self.weight_rois: dict[str, NormalizedROI] = {
            station_id: roi
            for station_id, roi in zip(configured_station_ids, parsed_weight_rois)
        }
        self.station_count = int(station_count)
        self.station_configs = [
            {
                "index": index,
                "station_id": station_id,
                "camera_id": configured_camera_ids[index - 1],
                "weight_roi": self._roi_text(self.weight_rois.get(station_id)),
            }
            for index, station_id in enumerate(configured_station_ids, start=1)
        ]
        default_staging_dir = Path(getattr(store, "capture_dir", "data/captures")) / ".staging"
        self.sessions = StationSessionRegistry(
            staging_dir or default_staging_dir,
            configured_station_ids,
        )
        for station_id, camera_id in zip(configured_station_ids, configured_camera_ids):
            self.sessions.configure_camera(station_id, camera_id)
        self.inference = inference_coordinator or InferenceCoordinator(inference_queue_size)
        self._owns_inference = inference_coordinator is None
        self.diagnostic_image = Path(diagnostic_image) if diagnostic_image else None
        self.quality_settings = {
            "min_width": min_frame_width,
            "min_height": min_frame_height,
            "min_brightness": min_brightness,
            "max_brightness": max_brightness,
            "min_sharpness": min_sharpness,
        }
        self._ocr_reader: object | None = None
        self._ocr_lock = threading.Lock()
        self._ocr_preload_started = False
        self._ocr_preload_error: str | None = None
        self._recent: dict[str, float] = {}
        self._lock = threading.Lock()

    def start_ocr_preload(self) -> None:
        if self.weight_engine == "gemini":
            return
        if self._ocr_preload_started:
            return
        self._ocr_preload_started = True
        threading.Thread(
            target=self._preload_ocr,
            name="paddleocr-preload",
            daemon=True,
        ).start()

    def _preload_ocr(self) -> None:
        try:
            with self._ocr_lock:
                if self._ocr_reader is None:
                    self._ocr_reader = PaddleOCRTextReader.create(
                        download_enabled=self.ocr_download,
                        gpu=False,
                    )
            self._ocr_preload_error = None
        except RuntimeError as exc:
            self._ocr_preload_error = str(exc)

    def close(self) -> None:
        if self._owns_inference:
            self.inference.close()
        closed: set[int] = set()
        for reader in (
            self.gemini_reader,
            self.gemini_flash31_reader,
            self.gemini_flash37_reader,
            self.gemini_accurate_reader,
            *self._retired_gemini_readers,
        ):
            if reader is not None and id(reader) not in closed:
                reader.close()
                closed.add(id(reader))
        if self.codex_reader is not None:
            self.codex_reader.close()

    @staticmethod
    def _reader_model(reader: GeminiWeightReader | None) -> str | None:
        if reader is None:
            return None
        model = getattr(reader, "model", None)
        if model:
            return str(model)
        status = reader.status()
        value = status.get("model") if isinstance(status, dict) else None
        return str(value) if value else None

    def _gemini_reader_for(self, profile: str) -> GeminiWeightReader:
        if profile not in GEMINI_RECOGNITION_PROFILES:
            raise ValueError(
                "Chế độ nhận diện phải là flash31, fast, flash37 hoặc accurate"
            )
        if profile == "flash31":
            if self.gemini_flash31_reader is None:
                raise ValueError("Gemini 3.1 Flash-Lite chưa được cấu hình")
            return self.gemini_flash31_reader
        if profile == "flash37":
            if self.gemini_flash37_reader is None:
                raise ValueError("Gemini 3.7 Flash chưa được cấu hình")
            return self.gemini_flash37_reader
        if profile == "accurate":
            if self.gemini_accurate_reader is None:
                raise ValueError("Chế độ Chuẩn chưa được cấu hình")
            return self.gemini_accurate_reader
        if self.gemini_reader is None:
            raise RuntimeError("Gemini primary chưa được cấu hình")
        return self.gemini_reader

    def _install_gemini_readers(
        self,
        readers: tuple[
            GeminiWeightReader,
            GeminiWeightReader,
            GeminiWeightReader,
            GeminiWeightReader,
        ],
    ) -> None:
        fast, flash31, flash37, accurate = readers
        with self._lock:
            old_fast = self.gemini_reader
            old_flash31 = self.gemini_flash31_reader
            old_flash37 = self.gemini_flash37_reader
            old_accurate = self.gemini_accurate_reader
            self.gemini_reader = fast
            self.gemini_flash31_reader = flash31
            self.gemini_flash37_reader = flash37
            self.gemini_accurate_reader = accurate
        retired_ids = {id(reader) for reader in self._retired_gemini_readers}
        for reader in (old_fast, old_flash31, old_flash37, old_accurate):
            if reader is not None and id(reader) not in retired_ids:
                self._retired_gemini_readers.append(reader)
                retired_ids.add(id(reader))

    def replace_gemini_key(self, api_key: str) -> dict[str, object]:
        if self.gemini_key_manager is None:
            raise ValueError("Chức năng đổi Gemini key chưa được cấu hình")
        self._install_gemini_readers(self.gemini_key_manager.replace(api_key))
        return {
            "ok": True,
            "changed": True,
            "stored_encrypted": True,
            "key_id": self.gemini_key_manager.key_id(api_key),
            "message": "Đã kiểm tra, mã hóa và áp dụng Gemini API key mới",
        }

    def save_gemini_backup_key(self, api_key: str) -> dict[str, object]:
        if self.gemini_key_manager is None:
            raise ValueError("Chức năng Gemini key dự phòng chưa được cấu hình")
        key_id = self.gemini_key_manager.save_backup(api_key)
        return {
            "ok": True,
            "saved": True,
            "activated": False,
            "stored_encrypted": True,
            "key_id": key_id,
            "message": "Đã kiểm tra và lưu Gemini key dự phòng; key đang dùng không đổi",
        }

    def switch_gemini_key(self, slot: str) -> dict[str, object]:
        if self.gemini_key_manager is None:
            raise ValueError("Chức năng chuyển Gemini key chưa được cấu hình")
        self._install_gemini_readers(self.gemini_key_manager.activate(slot))
        key_status = self.gemini_key_manager.status()
        label = "dự phòng" if slot == "backup" else "chính"
        return {
            "ok": True,
            "changed": True,
            "active_slot": slot,
            "key_id": key_status.get("key_id"),
            "message": f"Đã chuyển sang Gemini key {label}",
        }

    @staticmethod
    def _roi_text(roi: NormalizedROI | None) -> str:
        if roi is None:
            return ""
        return f"{roi.x1:.4f},{roi.y1:.4f},{roi.x2:.4f},{roi.y2:.4f}"

    @staticmethod
    def _gemini_crop(frame: np.ndarray, roi: NormalizedROI) -> np.ndarray:
        left, top, right, bottom = roi.pixels(frame)
        width = max(1, right - left)
        height = max(1, bottom - top)
        pad_x = max(4, round(width * 0.12))
        pad_y = max(4, round(height * 0.18))
        frame_height, frame_width = frame.shape[:2]
        return frame[
            max(0, top - pad_y) : min(frame_height, bottom + pad_y),
            max(0, left - pad_x) : min(frame_width, right + pad_x),
        ]

    @staticmethod
    def _distant_weight_roi(frame: np.ndarray) -> tuple[NormalizedROI, str] | None:
        """Find a tiny red LED row in a portrait factory overview.

        The normal detector is deliberately strict for OCR. This fallback is
        only used to create a contextual zoom inset for AI and cloud evidence.
        """

        if frame.ndim != 3 or frame.shape[2] < 3:
            return None
        height, width = frame.shape[:2]
        blue, green, red = cv2.split(frame[:, :, :3])
        red_i16 = red.astype(np.int16)
        other = np.maximum(green, blue).astype(np.int16)
        mask = ((red_i16 >= 120) & (red_i16 - other >= 45)).astype(np.uint8)
        mask[: round(height * 0.30), :] = 0
        joined = cv2.morphologyEx(
            mask,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        )
        count, _, stats, _ = cv2.connectedComponentsWithStats(joined, connectivity=8)
        candidates: list[tuple[float, tuple[int, int, int, int]]] = []
        for index in range(1, count):
            left, top, box_width, box_height, _ = (int(value) for value in stats[index])
            if box_width < 5 or box_height < 5:
                continue
            if box_width > width * 0.08 or box_height > height * 0.035:
                continue
            aspect = box_width / max(1, box_height)
            if not 0.8 <= aspect <= 12:
                continue
            region = mask[top : top + box_height, left : left + box_width]
            red_pixels = int(np.count_nonzero(region))
            density = red_pixels / max(1, box_width * box_height)
            if red_pixels < 8 or density < 0.08:
                continue
            center_bias = (top + (box_height / 2)) / max(1, height)
            score = red_pixels * (1 + min(aspect, 4) * 0.12) + center_bias * 8
            candidates.append(
                (score, (left, top, left + box_width, top + box_height))
            )
        if not candidates:
            return None
        _, (left, top, right, bottom) = max(candidates, key=lambda item: item[0])
        return NormalizedROI(
            left / width,
            top / height,
            right / width,
            bottom / height,
        ), "distant-red-led"

    @staticmethod
    def _scale_context_crop(frame: np.ndarray, roi: NormalizedROI) -> np.ndarray:
        """Include the indicator, scale platform, and weighed object in the zoom."""

        left, top, right, bottom = roi.pixels(frame)
        frame_height, frame_width = frame.shape[:2]
        roi_width = max(1, right - left)
        roi_height = max(1, bottom - top)
        crop_width = min(
            frame_width,
            max(round(frame_width * 0.40), roi_width * 10),
        )
        crop_height = min(
            frame_height,
            max(round(frame_height * 0.24), roi_height * 12),
        )
        center_x = (left + right) / 2
        # Keep more room above the LED row for the platform and weighed item.
        crop_left = round(center_x - (crop_width / 2))
        crop_top = round(((top + bottom) / 2) - (crop_height * 0.64))
        crop_left = min(max(0, crop_left), frame_width - crop_width)
        crop_top = min(max(0, crop_top), frame_height - crop_height)
        return frame[
            crop_top : crop_top + crop_height,
            crop_left : crop_left + crop_width,
        ]

    @classmethod
    def _zoomed_evidence(
        cls,
        frame: np.ndarray,
        roi: NormalizedROI,
    ) -> tuple[np.ndarray, NormalizedROI]:
        """Keep the full scene and append a large, clearly marked scale-display inset."""

        crop = cls._scale_context_crop(frame, roi)
        crop_height, crop_width = crop.shape[:2]
        frame_height, frame_width = frame.shape[:2]
        if crop_height < 1 or crop_width < 1:
            return frame, roi

        margin = max(12, round(min(frame_height, frame_width) * 0.012))
        label_height = max(30, round(frame_height * 0.04))
        portrait = frame_height > frame_width * 1.15
        target_width = max(1, frame_width - (2 * margin))
        target_height = (
            max(120, frame_height - label_height - (3 * margin))
            if portrait
            else max(120, round(frame_height * 0.34))
        )
        scale = min(target_width / crop_width, target_height / crop_height)
        zoom_width = max(1, min(target_width, round(crop_width * scale)))
        zoom_height = max(1, min(target_height, round(crop_height * scale)))
        interpolation = cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA
        zoomed = cv2.resize(crop, (zoom_width, zoom_height), interpolation=interpolation)

        if portrait:
            composite = np.full(
                (frame_height, frame_width * 2, 3),
                24,
                dtype=frame.dtype,
            )
            zoom_left = frame_width + ((frame_width - zoom_width) // 2)
            zoom_top = label_height + margin + (
                (frame_height - label_height - (2 * margin) - zoom_height) // 2
            )
            label_origin = (frame_width + margin, label_height)
        else:
            panel_height = label_height + zoom_height + (2 * margin)
            composite = np.full(
                (frame_height + panel_height, frame_width, 3),
                24,
                dtype=frame.dtype,
            )
            zoom_left = (frame_width - zoom_width) // 2
            zoom_top = frame_height + label_height + margin
            label_origin = (margin, frame_height + label_height)
        composite[:frame_height, :frame_width] = frame
        composite[
            zoom_top : zoom_top + zoom_height,
            zoom_left : zoom_left + zoom_width,
        ] = zoomed
        cv2.rectangle(
            composite,
            (max(0, zoom_left - 2), max(0, zoom_top - 2)),
            (
                min(composite.shape[1] - 1, zoom_left + zoom_width + 1),
                min(composite.shape[0] - 1, zoom_top + zoom_height + 1),
            ),
            (230, 230, 230),
            2,
        )
        cv2.putText(
            composite,
            "ZOOM MAN HINH CAN",
            label_origin,
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.55, frame_width / 1800),
            (240, 240, 240),
            2,
            cv2.LINE_AA,
        )
        composite_height = composite.shape[0]
        composite_width = composite.shape[1]
        zoom_roi = NormalizedROI(
            zoom_left / composite_width,
            zoom_top / composite_height,
            (zoom_left + zoom_width) / composite_width,
            (zoom_top + zoom_height) / composite_height,
        )
        return composite, zoom_roi

    @staticmethod
    def _canonical_evidence(frame: np.ndarray) -> tuple[np.ndarray, str]:
        encoded = encode_staged_jpeg(frame, quality=90)
        canonical = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if canonical is None:
            raise OSError("Không chuẩn hóa được ảnh zoom cân")
        data_url = "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
        return canonical, data_url

    def status(self) -> dict[str, object]:
        station_states = {item["station_id"]: item for item in self.sessions.statuses()}
        stations: list[dict[str, object]] = []
        for config in self.station_configs:
            station = dict(config)
            station.update(station_states.get(str(config["station_id"]), {}))
            station["diagnostic_path"] = str(
                self.diagnostic_path_for(str(config["station_id"])) or ""
            )
            stations.append(station)
        return {
            "gateway_id": self.gateway_id,
            "station_count": self.station_count,
            "auto_advance": self.auto_advance,
            "weight_burst_frames": self.weight_burst_frames,
            "weight_engine": self.weight_engine,
            "ocr_ready": self._ocr_reader is not None,
            "ocr_preload_error": self._ocr_preload_error,
            "gemini": (
                {
                    **self.gemini_reader.status(),
                    **(self.gemini_key_manager.status() if self.gemini_key_manager else {}),
                }
                if self.gemini_reader is not None
                else {"enabled": False}
            ),
            "codex": (
                self.codex_reader.status()
                if self.codex_reader is not None
                else {
                    "enabled": False,
                    "installed": False,
                    "authenticated": False,
                    "available": False,
                }
            ),
            "recognition_providers": {
                "default": "gemini",
                "gemini": {"available": self.gemini_reader is not None},
                "codex": {
                    "available": bool(
                        self.codex_reader is not None
                        and self.codex_reader.status().get("available")
                    )
                },
            },
            "recognition_profiles": {
                "default": "flash31",
                "flash31": {
                    "enabled": self.gemini_flash31_reader is not None,
                    "model": self._reader_model(self.gemini_flash31_reader),
                },
                "fast": {
                    "enabled": self.gemini_reader is not None,
                    "model": self._reader_model(self.gemini_reader),
                },
                "flash37": {
                    "enabled": self.gemini_flash37_reader is not None,
                    "model": self._reader_model(self.gemini_flash37_reader),
                },
                "accurate": {
                    "enabled": self.gemini_accurate_reader is not None,
                    "model": self._reader_model(self.gemini_accurate_reader),
                },
            },
            "stations": stations,
            "inference": self.inference.status().as_dict(),
        }

    def stage_evidence_step(
        self,
        frame: np.ndarray,
        *,
        event_id: str,
        station_id: str,
        kind: str,
        weight: float,
        unit: str,
        qr_code: str = "",
    ) -> dict[str, object]:
        """Durably save each accepted weighing step before final confirmation."""
        if kind not in {"core", "product", "inventory"}:
            raise ValueError("capture_kind phải là core, product hoặc inventory")
        if station_id not in {str(item["station_id"]) for item in self.station_configs}:
            raise ValueError("station_id không hợp lệ")
        uuid.UUID(event_id)
        folder = self.sessions.staging_dir / station_id
        folder.mkdir(parents=True, exist_ok=True)
        image_path = folder / f"{event_id}_{kind}.jpg"
        metadata_path = folder / f"{event_id}_steps.json"
        encoded_ok, encoded = cv2.imencode(".jpg", frame)
        if not encoded_ok:
            raise OSError("Không mã hóa được ảnh bằng chứng")
        with self._lock:
            image_path.write_bytes(encoded.tobytes())
            metadata: dict[str, object] = {"event_id": event_id, "station_id": station_id}
            if metadata_path.is_file():
                try:
                    loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        metadata.update(loaded)
                except (OSError, json.JSONDecodeError):
                    pass
            metadata[kind] = {
                "image_path": str(image_path.resolve()),
                "weight": float(weight),
                "unit": unit,
                "qr_code": qr_code.strip(),
            }
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {"image_path": str(image_path.resolve()), "metadata_path": str(metadata_path.resolve())}

    def detect_panel_regions(
        self,
        frame: np.ndarray,
        *,
        recognition_profile: str = "fast",
    ) -> dict[str, object]:
        reader = self._gemini_reader_for(recognition_profile)
        detector = getattr(reader, "detect_panel_regions", None)
        if detector is None:
            raise ValueError("Gemini hiện tại chưa hỗ trợ tự tìm màn hình")
        result = detector(frame)
        items = result.get("regions") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("Kết quả tự tìm màn hình không hợp lệ")
        normalized: list[dict[str, object]] = []
        labels: set[str] = set()
        for index, item in enumerate(items[:24], start=1):
            if not isinstance(item, dict):
                continue
            try:
                x1, y1, x2, y2 = (
                    float(item["x1"]),
                    float(item["y1"]),
                    float(item["x2"]),
                    float(item["y2"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                continue
            if x2 - x1 < 0.008 or y2 - y1 < 0.008:
                continue
            label = str(item.get("label") or f"Chỉ số {index:02d}").strip()[:80]
            if not label or label.casefold() in labels:
                base = f"Chỉ số {index:02d}"
                label = base
                suffix = 2
                while label.casefold() in labels:
                    label = f"{base} {suffix}"
                    suffix += 1
            labels.add(label.casefold())
            normalized.append(
                {
                    "label": label,
                    "x1": round(x1, 5),
                    "y1": round(y1, 5),
                    "x2": round(x2, 5),
                    "y2": round(y2, 5),
                }
            )
        return {**result, "regions": normalized}

    def analyze_panel_regions(
        self,
        frame: np.ndarray,
        regions: object,
        *,
        recognition_profile: str = "fast",
    ) -> dict[str, object]:
        if self.gemini_reader is None:
            raise ValueError("Gemini chưa được bật trên backend")
        if not isinstance(regions, list) or not 1 <= len(regions) <= 24:
            raise ValueError("Cần cấu hình từ 1 đến 24 vùng chỉ số")
        cropped: list[tuple[str, np.ndarray]] = []
        normalized: list[dict[str, object]] = []
        labels: set[str] = set()
        for item in regions:
            if not isinstance(item, dict):
                raise ValueError("Vùng chỉ số không hợp lệ")
            label = str(item.get("label", "")).strip()
            if not label or len(label) > 80 or label.casefold() in labels:
                raise ValueError("Tên vùng chỉ số trống, trùng hoặc quá dài")
            try:
                roi = NormalizedROI(
                    float(item["x1"]),
                    float(item["y1"]),
                    float(item["x2"]),
                    float(item["y2"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Tọa độ vùng {label} không hợp lệ") from exc
            if not (0 <= roi.x1 < roi.x2 <= 1 and 0 <= roi.y1 < roi.y2 <= 1):
                raise ValueError(f"Tọa độ vùng {label} nằm ngoài ảnh")
            left, top, right, bottom = roi.pixels(frame)
            if right - left < 8 or bottom - top < 8:
                raise ValueError(f"Vùng {label} quá nhỏ")
            labels.add(label.casefold())
            cropped.append((label, frame[top:bottom, left:right]))
            normalized.append(
                {
                    "label": label,
                    "x1": roi.x1,
                    "y1": roi.y1,
                    "x2": roi.x2,
                    "y2": roi.y2,
                }
            )
        reader = self._gemini_reader_for(recognition_profile)
        result = reader.read_panel_regions(cropped)
        return {
            **result,
            "regions": normalized,
            "recognition_profile": recognition_profile,
        }

    def panel_regions(self, station_id: str) -> list[dict[str, object]]:
        station_id = str(station_id).strip()
        if station_id not in {str(item["station_id"]) for item in self.station_configs}:
            raise ValueError("station_id không hợp lệ")
        path = self.sessions.staging_dir.parent / "panel-regions.json"
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = stored.get(station_id, []) if isinstance(stored, dict) else []
        return items if isinstance(items, list) else []

    def save_panel_regions(self, station_id: str, regions: object) -> list[dict[str, object]]:
        station_id = str(station_id).strip()
        if station_id not in {str(item["station_id"]) for item in self.station_configs}:
            raise ValueError("station_id không hợp lệ")
        if not isinstance(regions, list) or len(regions) > 24:
            raise ValueError("Danh sách vùng chỉ số không hợp lệ")
        normalized: list[dict[str, object]] = []
        labels: set[str] = set()
        for item in regions:
            if not isinstance(item, dict):
                raise ValueError("Vùng chỉ số không hợp lệ")
            label = str(item.get("label", "")).strip()
            if not label or len(label) > 80 or label.casefold() in labels:
                raise ValueError("Tên vùng chỉ số trống, trùng hoặc quá dài")
            try:
                x1, y1, x2, y2 = (
                    float(item["x1"]),
                    float(item["y1"]),
                    float(item["x2"]),
                    float(item["y2"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Tọa độ vùng {label} không hợp lệ") from exc
            if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
                raise ValueError(f"Tọa độ vùng {label} nằm ngoài ảnh")
            if x2 - x1 < 0.005 or y2 - y1 < 0.005:
                raise ValueError(f"Vùng {label} quá nhỏ")
            labels.add(label.casefold())
            normalized.append(
                {"label": label, "x1": x1, "y1": y1, "x2": x2, "y2": y2}
            )
        path = self.sessions.staging_dir.parent / "panel-regions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                stored = {}
            if not isinstance(stored, dict):
                stored = {}
            stored[station_id] = normalized
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(path)
        return normalized

    def _cleanup_evidence_steps(self, station_id: str, event_id: str) -> None:
        """Remove transient two-step evidence after save or operator discard."""
        station_id = str(station_id).strip()
        if station_id not in {str(item["station_id"]) for item in self.station_configs}:
            return
        try:
            uuid.UUID(str(event_id))
        except (ValueError, TypeError, AttributeError):
            return
        folder = self.sessions.staging_dir / station_id
        for suffix in ("_core.jpg", "_product.jpg", "_inventory.jpg", "_steps.json"):
            try:
                (folder / f"{event_id}{suffix}").unlink(missing_ok=True)
            except OSError:
                pass

    def discard_session(self, station_id: str, *, event_id: str | None = None) -> bool:
        try:
            discarded = self.sessions.discard(station_id, event_id=event_id)
        except AnalysisBindingMismatch:
            # The browser may only know the photo event after an AI failure.
            # Clearing the station binding is safe here and must not prevent
            # the operator from dropping the failed local preview.
            discarded = self.sessions.discard(station_id)
        if event_id:
            self._cleanup_evidence_steps(station_id, event_id)
        return discarded

    def diagnostic_path_for(self, station_id: str) -> Path | None:
        if self.diagnostic_image is None:
            return None
        text = str(self.diagnostic_image)
        if "{station_id}" in text:
            return Path(text.format(station_id=station_id))
        if self.station_count == 1:
            return self.diagnostic_image
        return self.diagnostic_image.with_name(
            f"{self.diagnostic_image.stem}_{station_id}{self.diagnostic_image.suffix or '.jpg'}"
        )

    def _write_diagnostic(self, station_id: str, frame: np.ndarray) -> None:
        path = self.diagnostic_path_for(station_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(path), frame):
            raise RuntimeError("Không ghi được ảnh chẩn đoán OCR")

    def _decode_qr(self, frame: np.ndarray) -> dict[str, object]:
        detections = self.reader.decode(frame)
        if not detections:
            return {"ok": True, "found": False}
        detection = detections[0]
        height, width = frame.shape[:2]
        points = np.asarray(detection.points, dtype=np.float32).reshape((-1, 2))
        x1, y1 = points.min(axis=0)
        x2, y2 = points.max(axis=0)
        qr_roi = (
            f"{max(0.0, x1 / width):.4f},{max(0.0, y1 / height):.4f},"
            f"{min(1.0, x2 / width):.4f},{min(1.0, y2 / height):.4f}"
        )
        return {
            "ok": True,
            "found": True,
            "qr_code": detection.value,
            "decoder": detection.decoder,
            "qr_roi": qr_roi,
        }

    def decode_qr(self, frame: np.ndarray) -> dict[str, object]:
        return self.inference.run(self._decode_qr, frame)

    def capture_photo_draft(
        self,
        frame: np.ndarray,
        *,
        client_qr_code: str = "",
        event_id: str | None = None,
        parent_event_id: str = "",
        capture_kind: str = "core",
        capture_round: int = 0,
        station_id: str = "",
        camera_id: str = "",
        work_date: str = "",
        shift: str = "",
        machine: str = "",
        production_order: str = "",
    ) -> dict[str, object]:
        """Save one image for later AI processing while decoding QR locally."""

        event_id = str(event_id or uuid.uuid4()).strip()
        try:
            parsed_event_id = uuid.UUID(event_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("event_id ảnh chờ không hợp lệ") from exc
        if parsed_event_id.version != 4:
            raise ValueError("event_id ảnh chờ phải là UUID v4")
        parent_event_id = parent_event_id.strip() or event_id
        try:
            parsed_parent_event_id = uuid.UUID(parent_event_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("event_id phiếu cân không hợp lệ") from exc
        if parsed_parent_event_id.version != 4:
            raise ValueError("event_id phiếu cân phải là UUID v4")
        capture_kind = capture_kind.strip().lower()
        if capture_kind not in {"core", "product"}:
            raise ValueError("Ô ảnh phải là cân lõi hoặc cân sản phẩm")
        if not 0 <= capture_round <= 3:
            raise ValueError("Lần cân phải từ 1 đến 4")
        configured = {
            (str(item["station_id"]), str(item["camera_id"]))
            for item in self.station_configs
        }
        if (station_id, camera_id) not in configured:
            raise ValueError("Trạm hoặc camera không hợp lệ")

        client_qr = client_qr_code.strip()
        if len(client_qr) > 512 or any(ord(character) < 32 for character in client_qr):
            raise ValueError("Mã QR từ trình duyệt không hợp lệ")
        # QR is deliberately outside the shared AI/FIFO inference queue so a
        # busy or failed Gemini request cannot delay photo-only capture.
        decoded = self._decode_qr(frame)
        local_qr = str(decoded.get("qr_code") or "").strip()
        qr_conflict = bool(client_qr and local_qr and client_qr != local_qr)
        if qr_conflict:
            qr_code = ""
            qr_source = "browser+backend-conflict"
        elif local_qr:
            qr_code = local_qr
            qr_source = f"camera:{decoded.get('decoder', 'local')}"
            if client_qr:
                qr_source += "+browser-confirmed"
        elif client_qr:
            qr_code = client_qr
            qr_source = "browser-barcode-detector"
        else:
            qr_code = ""
            qr_source = "none"

        draft, duplicate = self.store.save_photo_draft_idempotent(
            frame,
            qr_code=qr_code,
            qr_source=qr_source,
            needs_sync=self.sync_worker is not None,
            event_id=event_id,
            parent_event_id=parent_event_id,
            capture_kind=capture_kind,
            capture_round=capture_round,
            work_date=work_date,
            shift=shift,
            machine=machine,
            production_order=production_order,
            gateway_id=self.gateway_id,
            station_id=station_id,
            camera_id=camera_id,
        )
        if self.sync_worker is not None:
            self.sync_worker.sync_photo_draft_event(draft.event_id)
        current = self.store.get_photo_draft(draft.event_id) or draft
        return {
            "ok": True,
            "id": current.id,
            "event_id": current.parent_event_id,
            "capture_id": current.event_id,
            "capture_kind": current.capture_kind,
            "capture_round": current.capture_round,
            "workflow": "photo_draft",
            "status": current.status,
            "duplicate": duplicate,
            "qr_found": bool(current.qr_code),
            "qr_conflict": qr_conflict,
            "qr_code": current.qr_code,
            "qr_decoder": current.qr_source,
            "sync_status": current.sync_status,
            "remote_id": current.remote_id,
            "remote_image_url": current.remote_image_url,
            "remote_image_public_id": current.remote_image_public_id,
            "sync_error": current.sync_error,
            "pending_count": self.store.pending_count(),
            "ai_requested": False,
        }

    def assess_quality(self, frame: np.ndarray) -> FrameQuality:
        return assess_frame_quality(frame, **self.quality_settings)

    def quality_result(self, quality: FrameQuality) -> tuple[dict[str, object], bool]:
        payload = quality.as_dict(ignore_low_resolution=self.weight_engine == "gemini")
        return payload, bool(payload["accepted"])

    def _analyze_frame(
        self,
        frame: np.ndarray,
        roi_text: str,
        unit: str,
        weight_frames: list[np.ndarray] | None = None,
        roi_method_override: str | None = None,
        recognition_profile: str = "fast",
        recognition_provider: str = "gemini",
        capture_kind: str = "",
        client_qr_code: str = "",
    ) -> dict[str, object]:
        if unit not in UNITS:
            raise ValueError("Đơn vị không hợp lệ")
        if recognition_profile not in GEMINI_RECOGNITION_PROFILES:
            raise ValueError(
                "Chế độ nhận diện phải là flash31, fast, flash37 hoặc accurate"
            )
        recognition_provider = recognition_provider.strip().lower()
        if recognition_provider not in AI_RECOGNITION_PROVIDERS:
            raise ValueError("Bộ AI nhận diện phải là gemini hoặc codex")
        if capture_kind not in {"", "core", "product", "inventory"}:
            raise ValueError("capture_kind phải là core, product hoặc inventory")
        quality = self.assess_quality(frame)
        quality_payload, quality_pass = self.quality_result(quality)
        # QR belongs to the product step. Avoid spending CPU decoding unrelated
        # pixels while the operator is capturing the core weight.
        decoded = (
            {
                "ok": True,
                "found": False,
                "qr_code": None,
                "decoder": "not-requested-core-step",
                "qr_roi": None,
            }
            if capture_kind == "core"
            else self._decode_qr(frame)
        )
        client_qr = client_qr_code.strip()
        if len(client_qr) > 512 or any(ord(character) < 32 for character in client_qr):
            raise ValueError("Mã QR từ trình duyệt không hợp lệ")
        qr_conflict = False
        if client_qr:
            local_qr = str(decoded.get("qr_code") or "").strip()
            if local_qr and local_qr != client_qr:
                qr_conflict = True
                decoded = {
                    "ok": True,
                    "found": False,
                    "qr_code": None,
                    "decoder": "dedicated-decoder-conflict",
                    "qr_roi": decoded.get("qr_roi"),
                }
            elif local_qr:
                decoded["decoder"] = f"{decoded.get('decoder', 'local')}+browser-confirmed"
            else:
                decoded = {
                    "ok": True,
                    "found": True,
                    "qr_code": client_qr,
                    "decoder": "browser-barcode-detector",
                    "qr_roi": None,
                }
        frames = [frame, *(weight_frames or [])]
        auto_roi = roi_text.strip().lower() in {"", "auto"}
        roi: NormalizedROI | None
        crop_retry_method: str | None = None
        if self.weight_engine == "gemini":
            provider_prefix = recognition_provider
            optimized_capture = capture_kind in {"core", "product", "inventory"}
            if not optimized_capture:
                roi = None
                roi_method = f"{provider_prefix}-full-frame"
            elif auto_roi:
                located = detect_weight_roi(frame)
                if located is None:
                    roi = None
                else:
                    roi, detected_method = located
                    crop_retry_method = detected_method
                roi_method = f"{provider_prefix}-full-frame"
            else:
                roi = parse_normalized_roi(roi_text)
                crop_retry_method = roi_method_override or "manual"
                roi_method = (
                    f"{provider_prefix}-full-frame+{roi_method_override}"
                    if roi_method_override and roi_method_override.startswith("zoom-")
                    else f"{provider_prefix}-full-frame"
                )
        elif auto_roi:
            located = (
                detect_weight_roi_consensus(frames)
                if len(frames) > 1
                else detect_weight_roi(frame)
            )
            if located is None:
                return {
                    "ok": True,
                    "qr_found": bool(decoded.get("found")),
                    "qr_code": decoded.get("qr_code"),
                    "qr_decoder": decoded.get("decoder"),
                    "qr_roi": decoded.get("qr_roi"),
                    "weight_found": False,
                    "weight": None,
                    "unit": unit,
                    "confidence": None,
                    "weight_raw": "AUTO ROI: không tìm thấy vùng LED đỏ",
                    "recognition_source": "none",
                    "local_candidate": None,
                    "gemini_used": False,
                    "gemini_suggestion": None,
                    "gemini_latency_seconds": None,
                    "gemini_input_tokens": None,
                    "gemini_output_tokens": None,
                    "gemini_thinking_tokens": None,
                    "gemini_total_tokens": None,
                    "requires_human_review": False,
                    "roi": None,
                    "roi_method": "not-found",
                    "quality": quality_payload,
                    "quality_pass": quality_pass,
                }
            roi, roi_method = located
        else:
            roi = parse_normalized_roi(roi_text)
            roi_method = roi_method_override or "manual"

        local_candidate: WeightReading | None = None
        gemini_used = self.weight_engine == "gemini"
        codex_used = False
        gemini_suggestion: float | None = None
        gemini_latency_seconds: float | None = None
        gemini_input_tokens: int | None = None
        gemini_output_tokens: int | None = None
        gemini_thinking_tokens: int | None = None
        gemini_total_tokens: int | None = None
        gemini_attempts = 0
        gemini_fallback_used = False
        ai_crop_applied = False
        requires_human_review = False
        if self.weight_engine == "gemini":
            if recognition_provider == "codex":
                if self.codex_reader is None:
                    raise ValueError("Codex chưa được bật trên máy backend")
                codex_status = self.codex_reader.status()
                if not codex_status.get("available"):
                    raise ValueError(str(codex_status.get("message") or "Codex chưa đăng nhập"))
                selected_ai_reader = self.codex_reader
                gemini_used = False
                codex_used = True
            else:
                selected_ai_reader = self._gemini_reader_for(recognition_profile)
            provider_label = "CODEX" if codex_used else "GEMINI"
            provider_source = "codex-primary" if codex_used else "gemini-primary"
            single_image_request = len(frames) == 1
            ai_frames = [frame] if single_image_request else frames
            if len(ai_frames) == 2:
                reading = WeightReading(
                    None,
                    unit,
                    False,
                    f"{provider_label} PRIMARY: cần ít nhất 3 frame camera mới",
                )
                recognition_source = "none"
            else:
                suggestion = selected_ai_reader.read(ai_frames, unit=unit)
                gemini_attempts = 1
                suggestion_raw = suggestion.raw
                suggestions = [suggestion]
                crop_is_available = bool(
                    capture_kind in {"core", "product", "inventory"} and roi is not None
                )
                # Full-frame is the normal path: Gemini can locate the small scale
                # display from its factory context. Only retry a focused LED crop
                # when a valid AI response explicitly says the weight is unreadable.
                # Network/API errors are not retried here.
                if (
                    crop_is_available
                    and suggestion.value is None
                    and not suggestion.raw.startswith(f"{provider_label} ERROR:")
                ):
                    cropped_frames = [self._gemini_crop(item, roi) for item in ai_frames]
                    fallback = selected_ai_reader.read(cropped_frames, unit=unit)
                    suggestions.append(fallback)
                    gemini_attempts = 2
                    gemini_fallback_used = True
                    ai_crop_applied = True
                    suggestion_raw = (
                        f"FULL FRAME ATTEMPT: {suggestion.raw}; "
                        f"CROP RETRY: {fallback.raw}"
                    )
                    suggestion = fallback
                    roi_method = (
                        f"{provider_prefix}-full-frame+crop-"
                        f"{crop_retry_method or 'detected'}-retry"
                    )
                gemini_suggestion = suggestion.value
                gemini_latency_seconds = sum(item.latency_seconds for item in suggestions)
                gemini_input_tokens = sum(item.input_tokens for item in suggestions)
                gemini_output_tokens = sum(item.output_tokens for item in suggestions)
                gemini_thinking_tokens = sum(item.thinking_tokens for item in suggestions)
                gemini_total_tokens = sum(item.total_tokens for item in suggestions)
                local_qr = str(decoded.get("qr_code") or "").strip()
                gemini_qr = str(suggestion.qr_code or "").strip()
                qr_note = ""
                if qr_conflict:
                    qr_note = "; QR: browser/backend conflict; manual code required"
                elif local_qr and gemini_qr and local_qr != gemini_qr:
                    qr_note = "; QR: local/Gemini conflict; kept checksum-validated local QR"
                    decoded["decoder"] = (
                        f"{decoded.get('decoder', 'local')}+gemini-conflict-local-kept"
                    )
                elif local_qr:
                    if gemini_qr == local_qr:
                        decoded["decoder"] = f"{decoded.get('decoder', 'local')}+gemini"
                elif gemini_qr:
                    decoded = {
                        "ok": True,
                        "found": True,
                        "qr_code": gemini_qr,
                        "decoder": "gemini-full-frame",
                        "qr_roi": None,
                    }
                if suggestion.value is None:
                    reading = WeightReading(
                        None,
                        unit,
                        False,
                        f"{suggestion_raw}{qr_note}; {provider_label} PRIMARY: rejected",
                    )
                    recognition_source = "none"
                else:
                    reading = WeightReading(
                        suggestion.value,
                        suggestion.unit,
                        True,
                        (
                            f"{suggestion_raw}{qr_note}; {provider_label} PRIMARY: "
                            + (
                                "single focused-crop retry accepted"
                                if ai_crop_applied
                                else "single full-image accepted"
                            )
                            if single_image_request
                            else f"{suggestion_raw}{qr_note}; {provider_label} PRIMARY: 3-frame schema accepted"
                        ),
                    )
                    recognition_source = provider_source
        else:
            with self._ocr_lock:
                weight_source = CameraOCRWeightSource(
                    roi,
                    unit=unit,
                    min_confidence=self.ocr_min_confidence,
                    download_enabled=self.ocr_download,
                    reader=self._ocr_reader,
                )
                reading = (
                    weight_source.capture_many(frames)
                    if len(frames) > 1
                    else weight_source.capture(frame)
                )
                self._ocr_reader = weight_source._reader
            candidate_reader = getattr(weight_source, "candidate_reading", None)
            local_candidate = (
                candidate_reader()
                if callable(candidate_reader)
                else (reading if reading.value is not None else None)
            )
            recognition_source = "paddle-local" if reading.value is not None else "none"
        if (
            self.weight_engine == "hybrid"
            and reading.value is None
            and self.gemini_reader is not None
            and len(frames) >= 3
        ):
            gemini_used = True
            selected_gemini_reader = self._gemini_reader_for(recognition_profile)
            suggestion = selected_gemini_reader.read(
                frames,
                unit=unit,
            )
            gemini_suggestion = suggestion.value
            gemini_latency_seconds = suggestion.latency_seconds
            gemini_input_tokens = suggestion.input_tokens
            gemini_output_tokens = suggestion.output_tokens
            gemini_thinking_tokens = suggestion.thinking_tokens
            gemini_total_tokens = suggestion.total_tokens
            local_cloud_agree = (
                suggestion.value is not None
                and local_candidate is not None
                and local_candidate.value is not None
                and local_candidate.unit == suggestion.unit
                and round(local_candidate.value, 6) == round(suggestion.value, 6)
            )
            if local_cloud_agree:
                confidence = local_candidate.confidence
                reading = WeightReading(
                    suggestion.value,
                    suggestion.unit,
                    True,
                    (
                        f"{reading.raw}; {local_candidate.raw}; {suggestion.raw}; "
                        "HYBRID: local majority confirmed by Gemini"
                    ),
                    confidence,
                )
                recognition_source = "paddle-local+gemini"
            else:
                requires_human_review = suggestion.value is not None
                reading = WeightReading(
                    None,
                    unit,
                    False,
                    f"{reading.raw}; {suggestion.raw}; HYBRID: no independent agreement",
                )
        return {
            "ok": True,
            "qr_found": bool(decoded.get("found")),
            "qr_code": decoded.get("qr_code"),
            "qr_decoder": decoded.get("decoder"),
            "qr_roi": decoded.get("qr_roi"),
            "qr_conflict": qr_conflict,
            "weight_found": reading.value is not None,
            "weight": reading.value,
            "unit": reading.unit,
            "confidence": reading.confidence,
            "weight_raw": reading.raw,
            "recognition_source": recognition_source,
            "recognition_profile": recognition_profile,
            "recognition_provider": recognition_provider,
            "local_candidate": (
                local_candidate.value
                if local_candidate is not None
                else None
            ),
            "gemini_used": gemini_used,
            "codex_used": codex_used,
            "gemini_suggestion": gemini_suggestion,
            "gemini_latency_seconds": gemini_latency_seconds,
            "gemini_input_tokens": gemini_input_tokens,
            "gemini_output_tokens": gemini_output_tokens,
            "gemini_thinking_tokens": gemini_thinking_tokens,
            "gemini_total_tokens": gemini_total_tokens,
            "gemini_attempts": gemini_attempts,
            "gemini_fallback_used": gemini_fallback_used,
            "ai_latency_seconds": gemini_latency_seconds,
            "ai_attempts": gemini_attempts,
            "ai_fallback_used": gemini_fallback_used,
            "requires_human_review": requires_human_review,
            "roi": self._roi_text(roi) if roi is not None else None,
            "roi_method": roi_method,
            "gemini_crop_applied": ai_crop_applied,
            "ai_crop_applied": ai_crop_applied,
            "burst_frames": len(frames),
            "quality": quality_payload,
            "quality_pass": quality_pass,
        }

    def analyze(
        self,
        frame: np.ndarray,
        roi_text: str,
        unit: str,
        *,
        event_id: str | None = None,
        station_id: str | None = None,
        camera_id: str | None = None,
        weight_frames: list[np.ndarray] | None = None,
        require_temporal: bool = False,
        recognition_profile: str = "fast",
        recognition_provider: str = "gemini",
        capture_kind: str = "",
        client_qr_code: str = "",
        context_station_id: str | None = None,
    ) -> dict[str, object]:
        additional_frames = list(weight_frames or [])
        if len(additional_frames) >= MAX_BURST_FRAMES:
            raise ValueError(f"Burst chỉ được tối đa {MAX_BURST_FRAMES} frame kể cả ảnh chính")
        expected_aspect = frame.shape[1] / max(1, frame.shape[0])
        for extra in additional_frames:
            if extra.ndim != 3 or extra.shape[2] < 3:
                raise ValueError("Burst chứa frame không hợp lệ")
            aspect = extra.shape[1] / max(1, extra.shape[0])
            if abs(aspect - expected_aspect) > 0.03:
                raise ValueError("Các frame trong burst không cùng tỷ lệ ảnh")
        if (
            require_temporal
            and self.weight_engine != "gemini"
            and self.weight_burst_frames >= 3
            and len(additional_frames) < 2
        ):
            raise ValueError("Camera không lấy đủ tối thiểu 3 frame LED; hãy chụp lại")
        identities = (event_id, station_id, camera_id)
        configured_roi = self.weight_rois.get(context_station_id or station_id or "")
        if configured_roi is None and not any(identities) and self.station_count == 1:
            configured_roi = self.weight_rois.get(str(self.station_configs[0]["station_id"]))
        auto_roi_requested = roi_text.strip().lower() in {"", "auto"}
        roi_method_override = None
        if auto_roi_requested and configured_roi is not None:
            roi_text = self._roi_text(configured_roi)
            roi_method_override = "camera-calibrated"
        evidence_image: str | None = None
        evidence_zoom_applied = False
        evidence_zoom_method: str | None = None
        if self.weight_engine == "gemini" and capture_kind in {"core", "product", "inventory"}:
            located: tuple[NormalizedROI, str] | None
            if configured_roi is not None and auto_roi_requested:
                located = configured_roi, "camera-calibrated"
            elif not auto_roi_requested:
                located = parse_normalized_roi(roi_text), "manual"
            else:
                located = detect_weight_roi(frame) or self._distant_weight_roi(frame)
            if located is not None:
                source_roi, evidence_zoom_method = located
                composite, zoom_roi = self._zoomed_evidence(frame, source_roi)
                frame, evidence_image = self._canonical_evidence(composite)
                roi_text = self._roi_text(zoom_roi)
                roi_method_override = f"zoom-{evidence_zoom_method}"
                evidence_zoom_applied = True
        evidence_metadata = {
            "evidence_image": evidence_image,
            "evidence_zoom_applied": evidence_zoom_applied,
            "evidence_zoom_method": evidence_zoom_method,
        }
        if not any(identities):
            result = self.inference.run(
                self._analyze_frame,
                frame,
                roi_text,
                unit,
                additional_frames,
                roi_method_override,
                recognition_profile,
                recognition_provider,
                capture_kind,
                client_qr_code,
            )
            return {**result, **evidence_metadata}
        if not all(identities):
            raise ValueError("Cần đủ event_id, station_id và camera_id")
        assert event_id is not None and station_id is not None and camera_id is not None
        binding = self.sessions.stage(
            frame,
            event_id=event_id,
            station_id=station_id,
            camera_id=camera_id,
        )
        try:
            self._write_diagnostic(station_id, frame)
            result = self.inference.run(
                self._analyze_frame,
                frame,
                roi_text,
                unit,
                additional_frames,
                roi_method_override,
                recognition_profile,
                recognition_provider,
                capture_kind,
                client_qr_code,
            )
            binding = self.sessions.mark_ready(binding.analysis_id)
        except Exception as exc:
            try:
                self.sessions.mark_failed(binding.analysis_id, exc)
            except SessionConflictError:
                pass
            raise
        return {**result, **binding.as_dict(), **evidence_metadata}

    def capture(
        self,
        qr_code: str,
        weight: float,
        unit: str,
        frame: np.ndarray,
        vision_confirmed: bool = False,
        weight_raw: str = "",
        *,
        product_frame: np.ndarray | None = None,
        product_weight: float | None = None,
        event_id: str | None = None,
        analysis_id: str | None = None,
        station_id: str | None = None,
        camera_id: str | None = None,
        frame_sha256: str | None = None,
    ) -> dict[str, object]:
        qr_code = qr_code.strip()
        if not qr_code:
            decoded = self.decode_qr(frame)
            if not decoded.get("found"):
                raise ValueError("Chưa có QR; hãy quét mã hoặc đưa QR vào camera")
            qr_code = str(decoded["qr_code"])
            qr_source = f"camera:{decoded['decoder']}"
        else:
            qr_source = "test-ui:input"
        if len(qr_code) > 512:
            raise ValueError("QR dài quá 512 ký tự")
        if unit not in UNITS:
            raise ValueError("Đơn vị không hợp lệ")
        if not math.isfinite(weight) or weight < 0:
            raise ValueError("Số cân phải là số không âm")
        if product_weight is not None:
            validate_production_weights(
                weight, product_weight, unit, _raw_tag(weight_raw, "SOURCE_MACHINE")
            )
        quality = self.assess_quality(frame)
        quality_payload, quality_pass = self.quality_result(quality)
        if not quality_pass:
            raise ValueError(
                "Ảnh chưa đạt chất lượng: "
                + "; ".join(str(issue) for issue in quality_payload["issues"])
            )

        # ``event_id`` is also the idempotency key used by unbound, per-round
        # saves.  It must be accepted on its own so a browser retry cannot
        # create a second measurement.  Analysis binding is only requested
        # when one of the analysis identity fields is supplied.
        identity_values = (analysis_id, station_id, camera_id)
        bound_capture = any(identity_values) or bool(frame_sha256)
        if bound_capture and not all((event_id, *identity_values)):
            raise ValueError("Cần đủ event_id, analysis_id, station_id và camera_id")
        computed_frame_sha = jpeg_sha256(encode_staged_jpeg(frame))
        if frame_sha256 and frame_sha256.lower() != computed_frame_sha:
            raise AnalysisBindingMismatch("frame_sha256 không khớp ảnh gửi để lưu")

        captured_at: str | None = None
        if bound_capture:
            assert event_id and analysis_id and station_id and camera_id
            try:
                binding = self.sessions.validate(
                    analysis_id,
                    event_id=event_id,
                    station_id=station_id,
                    camera_id=camera_id,
                    frame_sha256=computed_frame_sha,
                )
                captured_at = binding.captured_at
            except AnalysisBindingNotFound:
                # Completed bindings are retained for a TTL, but a valid retry
                # must remain idempotent even after that TTL or a process restart.
                existing = self.store.get(event_id)
                if existing is None:
                    raise
                expected = (
                    getattr(existing, "analysis_id", ""),
                    getattr(existing, "station_id", ""),
                    getattr(existing, "camera_id", ""),
                    getattr(existing, "frame_sha256", ""),
                )
                supplied = (analysis_id, station_id, camera_id, computed_frame_sha)
                if supplied != expected:
                    raise AnalysisBindingMismatch(
                        "Danh tính lần lưu lại không khớp bản ghi cục bộ"
                    )
                captured_at = existing.captured_at

        with self._lock:
            capture_key = frame_fingerprint(frame)
            if not bound_capture and not event_id:
                now = time.monotonic()
                if now - self._recent.get(capture_key, float("-inf")) < self.duplicate_window:
                    raise ValueError("Ảnh này vừa được lưu; hãy chụp khung hình mới")
            measurement, duplicate = self._save_idempotent(
                qr_code=qr_code,
                weight=weight,
                unit=unit,
                frame=frame,
                weight_source=(
                    "camera-gemini:test-ui"
                    if vision_confirmed and "GEMINI" in weight_raw
                    else "camera-ocr:test-ui"
                    if vision_confirmed
                    else "manual-test-ui"
                ),
                needs_sync=self.sync_worker is not None,
                qr_source=qr_source,
                weight_raw=_persistable_weight_raw(
                    weight_raw,
                    weight=weight,
                    vision_confirmed=vision_confirmed,
                ),
                weight_stable=True,
                event_id=event_id,
                captured_at=captured_at,
                gateway_id=self.gateway_id if (bound_capture or event_id) else "",
                station_id=station_id or "",
                camera_id=camera_id or "",
                analysis_id=analysis_id or "",
            )
            if not bound_capture and not event_id:
                self._recent[capture_key] = time.monotonic()

        if bound_capture:
            self.sessions.mark_saved(str(analysis_id))
        if product_weight is not None:
            self.store.attach_product_weight(measurement.event_id, product_weight)
        if product_frame is not None:
            self.store.attach_product_image(measurement.event_id, product_frame)
            measurement = self.store.get(measurement.event_id) or measurement
        if bound_capture and station_id:
            self._cleanup_evidence_steps(station_id, measurement.event_id)
        # Commit locally first, then synchronously confirm this exact event so
        # one operator click sends the product code, core weight and evidence
        # image together. A failed cloud attempt remains durable in the outbox.
        if self.sync_worker is not None:
            cloud_confirmed = self.sync_worker.sync_event(measurement.event_id)
            if (
                not cloud_confirmed
                and product_weight is not None
                and measurement.product_image_path
            ):
                supabase_url = os.environ.get("ROLL_SCALE_SUPABASE_URL", "").strip()
                service_key = os.environ.get("ROLL_SCALE_SUPABASE_SERVICE_KEY", "").strip()
                if supabase_url and service_key:
                    try:
                        remote = persist_product_evidence(
                            supabase_url,
                            service_key,
                            event_id=measurement.event_id,
                            gateway_id=self.gateway_id,
                            image_path=measurement.product_image_path,
                            product_weight=product_weight,
                        )
                        core_url = remote.get("core_image_url") or remote.get("image_url")
                        core_public_id = remote.get("core_image_public_id") or remote.get("image_public_id")
                        self.store.mark_synced(
                            measurement.event_id,
                            int(remote["id"]) if remote.get("id") is not None else None,
                            str(core_url) if core_url else None,
                            str(core_public_id) if core_public_id else None,
                        )
                        cloud_confirmed = True
                    except Exception:
                        cloud_confirmed = False
        saved = self.store.get(measurement.event_id)
        current = saved or measurement
        return {
            "ok": True,
            "id": current.id,
            "event_id": current.event_id,
            "analysis_id": getattr(current, "analysis_id", analysis_id or ""),
            "gateway_id": getattr(current, "gateway_id", self.gateway_id if bound_capture else ""),
            "station_id": getattr(current, "station_id", station_id or ""),
            "camera_id": getattr(current, "camera_id", camera_id or ""),
            "frame_sha256": getattr(current, "frame_sha256", computed_frame_sha),
            "duplicate": duplicate,
            "qr_code": qr_code,
            "weight": weight,
            "unit": unit,
            "sync_status": current.sync_status,
            "remote_id": current.remote_id,
            "remote_image_url": current.remote_image_url,
            "remote_image_public_id": getattr(current, "remote_image_public_id", None),
            "sync_error": current.sync_error,
            "pending_count": self.store.pending_count(),
        }

    def capture_inventory(
        self,
        product_code: str,
        weight: float,
        core_weight: float,
        tare_weight: float,
        unit: str,
        frame: np.ndarray,
        vision_confirmed: bool = False,
        weight_raw: str = "",
        *,
        event_id: str | None = None,
        analysis_id: str | None = None,
        station_id: str | None = None,
        camera_id: str | None = None,
        frame_sha256: str | None = None,
    ) -> dict[str, object]:
        """Commit one photographed inventory weight without a core capture step."""

        product_code = product_code.strip()
        if not product_code:
            decoded = self.decode_qr(frame)
            if not decoded.get("found"):
                raise ValueError("Chưa có mã sản phẩm; hãy quét QR hoặc nhập thủ công")
            product_code = str(decoded["qr_code"])
            qr_source = f"camera:{decoded['decoder']}"
        else:
            qr_source = "test-ui:input"
        if len(product_code) > 512:
            raise ValueError("Mã sản phẩm dài quá 512 ký tự")
        if unit not in UNITS:
            raise ValueError("Đơn vị không hợp lệ")
        for label, value in (
            ("Khối lượng", weight),
            ("Khối lượng lõi", core_weight),
            ("Khối lượng bì", tare_weight),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} phải là số không âm")
        quality = self.assess_quality(frame)
        quality_payload, quality_pass = self.quality_result(quality)
        if not quality_pass:
            raise ValueError(
                "Ảnh chưa đạt chất lượng: "
                + "; ".join(str(issue) for issue in quality_payload["issues"])
            )

        identity_values = (event_id, analysis_id, station_id, camera_id)
        bound_capture = any(identity_values) or bool(frame_sha256)
        if bound_capture and not all(identity_values):
            raise ValueError("Cần đủ event_id, analysis_id, station_id và camera_id")
        computed_frame_sha = jpeg_sha256(encode_staged_jpeg(frame))
        if frame_sha256 and frame_sha256.lower() != computed_frame_sha:
            raise AnalysisBindingMismatch("frame_sha256 không khớp ảnh kiểm kho")

        captured_at: str | None = None
        if bound_capture:
            assert event_id and analysis_id and station_id and camera_id
            try:
                binding = self.sessions.validate(
                    analysis_id,
                    event_id=event_id,
                    station_id=station_id,
                    camera_id=camera_id,
                    frame_sha256=computed_frame_sha,
                )
                captured_at = binding.captured_at
            except AnalysisBindingNotFound:
                existing = self.store.get_inventory_check(event_id)
                if existing is None:
                    raise
                expected = (
                    existing.analysis_id,
                    existing.station_id,
                    existing.camera_id,
                    existing.frame_sha256,
                )
                supplied = (analysis_id, station_id, camera_id, computed_frame_sha)
                if supplied != expected:
                    raise AnalysisBindingMismatch(
                        "Danh tính lần lưu kiểm kho không khớp bản ghi cục bộ"
                    )
                captured_at = existing.captured_at

        with self._lock:
            capture_key = frame_fingerprint(frame)
            if not bound_capture:
                now = time.monotonic()
                if now - self._recent.get(capture_key, float("-inf")) < self.duplicate_window:
                    raise ValueError("Ảnh này vừa được lưu; hãy chụp khung hình mới")
            check, duplicate = self.store.save_inventory_check_idempotent(
                product_code=product_code,
                weight=weight,
                core_weight=core_weight,
                tare_weight=tare_weight,
                unit=unit,
                frame=frame,
                weight_source=(
                    "camera-gemini:inventory"
                    if vision_confirmed and "GEMINI" in weight_raw
                    else "camera-ocr:inventory"
                    if vision_confirmed
                    else "manual:inventory"
                ),
                needs_sync=self.sync_worker is not None,
                qr_source=qr_source,
                weight_raw=_persistable_weight_raw(
                    weight_raw,
                    weight=weight,
                    vision_confirmed=vision_confirmed,
                ),
                weight_stable=True,
                event_id=event_id,
                captured_at=captured_at,
                gateway_id=self.gateway_id if bound_capture else "",
                station_id=station_id or "",
                camera_id=camera_id or "",
                analysis_id=analysis_id or "",
            )
            if not bound_capture:
                self._recent[capture_key] = time.monotonic()

        if bound_capture:
            self.sessions.mark_saved(str(analysis_id))
        if bound_capture and station_id:
            self._cleanup_evidence_steps(station_id, check.event_id)
        if self.sync_worker is not None:
            self.sync_worker.sync_inventory_event(check.event_id)
        current = self.store.get_inventory_check(check.event_id) or check
        return {
            "ok": True,
            "id": current.id,
            "event_id": current.event_id,
            "workflow": "inventory_check",
            "analysis_id": current.analysis_id,
            "gateway_id": current.gateway_id,
            "station_id": current.station_id,
            "camera_id": current.camera_id,
            "frame_sha256": current.frame_sha256,
            "duplicate": duplicate,
            "product_code": current.product_code,
            "weight": current.weight,
            "core_weight": current.core_weight,
            "tare_weight": current.tare_weight,
            "unit": current.unit,
            "sync_status": current.sync_status,
            "remote_id": current.remote_id,
            "remote_image_url": current.remote_image_url,
            "remote_image_public_id": current.remote_image_public_id,
            "sync_error": current.sync_error,
            "pending_count": self.store.pending_count(),
        }

    def _save_idempotent(self, **kwargs: object) -> tuple[object, bool]:
        """Isolate old/new MeasurementStore return and keyword contracts."""

        method = getattr(self.store, "save_idempotent", None)
        idempotent = callable(method)
        if not idempotent:
            method = self.store.save
        assert callable(method)
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            call_kwargs = kwargs
        else:
            accepts_arbitrary = any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            )
            call_kwargs = kwargs if accepts_arbitrary else {
                key: value for key, value in kwargs.items() if key in signature.parameters
            }
        result = method(**call_kwargs)
        if hasattr(result, "measurement") and hasattr(result, "duplicate"):
            return result.measurement, bool(result.duplicate)
        if isinstance(result, tuple) and len(result) == 2:
            return result[0], bool(result[1])
        return result, False

    def save_factory_sample(
        self,
        frame: np.ndarray,
        qr_roi: str,
        metadata: dict[str, object],
    ) -> dict[str, object]:
        if self.sample_store is None:
            raise RuntimeError("Chưa cấu hình thư mục thu ảnh xưởng")
        metadata = dict(metadata)
        metadata["quality"] = self.assess_quality(frame).as_dict()
        return self.sample_store.save(frame, metadata, qr_roi)

    def lookup(self, qr_code: str) -> dict[str, object]:
        qr_code = qr_code.strip()
        if not qr_code:
            raise ValueError("Thiếu mã QR")
        if not self.lookup_url or not self.lookup_token:
            raise RuntimeError("Chưa cấu hình Supabase lookup")
        return lookup_roll(self.lookup_url, qr_code, self.lookup_token)


def _frontend_index_path() -> Path:
    configured = os.environ.get("ROLL_SCALE_FRONTEND_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve() / "index.html"
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "assets" / "frontend" / "index.html"
    return _project_root() / "frontend" / "index.html"


def _frontend_font_path(filename: str) -> Path | None:
    if not re.fullmatch(r"roboto-[a-z0-9-]+\.woff2", filename):
        return None
    path = _frontend_index_path().parent / "fonts" / filename
    return path if path.is_file() else None


def load_frontend_html() -> str:
    index_path = _frontend_index_path()
    try:
        return index_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Không đọc được frontend: {index_path}") from exc


TEST_UI_HTML = load_frontend_html()


def _default_weight_engine() -> str:
    configured = os.environ.get("ROLL_SCALE_WEIGHT_ENGINE", "").strip().lower()
    if configured:
        return configured
    return (
        "gemini"
        if os.environ.get("ROLL_SCALE_GEMINI_API_KEY", "").strip()
        else "local"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local web UI for testing QR + scale + Supabase")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--db", default="data/measurements.db")
    parser.add_argument("--captures", default="data/captures")
    parser.add_argument("--demo-image", default="data/warehouse_scale_demo.png")
    parser.add_argument("--logo-image", default="data/viet_nhat_ipt_logo.jpg")
    parser.add_argument("--duplicate-window", type=float, default=5.0)
    default_yolo_model = os.environ.get("ROLL_SCALE_YOLO_MODEL")
    if (
        not default_yolo_model
        and not getattr(sys, "frozen", False)
        and Path("models/qr_demo_synthetic.pt").is_file()
    ):
        default_yolo_model = "models/qr_demo_synthetic.pt"
    parser.add_argument("--yolo-model", default=default_yolo_model, help="Custom QR detector best.pt")
    parser.add_argument("--yolo-confidence", type=float, default=0.25)
    parser.add_argument("--yolo-imgsz", type=int, default=960)
    parser.add_argument("--yolo-mode", choices=("first", "fallback"), default="fallback")
    parser.add_argument("--ocr-min-confidence", type=float, default=0.60)
    parser.add_argument("--ocr-download", action="store_true")
    parser.add_argument(
        "--weight-engine",
        choices=tuple(sorted(WEIGHT_ENGINES)),
        default=_default_weight_engine(),
        help="Bộ đọc cân: local, hybrid hoặc gemini (Gemini primary)",
    )
    parser.add_argument(
        "--gemini-fallback",
        action=argparse.BooleanOptionalAction,
        default=_env_flag("ROLL_SCALE_GEMINI_ENABLED", False),
        help="Gọi Gemini bằng một ảnh toàn khung để đọc QR và cân",
    )
    parser.add_argument(
        "--gemini-model",
        default=os.environ.get("ROLL_SCALE_GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
    )
    parser.add_argument(
        "--gemini-31-model",
        default=os.environ.get(
            "ROLL_SCALE_GEMINI_31_MODEL",
            DEFAULT_GEMINI_31_MODEL,
        ),
    )
    parser.add_argument(
        "--gemini-37-model",
        default=os.environ.get(
            "ROLL_SCALE_GEMINI_37_MODEL",
            DEFAULT_GEMINI_37_MODEL,
        ),
    )
    parser.add_argument(
        "--gemini-accurate-model",
        default=os.environ.get(
            "ROLL_SCALE_GEMINI_ACCURATE_MODEL",
            DEFAULT_GEMINI_ACCURATE_MODEL,
        ),
    )
    parser.add_argument(
        "--gemini-timeout",
        type=float,
        default=float(
            os.environ.get(
                "ROLL_SCALE_GEMINI_TIMEOUT",
                str(DEFAULT_GEMINI_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--gemini-31-timeout",
        type=float,
        default=float(
            os.environ.get(
                "ROLL_SCALE_GEMINI_31_TIMEOUT",
                str(DEFAULT_GEMINI_31_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--gemini-accurate-timeout",
        type=float,
        default=float(
            os.environ.get(
                "ROLL_SCALE_GEMINI_ACCURATE_TIMEOUT",
                str(DEFAULT_GEMINI_ACCURATE_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--gemini-37-timeout",
        type=float,
        default=float(
            os.environ.get(
                "ROLL_SCALE_GEMINI_37_TIMEOUT",
                str(DEFAULT_GEMINI_37_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--codex-enabled",
        action=argparse.BooleanOptionalAction,
        default=_env_flag("ROLL_SCALE_CODEX_ENABLED", True),
        help="Cho phép chọn Codex/ChatGPT mà không thay thế Gemini API",
    )
    parser.add_argument(
        "--codex-mode",
        choices=("auto", "cli", "oauth"),
        default=os.environ.get("ROLL_SCALE_CODEX_MODE", "auto").strip().lower(),
        help="auto dùng OAuth trên Render và Codex CLI ở máy local",
    )
    parser.add_argument(
        "--codex-command",
        default=os.environ.get("ROLL_SCALE_CODEX_COMMAND", "codex"),
    )
    parser.add_argument(
        "--codex-model",
        default=os.environ.get("ROLL_SCALE_CODEX_MODEL", ""),
        help="Để trống để Codex dùng model mặc định của tài khoản ChatGPT",
    )
    parser.add_argument(
        "--codex-timeout",
        type=float,
        default=float(
            os.environ.get(
                "ROLL_SCALE_CODEX_TIMEOUT",
                str(DEFAULT_CODEX_TIMEOUT_SECONDS),
            )
        ),
    )
    parser.add_argument(
        "--diagnostic-image",
        default=os.environ.get("ROLL_SCALE_DIAGNOSTIC_IMAGE"),
        help="Ghi đè ảnh phân tích gần nhất để hiệu chỉnh OCR tại xưởng",
    )
    parser.add_argument("--factory-samples", default="dataset/factory_raw")
    parser.add_argument("--staging-dir", help="Thư mục JPEG tạm đã khóa theo analysis_id")
    parser.add_argument("--inference-queue-size", type=int, default=8)
    parser.add_argument("--station-count", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument(
        "--station-id",
        action="append",
        dest="station_ids",
        help="ID trạm theo thứ tự; lặp lại 1-3 lần (mặc định station-01...)",
    )
    parser.add_argument(
        "--camera-id",
        action="append",
        dest="camera_ids",
        help="ID camera cấu hình theo trạm; lặp lại 1-3 lần (mặc định camera-01...)",
    )
    parser.add_argument(
        "--weight-roi",
        action="append",
        dest="weight_rois",
        help=(
            "ROI hàng gross x1,y1,x2,y2 theo từng trạm; lặp lại đúng station-count lần. "
            "Bỏ qua để tự dò LED."
        ),
    )
    parser.add_argument(
        "--weight-burst-frames",
        type=int,
        choices=range(1, MAX_BURST_FRAMES + 1),
        default=DEFAULT_WEIGHT_BURST_FRAMES,
        help="Tổng số frame cho local/hybrid; chế độ Gemini luôn chụp đúng 1 ảnh",
    )
    parser.add_argument(
        "--auto-advance",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Sau khi lưu SQLite thành công, chọn trạm kế tiếp",
    )
    parser.add_argument("--min-frame-width", type=int, default=640)
    parser.add_argument("--min-frame-height", type=int, default=480)
    parser.add_argument("--min-brightness", type=float, default=30.0)
    parser.add_argument("--max-brightness", type=float, default=250.0)
    parser.add_argument("--min-sharpness", type=float, default=35.0)
    parser.add_argument("--api-url", default=os.environ.get("ROLL_SCALE_API_URL"))
    parser.add_argument("--api-token", default=os.environ.get("ROLL_SCALE_DEVICE_TOKEN"))
    parser.add_argument("--lookup-url", default=os.environ.get("ROLL_SCALE_LOOKUP_URL"))
    parser.add_argument("--lookup-token", default=os.environ.get("ROLL_SCALE_LOOKUP_TOKEN"))
    parser.add_argument(
        "--gateway-id",
        "--device-id",
        dest="gateway_id",
        default=os.environ.get("ROLL_SCALE_GATEWAY_ID")
        or os.environ.get("ROLL_SCALE_DEVICE_ID", "gateway-01"),
        help="ID gateway; --device-id được giữ làm bí danh tương thích",
    )
    return parser


def create_server(args: argparse.Namespace) -> tuple[ThreadingHTTPServer, StationUIService]:
    if bool(args.api_url) != bool(args.api_token):
        raise ValueError("Cần đủ URL và token của API ghi")
    if bool(args.lookup_url) != bool(args.lookup_token):
        raise ValueError("Cần đủ URL và token của API tra cứu")
    web_username = os.environ.get("ROLL_SCALE_WEB_USERNAME", "").strip()
    web_password = os.environ.get("ROLL_SCALE_WEB_PASSWORD", "").strip()
    if bool(web_username) != bool(web_password):
        raise ValueError("Cần đủ ROLL_SCALE_WEB_USERNAME và ROLL_SCALE_WEB_PASSWORD")
    station_ids = getattr(args, "station_ids", None)
    camera_ids = getattr(args, "camera_ids", None)
    weight_rois = getattr(args, "weight_rois", None)
    if station_ids and len(station_ids) != args.station_count:
        raise ValueError("Số --station-id phải bằng --station-count")
    if camera_ids and len(camera_ids) != args.station_count:
        raise ValueError("Số --camera-id phải bằng --station-count")
    if camera_ids and len(set(camera_ids)) != len(camera_ids):
        raise ValueError("camera_id values must be unique")
    if weight_rois and len(weight_rois) != args.station_count:
        raise ValueError("Số --weight-roi phải bằng --station-count")
    weight_engine = args.weight_engine
    if args.gemini_fallback and weight_engine == "local":
        weight_engine = "hybrid"
    gemini_reader = None
    gemini_flash31_reader = None
    gemini_flash37_reader = None
    gemini_accurate_reader = None
    gemini_key_manager = None
    if weight_engine in {"hybrid", "gemini"}:
        gemini_encryption_key = os.environ.get(
            "ROLL_SCALE_GEMINI_KEY_ENCRYPTION_KEY", ""
        ) or os.environ.get("ROLL_SCALE_CODEX_TOKEN_KEY", "")
        gemini_key_store = EncryptedCodexTokenStore(
            args.api_url,
            args.api_token,
            secret_name=f"gemini-api-key:{args.gateway_id}",
            # Keep the legacy action name so already-deployed Supabase Functions
            # can store any encrypted secret by its distinct name. New Functions
            # accept this action too.
            secret_action="codex-auth",
            encryption_key=gemini_encryption_key,
        )
        gemini_backup_key_store = EncryptedCodexTokenStore(
            args.api_url,
            args.api_token,
            secret_name=f"gemini-api-key-backup:{args.gateway_id}",
            secret_action="codex-auth",
            encryption_key=gemini_encryption_key,
        )
        gemini_key_manager = GeminiKeyManager(
            gemini_key_store,
            backup_store=gemini_backup_key_store,
            fast_model=args.gemini_model,
            flash31_model=args.gemini_31_model,
            flash37_model=args.gemini_37_model,
            accurate_model=args.gemini_accurate_model,
            fast_timeout=args.gemini_timeout,
            flash31_timeout=args.gemini_31_timeout,
            flash37_timeout=args.gemini_37_timeout,
            accurate_timeout=args.gemini_accurate_timeout,
            initial_key=os.environ.get("ROLL_SCALE_GEMINI_API_KEY", ""),
        )
        gemini_api_key = gemini_key_manager.load_key()
        if not gemini_api_key:
            raise ValueError(
                f"weight_engine={weight_engine} cần Gemini API key trong biến môi trường "
                "hoặc kho key mã hóa Supabase"
            )
        (
            gemini_reader,
            gemini_flash31_reader,
            gemini_flash37_reader,
            gemini_accurate_reader,
        ) = gemini_key_manager.create_readers(
            gemini_api_key,
        )
    codex_reader: CodexWeightReader | CodexOAuthWeightReader | None = None
    if args.codex_enabled:
        codex_mode = args.codex_mode
        if codex_mode == "auto":
            codex_mode = "oauth" if os.environ.get("RENDER", "").strip() else "cli"
        if codex_mode == "oauth":
            token_store = EncryptedCodexTokenStore(
                args.api_url,
                args.api_token,
                secret_name=f"codex-oauth:{args.gateway_id}",
                encryption_key=os.environ.get("ROLL_SCALE_CODEX_TOKEN_KEY", ""),
            )
            codex_reader = CodexOAuthWeightReader(
                CodexOAuthClient(token_store, timeout_seconds=min(args.codex_timeout, 30.0)),
                model=args.codex_model,
                timeout_seconds=args.codex_timeout,
                client_version=os.environ.get("ROLL_SCALE_CODEX_CLIENT_VERSION", "0.124.0"),
            )
        else:
            codex_reader = CodexWeightReader(
                args.codex_command,
                model=args.codex_model,
                timeout_seconds=args.codex_timeout,
            )
    store = MeasurementStore(args.db, args.captures)
    worker = None
    if args.api_url:
        worker = OutboxSyncWorker(store, args.api_url, args.api_token, args.gateway_id)
        worker.start()
    service = StationUIService(
        store,
        worker,
        args.lookup_url,
        args.lookup_token,
        args.duplicate_window,
        QRReader(args.yolo_model, args.yolo_confidence, args.yolo_mode, args.yolo_imgsz),
        args.ocr_min_confidence,
        args.ocr_download,
        FactorySampleStore(args.factory_samples),
        args.min_frame_width,
        args.min_frame_height,
        args.min_brightness,
        args.max_brightness,
        args.min_sharpness,
        gateway_id=args.gateway_id,
        station_count=args.station_count,
        station_ids=station_ids,
        camera_ids=camera_ids,
        staging_dir=args.staging_dir,
        diagnostic_image=args.diagnostic_image,
        inference_queue_size=args.inference_queue_size,
        auto_advance=args.auto_advance,
        weight_rois=weight_rois,
        weight_burst_frames=args.weight_burst_frames,
        gemini_reader=gemini_reader,
        gemini_flash31_reader=gemini_flash31_reader,
        gemini_flash37_reader=gemini_flash37_reader,
        gemini_accurate_reader=gemini_accurate_reader,
        gemini_key_manager=gemini_key_manager,
        codex_reader=codex_reader,
        weight_engine=weight_engine,
    )
    demo_path = Path(args.demo_image)
    logo_path = Path(args.logo_image)

    class Handler(BaseHTTPRequestHandler):
        def is_https(self) -> bool:
            proto = str(self.headers.get("x-forwarded-proto", "")).split(",")[0].strip().lower()
            if proto == "https":
                return True
            return str(self.headers.get("origin", "")).startswith("https://")

        def cookie_header(self, value: str) -> str:
            parts = [
                f"{SESSION_COOKIE_NAME}={value}",
                "Path=/",
                "HttpOnly",
                f"Max-Age={SESSION_TTL_SECONDS}",
            ]
            if self.is_https():
                parts.extend(["Secure", "SameSite=None"])
            else:
                parts.append("SameSite=Lax")
            return "; ".join(parts)

        def add_embed_headers(self) -> None:
            origins = allowed_embed_origins()
            origin = str(self.headers.get("origin", "")).strip()
            if "*" in origins:
                ancestors = "*"
                if origin:
                    self.send_header("access-control-allow-origin", origin)
                    self.send_header("access-control-allow-credentials", "true")
                    self.send_header("vary", "Origin")
                else:
                    self.send_header("access-control-allow-origin", "*")
            elif origin in origins:
                ancestors = " ".join(origins)
                self.send_header("access-control-allow-origin", origin)
                self.send_header("access-control-allow-credentials", "true")
                self.send_header("vary", "Origin")
            else:
                ancestors = " ".join(origins) if origins else "'none'"
            self.send_header("content-security-policy", f"frame-ancestors {ancestors}")
            self.send_header(
                "access-control-allow-headers",
                "Authorization, Content-Type, X-Tram-Can-Session",
            )
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")

        def issue_session_cookie(self) -> str:
            if not web_username:
                return ""
            expires_at = int(time.time()) + SESSION_TTL_SECONDS
            token = encode_session_cookie(web_username, web_password, expires_at)
            self.session_token = token
            self.session_cookie = self.cookie_header(token)
            return token

        def apply_session_token(self, token: str) -> bool:
            token = urllib.parse.unquote(str(token or "").strip())
            if not decode_session_cookie(token, web_username, web_password):
                return False
            self.session_token = token
            self.session_cookie = self.cookie_header(token)
            return True

        def request_session_token(self) -> str:
            authorization = self.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                return authorization[7:].strip()
            header = self.headers.get("x-tram-can-session", "").strip()
            if header:
                return header
            raw = self.headers.get("cookie", "")
            match = re.search(
                rf"(?:^|;\s*){re.escape(SESSION_COOKIE_NAME)}=([^;]+)", raw
            )
            if match:
                return urllib.parse.unquote(match.group(1).strip())
            return ""

        def cookie_authorized(self) -> bool:
            if not web_username:
                return True
            token = self.request_session_token()
            return bool(token) and self.apply_session_token(token)

        def basic_authorized(self) -> bool:
            if not web_username:
                return True
            authorization = self.headers.get("authorization", "")
            if not authorization.startswith("Basic "):
                return False
            try:
                decoded = base64.b64decode(
                    authorization.removeprefix("Basic "), validate=True
                ).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return False
            return _secrets_match(username, web_username) and _secrets_match(
                password, web_password
            )

        def is_authorized(self) -> bool:
            if not web_username:
                return True
            if self.cookie_authorized():
                return True
            if self.basic_authorized():
                self.issue_session_cookie()
                return True
            return False

        def require_authorization(self) -> bool:
            if self.is_authorized():
                return True
            self.send_json(
                401,
                {
                    "ok": False,
                    "error": "authentication_required",
                    "message": "Đăng nhập tại /login rồi mở /kiem-kho. Nếu web khác nhúng, iframe cần allow-same-origin allow-scripts allow-forms.",
                    "login_url": "/login?next=/kiem-kho",
                },
            )
            return False

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self.add_embed_headers()
            self.send_header("content-length", "0")
            self.send_header("cache-control", "no-store")
            self.end_headers()

        def send_bytes(self, status_code: int, content_type: str, body: bytes) -> None:
            self.send_response(status_code)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.add_embed_headers()
            cookie = getattr(self, "session_cookie", None)
            if cookie:
                self.send_header("set-cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status_code: int, payload: dict[str, object]) -> None:
            self.send_bytes(
                status_code,
                "application/json; charset=utf-8",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )

        def read_json(self) -> dict[str, object]:
            length = int(self.headers.get("content-length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Request rỗng hoặc quá lớn")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("JSON không hợp lệ") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON phải là object")
            return payload

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/health":
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "release": os.environ.get("RENDER_GIT_COMMIT", "local")[:12],
                    },
                )
                return
            if parsed.path.startswith("/fonts/"):
                font_path = _frontend_font_path(Path(parsed.path).name)
                if font_path is None:
                    self.send_json(404, {"ok": False, "error": "font_missing"})
                    return
                self.send_bytes(200, "font/woff2", font_path.read_bytes())
                return
            if parsed.path == "/login":
                self.send_bytes(200, "text/html; charset=utf-8", LOGIN_HTML.encode("utf-8"))
                return
            if parsed.path in {"/", "/kiem-kho"}:
                query = urllib.parse.parse_qs(parsed.query)
                token = str((query.get("session") or [""])[0]).strip()
                if token:
                    self.apply_session_token(token)
                self.send_bytes(200, "text/html; charset=utf-8", load_frontend_html().encode("utf-8"))
                return
            if parsed.path == "/demo.jpg":
                if not demo_path.is_file():
                    self.send_json(404, {"ok": False, "error": "demo_image_missing"})
                    return
                content_type = "image/png" if demo_path.suffix.lower() == ".png" else "image/jpeg"
                self.send_bytes(200, content_type, demo_path.read_bytes())
                return
            if parsed.path == "/logo.jpg":
                if not logo_path.is_file():
                    self.send_json(404, {"ok": False, "error": "logo_image_missing"})
                    return
                content_type = "image/png" if logo_path.suffix.lower() == ".png" else "image/jpeg"
                self.send_bytes(200, content_type, logo_path.read_bytes())
                return
            if not self.require_authorization():
                return
            if parsed.path == "/api/measurement-image":
                query = urllib.parse.parse_qs(parsed.query)
                event_id = query.get("event_id", [""])[0]
                kind = query.get("kind", [""])[0]
                measurement = store.get(event_id)
                if measurement is None or kind not in {"core", "product"}:
                    self.send_json(404, {"ok": False, "error": "image_not_found"})
                    return
                image_path = Path(
                    measurement.image_path
                    if kind == "core"
                    else measurement.product_image_path
                )
                if not image_path.is_file():
                    self.send_json(404, {"ok": False, "error": "image_not_found"})
                    return
                self.send_bytes(200, "image/jpeg", image_path.read_bytes())
                return
            if parsed.path == "/api/photo-draft-image":
                event_id = urllib.parse.parse_qs(parsed.query).get("event_id", [""])[0]
                draft = store.get_photo_draft(event_id)
                image_path = Path(draft.image_path) if draft is not None else None
                if image_path is None or not image_path.is_file():
                    self.send_json(404, {"ok": False, "error": "image_not_found"})
                    return
                self.send_bytes(200, "image/jpeg", image_path.read_bytes())
                return
            if parsed.path == "/api/inventory-image":
                query = urllib.parse.parse_qs(parsed.query)
                event_id = query.get("event_id", [""])[0]
                check = store.get_inventory_check(event_id)
                image_path = Path(check.image_path) if check is not None else None
                if image_path is None or not image_path.is_file():
                    self.send_json(404, {"ok": False, "error": "image_not_found"})
                    return
                self.send_bytes(200, "image/jpeg", image_path.read_bytes())
                return
            if parsed.path == "/api/status":
                identity_status = service.status()
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "pending_count": store.pending_count(),
                        "yolo_enabled": service.reader.model is not None,
                         "yolo_mode": service.reader.yolo_mode,
                        "ocr_enabled": service.weight_engine != "gemini",
                        "ocr_engine": (
                            PADDLE_OCR_MODEL_NAME
                            if service.weight_engine != "gemini"
                            else None
                        ),
                        "ocr_min_confidence": service.ocr_min_confidence,
                        "sync_enabled": service.sync_worker is not None,
                        "image_provider": "cloudinary" if service.sync_worker is not None else "local",
                        "release": os.environ.get("RENDER_GIT_COMMIT", "local")[:12],
                        "quality_settings": service.quality_settings,
                        **identity_status,
                    },
                )
                return
            if parsed.path == "/api/production-orders":
                query = urllib.parse.parse_qs(parsed.query)
                work_date = str(query.get("work_date", [""])[0]).strip()
                shift = str(query.get("shift", [""])[0]).strip()
                machine = str(query.get("machine", [""])[0]).strip()
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", work_date):
                        raise ValueError
                    time.strptime(work_date, "%Y-%m-%d")
                except ValueError:
                    self.send_json(
                        422,
                        {
                            "ok": False,
                            "error": "invalid_input",
                            "message": "Ngày chọn LSX không hợp lệ",
                        },
                    )
                    return
                rows = [
                    {
                        "captured_at": item.captured_at,
                        "weight_raw": item.weight_raw,
                    }
                    for item in store.recent(200)
                ]
                orders, source, fallback_error, filter_relaxed = _load_production_orders(
                    work_date, shift=shift, machine=machine
                )
                if not orders and not _master_production_orders_configured():
                    orders = _production_orders_from_master(
                        rows, work_date, shift=shift, machine=machine
                    )
                    if orders:
                        source = "local"
                db_shifts, db_machines, suggestions = _production_order_filter_options(
                    work_date
                )
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "source": source,
                        "work_date": work_date,
                        "shift": shift or None,
                        "machine": machine or None,
                        "filter_relaxed": filter_relaxed,
                        "orders": orders,
                        "shifts": db_shifts,
                        "machines": db_machines,
                        "suggestions": suggestions,
                        "fallback_error": fallback_error or None,
                    },
                )
                return
            if parsed.path == "/api/measurements":
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    limit = max(1, min(int(query.get("limit", ["50"])[0]), 200))
                except ValueError:
                    limit = 50
                try:
                    offset = max(0, min(int(query.get("offset", ["0"])[0]), 50000))
                except ValueError:
                    offset = 0
                work_date = str(query.get("work_date", [""])[0]).strip()
                date_from = str(query.get("date_from", [""])[0]).strip()
                date_to = str(query.get("date_to", [""])[0]).strip()
                shift = str(query.get("shift", [""])[0]).strip()
                machine = str(query.get("machine", [""])[0]).strip()
                production_order = str(query.get("production_order", [""])[0]).strip()
                qr_code = str(query.get("qr_code", [""])[0]).strip()
                list_filters = {
                    "work_date": work_date,
                    "date_from": date_from,
                    "date_to": date_to,
                    "shift": shift,
                    "machine": machine,
                    "production_order": production_order,
                    "qr_code": qr_code,
                }
                local_total_count, local_error_count = _local_production_counts(
                    store,
                    **list_filters,
                )
                supabase_url = _supabase_project_url()
                publishable_key = _supabase_read_key()
                ingest_url = _ingest_api_url()
                ingest_token = _ingest_api_token()
                remote_items: list[dict[str, object]] | None = None
                remote_total_count: int | None = None
                remote_source = ""
                fallback_error = ""
                if supabase_url and publishable_key:
                    try:
                        remote_items = fetch_supabase_table(
                            supabase_url,
                            publishable_key,
                            limit=limit,
                            offset=offset,
                            **list_filters,
                        )
                        remote_source = "can_tu_dong"
                    except Exception as exc:
                        fallback_error = str(exc)
                if remote_items is None and ingest_url and ingest_token:
                    try:
                        remote_items, remote_total_count = _fetch_ingest_measurements_paged(
                            ingest_url,
                            ingest_token,
                            limit=limit,
                            offset=offset,
                            work_date=work_date,
                            date_from=date_from,
                            date_to=date_to,
                            shift=shift,
                            machine=machine,
                            production_order=production_order,
                            qr_code=qr_code,
                        )
                        remote_source = "can_tu_dong:ingest"
                    except Exception as exc:
                        fallback_error = "; ".join(
                            value for value in (fallback_error, str(exc)) if value
                        )
                if remote_items is None:
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "source": "local",
                            "fallback_error": fallback_error or None,
                            "work_date": work_date,
                            "date_from": date_from,
                            "date_to": date_to,
                            "shift": shift,
                            "machine": machine,
                            "production_order": production_order,
                            "qr_code": qr_code,
                            "total_count": local_total_count,
                            "error_count": local_error_count,
                            "count_exact": True,
                            "offset": offset,
                            "limit": limit,
                            "items": _local_production_items(
                                store, offset + limit, **list_filters
                            )[offset : offset + limit],
                        },
                    )
                    return
                count_error = ""
                if supabase_url and publishable_key and remote_source == "can_tu_dong":
                    try:
                        remote_total_count = fetch_supabase_table_count(
                            supabase_url,
                            publishable_key,
                            **list_filters,
                        )
                    except Exception as exc:
                        count_error = str(exc)
                remote_error_rows: list[dict[str, object]] | None = None
                remote_error_parent_ids: set[str] | None = None
                if supabase_url and publishable_key:
                    try:
                        remote_error_rows = fetch_supabase_photo_drafts(
                            supabase_url,
                            publishable_key,
                            work_date=work_date,
                            date_from=date_from,
                            date_to=date_to,
                            shift=shift,
                            machine=machine,
                            production_order=production_order,
                            qr_code=qr_code,
                        )
                        remote_error_parent_ids = {
                            parent_id
                            for item in remote_error_rows
                            if (
                                parent_id := str(
                                    item.get("parent_event_id")
                                    or item.get("event_id")
                                    or ""
                                ).strip()
                            )
                        }
                    except Exception as exc:
                        remote_error_rows = None
                        remote_error_parent_ids = None
                        count_error = "; ".join(
                            value for value in (count_error, str(exc)) if value
                        )
                items = []
                for item in remote_items:
                    core_url = item.get("core_image_url") or item.get("image_url")
                    product_url = item.get("product_image_url")
                    product_path = item.get("product_image_path")
                    if not product_url and isinstance(product_path, str) and product_path:
                        if supabase_url and publishable_key:
                            try:
                                product_url = sign_storage_image(
                                    supabase_url,
                                    publishable_key,
                                    product_path,
                                )
                            except Exception:
                                pass
                    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
                    raw_weight = str(metadata.get("weight_raw", "") or item.get("weight_raw", ""))
                    product_weight_value = item.get("product_weight")
                    if product_weight_value is None:
                        product_weight_value = metadata.get("product_weight")
                    if product_weight_value is None:
                        match = re.search(
                            r"(?:^|; )PRODUCT_WEIGHT=([0-9]+(?:\.[0-9]+)?)",
                            raw_weight,
                        )
                        product_weight_value = float(match.group(1)) if match else item.get("weight")
                    core_weight_value = metadata.get("core_weight")
                    if core_weight_value is None:
                        tare_value = item.get("tare_weight")
                        core_weight_value = tare_value if tare_value not in (None, 0, 0.0) else item.get("weight")
                    payload = {
                        "event_id": str(
                            item.get("event_id") or item.get("id") or ""
                        ),
                        "row_id": item.get("id"),
                        "qr_code": item.get("qr_code", ""),
                        "core_weight": core_weight_value,
                        "product_weight": product_weight_value,
                        "tare_weight": item.get("tare_weight"),
                        "net_weight": item.get("net_weight"),
                        "weight_raw": (
                            raw_weight
                            if raw_weight
                            else (
                                f"PRODUCT_WEIGHT={product_weight_value}"
                                if product_weight_value is not None
                                else ""
                            )
                        ),
                        "unit": item.get("unit", "kg"),
                        "captured_at": item.get("captured_at", ""),
                        "work_date": _item_source_date(item),
                        "shift": _item_source_value(item, "shift", "SOURCE_SHIFT"),
                        "machine": _item_source_value(item, "machine", "SOURCE_MACHINE"),
                        "production_order": _item_source_value(
                            item,
                            "production_order",
                            "SOURCE_PRODUCTION_ORDER",
                        ),
                        "error_status": _item_error_status(item),
                        "error_reason": _item_error_reason(item),
                        "sync_status": "synced",
                        "sync_error": None,
                        "core_image_url": core_url,
                        "product_image_url": product_url,
                        "has_core_image": bool(core_url),
                        "has_product_image": bool(product_url),
                    }
                    if _matches_source_filters(
                        payload,
                        **list_filters,
                    ):
                        items.append(payload)
                filters = list_filters
                local_measurement_ids = _local_measurement_event_ids(store, **filters)
                local_unsynced_measurement_ids = _local_measurement_event_ids(
                    store,
                    **filters,
                    unsynced_only=True,
                )
                local_unsynced_error_ids = (
                    _local_error_parent_ids(store, **filters, unsynced_only=True)
                    - local_measurement_ids
                )
                error_parent_ids = (
                    remote_error_parent_ids | local_unsynced_error_ids
                    if remote_error_parent_ids is not None
                    else _local_error_parent_ids(store, **filters) - local_measurement_ids
                )
                error_count = len(error_parent_ids)
                local_error_rows = store.photo_draft_source_rows()
                error_items = _photo_draft_display_items(
                    (remote_error_rows or []) + local_error_rows,
                    **filters,
                )
                measurement_item_ids = {
                    str(item.get("event_id") or "").strip() for item in items
                }
                items.extend(
                    item
                    for item in error_items
                    if str(item.get("event_id") or "").strip()
                    not in measurement_item_ids
                )
                items.sort(
                    key=lambda item: str(item.get("captured_at") or ""),
                    reverse=True,
                )
                items = items[:limit]
                if remote_total_count is not None:
                    measurement_count = remote_total_count + len(
                        local_unsynced_measurement_ids
                    )
                    count_exact = remote_error_parent_ids is not None
                else:
                    # Ingest GET has no filtered count; use returned window size.
                    measurement_count = max(len(items), len(local_unsynced_measurement_ids))
                    count_exact = False
                    if not count_error:
                        count_error = "Đếm gần đúng theo cửa sổ dữ liệu cloud gần nhất"
                total_count = measurement_count + error_count
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "source": remote_source or "can_tu_dong",
                        "fallback_error": fallback_error or None,
                        "work_date": work_date,
                        "date_from": date_from,
                        "date_to": date_to,
                        "shift": shift,
                        "machine": machine,
                        "production_order": production_order,
                        "qr_code": qr_code,
                        "offset": offset,
                        "limit": limit,
                        "total_count": total_count,
                        "error_count": error_count,
                        "count_exact": count_exact,
                        "count_error": count_error or None,
                        "items": items,
                    },
                )
                return
            if parsed.path == "/api/weighing-batches":
                query = urllib.parse.parse_qs(parsed.query)
                ingest_url = _ingest_api_url()
                ingest_token = _ingest_api_token()
                if not ingest_url or not ingest_token:
                    self.send_json(
                        503,
                        {
                            "ok": False,
                            "error": "supabase_not_configured",
                            "message": "Chưa cấu hình Supabase để đọc bảng ca_can",
                        },
                    )
                    return
                try:
                    items = fetch_remote_weigh_batches(
                        ingest_url,
                        ingest_token,
                        work_date=str(query.get("work_date", [""])[0]).strip(),
                        shift=str(query.get("shift", [""])[0]).strip(),
                        machine=str(query.get("machine", [""])[0]).strip(),
                        production_order=str(
                            query.get("production_order", [""])[0]
                        ).strip(),
                        limit=max(
                            1,
                            min(int(query.get("limit", ["50"])[0]), 200),
                        ),
                    )
                except (TypeError, ValueError):
                    self.send_json(
                        422,
                        {
                            "ok": False,
                            "error": "invalid_input",
                            "message": "Giới hạn danh sách đợt cân không hợp lệ",
                        },
                    )
                    return
                except Exception as exc:
                    self.send_json(
                        502,
                        {
                            "ok": False,
                            "error": "weighing_batch_list_failed",
                            "message": str(exc),
                        },
                    )
                    return
                self.send_json(
                    200,
                    {"ok": True, "source": "ca_can", "items": items},
                )
                return
            if parsed.path == "/api/inventory-checks":
                query = urllib.parse.parse_qs(parsed.query)
                try:
                    limit = max(1, min(int(query.get("limit", ["50"])[0]), 200))
                except ValueError:
                    limit = 50
                local_items = _local_inventory_items(store, limit)
                supabase_url = _supabase_project_url()
                publishable_key = _supabase_read_key()
                if not supabase_url or not publishable_key:
                    self.send_json(
                        200,
                        {"ok": True, "source": "local", "items": local_items},
                    )
                    return
                try:
                    remote_items = fetch_supabase_rows(
                        supabase_url,
                        publishable_key,
                        "can_kiem_kho",
                        limit=max(limit, 200),
                    )
                    remote_items.sort(
                        key=lambda item: str(item.get("captured_at", "")), reverse=True
                    )
                    for item in remote_items:
                        item["sync_status"] = "synced"
                        item["sync_error"] = None
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "source": "supabase",
                            "items": remote_items[:limit],
                        },
                    )
                except Exception as exc:
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "source": "local",
                            "fallback_error": str(exc),
                            "items": local_items,
                        },
                    )
                return
            if parsed.path == "/api/lookup":
                qr_code = urllib.parse.parse_qs(parsed.query).get("qr", [""])[0]
                try:
                    result = service.lookup(qr_code)
                    self.send_json(200 if result.get("found") else 404, result)
                except ValueError as exc:
                    self.send_json(422, {"ok": False, "error": "invalid_input", "message": str(exc)})
                except Exception as exc:
                    self.send_json(502, {"ok": False, "error": "lookup_failed", "message": str(exc)})
                return
            if parsed.path == "/api/panel/regions":
                station_id = urllib.parse.parse_qs(parsed.query).get("station_id", [""])[0]
                try:
                    self.send_json(
                        200,
                        {"ok": True, "regions": service.panel_regions(station_id)},
                    )
                except ValueError as exc:
                    self.send_json(
                        422,
                        {"ok": False, "error": "invalid_input", "message": str(exc)},
                    )
                return
            self.send_json(404, {"ok": False, "error": "not_found"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/login":
                try:
                    payload = self.read_json()
                    if not web_username:
                        self.send_json(200, {"ok": True, "session": "", "next": safe_login_next(str(payload.get("next", "")))})
                        return
                    username = str(payload.get("username", "")).strip()
                    password = str(payload.get("password", "")).strip()
                    if not (
                        _secrets_match(username, web_username)
                        and _secrets_match(password, web_password)
                    ):
                        self.send_json(
                            401,
                            {
                                "ok": False,
                                "error": "authentication_required",
                                "message": "Sai tên đăng nhập hoặc mật khẩu",
                            },
                        )
                        return
                    token = self.issue_session_cookie()
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "session": token,
                            "next": safe_login_next(str(payload.get("next", ""))),
                        },
                    )
                except ValueError as exc:
                    self.send_json(400, {"ok": False, "error": "invalid_input", "message": str(exc)})
                return
            if not self.require_authorization():
                return
            try:
                payload = self.read_json()
                if self.path == "/api/weighing-batches/confirm":
                    work_date = str(payload.get("work_date") or "").strip()
                    shift = str(payload.get("shift") or "").strip()
                    machine = str(payload.get("machine") or "").strip()
                    production_order = str(
                        payload.get("production_order") or ""
                    ).strip()
                    try:
                        milestone = int(payload.get("milestone"))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Mốc xác nhận không hợp lệ") from exc
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", work_date):
                        raise ValueError("Ngày cân không hợp lệ")
                    if not shift:
                        raise ValueError("Thiếu ca cân")
                    if not production_order:
                        raise ValueError("Thiếu Lệnh sản xuất")
                    if milestone < 10 or milestone % 10:
                        raise ValueError("Chỉ xác nhận theo từng nhóm đủ 10 cuộn")
                    ingest_url = _ingest_api_url()
                    ingest_token = _ingest_api_token()
                    if not ingest_url or not ingest_token:
                        raise ValueError("Chưa cấu hình Supabase để ghi bảng ca_can")
                    result = post_remote_action(
                        ingest_url,
                        ingest_token,
                        body={
                            "action": "confirm_weighing_batch",
                            "work_date": work_date,
                            "shift": shift[:80],
                            "machine": machine[:80],
                            "production_order": production_order[:80],
                            "milestone": milestone,
                            "confirmed_by": (web_username or "operator")[:120],
                        },
                    )
                    self.send_json(200, result)
                    return
                if self.path == "/api/session/discard":
                    discarded = service.discard_session(
                        str(payload.get("station_id", "")),
                        event_id=str(payload["event_id"]) if payload.get("event_id") else None,
                    )
                    self.send_json(200, {"ok": True, "discarded": discarded})
                    return
                if self.path == "/api/measurements/delete":
                    event_id = str(payload.get("event_id") or "").strip()
                    if not event_id:
                        raise ValueError("Thiếu event_id")
                    cloud_deleted = False
                    cloud_error = ""
                    ingest_url = _ingest_api_url()
                    ingest_token = _ingest_api_token()
                    if ingest_url and ingest_token:
                        try:
                            mutate_remote_measurement(
                                ingest_url,
                                ingest_token,
                                action="delete_measurement",
                                event_id=event_id,
                            )
                            cloud_deleted = True
                        except Exception as exc:
                            cloud_error = str(exc)
                    local_deleted = store.delete_measurement(event_id)
                    if not cloud_deleted and not local_deleted:
                        raise ValueError(
                            cloud_error or "Không tìm thấy dòng để xóa trên cloud/local"
                        )
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "deleted": True,
                            "event_id": event_id,
                            "cloud_deleted": cloud_deleted,
                            "local_deleted": local_deleted,
                            "cloud_error": cloud_error or None,
                        },
                    )
                    return
                if self.path == "/api/measurements/update":
                    event_id = str(payload.get("event_id") or "").strip()
                    qr_code = str(payload.get("qr_code") or "").strip()
                    work_date = str(payload.get("work_date") or "").strip()
                    shift = str(payload.get("shift") or "").strip()
                    machine = str(payload.get("machine") or "").strip()
                    production_order = str(payload.get("production_order") or "").strip()
                    error_status = str(payload.get("error_status") or "ok").strip().lower()
                    error_reason = str(payload.get("error_reason") or "").strip()[:500]
                    try:
                        core_weight = float(payload.get("core_weight"))
                        product_weight = float(payload.get("product_weight"))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Khối lượng không hợp lệ") from exc
                    if not event_id:
                        raise ValueError("Thiếu event_id")
                    if not qr_code:
                        raise ValueError("Mã SP không được trống")
                    if core_weight < 0 or product_weight < 0:
                        raise ValueError("Khối lượng phải ≥ 0")
                    if core_weight > product_weight:
                        raise ValueError(
                            "Cân lõi phải ≤ cân SP (ràng buộc DB: tare ≤ weight)"
                        )
                    if error_status not in {"ok", "error"}:
                        raise ValueError("Trạng thái lỗi không hợp lệ")
                    if error_status == "error" and not error_reason:
                        raise ValueError("Thiếu Lý do lỗi")
                    if error_status == "ok":
                        error_reason = ""
                    self.send_json(
                        200,
                        _persist_measurement_edit(
                            store,
                            event_id=event_id,
                            qr_code=qr_code,
                            core_weight=core_weight,
                            product_weight=product_weight,
                            work_date=work_date,
                            shift=shift,
                            machine=machine,
                            production_order=production_order,
                            error_status=error_status,
                            error_reason=error_reason,
                        ),
                    )
                    return
                if self.path == "/api/measurements/reread":
                    event_id = str(payload.get("event_id") or "").strip()
                    kind = str(payload.get("kind") or "").strip().lower()
                    image_url = str(payload.get("image_url") or "").strip()
                    qr_code = str(payload.get("qr_code") or "").strip()
                    work_date = str(payload.get("work_date") or "").strip()
                    shift = str(payload.get("shift") or "").strip()
                    machine = str(payload.get("machine") or "").strip()
                    production_order = str(
                        payload.get("production_order") or ""
                    ).strip()
                    unit = str(payload.get("unit") or "kg").strip() or "kg"
                    recognition_profile = str(
                        payload.get("recognition_profile") or "fast"
                    )
                    recognition_provider = str(
                        payload.get("recognition_provider") or "gemini"
                    )
                    if not event_id:
                        raise ValueError("Thiếu event_id")
                    if kind not in {"core", "product"}:
                        raise ValueError("kind phải là core hoặc product")
                    local = store.get(event_id)
                    previous_core: float | None = None
                    previous_product: float | None = None
                    previous_qr = qr_code
                    weight_raw = str(payload.get("weight_raw") or "").strip()
                    if local is not None:
                        previous_qr = previous_qr or str(local.qr_code or "").strip()
                        qr_code = previous_qr
                        previous_core = float(local.weight)
                        if local.product_weight is not None:
                            previous_product = float(local.product_weight)
                        weight_raw = weight_raw or (local.weight_raw or "")
                        if not work_date:
                            work_date = _item_source_date(
                                {
                                    "captured_at": local.captured_at,
                                    "weight_raw": local.weight_raw or "",
                                }
                            )
                        if not shift:
                            shift = _item_source_value(
                                {
                                    "weight_raw": local.weight_raw or "",
                                },
                                "shift",
                                "SOURCE_SHIFT",
                            )
                        if not machine:
                            machine = _item_source_value(
                                {"weight_raw": local.weight_raw or ""},
                                "machine",
                                "SOURCE_MACHINE",
                            )
                        if not production_order:
                            production_order = _item_source_value(
                                {"weight_raw": local.weight_raw or ""},
                                "production_order",
                                "SOURCE_PRODUCTION_ORDER",
                            )
                        unit = unit or local.unit or "kg"
                    try:
                        if previous_core is None:
                            previous_core = float(payload.get("core_weight"))
                        if previous_product is None:
                            previous_product = float(payload.get("product_weight"))
                    except (TypeError, ValueError) as exc:
                        raise ValueError(
                            "Thiếu khối lượng hiện tại để đọc lại"
                        ) from exc
                    image_bytes, image_source = _resolve_measurement_image_bytes(
                        store,
                        event_id=event_id,
                        kind=kind,
                        image_url=image_url,
                    )
                    frame = decode_image_bytes(image_bytes)
                    client_qr = str(payload.get("client_qr_code") or "").strip()
                    qr_result = (
                        _decode_product_qr_for_reread(service, frame, client_qr)
                        if kind == "product"
                        else {
                            "qr_code": "",
                            "qr_found": False,
                            "qr_conflict": False,
                            "qr_decoder": "",
                        }
                    )
                    # QR is decoded first and outside the AI queue, so a Gemini
                    # quota/network failure cannot discard a reliable QR result.
                    analysis: dict[str, object] = {}
                    weight_error = ""
                    try:
                        analysis = service.analyze(
                            frame,
                            "auto",
                            unit,
                            recognition_profile=recognition_profile,
                            recognition_provider=recognition_provider,
                            capture_kind=kind,
                            client_qr_code=("" if kind == "product" else previous_qr),
                        )
                    except Exception as exc:
                        weight_error = str(exc)
                    weight_found = bool(analysis.get("weight_found"))
                    new_weight: float | None = None
                    if weight_found:
                        try:
                            new_weight = float(analysis.get("weight"))
                        except (TypeError, ValueError) as exc:
                            raise ValueError("AI trả số cân không hợp lệ") from exc
                        if not math.isfinite(new_weight) or new_weight < 0:
                            raise ValueError("Số cân AI đọc được không hợp lệ")
                    elif kind == "core" or not qr_result.get("qr_found"):
                        detail = f": {weight_error}" if weight_error else ""
                        raise ValueError(
                            "AI không đọc được số cân từ ảnh "
                            + ("lõi" if kind == "core" else "SP")
                            + detail
                        )
                    core_weight = previous_core
                    product_weight = previous_product
                    read_qr = str(qr_result.get("qr_code") or "").strip()
                    qr_found = bool(qr_result.get("qr_found"))
                    qr_conflict = bool(qr_result.get("qr_conflict"))
                    qr_decoder = str(qr_result.get("qr_decoder") or "")
                    if kind == "core":
                        assert new_weight is not None
                        core_weight = new_weight
                        weight_raw = _upsert_raw_tag(
                            weight_raw, "HUMAN_CONFIRMED_CORE", f"{new_weight:g}"
                        )
                        weight_raw = _upsert_raw_tag(
                            weight_raw, "REREAD_CORE", f"{new_weight:g}"
                        )
                    else:
                        if new_weight is not None:
                            product_weight = new_weight
                            weight_raw = _upsert_raw_tag(
                                weight_raw, "PRODUCT_WEIGHT", f"{new_weight:g}"
                            )
                            weight_raw = _upsert_raw_tag(
                                weight_raw,
                                "HUMAN_CONFIRMED_PRODUCT",
                                f"{new_weight:g}",
                            )
                            weight_raw = _upsert_raw_tag(
                                weight_raw, "REREAD_PRODUCT", f"{new_weight:g}"
                            )
                        if read_qr:
                            qr_code = read_qr
                            weight_raw = _upsert_raw_tag(
                                weight_raw, "PRODUCT_ENTRY_CODE", read_qr
                            )
                            weight_raw = _upsert_raw_tag(
                                weight_raw, "REREAD_QR", read_qr
                            )
                            weight_raw = _upsert_raw_tag(
                                weight_raw, "REREAD_QR_DECODER", qr_decoder[:80]
                            )
                    if not str(qr_code or "").strip():
                        raise ValueError(
                            "Thiếu mã QR"
                            + (
                                " và không đọc lại được từ ảnh SP"
                                if kind == "product"
                                else ""
                            )
                        )
                    if float(core_weight) > float(product_weight):
                        raise ValueError(
                            "Cân lõi phải ≤ cân SP sau khi đọc lại "
                            f"({core_weight:g} > {product_weight:g})"
                        )
                    ai_raw = str(analysis.get("weight_raw") or "").strip()
                    if ai_raw:
                        weight_raw = _upsert_raw_tag(
                            weight_raw,
                            "REREAD_AI_RAW",
                            ai_raw.replace(";", ",")[:180],
                        )
                    persisted = _persist_measurement_edit(
                        store,
                        event_id=event_id,
                        qr_code=qr_code,
                        core_weight=float(core_weight),
                        product_weight=float(product_weight),
                        work_date=work_date,
                        shift=shift,
                        machine=machine,
                        production_order=production_order,
                        weight_raw=weight_raw,
                    )
                    product_code = ""
                    if read_qr:
                        if "_" in read_qr:
                            product_code = read_qr.split("_", 1)[0].strip()
                        elif "-" in read_qr:
                            product_code = read_qr.split("-", 1)[0].strip()
                        else:
                            product_code = read_qr
                    persisted.update(
                        {
                            "kind": kind,
                            "previous_core_weight": previous_core,
                            "previous_product_weight": previous_product,
                            "previous_qr_code": previous_qr,
                            "read_weight": new_weight,
                            "read_qr_code": read_qr or None,
                            "qr_found": qr_found,
                            "qr_conflict": qr_conflict,
                            "qr_decoder": qr_decoder or None,
                            "product_code": product_code or None,
                            "image_source": image_source,
                            "weight_found": weight_found,
                            "weight_error": weight_error or None,
                            "quality_pass": bool(analysis.get("quality_pass")),
                            "recognition_source": analysis.get("recognition_source"),
                            "recognition_provider": analysis.get(
                                "recognition_provider"
                            ),
                            "weight_raw_ai": ai_raw or None,
                        }
                    )
                    self.send_json(200, persisted)
                    return
                if self.path == "/api/codex/login":
                    if service.codex_reader is None:
                        raise ValueError("Codex chưa được bật trên máy backend")
                    self.send_json(
                        200,
                        service.codex_reader.start_device_login(
                            force=bool(payload.get("force"))
                        ),
                    )
                    return
                if self.path == "/api/codex/login/poll":
                    if service.codex_reader is None:
                        raise ValueError("Codex chưa được bật trên máy backend")
                    poll_login = getattr(service.codex_reader, "poll_device_login", None)
                    if poll_login is None:
                        raise ValueError("Chế độ Codex local không dùng đăng nhập web")
                    self.send_json(200, poll_login(str(payload.get("session_id", ""))))
                    return
                if self.path == "/api/gemini/key":
                    self.send_json(200, service.replace_gemini_key(str(payload.get("api_key", ""))))
                    return
                if self.path == "/api/gemini/backup-key":
                    self.send_json(
                        200,
                        service.save_gemini_backup_key(str(payload.get("api_key", ""))),
                    )
                    return
                if self.path == "/api/gemini/key-slot":
                    self.send_json(
                        200,
                        service.switch_gemini_key(str(payload.get("slot", ""))),
                    )
                    return
                if self.path == "/api/panel/regions":
                    self.send_json(
                        200,
                        {
                            "ok": True,
                            "regions": service.save_panel_regions(
                                str(payload.get("station_id", "")),
                                payload.get("regions"),
                            ),
                        },
                    )
                    return
                frame = decode_image(str(payload.get("image", "")))
                if self.path == "/api/panel/detect":
                    self.send_json(
                        200,
                        service.detect_panel_regions(
                            frame,
                            recognition_profile=str(
                                payload.get("recognition_profile", "fast")
                            ),
                        ),
                    )
                    return
                if self.path == "/api/panel/analyze":
                    self.send_json(
                        200,
                        service.analyze_panel_regions(
                            frame,
                            payload.get("regions"),
                            recognition_profile=str(payload.get("recognition_profile", "fast")),
                        ),
                    )
                    return
                product_frame = (
                    decode_image(str(payload.get("product_image", "")))
                    if payload.get("product_image")
                    else None
                )
                if self.path == "/api/decode":
                    self.send_json(200, service.decode_qr(frame))
                    return
                if self.path == "/api/photo-capture":
                    result = service.capture_photo_draft(
                        frame,
                        client_qr_code=str(payload.get("client_qr_code", "")),
                        event_id=str(payload.get("event_id", "")) or None,
                        parent_event_id=str(payload.get("parent_event_id", "")),
                        capture_kind=str(payload.get("capture_kind", "core")),
                        capture_round=int(payload.get("capture_round", 0)),
                        station_id=str(payload.get("station_id", "")),
                        camera_id=str(payload.get("camera_id", "")),
                        work_date=str(payload.get("work_date", "")),
                        shift=str(payload.get("shift", "")),
                        machine=str(payload.get("machine", "")),
                        production_order=str(payload.get("production_order", "")),
                    )
                    self.send_json(201, result)
                    return
                if self.path == "/api/analyze":
                    capture_kind = str(payload.get("capture_kind", "")).strip().lower()
                    if capture_kind and capture_kind not in {"core", "product", "inventory"}:
                        raise ValueError(
                            "capture_kind phải là core, product hoặc inventory"
                        )
                    encoded_weight_frames = payload.get("weight_frames", [])
                    if not isinstance(encoded_weight_frames, list):
                        raise ValueError("weight_frames phải là danh sách")
                    if len(encoded_weight_frames) >= MAX_BURST_FRAMES:
                        raise ValueError(
                            f"Burst chỉ được tối đa {MAX_BURST_FRAMES} frame kể cả ảnh chính"
                        )
                    weight_frames = []
                    for encoded_frame in encoded_weight_frames:
                        if not isinstance(encoded_frame, str):
                            raise ValueError("Burst chứa ảnh không hợp lệ")
                        weight_frames.append(decode_image(encoded_frame))
                    bind_core = capture_kind != "product"
                    result = service.analyze(
                        frame,
                        str(payload.get("roi", "")),
                        str(payload.get("unit", "kg")),
                        event_id=str(payload["event_id"]) if bind_core and payload.get("event_id") else None,
                        station_id=str(payload["station_id"]) if bind_core and payload.get("station_id") else None,
                        camera_id=str(payload["camera_id"]) if bind_core and payload.get("camera_id") else None,
                        weight_frames=weight_frames,
                        require_temporal=bool(payload.get("camera_capture", False)),
                        recognition_profile=str(payload.get("recognition_profile", "fast")),
                        recognition_provider=str(payload.get("recognition_provider", "gemini")),
                        capture_kind=capture_kind,
                        client_qr_code=str(payload.get("client_qr_code", "")),
                        context_station_id=str(payload.get("station_id", "")) or None,
                    )
                    if (
                        capture_kind
                        and result.get("weight_found")
                        and result.get("quality_pass")
                    ):
                        evidence_frame = (
                            decode_image(str(result["evidence_image"]))
                            if result.get("evidence_image")
                            else frame
                        )
                        staged = service.stage_evidence_step(
                            evidence_frame,
                            event_id=str(payload.get("event_id", "")),
                            station_id=str(payload.get("station_id", "")),
                            kind=capture_kind,
                            weight=float(result["weight"]),
                            unit=str(result.get("unit", payload.get("unit", "kg"))),
                            qr_code=str(result.get("qr_code", "")),
                        )
                        result["step_saved"] = True
                        result["step_image_path"] = staged["image_path"]
                    self.send_json(200, result)
                    return
                if self.path == "/api/factory-sample":
                    metadata = {
                        "predicted_qr_code": str(payload.get("predicted_qr_code", ""))[:512],
                        "predicted_weight": payload.get("predicted_weight"),
                        "expected_qr_code": str(payload.get("expected_qr_code", ""))[:512],
                        "expected_weight": payload.get("expected_weight"),
                        "unit": str(payload.get("unit", "kg")),
                        "recognition_ok": bool(payload.get("recognition_ok", False)),
                        "qr_decoder": str(payload.get("qr_decoder", ""))[:100],
                        "ocr_confidence": payload.get("ocr_confidence"),
                    }
                    result = service.save_factory_sample(
                        frame,
                        str(payload.get("qr_roi", "")),
                        metadata,
                    )
                    self.send_json(201, result)
                    return
                if self.path == "/api/capture":
                    try:
                        weight = float(payload.get("weight", ""))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Số cân không hợp lệ") from exc
                    weight_raw = _merge_source_tags(str(payload.get("weight_raw", "")), payload)
                    if not _raw_tag(weight_raw, "SOURCE_PRODUCTION_ORDER"):
                        raise ValueError("Thiếu Lệnh sản xuất")
                    product_weight_value = payload.get("product_weight")
                    if product_weight_value is None:
                        product_match = re.search(
                            r"(?:^|; )PRODUCT_WEIGHT=([0-9]+(?:\.[0-9]+)?)",
                            weight_raw,
                        )
                        product_weight_value = product_match.group(1) if product_match else None
                    result = service.capture(
                        str(payload.get("qr_code", "")),
                        weight,
                        str(payload.get("unit", "kg")),
                        frame,
                        bool(payload.get("vision_confirmed", False)),
                        weight_raw,
                        product_frame=product_frame,
                        product_weight=float(product_weight_value)
                        if product_weight_value is not None
                        else None,
                        event_id=str(payload["event_id"]) if payload.get("event_id") else None,
                        analysis_id=str(payload["analysis_id"])
                        if payload.get("analysis_id")
                        else None,
                        station_id=str(payload["station_id"])
                        if payload.get("station_id")
                        else None,
                        camera_id=str(payload["camera_id"])
                        if payload.get("camera_id")
                        else None,
                        frame_sha256=str(payload["frame_sha256"])
                        if payload.get("frame_sha256")
                        else None,
                    )
                    self.send_json(201, result)
                    return
                if self.path == "/api/inventory-capture":
                    try:
                        inventory_weight = float(payload.get("weight", ""))
                        inventory_core_weight = float(payload.get("core_weight", 0))
                        inventory_tare_weight = float(payload.get("tare_weight", 0))
                    except (TypeError, ValueError) as exc:
                        raise ValueError("Số cân kiểm kho không hợp lệ") from exc
                    result = service.capture_inventory(
                        str(payload.get("product_code", payload.get("qr_code", ""))),
                        inventory_weight,
                        inventory_core_weight,
                        inventory_tare_weight,
                        str(payload.get("unit", "kg")),
                        frame,
                        bool(payload.get("vision_confirmed", False)),
                        str(payload.get("weight_raw", "")),
                        event_id=str(payload["event_id"])
                        if payload.get("event_id")
                        else None,
                        analysis_id=str(payload["analysis_id"])
                        if payload.get("analysis_id")
                        else None,
                        station_id=str(payload["station_id"])
                        if payload.get("station_id")
                        else None,
                        camera_id=str(payload["camera_id"])
                        if payload.get("camera_id")
                        else None,
                        frame_sha256=str(payload["frame_sha256"])
                        if payload.get("frame_sha256")
                        else None,
                    )
                    self.send_json(201, result)
                    return
                self.send_json(404, {"ok": False, "error": "not_found"})
            except EventIdConflictError as exc:
                self.send_json(
                    409,
                    {"ok": False, "error": "event_id_conflict", "message": str(exc)},
                )
            except (SessionConflictError, AnalysisBindingMismatch) as exc:
                self.send_json(409, {"ok": False, "error": "session_conflict", "message": str(exc)})
            except InferenceQueueFull as exc:
                self.send_json(503, {"ok": False, "error": "inference_queue_full", "message": str(exc)})
            except ValueError as exc:
                self.send_json(422, {"ok": False, "error": "invalid_input", "message": str(exc)})
            except Exception as exc:
                self.send_json(500, {"ok": False, "error": "server_error", "message": str(exc)})

        def log_message(self, format: str, *args: object) -> None:
            return None

    return ThreadingHTTPServer((args.host, args.port), Handler), service


def run(args: argparse.Namespace) -> int:
    server, service = create_server(args)
    service.start_ocr_preload()
    print(f"Test UI: http://{args.host}:{server.server_port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    finally:
        server.server_close()
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()
        service.store.close()
    return 0


def main() -> None:
    _load_local_dotenv()
    try:
        raise SystemExit(run(build_parser().parse_args()))
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
