"""Tests for direct inbound OpenAI audio transcription."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ductor_bot.config import TranscriptionConfig
from ductor_bot.messenger.telegram.transcription import (
    OpenAITranscriber,
    TranscriptionError,
)


async def test_transcribes_without_forcing_one_language(tmp_path) -> None:
    key_file = tmp_path / "openai.key"
    key_file.write_text("secret-value\n", encoding="utf-8")
    audio_file = tmp_path / "mixed.ogg"
    audio_file.write_bytes(b"ogg-audio")
    transcriber = OpenAITranscriber(TranscriptionConfig(enabled=True, api_key_file=str(key_file)))

    response = MagicMock(status=200, headers={})
    response.json = AsyncMock(return_value={"text": "Привет, let's deploy."})
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.post.return_value = response

    with patch(
        "ductor_bot.messenger.telegram.transcription.aiohttp.ClientSession",
        return_value=session,
    ):
        result = await transcriber.transcribe(audio_file, duration_seconds=10)

    assert result == "Привет, let's deploy."
    request = session.post.call_args
    assert request.args[0].endswith("/audio/transcriptions")
    assert request.kwargs["headers"]["Authorization"] == "Bearer secret-value"
    form = request.kwargs["data"]
    field_names = [field[0]["name"] for field in form._fields]
    assert field_names == ["model", "file"]
    assert "language" not in field_names


async def test_rejects_unconfigured_and_oversized_audio(tmp_path) -> None:
    with pytest.raises(TranscriptionError, match="not configured"):
        await OpenAITranscriber(TranscriptionConfig()).transcribe(tmp_path / "missing.ogg")

    key_file = tmp_path / "key"
    key_file.write_text("key", encoding="utf-8")
    audio_file = tmp_path / "large.ogg"
    audio_file.write_bytes(b"large")
    transcriber = OpenAITranscriber(
        TranscriptionConfig(enabled=True, api_key_file=str(key_file), max_bytes=2)
    )
    with pytest.raises(TranscriptionError, match="too large"):
        await transcriber.transcribe(audio_file)
