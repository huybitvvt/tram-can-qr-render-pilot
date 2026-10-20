"""Camera source parsing and OpenCV backend selection."""

import cv2


def parse_source(value: str) -> int | str:
    value = value.strip()
    if not value:
        raise ValueError("CAMERA_SOURCE must not be empty")
    return int(value) if value.isdecimal() else value


def backend_id(name: str | None) -> int | None:
    """Map an optional .env backend name to an OpenCV API preference."""
    if not name or name.strip().upper() in {"AUTO", "NONE"}:
        return None
    candidate = name.strip().upper()
    if not candidate.startswith("CAP_"):
        candidate = "CAP_" + candidate
    result = getattr(cv2, candidate, None)
    if not isinstance(result, int):
        raise ValueError(f"Unsupported CAMERA_BACKEND: {name}")
    return result
