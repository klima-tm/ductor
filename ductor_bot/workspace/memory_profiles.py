"""Agent-wide or chat-isolated Markdown memory paths."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from ductor_bot.workspace.loader import read_file

if TYPE_CHECKING:
    from ductor_bot.session import SessionKey
    from ductor_bot.workspace.paths import DuctorPaths

_CHAT_MEMORY_TEMPLATE = """# Personal memory

This file contains durable facts for this chat only.

Retention rules:
- Keep stable preferences, important context, ongoing plans, and explicit corrections.
- Prefer short dated facts over transcripts or speculative interpretations.
- Never store credentials, authentication data, or facts belonging to another chat.
- When a fact changes, preserve the correction and clearly mark the old fact superseded.

## Identity and relationships

## Preferences and communication

## Important context

## Plans and commitments

## Corrections and superseded facts
"""


def chat_memory_profile_id(key: SessionKey) -> str:
    """Return a stable opaque profile ID without exposing the transport chat ID."""
    raw = f"{key.transport}:{key.chat_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def memory_path_from_workspace(workspace: Path, key: SessionKey, scope: str) -> Path:
    """Resolve memory from a workspace root for CLI project-root overrides."""
    if scope == "agent":
        return workspace / "memory_system" / "MAINMEMORY.md"
    if scope == "chat":
        return (
            workspace / "memory_system" / "profiles" / chat_memory_profile_id(key) / "MAINMEMORY.md"
        )
    raise ValueError(f"Unsupported memory scope: {scope}")


def memory_path(paths: DuctorPaths, key: SessionKey, scope: str) -> Path:
    """Resolve memory for a session; topics and model providers share a chat profile."""
    return memory_path_from_workspace(paths.workspace, key, scope)


def ensure_memory_file(paths: DuctorPaths, key: SessionKey, scope: str) -> Path:
    """Create a chat-profile memory file once and return its path."""
    target = memory_path(paths, key, scope)
    if scope == "agent" or target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(_CHAT_MEMORY_TEMPLATE)
    except FileExistsError:
        pass
    return target


def read_scoped_memory(paths: DuctorPaths, key: SessionKey, scope: str) -> str:
    """Read the current memory scope, creating a chat-profile seed when needed."""
    target = ensure_memory_file(paths, key, scope)
    return read_file(target) or ""


def memory_system_prompt(
    paths: DuctorPaths,
    key: SessionKey,
    scope: str,
    *,
    include_content: bool,
) -> str:
    """Build the model-facing boundary and optional durable-memory content."""
    target = ensure_memory_file(paths, key, scope)
    if scope == "chat":
        heading = "## PRIVATE MEMORY FOR THIS CHAT"
        boundary = (
            "This file belongs only to the person/chat in the current session. "
            "Read and update only this memory profile; never inspect sibling profiles."
        )
    else:
        heading = "## AGENT MEMORY"
        boundary = "This is the durable memory file shared by this agent."
    tool = paths.workspace / "tools" / "memory_tools" / "memory.py"
    tool_rules = (
        "REAL-TIME MEMORY CONTRACT: Decide semantically whether the current user "
        "message contains a new or corrected durable personal fact, preference, "
        "relationship, important context, or plan. If it does, you MUST call the "
        "structured current-chat memory tool before replying; do not wait for the "
        "user to say 'remember'. Never edit the profile file directly. Do not save "
        "secrets, guesses, or temporary chatter. Search before updating, superseding, "
        "or forgetting a fact. Use forget only when the user explicitly requests "
        "deletion. You may say or imply that something was noted, saved, remembered, "
        "updated, or forgotten only after the tool returns success.\n"
        "Prefer native memory_add, memory_search, memory_update, memory_supersede, "
        "and memory_forget tools when available. Otherwise use the Python tool.\n"
        f"Memory tool: python3 {tool} "
        "{add|search|update|supersede|forget} ...\n"
        f"Read {tool.parent / 'AGENTS.md'} for the exact operations."
    )
    parts = [heading, boundary, f"Memory path: {target}", tool_rules]
    if include_content:
        content = read_file(target) or ""
        if content.strip():
            parts.extend(["Current durable memory:", content])
    return "\n".join(parts)


def scope_memory_prompt(prompt: str, path: Path) -> str:
    """Make a maintenance prompt target the resolved memory file explicitly."""
    legacy = "memory_system/MAINMEMORY.md"
    if legacy in prompt:
        return prompt.replace(legacy, str(path))
    return f"{prompt}\n\nScoped memory path: {path}"
