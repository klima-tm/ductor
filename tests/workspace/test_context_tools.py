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
                        "available": False,
                        "source": None,
                        "updated_at": None,
                        "stale_after_seconds": 0,
                        "message": "No approved schedule source is connected yet.",
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

    schedule = shared.get_category("schedule")
    assert schedule["success"] is True
    assert schedule["available"] is False
    assert "No approved schedule" in schedule["message"]


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
    denied = mcp.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "get_finances", "arguments": {}},
        }
    )
    assert denied["error"]["code"] == -32602
