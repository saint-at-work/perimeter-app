from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class EventCreate(BaseModel):
    name: str
    polygon: List[List[float]]        # [[lat, lng], [lat, lng], ...]
    threshold_seconds: int = 60


class EventOut(BaseModel):
    id: int
    name: str
    polygon: List[List[float]]
    threshold_seconds: int
    created_at: datetime


class PingIn(BaseModel):
    user_id: str
    lat: float
    lng: float
    accuracy: Optional[float] = None


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
