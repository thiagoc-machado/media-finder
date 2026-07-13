"""Deterministic parsing for common release-name conventions."""

import re

from pydantic import BaseModel, Field


class ParsedRelease(BaseModel):
    """Metadata inferred from a release title."""

    quality: str | None = None
    languages: list[str] = Field(default_factory=list)
    codec: str | None = None
    audio_codec: str | None = None
    audio_channels: str | None = None
    source_type: str | None = None
    release_group: str | None = None


_QUALITY_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:480|576|720|1080|2160)(?:p|i)(?![A-Za-z0-9])", re.IGNORECASE)
_QUALITY_ALIAS_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:4k|uhd)(?![A-Za-z0-9])", re.IGNORECASE)

_LANGUAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "PT-BR",
        re.compile(
            r"(?<![A-Za-z0-9])(?:pt[- _.]?br|portugu[eê]s(?:e)?[ -_.]+br|brazilian(?:[ -_.]+portuguese)?)\b",
            re.IGNORECASE,
        ),
    ),
    ("PT-PT", re.compile(r"(?<![A-Za-z0-9])(?:pt[- _.]?pt|portugu[eê]s(?:e)?[ -_.]+portugal)\b", re.IGNORECASE)),
    (
        "Castellano",
        re.compile(r"(?<![A-Za-z0-9])(?:castellano|espa[nñ]ol[ -_.]+espa[nñ]a|spanish[ -_.]+spain)\b", re.IGNORECASE),
    ),
    (
        "Latino",
        re.compile(
            r"(?<![A-Za-z0-9])(?:latino|espa[nñ]ol[ -_.]+latino|latin[ -_.]+spanish|spanish[ -_.]+latino)\b",
            re.IGNORECASE,
        ),
    ),
    ("English", re.compile(r"(?<![A-Za-z0-9])(?:english|ingl[eê]s)\b", re.IGNORECASE)),
    ("Original", re.compile(r"(?<![A-Za-z0-9])original\b", re.IGNORECASE)),
    ("Multi", re.compile(r"(?<![A-Za-z0-9])multi(?:[ -_.]+(?:audio|language))?\b", re.IGNORECASE)),
    ("Dual Audio", re.compile(r"(?<![A-Za-z0-9])dual[ -_.]+audio\b", re.IGNORECASE)),
)

_DUBBED_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:dublado|dublagem)\b", re.IGNORECASE)

_CODEC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("x265", re.compile(r"(?<![A-Za-z0-9])(?:x265|x\.265|h265|h\.265|hevc)\b", re.IGNORECASE)),
    ("x264", re.compile(r"(?<![A-Za-z0-9])(?:x264|x\.264|h264|h\.264|avc)\b", re.IGNORECASE)),
    ("AV1", re.compile(r"(?<![A-Za-z0-9])av1\b", re.IGNORECASE)),
)

_SOURCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("WEB-DL", re.compile(r"(?<![A-Za-z0-9])web(?:[- .]?dl)\b", re.IGNORECASE)),
    ("WEBRip", re.compile(r"(?<![A-Za-z0-9])web[- .]?rip\b", re.IGNORECASE)),
    ("BluRay", re.compile(r"(?<![A-Za-z0-9])blu[- .]?ray\b", re.IGNORECASE)),
    ("BDRip", re.compile(r"(?<![A-Za-z0-9])bdrip\b", re.IGNORECASE)),
    ("BRRip", re.compile(r"(?<![A-Za-z0-9])brrip\b", re.IGNORECASE)),
    ("HDTV", re.compile(r"(?<![A-Za-z0-9])hdtv\b", re.IGNORECASE)),
    ("DVDRip", re.compile(r"(?<![A-Za-z0-9])dvd[- .]?rip\b", re.IGNORECASE)),
    ("HDCAM", re.compile(r"(?<![A-Za-z0-9])hdcam\b", re.IGNORECASE)),
    ("CAM", re.compile(r"(?<![A-Za-z0-9])cam\b", re.IGNORECASE)),
    ("TS", re.compile(r"(?<![A-Za-z0-9])(?:ts|telesync)\b", re.IGNORECASE)),
)

_AUDIO_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("TrueHD", re.compile(r"(?<![A-Za-z0-9])truehd\b", re.IGNORECASE)),
    ("DTS-HD", re.compile(r"(?<![A-Za-z0-9])dts[- .]?hd\b", re.IGNORECASE)),
    ("DTS", re.compile(r"(?<![A-Za-z0-9])dts\b", re.IGNORECASE)),
    ("EAC3", re.compile(r"(?<![A-Za-z0-9])e[- .]?ac[- .]?3\b", re.IGNORECASE)),
    ("AC3", re.compile(r"(?<![A-Za-z0-9])ac[- .]?3\b", re.IGNORECASE)),
    ("DD+", re.compile(r"(?<![A-Za-z0-9])dd\+(?![A-Za-z0-9])", re.IGNORECASE)),
    ("DD", re.compile(r"(?<![A-Za-z0-9])dd\b", re.IGNORECASE)),
    ("AAC", re.compile(r"(?<![A-Za-z0-9])aac\b", re.IGNORECASE)),
    ("Atmos", re.compile(r"(?<![A-Za-z0-9])atmos\b", re.IGNORECASE)),
)

