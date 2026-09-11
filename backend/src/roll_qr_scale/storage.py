from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import cv2
import numpy as np


LOCAL_BACKUP_PROVIDER = "render_persistent_disk"
DEFAULT_LOCAL_RETENTION_DAYS = 7
MAX_LOCAL_EVIDENCE_ITEMS = 200
MAX_LOCAL_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_LOCAL_EVIDENCE_IMAGE_BYTES = 6 * 1024 * 1024
LOCAL_EVIDENCE_SCAN_PAGE = 500
MAX_LOCAL_EVIDENCE_SCAN_ROWS = 20_000
LOCAL_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


@dataclass(frozen=True)
class Measurement:
    id: int
    event_id: str
    qr_code: str
    weight: float
    unit: str
    captured_at: str
    image_path: str
    weight_source: str
    sync_status: str
    qr_source: str = "camera"
    product_weight: float | None = None
    product_image_path: str = ""
    retry_count: int = 0
    sync_error: str | None = None
    remote_id: int | None = None
    remote_image_url: str | None = None
    remote_image_public_id: str | None = None
    weight_raw: str = ""
    weight_stable: bool = True
    gateway_id: str = ""
    station_id: str = ""
    camera_id: str = ""
    analysis_id: str = ""
    frame_sha256: str = ""
    payload_hash: str = ""

    def api_payload(self, device_id: str = "") -> dict[str, object]:
        payload = asdict(self)
        for local_field in (
            "id",
            "sync_status",
            "retry_count",
            "sync_error",
            "remote_id",
            "remote_image_url",
            "remote_image_public_id",
            "image_path",
            "product_image_path",
        ):
            payload.pop(local_field)

        # Identity belongs to the captured row. ``device_id`` only remains as a
        # fallback for rows produced before gateway identity was persisted.
        effective_gateway_id = self.gateway_id or device_id
        for optional_field in (
            "gateway_id",
            "station_id",
            "camera_id",
            "analysis_id",
            "frame_sha256",
            "payload_hash",
        ):
            if not payload.get(optional_field):
                payload.pop(optional_field, None)
        if effective_gateway_id:
            payload["gateway_id"] = effective_gateway_id
            # Older deployed functions only understand device_id. Sending the
            # same row-derived value keeps those deployments compatible.
            payload["device_id"] = effective_gateway_id
        return payload


@dataclass(frozen=True)
class InventoryCheck:
    """One-photo inventory weighing with its own durable cloud outbox."""

    id: int
    event_id: str
    product_code: str
    weight: float
    core_weight: float
    tare_weight: float
    unit: str
    captured_at: str
    image_path: str
    weight_source: str
    sync_status: str
    qr_source: str = "camera"
    retry_count: int = 0
    sync_error: str | None = None
    remote_id: int | None = None
    remote_image_url: str | None = None
    remote_image_public_id: str | None = None
    weight_raw: str = ""
    weight_stable: bool = True
    gateway_id: str = ""
    station_id: str = ""
    camera_id: str = ""
    analysis_id: str = ""
    frame_sha256: str = ""
    payload_hash: str = ""

    def api_payload(self, device_id: str = "") -> dict[str, object]:
        payload = asdict(self)
        for local_field in (
            "id",
            "sync_status",
            "retry_count",
            "sync_error",
            "remote_id",
            "remote_image_url",
            "remote_image_public_id",
            "image_path",
        ):
            payload.pop(local_field)
        payload["workflow"] = "inventory_check"
        # Keep qr_code for the shared ingest identity and rolls lookup while the
        # dedicated table exposes the clearer product_code column.
        payload["qr_code"] = self.product_code
        effective_gateway_id = self.gateway_id or device_id
        for optional_field in (
            "gateway_id",
            "station_id",
            "camera_id",
            "analysis_id",
            "frame_sha256",
            "payload_hash",
        ):
            if not payload.get(optional_field):
                payload.pop(optional_field, None)
        if effective_gateway_id:
            payload["gateway_id"] = effective_gateway_id
            payload["device_id"] = effective_gateway_id
        return payload


@dataclass(frozen=True)
class PhotoDraft:
    """One photo saved for later AI processing, without fabricated weights."""

    id: int
    event_id: str
    parent_event_id: str
    capture_kind: str
    capture_round: int
    qr_code: str
    captured_at: str
    image_path: str
    qr_source: str
    sync_status: str
    work_date: str = ""
    shift: str = ""
    machine: str = ""
    production_order: str = ""
    status: str = "awaiting_ai"
    retry_count: int = 0
    sync_error: str | None = None
    remote_id: int | None = None
    remote_image_url: str | None = None
    remote_image_public_id: str | None = None
    gateway_id: str = ""
    station_id: str = ""
    camera_id: str = ""
    frame_sha256: str = ""
    payload_hash: str = ""

    def api_payload(self, device_id: str = "") -> dict[str, object]:
        payload = asdict(self)
        for local_field in (
            "id",
            "sync_status",
            "retry_count",
            "sync_error",
            "remote_id",
            "remote_image_url",
            "remote_image_public_id",
            "image_path",
        ):
            payload.pop(local_field)
        payload["workflow"] = "photo_draft"
        effective_gateway_id = self.gateway_id or device_id
        for optional_field in (
            "qr_code",
            "parent_event_id",
            "capture_kind",
            "work_date",
            "shift",
            "machine",
            "production_order",
            "station_id",
            "camera_id",
            "frame_sha256",
            "payload_hash",
        ):
            if not payload.get(optional_field):
                payload.pop(optional_field, None)
        if effective_gateway_id:
            payload["gateway_id"] = effective_gateway_id
            payload["device_id"] = effective_gateway_id
        return payload


@dataclass(frozen=True)
class SaveResult:
    measurement: Measurement
    duplicate: bool

    @property
    def existing(self) -> Measurement:
        """Alias that makes the idempotent outcome explicit to callers."""

        return self.measurement

    def __iter__(self):
        # Allow the concise ``measurement, duplicate = ...`` form as well as
        # named attribute access.
        yield self.measurement
        yield self.duplicate


class EventIdConflictError(ValueError):
    """An event ID was reused for different immutable capture content."""

    def __init__(self, event_id: str):
        super().__init__(f"event_id already exists with different payload: {event_id}")
        self.event_id = event_id


