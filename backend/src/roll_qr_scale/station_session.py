from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE_STATES = frozenset({"analyzing", "ready", "error"})


class StationSessionError(ValueError):
    """Base error for invalid or conflicting camera-session operations."""


class SessionConflictError(StationSessionError):
    """A station already has an unsaved review or an identity mismatched."""


class AnalysisBindingNotFound(StationSessionError):
    """The supplied analysis ID is unknown or has expired."""


class AnalysisBindingMismatch(SessionConflictError):
    """Capture identities do not match the immutable analysis binding."""


def _identity(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or not _IDENTITY_RE.fullmatch(value):
        raise StationSessionError(f"{label} không hợp lệ")
    return value


def encode_staged_jpeg(frame: np.ndarray, *, quality: int = 95) -> bytes:
    if not isinstance(frame, np.ndarray) or frame.ndim not in (2, 3) or frame.size == 0:
        raise StationSessionError("Khung hình không hợp lệ")
    ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), min(100, max(1, int(quality)))],
    )
    if not ok:
        raise StationSessionError("Không mã hóa được ảnh JPEG")
    return encoded.tobytes()


def jpeg_sha256(jpeg: bytes) -> str:
    return hashlib.sha256(jpeg).hexdigest()


@dataclass(frozen=True)
class AnalysisBinding:
    analysis_id: str
    event_id: str
    station_id: str
    camera_id: str
    frame_sha256: str
    staged_path: Path
    captured_at: str
    created_at: float
    state: str = "analyzing"

    @property
    def image_path(self) -> Path:
        return self.staged_path

    def as_dict(self, *, include_path: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "analysis_id": self.analysis_id,
            "event_id": self.event_id,
            "station_id": self.station_id,
            "camera_id": self.camera_id,
            "frame_sha256": self.frame_sha256,
            "captured_at": self.captured_at,
            "state": self.state,
        }
        if include_path:
            result["staged_path"] = str(self.staged_path)
        return result


@dataclass
class StationSession:
    station_id: str
    configured_camera_id: str = ""
    current_analysis_id: str | None = None
    state: str = "idle"
    last_error: str = ""
    saved_count: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def status(self, bindings: dict[str, AnalysisBinding]) -> dict[str, object]:
        with self._lock:
            binding = bindings.get(self.current_analysis_id or "")
            result: dict[str, object] = {
                "station_id": self.station_id,
                "camera_id": self.configured_camera_id,
                "state": self.state,
                "saved_count": self.saved_count,
                "last_error": self.last_error or None,
            }
            if binding is not None:
                result.update(binding.as_dict())
            else:
                result.update(
                    {
                        "analysis_id": None,
                        "event_id": None,
                        "frame_sha256": None,
                    }
                )
            return result


