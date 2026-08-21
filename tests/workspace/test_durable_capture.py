"""Tests for conservative gateway-owned durable fact capture."""

from __future__ import annotations

from ductor_bot.session import SessionKey
from ductor_bot.workspace.durable_capture import (
    capture_explicit_memory,
    extract_durable_facts,
)
from ductor_bot.workspace.paths import DuctorPaths


def test_extracts_english_and_russian_names() -> None:
    assert extract_durable_facts("Hi, my name is Egor.")[0].value == "Egor"
    assert extract_durable_facts("Привет, меня зовут Мария.")[0].value == "Мария"


def test_extracts_explicit_memory_and_preferences() -> None:
    fact = extract_durable_facts("Please remember that I train on Tuesdays.")[0]
    assert fact.label == "Explicitly asked to remember"
    assert fact.value == "I train on Tuesdays"
    preference = extract_durable_facts("Я предпочитаю короткие ответы.")[0]
    assert preference.label == "Preference"


def test_rejects_credentials() -> None:
    assert extract_durable_facts("Remember that my API key is sk-secret-value-12345") == []
    assert extract_durable_facts("Запомни мой пароль hunter2") == []


def test_persists_only_to_current_chat_and_deduplicates(tmp_path) -> None:
    paths = DuctorPaths(tmp_path / ".ductor")
    first = SessionKey.telegram(100)
    second = SessionKey.telegram(200)

    assert (
        capture_explicit_memory(
            paths,
            first,
            "chat",
            "My name is Egor.",
            today="2026-08-21",
        )
        == 1
    )
    assert (
        capture_explicit_memory(
            paths,
            first,
            "chat",
            "My name is Egor.",
            today="2026-08-21",
        )
        == 0
    )

    first_memory = next(paths.memory_system_dir.glob("profiles/*/MAINMEMORY.md"))
    assert "Name: Egor" in first_memory.read_text(encoding="utf-8")
    assert capture_explicit_memory(paths, second, "agent", "My name is Maria.") == 0
    assert len(list(paths.memory_system_dir.glob("profiles/*/MAINMEMORY.md"))) == 1
