"""Proactive Telegram replies honor the same sticky voice/text preference."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

from ductor_bot.bus.adapters import from_webhook_wake
from ductor_bot.instagram import NO_REACTION_TOKEN
from ductor_bot.messenger.telegram.transport import TelegramTransport

if TYPE_CHECKING:
    import pytest


def _transport(mode: str, *, speech_configured: bool = True) -> tuple[TelegramTransport, MagicMock]:
    bot = MagicMock()
    bot._reply_modes.get.return_value = mode
    bot._speech.configured = speech_configured
    bot._speech.synthesize = AsyncMock(return_value=b"ogg")
    bot.bot_instance.send_voice = AsyncMock()
    bot.file_roots.return_value = None
    bot._orch = SimpleNamespace(paths=MagicMock())
    return TelegramTransport(bot), bot


async def test_proactive_text_mode_sends_text(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, bot = _transport("text")
    send_rich = AsyncMock()
    monkeypatch.setattr("ductor_bot.messenger.telegram.transport.send_rich", send_rich)
    env = from_webhook_wake(123, "Привет 😇")
    env.result_text = "Привет 😇"

    await transport.deliver(env)

    send_rich.assert_awaited_once()
    bot._speech.synthesize.assert_not_awaited()


async def test_no_reaction_token_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    transport, bot = _transport("voice")
    send_rich = AsyncMock()
    monkeypatch.setattr("ductor_bot.messenger.telegram.transport.send_rich", send_rich)
    env = from_webhook_wake(123, NO_REACTION_TOKEN)
    env.result_text = NO_REACTION_TOKEN

    await transport.deliver(env)

    send_rich.assert_not_awaited()
    bot._speech.synthesize.assert_not_awaited()
    bot.bot_instance.send_voice.assert_not_awaited()


async def test_proactive_voice_mode_sends_native_voice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, bot = _transport("voice")
    send_rich = AsyncMock()
    send_files = AsyncMock()
    monkeypatch.setattr("ductor_bot.messenger.telegram.transport.send_rich", send_rich)
    monkeypatch.setattr("ductor_bot.messenger.telegram.sender.send_files_from_text", send_files)
    env = from_webhook_wake(123, "Красиво 😍")
    env.result_text = "Красиво 😍"

    await transport.deliver(env)

    bot._speech.synthesize.assert_awaited_once_with("Красиво 😍")
    bot.bot_instance.send_voice.assert_awaited_once()
    send_files.assert_awaited_once()
    send_rich.assert_not_awaited()


async def test_proactive_voice_failure_falls_back_to_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ductor_bot.messenger.telegram.speech import SpeechError

    transport, bot = _transport("voice")
    bot._speech.synthesize.side_effect = SpeechError("no voice")
    send_rich = AsyncMock()
    monkeypatch.setattr("ductor_bot.messenger.telegram.transport.send_rich", send_rich)
    env = from_webhook_wake(123, "Текст")
    env.result_text = "Текст"

    await transport.deliver(env)

    send_rich.assert_awaited_once()
