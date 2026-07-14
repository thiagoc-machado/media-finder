"""Ephemeral, namespaced storage for metadata selection state."""

from __future__ import annotations

import asyncio
import secrets
import time
from copy import deepcopy
from typing import Any

from app.schemas.metadata import MetadataCandidate, ResolvedMedia


class MetadataResultStore:
    """Store candidates and resolved media only in process memory."""

    def __init__(self, *, max_items: int = 1000, default_ttl_seconds: int = 900) -> None:
        self.max_items = max(1, max_items)
        self.default_ttl_seconds = max(0, default_ttl_seconds)
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def save_candidate(self, candidate: MetadataCandidate, ttl_seconds: int | None = None) -> str:
        """Save one candidate under an unguessable candidate namespace."""

        return await self._save("candidate", candidate, ttl_seconds)

    async def get_candidate(self, token: str) -> MetadataCandidate | None:
        """Retrieve one candidate with a defensive copy."""

        value = await self._get("candidate", token)
        return value if isinstance(value, MetadataCandidate) else None

    async def save_resolved(self, media: ResolvedMedia, ttl_seconds: int | None = None) -> str:
        """Save one resolved media object in a separate namespace."""

        return await self._save("resolved", media, ttl_seconds)

    async def get_resolved(self, token: str) -> ResolvedMedia | None:
        """Retrieve one resolved media object with a defensive copy."""

        value = await self._get("resolved", token)
        return value if isinstance(value, ResolvedMedia) else None

    async def reset(self) -> None:
        """Clear all ephemeral metadata state."""

        async with self._lock:
            self._items.clear()

    async def size(self) -> int:
        """Return the number of live entries after lazy cleanup."""

        async with self._lock:
            self._cleanup(time.monotonic())
            return len(self._items)

    async def _save(self, namespace: str, value: Any, ttl_seconds: int | None) -> str:
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(0, ttl_seconds)
        token = secrets.token_urlsafe(32)
        async with self._lock:
            now = time.monotonic()
            self._cleanup(now)
            self._items[f"{namespace}:{token}"] = (now + ttl, deepcopy(value))
            while len(self._items) > self.max_items:
                self._items.pop(next(iter(self._items)))
        return token

    async def _get(self, namespace: str, token: str) -> Any | None:
        if not isinstance(token, str) or not token or len(token) > 200:
            return None
        async with self._lock:
            now = time.monotonic()
            self._cleanup(now)
            item = self._items.get(f"{namespace}:{token}")
            if item is None or item[0] <= now:
                self._items.pop(f"{namespace}:{token}", None)
                return None
            return deepcopy(item[1])

    def _cleanup(self, now: float) -> None:
        expired = [key for key, (expires_at, _) in self._items.items() if expires_at <= now]
        for key in expired:
            self._items.pop(key, None)
