# ==========================================================================
# PURPOSE: Digit detection from a single image.
# ==========================================================================
# IMPORTS & MODULE LOADING
# ==========================================================================

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

import cv2
import numpy as np
from ultralytics import YOLO

from .display_locator import DisplayRegion, locate_display_candidates
from .utils import draw_detections, draw_display_region

# ==========================================================================
# PARAMETERS
# ==========================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_PATH = PROJECT_ROOT / "model" / "best.pt"

# ==================================================
# model_1: legacy checkpoints (best_0.pt, best_1.pt, best_2.pt)
# ==================================================
# Class IDs 0-9 are digits 0-9; optional class 10 is "none".
MODEL_1_DIGITS = {index: str(index) for index in range(10)}

# ==================================================
# model_2: current best.pt
# ==================================================
# Class 0 is '-', class 1 is '.', and class IDs 2-11 are digits 0-9.
MODEL_2_SYMBOLS = {0: "-", 1: ".", **{index + 2: str(index) for index in range(10)}}

# ==========================================================================
# CORE LOGIC & FUNCTIONS
# ==========================================================================


class DetectionResult(TypedDict):
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class RecognitionOutput:
    """Detailed result from display localization and digit recognition."""

    annotated_image: np.ndarray
    detections: list[DetectionResult]
    roi: tuple[int, int, int, int] | None
    display_color: str | None
    candidate_count: int
    raw_digits: str | None
    ignored_none_count: int
    failure_reason: str | None
    crop_scale: float | None = None
    crop_preprocessing: str | None = None
    model_version: str = "model_1"


def _validate_model(model: YOLO) -> str:
    actual_names = {
        int(index): str(name).strip().lower() for index, name in model.names.items()
    }
    # ==================================================
    # model_1: legacy 0-9 + optional none
    # ==================================================
    legacy_digits = all(
        actual_names.get(index) in {symbol, f"number {symbol}"}
        for index, symbol in MODEL_1_DIGITS.items()
    )
    if legacy_digits and (
        len(actual_names) == 10
        or (len(actual_names) == 11 and actual_names.get(10) == "none")
    ):
        return "model_1"

    # ==================================================
    # model_2: '-', '.', then 0-9
    # ==================================================
    if len(actual_names) == 12 and all(
        actual_names.get(index) == symbol for index, symbol in MODEL_2_SYMBOLS.items()
    ):
        return "model_2"

    raise ValueError(
        "The model must use model_1 (classes 0-9, optional 10='none') "
        "or model_2 (0='-', 1='.', 2-11='0'..'9'); "
        f"got {model.names!r}."
    )


def _predict_region(
    model: YOLO,
    image: np.ndarray,
    region: DisplayRegion,
    *,
    confidence: float,
    image_size: int,
    crop_override: np.ndarray | None = None,
    model_version: str | None = None,
) -> tuple[list[DetectionResult], int]:
    model_version = model_version or _validate_model(model)
    crop = (
        crop_override
        if crop_override is not None
        else image[region.y1 : region.y2, region.x1 : region.x2]
    )
    result = model.predict(
        source=crop,
        conf=confidence,
        imgsz=image_size,
        verbose=False,
    )[0]
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return [], 0

    detections: list[DetectionResult] = []
    ignored_none_count = 0
    for coordinates, class_id, score in zip(
        boxes.xyxy.cpu().numpy(),
        boxes.cls.cpu().numpy().astype(int),
        boxes.conf.cpu().numpy(),
        strict=True,
    ):
        class_index = int(class_id)
        if model_version == "model_1" and class_index == 10:
            ignored_none_count += 1
            continue
        symbols = MODEL_1_DIGITS if model_version == "model_1" else MODEL_2_SYMBOLS
        if class_index not in symbols:
            continue
        x1, y1, x2, y2 = (float(value) for value in coordinates)
        detections.append(
            {
                "class_id": class_index,
                "class_name": symbols[class_index],
                "confidence": float(score),
                "bbox": (
                    x1 + region.x1,
                    y1 + region.y1,
                    x2 + region.x1,
                    y2 + region.y1,
                ),
            }
        )
    detections.sort(key=lambda detection: detection["bbox"][0])
    return detections, ignored_none_count


def _scaled_region(
    region: DisplayRegion, scale: float, image_shape: tuple[int, ...]
) -> DisplayRegion:
    """Tighten or expand a candidate around its center without leaving the frame."""
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
        region.color,
        region.locator_score,
    )


