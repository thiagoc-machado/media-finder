"""Bounded in-memory cache for metadata projections."""

from __future__ import annotations

from typing import Any

from app.services.provider_runtime import AsyncTTLCache


class MetadataCache:
    """Namespace cache with defensive copies and one configurable TTL."""

    def __init__(self, *, ttl_seconds: int, max_items: int) -> None:
        self._cache = AsyncTTLCache(ttl_seconds=ttl_seconds, max_items=max_items)

    async def get(self, namespace: str, key: str) -> Any | None:
        """Read one namespaced value."""

        return await self._cache.get(f"{namespace}:{key}")

    async def set(self, namespace: str, key: str, value: Any) -> None:
        """Store one namespaced value with a defensive copy."""

        await self._cache.set(f"{namespace}:{key}", value)

    async def reset(self) -> None:
        """Clear all metadata namespaces."""

        await self._cache.reset()
