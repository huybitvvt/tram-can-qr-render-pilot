"""Kill/fail camera subprocesses over real HTTP; require recovery and DB preservation."""
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import cv2

from roll_qr_scale import test_ui
from roll_qr_scale.camera_process import IsolatedCapture


def main():
    project = Path(__file__).resolve().parents[1]
    for key in list(os.environ):
        if key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_")):
            del os.environ[key]
    frame_path = project / "data/factory_scale_13_04_reference.jpg"
    with tempfile.TemporaryDirectory(prefix="camera-fault-", dir=project / ".test-tmp") as temp, patch.object(test_ui, "_load_local_dotenv"):
        root = Path(temp)
        os.environ["ROLL_SCALE_CAMERA_LOG_DIR"] = str(root)
        worker = root / "driver.py"
        worker.write_text('''
import cv2, json, os, socket, struct, sys, time
from pathlib import Path
def read(s,n):
    data=b''
    while len(data)<n: data+=s.recv(n-len(data))
    return data
with socket.create_connection(('127.0.0.1',int(sys.argv[-2]))) as s:
    s.sendall(sys.argv[-1].encode())
    config=json.loads(read(s,struct.unpack('!I',read(s,4))[0]))
    if config['source']==1:
        Path(__file__).with_suffix('.failed').write_text('native exit 86')
        os._exit(86)
    image=cv2.imread(sys.argv[1]); h,w=image.shape[:2]; data=image.tobytes()
    s.sendall(b'R')
    while True:
        s.sendall(struct.pack('!IIIdd',h,w,len(data),time.monotonic(),time.time())+data)
        time.sleep(.1)
''', encoding="utf-8")
        args = test_ui.build_parser().parse_args([
            "--port", "0", "--db", str(root / "test.db"), "--captures", str(root / "captures"),
            "--factory-samples", str(root / "samples"), "--weight-engine", "local-yolo",
            "--digit-model", str(project / "model/best.pt"), "--digit-confidence", ".2", "--digit-inference-confidence", ".35",
            "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
        ])
        server, service = test_ui.create_server(args)
        saved = service.store.save("KEEP-OLD-ROW", .67, "kg", cv2.imread(str(frame_path)), "gemini", needs_sync=True)
        original = hashlib.sha256(Path(saved.image_path).read_bytes()).hexdigest()
        camera = service.live_camera
        camera.detector = None
        opened = []
        def open_driver(source):
            result = IsolatedCapture(source, "DSHOW", 1920, 1080, 30,
                command=[os.sys.executable, str(worker), str(frame_path)], startup_timeout=10,
                cancelled=lambda: camera._stop.is_set() or str(source) != camera.source)
            opened.append(result)
            return result
        camera._open = open_driver
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def request(path, data=None):
            req = urllib.request.Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.load(response)
        def wait_snapshot():
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    result = request("/api/live/snapshot")
                    if result.get("image"): return result
                except urllib.error.HTTPError as error:
                    assert error.code == 503
                time.sleep(.1)
            raise AssertionError("Camera did not recover")
        try:
            request("/api/live/camera", {"source": "0"})
            first = wait_snapshot()
            request("/api/live/camera", {"source": "1"})
            assert camera.capture_snapshot() is None
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and not worker.with_suffix('.failed').exists():
                time.sleep(.1)
            assert worker.with_suffix('.failed').exists(), "Faulted source was not exercised"
            assert request("/api/health")["ok"] and request("/api/status")["weight_engine"] == "local-yolo"
            request("/api/live/camera", {"source": "0"})
            second = wait_snapshot()
            assert second["frame_id"] > first["frame_id"]
            entered, resume = threading.Event(), threading.Event()
            class SlowDetector:
                def detect_with_details(self, image):
                    entered.set()
                    resume.wait(10)
                    return None
            camera.detector = SlowDetector()
            assert entered.wait(5), "Blocked inference was not exercised"
            stable_pid = opened[-1]._process.pid
            try:
                frame_ids, health_times = set(), []
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    preview = request("/api/live/snapshot?preview=1")
                    frame_ids.add(preview["frame_id"])
                    started = time.monotonic()
                    assert request("/api/health")["ok"]
                    health_times.append(time.monotonic() - started)
                    time.sleep(.1)
                assert len(frame_ids) >= 5, "Preview froze behind inference"
                assert opened[-1]._process.pid == stable_pid, "Healthy driver restarted"
                full = request("/api/live/snapshot?capture=1")
                import base64
                import numpy as np
                def image_shape(payload):
                    data = np.frombuffer(base64.b64decode(payload["image"].split(",", 1)[1]), dtype=np.uint8)
                    return cv2.imdecode(data, cv2.IMREAD_COLOR).shape
                assert max(image_shape(preview)[:2]) <= 960
                assert image_shape(full) == cv2.imread(str(frame_path)).shape
                print(f"PASS: blocked AI, {len(frame_ids)} distinct preview frames in 3s; "
                      f"health max {max(health_times)*1000:.0f}ms; same driver PID; capture keeps original dimensions", flush=True)
            finally:
                resume.set()
                camera.detector = None
            process = opened[-1]._process
            process.kill()
            process.wait(timeout=3)
            assert request("/api/health")["ok"]
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline and (not opened or opened[-1]._process.pid == process.pid):
                time.sleep(.1)
            assert opened[-1]._process.pid != process.pid
            wait_snapshot()
            assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 1
            assert hashlib.sha256(Path(saved.image_path).read_bytes()).hexdigest() == original
            print("PASS: source 1 exits natively, source 0 reconnects; killing active driver keeps HTTP alive and auto-recovers; old row/photo unchanged")
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()
            service.close()
            service.store.close()


if __name__ == "__main__":
    main()
