"""FastAPI entry point for the local capture station."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api import routes_health, routes_measurements, routes_stream, routes_websocket
from backend.camera.capture_service import CaptureService
from backend.config import Settings, frontend_dist_path, load_settings
from backend.cv.digit_detector import DigitDetector
from backend.recognition.snapshot import RecognitionSnapshot, SnapshotStore
from backend.services.measurement_service import MeasurementService
from backend.services.processing_service import ProcessingService
from backend.services.websocket_manager import WebSocketManager
from backend.storage.sqlite_repository import SqliteRepository
from backend.storage.csv_repository import CsvRepository

logger = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    camera: CaptureService
    detector: DigitDetector | None
    snapshots: SnapshotStore
    websockets: WebSocketManager
    repository: SqliteRepository | CsvRepository | None
    measurements: MeasurementService
    processing: ProcessingService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    backend_logger = logging.getLogger("backend")
    backend_logger.setLevel(logging.DEBUG if settings.detection_debug else logging.INFO)
    if not backend_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        backend_logger.addHandler(handler)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if settings.camera_source.lower().startswith("rtsp://") and settings.rtsp_transport in {"tcp", "udp"}:
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", f"rtsp_transport;{settings.rtsp_transport}")

        repository: SqliteRepository | CsvRepository | None = None
        if settings.storage_enable:
            try:
                repository = CsvRepository(settings.csv_path) if settings.storage_type == "csv" else SqliteRepository(settings.database_path)
                repository.open()
            except Exception:
                logger.exception("Could not initialize local storage")
                repository = None

        detector: DigitDetector | None = None
        try:
            if not settings.model_path.is_file():
                raise FileNotFoundError(f"Model weights not found: {settings.model_path}")
            detector = DigitDetector(settings.model_path, settings.detection_confidence, display_colors=settings.display_colors, max_candidates=settings.display_max_candidates, image_size=settings.display_image_size)
            logger.info("Digit model loaded: %s", settings.model_path)
        except Exception:
            logger.exception("Digit model unavailable")

        camera = CaptureService(settings)
        snapshots = SnapshotStore()
        websockets = WebSocketManager()
        measurements = MeasurementService(settings, snapshots, repository)
        event_loop = asyncio.get_running_loop()

        def publish(event: dict) -> None:
            if not event_loop.is_closed():
                event_loop.call_soon_threadsafe(websockets.publish, event)

        processing = ProcessingService(settings, camera, detector, snapshots, publish, storage_available=lambda: repository is not None and repository.healthy)
        application.state.services = Services(settings, camera, detector, snapshots, websockets, repository, measurements, processing)
        if detector is None:
            timestamp = datetime.now(timezone.utc)
            snapshots.publish(RecognitionSnapshot(0, timestamp, {"type": "recognition", "timestamp": int(timestamp.timestamp() * 1000), "frame_width": 0, "frame_height": 0, "detections": [], "qr": None, "raw_digits": None, "numeric_value": None, "confidence": None, "status": "ERROR", "storage_enabled": repository is not None and repository.healthy}))
        camera.start()
        processing.start()
        try:
            yield
        finally:
            processing.stop()
            camera.stop()
            if repository:
                repository.close()

    application = FastAPI(title="Local QR + Seven-Segment Capture", lifespan=lifespan)
    application.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    application.include_router(routes_health.router)
    application.include_router(routes_stream.router)
    application.include_router(routes_measurements.router)
    application.include_router(routes_websocket.router)

    frontend = frontend_dist_path()
    index = frontend / "index.html"
    assets = frontend / "assets"
    if index.is_file():
        if assets.is_dir():
            application.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @application.get("/", include_in_schema=False)
        @application.get("/{path:path}", include_in_schema=False)
        async def frontend_application(path: str = ""):
            requested = (frontend / path).resolve()
            if path and frontend.resolve() in requested.parents and requested.is_file():
                return FileResponse(requested)
            return FileResponse(index)
    return application


app = create_app()
