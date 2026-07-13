"""Jackett provider using only its documented Torznab XML API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
from app.schemas.provider import ProviderCapabilities, ProviderHealth, ProviderIndexer, ProviderRequestMetrics
from app.schemas.search import SearchRequest, SearchResult
from app.services.normalization_service import normalize_result
from app.services.provider_runtime import AsyncTTLCache, ProviderRateLimiter

logger = logging.getLogger(__name__)

_CAPABILITY_CATEGORY_BY_MEDIA_TYPE = {"movie": 2000, "series": 5000, "anime": 5070, "other": 8000}
_INDEXER_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


class JackettProvider:
    """Query configured Jackett indexers through Torznab only."""

    slug = "jackett"
    name = "Jackett"

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: ProviderHTTPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._api_key = self.settings.jackett_api_key
        self._http = http_client or ProviderHTTPClient(
            self.settings.jackett_url,
            timeout_seconds=self.settings.jackett_timeout_seconds,
            headers={"Accept": "application/xml, text/xml"},
        )
        self._owns_http = http_client is None
        self._semaphore = asyncio.Semaphore(self.settings.jackett_max_concurrency)
        self._rate_limiter = ProviderRateLimiter(
            requests=self.settings.provider_rate_limit_requests,
            window_seconds=self.settings.provider_rate_limit_window_seconds,
        )
        self._cache = AsyncTTLCache(
            ttl_seconds=self.settings.jackett_cache_ttl_seconds,
            max_items=self.settings.provider_cache_max_items,
        )
        self._capability_cache = AsyncTTLCache(
            ttl_seconds=self.settings.jackett_cache_ttl_seconds,
            max_items=self.settings.provider_cache_max_items,
        )
        self.last_metrics: ProviderRequestMetrics | None = None

    async def health_check(self) -> ProviderHealth:
        """Validate configured indexer capabilities without performing a search."""

        if not self._api_key:
            return ProviderHealth(slug=self.slug, available=False, error="Provider API key is not configured")
        started = time.perf_counter()
        try:
            indexers = self._configured_indexers()
            if not indexers:
                raise ProviderConfigurationError("No Jackett indexer is configured")
            for indexer in indexers:
                capabilities = await self.get_capabilities(indexer)
                if not any(
                    [
                        capabilities.search,
                        capabilities.movie_search,
                        capabilities.tv_search,
                        capabilities.music_search,
                        capabilities.book_search,
                    ]
                ):
                    raise ProviderInvalidResponseError("Jackett indexer has no search capability")
            return ProviderHealth(
                slug=self.slug,
                available=True,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except ProviderError as exc:
            return ProviderHealth(
                slug=self.slug,
                available=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )

    async def get_capabilities(self, indexer: str) -> ProviderCapabilities:
        """Parse Torznab capabilities XML for one configured indexer."""

        self._require_api_key()
        normalized_indexer = _validate_indexer_name(indexer)
        cached = await self._capability_cache.get(normalized_indexer)
        if cached is not None:
            return cached
        root = await self._get_xml(_torznab_path(normalized_indexer), params={"apikey": self._api_key, "t": "caps"})
        capabilities = _parse_capabilities(root)
        await self._capability_cache.set(normalized_indexer, capabilities)
        return capabilities

    async def list_indexers(self) -> list[ProviderIndexer]:
        """Return only configured Jackett indexers with valid capabilities."""

        details = await self.indexer_status()
        return [item["indexer"] for item in details if item["valid"]]

    async def indexer_status(self) -> list[dict[str, Any]]:
        """Return safe status records for configured indexers, including errors."""

        self._require_api_key()
        details = []
        for indexer in self._configured_indexers():
            try:
                capabilities = await self.get_capabilities(indexer)
                details.append(
                    {
                        "name": indexer,
                        "valid": True,
                        "capabilities": capabilities,
                        "error": None,
                        "indexer": ProviderIndexer(
                            id=indexer,
                            name=indexer,
                            protocol="torznab",
                            capabilities=_capability_names(capabilities),
                            categories=list(capabilities.categories),
                        ),
                    }
                )
            except ProviderError as exc:
                details.append(
                    {
                        "name": indexer,
                        "valid": False,
                        "capabilities": ProviderCapabilities(),
                        "error": str(exc),
                        "indexer": ProviderIndexer(id=indexer, name=indexer, protocol="torznab"),
                    }
                )
        return details

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Search configured indexers concurrently and keep partial successes."""

        self._require_api_key()
        configured = self._configured_indexers()
        requested = request.provider_indexers.get("jackett", request.indexers)
        if requested and "all" not in {item.casefold() for item in requested}:
            wanted = {item.casefold() for item in requested}
            configured = [item for item in configured if item.casefold() in wanted]
        if not configured:
            return []
        cache_key = json.dumps(
            {
                "q": request.query,
                "media_type": request.media_type,
                "season": request.season,
                "episode": request.episode,
                "imdb_id": request.imdb_id,
                "tmdb_id": request.tmdb_id,
                "indexers": sorted(configured),
            },
            sort_keys=True,
        )
        cached = await self._cache.get(cache_key)
        if cached is not None:
            self.last_metrics = ProviderRequestMetrics(
                provider=self.slug,
                duration_ms=0,
                result_count=len(cached),
                cached=True,
                indexers_used=configured,
            )
            return cached

        started = time.perf_counter()
        attempts = await asyncio.gather(
            *(self._search_indexer(indexer, request) for indexer in configured),
            return_exceptions=True,
        )
        results: list[SearchResult] = []
        failed = 0
        for indexer, attempt in zip(configured, attempts, strict=True):
            if isinstance(attempt, BaseException):
                failed += 1
                logger.warning(
                    "provider_indexer_failed",
                    extra={"provider": self.slug, "indexer": indexer, "error_type": type(attempt).__name__},
                )
                continue
            results.extend(attempt)
        if failed == len(configured) and not results:
            raise ProviderError("All configured Jackett indexers failed")
        results = results[: self.settings.jackett_max_results]
        await self._cache.set(cache_key, results)
        self.last_metrics = ProviderRequestMetrics(
            provider=self.slug,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            result_count=len(results),
            indexers_used=configured,
        )
        logger.info(
            "provider_search_completed",
            extra={
                "provider": self.slug,
                "duration_ms": self.last_metrics.duration_ms,
                "result_count": len(results),
                "cache_hit": False,
                "indexers_used": configured,
            },
        )
        return results

    async def close(self) -> None:
        if self._owns_http:
            await self._http.close()

    async def reset_runtime(self) -> None:
        await self._cache.reset()
        await self._capability_cache.reset()
        await self._rate_limiter.reset()

    async def _search_indexer(self, indexer: str, request: SearchRequest) -> list[SearchResult]:
        capabilities = await self.get_capabilities(indexer)
        search_type = _search_type(request.media_type, capabilities)
        params: dict[str, Any] = {"apikey": self._api_key, "t": search_type, "q": request.query}
        category = _CAPABILITY_CATEGORY_BY_MEDIA_TYPE.get(request.media_type)
        if category is not None and category in capabilities.categories:
            params["cat"] = str(category)
        if search_type == "tvsearch":
            if request.season is not None:
                params["season"] = str(request.season)
            if request.episode is not None:
                params["ep"] = str(request.episode)
        if request.imdb_id:
            params["imdbid"] = request.imdb_id
        root = await self._get_xml(_torznab_path(indexer), params=params)
        rows = [_normalize_jackett_item(item, indexer, request) for item in _children_named(root, "item")]
        return [normalize_result(result) for result in rows if result is not None]

    async def _get_xml(self, path: str, *, params: dict[str, Any]) -> Any:
        if not await self._rate_limiter.allow():
            from app.exceptions import ProviderRateLimitError

            raise ProviderRateLimitError("Provider rate limit reached")
        async with self._semaphore:
            return await self._http.get_xml(path, params=params)

    def _configured_indexers(self) -> list[str]:
        values = [item.strip() for item in self.settings.jackett_indexers.split(",") if item.strip()]
        return values or ["all"]

    def _require_api_key(self) -> None:
        if not self._api_key:
            raise ProviderConfigurationError("Provider API key is not configured")


