#!/usr/bin/env python3
"""Manage durable memory for the current chat through Ductor's internal API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage current-chat durable memory")
    subparsers = parser.add_subparsers(dest="action", required=True)

    add = subparsers.add_parser("add", help="Store a new durable fact")
    add.add_argument("content")
    add.add_argument("--category", default="context")

    search = subparsers.add_parser("search", help="Find current-chat memories")
    search.add_argument("query", nargs="?", default="")

    for action in ("update", "supersede"):
        command = subparsers.add_parser(action, help=f"{action.title()} a durable fact")
        command.add_argument("memory_id")
        command.add_argument("content")
        command.add_argument("--category", default=None)

    forget = subparsers.add_parser("forget", help="Delete a fact at the user's request")
    forget.add_argument("memory_id")
    return parser


def _payload(args: argparse.Namespace) -> dict[str, object]:
    payload: dict[str, object] = {"action": args.action}
    for name in ("memory_id", "content", "category", "query"):
        value = getattr(args, name, None)
        if value is not None:
            payload[name] = value
    return payload


def main() -> int:
    args = _parser().parse_args()
    capability = os.environ.get("DUCTOR_MEMORY_CAPABILITY", "").strip()
    if not capability:
        print(json.dumps({"success": False, "error": "memory tool unavailable"}))
        return 2

    host = os.environ.get("DUCTOR_INTERAGENT_HOST", "127.0.0.1")
    port = os.environ.get("DUCTOR_INTERAGENT_PORT", "8799")
    request = urllib.request.Request(
        f"http://{host}:{port}/memory/manage",
        data=json.dumps(_payload(args)).encode(),
        headers={
            "Authorization": f"Bearer {capability}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            result = json.load(exc)
        except (ValueError, TypeError):
            result = {"success": False, "error": f"memory service HTTP {exc.code}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        result = {"success": False, "error": f"memory service unavailable: {exc}"}

    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
