"""Real HTTP/browser/local-model smoke with fake USB input and isolated data."""
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
    frame = cv2.imread(str(project / "data" / metadata["image"]))

    class FakeCapture:
        def isOpened(self): return True
        def set(self, *_args): return True
        def release(self): pass
        def read(self):
            time.sleep(0.04)
            return True, frame.copy()

    os.environ["ROLL_SCALE_APP_VARIANT"] = "ai-auto"
    os.environ["ROLL_SCALE_APP_VERSION"] = "0.2.0-ai-auto-beta1"
    artifact_dir = project / ".test-tmp"
    artifact_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ai-auto-browser-", dir=artifact_dir) as temp:
        root = Path(temp)
        args = test_ui.build_parser().parse_args([
            "--host", "127.0.0.1", "--port", "0", "--db", str(root / "test.db"),
            "--captures", str(root / "captures"), "--factory-samples", str(root / "samples"),
            "--weight-engine", "local-yolo", "--digit-model", str(project / "model/best.pt"),
            "--digit-confidence", "0.2", "--digit-inference-confidence", "0.35",
            "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
        ])
        server, service = test_ui.create_server(args)
        service.live_camera._open = lambda _source: FakeCapture()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(test_ui, "_ingest_api_url", return_value=""), patch.object(test_ui, "_supabase_project_url", return_value=""), sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors, requests = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: requests.append(request.url))
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="domcontentloaded")
                print("Browser loaded; waiting for local camera", flush=True)
                page.wait_for_function("current()?.backendMode && current()?.video.videoWidth > 0", timeout=60000)
                page.wait_for_function("document.title.includes('Cân AI tự động')", timeout=60000)
                print("Local preview opened", flush=True)
                page.wait_for_timeout(1500)
                assert not any("/api/analyze" in url for url in requests), "Preview must reuse cached recognition"
                assert service.store.connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] == 0
                page.evaluate("""qr => {
                    saveSourceContext({...sourceContext, shift:'HC1', machine:'Máy cách nhiệt', order:'LSX-AUTO-TEST', productCode:productCodeFromQr(qr)});
                    fillSourceFields(sourceContext);
                    selectCaptureSlot('core',0);
                }""", metadata["expected_qr_code"])
                page.evaluate("document.activeElement.blur()")
                page.keyboard.press("Space")
                print("Core capture requested", flush=True)
                page.wait_for_function("ensureRounds(current())[0].coreAnalysis && !ensureRounds(current())[0].coreAiPending", timeout=90000)
                actual = page.evaluate("({weight:ensureRounds(current())[0].weight, analysis:ensureRounds(current())[0].coreAnalysis})")
                page.screenshot(path=str(artifact_dir / "ai-auto-core.png"), full_page=True)
                assert float(actual["weight"]) == 13.04, actual
                print("Core recognition: 13.04", flush=True)
                page.evaluate("selectCaptureSlot('product',0)")
                page.evaluate("document.activeElement.blur()")
                page.keyboard.press("Space")
                print("Product capture requested", flush=True)
                page.wait_for_function("ensureRounds(current())[0].productAnalysis && !ensureRounds(current())[0].productAiPending", timeout=90000)
                assert page.evaluate("Number(ensureRounds(current())[0].productWeight)") == 13.04
                assert page.evaluate("ensureRounds(current())[0].qr") == metadata["expected_qr_code"]
                page.screenshot(path=str(artifact_dir / "ai-auto-capture.png"), full_page=True)
                page.evaluate("document.activeElement.blur()")
                page.keyboard.press("Enter")
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    row = service.store.connection.execute("SELECT * FROM measurements").fetchone()
                    if row is not None: break
                    page.wait_for_timeout(200)
                assert row is not None, page.locator("#captureStatus").inner_text()
                row = dict(row)
                assert row["qr_code"] == metadata["expected_qr_code"]
                assert Path(row["image_path"]).is_file() and Path(row["product_image_path"]).is_file()
                assert Path(row["image_path"]).resolve().is_relative_to(root.resolve())
                assert not errors, errors
                page.screenshot(path=str(artifact_dir / "ai-auto-saved.png"), full_page=True)
                browser.close()
                print("PASS: backend preview, matching local QR/13.04 kg, core/product photos, Enter saves one ticket; no cloud or existing-data writes")
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()
            service.close()
            service.store.close()


if __name__ == "__main__":
    main()
