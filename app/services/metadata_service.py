"""TMDB metadata orchestration for the first title-resolution subphase."""

from __future__ import annotations

import asyncio
import time

from app.clients.tmdb_client import TMDBClient
from app.schemas.metadata import (
    ExternalIds,
    MetadataCandidate,
    MetadataDetails,
    MetadataProviderError,
    MetadataSearchResult,
    ResolvedMedia,
    SeasonDetails,
    SeasonSummary,
)


class MetadataService:
    """Expose normalized TMDB operations to HTTP routes."""

    def __init__(self, tmdb: TMDBClient) -> None:
        self.tmdb = tmdb

    async def search(self, query: str, media_type: str = "all", max_age: int | None = 13) -> MetadataSearchResult:
        """Search TMDB and optionally restrict candidates to movie or series."""

        started = time.perf_counter()
        try:
            if media_type not in {"movie", "series", "all"}:
                raise ValueError("Metadata media type must be movie, series or all")
            if max_age is not None and (max_age < 0 or max_age > 18):
                raise ValueError("A classificação etária deve estar entre 0 e 18 anos")
            candidates = await self.tmdb.search_multi(query)
            if media_type in {"movie", "series"}:
                candidates = [candidate for candidate in candidates if candidate.media_type == media_type]
            if max_age is not None:
                rated = await asyncio.gather(*(self._with_age_rating(candidate) for candidate in candidates))
                candidates = [
                    candidate
                    for candidate in rated
                    if candidate.age_rating is not None and candidate.age_rating <= max_age
                ]
            return MetadataSearchResult(
                candidates=candidates,
                providers_requested=["tmdb"],
                providers_succeeded=["tmdb"],
                duration_ms=_elapsed_ms(started),
            )
        except Exception as exc:
            return MetadataSearchResult(
                errors=[
                    MetadataProviderError(
                        provider="tmdb",
                        error_type=type(exc).__name__,
                        message=_safe_error(exc),
                    )
                ],
                providers_requested=["tmdb"],
                duration_ms=_elapsed_ms(started),
            )

    async def _with_age_rating(self, candidate: MetadataCandidate) -> MetadataCandidate:
        """Attach a regional age rating without failing the whole catalog search."""

        try:
            rating = await self.tmdb.get_age_rating(candidate.media_type, int(candidate.provider_id))
        except Exception:
            rating = None
        return candidate.model_copy(update={"age_rating": rating})

    async def get_details(self, media_type: str, tmdb_id: int) -> MetadataDetails:
        """Fetch details and external IDs only after a candidate is selected."""

        if media_type == "movie":
            details = await self.tmdb.get_movie(tmdb_id)
        elif media_type == "series":
            details = await self.tmdb.get_tv_show(tmdb_id)
        else:
            raise ValueError("Metadata media type must be movie or series")
        external_ids = await self.tmdb.get_external_ids(media_type, tmdb_id)
        return details.model_copy(update={"external_ids": external_ids})

    async def get_external_ids(self, media_type: str, tmdb_id: int) -> ExternalIds:
        """Expose normalized external IDs for direct API consumers and tests."""

        return await self.tmdb.get_external_ids(media_type, tmdb_id)

    async def get_tv_season(self, tmdb_id: int, season_number: int) -> SeasonDetails:
        """Fetch one validated TV season."""

        return await self.tmdb.get_tv_season(tmdb_id, season_number)

    async def validate_episode(self, media: ResolvedMedia, season_number: int, episode_number: int) -> None:
        """Confirm a requested season and episode against the TMDB response."""

        if media.media_type != "series":
            raise ValueError("Apenas séries possuem temporadas e episódios")
        if season_number < 0 or season_number > 1000 or episode_number < 1 or episode_number > 1000:
            raise ValueError("Temporada ou episódio inválido")
        if season_number not in {season.season_number for season in media.seasons}:
            raise ValueError("Temporada inválida para esta série")
        season = await self.get_tv_season(media.tmdb_id, season_number)
        if episode_number not in {episode.episode_number for episode in season.episodes}:
            raise ValueError("Episódio inválido para esta temporada")

    async def resolve_candidate(
        self,
        candidate: MetadataCandidate,
        *,
        poster_url: str | None,
        show_specials: bool,
    ) -> ResolvedMedia:
        """Resolve a stored TMDB candidate into a trusted IMDb-backed object."""

        if candidate.provider != "tmdb" or candidate.media_type not in {"movie", "series"}:
            raise ValueError("Unsupported metadata candidate")
        try:
            tmdb_id = int(candidate.provider_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("TMDB candidate ID is invalid") from exc
        details = await self.get_details(candidate.media_type, tmdb_id)
        imdb_id = details.external_ids.imdb_id
        if not imdb_id:
            raise ValueError("TMDB candidate has no valid IMDb ID")
        seasons = _filter_seasons(details.seasons, show_specials=show_specials)
        return ResolvedMedia(
            media_type=details.media_type,
            title=details.title,
            original_title=details.original_title,
            year=details.year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            poster_url=poster_url,
            overview=details.overview,
            seasons=seasons,
        )

    async def close(self) -> None:
        """Close the underlying TMDB transport."""

        await self.tmdb.close()


def _safe_error(error: Exception) -> str:
    """Keep provider errors bounded and credential-free."""

    message = str(error) or type(error).__name__
    lowered = message.casefold()
    if "api_key" in lowered or "authorization" in lowered or "bearer" in lowered:
        return "TMDB request failed"
    return message[:240]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _filter_seasons(seasons: list[SeasonSummary], *, show_specials: bool) -> list[SeasonSummary]:
    """Keep only selectable seasons with known positive episode counts."""

    return [
        season
        for season in seasons
        if season.season_number >= 0
        and (show_specials or season.season_number > 0)
        and (season.episode_count is None or season.episode_count > 0)
    ]
