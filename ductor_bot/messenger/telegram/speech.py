"""Fixed-voice ElevenLabs replies and persistent per-chat reply modes."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import quote

import aiohttp

from ductor_bot.files.tags import FILE_PATH_RE
from ductor_bot.infra.json_store import atomic_json_save, load_json

if TYPE_CHECKING:
    from ductor_bot.config import SpeechConfig

logger = logging.getLogger(__name__)

ReplyMode = Literal["voice", "text"]
_BUTTON_RE = re.compile(r"\[button:[^\]]+\]", re.IGNORECASE)
_MARKDOWN_RE = re.compile(r"[*_~`#>]+")


class SpeechError(RuntimeError):
    """A safe, user-presentable speech generation failure category."""


class ReplyModeStore:
    """Persist a small per-chat voice/text preference map atomically."""

    def __init__(self, path: Path, default_mode: str = "voice") -> None:
        self._path = path
        self._default: ReplyMode = "text" if default_mode == "text" else "voice"
        self._modes: dict[str, ReplyMode] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        data = load_json(self._path) or {}
        raw_modes = data.get("reply_modes", {})
        if not isinstance(raw_modes, dict):
            return
        for chat_id, mode in raw_modes.items():
            if isinstance(chat_id, str) and mode in {"voice", "text"}:
                self._modes[chat_id] = cast("ReplyMode", mode)

    def get(self, chat_id: int) -> ReplyMode:
        return self._modes.get(str(chat_id), self._default)

    async def set(self, chat_id: int, mode: ReplyMode) -> None:
        async with self._lock:
            self._modes[str(chat_id)] = mode
            payload = {"version": 1, "reply_modes": dict(sorted(self._modes.items()))}
            await asyncio.to_thread(atomic_json_save, self._path, payload)


class ElevenLabsSpeech:
    """Minimal asynchronous ElevenLabs REST client for one configured voice."""

    def __init__(self, config: SpeechConfig) -> None:
        self._config = config

    @property
    def configured(self) -> bool:
        return bool(
            self._config.enabled
            and self._config.voice_id.strip()
            and self._config.api_key_file.strip()
        )

    async def synthesize(self, text: str) -> bytes:
        if not self.configured:
            raise SpeechError("speech is not configured")
        spoken = normalize_speech_text(text)
        if not spoken:
            raise SpeechError("the answer has no speakable text")
        if len(spoken) > self._config.max_chars:
            raise SpeechError("the answer is too long for speech")

        try:
            api_key = (await asyncio.to_thread(_read_api_key, self._config.api_key_file)).strip()
        except OSError as exc:
            raise SpeechError("the speech credential is unavailable") from exc
        if not api_key:
            raise SpeechError("the speech credential is empty")

        voice_id = quote(self._config.voice_id.strip(), safe="")
        output_format = quote(self._config.output_format, safe="")
        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={output_format}"
        )
        timeout = aiohttp.ClientTimeout(total=self._config.timeout_seconds)
        payload = {"text": spoken, "model_id": self._config.model_id}

        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    url,
                    headers={"xi-api-key": api_key, "content-type": "application/json"},
                    json=payload,
                ) as response,
            ):
                if response.status != 200:
                    logger.warning("ElevenLabs synthesis failed status=%d", response.status)
                    raise SpeechError("speech generation failed")
                audio = await response.read()
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise SpeechError("speech generation is temporarily unavailable") from exc

        if not audio:
            raise SpeechError("speech generation returned empty audio")
        return audio


def normalize_speech_text(text: str) -> str:
    """Remove transport markup that should not be spoken aloud."""
    clean = FILE_PATH_RE.sub("", text)
    clean = _BUTTON_RE.sub("", clean)
    clean = re.sub(r"!?\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
    clean = _MARKDOWN_RE.sub("", clean)
    return re.sub(r"\s+", " ", clean).strip()


def _read_api_key(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")
