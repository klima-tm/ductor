#!/usr/bin/env python3
"""Dependency-free stdio MCP adapter for approved, read-only Egor context."""

from __future__ import annotations

import json
import sys
from typing import Any

from _shared import get_category, get_schedule, search

_SERVER_INFO = {"name": "egor-context", "version": "1.0.0"}
_TOOL_CATEGORIES = {
    "get_current_work": "current_work",
    "get_goals": "goals",
    "get_diet": "diet",
}
_EMPTY_SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
_TOOLS = [
    *[
        {
            "name": name,
            "description": f"Read Egor's approved {category.replace('_', ' ')} snapshot with freshness metadata.",
            "inputSchema": _EMPTY_SCHEMA,
        }
        for name, category in _TOOL_CATEGORIES.items()
    ],
    {
        "name": "get_schedule",
        "description": (
            "Read Egor's actual Calendar events for a bounded date range plus approved "
            "reference routines. Calendar wins for specific dates."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "include_routines": {"type": "boolean", "default": True},
                "routine_query": {"type": "string", "maxLength": 200},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "search_shared_context",
        "description": "Search only administrator-approved Egor context categories.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 200}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]


def _result(request_id: object, result: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(message: dict[str, Any]) -> dict[str, object] | None:
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        return _result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": _SERVER_INFO,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})
    if method != "tools/call":
        return _error(request_id, -32601, "Method not found")

    params = message.get("params")
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid tools/call parameters")
    name = str(params.get("name") or "")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "Invalid tool arguments")
    if name in _TOOL_CATEGORIES and not arguments:
        payload = get_category(_TOOL_CATEGORIES[name])
    elif name == "get_schedule":
        start_date = arguments.get("start_date")
        end_date = arguments.get("end_date")
        include_routines = arguments.get("include_routines", True)
        routine_query = arguments.get("routine_query")
        if (
            (start_date is not None and not isinstance(start_date, str))
            or (end_date is not None and not isinstance(end_date, str))
            or not isinstance(include_routines, bool)
            or (routine_query is not None and not isinstance(routine_query, str))
        ):
            return _error(request_id, -32602, "Invalid schedule arguments")
        payload = get_schedule(
            start_date,
            end_date,
            include_routines=include_routines,
            routine_query=routine_query,
        )
    elif name == "search_shared_context" and isinstance(arguments.get("query"), str):
        payload = search(arguments["query"])
    else:
        return _error(request_id, -32602, "Unknown context tool or invalid arguments")
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "structuredContent": payload,
            "isError": not bool(payload.get("success")),
        },
    )


def main() -> int:
    for raw_line in sys.stdin:
        try:
            message = json.loads(raw_line)
            if not isinstance(message, dict):
                raise TypeError
            response = handle_request(message)
        except (json.JSONDecodeError, TypeError):
            response = _error(None, -32700, "Parse error")
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
