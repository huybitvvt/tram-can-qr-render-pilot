from __future__ import annotations

import os
import logging
import re
import sys
import threading
import traceback
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from roll_qr_scale.test_ui import build_parser, create_server


APP_NAME = "TramCanQR"
CONFIG_NAME = "config.env"
PADDLE_MODEL_NAME = "PP-OCRv6_medium_rec"
_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[3]


def writable_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    root = base / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _read_runtime_config(path: Path) -> dict[str, str]:
    """Read the small desktop config format without adding a dotenv dependency."""
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"{path.name}:{line_number}: cấu hình phải có dạng TEN=GIA_TRI")
        key, value = (part.strip() for part in line.split("=", 1))
        if not _ENV_KEY.fullmatch(key):
            raise ValueError(f"{path.name}:{line_number}: tên cấu hình không hợp lệ")
        if not key.startswith("ROLL_SCALE_"):
            raise ValueError(
                f"{path.name}:{line_number}: chỉ chấp nhận cấu hình ROLL_SCALE_* trên máy trạm"
            )
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def load_runtime_config(root: Path) -> Path | None:
    """Load user-local config first, then a portable config beside the executable."""
    candidates = [root / CONFIG_NAME]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / CONFIG_NAME)
    else:
        candidates.append(bundle_root() / CONFIG_NAME)
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for key, value in _read_runtime_config(candidate).items():
            os.environ.setdefault(key, value)
        return candidate
    return None


def _configured_station_count() -> int:
    # The Windows package is deployed as one isolated gateway per workstation.
    # Multi-camera source deployments remain available through an explicit
    # ROLL_SCALE_STATION_COUNT value, but an unconfigured customer machine must
    # never silently claim the identities of three stations.
    raw_value = os.environ.get("ROLL_SCALE_STATION_COUNT", "1")
    try:
        station_count = int(raw_value)
    except ValueError as exc:
        raise ValueError("ROLL_SCALE_STATION_COUNT phải là 1, 2 hoặc 3") from exc
    if station_count not in (1, 2, 3):
        raise ValueError("ROLL_SCALE_STATION_COUNT phải là 1, 2 hoặc 3")
    return station_count


def _configured_ids(plural_name: str, singular_name: str, station_count: int) -> list[str]:
    raw_value = os.environ.get(plural_name)
    if raw_value is None and station_count == 1:
        raw_value = os.environ.get(singular_name)
    values = [item.strip() for item in (raw_value or "").split(",") if item.strip()]
    if values and len(values) != station_count:
        raise ValueError(f"{plural_name} phải có đúng {station_count} giá trị, cách nhau bằng dấu phẩy")
    return values


def _configured_weight_rois(station_count: int) -> list[str]:
    raw_value = os.environ.get("ROLL_SCALE_WEIGHT_ROIS", "").strip()
    values = [item.strip() for item in raw_value.split(";") if item.strip()]
    if values and len(values) != station_count:
        raise ValueError(
            "ROLL_SCALE_WEIGHT_ROIS phải có đúng số ROI bằng số trạm, ngăn cách bằng dấu chấm phẩy"
        )
    return values


