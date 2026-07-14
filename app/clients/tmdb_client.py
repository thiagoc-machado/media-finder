"""Asynchronous, bounded client for the documented TMDB v3 API."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import date
from typing import Any

from app.clients.http_client import ProviderHTTPClient
from app.config import Settings
from app.exceptions import ProviderConfigurationError, ProviderError
from app.providers.real_utils import clean_text, safe_int
from app.schemas.metadata import (
    EpisodeSummary,
    ExternalIds,
    MetadataCandidate,
    MetadataDetails,
    MetadataProviderHealth,
    SeasonDetails,
    SeasonSummary,
)
from app.services.metadata_cache import MetadataCache
from app.services.provider_runtime import ProviderRateLimiter

_IMDB_RE = re.compile(r"^tt\d{7,10}$", re.IGNORECASE)


class TMDBClient:
    """Consume only TMDB JSON endpoints, never exposing the configured key."""

    provider = "tmdb"

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: ProviderHTTPClient | None = None,
    ) -> None:
        self.settings = settings
        self.enabled = settings.tmdb_enabled
        self._api_key = settings.tmdb_api_key.strip()
        self._auth_mode = settings.tmdb_auth_mode
        if self._auth_mode not in {"bearer", "api_key"}:
            raise ProviderConfigurationError("TMDB_AUTH_MODE must be bearer or api_key")
        self._owns_http = http_client is None
        self._http = http_client or ProviderHTTPClient(
            settings.tmdb_base_url,
            timeout_seconds=settings.tmdb_timeout_seconds,
        )
        self._cache = MetadataCache(
            ttl_seconds=settings.tmdb_cache_ttl_seconds,
            max_items=settings.metadata_result_store_max_items,
        )
        self._rate_limiter = ProviderRateLimiter(
            requests=settings.metadata_rate_limit_requests,
            window_seconds=settings.metadata_rate_limit_window_seconds,
        )
        self._semaphore = asyncio.Semaphore(settings.tmdb_max_concurrency)

    async def health_check(self) -> MetadataProviderHealth:
        """Validate configuration and authentication with TMDB's light endpoint."""

        started = time.perf_counter()
        if not self.enabled:
            return MetadataProviderHealth(enabled=False, available=False, error="TMDB is disabled")
        if not self._api_key:
            return MetadataProviderHealth(
                enabled=True,
                available=False,
                error="TMDB credentials are not configured",
            )
        try:
            await self._get_json("/configuration", params={})
        except ProviderError as exc:
            return MetadataProviderHealth(
                enabled=True,
                available=False,
                latency_ms=_elapsed_ms(started),
                error=str(exc),
            )
        return MetadataProviderHealth(enabled=True, available=True, latency_ms=_elapsed_ms(started))

    async def search_multi(self, query: str, page: int = 1) -> list[MetadataCandidate]:
        """Search movies and TV shows while ignoring people and adult entries."""

        query = _validate_query(query, self.settings.metadata_search_max_length)
        if page < 1 or page > 2:
            raise ValueError("TMDB page must be between 1 and 2")
        cache_key = f"{query.casefold()}|{page}|{self.settings.tmdb_language}|{self.settings.tmdb_region}"
        cached = await self._cache.get("search", cache_key)
        if cached is not None:
            return cached
        payload = await self._get_json(
            "/search/multi",
            params={
                "query": query,
                "page": page,
                "include_adult": "false",
                "language": self.settings.tmdb_language,
                "region": self.settings.tmdb_region,
            },
        )
        candidates: list[MetadataCandidate] = []
        for item in payload.get("results", []) if isinstance(payload, dict) else []:
            candidate = _candidate_from_payload(item)
            if candidate is not None:
                candidates.append(candidate)
        candidates = _deduplicate_candidates(candidates)[: self.settings.tmdb_max_results]
        await self._cache.set("search", cache_key, candidates)
        return candidates

    async def get_movie(self, tmdb_id: int) -> MetadataDetails:
        """Fetch one movie detail projection."""

        return await self._get_details("movie", tmdb_id)

    async def get_tv_show(self, tmdb_id: int) -> MetadataDetails:
        """Fetch one TV show detail projection, including season summaries."""

        return await self._get_details("tv", tmdb_id)

    async def get_external_ids(self, media_type: str, tmdb_id: int) -> ExternalIds:
        """Fetch IMDb, TVDB and Wikidata identifiers for one title."""

        normalized_type = _normalize_media_type(media_type)
        tmdb_id = _validate_tmdb_id(tmdb_id)
        cache_key = f"{normalized_type}|{tmdb_id}"
        cached = await self._cache.get("external_ids", cache_key)
        if cached is not None:
            return cached
        payload = await self._get_json(
            f"/{'movie' if normalized_type == 'movie' else 'tv'}/{tmdb_id}/external_ids",
            params={},
        )
        ids = _external_ids_from_payload(payload)
        await self._cache.set("external_ids", cache_key, ids)
        return ids

    async def get_tv_season(self, tmdb_id: int, season_number: int) -> SeasonDetails:
        """Fetch one TV season and its normalized episodes."""

        tmdb_id = _validate_tmdb_id(tmdb_id)
        if season_number < 0 or season_number > 1000:
            raise ValueError("Season number is out of range")
        cache_key = f"{tmdb_id}|{season_number}"
        cached = await self._cache.get("season", cache_key)
        if cached is not None:
            return cached
        payload = await self._get_json(f"/tv/{tmdb_id}/season/{season_number}", params={})
        details = _season_from_payload(payload, season_number)
        await self._cache.set("season", cache_key, details)
        return details

    async def reset_runtime(self) -> None:
        """Clear metadata cache and local rate-limit state."""

        await self._cache.reset()
        await self._rate_limiter.reset()

    async def close(self) -> None:
        """Close only the HTTP transport owned by this client."""

        if self._owns_http:
            await self._http.close()

    async def _get_details(self, endpoint_type: str, tmdb_id: int) -> MetadataDetails:
        tmdb_id = _validate_tmdb_id(tmdb_id)
        normalized_type = "movie" if endpoint_type == "movie" else "series"
        cache_key = f"{normalized_type}|{tmdb_id}"
        cached = await self._cache.get("details", cache_key)
        if cached is not None:
            return cached
        payload = await self._get_json(f"/{'movie' if normalized_type == 'movie' else 'tv'}/{tmdb_id}", params={})
        details = _details_from_payload(payload, normalized_type, tmdb_id)
        await self._cache.set("details", cache_key, details)
        return details

    async def _get_json(self, path: str, *, params: dict[str, Any]) -> Any:
        if not self.enabled:
            raise ProviderConfigurationError("TMDB is disabled")
        if not self._api_key:
            raise ProviderConfigurationError("TMDB credentials are not configured")
        if not await self._rate_limiter.allow():
            from app.exceptions import ProviderRateLimitError

            raise ProviderRateLimitError("Metadata provider rate limit reached")
        request_params = dict(params)
        headers: dict[str, str] = {}
        if self._auth_mode == "bearer":
            headers["Authorization"] = f"Bearer {self._api_key}"
        else:
            request_params["api_key"] = self._api_key
        async with self._semaphore:
            return await self._http.get_json(path, params=request_params, headers=headers)


