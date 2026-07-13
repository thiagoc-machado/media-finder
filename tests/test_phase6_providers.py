"""Unit and endpoint coverage for the Phase 6 real providers."""

from copy import deepcopy

import httpx
import pytest
from defusedxml import ElementTree
from pydantic import ValidationError

from app.clients.http_client import ProviderHTTPClient
from app.config import Settings
from app.exceptions import ProviderAuthenticationError, ProviderInvalidResponseError
from app.providers.jackett import JackettProvider
from app.providers.mock import MockProvider
from app.providers.prowlarr import ProwlarrProvider
from app.providers.registry import ProviderRegistry
from app.schemas.search import SearchRequest

pytestmark = pytest.mark.asyncio


class FakeProviderHTTP:
    """Small transport double that records safe paths and parameters only."""

    def __init__(self, *, json_payloads=None, xml_payloads=None, xml_errors=None):
        self.json_payloads = json_payloads or {}
        self.xml_payloads = xml_payloads or {}
        self.xml_errors = xml_errors or {}
        self.json_calls = []
        self.xml_calls = []

    async def get_json(self, path, *, params=None, headers=None):
        self.json_calls.append((path, dict(params or {}), dict(headers or {})))
        return deepcopy(self.json_payloads[path])

    async def get_xml(self, path, *, params=None, headers=None):
        self.xml_calls.append((path, dict(params or {})))
        if path in self.xml_errors:
            raise self.xml_errors[path]
        payload = self.xml_payloads.get((path, (params or {}).get("t")))
        if payload is None:
            payload = self.xml_payloads[path]
        return ElementTree.fromstring(payload)

    async def close(self):
        return None


def provider_settings(**overrides):
    values = {
        "app_env": "test",
        "prowlarr_api_key": "prowlarr-test-key",
        "jackett_api_key": "jackett-test-key",
        "prowlarr_cache_ttl_seconds": 60,
        "jackett_cache_ttl_seconds": 60,
        "provider_rate_limit_requests": 100,
    }
    values.update(overrides)
    return Settings(**values)


def prowlarr_payloads():
    return {
        "/api/v1/system/status": {"version": "1.42.0"},
        "/api/v1/indexer": [
            {
                "id": 7,
                "name": "Primary Indexer",
                "enable": True,
                "protocol": "torrent",
                "privacy": "public",
                "categories": [{"id": 2000}, {"id": 5000}],
            },
            {"id": 8, "name": "Disabled Indexer", "enable": False, "categories": []},
        ],
        "/api/v1/search": [
            {
                "title": "Example 1080p",
                "guid": "https://indexer.example/item/1",
                "indexer": "Primary Indexer",
                "indexerId": 7,
                "downloadUrl": "https://indexer.example/download?id=1&apikey=secret",
                "infoHash": "A" * 40,
                "size": 1234,
                "seeders": 12,
                "leechers": 2,
                "categories": [{"id": 2000}],
                "publishDate": "2025-01-02T03:04:05Z",
            }
        ],
    }


CAPS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<caps xmlns="http://torznab.com/schemas/2015/feed">
  <search available="yes" supportedParams="q" />
  <movie-search available="yes" supportedParams="q,imdbid" />
  <tv-search available="yes" supportedParams="q,season,ep" />
  <categories><category id="2000" name="Movies" /><category id="5000" name="TV" /></categories>
</caps>"""

RESULTS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>
  <item>
    <title>Example Series S02E03 1080p</title>
    <guid>jackett-result-1</guid>
    <link>https://indexer.example/item/2?apikey=secret</link>
    <pubDate>Thu, 02 Jan 2025 03:04:05 GMT</pubDate>
    <enclosure url="magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB" length="2048" />
    <torznab:attr name="category" value="5000" />
    <torznab:attr name="seeders" value="8" />
    <torznab:attr name="peers" value="3" />
  </item>
</channel></rss>"""


async def test_provider_http_client_maps_auth_and_invalid_payloads():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth":
            return httpx.Response(401, request=request)
        if request.url.path == "/xml":
            return httpx.Response(
                200,
                content=b'<!DOCTYPE foo [<!ENTITY xxe "secret">]><root>&xxe;</root>',
                request=request,
            )
        return httpx.Response(200, content=b"not-json", request=request)

    injected = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://provider.test",
    )
    client = ProviderHTTPClient("http://provider.test", timeout_seconds=2, client=injected)
    with pytest.raises(ProviderAuthenticationError):
        await client.get_json("/auth")
    with pytest.raises(ProviderInvalidResponseError):
        await client.get_json("/invalid")
    with pytest.raises(ProviderInvalidResponseError):
        await client.get_xml("/xml")
    await client.close()
    await injected.aclose()


async def test_prowlarr_health_indexers_search_and_cache_are_safe():
    fake = FakeProviderHTTP(json_payloads=prowlarr_payloads())
    provider = ProwlarrProvider(provider_settings(), http_client=fake)

    health = await provider.health_check()
    assert health.available is True
    assert health.version == "1.42.0"

    indexers = await provider.list_indexers()
    assert [item.id for item in indexers] == ["7"]
    assert indexers[0].capabilities == ["movie", "series"]

    request = SearchRequest(
        query="Example",
        media_type="movie",
        provider_indexers={"prowlarr": ["7"]},
    )
    results = await provider.search(request)
    cached = await provider.search(request)
    assert len(results) == 1
    assert cached[0].info_hash == "a" * 40
    assert cached[0].magnet_url.startswith("magnet:?xt=urn%3Abtih%3A")
    assert cached[0].source_url == "https://indexer.example/download?id=1"
    assert provider.last_metrics is not None and provider.last_metrics.cached is True
    search_calls = [call for call in fake.json_calls if call[0] == "/api/v1/search"]
    assert len(search_calls) == 1
    assert search_calls[0][1]["indexerIds"] == "7"
    assert search_calls[0][1]["type"] == "moviesearch"
    assert "secret" not in repr(fake.json_calls)


