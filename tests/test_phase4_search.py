"""HTTP, template, and in-memory security coverage for the Phase 4 UI."""

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app import database
from app.models.search_history import SearchHistory
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry
from app.schemas.search import SearchResult
from app.schemas.web import SearchQueryParams
from app.services.rate_limiter import SearchRateLimiter
from app.services.result_store import SearchResultStore

pytestmark = pytest.mark.asyncio


def token_from(html: str) -> str:
    """Extract one URL-safe result token from rendered result actions."""

    match = re.search(r"/search/result/([A-Za-z0-9_-]+)", html)
    assert match is not None
    return match.group(1)


async def test_home_renders_functional_form_options_and_local_assets(client):
    response = await client.get("/")

    assert response.status_code == 200
    assert 'hx-get="/search"' in response.text
    assert 'hx-target="#search-results"' in response.text
    assert 'hx-indicator="#search-loading"' in response.text
    assert 'hx-push-url="true"' in response.text
    assert 'name="providers" value="mock"' in response.text
    assert 'value="PT-BR"' in response.text
    assert 'value="2160p"' in response.text
    assert 'value="x265"' in response.text
    assert 'value="WEB-DL"' in response.text
    assert "Searching providers…" in response.text
    assert "fonts.googleapis.com" not in response.text


