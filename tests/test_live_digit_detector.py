from types import SimpleNamespace

import numpy as np
import pytest

from roll_qr_scale import test_ui  # Registers the bundled CV import path.
from backend.cv import digit_detector
from backend.cv.digit_detector import DigitDetector
from backend.cv.display_locator import DisplayRegion
from backend.cv.types import Box, Digit


def detector_for(monkeypatch, values="042", confidence=.95):
    detector = DigitDetector.__new__(DigitDetector)
    detector.confidence, detector.model_version = .2, "model_2"
    detector.display_colors, detector.max_candidates, detector.prefer_top_row = ("red",), 5, True
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    calls = []
    def predict(image, region, preprocessing):
        assert image is frame
        calls.append((region, preprocessing))
        return [Digit(value, confidence, Box(100 + index * 20, 120, 15, 30))
                for index, value in enumerate(values)], 0
    monkeypatch.setattr(detector, "_predict_crop", predict)
    monkeypatch.setattr(digit_detector, "locate_display_candidates",
                        lambda *a, **kw: [DisplayRegion(75, 95, 260, 180, "red", .9)])
    return detector, frame, calls


def previous_run(region=None):
    return SimpleNamespace(display=region or DisplayRegion(80, 100, 250, 170, "red", .9),
                           preprocessing="original", crop_scale=.7)


def test_live_crop_reads_current_frame_once_instead_of_reusing_old_value(monkeypatch):
    detector, frame, calls = detector_for(monkeypatch)
    monkeypatch.setattr(detector, "detect_with_details", lambda _: pytest.fail("Unexpected full search"))
    run = detector.detect_live(frame, previous_run())
    assert "".join(item.value for item in run.digits) == "042"
    assert run.inference_count == 1 and len(calls) == 1


@pytest.mark.parametrize("values,confidence", [("04", .95), ("042", .3), ("0?2", .95), ("", .95)])
def test_incomplete_or_weak_crop_reacquires_display(monkeypatch, values, confidence):
    detector, frame, calls = detector_for(monkeypatch, values, confidence)
    expected = object()
    monkeypatch.setattr(detector, "detect_with_details", lambda image: expected)
    assert detector.detect_live(frame, previous_run()) is expected
    assert len(calls) == 1


@pytest.mark.parametrize("previous", [None, previous_run(DisplayRegion(600, 100, 800, 200, "red", .9))])
def test_new_camera_or_mismatched_resolution_reacquires(monkeypatch, previous):
    detector, frame, calls = detector_for(monkeypatch)
    expected = object()
    monkeypatch.setattr(detector, "detect_with_details", lambda image: expected)
    assert detector.detect_live(frame, previous) is expected
    assert calls == []


def test_moved_display_reacquires_instead_of_reading_old_crop(monkeypatch):
    detector, frame, calls = detector_for(monkeypatch)
    monkeypatch.setattr(digit_detector, "locate_display_candidates",
                        lambda *a, **kw: [DisplayRegion(300, 100, 480, 180, "red", .9)])
    expected = object()
    monkeypatch.setattr(detector, "detect_with_details", lambda _: expected)
    assert detector.detect_live(frame, previous_run()) is expected
    assert calls == []


def test_live_crop_expands_with_current_digits_instead_of_cutting_new_leading_digit(monkeypatch):
    detector, frame, calls = detector_for(monkeypatch, "1042")
    candidate = DisplayRegion(40, 90, 280, 180, "red", .9)
    monkeypatch.setattr(digit_detector, "locate_display_candidates", lambda *a, **kw: [candidate])
    monkeypatch.setattr(detector, "detect_with_details", lambda _: pytest.fail("Unexpected full search"))
    run = detector.detect_live(frame, previous_run())
    assert "".join(item.value for item in run.digits) == "1042"
    assert calls[0][0] == digit_detector.scaled_region(candidate, .7, frame.shape)
    assert calls[0][0].x1 < previous_run().display.x1


def test_live_qr_scan_does_not_exhaustively_tile_when_label_is_missing(monkeypatch):
    decoder = test_ui.LocalQrDecoder()
    monkeypatch.setattr(decoder, "_candidates", lambda _: iter(()))
    monkeypatch.setattr(decoder, "_scan_tiles", lambda _: pytest.fail("Live QR must not block digits on tile scans"))
    assert decoder.decode(np.zeros((80, 120, 3), dtype=np.uint8), exhaustive=False) is None
