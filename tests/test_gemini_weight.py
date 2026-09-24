from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from roll_qr_scale.gemini_weight import GeminiWeightReader


class FakeModels:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            parsed=self.payload,
            text="",
            usage_metadata=SimpleNamespace(
                prompt_token_count=1234,
                candidates_token_count=37,
                thoughts_token_count=19,
                total_token_count=1290,
            ),
        )


class FakeClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.models = FakeModels(payload)
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("failure", [504, 503, 502, "timeout"])
def test_gemini_retries_transient_failure_with_same_image(monkeypatch, failure) -> None:
    waits = []
    monkeypatch.setattr("roll_qr_scale.gemini_weight.time.sleep", waits.append)
    calls = []
    error = TimeoutError("deadline expired") if failure == "timeout" else RuntimeError("server error")
    if failure != "timeout":
        error.code = failure
    successful = FakeModels({
        "weight_readable": True, "weight_digits": "1.04",
        "qr_readable": False, "qr_code": None, "all_frames_agree": True,
    })

    def generate_content(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise error
        return successful.generate_content(**kwargs)

    reader = GeminiWeightReader("secret-key", timeout_seconds=10.0,
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    result = reader.read([np.zeros((480, 640, 3), dtype=np.uint8)])
    assert result.readable and result.value == pytest.approx(1.04)
    assert len(calls) == 2 and waits == [1.0]
    assert calls[1]["contents"] is calls[0]["contents"]
    assert calls[1]["config"].http_options.timeout == 30_000
    assert calls[1]["config"].http_options.retry_options.attempts == 1
    assert reader.status()["requests"] == 2
    assert reader.status()["failures"] == 0


@pytest.mark.parametrize(("code", "expected_calls"), [(504, 2), (403, 1), (429, 1)])
def test_gemini_stops_retrying_and_never_invents_weight(monkeypatch, code, expected_calls) -> None:
    monkeypatch.setattr("roll_qr_scale.gemini_weight.time.sleep", lambda _: None)
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        error = RuntimeError("request failed for secret-key")
        error.code = code
        raise error

    reader = GeminiWeightReader("secret-key",
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)))
    result = reader.read([np.zeros((480, 640, 3), dtype=np.uint8)])
    assert len(calls) == expected_calls
    assert result.value is None and not result.readable
    assert result.raw.startswith("GEMINI ERROR:")
    assert result.transient_error is (code == 504)
    assert "secret-key" not in result.raw
    assert reader.status()["requests"] == expected_calls
    assert reader.status()["failures"] == 1


def test_gemini_reader_sends_three_sampled_full_images_and_returns_qr() -> None:
    client = FakeClient({
        "weight_readable": True,
        "weight_digits": "784",
        "qr_readable": True,
        "qr_code": "ROLL-784",
        "all_frames_agree": True,
    })
    reader = GeminiWeightReader("secret-key", client=client)
    frames = [
        np.full((20, 60, 3), index, dtype=np.uint8)
        for index in range(5)
    ]

    result = reader.read(frames)

    assert result.value == pytest.approx(7.84)
    assert result.readable
    assert result.qr_code == "ROLL-784"
    assert result.qr_readable
    assert result.input_tokens == 1234
    assert result.output_tokens == 37
    assert result.thinking_tokens == 19
    assert result.total_tokens == 1290
    assert len(client.models.calls) == 1
    assert len(client.models.calls[0]["contents"]) == 4  # prompt + 3 JPEG ROIs
    assert reader.status()["successes"] == 1
    assert reader.status()["input_tokens"] == 1234
    assert reader.status()["output_tokens"] == 37
    assert reader.status()["thinking_tokens"] == 19


@pytest.mark.parametrize(
    "payload",
    (
        {
            "weight_readable": False,
            "weight_digits": None,
            "qr_readable": False,
            "qr_code": None,
            "all_frames_agree": False,
        },
        {
            "weight_readable": True,
            "weight_digits": "78",
            "qr_readable": False,
            "qr_code": None,
            "all_frames_agree": True,
        },
        {
            "weight_readable": True,
            "weight_digits": "784",
            "qr_readable": False,
            "qr_code": None,
            "all_frames_agree": False,
        },
    ),
)
def test_gemini_reader_fails_closed_on_unreadable_or_invalid_payload(payload) -> None:
    reader = GeminiWeightReader("secret-key", client=FakeClient(payload))

    result = reader.read([
        np.zeros((20, 60, 3), dtype=np.uint8) for _ in range(3)
    ])

    assert result.value is None
    assert not result.readable
    assert reader.status()["failures"] == 1


