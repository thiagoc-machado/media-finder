"""Schemas shared by provider search implementations."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Normalized request sent to every search provider."""

    query: str
    media_type: Literal["movie", "series", "anime", "other", "all"] = "all"
    imdb_id: str | None = None
    tmdb_id: int | None = None
    season: int | None = None
    episode: int | None = None
    indexers: list[str] = Field(default_factory=list)
    provider_indexers: dict[str, list[str]] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """Provider-independent representation of one search result."""

    provider: str
    provider_result_id: str | None = None
    title: str
    media_type: Literal["movie", "series", "anime", "other"] | None = None
    info_hash: str | None = None
    magnet_url: str | None = None
    source_url: str | None = None
    quality: str | None = None
    languages: list[str] = Field(default_factory=list)
    size_bytes: int | None = None
    seeders: int | None = None
    leechers: int | None = None
    tracker: str | None = None
    trackers: list[str] = Field(default_factory=list)
    codec: str | None = None
    audio_codec: str | None = None
    audio_channels: str | None = None
    source_type: str | None = None
    release_group: str | None = None
    score: float = 0
    download_capability: Literal["magnet", "info_hash", "http_stream", "external", "unsupported"] = "unsupported"
    published_at: datetime | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)
    providers: list[str] = Field(default_factory=list)
    deduplication_type: Literal["none", "strong", "weak"] = "none"
    deduplication_warnings: list[str] = Field(default_factory=list)
    score_breakdown: list[str] = Field(default_factory=list)


class SearchFilters(BaseModel):
    """Optional restrictions applied after provider results are normalized."""

    media_types: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    qualities: list[str] = Field(default_factory=list)
    codecs: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    trackers: list[str] = Field(default_factory=list)
    min_size_bytes: int | None = None
    max_size_bytes: int | None = None
    min_seeders: int | None = None
    required_terms: list[str] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)


class SearchSort(str, Enum):
    """Stable sort modes supported by the domain pipeline."""

    SCORE_DESC = "score_desc"
    SEEDERS_DESC = "seeders_desc"
    SIZE_ASC = "size_asc"
    SIZE_DESC = "size_desc"
    QUALITY_DESC = "quality_desc"
    PROVIDER_ASC = "provider_asc"
    TRACKER_ASC = "tracker_asc"
    PUBLISHED_AT_DESC = "published_at_desc"
