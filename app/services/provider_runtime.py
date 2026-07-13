"""Small per-provider async cache and rate limiter."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from copy import deepcopy
from typing import Any


class AsyncTTLCache:
    """Bounded lazy-expiring cache storing normalized provider results only."""

    def __init__(self, *, ttl_seconds: float, max_items: int = 256) -> None:
        self.ttl_seconds = max(0, ttl_seconds)
        self.max_items = max(1, max_items)
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if self.ttl_seconds == 0 or expires_at <= time.monotonic():
                self._items.pop(key, None)
                return None
            return deepcopy(value)

    async def set(self, key: str, value: Any, *, ttl_seconds: float | None = None) -> None:
        async with self._lock:
            ttl = self.ttl_seconds if ttl_seconds is None else max(0, ttl_seconds)
            self._items[key] = (time.monotonic() + ttl, deepcopy(value))
            while len(self._items) > self.max_items:
                self._items.pop(next(iter(self._items)))

    async def reset(self) -> None:
        async with self._lock:
            self._items.clear()


class ProviderRateLimiter:
    """Non-blocking fixed-window limiter scoped to one provider instance."""

    def __init__(self, *, requests: int, window_seconds: float) -> None:
        self.requests = max(1, requests)
        self.window_seconds = max(1, window_seconds)
        self._calls: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def allow(self) -> bool:
        now = time.monotonic()
        async with self._lock:
            while self._calls and self._calls[0] <= now - self.window_seconds:
                self._calls.popleft()
            if len(self._calls) >= self.requests:
                return False
            self._calls.append(now)
            return True

    async def reset(self) -> None:
        async with self._lock:
            self._calls.clear()
