"""Chat-scoped structured memory operations for model-driven writes."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ductor_bot.infra.atomic_io import atomic_text_save
from ductor_bot.workspace.memory_profiles import ensure_memory_file

if TYPE_CHECKING:
    from ductor_bot.session import SessionKey
    from ductor_bot.workspace.paths import DuctorPaths

MemoryAction = Literal["add", "update", "supersede", "forget", "search"]

_CATEGORIES = {
    "identity": "Identity and relationships",
    "relationship": "Identity and relationships",
    "preference": "Preferences and communication",
    "context": "Important context",
    "plan": "Plans and commitments",
    "correction": "Corrections and superseded facts",
}
_DEFAULT_CATEGORY = "context"
_MAX_CONTENT_LENGTH = 1000
_META_PREFIX = "<!-- ductor-memory "
_META_SUFFIX = " -->"
_LINE_RE = re.compile(
    r"^- (?P<body>.*?) <!-- ductor-memory (?P<meta>\{.*\}) -->$",
    re.MULTILINE,
)
_SECRET_RE = re.compile(
    r"(?i)(?:password|парол|api[ _-]?key|secret|token|токен|"
    r"sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,})"
)


class MemoryOperationError(ValueError):
    """Raised when a model requests an invalid or unsafe memory operation."""


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One durable fact stored in a chat profile."""

    memory_id: str
    content: str
    category: str
    status: Literal["active", "superseded"]
    created_at: str
    updated_at: str
    source: str
    superseded_by: str | None = None

    def metadata(self) -> dict[str, str]:
        data = {
            "id": self.memory_id,
            "category": self.category,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
        }
        if self.superseded_by:
            data["superseded_by"] = self.superseded_by
        return data


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _clean_content(value: object) -> str:
    content = re.sub(r"\s+", " ", str(value or "")).strip()
    content = content.replace("<!--", "").replace("-->", "")
    if not content:
        raise MemoryOperationError("Memory content is required")
    if len(content) > _MAX_CONTENT_LENGTH:
        raise MemoryOperationError(f"Memory content exceeds {_MAX_CONTENT_LENGTH} characters")
    if _SECRET_RE.search(content):
        raise MemoryOperationError("Credentials and secrets cannot be stored in memory")
    return content


def _clean_category(value: object | None) -> str:
    category = str(value or _DEFAULT_CATEGORY).strip().lower()
    if category not in _CATEGORIES:
        allowed = ", ".join(sorted(_CATEGORIES))
        raise MemoryOperationError(f"Unknown memory category; use one of: {allowed}")
    return category


def _record_line(record: MemoryRecord) -> str:
    body = record.content
    if record.status == "superseded":
        body = f"~~{body}~~ (superseded)"
    metadata = json.dumps(record.metadata(), ensure_ascii=False, separators=(",", ":"))
    return f"- {body} {_META_PREFIX}{metadata}{_META_SUFFIX}"


