"""Tests for HikerAPI normalization, secure downloads, and monitor deduplication."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import time_machine
from aiohttp import web
from pydantic import ValidationError

from ductor_bot.config import AgentConfig, InstagramMonitorConfig
from ductor_bot.infra.json_store import load_json
from ductor_bot.instagram.client import (
    HikerAPIClient,
    HikerAPIError,
    InstagramItem,
    _media_descriptors,
)
from ductor_bot.instagram.observer import NO_REACTION_TOKEN, InstagramObserver
from ductor_bot.workspace.paths import DuctorPaths


def _item(
    item_id: str, *, kind: str = "post", taken_at: str = "2026-08-21T10:00:00Z"
) -> InstagramItem:
    return InstagramItem(
        item_id=item_id,
        kind=kind,  # type: ignore[arg-type]
        code=f"code-{item_id}",
        taken_at=taken_at,
        caption=f"caption {item_id}",
        raw={"pk": item_id, "image_versions": [{"url": "https://x.cdninstagram.com/a.jpg"}]},
    )


class FakeClient:
    def __init__(self, items: list[InstagramItem], media_path: Path) -> None:
        self.items = items
        self.media_path = media_path
        self.resolve_calls = 0
        self.download_calls: list[str] = []
        self.closed = False

    async def resolve_user_id(self, _username: str) -> str:
        self.resolve_calls += 1
        return "123"

    async def fetch_items(self, _user_id: str) -> list[InstagramItem]:
        return list(self.items)

    async def download_item(self, item: InstagramItem, _target_dir: Path) -> list[Path]:
        self.download_calls.append(item.item_id)
        return [self.media_path]

    async def close(self) -> None:
        self.closed = True


def _config(tmp_path: Path, *, enabled: bool = True) -> AgentConfig:
    return AgentConfig(
        allowed_user_ids=[449932774],
        instagram_monitor=InstagramMonitorConfig(
            enabled=enabled,
            username="@Anya.Example",
            chat_id=449932774,
            api_key_file=str(tmp_path / "hiker.key"),
            poll_interval_seconds=60,
        ),
    )


def test_config_normalizes_username_and_rejects_fast_polling(tmp_path: Path) -> None:
    config = _config(tmp_path)
    assert config.instagram_monitor.username == "anya.example"
    with pytest.raises(ValidationError):
        InstagramMonitorConfig(poll_interval_seconds=59)


def test_media_descriptors_prefers_video_and_expands_carousel() -> None:
    raw = {
        "resources": [
            {"video_url": "https://a.cdninstagram.com/video.mp4"},
            {
                "image_versions": [
                    {"url": "https://a.cdninstagram.com/small.jpg", "width": 10, "height": 10},
                    {"url": "https://a.cdninstagram.com/large.jpg", "width": 20, "height": 20},
                ]
            },
        ]
    }
    assert _media_descriptors(raw) == [
        "https://a.cdninstagram.com/video.mp4",
        "https://a.cdninstagram.com/large.jpg",
    ]


async def test_client_fetches_and_downloads_actual_media(
    aiohttp_server: Any,
    tmp_path: Path,
) -> None:
    async def user(_request: web.Request) -> web.Response:
        assert _request.headers["User-Agent"].startswith("SisterAgent/")
        assert _request.headers["x-access-key"] == "test-key"
        return web.json_response({"pk": "123"})

    async def feed(request: web.Request) -> web.Response:
        base = f"{request.scheme}://{request.host}"
        return web.json_response(
            [[{"pk": "f1", "code": "ABC", "image_versions": [{"url": f"{base}/image"}]}], None]
        )

    async def stories(request: web.Request) -> web.Response:
        base = f"{request.scheme}://{request.host}"
        return web.json_response(
            [{"pk": "s1", "product_type": "story", "video_url": f"{base}/video"}]
        )

    async def image(_request: web.Request) -> web.Response:
        assert _request.headers["User-Agent"].startswith("SisterAgent/")
        return web.Response(body=b"jpeg", content_type="image/jpeg")

    async def video(_request: web.Request) -> web.Response:
        assert _request.headers["User-Agent"].startswith("SisterAgent/")
        return web.Response(body=b"mp4", content_type="video/mp4")

    app = web.Application()
    app.router.add_get("/v1/user/by/username", user)
    app.router.add_get("/v1/user/medias/chunk", feed)
    app.router.add_get("/v1/user/stories", stories)
    app.router.add_get("/image", image)
    app.router.add_get("/video", video)
    server = await aiohttp_server(app)
    key = tmp_path / "key"
    key.write_text("test-key", encoding="utf-8")
    client = HikerAPIClient(str(key), base_url=str(server.make_url("/")))

    assert await client.resolve_user_id("anya") == "123"
    items = await client.fetch_items("123")
    assert {(item.kind, item.item_id) for item in items} == {("post", "f1"), ("story", "s1")}
    downloaded = await client.download_item(items[1], tmp_path / "media")
    assert downloaded[0].suffix == ".mp4"
    assert downloaded[0].read_bytes() == b"mp4"
    await client.close()


async def test_fixture_journey_retries_media_batch_then_suppresses_duplicates(
    aiohttp_server: Any,
    tmp_path: Path,
) -> None:
    """Exercise seed, reel/story media, retry, delivery, and dedup as one journey."""
    current: dict[str, list[dict[str, Any]]] = {
        "feed": [{"pk": "old-post", "code": "OLD", "taken_at": 1}],
        "stories": [],
    }

    async def user(_request: web.Request) -> web.Response:
        return web.json_response({"pk": "123"})

    async def feed(_request: web.Request) -> web.Response:
        return web.json_response([current["feed"], None])

    async def stories(_request: web.Request) -> web.Response:
        return web.json_response(current["stories"])

    async def image(_request: web.Request) -> web.Response:
        return web.Response(body=b"fixture-image", content_type="image/jpeg")

    async def video(_request: web.Request) -> web.Response:
        return web.Response(body=b"fixture-video", content_type="video/mp4")

    app = web.Application()
    app.router.add_get("/v1/user/by/username", user)
    app.router.add_get("/v1/user/medias/chunk", feed)
    app.router.add_get("/v1/user/stories", stories)
    app.router.add_get("/fixture.jpg", image)
    app.router.add_get("/fixture.mp4", video)
    server = await aiohttp_server(app)
    base_url = str(server.make_url("/"))
    key = tmp_path / "key"
    key.write_text("test-key", encoding="utf-8")
    client = HikerAPIClient(str(key), base_url=base_url)
    paths = DuctorPaths(ductor_home=tmp_path / "ductor")
    observer = InstagramObserver(
        _config(tmp_path),
        paths,
        client=client,
    )
    wake = AsyncMock(side_effect=[None, "What a mood 😍"])
    observer.set_wake_handler(wake)

    assert await observer.poll_once() == 0
    wake.assert_not_awaited()

    current["feed"].append(
        {
            "pk": "new-reel",
            "code": "REEL",
            "product_type": "clips",
            "taken_at": 2,
            "video_url": f"{base_url}fixture.mp4",
        }
    )
    current["stories"].append(
        {
            "pk": "new-story",
            "product_type": "story",
            "taken_at": 3,
            "image_versions": [{"url": f"{base_url}fixture.jpg"}],
        }
    )

    assert await observer.poll_once() == 0
    assert await observer.poll_once() == 1
    assert await observer.poll_once() == 0
    assert wake.await_count == 2

    retry_prompt = wake.await_args_list[0].args[1]
    delivered_prompt = wake.await_args_list[1].args[1]
    for prompt in (retry_prompt, delivered_prompt):
        assert "ITEM 1 — reel" in prompt
        assert "ITEM 2 — story" in prompt
        assert ".mp4" in prompt
        assert ".jpg" in prompt

    state = load_json(paths.instagram_monitor_state_path)
    assert state is not None
    assert "reel:new-reel" in state["seen"]
    assert "story:new-story" in state["seen"]
    await client.close()


async def test_client_rejects_unexpected_media_host(tmp_path: Path) -> None:
    key = tmp_path / "key"
    key.write_text("test-key", encoding="utf-8")
    client = HikerAPIClient(str(key))
    bad = _item("bad")
    bad.raw["image_versions"] = [{"url": "https://example.com/private"}]
    with pytest.raises(HikerAPIError, match="unexpected host"):
        await client.download_item(bad, tmp_path / "media")
    await client.close()


async def test_first_poll_seeds_without_sending(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value="reaction")
    observer.set_wake_handler(wake)

    assert await observer.poll_once() == 0
    wake.assert_not_awaited()
    assert client.download_calls == []


async def test_new_item_wakes_once_with_real_media_path(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value="Красиво 😍")
    observer.set_wake_handler(wake)
    await observer.poll_once()

    client.items.append(_item("new", kind="reel", taken_at="2026-08-21T11:00:00Z"))
    assert await observer.poll_once() == 1
    assert await observer.poll_once() == 0
    wake.assert_awaited_once()
    assert wake.await_args is not None
    prompt = wake.await_args.args[1]
    assert "ITEM 1 — reel" in prompt
    assert str(media) in prompt
    assert NO_REACTION_TOKEN in prompt
    assert "Return only the message for Anya" in prompt


async def test_multiple_new_items_are_evaluated_in_one_turn(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value="What a view 😍")
    observer.set_wake_handler(wake)
    await observer.poll_once()
    client.items.extend(
        [
            _item("new-1", kind="story", taken_at="2026-08-21T11:00:00Z"),
            _item("new-2", kind="reel", taken_at="2026-08-21T11:01:00Z"),
        ]
    )

    assert await observer.poll_once() == 1
    wake.assert_awaited_once()
    assert wake.await_args is not None
    prompt = wake.await_args.args[1]
    assert "ITEM 1 — story" in prompt
    assert "ITEM 2 — reel" in prompt


async def test_no_reaction_keeps_daily_opportunity_open(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value=NO_REACTION_TOKEN)
    observer.set_wake_handler(wake)

    with time_machine.travel("2026-08-23 12:00:00+00:00"):
        await observer.poll_once()
        client.items.append(_item("ordinary"))
        assert await observer.poll_once() == 0
        wake.return_value = "Вот это уже сильно 😈"
        client.items.append(_item("worth-it", taken_at="2026-08-23T12:05:00Z"))
        assert await observer.poll_once() == 1

    assert wake.await_count == 2


async def test_daily_cap_observes_later_items_without_another_turn(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    paths = DuctorPaths(ductor_home=tmp_path)
    observer = InstagramObserver(
        _config(tmp_path),
        paths,
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value="Красота ❤️‍🔥")
    observer.set_wake_handler(wake)

    with time_machine.travel("2026-08-23 12:00:00+00:00"):
        await observer.poll_once()
        client.items.append(_item("first"))
        assert await observer.poll_once() == 1
        client.items.append(_item("later", taken_at="2026-08-23T16:00:00Z"))
        assert await observer.poll_once() == 0

    wake.assert_awaited_once()
    state = load_json(paths.instagram_monitor_state_path)
    assert state is not None
    assert state["last_reaction_date"] == "2026-08-23"
    assert "post:later" in state["seen"]


async def test_failed_wake_is_retried_and_not_marked_seen(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    media.write_bytes(b"image")
    client = FakeClient([_item("old")], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    wake = AsyncMock(return_value=None)
    observer.set_wake_handler(wake)
    await observer.poll_once()
    client.items.append(_item("new"))

    assert await observer.poll_once() == 0
    assert await observer.poll_once() == 0
    assert wake.await_count == 2


async def test_disabled_observer_does_not_start(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    client = FakeClient([], media)
    observer = InstagramObserver(
        _config(tmp_path, enabled=False),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )
    await observer.start()
    assert observer._task is None
    await observer.stop()
    assert client.closed is True


async def test_enabled_observer_can_be_wired_after_startup(tmp_path: Path) -> None:
    media = tmp_path / "media.jpg"
    client = FakeClient([], media)
    observer = InstagramObserver(
        _config(tmp_path),
        DuctorPaths(ductor_home=tmp_path),
        client=client,  # type: ignore[arg-type]
    )

    await observer.start()
    assert observer._task is not None
    observer.set_wake_handler(AsyncMock(return_value="reaction"))
    await observer.stop()
    assert client.closed is True
