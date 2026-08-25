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


def _string_list(value: object) -> list[str]:
    candidate = value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        candidate = parsed if isinstance(parsed, list) else [value]
    if not isinstance(candidate, list):
        return []
    return [str(item).strip() for item in candidate if str(item).strip()]


def _routine_evidence(routine: dict[str, Any]) -> dict[str, Any] | None:
    properties = routine.get("properties")
    if not isinstance(properties, dict):
        properties = routine
    name = str(properties.get("Name") or "").strip()
    if not name:
        return None
    evidence: dict[str, Any] = {
        "name": name,
        "schedule_blocks": _string_list(properties.get("Schedule block")),
        "activation": _string_list(properties.get("Activation")),
    }
    for source, target in (
        ("Default time", "default_time"),
        ("Duration", "duration"),
        ("Status", "status"),
        ("View", "view"),
    ):
        value = properties.get(source)
        if value not in (None, ""):
            evidence[target] = value
    return evidence


def _matching_routines(summary: str, routines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_summary = " ".join(summary.casefold().split())
    matches: list[dict[str, Any]] = []
    for routine in routines:
        blocks = routine.get("schedule_blocks")
        if not isinstance(blocks, list):
            continue
        matched_blocks = [
            str(block).strip()
            for block in blocks
            if str(block).strip() and " ".join(str(block).casefold().split()) in normalized_summary
        ]
        if matched_blocks:
            match = dict(routine)
            match["matched_schedule_blocks"] = matched_blocks
            matches.append(match)
    return matches


def _attach_same_activity_groups(events: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], list[int]] = {}
    labels: dict[tuple[str, str], tuple[str, str]] = {}
    for index, event in enumerate(events):
        evidence = event.get("schedule_evidence")
        if not isinstance(evidence, dict):
            continue
        routines = evidence.get("matching_routines")
        if not isinstance(routines, list):
            continue
        for routine in routines:
            if not isinstance(routine, dict):
                continue
            routine_name = str(routine.get("name") or "").strip()
            blocks = routine.get("matched_schedule_blocks")
            if not routine_name or not isinstance(blocks, list):
                continue
            for block in blocks:
                block_name = str(block).strip()
                if not block_name:
                    continue
                key = (routine_name.casefold(), block_name.casefold())
                groups.setdefault(key, []).append(index)
                labels[key] = (routine_name, block_name)

    for key, indexes in groups.items():
        unique_indexes = list(dict.fromkeys(indexes))
        if len(unique_indexes) < 2:
            continue
        routine_name, block_name = labels[key]
        concrete_indexes = [
            index
            for index in unique_indexes
            if events[index]["schedule_evidence"].get("is_recurring_calendar_event") is False
            and events[index]["schedule_evidence"].get("calendar_source") == "non_primary"
        ]
        template_indexes = [
            index
            for index in unique_indexes
            if events[index]["schedule_evidence"].get("is_recurring_calendar_event") is True
            and events[index]["schedule_evidence"].get("calendar_source") == "primary"
        ]
        likely_alternatives = bool(concrete_indexes and template_indexes)
        for index in unique_indexes:
            evidence = events[index]["schedule_evidence"]
            if likely_alternatives:
                roles = evidence.setdefault("likely_schedule_roles", [])
                roles.append(
                    {
                        "routine": routine_name,
                        "schedule_block": block_name,
                        "role": (
                            "concrete_instance"
                            if index in concrete_indexes
                            else "recurring_template_replaced_by_concrete_instance"
                            if index in template_indexes
                            else "related_instance"
                        ),
                    }
                )
            same_activity = evidence.setdefault("same_activity_groups", [])
            same_activity.append(
                {
                    "routine": routine_name,
                    "schedule_block": block_name,
                    "likely_alternative_instances": likely_alternatives,
                    "other_events": [
                        {
                            "summary": events[other].get("summary"),
                            "display_start": events[other].get("display_start"),
                            "display_end": events[other].get("display_end"),
                            "is_recurring_calendar_event": events[other]["schedule_evidence"].get(
                                "is_recurring_calendar_event"
                            ),
                            "calendar_source": events[other]["schedule_evidence"].get(
                                "calendar_source"
                            ),
                        }
                        for other in unique_indexes
                        if other != index
                    ],
                }
            )


def _is_likely_replaced_template(event: dict[str, Any]) -> bool:
    evidence = event.get("schedule_evidence")
    if not isinstance(evidence, dict):
        return False
    roles = evidence.get("likely_schedule_roles")
    return isinstance(roles, list) and any(
        isinstance(role, dict)
        and role.get("role") == "recurring_template_replaced_by_concrete_instance"
        for role in roles
    )


