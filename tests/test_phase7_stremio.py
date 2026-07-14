"""Offline contract tests for Stremio addon integrations."""

import json
from pathlib import Path

import httpx
import pytest

from app.clients.stremio_addon_client import StremioAddonClient
from app.config import Settings
from app.exceptions import ProviderConfigurationError
from app.providers.mediafusion import MediaFusionProvider
from app.providers.torrentio import TorrentioProvider
from app.schemas.search import SearchRequest
from app.schemas.stremio import StremioStream
from app.schemas.web import SearchQueryParams
from app.services.deduplication_service import deduplicate_results
from app.services.stremio_stream_service import normalize_stremio_stream
from app.utils.stremio_url import build_stremio_resource_url

HASH = "0123456789abcdef0123456789abcdef01234567"
MANIFEST_URL = "http://addon.test/config/manifest.json"
FIXTURES = Path(__file__).parent / "fixtures"


class FakeAddonHTTP:
    """Small response fixture that never performs network I/O."""

    def __init__(self, provider: str = "torrentio") -> None:
        self.paths: list[str] = []
        self.provider = provider

    async def get_response(self, path: str, *, params=None, headers=None):
        self.paths.append(path)
        if path.endswith("/manifest.json"):
            return httpx.Response(
                200,
                json={
                    "id": "test.addon",
                    "name": "Test Addon",
                    "version": "1.0",
                    "resources": [{"name": "stream", "types": ["movie", "series"]}],
                },
            )
        fixture = "mediafusion_streams.json" if self.provider == "mediafusion" else "torrentio_streams.json"
        return httpx.Response(200, json=json.loads((FIXTURES / fixture).read_text()))

    async def close(self) -> None:
        pass


def _settings(**overrides) -> Settings:
    values = {
        "torrentio_manifest_url": MANIFEST_URL,
        "mediafusion_manifest_url": MANIFEST_URL,
        "stremio_addon_allow_private_hosts": True,
        "app_secret_key": "x" * 64,
    }
    values.update(overrides)
    return Settings(**values)


def test_resource_url_preserves_opaque_config_path():
    assert build_stremio_resource_url(MANIFEST_URL, "stream", "series", "tt1234567:1:2") == (
        "http://addon.test/config/stream/series/tt1234567%3A1%3A2.json"
    )


@pytest.mark.asyncio
async def test_generic_client_fetches_manifest_and_streams_with_aliases():
    fake = FakeAddonHTTP()
    client = StremioAddonClient(
        MANIFEST_URL,
        provider_slug="test",
        timeout_seconds=2,
        cache_ttl_seconds=120,
        max_items=10,
        max_response_bytes=1024 * 1024,
        max_redirects=1,
        allow_private_hosts=True,
        http_client=fake,
    )

    manifest = await client.get_manifest()
    response = await client.get_streams("series", "tt1234567:1:2")

    assert manifest.name == "Test Addon"
    assert response.streams[0].info_hash == HASH
    assert fake.paths == ["/config/manifest.json", "/config/stream/series/tt1234567%3A1%3A2.json"]


def test_stream_normalization_classifies_capabilities_without_fetching_urls():
    magnet_result = normalize_stremio_stream(
        StremioStream.model_validate(
            {
                "name": "Movie 1080p",
                "url": f"magnet:?xt=urn:btih:{HASH}",
                "sources": ["tracker:udp://tracker.example:80/announce", "dht:ignored"],
            }
        ),
        "torrentio",
        "movie",
        "tt1234567",
    )
    http_result = normalize_stremio_stream(
        StremioStream.model_validate({"title": "Live", "url": "https://stream.example/live.m3u8"}),
        "mediafusion",
        "movie",
        "tt1234567",
    )

    assert magnet_result.download_capability == "magnet"
    assert magnet_result.info_hash == HASH
    assert magnet_result.trackers == ["udp://tracker.example:80/announce"]
    assert http_result.download_capability == "http_stream"
    assert http_result.source_url == "https://stream.example/live.m3u8"


@pytest.mark.asyncio
async def test_torrentio_search_uses_imdb_id_and_mediafusion_rejects_anime():
    fake = FakeAddonHTTP()
    settings = _settings()
    provider = TorrentioProvider(settings, http_client=fake)
    results = await provider.search(SearchRequest(query="Movie", media_type="movie", imdb_id="tt1234567"))

    assert results[0].provider == "torrentio"
    assert fake.paths[-1].endswith("/stream/movie/tt1234567.json")

    mediafusion = MediaFusionProvider(settings, http_client=FakeAddonHTTP("mediafusion"))
    with pytest.raises(ProviderConfigurationError, match="does not support"):
        await mediafusion.search(SearchRequest(query="Anime", media_type="anime", imdb_id="tt1234567"))


def test_web_schema_validates_imdb_id_without_lookup():
    params = SearchQueryParams(query="Movie", media_type="movie", imdb_id=" TT1234567 ")
    assert params.imdb_id == "tt1234567"
    assert params.to_search_request().imdb_id == "tt1234567"
    with pytest.raises(ValueError):
        SearchQueryParams(query="Movie", imdb_id="movie-title")


def test_capability_merge_keeps_strongest_and_all_providers():
    first = normalize_stremio_stream(
        StremioStream.model_validate({"title": "Movie", "infoHash": HASH}),
        "torrentio",
        "movie",
        "tt1234567",
    )
    second = first.model_copy(update={"provider": "mediafusion", "download_capability": "external", "seeders": 42})
    merged = deduplicate_results([first, second])

    assert len(merged) == 1
    assert merged[0].providers == ["torrentio", "mediafusion"]
    assert merged[0].download_capability == "magnet"
    assert merged[0].seeders == 42
