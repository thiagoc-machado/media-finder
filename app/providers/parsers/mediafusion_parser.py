"""Tolerant MediaFusion stream parser."""

from app.providers.parsers.common import parse_stream_text
from app.schemas.stremio import StremioStream


def parse_mediafusion_stream(stream: StremioStream) -> dict:
    """Parse MediaFusion release evidence without executing returned URLs."""

    return parse_stream_text(stream)