def _parse_record(match: re.Match[str]) -> MemoryRecord | None:
    try:
        metadata = json.loads(match.group("meta"))
    except (json.JSONDecodeError, TypeError):
        return None
    body = match.group("body")
    status = metadata.get("status", "active")
    if status == "superseded" and body.startswith("~~"):
        body = re.sub(r"^~~(.*)~~ \(superseded\)$", r"\1", body)
    try:
        return MemoryRecord(
            memory_id=str(metadata["id"]),
            content=body,
            category=str(metadata["category"]),
            status=status,
            created_at=str(metadata["created_at"]),
            updated_at=str(metadata["updated_at"]),
            source=str(metadata.get("source", "model")),
            superseded_by=(
                str(metadata["superseded_by"]) if metadata.get("superseded_by") else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _insert_under_section(content: str, section: str, line: str) -> str:
    heading = f"## {section}"
    heading_index = content.find(heading)
    if heading_index < 0:
        return f"{content.rstrip()}\n\n{heading}\n\n{line}\n"
    body_start = heading_index + len(heading)
    next_heading = content.find("\n## ", body_start)
    if next_heading < 0:
        return f"{content.rstrip()}\n{line}\n"
    before = content[:next_heading].rstrip()
    after = content[next_heading:]
    return f"{before}\n\n{line}\n{after}"


class StructuredMemoryStore:
    """Atomic CRUD operations over managed records inside ``MAINMEMORY.md``."""

    def __init__(self, path: Path, *, source: str = "model") -> None:
        self._path = path
        self._source = source
        self._lock = _path_lock(path)

    def all(self, *, include_superseded: bool = False) -> list[MemoryRecord]:
        with self._lock:
            return self._records(self._read(), include_superseded=include_superseded)

    def search(self, query: str = "") -> list[MemoryRecord]:
        normalized = re.sub(r"\s+", " ", query).strip().casefold()
        records = self.all()
        if not normalized:
            return records
        terms = normalized.split()
        return [
            record for record in records if all(term in record.content.casefold() for term in terms)
        ]

    def add(self, content: object, category: object | None = None) -> MemoryRecord:
        clean_content = _clean_content(content)
        clean_category = _clean_category(category)
        with self._lock:
            text = self._read()
            for existing in self._records(text):
                if existing.content.casefold() == clean_content.casefold():
                    return existing
            stamp = _now()
            record = MemoryRecord(
                memory_id=secrets.token_urlsafe(8),
                content=clean_content,
                category=clean_category,
                status="active",
                created_at=stamp,
                updated_at=stamp,
                source=self._source,
            )
            updated = _insert_under_section(text, _CATEGORIES[clean_category], _record_line(record))
            atomic_text_save(self._path, updated)
            return record

    def update(
        self,
        memory_id: object,
        content: object,
        category: object | None = None,
    ) -> MemoryRecord:
        clean_content = _clean_content(content)
        with self._lock:
            text = self._read()
            found = self._find(text, memory_id)
            clean_category = _clean_category(category or found.category)
            updated_record = replace(
                found,
                content=clean_content,
                category=clean_category,
                updated_at=_now(),
            )
            updated = self._remove_record(text, found.memory_id)
            updated = _insert_under_section(
                updated, _CATEGORIES[clean_category], _record_line(updated_record)
            )
            atomic_text_save(self._path, updated)
            return updated_record

    def supersede(
        self,
        memory_id: object,
        content: object,
        category: object | None = None,
    ) -> tuple[MemoryRecord, MemoryRecord]:
        clean_content = _clean_content(content)
        with self._lock:
            text = self._read()
            old = self._find(text, memory_id)
            clean_category = _clean_category(category or old.category)
            stamp = _now()
            new = MemoryRecord(
                memory_id=secrets.token_urlsafe(8),
                content=clean_content,
                category=clean_category,
                status="active",
                created_at=stamp,
                updated_at=stamp,
                source=self._source,
            )
            old = replace(old, status="superseded", updated_at=stamp, superseded_by=new.memory_id)
            updated = self._replace_record(text, old)
            updated = _insert_under_section(updated, _CATEGORIES[clean_category], _record_line(new))
            atomic_text_save(self._path, updated)
            return old, new

    def forget(self, memory_id: object) -> MemoryRecord:
        with self._lock:
            text = self._read()
            found = self._find(text, memory_id)
            atomic_text_save(self._path, self._remove_record(text, found.memory_id))
            return found

    def _read(self) -> str:
        return self._path.read_text(encoding="utf-8")

    @staticmethod
    def _records(text: str, *, include_superseded: bool = False) -> list[MemoryRecord]:
        records = [record for match in _LINE_RE.finditer(text) if (record := _parse_record(match))]
        if include_superseded:
            return records
        return [record for record in records if record.status == "active"]

    @staticmethod
    def _find(text: str, memory_id: object) -> MemoryRecord:
        target = str(memory_id or "").strip()
        for record in StructuredMemoryStore._records(text, include_superseded=True):
            if secrets.compare_digest(record.memory_id, target):
                return record
        raise MemoryOperationError("Memory ID was not found in this chat profile")

    @staticmethod
    def _replace_record(text: str, record: MemoryRecord) -> str:
        for match in _LINE_RE.finditer(text):
            parsed = _parse_record(match)
            if parsed and parsed.memory_id == record.memory_id:
                return f"{text[: match.start()]}{_record_line(record)}{text[match.end() :]}"
        raise MemoryOperationError("Memory ID was not found in this chat profile")

    @staticmethod
    def _remove_record(text: str, memory_id: str) -> str:
        for match in _LINE_RE.finditer(text):
            parsed = _parse_record(match)
            if parsed and parsed.memory_id == memory_id:
                start = match.start()
                end = match.end()
                if end < len(text) and text[end] == "\n":
                    end += 1
                return f"{text[:start]}{text[end:]}"
        raise MemoryOperationError("Memory ID was not found in this chat profile")


_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(resolved, threading.RLock())


@dataclass(frozen=True, slots=True)
class _Capability:
    store: StructuredMemoryStore
    expires_at: float


class MemoryCapabilityRegistry:
    """Issue short-lived, chat-bound capabilities to provider subprocesses."""

    def __init__(self, *, ttl_seconds: float = 900) -> None:
        self._ttl_seconds = ttl_seconds
        self._items: dict[str, _Capability] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        paths: DuctorPaths,
        key: SessionKey,
        scope: str,
        *,
        source: str,
    ) -> str:
        target = ensure_memory_file(paths, key, scope)
        token = secrets.token_urlsafe(32)
        capability = _Capability(
            StructuredMemoryStore(target, source=source),
            time.monotonic() + self._ttl_seconds,
        )
        with self._lock:
            self._purge_expired_locked()
            self._items[token] = capability
        return token

    def execute(self, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        capability = self._resolve(token)
        action = str(payload.get("action", "")).strip().lower()
        store = capability.store
        if action == "add":
            record = store.add(payload.get("content"), payload.get("category"))
            return {"success": True, "action": "added", "memory": _public_record(record)}
        if action == "update":
            record = store.update(
                payload.get("memory_id"), payload.get("content"), payload.get("category")
            )
            return {"success": True, "action": "updated", "memory": _public_record(record)}
        if action == "supersede":
            old, new = store.supersede(
                payload.get("memory_id"), payload.get("content"), payload.get("category")
            )
            return {
                "success": True,
                "action": "superseded",
                "old_memory": _public_record(old),
                "memory": _public_record(new),
            }
        if action == "forget":
            record = store.forget(payload.get("memory_id"))
            return {"success": True, "action": "forgotten", "memory_id": record.memory_id}
        if action == "search":
            records = store.search(str(payload.get("query", "")))
            return {
                "success": True,
                "action": "searched",
                "memories": [_public_record(record) for record in records],
            }
        raise MemoryOperationError("Unknown memory action")

    def clear(self) -> None:
        """Clear capabilities (test and shutdown hygiene)."""
        with self._lock:
            self._items.clear()

    def _resolve(self, token: str) -> _Capability:
        if not token:
            raise PermissionError("Memory capability is missing")
        with self._lock:
            self._purge_expired_locked()
            capability = self._items.get(token)
        if capability is None:
            raise PermissionError("Memory capability is invalid or expired")
        return capability

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [token for token, item in self._items.items() if item.expires_at <= now]
        for token in expired:
            self._items.pop(token, None)


def _public_record(record: MemoryRecord) -> dict[str, str]:
    return {
        "id": record.memory_id,
        "content": record.content,
        "category": record.category,
        "status": record.status,
        "updated_at": record.updated_at,
    }


memory_capabilities = MemoryCapabilityRegistry()