def test_gemini_reader_accepts_one_full_still_image() -> None:
    client = FakeClient({
        "weight_readable": True,
        "weight_digits": "1304",
        "qr_readable": True,
        "qr_code": "ROLL-STILL",
        "all_frames_agree": True,
    })
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.read([np.zeros((480, 640, 3), dtype=np.uint8)])

    assert result.value == pytest.approx(13.04)
    assert result.qr_code == "ROLL-STILL"
    assert len(client.models.calls[0]["contents"]) == 2  # prompt + full still image


@pytest.mark.parametrize(("display", "expected"), (("10.8", 10.8), ("13,04", 13.04)))
def test_gemini_reader_accepts_visible_decimal_precision(display, expected) -> None:
    client = FakeClient({
        "weight_readable": True,
        "weight_digits": display,
        "qr_readable": False,
        "qr_code": None,
        "all_frames_agree": True,
    })
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.read([np.zeros((480, 640, 3), dtype=np.uint8)])

    assert result.value == pytest.approx(expected)
    assert result.readable
    assert "including the decimal point" in client.models.calls[0]["contents"][0]


def test_gemini_reader_redacts_api_key_from_errors() -> None:
    class FailingModels:
        def generate_content(self, **kwargs):
            raise RuntimeError("request failed for secret-key")

    reader = GeminiWeightReader(
        "secret-key",
        client=SimpleNamespace(models=FailingModels()),
    )

    result = reader.read([
        np.zeros((20, 60, 3), dtype=np.uint8) for _ in range(3)
    ])

    assert result.value is None
    assert "secret-key" not in result.raw
    assert "[redacted]" in result.raw


def test_fast_reader_limits_image_size_and_does_not_trust_ai_qr() -> None:
    client = FakeClient({
        "weight_readable": True,
        "weight_digits": "1304",
        "qr_readable": True,
        "qr_code": "HALLUCINATED-CODE",
        "all_frames_agree": True,
    })
    reader = GeminiWeightReader(
        "secret-key",
        client=client,
        max_image_edge=640,
        jpeg_quality=80,
        media_resolution="medium",
        include_qr=False,
    )

    result = reader.read([np.zeros((1080, 1920, 3), dtype=np.uint8)])

    image_part = client.models.calls[0]["contents"][1]
    encoded = np.frombuffer(image_part.inline_data.data, dtype=np.uint8)
    decoded = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert max(decoded.shape[:2]) == 640
    assert result.value == pytest.approx(13.04)
    assert result.qr_code is None
    assert result.qr_readable is False
    assert reader.status()["media_resolution"] == "medium"
    assert reader.status()["include_qr"] is False


def test_panel_reader_sends_all_named_regions_in_one_request() -> None:
    client = FakeClient({
        "region_01": {"readable": True, "value": "21,69"},
        "region_02": {"readable": False, "value": None},
    })
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.read_panel_regions([
        ("Ext. Speed 1", np.full((30, 60, 3), (20, 20, 220), dtype=np.uint8)),
        ("TEMP 1", np.full((28, 58, 3), (20, 180, 20), dtype=np.uint8)),
    ])

    assert result["readings"] == [
        {"label": "Ext. Speed 1", "readable": True, "value": "21.69"},
        {"label": "TEMP 1", "readable": False, "value": None},
    ]
    assert len(client.models.calls) == 1
    assert len(client.models.calls[0]["contents"]) == 3
    schema = client.models.calls[0]["config"].response_schema
    assert set(schema["required"]) == {"region_01", "region_02"}
    assert "gray/unlit ghost segment" in client.models.calls[0]["contents"][0]


