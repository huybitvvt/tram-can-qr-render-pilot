"""Verify live YOLO reuse, offline preview and saved evidence in a real browser."""
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import cv2
from playwright.sync_api import sync_playwright

from roll_qr_scale import test_ui


def main():
    project = Path(__file__).resolve().parents[1]
    artifacts = project / ".test-tmp"
    metadata = json.loads((project / "data/factory_scale_13_04_reference.json").read_text(encoding="utf-8"))
    frame = cv2.imread(str(project / "data" / metadata["image"]))
    opened, cloud_calls = [], []
    release_cloud, slow_cloud = threading.Event(), threading.Event()
    original_orders = test_ui._load_production_orders
    def orders(*args, **kwargs):
        if not slow_cloud.is_set(): return original_orders(*args, **kwargs)
        cloud_calls.append(time.monotonic())
        release_cloud.wait(30)
        return [], "local", "network unavailable for smoke test", False
    class FakeCapture:
        def __init__(self): opened.append(self)
        def isOpened(self): return True
        def release(self): pass
        def read(self):
            time.sleep(.1)
            return True, frame.copy()
    for key in list(os.environ):
        if key.startswith(("ROLL_SCALE_", "SUPABASE_KHO_")):
            del os.environ[key]
    with tempfile.TemporaryDirectory(prefix="live-reuse-", dir=artifacts) as temp, \
            patch.object(test_ui, "_load_local_dotenv"), patch.object(test_ui, "_load_production_orders", side_effect=orders):
        root = Path(temp)
        args = test_ui.build_parser().parse_args([
            "--host", "127.0.0.1", "--port", "0", "--db", str(root / "test.db"),
            "--captures", str(root / "captures"), "--factory-samples", str(root / "samples"),
            "--weight-engine", "local-yolo", "--digit-model", str(project / "model/best.pt"),
            "--digit-confidence", ".2", "--digit-inference-confidence", ".35",
            "--api-url=", "--api-token=", "--lookup-url=", "--lookup-token=", "--no-auto-sync",
        ])
        server, service = test_ui.create_server(args)
        service.live_camera._open = lambda _: FakeCapture()
        inference_jobs = []
        original_submit = service.inference.submit
        def traced_submit(function, *args, **kwargs):
            inference_jobs.append(function.__name__)
            return original_submit(function, *args, **kwargs)
        service.inference.submit = traced_submit
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100})
                errors, previews, analyses, captures, failures = [], set(), [], [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def response_seen(response):
                    if response.status not in (200, 201):
                        if "/api/" in response.url: failures.append((urlsplit(response.url).path, response.status))
                        return
                    if "/api/live/snapshot?preview=1" in response.url:
                        previews.add(response.json()["frame_id"])
                    elif "/api/live/snapshot?capture=1" in response.url:
                        result = response.json()
                        captures.append({"frame_id": result["frame_id"], "reused": bool(result.get("live_capture_token"))})
                    elif response.url.endswith("/api/analyze"):
                        analyses.append(response.json())
                page.on("response", response_seen)
                browser.contexts[0].route("**/*", lambda route: route.continue_()
                    if urlsplit(route.request.url).hostname in {"127.0.0.1", "localhost"}
                    else route.abort())
                page.goto(f"http://127.0.0.1:{server.server_port}", wait_until="domcontentloaded")
                page.wait_for_function("!!current() && !!appStatus", timeout=60000)
                page.evaluate("""qr => {
                    saveSourceContext({...sourceContext, shift:'HC1', machine:'Máy cách nhiệt', order:'LSX-LIVE-REUSE', productCode:productCodeFromQr(qr)});
                    fillSourceFields(sourceContext); selectCaptureSlot('core',0);
                }""", metadata["expected_qr_code"])
                page.locator("#openDefaultCamBtn").click()
                page.wait_for_function("current().backendMode && current().lastLiveRecognition?.weight_found", timeout=60000)
                # Cold model startup may outlast the freshness limit. Wait for
                # its first normal live update before checking the reuse path.
                deadline = time.monotonic() + 30
                while service.live_camera.recognized_capture() is None:
                    assert time.monotonic() < deadline, "Live reading did not become fresh after warmup"
                    page.wait_for_timeout(100)
                for kind in ("core", "product"):
                    page.evaluate("kind => {selectCaptureSlot(kind,0); document.activeElement.blur();}", kind)
                    page.keyboard.press("Space")
                    field = "coreAnalysis" if kind == "core" else "productAnalysis"
                    try:
                        page.wait_for_function(f"!!ensureRounds(current())[0].{field}", timeout=30000)
                    except Exception:
                        print("DEBUG", page.evaluate("({status:document.getElementById('captureStatus').textContent,state:current().state})"),
                              errors, failures, captures, "age", time.monotonic()-service.live_camera._recognized_at,
                              "run_ms", getattr(service.live_camera._recognized_run, "elapsed_ms", None), flush=True)
                        page.screenshot(path=str(artifacts / "rc78-reuse-failure.png"), full_page=True)
                        raise
                    result = page.evaluate(f"ensureRounds(current())[0].{field}")
                    assert result.get("live_capture_reused"), (result.get("weight"), captures, failures,
                        time.monotonic()-service.live_camera._recognized_at, getattr(service.live_camera._recognized_run,"elapsed_ms",None), inference_jobs)
                    assert result["weight"] == metadata["expected_weight"] and result["inference_count"] == 0
                    assert result["step_saved"] and not result["gemini_used"]
                assert service.inference.status().submitted == 0, inference_jobs
                print("PASS: real CPU YOLO live -> Space core/product reuses 13.04 kg + QR with zero extra inference/FIFO jobs", flush=True)

                slow_cloud.set()
                page.evaluate("""() => {window.slowCloudReads = Array.from({length:6}, (_,i) =>
                    api('/api/production-orders?work_date=2026-10-21&smoke=' + i).catch(() => null));}""")
                page.wait_for_timeout(500)
                assert len(cloud_calls) == 2, cloud_calls
                previews.clear()
                page.wait_for_timeout(2000)
                assert len(previews) >= 5, previews
                print(f"PASS: six slow cloud reads use only two HTTP slots; camera still displays {len(previews)} frames in 2s with Internet blocked", flush=True)
                release_cloud.set()
                page.wait_for_function("dataReadActive === 0 && dataReadWaiters.length === 0", timeout=15000)
                slow_cloud.clear()

                before = service.live_camera._frame_id
                browser.contexts[0].set_offline(True)
                page.wait_for_timeout(600)
                assert service.live_camera._frame_id > before and service.live_camera.connected
                browser.contexts[0].set_offline(False)
                page.wait_for_function("current().backendSnapshotFailed === false", timeout=12000)
                previews.clear()
                page.wait_for_timeout(1500)
                assert len(previews) >= 4 and len(opened) == 1
                print("PASS: browser network offline/online recovers automatically; USB capture keeps running on the same instance", flush=True)

                held = []
                def hang_first(route):
                    if not held: held.append(route)
                    else: route.continue_()
                page.route("**/api/live/snapshot?preview=1", hang_first)
                page.wait_for_function("current().backendSnapshotFailed === true", timeout=12000)
                page.wait_for_function("current().backendSnapshotFailed === false", timeout=10000)
                held[0].abort()
                page.unroute("**/api/live/snapshot?preview=1")
                print("PASS: a hung preview request times out and refresh resumes without reopening camera", flush=True)

                page.evaluate("document.activeElement.blur()")
                page.keyboard.press("Enter")
                deadline = time.monotonic() + 20
                row = None
                while time.monotonic() < deadline:
                    row = service.store.connection.execute("SELECT * FROM measurements").fetchone()
                    if row is not None and row["product_image_path"]: break
                    page.wait_for_timeout(100)
                assert row is not None and row["qr_code"] == metadata["expected_qr_code"]
                for key in ("image_path", "product_image_path"):
                    assert cv2.imread(row[key]).shape == frame.shape
                assert not errors, errors
                page.screenshot(path=str(artifacts / "rc78-live-capture-offline.png"), full_page=True)
                browser.contexts[0].unroute_all(behavior="wait")
                browser.close()
                print("PASS: Enter saves both original-resolution evidence photos locally with no cloud access or page errors", flush=True)
        finally:
            release_cloud.set()
            server.shutdown()
            thread.join(5)
            server.server_close()
            service.close()
            service.store.close()


if __name__ == "__main__":
    main()
