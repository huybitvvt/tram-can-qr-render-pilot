"""Isolated Windows launcher for the local YOLO trial channel."""
from __future__ import annotations

import json
import logging
import multiprocessing
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from roll_qr_scale import windows_app as desktop
from roll_qr_scale.windows_app import build_parser, create_server

APP_NAME = "TramCanQRAuto"
APP_VERSION = "0.2.0-ai-auto-beta1"
# Import connection/identity settings only. Never share runtime paths or AI keys.
_IMPORT_KEYS = {
    "ROLL_SCALE_STATION_COUNT", "ROLL_SCALE_GATEWAY_ID", "ROLL_SCALE_DEVICE_ID",
    "ROLL_SCALE_STATION_IDS", "ROLL_SCALE_CAMERA_IDS", "ROLL_SCALE_STATION_ID", "ROLL_SCALE_CAMERA_ID",
    "ROLL_SCALE_API_URL", "ROLL_SCALE_DEVICE_TOKEN", "ROLL_SCALE_LOOKUP_URL", "ROLL_SCALE_LOOKUP_TOKEN",
    "ROLL_SCALE_LOCAL_RETENTION_DAYS", "ROLL_SCALE_AUTO_SYNC", "ROLL_SCALE_SYNC_TIMEOUT",
    "ROLL_SCALE_WEB_USERNAME", "ROLL_SCALE_WEB_PASSWORD",
    *desktop._KHO_ENV_KEYS,
}
_IMPORT_PREFIXES = ("ROLL_SCALE_SUPABASE_", "ROLL_SCALE_KHO_", "ROLL_SCALE_PRODUCTION_ORDER_")
_DEFAULT_CONFIG = {
    "ROLL_SCALE_STATION_COUNT": "1", "ROLL_SCALE_GATEWAY_ID": "gateway-01",
    "ROLL_SCALE_STATION_IDS": "station-01", "ROLL_SCALE_CAMERA_IDS": "camera-01",
    "ROLL_SCALE_LOCAL_RETENTION_DAYS": "7", "ROLL_SCALE_PORT": "8081",
    "ROLL_SCALE_WEIGHT_ENGINE": "local-yolo", "ROLL_SCALE_WEIGHT_BURST_FRAMES": "1",
    "ROLL_SCALE_DIGIT_CONFIDENCE": "0.2", "ROLL_SCALE_DIGIT_INFERENCE_CONFIDENCE": "0.35",
    "ROLL_SCALE_DIGIT_IMAGE_SIZE": "640", "ROLL_SCALE_DECIMAL_PLACES": "2",
    "ROLL_SCALE_CAMERA_WIDTH": "1920", "ROLL_SCALE_CAMERA_HEIGHT": "1080",
    "ROLL_SCALE_CAMERA_RECOGNITION_MAX_EDGE": "960", "ROLL_SCALE_CAMERA_SOURCE": "0",
    "ROLL_SCALE_LIVE_INFERENCE_FPS": "2",
}


def prepare_config(root: Path, legacy_root: Path) -> Path:
    """Create the trial config once, without modifying the installed Gemini app."""
    path = root / "config.env"
    if path.is_file():
        return path
    values = dict(_DEFAULT_CONFIG)
    legacy = legacy_root / "config.env"
    if legacy.is_file():
        for key, value in desktop._read_runtime_config(legacy).items():
            if key in _IMPORT_KEYS or key.startswith(_IMPORT_PREFIXES):
                values[key] = value
    root.mkdir(parents=True, exist_ok=True)
    text = "# Can AI tu dong - cau hinh rieng; khong commit file nay.\n"
    text += "# Ban Gemini va du lieu cu van o thu muc TramCanQR.\n"
    text += "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(text)
    except FileExistsError:
        pass
    return path


def build_auto_argv(root: Path, assets: Path) -> list[str]:
    argv = desktop.build_runtime_argv(root, assets)
    configured = os.environ.get("ROLL_SCALE_DIGIT_MODEL", "").strip()
    model = Path(configured).expanduser() if configured else assets / "model" / "best.pt"
    if not model.is_absolute():
        model = root / model
    if not model.is_file():
        raise FileNotFoundError(f"Khong tim thay model so can: {model}")
    argv.extend(["--digit-model", str(model), "--weight-engine", "local-yolo", "--weight-burst-frames", "1"])
    return argv


def open_existing_auto_server(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=1) as response:
            status = json.load(response)
        if status.get("app_variant") != "ai-auto":
            return False
    except (OSError, urllib.error.URLError, ValueError):
        return False
    if os.environ.get("ROLL_SCALE_OPEN_BROWSER", "1") != "0":
        webbrowser.open(f"http://127.0.0.1:{port}")
    return True


def main() -> None:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    root = base / APP_NAME
    config = prepare_config(root, base / "TramCanQR")
    desktop.configure_logging(root)
    os.environ["ROLL_SCALE_CAMERA_LOG_DIR"] = str(root / "logs")
    for key, value in desktop._read_runtime_config(config).items():
        os.environ.setdefault(key, value)
    for key, value in _DEFAULT_CONFIG.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault("ROLL_SCALE_NHAP_KHO_EXPORT_DIR", str(root / "exports"))
    os.environ["ROLL_SCALE_APP_VARIANT"] = "ai-auto"
    os.environ["ROLL_SCALE_APP_VERSION"] = APP_VERSION
    os.environ["ROLL_SCALE_WEIGHT_ENGINE"] = "local-yolo"
    assets = desktop.bundle_root()
    if getattr(sys, "frozen", False):
        assets = assets / "assets"
    args = build_parser().parse_args(build_auto_argv(root, assets))
    if open_existing_auto_server(args.port):
        return
    logging.info("Starting Can AI tu dong %s on port %s", APP_VERSION, args.port)
    server, service = create_server(args)
    if os.environ.get("ROLL_SCALE_OPEN_BROWSER", "1") != "0":
        threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{server.server_port}")).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        service.close()
        service.store.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--camera-worker":
        from roll_qr_scale.camera_worker import main as camera_main
        raise SystemExit(camera_main())
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as exc:
        logging.exception("Can AI tu dong startup failed")
        if os.environ.get("ROLL_SCALE_HEADLESS", "0") != "1":
            desktop.show_startup_error(f"Khong mo duoc Can AI tu dong.\n\n{exc}\n\nLog: %LOCALAPPDATA%\\TramCanQRAuto\\logs\\app.log")
        raise
