"""HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, field_validator


class MeasurementCreate(BaseModel):
    qr_data: Annotated[str, Field(min_length=1)]
    raw_digits: Annotated[str, Field(pattern=r"^-?[0-9]+$")]
    numeric_value: Annotated[float, Field(allow_inf_nan=False)]
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]

    @field_validator("qr_data")
    @classmethod
    def trim_qr(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("qr_data must not be empty")
        return value


class Measurement(MeasurementCreate):
    id: int
    captured_at: datetime
    created_at: datetime
