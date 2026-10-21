import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from roll_qr_scale import test_ui
from backend.cv.types import Box, Digit
from backend.cv.display_locator import DisplayRegion
from roll_qr_scale.digit_postprocess import (
    remove_unlit_trailing_digit,
    resolve_weak_crop_disagreement,
)
from roll_qr_scale.storage import MeasurementStore


def test_red_led_postprocess_removes_only_unsupported_weak_trailing_box():
    frame = np.zeros((100, 150, 3), dtype=np.uint8)
    digits = []
    for index, value in enumerate((6, 3, 0)):
        x = 10 + index * 25
        frame[20:60, x : x + 20] = (0, 0, 255)
        digits.append(Digit(value, 0.8, Box(x, 20, 20, 40), value))
    digits.append(Digit(0, 0.4, Box(85, 18, 30, 44), 0))

    result = remove_unlit_trailing_digit(frame, digits, display_colors=("red",))

    assert [item.value for item in result] == [6, 3, 0]


def test_red_led_postprocess_keeps_illuminated_trailing_zero():
    frame = np.zeros((100, 150, 3), dtype=np.uint8)
    digits = []
    for index, value in enumerate((0, 1, 5, 0)):
        x = 10 + index * 25
        frame[20:60, x : x + 20] = (0, 0, 255)
        digits.append(Digit(value, 0.8, Box(x, 20, 20, 40), value))

    result = remove_unlit_trailing_digit(frame, digits, display_colors=("red",))

    assert [item.value for item in result] == [0, 1, 5, 0]


def test_weak_digit_row_uses_consensus_from_alternate_crop_sizes():
    frame = np.zeros((160, 200, 3), dtype=np.uint8)
    run = SimpleNamespace(
        display=DisplayRegion(40, 30, 160, 120, "red", 0.9),
        crop_scale=0.6,
        digits=[
            Digit(6, 0.4, Box(70, 60, 20, 40), 6),
            Digit(9, 0.9, Box(95, 60, 20, 40), 9),
            Digit(9, 0.8, Box(120, 60, 20, 40), 9),
        ],
    )

    class Detector:
        confidence = 0.2
        display_colors = ("red",)

        def _predict_crop(self, image, region, preprocessing):
            return [
                Digit(6, 0.8, Box(70, 60, 20, 40), 6),
                Digit(9, 0.8, Box(95, 60, 20, 40), 9),
                Digit(8, 0.8, Box(120, 60, 20, 40), 8),
            ], 0

    resolve_weak_crop_disagreement(frame, run, Detector())

    assert [item.value for item in run.digits] == [6, 9, 8]


def test_local_model_matches_supplied_checkpoint():
    info = json.loads(Path("model/MODEL-INFO.json").read_text())
    model = Path("model/best.pt")
    assert model.stat().st_size == info["bytes"]
    assert hashlib.sha256(model.read_bytes()).hexdigest() == info["sha256"]


def test_local_detector_prefers_gross_above_aligned_lower_rows():
    from backend.cv.digit_detector import top_display_rows
    from backend.cv.display_locator import DisplayRegion

    gross = DisplayRegion(480, 680, 685, 910, "red", 0.5)
    lower = DisplayRegion(445, 800, 685, 1035, "red", 0.9)
    bottom = DisplayRegion(430, 925, 665, 1130, "red", 0.8)
    unrelated = DisplayRegion(50, 100, 100, 130, "red", 0.6)
    assert top_display_rows([lower, bottom, unrelated, gross]) == [unrelated, gross]


def test_local_yolo_reads_operator_verified_1304_and_qr(tmp_path):
    metadata = json.loads(Path("data/factory_scale_13_04_reference.json").read_text(encoding="utf-8"))
    frame = cv2.imread(str(Path("data") / metadata["image"]))
    detector = test_ui.LocalDigitDetector(Path("model/best.pt"), 0.2, prefer_top_row=True)
    store = MeasurementStore(tmp_path / "check.db", tmp_path / "captures")
    service = test_ui.StationUIService(store, None, None, None, weight_engine="local-yolo",
        digit_detector=detector, local_qr_decoder=test_ui.LocalQrDecoder(), digit_inference_confidence=0.35)
    try:
        result = service._analyze_local_frame(frame, "kg", "", "", None, None)
        assert detector.model_version == "model_2"
        assert result["weight_found"] is True
        assert result["weight"] == pytest.approx(metadata["expected_weight"])
        assert result["qr_code"] == metadata["expected_qr_code"]
        assert result["gemini_used"] is False
        assert result["requires_human_review"] is False
    finally:
        service.close()
        store.close()
