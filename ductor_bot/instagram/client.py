"""Small HikerAPI client for public posts, reels, stories, and media bytes."""

from __future__ import annotations

import asyncio
import contextlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import ParseResult, urlparse

import aiohttp

InstagramKind = Literal["post", "reel", "story"]
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_-]+")
_CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


class HikerAPIError(RuntimeError):
    """HikerAPI or Instagram-media retrieval failed safely."""


@dataclass(frozen=True, slots=True)
class InstagramItem:
    """Normalized Instagram item returned by the monitoring client."""

    item_id: str
    kind: InstagramKind
    code: str
    taken_at: str
    caption: str
    raw: dict[str, Any]

    @property
    def sort_key(self) -> str:
        return self.taken_at or self.item_id


class HikerAPIClient:
    """Read only the HikerAPI endpoints needed by the monitor."""

    def __init__(  # noqa: PLR0913
        self,
        api_key_file: str,
        *,
        timeout_seconds: float = 45.0,
        max_download_bytes: int = 50 * 1024 * 1024,
        max_media_per_item: int = 5,
        base_url: str = "https://api.hikerapi.com",
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key_file = api_key_file
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._max_download_bytes = max_download_bytes
        self._max_media_per_item = max_media_per_item
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._owns_session = session is None

    async def close(self) -> None:
        """Close the internally owned HTTP session."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def resolve_user_id(self, username: str) -> str:
        """Resolve a public Instagram username to its stable numeric ID."""
        data = await self._request_json("/v1/user/by/username", {"username": username})
        if not isinstance(data, dict):
            raise HikerAPIError("HikerAPI returned an invalid user response")
        user_id = data.get("pk") or data.get("id")
        if user_id is None:
            raise HikerAPIError("HikerAPI user response has no ID")
        return str(user_id)

    async def fetch_items(self, user_id: str) -> list[InstagramItem]:
        """Fetch the latest profile media and current stories."""
        feed_data, story_data = await asyncio.gather(
            self._request_json("/v1/user/medias/chunk", {"user_id": user_id}),
            self._request_json("/v1/user/stories", {"user_id": user_id}),
        )
        items = self._normalize_collection(feed_data, source="feed")
        items.extend(self._normalize_collection(story_data, source="story"))
        unique: dict[str, InstagramItem] = {}
        for item in items:
            unique[f"{item.kind}:{item.item_id}"] = item
        return list(unique.values())

    async def download_item(self, item: InstagramItem, target_dir: Path) -> list[Path]:
        """Download the actual photo/video resources for one Instagram item."""
        descriptors = _media_descriptors(item.raw)[: self._max_media_per_item]
        if not descriptors:
            return []
        await asyncio.to_thread(target_dir.mkdir, parents=True, exist_ok=True)
        safe_id = _SAFE_ID_RE.sub("_", item.item_id)[:100] or "item"
        paths: list[Path] = []
        for index, url in enumerate(descriptors, start=1):
            path = await self._download_media(
                url,
                target_dir / f"{item.kind}-{safe_id}-{index}",
            )
            paths.append(path)
        return paths

    async def _request_json(self, path: str, params: dict[str, str]) -> Any:
        key = (await asyncio.to_thread(_read_key, self._api_key_file)).strip()
        if not key:
            raise HikerAPIError("HikerAPI credential is empty")
        session = self._get_session()
        try:
            async with session.get(
                f"{self._base_url}{path}",
                headers={"x-access-key": key},
                params=params,
                timeout=self._timeout,
            ) as response:
                _require_status(response.status, "HikerAPI request")
                return await response.json(content_type=None)
        except HikerAPIError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError, OSError) as exc:
            raise HikerAPIError("HikerAPI request failed") from exc

    async def _download_media(self, url: str, stem: Path) -> Path:
        _validate_media_url(url, self._base_url)
        session = self._get_session()
        temporary = stem.with_suffix(".part")
        try:
            async with session.get(url, timeout=self._timeout) as response:
                _require_status(response.status, "Instagram media download")
                _validate_media_url(str(response.url), self._base_url)
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                extension = _content_extension(content_type)
                final = stem.with_suffix(extension)
                size = 0
                with temporary.open("wb") as handle:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        size += len(chunk)
                        _enforce_size(size, self._max_download_bytes)
                        handle.write(chunk)
                temporary.replace(final)
                return final
        except HikerAPIError:
            raise
        except (aiohttp.ClientError, TimeoutError, OSError) as exc:
            raise HikerAPIError("Instagram media download failed") from exc
        finally:
            with contextlib.suppress(OSError):
                temporary.unlink()

    def _normalize_collection(self, data: Any, *, source: str) -> list[InstagramItem]:
        raw_items = data
        if (
            isinstance(data, list)
            and len(data) == 2
            and isinstance(data[0], list)
            and (data[1] is None or isinstance(data[1], str))
        ):
            raw_items = data[0]
        if not isinstance(raw_items, list):
            raise HikerAPIError("HikerAPI returned an invalid media collection")
        normalized: list[InstagramItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item_id = raw.get("pk") or raw.get("id")
            if item_id is None:
                continue
            product_type = str(raw.get("product_type") or "")
            kind: InstagramKind
            if source == "story" or product_type == "story":
                kind = "story"
            elif product_type in {"clips", "reels", "reel"}:
                kind = "reel"
            else:
                kind = "post"
            normalized.append(
                InstagramItem(
                    item_id=str(item_id),
                    kind=kind,
                    code=str(raw.get("code") or ""),
                    taken_at=str(raw.get("taken_at") or raw.get("taken_at_ts") or ""),
                    caption=str(raw.get("caption_text") or ""),
                    raw=raw,
                )
            )
        return normalized

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session


def _read_key(path: str) -> str:
    return Path(path).expanduser().read_text(encoding="utf-8")


def _media_descriptors(raw: dict[str, Any]) -> list[str]:
    resources = raw.get("resources")
    nodes = resources if isinstance(resources, list) and resources else [raw]
    urls: list[str] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        video_url = node.get("video_url")
        if isinstance(video_url, str) and video_url:
            urls.append(video_url)
            continue
        versions = node.get("image_versions")
        candidates = list(versions) if isinstance(versions, list) else []
        image_v2 = node.get("image_versions2")
        if isinstance(image_v2, dict) and isinstance(image_v2.get("candidates"), list):
            candidates.extend(image_v2["candidates"])
        best = max(
            (candidate for candidate in candidates if isinstance(candidate, dict)),
            key=lambda candidate: (
                int(candidate.get("width") or 0) * int(candidate.get("height") or 0)
            ),
            default=None,
        )
        if isinstance(best, dict) and isinstance(best.get("url"), str):
            urls.append(best["url"])
            continue
        thumbnail = node.get("thumbnail_url")
        if isinstance(thumbnail, str) and thumbnail:
            urls.append(thumbnail)
    return list(dict.fromkeys(urls))


def _validate_media_url(url: str, base_url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" and not _is_local_test_url(parsed, base_url):
        raise HikerAPIError("Instagram media URL must use HTTPS")
    hostname = (parsed.hostname or "").lower()
    allowed = hostname.endswith((".cdninstagram.com", ".fbcdn.net"))
    if not allowed and not _is_same_host(url, base_url):
        raise HikerAPIError("Instagram media URL used an unexpected host")


def _is_same_host(url: str, base_url: str) -> bool:
    return urlparse(url).hostname == urlparse(base_url).hostname


def _is_local_test_url(parsed: ParseResult, base_url: str) -> bool:
    hostname = (parsed.hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost"} and hostname == urlparse(base_url).hostname


def _require_status(status: int, operation: str) -> None:
    if status != 200:
        raise HikerAPIError(f"{operation} failed with status {status}")


def _content_extension(content_type: str) -> str:
    extension = _CONTENT_EXTENSIONS.get(content_type)
    if extension is None:
        raise HikerAPIError("Instagram media had an unsupported content type")
    return extension


def _enforce_size(size: int, maximum: int) -> None:
    if size > maximum:
        raise HikerAPIError("Instagram media exceeded the download limit")
