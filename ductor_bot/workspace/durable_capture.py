"""Gateway-owned capture of explicit durable user facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ductor_bot.infra.atomic_io import atomic_text_save
from ductor_bot.workspace.memory_profiles import ensure_memory_file

if TYPE_CHECKING:
    from ductor_bot.session import SessionKey
    from ductor_bot.workspace.paths import DuctorPaths

_SECRET_RE = re.compile(
    r"(?i)(?:password|парол|api[ _-]?key|secret|token|токен|"
    r"sk-[a-z0-9_-]{12,}|bearer\s+[a-z0-9._-]{12,})"
)
_NAME_PATTERNS = (
    re.compile(r"(?iu)\b(?:my name is|call me)\s+([^.!?,;:\n]{1,100})"),
    re.compile(r"(?iu)\b(?:меня зовут|зови меня)\s+([^.!?,;:\n]{1,100})"),
)
_REMEMBER_PATTERNS = (
    re.compile(r"(?iu)\b(?:please\s+)?remember(?:\s+that)?\s*[:,]?\s+(.{1,500})$"),
    re.compile(r"(?iu)\b(?:пожалуйста[\s,]+)?запомни(?:\s*,?\s*что)?\s*[:,]?\s+(.{1,500})$"),
)
_PREFERENCE_PATTERNS = (
    re.compile(r"(?iu)\bI prefer\s+(.{1,300})$"),
    re.compile(r"(?iu)\bя предпочитаю\s+(.{1,300})$"),
)


@dataclass(frozen=True, slots=True)
class DurableFact:
    section: str
    label: str
    value: str


def extract_durable_facts(text: str) -> list[DurableFact]:
    """Extract conservative, explicit durable facts from one user message."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized or _SECRET_RE.search(normalized):
        return []

    facts: list[DurableFact] = []
    for pattern in _NAME_PATTERNS:
        match = pattern.search(normalized)
        if match and (name := _clean_name(match.group(1))):
            facts.append(DurableFact("Identity and relationships", "Name", name))
            break

    if not facts:
        for pattern in _REMEMBER_PATTERNS:
            match = pattern.search(normalized)
            if match and (value := _clean_fact(match.group(1))):
                facts.append(
                    DurableFact("Important context", "Explicitly asked to remember", value)
                )
                break

    for pattern in _PREFERENCE_PATTERNS:
        match = pattern.search(normalized)
        if match and (value := _clean_fact(match.group(1))):
            facts.append(DurableFact("Preferences and communication", "Preference", value))
            break

    return facts


def capture_explicit_memory(
    paths: DuctorPaths,
    key: SessionKey,
    scope: str,
    text: str,
    *,
    today: str | None = None,
) -> int:
    """Persist explicit facts to the current chat profile; return additions."""
    if scope != "chat":
        return 0
    facts = extract_durable_facts(text)
    if not facts:
        return 0

    target = ensure_memory_file(paths, key, scope)
    content = target.read_text(encoding="utf-8")
    date = today or datetime.now(UTC).date().isoformat()
    added = 0
    for fact in facts:
        signature = f"{fact.label}: {fact.value}".casefold()
        if signature in content.casefold():
            continue
        bullet = f"- {date} — {fact.label}: {fact.value}"
        content = _insert_under_section(content, fact.section, bullet)
        added += 1
    if added:
        atomic_text_save(target, content)
    return added


def _clean_name(value: str) -> str | None:
    candidate = re.split(r"(?iu)\s+(?:and|и)\s+", value, maxsplit=1)[0].strip(" -'\"")
    if not candidate or len(candidate) > 80 or len(candidate.split()) > 6:
        return None
    if any(not (char.isalpha() or char in " -'") for char in candidate):
        return None
    return candidate


def _clean_fact(value: str) -> str | None:
    candidate = value.strip().rstrip(".!?").strip()
    if not candidate or _SECRET_RE.search(candidate):
        return None
    return candidate


def _insert_under_section(content: str, section: str, bullet: str) -> str:
    heading = f"## {section}"
    heading_index = content.find(heading)
    if heading_index < 0:
        return f"{content.rstrip()}\n\n{heading}\n\n{bullet}\n"
    body_start = heading_index + len(heading)
    next_heading = content.find("\n## ", body_start)
    if next_heading < 0:
        return f"{content.rstrip()}\n{bullet}\n"
    before = content[:next_heading].rstrip()
    after = content[next_heading:]
    return f"{before}\n\n{bullet}\n{after}"
