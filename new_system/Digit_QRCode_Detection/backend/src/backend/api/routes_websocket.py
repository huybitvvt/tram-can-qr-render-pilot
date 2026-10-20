"""Recognition event channel."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/detections")
async def detection_socket(socket: WebSocket):
    services = socket.app.state.services
    origin = socket.headers.get("origin")
    if origin and origin not in services.settings.cors_origins:
        await socket.close(code=1008)
        return
    await socket.accept()
    queue = services.websockets.subscribe()
    try:
        _, snapshot = services.snapshots.current()
        if snapshot:
            await socket.send_json(snapshot.payload)
        else:
            await socket.send_json({"type": "recognition", "timestamp": 0, "frame_width": 0, "frame_height": 0, "detections": [], "qr": None, "raw_digits": None, "numeric_value": None, "confidence": None, "status": "WAITING", "storage_enabled": services.repository is not None and services.repository.healthy})
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                _, current = services.snapshots.current()
                event = current.payload if current else {"type": "recognition", "timestamp": 0, "frame_width": 0, "frame_height": 0, "detections": [], "qr": None, "raw_digits": None, "numeric_value": None, "confidence": None, "status": "WAITING", "storage_enabled": services.repository is not None and services.repository.healthy}
            await socket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        services.websockets.unsubscribe(queue)
