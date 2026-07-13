"""Prowlarr provider using its documented v1 JSON API."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from app.clients.http_client import ProviderHTTPClient
from app.config import Settings, get_settings
from app.exceptions import ProviderConfigurationError, ProviderError, ProviderInvalidResponseError
from app.providers.real_utils import (
    clean_text,
    media_type_from_categories,
    normalized_magnet_and_hash,
    safe_datetime,
    safe_external_url,
    safe_identifier,
    safe_int,
)
from app.schemas.provider import ProviderHealth, ProviderIndexer, ProviderRequestMetrics
from app.schemas.search import SearchRequest, SearchResult
from app.services.normalization_service import normalize_result
from app.services.provider_runtime import AsyncTTLCache, ProviderRateLimiter

logger = logging.getLogger(__name__)

_CATEGORY_BY_MEDIA_TYPE = {"movie": 2000, "series": 5000, "anime": 5070, "other": 8000}


class ProwlarrProvider:
    """Search Prowlarr without exposing its API key to callers or templates."""

    slug = "prowlarr"
    name = "Prowlarr"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: ProviderHTTPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._api_key = self.settings.prowlarr_api_key
        self._http = http_client or ProviderHTTPClient(
            self.settings.prowlarr_url,
            timeout_seconds=self.settings.prowlarr_timeout_seconds,
            headers={"X-Api-Key": self._api_key} if self._api_key else None,
        )
        self._owns_http = http_client is None
        self._semaphore = asyncio.Semaphore(self.settings.prowlarr_max_concurrency)
        self._rate_limiter = ProviderRateLimiter(
            requests=self.settings.provider_rate_limit_requests,
            window_seconds=self.settings.provider_rate_limit_window_seconds,
        )
        self._search_cache = AsyncTTLCache(
            ttl_seconds=self.settings.prowlarr_cache_ttl_seconds,
            max_items=self.settings.provider_cache_max_items,
        )
        self._indexer_cache = AsyncTTLCache(
            ttl_seconds=self.settings.prowlarr_cache_ttl_seconds,
            max_items=self.settings.provider_cache_max_items,
        )
        self.last_metrics: ProviderRequestMetrics | None = None

    async def health_check(self) -> ProviderHealth:
        """Check authenticated status without executing a search."""

        if not self._api_key:
            return ProviderHealth(slug=self.slug, available=False, error="Provider API key is not configured")
        started = time.perf_counter()
        try:
            payload = await self._get_json("/api/v1/system/status")
            if not isinstance(payload, dict):
                raise ProviderInvalidResponseError("Prowlarr returned an invalid status payload")
            version = clean_text(payload.get("version"), max_length=80)
            return ProviderHealth(
                slug=self.slug,
                available=True,
                version=version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except ProviderError as exc:
            return ProviderHealth(
                slug=self.slug,
                available=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )

    async def list_indexers(self, *, include_disabled: bool = False) -> list[ProviderIndexer]:
        """List safe Prowlarr indexer metadata, excluding disabled entries by default."""

        self._require_api_key()
        cache_key = "all" if include_disabled else "enabled"
        cached = await self._indexer_cache.get(cache_key)
        if cached is not None:
            return cached
        payload = await self._get_json("/api/v1/indexer")
        if not isinstance(payload, list):
            raise ProviderInvalidResponseError("Prowlarr returned an invalid indexer list")
        indexers = [_parse_indexer(item) for item in payload if isinstance(item, dict)]
        indexers = [item for item in indexers if item is not None and (include_disabled or item.enabled)]
        await self._indexer_cache.set(cache_key, indexers)
        return indexers

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Search selected Prowlarr indexers and normalize safe result fields."""

        self._require_api_key()
        selected = _request_indexers(request)
        cache_key = json.dumps(
            {
                "q": request.query,
                "media_type": request.media_type,
                "season": request.season,
                "episode": request.episode,
                "imdb_id": request.imdb_id,
                "tmdb_id": request.tmdb_id,
                "indexers": sorted(selected),
            },
            sort_keys=True,
        )
        cached = await self._search_cache.get(cache_key)
        if cached is not None:
            self.last_metrics = ProviderRequestMetrics(
                provider=self.slug,
                duration_ms=0,
                result_count=len(cached),
                cached=True,
                indexers_used=selected,
            )
            return cached

        started = time.perf_counter()
        indexers = await self.list_indexers()
        selected_indexers = _select_indexers(indexers, selected)
        if selected and not selected_indexers:
            return []
        indexer_ids = [indexer.id for indexer in selected_indexers] if selected else []
        categories = _supported_category(request.media_type, selected_indexers or indexers)
        params: dict[str, Any] = {
            "query": _structured_query(request),
            "type": _search_type(request.media_type),
        }
        if indexer_ids:
            params["indexerIds"] = ",".join(indexer_ids)
        if categories:
            params["categories"] = str(categories)
        elif request.media_type not in {"all", "other"}:
            logger.info(
                "provider_search_category_fallback",
                extra={"provider": self.slug, "media_type": request.media_type, "indexers": indexer_ids},
            )

        payload = await self._get_json("/api/v1/search", params=params)
        rows = (
            payload if isinstance(payload, list) else payload.get("results", []) if isinstance(payload, dict) else None
        )
        if not isinstance(rows, list):
            raise ProviderInvalidResponseError("Prowlarr returned an invalid search payload")
        results = [_normalize_prowlarr_result(row, request) for row in rows if isinstance(row, dict)]
        results = [normalize_result(result) for result in results if result is not None]
        results = results[: self.settings.prowlarr_max_results]
        await self._search_cache.set(cache_key, results)
        self.last_metrics = ProviderRequestMetrics(
            provider=self.slug,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            result_count=len(results),
            indexers_used=indexer_ids,
        )
        logger.info(
            "provider_search_completed",
            extra={
                "provider": self.slug,
                "duration_ms": self.last_metrics.duration_ms,
                "result_count": len(results),
                "cache_hit": False,
                "indexers_used": indexer_ids,
            },
        )
        return results

    async def close(self) -> None:
        if self._owns_http:
            await self._http.close()

    async def reset_runtime(self) -> None:
        await self._search_cache.reset()
        await self._indexer_cache.reset()
        await self._rate_limiter.reset()

    async def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if not await self._rate_limiter.allow():
            from app.exceptions import ProviderRateLimitError

            raise ProviderRateLimitError("Provider rate limit reached")
        async with self._semaphore:
            return await self._http.get_json(
                path,
                params=params,
                headers={"X-Api-Key": self._api_key} if self._api_key else None,
            )

    def _require_api_key(self) -> None:
        if not self._api_key:
            raise ProviderConfigurationError("Provider API key is not configured")


