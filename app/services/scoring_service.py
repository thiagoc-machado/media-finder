"""Configurable deterministic scoring for normalized search results."""

from collections.abc import Iterable

from pydantic import BaseModel, Field

from app.schemas.search import SearchResult
from app.utils.release_parser import normalize_codec, normalize_language, normalize_quality, normalize_source_type


class ScoringPreferences(BaseModel):
    """All weights and preferences used by :func:`score_results`."""

    preferred_languages: list[str] = Field(default_factory=list)
    preferred_qualities: list[str] = Field(default_factory=list)
    preferred_codecs: list[str] = Field(default_factory=list)
    preferred_sources: list[str] = Field(default_factory=list)
    language_weight: float = 100
    quality_weight: float = 60
    codec_weight: float = 20
    source_weight: float = 20
    seeders_weight: float = 1
    seeders_cap: int = 100
    preferred_min_size_bytes: int | None = None
    preferred_max_size_bytes: int | None = None
    size_penalty: float = 15
    low_seeders_threshold: int | None = None
    low_seeders_penalty: float = 20
    excluded_terms: list[str] = Field(default_factory=list)
    excluded_term_penalty: float = 1000


class ScoringService:
    """Calculate explainable scores without mutating input models."""

    def score(self, result: SearchResult, preferences: ScoringPreferences) -> SearchResult:
        """Return a scored copy of one result."""

        total = 0.0
        breakdown: list[str] = []

        if preferences.language_weight and _matches(
            result.languages, preferences.preferred_languages, normalize_language
        ):
            total += preferences.language_weight
            breakdown.append(
                _component(
                    preferences.language_weight,
                    "Preferred language",
                    _first_match(result.languages, preferences.preferred_languages, normalize_language),
                )
            )
        if preferences.quality_weight and _matches(
            [result.quality], preferences.preferred_qualities, normalize_quality
        ):
            total += preferences.quality_weight
            breakdown.append(_component(preferences.quality_weight, "Preferred quality", result.quality))
        if preferences.codec_weight and _matches([result.codec], preferences.preferred_codecs, normalize_codec):
            total += preferences.codec_weight
            breakdown.append(_component(preferences.codec_weight, "Preferred codec", result.codec))
        if preferences.source_weight and _matches(
            [result.source_type], preferences.preferred_sources, normalize_source_type
        ):
            total += preferences.source_weight
            breakdown.append(_component(preferences.source_weight, "Preferred source", result.source_type))

        if result.seeders is not None and preferences.seeders_weight:
            cap = max(preferences.seeders_cap, 0)
            available = min(max(result.seeders, 0), cap)
            seed_score = available * preferences.seeders_weight
            total += seed_score
            breakdown.append(f"{seed_score:+.1f} Seed availability: {available}/{cap}")

        if (
            preferences.size_penalty
            and result.size_bytes is not None
            and _outside_preferred_size(result.size_bytes, preferences)
        ):
            total -= preferences.size_penalty
            label = (
                "Size below preferred range"
                if (
                    preferences.preferred_min_size_bytes is not None
                    and result.size_bytes < preferences.preferred_min_size_bytes
                )
                else "Size above preferred range"
            )
            breakdown.append(f"{-preferences.size_penalty:+.1f} {label}")

        if (
            preferences.low_seeders_penalty
            and preferences.low_seeders_threshold is not None
            and result.seeders is not None
            and result.seeders < preferences.low_seeders_threshold
        ):
            total -= preferences.low_seeders_penalty
            breakdown.append(f"{-preferences.low_seeders_penalty:+.1f} Low seed availability")

        title = result.title.casefold()
        for term in _unique_terms(preferences.excluded_terms):
            if preferences.excluded_term_penalty and term in title:
                total -= preferences.excluded_term_penalty
                breakdown.append(f"{-preferences.excluded_term_penalty:+.1f} Excluded term: {term}")

        return result.model_copy(deep=True, update={"score": round(total, 2), "score_breakdown": breakdown})

    def score_many(self, results: Iterable[SearchResult], preferences: ScoringPreferences) -> list[SearchResult]:
        """Score results in input order."""

        return [self.score(result, preferences) for result in results]


def score_result(result: SearchResult, preferences: ScoringPreferences) -> SearchResult:
    """Convenience wrapper for one result."""

    return ScoringService().score(result, preferences)


def score_results(results: Iterable[SearchResult], preferences: ScoringPreferences) -> list[SearchResult]:
    """Convenience wrapper for a result collection."""

    return ScoringService().score_many(results, preferences)


def _matches(values: Iterable[str | None], wanted: Iterable[str], normalizer) -> bool:
    """Match any known result value against any configured preference."""

    available = {_canonical(value, normalizer) for value in values if value}
    expected = {_canonical(value, normalizer) for value in wanted if value}
    return bool(available & expected)


def _first_match(values: Iterable[str], wanted: Iterable[str], normalizer) -> str:
    """Return the first matching result value for an explanation."""

    expected = {_canonical(value, normalizer) for value in wanted if value}
    return next(value for value in values if _canonical(value, normalizer) in expected)


def _canonical(value: str, normalizer) -> str:
    """Normalize a preference or result value for comparison."""

    return (normalizer(value) or "").strip().casefold()


def _component(amount: float, label: str, value: str | None) -> str:
    """Format one explainable score contribution."""

    return f"{amount:+.1f} {label}: {value or 'unknown'}"


def _outside_preferred_size(size: int, preferences: ScoringPreferences) -> bool:
    """Return whether a known size falls outside configured preferred bounds."""

    return (preferences.preferred_min_size_bytes is not None and size < preferences.preferred_min_size_bytes) or (
        preferences.preferred_max_size_bytes is not None and size > preferences.preferred_max_size_bytes
    )


def _unique_terms(values: Iterable[str]) -> list[str]:
    """Normalize excluded terms and keep one penalty per distinct term."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
