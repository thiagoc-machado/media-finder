"""Phase 5 qBittorrent contract and endpoint tests using a complete fake service."""

import re

import pytest
from sqlalchemy import select

from app import database
from app.exceptions import CategoryNotFoundError
from app.models.download_history import DownloadHistory
from app.schemas.download import (
    AddTorrentResult,
    CategoryValidationItem,
    CategoryValidationResult,
    QBitTorrentCategory,
    QBitTorrentHealth,
    TorrentStatus,
)
from app.services.qbittorrent_service import build_qbittorrent_tags

pytestmark = pytest.mark.asyncio
HASH = "a" * 40


class FakeQBitTorrentService:
    """Async fake that records only safe operation metadata."""

    def __init__(self, *, categories=None, available=True, exists=False, add_error=None):
        self.categories = categories or {"movies": QBitTorrentCategory(name="movies")}
        self.available = available
        self.exists = exists
        self.add_error = add_error
        self.added = []

    def get_category_for_media_type(self, media_type):
        return {"movie": "movies", "series": "series", "anime": None, "other": None}.get(media_type)

    async def health_check(self):
        return QBitTorrentHealth(available=self.available, version="test" if self.available else None)

    async def list_categories(self):
        if not self.available:
            from app.exceptions import QBitTorrentUnavailableError

            raise QBitTorrentUnavailableError("unavailable")
        return self.categories

    async def validate_configured_categories(self):
        names = {name.casefold() for name in self.categories}
        return CategoryValidationResult(
            categories=[
                CategoryValidationItem(
                    media_type=media_type,
                    configured_category=category,
                    exists=bool(category and category.casefold() in names),
                    available_for_download=bool(category and category.casefold() in names),
                )
                for media_type, category in {
                    "movie": "movies",
                    "series": "series",
                    "anime": None,
                    "other": None,
                }.items()
            ]
        )

    async def torrent_exists(self, info_hash):
        return self.exists

    async def add_torrent(self, magnet_url, media_type, provider, quality=None, languages=None, paused=False):
        if self.add_error:
            raise self.add_error
        self.added.append(
            {
                "magnet_url": magnet_url,
                "media_type": media_type,
                "provider": provider,
                "quality": quality,
                "languages": languages,
                "paused": paused,
            }
        )
        self.exists = True
        category = "series" if media_type == "series" else "movies"
        return AddTorrentResult(status="queued", info_hash=HASH, category=category, message="Added to qBittorrent")

    async def get_torrent(self, info_hash):
        if not self.exists:
            return None
        return TorrentStatus(
            info_hash=HASH,
            name="Example",
            state="downloading",
            progress=0.25,
            downloaded_bytes=25,
            total_size_bytes=100,
            download_speed=10,
            category="movies",
            tags=["media-finder"],
        )


def _token_and_csrf(text: str) -> tuple[str, str]:
    token = re.search(r'name="result_token" value="([^"]+)"', text)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', text)
    assert token and csrf
    return token.group(1), csrf.group(1)


async def test_download_uses_only_result_token_and_persists_safe_history(client, monkeypatch):
    fake = FakeQBitTorrentService()
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get("/search?query=Example&providers=mock", headers={"HX-Request": "true"})
    token, csrf = _token_and_csrf(search.text)
    assert (
        "Radarr/Sonarr will only import this download automatically if the media is already monitored." in search.text
    )

    response = await client.post(
        "/downloads",
        data={
            "result_token": token,
            "csrf_token": csrf,
            "paused": "false",
            "magnet_url": "magnet:?xt=urn:btih:" + "f" * 40,
            "category": "radarr",
        },
    )

    assert response.status_code == 200
    assert "Added to qBittorrent" in response.text
    assert fake.added[0]["media_type"] == "movie"
    assert fake.added[0]["magnet_url"] != "magnet:?xt=urn:btih:" + "f" * 40
    assert "magnet:?xt=urn:btih:" + HASH not in response.text
    with database.SessionLocal() as session:
        row = session.scalar(select(DownloadHistory).where(DownloadHistory.info_hash == "1" * 40))
        assert row is not None
        assert row.magnet_url is None
        assert row.category == "movies"
        assert row.status == "queued"


async def test_download_requires_csrf_and_rejects_expired_token(client):
    missing = await client.post("/downloads", data={"result_token": "missing"})
    assert missing.status_code == 403

    home = await client.get("/")
    _, csrf = _token_and_csrf(
        (await client.get("/search?query=Example&providers=mock", headers={"HX-Request": "true"})).text
    )
    expired = await client.post("/downloads", data={"result_token": "expired", "csrf_token": csrf})
    assert expired.status_code == 410
    assert "Result expired" in expired.text
    assert home.status_code == 200


