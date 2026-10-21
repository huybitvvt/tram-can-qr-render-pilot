"""Backend-side checks for digits that are unsupported by the LED pixels."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

import cv2
import numpy as np


def resolve_weak_crop_disagreement(frame: np.ndarray, run: object, detector: object) -> None:
    """Use two alternate crops to break a low-confidence digit-row tie."""

    display = getattr(run, "display", None)
    digits = getattr(run, "digits", None)
    if (
        not display
        or not digits
        or min(float(item.confidence) for item in digits) >= 0.45
    ):
        return
    if "red" not in {
        str(color).strip().lower()
        for color in getattr(detector, "display_colors", ("red",))
    }:
        return

    previous_scale = float(getattr(run, "crop_scale", 1.0) or 1.0)
    if previous_scale <= 0:
        return
    height, width = frame.shape[:2]
    center_x = (display.x1 + display.x2) / 2
    center_y = (display.y1 + display.y2) / 2
    base_width = display.width / previous_scale
    base_height = display.height / previous_scale

    def crop_region(scale: float) -> object:
        half_width = base_width * scale / 2
        half_height = base_height * scale / 2
        x1 = max(0, round(center_x - half_width))
        y1 = max(0, round(center_y - half_height))
        x2 = min(width, round(center_x + half_width))
        y2 = min(height, round(center_y + half_height))
        return type(display)(x1, y1, x2, y2, display.color, display.locator_score)

    baseline = sorted(digits, key=lambda item: item.box.x + item.box.width / 2)
    readings = [baseline]
    predict = getattr(detector, "_predict_crop", None)
    if not callable(predict):
        return
    for scale in (0.7, 1.0):
        proposals, _ = predict(frame, crop_region(scale), "original")
        accepted = [
            item
            for item in proposals
            if float(item.confidence) >= float(getattr(detector, "confidence", 0.0))
        ]
        if 3 <= len(accepted) <= 6:
            readings.append(
                sorted(accepted, key=lambda item: item.box.x + item.box.width / 2)
            )

    signatures = ["".join(str(item.value) for item in row) for row in readings]
    winner, votes = Counter(signatures).most_common(1)[0]
    if winner != signatures[0] and votes > len(readings) / 2:
        run.digits[:] = readings[signatures.index(winner)]


def remove_unlit_trailing_digit(
    frame: np.ndarray,
    digits: Sequence[object],
    *,
    display_colors: Iterable[str],
) -> list[object]:
    """Drop a low-confidence trailing box that is not illuminated red.

    Small red LED displays can produce a spurious final digit from nearby
    reflections or printed marks. This conservative check only applies to
    red-display cameras and requires all three signals: a strong prefix, a
    weak trailing detection, and little red LED evidence inside that box.
    """

    ordered = sorted(digits, key=lambda item: item.box.x + item.box.width / 2)
    colors = {str(color).strip().lower() for color in display_colors}
    if (
        "red" not in colors
        or len(ordered) < 4
        or not all(str(item.value).isdigit() for item in ordered)
    ):
        return ordered

    trailing = ordered[-1]
    prefix = ordered[:-1]
    prefix_confidence = min(float(item.confidence) for item in prefix)
    trailing_confidence = float(trailing.confidence)
    widths = [float(item.box.width) for item in prefix]
    median_width = float(np.median(widths)) if widths else 0.0
    if (
        prefix_confidence < 0.50
        or trailing_confidence >= 0.50
        or prefix_confidence - trailing_confidence < 0.08
        or median_width <= 0
        or float(trailing.box.width) < median_width * 1.25
    ):
        return ordered

    height, width = frame.shape[:2]
    x1 = max(0, int(np.floor(trailing.box.x)))
    y1 = max(0, int(np.floor(trailing.box.y)))
    x2 = min(width, int(np.ceil(trailing.box.x + trailing.box.width)))
    y2 = min(height, int(np.ceil(trailing.box.y + trailing.box.height)))
    if x2 <= x1 or y2 <= y1:
        return ordered

    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    red_led = (
        ((hue <= 15) | (hue >= 165))
        & (hsv[:, :, 1] >= 80)
        & (hsv[:, :, 2] >= 100)
    )
    if float(np.mean(red_led)) > 0.12:
        return ordered

    return prefix
