"""Environment-backed configuration for the local capture station."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", PROJECT_ROOT)).resolve()
RUNTIME_ROOT = Path(sys.executable).resolve().parent if IS_FROZEN else PROJECT_ROOT
DEFAULT_ENV_PATH = RUNTIME_ROOT / ".env" if IS_FROZEN else BACKEND_ROOT / ".env"


def _without_backend_prefix(path: Path) -> Path:
    parts = path.parts
    return Path(*parts[1:]) if parts and parts[0].lower() == "backend" else path


def bundled_resource(relative: str | Path) -> Path:
    """Resolve an immutable file included by PyInstaller or stored in the repository."""
    relative = Path(relative)
    if not IS_FROZEN:
        return PROJECT_ROOT / relative
    return BUNDLE_ROOT / _without_backend_prefix(relative)


def runtime_file(relative: str | Path) -> Path:
    """Resolve a writable file beside the packaged executable."""
    relative = Path(relative)
    return (RUNTIME_ROOT / _without_backend_prefix(relative)) if IS_FROZEN else (PROJECT_ROOT / relative)


def frontend_dist_path() -> Path:
    return BUNDLE_ROOT / "frontend_dist" if IS_FROZEN else PROJECT_ROOT / "frontend" / "dist"


def _file_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"Invalid .env entry on line {line_number}")
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _integer(values: dict[str, str], key: str, default: int, minimum: int = 1) -> int:
    value = int(values.get(key, default))
    if value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


def _float(values: dict[str, str], key: str, default: float, minimum: float = 0) -> float:
    value = float(values.get(key, default))
    if not minimum <= value:
        raise ValueError(f"{key} must be at least {minimum}")
    return value


def _boolean(values: dict[str, str], key: str, default: bool) -> bool:
    raw = values.get(key, str(default)).strip().rstrip(";").lower()
    if raw not in {"true", "false", "1", "0", "yes", "no"}:
        raise ValueError(f"{key} must be true or false")
    return raw in {"true", "1", "yes"}


def redact_source(source: str) -> str:
    """Return a camera source safe for logging."""
    parts = urlsplit(source)
    if not parts.scheme or not parts.netloc:
        return source
    host = parts.netloc.rsplit("@", 1)[-1]
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    camera_source: str
    camera_backend: str | None
    frame_width: int
    frame_height: int
    camera_fps: int
    camera_reconnect_seconds: float
    rtsp_transport: str
    model_path: Path
    detection_confidence: float
    inference_confidence: float
    inference_fps: float
    required_stable_frames: int
    decimal_places: int
    storage_enable: bool
    storage_type: str
    database_path: Path
    csv_path: Path
    duplicate_window_seconds: int
    snapshot_max_age_seconds: float
    cors_origins: tuple[str, ...]
    jpeg_quality: int
    stream_fps: float
    display_colors: tuple[str, ...] = ("red",)
    display_max_candidates: int = 5
    display_image_size: int = 640
    detection_debug: bool = False


def load_settings(env_path: Path = DEFAULT_ENV_PATH) -> Settings:
    values = _file_values(env_path)
    values.update({key: value for key, value in os.environ.items() if key in values or key in {
        "HOST", "PORT", "CAMERA_SOURCE", "CAMERA_BACKEND", "FRAME_WIDTH", "FRAME_HEIGHT", "CAMERA_FPS",
        "CAMERA_RECONNECT_SECONDS", "RTSP_TRANSPORT", "MODEL_PATH", "DETECTION_CONFIDENCE", "INFERENCE_CONFIDENCE",
        "INFERENCE_FPS", "REQUIRED_STABLE_FRAMES", "DECIMAL_PLACES", "STORAGE_ENABLE", "STORAGE_TYPE", "DATABASE_PATH", "CSV_PATH",
        "DUPLICATE_WINDOW_SECONDS", "SNAPSHOT_MAX_AGE_SECONDS", "CORS_ORIGINS", "JPEG_QUALITY", "STREAM_FPS",
        "DISPLAY_COLORS", "DISPLAY_MAX_CANDIDATES", "DISPLAY_IMAGE_SIZE", "DETECTION_DEBUG",
    }})
    model_path = Path(values.get("MODEL_PATH", "backend/model/best.pt"))
    database_path = Path(values.get("DATABASE_PATH", "backend/data/measurements.db"))
    csv_path = Path(values.get("CSV_PATH", "backend/data/measurements.csv"))
    if not model_path.is_absolute():
        external_model = runtime_file(model_path)
        packaged_model = bundled_resource(model_path)
        model_path = external_model if IS_FROZEN and external_model.is_file() else packaged_model
    if not database_path.is_absolute():
        database_path = runtime_file(database_path)
    if not csv_path.is_absolute():
        csv_path = runtime_file(csv_path)
    storage_type = values.get("STORAGE_TYPE", "sqlite").strip().lower()
    if storage_type not in {"sqlite", "csv"}:
        raise ValueError("STORAGE_TYPE must be sqlite or csv")
    confidence = _float(values, "INFERENCE_CONFIDENCE", 0.70)
    if confidence > 1:
        raise ValueError("INFERENCE_CONFIDENCE must be at most 1")
    detection_confidence = _float(values, "DETECTION_CONFIDENCE", 0.25)
    if detection_confidence > 1:
        raise ValueError("DETECTION_CONFIDENCE must be at most 1")
    quality = _integer(values, "JPEG_QUALITY", 80)
    if quality > 100:
        raise ValueError("JPEG_QUALITY must be at most 100")
    display_colors = tuple(item.strip().lower() for item in values.get("DISPLAY_COLORS", "red").split(",") if item.strip())
    if not display_colors or any(item not in {"red", "green", "blue"} for item in display_colors):
        raise ValueError("DISPLAY_COLORS must contain red, green, or blue")
    return Settings(
        host=values.get("HOST", "127.0.0.1"),
        port=_integer(values, "PORT", 8000),
        camera_source=values.get("CAMERA_SOURCE", "0"),
        camera_backend=values.get("CAMERA_BACKEND", "").strip() or None,
        frame_width=_integer(values, "FRAME_WIDTH", 1280),
        frame_height=_integer(values, "FRAME_HEIGHT", 720),
        camera_fps=_integer(values, "CAMERA_FPS", 30),
        camera_reconnect_seconds=_float(values, "CAMERA_RECONNECT_SECONDS", 2, 0.1),
        rtsp_transport=values.get("RTSP_TRANSPORT", "tcp").lower(),
        model_path=model_path,
        detection_confidence=detection_confidence,
        inference_confidence=confidence,
        inference_fps=_float(values, "INFERENCE_FPS", 7),
        required_stable_frames=_integer(values, "REQUIRED_STABLE_FRAMES", 3),
        decimal_places=_integer(values, "DECIMAL_PLACES", 2, 0),
        storage_enable=_boolean(values, "STORAGE_ENABLE", False),
        storage_type=storage_type,
        database_path=database_path,
        csv_path=csv_path,
        duplicate_window_seconds=_integer(values, "DUPLICATE_WINDOW_SECONDS", 60, 0),
        snapshot_max_age_seconds=_float(values, "SNAPSHOT_MAX_AGE_SECONDS", 3, 0.1),
        cors_origins=tuple(item.strip() for item in values.get("CORS_ORIGINS", "http://localhost:5173").split(",") if item.strip()),
        jpeg_quality=quality,
        stream_fps=_float(values, "STREAM_FPS", 20),
        display_colors=display_colors,
        display_max_candidates=_integer(values, "DISPLAY_MAX_CANDIDATES", 5),
        display_image_size=_integer(values, "DISPLAY_IMAGE_SIZE", 640),
        detection_debug=_boolean(values, "DETECTION_DEBUG", False),
    )
