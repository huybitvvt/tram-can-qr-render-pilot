from __future__ import annotations

import argparse
import os
import platform
import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from .capture_gate import frame_fingerprint
from .qr_input import HIDQRInput, SerialQRInput
from .qr_reader import QRDetection, QRReader, draw_qr_detections
from .scale import ManualWeightSource, SerialWeightSource, WeightReading
from .storage import MeasurementStore
from .sync import OutboxSyncWorker
from .weight_ocr import CameraOCRWeightSource, parse_normalized_roi


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind a QR code to a scale value and store the evidence image."
    )
    parser.add_argument("--source", default="0", help="Camera index (0), image, or video path")
    parser.add_argument(
        "--qr-input",
        choices=("camera", "hid", "serial"),
        default="camera",
        help="Primary QR input: evidence camera, USB keyboard-wedge scanner, or scanner COM port",
    )
    parser.add_argument("--qr-serial-port", help="QR scanner COM port when --qr-input serial")
    parser.add_argument("--qr-baudrate", type=int, default=9600)
    parser.add_argument("--scanner-min-length", type=int, default=3)
    parser.add_argument(
        "--camera-qr-fallback",
        action="store_true",
        help="Try camera decoding when the primary scanner has no QR",
    )
    parser.add_argument("--duplicate-window", type=float, default=5.0)
    parser.add_argument("--serial-port", help="Scale COM port, for example COM3")
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument(
        "--weight-input",
        choices=("auto", "camera", "serial", "manual"),
        default="auto",
        help="Weight source; auto selects serial when --serial-port is present, otherwise manual",
    )
    parser.add_argument("--weight", default="", help="Initial manual weight when no serial port is used")
    parser.add_argument("--unit", default="kg")
    parser.add_argument("--stable-samples", type=int, default=3)
    parser.add_argument("--stability-tolerance", type=float, default=0.02)
    parser.add_argument("--allow-unstable", action="store_true")
    parser.add_argument(
        "--weight-roi",
        help="Required for camera OCR: tight display area as normalized x1,y1,x2,y2",
    )
    parser.add_argument("--ocr-min-confidence", type=float, default=0.60)
    parser.add_argument(
        "--ocr-download",
        action="store_true",
        help="Allow PaddleOCR to download PP-OCRv6_medium_rec once; omit for offline operation",
    )
    parser.add_argument("--ocr-gpu", action="store_true", help="Use a PaddlePaddle CUDA runtime")
    parser.add_argument("--db", default="data/measurements.db")
    parser.add_argument("--captures", default="data/captures")
    parser.add_argument("--yolo-model", help="Custom QR detector weights (best.pt), not stock COCO weights")
    parser.add_argument("--yolo-confidence", type=float, default=0.25)
    parser.add_argument("--yolo-imgsz", type=int, default=960)
    parser.add_argument(
        "--yolo-mode",
        choices=("first", "fallback"),
        default="first",
        help="With a custom model, run YOLO before full-frame decode or only as fallback",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("ROLL_SCALE_API_URL"),
        help="Supabase ingest Edge Function URL",
    )
    parser.add_argument(
        "--api-token",
        default=os.environ.get("ROLL_SCALE_DEVICE_TOKEN")
        or os.environ.get("ROLL_SCALE_API_TOKEN"),
        help="Per-installation ingest token (or set ROLL_SCALE_DEVICE_TOKEN)",
    )
    parser.add_argument(
        "--gateway-id",
        "--device-id",
        dest="gateway_id",
        default=os.environ.get("ROLL_SCALE_GATEWAY_ID")
        or os.environ.get("ROLL_SCALE_DEVICE_ID")
        or platform.node()
        or "gateway-01",
        help="Stable ID of this computer; --device-id remains as a compatibility alias",
    )
    parser.add_argument(
        "--station-id",
        default=os.environ.get("ROLL_SCALE_STATION_ID", "station-01"),
        help="Logical weighing-station ID",
    )
    parser.add_argument(
        "--camera-id",
        default=os.environ.get("ROLL_SCALE_CAMERA_ID", "camera-01"),
        help="Logical physical-camera ID assigned to the station",
    )
    parser.add_argument("--sync-interval", type=float, default=2.0)
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Retry the local outbox without opening a camera",
    )
    parser.add_argument("--once", action="store_true", help="Process one frame without opening a window")
    parser.add_argument("--auto-save", action="store_true", help="With --once, save when QR and weight are valid")
    return parser


