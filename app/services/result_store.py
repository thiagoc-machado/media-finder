"""Bounded in-memory storage for short-lived search result tokens."""

import asyncio
import secrets
import time
from collections import OrderedDict
from collections.abc import Iterable

from app.schemas.search import SearchResult


class SearchResultStore:
    """Store result objects behind random tokens with lazy TTL cleanup."""

    def __init__(self, *, ttl_seconds: int = 900, max_items: int = 2000) -> None:
        if ttl_seconds <= 0 or max_items <= 0:
            raise ValueError("Result store limits must be positive")
        self.ttl_seconds = ttl_seconds
        self.max_items = max_items
        self._items: OrderedDict[str, tuple[float, SearchResult]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def save_many(self, results: Iterable[SearchResult], ttl_seconds: int | None = None) -> list[str]:
        """Save independent deep copies and return URL-safe random tokens."""

        ttl = self.ttl_seconds if ttl_seconds is None else ttl_seconds
        if ttl <= 0:
            raise ValueError("TTL must be positive")
        result_list = list(results)
        now = time.monotonic()
        async with self._lock:
            self._cleanup_locked(now)
            tokens: list[str] = []
            for result in result_list:
                token = secrets.token_urlsafe(32)
                self._items[token] = (now + ttl, result.model_copy(deep=True))
                tokens.append(token)
            self._trim_locked()
            return tokens

    async def get(self, token: str) -> SearchResult | None:
        """Return a deep copy for a valid, unexpired token."""

        if not token or len(token) > 128:
            return None
        now = time.monotonic()
        async with self._lock:
            self._cleanup_locked(now)
            item = self._items.get(token)
            if item is None:
                return None
            expires_at, result = item
            if expires_at <= now:
                self._items.pop(token, None)
                return None
            self._items.move_to_end(token)
            return result.model_copy(deep=True)

    async def cleanup(self) -> int:
        """Remove expired entries and return the number removed."""

        async with self._lock:
            before = len(self._items)
            self._cleanup_locked(time.monotonic())
            return before - len(self._items)

    async def size(self) -> int:
        """Return the number of currently live entries."""

        async with self._lock:
            self._cleanup_locked(time.monotonic())
            return len(self._items)

    def _cleanup_locked(self, now: float) -> None:
        """Remove expired entries while the lock is held."""

        expired = [token for token, (expires_at, _) in self._items.items() if expires_at <= now]
        for token in expired:
            self._items.pop(token, None)

    def _trim_locked(self) -> None:
        """Keep the newest entries within the configured bound."""

        while len(self._items) > self.max_items:
            self._items.popitem(last=False)
