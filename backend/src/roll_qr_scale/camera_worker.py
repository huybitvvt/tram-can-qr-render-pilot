"""Minimal subprocess entry: no model, database, configuration or web imports."""
from __future__ import annotations

import faulthandler
import json
import os
import socket
import struct
import sys
import time
import traceback

FRAME_HEADER = struct.Struct("!IIIdd")
MAX_FRAME_BYTES = 64 * 1024 * 1024


def receive_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        part = connection.recv(size - len(data))
        if not part:
            raise EOFError("Station disconnected")
        data.extend(part)
    return bytes(data)


def main() -> int:
    # PyInstaller GUI executables set sys.stderr=None; use the inherited pipe/file.
    errors = None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        import msvcrt
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
        ctypes.windll.kernel32.GetStdHandle.restype = wintypes.HANDLE
        handle = ctypes.windll.kernel32.GetStdHandle(-12)
        if handle not in (None, 0, ctypes.c_void_p(-1).value):
            try:
                errors = os.fdopen(msvcrt.open_osfhandle(handle, os.O_WRONLY), "w", buffering=1)
            except OSError:
                pass
    if errors is None:
        errors = sys.stderr
    if errors is not None:
        faulthandler.enable(errors, all_threads=True)
    capture = None
    with socket.create_connection(("127.0.0.1", int(sys.argv[-2])), timeout=10) as connection:
        connection.sendall(sys.argv[-1].encode("ascii"))
        config = json.loads(receive_exact(connection, struct.unpack("!I", receive_exact(connection, 4))[0]))
        try:
            import cv2
            source = config["source"]
            is_rtsp = isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://"))
            if is_rtsp:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;" + config["rtsp_transport"]
            name = str(config["backend"] or "AUTO").upper()
            backend = None if is_rtsp or name in {"AUTO", "NONE"} else getattr(cv2, name if name.startswith("CAP_") else "CAP_" + name)
            capture = cv2.VideoCapture(source) if backend is None else cv2.VideoCapture(source, backend)
            if not capture.isOpened():
                connection.sendall(b"E")
                return 1
            for key, value in ((cv2.CAP_PROP_FRAME_WIDTH, config["width"]), (cv2.CAP_PROP_FRAME_HEIGHT, config["height"]),
                               (cv2.CAP_PROP_FPS, config["fps"]), (cv2.CAP_PROP_BUFFERSIZE, 1)):
                capture.set(key, value)
            last_sent = 0.0
            ready = False
            while True:
                ok, frame = capture.read()
                captured, timestamp = time.monotonic(), time.time()
                if not ok or frame is None:
                    return 2
                if not ready:
                    # USB devices may take several seconds to deliver their first frame.
                    # Keep the cancellable startup deadline until a real frame exists.
                    connection.sendall(b"R")
                    ready = True
                # Drain the driver continuously; transport at most ten current frames/sec.
                if captured - last_sent < 0.1:
                    continue
                height, width = frame.shape[:2]
                data = frame.tobytes()
                if not (0 < len(data) <= MAX_FRAME_BYTES and len(data) == height * width * 3):
                    raise ValueError("Unsupported camera frame size/format")
                connection.sendall(FRAME_HEADER.pack(height, width, len(data), captured, timestamp) + data)
                last_sent = captured
        except Exception:
            if errors is not None:
                traceback.print_exc(file=errors)
            try:
                connection.sendall(b"E")
            except OSError:
                pass
            return 1
        finally:
            if capture is not None:
                try:
                    capture.release()
                except Exception:
                    if errors is not None:
                        traceback.print_exc(file=errors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