_CHANNEL_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:2\.0|5\.1|7\.1)(?![A-Za-z0-9])")
_GROUP_PATTERN = re.compile(r"-(?P<group>[A-Za-z0-9][A-Za-z0-9&+'_]{1,31})(?:\.[A-Za-z0-9]{2,5})?$")
_INVALID_GROUPS = {
    "aac",
    "ac3",
    "audio",
    "atmos",
    "av1",
    "bdrip",
    "bluray",
    "brrip",
    "cam",
    "dd",
    "dd+",
    "dl",
    "dts",
    "eac3",
    "h264",
    "h265",
    "hdtv",
    "hd",
    "hevc",
    "mkv",
    "mp4",
    "ts",
    "truehd",
    "ray",
    "rip",
    "480p",
    "576p",
    "720p",
    "1080i",
    "1080p",
    "2160p",
    "4k",
    "uhd",
    "avc",
    "multi",
    "dual",
    "web-dl",
    "webdl",
    "webrip",
    "x264",
    "x265",
}


def parse_release(title: str) -> ParsedRelease:
    """Parse release metadata without guessing from standalone numbers."""

    text = title or ""
    return ParsedRelease(
        quality=_parse_quality(text),
        languages=_parse_languages(text),
        codec=_first_normalized(text, _CODEC_PATTERNS),
        audio_codec=_first_normalized(text, _AUDIO_PATTERNS),
        audio_channels=_first_match(text, _CHANNEL_PATTERN),
        source_type=_first_normalized(text, _SOURCE_PATTERNS),
        release_group=_parse_release_group(text),
    )


def normalize_quality(value: str | None) -> str | None:
    """Normalize a quality value supplied by a provider."""

    if not value:
        return None
    match = _QUALITY_PATTERN.search(value)
    if match:
        return match.group(0).lower()
    if _QUALITY_ALIAS_PATTERN.search(value):
        return "2160p"
    return value.strip()


def normalize_language(value: str) -> str:
    """Normalize one language alias without inferring missing languages."""

    text = value.strip()
    if not text:
        return ""
    for canonical, pattern in _LANGUAGE_PATTERNS:
        if pattern.search(text):
            return canonical
    if _DUBBED_PATTERN.search(text):
        return "Dubbed"
    return text


def normalize_codec(value: str | None) -> str | None:
    """Normalize one video codec alias."""

    return _normalize_value(value, _CODEC_PATTERNS)


def normalize_source_type(value: str | None) -> str | None:
    """Normalize one release source alias."""

    return _normalize_value(value, _SOURCE_PATTERNS)


def normalize_audio_codec(value: str | None) -> str | None:
    """Normalize one audio codec alias."""

    return _normalize_value(value, _AUDIO_PATTERNS)


def normalize_audio_channels(value: str | None) -> str | None:
    """Normalize one audio channel value."""

    if not value:
        return None
    match = _CHANNEL_PATTERN.search(value)
    return match.group(0) if match else value.strip()


def _parse_quality(text: str) -> str | None:
    """Find an explicit quality token before considering aliases."""

    match = _QUALITY_PATTERN.search(text)
    if match:
        return match.group(0).lower()
    if _QUALITY_ALIAS_PATTERN.search(text):
        return "2160p"
    return None


def _parse_languages(text: str) -> list[str]:
    """Return canonical languages in a stable alias order."""

    languages = [canonical for canonical, pattern in _LANGUAGE_PATTERNS if pattern.search(text)]
    if _DUBBED_PATTERN.search(text) and "PT-BR" not in languages:
        languages.append("Dubbed")
    return _unique(languages)


def _parse_release_group(text: str) -> str | None:
    """Extract a final hyphenated release group only with release evidence."""

    if not any(pattern.search(text) for _, pattern in (*_CODEC_PATTERNS, *_SOURCE_PATTERNS)) and not (
        _QUALITY_PATTERN.search(text) or _QUALITY_ALIAS_PATTERN.search(text)
    ):
        return None
    match = _GROUP_PATTERN.search(text.rstrip())
    if not match:
        return None
    group = match.group("group").strip("._")
    if group.casefold() in _INVALID_GROUPS:
        return None
    return group


def _first_normalized(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    """Return the first canonical pattern match."""

    return next((canonical for canonical, pattern in patterns if pattern.search(text)), None)


def _first_match(text: str, pattern: re.Pattern[str]) -> str | None:
    """Return the first literal pattern match."""

    match = pattern.search(text)
    return match.group(0) if match else None


def _normalize_value(value: str | None, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> str | None:
    """Normalize a provider value if it contains a known alias."""

    if not value:
        return None
    return _first_normalized(value, patterns) or value.strip()


def _unique(values: list[str]) -> list[str]:
    """Deduplicate strings case-insensitively while preserving order."""

    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
