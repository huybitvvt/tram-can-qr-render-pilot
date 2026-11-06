"""MJPEG stream backed by the shared latest frame."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get("/stream")
async def stream(request: Request):
    services = request.app.state.services
    camera = services.camera
    settings = services.settings
    if not camera.connected:
        raise HTTPException(status_code=503, detail={"code": "CAMERA_UNAVAILABLE", "message": "The camera is not connected."})

    async def frames():
        after_id = 0
        interval = 1 / settings.stream_fps
        while not await request.is_disconnected():
            frame = await asyncio.to_thread(camera.wait_for_frame, after_id, 1)
            if frame is None:
                if not camera.connected:
                    break
                continue
            after_id = frame.frame_id
            image = await asyncio.to_thread(camera.encode_jpeg, frame, settings.jpeg_quality)
            if image is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(image)).encode() + b"\r\n\r\n" + image + b"\r\n"
            await asyncio.sleep(interval)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store, no-cache, must-revalidate"})