async def test_valid_htmx_search_uses_pipeline_and_renders_desktop_and_mobile_results(client):
    response = await client.get(
        "/search",
        params={
            "query": "Example",
            "providers": "mock",
            "min_seeders": "20",
            "sort_by": "seeders_desc",
        },
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Example" in response.text
    assert "Brutos: <strong>4</strong>" in response.text
    assert "Deduplicados: <strong>3</strong>" in response.text
    assert "Filtrados: <strong>1</strong>" in response.text
    assert "Mock Provider" not in response.text  # the table uses the stable provider slug
    assert "result-card" in response.text
    assert "results-table" in response.text
    assert "Download" in response.text
    assert "Abrir magnet" in response.text
    assert "disabled" in response.text
    assert "magnet:?xt=urn:btih:1111111111111111111111111111111111111111" not in response.text
    assert '"mock_result"' not in response.text

    full_page = await client.get("/search?query=Example&providers=mock")
    assert full_page.status_code == 200
    assert "<!doctype html>" in full_page.text
    assert 'value="Example"' in full_page.text
    assert "results-table" in full_page.text


async def test_search_preserves_filters_and_supports_validation_errors(client):
    valid = await client.get(
        "/search?query=Example&providers=mock&languages=PT-BR&qualities=720p&weak_deduplication=false",
        headers={"HX-Request": "true"},
    )
    assert valid.status_code == 200
    assert "Example" in valid.text

    invalid_query = await client.get("/search?query=x", headers={"HX-Request": "true"})
    assert invalid_query.status_code == 200
    assert "pelo menos 2 caracteres" in invalid_query.text

    invalid_provider = await client.get(
        "/search?query=Example&providers=not-registered",
        headers={"HX-Request": "true"},
    )
    assert invalid_provider.status_code == 200
    assert "não registrado" in invalid_provider.text

    invalid_non_htmx = await client.get("/search?query=x")
    assert invalid_non_htmx.status_code == 400
    assert "pelo menos 2 caracteres" in invalid_non_htmx.text


async def test_search_result_token_detail_is_temporary_and_sanitized(client):
    response = await client.get("/search?query=Example&providers=mock", headers={"HX-Request": "true"})
    token = token_from(response.text)

    detail = await client.get(f"/search/result/{token}", headers={"HX-Request": "true"})
    assert detail.status_code == 200
    assert "Score breakdown" in detail.text
    assert "11111111…11111111" in detail.text
    assert "magnet:?xt=urn:btih:1111…1111" in detail.text
    assert "magnet:?xt=urn:btih:1111111111111111111111111111111111111111" not in detail.text
    assert "mock_result" not in detail.text
    assert "Copy magnet" in detail.text
    assert "disabled" in detail.text

    magnet = await client.get(f"/search/result/{token}/magnet", follow_redirects=False)
    assert magnet.status_code == 307
    assert magnet.headers["location"].startswith("magnet:")

    missing = await client.get("/search/result/not-a-real-token")
    assert missing.status_code == 404


async def test_history_persists_only_safe_search_metadata_and_paginates(client):
    await client.get("/search?query=HistoryExample&providers=mock", headers={"HX-Request": "true"})
    response = await client.get("/search/history")

    assert response.status_code == 200
    assert "Histórico de buscas" in response.text
    assert "HistoryExample" in response.text
    assert "Repetir" in response.text
    assert "magnet" not in response.text.casefold()
    assert "raw_data" not in response.text

    with database.SessionLocal() as session:
        row = session.scalar(select(SearchHistory).where(SearchHistory.query == "HistoryExample"))
        assert row is not None
        assert row.providers_json == '["mock"]'
        assert "magnet" not in row.filters_json.casefold()
        assert "raw_data" not in row.filters_json


async def test_partial_provider_error_is_visible_without_hiding_success(client, monkeypatch):
    registry = ProviderRegistry()
    registry.register(MockProvider(slug="good"), priority=10)
    registry.register(MockProvider(slug="bad", error="provider exploded"), priority=20)
    monkeypatch.setattr(client._transport.app.state, "provider_registry", registry)

    response = await client.get(
        "/search?query=Example&providers=good&providers=bad",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "Algumas fontes não responderam" in response.text
    assert "bad: provider exploded" in response.text
    assert "Example" in response.text


async def test_timeout_provider_is_reported(monkeypatch, client):
    registry = ProviderRegistry()
    registry.register(MockProvider(slug="slow", latency_seconds=0.05), priority=10)
    monkeypatch.setattr(client._transport.app.state, "provider_registry", registry)
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "search_provider_timeout_seconds", 0.01)
    response = await client.get(
        "/search?query=Example&providers=slow",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    assert "timed out" in response.text
    assert "0 resultados" in response.text


async def test_result_store_ttl_limit_and_deep_copy():
    store = SearchResultStore(ttl_seconds=1, max_items=2)
    results = [SearchResult(provider="mock", title=f"Result {index}") for index in range(3)]
    tokens = await store.save_many(results)
    assert len(tokens) == 3
    assert await store.size() == 2
    assert await store.get(tokens[0]) is None
    stored = await store.get(tokens[-1])
    assert stored is not None
    stored.title = "changed"
    assert (await store.get(tokens[-1])).title == "Result 2"

    expiring = SearchResultStore(ttl_seconds=1, max_items=5)
    token = (await expiring.save_many([results[0]], ttl_seconds=1))[0]
    expiring._items[token] = (0, results[0])
    assert await expiring.get(token) is None


async def test_rate_limiter_is_bounded_and_resettable():
    limiter = SearchRateLimiter(requests=2, window_seconds=60)
    assert await limiter.allow("127.0.0.1")
    assert await limiter.allow("127.0.0.1")
    assert not await limiter.allow("127.0.0.1")
    assert await limiter.allow("127.0.0.2")
    await limiter.reset()
    assert await limiter.allow("127.0.0.1")


async def test_search_endpoint_rate_limit_is_user_facing(client):
    responses = [await client.get("/search?query=RateLimit&providers=mock") for _ in range(20)]
    blocked = await client.get("/search?query=RateLimit&providers=mock", headers={"HX-Request": "true"})
    assert all(response.status_code == 200 for response in responses)
    assert blocked.status_code == 429
    assert "Muitas buscas" in blocked.text


async def test_provider_title_is_escaped_in_rendered_html(client):
    response = await client.get(
        "/search?query=%3Cscript%3Ealert(1)%3C%2Fscript%3E&providers=mock",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text


async def test_web_schema_bounds_and_conversion():
    empty_numbers = SearchQueryParams(query="Example", min_seeders="", season="", episode="")
    assert empty_numbers.min_seeders is None
    assert empty_numbers.to_filters().min_seeders is None
    assert SearchQueryParams(query="Example", min_seeders=0).to_filters().min_seeders is None

    params = SearchQueryParams(
        query="  Example   Movie ",
        providers=["mock", "mock"],
        min_size="1.5 GB",
        max_size="2 GiB",
        required_terms="extended, remux, extended",
        media_type="series",
        season=1,
        episode=2,
    )
    assert params.query == "Example Movie"
    assert params.providers == ["mock"]
    assert params.to_search_request().query == "Example Movie"
    filters = params.to_filters()
    assert filters.min_size_bytes == 1_500_000_000
    assert filters.max_size_bytes == 2 * 1024**3
    assert filters.required_terms == ["extended", "remux"]

    with pytest.raises(ValueError):
        SearchQueryParams(query="Example", media_type="movie", season=1)
    with pytest.raises(ValueError):
        SearchQueryParams(query="Example", min_size="2 GB", max_size="1 GB").to_filters()


async def test_empty_seed_filter_is_accepted_by_search_endpoint(client):
    response = await client.get(
        "/search?query=Example&providers=mock&min_seeders=",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    assert "Example" in response.text


async def test_static_assets_and_health_smoke(client):
    css = Path("app/static/css/app.css").read_text()
    js = Path("app/static/js/app.js").read_text()
    health = await client.get("/health")
    providers = await client.get("/providers/health")
    assert "search-panel-functional" in css
    assert "htmx:beforeRequest" in js
    assert health.status_code == 200
    assert providers.status_code == 200
