"""
Perimeter backend — geofenced attendance confirmation API.

Run with:
    uvicorn main:app --reload

Endpoints:
    POST /events                       create an event + its boundary polygon
    GET  /events/{event_id}            fetch an event
    POST /events/{event_id}/ping       submit a GPS ping for a user, get dwell status back
    GET  /events/{event_id}/attendance list confirmed attendees for an event
"""
import json
from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from database import init_db, get_session
from models import Event, CheckIn, AttendanceRecord
from schemas import EventCreate, EventOut, PingIn, PingOut, AttendanceOut
from geo import point_in_polygon

# How long a gap between pings before we consider the "inside streak" broken
# (accounts for the phone's ping interval + brief GPS hiccups).
MAX_PING_GAP_SECONDS = 90

app = FastAPI(title="Perimeter Attendance API")

# Dev-friendly CORS. Lock this down to your real frontend origin before shipping.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


def event_to_out(event: Event) -> EventOut:
    return EventOut(
        id=event.id,
        name=event.name,
        polygon=event.polygon(),
        threshold_seconds=event.threshold_seconds,
        created_at=event.created_at,
    )


@app.post("/events", response_model=EventOut)
def create_event(payload: EventCreate, session: Session = Depends(get_session)):
    if len(payload.polygon) < 3:
        raise HTTPException(400, "Polygon needs at least 3 points")

    event = Event(
        name=payload.name,
        polygon_json=json.dumps(payload.polygon),
        threshold_seconds=payload.threshold_seconds,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event_to_out(event)


@app.get("/events/{event_id}", response_model=EventOut)
def get_event(event_id: int, session: Session = Depends(get_session)):
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event_to_out(event)


@app.post("/events/{event_id}/ping", response_model=PingOut)
def ping(event_id: int, payload: PingIn, session: Session = Depends(get_session)):
    event = session.get(Event, event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    now = datetime.utcnow()
    inside = point_in_polygon(payload.lat, payload.lng, event.polygon())

    # Already confirmed? just acknowledge, no need to keep counting.
    already_confirmed = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.event_id == event_id,
            AttendanceRecord.user_id == payload.user_id,
        )
    ).first()
    if already_confirmed:
        return PingOut(
            inside=inside,
            dwell_seconds=event.threshold_seconds,
            threshold_seconds=event.threshold_seconds,
            confirmed=True,
            already_confirmed=True,
        )

    existing_checkin = session.exec(
        select(CheckIn).where(CheckIn.event_id == event_id,
                              CheckIn.user_id == payload.user_id)
    ).first()

    if not inside:
        # Outside the boundary — clear any in-progress streak.
        if existing_checkin:
            session.delete(existing_checkin)
            session.commit()
        return PingOut(
            inside=False, dwell_seconds=0, threshold_seconds=event.threshold_seconds,
            confirmed=False, already_confirmed=False,
        )

    # Inside the boundary.
    if existing_checkin:
        gap = (now - existing_checkin.last_ping_at).total_seconds()
        if gap > MAX_PING_GAP_SECONDS:
            # Too long since last ping — treat as a fresh entry rather than trusting a stale streak.
            existing_checkin.entered_at = now
        existing_checkin.last_ping_at = now
        existing_checkin.last_lat = payload.lat
        existing_checkin.last_lng = payload.lng
        existing_checkin.last_accuracy = payload.accuracy
        checkin = existing_checkin
    else:
        checkin = CheckIn(
            event_id=event_id,
            user_id=payload.user_id,
            entered_at=now,
            last_ping_at=now,
            last_lat=payload.lat,
            last_lng=payload.lng,
            last_accuracy=payload.accuracy,
        )
        session.add(checkin)

    session.commit()
    session.refresh(checkin)

    dwell_seconds = (now - checkin.entered_at).total_seconds()
    confirmed = dwell_seconds >= event.threshold_seconds

    if confirmed:
        record = AttendanceRecord(
            event_id=event_id,
            user_id=payload.user_id,
            confirmed_at=now,
            entered_at=checkin.entered_at,
        )
        session.add(record)
        session.delete(checkin)
        session.commit()

    return PingOut(
        inside=True,
        dwell_seconds=dwell_seconds,
        threshold_seconds=event.threshold_seconds,
        confirmed=confirmed,
        already_confirmed=False,
    )


@app.get("/events/{event_id}/attendance", response_model=List[AttendanceOut])
def get_attendance(event_id: int, session: Session = Depends(get_session)):
    records = session.exec(
        select(AttendanceRecord).where(AttendanceRecord.event_id == event_id)
    ).all()
    return [
        AttendanceOut(user_id=r.user_id,
                      confirmed_at=r.confirmed_at, entered_at=r.entered_at)
        for r in records
    ]
