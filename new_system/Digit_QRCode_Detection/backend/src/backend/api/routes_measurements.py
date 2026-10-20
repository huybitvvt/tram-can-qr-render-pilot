"""Recent measurements and operator-approved saves."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from backend.api.schemas import Measurement, MeasurementCreate
from backend.services.measurement_service import MeasurementError

router = APIRouter()


@router.get("/measurements", response_model=list[Measurement])
async def list_measurements(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20):
    service = request.app.state.services.measurements
    try:
        return await asyncio.to_thread(service.list_recent, limit)
    except MeasurementError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error


@router.post("/measurements", response_model=Measurement, status_code=201)
async def create_measurement(request: Request, payload: MeasurementCreate):
    services = request.app.state.services
    try:
        saved, event = await asyncio.to_thread(services.measurements.save, payload)
    except MeasurementError as error:
        raise HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message}) from error
    if services.processing:
        services.processing.mark_saved(saved["qr_data"], saved["raw_digits"])
    services.websockets.publish(event)
    return saved
