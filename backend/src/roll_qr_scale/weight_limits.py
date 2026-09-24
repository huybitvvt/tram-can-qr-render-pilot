"""Validate production scale readings before they are saved."""

import math


def validate_production_weights(
    core: float | None,
    product: float | None,
    unit: str,
    machine: str,
) -> None:
    factor = {"kg": 1, "g": 0.001, "lb": 0.45359237}.get(unit)
    if factor is None:
        raise ValueError("Đơn vị không hợp lệ")
    values = (value for value in (core, product) if value is not None)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("Khối lượng phải là số hữu hạn không âm")
