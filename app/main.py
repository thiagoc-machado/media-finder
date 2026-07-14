"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.clients.tmdb_client import TMDBClient
from app.config import get_settings
from app.providers.jackett import JackettProvider
from app.providers.mediafusion import MediaFusionProvider
from app.providers.mock import MockProvider
from app.providers.prowlarr import ProwlarrProvider
from app.providers.registry import ProviderRegistry
from app.providers.torrentio import TorrentioProvider
from app.routers import downloads, health, metadata, pages, providers, qbittorrent, search, settings
from app.services.metadata_result_store import MetadataResultStore
from app.services.metadata_service import MetadataService
from app.services.qbittorrent_service import QBitTorrentService
from app.services.rate_limiter import SearchRateLimiter
from app.services.result_store import SearchResultStore

settings_config = get_settings()
settings_config.validate_security()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Release provider HTTP clients when the application stops."""

    yield
    await application.state.metadata_service.close()
    for provider in application.state.provider_instances:
        await provider.close()


app = FastAPI(title=settings_config.app_name, version=__version__, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings_config.app_secret_key,
    same_site="lax",
    # TLS is normally terminated by the home-server reverse proxy. Keep the
    # cookie usable for the local HTTP smoke tests as well; HttpOnly and Lax
    # remain enabled by Starlette's SessionMiddleware.
    https_only=False,
)
provider_registry = ProviderRegistry()
provider_registry.register(MockProvider(), priority=10)
provider_instances = []
if settings_config.prowlarr_enabled:
    prowlarr_provider = ProwlarrProvider(settings_config)
    provider_registry.register(prowlarr_provider, priority=20)
    provider_instances.append(prowlarr_provider)
if settings_config.jackett_enabled:
    jackett_provider = JackettProvider(settings_config)
    provider_registry.register(jackett_provider, priority=30)
    provider_instances.append(jackett_provider)
if settings_config.torrentio_enabled and settings_config.torrentio_manifest_url:
    torrentio_provider = TorrentioProvider(settings_config)
    provider_registry.register(torrentio_provider, priority=40)
    provider_instances.append(torrentio_provider)
if settings_config.mediafusion_enabled and settings_config.mediafusion_manifest_url:
    mediafusion_provider = MediaFusionProvider(settings_config)
    provider_registry.register(mediafusion_provider, priority=50)
    provider_instances.append(mediafusion_provider)
app.state.provider_registry = provider_registry
app.state.settings_config = settings_config
app.state.metadata_service = MetadataService(TMDBClient(settings_config))
app.state.metadata_result_store = MetadataResultStore(
    max_items=settings_config.metadata_result_store_max_items,
    default_ttl_seconds=settings_config.metadata_result_token_ttl_seconds,
)
app.state.provider_instances = provider_instances
app.state.result_store = SearchResultStore(
    ttl_seconds=settings_config.search_result_token_ttl_seconds,
    max_items=settings_config.search_result_store_max_items,
)
app.state.search_rate_limiter = SearchRateLimiter(
    requests=settings_config.search_rate_limit_requests,
    window_seconds=settings_config.search_rate_limit_window_seconds,
)
app.state.metadata_rate_limiter = SearchRateLimiter(
    requests=settings_config.metadata_rate_limit_requests,
    window_seconds=settings_config.metadata_rate_limit_window_seconds,
)
app.state.qbittorrent_service = QBitTorrentService(settings_config)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages.router)
app.include_router(health.router)
app.include_router(qbittorrent.router)
app.include_router(search.router)
app.include_router(metadata.router)
app.include_router(downloads.router)
app.include_router(providers.router)
app.include_router(settings.router)
