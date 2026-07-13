"""Safe parsing and construction of magnet URIs."""

import base64
import binascii
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse

from app.exceptions import InvalidMagnetError

MAX_MAGNET_LENGTH = 16_384
_HEX_HASH = re.compile(r"^[0-9a-fA-F]{40}$")
_BASE32_HASH = re.compile(r"^[A-Za-z2-7]{32}$")


@dataclass(frozen=True)
class ParsedMagnet:
    """Decoded magnet components with unknown query parameters preserved."""

    info_hash: str
    display_name: str | None
    trackers: tuple[str, ...]
    params: tuple[tuple[str, str], ...]


def validate_info_hash(value: str) -> bool:
    """Return whether a value is a valid hexadecimal or base32 BTIH."""

    if not isinstance(value, str) or len(value) > MAX_MAGNET_LENGTH or _has_control_chars(value):
        return False
    if _HEX_HASH.fullmatch(value):
        return True
    if not _BASE32_HASH.fullmatch(value):
        return False
    try:
        base64.b32decode(value.upper(), casefold=True)
    except (binascii.Error, ValueError):
        return False
    return True


def normalize_info_hash(value: str) -> str:
    """Normalize hexadecimal hashes to lowercase and decode base32 hashes."""

    if not validate_info_hash(value):
        raise InvalidMagnetError("Invalid BTIH info hash")
    if _HEX_HASH.fullmatch(value):
        return value.lower()
    try:
        return base64.b32decode(value.upper(), casefold=True).hex()
    except (binascii.Error, ValueError) as exc:
        raise InvalidMagnetError("Invalid base32 BTIH info hash") from exc


def extract_info_hash(magnet_url: str) -> str:
    """Extract and normalize the first valid BTIH from a magnet URI."""

    return parse_magnet(magnet_url).info_hash


def parse_magnet(magnet_url: str) -> ParsedMagnet:
    """Parse a magnet URI without making any network request."""

    _validate_magnet_input(magnet_url)
    parsed = urlparse(magnet_url)
    if parsed.scheme.casefold() != "magnet":
        raise InvalidMagnetError("Magnet URI must use the magnet scheme")

    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    hash_value: str | None = None
    display_name: str | None = None
    trackers: list[str] = []
    unknown: list[tuple[str, str]] = []
    for key, value in pairs:
        if _has_control_chars(key) or _has_control_chars(value):
            raise InvalidMagnetError("Magnet URI contains control characters")
        key_lower = key.casefold()
        if key_lower == "xt" and value.casefold().startswith("urn:btih:"):
            candidate = value.split(":", 2)[-1]
            if hash_value is None and validate_info_hash(candidate):
                hash_value = normalize_info_hash(candidate)
        elif key_lower == "dn" and display_name is None:
            display_name = value
        elif key_lower == "tr":
            _append_unique(trackers, value)
        else:
            unknown.append((key, value))

    if hash_value is None:
        raise InvalidMagnetError("Magnet URI must contain a valid xt=urn:btih value")
    return ParsedMagnet(
        info_hash=hash_value,
        display_name=display_name,
        trackers=tuple(trackers),
        params=tuple(unknown),
    )


def build_magnet(
    info_hash: str,
    *,
    display_name: str | None = None,
    trackers: Sequence[str] | None = None,
    params: Mapping[str, str | Sequence[str]] | Sequence[tuple[str, str]] | None = None,
) -> str:
    """Build a magnet URI without adding arbitrary trackers."""

    normalized_hash = normalize_info_hash(info_hash)
    pairs: list[tuple[str, str]] = [("xt", f"urn:btih:{normalized_hash}")]
    if display_name is not None:
        _validate_query_value(display_name, "display name")
        pairs.append(("dn", display_name))
    for tracker in _unique_values(trackers or []):
        _validate_query_value(tracker, "tracker")
        pairs.append(("tr", tracker))
    pairs.extend(_normalize_params(params))
    return "magnet:?" + urlencode(pairs, doseq=True)


def normalize_magnet(magnet_url: str) -> str:
    """Canonicalize a valid magnet while retaining unknown query parameters."""

    parsed = parse_magnet(magnet_url)
    return build_magnet(
        parsed.info_hash,
        display_name=parsed.display_name,
        trackers=parsed.trackers,
        params=parsed.params,
    )


def _validate_magnet_input(value: str) -> None:
    """Reject oversized or control-character-bearing input before parsing."""

    if not isinstance(value, str) or not value or len(value) > MAX_MAGNET_LENGTH:
        raise InvalidMagnetError("Magnet URI is empty or exceeds the maximum length")
    if _has_control_chars(value):
        raise InvalidMagnetError("Magnet URI contains control characters")


def _validate_query_value(value: str, label: str) -> None:
    """Reject control characters from generated query parameters."""

    if _has_control_chars(value):
        raise InvalidMagnetError(f"Invalid {label}")


def _normalize_params(
    params: Mapping[str, str | Sequence[str]] | Sequence[tuple[str, str]] | None,
) -> list[tuple[str, str]]:
    """Convert optional unknown parameters to ordered query pairs."""

    if params is None:
        return []
    pairs = list(params.items()) if isinstance(params, Mapping) else list(params)
    normalized: list[tuple[str, str]] = []
    for key, value in pairs:
        if key.casefold() in {"xt", "dn", "tr"}:
            continue
        values = value if isinstance(value, Sequence) and not isinstance(value, str) else [value]
        for item in values:
            _validate_query_value(key, "parameter name")
            _validate_query_value(str(item), "parameter value")
            normalized.append((key, str(item)))
    return normalized


def _append_unique(values: list[str], value: str) -> None:
    """Append a non-duplicate tracker while preserving its first spelling."""

    if value and value.casefold() not in {item.casefold() for item in values}:
        values.append(value)


def _unique_values(values: Sequence[str]) -> list[str]:
    """Return unique non-empty values in input order."""

    result: list[str] = []
    for value in values:
        if value:
            _append_unique(result, value)
    return result


def _has_control_chars(value: str) -> bool:
    """Detect characters that could corrupt a URI or log output."""

    return any(ord(character) < 32 or ord(character) == 127 for character in value)
