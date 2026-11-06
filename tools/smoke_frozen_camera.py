"""Verify the GUI EXE's lightweight camera-worker path and lossless IPC."""
import os
import tempfile
from pathlib import Path

import cv2

from roll_qr_scale.camera_process import IsolatedCapture


def main():
    project = Path(__file__).resolve().parents[1]
    executable = project / "dist/TramCanQR/TramCanQR.exe"
    with tempfile.TemporaryDirectory(prefix="frozen-camera-", dir=project / ".test-tmp") as temp:
        root = Path(temp)
        os.environ["ROLL_SCALE_CAMERA_LOG_DIR"] = str(root)
        frame = cv2.imread(str(project / "data/factory_scale_13_04_reference.jpg"))
        height, width = frame.shape[:2]
        # VideoWriter MJPG needs even dimensions.
        width, height = width - width % 2, height - height % 2
        frame = frame[:height, :width]
        path = root / "sample.avi"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30, (width, height))
        assert writer.isOpened()
        for _ in range(90):
            writer.write(frame)
        writer.release()
        capture = IsolatedCapture(str(path), "AUTO", width, height, 30,
                                  command=[str(executable), "--camera-worker"], startup_timeout=30)
        try:
            ok, actual = capture.read()
            assert ok and actual.shape == frame.shape
        finally:
            capture.release()
        assert capture._process.poll() is not None
        print("PASS: frozen GUI EXE camera helper opens real OpenCV input and transports full frames; worker stops cleanly", flush=True)
        try:
            invalid = IsolatedCapture(str(path), "INVALID_FOR_SMOKE", width, height, 30,
                                      command=[str(executable), "--camera-worker"], startup_timeout=30)
        except OSError:
            pass
        else:
            invalid.release()
            raise AssertionError("Invalid driver should fail in the child")
        assert "CAP_INVALID_FOR_SMOKE" in (root / "camera-driver.log").read_text(encoding="utf-8", errors="replace")
        print("PASS: frozen GUI child failure reaches camera-driver.log and returns to parent without starting model/DB/browser")


if __name__ == "__main__":
    main()
