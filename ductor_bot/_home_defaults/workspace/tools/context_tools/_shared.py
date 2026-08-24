"""Read-only access to an administrator-curated shared-context snapshot."""

from __future__ import annotations

import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_ENV = "DUCTOR_SHARED_CONTEXT_FILE"
_MAX_FILE_BYTES = 1024 * 1024
_CATEGORIES = {"current_work", "goals", "schedule", "diet"}


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _load() -> tuple[dict[str, Any] | None, str | None]:
    raw_path = os.environ.get(_ENV, "").strip()
    if not raw_path:
        return None, "shared context is not configured"
    path = Path(raw_path).expanduser()
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None, "shared context snapshot exceeds the size limit"
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "shared context snapshot is unavailable"
    if not isinstance(data, dict) or data.get("version") != 1:
        return None, "shared context snapshot has an unsupported format"
    categories = data.get("categories")
    if not isinstance(categories, dict):
        return None, "shared context snapshot has no categories"
    return data, None


def _stale(entry: dict[str, Any]) -> bool:
    updated = _parse_time(entry.get("updated_at"))
    threshold = entry.get("stale_after_seconds")
    if updated is None or not isinstance(threshold, (int, float)) or threshold <= 0:
        return False
    age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
    return age > threshold


def get_category(category: str) -> dict[str, Any]:
    if category not in _CATEGORIES:
        return {"success": False, "error": "category is not approved"}
    snapshot, error = _load()
    if snapshot is None:
        return {"success": False, "error": error}
    entry = snapshot["categories"].get(category)
    if not isinstance(entry, dict):
        return {"success": False, "error": "approved category is missing"}
    result = {
        "success": True,
        "category": category,
        "available": entry.get("available") is True,
        "source": entry.get("source"),
        "updated_at": entry.get("updated_at"),
        "stale": _stale(entry),
    }
    if result["available"]:
        result["content"] = str(entry.get("content") or "")
        if result["stale"]:
            result["warning"] = "This snapshot may be stale; state that caveat instead of guessing."
    else:
        result["message"] = str(entry.get("message") or "Information is unavailable.")
    return result


def _date(value: str | None, *, fallback: date) -> date:
    if value is None:
        return fallback
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("dates must use YYYY-MM-DD") from error


def _event_time(value: object, *, local_zone: ZoneInfo, default: datetime) -> datetime:
    if not isinstance(value, dict):
        return default
    date_time = value.get("dateTime")
    if isinstance(date_time, str):
        parsed = _parse_time(date_time)
        if parsed is not None:
            return parsed.astimezone(local_zone)
    day = value.get("date")
    if isinstance(day, str):
        try:
            return datetime.combine(date.fromisoformat(day), time.min, local_zone)
        except ValueError:
            pass
    return default


