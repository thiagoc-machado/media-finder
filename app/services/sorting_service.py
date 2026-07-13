"""Stable ordering strategies for processed search results."""

from collections.abc import Iterable

from app.schemas.search import SearchResult, SearchSort
from app.utils.release_parser import normalize_quality

QUALITY_RANK = {
    "480p": 1,
    "576p": 2,
    "720p": 3,
    "1080i": 4,
    "1080p": 5,
    "2160p": 6,
}


class SortingService:
    """Sort without mutating the caller's collection or its result objects."""

    def sort(self, results: Iterable[SearchResult], sort_by: SearchSort | str) -> list[SearchResult]:
        """Apply one supported stable sort with unknown values last."""

        mode = _sort_mode(sort_by)
        values = list(results)
        if mode == SearchSort.SCORE_DESC:
            return sorted(values, key=lambda result: _descending_key(result.score))
        if mode == SearchSort.SEEDERS_DESC:
            return sorted(values, key=lambda result: _descending_key(result.seeders))
        if mode == SearchSort.SIZE_ASC:
            return sorted(values, key=lambda result: _ascending_key(result.size_bytes))
        if mode == SearchSort.SIZE_DESC:
            return sorted(values, key=lambda result: _descending_key(result.size_bytes))
        if mode == SearchSort.QUALITY_DESC:
            return sorted(values, key=lambda result: _descending_key(_quality_rank(result.quality)))
        if mode == SearchSort.PROVIDER_ASC:
            return sorted(values, key=lambda result: _text_key(result.provider))
        if mode == SearchSort.TRACKER_ASC:
            return sorted(values, key=lambda result: _text_key(result.tracker or _first(result.trackers)))
        if mode == SearchSort.PUBLISHED_AT_DESC:
            return sorted(
                values,
                key=lambda result: _descending_key(result.published_at.timestamp() if result.published_at else None),
            )
        raise ValueError(f"Unsupported search sort: {sort_by}")


def sort_results(results: Iterable[SearchResult], sort_by: SearchSort | str) -> list[SearchResult]:
    """Convenience wrapper around :class:`SortingService`."""

    return SortingService().sort(results, sort_by)


def _sort_mode(value: SearchSort | str) -> SearchSort:
    """Coerce a public string value to the enum used internally."""

    try:
        return value if isinstance(value, SearchSort) else SearchSort(value)
    except ValueError as exc:
        raise ValueError(f"Unsupported search sort: {value}") from exc


def _ascending_key(value):
    """Place ``None`` after known values in ascending order."""

    return (value is None, value if value is not None else 0)


def _descending_key(value):
    """Place ``None`` after known values in descending order."""

    return (value is None, -(value if value is not None else 0))


def _quality_rank(value: str | None) -> int | None:
    """Map quality to the documented descending quality order."""

    normalized = normalize_quality(value)
    return QUALITY_RANK.get(normalized) if normalized else None


def _text_key(value: str | None) -> tuple[bool, str]:
    """Sort text case-insensitively with missing text last."""

    normalized = value.strip().casefold() if value else ""
    return (not bool(normalized), normalized)


def _first(values: list[str]) -> str | None:
    """Return the first tracker when the primary field is absent."""

    return values[0] if values else None
