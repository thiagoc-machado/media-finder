"""Unit tests for the synchronous qbittorrent-api adapter."""

import asyncio

import pytest

from app.config import Settings
from app.exceptions import (
    CategoryNotConfiguredError,
    CategoryNotFoundError,
    QBitTorrentTimeoutError,
)
from app.services.qbittorrent_service import QBitTorrentService

pytestmark = pytest.mark.asyncio
HASH = "b" * 40


class LoginFailed(Exception):
    """Exception-shaped fake for qbittorrent-api authentication failures."""


class FakeClient:
    def __init__(self, *, categories=None, existing=None, add_result="Ok.", add_visible=True):
        self.categories = categories or {"movies": {"savePath": "/downloads/movies"}, "series": {}}
        self.existing = set(existing or [])
        self.add_result = add_result
        self.add_visible = add_visible
        self.login_count = 0
        self.add_calls = []

    def auth_log_in(self):
        self.login_count += 1

    def app_version(self):
        return "4.6.0"

    def torrents_categories(self):
        return self.categories

    def torrents_info(self, torrent_hashes=None):
        if torrent_hashes in self.existing:
            return [
                {
                    "hash": HASH,
                    "name": "Example",
                    "state": "downloading",
                    "progress": 0.5,
                    "downloaded": 50,
                    "size": 100,
                    "dlspeed": 10,
                    "eta": 20,
                    "category": "movies",
                    "tags": "media-finder, provider:mock",
                }
            ]
        return []

    def torrents_add(self, **kwargs):
        self.add_calls.append(kwargs)
        if self.add_visible:
            self.existing.add(HASH)
        return self.add_result


def settings(**kwargs):
    return Settings(app_env="test", app_secret_key="x" * 40, **kwargs)


async def test_health_auth_categories_and_add_use_threaded_client(monkeypatch):
    client = FakeClient()
    calls = []

    async def fake_to_thread(function):
        calls.append(function)
        return function()

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    service = QBitTorrentService(settings(), client_factory=lambda **kwargs: client)

    health = await service.health_check()
    categories = await service.list_categories()
    outcome = await service.add_torrent(
        f"magnet:?xt=urn:btih:{HASH}",
        "movie",
        "mock",
        quality="1080p",
        languages=["PT-BR"],
        paused=True,
    )

    assert health.available is True
    assert categories["movies"].save_path == "/downloads/movies"
    assert outcome.status == "queued"
    assert client.login_count == 1
    assert len(calls) >= 5
    assert client.add_calls[0] == {
        "urls": f"magnet:?xt=urn%3Abtih%3A{HASH}",
        "category": "movies",
        "tags": ["media-finder", "provider:mock", "type:movie", "quality:1080p", "language:pt-br"],
        "is_paused": True,
    }
    assert "save_path" not in client.add_calls[0]


async def test_duplicate_ambiguous_and_missing_categories(monkeypatch):
    calls = []

    async def fake_to_thread(function):
        calls.append(function)
        return function()

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)
    duplicate_client = FakeClient(existing=[HASH])
    duplicate = QBitTorrentService(settings(), client_factory=lambda **kwargs: duplicate_client)
    assert (await duplicate.add_torrent(f"magnet:?xt=urn:btih:{HASH}", "movie", "mock")).status == "duplicate"
    assert duplicate_client.add_calls == []

    ambiguous_client = FakeClient(add_result="Fails.", add_visible=False)
    ambiguous = QBitTorrentService(settings(), client_factory=lambda **kwargs: ambiguous_client)
    failed = await ambiguous.add_torrent(f"magnet:?xt=urn:btih:{HASH}", "movie", "mock")
    assert failed.status == "failed"

    missing = QBitTorrentService(
        settings(),
        client_factory=lambda **kwargs: FakeClient(categories={"series": {}}),
    )
    with pytest.raises(CategoryNotFoundError):
        await missing.add_torrent(f"magnet:?xt=urn:btih:{HASH}", "movie", "mock")

    with pytest.raises(CategoryNotConfiguredError):
        await duplicate.add_torrent(f"magnet:?xt=urn:btih:{HASH}", "anime", "mock")


async def test_authentication_failure_and_operation_timeout(monkeypatch):
    class BadClient(FakeClient):
        def auth_log_in(self):
            raise LoginFailed("invalid")

    async def immediate(function):
        return function()

    monkeypatch.setattr(asyncio, "to_thread", immediate)
    unavailable = QBitTorrentService(settings(), client_factory=lambda **kwargs: BadClient())
    health = await unavailable.health_check()
    assert health.available is False
    assert health.error == "Authentication failed"

    client = FakeClient()
    service = QBitTorrentService(
        settings(qbittorrent_operation_timeout_seconds=0.01), client_factory=lambda **kwargs: client
    )
    service._client = client

    async def slow(function):
        await asyncio.sleep(0.1)
        return function()

    monkeypatch.setattr(asyncio, "to_thread", slow)
    with pytest.raises(QBitTorrentTimeoutError):
        await service.torrent_exists(HASH)