def _overlap(first: DetectionResult, second: DetectionResult) -> float:
    ax1, ay1, ax2, ay2 = first["bbox"]
    bx1, by1, bx2, by2 = second["bbox"]
    intersection = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0.0, min(ay2, by2) - max(ay1, by1)
    )
    first_area = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    second_area = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _deduplicate_digits(detections: list[DetectionResult]) -> list[DetectionResult]:
    """Keep the best class per position, including boxes of different classes."""
    selected: list[DetectionResult] = []
    for detection in sorted(
        detections, key=lambda item: item["confidence"], reverse=True
    ):
        if all(_overlap(detection, other) < 0.45 for other in selected):
            selected.append(detection)
    return sorted(selected, key=lambda item: (item["bbox"][0] + item["bbox"][2]) / 2)


def _consistent_digit_row(detections: list[DetectionResult]) -> list[DetectionResult]:
    """Discard short or vertically displaced boxes outside the display reading."""
    if len(detections) < 3:
        return detections
    # model_2 punctuation can be much shorter than digits; estimate the row
    # from numeric glyphs so a real decimal point or minus is not discarded.
    digit_detections = [
        item for item in detections if item["class_name"] not in {"-", "."}
    ]
    reference = digit_detections if len(digit_detections) >= 2 else detections
    reference_heights = np.array(
        [detection["bbox"][3] - detection["bbox"][1] for detection in reference]
    )
    reference_areas = np.array(
        [
            (detection["bbox"][2] - detection["bbox"][0])
            * (detection["bbox"][3] - detection["bbox"][1])
            for detection in reference
        ]
    )
    reference_centers_y = np.array(
        [(detection["bbox"][1] + detection["bbox"][3]) / 2 for detection in reference]
    )
    median_height = float(np.median(reference_heights))
    median_area = float(np.median(reference_areas))
    median_center = float(np.median(reference_centers_y))
    heights = [detection["bbox"][3] - detection["bbox"][1] for detection in detections]
    areas = [
        (detection["bbox"][2] - detection["bbox"][0])
        * (detection["bbox"][3] - detection["bbox"][1])
        for detection in detections
    ]
    centers_y = [
        (detection["bbox"][1] + detection["bbox"][3]) / 2 for detection in detections
    ]
    return [
        detection
        for detection, height, area, center_y in zip(
            detections, heights, areas, centers_y, strict=True
        )
        if height
        >= (0.05 if detection["class_name"] in {"-", "."} else 0.45) * median_height
        and area <= 2.0 * median_area
        and abs(center_y - median_center)
        <= (0.85 if detection["class_name"] in {"-", "."} else 0.7) * median_height
    ]


def _reading_score(region: DisplayRegion, detections: list[DetectionResult]) -> float:
    """Prefer complete, confident rows of digits over isolated guesses."""
    if not detections:
        return region.locator_score * 0.1
    confidences = [detection["confidence"] for detection in detections]
    heights = [detection["bbox"][3] - detection["bbox"][1] for detection in detections]
    centers_y = [
        (detection["bbox"][1] + detection["bbox"][3]) / 2 for detection in detections
    ]
    median_height = float(np.median(heights))
    vertical_spread = (
        (max(centers_y) - min(centers_y)) / median_height if median_height > 0 else 1.0
    )
    alignment = max(0.0, 1.0 - vertical_spread)
    return (
        len(detections) * 0.8
        + sum(confidences)
        + region.locator_score * 0.2
        + alignment * 0.25
    )


