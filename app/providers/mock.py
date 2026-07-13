"""Deterministic provider used by tests and local development."""

import asyncio
import time
from typing import Any

from app.schemas.provider import ProviderHealth
from app.schemas.search import SearchRequest, SearchResult


class MockProvider:
    """Configurable provider simulation with no external network calls."""

    def __init__(
        self,
        *,
        slug: str = "mock",
        name: str = "Mock Provider",
        latency_seconds: float = 0,
        error: str | None = None,
        empty: bool = False,
        health_available: bool = True,
        health_latency_seconds: float = 0,
        health_error: str | None = None,
    ) -> None:
        self.slug = slug
        self.name = name
        self.latency_seconds = latency_seconds
        self.error = error
        self.empty = empty
        self.health_available = health_available
        self.health_latency_seconds = health_latency_seconds
        self.health_error = health_error

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Return predictable media variants after the configured delay."""

        await asyncio.sleep(self.latency_seconds)
        if self.error is not None:
            raise RuntimeError(self.error)
        if self.empty:
            return []

        media_type = request.media_type if request.media_type != "all" else "movie"
        return [
            self._result(
                request,
                media_type=media_type,
                result_id="mock-720p",
                title=f"{request.query} 720p PT-BR WEB-DL",
                info_hash="1" * 40,
                quality="720p",
                languages=["PT-BR"],
                size_bytes=1_200_000_000,
                seeders=42,
            ),
            self._result(
                request,
                media_type=media_type,
                result_id="mock-1080p",
                title=f"{request.query} 1080p Castellano",
                info_hash="2" * 40,
                quality="1080p",
                languages=["Castellano"],
                size_bytes=4_800_000_000,
                seeders=18,
            ),
            self._result(
                request,
                media_type=media_type,
                result_id="mock-2160p",
                title=f"{request.query} 2160p Dual Audio",
                info_hash="3" * 40,
                quality="2160p",
                languages=["PT-BR", "Dual Audio"],
                size_bytes=18_500_000_000,
                seeders=7,
            ),
            self._result(
                request,
                media_type=media_type,
                result_id="mock-720p-copy",
                title=f"{request.query} 720p PT-BR WEB-DL alternate",
                info_hash="1" * 40,
                quality="720p",
                languages=["PT-BR"],
                size_bytes=1_350_000_000,
                seeders=31,
            ),
        ]

    async def health_check(self) -> ProviderHealth:
        """Return configured mock availability after the configured delay."""

        started = time.perf_counter()
        await asyncio.sleep(self.health_latency_seconds)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        if not self.health_available:
            return ProviderHealth(
                slug=self.slug,
                available=False,
                latency_ms=latency_ms,
                error=self.health_error or "Mock provider is unavailable",
            )
        return ProviderHealth(slug=self.slug, available=True, latency_ms=latency_ms)

    def _result(
        self,
        request: SearchRequest,
        *,
        media_type: str,
        result_id: str,
        title: str,
        info_hash: str,
        quality: str,
        languages: list[str],
        size_bytes: int,
        seeders: int,
    ) -> SearchResult:
        """Build a fresh result object for each search invocation."""

        raw_data: dict[str, Any] = {"query": request.query, "mock_result": result_id}
        return SearchResult(
            provider=self.slug,
            provider_result_id=result_id,
            title=title,
            media_type=media_type,  # type: ignore[arg-type]
            info_hash=info_hash,
            magnet_url=f"magnet:?xt=urn:btih:{info_hash}",
            quality=quality,
            languages=languages,
            size_bytes=size_bytes,
            seeders=seeders,
            leechers=seeders // 3,
            tracker=f"{self.slug}.example",
            trackers=[f"{self.slug}.example"],
            codec="HEVC" if quality == "2160p" else "H.264",
            audio_codec="AAC",
            source_type="WEB-DL",
            raw_data=raw_data,
            download_capability="magnet",
        )
