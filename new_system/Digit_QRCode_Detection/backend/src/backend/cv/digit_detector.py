"""Locate the illuminated display, then recognize digits in its crop."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass
from collections.abc import Sequence
import logging
import time

import cv2
import numpy as np
from ultralytics import YOLO

from backend.cv.display_locator import DisplayRegion, locate_display_candidates, scaled_region
from backend.cv.types import Box, Digit

logger = logging.getLogger(__name__)

MODEL_1_DIGITS = {index: str(index) for index in range(10)}
MODEL_2_SYMBOLS = {0: "-", 1: ".", **{index + 2: str(index) for index in range(10)}}


def _model_version(names: dict[int, str]) -> str:
    actual = {int(index): str(name).strip().lower() for index, name in names.items()}
    legacy_digits = all(
        actual.get(index) in {symbol, f"number {symbol}"}
        for index, symbol in MODEL_1_DIGITS.items()
    )
    if legacy_digits and (
        len(actual) == 10 or (len(actual) == 11 and actual.get(10) == "none")
    ):
        return "model_1"
    if len(actual) == 12 and all(
        actual.get(index) == symbol for index, symbol in MODEL_2_SYMBOLS.items()
    ):
        return "model_2"
    raise ValueError(
        "MODEL_PATH must use model_1 (classes 0-9, optional 10='none') "
        "or model_2 (0='-', 1='.', 2-11='0'..'9'); "
        f"got {names!r}"
    )


@dataclass(frozen=True)
class DetectionRun:
    digits: list[Digit]
    display: DisplayRegion | None
    candidate_count: int
    crop_scale: float | None
    preprocessing: str | None
    ignored_none_count: int
    inference_count: int
    elapsed_ms: float
    model_version: str = "model_1"


def _iou(first: Digit, second: Digit) -> float:
    a, b = first.box, second.box
    overlap = max(0.0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x)) * max(0.0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    union = a.width * a.height + b.width * b.height - overlap
    return overlap / union if union else 0.0


def _filter_row(digits: list[Digit]) -> list[Digit]:
    selected: list[Digit] = []
    for digit in sorted(digits, key=lambda item: item.confidence, reverse=True):
        if all(_iou(digit, other) < 0.45 for other in selected):
            selected.append(digit)
    if len(selected) >= 3:
        numeric = [item for item in selected if str(item.value).isdigit()]
        reference = numeric if len(numeric) >= 2 else selected
        median_height = float(np.median([item.box.height for item in reference]))
        median_area = float(np.median([item.box.width * item.box.height for item in reference]))
        median_center = float(np.median([item.box.y + item.box.height / 2 for item in reference]))
        selected = [
            item for item in selected
            if item.box.height >= (0.05 if item.value == "-" else 0.45) * median_height
            and item.box.width * item.box.height <= 2.0 * median_area
            and abs(item.box.y + item.box.height / 2 - median_center)
            <= (0.85 if item.value == "-" else 0.7) * median_height
        ]
    return sorted(selected, key=lambda item: item.box.x + item.box.width / 2)


def _reading_score(region: DisplayRegion, digits: list[Digit]) -> float:
    if not digits:
        return region.locator_score * 0.1
    centers = [item.box.y + item.box.height / 2 for item in digits]
    median_height = float(np.median([item.box.height for item in digits]))
    spread = (max(centers) - min(centers)) / median_height if median_height else 1.0
    return len(digits) * 0.8 + sum(item.confidence for item in digits) + region.locator_score * 0.2 + max(0.0, 1.0 - spread) * 0.25


def _refine_ambiguous_digit(image: np.ndarray, digit: Digit) -> Digit:
    """Resolve the model's recurring 2/3/5 confusion from lit segment geometry."""
    if str(digit.value) not in {"2", "3", "5"}:
        return digit
    height, width = image.shape[:2]
    x1 = max(0, int(np.floor(digit.box.x)))
    y1 = max(0, int(np.floor(digit.box.y)))
    x2 = min(width, int(np.ceil(digit.box.x + digit.box.width)))
    y2 = min(height, int(np.ceil(digit.box.y + digit.box.height)))
    crop = image[y1:y2, x1:x2]
    if crop.size == 0 or crop.shape[0] < 12 or crop.shape[1] < 8:
        return digit

    value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
    bright = value > np.percentile(value, 65)
    crop_height, crop_width = bright.shape

    def occupancy(left: float, right: float, top: float, bottom: float) -> float:
        sample = bright[
            round(crop_height * top):round(crop_height * bottom),
            round(crop_width * left):round(crop_width * right),
        ]
        return float(np.mean(sample)) if sample.size else 0.0

    upper_left = occupancy(0.00, 0.35, 0.18, 0.45)
    upper_right = occupancy(0.65, 1.00, 0.18, 0.45)
    lower_left = occupancy(0.00, 0.35, 0.55, 0.82)
    lower_right = occupancy(0.65, 1.00, 0.55, 0.82)

    refined: str | None = None
    if upper_right - upper_left > 0.15 and lower_right - lower_left > 0.15:
        refined = "3"
    elif upper_left - upper_right > 0.15 and lower_right >= lower_left - 0.10:
        refined = "5"
    elif lower_left - lower_right > 0.15:
        refined = "2"
    if refined is None or refined == str(digit.value):
        return digit

    class_id = int(refined) if isinstance(digit.value, int) else int(refined) + 2
    logger.debug("segment refinement: model=%s refined=%s box=%s", digit.value, refined, digit.box.as_dict())
    return Digit(int(refined) if isinstance(digit.value, int) else refined, digit.confidence, digit.box, class_id)