def analyze_image(
    image_path: str | Path,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    *,
    confidence: float = 0.25,
    image_size: int = 640,
    grayscale: bool = False,
    display_colors: Sequence[str] = ("red",),
    max_roi_candidates: int = 5,
) -> RecognitionOutput:
    """Locate a display, run digit inference on its crop, and map boxes back."""
    source = Path(image_path)
    weights = Path(model_path)
    if not source.is_file():
        raise FileNotFoundError(f"Image not found: {source}")
    if not weights.is_file():
        raise FileNotFoundError(f"Model weights not found: {weights}")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1.")
    if image_size < 1:
        raise ValueError("image_size must be at least 1.")

    original = cv2.imread(str(source))
    if original is None:
        raise ValueError(f"Could not read image: {source}")
    inference_image = original
    if grayscale:
        gray = cv2.cvtColor(original, cv2.COLOR_BGR2GRAY)
        inference_image = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    model = YOLO(str(weights))
    model_version = _validate_model(model)
    candidates = locate_display_candidates(
        original,
        colors=display_colors,
        max_candidates=max_roi_candidates,
    )
    if not candidates:
        return RecognitionOutput(
            annotated_image=inference_image.copy(),
            detections=[],
            roi=None,
            display_color=None,
            candidate_count=0,
            raw_digits=None,
            ignored_none_count=0,
            failure_reason="no_display_candidate",
            model_version=model_version,
        )

    evaluated: list[tuple[DisplayRegion, float, str, list[DetectionResult], int]] = []
    proposal_confidence = min(confidence, 0.05)
    for region in candidates:
        for scale in (0.6, 0.7, 0.8, 1.0):
            crop_region = _scaled_region(region, scale, inference_image.shape)
            if crop_region.width < 20 or crop_region.height < 10:
                continue
            crop = inference_image[
                crop_region.y1 : crop_region.y2,
                crop_region.x1 : crop_region.x2,
            ]
            variants = [("original", inference_image)]
            if scale == 0.7:
                enhanced = cv2.detailEnhance(crop, sigma_s=10, sigma_r=0.15)
                variants.append(("sharpened", enhanced))
            for preprocessing, variant_image in variants:
                proposal_detections, ignored_none_count = _predict_region(
                    model,
                    inference_image,
                    crop_region,
                    confidence=proposal_confidence,
                    image_size=image_size,
                    crop_override=(
                        variant_image if preprocessing == "sharpened" else None
                    ),
                    model_version=model_version,
                )
                evaluated.append(
                    (
                        crop_region,
                        scale,
                        preprocessing,
                        _consistent_digit_row(_deduplicate_digits(proposal_detections)),
                        ignored_none_count,
                    )
                )

    (
        selected_region,
        crop_scale,
        crop_preprocessing,
        proposal_detections,
        ignored_none_count,
    ) = max(
        evaluated,
        key=lambda item: _reading_score(
            item[0],
            [
                detection
                for detection in item[3]
                if detection["confidence"] >= confidence
            ],
        ),
    )
    detections = [
        detection
        for detection in proposal_detections
        if detection["confidence"] >= confidence
    ]
    annotated = draw_display_region(
        inference_image,
        selected_region.bbox,
        color_name=selected_region.color,
        digits_found=bool(detections),
    )
    if detections:
        annotated = draw_detections(
            annotated,
            [detection["bbox"] for detection in detections],
            [detection["class_id"] for detection in detections],
            [detection["confidence"] for detection in detections],
            labels=[detection["class_name"] for detection in detections],
        )
    raw_digits = "".join(detection["class_name"] for detection in detections)
    return RecognitionOutput(
        annotated_image=annotated,
        detections=detections,
        roi=selected_region.bbox,
        display_color=selected_region.color,
        candidate_count=len(candidates),
        raw_digits=raw_digits
        if any(symbol.isdigit() for symbol in raw_digits)
        else None,
        ignored_none_count=ignored_none_count,
        failure_reason=None
        if any(item["class_name"].isdigit() for item in detections)
        else "no_digits_detected",
        crop_scale=crop_scale,
        crop_preprocessing=crop_preprocessing,
        model_version=model_version,
    )


def recognize_image_with_detections(
    image_path: str | Path,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    *,
    confidence: float = 0.25,
    image_size: int = 640,
    grayscale: bool = False,
    display_colors: Sequence[str] = ("red",),
    max_roi_candidates: int = 5,
) -> tuple[np.ndarray, list[DetectionResult]]:
    """Return an annotated image and its digit detections without saving either.

    Supports model_1 (digit classes 0-9, optional none) and model_2
    (classes '-', '.', then digits 0-9). Legacy ``none`` predictions are ignored.
    """
    output = analyze_image(
        image_path,
        model_path,
        confidence=confidence,
        image_size=image_size,
        grayscale=grayscale,
        display_colors=display_colors,
        max_roi_candidates=max_roi_candidates,
    )
    return output.annotated_image, output.detections


def recognize_image(
    image_path: str | Path,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    *,
    confidence: float = 0.25,
    image_size: int = 640,
    grayscale: bool = False,
    display_colors: Sequence[str] = ("red",),
    max_roi_candidates: int = 5,
) -> np.ndarray:
    """Detect digits and return an annotated OpenCV BGR image."""
    annotated, _ = recognize_image_with_detections(
        image_path,
        model_path,
        confidence=confidence,
        image_size=image_size,
        grayscale=grayscale,
        display_colors=display_colors,
        max_roi_candidates=max_roi_candidates,
    )
    return annotated


# A descriptive alias for callers that prefer a detection-oriented name.
detect_image = recognize_image
