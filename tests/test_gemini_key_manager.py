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
        "spare": "",
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
    assert day_store.value["shift_keys"] == {
        "day": "day-key-value-123456789", "night": "night-key-value-1234567", "spare": "",
    }
    assert night_store.value is None


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


@pytest.fixture
def key_ring(monkeypatch):
    store = MemoryStore({"api_key": "day-key-value-123456789"})
    night_store = MemoryStore({"api_key": "night-key-value-1234567"})
    current = manager(store, backup_store=night_store)
    monkeypatch.setattr(current, "validate", lambda key: None)
    current.load_shift_keys()
    current.save_spare("spare-key-value-1234567")
    return current, store, night_store


@pytest.mark.parametrize("slot", ["day", "night"])
def test_spare_swap_preserves_other_shift_and_survives_restart(key_ring, monkeypatch, slot):
    current, store, night_store = key_ring
    original = current.load_shift_keys()
    revision = current.status()["key_revision"]
    # Switching already configured keys must not contact Google again.
    monkeypatch.setattr(current, "validate", lambda key: pytest.fail("Google called during swap"))
    readers = current.swap_spare(slot, swap_id="request-swap-00000001", expected_revision=revision)
    other = "night" if slot == "day" else "day"
    assert all(reader.api_key == original["spare"] for reader in readers)
    expected = {slot: original["spare"], "spare": original[slot], other: original[other]}
    assert current.load_shift_keys() == expected
    assert manager(store, backup_store=night_store).load_shift_keys() == expected
    assert night_store.value == {"api_key": "night-key-value-1234567"}
    assert current.status()["key_revision"] != revision
    assert all(key not in str(current.status()) for key in expected.values())


def test_three_keys_rotate_across_both_shifts(key_ring):
    current, _, _ = key_ring
    original = current.load_shift_keys()
    for index, slot in enumerate(("day", "night", "day")):
        current.swap_spare(slot, swap_id=f"request-swap-{index:08d}",
                           expected_revision=current.status()["key_revision"])
    assert current.load_shift_keys() == {
        "day": original["night"], "night": original["day"], "spare": original["spare"],
    }


def test_repeated_swap_request_does_not_reverse_roles(key_ring):
    current, store, _ = key_ring
    revision = current.status()["key_revision"]
    current.swap_spare("night", swap_id="request-swap-00000001", expected_revision=revision)
    saved = dict(store.value)
    current.swap_spare("night", swap_id="request-swap-00000001", expected_revision=revision)
    assert store.value == saved
    with pytest.raises(ValueError, match="ca khác"):
        current.swap_spare("day", swap_id="request-swap-00000001", expected_revision=revision)
    with pytest.raises(ValueError, match="đã thay đổi"):
        current.swap_spare("day", swap_id="request-swap-00000002", expected_revision=revision)


def test_swap_retry_after_committed_write_loses_response(key_ring, monkeypatch):
    current, store, _ = key_ring
    revision = current.status()["key_revision"]
    original_write = store.write
    created = []
    current.reader_factory = lambda key, **kwargs: (created.append(FakeReader(key, **kwargs)) or created[-1])
    def ambiguous_write(value):
        original_write(value)
        raise TimeoutError("response lost")
    monkeypatch.setattr(store, "write", ambiguous_write)
    with pytest.raises(TimeoutError):
        current.swap_spare("day", swap_id="request-swap-00000001", expected_revision=revision)
    assert all(reader.closed for reader in created)
    # Retry reads the committed record; it does not write or call Google.
    readers = current.swap_spare("day", swap_id="request-swap-00000001", expected_revision=revision)
    assert all(reader.api_key == "spare-key-value-1234567" and not reader.closed for reader in readers)
    assert current.load_shift_keys()["spare"] == "day-key-value-123456789"


def test_failed_swap_write_preserves_assignments_and_closes_clients(key_ring, monkeypatch):
    current, store, _ = key_ring
    before = dict(store.value)
    status = current.status()
    created = []
    current.reader_factory = lambda key, **kwargs: (created.append(FakeReader(key, **kwargs)) or created[-1])
    monkeypatch.setattr(store, "write", lambda value: (_ for _ in ()).throw(RuntimeError("store down")))
    with pytest.raises(RuntimeError, match="store down"):
        current.swap_spare("day", swap_id="request-swap-00000001", expected_revision=status["key_revision"])
    assert store.value == before
    assert current.status() == status
    assert len(created) == 4 and all(reader.closed for reader in created)


@pytest.mark.parametrize("slot", ["day", "night", "spare"])
def test_saving_one_assignment_keeps_other_two_and_rejects_duplicates(key_ring, slot):
    current, store, _ = key_ring
    original = current.load_shift_keys()
    save = current.save_spare if slot == "spare" else lambda value: current.replace_shift_key(slot, value)
    with pytest.raises(ValueError, match="khác"):
        save(original["day" if slot != "day" else "spare"])
    save("new-key-value-123456789")
    expected = dict(original, **{slot: "new-key-value-123456789"})
    assert store.value["shift_keys"] == expected


def test_legacy_store_read_failure_never_overwrites_night_key(monkeypatch):
    store = MemoryStore({"api_key": "day-key-value-123456789"})
    night = MemoryStore(error=RuntimeError("night store unreachable"))
    current = manager(store, backup_store=night)
    assert current.load_shift_keys()["day"] == "day-key-value-123456789"
    monkeypatch.setattr(current, "validate", lambda key: None)
    with pytest.raises(RuntimeError, match="unreachable"):
        current.save_spare("spare-key-value-1234567")
    assert store.value == {"api_key": "day-key-value-123456789"}


def test_service_hot_swap_keeps_inflight_client_and_ignores_its_late_failure(key_ring, tmp_path):
    from roll_qr_scale.storage import MeasurementStore
    from roll_qr_scale.test_ui import StationUIService

    current, _, _ = key_ring
    keys = current.load_shift_keys()
    day = current.create_readers(keys["day"])
    night = current.create_readers(keys["night"])
    store = MeasurementStore(tmp_path / "measurement.db", tmp_path / "captures")
    service = StationUIService(store, None, None, None, gemini_reader=day[0],
                              gemini_flash31_reader=day[1], gemini_flash37_reader=day[2],
                              gemini_accurate_reader=day[3], gemini_night_readers=night,
                              gemini_key_manager=current, weight_engine="gemini", auto_sync=False)
    try:
        service._mark_gemini_slot_failed("day", day[0])
        assert service._gemini_active_slot("day") == "night"
        result = service.switch_gemini_key("12C1", swap_id="request-swap-00000001",
                                           expected_revision=current.status()["key_revision"])
        assert result["key_id"] == current.key_id(keys["spare"])
        assert service._gemini_reader_for("fast", "day").api_key == keys["spare"]
        assert service._gemini_reader_for("fast", "night") is night[0]
        assert service._gemini_active_slot("day") == "day"
        assert all(not reader.closed for reader in day)
        service._mark_gemini_slot_failed("day", day[0])
        assert service._gemini_active_slot("day") == "day"
        assert "day" not in service._gemini_failed_slots
    finally:
        service.close()
        store.close()
    assert all(reader.closed for reader in (*day, *night))


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
    assert day_store.value["shift_keys"][slot] == "AQ.new-key-value-123456789"
    other = "night" if slot == "day" else "day"
    assert day_store.value["shift_keys"][other] == (old_night if slot == "day" else old_day)["api_key"]
    assert night_store.value == old_night
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
