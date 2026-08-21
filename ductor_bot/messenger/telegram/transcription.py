"""Direct multilingual OpenAI transcription for inbound Telegram audio."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from ductor_bot.config import TranscriptionConfig

logger = logging.getLogger(__name__)

_TRANSCRIPTIONS_URL = "https://api.openai.com/v1/audio/transcriptions"
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class TranscriptionError(RuntimeError):
    """Safe, user-presentable inbound transcription failure category."""


class OpenAITranscriber:
    """Small async client whose credential is isolated from model subprocesses."""

    def __init__(self, config: TranscriptionConfig) -> None:
        self._config = config

    @property
    def configured(self) -> bool:
        return bool(self._config.enabled and self._config.api_key_file.strip())

    async def transcribe(
        self,
        path: Path,
        *,
        media_type: str = "audio/ogg",
        duration_seconds: int | None = None,
    ) -> str:
        if not self.configured:
            raise TranscriptionError("transcription is not configured")
        try:
            size, api_key, audio = _read_request_data(path, self._config.api_key_file)
        except OSError as exc:
            raise TranscriptionError("the transcription credential is unavailable") from exc
        if not api_key:
            raise TranscriptionError("the transcription credential is empty")
        if size > self._config.max_bytes:
            raise TranscriptionError("the audio message is too large to transcribe")

        timeout_seconds = self._request_timeout(duration_seconds)
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for attempt in range(2):
                    form = aiohttp.FormData()
                    form.add_field("model", self._config.model_id)
                    # Deliberately omit ``language``: one voice note may mix languages.
                    form.add_field(
                        "file",
                        audio,
                        filename=path.name,
                        content_type=media_type or "application/octet-stream",
                    )
                    async with session.post(
                        _TRANSCRIPTIONS_URL,
                        headers={"Authorization": f"Bearer {api_key}"},
                        data=form,
                    ) as response:
                        if response.status == 200:
                            payload = await response.json(content_type=None)
                            return _transcript_from_payload(payload)
                        if response.status not in _RETRYABLE_STATUSES or attempt == 1:
                            logger.warning(
                                "OpenAI transcription failed status=%d",
                                response.status,
                            )
                            _raise_transcription_failure()
                        delay = _retry_delay(response.headers.get("Retry-After"))
                    await asyncio.sleep(delay)
        except TranscriptionError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise TranscriptionError("voice transcription is temporarily unavailable") from exc

        raise TranscriptionError("voice transcription failed")

    def _request_timeout(self, duration_seconds: int | None) -> float:
        if not isinstance(duration_seconds, int) or duration_seconds <= 0:
            return self._config.timeout_seconds
        return min(600.0, max(self._config.timeout_seconds, duration_seconds * 2.0))


def _retry_delay(value: str | None) -> float:
    if value and value.isdigit():
        return min(float(value), 10.0)
    return 1.0


def _read_request_data(path: Path, api_key_file: str) -> tuple[int, str, bytes]:
    return (
        path.stat().st_size,
        Path(api_key_file).expanduser().read_text(encoding="utf-8").strip(),
        path.read_bytes(),
    )


def _transcript_from_payload(payload: object) -> str:
    text = payload.get("text") if isinstance(payload, dict) else None
    if isinstance(text, str) and text.strip():
        return text.strip()
    raise TranscriptionError("transcription returned empty text")


def _raise_transcription_failure() -> None:
    raise TranscriptionError("voice transcription failed")
