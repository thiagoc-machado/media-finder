"""Explicit registry for configured search providers."""

import asyncio
import time
from dataclasses import dataclass
from typing import Sequence

from app.providers.base import SearchProvider
from app.schemas.provider import ProviderHealth


class ProviderRegistryError(Exception):
    """Base error for provider registry operations."""


class DuplicateProviderError(ProviderRegistryError):
    """Raised when a provider slug is registered more than once."""


class ProviderNotFoundError(ProviderRegistryError):
    """Raised when a requested provider slug is not registered."""


@dataclass(frozen=True)
class ProviderRegistration:
    """Provider metadata kept by the registry."""

    provider: SearchProvider
    enabled: bool
    priority: int
    order: int


class ProviderRegistry:
    """Maintain an explicit, deterministic collection of providers."""

    def __init__(self) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}
        self._next_order = 0

    def register(self, provider: SearchProvider, *, enabled: bool = True, priority: int = 100) -> None:
        """Register one provider, rejecting duplicate or invalid slugs."""

        slug = getattr(provider, "slug", "")
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError("Provider slug must be a non-empty string")
        if slug in self._registrations:
            raise DuplicateProviderError(f"Provider slug already registered: {slug}")
        if not callable(getattr(provider, "search", None)) or not callable(getattr(provider, "health_check", None)):
            raise TypeError(f"Provider does not implement the SearchProvider contract: {slug}")
        if not isinstance(priority, int):
            raise TypeError("Provider priority must be an integer")

        self._registrations[slug] = ProviderRegistration(
            provider=provider,
            enabled=enabled,
            priority=priority,
            order=self._next_order,
        )
        self._next_order += 1

    def get(self, slug: str) -> SearchProvider:
        """Return a registered provider, regardless of enabled state."""

        try:
            return self._registrations[slug].provider
        except KeyError as exc:
            raise ProviderNotFoundError(f"Provider is not registered: {slug}") from exc

    def registration(self, slug: str) -> ProviderRegistration:
        """Return the complete registration metadata for one provider."""

        if slug not in self._registrations:
            raise ProviderNotFoundError(f"Provider is not registered: {slug}")
        return self._registrations[slug]

    def registrations(self) -> list[ProviderRegistration]:
        """List registrations in priority order, then registration order."""

        return sorted(self._registrations.values(), key=lambda item: (item.priority, item.order))

    def providers(self) -> list[SearchProvider]:
        """List all registered providers in deterministic priority order."""

        return [registration.provider for registration in self.registrations()]

    def enabled_providers(self) -> list[SearchProvider]:
        """List only enabled providers in deterministic priority order."""

        return [registration.provider for registration in self.registrations() if registration.enabled]

    def set_enabled(self, slug: str, enabled: bool) -> None:
        """Enable or disable a registered provider without replacing it."""

        registration = self.registration(slug)
        self._registrations[slug] = ProviderRegistration(
            provider=registration.provider,
            enabled=enabled,
            priority=registration.priority,
            order=registration.order,
        )

    def select(self, slugs: Sequence[str] | None = None) -> list[SearchProvider]:
        """Select enabled providers, preserving registry priority order."""

        if slugs is None:
            return self.enabled_providers()

        requested = set(slugs)
        for slug in requested:
            if slug not in self._registrations:
                raise ProviderNotFoundError(f"Provider is not registered: {slug}")

        return [
            registration.provider
            for registration in self.registrations()
            if registration.enabled and registration.provider.slug in requested
        ]

    async def health_check(self, slug: str, *, timeout: float | None = None) -> ProviderHealth:
        """Run one provider health check with an optional timeout."""

        provider = self.get(slug)
        started = time.perf_counter()
        try:
            check = provider.health_check()
            result = await asyncio.wait_for(check, timeout=timeout) if timeout is not None else await check
            if result.latency_ms is None:
                result = result.model_copy(update={"latency_ms": _elapsed_ms(started)})
            return result
        except (TimeoutError, asyncio.TimeoutError):
            return ProviderHealth(
                slug=slug,
                available=False,
                latency_ms=_elapsed_ms(started),
                error=f"Health check timed out after {timeout:g} seconds",
            )
        except Exception as exc:
            return ProviderHealth(
                slug=slug,
                available=False,
                latency_ms=_elapsed_ms(started),
                error=str(exc) or type(exc).__name__,
            )

    async def health_checks(
        self,
        slugs: Sequence[str] | None = None,
        *,
        timeout: float | None = None,
    ) -> list[ProviderHealth]:
        """Run health checks concurrently in registry priority order."""

        providers = self.select(slugs)
        return list(
            await asyncio.gather(*(self.health_check(provider.slug, timeout=timeout) for provider in providers))
        )


def _elapsed_ms(started: float) -> float:
    """Convert a monotonic timer interval to rounded milliseconds."""

    return round((time.perf_counter() - started) * 1000, 2)
