from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import math
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .gemini_weight import GeminiWeightSuggestion


DEFAULT_ANTIGRAVITY_MODEL = "gemini-3.6-flash-low"
DEFAULT_ANTIGRAVITY_COMMAND = "agy"
DEFAULT_ANTIGRAVITY_TIMEOUT_SECONDS = 120.0
DEFAULT_ANTIGRAVITY_MAX_IMAGE_EDGE = 1280
DEFAULT_ANTIGRAVITY_JPEG_QUALITY = 86
DEFAULT_ANTIGRAVITY_ROTATE_IMAGE_TURNS = 20
DEFAULT_ANTIGRAVITY_QUOTA_TIMEOUT_SECONDS = 25.0
_ANTIGRAVITY_AGENT_NAME = "roll-scale-reader"
_FIXED_WEIGHT = re.compile(r"^(?:0|[1-9]\d{0,3})\.\d{2}$")

_ANTIGRAVITY_AGENT_DEFINITION = """---
name: roll-scale-reader
description: Đọc duy nhất chỉ số gross trên ảnh cân công nghiệp.
mainAgent: true
subagent: false
inheritCustomizations: false
excludeDefaultComponents: true
tools:
  - view_file
---

# Trình đọc cân

Chỉ dùng `view_file` với đúng đường dẫn ảnh được chỉ định. Đọc hàng gross đang
phát sáng trên màn hình cân; bỏ qua tare, net, QR, nhãn và mọi số khác. Cân luôn
có đúng hai chữ số thập phân: thấy 7.02 thì trả weight_digits là 702; thấy 13.04
thì trả 1304. Không đoán nét bị mất. Với ba ảnh, all_frames_agree chỉ đúng khi
cả ba cùng một số. Luôn trả JSON đúng schema; không giải thích và không gọi công
cụ khác.
"""

_ANTIGRAVITY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "weight_readable": {"type": "boolean"},
        "weight_digits": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "qr_readable": {"type": "boolean"},
        "qr_code": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "all_frames_agree": {"type": "boolean"},
    },
    "required": [
        "weight_readable",
        "weight_digits",
        "qr_readable",
        "qr_code",
        "all_frames_agree",
    ],
    "additionalProperties": False,
}


