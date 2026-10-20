"""Open a legacy station's DB/config/photos with the new frozen local app."""
import base64
from contextlib import closing
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import cv2

from roll_qr_scale.storage import MeasurementStore


def main():
    project = Path(__file__).resolve().parents[1]
    executable = project / "dist/TramCanQR/TramCanQR.exe"
    metadata = json.loads((project / "data/factory_scale_13_04_reference.json").read_text(encoding="utf-8"))
    sample = project / "data" / metadata["image"]
    frame = cv2.imread(str(sample))
    with tempfile.TemporaryDirectory(prefix="legacy upgrade ", dir=project / ".test-tmp") as temp:
        base = Path(temp)
        station = base / "TramCanQR"
        store = MeasurementStore(station / "data/measurements.db", station / "data/captures")
        for index, state in enumerate(("pending", "failed")):
            row = store.save(f"LEGACY-{index}", 0.67, "kg", frame, "gemini", needs_sync=True,
                             event_id=f"legacy-{index}", gateway_id="gateway-04", station_id="station-04", camera_id="camera-04")
            store.attach_product_image(row.event_id, frame)
            store.attach_product_weight(row.event_id, 13.04)
            store.connection.execute("UPDATE measurements SET sync_status=? WHERE event_id=?", (state, row.event_id))
            store.connection.commit()
        before = [tuple(row) for row in store.connection.execute("SELECT * FROM measurements ORDER BY id")]
        store.close()
        staging = station / "data/captures/.staging"
        staging.mkdir()
        (staging / "preserved-draft.jpg").write_bytes(sample.read_bytes())
        (staging / ".active-bindings.json").write_text("{}", encoding="utf-8")
        old_files = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (station / "data/captures").rglob("*") if path.is_file()}
        config = station / "config.env"
        config.write_bytes(
            b"ROLL_SCALE_STATION_COUNT=1\r\nROLL_SCALE_GATEWAY_ID=gateway-04\r\n"
            b"ROLL_SCALE_STATION_IDS=station-04\r\nROLL_SCALE_CAMERA_IDS=camera-04\r\nROLL_SCALE_PORT=8080\r\n"
            b"ROLL_SCALE_WEIGHT_ENGINE=gemini\r\nROLL_SCALE_GEMINI_API_KEY=test-private-key\r\n"
            b"ROLL_SCALE_DIGIT_MODEL=C:/missing-colleague-source/model/best.pt\r\n"
            b"ROLL_SCALE_API_URL=http://127.0.0.1:9/ingest-measurement\r\nROLL_SCALE_DEVICE_TOKEN=test-token\r\n"
            b"ROLL_SCALE_LOOKUP_URL=http://127.0.0.1:9/lookup-roll\r\nROLL_SCALE_LOOKUP_TOKEN=test-lookup\r\n"
            b"SUPABASE_KHO_URL=http://127.0.0.1:9\r\nSUPABASE_KHO_KEY=test-kho-key\r\n"
        )
        original_config = config.read_bytes()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {key: value for key, value in os.environ.items() if not key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_", "PYTHON"))}
        env.update({"LOCALAPPDATA": str(base), "ROLL_SCALE_PORT": str(port), "ROLL_SCALE_AUTO_SYNC": "0",
                    "ROLL_SCALE_OPEN_BROWSER": "0", "ROLL_SCALE_HEADLESS": "1", "YOLO_CONFIG_DIR": str(base / "ultralytics"),
                    "TEMP": str(base), "TMP": str(base)})
        process = subprocess.Popen([str(executable)], cwd=base, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        def request(path, payload=None):
            req = urllib.request.Request(f"http://127.0.0.1:{port}" + path,
                data=json.dumps(payload).encode() if payload is not None else None, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)

        try:
            deadline = time.monotonic() + 90
            status = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError((station / "logs/app.log").read_text(encoding="utf-8", errors="replace")[-5000:])
                try:
                    status = request("/api/status")
                    break
                except OSError:
                    time.sleep(0.5)
            assert status and status["app_version"] == "0.2.0-rc75" and status["weight_engine"] == "local-yolo"
            assert status["gateway_id"] == "gateway-04" and status["stations"][0]["station_id"] == "station-04"
            assert status["sync_enabled"] and status["sync_mode"] == "manual"
            assert config.read_bytes() == original_config
            with closing(sqlite3.connect(station / "data/measurements.db")) as database:
                assert database.execute("SELECT * FROM measurements ORDER BY id").fetchall() == before
            marker = json.loads((station / "backups/local-rc75.json").read_text(encoding="utf-8"))
            backup = Path(marker["directory"])
            assert (backup / "config.env").read_bytes() == original_config
            with closing(sqlite3.connect(backup / "measurements.db")) as database:
                assert database.execute("SELECT * FROM measurements ORDER BY id").fetchall() == before
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in old_files.items())
            print("PASS: frozen in-place startup; old pending/failed rows, both photos, staging, station04 and cloud config retained; DB/config backup verified", flush=True)
            result = request("/api/analyze", {"image": "data:image/jpeg;base64," + base64.b64encode(sample.read_bytes()).decode(), "unit": "kg", "roi": "auto"})
            assert result["weight_found"] and result["weight"] == metadata["expected_weight"], result
            assert result["qr_code"] == metadata["expected_qr_code"]
            assert result["recognition_provider"] == "local-yolo" and not result["gemini_used"]
            assert config.read_bytes() == original_config
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                       for path, digest in old_files.items() if path.suffix == ".jpg")
            with closing(sqlite3.connect(station / "data/measurements.db")) as database:
                assert database.execute("SELECT * FROM measurements ORDER BY id").fetchall() == before
            print("PASS: old gemini setting and missing external model overridden by bundled CPU YOLO; reads 13.04 kg + QR; no cloud writes", flush=True)
        finally:
            process.terminate()
            process.wait(timeout=20)


if __name__ == "__main__":
    main()
