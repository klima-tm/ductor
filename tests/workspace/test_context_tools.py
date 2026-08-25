"""Tests for the read-only, administrator-curated Egor context tools."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def context_dir(monkeypatch: pytest.MonkeyPatch) -> Path:
    path = (
        Path(__file__).parents[2]
        / "ductor_bot"
        / "_home_defaults"
        / "workspace"
        / "tools"
        / "context_tools"
    )
    monkeypatch.syspath_prepend(str(path))
    return path


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "context.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "generated_at": "2026-08-23T00:00:00Z",
                "categories": {
                    "current_work": {
                        "available": True,
                        "source": "approved_goals",
                        "updated_at": "2026-08-23T00:00:00Z",
                        "stale_after_seconds": 999999999,
                        "content": "- Build the context bridge",
                    },
                    "goals": {
                        "available": True,
                        "source": "approved_goals",
                        "updated_at": "2020-01-01T00:00:00Z",
                        "stale_after_seconds": 60,
                        "content": "- Move to a warm country\n- Improve English",
                    },
                    "schedule": {
                        "available": True,
                        "source": "approved_calendar_and_routines",
                        "updated_at": "2026-08-23T00:00:00Z",
                        "stale_after_seconds": 999999999,
                        "content": "Lesson 17:30; English Window: 18:00-22:30",
                        "data": {
                            "timezone": "Asia/Bangkok",
                            "calendar_coverage": {
                                "start": "2026-08-23",
                                "end": "2026-09-30",
                            },
                            "calendar_events": [
                                {
                                    "id": "event-1",
                                    "summary": "Lesson",
                                    "recurringEventId": "lesson-template",
                                    "calendar": {"primary": True},
                                    "start": {"dateTime": "2026-08-27T17:30:00+07:00"},
                                    "end": {"dateTime": "2026-08-27T18:30:00+07:00"},
                                },
                                {
                                    "id": "event-offset",
                                    "summary": "Imported lesson",
                                    "calendar": {"primary": False},
                                    "start": {"dateTime": "2026-08-27T10:30:00Z"},
                                    "end": {"dateTime": "2026-08-27T11:30:00Z"},
                                },
                            ],
                            "routines": [
                                {
                                    "Name": "English",
                                    "Default time": "Window: 18:00-22:30",
                                    "Schedule block": '["Lesson"]',
                                    "Activation": '["Daily"]',
                                    "Status": "Set",
                                    "View": "Daily",
                                }
                            ],
                        },
                    },
                    "diet": {
                        "available": False,
                        "source": None,
                        "updated_at": None,
                        "stale_after_seconds": 0,
                        "message": "No approved diet source is connected yet.",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DUCTOR_SHARED_CONTEXT_FILE", str(path))
    return path


def test_category_reports_source_freshness_and_unavailable_state(
    context_dir: Path, snapshot: Path
) -> None:
    del snapshot
    shared = _module("test_context_shared", context_dir / "_shared.py")
    goals = shared.get_category("goals")
    assert goals["success"] is True
    assert goals["source"] == "approved_goals"
    assert goals["updated_at"] == "2020-01-01T00:00:00Z"
    assert goals["stale"] is True
    assert "warning" in goals

    schedule = shared.get_schedule("2026-08-27", "2026-08-27")
    assert schedule["success"] is True
    assert schedule["available"] is True
    assert schedule["calendar_events"][0]["summary"] == "Lesson"
    assert schedule["calendar_events"][0]["display_start"] == "2026-08-27T17:30:00+07:00"
    evidence = schedule["calendar_events"][0]["schedule_evidence"]
    assert evidence["is_recurring_calendar_event"] is True
    assert evidence["calendar_source"] == "primary"
    assert evidence["matching_routines"] == [
        {
            "name": "English",
            "schedule_blocks": ["Lesson"],
            "activation": ["Daily"],
            "default_time": "Window: 18:00-22:30",
            "status": "Set",
            "view": "Daily",
        }
    ]
    assert schedule["routines"][0]["Name"] == "English"
    assert schedule["calendar_authoritative_for_specific_dates"] is True


def test_schedule_query_is_bounded_and_filters_by_date(context_dir: Path, snapshot: Path) -> None:
    del snapshot
    shared = _module("test_context_schedule", context_dir / "_shared.py")
    empty = shared.get_schedule("2026-08-28", "2026-08-28", include_routines=False)
    assert empty["calendar_events"] == []
    assert empty["routines"] == []
    invalid = shared.get_schedule("2026-08-27", "2026-10-01")
    assert invalid == {"success": False, "error": "schedule queries are limited to 32 days"}


def test_schedule_clock_query_normalizes_offsets_and_returns_all_overlaps(
    context_dir: Path, snapshot: Path
) -> None:
    del snapshot
    shared = _module("test_context_clock_schedule", context_dir / "_shared.py")
    result = shared.get_schedule(
        "2026-08-27", "2026-08-27", at_time="17:30", include_routines=False
    )
    assert [event["summary"] for event in result["calendar_events"]] == [
        "Lesson",
        "Imported lesson",
    ]
    assert result["calendar_events"][1]["display_start"] == "2026-08-27T17:30:00+07:00"
    assert result["requested_time"] == "17:30"
    assert result["all_simultaneous_calendar_events_are_returned"] is True
    imported_evidence = result["calendar_events"][1]["schedule_evidence"]
    assert imported_evidence["is_recurring_calendar_event"] is False
    assert imported_evidence["calendar_source"] == "non_primary"
    assert imported_evidence["matching_routines"][0]["name"] == "English"
    assert shared.get_schedule("2026-08-27", "2026-08-28", at_time="17:30") == {
        "success": False,
        "error": "at_time requires one date (start_date and end_date must match)",
    }
    assert shared.get_schedule("2026-08-27", "2026-08-27", at_time="5pm") == {
        "success": False,
        "error": "at_time must use HH:MM",
    }


def test_schedule_regression_for_kaliningrad_five_pm(context_dir: Path, snapshot: Path) -> None:
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    schedule = payload["categories"]["schedule"]["data"]
    schedule["timezone"] = "Europe/Kaliningrad"
    schedule["calendar_events"] = [
        {
            "summary": "Build block",
            "start": {"dateTime": "2026-08-25T21:15:00+07:00"},
            "end": {"dateTime": "2026-08-25T22:15:00+07:00"},
        },
        {
            "summary": "italki Lesson: english - Emmanuel",
            "start": {"dateTime": "2026-08-25T15:00:00Z"},
            "end": {"dateTime": "2026-08-25T16:00:00Z"},
        },
        {
            "summary": "Post something",
            "start": {"dateTime": "2026-08-25T22:00:00+07:00"},
            "end": {"dateTime": "2026-08-25T22:30:00+07:00"},
        },
        {
            "summary": "Bangkok five pm macro",
            "start": {"dateTime": "2026-08-25T13:00:00+07:00"},
            "end": {"dateTime": "2026-08-25T19:50:00+07:00"},
        },
    ]
    snapshot.write_text(json.dumps(payload), encoding="utf-8")
    shared = _module("test_context_kaliningrad_schedule", context_dir / "_shared.py")

    result = shared.get_schedule(
        "2026-08-25", "2026-08-25", at_time="17:00", include_routines=False
    )

    assert [event["summary"] for event in result["calendar_events"]] == [
        "Build block",
        "italki Lesson: english - Emmanuel",
        "Post something",
    ]
    assert {event["display_start"] for event in result["calendar_events"]} == {
        "2026-08-25T16:15:00+02:00",
        "2026-08-25T17:00:00+02:00",
    }
    assert result["timezone"] == "Europe/Kaliningrad"


def test_search_is_bounded_to_approved_categories(context_dir: Path, snapshot: Path) -> None:
    del snapshot
    shared = _module("test_context_search", context_dir / "_shared.py")
    result = shared.search("warm country")
    assert result["success"] is True
    assert result["matches"][0]["category"] == "goals"
    assert shared.get_category("finances") == {
        "success": False,
        "error": "category is not approved",
    }


def test_mcp_lists_only_five_read_tools(context_dir: Path, snapshot: Path) -> None:
    del snapshot
    _module("_shared", context_dir / "_shared.py")
    mcp = _module("test_context_mcp", context_dir / "context_mcp.py")
    listed = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert {tool["name"] for tool in listed["result"]["tools"]} == {
        "get_current_work",
        "get_goals",
        "get_schedule",
        "get_diet",
        "search_shared_context",
    }
    schedule_tool = next(
        tool for tool in listed["result"]["tools"] if tool["name"] == "get_schedule"
    )
    assert "start_date" in schedule_tool["inputSchema"]["properties"]
    assert "at_time" in schedule_tool["inputSchema"]["properties"]
    denied = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_finances", "arguments": {}},
        }
    )
    assert denied["error"]["code"] == -32602
