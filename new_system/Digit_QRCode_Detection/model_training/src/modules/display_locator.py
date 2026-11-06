"""Locate illuminated seven-segment displays with OpenCV color masks."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np

HSV_PROFILES: dict[
    str, tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]
] = {
    "red": (
        ((0, 80, 100), (15, 255, 255)),
        ((165, 80, 100), (179, 255, 255)),
    ),
    "green": (((35, 70, 80), (90, 255, 255)),),
    "blue": (((90, 70, 80), (135, 255, 255)),),
}


@dataclass(frozen=True)
class DisplayRegion:
    """A padded display candidate in full-image coordinates."""

    x1: int
    y1: int
    x2: int
    y2: int
    color: str
    locator_score: float

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return self.x1, self.y1, self.x2, self.y2


def _odd(value: int) -> int:
    value = max(3, value)
    return value if value % 2 else value + 1


def _intersection_over_union(first: DisplayRegion, second: DisplayRegion) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    first_area = first.width * first.height
    second_area = second.width * second.height
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _color_mask(hsv: np.ndarray, color: str) -> np.ndarray:
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in HSV_PROFILES[color]:
        mask |= cv2.inRange(hsv, lower, upper)
    return mask


def locate_display_candidates(
    image: np.ndarray,
    *,
    colors: Sequence[str] = ("red",),
    max_candidates: int = 5,
) -> list[DisplayRegion]:
    """Return likely illuminated display regions ordered by locator score."""
    if image is None or not isinstance(image, np.ndarray) or image.ndim != 3:
        raise ValueError("image must be a valid BGR image.")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1.")

    requested_colors = tuple(dict.fromkeys(color.strip().lower() for color in colors))
    unknown = sorted(set(requested_colors) - set(HSV_PROFILES))
    if unknown:
        raise ValueError(
            f"Unsupported display colors: {unknown}. "
            f"Choose from {sorted(HSV_PROFILES)}."
        )

    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (_odd(round(width * 0.019)), _odd(round(height * 0.007))),
    )
    dilation_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT,
        (_odd(round(width * 0.008)), _odd(round(height * 0.005))),
    )
    regions: list[DisplayRegion] = []

    for color in requested_colors:
        raw_mask = _color_mask(hsv, color)
        grouped = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, close_kernel)
        grouped = cv2.dilate(grouped, dilation_kernel, iterations=1)
        contours, _ = cv2.findContours(
            grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for contour in contours:
            x, y, candidate_width, candidate_height = cv2.boundingRect(contour)
            if candidate_width < max(20, round(width * 0.018)):
                continue
            if candidate_height < max(8, round(height * 0.007)):
                continue
            aspect_ratio = candidate_width / candidate_height
            if not 1.2 <= aspect_ratio <= 8.0:
                continue
            if candidate_width > width * 0.40 or candidate_height > height * 0.25:
                continue

            raw_pixels = cv2.countNonZero(
                raw_mask[y : y + candidate_height, x : x + candidate_width]
            )
            density = raw_pixels / (candidate_width * candidate_height)
            if density < 0.015:
                continue

            raw_region = raw_mask[
                y : y + candidate_height,
                x : x + candidate_width,
            ]
            _, _, component_stats, _ = cv2.connectedComponentsWithStats(raw_region)
            component_areas = [
                int(area) for area in component_stats[1:, cv2.CC_STAT_AREA] if area >= 3
            ]
            component_count = len(component_areas)
            component_total = sum(component_areas)
            dominance = (
                max(component_areas, default=0) / component_total
                if component_total
                else 1.0
            )

            padding_x = round(candidate_width * 0.35)
            padding_y = round(candidate_height * 0.70)
            x1 = max(0, x - padding_x)
            y1 = max(0, y - padding_y)
            x2 = min(width, x + candidate_width + padding_x)
            y2 = min(height, y + candidate_height + padding_y)
            # Seven-segment displays usually contain several separated bright
            # components with an overall aspect ratio near 2:1. These terms
            # prevent a single solid-colored machine panel from winning only
            # because its color mask is dense.
            component_score = min(component_count, 6) * 0.02
            separation_score = (1.0 - dominance) * 0.60
            aspect_score = max(0.0, 0.2 - abs(aspect_ratio - 2.2) * 0.05)
            score = density + component_score + separation_score + aspect_score
            regions.append(DisplayRegion(x1, y1, x2, y2, color, score))

    regions.sort(key=lambda region: region.locator_score, reverse=True)
    selected: list[DisplayRegion] = []
    for region in regions:
        if all(_intersection_over_union(region, other) < 0.45 for other in selected):
            selected.append(region)
        if len(selected) == max_candidates:
            break
    return selected
