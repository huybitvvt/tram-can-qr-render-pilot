"""Find small illuminated displays in a full camera frame."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np


HSV_PROFILES = {
    "red": (((0, 80, 100), (15, 255, 255)), ((165, 80, 100), (179, 255, 255))),
    "green": (((35, 70, 80), (90, 255, 255)),),
    "blue": (((90, 70, 80), (135, 255, 255)),),
}


@dataclass(frozen=True)
class DisplayRegion:
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


def _iou(first: DisplayRegion, second: DisplayRegion) -> float:
    x1 = max(first.x1, second.x1)
    y1 = max(first.y1, second.y1)
    x2 = min(first.x2, second.x2)
    y2 = min(first.y2, second.y2)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union else 0.0


def locate_display_candidates(
    image: np.ndarray,
    *,
    colors: Sequence[str] = ("red",),
    max_candidates: int = 3,
) -> list[DisplayRegion]:
    """Return color and geometry based display proposals in full-frame coordinates."""
    if image is None or not isinstance(image, np.ndarray) or image.ndim != 3:
        raise ValueError("image must be a BGR color image")
    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")
    requested = tuple(dict.fromkeys(color.strip().lower() for color in colors))
    if not requested or any(color not in HSV_PROFILES for color in requested):
        raise ValueError("display colors must be red, green, or blue")

    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    close_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (_odd(round(width * 0.019)), _odd(round(height * 0.007)))
    )
    dilation_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (_odd(round(width * 0.008)), _odd(round(height * 0.005)))
    )
    regions: list[DisplayRegion] = []
    for color in requested:
        raw_mask = np.zeros((height, width), dtype=np.uint8)
        for lower, upper in HSV_PROFILES[color]:
            raw_mask |= cv2.inRange(hsv, lower, upper)
        grouped = cv2.morphologyEx(raw_mask, cv2.MORPH_CLOSE, close_kernel)
        grouped = cv2.dilate(grouped, dilation_kernel, iterations=1)
        contours, _ = cv2.findContours(grouped, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, box_width, box_height = cv2.boundingRect(contour)
            if box_width < max(20, round(width * 0.018)):
                continue
            if box_height < max(8, round(height * 0.007)):
                continue
            aspect = box_width / box_height
            if not 1.2 <= aspect <= 8.0:
                continue
            if box_width > width * 0.40 or box_height > height * 0.25:
                continue
            raw_region = raw_mask[y : y + box_height, x : x + box_width]
            density = cv2.countNonZero(raw_region) / (box_width * box_height)
            if density < 0.015:
                continue
            _, _, stats, _ = cv2.connectedComponentsWithStats(raw_region)
            areas = [int(area) for area in stats[1:, cv2.CC_STAT_AREA] if area >= 3]
            total_area = sum(areas)
            dominance = max(areas, default=0) / total_area if total_area else 1.0
            score = (
                density
                + min(len(areas), 6) * 0.02
                + (1.0 - dominance) * 0.60
                + max(0.0, 0.2 - abs(aspect - 2.2) * 0.05)
            )
            padding_x = round(box_width * 0.35)
            padding_y = round(box_height * 0.70)
            regions.append(DisplayRegion(
                max(0, x - padding_x), max(0, y - padding_y),
                min(width, x + box_width + padding_x),
                min(height, y + box_height + padding_y), color, score,
            ))

    regions.sort(key=lambda region: region.locator_score, reverse=True)
    selected: list[DisplayRegion] = []
    for region in regions:
        if all(_iou(region, other) < 0.45 for other in selected):
            selected.append(region)
        if len(selected) == max_candidates:
            break
    return selected


def scaled_region(region: DisplayRegion, scale: float, image_shape: tuple[int, ...]) -> DisplayRegion:
    """Scale a candidate around its center and clip it to the frame."""
    height, width = image_shape[:2]
    center_x = (region.x1 + region.x2) / 2
    center_y = (region.y1 + region.y2) / 2
    half_width = region.width * scale / 2
    half_height = region.height * scale / 2
    return DisplayRegion(
        max(0, round(center_x - half_width)),
        max(0, round(center_y - half_height)),
        min(width, round(center_x + half_width)),
        min(height, round(center_y + half_height)),
        region.color, region.locator_score,
    )
