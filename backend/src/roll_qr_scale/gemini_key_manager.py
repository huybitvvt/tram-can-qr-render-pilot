from __future__ import annotations

import hashlib
import threading
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
        self.initial_key = initial_key.strip()
        self.reader_factory = reader_factory
        self._lock = threading.RLock()
        self._source = "environment" if self.initial_key else "none"
        self._key_id = self.key_id(self.initial_key) if self.initial_key else ""
        self._primary_key_id = self._key_id
        self._backup_key_id = ""
        self._backup_configured = False
        self._active_slot = "primary"
        self._last_error = ""

    @staticmethod
    def key_id(api_key: str) -> str:
        """Return a safe short identifier without exposing any part of the key."""
        value = api_key.strip()
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
        return self._saved_key(self.backup_store)

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
        """Load the two fixed shift keys without a process-wide active slot.

        The legacy primary/backup selector is retained for older clients, but
        production capture routes 12C1 to ``day`` and 12C2 to ``night`` on
        every request. This prevents one operator changing the key used by the
        other shift.
        """

        errors: list[str] = []
        try:
            day_key, day_source, _ = self._primary_key()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc).strip()}")
            day_key = self.initial_key
            day_source = "environment" if day_key else "none"
        try:
            night_key = self._backup_key()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {str(exc).strip()}")
            night_key = ""
        with self._lock:
            self._source = day_source
            self._key_id = self.key_id(day_key)
            self._primary_key_id = self._key_id
            self._backup_key_id = self.key_id(night_key)
            self._backup_configured = bool(night_key)
            self._active_slot = "automatic-by-shift"
            self._last_error = "; ".join(errors)[:300]
        return {"day": day_key, "night": night_key}

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
                    media_resolution="high",
                    include_qr=False,
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
                    media_resolution="high",
                    include_qr=False,
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
                    media_resolution="high",
                    include_qr=False,
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
                    media_resolution="high",
                    include_qr=False,
                )
            )
        except Exception:
            for reader in readers:
                reader.close()
            raise
        flash31, fast, flash37, accurate = readers
        return fast, flash31, flash37, accurate

    @staticmethod
    def _validate_format(api_key: str) -> str:
        value = api_key.strip()
        if not 20 <= len(value) <= 256 or any(character.isspace() for character in value):
            raise ValueError("Gemini API key không đúng định dạng")
        return value

    def validate(self, api_key: str) -> None:
        value = self._validate_format(api_key)
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("Thiếu google-genai trên backend") from exc
        client = genai.Client(
            api_key=value,
            http_options=types.HttpOptions(timeout=10000),
        )
        try:
            client.models.get(model=self.flash31_model)
        except Exception as exc:
            raise ValueError(f"Gemini từ chối key hoặc model: {str(exc)[:240]}") from exc
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
        """Validate, persist and build readers for one fixed shift slot."""

        if slot == "day":
            readers = self.replace(api_key)
            with self._lock:
                self._active_slot = "automatic-by-shift"
            return readers
        if slot != "night":
            raise ValueError("Khe Gemini key phải là day hoặc night")
        value = self._validate_format(api_key)
        self.validate(value)
        primary, _, _ = self._primary_key()
        if value == primary:
            raise ValueError("Key ca đêm phải khác Key ca ngày")
        if self.backup_store is None or not self.backup_store.configured:
            raise ValueError("Kho Key ca đêm chưa được cấu hình")
        readers = self.create_readers(value)
        try:
            self.backup_store.write({"api_key": value, "provider": "gemini-night"})
        except Exception:
            for reader in readers:
                reader.close()
            raise
        with self._lock:
            self._backup_configured = True
            self._backup_key_id = self.key_id(value)
            self._active_slot = "automatic-by-shift"
            self._last_error = ""
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
                "backup_change_enabled": bool(
                    self.backup_store is not None and self.backup_store.configured
                ),
                "switch_enabled": bool(
                    self.store.configured
                    and self.backup_store is not None
                    and self.backup_store.configured
                ),
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
