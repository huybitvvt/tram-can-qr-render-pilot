"""Readiness report without causing work or writes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
def health(request: Request):
    state = request.app.state.services
    camera = "connected" if state.camera.connected else "disconnected"
    model = "loaded" if state.detector is not None else "unavailable"
    database = "ready" if state.repository is not None and state.repository.healthy else "disabled" if not state.settings.storage_enable else "unavailable"
    body = {"status": "ok", "camera": camera, "model": model, "database": database, "storage_type": state.settings.storage_type if state.settings.storage_enable else None, "storage_enabled": database == "ready"}
    if camera != "connected":
        code, message = "CAMERA_UNAVAILABLE", "The camera is not connected."
    elif model != "loaded":
        code, message = "MODEL_UNAVAILABLE", "Trained digit model weights are not loaded."
    elif database == "unavailable":
        code, message = "DATABASE_UNAVAILABLE", "Local storage is not available."
    else:
        return body
    return JSONResponse(status_code=503, content={"detail": {"code": code, "message": message}, "components": body})
