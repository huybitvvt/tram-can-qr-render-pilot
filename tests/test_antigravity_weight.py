import io
import json
from types import SimpleNamespace

import numpy as np
import pytest

import roll_qr_scale.antigravity_weight as antigravity_module
from roll_qr_scale.antigravity_weight import AntigravityWeightReader


def test_cli_reader_uses_isolated_project_and_parses_usage(monkeypatch) -> None:
    reader = AntigravityWeightReader(command="agy")
    assert reader.rotate_image_turns == 20
    monkeypatch.setattr(reader, "_executable", lambda: "agy")

    def fake_turn(prompt, frames):
        assert "view_file" in prompt
        assert "find_by_name" not in prompt
        assert len(frames) == 1
        return {
            "status": "SUCCESS",
            "structured_output": {
                "weight_readable": True,
                "weight_digits": "702",
                "qr_readable": False,
                "qr_code": None,
                "all_frames_agree": True,
            },
            "usage": {
                "input_tokens": 101,
                "output_tokens": 23,
                "thinking_tokens": 7,
                "total_tokens": 131,
            },
        }

    monkeypatch.setattr(reader, "_stream_turn_locked", fake_turn)
    result = reader.read([np.zeros((40, 80, 3), dtype=np.uint8)])

    assert result.value == pytest.approx(7.02)
    assert result.readable is True
    assert result.input_tokens == 101
    assert result.output_tokens == 23
    assert result.thinking_tokens == 7
    assert result.total_tokens == 131
    assert reader.status(refresh=True)["successes"] == 1


def test_cli_reader_fails_closed_when_image_permission_is_denied(monkeypatch) -> None:
    reader = AntigravityWeightReader(command="agy")
    monkeypatch.setattr(reader, "_executable", lambda: "agy")
    monkeypatch.setattr(
        reader,
        "_stream_turn_locked",
        lambda *args, **kwargs: {
            "status": "SUCCESS",
            "response": "",
            "denied_actions": [{"action": "command"}],
        },
    )

    result = reader.read([np.zeros((40, 80, 3), dtype=np.uint8)])

    assert result.value is None
    assert result.readable is False
    assert "không được phép mở ảnh" in result.raw


def test_login_check_uses_cached_google_account(monkeypatch) -> None:
    reader = AntigravityWeightReader(command="agy")
    monkeypatch.setattr(reader, "_executable", lambda: "agy")
    monkeypatch.setattr(
        reader,
        "_run",
        lambda arguments, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="gemini-3.6-flash-low",
            stderr="",
        ),
    )
    warmed = []
    monkeypatch.setattr(reader, "_warm_stream", lambda: warmed.append(True))

    result = reader.check_login()

    assert result["authenticated"] is True
    assert warmed == [True]
    assert reader.status(refresh=True)["available"] is True


def test_persistent_stream_uses_safe_headless_flags(monkeypatch) -> None:
    reader = AntigravityWeightReader(command="agy")
    monkeypatch.setattr(reader, "_executable", lambda: "agy")
    captured = {}

    class FakeProcess:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = []
            self.stderr = []
            self.running = True

        def poll(self):
            return None if self.running else 0

        def wait(self, timeout=None):
            self.running = False
            return 0

        def terminate(self):
            self.running = False

        def kill(self):
            self.running = False

    def fake_popen(arguments, **kwargs):
        captured["arguments"] = arguments
        captured["kwargs"] = kwargs
        agent_path = (
            antigravity_module.Path(kwargs["cwd"])
            / ".agents"
            / "agents"
            / "roll-scale-reader"
            / "agent.md"
        )
        captured["agent_definition"] = agent_path.read_text(encoding="utf-8")
        return FakeProcess()

    monkeypatch.setattr(antigravity_module.subprocess, "Popen", fake_popen)
    with reader._stream_lock:
        reader._start_stream_locked()
    reader.close()

    arguments = captured["arguments"]
    assert "--input-format" in arguments
    assert "stream-json" in arguments
    assert "--new-project" in arguments
    assert arguments[arguments.index("--agent") + 1] == "roll-scale-reader"
    assert arguments[arguments.index("--effort") + 1] == "low"
    assert "--sandbox" in arguments
    assert "--dangerously-skip-permissions" not in arguments
    assert "excludeDefaultComponents: true" in captured["agent_definition"]
    assert "  - view_file" in captured["agent_definition"]


