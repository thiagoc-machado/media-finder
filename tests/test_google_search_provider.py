"""Offline tests for the API-free public Google search provider."""

import httpx
import pytest

from app.config import Settings
from app.providers.google_search import DuckDuckGoProvider, _parse_markdown_results
from app.schemas.search import SearchRequest


class FakeGoogleHTTP:
    def __init__(self, body: str):
        self.body = body
        self.calls = []

    async def get_response(self, path, *, params=None, headers=None, follow_redirects=False):
        self.calls.append((path, params, headers, follow_redirects))
        return httpx.Response(200, text=self.body)

    async def close(self):
        pass


def _settings(**overrides):
    values = {"app_secret_key": "x" * 64, "duckduckgo_search_enabled": True}
    values.update(overrides)
    return Settings(**values)


def test_markdown_fallback_extracts_duckduckgo_result_links():
    items = _parse_markdown_results(
        "## [Narnia.pdf - Google Drive](http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdrive.google.com%2Ffile%2Fd%2Fabc%2Fview)"
    )

    assert items == [
        (
            "http://duckduckgo.com/l/?uddg=https%3A%2F%2Fdrive.google.com%2Ffile%2Fd%2Fabc%2Fview",
            "Narnia.pdf - Google Drive",
        )
    ]


@pytest.mark.asyncio
async def test_public_google_search_uses_site_scope_and_filters_non_media():
    fake = FakeGoogleHTTP(
        '<a href="/url?q=https://drive.google.com/file/d/media/view&sa=U">Movie 1080p.mp4</a>'
        '<a href="/url?q=https://drive.google.com/file/d/icon/view&sa=U">icon.ico</a>'
        '<a href="/url?q=https://drive.google.com/file/d/audio/view&sa=U">soundtrack.mp3</a>'
        '<a href="/url?q=https://drive.google.com/file/d/image/view&sa=U">poster.jpg</a>'
        '<a href="/url?q=https://drive.google.com/drive/folders/folder123456/view&sa=U">Matrix folder</a>'
        '<a href="https://example.com/movie.mp4">External movie.mp4</a>'
    )
    provider = DuckDuckGoProvider(_settings(), http_client=fake)
    results = await provider.search(SearchRequest(query="Narnia", media_type="movie", file_type="pdf"))

    assert results == []
    assert fake.calls[0][0] == "/html/"
    assert fake.calls[0][1]["q"] == "site:drive.google.com Narnia"
    assert fake.calls[0][3] is True
    assert "text/html" in fake.calls[0][2]["Accept"]


@pytest.mark.asyncio
async def test_disabled_public_google_search_returns_no_results():
    provider = DuckDuckGoProvider(_settings(duckduckgo_search_enabled=False), http_client=FakeGoogleHTTP(""))
    assert await provider.search(SearchRequest(query="Movie")) == []


@pytest.mark.asyncio
async def test_other_search_targets_pdf_and_marks_it_for_local_storage():
    fake = FakeGoogleHTTP('<a href="https://drive.google.com/file/d/pdf123456789/view">Book.pdf</a>')
    provider = DuckDuckGoProvider(_settings(), http_client=fake)
    results = await provider.search(SearchRequest(query="Book", media_type="other"))

    assert results[0].media_type == "other"
    assert results[0].raw_data["media_kind"] == "pdf"
    assert fake.calls[0][1]["q"] == "site:drive.google.com Book"


@pytest.mark.asyncio
async def test_public_search_marks_torrent_files_for_qbittorrent():
    fake = FakeGoogleHTTP('<a href="https://drive.google.com/file/d/torrent123456789/view">Narnia.torrent</a>')
    provider = DuckDuckGoProvider(_settings(), http_client=fake)
    results = await provider.search(SearchRequest(query="Narnia", media_type="movie"))

    assert results[0].raw_data["media_kind"] == "torrent"
    assert results[0].download_capability == "external"


@pytest.mark.asyncio
async def test_public_search_supports_music_video_and_zip_filters():
    fake = FakeGoogleHTTP(
        '<a href="https://drive.google.com/file/d/music/view">Narnia soundtrack.mp3</a>'
        '<a href="https://drive.google.com/file/d/video/view">Narnia trailer.mp4</a>'
        '<a href="https://drive.google.com/file/d/archive/view">Narnia.zip</a>'
    )
    provider = DuckDuckGoProvider(_settings(), http_client=fake)

    music = await provider.search(SearchRequest(query="Narnia", file_type="music"))
    video = await provider.search(SearchRequest(query="Narnia", file_type="video"))
    archive = await provider.search(SearchRequest(query="Narnia", file_type="zip"))

    assert [item.raw_data["media_kind"] for item in music] == ["music"]
    assert [item.raw_data["media_kind"] for item in video] == ["video"]
    assert [item.raw_data["media_kind"] for item in archive] == ["zip"]


@pytest.mark.asyncio
async def test_duckduckgo_parses_redirect_to_drive_pdf():
    fake = FakeGoogleHTTP(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdrive.google.com%2Ffile%2Fd%2Fpdf123456789%2Fview">Narnia.pdf</a>'
    )
    provider = DuckDuckGoProvider(_settings(), http_client=fake)

    results = await provider.search(SearchRequest(query="Narnia", media_type="other"))

    assert results[0].title == "Narnia.pdf"
    assert results[0].raw_data["media_kind"] == "pdf"


@pytest.mark.asyncio
async def test_duckduckgo_accepts_drive_suffix_in_result_title():
    fake = FakeGoogleHTTP(
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdrive.google.com%2Ffile%2Fd%2Fpdf123456789%2Fview">'
        "As Crônicas de Nárnia.pdf - Google Drive</a>"
    )
    provider = DuckDuckGoProvider(_settings(), http_client=fake)

    results = await provider.search(SearchRequest(query="Narnia", media_type="other"))

    assert len(results) == 1
    assert results[0].title == "As Crônicas de Nárnia.pdf"
    assert results[0].raw_data["media_kind"] == "pdf"