class MeasurementStore:
    """Thread-safe SQLite event store and durable synchronization outbox."""

    def __init__(self, db_path: str | Path, capture_dir: str | Path):
        self.db_path = Path(db_path)
        self.capture_dir = Path(capture_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS measurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                qr_code TEXT NOT NULL,
                weight REAL NOT NULL,
                unit TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image_path TEXT NOT NULL,
                product_image_path TEXT NOT NULL DEFAULT '',
                weight_source TEXT NOT NULL,
                qr_source TEXT NOT NULL DEFAULT 'camera',
                product_weight REAL,
                sync_status TEXT NOT NULL DEFAULT 'local',
                sync_error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                last_attempt_at TEXT,
                synced_at TEXT,
                remote_id INTEGER,
                remote_image_url TEXT,
                remote_image_public_id TEXT,
                weight_raw TEXT NOT NULL DEFAULT '',
                weight_stable INTEGER NOT NULL DEFAULT 1,
                gateway_id TEXT NOT NULL DEFAULT '',
                station_id TEXT NOT NULL DEFAULT '',
                camera_id TEXT NOT NULL DEFAULT '',
                analysis_id TEXT NOT NULL DEFAULT '',
                frame_sha256 TEXT NOT NULL DEFAULT '',
                payload_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                product_code TEXT NOT NULL,
                weight REAL NOT NULL,
                core_weight REAL NOT NULL DEFAULT 0,
                tare_weight REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                image_path TEXT NOT NULL,
                weight_source TEXT NOT NULL,
                qr_source TEXT NOT NULL DEFAULT 'camera',
                sync_status TEXT NOT NULL DEFAULT 'local',
                sync_error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                last_attempt_at TEXT,
                synced_at TEXT,
                remote_id INTEGER,
                remote_image_url TEXT,
                remote_image_public_id TEXT,
                weight_raw TEXT NOT NULL DEFAULT '',
                weight_stable INTEGER NOT NULL DEFAULT 1,
                gateway_id TEXT NOT NULL DEFAULT '',
                station_id TEXT NOT NULL DEFAULT '',
                camera_id TEXT NOT NULL DEFAULT '',
                analysis_id TEXT NOT NULL DEFAULT '',
                frame_sha256 TEXT NOT NULL DEFAULT '',
                payload_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS photo_drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                parent_event_id TEXT NOT NULL DEFAULT '',
                capture_kind TEXT NOT NULL DEFAULT 'core',
                capture_round INTEGER NOT NULL DEFAULT 0,
                qr_code TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL,
                image_path TEXT NOT NULL,
                qr_source TEXT NOT NULL DEFAULT 'none',
                work_date TEXT NOT NULL DEFAULT '',
                shift TEXT NOT NULL DEFAULT '',
                machine TEXT NOT NULL DEFAULT '',
                production_order TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'awaiting_ai',
                sync_status TEXT NOT NULL DEFAULT 'local',
                sync_error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                next_retry_at TEXT,
                last_attempt_at TEXT,
                synced_at TEXT,
                remote_id INTEGER,
                remote_image_url TEXT,
                remote_image_public_id TEXT,
                gateway_id TEXT NOT NULL DEFAULT '',
                station_id TEXT NOT NULL DEFAULT '',
                camera_id TEXT NOT NULL DEFAULT '',
                frame_sha256 TEXT NOT NULL DEFAULT '',
                payload_hash TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._migrate_existing_database()
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_qr ON measurements(qr_code)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_outbox "
            "ON measurements(sync_status, next_retry_at)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_measurements_station_time "
            "ON measurements(gateway_id, station_id, camera_id, captured_at DESC)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_checks_product "
            "ON inventory_checks(product_code)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_checks_outbox "
            "ON inventory_checks(sync_status, next_retry_at)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_checks_station_time "
            "ON inventory_checks(gateway_id, station_id, camera_id, captured_at DESC)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_photo_drafts_outbox "
            "ON photo_drafts(sync_status, next_retry_at)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_photo_drafts_status_time "
            "ON photo_drafts(status, captured_at DESC)"
        )
        self.connection.commit()

    def _migrate_existing_database(self) -> None:
        existing = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(measurements)").fetchall()
        }
        additions = {
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "next_retry_at": "TEXT",
            "last_attempt_at": "TEXT",
            "synced_at": "TEXT",
            "remote_id": "INTEGER",
            "remote_image_url": "TEXT",
            "remote_image_public_id": "TEXT",
            "weight_raw": "TEXT NOT NULL DEFAULT ''",
            "weight_stable": "INTEGER NOT NULL DEFAULT 1",
            "qr_source": "TEXT NOT NULL DEFAULT 'camera'",
            "sync_error": "TEXT",
            "gateway_id": "TEXT NOT NULL DEFAULT ''",
            "station_id": "TEXT NOT NULL DEFAULT ''",
            "camera_id": "TEXT NOT NULL DEFAULT ''",
            "analysis_id": "TEXT NOT NULL DEFAULT ''",
            "frame_sha256": "TEXT NOT NULL DEFAULT ''",
            "payload_hash": "TEXT NOT NULL DEFAULT ''",
            "product_image_path": "TEXT NOT NULL DEFAULT ''",
            "product_weight": "REAL",
        }
        for column, definition in additions.items():
            if column not in existing:
                self.connection.execute(
                    f"ALTER TABLE measurements ADD COLUMN {column} {definition}"
                )

        photo_existing = {
            str(row["name"])
            for row in self.connection.execute("PRAGMA table_info(photo_drafts)").fetchall()
        }
        photo_additions = {
            "parent_event_id": "TEXT NOT NULL DEFAULT ''",
            "capture_kind": "TEXT NOT NULL DEFAULT 'core'",
            "capture_round": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in photo_additions.items():
            if column not in photo_existing:
                self.connection.execute(
                    f"ALTER TABLE photo_drafts ADD COLUMN {column} {definition}"
                )
        self.connection.execute(
            "UPDATE photo_drafts SET parent_event_id = event_id "
            "WHERE parent_event_id = ''"
        )

        # Backfill structured product weight from captures made before the
        # dedicated column existed. Do not guess rows without this exact tag.
        product_rows = self.connection.execute(
            "SELECT id, weight_raw FROM measurements WHERE product_weight IS NULL"
        ).fetchall()
        for row in product_rows:
            match = re.search(
                r"(?:^|; )PRODUCT_WEIGHT=([0-9]+(?:\.[0-9]+)?)",
                str(row["weight_raw"]),
            )
            if match:
                self.connection.execute(
                    "UPDATE measurements SET product_weight = ? WHERE id = ?",
                    (float(match.group(1)), int(row["id"])),
                )

        # Upgrade prior captures without deleting or rewriting their evidence.
        # Hashes can be reconstructed from the immutable row and on-disk JPEG.
        rows = self.connection.execute(
            "SELECT * FROM measurements WHERE frame_sha256 = '' OR payload_hash = ''"
        ).fetchall()
        for row in rows:
            frame_sha256 = str(row["frame_sha256"])
            if not frame_sha256:
                try:
                    frame_sha256 = hashlib.sha256(
                        Path(str(row["image_path"])).read_bytes()
                    ).hexdigest()
                except OSError:
                    # Missing legacy evidence must not prevent the database from
                    # opening. The empty hash continues to identify it as legacy.
                    frame_sha256 = ""
            payload_hash = str(row["payload_hash"])
            if not payload_hash:
                payload_hash = self._calculate_payload_hash(
                    qr_code=str(row["qr_code"]),
                    weight=float(row["weight"]),
                    unit=str(row["unit"]),
                    captured_at=str(row["captured_at"]),
                    weight_source=str(row["weight_source"]),
                    qr_source=str(row["qr_source"]),
                    weight_raw=str(row["weight_raw"]),
                    weight_stable=bool(row["weight_stable"]),
                    gateway_id=str(row["gateway_id"]),
                    station_id=str(row["station_id"]),
                    camera_id=str(row["camera_id"]),
                    analysis_id=str(row["analysis_id"]),
                    frame_sha256=frame_sha256,
                )
            self.connection.execute(
                "UPDATE measurements SET frame_sha256 = ?, payload_hash = ? WHERE id = ?",
                (frame_sha256, payload_hash, int(row["id"])),
            )

    @staticmethod
    def _calculate_payload_hash(
        *,
        qr_code: str,
        weight: float,
        unit: str,
        captured_at: str,
        weight_source: str,
        qr_source: str,
        weight_raw: str,
        weight_stable: bool,
        gateway_id: str,
        station_id: str,
        camera_id: str,
        analysis_id: str,
        frame_sha256: str,
    ) -> str:
        immutable_payload = {
            "analysis_id": analysis_id,
            "camera_id": camera_id,
            "captured_at": captured_at,
            "frame_sha256": frame_sha256,
            "gateway_id": gateway_id,
            "qr_code": qr_code,
            "qr_source": qr_source,
            "station_id": station_id,
            "unit": unit,
            "weight": float(weight),
            "weight_raw": weight_raw,
            "weight_source": weight_source,
            "weight_stable": bool(weight_stable),
        }
        canonical = json.dumps(
            immutable_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _calculate_inventory_payload_hash(
        *,
        product_code: str,
        weight: float,
        core_weight: float,
        tare_weight: float,
        unit: str,
        captured_at: str,
        weight_source: str,
        qr_source: str,
        weight_raw: str,
        weight_stable: bool,
        gateway_id: str,
        station_id: str,
        camera_id: str,
        analysis_id: str,
        frame_sha256: str,
    ) -> str:
        immutable_payload = {
            "analysis_id": analysis_id,
            "camera_id": camera_id,
            "captured_at": captured_at,
            "core_weight": float(core_weight),
            "frame_sha256": frame_sha256,
            "gateway_id": gateway_id,
            "product_code": product_code,
            "qr_source": qr_source,
            "station_id": station_id,
            "tare_weight": float(tare_weight),
            "unit": unit,
            "weight": float(weight),
            "weight_raw": weight_raw,
            "weight_source": weight_source,
            "weight_stable": bool(weight_stable),
            "workflow": "inventory_check",
        }
        canonical = json.dumps(
            immutable_payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _calculate_photo_draft_payload_hash(
        *,
        parent_event_id: str,
        capture_kind: str,
        capture_round: int,
        qr_code: str,
        qr_source: str,
        captured_at: str,
        work_date: str,
        shift: str,
        machine: str,
        production_order: str,
        gateway_id: str,
        station_id: str,
        camera_id: str,
        frame_sha256: str,
    ) -> str:
        immutable_payload = {
            "camera_id": camera_id,
            "capture_kind": capture_kind,
            "capture_round": capture_round,
            "captured_at": captured_at,
            "frame_sha256": frame_sha256,
            "gateway_id": gateway_id,
            "machine": machine,
            "parent_event_id": parent_event_id,
            "production_order": production_order,
            "qr_code": qr_code,
            "qr_source": qr_source,
            "shift": shift,
            "station_id": station_id,
            "status": "awaiting_ai",
            "work_date": work_date,
            "workflow": "photo_draft",
        }
        canonical = json.dumps(
            immutable_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def save(
        self,
        qr_code: str,
        weight: float,
        unit: str,
        frame: np.ndarray,
        weight_source: str,
        needs_sync: bool = False,
        qr_source: str = "camera",
        weight_raw: str = "",
        weight_stable: bool = True,
        *,
        event_id: str | None = None,
        captured_at: str | None = None,
        gateway_id: str = "",
        station_id: str = "",
        camera_id: str = "",
        analysis_id: str = "",
    ) -> Measurement:
        return self.save_idempotent(
            qr_code,
            weight,
            unit,
            frame,
            weight_source,
            needs_sync,
            qr_source,
            weight_raw,
            weight_stable,
            event_id=event_id,
            captured_at=captured_at,
            gateway_id=gateway_id,
            station_id=station_id,
            camera_id=camera_id,
            analysis_id=analysis_id,
        ).measurement

    def save_idempotent(
        self,
        qr_code: str,
        weight: float,
        unit: str,
        frame: np.ndarray,
        weight_source: str,
        needs_sync: bool = False,
        qr_source: str = "camera",
        weight_raw: str = "",
        weight_stable: bool = True,
        *,
        event_id: str | None = None,
        captured_at: str | None = None,
        gateway_id: str = "",
        station_id: str = "",
        camera_id: str = "",
        analysis_id: str = "",
    ) -> SaveResult:
        event_id = event_id or str(uuid.uuid4())
        if captured_at is None:
            # A caller retrying an explicit idempotency key should not have to
            # remember the timestamp that storage assigned on the first call.
            existing_measurement = self.get(event_id)
            if existing_measurement is not None:
                captured_at = existing_measurement.captured_at
        captured_at = captured_at or datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
        weight_raw = weight_raw[:1000]

        encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
        if not encoded_ok:
            raise OSError("Cannot encode capture image as JPEG")
        jpeg_bytes = encoded_frame.tobytes()
        frame_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()
        payload_hash = self._calculate_payload_hash(
            qr_code=qr_code,
            weight=weight,
            unit=unit,
            captured_at=captured_at,
            weight_source=weight_source,
            qr_source=qr_source,
            weight_raw=weight_raw,
            weight_stable=weight_stable,
            gateway_id=gateway_id,
            station_id=station_id,
            camera_id=camera_id,
            analysis_id=analysis_id,
            frame_sha256=frame_sha256,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        event_token = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8]
        image_path = self.capture_dir / f"{timestamp}_{event_token}_{uuid.uuid4().hex[:8]}.jpg"
        try:
            self._write_durable_capture(image_path, jpeg_bytes)
        except OSError as exc:
            image_path.unlink(missing_ok=True)
            raise OSError(f"Cannot write capture image: {image_path}") from exc

        sync_status = "pending" if needs_sync else "local"
        try:
            with self._lock:
                existing = self.connection.execute(
                    "SELECT * FROM measurements WHERE event_id = ?", (event_id,)
                ).fetchone()
                if existing is not None:
                    image_path.unlink(missing_ok=True)
                    if str(existing["payload_hash"]) == payload_hash:
                        return SaveResult(self._from_row(existing), duplicate=True)
                    raise EventIdConflictError(event_id)

                cursor = self.connection.execute(
                    """
                    INSERT INTO measurements (
                        event_id, qr_code, weight, unit, captured_at, image_path,
                        weight_source, qr_source, sync_status, weight_raw, weight_stable,
                        gateway_id, station_id, camera_id, analysis_id,
                        frame_sha256, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        qr_code,
                        weight,
                        unit,
                        captured_at,
                        str(image_path.resolve()),
                        weight_source,
                        qr_source,
                        sync_status,
                        weight_raw,
                        int(weight_stable),
                        gateway_id,
                        station_id,
                        camera_id,
                        analysis_id,
                        frame_sha256,
                        payload_hash,
                    ),
                )
                self.connection.commit()
        except sqlite3.IntegrityError as exc:
            # A different store/process may have committed the same event after
            # our pre-insert check. Resolve that race idempotently.
            with self._lock:
                self.connection.rollback()
                existing = self.connection.execute(
                    "SELECT * FROM measurements WHERE event_id = ?", (event_id,)
                ).fetchone()
            image_path.unlink(missing_ok=True)
            if existing is not None and str(existing["payload_hash"]) == payload_hash:
                return SaveResult(self._from_row(existing), duplicate=True)
            if existing is not None:
                raise EventIdConflictError(event_id) from exc
            raise
        except Exception:
            image_path.unlink(missing_ok=True)
            raise

        saved = self.get(event_id)
        if saved is None:  # pragma: no cover - protects against external DB corruption.
            image_path.unlink(missing_ok=True)
            raise RuntimeError(f"Inserted event cannot be read back: {event_id}")
        return SaveResult(saved, duplicate=False)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Measurement:
        return Measurement(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            qr_code=str(row["qr_code"]),
            weight=float(row["weight"]),
            unit=str(row["unit"]),
            captured_at=str(row["captured_at"]),
            image_path=str(row["image_path"]),
            product_image_path=str(row["product_image_path"]),
            weight_source=str(row["weight_source"]),
            sync_status=str(row["sync_status"]),
            qr_source=str(row["qr_source"]),
            product_weight=(
                float(row["product_weight"])
                if row["product_weight"] is not None
                else None
            ),
            retry_count=int(row["retry_count"]),
            sync_error=str(row["sync_error"]) if row["sync_error"] is not None else None,
            remote_id=int(row["remote_id"]) if row["remote_id"] is not None else None,
            remote_image_url=(
                str(row["remote_image_url"]) if row["remote_image_url"] is not None else None
            ),
            remote_image_public_id=(
                str(row["remote_image_public_id"])
                if row["remote_image_public_id"] is not None
                else None
            ),
            weight_raw=str(row["weight_raw"]),
            weight_stable=bool(row["weight_stable"]),
            gateway_id=str(row["gateway_id"]),
            station_id=str(row["station_id"]),
            camera_id=str(row["camera_id"]),
            analysis_id=str(row["analysis_id"]),
            frame_sha256=str(row["frame_sha256"]),
            payload_hash=str(row["payload_hash"]),
        )

    def get(self, event_id: str) -> Measurement | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM measurements WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def recent(self, limit: int = 50) -> list[Measurement]:
        safe_limit = max(1, min(int(limit), 2000))
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM measurements ORDER BY id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete_measurement(self, event_id: str) -> bool:
        event_id = str(event_id or "").strip()
        if not event_id:
            return False
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM measurements WHERE event_id = ?",
                (event_id,),
            )
            self.connection.commit()
            return cursor.rowcount > 0

    def delete_photo_drafts(self, parent_event_id: str) -> int:
        """Delete all local saved-error photos grouped into one displayed row."""

        parent_event_id = str(parent_event_id or "").strip()
        if not parent_event_id:
            return 0
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM photo_drafts WHERE parent_event_id = ? OR event_id = ?",
                (parent_event_id, parent_event_id),
            )
            self.connection.commit()
            return max(0, int(cursor.rowcount))

    def update_measurement_fields(
        self,
        event_id: str,
        *,
        qr_code: str,
        weight: float,
        product_weight: float,
        weight_raw: str = "",
    ) -> Measurement:
        event_id = str(event_id or "").strip()
        if not event_id:
            raise KeyError("Missing event_id")
        with self._lock:
            cursor = self.connection.execute(
                """
                UPDATE measurements
                SET qr_code = ?, weight = ?, product_weight = ?,
                    weight_raw = CASE
                        WHEN ? != '' THEN ?
                        ELSE weight_raw
                    END
                WHERE event_id = ?
                """,
                (
                    qr_code.strip(),
                    float(weight),
                    float(product_weight),
                    str(weight_raw or "").strip(),
                    str(weight_raw or "").strip(),
                    event_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown capture event: {event_id}")
            self.connection.commit()
            row = self.connection.execute(
                "SELECT * FROM measurements WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return self._from_row(row)

    def measurement_source_rows(self) -> list[dict[str, object]]:
        """Return lightweight source fields for exact filtered measurement counts."""

        with self._lock:
            rows = self.connection.execute(
                "SELECT event_id, captured_at, weight_raw, sync_status "
                "FROM measurements ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def photo_draft_source_rows(self) -> list[dict[str, object]]:
        """Return saved-error fields for counts and production-list display."""

        with self._lock:
            rows = self.connection.execute(
                "SELECT event_id, parent_event_id, capture_kind, capture_round, "
                "qr_code, captured_at, image_path, remote_image_url, work_date, "
                "shift, machine, production_order, status, sync_status, sync_error "
                "FROM photo_drafts "
                "ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def attach_product_image(self, event_id: str, frame: np.ndarray) -> str:
        """Persist the product-weight evidence beside its core-weight event."""
        encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
        if not encoded_ok:
            raise OSError("Cannot encode product capture image as JPEG")
        path = self.capture_dir / f"{event_id}_product.jpg"
        try:
            self._write_durable_capture(path, encoded_frame.tobytes())
        except OSError:
            path.unlink(missing_ok=True)
            raise
        with self._lock:
            cursor = self.connection.execute(
                "UPDATE measurements SET product_image_path = ? WHERE event_id = ?",
                (str(path.resolve()), event_id),
            )
            if cursor.rowcount != 1:
                path.unlink(missing_ok=True)
                raise KeyError(f"Unknown capture event: {event_id}")
            self.connection.commit()
        return str(path.resolve())

    def attach_product_weight(self, event_id: str, product_weight: float) -> None:
        if not np.isfinite(product_weight) or product_weight < 0:
            raise ValueError("Product weight must be a non-negative finite number")
        with self._lock:
            cursor = self.connection.execute(
                "UPDATE measurements SET product_weight = ? WHERE event_id = ?",
                (float(product_weight), event_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown capture event: {event_id}")
            self.connection.commit()

    def pending(
        self,
        limit: int = 20,
        include_deferred: bool = False,
        *,
        include_failed: bool = True,
    ) -> list[Measurement]:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        retry_clause = "" if include_deferred else "AND (next_retry_at IS NULL OR next_retry_at <= ?)"
        parameters: tuple[object, ...] = (limit,) if include_deferred else (now, limit)
        statuses = "('pending', 'failed')" if include_failed else "('pending')"
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT * FROM measurements
                WHERE (
                    sync_status IN {statuses}
                    OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')
                )
                  AND (image_path <> '' OR product_image_path <> '')
                  {retry_clause}
                ORDER BY id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def mark_synced(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            self.connection.execute(
                """
                UPDATE measurements
                SET sync_status = 'synced', sync_error = NULL, next_retry_at = NULL,
                    last_attempt_at = ?, synced_at = ?, remote_id = ?,
                    remote_image_url = ?, remote_image_public_id = ?
                WHERE event_id = ?
                """,
                (
                    now,
                    now,
                    remote_id,
                    remote_image_url,
                    remote_image_public_id,
                    event_id,
                ),
            )
            self.connection.commit()

    def _mark_cloudinary_pending(
        self,
        table: str,
        event_id: str,
        remote_id: int | None,
        remote_image_url: str | None,
        remote_image_public_id: str | None,
    ) -> None:
        if table not in {"measurements", "inventory_checks", "photo_drafts"}:
            raise ValueError("Unsupported outbox table")
        now = datetime.now(timezone.utc)
        retry_at = now + timedelta(seconds=30)
        with self._lock:
            self.connection.execute(
                f"""
                UPDATE {table}
                SET sync_status = 'synced', sync_error = 'cloudinary_pending',
                    next_retry_at = ?, last_attempt_at = ?,
                    synced_at = COALESCE(synced_at, ?), remote_id = ?,
                    remote_image_url = ?, remote_image_public_id = ?
                WHERE event_id = ?
                """,
                (
                    retry_at.isoformat(timespec="milliseconds"),
                    now.isoformat(timespec="milliseconds"),
                    now.isoformat(timespec="milliseconds"),
                    remote_id,
                    remote_image_url,
                    remote_image_public_id,
                    event_id,
                ),
            )
            self.connection.commit()

    def mark_cloudinary_pending(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        """Record a cloud row while keeping its missing Cloudinary image retryable."""

        self._mark_cloudinary_pending(
            "measurements",
            event_id,
            remote_id,
            remote_image_url,
            remote_image_public_id,
        )

    def mark_sync_failed(self, event_id: str, error: str) -> None:
        now_dt = datetime.now(timezone.utc)
        with self._lock:
            row = self.connection.execute(
                "SELECT retry_count FROM measurements WHERE event_id = ?", (event_id,)
            ).fetchone()
            retry_count = (int(row["retry_count"]) if row else 0) + 1
            delay_seconds = min(300, 2 ** min(retry_count, 8))
            next_retry = (now_dt + timedelta(seconds=delay_seconds)).isoformat(
                timespec="milliseconds"
            )
            self.connection.execute(
                """
                UPDATE measurements
                SET sync_status = 'failed', sync_error = ?, retry_count = ?,
                    last_attempt_at = ?, next_retry_at = ?
                WHERE event_id = ?
                """,
                (
                    error[:1000],
                    retry_count,
                    now_dt.isoformat(timespec="milliseconds"),
                    next_retry,
                    event_id,
                ),
            )
            self.connection.commit()

    def save_inventory_check_idempotent(
        self,
        product_code: str,
        weight: float,
        core_weight: float,
        tare_weight: float,
        unit: str,
        frame: np.ndarray,
        weight_source: str,
        needs_sync: bool = False,
        qr_source: str = "camera",
        weight_raw: str = "",
        weight_stable: bool = True,
        *,
        event_id: str | None = None,
        captured_at: str | None = None,
        gateway_id: str = "",
        station_id: str = "",
        camera_id: str = "",
        analysis_id: str = "",
    ) -> tuple[InventoryCheck, bool]:
        product_code = product_code.strip()
        if not product_code or len(product_code) > 512:
            raise ValueError("Product code must contain 1 to 512 characters")
        for label, value in (
            ("weight", weight),
            ("core_weight", core_weight),
            ("tare_weight", tare_weight),
        ):
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be a non-negative finite number")
        event_id = event_id or str(uuid.uuid4())
        if captured_at is None:
            existing_check = self.get_inventory_check(event_id)
            if existing_check is not None:
                captured_at = existing_check.captured_at
        captured_at = captured_at or datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
        weight_raw = weight_raw[:1000]
        encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
        if not encoded_ok:
            raise OSError("Cannot encode inventory check image as JPEG")
        jpeg_bytes = encoded_frame.tobytes()
        frame_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()
        payload_hash = self._calculate_inventory_payload_hash(
            product_code=product_code,
            weight=weight,
            core_weight=core_weight,
            tare_weight=tare_weight,
            unit=unit,
            captured_at=captured_at,
            weight_source=weight_source,
            qr_source=qr_source,
            weight_raw=weight_raw,
            weight_stable=weight_stable,
            gateway_id=gateway_id,
            station_id=station_id,
            camera_id=camera_id,
            analysis_id=analysis_id,
            frame_sha256=frame_sha256,
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        event_token = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8]
        image_path = (
            self.capture_dir
            / f"{timestamp}_{event_token}_{uuid.uuid4().hex[:8]}_inventory.jpg"
        )
        try:
            self._write_durable_capture(image_path, jpeg_bytes)
        except OSError as exc:
            image_path.unlink(missing_ok=True)
            raise OSError(f"Cannot write inventory check image: {image_path}") from exc

        try:
            with self._lock:
                existing = self.connection.execute(
                    "SELECT * FROM inventory_checks WHERE event_id = ?", (event_id,)
                ).fetchone()
                if existing is not None:
                    image_path.unlink(missing_ok=True)
                    if str(existing["payload_hash"]) == payload_hash:
                        return self._inventory_from_row(existing), True
                    raise EventIdConflictError(event_id)
                self.connection.execute(
                    """
                    INSERT INTO inventory_checks (
                        event_id, product_code, weight, core_weight, tare_weight,
                        unit, captured_at, image_path, weight_source, qr_source,
                        sync_status, weight_raw, weight_stable, gateway_id,
                        station_id, camera_id, analysis_id, frame_sha256, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        product_code,
                        float(weight),
                        float(core_weight),
                        float(tare_weight),
                        unit,
                        captured_at,
                        str(image_path.resolve()),
                        weight_source,
                        qr_source,
                        "pending" if needs_sync else "local",
                        weight_raw,
                        int(weight_stable),
                        gateway_id,
                        station_id,
                        camera_id,
                        analysis_id,
                        frame_sha256,
                        payload_hash,
                    ),
                )
                self.connection.commit()
        except sqlite3.IntegrityError as exc:
            with self._lock:
                self.connection.rollback()
                existing = self.connection.execute(
                    "SELECT * FROM inventory_checks WHERE event_id = ?", (event_id,)
                ).fetchone()
            image_path.unlink(missing_ok=True)
            if existing is not None and str(existing["payload_hash"]) == payload_hash:
                return self._inventory_from_row(existing), True
            if existing is not None:
                raise EventIdConflictError(event_id) from exc
            raise
        except Exception:
            image_path.unlink(missing_ok=True)
            raise
        saved = self.get_inventory_check(event_id)
        if saved is None:  # pragma: no cover - protects against external DB corruption.
            image_path.unlink(missing_ok=True)
            raise RuntimeError(f"Inserted inventory check cannot be read back: {event_id}")
        return saved, False

    @staticmethod
    def _inventory_from_row(row: sqlite3.Row) -> InventoryCheck:
        return InventoryCheck(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            product_code=str(row["product_code"]),
            weight=float(row["weight"]),
            core_weight=float(row["core_weight"]),
            tare_weight=float(row["tare_weight"]),
            unit=str(row["unit"]),
            captured_at=str(row["captured_at"]),
            image_path=str(row["image_path"]),
            weight_source=str(row["weight_source"]),
            sync_status=str(row["sync_status"]),
            qr_source=str(row["qr_source"]),
            retry_count=int(row["retry_count"]),
            sync_error=str(row["sync_error"]) if row["sync_error"] is not None else None,
            remote_id=int(row["remote_id"]) if row["remote_id"] is not None else None,
            remote_image_url=(
                str(row["remote_image_url"]) if row["remote_image_url"] is not None else None
            ),
            remote_image_public_id=(
                str(row["remote_image_public_id"])
                if row["remote_image_public_id"] is not None
                else None
            ),
            weight_raw=str(row["weight_raw"]),
            weight_stable=bool(row["weight_stable"]),
            gateway_id=str(row["gateway_id"]),
            station_id=str(row["station_id"]),
            camera_id=str(row["camera_id"]),
            analysis_id=str(row["analysis_id"]),
            frame_sha256=str(row["frame_sha256"]),
            payload_hash=str(row["payload_hash"]),
        )

    def get_inventory_check(self, event_id: str) -> InventoryCheck | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM inventory_checks WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._inventory_from_row(row) if row else None

    def recent_inventory_checks(self, limit: int = 50) -> list[InventoryCheck]:
        safe_limit = max(1, min(int(limit), 200))
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM inventory_checks ORDER BY id DESC LIMIT ?", (safe_limit,)
            ).fetchall()
        return [self._inventory_from_row(row) for row in rows]

    def pending_inventory_checks(
        self,
        limit: int = 20,
        include_deferred: bool = False,
        *,
        include_failed: bool = True,
    ) -> list[InventoryCheck]:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        retry_clause = "" if include_deferred else "AND (next_retry_at IS NULL OR next_retry_at <= ?)"
        parameters: tuple[object, ...] = (limit,) if include_deferred else (now, limit)
        statuses = "('pending', 'failed')" if include_failed else "('pending')"
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT * FROM inventory_checks
                WHERE (
                    sync_status IN {statuses}
                    OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')
                )
                  AND image_path <> ''
                  {retry_clause}
                ORDER BY id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._inventory_from_row(row) for row in rows]

    def mark_inventory_check_synced(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            self.connection.execute(
                """
                UPDATE inventory_checks
                SET sync_status = 'synced', sync_error = NULL, next_retry_at = NULL,
                    last_attempt_at = ?, synced_at = ?, remote_id = ?,
                    remote_image_url = ?, remote_image_public_id = ?
                WHERE event_id = ?
                """,
                (now, now, remote_id, remote_image_url, remote_image_public_id, event_id),
            )
            self.connection.commit()

    def mark_inventory_check_cloudinary_pending(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        """Keep a locally committed inventory row retryable after cloud failure."""

        self._mark_cloudinary_pending(
            "inventory_checks",
            event_id,
            remote_id,
            remote_image_url,
            remote_image_public_id,
        )

    def mark_inventory_check_failed(self, event_id: str, error: str) -> None:
        now_dt = datetime.now(timezone.utc)
        with self._lock:
            row = self.connection.execute(
                "SELECT retry_count FROM inventory_checks WHERE event_id = ?", (event_id,)
            ).fetchone()
            retry_count = (int(row["retry_count"]) if row else 0) + 1
            delay_seconds = min(300, 2 ** min(retry_count, 8))
            next_retry = (now_dt + timedelta(seconds=delay_seconds)).isoformat(
                timespec="milliseconds"
            )
            self.connection.execute(
                """
                UPDATE inventory_checks
                SET sync_status = 'failed', sync_error = ?, retry_count = ?,
                    last_attempt_at = ?, next_retry_at = ?
                WHERE event_id = ?
                """,
                (
                    error[:1000],
                    retry_count,
                    now_dt.isoformat(timespec="milliseconds"),
                    next_retry,
                    event_id,
                ),
            )
            self.connection.commit()

    def save_photo_draft_idempotent(
        self,
        frame: np.ndarray,
        *,
        qr_code: str = "",
        qr_source: str = "none",
        needs_sync: bool = False,
        event_id: str | None = None,
        parent_event_id: str = "",
        capture_kind: str = "core",
        capture_round: int = 0,
        captured_at: str | None = None,
        work_date: str = "",
        shift: str = "",
        machine: str = "",
        production_order: str = "",
        gateway_id: str = "",
        station_id: str = "",
        camera_id: str = "",
    ) -> tuple[PhotoDraft, bool]:
        qr_code = qr_code.strip()
        if len(qr_code) > 512 or any(ord(character) < 32 for character in qr_code):
            raise ValueError("QR must be empty or contain at most 512 printable characters")
        event_id = event_id or str(uuid.uuid4())
        parent_event_id = parent_event_id.strip() or event_id
        if capture_kind not in {"core", "product", "inventory"}:
            raise ValueError("Photo capture kind must be core, product or inventory")
        if not 0 <= capture_round <= 3:
            raise ValueError("Photo capture round must be between 0 and 3")
        if captured_at is None:
            existing_draft = self.get_photo_draft(event_id)
            if existing_draft is not None:
                captured_at = existing_draft.captured_at
        captured_at = captured_at or datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
        encoded_ok, encoded_frame = cv2.imencode(".jpg", frame)
        if not encoded_ok:
            raise OSError("Cannot encode photo draft as JPEG")
        jpeg_bytes = encoded_frame.tobytes()
        frame_sha256 = hashlib.sha256(jpeg_bytes).hexdigest()
        payload_hash = self._calculate_photo_draft_payload_hash(
            parent_event_id=parent_event_id,
            capture_kind=capture_kind,
            capture_round=capture_round,
            qr_code=qr_code,
            qr_source=qr_source,
            captured_at=captured_at,
            work_date=work_date,
            shift=shift,
            machine=machine,
            production_order=production_order,
            gateway_id=gateway_id,
            station_id=station_id,
            camera_id=camera_id,
            frame_sha256=frame_sha256,
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        event_token = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:8]
        image_path = (
            self.capture_dir
            / f"{timestamp}_{event_token}_{uuid.uuid4().hex[:8]}_photo_draft.jpg"
        )
        try:
            self._write_durable_capture(image_path, jpeg_bytes)
        except OSError as exc:
            image_path.unlink(missing_ok=True)
            raise OSError(f"Cannot write photo draft: {image_path}") from exc

        try:
            with self._lock:
                existing = self.connection.execute(
                    "SELECT * FROM photo_drafts WHERE event_id = ?", (event_id,)
                ).fetchone()
                if existing is not None:
                    image_path.unlink(missing_ok=True)
                    if str(existing["payload_hash"]) == payload_hash:
                        return self._photo_draft_from_row(existing), True
                    raise EventIdConflictError(event_id)
                self.connection.execute(
                    """
                    INSERT INTO photo_drafts (
                        event_id, parent_event_id, capture_kind, capture_round,
                        qr_code, captured_at, image_path, qr_source,
                        work_date, shift, machine, production_order, status,
                        sync_status, gateway_id, station_id, camera_id,
                        frame_sha256, payload_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_ai', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        parent_event_id,
                        capture_kind,
                        capture_round,
                        qr_code,
                        captured_at,
                        str(image_path.resolve()),
                        qr_source,
                        work_date[:10],
                        shift[:80],
                        machine[:80],
                        production_order[:80],
                        "pending" if needs_sync else "local",
                        gateway_id,
                        station_id,
                        camera_id,
                        frame_sha256,
                        payload_hash,
                    ),
                )

                self.connection.commit()
        except sqlite3.IntegrityError as exc:
            with self._lock:
                self.connection.rollback()
                existing = self.connection.execute(
                    "SELECT * FROM photo_drafts WHERE event_id = ?", (event_id,)
                ).fetchone()
            image_path.unlink(missing_ok=True)
            if existing is not None and str(existing["payload_hash"]) == payload_hash:
                return self._photo_draft_from_row(existing), True
            if existing is not None:
                raise EventIdConflictError(event_id) from exc
            raise
        except Exception:
            image_path.unlink(missing_ok=True)
            raise
        saved = self.get_photo_draft(event_id)
        if saved is None:  # pragma: no cover
            image_path.unlink(missing_ok=True)
            raise RuntimeError(f"Inserted photo draft cannot be read back: {event_id}")
        return saved, False

    @staticmethod
    def _photo_draft_from_row(row: sqlite3.Row) -> PhotoDraft:
        return PhotoDraft(
            id=int(row["id"]),
            event_id=str(row["event_id"]),
            parent_event_id=str(row["parent_event_id"] or row["event_id"]),
            capture_kind=str(row["capture_kind"]),
            capture_round=int(row["capture_round"]),
            qr_code=str(row["qr_code"]),
            captured_at=str(row["captured_at"]),
            image_path=str(row["image_path"]),
            qr_source=str(row["qr_source"]),
            sync_status=str(row["sync_status"]),
            work_date=str(row["work_date"]),
            shift=str(row["shift"]),
            machine=str(row["machine"]),
            production_order=str(row["production_order"]),
            status=str(row["status"]),
            retry_count=int(row["retry_count"]),
            sync_error=str(row["sync_error"]) if row["sync_error"] is not None else None,
            remote_id=int(row["remote_id"]) if row["remote_id"] is not None else None,
            remote_image_url=(
                str(row["remote_image_url"]) if row["remote_image_url"] is not None else None
            ),
            remote_image_public_id=(
                str(row["remote_image_public_id"])
                if row["remote_image_public_id"] is not None
                else None
            ),
            gateway_id=str(row["gateway_id"]),
            station_id=str(row["station_id"]),
            camera_id=str(row["camera_id"]),
            frame_sha256=str(row["frame_sha256"]),
            payload_hash=str(row["payload_hash"]),
        )

    def get_photo_draft(self, event_id: str) -> PhotoDraft | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM photo_drafts WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._photo_draft_from_row(row) if row else None

    def pending_photo_drafts(
        self,
        limit: int = 20,
        include_deferred: bool = False,
        *,
        include_failed: bool = True,
    ) -> list[PhotoDraft]:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        retry_clause = "" if include_deferred else "AND (next_retry_at IS NULL OR next_retry_at <= ?)"
        parameters: tuple[object, ...] = (limit,) if include_deferred else (now, limit)
        statuses = "('pending', 'failed')" if include_failed else "('pending')"
        with self._lock:
            rows = self.connection.execute(
                f"""
                SELECT * FROM photo_drafts
                WHERE (
                    sync_status IN {statuses}
                    OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')
                )
                  AND image_path <> ''
                  {retry_clause}
                ORDER BY id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._photo_draft_from_row(row) for row in rows]

    def mark_photo_draft_synced(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        with self._lock:
            self.connection.execute(
                """
                UPDATE photo_drafts
                SET sync_status = 'synced', sync_error = NULL, next_retry_at = NULL,
                    last_attempt_at = ?, synced_at = ?, remote_id = ?,
                    remote_image_url = ?, remote_image_public_id = ?
                WHERE event_id = ?
                """,
                (now, now, remote_id, remote_image_url, remote_image_public_id, event_id),
            )
            self.connection.commit()

    def mark_photo_draft_cloudinary_pending(
        self,
        event_id: str,
        remote_id: int | None = None,
        remote_image_url: str | None = None,
        remote_image_public_id: str | None = None,
    ) -> None:
        """Keep a locally committed AI-photo row retryable after cloud failure."""

        self._mark_cloudinary_pending(
            "photo_drafts",
            event_id,
            remote_id,
            remote_image_url,
            remote_image_public_id,
        )

    def mark_photo_draft_failed(self, event_id: str, error: str) -> None:
        now_dt = datetime.now(timezone.utc)
        with self._lock:
            row = self.connection.execute(
                "SELECT retry_count FROM photo_drafts WHERE event_id = ?", (event_id,)
            ).fetchone()
            retry_count = (int(row["retry_count"]) if row else 0) + 1
            delay_seconds = min(300, 2 ** min(retry_count, 8))
            next_retry = (now_dt + timedelta(seconds=delay_seconds)).isoformat(
                timespec="milliseconds"
            )
            self.connection.execute(
                """
                UPDATE photo_drafts
                SET sync_status = 'failed', sync_error = ?, retry_count = ?,
                    last_attempt_at = ?, next_retry_at = ?
                WHERE event_id = ?
                """,
                (
                    error[:1000],
                    retry_count,
                    now_dt.isoformat(timespec="milliseconds"),
                    next_retry,
                    event_id,
                ),
            )
            self.connection.commit()

    def photo_draft_pending_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS total FROM photo_drafts "
                "WHERE (sync_status IN ('pending', 'failed') "
                "OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')) "
                "AND image_path <> ''"
            ).fetchone()
        return int(row["total"])

    def inventory_pending_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS total FROM inventory_checks "
                "WHERE (sync_status IN ('pending', 'failed') "
                "OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')) "
                "AND image_path <> ''"
            ).fetchone()
        return int(row["total"])

    def pending_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS total FROM measurements "
                "WHERE (sync_status IN ('pending', 'failed') "
                "OR (sync_status = 'synced' AND sync_error = 'cloudinary_pending')) "
                "AND (image_path <> '' OR product_image_path <> '')"
            ).fetchone()
        return (
            int(row["total"])
            + self.inventory_pending_count()
            + self.photo_draft_pending_count()
        )

    def local_backup_report(
        self,
        retention_days: int = DEFAULT_LOCAL_RETENTION_DAYS,
        *,
        now: datetime | None = None,
        limit: int = MAX_LOCAL_EVIDENCE_ITEMS,
    ) -> dict[str, object]:
        """Return bounded, metadata-only proof for old local evidence files.

        Render's persistent disk is the independent evidence copy.  The report
        contains checksums and byte counts only; image bytes never leave the
        gateway during daily maintenance. Rows acknowledged by the Edge
        Function are eligible, including rows whose Cloudinary delivery is
        still pending. A failed Supabase request remains a normal local outbox
        row and is not offered for deletion.
        """

        safe_days = max(1, min(int(retention_days), 30))
        safe_limit = max(1, min(int(limit), MAX_LOCAL_EVIDENCE_ITEMS))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        cutoff = current - timedelta(days=safe_days)
        table_specs = (
            (
                "can_tu_dong",
                "measurements",
                (("core", "image_path", "frame_sha256"), ("product", "product_image_path", "")),
            ),
            (
                "can_kiem_kho",
                "inventory_checks",
                (("image", "image_path", "frame_sha256"),),
            ),
            (
                "anh_can_cho_ai",
                "photo_drafts",
                (("image", "image_path", "frame_sha256"),),
            ),
        )
        items: list[dict[str, object]] = []
        skipped = 0
        total_bytes = 0
        cutoff_text = cutoff.isoformat(timespec="milliseconds")
        with self._lock:
            snapshots: list[tuple[str, sqlite3.Row, tuple[tuple[str, str, str], ...]]] = []
            for remote_table, local_table, roles in table_specs:
                path_clause = "image_path <> ''"
                if local_table == "measurements":
                    path_clause = "(image_path <> '' OR product_image_path <> '')"
                # Missing files can leave a stale non-empty path in SQLite.
                # Page through old rows instead of letting a small LIMIT be
                # consumed by those tombstones. The SQL cutoff also prevents
                # a large recent outbox from filling the scan before retention
                # candidates are considered.
                offset = 0
                scanned = 0
                while scanned < MAX_LOCAL_EVIDENCE_SCAN_ROWS:
                    page_limit = min(
                        LOCAL_EVIDENCE_SCAN_PAGE,
                        MAX_LOCAL_EVIDENCE_SCAN_ROWS - scanned,
                    )
                    rows = self.connection.execute(
                        f"SELECT * FROM {local_table} "
                        f"WHERE sync_status = 'synced' AND {path_clause} "
                        "AND captured_at <= ? "
                        "ORDER BY captured_at ASC, event_id ASC LIMIT ? OFFSET ?",
                        (cutoff_text, page_limit, offset),
                    ).fetchall()
                    if not rows:
                        break
                    snapshots.extend((remote_table, row, roles) for row in rows)
                    scanned += len(rows)
                    offset += len(rows)
                    if len(rows) < page_limit:
                        break

        snapshots.sort(key=lambda item: str(item[1]["captured_at"]))
        for remote_table, row, roles in snapshots:
            if len(items) >= safe_limit:
                break
            captured_at = str(row["captured_at"] or "")
            try:
                captured = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            except ValueError:
                skipped += 1
                continue
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            if captured.astimezone(timezone.utc) > cutoff:
                continue
            roles_report: dict[str, dict[str, object]] = {}
            for role, path_column, expected_hash_column in roles:
                path = self._safe_capture_path(row[path_column])
                if path is None or not path.is_file():
                    continue
                try:
                    image_bytes = path.read_bytes()
                except OSError:
                    skipped += 1
                    continue
                if not (4 <= len(image_bytes) <= MAX_LOCAL_EVIDENCE_IMAGE_BYTES):
                    skipped += 1
                    continue
                digest = hashlib.sha256(image_bytes).hexdigest()
                expected_hash = str(row[expected_hash_column] or "").strip().lower() if expected_hash_column else ""
                if expected_hash and LOCAL_SHA256_PATTERN.match(expected_hash) and digest != expected_hash:
                    skipped += 1
                    continue
                if total_bytes + len(image_bytes) > MAX_LOCAL_EVIDENCE_BYTES:
                    break
                roles_report[role] = {"sha256": digest, "bytes": len(image_bytes)}
                total_bytes += len(image_bytes)
            if roles_report:
                items.append(
                    {
                        "table": remote_table,
                        "event_id": str(row["event_id"]),
                        "captured_at": captured_at,
                        "roles": roles_report,
                    }
                )
        return {
            "provider": LOCAL_BACKUP_PROVIDER,
            "retention_days": safe_days,
            "generated_at": current.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "items": items,
            "item_count": len(items),
            "total_bytes": total_bytes,
            "skipped": skipped,
            "cutoff": cutoff.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }

    def prune_local_captures(
        self,
        released: object,
        retention_days: int = DEFAULT_LOCAL_RETENTION_DAYS,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        """Delete only files explicitly released by remote maintenance.

        The remote function returns one release per successfully deleted
        Cloudinary object.  We re-check age, sync status, path containment and
        the reported checksum before unlinking.  Rows remain in SQLite, and a
        path shared by an unreleased row is never removed.
        """

        if not isinstance(released, list):
            return {"released": 0, "deleted": 0, "skipped": 0}
        safe_days = max(1, min(int(retention_days), 30))
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        cutoff = current.astimezone(timezone.utc) - timedelta(days=safe_days)
        release_map: dict[tuple[str, str, str], str] = {}
        for raw in released:
            if not isinstance(raw, dict):
                continue
            table = str(raw.get("table") or "").strip()
            event_id = str(raw.get("event_id") or "").strip()
            role = str(raw.get("role") or "").strip()
            digest = str(raw.get("sha256") or "").strip().lower()
            if table and event_id and role:
                release_map[(table, event_id, role)] = digest
        if not release_map:
            return {"released": 0, "deleted": 0, "skipped": 0}

        table_specs = (
            (
                "can_tu_dong",
                "measurements",
                (("core", "image_path"), ("product", "product_image_path")),
            ),
            ("can_kiem_kho", "inventory_checks", (("image", "image_path"),)),
            ("anh_can_cho_ai", "photo_drafts", (("image", "image_path"),)),
        )
        local_table_by_remote = {remote: local for remote, local, _ in table_specs}
        snapshots: list[tuple[str, sqlite3.Row, tuple[tuple[str, str], ...]]] = []
        with self._lock:
            for remote_table, local_table, roles in table_specs:
                rows = self.connection.execute(f"SELECT * FROM {local_table}").fetchall()
                snapshots.extend((remote_table, row, roles) for row in rows)

        def row_is_old_and_synced(row: sqlite3.Row) -> bool:
            if str(row["sync_status"] or "") != "synced":
                return False
            try:
                captured = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
            except ValueError:
                return False
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            return captured.astimezone(timezone.utc) <= cutoff

        candidate_keys = {
            (table, str(row["event_id"]), role)
            for table, row, roles in snapshots
            if row_is_old_and_synced(row)
            for role, _ in roles
            if (table, str(row["event_id"]), role) in release_map
        }
        referenced_by: dict[Path, set[tuple[str, str, str]]] = {}
        for table, row, roles in snapshots:
            key_event = str(row["event_id"])
            for role, path_column in roles:
                path = self._safe_capture_path(row[path_column])
                if path is not None:
                    referenced_by.setdefault(path, set()).add((table, key_event, role))

        deleted = 0
        skipped = 0
        for table, row, roles in snapshots:
            event_id = str(row["event_id"])
            if not row_is_old_and_synced(row):
                continue
            for role, path_column in roles:
                release_key = (table, event_id, role)
                if release_key not in candidate_keys:
                    continue
                path = self._safe_capture_path(row[path_column])
                digest = release_map.get(release_key, "")
                if path is None or not path.is_file():
                    skipped += 1
                    continue
                if any(key not in candidate_keys for key in referenced_by.get(path, set())):
                    skipped += 1
                    continue
                image_bytes: bytes | None = None
                unlinked = False
                try:
                    image_bytes = path.read_bytes()
                    if digest and hashlib.sha256(image_bytes).hexdigest() != digest:
                        skipped += 1
                        continue
                    path.unlink()
                    unlinked = True
                    assignments = [f"{path_column} = ''"]
                    # SQLite's remote fields represent the core image for all
                    # event types. Product evidence has no separate legacy
                    # local remote columns, so never clear the core pointer
                    # when only the product file was released.
                    if role == "core" or table != "can_tu_dong":
                        assignments.extend(
                            ["remote_image_url = NULL", "remote_image_public_id = NULL"]
                        )
                    with self._lock:
                        self.connection.execute("BEGIN")
                        current_row = self.connection.execute(
                            f"SELECT {', '.join(column for _, column in roles)}, "
                            f"sync_error FROM {local_table_by_remote[table]} "
                            "WHERE event_id = ?",
                            (event_id,),
                        ).fetchone()
                        if current_row is None:
                            raise RuntimeError("released local row disappeared")
                        has_remaining_local_path = any(
                            other_column != path_column
                            and bool(str(current_row[other_column] or "").strip())
                            for _, other_column in roles
                        )
                        if (
                            not has_remaining_local_path
                            and str(current_row["sync_error"] or "")
                            == "cloudinary_pending"
                        ):
                            # Query the current row inside the transaction. A
                            # two-image event may have had its first path
                            # cleared earlier in this same maintenance call.
                            assignments.extend(
                                ["sync_error = NULL", "next_retry_at = NULL"]
                            )
                        cursor = self.connection.execute(
                            f"UPDATE {local_table_by_remote[table]} SET "
                            + ", ".join(assignments)
                            + " WHERE event_id = ?",
                            (event_id,),
                        )
                        if cursor.rowcount != 1:
                            raise RuntimeError("released local row disappeared")
                        self.connection.commit()
                    deleted += 1
                except (OSError, RuntimeError, sqlite3.Error):
                    with self._lock:
                        if self.connection.in_transaction:
                            self.connection.rollback()
                    if unlinked and image_bytes is not None:
                        try:
                            self._write_durable_capture(path, image_bytes)
                        except OSError:
                            # The original bytes are still gone, but retaining
                            # the DB path avoids silently claiming a deletion.
                            pass
                    skipped += 1
        return {"released": len(candidate_keys), "deleted": deleted, "skipped": skipped}

    @staticmethod
    def _write_durable_capture(path: Path, image_bytes: bytes) -> None:
        """Commit image bytes to the persistent-disk file before cloud sync."""

        with path.open("wb") as stream:
            stream.write(image_bytes)
            stream.flush()
            os.fsync(stream.fileno())

    def _safe_capture_path(self, value: object) -> Path | None:
        if not value:
            return None
        try:
            root = self.capture_dir.resolve()
            candidate = Path(str(value)).resolve()
            candidate.relative_to(root)
        except (OSError, ValueError):
            return None
        return candidate if candidate != root else None

    def count(self) -> int:
        with self._lock:
            row = self.connection.execute("SELECT COUNT(*) AS total FROM measurements").fetchone()
        return int(row["total"])

    def close(self) -> None:
        with self._lock:
            self.connection.close()
