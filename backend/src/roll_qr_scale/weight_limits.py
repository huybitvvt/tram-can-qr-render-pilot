"""Limits for production core and whole-roll scale readings, in kg."""

import math
import unicodedata


def validate_production_weights(core: float, product: float, unit: str, machine: str) -> None:
    factor = {"kg": 1, "g": 0.001, "lb": 0.45359237}.get(unit)
    if factor is None:
        raise ValueError("Đơn vị không hợp lệ")
    if any(not math.isfinite(value) or value < 0 for value in (core, product)):
        raise ValueError("Khối lượng phải là số hữu hạn không âm")
    name = "".join(c for c in unicodedata.normalize("NFD", machine.lower()) if not unicodedata.combining(c))
    limit = 9 if "bao bi" in name else 15.5 if "cach nhiet" in name else None
    if core * factor > 1.2 + 1e-12:
        raise ValueError("Không cho lưu: lõi giấy vượt 1,2 kg")
    if limit is not None and product * factor > limit + 1e-12:
        label = str(limit).replace(".", ",")
        raise ValueError(f"Không cho lưu: khối lượng cuộn ({machine}) vượt {label} kg")
