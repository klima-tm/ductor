"""Tests for final native Telegram voice delivery and text fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from ductor_bot.messenger.telegram.message_dispatch import VoiceDispatch, run_voice_message
from ductor_bot.messenger.telegram.speech import SpeechError
from ductor_bot.orchestrator.registry import OrchestratorResult
from ductor_bot.session.key import SessionKey


def _dispatch() -> tuple[VoiceDispatch, MagicMock, MagicMock]:
    bot = MagicMock()
    status = MagicMock(message_id=90)
    bot.send_message = AsyncMock(return_value=status)
    bot.edit_message_text = AsyncMock()
    bot.send_voice = AsyncMock()
    bot.delete_message = AsyncMock()
    bot.set_message_reaction = AsyncMock()

    orchestrator = MagicMock()
    orchestrator.handle_message = AsyncMock(return_value=OrchestratorResult(text="Hello"))
    speech = MagicMock()
    speech.synthesize = AsyncMock(return_value=b"ogg-opus")
    message = MagicMock(message_id=42)
    dispatch = VoiceDispatch(
        bot=bot,
        orchestrator=orchestrator,
        message=message,
        key=SessionKey(chat_id=7),
        text="Hi",
        speech=speech,
        allowed_roots=[Path("/tmp")],
    )
    return dispatch, bot, speech


async def test_voice_dispatch_sends_native_voice_and_removes_status() -> None:
    dispatch, bot, speech = _dispatch()
    with (
        patch("ductor_bot.messenger.telegram.message_dispatch.TypingContext") as typing,
        patch(
            "ductor_bot.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ) as send_files,
        patch(
            "ductor_bot.messenger.telegram.message_dispatch.send_rich",
            new_callable=AsyncMock,
        ) as send_rich,
    ):
        typing.return_value.__aenter__ = AsyncMock()
        typing.return_value.__aexit__ = AsyncMock()
        result = await run_voice_message(dispatch)

    assert result == "Hello"
    speech.synthesize.assert_awaited_once_with("Hello")
    bot.send_voice.assert_awaited_once()
    assert bot.send_voice.await_args.kwargs["voice"].filename == "klima-ai.ogg"
    bot.delete_message.assert_awaited_once_with(chat_id=7, message_id=90)
    send_files.assert_awaited_once()
    send_rich.assert_not_awaited()


async def test_voice_dispatch_falls_back_to_complete_text() -> None:
    dispatch, bot, speech = _dispatch()
    speech.synthesize.side_effect = SpeechError("quota")
    with (
        patch("ductor_bot.messenger.telegram.message_dispatch.TypingContext") as typing,
        patch(
            "ductor_bot.messenger.telegram.message_dispatch.send_files_from_text",
            new_callable=AsyncMock,
        ),
        patch(
            "ductor_bot.messenger.telegram.message_dispatch.send_rich",
            new_callable=AsyncMock,
        ) as send_rich,
    ):
        typing.return_value.__aenter__ = AsyncMock()
        typing.return_value.__aexit__ = AsyncMock()
        result = await run_voice_message(dispatch)

    assert result == "Hello"
    bot.send_voice.assert_not_awaited()
    send_rich.assert_awaited_once()
    assert send_rich.await_args.args[2] == "Hello"
    assert "sending text instead" in bot.edit_message_text.await_args.kwargs["text"]
