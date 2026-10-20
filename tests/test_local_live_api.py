import base64
import json
import threading
import urllib.error
import urllib.request

import cv2
import numpy as np

from roll_qr_scale import live_camera, test_ui


def test_live_routes_use_matching_snapshot_without_saving_or_reanalyzing(tmp_path, monkeypatch):
    class FakeCamera:
        def __init__(self, source, *_args, **_kwargs):
            self.source, self.ready, self.started = source, False, False

        def cameras(self, **_kwargs):
            return [{"id": "0", "label": "USB 0", "selected": True}]

        def select_source(self, source):
            self.source = source
            self.ready = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

        def snapshot(self):
            if not self.ready:
                return None
            return np.full((80, 120, 3), 70, dtype=np.uint8), {"raw_digits": "630", "numeric_value": 6.3, "confidence": 0.9, "timestamp": 1}, 42

        def capture_snapshot(self):
            if not self.ready:
                return None
            return np.full((80, 120, 3), 90, dtype=np.uint8), {"qr": None, "numeric_value": None, "status": "CAPTURED"}, 43

    monkeypatch.setattr(live_camera, "LiveCamera", FakeCamera)
    monkeypatch.setattr(test_ui, "LocalDigitDetector", lambda *_a, **_k: object())
    monkeypatch.setattr(test_ui, "LocalQrDecoder", lambda: object())
    model = tmp_path / "model.pt"
    model.write_bytes(b"test")
    args = test_ui.build_parser().parse_args([
        "--host", "127.0.0.1", "--port", "0", "--db", str(tmp_path / "test.db"),
        "--captures", str(tmp_path / "captures"), "--factory-samples", str(tmp_path / "samples"),
        "--weight-engine", "local-yolo", "--digit-model", str(model),
        "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
    ])
    server, service = test_ui.create_server(args)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    try:
        assert request("/api/live/cameras")[1]["cameras"][0]["id"] == "0"
        assert request("/api/live/snapshot")[0] == 503
        assert request("/api/live/camera", {"source": "configured"})[0] == 200
        assert service.live_camera.started
        assert request("/api/live/camera", {"source": "rtsp://untrusted.invalid/test"})[0] == 422
        service.live_camera.ready = True
        code, snapshot = request("/api/live/snapshot")
        assert code == 200 and snapshot["frame_id"] == 42
        jpeg = np.frombuffer(base64.b64decode(snapshot["image"].split(",", 1)[1]), dtype=np.uint8)
        assert cv2.imdecode(jpeg, cv2.IMREAD_COLOR).shape == (80, 120, 3)
        assert snapshot["recognition"]["numeric_value"] == 6.3
        assert "image" not in request("/api/live/recognition")[1]
        fresh = request("/api/live/snapshot?capture=1")[1]
        assert fresh["frame_id"] == 43 and fresh["recognition"]["qr"] is None
        assert fresh["recognition"]["numeric_value"] is None
        assert fresh["image"] != snapshot["image"]
        assert service.inference.status().submitted == 0
        assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 0
        assert request("/api/live/camera", {"source": "1"})[0] == 200
        assert request("/api/live/snapshot")[0] == 503
    finally:
        server.shutdown()
        thread.join(3)
        server.server_close()
        service.close()
        service.store.close()
