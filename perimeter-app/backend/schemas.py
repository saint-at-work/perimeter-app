import math
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

USER_ID_PATTERN = r"^[A-Za-z0-9 _\-\.@]{1,64}$"


class EventCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    polygon: List[List[float]] = Field(min_length=3, max_length=200)
    threshold_seconds: int = Field(default=60, ge=10, le=86400)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("polygon")
    @classmethod
    def validate_polygon(cls, value: List[List[float]]) -> List[List[float]]:
        for point in value:
            if len(point) != 2:
                raise ValueError("each polygon point must be [lat, lng]")
            lat, lng = point
            if not (math.isfinite(lat) and math.isfinite(lng)):
                raise ValueError("coordinates must be finite numbers")
            if not (-90.0 <= lat <= 90.0):
                raise ValueError("latitude out of range [-90, 90]")
            if not (-180.0 <= lng <= 180.0):
                raise ValueError("longitude out of range [-180, 180]")
        return value


class EventOut(BaseModel):
    id: int
    name: str
    polygon: List[List[float]]
    threshold_seconds: int
    created_at: datetime


class PingIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64, pattern=USER_ID_PATTERN)
    lat: float
    lng: float
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=5000.0)

    @field_validator("lat", "lng")
    @classmethod
    def validate_coord(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinates must be finite numbers")
        return value

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, value: float) -> float:
        if not (-90.0 <= value <= 90.0):
            raise ValueError("latitude out of range [-90, 90]")
        return value

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, value: float) -> float:
        if not (-180.0 <= value <= 180.0):
            raise ValueError("longitude out of range [-180, 180]")
        return value


class PingOut(BaseModel):
    inside: bool
    dwell_seconds: float
    threshold_seconds: int
    confirmed: bool
    already_confirmed: bool


class AttendanceOut(BaseModel):
    user_id: str
    confirmed_at: datetime
    entered_at: datetime