#!/usr/bin/env python3
"""Minimal stdio MCP server for capability-bound current-chat memory."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

_SERVER_INFO = {"name": "ductor-memory", "version": "1.0.0"}
_TOOLS = [
    {
        "name": "memory_add",
        "description": "Proactively save one new stable fact about the current user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": [
                        "identity",
                        "relationship",
                        "preference",
                        "context",
                        "plan",
                        "correction",
                    ],
                },
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_search",
        "description": "Search active durable memories for the current user before changing one.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_update",
        "description": "Correct an existing memory in place using its memory ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["memory_id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_supersede",
        "description": "Mark a changed fact historical and create its active replacement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string"},
            },
            "required": ["memory_id", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_forget",
        "description": "Delete one memory only when the current user explicitly asks to forget it.",
        "inputSchema": {
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
    },
]
_ACTIONS = {tool["name"]: tool["name"].removeprefix("memory_") for tool in _TOOLS}


def _api_call(payload: dict[str, Any]) -> dict[str, Any]:
    capability = os.environ.get("DUCTOR_MEMORY_CAPABILITY", "").strip()
    if not capability:
        return {"success": False, "error": "memory tool unavailable"}
    host = os.environ.get("DUCTOR_INTERAGENT_HOST", "127.0.0.1")
    port = os.environ.get("DUCTOR_INTERAGENT_PORT", "8799")
    request = urllib.request.Request(
        f"http://{host}:{port}/memory/manage",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {capability}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            return json.load(exc)
        except (ValueError, TypeError):
            return {"success": False, "error": f"memory service HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"success": False, "error": f"memory service unavailable: {exc}"}


def _result(request_id: object, result: object) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def handle_request(message: dict[str, Any]) -> dict[str, object] | None:
    """Handle one MCP JSON-RPC request; notifications intentionally return None."""
    request_id = message.get("id")
    method = message.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        protocol = params.get("protocolVersion", "2025-06-18")
        return _result(
            request_id,
            {
                "protocolVersion": protocol,
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
    name = str(params.get("name", ""))
    action = _ACTIONS.get(name)
    arguments = params.get("arguments", {})
    if action is None or not isinstance(arguments, dict):
        return _error(request_id, -32602, "Unknown memory tool or invalid arguments")
    payload = {"action": action, **arguments}
    result = _api_call(payload)
    return _result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False),
                }
            ],
            "structuredContent": result,
            "isError": not bool(result.get("success")),
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
    sys.exit(main())
