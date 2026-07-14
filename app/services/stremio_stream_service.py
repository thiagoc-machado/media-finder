"""Conversion of Stremio streams into the existing SearchResult contract."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.providers.real_utils import clean_text, safe_external_url, safe_int
from app.schemas.search import SearchResult
from app.schemas.stremio import StremioStream
from app.utils.magnet import InvalidMagnetError, build_magnet, normalize_info_hash, parse_magnet

_TRACKER_RE = re.compile(r"^tracker:(https?://|udp://)([^\s]+)$", re.IGNORECASE)
_SENSITIVE_TRACKER_KEYS = {"apikey", "api_key", "key", "token", "passkey", "cookie", "password"}


def normalize_stremio_stream(
    stream: StremioStream,
    provider_slug: str,
    media_type: str,
    external_id: str,
    parsed_fields: dict[str, Any] | None = None,
) -> SearchResult:
    """Normalize one stream without fetching or interpreting its URL."""

    fields = parsed_fields or {}
    title = clean_text(stream.title or stream.name or stream.description or external_id, max_length=500) or external_id
    hash_value = None
    magnet = None
    try:
        if stream.info_hash:
            hash_value = normalize_info_hash(stream.info_hash.strip())
        elif stream.url and stream.url.casefold().startswith("magnet:"):
            hash_value = parse_magnet(stream.url).info_hash
        if hash_value:
            magnet = build_magnet(hash_value, trackers=_stream_trackers(stream))
    except (InvalidMagnetError, AttributeError):
        hash_value = None
    trackers = _stream_trackers(stream)
    url = safe_external_url(stream.url)
    external_url = safe_external_url(stream.external_url)
    if hash_value:
        capability = "magnet"
        source_url = url or external_url
    elif url:
        capability = "http_stream"
        source_url = url
    elif external_url or clean_text(stream.yt_id, max_length=120):
        capability = "external"
        source_url = external_url
    else:
        capability = "unsupported"
        source_url = None

    result_id = hashlib.sha256(
        "|".join(
            [
                provider_slug,
                external_id,
                title,
                hash_value or "",
                clean_text(stream.url, max_length=200) or "",
                clean_text(stream.external_url, max_length=200) or "",
            ]
        ).encode("utf-8")
    ).hexdigest()[:24]
    raw_data = {
        "stream_id": result_id,
        "external_id": external_id,
        "capability": capability,
        "file_idx": safe_int(stream.file_idx),
        "has_info_hash": hash_value is not None,
        "has_url": url is not None,
        "has_external_url": external_url is not None,
        "source_count": len(stream.sources),
        "filename": clean_text(stream.behavior_hints.filename, max_length=300),
        "not_web_ready": stream.behavior_hints.not_web_ready,
    }
    return SearchResult(
        provider=provider_slug,
        provider_result_id=result_id,
        title=title,
        media_type=media_type if media_type in {"movie", "series"} else "other",
        info_hash=hash_value,
        magnet_url=magnet,
        source_url=source_url,
        quality=fields.get("quality"),
        languages=fields.get("languages", []),
        size_bytes=safe_int(stream.behavior_hints.video_size) or fields.get("size_bytes"),
        seeders=fields.get("seeders"),
        tracker=fields.get("tracker") or (trackers[0] if trackers else None),
        trackers=[*trackers, *fields.get("trackers", [])],
        codec=fields.get("codec"),
        audio_codec=fields.get("audio_codec"),
        audio_channels=fields.get("audio_channels"),
        source_type=fields.get("source_type"),
        release_group=fields.get("release_group"),
        raw_data=raw_data,
        download_capability=capability,
    )


def _recognized_trackers(sources: list[str]) -> list[str]:
    """Accept only the explicit tracker source syntax from the Stremio protocol."""

    trackers: list[str] = []
    for source in sources:
        if not isinstance(source, str) or any(ord(char) < 32 or ord(char) == 127 for char in source):
            continue
        match = _TRACKER_RE.fullmatch(source.strip())
        if not match:
            continue
        candidate = match.group(1) + match.group(2)
        parsed = urlsplit(candidate)
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            continue
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _SENSITIVE_TRACKER_KEYS
        ]
        candidate = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
        if candidate.casefold() not in {item.casefold() for item in trackers}:
            trackers.append(candidate)
    return trackers


def _stream_trackers(stream: StremioStream) -> list[str]:
    """Combine protocol tracker sources with trackers embedded in a magnet URL."""

    trackers = _recognized_trackers(stream.sources)
    if stream.url and stream.url.casefold().startswith("magnet:"):
        try:
            for tracker in parse_magnet(stream.url).trackers:
                if tracker.casefold() not in {item.casefold() for item in trackers}:
                    trackers.append(tracker)
        except InvalidMagnetError:
            pass
    return trackers
