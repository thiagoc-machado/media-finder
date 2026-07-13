"""Shared provider behavior for Torrentio-compatible Stremio addons."""

from __future__ import annotations

import logging
import re
import time
from typing import Callable

from app.clients.stremio_addon_client import StremioAddonClient
from app.config import Settings
from app.exceptions import ProviderConfigurationError, ProviderError
from app.providers.parsers.common import parse_stream_text
from app.schemas.provider import ProviderHealth, ProviderRequestMetrics, StremioProviderStatus
from app.schemas.search import SearchRequest, SearchResult
from app.services.normalization_service import normalize_result
from app.services.stremio_stream_service import normalize_stremio_stream
from app.utils.stremio_url import abbreviated_external_id

logger = logging.getLogger(__name__)
_IMDB_RE = re.compile(r"^tt\d{7,10}$", re.IGNORECASE)


class StremioAddonProvider:
    """Provider adapter shared by configured Torrentio and MediaFusion addons."""

    slug = "stremio"
    name = "Stremio addon"
    supported_media_types = frozenset({"movie", "series", "anime"})

    def __init__(
        self,
        settings: Settings,
        *,
        manifest_url: str,
        timeout_seconds: float,
        cache_ttl_seconds: int,
        max_results: int,
        max_concurrency: int,
        http_client=None,
        ignore_live: bool = False,
        parser: Callable = parse_stream_text,
    ) -> None:
        self.settings = settings
        self.max_results = max_results
        self._ignore_live = ignore_live
        self._parser = parser
        self._client = (
            StremioAddonClient(
                manifest_url,
                provider_slug=self.slug,
                timeout_seconds=timeout_seconds,
                cache_ttl_seconds=cache_ttl_seconds,
                max_items=settings.provider_cache_max_items,
                max_response_bytes=settings.stremio_addon_max_response_bytes,
                max_redirects=settings.stremio_addon_max_redirects,
                allowed_schemes=settings.stremio_addon_allowed_schemes,
                allow_private_hosts=settings.stremio_addon_allow_private_hosts,
                max_concurrency=max_concurrency,
                rate_limit_requests=settings.provider_rate_limit_requests,
                rate_limit_window_seconds=settings.provider_rate_limit_window_seconds,
                http_client=http_client,
            )
            if manifest_url
            else None
        )
        self.last_metrics: ProviderRequestMetrics | None = None

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Resolve one IMDb-based Stremio stream request and normalize it."""

        media_type = self._validate_request(request)
        if self._client is None:
            raise ProviderConfigurationError("Stremio addon manifest URL is not configured")
        started = time.perf_counter()
        response = await self._client.get_streams(media_type, _stream_id(request))
        normalized: list[SearchResult] = []
        for stream in response.streams:
            if self._ignore_live and _looks_live(stream):
                continue
            fields = self._parser(stream)
            result = normalize_stremio_stream(
                stream,
                self.slug,
                media_type,
                _stream_id(request),
                parsed_fields=fields,
            )
            normalized.append(normalize_result(result))
        normalized = normalized[: self.max_results]
        self.last_metrics = ProviderRequestMetrics(
            provider=self.slug,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            result_count=len(normalized),
            cached=False,
            indexers_used=[],
        )
        logger.info(
            "stremio_provider_search_completed",
            extra={
                "provider": self.slug,
                "addon_id": self._client.fingerprint,
                "media_type": media_type,
                "external_id": abbreviated_external_id(_stream_id(request)),
                "duration_ms": self.last_metrics.duration_ms,
                "result_count": len(normalized),
                "cache_hit": False,
            },
        )
        return normalized

    async def health_check(self) -> ProviderHealth:
        """Delegate to the generic manifest-only health check."""

        if self._client is None:
            return ProviderHealth(slug=self.slug, available=False, error="Stremio addon manifest URL is not configured")
        return await self._client.health_check()

    async def status(self) -> StremioProviderStatus:
        """Return a safe status without returning the configured manifest URL."""

        enabled = self._client is not None
        if self._client is None:
            return StremioProviderStatus(
                enabled=enabled,
                available=False,
                error="Stremio addon manifest URL is not configured",
            )
        started = time.perf_counter()
        try:
            manifest = await self._client.get_manifest()
            if not self._client.supports_resource(manifest, "stream"):
                raise ProviderConfigurationError("Stremio addon has no stream resource")
            supports_movie = self._client.supports_type(manifest, "movie")
            supports_series = self._client.supports_type(manifest, "series")
            if not supports_movie and not supports_series:
                raise ProviderConfigurationError("Stremio addon supports neither movie nor series")
            return StremioProviderStatus(
                enabled=True,
                available=True,
                addon_name=manifest.name,
                addon_version=manifest.version,
                supports_movie=supports_movie,
                supports_series=supports_series,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except ProviderError as exc:
            return StremioProviderStatus(
                enabled=True,
                available=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )

    async def reset_runtime(self) -> None:
        if self._client is not None:
            await self._client.reset_runtime()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()

    def _validate_request(self, request: SearchRequest) -> str:
        if request.media_type == "all":
            raise ProviderConfigurationError("Stremio provider requires a resolved media type")
        if request.media_type not in self.supported_media_types:
            raise ProviderConfigurationError("Stremio provider does not support this media type")
        if not request.imdb_id or not _IMDB_RE.fullmatch(request.imdb_id):
            raise ProviderConfigurationError(f"{self.name} requires a resolved IMDb ID")
        if request.media_type in {"series", "anime"} and (request.season is None or request.episode is None):
            raise ProviderConfigurationError(f"{self.name} requires season and episode for series")
        return request.media_type


def _stream_id(request: SearchRequest) -> str:
    """Build only the documented Stremio movie/series external ID."""

    if request.media_type == "movie":
        return request.imdb_id or ""
    return f"{request.imdb_id}:{request.season}:{request.episode}"


def _looks_live(stream) -> bool:
    """Ignore explicit live/channel/HLS entries for MediaFusion."""

    text = " ".join(value.casefold() for value in (stream.name, stream.title, stream.description) if value)
    return any(marker in text for marker in ("live tv", "live stream", "channel", ".m3u8")) and not stream.info_hash
