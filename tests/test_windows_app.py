from __future__ import annotations

import os
import sqlite3
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


def test_local_upgrade_uses_existing_data_identity_and_bundled_model(tmp_path, monkeypatch):
    from roll_qr_scale.windows_app import build_local_argv
    from roll_qr_scale.test_ui import build_parser

    monkeypatch.setenv("ROLL_SCALE_WEIGHT_ENGINE", "gemini")
    monkeypatch.setenv("ROLL_SCALE_DIGIT_MODEL", "C:/missing-colleague-source/model/best.pt")
    monkeypatch.setenv("ROLL_SCALE_PORT", "8080")
    monkeypatch.setenv("ROLL_SCALE_STATION_COUNT", "1")
    monkeypatch.setenv("ROLL_SCALE_STATION_IDS", "station-04")
    monkeypatch.setenv("ROLL_SCALE_CAMERA_IDS", "camera-04")
    monkeypatch.setenv("ROLL_SCALE_GATEWAY_ID", "gateway-04")
    assets = tmp_path / "assets"
    model = assets / "model/best.pt"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fixture")
    root = tmp_path / "TramCanQR"
    args = build_parser().parse_args(build_local_argv(root, assets))
    assert args.weight_engine == "local-yolo" and args.weight_burst_frames == 1
    assert Path(args.digit_model) == model
    assert args.port == 8080 and args.gateway_id == "gateway-04"
    assert args.station_ids == ["station-04"] and args.camera_ids == ["camera-04"]
    assert Path(args.db) == root / "data/measurements.db"
    assert Path(args.captures) == root / "data/captures"


def test_upgrade_snapshot_includes_uncheckpointed_wal_and_preserves_config_photos(tmp_path):
    from roll_qr_scale.windows_app import backup_before_local_upgrade

    root = tmp_path / "TramCanQR"
    captures = root / "data/captures"
    captures.mkdir(parents=True)
    photo = captures / "old-core.jpg"
    photo.write_bytes(b"original-customer-photo")
    config = root / "config.env"
    config.write_bytes(b"ROLL_SCALE_WEIGHT_ENGINE=gemini\r\nROLL_SCALE_DEVICE_TOKEN=test-secret\r\n")
    original_config = config.read_bytes()
    database = root / "data/measurements.db"
    with sqlite3.connect(database) as source:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("PRAGMA wal_autocheckpoint=0")
        source.execute("CREATE TABLE measurements (event_id TEXT, sync_status TEXT, image_path TEXT)")
        source.executemany("INSERT INTO measurements VALUES (?, ?, ?)", [
            ("old-pending", "pending", str(photo)), ("old-failed", "failed", str(photo))])
        source.commit()
        backup = backup_before_local_upgrade(root, config)
        with sqlite3.connect(backup / "measurements.db") as snapshot:
            assert snapshot.execute("SELECT event_id, sync_status FROM measurements").fetchall() == [
                ("old-pending", "pending"), ("old-failed", "failed")]
        assert (backup / "config.env").read_bytes() == original_config
        source.execute("INSERT INTO measurements VALUES ('new-local', 'pending', ?)", (str(photo),))
        source.commit()
        assert backup_before_local_upgrade(root, config) == backup
        with sqlite3.connect(backup / "measurements.db") as snapshot:
            assert snapshot.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 2
    assert config.read_bytes() == original_config
    assert photo.read_bytes() == b"original-customer-photo"


def test_upgrade_refuses_corrupt_database_without_marking_backup_complete(tmp_path):
    from roll_qr_scale.windows_app import backup_before_local_upgrade

    (tmp_path / "data").mkdir()
    database = tmp_path / "data/measurements.db"
    database.write_bytes(b"corrupt-database")
    with pytest.raises(sqlite3.DatabaseError):
        backup_before_local_upgrade(tmp_path, None)
    assert not (tmp_path / "backups/local-rc75.json").exists()
    assert database.read_bytes() == b"corrupt-database"
