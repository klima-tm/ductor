"""Protocol tests for the dependency-free structured-memory MCP adapter."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture
def memory_mcp() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "ductor_bot"
        / "_home_defaults"
        / "workspace"
        / "tools"
        / "memory_tools"
        / "memory_mcp.py"
    )
    spec = importlib.util.spec_from_file_location("test_memory_mcp_server", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initialize_and_list_tools(memory_mcp: ModuleType) -> None:
    initialized = memory_mcp.handle_request(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )
    assert initialized["result"]["serverInfo"]["name"] == "ductor-memory"

    listed = memory_mcp.handle_request(  # type: ignore[attr-defined]
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "memory_add",
        "memory_search",
        "memory_update",
        "memory_supersede",
        "memory_forget",
    }


def test_tool_call_maps_to_capability_api(
    memory_mcp: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[dict[str, Any]] = []

    def fake_api(payload: dict[str, Any]) -> dict[str, Any]:
        captured.append(payload)
        return {"success": True, "memory": {"id": "m1"}}

    monkeypatch.setattr(memory_mcp, "_api_call", fake_api)
    response = memory_mcp.handle_request(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "memory_supersede",
                "arguments": {"memory_id": "old", "content": "new fact"},
            },
        }
    )
    assert captured == [{"action": "supersede", "memory_id": "old", "content": "new fact"}]
    assert response["result"]["isError"] is False
    assert response["result"]["structuredContent"]["success"] is True


def test_unknown_tool_is_rejected(memory_mcp: ModuleType) -> None:
    response = memory_mcp.handle_request(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "memory_other", "arguments": {}},
        }
    )
    assert response["error"]["code"] == -32602
