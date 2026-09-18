"""
Lightweight domain objects kept independent of the storage layer.

The old SQLModel/table variants are gone — persistence now goes through the
Supabase (PostgREST) wrapper in database.py. These dataclasses just give the
API layer typed, self-describing values.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Event:
    id: int
    name: str
    polygon: List[List[float]]
    threshold_seconds: int
    created_at: datetime


@dataclass
class CheckIn:
    event_id: int
    user_id: str
    entered_at: datetime
    last_ping_at: datetime
    last_lat: float
    last_lng: float
    last_accuracy: Optional[float] = None


@dataclass
class AttendanceRecord:
    event_id: int
    user_id: str
    confirmed_at: datetime
    entered_at: datetime