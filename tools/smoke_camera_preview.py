"""Exercise browser preview/recovery with a blocked AI and isolated local data."""
import os
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

from roll_qr_scale import test_ui


def main():
    project = Path(__file__).resolve().parents[1]
    artifacts = project / ".test-tmp"
    available, entered, resume = threading.Event(), threading.Event(), threading.Event()
    available.set()

    class FakeCapture:
        def __init__(self):
            self.frame_id = 0
        def isOpened(self): return True
        def release(self): pass
        def read(self):
            time.sleep(.1)
            if not available.is_set(): return False, None
            self.frame_id += 1
            frame = np.full((1080, 1920, 3), 55 + self.frame_id % 100, dtype=np.uint8)
            cv2.putText(frame, f"FRAME {self.frame_id}", (100, 400), cv2.FONT_HERSHEY_SIMPLEX, 4, (255, 255, 255), 8)
            return True, frame

    class SlowDetector:
        def detect_with_details(self, _image):
            entered.set()
            resume.wait(60)
            return SimpleNamespace(digits=[], display=None)

    for key in list(os.environ):
        if key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_")):
            del os.environ[key]
    with tempfile.TemporaryDirectory(prefix="camera-preview-", dir=artifacts) as temp, patch.object(test_ui, "_load_local_dotenv"):
        root = Path(temp)
        args = test_ui.build_parser().parse_args([
            "--host", "127.0.0.1", "--port", "0", "--db", str(root / "test.db"),
            "--captures", str(root / "captures"), "--factory-samples", str(root / "samples"),
            "--weight-engine", "local-yolo", "--digit-model", str(project / "model/best.pt"),
            "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
        ])
        server, service = test_ui.create_server(args)
        camera = service.live_camera
        camera._open = lambda _: FakeCapture()
        camera.detector = SlowDetector()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors, frames = [], set()
                page.on("pageerror", lambda error: errors.append(str(error)))
                def record_frame(response):
                    if "/api/live/snapshot?preview=1" in response.url and response.status == 200:
                        frames.add(response.json()["frame_id"])
                page.on("response", record_frame)
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="domcontentloaded")
                page.wait_for_function("!!current() && !!appStatus", timeout=60000)
                page.locator("#openDefaultCamBtn").click()
                page.wait_for_function("current().backendMode && current().video.videoWidth === 960", timeout=30000)
                assert entered.wait(2)
                assert camera.snapshot() is None, "AI should still be blocked"
                frames.clear()
                page.wait_for_timeout(2000)
                assert len(frames) >= 5, f"Browser preview stalled: {frames}"
                print(f"PASS: real Edge browser opens and displays {len(frames)} distinct preview frames in 2s while AI is blocked", flush=True)
                generation = page.evaluate("current().streamGeneration")
                available.clear()
                page.wait_for_function("current().backendSnapshotFailed === true", timeout=10000)
                available.set()
                page.wait_for_function("current().backendSnapshotFailed === false", timeout=15000)
                assert page.evaluate("current().streamGeneration") == generation
                assert page.evaluate("current().video.videoWidth") == 960
                assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 0
                assert not errors, errors
                page.screenshot(path=str(artifacts / "rc77-camera-preview.png"), full_page=True)
                browser.close()
                print("PASS: browser automatically resumes after source failure; no page errors, no new measurement or cloud write", flush=True)
        finally:
            available.set()
            resume.set()
            server.shutdown()
            thread.join(5)
            server.server_close()
            service.close()
            service.store.close()


if __name__ == "__main__":
    main()