def _open_source(source: str) -> tuple[np.ndarray | None, cv2.VideoCapture | None]:
    source_path = Path(source)
    if source_path.suffix.lower() in IMAGE_SUFFIXES:
        frame = cv2.imread(str(source_path))
        if frame is None:
            raise RuntimeError(f"Cannot read image: {source}")
        return frame, None

    capture_source: int | str = int(source) if source.isdigit() else source
    capture = cv2.VideoCapture(capture_source)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"Cannot open camera/video source: {source}")
    if isinstance(capture_source, int):
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return None, capture


def _put_line(frame: np.ndarray, text: str, row: int, color: tuple[int, int, int]) -> None:
    cv2.putText(frame, text, (18, 34 + row * 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (0, 0, 0), 4)
    cv2.putText(frame, text, (18, 34 + row * 31), cv2.FONT_HERSHEY_SIMPLEX, 0.72, color, 2)


def _draw_status(
    frame: np.ndarray,
    qr_value: str | None,
    reading: WeightReading,
    status: str,
    manual: bool,
    pending_count: int,
    qr_source: str | None,
    qr_input_mode: str,
    camera_weight: bool = False,
    awaiting_confirmation: bool = False,
) -> None:
    qr_text = qr_value or "WAITING"
    if len(qr_text) > 55:
        qr_text = qr_text[:52] + "..."
    weight_text = "WAITING" if reading.value is None else f"{reading.value:.3f} {reading.unit}"
    stability = "STABLE" if reading.stable else "UNSTABLE"
    source_text = qr_source or qr_input_mode
    _put_line(
        frame,
        f"QR: {qr_text} [{source_text}]",
        0,
        (40, 240, 40) if qr_value else (0, 200, 255),
    )
    _put_line(frame, f"WEIGHT: {weight_text} [{stability}]", 1, (40, 240, 40) if reading.stable else (0, 200, 255))
    _put_line(frame, f"STATUS: {status} | OUTBOX: {pending_count}", 2, (255, 255, 255))
    if camera_weight:
        hint = (
            "ENTER=confirm/save | SPACE=rescan | Q=quit"
            if awaiting_confirmation
            else "SPACE=capture QR+weight | Q=quit"
        )
    elif qr_input_mode == "hid":
        hint = "Scan QR (scanner suffix Enter) | SPACE=save | ESC=quit"
    else:
        hint = "Type weight; Backspace/C=edit | SPACE=save | Q=quit" if manual else "SPACE=save | Q=quit"
    _put_line(frame, hint, 3, (220, 220, 220))


def _save_current(
    store: MeasurementStore,
    frame: np.ndarray,
    qr_value: str | None,
    reading: WeightReading,
    source_name: str,
    qr_source: str,
    allow_unstable: bool,
    sync_worker: OutboxSyncWorker | None,
    recent_saves: dict[str, float],
    duplicate_window: float,
    *,
    gateway_id: str = "",
    station_id: str = "",
    camera_id: str = "",
    event_id: str | None = None,
) -> str:
    if not qr_value:
        return "NOT SAVED: no QR"
    if reading.value is None:
        return "NOT SAVED: no weight"
    if not reading.stable and not allow_unstable:
        return "NOT SAVED: weight is unstable"
    now = time.monotonic()
    capture_key = frame_fingerprint(frame)
    existing_event = store.get(event_id) if event_id else None
    if existing_event is None and (
        now - recent_saves.get(capture_key, float("-inf")) < duplicate_window
    ):
        return "NOT SAVED: duplicate frame too soon"

    save_result = store.save_idempotent(
        qr_code=qr_value,
        weight=reading.value,
        unit=reading.unit,
        frame=frame,
        weight_source=source_name,
        needs_sync=sync_worker is not None,
        qr_source=qr_source,
        weight_raw=reading.raw,
        weight_stable=reading.stable,
        event_id=event_id,
        gateway_id=gateway_id,
        station_id=station_id,
        camera_id=camera_id,
    )
    measurement = save_result.measurement
    recent_saves[capture_key] = now
    duplicate_suffix = "; DUPLICATE" if save_result.duplicate else ""
    if sync_worker is not None:
        return f"SAVED #{measurement.id}{duplicate_suffix}; PENDING MANUAL SYNC"
    return f"SAVED #{measurement.id}{duplicate_suffix}"


def run(args: argparse.Namespace) -> int:
    if bool(args.api_url) != bool(args.api_token):
        raise ValueError("Both --api-url and --api-token are required for Supabase sync")
    if args.sync_only:
        if not args.api_url:
            raise ValueError("--sync-only requires --api-url and --api-token")
        store = MeasurementStore(args.db, args.captures)
        worker = OutboxSyncWorker(
            store,
            api_url=args.api_url,
            device_token=args.api_token,
            device_id=args.gateway_id,
            interval=args.sync_interval,
        )
        try:
            synced = worker.sync_once(limit=1000, include_deferred=True)
            remaining = store.pending_count()
            print(f"SYNCED={synced} REMAINING={remaining}")
            return 0 if remaining == 0 else 2
        finally:
            store.close()
    if args.qr_input == "serial" and not args.qr_serial_port:
        raise ValueError("--qr-input serial requires --qr-serial-port")
    weight_input = args.weight_input
    if weight_input == "auto":
        weight_input = "serial" if args.serial_port else "manual"
    if weight_input == "serial" and not args.serial_port:
        raise ValueError("--weight-input serial requires --serial-port")
    if weight_input == "camera" and not args.weight_roi:
        raise ValueError("--weight-input camera requires a calibrated --weight-roi x1,y1,x2,y2")
    if args.qr_input == "hid" and weight_input == "manual" and not args.weight:
        raise ValueError("HID scanner with manual scale requires an initial --weight")
    if args.qr_serial_port and args.serial_port == args.qr_serial_port:
        raise ValueError("QR scanner and scale cannot use the same COM port")
    if args.once and args.qr_input != "camera":
        raise ValueError("--once currently requires --qr-input camera")
    static_frame, capture = _open_source(args.source)
    reader = QRReader(
        args.yolo_model,
        args.yolo_confidence,
        yolo_mode=args.yolo_mode,
        yolo_imgsz=args.yolo_imgsz,
    )
    store = MeasurementStore(args.db, args.captures)
    sync_worker = None
    if args.api_url:
        sync_worker = OutboxSyncWorker(
            store,
            api_url=args.api_url,
            device_token=args.api_token,
            device_id=args.gateway_id,
            interval=args.sync_interval,
        )
    if weight_input == "serial":
        weight_source = SerialWeightSource(
            args.serial_port,
            baudrate=args.baudrate,
            unit=args.unit,
            stable_samples=args.stable_samples,
            tolerance=args.stability_tolerance,
        )
    elif weight_input == "camera":
        weight_source = CameraOCRWeightSource(
            parse_normalized_roi(args.weight_roi),
            unit=args.unit,
            min_confidence=args.ocr_min_confidence,
            download_enabled=args.ocr_download,
            gpu=args.ocr_gpu,
        )
    else:
        weight_source = ManualWeightSource(args.weight, args.unit)
    qr_input = None
    if args.qr_input == "hid":
        qr_input = HIDQRInput(min_length=args.scanner_min_length)
    elif args.qr_input == "serial":
        qr_input = SerialQRInput(
            args.qr_serial_port,
            baudrate=args.qr_baudrate,
            min_length=args.scanner_min_length,
        )

    latest_qr: str | None = None
    latest_qr_source: str | None = None
    qr_seen_at = 0.0
    status = "READY"
    last_save_at = 0.0
    recent_saves: dict[str, float] = {}
    pending_frame: np.ndarray | None = None
    pending_detections: list[QRDetection] = []
    pending_event_id: str | None = None
    camera_weight = isinstance(weight_source, CameraOCRWeightSource)

    try:
        while True:
            if static_frame is not None:
                raw_frame = static_frame.copy()
            else:
                assert capture is not None
                ok, raw_frame = capture.read()
                if not ok:
                    if args.once:
                        raise RuntimeError("Cannot read a frame from source")
                    break

            scanner_value = qr_input.reading() if qr_input is not None else None
            use_camera_decoder = args.qr_input == "camera" or (
                args.camera_qr_fallback and scanner_value is None
            )
            detections: list[QRDetection] = (
                reader.decode(raw_frame) if use_camera_decoder and not camera_weight else []
            )
            if camera_weight and pending_frame is not None:
                detections = pending_detections
            elif scanner_value is not None:
                latest_qr = scanner_value.value
                latest_qr_source = scanner_value.source
            elif detections:
                latest_qr = detections[0].value
                latest_qr_source = f"camera:{detections[0].decoder}"
                qr_seen_at = time.monotonic()
            elif args.qr_input == "camera" or args.camera_qr_fallback:
                if time.monotonic() - qr_seen_at > 2.0:
                    latest_qr = None
                    latest_qr_source = None
            else:
                latest_qr = None
                latest_qr_source = None

            if args.once and camera_weight:
                detections = reader.decode(raw_frame) if use_camera_decoder else []
                if scanner_value is None and detections:
                    latest_qr = detections[0].value
                    latest_qr_source = f"camera:{detections[0].decoder}"
                weight_source.capture(raw_frame)

            display = (pending_frame if pending_frame is not None else raw_frame).copy()
            draw_qr_detections(display, detections)
            reading = weight_source.reading()
            if camera_weight:
                weight_source.draw_roi(display)
            _draw_status(
                display,
                latest_qr,
                reading,
                status,
                isinstance(weight_source, ManualWeightSource),
                store.pending_count(),
                latest_qr_source,
                args.qr_input,
                camera_weight,
                pending_frame is not None,
            )

            if args.once:
                if args.auto_save:
                    status = _save_current(
                        store,
                        raw_frame,
                        latest_qr,
                        reading,
                        weight_source.name,
                        latest_qr_source or args.qr_input,
                        args.allow_unstable,
                        sync_worker,
                        recent_saves,
                        args.duplicate_window,
                        gateway_id=args.gateway_id,
                        station_id=args.station_id,
                        camera_id=args.camera_id,
                    )
                    print(status)
                else:
                    print(f"QR={latest_qr!r} WEIGHT={reading.value!r} {reading.unit} STABLE={reading.stable}")
                return 0 if latest_qr else 2

            cv2.imshow("QR + Scale Capture", display)
            key = cv2.waitKeyEx(1)
            if key == 27 or (args.qr_input != "hid" and key in (ord("q"), ord("Q"))):
                break
            if camera_weight and pending_frame is not None and key in (10, 13):
                status = _save_current(
                    store,
                    pending_frame,
                    latest_qr,
                    weight_source.reading(),
                    weight_source.name,
                    latest_qr_source or args.qr_input,
                    False,
                    sync_worker,
                    recent_saves,
                    args.duplicate_window,
                    gateway_id=args.gateway_id,
                    station_id=args.station_id,
                    camera_id=args.camera_id,
                    event_id=pending_event_id,
                )
                if status.startswith("SAVED"):
                    if qr_input is not None:
                        qr_input.clear()
                    latest_qr = None
                    latest_qr_source = None
                    pending_frame = None
                    pending_detections = []
                    pending_event_id = None
                    weight_source.reset()
                continue
            if key == 32 and time.monotonic() - last_save_at > 0.75:
                if camera_weight:
                    pending_frame = raw_frame.copy()
                    pending_event_id = str(uuid.uuid4())
                    pending_detections = reader.decode(pending_frame) if use_camera_decoder else []
                    if scanner_value is not None:
                        latest_qr = scanner_value.value
                        latest_qr_source = scanner_value.source
                    elif pending_detections:
                        latest_qr = pending_detections[0].value
                        latest_qr_source = f"camera:{pending_detections[0].decoder}"
                    else:
                        latest_qr = None
                        latest_qr_source = None
                    reading = weight_source.capture(pending_frame)
                    confidence = (
                        f" ({reading.confidence:.0%})" if reading.confidence is not None else ""
                    )
                    if latest_qr and reading.value is not None:
                        status = (
                            f"DETECTED: {latest_qr} | {reading.value:g} {reading.unit}{confidence}; "
                            "press ENTER to confirm"
                        )
                    else:
                        missing = "QR and weight" if not latest_qr and reading.value is None else (
                            "QR" if not latest_qr else "weight"
                        )
                        status = f"DETECTION FAILED: no {missing}; SPACE=rescan"
                    last_save_at = time.monotonic()
                    continue
                status = _save_current(
                    store,
                    raw_frame,
                    latest_qr,
                    weight_source.reading(),
                    weight_source.name,
                    latest_qr_source or args.qr_input,
                    args.allow_unstable,
                    sync_worker,
                    recent_saves,
                    args.duplicate_window,
                    gateway_id=args.gateway_id,
                    station_id=args.station_id,
                    camera_id=args.camera_id,
                )
                if status.startswith("SAVED") and qr_input is not None:
                    qr_input.clear()
                    latest_qr = None
                    latest_qr_source = None
                last_save_at = time.monotonic()
                continue
            if isinstance(qr_input, HIDQRInput) and qr_input.handle_key(key):
                scanned = qr_input.reading()
                status = "QR SCANNED" if scanned else f"SCANNING QR: {len(qr_input.buffer)} chars"
                continue
            if weight_source.handle_key(key):
                status = "WEIGHT EDITED"
                continue
    finally:
        if sync_worker is not None:
            sync_worker.stop()
        weight_source.close()
        if qr_input is not None:
            qr_input.close()
        store.close()
        if capture is not None:
            capture.release()
        cv2.destroyAllWindows()
    return 0


def main() -> None:
    args = build_parser().parse_args()
    try:
        raise SystemExit(run(args))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
