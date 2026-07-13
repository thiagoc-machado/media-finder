"""Concurrent search service tests."""

import time

import pytest

from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry
from app.schemas.search import SearchRequest
from app.services.search_service import SearchService


def make_service(*providers: tuple[MockProvider, int], timeout: float = 1.0, provider_timeouts=None):
    registry = ProviderRegistry()
    for provider, priority in providers:
        registry.register(provider, priority=priority)
    return SearchService(registry, default_timeout=timeout, provider_timeouts=provider_timeouts)


@pytest.mark.asyncio
async def test_search_runs_providers_concurrently():
    service = make_service(
        (MockProvider(slug="one", latency_seconds=0.12), 10),
        (MockProvider(slug="two", latency_seconds=0.12), 20),
    )

    started = time.perf_counter()
    result = await service.search(SearchRequest(query="Example"))
    elapsed = time.perf_counter() - started

    assert elapsed < 0.21
    assert result.providers_succeeded == ["one", "two"]
    assert result.errors == []
    assert len(result.results) == 8


@pytest.mark.asyncio
async def test_search_preserves_partial_results_when_a_provider_raises():
    service = make_service(
        (MockProvider(slug="good", empty=False), 10),
        (MockProvider(slug="bad", error="provider exploded"), 20),
    )

    result = await service.search(SearchRequest(query="Example"))

    assert result.providers_requested == ["good", "bad"]
    assert result.providers_succeeded == ["good"]
    assert len(result.results) == 4
    assert result.errors[0].provider == "bad"
    assert result.errors[0].error_type == "RuntimeError"
    assert result.errors[0].message == "provider exploded"


@pytest.mark.asyncio
async def test_search_isolates_provider_timeout():
    service = make_service(
        (MockProvider(slug="fast", latency_seconds=0.01), 10),
        (MockProvider(slug="slow", latency_seconds=0.2), 20),
        timeout=0.5,
        provider_timeouts={"slow": 0.03},
    )

    result = await service.search(SearchRequest(query="Example"))

    assert result.providers_succeeded == ["fast"]
    assert len(result.results) == 4
    assert result.errors[0].provider == "slow"
    assert result.errors[0].error_type == "timeout"
    assert "0.03 seconds" in result.errors[0].message


@pytest.mark.asyncio
async def test_search_preserves_registry_priority_in_requested_and_result_order():
    service = make_service(
        (MockProvider(slug="lower-priority"), 20),
        (MockProvider(slug="higher-priority"), 10),
    )

    result = await service.search(SearchRequest(query="Example"), ["lower-priority", "higher-priority"])

    assert result.providers_requested == ["higher-priority", "lower-priority"]
    assert [item.provider for item in result.results[:4]] == ["higher-priority"] * 4
    assert [item.provider for item in result.results[4:]] == ["lower-priority"] * 4


@pytest.mark.asyncio
async def test_search_supports_explicit_empty_selection_and_empty_provider():
    service = make_service((MockProvider(slug="empty", empty=True), 10))

    no_selection = await service.search(SearchRequest(query="Example"), [])
    empty_result = await service.search(SearchRequest(query="Example"))

    assert no_selection.results == []
    assert no_selection.providers_requested == []
    assert empty_result.results == []
    assert empty_result.providers_succeeded == ["empty"]
    assert empty_result.errors == []
