from __future__ import annotations

import pytest

from roll_qr_scale.gemini_key_manager import GeminiKeyManager
from roll_qr_scale.codex_oauth import EncryptedCodexTokenStore


class MemoryStore:
    configured = True
    config_error = ""

    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def read(self):
        if self.error:
            raise self.error
        return self.value

    def write(self, value):
        if self.error:
            raise self.error
        self.value = value


class FakeReader:
    def __init__(self, api_key, **kwargs):
        self.api_key = api_key
        self.kwargs = kwargs
        self.closed = False

    def close(self):
        self.closed = True


def manager(
    store,
    initial="environment-key-value",
    *,
    backup_store=None,
):
    return GeminiKeyManager(
        store,
        backup_store=backup_store,
        fast_model="fast-model",
        flash31_model="flash31-model",
        flash37_model="flash37-model",
        accurate_model="accurate-model",
        fast_timeout=10,
        flash31_timeout=15,
        flash37_timeout=30,
        accurate_timeout=30,
        initial_key=initial,
        reader_factory=FakeReader,
    )


def test_load_prefers_encrypted_supabase_key() -> None:
    current = manager(MemoryStore({"api_key": "stored-key-value-123456"}))
    assert current.load_key() == "stored-key-value-123456"
    assert current.status()["source"] == "supabase-encrypted"
    assert current.status()["key_id"] == current.key_id("stored-key-value-123456")


def test_load_falls_back_to_environment_when_supabase_is_temporarily_down() -> None:
    current = manager(MemoryStore(error=RuntimeError("network down")))
    assert current.load_key() == "environment-key-value"
    assert current.status()["source"] == "environment"
    assert "network down" in str(current.status()["last_error"])


def test_replace_validates_before_persisting_and_creates_all_readers(monkeypatch) -> None:
    store = MemoryStore()
    current = manager(store)
    monkeypatch.setattr(current, "validate", lambda key: None)
    fast, flash31, flash37, accurate = current.replace("new-key-value-123456789")
    assert store.value == {
        "api_key": "new-key-value-123456789",
        "provider": "gemini",
        "active_slot": "primary",
    }
    assert fast.kwargs["model"] == "fast-model"
    assert flash31.kwargs["model"] == "flash31-model"
    assert flash31.kwargs["timeout_seconds"] == 15
    assert flash37.kwargs["model"] == "flash37-model"
    assert flash37.kwargs["thinking_level"] == "low"
    assert accurate.kwargs["model"] == "accurate-model"
    assert current.status()["stored_encrypted"] is True
    assert current.status()["key_id"] == current.key_id("new-key-value-123456789")


def test_replace_keeps_new_readers_out_when_store_fails(monkeypatch) -> None:
    current = manager(MemoryStore(error=RuntimeError("write failed")))
    monkeypatch.setattr(current, "validate", lambda key: None)
    created = []

    def create(api_key, **kwargs):
        reader = FakeReader(api_key, **kwargs)
        created.append(reader)
        return reader

    current.reader_factory = create
    with pytest.raises(RuntimeError, match="write failed"):
        current.replace("new-key-value-123456789")
    assert len(created) == 4
    assert all(item.closed for item in created)


def test_save_backup_validates_and_persists_without_activating(monkeypatch) -> None:
    primary_store = MemoryStore(
        {"api_key": "primary-key-value-123456", "active_slot": "primary"}
    )
    backup_store = MemoryStore()
    current = manager(
        primary_store,
        backup_store=backup_store,
    )
    current.load_key()
    monkeypatch.setattr(current, "validate", lambda key: None)

    backup_id = current.save_backup("backup-key-value-1234567")

    assert backup_store.value == {
        "api_key": "backup-key-value-1234567",
        "provider": "gemini-backup",
    }
    assert primary_store.value == {
        "api_key": "primary-key-value-123456",
        "active_slot": "primary",
    }
    assert current.status()["active_slot"] == "primary"
    assert current.status()["backup_configured"] is True
    assert current.status()["backup_key_id"] == backup_id


def test_activate_backup_keeps_primary_and_persists_selection(monkeypatch) -> None:
    primary_store = MemoryStore(
        {"api_key": "primary-key-value-123456", "active_slot": "primary"}
    )
    backup_store = MemoryStore({"api_key": "backup-key-value-1234567"})
    current = manager(
        primary_store,
        backup_store=backup_store,
    )
    current.load_key()
    monkeypatch.setattr(current, "validate", lambda key: None)

    readers = current.activate("backup")

    assert all(reader.api_key == "backup-key-value-1234567" for reader in readers)
    assert primary_store.value == {
        "api_key": "primary-key-value-123456",
        "provider": "gemini",
        "active_slot": "backup",
    }
    assert current.status()["active_slot"] == "backup"
    assert current.status()["key_id"] == current.key_id("backup-key-value-1234567")

    primary_readers = current.activate("primary")

    assert all(reader.api_key == "primary-key-value-123456" for reader in primary_readers)
    assert primary_store.value["active_slot"] == "primary"
    assert current.status()["active_slot"] == "primary"


def test_load_restores_selected_backup_after_restart() -> None:
    current = manager(
        MemoryStore(
            {"api_key": "primary-key-value-123456", "active_slot": "backup"}
        ),
        backup_store=MemoryStore({"api_key": "backup-key-value-1234567"}),
    )

    assert current.load_key() == "backup-key-value-1234567"
    assert current.status()["active_slot"] == "backup"
    assert current.status()["source"] == "supabase-encrypted-backup"


def test_shift_keys_are_loaded_independently_and_report_safe_ids() -> None:
    current = manager(
        MemoryStore({"api_key": "day-key-value-123456789"}),
        backup_store=MemoryStore({"api_key": "night-key-value-1234567"}),
    )

    assert current.load_shift_keys() == {
        "day": "day-key-value-123456789",
        "night": "night-key-value-1234567",
    }
    status = current.status()
    assert status["active_slot"] == "automatic-by-shift"
    assert status["routing"] == "12C1=day,12C2=night"
    assert status["day_key_id"] == current.key_id("day-key-value-123456789")
    assert status["night_key_id"] == current.key_id("night-key-value-1234567")


def test_replace_night_shift_key_does_not_replace_day_key(monkeypatch) -> None:
    day_store = MemoryStore({"api_key": "day-key-value-123456789"})
    night_store = MemoryStore()
    current = manager(day_store, backup_store=night_store)
    monkeypatch.setattr(current, "validate", lambda key: None)

    readers = current.replace_shift_key("night", "night-key-value-1234567")

    assert all(reader.api_key == "night-key-value-1234567" for reader in readers)
    assert day_store.value == {"api_key": "day-key-value-123456789"}
    assert night_store.value == {
        "api_key": "night-key-value-1234567",
        "provider": "gemini-night",
    }


def test_gemini_store_uses_legacy_compatible_encrypted_secret_action() -> None:
    store = EncryptedCodexTokenStore(
        "https://example.invalid/ingest",
        "device-token",
        secret_name="gemini-api-key:gateway-01",
        secret_action="codex-auth",
    )
    assert store.secret_action == "codex-auth"
