"""Conservative strong and weak deduplication for normalized results."""

import re
from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from app.schemas.search import SearchResult
from app.utils.magnet import InvalidMagnetError, extract_info_hash, normalize_info_hash, normalize_magnet, parse_magnet
from app.utils.release_parser import normalize_quality


class DeduplicationService:
    """Merge only results with a strong identity or a conservative weak key."""

    def deduplicate(self, results: Iterable[SearchResult], *, allow_weak: bool = True) -> list[SearchResult]:
        """Return one representative per duplicate identity, preserving first-seen order."""

        merged: dict[tuple[str, str], SearchResult] = {}
        output: list[SearchResult] = []
        for result in results:
            identity = _identity(result, allow_weak=allow_weak)
            if identity is None:
                output.append(result.model_copy(deep=True))
                continue
            existing = merged.get(identity)
            if existing is None:
                candidate = result.model_copy(deep=True)
                candidate.deduplication_type = identity[0]
                if identity[0] == "strong":
                    candidate.info_hash = identity[1]
                candidate.providers = _unique([*candidate.providers, candidate.provider])
                merged[identity] = candidate
                output.append(candidate)
            else:
                _merge_into(existing, result, identity[0])
        return output


def deduplicate_results(results: Iterable[SearchResult], *, allow_weak: bool = True) -> list[SearchResult]:
    """Convenience wrapper around :class:`DeduplicationService`."""

    return DeduplicationService().deduplicate(results, allow_weak=allow_weak)


def _identity(result: SearchResult, *, allow_weak: bool) -> tuple[str, str] | None:
    """Build a strong hash identity or an exact weak title/size/quality key."""

    info_hash = _result_hash(result)
    if info_hash:
        return ("strong", info_hash)
    if not allow_weak or result.size_bytes is None or not result.quality:
        return None
    title = re.sub(r"[^a-z0-9]+", " ", result.title.casefold()).strip()
    if not title:
        return None
    quality = normalize_quality(result.quality)
    return ("weak", f"{title}|{result.size_bytes}|{(quality or result.quality).casefold()}")


def _result_hash(result: SearchResult) -> str | None:
    """Return a valid normalized hash without trusting malformed provider data."""

    if result.info_hash:
        try:
            return normalize_info_hash(result.info_hash)
        except InvalidMagnetError:
            return None
    if result.magnet_url:
        try:
            return extract_info_hash(result.magnet_url)
        except InvalidMagnetError:
            return None
    return None


def _merge_into(target: SearchResult, incoming: SearchResult, deduplication_type: str) -> None:
    """Merge provider evidence into the first representative in place."""

    target.providers = _unique([*target.providers, target.provider, *incoming.providers, incoming.provider])
    target.trackers = _unique(
        [
            *target.trackers,
            *([target.tracker] if target.tracker else []),
            *incoming.trackers,
            *([incoming.tracker] if incoming.tracker else []),
        ]
    )
    if target.tracker is None and target.trackers:
        target.tracker = target.trackers[0]
    target.seeders = _max_known(target.seeders, incoming.seeders)
    target.leechers = _max_known(target.leechers, incoming.leechers)
    target.deduplication_type = deduplication_type
    target.deduplication_warnings = _unique([*target.deduplication_warnings, *incoming.deduplication_warnings])

    if target.size_bytes is None:
        target.size_bytes = incoming.size_bytes
    elif incoming.size_bytes is not None and target.size_bytes != incoming.size_bytes:
        warning = f"Conflicting sizes: {target.size_bytes} vs {incoming.size_bytes} bytes"
        if warning not in target.deduplication_warnings:
            target.deduplication_warnings.append(warning)

    for field in (
        "provider_result_id",
        "source_url",
        "quality",
        "codec",
        "audio_codec",
        "audio_channels",
        "source_type",
        "release_group",
        "media_type",
        "published_at",
    ):
        if getattr(target, field) in (None, "") and getattr(incoming, field) not in (None, ""):
            setattr(target, field, deepcopy(getattr(incoming, field)))
    target.languages = _unique([*target.languages, *incoming.languages])
    target.magnet_url = _choose_magnet(target.magnet_url, incoming.magnet_url)
    target_hash = _result_hash(target)
    incoming_hash = _result_hash(incoming)
    if target_hash:
        target.info_hash = target_hash
    elif incoming_hash:
        target.info_hash = incoming_hash
    target.raw_data = _merge_raw_data(target.raw_data, incoming.raw_data, target.provider, incoming.provider)


def _choose_magnet(first: str | None, second: str | None) -> str | None:
    """Choose the valid magnet carrying the most useful metadata."""

    candidates = [value for value in (first, second) if value]
    valid: list[tuple[int, str]] = []
    for value in candidates:
        try:
            parsed = parse_magnet(value)
        except InvalidMagnetError:
            continue
        completeness = len(parsed.trackers) * 2 + len(parsed.params) + int(parsed.display_name is not None)
        valid.append((completeness, value))
    if valid:
        _, (_, selected) = max(enumerate(valid), key=lambda item: (item[1][0], -item[0]))
        return normalize_magnet(selected)
    return first or second


def _merge_raw_data(
    first: dict[str, Any], second: dict[str, Any], first_provider: str, second_provider: str
) -> dict[str, Any]:
    """Retain original payloads grouped by their provider names."""

    merged = deepcopy(first)
    source_map = merged.get("_provider_sources")
    if not isinstance(source_map, dict):
        source_map = {}
        if first:
            source_map[first_provider] = [deepcopy(first)]
    for provider, payload in ((second_provider, second),):
        existing = source_map.setdefault(provider, [])
        if isinstance(existing, list):
            existing.append(deepcopy(payload))
        else:
            source_map[provider] = [deepcopy(existing), deepcopy(payload)]
    merged["_provider_sources"] = source_map
    return merged


def _max_known(first: int | None, second: int | None) -> int | None:
    """Use the largest non-null counter while retaining unknown as unknown."""

    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)


def _unique(values: Iterable[str]) -> list[str]:
    """Deduplicate text values case-insensitively in stable order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        value = value.strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            result.append(value)
    return result
