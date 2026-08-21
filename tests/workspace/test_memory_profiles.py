"""Tests for agent-wide and chat-isolated Markdown memory."""

from __future__ import annotations

from pathlib import Path

import pytest

from ductor_bot.session import SessionKey
from ductor_bot.workspace.memory_profiles import (
    chat_memory_profile_id,
    ensure_memory_file,
    memory_path,
    memory_system_prompt,
    read_scoped_memory,
)
from ductor_bot.workspace.paths import DuctorPaths


def _paths(tmp_path: Path) -> DuctorPaths:
    return DuctorPaths(ductor_home=tmp_path / "home")


def test_agent_scope_keeps_legacy_mainmemory_path(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    assert memory_path(paths, SessionKey(chat_id=10), "agent") == paths.mainmemory_path


def test_chat_scope_is_opaque_and_isolated(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    alice = memory_path(paths, SessionKey.telegram(123456), "chat")
    bob = memory_path(paths, SessionKey.telegram(654321), "chat")
    assert alice != bob
    assert "123456" not in str(alice)
    assert "654321" not in str(bob)
    assert alice.name == "MAINMEMORY.md"
    assert alice.parent.parent.name == "profiles"


def test_topics_and_models_share_the_parent_chat_profile(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    first = memory_path(paths, SessionKey.telegram(123, topic_id=1), "chat")
    second = memory_path(paths, SessionKey.telegram(123, topic_id=99), "chat")
    assert first == second
    assert chat_memory_profile_id(SessionKey.telegram(123)) == chat_memory_profile_id(
        SessionKey.telegram(123, topic_id=99)
    )


def test_transport_namespaces_equal_numeric_chat_ids(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    telegram = memory_path(paths, SessionKey.telegram(123), "chat")
    matrix = memory_path(paths, SessionKey.matrix(123), "chat")
    assert telegram != matrix


def test_chat_memory_is_seeded_once_and_not_overwritten(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123)
    target = ensure_memory_file(paths, key, "chat")
    assert "Personal memory" in target.read_text(encoding="utf-8")
    target.write_text("custom fact", encoding="utf-8")
    assert ensure_memory_file(paths, key, "chat") == target
    assert read_scoped_memory(paths, key, "chat") == "custom fact"


def test_chat_system_prompt_names_boundary_and_exact_path(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    key = SessionKey.telegram(123)
    target = ensure_memory_file(paths, key, "chat")
    target.write_text("- likes tea", encoding="utf-8")
    prompt = memory_system_prompt(paths, key, "chat", include_content=True)
    assert "PRIVATE MEMORY FOR THIS CHAT" in prompt
    assert "never inspect sibling profiles" in prompt
    assert str(target) in prompt
    assert "likes tea" in prompt
    assert "structured current-chat tool" in prompt
    assert "memory_tools/memory.py" in prompt
    assert "memory_tools/AGENTS.md" in prompt
    assert "do not wait for the user to say 'remember'" in prompt


def test_invalid_scope_fails_closed(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    with pytest.raises(ValueError, match="Unsupported memory scope"):
        memory_path(paths, SessionKey.telegram(123), "shared")
