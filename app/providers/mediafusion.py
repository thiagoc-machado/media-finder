"""MediaFusion Stremio addon provider."""

from app.config import Settings
from app.providers.parsers.mediafusion_parser import parse_mediafusion_stream
from app.providers.stremio_provider import StremioAddonProvider


class MediaFusionProvider(StremioAddonProvider):
    """Consume only MediaFusion movie and series stream resources."""

    slug = "mediafusion"
    name = "MediaFusion"
    supported_media_types = frozenset({"movie", "series"})

    def __init__(self, settings: Settings, *, http_client=None) -> None:
        super().__init__(
            settings,
            manifest_url=settings.mediafusion_manifest_url,
            timeout_seconds=settings.mediafusion_timeout_seconds,
            cache_ttl_seconds=settings.mediafusion_cache_ttl_seconds,
            max_results=settings.mediafusion_max_results,
            max_concurrency=settings.mediafusion_max_concurrency,
            http_client=http_client,
            ignore_live=True,
            parser=parse_mediafusion_stream,
        )
