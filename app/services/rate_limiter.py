"""Small in-memory per-client rate limiter for the search endpoint."""

import asyncio
import time
from collections import defaultdict, deque


class SearchRateLimiter:
    """Allow a bounded number of requests per client IP in a time window."""

    def __init__(self, *, requests: int = 20, window_seconds: int = 60) -> None:
        if requests <= 0 or window_seconds <= 0:
            raise ValueError("Rate limit settings must be positive")
        self.requests = requests
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, client_key: str) -> bool:
        """Record one request and return whether it is allowed."""

        now = time.monotonic()
        async with self._lock:
            cutoff = now - self.window_seconds
            for key in list(self._events):
                events = self._events[key]
                while events and events[0] <= cutoff:
                    events.popleft()
                if not events:
                    del self._events[key]
            events = self._events[client_key]
            if len(events) >= self.requests:
                return False
            events.append(now)
            return True

    async def reset(self) -> None:
        """Clear all counters, primarily for deterministic tests."""

        async with self._lock:
            self._events.clear()