async def test_anime_is_disabled_without_a_configured_category(client, monkeypatch):
    fake = FakeQBitTorrentService()
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get(
        "/search?query=Anime&providers=mock&media_type=anime",
        headers={"HX-Request": "true"},
    )
    token, csrf = _token_and_csrf(search.text)
    response = await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})
    assert response.status_code == 400
    assert "No qBittorrent category is configured" in response.text
    assert fake.added == []


async def test_duplicate_is_idempotent(client, monkeypatch):
    fake = FakeQBitTorrentService(exists=True)
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get("/search?query=Duplicate&providers=mock", headers={"HX-Request": "true"})
    token, csrf = _token_and_csrf(search.text)
    response = await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})
    assert response.status_code == 200
    assert "Already exists" in response.text
    assert fake.added == []


async def test_stale_local_history_does_not_block_readd(client, monkeypatch):
    fake = FakeQBitTorrentService()
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    with database.SessionLocal() as session:
        session.add(
            DownloadHistory(
                title="Old result",
                provider="torrentio",
                info_hash="1" * 40,
                media_type="movie",
                category="movies",
                status="queued",
                qbittorrent_hash="1" * 40,
            )
        )
        session.commit()

    search = await client.get("/search?query=Example&providers=mock", headers={"HX-Request": "true"})
    token, csrf = _token_and_csrf(search.text)
    response = await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})

    assert response.status_code == 200
    assert "Added to qBittorrent" in response.text
    assert len(fake.added) == 1


async def test_category_missing_and_status_refresh(client, monkeypatch):
    fake = FakeQBitTorrentService(
        categories={"series": QBitTorrentCategory(name="series")},
        add_error=CategoryNotFoundError("missing"),
    )
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get("/search?query=MissingCategory&providers=mock", headers={"HX-Request": "true"})
    token, csrf = _token_and_csrf(search.text)
    response = await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})
    assert response.status_code == 200
    assert "Configured qBittorrent category was not found" in response.text

    with database.SessionLocal() as session:
        row = session.scalar(select(DownloadHistory).where(DownloadHistory.title.like("MissingCategory%")))
        assert row is not None
        row.status = "queued"
        row.qbittorrent_hash = HASH
        session.commit()
        download_id = row.id
    fake.categories["movies"] = QBitTorrentCategory(name="movies")
    fake.exists = True
    status = await client.get(f"/downloads/{download_id}/status", headers={"HX-Request": "true"})
    assert status.status_code == 200
    assert "downloading" in status.text


async def test_series_download_uses_series_category(client, monkeypatch):
    fake = FakeQBitTorrentService(
        categories={
            "movies": QBitTorrentCategory(name="movies"),
            "series": QBitTorrentCategory(name="series"),
        }
    )
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get(
        "/search?query=SeriesDownload&providers=mock&media_type=series&season=1&episode=1",
        headers={"HX-Request": "true"},
    )
    token, csrf = _token_and_csrf(search.text)
    response = await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})
    assert response.status_code == 200
    assert fake.added[0]["media_type"] == "series"
    with database.SessionLocal() as session:
        row = session.scalar(select(DownloadHistory).where(DownloadHistory.title.like("SeriesDownload%")))
        assert row is not None
        assert row.category == "series"


async def test_download_history_page_is_paginated_and_safe(client, monkeypatch):
    fake = FakeQBitTorrentService()
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    search = await client.get("/search?query=HistoryDownload&providers=mock", headers={"HX-Request": "true"})
    token, csrf = _token_and_csrf(search.text)
    await client.post("/downloads", data={"result_token": token, "csrf_token": csrf})
    response = await client.get("/downloads")
    assert response.status_code == 200
    assert "HistoryDownload" in response.text
    assert "Refresh status" in response.text
    assert "magnet:?xt=urn:btih:" not in response.text


async def test_qbittorrent_read_only_endpoints_are_safe(client, monkeypatch):
    fake = FakeQBitTorrentService()
    monkeypatch.setattr(client._transport.app.state, "qbittorrent_service", fake)
    health = await client.get("/qbittorrent/health")
    categories = await client.get("/qbittorrent/categories")
    assert health.status_code == 200
    assert health.json()["available"] is True
    assert categories.status_code == 200
    assert categories.json()["valid_categories"] == ["movies"]
    assert "password" not in categories.text.casefold()


async def test_qbittorrent_tags_are_bounded_and_sanitized():
    tags = build_qbittorrent_tags(
        " Mock Provider ",
        "movie",
        "1080p/../../secret",
        ["PT-BR", "PT-BR", "https://example.invalid/secret", ""],
    )
    assert tags[0] == "media-finder"
    assert "provider:mock-provider" in tags
    assert "type:movie" in tags
    assert len(tags) <= 8
    assert all(len(tag) <= 64 for tag in tags)
    assert all("/" not in tag and "https" not in tag for tag in tags)
