import cv2
import numpy as np
import pytest
import qrcode

from roll_qr_scale.gemini_weight import GeminiWeightSuggestion
from roll_qr_scale.storage import MeasurementStore
from roll_qr_scale.test_ui import StationUIService, decode_image
from roll_qr_scale.weight_ocr import NormalizedROI, parse_normalized_roi


@pytest.mark.parametrize("shape", [(720, 1280), (1280, 720)])
@pytest.mark.parametrize("kind", ["product", "inventory"])
@pytest.mark.parametrize("bound", [False, True])
def test_qr_uses_original_pixels_and_reports_evidence_coordinates(
    tmp_path, monkeypatch, shape, kind, bound
):
    class WeightReader:
        def read(self, frames, *, unit):
            return GeminiWeightSuggestion(6.37, unit, True, True, "test", 0.1)

        def status(self):
            return {"enabled": True}

        def close(self):
            pass

    code = "MT-MN00453-QR-CAPTURE"
    frame = np.full((*shape, 3), 180, dtype=np.uint8)
    qr = cv2.cvtColor(np.asarray(qrcode.make(code).convert("RGB")), cv2.COLOR_RGB2BGR)
    qr = cv2.resize(qr, (132, 132), interpolation=cv2.INTER_AREA)
    frame[220:352, 150:282] = qr
    store = MeasurementStore(tmp_path / "measurements.db", tmp_path / "captures")
    service = StationUIService(
        store, None, None, None, gemini_reader=WeightReader(), weight_engine="gemini"
    )
    monkeypatch.setattr(
        service, "_find_scale_roi",
        lambda _: (NormalizedROI(0.4, 0.7, 0.6, 0.8), "red-led"),
    )
    original_decode = service._decode_qr
    expected = original_decode(frame)
    assert expected["qr_code"] == code
    decoded_frames = []

    def decode_original(actual):
        # A second JPEG pass changes small modules even without resizing.
        assert np.array_equal(actual, frame)
        decoded_frames.append(actual.shape)
        return original_decode(actual)

    monkeypatch.setattr(service, "_decode_qr", decode_original)
    identity = dict(
        event_id="998abc91-9d54-4089-bf44-aab7d7e3b747",
        station_id="station-01", camera_id="camera-01",
    ) if bound else {}
    try:
        result = service.analyze(
            frame, "auto", "kg", capture_kind=kind, client_qr_code=code, **identity
        )
        assert decoded_frames == [frame.shape]
        assert result["qr_found"] is True
        assert not result["qr_conflict"]
        assert result["qr_code"] == code
        assert result["weight"] == pytest.approx(6.37)
        assert result["evidence_zoom_applied"] is True
        evidence = decode_image(result["evidence_image"])
        before = parse_normalized_roi(expected["qr_roi"]).pixels(frame)
        after = parse_normalized_roi(result["qr_roi"]).pixels(evidence)
        assert after == pytest.approx(before, abs=1)
        if bound:
            assert result["analysis_id"]
            assert result["frame_sha256"]
    finally:
        service.close()
        store.close()
