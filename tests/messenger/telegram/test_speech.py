"""Tests for fixed-voice ElevenLabs replies and reply-mode persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ductor_bot.config import SpeechConfig
from ductor_bot.messenger.telegram.speech import (
    ElevenLabsSpeech,
    ReplyModeStore,
    SpeechError,
    normalize_speech_text,
)


async def test_reply_mode_store_persists_per_chat(tmp_path) -> None:
    path = tmp_path / "reply_preferences.json"
    store = ReplyModeStore(path, default_mode="voice")

    assert store.get(10) == "voice"
    await store.set(10, "text")

    reloaded = ReplyModeStore(path, default_mode="voice")
    assert reloaded.get(10) == "text"
    assert reloaded.get(20) == "voice"


def test_normalize_speech_text_removes_transport_markup() -> None:
    text = "**Hello** [site](https://example.com) [button:Go] <file:/tmp/report.pdf>"
    assert normalize_speech_text(text) == "Hello site"


async def test_synthesize_requests_native_opus_without_exposing_key(tmp_path) -> None:
    key_file = tmp_path / "elevenlabs.key"
    key_file.write_text("secret-value\n", encoding="utf-8")
    speech = ElevenLabsSpeech(
        SpeechConfig(
            enabled=True,
            voice_id="voice/one",
            api_key_file=str(key_file),
            output_format="opus_48000_64",
        )
    )

    response = MagicMock()
    response.status = 200
    response.read = AsyncMock(return_value=b"ogg-opus")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.post.return_value = response

    with patch(
        "ductor_bot.messenger.telegram.speech.aiohttp.ClientSession",
        return_value=session,
    ):
        result = await speech.synthesize("**Hello**")

    assert result == b"ogg-opus"
    url = session.post.call_args.args[0]
    assert "voice%2Fone" in url
    assert "output_format=opus_48000_64" in url
    assert session.post.call_args.kwargs["headers"]["xi-api-key"] == "secret-value"


async def test_synthesize_rejects_unconfigured_or_oversized_text(tmp_path) -> None:
    unconfigured = ElevenLabsSpeech(SpeechConfig())
    with pytest.raises(SpeechError, match="not configured"):
        await unconfigured.synthesize("hello")

    key_file = tmp_path / "key"
    key_file.write_text("key", encoding="utf-8")
    limited = ElevenLabsSpeech(
        SpeechConfig(
            enabled=True,
            voice_id="voice",
            api_key_file=str(key_file),
            max_chars=3,
        )
    )
    with pytest.raises(SpeechError, match="too long"):
        await limited.synthesize("long")