def _candidate_from_payload(payload: Any) -> MetadataCandidate | None:
    if not isinstance(payload, dict) or payload.get("media_type") not in {"movie", "tv"}:
        return None
    if _as_bool(payload.get("adult")):
        return None
    media_type = "movie" if payload.get("media_type") == "movie" else "series"
    title_key = "title" if media_type == "movie" else "name"
    original_key = "original_title" if media_type == "movie" else "original_name"
    title = clean_text(payload.get(title_key), max_length=300)
    if not title:
        return None
    provider_id = _provider_id(payload.get("id"))
    if provider_id is None:
        return None
    release_date = _safe_date(payload.get("release_date" if media_type == "movie" else "first_air_date"))
    return MetadataCandidate(
        provider="tmdb",
        provider_id=provider_id,
        media_type=media_type,
        title=title,
        original_title=clean_text(payload.get(original_key), max_length=300),
        year=release_date.year if release_date else None,
        release_date=release_date,
        overview=clean_text(payload.get("overview"), max_length=600),
        poster_path=_safe_image_path(payload.get("poster_path")),
        backdrop_path=_safe_image_path(payload.get("backdrop_path")),
        popularity=_safe_float(payload.get("popularity")),
        vote_average=_safe_float(payload.get("vote_average")),
        vote_count=safe_int(payload.get("vote_count")),
        original_language=clean_text(payload.get("original_language"), max_length=20),
        adult=False,
    )


