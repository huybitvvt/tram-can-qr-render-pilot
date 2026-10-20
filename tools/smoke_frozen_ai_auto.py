"""Run the frozen app outside the repo with temporary legacy/trial data."""
import base64
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def main():
    project = Path(__file__).resolve().parents[1]
    exe = project / "dist/TramCanQRAuto/TramCanQRAuto.exe"
    metadata = json.loads((project / "data/factory_scale_13_04_reference.json").read_text(encoding="utf-8"))
    image = (project / "data" / metadata["image"]).read_bytes()
    with tempfile.TemporaryDirectory(prefix="frozen-auto-", dir=project / ".test-tmp") as temp:
        root = Path(temp)
        legacy = root / "TramCanQR"
        legacy.mkdir()
        legacy_config = b"ROLL_SCALE_GATEWAY_ID=gateway-04\nROLL_SCALE_STATION_IDS=station-04\nROLL_SCALE_CAMERA_IDS=camera-04\nROLL_SCALE_PORT=8080\nROLL_SCALE_GEMINI_API_KEY=private-test-only\n"
        (legacy / "config.env").write_bytes(legacy_config)
        (legacy / "data").mkdir()
        (legacy / "data/measurements.db").write_bytes(b"legacy-db-must-not-change")
        env = {key: value for key, value in os.environ.items() if not key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_", "PYTHON"))}
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env.update({"LOCALAPPDATA": str(root), "ROLL_SCALE_PORT": str(port),
                    "ROLL_SCALE_OPEN_BROWSER": "0", "ROLL_SCALE_HEADLESS": "1",
                    "YOLO_CONFIG_DIR": str(root / "ultralytics"), "TEMP": str(root), "TMP": str(root)})
        process = subprocess.Popen([str(exe)], cwd=root, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        base = f"http://127.0.0.1:{port}"

        def request(path, payload=None):
            req = urllib.request.Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.load(response)

        try:
            deadline = time.monotonic() + 90
            status = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    log = root / "TramCanQRAuto/logs/app.log"
                    raise RuntimeError(log.read_text(encoding="utf-8", errors="replace")[-6000:] if log.exists() else f"Frozen app exited: {process.returncode}")
                try:
                    status = request("/api/status")
                    break
                except OSError:
                    time.sleep(0.5)
            assert status is not None, "Frozen app did not start"
            assert status["app_variant"] == "ai-auto" and status["weight_engine"] == "local-yolo"
            assert status["app_version"] == "0.2.0-ai-auto-beta1"
            assert status["gateway_id"] == "gateway-04" and status["stations"][0]["station_id"] == "station-04"
            assert status["digit_model_version"] == "model_2" and not status["sync_enabled"]
            print("Frozen startup and isolated station-04 config: PASS", flush=True)
            result = request("/api/analyze", {"image": "data:image/jpeg;base64," + base64.b64encode(image).decode(), "unit": "kg", "roi": "auto"})
            assert result["weight_found"] and result["weight"] == 13.04, result
            assert result["qr_code"] == metadata["expected_qr_code"]
            assert result["recognition_provider"] == "local-yolo" and not result["gemini_used"]
            assert (legacy / "config.env").read_bytes() == legacy_config
            assert (legacy / "data/measurements.db").read_bytes() == b"legacy-db-must-not-change"
            new_config = (root / "TramCanQRAuto/config.env").read_text()
            assert "private-test-only" not in new_config and "ROLL_SCALE_PORT=8081" in new_config
            model_path = Path(status["digit_model_path"])
            assert hashlib.sha256(model_path.read_bytes()).hexdigest() == "9ed72153375c0ddfd42e247dc0453c95c3c1061b4ab66f397384aa6bb7c8a8e8"
            print("PASS: frozen CPU YOLO + QR reads 13.04 kg; bundled model; legacy config/DB preserved; no cloud", flush=True)
        finally:
            process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
