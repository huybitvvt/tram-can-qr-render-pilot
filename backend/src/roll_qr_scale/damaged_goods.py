"""Identity and destination for photographed damaged goods; no schema changes."""
import re

DAMAGED_KINDS = ("NKM", "NC", "RM")
DAMAGED_WAREHOUSE = "Kho hàng hỏng"


def damaged_kind(item: dict) -> str:
    raw = str(item.get("weight_raw") or "")
    metadata = item.get("metadata")
    if not raw and isinstance(metadata, dict):
        raw = str(metadata.get("weight_raw") or "")
    match = re.search(r"(?:^|; )DAMAGED_KIND=(NKM|NC|RM)(?:;|$)", raw)
    return match.group(1) if match else ""


def warehouse_for_items(items: list[dict], requested: str) -> str:
    damaged = [bool(damaged_kind(item)) for item in items]
    if any(damaged) and not all(damaged):
        raise ValueError("Đẩy riêng hàng hỏng và hàng thành phẩm")
    return DAMAGED_WAREHOUSE if any(damaged) else requested