def _validate_indexer_name(value: str) -> str:
    cleaned = safe_identifier(value, max_length=120)
    if not cleaned or not _INDEXER_NAME_RE.fullmatch(cleaned):
        raise ProviderConfigurationError("Jackett indexer name is invalid")
    return cleaned


def _torznab_path(indexer: str) -> str:
    return f"/api/v2.0/indexers/{_validate_indexer_name(indexer)}/results/torznab/api"


def _local_name(tag: Any) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _children_named(root: Any, name: str) -> list[Any]:
    return [element for element in root.iter() if _local_name(element.tag) == name.casefold()]


def _first_child_text(element: Any, name: str) -> str | None:
    for child in list(element):
        if _local_name(child.tag) == name.casefold():
            return clean_text(child.text, max_length=2000)
    return None


def _torznab_attrs(element: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in list(element):
        if _local_name(child.tag) != "attr":
            continue
        name = child.attrib.get("name", "").casefold()
        value = child.attrib.get("value")
        if name and isinstance(value, str):
            values[name] = value
    return values


def _parse_capabilities(root: Any) -> ProviderCapabilities:
    modes = {
        _local_name(element.tag): element
        for element in root.iter()
        if _local_name(element.tag) in {"search", "tv-search", "movie-search", "music-search", "book-search"}
    }
    categories: dict[int, str] = {}
    for element in root.iter():
        if _local_name(element.tag) not in {"category", "subcat"}:
            continue
        identifier = safe_int(element.attrib.get("id"))
        name = clean_text(element.attrib.get("name"), max_length=120)
        if identifier is not None and name:
            categories[identifier] = name
    return ProviderCapabilities(
        search=_available_mode(modes.get("search")),
        movie_search=_available_mode(modes.get("movie-search")),
        tv_search=_available_mode(modes.get("tv-search")),
        music_search=_available_mode(modes.get("music-search")),
        book_search=_available_mode(modes.get("book-search")),
        categories=categories,
    )


def _available_mode(element: Any) -> bool:
    if element is None:
        return False
    return element.attrib.get("available", "yes").casefold() not in {"no", "false", "0"}


def _capability_names(capabilities: ProviderCapabilities) -> list[str]:
    return [
        name
        for name, enabled in {
            "search": capabilities.search,
            "movie": capabilities.movie_search,
            "tv": capabilities.tv_search,
            "music": capabilities.music_search,
            "book": capabilities.book_search,
        }.items()
        if enabled
    ]


def _search_type(media_type: str, capabilities: ProviderCapabilities) -> str:
    if media_type == "movie":
        return "movie" if capabilities.movie_search else "search"
    if media_type in {"series", "anime"}:
        return "tvsearch" if capabilities.tv_search else "search"
    return "search"


def _normalize_jackett_item(element: Any, indexer: str, request: SearchRequest) -> SearchResult | None:
    attrs = _torznab_attrs(element)
    title = _first_child_text(element, "title")
    if not title:
        return None
    guid = _first_child_text(element, "guid")
    link = _first_child_text(element, "link")
    enclosure = next((child for child in list(element) if _local_name(child.tag) == "enclosure"), None)
    enclosure_url = enclosure.attrib.get("url") if enclosure is not None else None
    magnet, info_hash = normalized_magnet_and_hash(attrs.get("magneturl") or enclosure_url, attrs.get("infohash"))
    categories = []
    category_value = attrs.get("category")
    if category_value:
        for part in category_value.split(","):
            parsed = safe_int(part)
            if parsed is not None:
                categories.append(parsed)
    source_url = safe_external_url(enclosure_url) or safe_external_url(link)
    result_id = safe_identifier(guid) or f"{indexer}:{title}"
    seeders = safe_int(attrs.get("seeders"))
    peers = safe_int(attrs.get("peers"))
    size = safe_int(attrs.get("size")) or safe_int(enclosure.attrib.get("length") if enclosure is not None else None)
    return SearchResult(
        provider="jackett",
        provider_result_id=result_id,
        title=title,
        media_type=media_type_from_categories(categories, request.media_type),
        info_hash=info_hash,
        magnet_url=magnet,
        source_url=source_url,
        size_bytes=size,
        seeders=seeders,
        leechers=peers,
        tracker=indexer,
        trackers=[indexer],
        published_at=safe_datetime(_first_child_text(element, "pubDate")),
        raw_data={
            "guid": result_id,
            "indexer": indexer,
            "categories": categories,
            "protocol": "torznab",
            "has_magnet": magnet is not None,
            "has_source_url": source_url is not None,
            "download_volume_factor": clean_text(attrs.get("downloadvolumefactor"), max_length=20),
            "upload_volume_factor": clean_text(attrs.get("uploadvolumefactor"), max_length=20),
        },
    )