def test_stream_usage_is_reported_per_turn_not_cumulative() -> None:
    reader = AntigravityWeightReader(command="agy")

    first = reader._turn_usage(
        {"input_tokens": 100, "output_tokens": 20, "thinking_tokens": 5, "total_tokens": 120}
    )
    second = reader._turn_usage(
        {"input_tokens": 130, "output_tokens": 27, "thinking_tokens": 7, "total_tokens": 157}
    )

    assert first == {
        "input_tokens": 100,
        "output_tokens": 20,
        "thinking_tokens": 5,
        "total_tokens": 120,
    }
    assert second == {
        "input_tokens": 30,
        "output_tokens": 7,
        "thinking_tokens": 2,
        "total_tokens": 37,
    }


def test_quota_status_parses_real_five_hour_and_weekly_buckets(monkeypatch) -> None:
    reader = AntigravityWeightReader(command="agy")
    monkeypatch.setattr(reader, "_executable", lambda: "agy")
    reader._authenticated = True
    monkeypatch.setattr(
        reader,
        "_run",
        lambda arguments, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "SUCCESS",
                    "command": {
                        "data": {
                            "groups": [
                                {
                                    "name": "Gemini Models",
                                    "buckets": [
                                        {
                                            "id": "gemini-weekly",
                                            "name": "Weekly Limit Remaining",
                                            "window": "weekly",
                                            "remaining_fraction": 0.93,
                                            "reset_time": "2099-01-01T00:00:00Z",
                                        },
                                        {
                                            "id": "gemini-5h",
                                            "name": "Five Hour Limit Remaining",
                                            "window": "5h",
                                            "remaining_fraction": 0.91,
                                            "reset_time": "2099-01-01T00:00:00Z",
                                        },
                                    ],
                                }
                            ]
                        }
                    },
                }
            ),
            stderr="",
        ),
    )

    result = reader.quota_status(refresh=True)

    assert result["ok"] is True
    assert result["approximate"] is False
    buckets = result["groups"][0]["buckets"]
    assert buckets[0]["window"] == "weekly"
    assert buckets[0]["remaining_percent"] == 93.0
    assert buckets[1]["window"] == "5h"
    assert buckets[1]["remaining_percent"] == 91.0


def test_warmed_standby_replaces_long_conversation_after_valid_read(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, name: str):
            self.name = name

        def poll(self):
            return None

    reader = AntigravityWeightReader(command="agy", rotate_image_turns=2)
    old_process = FakeProcess("old")
    reader._stream_process = old_process
    reader._stream_session_turns = 3  # one warm-up plus two image turns
    reader._stream_warmed = True

    standby = AntigravityWeightReader(command="agy", _allow_standby=False)
    fresh_process = FakeProcess("fresh")
    standby._stream_process = fresh_process
    standby._stream_workspace = SimpleNamespace(name="fresh-workspace")
    standby._stream_events = SimpleNamespace()
    standby._stream_session_turns = 1
    standby._stream_usage_previous = {"input_tokens": 100}
    standby._stream_warmed = True
    reader._standby_reader = standby
    reader._standby_ready = True

    stopped = []

    def fake_stop(*, graceful):
        stopped.append((reader._stream_process, graceful))
        reader._stream_process = None
        reader._stream_workspace = None
        reader._stream_events = None

    monkeypatch.setattr(reader, "_stop_stream_locked", fake_stop)
    expected = antigravity_module.GeminiWeightSuggestion(
        7.02,
        "kg",
        True,
        True,
        "standby",
        1.0,
    )
    monkeypatch.setattr(standby, "_read_cli", lambda frames, unit: expected)

    assert reader._read_from_warmed_standby([np.zeros((10, 10, 3))], "kg") is expected
    assert stopped == [(old_process, False)]
    assert reader._stream_process is fresh_process
    assert reader._stream_session_turns == 1
    assert reader._stream_warmed is True
    assert reader._stream_rotations == 1
    assert standby._stream_process is None


def test_unreadable_standby_does_not_replace_proven_conversation(monkeypatch) -> None:
    class FakeProcess:
        def poll(self):
            return None

    reader = AntigravityWeightReader(command="agy", rotate_image_turns=1)
    old_process = FakeProcess()
    reader._stream_process = old_process
    reader._stream_session_turns = 2
    reader._stream_warmed = True

    standby = AntigravityWeightReader(command="agy", _allow_standby=False)
    standby._stream_process = FakeProcess()
    standby._stream_warmed = True
    reader._standby_reader = standby
    reader._standby_ready = True
    monkeypatch.setattr(
        standby,
        "_read_cli",
        lambda frames, unit: antigravity_module.GeminiWeightSuggestion(
            None,
            unit,
            False,
            False,
            "unreadable",
            1.0,
        ),
    )
    monkeypatch.setattr(standby, "close", lambda: None)

    result = reader._read_from_warmed_standby([np.zeros((10, 10, 3))], "kg")

    assert result is None
    assert reader._stream_process is old_process
    assert reader._stream_rotations == 0
