"""Small transactional repository backed by one local SQLite file."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class SqliteRepository:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._healthy = False

    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._healthy

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout=5000")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript((Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8"))
        except Exception:
            connection.close()
            raise
        with self._lock:
            self._connection = connection
            self._healthy = True

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self._healthy = False

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._require_connection()
            try:
                rows = connection.execute("SELECT * FROM measurements ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
            except sqlite3.Error:
                self._healthy = False
                raise
            return [dict(row) for row in rows]

    def insert_if_new(self, payload: dict[str, Any], captured_at: datetime, duplicate_window_seconds: int) -> dict[str, Any] | None:
        created_at = datetime.now(timezone.utc)
        cutoff = utc_text(created_at - timedelta(seconds=duplicate_window_seconds))
        with self._lock:
            connection = self._require_connection()
            try:
                with connection:
                    duplicate = connection.execute(
                        "SELECT id FROM measurements WHERE qr_data=? AND numeric_value=? AND created_at>=? LIMIT 1",
                        (payload["qr_data"], payload["numeric_value"], cutoff),
                    ).fetchone()
                    if duplicate is not None:
                        return None
                    cursor = connection.execute(
                        "INSERT INTO measurements(qr_data, raw_digits, numeric_value, confidence, captured_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (payload["qr_data"], payload["raw_digits"], payload["numeric_value"], payload["confidence"], utc_text(captured_at), utc_text(created_at)),
                    )
                    row = connection.execute("SELECT * FROM measurements WHERE id=?", (cursor.lastrowid,)).fetchone()
                    assert row is not None
                    return dict(row)
            except sqlite3.Error:
                self._healthy = False
                raise

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLite repository is not open")
        return self._connection
