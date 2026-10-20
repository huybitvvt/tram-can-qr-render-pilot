"""Crop-first QR decoding for camera frames using only OpenCV."""

from __future__ import annotations

from collections.abc import Iterator

import cv2
import numpy as np

from backend.cv.types import Box, QrResult


def _bounds(points: np.ndarray) -> Box:
    vertices = points.reshape(-1, 2)
    x1, y1 = vertices.min(axis=0)
    x2, y2 = vertices.max(axis=0)
    return Box(float(x1), float(y1), float(x2 - x1), float(y2 - y1))


class QrDecoder:
    """Track a recent QR position, then reacquire with progressively enhanced crops."""

    # Same order as the tested model_training scanner.
    CROP_VARIANTS = (
        (0.10, 1, "color"),
        (0.25, 1, "color"),
        (0.40, 2, "color"),
        (0.25, 2, "gray"),
        (0.40, 2, "clahe"),
        (1.00, 2, "gray"),
        (0.10, 3, "gray"),
    )

    def __init__(self, *, preview_max_side: int = 800, crop_padding: float = 0.40) -> None:
        if preview_max_side < 1:
            raise ValueError("preview_max_side must be positive")
        if crop_padding < 0:
            raise ValueError("crop_padding must be non-negative")
        self._detector = cv2.QRCodeDetector()
        self._clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self.preview_max_side = preview_max_side
        self.crop_padding = crop_padding
        self._last_box: Box | None = None
        self.last_stage = "none"

    @staticmethod
    def _crop_region(box: Box, image: np.ndarray, padding: float, *, min_margin: int = 4) -> tuple[int, int, int, int]:
        height, width = image.shape[:2]
        margin = max(min_margin, round(max(box.width, box.height) * padding))
        return (
            max(0, int(np.floor(box.x)) - margin),
            max(0, int(np.floor(box.y)) - margin),
            min(width, int(np.ceil(box.x + box.width)) + margin),
            min(height, int(np.ceil(box.y + box.height)) + margin),
        )

    @staticmethod
    def _result(data: str, points: np.ndarray | None, x: int = 0, y: int = 0, scale: int = 1) -> QrResult | None:
        data = data.strip()
        if not data or points is None:
            return None
        mapped = points.reshape(-1, 2).copy()
        mapped[:, 0] = mapped[:, 0] / scale + x
        mapped[:, 1] = mapped[:, 1] / scale + y
        return QrResult(data, _bounds(mapped))

    def _decode_cached(self, image: np.ndarray, box: Box) -> QrResult | None:
        x1, y1, x2, y2 = self._crop_region(box, image, self.crop_padding, min_margin=12)
        if x2 <= x1 or y2 <= y1:
            return None
        data, points, _ = self._detector.detectAndDecode(image[y1:y2, x1:x2])
        return self._result(data, points, x1, y1)

    def _candidates(self, image: np.ndarray) -> Iterator[Box]:
        found, points = self._detector.detect(image)
        if found and points is not None:
            yield _bounds(points)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        found, points = self._detector.detect(self._clahe.apply(gray))
        if found and points is not None:
            yield _bounds(points)

        height, width = gray.shape[:2]
        scale = min(0.5, self.preview_max_side / max(width, height))
        preview_width = max(1, int(width * scale))
        preview_height = max(1, int(height * scale))
        preview = cv2.resize(gray, (preview_width, preview_height), interpolation=cv2.INTER_AREA)
        found, points = self._detector.detect(preview)
        if found and points is not None:
            mapped = points.reshape(-1, 2).copy()
            mapped[:, 0] *= width / preview_width
            mapped[:, 1] *= height / preview_height
            yield _bounds(mapped)

    def _scan_candidate(self, image: np.ndarray, box: Box) -> QrResult | None:
        for padding, scale, preprocessing in self.CROP_VARIANTS:
            x1, y1, x2, y2 = self._crop_region(box, image, padding)
            if x2 - x1 < 12 or y2 - y1 < 12:
                continue
            crop = image[y1:y2, x1:x2]
            if preprocessing != "color":
                crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
                if preprocessing == "clahe":
                    crop = self._clahe.apply(crop)
            sample = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale != 1 else crop
            data, points, _ = self._detector.detectAndDecode(sample)
            result = self._result(data, points, x1, y1, scale)
            if result is not None:
                return result
        return None

    def _scan_tiles(self, image: np.ndarray) -> QrResult | None:
        """Decode small QRs in local tiles when full-frame localization is distracted."""
        height, width = image.shape[:2]
        tile_size = max(240, min(400, round(max(width, height) * 0.20)))
        step = max(1, round(tile_size * 0.75))
        for y1 in range(0, max(1, height - 100), step):
            for x1 in range(0, max(1, width - 100), step):
                crop = image[y1:min(height, y1 + tile_size), x1:min(width, x1 + tile_size)]
                if min(crop.shape[:2]) < 100:
                    continue
                sample = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                try:
                    data, points, _ = self._detector.detectAndDecode(sample)
                except cv2.error:
                    # OpenCV can reject a degenerate contour in a cluttered tile.
                    continue
                result = self._result(data, points, x1, y1, 2)
                if result is not None:
                    return result
        return None

    def decode(self, image: np.ndarray) -> QrResult | None:
        """Return a decoded QR and full-frame box, never data from an older frame."""
        if not isinstance(image, np.ndarray) or image.ndim not in (2, 3) or image.size == 0:
            raise ValueError("image must be a grayscale or BGR OpenCV image")
        self.last_stage = "none"
        had_cached_box = self._last_box is not None
        if self._last_box is not None:
            result = self._decode_cached(image, self._last_box)
            if result is not None:
                self._last_box = result.box
                self.last_stage = "cached_crop"
                return result
            self._last_box = None

        seen: list[Box] = []
        for candidate in self._candidates(image):
            center = (candidate.x + candidate.width / 2, candidate.y + candidate.height / 2)
            if any(abs(center[0] - (other.x + other.width / 2)) < 12 and abs(center[1] - (other.y + other.height / 2)) < 12 for other in seen):
                continue
            seen.append(candidate)
            result = self._scan_candidate(image, candidate)
            if result is not None:
                self._last_box = result.box
                self.last_stage = "localized_crop"
                return result

        result = self._scan_tiles(image)
        if result is not None:
            self._last_box = result.box
            self.last_stage = "tiled_crop"
            return result

        # Reacquire a moved QR even if the locator missed after a cached hit.
        if had_cached_box or seen:
            data, points, _ = self._detector.detectAndDecode(image)
            result = self._result(data, points)
            if result is not None:
                self._last_box = result.box
                self.last_stage = "full_frame"
                return result
        return None