class DigitDetector:
    def __init__(self, model_path: Path, confidence: float, *, display_colors: Sequence[str] = ("red",), max_candidates: int = 5, image_size: int = 640) -> None:
        self.confidence = confidence
        self.display_colors = tuple(display_colors)
        self.max_candidates = max_candidates
        self.image_size = image_size
        self.model = YOLO(str(model_path))
        self.model_version = _model_version(self.model.names)
        logger.info("Digit model mapping: %s", self.model_version)

    def _predict_crop(self, image: np.ndarray, region: DisplayRegion, preprocessing: str) -> tuple[list[Digit], int]:
        crop = image[region.y1:region.y2, region.x1:region.x2]
        if preprocessing == "sharpened":
            crop = cv2.detailEnhance(crop, sigma_s=10, sigma_r=0.15)
        result = self.model.predict(source=crop, conf=min(self.confidence, 0.05), imgsz=self.image_size, verbose=False)[0]
        detections: list[Digit] = []
        ignored_none = 0
        if result.boxes is None:
            return detections, ignored_none
        for coordinates, class_id, score in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist(), strict=True):
            class_index = int(class_id)
            if self.model_version == "model_1" and class_index == 10:
                ignored_none += 1
                continue
            if self.model_version == "model_2" and class_index == 1:
                # The scale has a fixed two-place reading; a predicted dot is
                # not needed for inference, confidence, or the frontend overlay.
                continue
            symbols = MODEL_1_DIGITS if self.model_version == "model_1" else MODEL_2_SYMBOLS
            if class_index not in symbols:
                raise ValueError(f"Invalid model class id: {class_index}")
            value: int | str = class_index if self.model_version == "model_1" else symbols[class_index]
            x1, y1, x2, y2 = coordinates
            detections.append(Digit(value, float(score), Box(float(x1 + region.x1), float(y1 + region.y1), float(x2 - x1), float(y2 - y1)), class_index))
        logger.debug("crop=%s preprocessing=%s raw=%s ignored_none=%s", region.bbox, preprocessing, [(item.value, round(item.confidence, 3), item.box.as_dict()) for item in detections], ignored_none)
        detections = [_refine_ambiguous_digit(image, item) for item in detections]
        return _filter_row(detections), ignored_none

    def detect_with_details(self, image: np.ndarray) -> DetectionRun:
        started = time.perf_counter()
        candidates = locate_display_candidates(image, colors=self.display_colors, max_candidates=self.max_candidates)
        logger.debug("display locator: candidates=%s regions=%s", len(candidates), [(item.color, item.bbox, round(item.locator_score, 3)) for item in candidates])
        if not candidates:
            return DetectionRun([], None, 0, None, None, 0, 0, (time.perf_counter() - started) * 1000, self.model_version)
        best: tuple[float, DisplayRegion, float, str, list[Digit], int] | None = None
        inference_count = 0
        for candidate in candidates:
            for scale in (0.6, 0.7, 0.8, 1.0):
                region = scaled_region(candidate, scale, image.shape)
                if region.width < 20 or region.height < 10:
                    continue
                for preprocessing in (("original", "sharpened") if scale == 0.7 else ("original",)):
                    proposals, ignored_none = self._predict_crop(image, region, preprocessing)
                    inference_count += 1
                    accepted = [item for item in proposals if item.confidence >= self.confidence]
                    score = _reading_score(region, accepted)
                    logger.debug("crop score: region=%s scale=%.1f preprocessing=%s accepted=%s score=%.3f", region.bbox, scale, preprocessing, [(item.value, round(item.confidence, 3)) for item in accepted], score)
                    if best is None or score > best[0]:
                        best = (score, region, scale, preprocessing, accepted, ignored_none)
        if best is None:
            return DetectionRun([], None, len(candidates), None, None, 0, inference_count, (time.perf_counter() - started) * 1000, self.model_version)
        _, region, scale, preprocessing, digits, ignored_none = best
        elapsed_ms = (time.perf_counter() - started) * 1000
        if digits:
            logger.info("display selected: roi=%s color=%s scale=%.1f preprocessing=%s passes=%s ignored_none=%s digits=%s elapsed_ms=%.1f", region.bbox, region.color, scale, preprocessing, inference_count, ignored_none, [(item.value, round(item.confidence, 3), item.box.as_dict()) for item in digits], elapsed_ms)
        else:
            logger.debug("display selected without digits: roi=%s color=%s scale=%.1f preprocessing=%s passes=%s ignored_none=%s elapsed_ms=%.1f", region.bbox, region.color, scale, preprocessing, inference_count, ignored_none, elapsed_ms)
        return DetectionRun(digits, region, len(candidates), scale, preprocessing, ignored_none, inference_count, elapsed_ms, self.model_version)

    def detect(self, image: np.ndarray) -> list[Digit]:
        return self.detect_with_details(image).digits
