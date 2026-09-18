"""
Supabase (PostgREST) persistence layer.

Uses the service_role key — the backend is the only holder, RLS has no
policies so anon/authenticated keys can access nothing (see supabase_schema.sql).
"""
import json
import os
from datetime import datetime
from typing import Any, List, Optional

from dotenv import load_dotenv

load_dotenv()

from models import AttendanceRecord, CheckIn, Event

_client = None


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set — copy backend/.env.example to backend/.env "
            "and fill it in (locally), or set it in the Render dashboard."
        )
    return value


def _client_or_raise():
    global _client
    if _client is None:
        from supabase import create_client

        _client = create_client(_env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY"))
    return _client


def verify_supabase() -> None:
    """Fail fast if Supabase is missing/unreachable (called on app startup)."""
    client = _client_or_raise()
    try:
        client.table("events").select("id").limit(1).execute()
    except Exception as exc:
        raise RuntimeError(f"Supabase unreachable: {exc}") from exc


def _rows(res: Any) -> List[Any]:
    """supabase-py types .data as JSON; normalize to a plain list once."""
    return res.data or []


def _parse_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    # PostgREST returns ISO strings; fromisoformat doesn't accept trailing "Z".
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _parse_polygon(value) -> List[List[float]]:
    if isinstance(value, str):
        value = json.loads(value)
    return [[float(lat), float(lng)] for lat, lng in value]


def _event_from_row(row: Any) -> Event:
    return Event(
        id=row["id"],
        name=row["name"],
        polygon=_parse_polygon(row["polygon_json"]),
        threshold_seconds=row["threshold_seconds"],
        created_at=_parse_dt(row["created_at"]),
    )


def create_event(name: str, polygon: List[List[float]], threshold_seconds: int) -> Event:
    res = (
        _client_or_raise()
        .table("events")
        .insert(
            {
                "name": name,
                "polygon_json": polygon,
                "threshold_seconds": threshold_seconds,
            }
        )
        .execute()
    )
    return _event_from_row(_rows(res)[0])


def get_event(event_id: int) -> Optional[Event]:
    res = (
        _client_or_raise()
        .table("events")
        .select("*")
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = _rows(res)
    if not rows:
        return None
    return _event_from_row(rows[0])


def _checkin_from_row(row: Any) -> CheckIn:
    return CheckIn(
        event_id=row["event_id"],
        user_id=row["user_id"],
        entered_at=_parse_dt(row["entered_at"]),
        last_ping_at=_parse_dt(row["last_ping_at"]),
        last_lat=row["last_lat"],
        last_lng=row["last_lng"],
        last_accuracy=row.get("last_accuracy"),
    )


def get_checkin(event_id: int, user_id: str) -> Optional[CheckIn]:
    res = (
        _client_or_raise()
        .table("check_ins")
        .select("*")
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = _rows(res)
    if not rows:
        return None
    return _checkin_from_row(rows[0])


def upsert_checkin(checkin: CheckIn) -> None:
    _client_or_raise().table("check_ins").upsert(
        {
            "event_id": checkin.event_id,
            "user_id": checkin.user_id,
            "entered_at": checkin.entered_at.isoformat(),
            "last_ping_at": checkin.last_ping_at.isoformat(),
            "last_lat": checkin.last_lat,
            "last_lng": checkin.last_lng,
            "last_accuracy": checkin.last_accuracy,
        },
        on_conflict="event_id,user_id",
    ).execute()


def delete_checkin(event_id: int, user_id: str) -> None:
    (
        _client_or_raise()
        .table("check_ins")
        .delete()
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .execute()
    )


def get_attendance_record(event_id: int, user_id: str) -> Optional[AttendanceRecord]:
    res = (
        _client_or_raise()
        .table("attendance_records")
        .select("*")
        .eq("event_id", event_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = _rows(res)
    if not rows:
        return None
    row: Any = rows[0]
    return AttendanceRecord(
        event_id=row["event_id"],
        user_id=row["user_id"],
        confirmed_at=_parse_dt(row["confirmed_at"]),
        entered_at=_parse_dt(row["entered_at"]),
    )


def list_attendance(event_id: int) -> List[AttendanceRecord]:
    res = (
        _client_or_raise()
        .table("attendance_records")
        .select("*")
        .eq("event_id", event_id)
        .order("confirmed_at")
        .execute()
    )
    return [
        AttendanceRecord(
            event_id=row["event_id"],
            user_id=row["user_id"],
            confirmed_at=_parse_dt(row["confirmed_at"]),
            entered_at=_parse_dt(row["entered_at"]),
        )
        for row in _rows(res)
    ]


def insert_attendance(record: AttendanceRecord) -> None:
    # Concurrent pings that cross the threshold together must not double-insert:
    # second writer is ignored, first confirmation wins.
    _client_or_raise().table("attendance_records").upsert(
        {
            "event_id": record.event_id,
            "user_id": record.user_id,
            "confirmed_at": record.confirmed_at.isoformat(),
            "entered_at": record.entered_at.isoformat(),
        },
        on_conflict="event_id,user_id",
        ignore_duplicates=True,
    ).execute()
