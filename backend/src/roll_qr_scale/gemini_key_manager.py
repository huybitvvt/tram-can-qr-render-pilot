from __future__ import annotations

import hashlib
import re
import threading
import uuid
from typing import Callable

from .codex_oauth import EncryptedCodexTokenStore
from .gemini_weight import GeminiWeightReader


class GeminiKeyManager:
    """Validate, encrypt and hot-swap all Gemini profile readers as one unit."""

    def __init__(
        self,
        store: EncryptedCodexTokenStore,
        *,
        backup_store: EncryptedCodexTokenStore | None = None,
        fast_model: str,
        flash31_model: str,
        flash37_model: str,
        accurate_model: str,
        fast_timeout: float,
        flash31_timeout: float,
        flash37_timeout: float,
        accurate_timeout: float,
        initial_key: str,
        initial_backup_key: str = "",
        initial_spare_key: str = "",
        rpm_limit: int = 15,
        tpm_limit: int = 250_000,
        rpd_limit: int = 500,
        reader_factory: Callable[..., GeminiWeightReader] = GeminiWeightReader,
    ) -> None:
        self.store = store
        self.backup_store = backup_store
        self.fast_model = fast_model
        self.flash31_model = flash31_model
        self.flash37_model = flash37_model
        self.accurate_model = accurate_model
        self.fast_timeout = float(fast_timeout)
        self.flash31_timeout = float(flash31_timeout)
        self.flash37_timeout = float(flash37_timeout)
        self.accurate_timeout = float(accurate_timeout)
        self.rpm_limit = max(1, int(rpm_limit))
        self.tpm_limit = max(1, int(tpm_limit))
        self.rpd_limit = max(1, int(rpd_limit))
        self.initial_key = initial_key.strip()
        self.initial_backup_key = initial_backup_key.strip()
        self.initial_spare_key = initial_spare_key.strip()
        self.reader_factory = reader_factory
        self._lock = threading.RLock()
        self._source = "environment" if self.initial_key else "none"
        self._key_id = self.key_id(self.initial_key) if self.initial_key else ""
        self._primary_key_id = self._key_id
        self._backup_key_id = ""
        self._backup_configured = False
        self._active_slot = "primary"
        self._last_error = ""
        self._spare_key_id = ""
        self._key_revision = ""

    @staticmethod
    def key_id(api_key: str) -> str:
        """Return a safe short identifier without exposing any part of the key."""
        value = GeminiKeyManager._normalize_pasted_key(api_key)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10] if value else ""

    def _saved_key(self, store: EncryptedCodexTokenStore | None) -> str:
        if store is None or not store.configured:
            return ""
        saved = store.read()
        return str(saved.get("api_key") or "").strip() if saved else ""

    def _primary_key(self) -> tuple[str, str, str]:
        if self.store.configured:
            saved = self.store.read()
            if saved and str(saved.get("api_key") or "").strip():
                slot = "backup" if saved.get("active_slot") == "backup" else "primary"
                return str(saved["api_key"]).strip(), "supabase-encrypted", slot
        return self.initial_key, "environment" if self.initial_key else "none", "primary"

    def _backup_key(self) -> str:
        try:
            saved = self._saved_key(self.backup_store)
        except Exception:
            saved = ""
        return saved or self.initial_backup_key

    def load_key(self) -> str:
        errors: list[str] = []
        try:
            primary, primary_source, selected_slot = self._primary_key()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc).strip()}")
            primary = self.initial_key
            primary_source = "environment" if primary else "none"
            selected_slot = "primary"
        try:
            backup = self._backup_key()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc).strip()}")
            backup = ""
        active_slot = "backup" if selected_slot == "backup" and backup else "primary"
        value = backup if active_slot == "backup" else primary
        source = "supabase-encrypted-backup" if active_slot == "backup" else primary_source
        with self._lock:
            self._source = source
            self._key_id = self.key_id(value)
            self._primary_key_id = self.key_id(primary)
            self._backup_key_id = self.key_id(backup)
            self._backup_configured = bool(backup)
            self._active_slot = active_slot
            self._last_error = "; ".join(errors)[:300]
        return value

    def load_shift_keys(self) -> dict[str, str]:
        """Load the shift assignments and shared spare, including legacy stores."""
        try:
            saved, keys = self._read_shift_keys(allow_partial=True)
        except Exception:
            # Read failures must never trigger a write that replaces saved keys.
            keys = {"day": self.initial_key, "night": self.initial_backup_key,
                    "spare": self.initial_spare_key}
            with self._lock:
                self._adopt_shift_keys({}, keys)
                self._last_error = "Chưa đọc được kho key mã hóa. Kiểm tra mạng và thử lại."
            return keys
        with self._lock:
            self._adopt_shift_keys(saved, keys)
        return keys

    def _read_shift_keys(self, *, allow_partial: bool = False) -> tuple[dict, dict[str, str]]:
        saved = (self.store.read() if self.store.configured else None) or {}
        ring = saved.get("shift_keys")
        if isinstance(ring, dict):
            return saved, {slot: str(ring.get(slot) or "").strip()
                           for slot in ("day", "night", "spare")}
        # Strict reads during mutation: do not erase a legacy night key if
        # its store is temporarily unreachable.
        try:
            night = self._saved_key(self.backup_store) or self.initial_backup_key
        except Exception:
            if not allow_partial:
                raise
            night = self.initial_backup_key
        return saved, {
            "day": str(saved.get("api_key") or self.initial_key).strip(),
            "night": night,
            "spare": self.initial_spare_key,
        }

    @staticmethod
    def _revision(saved: dict, keys: dict[str, str]) -> str:
        return str(saved.get("key_revision") or hashlib.sha256(
            "\0".join(keys[slot] for slot in ("day", "night", "spare")).encode("utf-8")
        ).hexdigest())

    def _adopt_shift_keys(self, saved: dict, keys: dict[str, str]) -> None:
        self._source = "supabase-encrypted" if saved else ("environment" if keys["day"] else "none")
        self._key_id = self._primary_key_id = self.key_id(keys["day"])
        self._backup_key_id = self.key_id(keys["night"])
        self._backup_configured = bool(keys["night"])
        self._spare_key_id = self.key_id(keys["spare"])
        self._key_revision = self._revision(saved, keys)
        self._active_slot = "automatic-by-shift"
        self._last_error = ""

    def _write_shift_keys(self, keys: dict[str, str], *, swap_id: str = "", slot: str = "") -> None:
        # All assignments are encrypted in ONE record and ONE write. A failed
        # swap can never persist only one half and lose the old key.
        saved = {"api_key": keys["day"], "provider": "gemini-shifts",
                 "active_slot": "automatic-by-shift", "shift_keys": dict(keys),
                 "key_revision": uuid.uuid4().hex,
                 "last_swap_id": swap_id, "last_swap_slot": slot}
        self.store.write(saved)
        self._adopt_shift_keys(saved, keys)

    def create_readers(
        self,
        api_key: str,
    ) -> tuple[
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
    ]:
        readers: list[GeminiWeightReader] = []
        try:
            readers.append(
                self.reader_factory(
                    api_key,
                    model=self.flash31_model,
                    timeout_seconds=self.flash31_timeout,
                    thinking_level="minimal",
                    max_image_edge=1600,
                    jpeg_quality=90,
                    media_resolution="medium",
                    include_qr=False,
                    rpm_limit=self.rpm_limit,
                    tpm_limit=self.tpm_limit,
                    rpd_limit=self.rpd_limit,
                )
            )
            readers.append(
                self.reader_factory(
                    api_key,
                    model=self.fast_model,
                    timeout_seconds=self.fast_timeout,
                    thinking_level="minimal",
                    max_image_edge=1600,
                    jpeg_quality=90,
                    media_resolution="medium",
                    include_qr=False,
                    rpm_limit=self.rpm_limit,
                    tpm_limit=self.tpm_limit,
                    rpd_limit=self.rpd_limit,
                )
            )
            readers.append(
                self.reader_factory(
                    api_key,
                    model=self.flash37_model,
                    timeout_seconds=self.flash37_timeout,
                    thinking_level="low",
                    max_image_edge=1600,
                    jpeg_quality=90,
                    media_resolution="medium",
                    include_qr=False,
                    rpm_limit=self.rpm_limit,
                    tpm_limit=self.tpm_limit,
                    rpd_limit=self.rpd_limit,
                )
            )
            readers.append(
                self.reader_factory(
                    api_key,
                    model=self.accurate_model,
                    timeout_seconds=self.accurate_timeout,
                    thinking_level="medium",
                    max_image_edge=1600,
                    jpeg_quality=90,
                    media_resolution="medium",
                    include_qr=False,
                    rpm_limit=self.rpm_limit,
                    tpm_limit=self.tpm_limit,
                    rpd_limit=self.rpd_limit,
                )
            )
        except Exception:
            for reader in readers:
                reader.close()
            raise
        flash31, fast, flash37, accurate = readers
        return fast, flash31, flash37, accurate

    @staticmethod
    def _normalize_pasted_key(api_key: str) -> str:
        value = api_key.strip()
        assignment = re.fullmatch(
            r"(?:export\s+)?(?:ROLL_SCALE_GEMINI_API_KEY|"
            r"ROLL_SCALE_GEMINI_BACKUP_API_KEY|ROLL_SCALE_GEMINI_SPARE_API_KEY|"
            r"GEMINI_API_KEY|GOOGLE_API_KEY)"
            r"\s*=\s*(.+)",
            value,
        )
        if assignment:
            value = assignment.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'`":
            value = value[1:-1].strip()
        return value

    @staticmethod
    def _validate_format(api_key: str) -> str:
        value = GeminiKeyManager._normalize_pasted_key(api_key)
        if not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", value):
            raise ValueError(
                "Gemini API key không đúng định dạng. Hãy sao chép đầy đủ key "
                "từ Google AI Studio, không dùng chuỗi đã che hoặc có ký tự lạ."
            )
        return value

    @staticmethod
    def _validation_error(exc: Exception) -> str:
        payload = getattr(exc, "response_json", {})
        error = payload.get("error", payload) if isinstance(payload, dict) else {}
        reasons = {
            detail.get("reason")
            for detail in error.get("details", [])
            if isinstance(detail, dict)
        }
        code = getattr(exc, "code", None)
        if "API_KEY_INVALID" in reasons or code == 401:
            return (
                "Google không chấp nhận key này. Hãy sao chép lại toàn bộ key "
                "trong Google AI Studio; nếu vẫn lỗi, tạo key mới. Key cũ vẫn được giữ."
            )
        if code == 403:
            return (
                "Google từ chối quyền sử dụng key. Kiểm tra quyền và giới hạn "
                "Gemini API của project trong Google AI Studio. Key cũ vẫn được giữ."
            )
        if code == 429:
            return (
                "Project của key đã hết hạn mức Gemini. Chờ hạn mức được cấp lại "
                "hoặc dùng key của project khác. Key cũ vẫn được giữ."
            )
        if code == 404:
            return (
                "Model cân đang cấu hình không khả dụng với key này. "
                "Kiểm tra ROLL_SCALE_GEMINI_MODEL. Key cũ vẫn được giữ."
            )
        if code == 400:
            return (
                "Google từ chối yêu cầu kiểm tra key. Kiểm tra key và model cân "
                "trong Google AI Studio. Key cũ vẫn được giữ."
            )
        return (
            "Chưa kiểm tra được key với Google. Kiểm tra kết nối mạng và thử lại. "
            "Key cũ vẫn được giữ."
        )

    def validate(self, api_key: str) -> None:
        value = self._validate_format(api_key)
        try:
            from google import genai
            from google.genai import types
            from .gemini_transport import prefer_httpx_transport
        except ImportError as exc:
            raise RuntimeError("Thiếu google-genai trên backend") from exc
        prefer_httpx_transport()
        client = genai.Client(
            api_key=value,
            http_options=types.HttpOptions(
                timeout=10000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            # Check the inference endpoint and the configured capture model.
            # Metadata access to a different model does not prove that this
            # key can run capture, especially for service-account auth keys.
            client.models.generate_content(
                model=self.fast_model,
                contents="Reply OK.",
                config=types.GenerateContentConfig(
                    max_output_tokens=8,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=True,
                    ),
                ),
            )
        except Exception as exc:
            raise ValueError(self._validation_error(exc)) from exc
        finally:
            client.close()

    def replace(
        self,
        api_key: str,
    ) -> tuple[
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
    ]:
        value = self._validate_format(api_key)
        self.validate(value)
        readers = self.create_readers(value)
        try:
            self.store.write(
                {"api_key": value, "provider": "gemini", "active_slot": "primary"}
            )
        except Exception:
            for reader in readers:
                reader.close()
            raise
        with self._lock:
            self._source = "supabase-encrypted"
            self._key_id = self.key_id(value)
            self._primary_key_id = self._key_id
            self._active_slot = "primary"
            self._last_error = ""
        return readers

    def save_backup(self, api_key: str) -> str:
        if self.backup_store is None or not self.backup_store.configured:
            raise ValueError("Kho Gemini key dự phòng chưa được cấu hình")
        with self._lock:
            if self._active_slot == "backup":
                raise ValueError("Hãy chuyển về key chính trước khi thay key dự phòng")
        value = self._validate_format(api_key)
        self.validate(value)
        primary, _, _ = self._primary_key()
        if value == primary:
            raise ValueError("Gemini key dự phòng phải khác key chính")
        self.backup_store.write({"api_key": value, "provider": "gemini-backup"})
        key_id = self.key_id(value)
        with self._lock:
            self._backup_configured = True
            self._backup_key_id = key_id
            self._last_error = ""
        return key_id

    def replace_shift_key(
        self,
        slot: str,
        api_key: str,
    ) -> tuple[
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
    ]:
        """Replace one assignment while preserving both other keys."""
        if slot not in {"day", "night"}:
            raise ValueError("Khe Gemini key phải là day hoặc night")
        value = self._validate_format(api_key)
        self.validate(value)
        with self._lock:
            _, keys = self._read_shift_keys()
            if any(value == key for other, key in keys.items() if other != slot):
                raise ValueError("Key ca ngày, ca đêm và key phụ phải khác nhau")
            readers = self.create_readers(value)
            keys[slot] = value
            try:
                self._write_shift_keys(keys)
            except Exception:
                for reader in readers:
                    reader.close()
                raise
        return readers

    def save_spare(self, api_key: str) -> str:
        value = self._validate_format(api_key)
        self.validate(value)
        with self._lock:
            _, keys = self._read_shift_keys()
            if value in (keys["day"], keys["night"]):
                raise ValueError("Key phụ phải khác Key ca ngày và Key ca đêm")
            keys["spare"] = value
            self._write_shift_keys(keys)
        return self.key_id(value)

    def swap_spare(self, slot: str, *, swap_id: str, expected_revision: str) -> tuple:
        if slot not in {"day", "night"}:
            raise ValueError("Khe Gemini key phải là day hoặc night")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", swap_id) or not expected_revision:
            raise ValueError("Thiếu mã yêu cầu đổi key. Tải lại trang rồi thử lại.")
        with self._lock:
            saved, keys = self._read_shift_keys()
            # Retrying after a lost HTTP response must not swap the keys back.
            if saved.get("last_swap_id") == swap_id:
                if saved.get("last_swap_slot") != slot:
                    raise ValueError("Mã yêu cầu đổi key đã dùng cho ca khác")
                readers = self.create_readers(keys[slot])
                self._adopt_shift_keys(saved, keys)
                return readers
            if self._revision(saved, keys) != expected_revision:
                raise ValueError("Cấu hình key đã thay đổi. Tải lại trang rồi thử lại.")
            if not keys["spare"] or not keys[slot]:
                raise ValueError("Hãy cấu hình key phụ và key của ca trước khi đổi")
            if keys["spare"] == keys[slot]:
                raise ValueError("Key phụ đang trùng key của ca")
            keys[slot], keys["spare"] = keys["spare"], keys[slot]
            # Build locally without calling the stalled Google endpoint again.
            readers = self.create_readers(keys[slot])
            try:
                self._write_shift_keys(keys, swap_id=swap_id, slot=slot)
            except Exception:
                for reader in readers:
                    reader.close()
                raise
            return readers

    def activate(
        self,
        slot: str,
    ) -> tuple[
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
        GeminiWeightReader,
    ]:
        if slot not in {"primary", "backup"}:
            raise ValueError("Khe Gemini key phải là primary hoặc backup")
        primary, primary_source, _ = self._primary_key()
        if slot == "backup":
            value = self._backup_key()
            source = "supabase-encrypted-backup"
            if not value:
                raise ValueError("Chưa lưu Gemini key dự phòng")
        else:
            value, source = primary, primary_source
            if not value:
                raise ValueError("Chưa cấu hình Gemini key chính")
        self.validate(value)
        readers = self.create_readers(value)
        try:
            self.store.write(
                {"api_key": primary, "provider": "gemini", "active_slot": slot}
            )
        except Exception:
            for reader in readers:
                reader.close()
            raise
        with self._lock:
            self._source = source
            self._key_id = self.key_id(value)
            if slot == "primary":
                self._primary_key_id = self._key_id
            else:
                self._backup_configured = True
                self._backup_key_id = self._key_id
            self._active_slot = slot
            self._last_error = ""
        return readers

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "change_enabled": self.store.configured,
                "backup_change_enabled": self.store.configured,
                "spare_change_enabled": self.store.configured,
                "switch_enabled": self.store.configured and bool(self._spare_key_id),
                "spare_configured": bool(self._spare_key_id),
                "spare_key_id": self._spare_key_id or None,
                "key_revision": self._key_revision or None,
                "source": self._source,
                "key_id": self._key_id or None,
                "primary_key_id": self._primary_key_id or None,
                "backup_key_id": self._backup_key_id or None,
                "backup_configured": self._backup_configured,
                "active_slot": self._active_slot,
                "routing": "12C1=day,12C2=night",
                "day_key_id": self._primary_key_id or None,
                "night_key_id": self._backup_key_id or None,
                "day_configured": bool(self._primary_key_id),
                "night_configured": self._backup_configured,
                "stored_encrypted": self._source.startswith("supabase-encrypted"),
                "last_error": self._last_error or None,
                "message": self.store.config_error if not self.store.configured else "Sẵn sàng đổi Gemini API key",
            }
