"""Validate saves against the live recognition and persistence policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import sqlite3
import csv

from backend.api.schemas import MeasurementCreate
from backend.config import Settings
from backend.recognition.snapshot import SnapshotStore
from backend.storage.sqlite_repository import SqliteRepository
from backend.storage.csv_repository import CsvRepository


@dataclass(frozen=True)
class MeasurementError(Exception):
    status_code: int
    code: str
    message: str


class MeasurementService:
    def __init__(self, settings: Settings, snapshots: SnapshotStore, repository: SqliteRepository | CsvRepository | None):
        self.settings = settings
        self.snapshots = snapshots
        self.repository = repository

    def list_recent(self, limit: int) -> list[dict[str, Any]]:
        if self.repository is None:
            if self.settings.storage_enable:
                raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.")
            return []
        if not self.repository.healthy:
            raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.")
        try:
            return self.repository.list_recent(limit)
        except (sqlite3.Error, OSError, csv.Error, ValueError) as error:
            raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.") from error

    def save(self, request: MeasurementCreate) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.repository is None:
            if self.settings.storage_enable:
                raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.")
            raise MeasurementError(503, "STORAGE_DISABLED", "Local storage is disabled in backend configuration.")
        if not self.repository.healthy:
            raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.")
        _, snapshot = self.snapshots.current()
        if snapshot is None or snapshot.payload["status"] != "READY_TO_SAVE":
            raise MeasurementError(400, "INCOMPLETE_RECOGNITION", "There is no ready recognition to save.")
        age = (datetime.now(timezone.utc) - snapshot.captured_at).total_seconds()
        if age > self.settings.snapshot_max_age_seconds:
            raise MeasurementError(400, "INCOMPLETE_RECOGNITION", "The recognition is no longer current.")
        result = snapshot.payload
        expected = (result["qr"]["data"], result["raw_digits"], result["numeric_value"])
        actual = (request.qr_data, request.raw_digits, request.numeric_value)
        if expected != actual or result["confidence"] < self.settings.inference_confidence:
            raise MeasurementError(400, "INVALID_VALUE", "The submitted measurement does not match the current recognition.")
        saved_payload = request.model_dump()
        saved_payload["confidence"] = result["confidence"]
        try:
            saved = self.repository.insert_if_new(saved_payload, snapshot.captured_at, self.settings.duplicate_window_seconds)
        except (sqlite3.Error, OSError, csv.Error, ValueError) as error:
            raise MeasurementError(503, "DATABASE_UNAVAILABLE", "Local storage is unavailable.") from error
        if saved is None:
            raise MeasurementError(409, "DUPLICATE_RECORD", "This QR and value were already saved recently.")
        event = dict(result, status="SAVED")
        return saved, event
