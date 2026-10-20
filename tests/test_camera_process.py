"""Real subprocess/IPC regressions for failed Windows camera drivers."""
from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

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
    if config['source'] == 3:
        s.sendall(struct.pack('!IIIdd',4,6,72,time.monotonic()-4,time.time()-4) + bytes([21])*72)
        time.sleep(.3)
    if config['source'] in (4, 5):
        s.sendall(struct.pack('!IIIdd',4,6,72,time.monotonic(),time.time()) + bytes([21])*72)
        time.sleep(3.3 if config['source'] == 4 else 30)
    if config['source'] == 6:
        packet = struct.pack('!IIIdd',4,6,72,time.monotonic(),time.time()) + bytes([21])*72
        s.sendall(packet[:10]); time.sleep(.3)
        s.sendall(packet[10:50]); time.sleep(.3)
        s.sendall(packet[50:])
        time.sleep(.1)
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


@pytest.mark.parametrize("selected,source", [("00", 0), ("01", 1)])
def test_equivalent_usb_source_opens_but_generation_change_cancels(monkeypatch, selected, source):
    from roll_qr_scale import camera_process, live_camera

    monkeypatch.setattr(live_camera, "sys", SimpleNamespace(platform="win32"))
    camera = LiveCamera(selected, None, object())
    callbacks = []
    monkeypatch.setattr(camera_process, "IsolatedCapture", lambda *a, **kw: callbacks.append(kw["cancelled"]))
    camera._open(source)
    cancelled = callbacks[0]
    assert not cancelled()
    camera.select_source("2")
    camera.select_source(selected)
    assert cancelled(), "Switching away and back must cancel the old generation"


def test_stale_mailbox_frame_is_skipped_without_restarting_driver(worker):
    camera = IsolatedCapture(3, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3)
    try:
        ok, frame = camera.read()
        assert ok and np.all(frame == 73)
        assert camera._process.poll() is None
    finally:
        camera.release()


def test_fragmented_frame_keeps_framing_across_socket_poll_timeouts(worker):
    camera = IsolatedCapture(6, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3)
    try:
        ok, frame = camera.read()
        assert ok and np.all(frame == 21)
        assert camera._process.poll() is None
    finally:
        camera.release()


def test_slow_frame_recovers_on_same_process_instead_of_three_second_restart(worker):
    camera = IsolatedCapture(4, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3)
    try:
        assert camera.read()[0]
        ok, frame = camera.read()
        assert ok and np.all(frame == 73)
        assert camera._process.poll() is None
    finally:
        camera.release()


def test_source_switch_interrupts_read_after_worker_has_opened(worker):
    changed = threading.Event()
    camera = IsolatedCapture(5, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3,
                             cancelled=changed.is_set)
    try:
        assert camera.read()[0]
        threading.Timer(.1, changed.set).start()
        started = time.monotonic()
        assert camera.read() == (False, None)
        assert time.monotonic() - started < 1
        assert not camera.isOpened()
    finally:
        camera.release()


def test_hung_reader_has_bounded_watchdog_and_releases_process(worker):
    camera = IsolatedCapture(5, "DSHOW", 6, 4, 30, command=worker, startup_timeout=3, frame_timeout=.4)
    try:
        assert camera.read()[0]
        started = time.monotonic()
        assert camera.read() == (False, None)
        assert time.monotonic() - started < 1.5
    finally:
        camera.release()
    assert camera._process.poll() is not None


@pytest.fixture
def faulty_opencv_worker(tmp_path, monkeypatch):
    """Run the production worker against an intermittently failing driver."""
    monkeypatch.setenv("ROLL_SCALE_CAMERA_LOG_DIR", str(tmp_path))
    path = tmp_path / "faulty_opencv.py"
    path.write_text('''
import sys, time, types
import numpy as np
class Capture:
    def __init__(self, source, *args):
        self.source, self.calls = source, 0
    def isOpened(self): return True
    def set(self, *args): pass
    def release(self): pass
    def read(self):
        self.calls += 1
        if self.calls <= 3 or (self.calls > 4 and (self.source == 1 or self.calls % 3 != 1)):
            return False, None
        time.sleep(.15)
        return True, np.full((4,6,3), self.calls, dtype=np.uint8)
sys.modules['cv2'] = types.SimpleNamespace(VideoCapture=Capture,
    CAP_PROP_FRAME_WIDTH=1, CAP_PROP_FRAME_HEIGHT=2, CAP_PROP_FPS=3, CAP_PROP_BUFFERSIZE=4)
from roll_qr_scale.camera_worker import main
raise SystemExit(main())
''', encoding="utf-8")
    return [sys.executable, str(path)]


def test_real_worker_survives_transient_driver_read_failures(faulty_opencv_worker):
    camera = IsolatedCapture(0, "AUTO", 6, 4, 30, command=faulty_opencv_worker, startup_timeout=5)
    try:
        ok, first = camera.read()
        assert ok
        ok, second = camera.read()
        assert ok and second[0, 0, 0] > first[0, 0, 0]
        assert camera._process.poll() is None
    finally:
        camera.release()


def test_real_worker_exits_when_driver_keeps_failing(faulty_opencv_worker):
    camera = IsolatedCapture(1, "AUTO", 6, 4, 30, command=faulty_opencv_worker, startup_timeout=5)
    try:
        assert camera.read()[0]
        assert camera.read() == (False, None)
        camera._process.wait(timeout=3)
        assert camera._process.returncode == 2
    finally:
        camera.release()


@pytest.mark.parametrize("entry", ["windows_app", "windows_auto_app"])
def test_desktop_worker_entry_never_imports_station_or_model(tmp_path, monkeypatch, entry):
    monkeypatch.setenv("ROLL_SCALE_CAMERA_LOG_DIR", str(tmp_path))
    path = tmp_path / "test.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (120, 80))
    assert writer.isOpened()
    for _ in range(120):
        writer.write(np.full((80, 120, 3), 94, dtype=np.uint8))
    writer.release()
    code = f'''
import importlib.abc, runpy, sys
class NoStation(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname in ('roll_qr_scale.test_ui', 'torch', 'ultralytics'):
            raise RuntimeError('Camera worker imported station/model: ' + fullname)
sys.meta_path.insert(0, NoStation())
runpy.run_module('roll_qr_scale.{entry}', run_name='__main__')
'''
    camera = IsolatedCapture(str(path), "AUTO", 120, 80, 30,
                             command=[sys.executable, "-c", code, "--camera-worker"], startup_timeout=10)
    try:
        ok, frame = camera.read()
        assert ok and frame.shape == (80, 120, 3)
    finally:
        camera.release()
