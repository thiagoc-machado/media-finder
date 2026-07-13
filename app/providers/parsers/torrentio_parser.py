"""Tolerant Torrentio stream parser."""

from app.providers.parsers.common import parse_stream_text
from app.schemas.stremio import StremioStream


def parse_torrentio_stream(stream: StremioStream) -> dict:
    """Parse Torrentio's human-readable release text without relying on layout."""

    return parse_stream_text(stream)
