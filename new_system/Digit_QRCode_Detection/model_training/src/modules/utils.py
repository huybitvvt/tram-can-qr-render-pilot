# ==========================================================================
# PURPOSE: Utilities for rendering digit detections on OpenCV images.
# ==========================================================================
# IMPORTS & MODULE LOADING
# ==========================================================================

from __future__ import annotations

from collections.abc import Iterable, Sequence

import cv2
import numpy as np

# ==========================================================================
# PARAMETERS
# ==========================================================================
PASTEL_COLORS: tuple[tuple[int, int, int], ...] = (
    (203, 192, 255),  # pink
    (191, 230, 255),  # peach
    (180, 229, 255),  # yellow
    (180, 238, 210),  # mint
    (255, 230, 190),  # blue
    (255, 210, 205),  # lavender
    (210, 245, 255),  # cyan
    (203, 218, 255),  # coral
    (230, 210, 245),  # lilac
    (190, 245, 225),  # green
)
# ==========================================================================
# CORE LOGIC & FUNCTIONS
# ==========================================================================


def class_name(class_id: int) -> str:
    """Return the legacy model_1 display name for a digit class."""
    if not 0 <= int(class_id) <= 9:
        raise ValueError(f"Digit class must be in the range 0-9, got {class_id!r}.")
    return f"{int(class_id)}"


def draw_detections(
    image: np.ndarray,
    boxes: Iterable[Sequence[float]],
    class_ids: Iterable[int],
    confidences: Iterable[float] | None = None,
    *,
    thickness: int = 1,
    labels: Iterable[str] | None = None,
) -> np.ndarray:
    """Draw pastel, thin bounding boxes and digit labels on an image.

    Args:
        image: OpenCV BGR image. The original is left unchanged.
        boxes: Bounding boxes in ``(x1, y1, x2, y2)`` format.
        class_ids: Predicted model class ids, one per box.
        confidences: Optional confidence scores, one per box.
        thickness: Bounding-box border width in pixels.
        labels: Optional resolved class labels. Required for model_2 punctuation
            and its shifted digit class IDs; omitted for legacy model_1 calls.

    Returns:
        A copy of ``image`` with the detections rendered. Nothing is saved.
    """
    if image is None or not isinstance(image, np.ndarray):
        raise ValueError("image must be a valid NumPy/OpenCV image.")
    if thickness < 1:
        raise ValueError("thickness must be at least 1.")

    box_list = list(boxes)
    class_list = list(class_ids)
    if len(box_list) != len(class_list):
        raise ValueError("boxes and class_ids must have the same length.")

    confidence_list = None if confidences is None else list(confidences)
    if confidence_list is not None and len(confidence_list) != len(box_list):
        raise ValueError("confidences and boxes must have the same length.")
    label_list = None if labels is None else list(labels)
    if label_list is not None and len(label_list) != len(box_list):
        raise ValueError("labels and boxes must have the same length.")

    annotated = image.copy()
    height, width = annotated.shape[:2]

    for index, (box, class_id) in enumerate(zip(box_list, class_list, strict=True)):
        if len(box) != 4:
            raise ValueError(f"Box at index {index} must contain four coordinates.")

        digit = int(class_id)
        #==================================================
        # model_1: use the original class ID as the digit label.
        # model_2: use the label resolved from the checkpoint class mapping.
        #==================================================
        label = class_name(digit) if label_list is None else label_list[index]
        if confidence_list is not None:
            # label = f"{label} {float(confidence_list[index]):.2f}"
            label = f"{label}"

        x1, y1, x2, y2 = (int(round(value)) for value in box)
        x1, x2 = sorted((max(0, min(x1, width - 1)), max(0, min(x2, width - 1))))
        y1, y2 = sorted((max(0, min(y1, height - 1)), max(0, min(y2, height - 1))))
        color = PASTEL_COLORS[digit % len(PASTEL_COLORS)]

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness, cv2.LINE_AA)
        (text_width, text_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1
        )
        text_y = max(text_height + baseline + 3, y1)
        cv2.rectangle(
            annotated,
            (x1, text_y - text_height - baseline - 3),
            (min(width - 1, x1 + text_width + 6), text_y + 1),
            color,
            cv2.FILLED,
        )
        cv2.putText(
            annotated,
            label,
            (x1 + 3, text_y - baseline - 1),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (60, 60, 60),
            1,
            cv2.LINE_AA,
        )

    return annotated


def draw_display_region(
    image: np.ndarray,
    bbox: Sequence[float],
    *,
    color_name: str,
    digits_found: bool,
) -> np.ndarray:
    """Draw the display crop selected for digit inference."""
    annotated = image.copy()
    height, width = annotated.shape[:2]
    x1, y1, x2, y2 = (int(round(value)) for value in bbox)
    x1 = max(0, min(x1, width - 1))
    y1 = max(0, min(y1, height - 1))
    x2 = max(0, min(x2, width - 1))
    y2 = max(0, min(y2, height - 1))
    color = (130, 210, 150) if digits_found else (120, 190, 255)
    label = f"display ({color_name})"
    if not digits_found:
        label += " - no digits"
    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    cv2.putText(
        annotated,
        label,
        (x1 + 4, max(18, y1 - 7)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )
    return annotated
