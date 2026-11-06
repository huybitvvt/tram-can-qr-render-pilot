from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from roll_qr_scale.windows_app import backup_before_gemini_recovery, build_gemini_argv

from roll_qr_scale.windows_app import (
    _read_runtime_config,
    build_runtime_argv,
    load_runtime_config,
    prepare_paddleocr_model,
)


@pytest.mark.parametrize("old_engine", ["gemini", "local-yolo", "local"])
def test_gemini_recovery_keeps_customer_config_and_overrides_only_runtime_engine(tmp_path, monkeypatch, old_engine):
    from roll_qr_scale.test_ui import build_parser
    monkeypatch.setattr(os, "environ", os.environ.copy())
    config = tmp_path / "config.env"
    original = (f"ROLL_SCALE_WEIGHT_ENGINE={old_engine}\n"
                "ROLL_SCALE_GEMINI_API_KEY=old-test-key\n"
                "ROLL_SCALE_GATEWAY_ID=gateway-02\n"
                "ROLL_SCALE_STATION_IDS=station-02\n"
                "ROLL_SCALE_CAMERA_IDS=camera-02\n").encode()
    config.write_bytes(original)
    for name in _read_runtime_config(config):
        monkeypatch.delenv(name, raising=False)
    load_runtime_config(tmp_path)
    args = build_parser().parse_args(build_gemini_argv(tmp_path, tmp_path / "assets"))
    assert args.weight_engine == "gemini"
    assert args.station_ids == ["station-02"] and args.camera_ids == ["camera-02"]
    assert args.db == str(tmp_path / "data" / "measurements.db")
    assert os.environ["ROLL_SCALE_GEMINI_API_KEY"] == "old-test-key"
    assert config.read_bytes() == original


def test_gemini_recovery_backs_up_current_wal_without_restoring_old_local_backup(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    config = tmp_path / "config.env"
    config.write_bytes(b"ROLL_SCALE_WEIGHT_ENGINE=gemini\r\nROLL_SCALE_GEMINI_API_KEY=old-test-key\r\n")
    captures = data / "captures"
    captures.mkdir()
    photo = captures / "rc79-photo.jpg"
    photo.write_bytes(b"existing customer photo")
    # A previous migration backup must never replace rows created afterwards.
    backups = tmp_path / "backups"
    backups.mkdir()
    (backups / "local-rc75.json").write_text('{"directory":"old-backup-not-to-restore"}')
    original_config, original_photo = config.read_bytes(), photo.read_bytes()
    with sqlite3.connect(data / "measurements.db") as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("CREATE TABLE recovery_test (id INTEGER, weight REAL)")
        connection.execute("INSERT INTO recovery_test VALUES (79, 7.09)")
        connection.commit()
        backup = backup_before_gemini_recovery(tmp_path, config)
        with sqlite3.connect(backup / "measurements.db") as snapshot:
            assert snapshot.execute("SELECT * FROM recovery_test").fetchall() == [(79, 7.09)]
            assert snapshot.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT * FROM recovery_test").fetchall() == [(79, 7.09)]
        assert backup_before_gemini_recovery(tmp_path, config) == backup
    assert (backup / "config.env").read_bytes() == original_config
    assert config.read_bytes() == original_config and photo.read_bytes() == original_photo


def test_gemini_recovery_does_not_mark_a_corrupt_database_backed_up(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "measurements.db").write_bytes(b"invalid sqlite")
    with pytest.raises(sqlite3.DatabaseError):
        backup_before_gemini_recovery(tmp_path, None)
    assert not (tmp_path / "backups" / "gemini-rc80.json").exists()


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


def test_runtime_config_accepts_supported_warehouse_aliases(tmp_path, monkeypatch) -> None:
    from roll_qr_scale.warehouse import kho_configured, kho_db_label, kho_supabase_url

    config = tmp_path / "config.env"
    config.write_text(
        'SUPABASE_KHO_DB_LABEL="kho"\n'
        "SUPABASE_KHO_URL=https://warehouse.example\n"
        "SUPABASE_KHO_KEY=warehouse-anon-key\n", encoding="utf-8",
    )
    for name in ("ROLL_SCALE_KHO_SUPABASE_URL", "SUPABASE_KHO_URL", "NEXT_PUBLIC_SUPABASE_KHO_URL",
                 "ROLL_SCALE_KHO_SUPABASE_SERVICE_KEY", "SUPABASE_KHO_SERVICE_KEY", "SUPABASE_KHO_KEY",
                 "ROLL_SCALE_KHO_DB_LABEL", "SUPABASE_KHO_DB_LABEL"):
        monkeypatch.delenv(name, raising=False)
    for name in _read_runtime_config(config):
        monkeypatch.delenv(name, raising=False)
    assert load_runtime_config(tmp_path) == config
    assert kho_configured()
    assert kho_supabase_url() == "https://warehouse.example"
    assert kho_db_label() == "kho"
    config.write_text("SUPABASE_KHO_UNKNOWN=value\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _read_runtime_config(config)


@pytest.mark.parametrize(
    "content",
    [
        (
            b"# legacy Windows comment \x9e\r\n"
            b"ROLL_SCALE_STATION_COUNT=1\r\n"
            b"ROLL_SCALE_GATEWAY_ID=gateway-02\r\n"
        ),
        (
            "# Cấu hình máy trạm\r\n"
            "ROLL_SCALE_STATION_COUNT=1\r\n"
            "ROLL_SCALE_GATEWAY_ID=gateway-02\r\n"
        ).encode("utf-16"),
    ],
)
def test_runtime_config_accepts_legacy_windows_encodings(
    tmp_path: Path, content: bytes
) -> None:
    config = tmp_path / "config.env"
    config.write_bytes(content)

    assert _read_runtime_config(config) == {
        "ROLL_SCALE_STATION_COUNT": "1",
        "ROLL_SCALE_GATEWAY_ID": "gateway-02",
    }


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


@pytest.mark.parametrize("station_number", range(1, 11))
def test_ten_workstations_keep_one_station_each_and_preserve_explicit_identity(tmp_path, monkeypatch, station_number):
    from roll_qr_scale.test_ui import StationUIService, build_parser
    from roll_qr_scale.storage import MeasurementStore
    from roll_qr_scale.windows_app import build_rapidocr_argv

    for key in list(os.environ):
        if key.startswith('ROLL_SCALE_'):
            monkeypatch.delenv(key)
    suffix = f'{station_number:02d}'
    monkeypatch.setenv('ROLL_SCALE_STATION_COUNT', '1')
    monkeypatch.setenv('ROLL_SCALE_GATEWAY_ID', f'gateway-{suffix}')
    monkeypatch.setenv('ROLL_SCALE_STATION_IDS', f'station-{suffix}')
    monkeypatch.setenv('ROLL_SCALE_CAMERA_IDS', f'camera-{suffix}')
    args = build_parser().parse_args(build_rapidocr_argv(tmp_path, tmp_path/'assets'))
    store = MeasurementStore(args.db, args.captures)
    service = StationUIService(store, None, None, None, weight_engine=args.weight_engine,
        station_count=args.station_count, station_ids=args.station_ids,
        camera_ids=args.camera_ids, gateway_id=args.gateway_id, auto_sync=False)
    try:
        assert service.station_count == 1
        assert service.gateway_id == f'gateway-{suffix}'
        source = service.validate_station_source(f'station-{suffix}', f'camera-{suffix}')
        assert source['station_id'] == f'station-{suffix}'
        assert source['camera_id'] == f'camera-{suffix}'
    finally:
        service.close()
        store.close()


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
