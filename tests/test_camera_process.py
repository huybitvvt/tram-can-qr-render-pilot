"""Real subprocess/IPC regressions for failed Windows camera drivers."""
from __future__ import annotations

import subprocess
import sys
import time

import cv2
import numpy as np
import pytest

from roll_qr_scale.camera_process import IsolatedCapture
from roll_qr_scale.live_camera import LiveCamera


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLL_SCALE_CAMERA_LOG_DIR", str(tmp_path))
    path = tmp_path / "fake_driver.py"
    path.write_text('''
import json, os, socket, struct, sys, time
def read(s, size):
    data = b''
    while len(data) < size: data += s.recv(size-len(data))
    return data
with socket.create_connection(('127.0.0.1',int(sys.argv[-2]))) as s:
    s.sendall(sys.argv[-1].encode())
    config=json.loads(read(s,struct.unpack('!I',read(s,4))[0]))
    if config['source'] == 1:
        os._exit(86)
    if config['source'] == 2:
        time.sleep(30)
    s.sendall(b'R')
    while True:
        s.sendall(struct.pack('!IIIdd',4,6,72,time.monotonic(),time.time()) + bytes([73])*72)
        time.sleep(.04)
''', encoding="utf-8")
    return [sys.executable, str(path)]


def test_driver_process_can_die_and_another_source_still_opens(worker):
    with pytest.raises((EOFError, OSError)):
        IsolatedCapture(1, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3)
    camera = IsolatedCapture(0, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3)
    try:
        ok, frame = camera.read()
        assert ok and frame.shape == (4, 6, 3) and np.all(frame == 73)
        assert time.monotonic() - camera.captured_monotonic < 2
        camera._process.kill()
        camera._process.wait(3)
        deadline = time.monotonic() + 3
        while camera.isOpened() and time.monotonic() < deadline:
            time.sleep(.01)
        assert not camera.isOpened()
        assert camera.read() == (False, None)
    finally:
        camera.release()


def test_hung_driver_open_can_be_cancelled_without_waiting_20_seconds(worker):
    started = time.monotonic()
    with pytest.raises((OSError, TimeoutError)):
        IsolatedCapture(2, "DSHOW", 6, 4, 30, command=worker, startup_timeout=20,
                        cancelled=lambda: time.monotonic() - started > .6)
    assert time.monotonic() - started < 4


def test_camera_list_does_not_open_other_drivers(monkeypatch):
    camera = LiveCamera("0", None, object())
    monkeypatch.setattr(camera, "_open", lambda *_: pytest.fail("HTTP discovery must not open drivers"))
    assert [item["id"] for item in camera.cameras(maximum_index=3)] == ["configured", "0", "1", "2", "3"]


def test_real_opencv_worker_transports_full_frame_without_model_imports(tmp_path, monkeypatch):
    monkeypatch.setenv("ROLL_SCALE_CAMERA_LOG_DIR", str(tmp_path))
    path = tmp_path / "test.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (1280, 720))
    assert writer.isOpened()
    frame = np.full((720, 1280, 3), 94, dtype=np.uint8)
    for _ in range(90):
        writer.write(frame)
    writer.release()
    camera = IsolatedCapture(str(path), "AUTO", 1280, 720, 30, startup_timeout=10)
    try:
        ok, result = camera.read()
        assert ok and result.shape == frame.shape
        assert abs(float(result.mean()) - 94) < 2
    finally:
        camera.release()
    assert camera._process.poll() is not None
