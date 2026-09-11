from __future__ import annotations

import base64
import json
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path


class IngestResponseError(RuntimeError):
    """The cloud did not acknowledge the exact event that was sent."""


def fetch_remote_json(
    url: str,
    token: str,
    *,
    params: dict[str, object] | None = None,
    timeout: float = 10.0,
) -> dict[str, object]:
    separator = "&" if "?" in url else "?"
    query = urllib.parse.urlencode(params or {})
    request_url = f"{url}{separator}{query}" if query else url
    request = urllib.request.Request(
        request_url,
        headers={"Accept": "application/json", "X-Device-Token": token},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Supabase response is invalid")
    return parsed


def fetch_remote_measurement_page(
    url: str,
    token: str,
    *,
    limit: int = 50,
    offset: int = 0,
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    work_date: str = "",
    qr_code: str = "",
    timeout: float = 30.0,
) -> tuple[list[dict[str, object]], int | None]:
    params: dict[str, object] = {
        "limit": max(1, min(limit, 1000)),
        "offset": max(0, int(offset)),
    }
    if date_from:
        params["date_from"] = date_from
    if date_to:
        params["date_to"] = date_to
    if work_date:
        params["work_date"] = work_date
    if shift:
        params["shift"] = shift
    if machine:
        params["machine"] = machine
    if production_order:
        params["production_order"] = production_order
    if qr_code:
        params["qr_code"] = qr_code
    parsed = fetch_remote_json(url, token, params=params, timeout=timeout)
    if parsed.get("ok") is not True:
        raise RuntimeError("Supabase list response is invalid")
    items = parsed.get("items")
    if not isinstance(items, list):
        raise RuntimeError("Supabase list response has no items")
    total_value = parsed.get("total_count")
    total_count = (
        int(total_value)
        if isinstance(total_value, (int, float)) and int(total_value) >= 0
        else None
    )
    return [item for item in items if isinstance(item, dict)], total_count


def fetch_remote_measurements(
    url: str,
    token: str,
    **options: object,
) -> list[dict[str, object]]:
    items, _ = fetch_remote_measurement_page(url, token, **options)
    return items


def mutate_remote_measurement(
    url: str,
    token: str,
    *,
    action: str,
    event_id: str,
    payload: dict[str, object] | None = None,
    timeout: float = 30.0,
) -> dict[str, object]:
    body = {"action": action, "event_id": str(event_id).strip()}
    if payload:
        body.update(payload)
    return post_remote_action(url, token, body=body, timeout=timeout)


def post_remote_action(
    url: str,
    token: str,
    *,
    body: dict[str, object],
    timeout: float = 30.0,
) -> dict[str, object]:
    """Post a non-image command to the authenticated ingest Edge Function."""

    action = str(body.get("action") or "remote_action")
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Device-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            raise RuntimeError(f"Cloud {action} failed: HTTP {exc.code}") from exc
        message = str(parsed.get("error") or parsed.get("message") or detail)
        detail_text = str(parsed.get("detail") or "").strip()
        if detail_text and detail_text not in message:
            message = f"{message}: {detail_text}"
        raise RuntimeError(message) from exc
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        message = str((parsed or {}).get("error") or f"{action} failed")
        detail_text = str((parsed or {}).get("detail") or "").strip()
        if detail_text and detail_text not in message:
            message = f"{message}: {detail_text}"
        raise RuntimeError(message)
    return parsed


def fetch_remote_weigh_batches(
    url: str,
    token: str,
    *,
    work_date: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    limit: int = 50,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "action": "weighing-batches",
        "limit": max(1, min(int(limit), 200)),
    }
    for field, value in (
        ("work_date", work_date),
        ("shift", shift),
        ("machine", machine),
        ("production_order", production_order),
    ):
        selected = str(value or "").strip()
        if selected:
            params[field] = selected
    parsed = fetch_remote_json(url, token, params=params, timeout=timeout)
    if parsed.get("ok") is not True or not isinstance(parsed.get("items"), list):
        raise RuntimeError("Supabase ca_can response is invalid")
    return [item for item in parsed["items"] if isinstance(item, dict)]


def fetch_supabase_rows(
    supabase_url: str,
    publishable_key: str,
    table: str,
    *,
    limit: int = 500,
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    query = urllib.parse.urlencode({
        "select": "*",
        "limit": max(1, min(limit, 1000)),
    })
    encoded_table = urllib.parse.quote(table, safe="")
    request = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/rest/v1/{encoded_table}?{query}",
        headers={
            "Accept": "application/json",
            "apikey": publishable_key,
            "Authorization": f"Bearer {publishable_key}",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, list):
        raise RuntimeError(f"Supabase {table} response is invalid")
    return [item for item in parsed if isinstance(item, dict)]


def fetch_supabase_table(
    supabase_url: str,
    publishable_key: str,
    *,
    limit: int = 50,
    offset: int = 0,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    params: dict[str, object] = {
        "select": (
            "id,event_id,image_url,core_image_url,product_image_url,"
            "product_image_path,qr_code,weight,tare_weight,net_weight,unit,"
            "captured_at,error_status,error_reason,metadata"
        ),
        "order": "captured_at.desc",
        "limit": max(1, min(limit, 200)),
        "offset": max(0, int(offset)),
    }
    if work_date:
        params["metadata->>work_date"] = f"eq.{work_date}"
    elif date_from and date_to:
        params["and"] = (
            f"(metadata->>work_date.gte.{date_from},"
            f"metadata->>work_date.lte.{date_to})"
        )
    elif date_from:
        params["metadata->>work_date"] = f"gte.{date_from}"
    elif date_to:
        params["metadata->>work_date"] = f"lte.{date_to}"
    for field, value in (
        ("shift", shift),
        ("machine", machine),
        ("production_order", production_order),
    ):
        selected = str(value or "").strip()
        if selected:
            params[f"metadata->>{field}"] = f"eq.{selected}"
    selected_qr = str(qr_code or "").strip()
    if selected_qr:
        safe = selected_qr.replace("*", "").replace(",", "").replace(")", "")
        if safe:
            params["qr_code"] = f"ilike.*{safe}*"
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/rest/v1/can_tu_dong?{query}",
        headers={
            "Accept": "application/json",
            "apikey": publishable_key,
            "Authorization": f"Bearer {publishable_key}",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, list):
        raise RuntimeError("Supabase can_tu_dong response is invalid")
    return [item for item in parsed if isinstance(item, dict)]


def fetch_supabase_table_count(
    supabase_url: str,
    publishable_key: str,
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
    timeout: float = 10.0,
) -> int:
    """Return an exact count for the selected production source filters."""

    params: dict[str, object] = {"select": "event_id", "limit": 1}
    if work_date:
        params["metadata->>work_date"] = f"eq.{work_date}"
    elif date_from and date_to:
        params["and"] = (
            f"(metadata->>work_date.gte.{date_from},"
            f"metadata->>work_date.lte.{date_to})"
        )
    elif date_from:
        params["metadata->>work_date"] = f"gte.{date_from}"
    elif date_to:
        params["metadata->>work_date"] = f"lte.{date_to}"
    for field, value in (
        ("shift", shift),
        ("machine", machine),
        ("production_order", production_order),
    ):
        selected = str(value or "").strip()
        if selected:
            params[f"metadata->>{field}"] = f"eq.{selected}"
    selected_qr = str(qr_code or "").strip()
    if selected_qr:
        safe = selected_qr.replace("*", "").replace(",", "").replace(")", "")
        if safe:
            params["qr_code"] = f"ilike.*{safe}*"
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/rest/v1/can_tu_dong?{query}",
        headers={
            "Accept": "application/json",
            "apikey": publishable_key,
            "Authorization": f"Bearer {publishable_key}",
            "Prefer": "count=exact",
            "Range-Unit": "items",
            "Range": "0-0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_range = str(response.headers.get("Content-Range", ""))
    if "/" not in content_range:
        raise RuntimeError("Supabase count response has no Content-Range")
    total = content_range.rsplit("/", 1)[-1]
    if not total.isdigit():
        raise RuntimeError("Supabase count response is invalid")
    return int(total)


def fetch_supabase_photo_drafts(
    supabase_url: str,
    service_key: str,
    *,
    work_date: str = "",
    date_from: str = "",
    date_to: str = "",
    shift: str = "",
    machine: str = "",
    production_order: str = "",
    qr_code: str = "",
    timeout: float = 10.0,
) -> list[dict[str, object]]:
    """Return saved unreadable photos for production-list display."""

    saved_rows: list[dict[str, object]] = []
    page_size = 1000
    for page in range(50):
        params: dict[str, object] = {
            "select": (
                "parent_event_id,event_id,capture_kind,capture_round,qr_code,"
                "captured_at,image_url,work_date,shift,machine,production_order,status"
            ),
            "order": "captured_at.desc",
            "limit": page_size,
            "offset": page * page_size,
        }
        if work_date:
            params["work_date"] = f"eq.{work_date}"
        elif date_from and date_to:
            params["and"] = f"(work_date.gte.{date_from},work_date.lte.{date_to})"
        elif date_from:
            params["work_date"] = f"gte.{date_from}"
        elif date_to:
            params["work_date"] = f"lte.{date_to}"
        for field, value in (("shift", shift), ("machine", machine), ("production_order", production_order)):
            selected = str(value or "").strip()
            if selected:
                params[field] = f"eq.{selected}"
        selected_qr = str(qr_code or "").strip()
        if selected_qr:
            safe = selected_qr.replace("*", "").replace(",", "").replace(")", "")
            if safe:
                params["qr_code"] = f"ilike.*{safe}*"
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{supabase_url.rstrip('/')}/rest/v1/anh_can_cho_ai?{query}",
            headers={
                "Accept": "application/json",
                "apikey": service_key,
                "Authorization": f"Bearer {service_key}",
            },
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if not isinstance(parsed, list):
            raise RuntimeError("Supabase anh_can_cho_ai response is invalid")
        rows = [item for item in parsed if isinstance(item, dict)]
        saved_rows.extend(rows)
        if len(rows) < page_size:
            return saved_rows
    raise RuntimeError("Supabase saved-error count exceeds the safe page limit")


def fetch_supabase_photo_draft_parent_ids(
    supabase_url: str,
    service_key: str,
    **filters: object,
) -> set[str]:
    """Return distinct production events whose unreadable photos were saved."""

    return {
        parent_id
        for item in fetch_supabase_photo_drafts(supabase_url, service_key, **filters)
        if (
            parent_id := str(
                item.get("parent_event_id") or item.get("event_id") or ""
            ).strip()
        )
    }


def delete_supabase_photo_drafts(
    supabase_url: str,
    service_key: str,
    parent_event_id: str,
    *,
    timeout: float = 10.0,
) -> int:
    """Delete every saved-error photo belonging to one displayed production row."""

    event_id = str(parent_event_id or "").strip()
    if not event_id or any(character in event_id for character in ",()"):
        raise ValueError("Invalid photo draft parent event ID")
    params = {
        "select": "event_id,parent_event_id",
        "or": f"(parent_event_id.eq.{event_id},event_id.eq.{event_id})",
    }
    request = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/rest/v1/anh_can_cho_ai?{urllib.parse.urlencode(params)}",
        headers={
            "Accept": "application/json",
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Prefer": "return=representation",
        },
        method="DELETE",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read().decode("utf-8"))
    if not isinstance(parsed, list):
        raise RuntimeError("Supabase anh_can_cho_ai delete response is invalid")
    return len(parsed)


def persist_product_evidence(
    supabase_url: str,
    service_key: str,
    *,
    event_id: str,
    gateway_id: str,
    image_path: str | Path,
    product_weight: float,
    timeout: float = 20.0,
) -> dict[str, object]:
    object_path = f"{gateway_id}/product-weight/{event_id}.jpg"
    encoded_path = urllib.parse.quote(object_path, safe="/")
    auth_headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    upload = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/storage/v1/object/roll-captures/{encoded_path}",
        data=Path(image_path).read_bytes(),
        headers={**auth_headers, "Content-Type": "image/jpeg", "x-upsert": "true"},
        method="POST",
    )
    with urllib.request.urlopen(upload, timeout=timeout):
        pass
    stable_url = (
        f"{supabase_url.rstrip('/')}/storage/v1/object/authenticated/"
        f"roll-captures/{encoded_path}"
    )
    product_fields = {
        "product_weight": float(product_weight),
        "product_image_path": object_path,
        "product_image_url": stable_url,
        "product_image_public_id": object_path,
    }
    patch_url = (
        f"{supabase_url.rstrip('/')}/rest/v1/can_tu_dong?"
        f"event_id=eq.{urllib.parse.quote(event_id)}&select=*"
    )
    def patch_row(fields: dict[str, object]) -> list[object]:
        patch = urllib.request.Request(
            patch_url,
            data=json.dumps(fields).encode("utf-8"),
            headers={
                **auth_headers,
                "Content-Type": "application/json",
                "Prefer": "return=representation",
            },
            method="PATCH",
        )
        with urllib.request.urlopen(patch, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
        return value if isinstance(value, list) else []
    try:
        rows = patch_row(product_fields)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:
            raise
        product_fields.pop("product_weight", None)
        rows = patch_row(product_fields)
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError("Supabase product evidence update matched no event")
    return rows[0]


def sign_storage_image(
    supabase_url: str,
    service_key: str,
    object_path: str,
    *,
    expires_in: int = 3600,
    timeout: float = 10.0,
) -> str:
    encoded_path = urllib.parse.quote(object_path, safe="/")
    request = urllib.request.Request(
        f"{supabase_url.rstrip('/')}/storage/v1/object/sign/roll-captures/{encoded_path}",
        data=json.dumps({"expiresIn": expires_in}).encode("utf-8"),
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    signed = payload.get("signedURL") if isinstance(payload, dict) else None
    if not isinstance(signed, str) or not signed:
        raise RuntimeError("Supabase Storage did not return a signed URL")
    return f"{supabase_url.rstrip('/')}/storage/v1{signed}"


def validate_ingest_response(
    response: dict[str, object],
    expected_event_id: str,
    *,
    require_remote_image: bool = True,
    require_product_image: bool = False,
) -> dict[str, object]:
    if response.get("ok") is not True:
        raise IngestResponseError("ingest response did not report ok=true")
    response_event_id = response.get("event_id")
    if not isinstance(response_event_id, str) or response_event_id != expected_event_id:
        raise IngestResponseError("ingest response event_id does not match the sent event")
    remote_id = response.get("id")
    if isinstance(remote_id, bool):
        raise IngestResponseError("ingest response id must be a positive integer")
    if isinstance(remote_id, int):
        valid_remote_id = remote_id > 0
    elif isinstance(remote_id, str):
        valid_remote_id = remote_id.isdigit() and int(remote_id) > 0
    else:
        valid_remote_id = False
    if not valid_remote_id:
        raise IngestResponseError("ingest response id must be a positive integer")
    if require_remote_image:
        core_pair = (response.get("core_image_url"), response.get("core_image_public_id"))
        legacy_pair = (response.get("image_url"), response.get("image_public_id"))
        if not any(
            all(isinstance(value, str) and value.strip() for value in pair)
            for pair in (core_pair, legacy_pair)
        ):
            raise IngestResponseError(
                "ingest response must confirm persisted core-weight evidence"
            )
    if require_product_image:
        product_pair = (
            response.get("product_image_url"),
            response.get("product_image_public_id"),
        )
        if not all(isinstance(value, str) and value.strip() for value in product_pair):
            raise IngestResponseError(
                "ingest response must confirm persisted product-weight evidence"
            )
    return response


def post_measurement(
    url: str,
    payload: dict[str, object],
    image_path: str | Path,
    token: str,
    timeout: float = 10.0,
) -> dict[str, object]:
    body = dict(payload)
    body["image_base64"] = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    # The shared ingest endpoint routes one-photo inventory checks separately
    # while preserving the established core-weight role for production slips.
    workflow = body.get("workflow")
    body["image_role"] = (
        "inventory_check"
        if workflow == "inventory_check"
        else "photo_draft"
        if workflow == "photo_draft"
        else "core_weight"
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Device-Token": token,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response_body = response.read()
        if not 200 <= response.status < 300:
            raise RuntimeError(f"API returned HTTP {response.status}")
    if not response_body:
        return {}
    parsed = json.loads(response_body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("API response must be a JSON object")
    return parsed
