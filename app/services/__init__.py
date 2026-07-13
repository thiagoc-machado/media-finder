"""Application service exports."""

from app.services.deduplication_service import DeduplicationService, deduplicate_results
from app.services.filter_service import FilterService, filter_results
from app.services.normalization_service import NormalizationService, normalize_result, normalize_results
from app.services.pipeline_service import process_search_results
from app.services.scoring_service import ScoringPreferences, ScoringService, score_result, score_results
from app.services.sorting_service import SortingService, sort_results

__all__ = [
    "DeduplicationService",
    "FilterService",
    "NormalizationService",
    "ScoringPreferences",
    "ScoringService",
    "SortingService",
    "deduplicate_results",
    "filter_results",
    "normalize_result",
    "normalize_results",
    "process_search_results",
    "score_result",
    "score_results",
    "sort_results",
]
