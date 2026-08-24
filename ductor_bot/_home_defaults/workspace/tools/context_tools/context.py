#!/usr/bin/env python3
"""Read administrator-approved context about Egor; never writes source data."""

from __future__ import annotations

import argparse
import json

from _shared import get_category, get_schedule, search

_COMMANDS = {
    "current-work": "current_work",
    "goals": "goals",
    "diet": "diet",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*_COMMANDS, "schedule", "search"])
    parser.add_argument("query", nargs="*")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--no-routines", action="store_true")
    parser.add_argument("--routine-query")
    args = parser.parse_args()
    if args.command == "search":
        result = search(" ".join(args.query))
    elif args.command == "schedule":
        result = get_schedule(
            args.start,
            args.end,
            include_routines=not args.no_routines,
            routine_query=args.routine_query,
        )
    else:
        result = get_category(_COMMANDS[args.command])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