def test_panel_reader_packs_many_regions_into_one_image_with_minimal_thinking() -> None:
    payload = {
        f"region_{index:02d}": {"readable": True, "value": str(index)}
        for index in range(1, 13)
    }
    client = FakeClient(payload)
    reader = GeminiWeightReader(
        "secret-key",
        client=client,
        model="gemini-3.1-pro-preview",
        thinking_level="medium",
        max_image_edge=1600,
    )
    regions = [
        (
            f"Chỉ số {index:02d}",
            np.full((45, 90, 3), (20, 20, 180), dtype=np.uint8),
        )
        for index in range(1, 13)
    ]

    result = reader.read_panel_regions(regions)

    assert result["contact_sheet"] is True
    assert result["input_images"] == 1
    assert len(result["readings"]) == 12
    call = client.models.calls[0]
    assert len(call["contents"]) == 2  # prompt + one indexed contact sheet
    encoded = np.frombuffer(call["contents"][1].inline_data.data, dtype=np.uint8)
    contact_sheet = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    assert contact_sheet.shape[0] > 900
    assert contact_sheet.shape[1] > 1400
    assert max(contact_sheet.shape[:2]) <= 1600
    assert call["config"].thinking_config.thinking_level.value == "MINIMAL"
    assert "Blue header R01" in call["contents"][0]


def test_panel_reader_uses_low_as_gemini_37_minimum_thinking_level() -> None:
    client = FakeClient({
        "region_01": {"readable": True, "value": "1304"},
    })
    reader = GeminiWeightReader(
        "secret-key",
        client=client,
        model="gemini-3.7-flash",
        thinking_level="low",
    )

    reader.read_panel_regions([
        ("Cân", np.zeros((40, 80, 3), dtype=np.uint8)),
    ])

    config = client.models.calls[0]["config"]
    assert config.thinking_config.thinking_level.value == "LOW"


def test_panel_detector_returns_sorted_distinct_active_display_rows() -> None:
    client = FakeClient({
        "regions": [
            {"x1": 500, "y1": 100, "x2": 620, "y2": 160},
            {"x1": 100, "y1": 200, "x2": 200, "y2": 300},
            {"x1": 103, "y1": 202, "x2": 198, "y2": 298},
            {"x1": 50, "y1": 50, "x2": 52, "y2": 53},
        ]
    })
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.detect_panel_regions(np.zeros((600, 800, 3), dtype=np.uint8))

    assert result["method"] == "gemini-active-display-detection"
    assert result["regions"] == [
        {
            "label": "Chỉ số 01",
            "x1": 0.49,
            "y1": 0.093,
            "x2": 0.63,
            "y2": 0.167,
        },
        {
            "label": "Chỉ số 02",
            "x1": 0.092,
            "y1": 0.188,
            "x2": 0.208,
            "y2": 0.312,
        },
    ]
    assert len(client.models.calls) == 1
    assert len(client.models.calls[0]["contents"]) == 3
    assert "ORIGINAL image orientation" in client.models.calls[0]["contents"][0]
    assert "analog gauges" in client.models.calls[0]["contents"][0]
    assert client.models.calls[0]["config"].response_schema["required"] == [
        "regions"
    ]


def test_panel_reader_rejects_invalid_or_guessed_value() -> None:
    client = FakeClient({"region_01": {"readable": True, "value": "TEMP 229 C"}})
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.read_panel_regions([
        ("TEMP 1", np.zeros((30, 60, 3), dtype=np.uint8)),
    ])

    assert result["readings"] == [
        {"label": "TEMP 1", "readable": False, "value": None}
    ]


def test_panel_reader_keeps_other_results_when_one_region_is_missing() -> None:
    client = FakeClient({
        "region_01": {"readable": True, "value": "229"},
    })
    reader = GeminiWeightReader("secret-key", client=client)

    result = reader.read_panel_regions([
        ("TEMP 1", np.zeros((30, 60, 3), dtype=np.uint8)),
        ("TEMP 2", np.zeros((30, 60, 3), dtype=np.uint8)),
    ])

    assert result["readings"] == [
        {"label": "TEMP 1", "readable": True, "value": "229"},
        {"label": "TEMP 2", "readable": False, "value": None},
    ]


def test_panel_evidence_removes_gray_ghost_segments_but_keeps_led_pixels() -> None:
    image = np.full((12, 20, 3), 75, dtype=np.uint8)
    image[4:7, 3:8] = (20, 20, 220)
    image[8:10, 12:15] = (20, 180, 20)

    evidence = GeminiWeightReader._panel_evidence(image)
    isolated = evidence[:, 23:]

    assert np.all(isolated[0, 0] == 0)
    assert isolated[5, 4, 2] == 220
    assert isolated[8, 12, 1] == 180
