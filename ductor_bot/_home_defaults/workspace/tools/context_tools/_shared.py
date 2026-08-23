"""Read-only access to an administrator-curated shared-context snapshot."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