class StationSessionRegistry:
    """Own immutable staged-image bindings for all configured stations."""

    def __init__(
        self,
        staging_dir: str | Path,
        station_ids: list[str] | tuple[str, ...],
        *,
        completed_ttl: float = 24 * 60 * 60,
        jpeg_quality: int = 95,
    ) -> None:
        if not station_ids:
            raise ValueError("At least one station is required")
        if len(station_ids) > 3:
            raise ValueError("At most three stations are supported")
        normalized = [_identity(value, "station_id") for value in station_ids]
        if len(set(normalized)) != len(normalized):
            raise ValueError("station_id values must be unique")
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.completed_ttl = max(1.0, float(completed_ttl))
        self.jpeg_quality = int(jpeg_quality)
        self._sessions = {value: StationSession(value) for value in normalized}
        self._bindings: dict[str, AnalysisBinding] = {}
        self._lock = threading.RLock()
        self._state_path = self.staging_dir / ".active-bindings.json"
        self._restore_persisted_bindings()

    @property
    def station_ids(self) -> tuple[str, ...]:
        return tuple(self._sessions)

    def configure_camera(self, station_id: str, camera_id: str) -> None:
        session = self._session(station_id)
        camera_id = _identity(camera_id, "camera_id") if camera_id else ""
        with self._lock, session._lock:
            if camera_id and any(
                other is not session and other.configured_camera_id == camera_id
                for other in self._sessions.values()
            ):
                raise ValueError(f"camera_id đã được gán cho trạm khác: {camera_id}")
            session.configured_camera_id = camera_id

    def stage(
        self,
        frame: np.ndarray,
        *,
        event_id: str,
        station_id: str,
        camera_id: str,
        captured_at: str | None = None,
    ) -> AnalysisBinding:
        event_id = _identity(event_id, "event_id")
        station_id = _identity(station_id, "station_id")
        camera_id = _identity(camera_id, "camera_id")
        session = self._session(station_id)
        with session._lock:
            if session.configured_camera_id and session.configured_camera_id != camera_id:
                raise AnalysisBindingMismatch(
                    f"camera_id {camera_id} không thuộc {station_id}"
                )
        jpeg = encode_staged_jpeg(frame, quality=self.jpeg_quality)
        digest = jpeg_sha256(jpeg)

        with self._lock, session._lock:
            self._prune_locked()
            current = self._bindings.get(session.current_analysis_id or "")
            if current is not None and current.state not in {"saved", "discarded"}:
                if current.event_id != event_id:
                    raise SessionConflictError(
                        f"{station_id} còn một lần cân chưa lưu; hãy lưu hoặc hủy trước khi chụp lại"
                    )
                self._require_match(current, station_id, camera_id, digest)
                return current

            analysis_id = str(uuid.uuid4())
            captured_at = captured_at or datetime.now(timezone.utc).isoformat()
            folder = self.staging_dir / station_id
            folder.mkdir(parents=True, exist_ok=True)
            final_path = folder / f"{event_id}_{analysis_id}.jpg"
            temporary_path = final_path.with_suffix(".tmp")
            try:
                with temporary_path.open("wb") as staged:
                    staged.write(jpeg)
                    staged.flush()
                    os.fsync(staged.fileno())
                temporary_path.replace(final_path)
            finally:
                if temporary_path.exists():
                    temporary_path.unlink()
            binding = AnalysisBinding(
                analysis_id=analysis_id,
                event_id=event_id,
                station_id=station_id,
                camera_id=camera_id,
                frame_sha256=digest,
                staged_path=final_path,
                captured_at=captured_at,
                created_at=time.time(),
            )
            self._bindings[analysis_id] = binding
            session.current_analysis_id = analysis_id
            if not session.configured_camera_id:
                session.configured_camera_id = camera_id
            session.state = "analyzing"
            session.last_error = ""
            self._persist_active_bindings_locked()
            return binding

    begin_analysis = stage

    def restore_ready(self, binding: AnalysisBinding) -> AnalysisBinding:
        """Restore one active staged binding after a gateway process restart.

        The staged JPEG and its hash are the trust boundary.  This method is
        intentionally explicit (the caller must provide the immutable binding)
        so normal captures remain unchanged while a controlled restart can
        preserve an operator's unsaved review.
        """

        if binding.state not in {"analyzing", "ready", "error"}:
            raise StationSessionError("Chỉ được khôi phục phiên chưa hoàn tất")
        analysis_id = _identity(binding.analysis_id, "analysis_id")
        event_id = _identity(binding.event_id, "event_id")
        station_id = _identity(binding.station_id, "station_id")
        camera_id = _identity(binding.camera_id, "camera_id")
        staged_path = Path(binding.staged_path)
        try:
            staged_path = staged_path.resolve()
            staged_path.relative_to(self.staging_dir.resolve())
        except ValueError as exc:
            raise StationSessionError("Ảnh staging nằm ngoài thư mục an toàn") from exc
        if not staged_path.is_file():
            raise AnalysisBindingNotFound("Ảnh staging cần khôi phục không tồn tại")
        if jpeg_sha256(staged_path.read_bytes()) != str(binding.frame_sha256).lower():
            raise AnalysisBindingMismatch("Hash ảnh staging không khớp binding")
        session = self._session(station_id)
        with self._lock, session._lock:
            current = self._bindings.get(session.current_analysis_id or "")
            if current is not None and current.state not in {"saved", "discarded"}:
                raise SessionConflictError(f"{station_id} đã có phiên đang xử lý")
            if analysis_id in self._bindings:
                raise SessionConflictError("analysis_id đã tồn tại")
            if session.configured_camera_id and session.configured_camera_id != camera_id:
                raise AnalysisBindingMismatch(
                    f"camera_id {camera_id} không thuộc {station_id}"
                )
            restored = replace(
                binding,
                analysis_id=analysis_id,
                event_id=event_id,
                station_id=station_id,
                camera_id=camera_id,
                frame_sha256=str(binding.frame_sha256).lower(),
                staged_path=staged_path,
            )
            self._bindings[analysis_id] = restored
            session.current_analysis_id = analysis_id
            session.state = restored.state
            session.last_error = ""
            if not session.configured_camera_id:
                session.configured_camera_id = camera_id
            self._persist_active_bindings_locked()
            return restored

    def mark_ready(self, analysis_id: str) -> AnalysisBinding:
        return self._transition(analysis_id, "ready")

    def mark_failed(self, analysis_id: str, error: object) -> AnalysisBinding:
        binding = self._transition(analysis_id, "error")
        session = self._sessions[binding.station_id]
        with session._lock:
            session.last_error = str(error)[:500]
        return binding

    def validate(
        self,
        analysis_id: str,
        *,
        event_id: str,
        station_id: str,
        camera_id: str,
        frame_sha256: str | None = None,
        require_ready: bool = True,
    ) -> AnalysisBinding:
        with self._lock:
            self._prune_locked()
            binding = self._bindings.get(str(analysis_id))
            if binding is None:
                raise AnalysisBindingNotFound("analysis_id không tồn tại hoặc đã hết hạn")
            supplied = (
                _identity(event_id, "event_id"),
                _identity(station_id, "station_id"),
                _identity(camera_id, "camera_id"),
            )
            expected = (binding.event_id, binding.station_id, binding.camera_id)
            if supplied != expected:
                raise AnalysisBindingMismatch(
                    "event_id/station_id/camera_id không khớp lần phân tích"
                )
            if frame_sha256 and str(frame_sha256).lower() != binding.frame_sha256:
                raise AnalysisBindingMismatch("frame_sha256 không khớp ảnh đã phân tích")
            if require_ready and binding.state not in {"ready", "saved"}:
                raise SessionConflictError(
                    f"Lần phân tích chưa sẵn sàng để lưu (state={binding.state})"
                )
            if not binding.staged_path.is_file():
                raise AnalysisBindingNotFound("Ảnh phân tích đã hết hạn")
            return binding

    validate_capture = validate

    def load_frame(self, binding: AnalysisBinding) -> np.ndarray:
        frame = cv2.imread(str(binding.staged_path), cv2.IMREAD_COLOR)
        if frame is None:
            raise AnalysisBindingNotFound("Không đọc được ảnh phân tích đã lưu tạm")
        return frame

    def mark_saved(self, analysis_id: str) -> AnalysisBinding:
        previous = self.binding(analysis_id)
        binding = self._transition(analysis_id, "saved")
        session = self._sessions[binding.station_id]
        with session._lock:
            if previous is not None and previous.state != "saved":
                session.saved_count += 1
            # Keep the completed binding indexed for idempotent capture retries,
            # but release the station so a new event can begin immediately.
            if session.current_analysis_id == binding.analysis_id:
                session.current_analysis_id = None
                session.state = "idle"
                session.last_error = ""
        return binding

    complete = mark_saved

    def discard(self, station_id: str, *, event_id: str | None = None) -> bool:
        session = self._session(station_id)
        with self._lock, session._lock:
            binding = self._bindings.get(session.current_analysis_id or "")
            if binding is None:
                session.current_analysis_id = None
                session.state = "idle"
                return False
            if event_id is not None and binding.event_id != event_id:
                raise AnalysisBindingMismatch("event_id không khớp lần đang xem lại")
            discarded = replace(binding, state="discarded")
            self._bindings[binding.analysis_id] = discarded
            session.current_analysis_id = None
            session.state = "idle"
            session.last_error = ""
            self._persist_active_bindings_locked()
            return True

    def binding(self, analysis_id: str) -> AnalysisBinding | None:
        with self._lock:
            return self._bindings.get(analysis_id)

    def statuses(self) -> list[dict[str, object]]:
        with self._lock:
            return [session.status(self._bindings) for session in self._sessions.values()]

    def _session(self, station_id: str) -> StationSession:
        station_id = str(station_id).strip()
        try:
            return self._sessions[station_id]
        except KeyError as exc:
            raise StationSessionError(f"station_id chưa cấu hình: {station_id}") from exc

    def _transition(self, analysis_id: str, state: str) -> AnalysisBinding:
        with self._lock:
            binding = self._bindings.get(str(analysis_id))
            if binding is None:
                raise AnalysisBindingNotFound("analysis_id không tồn tại hoặc đã hết hạn")
            if state in {"ready", "error"} and binding.state in {"saved", "discarded"}:
                raise SessionConflictError(
                    f"Không thể chuyển analysis đã {binding.state} sang {state}"
                )
            if state == "saved" and binding.state not in {"ready", "saved", "discarded"}:
                raise SessionConflictError(
                    f"Không thể lưu analysis ở state={binding.state}"
                )
            updated = replace(binding, state=state)
            self._bindings[binding.analysis_id] = updated
            session = self._sessions[binding.station_id]
            with session._lock:
                if session.current_analysis_id == binding.analysis_id:
                    session.state = state
            self._persist_active_bindings_locked()
            return updated

    def _restore_persisted_bindings(self) -> None:
        """Restore unsaved bindings after a process restart.

        The JPEG hash remains the trust boundary. Invalid or incomplete entries
        are ignored so one damaged session cannot prevent the service starting.
        """

        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        items = payload.get("bindings") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return
        staging_root = self.staging_dir.resolve()
        with self._lock:
            interrupted = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    analysis_id = _identity(str(item["analysis_id"]), "analysis_id")
                    event_id = _identity(str(item["event_id"]), "event_id")
                    station_id = _identity(str(item["station_id"]), "station_id")
                    camera_id = _identity(str(item["camera_id"]), "camera_id")
                    frame_sha256 = str(item["frame_sha256"]).strip().lower()
                    captured_at = str(item["captured_at"]).strip()
                    created_at = float(item["created_at"])
                    state = str(item["state"]).strip()
                    staged_path = (staging_root / str(item["staged_file"])).resolve()
                    staged_path.relative_to(staging_root)
                except (KeyError, TypeError, ValueError, StationSessionError):
                    continue
                if (
                    station_id not in self._sessions
                    or state not in _ACTIVE_STATES
                    or not _SHA256_RE.fullmatch(frame_sha256)
                    or not captured_at
                    or not staged_path.is_file()
                ):
                    continue
                try:
                    if jpeg_sha256(staged_path.read_bytes()) != frame_sha256:
                        continue
                except OSError:
                    continue
                session = self._sessions[station_id]
                if session.current_analysis_id is not None or analysis_id in self._bindings:
                    continue
                # The worker that owned an in-flight analysis died with the old
                # process. Keep its staged image, but do not report it as running.
                restored_state = "error" if state == "analyzing" else state
                binding = AnalysisBinding(
                    analysis_id=analysis_id,
                    event_id=event_id,
                    station_id=station_id,
                    camera_id=camera_id,
                    frame_sha256=frame_sha256,
                    staged_path=staged_path,
                    captured_at=captured_at,
                    created_at=created_at,
                    state=restored_state,
                )
                self._bindings[analysis_id] = binding
                session.current_analysis_id = analysis_id
                session.state = restored_state
                if state == "analyzing":
                    session.last_error = "Phân tích bị gián đoạn khi ứng dụng khởi động lại"
                    interrupted = True
            if interrupted:
                self._persist_active_bindings_locked()

    def _persist_active_bindings_locked(self) -> None:
        staging_root = self.staging_dir.resolve()
        bindings: list[dict[str, object]] = []
        for session in self._sessions.values():
            binding = self._bindings.get(session.current_analysis_id or "")
            if binding is None or binding.state not in _ACTIVE_STATES:
                continue
            try:
                staged_file = binding.staged_path.resolve().relative_to(staging_root).as_posix()
            except ValueError as exc:
                raise StationSessionError("Ảnh staging nằm ngoài thư mục an toàn") from exc
            bindings.append(
                {
                    "analysis_id": binding.analysis_id,
                    "event_id": binding.event_id,
                    "station_id": binding.station_id,
                    "camera_id": binding.camera_id,
                    "frame_sha256": binding.frame_sha256,
                    "staged_file": staged_file,
                    "captured_at": binding.captured_at,
                    "created_at": binding.created_at,
                    "state": binding.state,
                }
            )
        temporary_path = self._state_path.with_suffix(".tmp")
        try:
            with temporary_path.open("w", encoding="utf-8") as persisted:
                json.dump(
                    {"version": 1, "bindings": bindings},
                    persisted,
                    ensure_ascii=False,
                    indent=2,
                )
                persisted.flush()
                os.fsync(persisted.fileno())
            temporary_path.replace(self._state_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _require_match(
        binding: AnalysisBinding,
        station_id: str,
        camera_id: str,
        frame_sha256: str,
    ) -> None:
        if (
            binding.station_id != station_id
            or binding.camera_id != camera_id
            or binding.frame_sha256 != frame_sha256
        ):
            raise AnalysisBindingMismatch(
                "Không thể thay camera hoặc khung hình cho cùng event_id"
            )

    def _prune_locked(self) -> None:
        cutoff = time.time() - self.completed_ttl
        expired = [
            analysis_id
            for analysis_id, binding in self._bindings.items()
            if binding.state in {"saved", "discarded"} and binding.created_at < cutoff
        ]
        for analysis_id in expired:
            binding = self._bindings.pop(analysis_id)
            try:
                binding.staged_path.unlink(missing_ok=True)
            except OSError:
                pass


# Concise aliases for integrations that treat this object as a binding store.
AnalysisBindingStore = StationSessionRegistry
CameraSessionRegistry = StationSessionRegistry