def _schedule_reflow_groups(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for concrete in events:
        evidence = concrete.get("schedule_evidence")
        if not isinstance(evidence, dict):
            continue
        if evidence.get("is_recurring_calendar_event") is not False:
            continue
        if evidence.get("calendar_source") != "non_primary":
            continue
        concrete_start = _parse_time(concrete.get("display_start"))
        concrete_end = _parse_time(concrete.get("display_end"))
        if concrete_start is None or concrete_end is None:
            continue
        displaced: list[dict[str, Any]] = []
        for candidate in events:
            if candidate is concrete or _is_likely_replaced_template(candidate):
                continue
            candidate_evidence = candidate.get("schedule_evidence")
            if not isinstance(candidate_evidence, dict):
                continue
            if candidate_evidence.get("is_recurring_calendar_event") is not True:
                continue
            if candidate_evidence.get("calendar_source") != "primary":
                continue
            candidate_start = _parse_time(candidate.get("display_start"))
            candidate_end = _parse_time(candidate.get("display_end"))
            if candidate_start is None or candidate_end is None:
                continue
            if candidate_start >= concrete_end or candidate_end <= concrete_start:
                continue
            routine_names = [
                str(routine.get("name"))
                for routine in candidate_evidence.get("matching_routines", [])
                if isinstance(routine, dict) and routine.get("name")
            ]
            displaced.append(
                {
                    "summary": candidate.get("summary"),
                    "display_start": candidate.get("display_start"),
                    "display_end": candidate.get("display_end"),
                    "matching_routines": routine_names,
                }
            )
        if displaced:
            groups.append(
                {
                    "concrete_event": {
                        "summary": concrete.get("summary"),
                        "display_start": concrete.get("display_start"),
                        "display_end": concrete.get("display_end"),
                    },
                    "displaced_recurring_candidates": displaced,
                    "later_gaps_are_provisional": True,
                }
            )
    return groups


def get_schedule(
    start_date: str | None = None,
    end_date: str | None = None,
    *,
    at_time: str | None = None,
    include_routines: bool = False,
    routine_query: str | None = None,
    include_event_metadata: bool = False,
    include_replaced_templates: bool = False,
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
    raw_routines = data.get("routines")
    routine_records = (
        [routine for routine in raw_routines if isinstance(routine, dict)]
        if isinstance(raw_routines, list)
        else []
    )
    routine_evidence = [
        evidence
        for routine in routine_records
        if (evidence := _routine_evidence(routine)) is not None
    ]
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
                if include_event_metadata:
                    normalized_event = dict(event)
                else:
                    normalized_event = {
                        key: event[key]
                        for key in ("summary", "status", "location")
                        if event.get(key) not in (None, "")
                    }
                normalized_event["display_start"] = event_start.isoformat()
                normalized_event["display_end"] = event_end.isoformat()
                normalized_event["display_timezone"] = timezone_name
                calendar = event.get("calendar")
                primary = calendar.get("primary") if isinstance(calendar, dict) else None
                normalized_event["schedule_evidence"] = {
                    "is_recurring_calendar_event": isinstance(event.get("recurringEventId"), str),
                    "calendar_source": (
                        "primary"
                        if primary is True
                        else "non_primary"
                        if primary is False
                        else "unknown"
                    ),
                    "matching_routines": _matching_routines(
                        str(event.get("summary") or ""), routine_evidence
                    ),
                }
                events.append(normalized_event)
    events.sort(key=lambda event: str(event.get("display_start") or ""))
    _attach_same_activity_groups(events)
    reflow_groups = _schedule_reflow_groups(events)
    source_event_count = len(events)
    replaced_templates = [event for event in events if _is_likely_replaced_template(event)]
    if not include_replaced_templates:
        events = [event for event in events if not _is_likely_replaced_template(event)]
        for event in events:
            evidence = event.get("schedule_evidence")
            if isinstance(evidence, dict):
                evidence.pop("same_activity_groups", None)

    routines: list[dict[str, Any]] = []
    normalized_query = " ".join((routine_query or "").split())[:200].casefold()
    if include_routines or normalized_query:
        for routine in routine_records:
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
        "all_simultaneous_calendar_events_are_returned": (
            include_replaced_templates or not replaced_templates
        ),
        "all_probable_active_calendar_events_are_returned": True,
        "use_display_start_and_display_end_for_clock_times": True,
        "full_event_metadata_included": include_event_metadata,
        "source_calendar_event_count": source_event_count,
        "likely_replaced_template_count": len(replaced_templates),
        "likely_replaced_templates_included": include_replaced_templates,
        "schedule_reflow": {
            "unresolved": bool(reflow_groups),
            "groups": reflow_groups,
            "later_gaps_are_provisional": bool(reflow_groups),
        },
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