class AntigravityWeightReader:
    """Read a scale through Antigravity CLI or its optional Python SDK.

    The CLI path uses the Google-account session created by ``agy``. The SDK
    path is deliberately opt-in via ``ROLL_SCALE_ANTIGRAVITY_API_KEY`` so a
    Gemini key cannot be silently reused by a different provider.
    """

    def __init__(
        self,
        command: str = DEFAULT_ANTIGRAVITY_COMMAND,
        *,
        model: str = DEFAULT_ANTIGRAVITY_MODEL,
        timeout_seconds: float = DEFAULT_ANTIGRAVITY_TIMEOUT_SECONDS,
        api_key: str = "",
        max_image_edge: int = DEFAULT_ANTIGRAVITY_MAX_IMAGE_EDGE,
        jpeg_quality: int = DEFAULT_ANTIGRAVITY_JPEG_QUALITY,
        rotate_image_turns: int = DEFAULT_ANTIGRAVITY_ROTATE_IMAGE_TURNS,
        _allow_standby: bool = True,
    ) -> None:
        command = str(command or DEFAULT_ANTIGRAVITY_COMMAND).strip()
        model = str(model or DEFAULT_ANTIGRAVITY_MODEL).strip()
        if not command:
            raise ValueError("Antigravity command is required")
        if not model:
            raise ValueError("Antigravity model is required")
        if not 10.0 <= float(timeout_seconds) <= 180.0:
            raise ValueError("Antigravity timeout must be between 10 and 180 seconds")
        if not 512 <= int(max_image_edge) <= 2048:
            raise ValueError("Antigravity max image edge must be between 512 and 2048")
        if not 70 <= int(jpeg_quality) <= 95:
            raise ValueError("Antigravity JPEG quality must be between 70 and 95")
        if not 1 <= int(rotate_image_turns) <= 50:
            raise ValueError("Antigravity rotation must be between 1 and 50 image turns")
        self.command = command
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.api_key = str(api_key or os.environ.get("ROLL_SCALE_ANTIGRAVITY_API_KEY", "")).strip()
        self.max_image_edge = int(max_image_edge)
        self.jpeg_quality = int(jpeg_quality)
        self.rotate_image_turns = int(rotate_image_turns)
        self._lock = threading.Lock()
        self._requests = 0
        self._successes = 0
        self._failures = 0
        self._last_latency_seconds: float | None = None
        self._last_error: str | None = None
        self._status_cache: tuple[float, dict[str, object]] | None = None
        self._login_process: subprocess.Popen[bytes] | None = None
        self._authenticated: bool | None = None
        self._stream_lock = threading.Lock()
        self._stream_process: subprocess.Popen[str] | None = None
        self._stream_workspace: tempfile.TemporaryDirectory[str] | None = None
        self._stream_events: queue.Queue[str | None] | None = None
        self._stream_stderr: deque[str] = deque(maxlen=20)
        self._stream_turns = 0
        self._stream_session_turns = 0
        self._stream_usage_previous: dict[str, int] = {}
        self._stream_warmed = False
        self._allow_standby = bool(_allow_standby)
        self._rotation_lock = threading.Lock()
        self._rotation_closed = False
        self._standby_reader: AntigravityWeightReader | None = None
        self._standby_thread: threading.Thread | None = None
        self._standby_ready = False
        self._stream_rotations = 0
        self._quota_lock = threading.Lock()
        self._quota_cache: tuple[float, dict[str, object]] | None = None

    def _executable(self) -> str | None:
        candidate = Path(self.command).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        located = shutil.which(self.command)
        if located:
            return located
        if self.command == DEFAULT_ANTIGRAVITY_COMMAND and os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
            if local_app_data:
                for filename in ("agy.exe", "agy.cmd", "agy.bat"):
                    installed = Path(local_app_data) / "agy" / "bin" / filename
                    if installed.is_file():
                        return str(installed.resolve())
        return None

    def _sdk_model(self) -> str:
        return re.sub(r"-(?:low|medium|high|extra-high)$", "", self.model)

    @staticmethod
    def _command_for(executable: str, arguments: list[str]) -> list[str]:
        suffix = Path(executable).suffix.lower()
        if os.name == "nt" and suffix in {".cmd", ".bat"}:
            return [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/d",
                "/s",
                "/c",
                executable,
                *arguments,
            ]
        if os.name == "nt" and suffix == ".ps1":
            return [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                executable,
                *arguments,
            ]
        return [executable, *arguments]

    @staticmethod
    def _sample_frames(frames: list[np.ndarray]) -> list[np.ndarray]:
        usable = [frame for frame in frames if isinstance(frame, np.ndarray) and frame.size]
        if len(usable) == 1:
            return usable
        if len(usable) < 3:
            return []
        if len(usable) == 3:
            return usable
        middle = len(usable) // 2
        return [usable[0], usable[middle], usable[-1]]

    def _jpeg(self, image: np.ndarray) -> bytes:
        if image.ndim == 2:
            prepared = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        elif image.ndim == 3 and image.shape[2] >= 3:
            prepared = image[:, :, :3]
        else:
            raise ValueError("Antigravity camera image is invalid")
        height, width = prepared.shape[:2]
        longest = max(height, width)
        if longest > self.max_image_edge:
            scale = self.max_image_edge / longest
            prepared = cv2.resize(
                prepared,
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation=cv2.INTER_AREA,
            )
        ok, encoded = cv2.imencode(
            ".jpg", prepared, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
        )
        if not ok:
            raise ValueError("Cannot encode Antigravity image")
        return encoded.tobytes()

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return f"{type(exc).__name__}: {str(exc).strip()}"[:300]

    def _run(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]:
        executable = self._executable()
        if executable is None:
            raise FileNotFoundError("Không tìm thấy Antigravity CLI (`agy`) trên máy backend")
        return subprocess.run(
            self._command_for(executable, arguments),
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    @staticmethod
    def _json_from_output(output: str) -> dict[str, Any]:
        cleaned = str(output or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
        try:
            payload = json.loads(cleaned)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        # CLI JSON mode can include a short diagnostic line before its object.
        for line in reversed(cleaned.splitlines()):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("Antigravity không trả JSON hợp lệ")

    @staticmethod
    def _prompt() -> str:
        return "Đọc ảnh của lượt hiện tại bằng view_file và trả JSON đúng schema."

    @staticmethod
    def _with_usage(
        suggestion: GeminiWeightSuggestion,
        usage: object,
    ) -> GeminiWeightSuggestion:
        details = usage if isinstance(usage, dict) else {}
        input_tokens = int(details.get("input_tokens") or 0)
        output_tokens = int(details.get("output_tokens") or 0)
        thinking_tokens = int(details.get("thinking_tokens") or 0)
        total_tokens = int(details.get("total_tokens") or 0)
        return GeminiWeightSuggestion(
            suggestion.value,
            suggestion.unit,
            suggestion.readable,
            suggestion.all_frames_agree,
            f"{suggestion.raw}; tokens={input_tokens}+{output_tokens}+{thinking_tokens}",
            suggestion.latency_seconds,
            qr_code=suggestion.qr_code,
            qr_readable=suggestion.qr_readable,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _pipe_stdout(
        process: subprocess.Popen[str],
        events: queue.Queue[str | None],
    ) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    events.put(line)
        finally:
            events.put(None)

    def _pipe_stderr(self, process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            cleaned = line.strip()
            if cleaned:
                self._stream_stderr.append(cleaned)

    def _stop_stream_locked(self, *, graceful: bool) -> None:
        process = self._stream_process
        workspace = self._stream_workspace
        self._stream_process = None
        self._stream_workspace = None
        self._stream_events = None
        self._stream_usage_previous = {}
        self._stream_session_turns = 0
        self._stream_warmed = False
        if process is not None and process.poll() is None:
            try:
                if graceful and process.stdin is not None:
                    process.stdin.close()
                    process.wait(timeout=3.0)
                else:
                    process.terminate()
                    process.wait(timeout=3.0)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass
        if workspace is not None:
            workspace.cleanup()

    def _start_stream_locked(
        self,
    ) -> tuple[
        subprocess.Popen[str],
        Path,
        queue.Queue[str | None],
    ]:
        current = self._stream_process
        workspace = self._stream_workspace
        events = self._stream_events
        if (
            current is not None
            and current.poll() is None
            and workspace is not None
            and events is not None
        ):
            return current, Path(workspace.name), events
        self._stop_stream_locked(graceful=False)
        executable = self._executable()
        if executable is None:
            raise FileNotFoundError("Không tìm thấy Antigravity CLI (`agy`) trên máy backend")
        workspace = tempfile.TemporaryDirectory(prefix="roll-scale-antigravity-stream-")
        workspace_path = Path(workspace.name)
        schema_path = workspace_path / "response-schema.json"
        schema_path.write_text(
            json.dumps(_ANTIGRAVITY_RESPONSE_SCHEMA, ensure_ascii=False),
            encoding="utf-8",
        )
        agent_path = (
            workspace_path
            / ".agents"
            / "agents"
            / _ANTIGRAVITY_AGENT_NAME
            / "agent.md"
        )
        agent_path.parent.mkdir(parents=True, exist_ok=True)
        agent_path.write_text(_ANTIGRAVITY_AGENT_DEFINITION, encoding="utf-8")
        arguments = [
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--agent",
            _ANTIGRAVITY_AGENT_NAME,
            "--json-schema",
            str(schema_path),
            "--new-project",
            "--disable-slash-commands",
            "--effort",
            "low",
            "--print-timeout",
            f"{max(10, round(self.timeout_seconds))}s",
            "--sandbox",
        ]
        if self.model:
            arguments.extend(("--model", self.model))
        process = subprocess.Popen(
            self._command_for(executable, arguments),
            cwd=str(workspace_path),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        events = queue.Queue()
        self._stream_process = process
        self._stream_workspace = workspace
        self._stream_events = events
        self._stream_stderr.clear()
        threading.Thread(
            target=self._pipe_stdout,
            args=(process, events),
            name="antigravity-stdout",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._pipe_stderr,
            args=(process,),
            name="antigravity-stderr",
            daemon=True,
        ).start()
        return process, workspace_path, events

    def _turn_usage(self, cumulative: object) -> dict[str, int]:
        details = cumulative if isinstance(cumulative, dict) else {}
        keys = ("input_tokens", "output_tokens", "thinking_tokens", "total_tokens")
        current = {key: int(details.get(key) or 0) for key in keys}
        delta = {
            key: (
                current[key] - self._stream_usage_previous.get(key, 0)
                if current[key] >= self._stream_usage_previous.get(key, 0)
                else current[key]
            )
            for key in keys
        }
        self._stream_usage_previous = current
        return delta

    def _stream_turn_locked(
        self,
        prompt: str,
        frames: list[np.ndarray],
    ) -> dict[str, Any]:
        process, workspace, events = self._start_stream_locked()
        self._stream_turns += 1
        self._stream_session_turns += 1
        image_paths: list[Path] = []
        try:
            for index, frame in enumerate(frames, start=1):
                path = workspace / f"scale-turn-{self._stream_turns:06d}-{index}.jpg"
                path.write_bytes(self._jpeg(frame))
                image_paths.append(path)
            if image_paths:
                names = ", ".join(str(path.resolve()) for path in image_paths)
                prompt = (
                    f"{prompt} Đường dẫn chính xác: {names}. "
                    "Bỏ qua toàn bộ ảnh và kết quả của các lượt trước."
                )
            message = {"event": "user", "message": {"content": prompt}}
            if process.stdin is None:
                raise RuntimeError("Antigravity stream không có stdin")
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Antigravity stream quá thời gian chờ")
                try:
                    line = events.get(timeout=remaining)
                except queue.Empty as exc:
                    raise TimeoutError("Antigravity stream quá thời gian chờ") from exc
                if line is None:
                    detail = " | ".join(self._stream_stderr) or "Antigravity stream đã dừng"
                    raise RuntimeError(detail[-500:])
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("event") != "result":
                    continue
                envelope = event.get("result")
                if not isinstance(envelope, dict):
                    raise RuntimeError("Antigravity stream không trả result hợp lệ")
                envelope = dict(envelope)
                envelope["usage"] = self._turn_usage(envelope.get("usage"))
                return envelope
        except Exception:
            self._stop_stream_locked(graceful=False)
            raise
        finally:
            for path in image_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _warm_stream(self) -> None:
        with self._stream_lock:
            if self._stream_warmed and self._stream_process is not None:
                if self._stream_process.poll() is None:
                    return
            envelope = self._stream_turn_locked(
                "Lượt khởi động, không dùng bất kỳ công cụ nào. Trả JSON với "
                "weight_readable=false, weight_digits=null, qr_readable=false, "
                "qr_code=null và all_frames_agree=false.",
                [],
            )
            if str(envelope.get("status") or "").upper() != "SUCCESS":
                raise RuntimeError(str(envelope.get("error") or "Antigravity warm-up failed"))
            self._stream_warmed = True

    def _new_standby_reader(self) -> AntigravityWeightReader:
        return AntigravityWeightReader(
            self.command,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
            api_key=self.api_key,
            max_image_edge=self.max_image_edge,
            jpeg_quality=self.jpeg_quality,
            rotate_image_turns=self.rotate_image_turns,
            _allow_standby=False,
        )

    def _ensure_standby_warming(self) -> None:
        """Prepare a clean conversation without adding cold-start to a capture."""

        if (
            not self._allow_standby
            or self.api_key
            or self._authenticated is not True
            or self._executable() is None
        ):
            return
        with self._rotation_lock:
            if self._rotation_closed or self._standby_reader is not None:
                return
            standby = self._new_standby_reader()
            self._standby_reader = standby
            self._standby_ready = False

            def warm() -> None:
                ready = False
                try:
                    standby._warm_stream()
                    ready = True
                except Exception:
                    standby.close()
                with self._rotation_lock:
                    if self._standby_reader is standby and not self._rotation_closed:
                        if ready:
                            self._standby_ready = True
                        else:
                            self._standby_reader = None
                            self._standby_ready = False
                    self._standby_thread = None

            thread = threading.Thread(
                target=warm,
                name="antigravity-standby-warm",
                daemon=True,
            )
            self._standby_thread = thread
            thread.start()

    def _rotation_due(self) -> bool:
        image_turns = max(
            0,
            self._stream_session_turns - (1 if self._stream_warmed else 0),
        )
        active = self._stream_process
        active_stopped = active is None or active.poll() is not None
        return image_turns >= self.rotate_image_turns or active_stopped

    def _take_ready_standby(self) -> AntigravityWeightReader | None:
        if not self._rotation_due():
            return None
        with self._rotation_lock:
            if not self._standby_ready or self._standby_reader is None:
                return None
            standby = self._standby_reader
            self._standby_reader = None
            self._standby_ready = False
            return standby

    def _adopt_standby_stream(self, standby: AntigravityWeightReader) -> None:
        with self._stream_lock, standby._stream_lock:
            self._stop_stream_locked(graceful=False)
            self._stream_process = standby._stream_process
            self._stream_workspace = standby._stream_workspace
            self._stream_events = standby._stream_events
            self._stream_stderr = standby._stream_stderr
            self._stream_session_turns = standby._stream_session_turns
            self._stream_usage_previous = dict(standby._stream_usage_previous)
            self._stream_warmed = standby._stream_warmed
            standby._stream_process = None
            standby._stream_workspace = None
            standby._stream_events = None
            standby._stream_usage_previous = {}
            standby._stream_warmed = False
        self._stream_rotations += 1

    def _read_from_warmed_standby(
        self,
        sampled: list[np.ndarray],
        unit: str,
    ) -> GeminiWeightSuggestion | None:
        """Validate a clean conversation before replacing the proven one."""

        standby = self._take_ready_standby()
        if standby is None:
            return None
        try:
            suggestion = standby._read_cli(sampled, unit)
            if suggestion.value is None:
                standby.close()
                return None
            self._adopt_standby_stream(standby)
            return suggestion
        except Exception:
            standby.close()
            return None

    def _read_cli(self, sampled: list[np.ndarray], unit: str) -> GeminiWeightSuggestion:
        rotated = self._read_from_warmed_standby(sampled, unit)
        if rotated is not None:
            self._ensure_standby_warming()
            return rotated
        try:
            with self._stream_lock:
                envelope = self._stream_turn_locked(self._prompt(), sampled)
                self._stream_warmed = True
        finally:
            # Start only after the foreground turn, so warming cannot compete
            # with the operator's current image request.
            self._ensure_standby_warming()
        if str(envelope.get("status") or "").upper() != "SUCCESS":
            raise RuntimeError(str(envelope.get("error") or "Antigravity CLI failed"))
        payload = envelope.get("structured_output")
        if not isinstance(payload, dict):
            if envelope.get("denied_actions"):
                raise RuntimeError("Antigravity không được phép mở ảnh trong workspace tạm")
            payload = self._json_from_output(str(envelope.get("response") or ""))
        return self._with_usage(
            self._suggestion(payload, unit, "CLI-STREAM", len(sampled)),
            envelope.get("usage"),
        )

    async def _read_sdk_async(
        self,
        sampled: list[np.ndarray],
    ) -> tuple[dict[str, Any], Any]:
        from google.antigravity import Agent, Image, LocalAgentConfig

        config = LocalAgentConfig(
            model=self._sdk_model(),
            api_key=self.api_key,
            response_schema=_ANTIGRAVITY_RESPONSE_SCHEMA,
        )
        async with Agent(config) as agent:
            contents: list[object] = [self._prompt()]
            contents.extend(
                Image(
                    data=self._jpeg(frame),
                    mime_type="image/jpeg",
                    description="Ảnh màn hình cân công nghiệp",
                )
                for frame in sampled
            )
            response = await agent.chat(contents)
            payload = await response.structured_output()
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump()
            if not isinstance(payload, dict):
                raise ValueError("Antigravity SDK không trả structured output")
            return payload, response.usage_metadata

    def _read_sdk(self, sampled: list[np.ndarray], unit: str) -> GeminiWeightSuggestion:
        payload, usage = asyncio.run(self._read_sdk_async(sampled))
        suggestion = self._suggestion(payload, unit, "SDK", len(sampled))
        return self._with_usage(
            suggestion,
            {
                "input_tokens": getattr(usage, "prompt_token_count", 0),
                "output_tokens": getattr(usage, "candidates_token_count", 0),
                "thinking_tokens": getattr(usage, "thoughts_token_count", 0),
                "total_tokens": getattr(usage, "total_token_count", 0),
            },
        )

    def _suggestion(
        self,
        payload: dict[str, Any],
        unit: str,
        backend: str,
        sample_count: int,
    ) -> GeminiWeightSuggestion:
        digits = str(payload.get("weight_digits") or "").strip()
        reading = f"{digits[:-2]}.{digits[-2:]}" if digits.isdigit() and 3 <= len(digits) <= 6 else ""
        agreement = sample_count == 1 or bool(payload.get("all_frames_agree"))
        valid = bool(payload.get("weight_readable")) and agreement and _FIXED_WEIGHT.fullmatch(reading) is not None
        value = float(reading) if valid else None
        if value is not None and (not math.isfinite(value) or value < 0):
            value = None
            valid = False
        qr_code = str(payload.get("qr_code") or "").strip()
        qr_valid = bool(payload.get("qr_readable")) and bool(qr_code) and len(qr_code) <= 512
        if not qr_valid:
            qr_code = ""
        return GeminiWeightSuggestion(
            value,
            unit,
            valid,
            agreement,
            f"ANTIGRAVITY {backend}:{reading if valid else 'weight-unreadable'}@{self.model}; "
            f"qr={'readable' if qr_valid else 'unreadable'}; agree={agreement}",
            0.0,
            qr_code=qr_code or None,
            qr_readable=qr_valid,
        )

    def status(self, *, refresh: bool = False) -> dict[str, object]:
        with self._lock:
            if not refresh and self._status_cache and time.monotonic() - self._status_cache[0] < 5.0:
                return dict(self._status_cache[1])
        executable = self._executable()
        try:
            import google.antigravity  # noqa: F401

            sdk_installed = True
        except Exception:
            sdk_installed = False
        cli_installed = executable is not None
        if self.api_key and sdk_installed:
            authenticated = True
            available = True
            auth_method = "api_key"
            message = "Antigravity SDK sẵn sàng bằng API key riêng"
        elif cli_installed:
            authenticated = self._authenticated
            available = authenticated is True
            auth_method = "google_account_cli"
            message = (
                "Antigravity đã đăng nhập bằng tài khoản Google"
                if authenticated
                else "Đã thấy Antigravity CLI; bấm Đăng nhập rồi Kiểm tra"
            )
        else:
            authenticated = False
            available = False
            auth_method = None
            message = (
                "Chưa cài Antigravity CLI (`agy`) và chưa có ROLL_SCALE_ANTIGRAVITY_API_KEY"
            )
        result: dict[str, object] = {
            "enabled": True,
            "installed": bool(cli_installed or sdk_installed),
            "cli_installed": cli_installed,
            "sdk_installed": sdk_installed,
            "authenticated": authenticated,
            "available": available,
            "auth_method": auth_method,
            "model": self.model,
            "message": message,
            "persistent_process": bool(
                self._stream_process is not None
                and self._stream_process.poll() is None
            ),
            "stream_warmed": self._stream_warmed,
            "stream_turns": self._stream_turns,
            "stream_image_turns": max(
                0,
                self._stream_session_turns - (1 if self._stream_warmed else 0),
            ),
            "rotate_image_turns": self.rotate_image_turns,
            "stream_rotations": self._stream_rotations,
            "standby_warmed": self._standby_ready,
        }
        with self._lock:
            result.update(
                {
                    "requests": self._requests,
                    "successes": self._successes,
                    "failures": self._failures,
                    "last_latency_seconds": self._last_latency_seconds,
                    "last_error": self._last_error,
                }
            )
            self._status_cache = (time.monotonic(), dict(result))
        return result

    @staticmethod
    def _quota_reset_seconds(value: object) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0, round((parsed - datetime.now(timezone.utc)).total_seconds()))
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _normalize_quota(cls, payload: object) -> dict[str, object]:
        envelope = payload if isinstance(payload, dict) else {}
        command = envelope.get("command")
        command = command if isinstance(command, dict) else {}
        data = command.get("data")
        data = data if isinstance(data, dict) else {}
        groups = data.get("groups")
        groups = groups if isinstance(groups, list) else []
        normalized_groups: list[dict[str, object]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            buckets = group.get("buckets")
            buckets = buckets if isinstance(buckets, list) else []
            normalized_buckets: list[dict[str, object]] = []
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                try:
                    remaining = min(1.0, max(0.0, float(bucket.get("remaining_fraction"))))
                except (TypeError, ValueError):
                    continue
                reset_time = str(bucket.get("reset_time") or "").strip() or None
                normalized_buckets.append(
                    {
                        "id": str(bucket.get("id") or ""),
                        "name": str(bucket.get("name") or ""),
                        "window": str(bucket.get("window") or ""),
                        "remaining_fraction": remaining,
                        "remaining_percent": round(remaining * 100, 1),
                        "reset_time": reset_time,
                        "reset_in_seconds": cls._quota_reset_seconds(reset_time),
                    }
                )
            if normalized_buckets:
                normalized_groups.append(
                    {
                        "id": (
                            "gemini"
                            if "gemini" in str(group.get("name") or "").lower()
                            else "third_party"
                        ),
                        "name": str(group.get("name") or ""),
                        "description": str(group.get("description") or ""),
                        "buckets": normalized_buckets,
                    }
                )
        return {
            "ok": str(envelope.get("status") or "").upper() == "SUCCESS",
            "source": "antigravity-cli",
            "approximate": False,
            "fetched_at": time.time(),
            "groups": normalized_groups,
            "message": str(envelope.get("error") or "").strip(),
        }

    def quota_status(self, *, refresh: bool = False) -> dict[str, object]:
        """Read the account/model quota without starting an agent turn.

        Antigravity exposes the same 5-hour and weekly values shown in its
        Models & Usage panel through the read-only ``/usage`` slash command.
        Keep this separate from ``status()`` because a refresh can take a few
        seconds and must never delay the capture status endpoint.
        """

        with self._quota_lock:
            if (
                not refresh
                and self._quota_cache is not None
                and time.time() - self._quota_cache[0] < 60
            ):
                return dict(self._quota_cache[1])
        # ``/usage`` is read-only and also doubles as a lightweight auth
        # probe.  Do not require ``check_login()`` first: a gateway restart
        # loses the in-memory flag while the agy Google session remains
        # persisted on disk.
        if self.api_key or self._executable() is None:
            result = {
                "ok": False,
                "source": "antigravity-cli",
                "approximate": False,
                "fetched_at": time.time(),
                "groups": [],
                "message": "Antigravity chưa đăng nhập bằng CLI; chưa lấy được quota 5 giờ/tuần",
            }
        else:
            try:
                completed = self._run(
                    [
                        "-p",
                        "/usage",
                        "--output-format",
                        "json",
                        "--print-timeout",
                        f"{round(DEFAULT_ANTIGRAVITY_QUOTA_TIMEOUT_SECONDS)}s",
                    ],
                    cwd=Path(tempfile.gettempdir()),
                    timeout=DEFAULT_ANTIGRAVITY_QUOTA_TIMEOUT_SECONDS,
                )
                result = self._normalize_quota(self._json_from_output(completed.stdout))
                if completed.returncode != 0:
                    result["ok"] = False
                    result["message"] = (
                        completed.stderr or completed.stdout or "Antigravity không trả quota"
                    ).strip()[-300:]
                elif result.get("ok"):
                    with self._lock:
                        self._authenticated = True
                        self._status_cache = None
            except Exception as exc:
                result = {
                    "ok": False,
                    "source": "antigravity-cli",
                    "approximate": False,
                    "fetched_at": time.time(),
                    "groups": [],
                    "message": self._safe_error(exc),
                }
        with self._quota_lock:
            self._quota_cache = (time.time(), dict(result))
        return result

    def start_login(self, *, force: bool = False) -> dict[str, object]:
        executable = self._executable()
        if executable is None:
            return {
                "started": False,
                "authenticated": False,
                "message": (
                    "Chưa tìm thấy `agy`. Cài Antigravity CLI rồi chạy `agy` một lần "
                    "trên máy backend để đăng nhập Google."
                ),
            }
        current = self.status(refresh=True)
        if not force and current.get("authenticated") is True:
            return {"started": False, "authenticated": True, "message": current.get("message")}
        with self._stream_lock:
            self._stop_stream_locked(graceful=True)
        with self._lock:
            if self._login_process is not None and self._login_process.poll() is None:
                return {
                    "started": False,
                    "authenticated": False,
                    "message": "Cửa sổ đăng nhập Antigravity đang mở",
                }
            creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) if os.name == "nt" else 0
            self._login_process = subprocess.Popen(
                self._command_for(executable, []),
                cwd=tempfile.gettempdir(),
                creationflags=creation_flags,
            )
            self._authenticated = False
            self._status_cache = None
        return {
            "started": True,
            "authenticated": False,
            "message": "Đã mở Antigravity CLI. Đăng nhập Google trong cửa sổ mới rồi bấm Kiểm tra.",
        }

    def check_login(self) -> dict[str, object]:
        if self.api_key:
            return {"ok": True, "authenticated": True, "message": "API key Antigravity đã được cấu hình"}
        executable = self._executable()
        if executable is None:
            return {
                "ok": False,
                "authenticated": False,
                "message": "Chưa cài Antigravity CLI (`agy`)",
            }
        try:
            completed = self._run(
                ["-p", "/model", "--print-timeout", "15s"],
                cwd=Path(tempfile.gettempdir()),
                timeout=min(20.0, self.timeout_seconds),
            )
            authenticated = completed.returncode == 0
            message = (
                "Antigravity đã đăng nhập và phản hồi được"
                if authenticated
                else (completed.stderr or completed.stdout or "Antigravity chưa đăng nhập").strip()[-300:]
            )
            with self._lock:
                self._authenticated = authenticated
                self._status_cache = None
            if authenticated:
                try:
                    self._warm_stream()
                    message = "Antigravity đã đăng nhập; agent đọc cân đã được làm nóng"
                except Exception as exc:
                    message = (
                        "Antigravity đã đăng nhập nhưng chưa làm nóng được agent: "
                        f"{self._safe_error(exc)}"
                    )
            return {"ok": authenticated, "authenticated": authenticated, "message": message}
        except Exception as exc:
            return {"ok": False, "authenticated": False, "message": self._safe_error(exc)}

    def read(self, frames: list[np.ndarray], *, unit: str = "kg") -> GeminiWeightSuggestion:
        sampled = self._sample_frames(frames)
        if len(sampled) not in {1, 3}:
            return GeminiWeightSuggestion(
                None,
                unit,
                False,
                False,
                "ANTIGRAVITY: cần 1 ảnh tĩnh hoặc 3 frame camera",
                0.0,
            )
        started = time.perf_counter()
        with self._lock:
            self._requests += 1
        try:
            if self._executable() is not None:
                suggestion = self._read_cli(sampled, unit)
            elif self.api_key:
                suggestion = self._read_sdk(sampled, unit)
            else:
                raise RuntimeError(
                    "Antigravity chưa đăng nhập. Bấm Đăng nhập Antigravity hoặc cấu hình "
                    "ROLL_SCALE_ANTIGRAVITY_API_KEY."
                )
            latency = time.perf_counter() - started
            suggestion = GeminiWeightSuggestion(
                suggestion.value,
                suggestion.unit,
                suggestion.readable,
                suggestion.all_frames_agree,
                suggestion.raw,
                latency,
                qr_code=suggestion.qr_code,
                qr_readable=suggestion.qr_readable,
                input_tokens=suggestion.input_tokens,
                output_tokens=suggestion.output_tokens,
                thinking_tokens=suggestion.thinking_tokens,
                total_tokens=suggestion.total_tokens,
            )
            with self._lock:
                self._last_latency_seconds = latency
                self._last_error = None
                if self._executable() is not None:
                    self._authenticated = True
                if suggestion.value is not None:
                    self._successes += 1
                else:
                    self._failures += 1
                self._status_cache = None
            return suggestion
        except Exception as exc:
            latency = time.perf_counter() - started
            error = self._safe_error(exc)
            with self._lock:
                self._failures += 1
                self._last_latency_seconds = latency
                self._last_error = error
                self._status_cache = None
            return GeminiWeightSuggestion(
                None,
                unit,
                False,
                False,
                f"ANTIGRAVITY ERROR: {error}",
                latency,
            )

    def close(self) -> None:
        with self._rotation_lock:
            self._rotation_closed = True
            standby = self._standby_reader
            standby_thread = self._standby_thread
            self._standby_reader = None
            self._standby_ready = False
        if standby is not None:
            process = standby._stream_process
            if process is not None and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            if (
                standby_thread is not None
                and standby_thread is not threading.current_thread()
                and standby_thread.is_alive()
            ):
                standby_thread.join(timeout=5.0)
            if standby_thread is None or not standby_thread.is_alive():
                standby.close()
        with self._stream_lock:
            self._stop_stream_locked(graceful=True)
        with self._lock:
            process = self._login_process
            self._login_process = None
        if process is not None and process.poll() is None:
            process.terminate()
