from __future__ import annotations

import os
from pathlib import Path

from .test_ui import build_parser, run


RENDER_DISK_ROOT = Path("/var/data")


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def build_render_argv() -> list[str]:
    configured_root = os.environ.get("ROLL_SCALE_DATA_ROOT", "").strip()
    data_root = Path(
        configured_root
        or (RENDER_DISK_ROOT if RENDER_DISK_ROOT.is_dir() else "/tmp/tram-can-qr")
    )
    data_root.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", "10000"))
    station_count = int(os.environ.get("ROLL_SCALE_STATION_COUNT", "1"))
    argv = [
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--db",
        str(data_root / "measurements.db"),
        "--captures",
        str(data_root / "captures"),
        "--factory-samples",
        str(data_root / "factory_raw"),
        "--staging-dir",
        str(data_root / "captures" / ".staging"),
        "--station-count",
        str(station_count),
        "--weight-engine",
        os.environ.get("ROLL_SCALE_WEIGHT_ENGINE", "gemini"),
    ]
    for station_id in _csv_env("ROLL_SCALE_STATION_IDS"):
        argv.extend(("--station-id", station_id))
    for camera_id in _csv_env("ROLL_SCALE_CAMERA_IDS"):
        argv.extend(("--camera-id", camera_id))
    for machine_id in _csv_env("ROLL_SCALE_MACHINE_IDS"):
        argv.extend(("--machine-id", machine_id))
    return argv


def main() -> None:
    args = build_parser().parse_args(build_render_argv())
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
