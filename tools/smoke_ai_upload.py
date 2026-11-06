"""Exercise the file picker with real CPU YOLO, isolated data and a fake USB camera."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import cv2
from playwright.sync_api import sync_playwright

from roll_qr_scale import test_ui


def main():
    project = Path(__file__).resolve().parents[1]
    metadata = json.loads((project / "data/factory_scale_13_04_reference.json").read_text(encoding="utf-8"))
    sample = project / "data" / metadata["image"]
    frame = cv2.imread(str(sample))
    artifacts = project / ".test-tmp"
    artifacts.mkdir(exist_ok=True)

    class FakeCapture:
        def isOpened(self): return True
        def set(self, *_args): return True
        def release(self): pass
        def read(self):
            time.sleep(0.04)
            return True, frame.copy()

    for key in list(os.environ):
        if key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_")):
            del os.environ[key]
    os.environ["ROLL_SCALE_APP_VARIANT"] = "ai-auto"
    os.environ["ROLL_SCALE_APP_VERSION"] = "0.2.0-ai-auto-beta1"
    with tempfile.TemporaryDirectory(prefix="ai-upload-", dir=artifacts) as temp, patch.object(test_ui, "_load_local_dotenv"):
        root = Path(temp)
        args = test_ui.build_parser().parse_args([
            "--port", "0", "--db", str(root / "test.db"), "--captures", str(root / "captures"),
            "--factory-samples", str(root / "samples"), "--weight-engine", "local-yolo",
            "--digit-model", str(project / "model/best.pt"), "--digit-confidence", "0.2",
            "--digit-inference-confidence", "0.35", "--api-url=", "--api-token=",
            "--lookup-url=", "--lookup-token=", "--no-auto-sync",
        ])
        server, service = test_ui.create_server(args)
        service.live_camera._open = lambda _source: FakeCapture()
        service.live_camera.cameras = lambda **_kwargs: []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors, analysis_requests = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: analysis_requests.append(request.url)
                        if "/api/analyze" in request.url or "capture=1" in request.url else None)
                page.route("**/api/live/camera", lambda route: route.fulfill(
                    status=503, content_type="application/json", body='{"message":"Camera chưa kết nối"}'))
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="domcontentloaded")
                page.wait_for_function("!!current() && !!appStatus", timeout=60000)
                page.locator("#testImageBtn").wait_for(state="visible")
                page.evaluate("""qr => {
                    saveSourceContext({...sourceContext, shift:'HC1', machine:'Máy cách nhiệt', order:'LSX-UPLOAD-TEST', productCode:productCodeFromQr(qr)});
                    fillSourceFields(sourceContext); selectCaptureSlot('core',0);
                }""", metadata["expected_qr_code"])
                assert not page.evaluate("!!current().stream")
                page.locator("#testImageInput").set_input_files({
                    "name": "invalid.txt", "mimeType": "text/plain", "buffer": b"not an image"})
                page.wait_for_function("document.getElementById('captureStatus').textContent.includes('không phải ảnh')")
                assert not analysis_requests
                print("PASS: visible picker works without a camera; non-image rejected", flush=True)

                with page.expect_file_chooser() as chooser:
                    page.locator("#testImageBtn").click()
                chooser.value.set_files(sample)
                page.wait_for_function("ensureRounds(current())[0].coreAnalysis && !ensureRounds(current())[0].coreAiPending", timeout=90000)
                assert page.evaluate("Number(ensureRounds(current())[0].weight)") == metadata["expected_weight"]
                assert page.locator("#testImageInput").input_value() == ""
                assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 0
                print("PASS: uploaded core reads 13.04 kg using the local model, no automatic ticket", flush=True)

                page.unroute("**/api/live/camera")
                page.locator("#openDefaultCamBtn").click()
                page.wait_for_function("current().backendMode && current().video.videoWidth > 0", timeout=60000)
                page.evaluate("selectCaptureSlot('product',0)")
                page.locator("#testImageInput").set_input_files({
                    "name": "corrupt.jpg", "mimeType": "image/jpeg", "buffer": b"not jpeg"})
                page.wait_for_function("document.getElementById('captureStatus').textContent.includes('Không giải mã')")
                assert page.evaluate("current().backendMode && !!current().stream")
                print("PASS: corrupt image leaves the live camera and existing core intact", flush=True)

                page.locator("#testImageInput").set_input_files(sample)
                page.wait_for_function("ensureRounds(current())[0].productAnalysis && !ensureRounds(current())[0].productAiPending", timeout=90000)
                assert page.evaluate("Number(ensureRounds(current())[0].productWeight)") == metadata["expected_weight"]
                assert page.evaluate("ensureRounds(current())[0].qr") == metadata["expected_qr_code"]
                assert not page.evaluate("current().backendMode || !!current().stream")
                assert len(analysis_requests) == 2, analysis_requests
                page.screenshot(path=str(artifacts / "ai-local-upload.png"), full_page=True)
                page.evaluate("document.activeElement.blur()")
                page.keyboard.press("Enter")
                deadline = time.monotonic() + 30
                row = None
                while time.monotonic() < deadline:
                    row = service.store.connection.execute("SELECT * FROM measurements").fetchone()
                    if row is not None and row["image_path"] and row["product_image_path"]: break
                    page.wait_for_timeout(200)
                assert row is not None, page.locator("#captureStatus").inner_text()
                page.wait_for_function("!current()._saveLock && !current()._saveAllLock", timeout=30000)
                assert row["qr_code"] == metadata["expected_qr_code"]
                for field in ("image_path", "product_image_path"):
                    image = Path(row[field]).resolve()
                    assert image.is_file() and image.is_relative_to(root.resolve()), (field, dict(row), str(root))
                assert not errors, errors
                browser.close()
                print("PASS: same file can be selected again for product; QR matches; Enter saves both photos locally; no camera snapshot/cloud", flush=True)
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()
            service.close()
            service.store.close()


if __name__ == "__main__":
    main()
