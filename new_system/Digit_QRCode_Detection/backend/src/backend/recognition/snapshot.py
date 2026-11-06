"""Thread-safe latest recognition snapshot."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RecognitionSnapshot:
    frame_id: int
    captured_at: datetime
    payload: dict[str, Any]


class SnapshotStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: RecognitionSnapshot | None = None
        self._version = 0

    def publish(self, snapshot: RecognitionSnapshot) -> int:
        with self._lock:
            self._snapshot = snapshot
            self._version += 1
            return self._version

    def current(self) -> tuple[int, RecognitionSnapshot | None]:
        with self._lock:
            return self._version, self._snapshot