def _request_indexers(request: SearchRequest) -> list[str]:
    selected = request.provider_indexers.get("prowlarr", request.indexers)
    return [value.strip() for value in selected if isinstance(value, str) and value.strip().casefold() != "all"]


def _parse_indexer(payload: dict[str, Any]) -> ProviderIndexer | None:
    identifier = safe_identifier(payload.get("id"))
    name = clean_text(payload.get("name"), max_length=160)
    if not identifier or not name:
        return None
    enabled_value = _safe_bool(payload.get("enable", payload.get("enabled", payload.get("isEnabled", True))))
    categories = _category_ids(payload.get("categories", []))
    capabilities = []
    for media_type, category in _CATEGORY_BY_MEDIA_TYPE.items():
        if any(category <= item < category + 1000 for item in categories):
            capabilities.append(media_type)
    return ProviderIndexer(
        id=identifier,
        name=name,
        enabled=bool(enabled_value),
        protocol=clean_text(payload.get("protocol"), max_length=40),
        privacy=clean_text(payload.get("privacy"), max_length=40),
        categories=categories,
        capabilities=capabilities,
    )


def _safe_bool(value: Any) -> bool:
    """Interpret common provider boolean values without trusting arbitrary text."""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1", "enabled"}:
            return True
        if normalized in {"false", "no", "0", "disabled"}:
            return False
    return False


def _category_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    categories = []
    for item in value:
        raw = item.get("id") if isinstance(item, dict) else item
        parsed = safe_int(raw)
        if parsed is not None and parsed not in categories:
            categories.append(parsed)
    return categories


def _select_indexers(indexers: list[ProviderIndexer], selected: list[str]) -> list[ProviderIndexer]:
    if not selected:
        return indexers
    wanted = {value.casefold() for value in selected}
    return [indexer for indexer in indexers if indexer.id.casefold() in wanted or indexer.name.casefold() in wanted]


def _supported_category(media_type: str, indexers: list[ProviderIndexer]) -> int | None:
    category = _CATEGORY_BY_MEDIA_TYPE.get(media_type)
    if category is None or not indexers:
        return None
    if all(any(category <= item < category + 1000 for item in indexer.categories) for indexer in indexers):
        return category
    return None


def _search_type(media_type: str) -> str:
    return {"movie": "moviesearch", "series": "tvsearch", "anime": "tvsearch"}.get(media_type, "search")


def _structured_query(request: SearchRequest) -> str:
    pieces = [request.query]
    if request.imdb_id:
        pieces.append(f"{{ImdbId:{request.imdb_id}}}")
    if request.tmdb_id is not None:
        pieces.append(f"{{TmdbId:{request.tmdb_id}}}")
    if request.season is not None:
        pieces.append(f"{{Season:{request.season}}}")
    if request.episode is not None:
        pieces.append(f"{{Episode:{request.episode}}}")
    return " ".join(pieces)


def _normalize_prowlarr_result(payload: dict[str, Any], request: SearchRequest) -> SearchResult | None:
    title = clean_text(payload.get("title"))
    if not title:
        return None
    categories = _category_ids(payload.get("categories", []))
    magnet, info_hash = normalized_magnet_and_hash(payload.get("magnetUrl"), payload.get("infoHash"))
    source_url = (
        safe_external_url(payload.get("downloadUrl"))
        or safe_external_url(payload.get("infoUrl"))
        or safe_external_url(payload.get("guid"))
    )
    indexer = clean_text(payload.get("indexer"), max_length=160) or "Prowlarr"
    indexer_id = safe_identifier(payload.get("indexerId"))
    result_id = safe_identifier(payload.get("guid")) or f"{indexer_id or indexer}:{title}"
    return SearchResult(
        provider="prowlarr",
        provider_result_id=result_id,
        title=title,
        media_type=media_type_from_categories(categories, request.media_type),
        info_hash=info_hash,
        magnet_url=magnet,
        source_url=source_url,
        size_bytes=safe_int(payload.get("size")),
        seeders=safe_int(payload.get("seeders")),
        leechers=safe_int(payload.get("leechers")),
        tracker=indexer,
        trackers=[indexer],
        published_at=safe_datetime(payload.get("publishDate")),
        raw_data={
            "guid": result_id,
            "indexer": indexer,
            "indexer_id": indexer_id,
            "protocol": clean_text(payload.get("protocol"), max_length=40),
            "categories": categories,
            "has_magnet": magnet is not None,
            "has_source_url": source_url is not None,
        },
    )