def get_schedule(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    at_time: str | None = None,
    include_routines: bool = True,
    routine_query: str | None = None,
) -> dict[str, Any]:
    """Return a bounded date slice plus the approved reference routines."""

    snapshot, error = _load()
    if snapshot is None:
        return {"success": False, "error": error}
    entry = snapshot["categories"].get("schedule")
    if not isinstance(entry, dict):
        return {"success": False, "error": "approved schedule category is missing"}
    if entry.get("available") is not True:
        return {
            "success": True,
            "category": "schedule",
            "available": False,
            "source": entry.get("source"),
            "updated_at": entry.get("updated_at"),
            "stale": False,
            "message": str(entry.get("message") or "Schedule information is unavailable."),
        }
    data = entry.get("data")
    if not isinstance(data, dict):
        return {"success": False, "error": "approved schedule data is malformed"}

    timezone_name = str(data.get("timezone") or "UTC")
    try:
        local_zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return {"success": False, "error": "approved schedule timezone is invalid"}
    today = datetime.now(local_zone).date()
    try:
        start = _date(start_date, fallback=today)
        end = _date(end_date, fallback=start)
    except ValueError as parse_error:
        return {"success": False, "error": str(parse_error)}
    if end < start:
        return {"success": False, "error": "end_date must not be before start_date"}
    if (end - start).days > 31:
        return {"success": False, "error": "schedule queries are limited to 32 days"}

    requested_at: datetime | None = None
    if at_time is not None:
        if start != end:
            return {
                "success": False,
                "error": "at_time requires one date (start_date and end_date must match)",
            }
        try:
            parsed_clock = time.fromisoformat(at_time)
        except ValueError:
            return {"success": False, "error": "at_time must use HH:MM"}
        if parsed_clock.second or parsed_clock.microsecond or len(at_time) != 5:
            return {"success": False, "error": "at_time must use HH:MM"}
        requested_at = datetime.combine(start, parsed_clock, local_zone)

    range_start = datetime.combine(start, time.min, local_zone)
    range_end = datetime.combine(end + timedelta(days=1), time.min, local_zone)
    events: list[dict[str, Any]] = []
    raw_events = data.get("calendar_events")
    if isinstance(raw_events, list):
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            event_start = _event_time(event.get("start"), local_zone=local_zone, default=range_end)
            event_end = _event_time(event.get("end"), local_zone=local_zone, default=event_start)
            if requested_at is not None:
                included = event_start <= requested_at < event_end
            else:
                included = event_start < range_end and event_end > range_start
            if included:
                normalized_event = dict(event)
                normalized_event["display_start"] = event_start.isoformat()
                normalized_event["display_end"] = event_end.isoformat()
                normalized_event["display_timezone"] = timezone_name
                events.append(normalized_event)
    events.sort(key=lambda event: str(event.get("display_start") or ""))

    routines: list[dict[str, Any]] = []
    normalized_query = " ".join((routine_query or "").split())[:200].casefold()
    if include_routines:
        raw_routines = data.get("routines")
        if isinstance(raw_routines, list):
            for routine in raw_routines:
                if not isinstance(routine, dict):
                    continue
                if (
                    normalized_query
                    and normalized_query not in json.dumps(routine, ensure_ascii=False).casefold()
                ):
                    continue
                routines.append(routine)

    result: dict[str, Any] = {
        "success": True,
        "category": "schedule",
        "available": True,
        "source": entry.get("source"),
        "updated_at": entry.get("updated_at"),
        "stale": _stale(entry),
        "timezone": timezone_name,
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "calendar_events": events,
        "routines": routines,
        "calendar_authoritative_for_specific_dates": True,
        "routine_times_are_reference_only": True,
        "all_simultaneous_calendar_events_are_returned": True,
        "use_display_start_and_display_end_for_clock_times": True,
    }
    if requested_at is not None:
        result["requested_time"] = at_time
    coverage = data.get("calendar_coverage")
    if isinstance(coverage, dict):
        result["calendar_coverage"] = coverage
        coverage_start = coverage.get("start")
        coverage_end = coverage.get("end")
        if isinstance(coverage_start, str) and isinstance(coverage_end, str):
            result["coverage_complete"] = (
                coverage_start <= start.isoformat() and end.isoformat() <= coverage_end
            )
    if result["stale"]:
        result["warning"] = "This snapshot may be stale; state that caveat instead of guessing."
    return result


def search(query: str) -> dict[str, Any]:
    normalized = " ".join(query.strip().split())[:200]
    if not normalized:
        return {"success": False, "error": "query is required"}
    terms = [term.casefold() for term in normalized.split()]
    matches: list[dict[str, Any]] = []
    for category in sorted(_CATEGORIES):
        result = get_category(category)
        content = result.get("content")
        if not result.get("success") or not isinstance(content, str):
            continue
        for line in content.splitlines():
            candidate = line.strip()
            folded = candidate.casefold()
            if candidate and all(term in folded for term in terms):
                matches.append(
                    {
                        "category": category,
                        "text": candidate,
                        "source": result.get("source"),
                        "updated_at": result.get("updated_at"),
                        "stale": result.get("stale", False),
                    }
                )
            if len(matches) >= 20:
                break
        if len(matches) >= 20:
            break
    return {"success": True, "query": normalized, "matches": matches}
