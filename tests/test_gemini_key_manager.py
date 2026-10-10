from __future__ import annotations

from types import SimpleNamespace

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


@pytest.mark.parametrize(
    "pasted",
    [
        "AQ.test-key-value-123456789",
        '  "AQ.test-key-value-123456789"  ',
        "'AQ.test-key-value-123456789'",
        "`AQ.test-key-value-123456789`",
        'ROLL_SCALE_GEMINI_API_KEY="AQ.test-key-value-123456789"',
        "ROLL_SCALE_GEMINI_BACKUP_API_KEY = 'AQ.test-key-value-123456789'",
        'export GEMINI_API_KEY="AQ.test-key-value-123456789"',
        "GOOGLE_API_KEY=AQ.test-key-value-123456789",
        "AIza-test-key-value-123456789",
    ],
)
def test_pasted_key_preserves_full_auth_key_and_normalizes_wrappers(pasted) -> None:
    expected = (
        "AIza-test-key-value-123456789"
        if pasted.startswith("AIza")
        else "AQ.test-key-value-123456789"
    )
    assert GeminiKeyManager._validate_format(pasted) == expected
    assert GeminiKeyManager.key_id(pasted) == GeminiKeyManager.key_id(expected)


@pytest.mark.parametrize(
    "pasted",
    [
        "*" * 40,
        "•" * 40,
        "AQ.test-key value-123456789",
        "AQ.test-key\nvalue-123456789",
        "AQ.test-key\u200b-value-123456789",
        '"AQ.test-key-value-123456789',
        "SUPABASE_KHO_KEY=AQ.test-key-value-123456789",
        "AQ." + "a" * 254,
    ],
)
def test_masked_incomplete_or_corrupted_key_is_rejected_before_google(pasted) -> None:
    with pytest.raises(ValueError, match="đúng định dạng"):
        GeminiKeyManager._validate_format(pasted)


@pytest.fixture
def validation_client(monkeypatch):
    from google import genai

    def install(error=None):
        calls = []
        options = []

        def generate_content(**kwargs):
            calls.append(kwargs)
            if error is not None:
                raise error
            return SimpleNamespace(text="OK")

        client = SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
            closed=False,
        )
        client.close = lambda: setattr(client, "closed", True)

        def create(**kwargs):
            options.append(kwargs)
            return client

        monkeypatch.setattr(genai, "Client", create)
        return client, calls, options

    return install


def test_validation_calls_capture_model_with_supplied_auth_key(validation_client) -> None:
    client, calls, options = validation_client()
    current = manager(MemoryStore())
    current.validate('GEMINI_API_KEY="AQ.test-key-value-123456789"')

    assert options[0]["api_key"] == "AQ.test-key-value-123456789"
    assert options[0]["http_options"].timeout == 10000
    assert options[0]["http_options"].retry_options.attempts == 1
    assert calls[0]["model"] == "fast-model"
    assert calls[0]["config"].max_output_tokens == 8
    assert calls[0]["config"].automatic_function_calling.disable is True
    assert client.closed


@pytest.mark.parametrize("slot", ["day", "night"])
def test_normalized_key_is_persisted_and_activated_for_only_selected_shift(
    validation_client, slot,
) -> None:
    validation_client()
    old_day = {"api_key": "old-day-key-value-123456"}
    old_night = {"api_key": "old-night-key-value-123456"}
    day_store = MemoryStore(old_day)
    night_store = MemoryStore(old_night)
    current = manager(day_store, backup_store=night_store)
    current.load_shift_keys()

    readers = current.replace_shift_key(
        slot, 'ROLL_SCALE_GEMINI_API_KEY="AQ.new-key-value-123456789"'
    )

    assert all(reader.api_key == "AQ.new-key-value-123456789" for reader in readers)
    selected = day_store if slot == "day" else night_store
    assert selected.value["api_key"] == "AQ.new-key-value-123456789"
    assert (night_store.value if slot == "day" else day_store.value) == (
        old_night if slot == "day" else old_day
    )
    assert current.status()[f"{slot}_key_id"] == current.key_id(
        "AQ.new-key-value-123456789"
    )


@pytest.mark.parametrize(
    ("code", "reason", "message"),
    [
        (400, "API_KEY_INVALID", "Google không chấp nhận key"),
        (401, "ACCESS_TOKEN_TYPE_UNSUPPORTED", "Google không chấp nhận key"),
        (403, "API_KEY_SERVICE_BLOCKED", "quyền sử dụng key"),
        (429, "", "hết hạn mức"),
        (404, "", "Model cân"),
        (400, "", "yêu cầu kiểm tra key"),
        (503, "", "kết nối mạng"),
        (None, "", "kết nối mạng"),
    ],
)
@pytest.mark.parametrize("slot", ["day", "night"])
def test_failed_google_validation_keeps_both_shift_keys_and_hides_raw_error(
    validation_client, code, reason, message, slot,
) -> None:
    attempted_key = "AQ.test-key-value-123456789"
    error = RuntimeError(f"Google rejected secret {attempted_key}")
    error.code = code
    error.response_json = {"error": {"details": [{"reason": reason}]}}
    client, _, _ = validation_client(error)
    day_store = MemoryStore({"api_key": "old-day-key-value-123456"})
    night_store = MemoryStore({"api_key": "old-night-key-value-123456"})
    current = manager(day_store, backup_store=night_store)
    current.load_shift_keys()
    previous_status = current.status()
    created = []
    current.reader_factory = lambda *args, **kwargs: created.append(args)

    with pytest.raises(ValueError, match=message) as caught:
        current.replace_shift_key(slot, attempted_key)

    assert attempted_key not in str(caught.value)
    assert "Key cũ vẫn được giữ" in str(caught.value)
    assert day_store.value == {"api_key": "old-day-key-value-123456"}
    assert night_store.value == {"api_key": "old-night-key-value-123456"}
    assert current.status() == previous_status
    assert created == []
    assert client.closed