def _deduplicate_candidates(candidates: list[MetadataCandidate]) -> list[MetadataCandidate]:
    """Deduplicate repeated TMDB entries while preserving relevance order."""

    seen: set[tuple[str, str]] = set()
    result: list[MetadataCandidate] = []
    for candidate in candidates:
        key = (candidate.media_type, candidate.provider_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def _details_from_payload(payload: Any, media_type: str, tmdb_id: int) -> MetadataDetails:
    if not isinstance(payload, dict):
        raise ValueError("TMDB returned an invalid detail response")
    title = clean_text(payload.get("title" if media_type == "movie" else "name"), max_length=300)
    if not title:
        raise ValueError("TMDB detail has no title")
    release_date = _safe_date(payload.get("release_date" if media_type == "movie" else "first_air_date"))
    seasons = []
    if media_type == "series":
        seasons = [_season_summary(item) for item in payload.get("seasons", []) if _season_summary(item)]
    return MetadataDetails(
        provider="tmdb",
        provider_id=str(tmdb_id),
        media_type=media_type,
        title=title,
        original_title=clean_text(
            payload.get("original_title" if media_type == "movie" else "original_name"), max_length=300
        ),
        overview=clean_text(payload.get("overview"), max_length=1000),
        year=release_date.year if release_date else None,
        release_date=release_date,
        poster_path=_safe_image_path(payload.get("poster_path")),
        backdrop_path=_safe_image_path(payload.get("backdrop_path")),
        seasons=seasons,
        number_of_seasons=safe_int(payload.get("number_of_seasons")),
        number_of_episodes=safe_int(payload.get("number_of_episodes")),
    )


def _external_ids_from_payload(payload: Any) -> ExternalIds:
    if not isinstance(payload, dict):
        raise ValueError("TMDB returned invalid external IDs")
    imdb_id = clean_text(payload.get("imdb_id"), max_length=20)
    if imdb_id and not _IMDB_RE.fullmatch(imdb_id):
        imdb_id = None
    return ExternalIds(
        imdb_id=imdb_id.lower() if imdb_id else None,
        tvdb_id=safe_int(payload.get("tvdb_id")),
        wikidata_id=clean_text(payload.get("wikidata_id"), max_length=40),
    )


def _season_from_payload(payload: Any, fallback_number: int) -> SeasonDetails:
    if not isinstance(payload, dict):
        raise ValueError("TMDB returned an invalid season response")
    episodes = []
    for item in payload.get("episodes", []):
        if not isinstance(item, dict):
            continue
        number = safe_int(item.get("episode_number"))
        if number is None:
            continue
        episodes.append(
            EpisodeSummary(
                episode_number=number,
                name=clean_text(item.get("name"), max_length=300),
                overview=clean_text(item.get("overview"), max_length=600),
                air_date=_safe_date(item.get("air_date")),
                runtime_minutes=safe_int(item.get("runtime")),
                still_path=_safe_image_path(item.get("still_path")),
            )
        )
    return SeasonDetails(
        season_number=safe_int(payload.get("season_number")) or fallback_number,
        name=clean_text(payload.get("name"), max_length=300),
        episodes=episodes,
    )


def _season_summary(payload: Any) -> SeasonSummary | None:
    if not isinstance(payload, dict):
        return None
    number = safe_int(payload.get("season_number"))
    if number is None:
        return None
    return SeasonSummary(
        season_number=number,
        name=clean_text(payload.get("name"), max_length=300),
        episode_count=safe_int(payload.get("episode_count")),
        air_date=_safe_date(payload.get("air_date")),
        poster_path=_safe_image_path(payload.get("poster_path")),
    )


def _validate_query(query: str, max_length: int) -> str:
    if not isinstance(query, str):
        raise ValueError("Metadata query is invalid")
    normalized = " ".join(query.split())
    if len(normalized) < 2 or len(normalized) > max_length:
        raise ValueError("Metadata query length is invalid")
    return normalized


def _normalize_media_type(media_type: str) -> str:
    if media_type not in {"movie", "series"}:
        raise ValueError("TMDB media type must be movie or series")
    return media_type


def _validate_tmdb_id(tmdb_id: int) -> int:
    if isinstance(tmdb_id, bool) or not isinstance(tmdb_id, int) or not 1 <= tmdb_id <= 2_147_483_647:
        raise ValueError("TMDB ID is invalid")
    return tmdb_id


def _provider_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return str(number) if number > 0 else None


def _safe_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _safe_image_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    if len(value) > 300 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    if "//" in value or "?" in value or "#" in value or "://" in value:
        return None
    return value


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _as_bool(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.casefold() == "true")


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
