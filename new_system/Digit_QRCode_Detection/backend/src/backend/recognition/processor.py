"""Combine independent QR and digit results into one recognition event."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any

from backend.cv.types import Digit, QrResult
from backend.recognition.stabilizer import Stabilizer


def build_recognition(
    *, captured_at: datetime, frame_width: int, frame_height: int,
    qr: QrResult | None, digits: list[Digit], threshold: float,
    decimal_places: int, stabilizer: Stabilizer, model_version: str = "model_1",
) -> dict[str, Any]:
    ordered = sorted(
        (digit for digit in digits if not (model_version == "model_2" and digit.value == ".")),
        key=lambda detection: detection.box.x + detection.box.width / 2,
    )
    raw_digits = "".join(str(digit.value) for digit in ordered) or None
    confidence = min((digit.confidence for digit in ordered), default=None)
    value: float | None = None
    if raw_digits is not None:
        if model_version == "model_1" and re.fullmatch(r"[0-9]+", raw_digits):
            value = int(raw_digits) / 10 ** decimal_places
        elif model_version == "model_2" and re.fullmatch(r"-?[0-9]+", raw_digits):
            value = int(raw_digits) / 10 ** decimal_places
    key = (qr.data, raw_digits) if qr is not None and value is not None and confidence is not None and confidence >= threshold else None
    stable = stabilizer.update(key)
    if qr is None and raw_digits is None:
        status = "WAITING"
    elif qr is None or value is None:
        status = "INCOMPLETE"
    elif confidence is not None and confidence < threshold:
        status = "LOW_CONFIDENCE"
    elif stable:
        status = "READY_TO_SAVE"
    else:
        status = "DETECTING"
    detections: list[dict[str, Any]] = []
    if qr is not None:
        detections.append({"type": "qr", "confidence": 1.0, "bbox": qr.box.as_dict()})
    detections.extend({"type": "digit", "class": digit.class_id if digit.class_id is not None else digit.value, "value": digit.value, "confidence": digit.confidence, "bbox": digit.box.as_dict()} for digit in ordered)
    return {
        "type": "recognition", "timestamp": int(captured_at.timestamp() * 1000),
        "frame_width": frame_width, "frame_height": frame_height,
        "detections": detections, "qr": {"data": qr.data} if qr else None,
        "raw_digits": raw_digits, "numeric_value": value,
        "confidence": confidence, "status": status,
    }
