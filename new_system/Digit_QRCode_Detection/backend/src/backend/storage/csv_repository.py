"""Thread-safe, atomic local measurement storage in one CSV file."""

from __future__ import annotations

import csv
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.storage.sqlite_repository import utc_text


FIELDS = ("id", "qr_data", "raw_digits", "numeric_value", "confidence", "captured_at", "created_at")


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class CsvRepository:
    """Provide the measurement repository interface using an atomic CSV file."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._healthy = False

    @property
    def healthy(self) -> bool:
        with self._lock:
            return self._healthy

    def open(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self._write_rows([])
            else:
                self._read_rows()
            self._healthy = True

    def close(self) -> None:
        with self._lock:
            self._healthy = False

    def list_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            self._require_open()
            try:
                return list(reversed(self._read_rows()))[:limit]
            except (OSError, csv.Error, ValueError):
                self._healthy = False
                raise

    def insert_if_new(self, payload: dict[str, Any], captured_at: datetime, duplicate_window_seconds: int) -> dict[str, Any] | None:
        created_at = datetime.now(timezone.utc)
        cutoff = created_at - timedelta(seconds=duplicate_window_seconds)
        with self._lock:
            self._require_open()
            try:
                rows = self._read_rows()
                duplicate = any(
                    row["qr_data"] == payload["qr_data"]
                    and row["numeric_value"] == payload["numeric_value"]
                    and _parse_utc(row["created_at"]) >= cutoff
                    for row in rows
                )
                if duplicate:
                    return None
                record = {
                    "id": max((int(row["id"]) for row in rows), default=0) + 1,
                    "qr_data": payload["qr_data"],
                    "raw_digits": payload["raw_digits"],
                    "numeric_value": float(payload["numeric_value"]),
                    "confidence": float(payload["confidence"]),
                    "captured_at": utc_text(captured_at),
                    "created_at": utc_text(created_at),
                }
                rows.append(record)
                self._write_rows(rows)
                return record
            except (OSError, csv.Error, ValueError):
                self._healthy = False
                raise

    def _read_rows(self) -> list[dict[str, Any]]:
        with self.path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"Invalid CSV columns in {self.path}")
            rows: list[dict[str, Any]] = []
            for row in reader:
                rows.append({
                    "id": int(row["id"]),
                    "qr_data": row["qr_data"],
                    "raw_digits": row["raw_digits"],
                    "numeric_value": float(row["numeric_value"]),
                    "confidence": float(row["confidence"]),
                    "captured_at": row["captured_at"],
                    "created_at": row["created_at"],
                })
            return rows

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=self.path.parent, delete=False) as file:
                temporary = file.name
                writer = csv.DictWriter(file, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None and Path(temporary).exists():
                Path(temporary).unlink()

    def _require_open(self) -> None:
        if not self._healthy:
            raise RuntimeError("CSV repository is not open")
