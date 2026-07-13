"""High-level post-provider processing pipeline for Phase 3."""

import time

from app.schemas.provider import ProcessedSearchResult, SearchExecutionResult
from app.schemas.search import SearchFilters, SearchSort
from app.services.deduplication_service import DeduplicationService
from app.services.filter_service import FilterService
from app.services.normalization_service import NormalizationService
from app.services.scoring_service import ScoringPreferences, ScoringService
from app.services.sorting_service import SortingService


async def process_search_results(
    execution_result: SearchExecutionResult,
    filters: SearchFilters,
    scoring_preferences: ScoringPreferences,
    sort_by: SearchSort | str,
    *,
    allow_weak_dedup: bool = True,
) -> ProcessedSearchResult:
    """Normalize, deduplicate, filter, score, and order provider output."""

    started = time.perf_counter()
    normalization = NormalizationService()
    deduplication = DeduplicationService()
    filtering = FilterService()
    scoring = ScoringService()
    sorting = SortingService()

    normalized = normalization.normalize_many(execution_result.results)
    deduplicated = deduplication.deduplicate(normalized, allow_weak=allow_weak_dedup)
    filtered = filtering.apply(deduplicated, filters)
    scored = scoring.score_many(filtered, scoring_preferences)
    ordered = sorting.sort(scored, sort_by)

    processing_ms = (time.perf_counter() - started) * 1000
    return ProcessedSearchResult(
        results=ordered,
        provider_errors=list(execution_result.errors),
        raw_count=len(execution_result.results),
        normalized_count=len(normalized),
        deduplicated_count=len(deduplicated),
        filtered_count=len(filtered),
        duration_ms=round(execution_result.duration_ms + processing_ms, 2),
    )
