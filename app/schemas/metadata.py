"""Validated metadata projections used by the title-resolution flow."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetadataCandidate(BaseModel):
    """One safe, normalized movie or series candidate."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    provider_id: str
    media_type: Literal["movie", "series"]
    title: str
    original_title: str | None = None
    year: int | None = None
    release_date: date | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    popularity: float | None = None
    vote_average: float | None = None
    vote_count: int | None = None
    original_language: str | None = None
    adult: bool = False
    age_rating: int | None = Field(default=None, ge=0, le=18)


class ExternalIds(BaseModel):
    """External identifiers returned by the metadata provider."""

    model_config = ConfigDict(extra="ignore")

    imdb_id: str | None = None
    tvdb_id: int | None = None
    wikidata_id: str | None = None


class SeasonSummary(BaseModel):
    """Compact season information attached to a TV show."""

    season_number: int
    name: str | None = None
    episode_count: int | None = None
    air_date: date | None = None
    poster_path: str | None = None


class EpisodeSummary(BaseModel):
    """Compact episode information returned by a season endpoint."""

    episode_number: int
    name: str | None = None
    overview: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = None
    still_path: str | None = None


class MetadataDetails(BaseModel):
    """Safe details for one selected TMDB movie or series."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    provider_id: str
    media_type: Literal["movie", "series"]
    title: str
    original_title: str | None = None
    overview: str | None = None
    year: int | None = None
    release_date: date | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    external_ids: ExternalIds = Field(default_factory=ExternalIds)
    seasons: list[SeasonSummary] = Field(default_factory=list)
    number_of_seasons: int | None = None
    number_of_episodes: int | None = None


class SeasonDetails(BaseModel):
    """Safe details for one TV season."""

    season_number: int
    name: str | None = None
    episodes: list[EpisodeSummary] = Field(default_factory=list)


class ResolvedMedia(BaseModel):
    """Trusted, temporary metadata state used by release searches."""

    media_type: Literal["movie", "series"]
    title: str
    original_title: str | None = None
    year: int | None = None
    tmdb_id: int
    imdb_id: str
    poster_url: str | None = None
    overview: str | None = None
    seasons: list[SeasonSummary] = Field(default_factory=list)

    @field_validator("imdb_id")
    @classmethod
    def validate_imdb(cls, value: str) -> str:
        import re

        if not isinstance(value, str) or not re.fullmatch(r"tt\d{7,10}", value, re.IGNORECASE):
            raise ValueError("IMDb ID is invalid")
        return value.lower()

    @field_validator("tmdb_id")
    @classmethod
    def validate_tmdb(cls, value: int) -> int:
        if isinstance(value, bool) or value < 1:
            raise ValueError("TMDB ID is invalid")
        return value


class MetadataProviderHealth(BaseModel):
    """Public health projection that never contains credentials."""

    enabled: bool
    available: bool
    latency_ms: float | None = None
    error: str | None = None


class MetadataProviderError(BaseModel):
    """Safe error from one metadata provider."""

    provider: str
    error_type: str
    message: str


class MetadataSearchResult(BaseModel):
    """Metadata search result with partial-provider diagnostics."""

    candidates: list[MetadataCandidate] = Field(default_factory=list)
    errors: list[MetadataProviderError] = Field(default_factory=list)
    providers_requested: list[str] = Field(default_factory=list)
    providers_succeeded: list[str] = Field(default_factory=list)
    duration_ms: float = 0
    cached: bool = False
