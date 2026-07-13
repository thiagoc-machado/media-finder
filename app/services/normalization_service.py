"""Normalization of provider results into the common domain contract."""

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from app.schemas.search import SearchResult
from app.utils.magnet import InvalidMagnetError, normalize_info_hash, normalize_magnet, parse_magnet
from app.utils.release_parser import (
    normalize_audio_channels,
    normalize_audio_codec,
    normalize_codec,
    normalize_language,
    normalize_quality,
    normalize_source_type,
    parse_release,
)
from app.utils.size import parse_size


class NormalizationService:
    """Apply only deterministic, evidence-based transformations."""

    def normalize(self, result: SearchResult) -> SearchResult:
        """Return a normalized copy while retaining the provider payload."""

        parsed = parse_release(result.title)
        updates: dict[str, Any] = {"raw_data": deepcopy(result.raw_data)}

        updates["provider"] = result.provider.strip() or result.provider
        updates["title"] = " ".join(result.title.split())
        updates["providers"] = _unique([*result.providers, result.provider])

        updates["quality"] = normalize_quality(result.quality) if result.quality else parsed.quality
        updates["languages"] = _normalize_languages(result.languages) if result.languages else parsed.languages
        updates["codec"] = normalize_codec(result.codec) if result.codec else parsed.codec
        updates["audio_codec"] = normalize_audio_codec(result.audio_codec) if result.audio_codec else parsed.audio_codec
        updates["audio_channels"] = (
            normalize_audio_channels(result.audio_channels) if result.audio_channels else parsed.audio_channels
        )
        updates["source_type"] = normalize_source_type(result.source_type) if result.source_type else parsed.source_type
        updates["release_group"] = result.release_group.strip() if result.release_group else parsed.release_group

        trackers = _unique([*result.trackers, *([result.tracker] if result.tracker else [])])
        magnet = result.magnet_url
        parsed_magnet = None
        if magnet:
            try:
                parsed_magnet = parse_magnet(magnet)
                magnet = normalize_magnet(magnet)
                trackers = _unique([*trackers, *parsed_magnet.trackers])
            except InvalidMagnetError:
                # A provider's invalid URL is useful evidence and remains in raw_data.
                pass
        updates["magnet_url"] = magnet
        if result.info_hash:
            try:
                updates["info_hash"] = normalize_info_hash(result.info_hash)
            except InvalidMagnetError:
                updates["info_hash"] = result.info_hash
        elif parsed_magnet is not None:
            updates["info_hash"] = parsed_magnet.info_hash

        inferred_size = _infer_size(result.raw_data)
        if result.size_bytes is not None:
            updates["size_bytes"] = result.size_bytes
        elif inferred_size is not None:
            updates["size_bytes"] = inferred_size

        updates["trackers"] = trackers
        updates["tracker"] = result.tracker.strip() if result.tracker else (trackers[0] if trackers else None)
        return result.model_copy(deep=True, update=updates)

    def normalize_many(self, results: Iterable[SearchResult]) -> list[SearchResult]:
        """Normalize results in input order."""

        return [self.normalize(result) for result in results]


def normalize_result(result: SearchResult) -> SearchResult:
    """Convenience wrapper for one result."""

    return NormalizationService().normalize(result)


def normalize_results(results: Iterable[SearchResult]) -> list[SearchResult]:
    """Convenience wrapper for a result collection."""

    return NormalizationService().normalize_many(results)


def _normalize_languages(values: Iterable[str]) -> list[str]:
    """Normalize language aliases without adding inferred languages."""

    return _unique(normalize_language(value) for value in values if value and value.strip())


def _infer_size(raw_data: dict[str, Any]) -> int | None:
    """Read a size only from common provider payload fields."""

    for key in ("size_bytes", "size", "size_text"):
        if key not in raw_data or raw_data[key] is None:
            continue
        try:
            return parse_size(raw_data[key])
        except ValueError:
            continue
    return None


def _unique(values: Iterable[str]) -> list[str]:
    """Deduplicate strings case-insensitively while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized.casefold() not in seen:
            seen.add(normalized.casefold())
            result.append(normalized)
    return result
