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
    parser.add_argument("--at")
    routine_mode = parser.add_mutually_exclusive_group()
    routine_mode.add_argument("--with-routines", action="store_true")
    routine_mode.add_argument("--no-routines", action="store_true")
    parser.add_argument("--routine-query")
    parser.add_argument("--full-event-metadata", action="store_true")
    parser.add_argument("--include-replaced-templates", action="store_true")
    args = parser.parse_args()
    if args.command == "search":
        result = search(" ".join(args.query))
    elif args.command == "schedule":
        result = get_schedule(
            args.start,
            args.end,
            at_time=args.at,
            include_routines=args.with_routines and not args.no_routines,
            routine_query=args.routine_query,
            include_event_metadata=args.full_event_metadata,
            include_replaced_templates=args.include_replaced_templates,
        )
    else:
        result = get_category(_COMMANDS[args.command])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
