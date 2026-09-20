from __future__ import annotations

import os
from pathlib import Path

import pytest

from roll_qr_scale.windows_app import (
    _read_runtime_config,
    build_runtime_argv,
    load_runtime_config,
    prepare_paddleocr_model,
)


def test_runtime_config_loads_only_desktop_keys_and_preserves_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.env"
    config.write_text(
        "\ufeff# customer config\n"
        "ROLL_SCALE_STATION_COUNT=2\n"
        'ROLL_SCALE_GATEWAY_ID="gateway-factory"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ROLL_SCALE_GATEWAY_ID", "gateway-process")
    monkeypatch.delenv("ROLL_SCALE_STATION_COUNT", raising=False)

    assert load_runtime_config(tmp_path) == config
    assert os.environ["ROLL_SCALE_STATION_COUNT"] == "2"
    assert os.environ["ROLL_SCALE_GATEWAY_ID"] == "gateway-process"

    config.write_text("CLOUDINARY_API_SECRET=must-not-be-here\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"chỉ chấp nhận cấu hình ROLL_SCALE_\*"):
        _read_runtime_config(config)


def test_packaged_runtime_defaults_to_one_isolated_station_and_tested_ocr_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "ROLL_SCALE_STATION_COUNT",
        "ROLL_SCALE_STATION_IDS",
        "ROLL_SCALE_STATION_ID",
        "ROLL_SCALE_CAMERA_IDS",
        "ROLL_SCALE_CAMERA_ID",
        "ROLL_SCALE_PORT",
        "ROLL_SCALE_YOLO_IMGSZ",
        "ROLL_SCALE_OCR_MIN_CONFIDENCE",
        "ROLL_SCALE_WEIGHT_ROIS",
        "ROLL_SCALE_WEIGHT_BURST_FRAMES",
    ):
        monkeypatch.delenv(name, raising=False)

    argv = build_runtime_argv(tmp_path / "runtime", tmp_path / "assets")

    assert argv[argv.index("--station-count") + 1] == "1"
    assert argv[argv.index("--yolo-imgsz") + 1] == "960"
    assert argv[argv.index("--ocr-min-confidence") + 1] == "0.6"
    assert argv[argv.index("--weight-burst-frames") + 1] == "5"
    assert argv[argv.index("--logo-image") + 1].endswith(
        "assets\\data\\viet_nhat_ipt_logo.jpg"
    )
    assert "--station-id" not in argv
    assert "--camera-id" not in argv


def test_packaged_runtime_points_paddleocr_at_bundled_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import roll_qr_scale.windows_app as windows_app

    model_dir = tmp_path / "assets" / "paddleocr" / "PP-OCRv6_medium_rec"
    model_dir.mkdir(parents=True)
    monkeypatch.setattr(windows_app, "bundle_root", lambda: tmp_path)
    monkeypatch.delenv("ROLL_SCALE_PADDLE_MODEL_DIR", raising=False)

    prepare_paddleocr_model(tmp_path / "runtime")

    assert os.environ["ROLL_SCALE_PADDLE_MODEL_DIR"] == str(model_dir)


def test_packaged_runtime_accepts_two_explicit_station_and_camera_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROLL_SCALE_STATION_COUNT", "2")
    monkeypatch.setenv("ROLL_SCALE_STATION_IDS", "scale-a,scale-b")
    monkeypatch.setenv("ROLL_SCALE_CAMERA_IDS", "cam-a,cam-b")

    argv = build_runtime_argv(tmp_path / "runtime", tmp_path / "assets")

    assert argv.count("--station-id") == 2
    assert argv.count("--camera-id") == 2
    assert [argv[index + 1] for index, item in enumerate(argv) if item == "--station-id"] == [
        "scale-a",
        "scale-b",
    ]
    assert [argv[index + 1] for index, item in enumerate(argv) if item == "--camera-id"] == [
        "cam-a",
        "cam-b",
    ]


def test_packaged_runtime_accepts_one_calibrated_weight_roi_per_station(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROLL_SCALE_STATION_COUNT", "2")
    monkeypatch.setenv(
        "ROLL_SCALE_WEIGHT_ROIS",
        "0.40,0.70,0.60,0.90;0.41,0.71,0.61,0.91",
    )
    monkeypatch.setenv("ROLL_SCALE_WEIGHT_BURST_FRAMES", "7")

    argv = build_runtime_argv(tmp_path / "runtime", tmp_path / "assets")

    assert [argv[index + 1] for index, item in enumerate(argv) if item == "--weight-roi"] == [
        "0.40,0.70,0.60,0.90",
        "0.41,0.71,0.61,0.91",
    ]
    assert argv[argv.index("--weight-burst-frames") + 1] == "7"


def test_packaged_runtime_rejects_identity_count_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROLL_SCALE_STATION_COUNT", "3")
    monkeypatch.setenv("ROLL_SCALE_STATION_IDS", "only-one")

    with pytest.raises(ValueError, match="đúng 3 giá trị"):
        build_runtime_argv(tmp_path / "runtime", tmp_path / "assets")
