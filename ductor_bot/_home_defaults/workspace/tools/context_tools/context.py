#!/usr/bin/env python3
"""Read administrator-approved context about Egor; never writes source data."""

from __future__ import annotations

import argparse
import json

from _shared import get_category, search

_COMMANDS = {
    "current-work": "current_work",
    "goals": "goals",
    "schedule": "schedule",
    "diet": "diet",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*_COMMANDS, "search"])
    parser.add_argument("query", nargs="*")
    args = parser.parse_args()
    if args.command == "search":
        result = search(" ".join(args.query))
    else:
        result = get_category(_COMMANDS[args.command])
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
