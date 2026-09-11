from __future__ import annotations

import threading
import base64
import inspect
import time
from pathlib import Path
from collections.abc import Callable

from .api_client import post_measurement, post_remote_action, validate_ingest_response
from .storage import InventoryCheck, Measurement, MeasurementStore, PhotoDraft


SendFunction = Callable[[str, dict[str, object], str, str], dict[str, object]]
MaintenanceFunction = Callable[..., dict[str, object]]


def _default_send(
    url: str,
    payload: dict[str, object],
    image_path: str,
    token: str,
) -> dict[str, object]:
    return post_measurement(url, payload, image_path, token)


def _default_maintenance(
    url: str,
    token: str,
    local_evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    report = local_evidence or {
        "provider": "render_persistent_disk",
        "retention_days": 7,
        "items": [],
    }
    retention_days = int(report.get("retention_days") or 7)
    return post_remote_action(
        url,
        token,
        body={
            "action": "backup_maintenance",
            "retention_days": retention_days,
            "backup_provider": "render_persistent_disk",
            "local_evidence": report,
        },
        timeout=60.0,
    )


class OutboxSyncWorker:
    """Upload locally committed events in the background with durable retries."""

    def __init__(
        self,
        store: MeasurementStore,
        api_url: str,
        device_token: str,
        device_id: str = "",
        interval: float = 2.0,
        send: SendFunction = _default_send,
        *,
        gateway_id: str | None = None,
        require_remote_image: bool = True,
        maintenance_enabled: bool = False,
        maintenance_interval: float = 24 * 60 * 60,
        maintenance: MaintenanceFunction = _default_maintenance,
        local_retention_days: int = 7,
        maintenance_report_limit: int = 200,
    ):
        self.store = store
        self.api_url = api_url
        self.device_token = device_token
        # device_id is retained as a constructor fallback for legacy rows. New
        # captures carry their gateway identity in the outbox row itself.
        self.device_id = gateway_id if gateway_id is not None else device_id
        self.require_remote_image = require_remote_image
        self.interval = interval
        self.send = send
        self.maintenance_enabled = bool(maintenance_enabled)
        self.maintenance_interval = max(60.0, float(maintenance_interval))
        self.maintenance = maintenance
        self.local_retention_days = max(1, min(int(local_retention_days), 30))
        self.maintenance_report_limit = max(1, min(int(maintenance_report_limit), 200))
        self._maintenance_lock = threading.Lock()
        self._maintenance_last_run: float | None = None
        self._maintenance_last_success: str | None = None
        self._maintenance_last_error: str | None = None
        self._maintenance_result: dict[str, object] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._sync_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="supabase-outbox", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            # Failed uploads stay in the durable outbox with exponential
            # backoff. Event IDs make retries idempotent at the cloud boundary.
            self.sync_once(retry_failed=True)
            if (
                self.maintenance_enabled
                and (
                    self._maintenance_last_run is None
                    or time.monotonic() - self._maintenance_last_run
                    >= self.maintenance_interval
                )
            ):
                self.run_maintenance()
            self._wake.wait(self.interval)
            self._wake.clear()

    def run_maintenance(self) -> bool:
        """Release old Cloudinary objects only after local evidence is reported.

        The report is metadata-only.  The local JPEG remains the source of
        truth until the Edge Function confirms remote deletion, at which point
        the same role may be removed from the Render disk while its SQLite row
        stays intact.
        """

        if not self.maintenance_enabled:
            return False
        with self._maintenance_lock:
            self._maintenance_last_run = time.monotonic()
            try:
                try:
                    local_report = self.store.local_backup_report(
                        self.local_retention_days,
                        limit=self.maintenance_report_limit,
                    )
                except Exception as exc:
                    # A local read failure must never authorize remote deletion.
                    local_report = {
                        "provider": "render_persistent_disk",
                        "retention_days": self.local_retention_days,
                        "items": [],
                        "item_count": 0,
                        "total_bytes": 0,
                        "skipped": 1,
                        "error": str(exc)[:500],
                    }
                result = self._call_maintenance(local_report)
                result = dict(result)
                local_prune = self.store.prune_local_captures(
                    result.get("released"),
                    self.local_retention_days,
                )
                result["backup_provider"] = "render_persistent_disk"
                result["local_retention_days"] = self.local_retention_days
                result["local_report_items"] = int(local_report.get("item_count") or 0)
                result["local_report_bytes"] = int(local_report.get("total_bytes") or 0)
                result["local_report_skipped"] = int(local_report.get("skipped") or 0)
                result["local_prune"] = local_prune
                self._maintenance_result = result
                self._maintenance_last_success = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
                self._maintenance_last_error = None
                return True
            except Exception as exc:
                self._maintenance_last_error = str(exc)[:500]
                return False

    def _call_maintenance(self, local_report: dict[str, object]) -> dict[str, object]:
        """Call old two-argument test/integration hooks without losing reports."""

        try:
            signature = inspect.signature(self.maintenance)
            positional = [
                parameter
                for parameter in signature.parameters.values()
                if parameter.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
            accepts_report = any(
                parameter.kind == inspect.Parameter.VAR_POSITIONAL
                for parameter in signature.parameters.values()
            ) or len(positional) >= 3
        except (TypeError, ValueError):
            accepts_report = True
        if accepts_report:
            return self.maintenance(self.api_url, self.device_token, local_report)
        return self.maintenance(self.api_url, self.device_token)

    def maintenance_status(self) -> dict[str, object]:
        return {
            "enabled": self.maintenance_enabled,
            "interval_seconds": self.maintenance_interval,
            "last_success": self._maintenance_last_success,
            "last_error": self._maintenance_last_error,
            "result": dict(self._maintenance_result),
        }

    def _sync_measurement(self, measurement: Measurement) -> bool:
        try:
            payload = measurement.api_payload(self.device_id)
            if measurement.product_image_path:
                payload["product_image_base64"] = base64.b64encode(
                    Path(measurement.product_image_path).read_bytes()
                ).decode("ascii")
            response = self.send(
                self.api_url,
                payload,
                measurement.image_path,
                self.device_token,
            )
            validate_ingest_response(
                response,
                measurement.event_id,
                require_remote_image=self.require_remote_image,
                require_product_image=bool(measurement.product_image_path),
            )
            remote_id = response.get("id")
            remote_image_url = response.get("core_image_url") or response.get("image_url")
            remote_image_public_id = (
                response.get("core_image_public_id") or response.get("image_public_id")
            )
            mark_pending = response.get("cloudinary_pending") is True
            if mark_pending:
                self.store.mark_cloudinary_pending(
                    measurement.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            else:
                self.store.mark_synced(
                    measurement.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            return True
        except Exception as exc:
            self.store.mark_sync_failed(measurement.event_id, str(exc))
            return False

    def _sync_inventory_check(self, check: InventoryCheck) -> bool:
        try:
            response = self.send(
                self.api_url,
                check.api_payload(self.device_id),
                check.image_path,
                self.device_token,
            )
            validate_ingest_response(
                response,
                check.event_id,
                require_remote_image=self.require_remote_image,
            )
            remote_id = response.get("id")
            remote_image_url = response.get("image_url") or response.get("core_image_url")
            remote_image_public_id = (
                response.get("image_public_id") or response.get("core_image_public_id")
            )
            mark_pending = response.get("cloudinary_pending") is True
            if mark_pending:
                self.store.mark_inventory_check_cloudinary_pending(
                    check.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            else:
                self.store.mark_inventory_check_synced(
                    check.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            return True
        except Exception as exc:
            self.store.mark_inventory_check_failed(check.event_id, str(exc))
            return False

    def _sync_photo_draft(self, draft: PhotoDraft) -> bool:
        try:
            response = self.send(
                self.api_url,
                draft.api_payload(self.device_id),
                draft.image_path,
                self.device_token,
            )
            validate_ingest_response(
                response,
                draft.event_id,
                require_remote_image=self.require_remote_image,
            )
            remote_id = response.get("id")
            remote_image_url = response.get("image_url") or response.get("core_image_url")
            remote_image_public_id = (
                response.get("image_public_id") or response.get("core_image_public_id")
            )
            mark_pending = response.get("cloudinary_pending") is True
            if mark_pending:
                self.store.mark_photo_draft_cloudinary_pending(
                    draft.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            else:
                self.store.mark_photo_draft_synced(
                    draft.event_id,
                    int(remote_id) if remote_id is not None else None,
                    str(remote_image_url) if remote_image_url else None,
                    str(remote_image_public_id) if remote_image_public_id else None,
                )
            return True
        except Exception as exc:
            self.store.mark_photo_draft_failed(draft.event_id, str(exc))
            return False

    def sync_event(self, event_id: str) -> bool:
        """Synchronize one just-confirmed event before the UI reports cloud success."""

        with self._sync_lock:
            measurement = self.store.get(event_id)
            if measurement is None:
                return False
            if measurement.sync_status == "synced":
                return True
            return self._sync_measurement(measurement)

    def sync_inventory_event(self, event_id: str) -> bool:
        """Synchronize one inventory check while retaining failed rows locally."""

        with self._sync_lock:
            check = self.store.get_inventory_check(event_id)
            if check is None:
                return False
            if check.sync_status == "synced":
                return True
            return self._sync_inventory_check(check)

    def sync_photo_draft_event(self, event_id: str) -> bool:
        """Synchronize a photo-only draft without invoking the weight AI."""

        with self._sync_lock:
            draft = self.store.get_photo_draft(event_id)
            if draft is None:
                return False
            if draft.sync_status == "synced":
                return True
            return self._sync_photo_draft(draft)

    def sync_once(
        self,
        limit: int = 20,
        include_deferred: bool = False,
        *,
        retry_failed: bool = True,
    ) -> int:
        with self._sync_lock:
            synced = 0
            queued: list[Measurement | InventoryCheck | PhotoDraft] = [
                *self.store.pending(
                    limit,
                    include_deferred=include_deferred,
                    include_failed=retry_failed,
                ),
                *self.store.pending_inventory_checks(
                    limit,
                    include_deferred=include_deferred,
                    include_failed=retry_failed,
                ),
                *self.store.pending_photo_drafts(
                    limit,
                    include_deferred=include_deferred,
                    include_failed=retry_failed,
                ),
            ]
            queued.sort(key=lambda item: (item.captured_at, item.id))
            for item in queued[:limit]:
                succeeded = (
                    self._sync_photo_draft(item)
                    if isinstance(item, PhotoDraft)
                    else self._sync_inventory_check(item)
                    if isinstance(item, InventoryCheck)
                    else self._sync_measurement(item)
                )
                if succeeded:
                    synced += 1
            return synced

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(12.0, self.interval + 1.0))
