"""Bound server-side YOLO results to a captured image and station identity."""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Capture:
    image_sha256: str
    station_id: str
    camera_id: str
    created: float
    run: Any
    qr: dict[str, Any]


class LiveCaptureCache:
    def __init__(self, maximum: int = 32, ttl: float = 60.0):
        self._maximum, self._ttl = maximum, ttl
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Capture] = OrderedDict()

    def put(self, image: str, station_id: str, camera_id: str, run: Any, qr: dict) -> str:
        token = secrets.token_urlsafe(24)
        capture = _Capture(hashlib.sha256(image.encode("utf-8")).hexdigest(), station_id, camera_id,
                           time.monotonic(), run, dict(qr))
        with self._lock:
            self._entries[token] = capture
            while len(self._entries) > self._maximum:
                self._entries.popitem(last=False)
        return token

    def get(self, token: str, image: str, station_id: str, camera_id: str) -> tuple | None:
        if not token or len(token) > 128:
            return None
        with self._lock:
            capture = self._entries.get(token)
            if capture is None:
                return None
            if time.monotonic() - capture.created > self._ttl:
                del self._entries[token]
                return None
        if (capture.station_id != station_id or capture.camera_id != camera_id
                or capture.image_sha256 != hashlib.sha256(image.encode("utf-8")).hexdigest()):
            return None
        return capture.run, dict(capture.qr)
