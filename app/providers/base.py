"""Common provider protocol."""

from typing import Protocol, runtime_checkable

from app.schemas.provider import ProviderHealth
from app.schemas.search import SearchRequest, SearchResult


@runtime_checkable
class SearchProvider(Protocol):
    """Async interface implemented by every search provider."""

    slug: str
    name: str

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Search the provider with a normalized request."""

        ...

    async def health_check(self) -> ProviderHealth:
        """Return the current provider availability."""

        ...
