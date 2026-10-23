"""Camera capture in a disposable process; frames never leave RAM."""
import multiprocessing as mp
import time

import cv2
import numpy as np

MAX_WIDTH, MAX_HEIGHT = 1920, 1080


def _capture(index, backend, pixels, meta, timestamp, lock):
    # A driver can hang in VideoCapture/open/read. Only this child owns it.
    cv2.setNumThreads(1)
    camera = None
    try:
        camera = cv2.VideoCapture(index, backend)
        if not camera.isOpened():
            with lock:
                meta[3] = -1
            return
        camera.set(cv2.CAP_PROP_FRAME_WIDTH, MAX_WIDTH)
        camera.set(cv2.CAP_PROP_FRAME_HEIGHT, MAX_HEIGHT)
        buffer = np.frombuffer(pixels, dtype=np.uint8)
        failures = 0
        while True:
            ok, frame = camera.read()
            if not ok or frame is None:
                failures += 1
                if failures >= 8:
                    with lock:
                        meta[3] = -1
                    return
                time.sleep(.1)
                continue
            failures = 0
            height, width = frame.shape[:2]
            scale = min(1, MAX_WIDTH/width, MAX_HEIGHT/height)
            if scale < 1:
                frame = cv2.resize(frame, (int(width*scale), int(height*scale)))
            height, width = frame.shape[:2]
            with lock:
                buffer[:frame.size] = frame.ravel()
                meta[0], meta[1], meta[2], meta[3] = width, height, meta[2]+1, 1
                timestamp.value = time.monotonic()
            time.sleep(.025)
    except Exception:
        with lock:
            meta[3] = -1
    finally:
        if camera is not None:
            camera.release()


class Camera:
    def __init__(self, index, backend):
        ctx = mp.get_context('spawn')
        self.pixels = ctx.RawArray('B', MAX_WIDTH*MAX_HEIGHT*3)
        self.meta = ctx.RawArray('i', 4)
        self.timestamp = ctx.RawValue('d', 0)
        self.lock = ctx.Lock()
        self.process = ctx.Process(target=_capture, args=(
            index, backend, self.pixels, self.meta, self.timestamp, self.lock),
            name='TrialCamera', daemon=True)
        self.started_at = time.monotonic()
        self.sequence = 0
        self.process.start()

    def latest(self):
        if not self.lock.acquire(False):
            return None
        try:
            width, height, sequence, _ = self.meta
            if sequence == self.sequence or not width or not height:
                return None
            frame = np.frombuffer(self.pixels, dtype=np.uint8, count=width*height*3)
            result = frame.reshape(height, width, 3).copy(), self.timestamp.value
            self.sequence = sequence
            return result
        finally:
            self.lock.release()

    def failed(self):
        return self.meta[3] == -1 or not self.process.is_alive()

    def close(self):
        # Never wait on a camera driver's lock or release in the GUI process.
        if self.process.is_alive():
            self.process.terminate()
        self.process.join(timeout=.4)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=.4)
        self.process.close()
