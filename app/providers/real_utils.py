"""Shared validation and normalization helpers for Prowlarr and Jackett."""

from __future__ import annotations

import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from app.utils.magnet import (
    InvalidMagnetError,
    build_magnet,
    normalize_info_hash,
    normalize_magnet,
    parse_magnet,
)

_SENSITIVE_QUERY_KEYS = {"apikey", "api_key", "key", "token", "passkey", "cookie", "password"}
_TAG_RE = re.compile(r"<[^>]*>")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean_text(value: Any, *, max_length: int = 500) -> str | None:
    """Convert provider text to plain bounded text without HTML markup."""

    if value is None or not isinstance(value, (str, int, float)):
        return None
    text = html.unescape(str(value))
    text = _CONTROL_RE.sub(" ", _TAG_RE.sub(" ", text))
    text = " ".join(text.split())[:max_length].strip()
    return text or None


def safe_external_url(value: Any, *, max_length: int = 2000) -> str | None:
    """Validate an HTTP(S) URL and remove credential-like query parameters."""

    if not isinstance(value, str) or len(value) > max_length:
        return None
    candidate = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in candidate):
        return None
    try:
        parsed = urlsplit(candidate)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username or parsed.password or parsed.fragment:
            return None
    except ValueError:
        return None
    filtered = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _SENSITIVE_QUERY_KEYS
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(filtered), ""))


def safe_identifier(value: Any, *, max_length: int = 300) -> str | None:
    """Keep stable provider identifiers without retaining URLs or secrets."""

    cleaned = clean_text(value, max_length=max_length)
    if not cleaned or "apikey=" in cleaned.casefold() or "token=" in cleaned.casefold():
        return None
    return cleaned


def safe_int(value: Any, *, minimum: int = 0) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = int(float(str(value).strip()))
        return number if number >= minimum else None
    except (OverflowError, TypeError, ValueError):
        return None


def safe_datetime(value: Any) -> datetime | None:
    """Parse ISO or RFC-2822 dates, returning None for untrusted values."""

    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        try:
            return parsedate_to_datetime(candidate)
        except (TypeError, ValueError, OverflowError):
            return None


def normalized_magnet_and_hash(magnet: Any, info_hash: Any) -> tuple[str | None, str | None]:
    """Accept only a valid magnet or BTIH and build a safe magnet from a hash."""

    normalized_hash: str | None = None
    normalized_magnet: str | None = None
    if isinstance(magnet, str):
        try:
            normalized_magnet = normalize_magnet(magnet)
            normalized_hash = parse_magnet(normalized_magnet).info_hash
        except InvalidMagnetError:
            normalized_magnet = None
    if normalized_hash is None and isinstance(info_hash, str):
        try:
            normalized_hash = normalize_info_hash(unquote(info_hash.strip()))
            normalized_magnet = build_magnet(normalized_hash)
        except InvalidMagnetError:
            pass
    return normalized_magnet, normalized_hash


def media_type_from_categories(categories: list[int], requested: str) -> str | None:
    """Map standard Torznab category families to the common domain."""

    if requested != "all":
        return requested
    if any(2000 <= category < 3000 for category in categories):
        return "movie"
    if 5070 in categories:
        return "anime"
    if any(5000 <= category < 6000 for category in categories):
        return "series"
    if any(8000 <= category < 9000 for category in categories):
        return "other"
    return None
