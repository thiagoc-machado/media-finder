"""Schemas for provider status and aggregated searches."""

from pydantic import BaseModel, Field

from app.schemas.search import SearchResult


class ProviderHealth(BaseModel):
    """Availability information returned by a provider health check."""

    slug: str
    available: bool
    version: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class ProviderIndexer(BaseModel):
    """Safe public projection of one configured provider indexer."""

    id: str
    name: str
    enabled: bool = True
    protocol: str | None = None
    privacy: str | None = None
    categories: list[int] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class ProviderCapabilities(BaseModel):
    """Capabilities exposed by a Torznab-compatible provider indexer."""

    search: bool = False
    movie_search: bool = False
    tv_search: bool = False
    music_search: bool = False
    book_search: bool = False
    categories: dict[int, str] = Field(default_factory=dict)


class ProviderRequestMetrics(BaseModel):
    """Safe metrics for one provider request."""

    provider: str
    duration_ms: float
    result_count: int
    cached: bool = False
    indexers_used: list[str] = Field(default_factory=list)


class StremioProviderStatus(BaseModel):
    """Safe status projection for a configured Stremio addon."""

    enabled: bool
    available: bool
    addon_name: str | None = None
    addon_version: str | None = None
    supports_movie: bool = False
    supports_series: bool = False
    latency_ms: float | None = None
    error: str | None = None


class ProviderSearchError(BaseModel):
    """Structured warning for a provider search that did not complete."""

    provider: str
    error_type: str
    message: str


class SearchExecutionResult(BaseModel):
    """Aggregate result for one concurrent provider search execution."""

    results: list[SearchResult] = Field(default_factory=list)
    errors: list[ProviderSearchError] = Field(default_factory=list)
    providers_requested: list[str] = Field(default_factory=list)
    providers_succeeded: list[str] = Field(default_factory=list)
    duration_ms: float = 0


class ProcessedSearchResult(BaseModel):
    """Metrics and output from the post-provider domain processing pipeline."""

    results: list[SearchResult] = Field(default_factory=list)
    provider_errors: list[ProviderSearchError] = Field(default_factory=list)
    raw_count: int = 0
    normalized_count: int = 0
    deduplicated_count: int = 0
    filtered_count: int = 0
    duration_ms: float = 0
