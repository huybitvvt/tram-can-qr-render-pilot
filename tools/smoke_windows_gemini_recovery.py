"""Run the frozen Gemini EXE against existing data and a loopback SDK stub."""
import base64
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2

from roll_qr_scale.storage import MeasurementStore


def main():
    project = Path(__file__).resolve().parents[1]
    calls = []

    class GeminiStub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.headers.get("x-goog-api-key") == "recovery-test-key"
            calls.append(request)
            reading = {"weight_readable": True, "weight_digits": "13.04",
                       "qr_readable": False, "qr_code": None,
                       "all_frames_agree": True, "display_blank": False}
            result = {"candidates": [{"content": {"role": "model", "parts": [{"text": json.dumps(reading)}]},
                                      "finishReason": "STOP"}],
                      "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 30, "totalTokenCount": 130}}
            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    stub = ThreadingHTTPServer(("127.0.0.1", 0), GeminiStub)
    stub_thread = threading.Thread(target=stub.serve_forever, daemon=True)
    stub_thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gemini-recovery-", dir=project / ".test-tmp") as temp:
            sandbox = Path(temp)
            local = sandbox / "TramCanQR"
            data = local / "data"
            data.mkdir(parents=True)
            with socket.socket() as port_socket:
                port_socket.bind(("127.0.0.1", 0))
                port = port_socket.getsockname()[1]
            config = local / "config.env"
            config.write_text("\n".join([
                "ROLL_SCALE_STATION_COUNT=1", "ROLL_SCALE_GATEWAY_ID=gateway-02",
                "ROLL_SCALE_STATION_IDS=station-02", "ROLL_SCALE_CAMERA_IDS=camera-02",
                "ROLL_SCALE_WEIGHT_ENGINE=local-yolo", "ROLL_SCALE_GEMINI_API_KEY=recovery-test-key",
                f"ROLL_SCALE_PORT={port}", "ROLL_SCALE_OPEN_BROWSER=0", "ROLL_SCALE_AUTO_SYNC=0",
            ]) + "\n", encoding="utf-8")
            config_before = config.read_bytes()
            frame = cv2.imread(str(project / "data/factory_scale_13_04_reference.jpg"))
            assert frame is not None
            store = MeasurementStore(data / "measurements.db", data / "captures")
            previous = store.save("RECOVERY-EXISTING", 7.09, "kg", frame, "manual")
            draft, _ = store.save_photo_draft_idempotent(frame, capture_kind="product",
                event_id=str(uuid.uuid4()), parent_event_id=str(uuid.uuid4()), station_id="station-02", camera_id="camera-02")
            store.close()
            previous_photo = Path(previous.image_path)
            old_photo_hash = hashlib.sha256(previous_photo.read_bytes()).hexdigest()
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_", "GOOGLE_", "GEMINI_"))}
            env.update(LOCALAPPDATA=str(sandbox), ROLL_SCALE_OPEN_BROWSER="0",
                       GOOGLE_GEMINI_BASE_URL=f"http://127.0.0.1:{stub.server_port}")
            executable = project / "dist/TramCanQR/TramCanQR.exe"
            process = subprocess.Popen([str(executable)], cwd=sandbox, env=env,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                def request(path, payload=None):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
                        data=json.dumps(payload).encode() if payload is not None else None,
                        headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=45) as response:
                        return json.load(response)

                deadline = time.monotonic() + 60
                status = None
                while time.monotonic() < deadline:
                    assert process.poll() is None, "Frozen app exited during startup"
                    try:
                        status = request("/api/status")
                        break
                    except OSError:
                        time.sleep(.2)
                assert status is not None and status["weight_engine"] == "gemini"
                assert status["gemini"]["enabled"] and not calls
                assert config.read_bytes() == config_before
                assert hashlib.sha256(previous_photo.read_bytes()).hexdigest() == old_photo_hash
                backups = list((local / "backups").glob("before-gemini-rc80-*"))
                assert len(backups) == 1
                with closing(sqlite3.connect(backups[0] / "measurements.db")) as connection:
                    assert connection.execute("SELECT weight FROM measurements").fetchall() == [(7.09,)]
                    assert connection.execute("SELECT COUNT(*) FROM photo_drafts").fetchone() == (1,)
                assert (backups[0] / "config.env").read_bytes() == config_before
                print("PASS frozen EXE: Gemini enabled with unchanged old config/key/station; existing DB/photo/draft preserved and backed up", flush=True)

                encoded, jpeg = cv2.imencode(".jpg", frame)
                assert encoded
                image = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
                event_id = str(uuid.uuid4())
                payload = {"image": image, "event_id": event_id, "station_id": "station-02",
                           "camera_id": "camera-02", "capture_kind": "core", "capture_round": 0,
                           "roi": "auto", "unit": "kg", "recognition_provider": "gemini",
                           "recognition_profile": "fast", "shift": "HC1"}
                result = request("/api/analyze", payload)
                assert calls and result["gemini_used"] and result["weight"] == 13.04, result.get("weight_raw")
                assert result["analysis_id"] and result["frame_sha256"]
                product = request("/api/analyze", {**payload, "capture_kind": "product"})
                assert product["gemini_used"] and product["weight"] == 13.04
                saved = request("/api/capture", {
                    "event_id": event_id, "station_id": "station-02", "camera_id": "camera-02",
                    "analysis_id": result["analysis_id"], "frame_sha256": result["frame_sha256"],
                    "qr_code": result["qr_code"], "weight": result["weight"], "product_weight": product["weight"],
                    "image": result.get("evidence_image") or image,
                    "product_image": product.get("evidence_image") or image, "unit": "kg",
                    "vision_confirmed": True, "weight_raw": result["weight_raw"],
                })
                assert saved["event_id"] == event_id
                with closing(sqlite3.connect(data / "measurements.db")) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM measurements").fetchone() == (2,)
                    assert connection.execute("SELECT weight FROM measurements WHERE id = ?", (previous.id,)).fetchone() == (7.09,)
                assert config.read_bytes() == config_before
                print("PASS frozen EXE: real Gemini SDK reaches loopback stub, reads core/product 13.04 and saves a new measurement alongside old data", flush=True)
            finally:
                process.terminate()
                process.wait(timeout=20)
    finally:
        stub.shutdown()
        stub_thread.join(5)
        stub.server_close()


if __name__ == "__main__":
    main()
