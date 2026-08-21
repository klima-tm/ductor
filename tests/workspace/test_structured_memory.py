"""Tests for model-driven, chat-scoped structured memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from ductor_bot.session import SessionKey
from ductor_bot.workspace.memory_profiles import ensure_memory_file
from ductor_bot.workspace.paths import DuctorPaths
from ductor_bot.workspace.structured_memory import (
    MemoryCapabilityRegistry,
    MemoryOperationError,
    StructuredMemoryStore,
)


def _store(tmp_path: Path) -> tuple[StructuredMemoryStore, Path]:
    paths = DuctorPaths(tmp_path / "home")
    target = ensure_memory_file(paths, SessionKey.telegram(123), "chat")
    return StructuredMemoryStore(target, source="model:claude"), target


def test_add_search_update_supersede_and_forget(tmp_path: Path) -> None:
    store, target = _store(tmp_path)
    first = store.add("The user prefers concise answers", "preference")
    assert store.add("The user prefers concise answers", "preference").memory_id == first.memory_id
    assert store.search("concise answers") == [first]

    updated = store.update(first.memory_id, "The user prefers very concise answers")
    assert updated.memory_id == first.memory_id
    old, replacement = store.supersede(
        first.memory_id,
        "The user now prefers detailed answers",
    )
    assert old.status == "superseded"
    assert replacement.status == "active"
    assert store.search("detailed") == [replacement]
    assert store.search("concise") == []
    assert "superseded" in target.read_text(encoding="utf-8")

    forgotten = store.forget(replacement.memory_id)
    assert forgotten.memory_id == replacement.memory_id
    assert store.search("") == []


def test_rejects_secrets_unknown_categories_and_cross_profile_ids(tmp_path: Path) -> None:
    store, _target = _store(tmp_path)
    with pytest.raises(MemoryOperationError, match="secrets"):
        store.add("The API key is sk-example-secret-value", "context")
    with pytest.raises(MemoryOperationError, match="Unknown memory category"):
        store.add("A fact", "unknown")
    with pytest.raises(MemoryOperationError, match="not found"):
        store.update("another-profile-id", "Changed fact")


def test_capability_binds_operations_to_one_chat(tmp_path: Path) -> None:
    paths = DuctorPaths(tmp_path / "home")
    registry = MemoryCapabilityRegistry()
    alice = SessionKey.telegram(100)
    bob = SessionKey.telegram(200)
    token = registry.issue(paths, alice, "chat", source="model:codex")

    result = registry.execute(
        token,
        {"action": "add", "content": "Alice likes tea", "category": "preference"},
    )
    assert result["success"] is True
    assert "Alice likes tea" in ensure_memory_file(paths, alice, "chat").read_text()
    assert "Alice likes tea" not in ensure_memory_file(paths, bob, "chat").read_text()
    with pytest.raises(PermissionError):
        registry.execute("invalid", {"action": "search", "query": "tea"})
