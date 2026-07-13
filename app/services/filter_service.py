"""Composable, deterministic filtering of normalized search results."""

from collections.abc import Iterable

from app.schemas.search import SearchFilters, SearchResult
from app.utils.release_parser import normalize_codec, normalize_language, normalize_quality, normalize_source_type


class FilterService:
    """Apply AND-across-categories and OR-within-category restrictions."""

    def apply(self, results: Iterable[SearchResult], filters: SearchFilters) -> list[SearchResult]:
        """Filter results while preserving their input order.

        A configured size bound excludes an item with unknown size.  Likewise,
        ``min_seeders`` excludes an item whose seeder count is unknown.
        """

        return [result for result in results if self.matches(result, filters)]

    def matches(self, result: SearchResult, filters: SearchFilters) -> bool:
        """Return whether one result satisfies all configured restrictions."""

        if filters.media_types and not _matches_any([result.media_type], filters.media_types):
            return False
        if filters.providers and not _matches_any([result.provider, *result.providers], filters.providers):
            return False
        if filters.languages and not _matches_any(result.languages, filters.languages, normalize_language):
            return False
        if filters.qualities and not _matches_any([result.quality], filters.qualities, normalize_quality):
            return False
        if filters.codecs and not _matches_any([result.codec], filters.codecs, normalize_codec):
            return False
        if filters.source_types and not _matches_any([result.source_type], filters.source_types, normalize_source_type):
            return False
        if filters.trackers and not _matches_any([result.tracker, *result.trackers], filters.trackers):
            return False

        if filters.min_size_bytes is not None and (
            result.size_bytes is None or result.size_bytes < filters.min_size_bytes
        ):
            return False
        if filters.max_size_bytes is not None and (
            result.size_bytes is None or result.size_bytes > filters.max_size_bytes
        ):
            return False
        if filters.min_seeders is not None and (result.seeders is None or result.seeders < filters.min_seeders):
            return False

        title = result.title.casefold()
        required_terms = _terms(filters.required_terms)
        excluded_terms = _terms(filters.excluded_terms)
        return all(term in title for term in required_terms) and not any(term in title for term in excluded_terms)


def filter_results(results: Iterable[SearchResult], filters: SearchFilters) -> list[SearchResult]:
    """Convenience wrapper around :class:`FilterService`."""

    return FilterService().apply(results, filters)


def _matches_any(
    values: Iterable[str | None],
    wanted: Iterable[str],
    normalizer=None,
) -> bool:
    """Compare category values case-insensitively with OR semantics."""

    available = {
        _canonical(value, normalizer) for value in values if value is not None and _canonical(value, normalizer)
    }
    expected = {
        _canonical(value, normalizer) for value in wanted if value is not None and _canonical(value, normalizer)
    }
    return bool(available & expected)


def _canonical(value: str, normalizer=None) -> str:
    """Normalize a filter value with the category's alias normalizer."""

    normalized = normalizer(value) if normalizer else value
    return (normalized or "").strip().casefold()


def _terms(values: Iterable[str]) -> list[str]:
    """Discard empty search terms and normalize case."""

    return [value.strip().casefold() for value in values if value and value.strip()]
