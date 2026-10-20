"""Keep Windows camera drivers outside the station/model process."""
from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)
FRAME_HEADER = struct.Struct("!IIIdd")
MAX_FRAME_BYTES = 64 * 1024 * 1024


def receive_exact(connection: socket.socket, size: int, *, cancelled=None, deadline=None) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        if cancelled is not None and cancelled():
            raise OSError("Camera source changed")
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("Camera startup timed out")
        try:
            part = connection.recv(size - len(chunks))
        except socket.timeout:
            if deadline is None:
                raise
            continue
        if not part:
            raise EOFError("Camera worker disconnected")
        chunks.extend(part)
    return bytes(chunks)


class IsolatedCapture:
    """VideoCapture-compatible reader with one bounded mailbox of lossless frames."""

    def __init__(self, source: int | str, backend: str | None, width: int, height: int,
                 fps: int, rtsp_transport: str = "tcp", *, command: list[str] | None = None,
                 startup_timeout: float = 20.0, cancelled=None) -> None:
        self._process: subprocess.Popen | None = None
        self._connection: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._released = False
        self._opened = False
        self._frames: queue.Queue = queue.Queue(maxsize=1)
        self.captured_monotonic = self.captured_timestamp = 0.0
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(0.2)
        deadline = time.monotonic() + startup_timeout
        token = secrets.token_hex(16)
        if command is None:
            command = ([sys.executable, "--camera-worker"] if getattr(sys, "frozen", False)
                       else [sys.executable, "-m", "roll_qr_scale.camera_worker"])
        log_dir = Path(os.environ.get("ROLL_SCALE_CAMERA_LOG_DIR", tempfile.gettempdir()))
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with (log_dir / "camera-driver.log").open("ab", buffering=0) as errors:
                self._process = subprocess.Popen(
                    [*command, str(server.getsockname()[1]), token], stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=errors,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            while True:
                if time.monotonic() >= deadline or (cancelled is not None and cancelled()):
                    raise TimeoutError("Camera startup cancelled/timed out")
                if self._process.poll() is not None:
                    raise OSError(f"Camera driver exited during startup (exit={self._process.returncode})")
                try:
                    connection, _ = server.accept()
                    break
                except socket.timeout:
                    continue
            self._connection = connection
            connection.settimeout(0.2)
            if not secrets.compare_digest(receive_exact(connection, len(token), cancelled=cancelled, deadline=deadline).decode("ascii"), token):
                raise RuntimeError("Camera worker authentication failed")
            config = json.dumps({"source": source, "backend": backend, "width": width,
                                 "height": height, "fps": fps, "rtsp_transport": rtsp_transport}).encode()
            connection.sendall(struct.pack("!I", len(config)) + config)
            if receive_exact(connection, 1, cancelled=cancelled, deadline=deadline) != b"R":
                raise OSError("Không mở được camera. Chọn lại camera USB hoặc kiểm tra camera-driver.log.")
            connection.settimeout(5.0)
            self._opened = True
            self._reader = threading.Thread(target=self._receive, name="camera-ipc", daemon=True)
            self._reader.start()
        except BaseException:
            self.release()
            raise
        finally:
            server.close()

    def _publish(self, frame) -> None:
        try:
            self._frames.put_nowait(frame)
        except queue.Full:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                pass

    def _receive(self) -> None:
        connection = self._connection
        try:
            while not self._released:
                height, width, size, captured, timestamp = FRAME_HEADER.unpack(
                    receive_exact(connection, FRAME_HEADER.size))
                if not (0 < size <= MAX_FRAME_BYTES and size == height * width * 3):
                    raise ValueError("Camera worker frame dimensions invalid")
                data = receive_exact(connection, size)
                frame = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
                self._publish((frame, captured, timestamp))
        except (OSError, EOFError, ValueError, struct.error):
            if not self._released:
                code = self._process.poll()
                logger.warning("Camera driver disconnected (exit=%s); station server remains running", code)
        finally:
            self._opened = False
            self._publish(None)

    def isOpened(self) -> bool:
        return self._opened and not self._released

    def read(self):
        try:
            result = self._frames.get(timeout=3.0)
        except queue.Empty:
            return False, None
        if result is None:
            return False, None
        frame, self.captured_monotonic, self.captured_timestamp = result
        if time.monotonic() - self.captured_monotonic > 2.0:
            return False, None
        return True, frame

    def release(self) -> None:
        self._released = True
        self._opened = False
        if self._connection is not None:
            try:
                self._connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._connection.close()
            self._connection = None
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=3)
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=1)
        self._publish(None)
