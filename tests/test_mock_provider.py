"""Mock provider behavior tests."""

import pytest

from app.providers.mock import MockProvider
from app.schemas.search import SearchRequest


@pytest.mark.asyncio
async def test_mock_provider_returns_predictable_variants_without_deduplication():
    provider = MockProvider()
    results = await provider.search(SearchRequest(query="Example"))

    assert [result.quality for result in results] == ["720p", "1080p", "2160p", "720p"]
    assert results[0].languages == ["PT-BR"]
    assert results[1].languages == ["Castellano"]
    assert results[2].languages == ["PT-BR", "Dual Audio"]
    assert results[0].info_hash == results[3].info_hash
    assert [result.size_bytes for result in results] == [1_200_000_000, 4_800_000_000, 18_500_000_000, 1_350_000_000]
    assert [result.seeders for result in results] == [42, 18, 7, 31]


@pytest.mark.asyncio
async def test_mock_provider_can_be_empty_or_raise():
    request = SearchRequest(query="Example")

    assert await MockProvider(empty=True).search(request) == []
    with pytest.raises(RuntimeError, match="mock failure"):
        await MockProvider(error="mock failure").search(request)


@pytest.mark.asyncio
async def test_mock_provider_health_can_be_available_or_unavailable():
    available = await MockProvider().health_check()
    unavailable = await MockProvider(health_available=False, health_error="offline").health_check()

    assert available.available is True
    assert available.slug == "mock"
    assert unavailable.available is False
    assert unavailable.error == "offline"
