"""Concurrent provider search orchestration."""

import asyncio
import time
from collections.abc import Mapping, Sequence

from app.providers.registry import ProviderRegistry
from app.schemas.provider import ProviderSearchError, SearchExecutionResult
from app.schemas.search import SearchRequest, SearchResult


class SearchService:
    """Execute independent provider searches without cross-provider failure."""

    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        default_timeout: float = 10.0,
        provider_timeouts: Mapping[str, float] | None = None,
    ) -> None:
        if default_timeout <= 0:
            raise ValueError("default_timeout must be greater than zero")
        self.registry = registry
        self.default_timeout = default_timeout
        self.provider_timeouts = dict(provider_timeouts or {})
        if any(timeout <= 0 for timeout in self.provider_timeouts.values()):
            raise ValueError("Provider timeouts must be greater than zero")

    async def search(
        self,
        request: SearchRequest,
        provider_slugs: Sequence[str] | None = None,
    ) -> SearchExecutionResult:
        """Search selected providers concurrently and aggregate partial success."""

        started = time.perf_counter()
        providers = self.registry.select(provider_slugs)
        requested = [provider.slug for provider in providers]
        if not providers:
            return SearchExecutionResult(
                providers_requested=[],
                duration_ms=_elapsed_ms(started),
            )

        attempts = await asyncio.gather(
            *(self._search_provider(provider, request) for provider in providers),
            return_exceptions=True,
        )

        results: list[SearchResult] = []
        errors: list[ProviderSearchError] = []
        succeeded: list[str] = []
        for provider, attempt in zip(providers, attempts, strict=True):
            if isinstance(attempt, BaseException):
                errors.append(self._format_error(provider.slug, attempt))
                continue
            succeeded.append(provider.slug)
            results.extend(attempt)

        return SearchExecutionResult(
            results=results,
            errors=errors,
            providers_requested=requested,
            providers_succeeded=succeeded,
            duration_ms=_elapsed_ms(started),
        )

    async def _search_provider(self, provider, request: SearchRequest) -> list[SearchResult]:
        """Run one provider with only its own timeout boundary."""

        timeout = self.provider_timeouts.get(provider.slug, self.default_timeout)
        return await asyncio.wait_for(provider.search(request), timeout=timeout)

    def _format_error(self, slug: str, error: BaseException) -> ProviderSearchError:
        """Convert an isolated provider failure to a user-safe warning."""

        if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
            timeout = self.provider_timeouts.get(slug, self.default_timeout)
            return ProviderSearchError(
                provider=slug,
                error_type="timeout",
                message=f"Provider timed out after {timeout:g} seconds",
            )
        return ProviderSearchError(
            provider=slug,
            error_type=type(error).__name__,
            message=str(error) or type(error).__name__,
        )


def _elapsed_ms(started: float) -> float:
    """Convert a monotonic timer interval to rounded milliseconds."""

    return round((time.perf_counter() - started) * 1000, 2)