async def test_prowlarr_without_key_is_unavailable_without_request():
    fake = FakeProviderHTTP(json_payloads=prowlarr_payloads())
    provider = ProwlarrProvider(provider_settings(prowlarr_api_key=""), http_client=fake)

    health = await provider.health_check()
    assert health.available is False
    assert "key" in (health.error or "").casefold()
    assert fake.json_calls == []


async def test_jackett_caps_search_normalization_and_indexer_selection():
    path = "/api/v2.0/indexers/demo/results/torznab/api"
    paths = {(path, "caps"): CAPS_XML, (path, "tvsearch"): RESULTS_XML}
    fake = FakeProviderHTTP(xml_payloads=paths)
    provider = JackettProvider(provider_settings(jackett_indexers="demo"), http_client=fake)

    health = await provider.health_check()
    assert health.available is True
    capabilities = await provider.get_capabilities("demo")
    assert capabilities.movie_search is True
    assert capabilities.tv_search is True
    assert capabilities.categories[5000] == "TV"

    request = SearchRequest(
        query="Example",
        media_type="series",
        season=2,
        episode=3,
        provider_indexers={"jackett": ["demo"]},
    )
    results = await provider.search(request)
    assert len(results) == 1
    assert results[0].provider == "jackett"
    assert results[0].info_hash == "b" * 40
    assert results[0].source_url == "https://indexer.example/item/2"
    search_call = fake.xml_calls[-1]
    assert search_call[1]["t"] == "tvsearch"
    assert search_call[1]["season"] == "2"
    assert search_call[1]["ep"] == "3"
    assert search_call[1]["apikey"] == "jackett-test-key"


async def test_jackett_keeps_partial_indexer_success():
    good_path = "/api/v2.0/indexers/all/results/torznab/api"
    bad_path = "/api/v2.0/indexers/bad/results/torznab/api"
    fake = FakeProviderHTTP(
        xml_payloads={(good_path, "caps"): CAPS_XML, (good_path, "search"): RESULTS_XML},
        xml_errors={bad_path: ProviderInvalidResponseError("Provider returned invalid XML")},
    )
    provider = JackettProvider(provider_settings(jackett_indexers="all,bad"), http_client=fake)

    results = await provider.search(SearchRequest(query="Example"))
    assert len(results) == 1
    assert provider.last_metrics is not None
    assert provider.last_metrics.indexers_used == ["all", "bad"]


async def test_provider_indexer_endpoints_return_safe_projections(client, monkeypatch):
    prowlarr_http = FakeProviderHTTP(json_payloads=prowlarr_payloads())
    jackett_http = FakeProviderHTTP(
        xml_payloads={
            ("/api/v2.0/indexers/demo/results/torznab/api", "caps"): CAPS_XML,
        }
    )
    registry = ProviderRegistry()
    registry.register(ProwlarrProvider(provider_settings(), http_client=prowlarr_http), priority=10)
    registry.register(
        JackettProvider(provider_settings(jackett_indexers="demo"), http_client=jackett_http), priority=20
    )
    monkeypatch.setattr(client._transport.app.state, "provider_registry", registry)

    prowlarr_response = await client.get("/providers/prowlarr/indexers")
    jackett_response = await client.get("/providers/jackett/indexers")
    assert prowlarr_response.status_code == 200
    assert prowlarr_response.json()[0]["name"] == "Primary Indexer"
    assert jackett_response.status_code == 200
    assert jackett_response.json()[0]["name"] == "demo"
    assert "jackett-test-key" not in jackett_response.text


async def test_search_combines_mock_providers_and_keeps_pipeline_contract(client, monkeypatch):
    prowlarr_http = FakeProviderHTTP(json_payloads=prowlarr_payloads())
    jackett_path = "/api/v2.0/indexers/demo/results/torznab/api"
    jackett_http = FakeProviderHTTP(
        xml_payloads={(jackett_path, "caps"): CAPS_XML, (jackett_path, "search"): RESULTS_XML}
    )
    registry = ProviderRegistry()
    registry.register(MockProvider(), priority=10)
    registry.register(ProwlarrProvider(provider_settings(), http_client=prowlarr_http), priority=20)
    registry.register(
        JackettProvider(provider_settings(jackett_indexers="demo"), http_client=jackett_http), priority=30
    )
    monkeypatch.setattr(client._transport.app.state, "provider_registry", registry)

    response = await client.get(
        "/search",
        params={"query": "Example", "providers": ["mock", "prowlarr", "jackett"]},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "prowlarr" in response.text
    assert "jackett" in response.text
    assert "Example" in response.text


async def test_provider_registration_flags_are_respected():
    settings = provider_settings(prowlarr_enabled=False, jackett_enabled=True)
    registry = ProviderRegistry()
    registry.register(JackettProvider(settings, http_client=FakeProviderHTTP()), priority=20)
    assert [provider.slug for provider in registry.enabled_providers()] == ["jackett"]


async def test_provider_configuration_validates_urls_and_runtime_limits():
    settings = provider_settings(prowlarr_url="http://prowlarr:9696/", provider_cache_max_items=10)
    assert settings.prowlarr_url == "http://prowlarr:9696"
    assert settings.provider_cache_max_items == 10

    with pytest.raises(ValidationError):
        Settings(prowlarr_url="ftp://prowlarr:9696", app_env="test")
    with pytest.raises(ValidationError):
        Settings(jackett_url="http://jackett:9117/?apikey=secret", app_env="test")
