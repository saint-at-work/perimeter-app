"""
Perimeter backend — geofenced attendance confirmation API (production build).

Data layer: Supabase (PostgREST) via the service_role key — see database.py.
SQLite/SQLModel are gone.

Run locally with:
    uvicorn main:app --reload        (after filling backend/.env)

Deploy on Render via the repo-root render.yaml (gunicorn + uvicorn worker).

Endpoints:
    POST /events                          create an event + its boundary polygon
    GET  /events/{event_id}               fetch an event
    POST /events/{event_id}/ping          submit a GPS ping for a user, get dwell status back
    GET  /events/{event_id}/attendance    list confirmed attendees for an event
    GET  /health                          liveness probe for the platform
"""
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database import verify_supabase, get_event, create_event, get_checkin
from database import upsert_checkin, delete_checkin, get_attendance_record
from database import list_attendance, insert_attendance
from geo import point_in_polygon
from models import CheckIn, AttendanceRecord
from schemas import EventCreate, EventOut, PingIn, PingOut, AttendanceOut

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("perimeter")

# A gap between pings longer than this breaks the "inside" streak (accounts
# for the phone's ping interval plus brief GPS hiccups).
MAX_PING_GAP_SECONDS = 90

# Ceiling for how fast a single user may ping, defensive against scripted
# spam aimed at confirming fake dwell time.
MIN_PING_INTERVAL_SECONDS = 1.0

# Reject request bodies larger than this (defense against oversized-payload
# abuse; legit payloads are a few hundred bytes at most).
MAX_BODY_BYTES = 8 * 1024

# --------------------------------------------------------------------------
# Rate limiting (slowapi). In-memory => per-process; fine at this scale. The
# documented scale-up path is the Redis-backed limiter.storage.RedisStorage.
# --------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    verify_supabase()  # fail fast if Supabase is missing/unreachable
    logger.info("Supabase connection verified")
    yield


app = FastAPI(title="Perimeter Attendance API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak internals to clients; log the real error server-side."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# --------------------------------------------------------------------------
# CORS — locked to allowed origins from env (never "*")
# --------------------------------------------------------------------------
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)


@app.middleware("http")
async def body_size_cap(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        body = await request.body()
        if len(body) > MAX_BODY_BYTES:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
    return await call_next(request)


# --------------------------------------------------------------------------
# Per-user ping throttle (independent of IP-based rate limiting)
# --------------------------------------------------------------------------
_throttle_lock = threading.Lock()
_last_ping: Dict[Tuple[int, str], datetime] = {}


def _check_ping_throttle(event_id: int, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    with _throttle_lock:
        if len(_last_ping) > 5000:
            _last_ping.clear()  # crude cap on in-memory growth
        last = _last_ping.get((event_id, user_id))
        if last and (now - last).total_seconds() < MIN_PING_INTERVAL_SECONDS:
            raise HTTPException(429, "Too many pings — slow down")
        _last_ping[(event_id, user_id)] = now


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/events", response_model=EventOut)
@limiter.limit("20/minute")
def create_event_route(request: Request, payload: EventCreate):
    event = create_event(
        name=payload.name,
        polygon=payload.polygon,
        threshold_seconds=payload.threshold_seconds,
    )
    logger.info("Event %s created: %r", event.id, event.name)
    return event_to_out(event)


@app.get("/events/{event_id}", response_model=EventOut)
@limiter.limit("60/minute")
def get_event_route(request: Request, event_id: int):
    event = get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")
    return event_to_out(event)


@app.post("/events/{event_id}/ping", response_model=PingOut)
@limiter.limit("120/minute")
def ping(
    request: Request,
    event_id: int,
    payload: PingIn,
):
    event = get_event(event_id)
    if not event:
        raise HTTPException(404, "Event not found")

    _check_ping_throttle(event_id, payload.user_id)

    now = datetime.now(timezone.utc)
    inside = point_in_polygon(payload.lat, payload.lng, event.polygon)

    # Already confirmed? just acknowledge — no need to keep counting.
    already_confirmed = get_attendance_record(event_id, payload.user_id)
    if already_confirmed:
        return PingOut(
            inside=inside,
            dwell_seconds=float(event.threshold_seconds),
            threshold_seconds=event.threshold_seconds,
            confirmed=True,
            already_confirmed=True,
        )

    existing_checkin = get_checkin(event_id, payload.user_id)

    if not inside:
        # Outside the boundary — clear any in-progress streak.
        if existing_checkin:
            delete_checkin(event_id, payload.user_id)
        return PingOut(
            inside=False, dwell_seconds=0, threshold_seconds=event.threshold_seconds,
            confirmed=False, already_confirmed=False,
        )

    # Inside the boundary.
    if existing_checkin:
        gap = (now - existing_checkin.last_ping_at).total_seconds()
        if gap > MAX_PING_GAP_SECONDS:
            # Too long since last ping — treat as a fresh entry rather than
            # trusting a stale streak.
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

    upsert_checkin(checkin)

    dwell_seconds = (now - checkin.entered_at).total_seconds()
    confirmed = dwell_seconds >= event.threshold_seconds

    if confirmed:
        insert_attendance(AttendanceRecord(
            event_id=event_id,
            user_id=payload.user_id,
            confirmed_at=now,
            entered_at=checkin.entered_at,
        ))
        delete_checkin(event_id, payload.user_id)

    return PingOut(
        inside=True,
        dwell_seconds=dwell_seconds,
        threshold_seconds=event.threshold_seconds,
        confirmed=confirmed,
        already_confirmed=False,
    )


@app.get("/events/{event_id}/attendance", response_model=List[AttendanceOut])
@limiter.limit("60/minute")
def get_attendance(request: Request, event_id: int):
    # Validate the event exists so a 404 is returned for unknown events.
    if not get_event(event_id):
        raise HTTPException(404, "Event not found")
    records = list_attendance(event_id)
    return [
        AttendanceOut(
            user_id=r.user_id,
            confirmed_at=r.confirmed_at,
            entered_at=r.entered_at,
        )
        for r in records
    ]


# --------------------------------------------------------------------------
# Mapping helpers
# --------------------------------------------------------------------------

def event_to_out(event) -> EventOut:
    return EventOut(
        id=event.id,
        name=event.name,
        polygon=event.polygon,
        threshold_seconds=event.threshold_seconds,
        created_at=event.created_at,
    )