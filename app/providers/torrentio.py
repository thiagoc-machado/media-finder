"""Torrentio Stremio addon provider."""

from app.config import Settings
from app.providers.parsers.torrentio_parser import parse_torrentio_stream
from app.providers.stremio_provider import StremioAddonProvider


class TorrentioProvider(StremioAddonProvider):
    """Consume only Torrentio's configured manifest and stream resources."""

    slug = "torrentio"
    name = "Torrentio"

    def __init__(self, settings: Settings, *, http_client=None) -> None:
        super().__init__(
            settings,
            manifest_url=settings.torrentio_manifest_url,
            timeout_seconds=settings.torrentio_timeout_seconds,
            cache_ttl_seconds=settings.torrentio_cache_ttl_seconds,
            max_results=settings.torrentio_max_results,
            max_concurrency=settings.torrentio_max_concurrency,
            http_client=http_client,
            parser=parse_torrentio_stream,
        )
