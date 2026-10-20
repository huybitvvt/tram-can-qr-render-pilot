"""Locate, crop, and decode QR codes with OpenCV; no trained model required."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import cv2
import numpy as np


@dataclass(frozen=True)
class QrScanResult:
    data: str | None
    bbox: tuple[float, float, float, float] | None
    crop: tuple[int, int, int, int] | None
    localization: str | None
    preprocessing: str | None
    decode_attempts: int
    elapsed_ms: float


def _bounds(points: np.ndarray) -> tuple[float, float, float, float]:
    vertices = points.reshape(-1, 2)
    x1, y1 = vertices.min(axis=0)
    x2, y2 = vertices.max(axis=0)
    return float(x1), float(y1), float(x2), float(y2)


def _crop_region(
    bbox: tuple[float, float, float, float],
    image_shape: tuple[int, ...],
    padding_ratio: float,
) -> tuple[int, int, int, int]:
    height, width = image_shape[:2]
    x1, y1, x2, y2 = bbox
    margin = max(4, round(max(x2 - x1, y2 - y1) * padding_ratio))
    return (
        max(0, int(np.floor(x1)) - margin),
        max(0, int(np.floor(y1)) - margin),
        min(width, int(np.ceil(x2)) + margin),
        min(height, int(np.ceil(y2)) + margin),
    )


class QrScanner:
    """Try cheap QR crops first, then enhanced localization and full-frame fallback."""

    # Tested against ssd/test_2: tight crops recover small QR codes that
    # full-frame detectAndDecode can locate but not decode.
    CROP_VARIANTS = (
        (0.10, 1, "color"),
        (0.25, 1, "color"),
        (0.40, 2, "color"),
        (0.25, 2, "gray"),
        (0.40, 2, "clahe"),
        (1.00, 2, "gray"),
        (0.10, 3, "gray"),
    )

    def __init__(self) -> None:
        self.detector = cv2.QRCodeDetector()
        self.clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def _candidates(self, image: np.ndarray):
        found, points = self.detector.detect(image)
        if found and points is not None:
            yield "original", _bounds(points)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        found, points = self.detector.detect(self.clahe.apply(gray))
        if found and points is not None:
            yield "clahe", _bounds(points)

        height, width = gray.shape[:2]
        half_width, half_height = max(1, width // 2), max(1, height // 2)
        preview = cv2.resize(gray, (half_width, half_height), interpolation=cv2.INTER_AREA)
        found, points = self.detector.detect(preview)
        if found and points is not None:
            mapped = points.reshape(-1, 2).copy()
            mapped[:, 0] *= width / half_width
            mapped[:, 1] *= height / half_height
            yield "half_gray", _bounds(mapped)

    def _scan_crop(
        self, image: np.ndarray, bbox: tuple[float, float, float, float]
    ) -> tuple[str | None, tuple[float, float, float, float] | None, tuple[int, int, int, int] | None, str | None, int]:
        attempts = 0
        for padding, scale, preprocessing in self.CROP_VARIANTS:
            x1, y1, x2, y2 = _crop_region(bbox, image.shape, padding)
            if x2 - x1 < 12 or y2 - y1 < 12:
                continue
            crop = image[y1:y2, x1:x2]
            if preprocessing != "color":
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
                if preprocessing == "clahe":
                    crop = self.clahe.apply(crop)
            sample = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else crop
            data, points, _ = self.detector.detectAndDecode(sample)
            attempts += 1
            data = data.strip()
            if data and points is not None:
                mapped = points.reshape(-1, 2).copy()
                mapped[:, 0] = mapped[:, 0] / scale + x1
                mapped[:, 1] = mapped[:, 1] / scale + y1
                return data, _bounds(mapped), (x1, y1, x2, y2), f"{preprocessing}, {scale}x, padding={padding}", attempts
        return None, None, None, None, attempts

    def scan(self, image: np.ndarray) -> QrScanResult:
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3) or image.size == 0:
            raise ValueError("image must be a grayscale or BGR OpenCV image")
        started = perf_counter()
        attempts = 0
        first_candidate: tuple[str, tuple[float, float, float, float]] | None = None
        seen: list[tuple[float, float, float, float]] = []
        for localization, bbox in self._candidates(image):
            # Enhanced previews often locate the same QR; avoid decoding it again.
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            if any(abs(center[0] - (other[0] + other[2]) / 2) < 12 and abs(center[1] - (other[1] + other[3]) / 2) < 12 for other in seen):
                continue
            seen.append(bbox)
            if first_candidate is None:
                first_candidate = (localization, bbox)
            data, decoded_box, crop, preprocessing, count = self._scan_crop(image, bbox)
            attempts += count
            if data:
                return QrScanResult(data, decoded_box, crop, localization, preprocessing, attempts, (perf_counter() - started) * 1000)

        if first_candidate is None:
            return QrScanResult(None, None, None, None, None, attempts, (perf_counter() - started) * 1000)

        # The original full-frame method can still succeed when a crop fails.
        data, points, _ = self.detector.detectAndDecode(image)
        attempts += 1
        data = data.strip()
        if data and points is not None:
            return QrScanResult(data, _bounds(points), None, "full_frame", "original", attempts, (perf_counter() - started) * 1000)
        return QrScanResult(None, first_candidate[1] if first_candidate else None, None, first_candidate[0] if first_candidate else None, None, attempts, (perf_counter() - started) * 1000)


def draw_qr_box(image: np.ndarray, result: QrScanResult) -> np.ndarray:
    """Draw the QR code's full-frame bounding box on a copy of an image."""
    annotated = image.copy()
    if result.data is None or result.bbox is None:
        return annotated
    x1, y1, x2, y2 = (int(round(value)) for value in result.bbox)
    height, width = annotated.shape[:2]
    x1, x2 = max(0, x1), min(width - 1, x2)
    y1, y2 = max(0, y1), min(height - 1, y2)
    color = (195, 235, 145)
    label = "QR code"
    cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)
    cv2.putText(annotated, label, (x1, max(18, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    return annotated
