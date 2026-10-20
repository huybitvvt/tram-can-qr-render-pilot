import hashlib
import json
from pathlib import Path

import cv2
import pytest

from roll_qr_scale import test_ui
from roll_qr_scale.storage import MeasurementStore


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
