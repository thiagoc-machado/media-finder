"""Schemas for provider status and aggregated searches."""

from pydantic import BaseModel, Field

from app.schemas.search import SearchResult


class ProviderHealth(BaseModel):
    """Availability information returned by a provider health check."""

    slug: str
    available: bool
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
