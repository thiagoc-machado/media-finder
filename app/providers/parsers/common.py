"""Conservative text extraction shared by Stremio addon parsers."""

from __future__ import annotations

import re
from typing import Any

from app.providers.real_utils import clean_text, safe_int
from app.schemas.stremio import StremioStream
from app.utils.release_parser import parse_release
from app.utils.size import parse_size

_SIZE_RE = re.compile(r"(?<![A-Za-z])(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)\b", re.IGNORECASE)
_SEED_RE = re.compile(r"(?:seeders?|seeds?|seed|👤)\s*[:=\-]?\s*(\d+)", re.IGNORECASE)
_LANGUAGE_TOKENS = ("PT-BR", "PTBR", "PT-PT", "CASTELLANO", "LATINO", "DUAL AUDIO", "ENGLISH", "MULTI")


def parse_stream_text(stream: StremioStream) -> dict[str, Any]:
    """Extract only common release evidence from names and descriptions."""

    text = "\n".join(value for value in (stream.title, stream.name, stream.description) if isinstance(value, str))
    parsed = parse_release(text)
    size_bytes = safe_int(stream.behavior_hints.video_size)
    if size_bytes is None:
        match = _SIZE_RE.search(text)
        if match:
            try:
                size_bytes = parse_size(f"{match.group(1)} {match.group(2)}")
            except ValueError:
                size_bytes = None
    seed_match = _SEED_RE.search(text)
    seeders = safe_int(seed_match.group(1)) if seed_match else None
    languages = []
    language_names = {
        "PT-BR": "PT-BR",
        "PTBR": "PT-BR",
        "PT-PT": "PT-PT",
        "CASTELLANO": "Castellano",
        "LATINO": "Latino",
        "DUAL AUDIO": "Dual Audio",
        "ENGLISH": "English",
        "MULTI": "Multi",
    }
    upper_text = text.upper()
    for token in _LANGUAGE_TOKENS:
        if token in upper_text:
            languages.append(language_names[token])
    return {
        "quality": parsed.quality,
        "languages": languages or parsed.languages,
        "size_bytes": size_bytes,
        "seeders": seeders,
        "codec": parsed.codec,
        "audio_codec": parsed.audio_codec,
        "audio_channels": parsed.audio_channels,
        "source_type": parsed.source_type,
        "release_group": parsed.release_group,
        "tracker": _extract_label(text, "tracker"),
    }


def _extract_label(text: str, label: str) -> str | None:
    match = re.search(rf"\b{label}\s*[:=]\s*([^\s|,]+)", text, re.IGNORECASE)
    return clean_text(match.group(1), max_length=160) if match else None