def build_runtime_argv(root: Path, assets: Path) -> list[str]:
    station_count = _configured_station_count()
    station_ids = _configured_ids("ROLL_SCALE_STATION_IDS", "ROLL_SCALE_STATION_ID", station_count)
    camera_ids = _configured_ids("ROLL_SCALE_CAMERA_IDS", "ROLL_SCALE_CAMERA_ID", station_count)
    weight_rois = _configured_weight_rois(station_count)
    try:
        port = int(os.environ.get("ROLL_SCALE_PORT", "8080"))
        yolo_imgsz = int(os.environ.get("ROLL_SCALE_YOLO_IMGSZ", "960"))
        ocr_confidence = float(os.environ.get("ROLL_SCALE_OCR_MIN_CONFIDENCE", "0.60"))
        weight_burst_frames = int(os.environ.get("ROLL_SCALE_WEIGHT_BURST_FRAMES", "5"))
    except ValueError as exc:
        raise ValueError(
            "PORT, YOLO_IMGSZ, OCR_MIN_CONFIDENCE và WEIGHT_BURST_FRAMES phải là số hợp lệ"
        ) from exc
    if not 1 <= weight_burst_frames <= 9:
        raise ValueError("ROLL_SCALE_WEIGHT_BURST_FRAMES phải từ 1 đến 9")

    model = assets / "models" / "qr_demo_synthetic.pt"
    demo = assets / "data" / "warehouse_scale_demo.png"
    logo = assets / "data" / "viet_nhat_ipt_logo.jpg"
    argv = [
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--db",
        str(root / "data" / "measurements.db"),
        "--captures",
        str(root / "data" / "captures"),
        "--factory-samples",
        str(root / "dataset" / "factory_raw"),
        "--demo-image",
        str(demo),
        "--logo-image",
        str(logo),
        "--station-count",
        str(station_count),
        "--yolo-mode",
        "fallback",
        "--yolo-imgsz",
        str(yolo_imgsz),
        "--ocr-min-confidence",
        str(ocr_confidence),
        "--weight-burst-frames",
        str(weight_burst_frames),
    ]
    for station_id in station_ids:
        argv.extend(("--station-id", station_id))
    for camera_id in camera_ids:
        argv.extend(("--camera-id", camera_id))
    for weight_roi in weight_rois:
        argv.extend(("--weight-roi", weight_roi))
    if model.is_file():
        argv.extend(("--yolo-model", str(model)))
    return argv


def open_existing_server(port: int) -> bool:
    """Reopen the existing local UI instead of starting a second gateway."""
    url = f"http://127.0.0.1:{port}/api/status"
    try:
        with urllib.request.urlopen(url, timeout=0.8) as response:
            if response.status != 200:
                return False
            payload = response.read(512).decode("utf-8", errors="ignore")
            if '"ok"' not in payload:
                return False
    except (OSError, urllib.error.URLError, ValueError):
        return False
    webbrowser.open(f"http://127.0.0.1:{port}")
    return True


def prepare_paddleocr_model(root: Path) -> None:
    del root  # Kept in the signature for compatibility with startup tests.
    source = bundle_root() / "assets" / "paddleocr" / PADDLE_MODEL_NAME
    if source.is_dir():
        os.environ.setdefault("ROLL_SCALE_PADDLE_MODEL_DIR", str(source))


def configure_logging(root: Path) -> Path:
    log_path = root / "logs" / "app.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    return log_path


def show_startup_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Trạm cân QR - Lỗi khởi động", 0x10)
    except Exception:
        pass


def main() -> None:
    root = writable_root()
    config_path = load_runtime_config(root)
    configure_logging(root)
    logging.info("Starting TramCanQR")
    if config_path is not None:
        logging.info("Loaded runtime configuration from %s", config_path)
    prepare_paddleocr_model(root)
    assets = bundle_root()
    if getattr(sys, "frozen", False):
        assets = assets / "assets"
    argv = build_runtime_argv(root, assets)
    args = build_parser().parse_args(argv)
    if open_existing_server(args.port):
        logging.info("Existing gateway found on port %s; opened its UI", args.port)
        return
    server, service = create_server(args)
    service.start_ocr_preload()
    url = f"http://127.0.0.1:{server.server_port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if service.sync_worker is not None:
            service.sync_worker.stop()
        service.close()
        service.store.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        root = writable_root()
        log_path = configure_logging(root)
        logging.exception("TramCanQR startup failed")
        show_startup_error(
            f"Không khởi động được Trạm cân QR.\n\n{exc}\n\n"
            f"Chi tiết: {log_path}"
        )
        traceback.print_exc()
        raise
