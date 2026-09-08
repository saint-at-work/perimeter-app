"""
Database tables.

Event        -> one event, with its polygon stored as JSON text (list of [lat, lng])
CheckIn      -> a running record of one user's presence inside an event's boundary
AttendanceRecord -> a confirmed attendance (dwell threshold was met)
"""
from typing import Optional, List
from datetime import datetime
from sqlmodel import SQLModel, Field
import json


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    polygon_json: str            # JSON-encoded list of [lat, lng]
    threshold_seconds: int = 60  # how long a user must stay inside to be "confirmed"
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def polygon(self) -> List[List[float]]:
        return json.loads(self.polygon_json)


class CheckIn(SQLModel, table=True):
    """Tracks an in-progress (unconfirmed) presence session for one user at one event."""
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id")
    # any string identifying the attendee (name, device id, etc.)
    user_id: str
    entered_at: datetime         # when this continuous "inside" streak started
    last_ping_at: datetime
    last_lat: float
    last_lng: float
    last_accuracy: Optional[float] = None


class AttendanceRecord(SQLModel, table=True):
    """A confirmed attendance — dwell threshold was met."""
    id: Optional[int] = Field(default=None, primary_key=True)
    event_id: int = Field(foreign_key="event.id")
    user_id: str
    confirmed_at: datetime = Field(default_factory=datetime.utcnow)
    entered_at: datetime
