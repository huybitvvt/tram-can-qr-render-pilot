from pathlib import Path

from roll_qr_scale import windows_auto_app as auto


def test_trial_imports_station_and_cloud_settings_without_keys_or_shared_paths(tmp_path):
    legacy = tmp_path / "TramCanQR"
    legacy.mkdir()
    config = legacy / "config.env"
    content = (
        "ROLL_SCALE_GATEWAY_ID=gateway-04\nROLL_SCALE_STATION_IDS=station-04\n"
        "ROLL_SCALE_CAMERA_IDS=camera-04\nROLL_SCALE_PORT=8080\n"
        "ROLL_SCALE_GEMINI_API_KEY=private-test-key\nROLL_SCALE_DIGIT_MODEL=C:/old/model.pt\n"
        "ROLL_SCALE_DEVICE_TOKEN=test-device-token\nSUPABASE_KHO_KEY=test-warehouse-key\n"
        "ROLL_SCALE_DATA_ROOT=C:/old-data\n"
    )
    config.write_text(content, encoding="utf-8")
    root = tmp_path / "TramCanQRAuto"
    trial = auto.prepare_config(root, legacy)
    values = auto.desktop._read_runtime_config(trial)
    assert values["ROLL_SCALE_GATEWAY_ID"] == "gateway-04"
    assert values["ROLL_SCALE_STATION_IDS"] == "station-04"
    assert values["ROLL_SCALE_CAMERA_IDS"] == "camera-04"
    assert values["ROLL_SCALE_DEVICE_TOKEN"] == "test-device-token"
    assert values["SUPABASE_KHO_KEY"] == "test-warehouse-key"
    assert values["ROLL_SCALE_PORT"] == "8081"
    assert values["ROLL_SCALE_WEIGHT_ENGINE"] == "local-yolo"
    assert not any("GEMINI" in key or key in {"ROLL_SCALE_DIGIT_MODEL", "ROLL_SCALE_DATA_ROOT"} for key in values)
    assert config.read_text(encoding="utf-8") == content
    assert not (root / "data").exists()
    trial.write_text("ROLL_SCALE_PORT=8099\n", encoding="utf-8")
    auto.prepare_config(root, legacy)
    assert trial.read_text(encoding="utf-8") == "ROLL_SCALE_PORT=8099\n"


def test_trial_runtime_uses_own_data_and_bundled_model(tmp_path, monkeypatch):
    for key in auto._DEFAULT_CONFIG:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("ROLL_SCALE_DIGIT_MODEL", raising=False)
    monkeypatch.setenv("ROLL_SCALE_PORT", "8081")
    root, assets = tmp_path / "trial", tmp_path / "assets"
    model = assets / "model" / "best.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"test")
    args = auto.build_parser().parse_args(auto.build_auto_argv(root, assets))
    assert args.weight_engine == "local-yolo"
    assert args.weight_burst_frames == 1
    assert args.port == 8081
    assert Path(args.db) == root / "data" / "measurements.db"
    assert Path(args.captures) == root / "data" / "captures"
    assert Path(args.digit_model) == model
