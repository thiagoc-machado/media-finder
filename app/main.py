"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.config import get_settings
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry
from app.routers import downloads, health, pages, providers, qbittorrent, search, settings
from app.services.qbittorrent_service import QBitTorrentService
from app.services.rate_limiter import SearchRateLimiter
from app.services.result_store import SearchResultStore

settings_config = get_settings()
settings_config.validate_security()
app = FastAPI(title=settings_config.app_name, version=__version__)
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
provider_registry.register(MockProvider())
app.state.provider_registry = provider_registry
app.state.result_store = SearchResultStore(
    ttl_seconds=settings_config.search_result_token_ttl_seconds,
    max_items=settings_config.search_result_store_max_items,
)
app.state.search_rate_limiter = SearchRateLimiter(
    requests=settings_config.search_rate_limit_requests,
    window_seconds=settings_config.search_rate_limit_window_seconds,
)
app.state.qbittorrent_service = QBitTorrentService(settings_config)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages.router)
app.include_router(health.router)
app.include_router(qbittorrent.router)
app.include_router(search.router)
app.include_router(downloads.router)
app.include_router(providers.router)
app.include_router(settings.router)
