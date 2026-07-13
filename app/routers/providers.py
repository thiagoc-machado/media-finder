"""Provider status routes."""

from fastapi import APIRouter, HTTPException, Request

from app.exceptions import ProviderError
from app.providers.jackett import JackettProvider
from app.providers.mediafusion import MediaFusionProvider
from app.providers.prowlarr import ProwlarrProvider
from app.providers.registry import ProviderNotFoundError, ProviderRegistry
from app.providers.torrentio import TorrentioProvider
from app.schemas.provider import ProviderHealth, ProviderIndexer, StremioProviderStatus

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/health", response_model=list[ProviderHealth])
async def provider_health(request: Request) -> list[ProviderHealth]:
    """Return health for all enabled providers in registry priority order."""

    registry: ProviderRegistry = request.app.state.provider_registry
    return await registry.health_checks()


@router.get("/torrentio/status", response_model=StremioProviderStatus)
async def torrentio_status(request: Request) -> StremioProviderStatus:
    """Return safe Torrentio status without exposing its manifest URL."""

    return await _stremio_status(request, "torrentio", TorrentioProvider, request.app.state.settings_config)


@router.get("/mediafusion/status", response_model=StremioProviderStatus)
async def mediafusion_status(request: Request) -> StremioProviderStatus:
    """Return safe MediaFusion status without exposing its manifest URL."""

    return await _stremio_status(request, "mediafusion", MediaFusionProvider, request.app.state.settings_config)


@router.get("/prowlarr/indexers", response_model=list[ProviderIndexer])
async def prowlarr_indexers(request: Request) -> list[ProviderIndexer]:
    """Return the safe enabled-indexer projection exposed by Prowlarr."""

    provider = _enabled_provider(request, "prowlarr", ProwlarrProvider)
    try:
        return await provider.list_indexers()
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/jackett/indexers")
async def jackett_indexers(request: Request) -> list[dict]:
    """Return safe status and capability projections for configured Jackett indexers."""

    provider = _enabled_provider(request, "jackett", JackettProvider)
    try:
        details = await provider.indexer_status()
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [
        {
            "id": item["indexer"].id,
            "name": item["name"],
            "enabled": item["valid"],
            "protocol": item["indexer"].protocol,
            "capabilities": item["indexer"].capabilities,
            "categories": item["indexer"].categories,
            "error": item["error"],
        }
        for item in details
    ]


def _enabled_provider(request: Request, slug: str, provider_type):
    """Resolve one enabled provider without leaking configuration details."""

    registry: ProviderRegistry = request.app.state.provider_registry
    try:
        registration = registry.registration(slug)
    except ProviderNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Provider não habilitado.") from exc
    if not registration.enabled or not isinstance(registration.provider, provider_type):
        raise HTTPException(status_code=404, detail="Provider não habilitado.")
    return registration.provider


async def _stremio_status(request: Request, slug: str, provider_type, settings) -> StremioProviderStatus:
    """Resolve a configured Stremio provider, including disabled status safely."""

    registry: ProviderRegistry = request.app.state.provider_registry
    try:
        registration = registry.registration(slug)
    except ProviderNotFoundError:
        enabled = bool(getattr(settings, f"{slug}_enabled", False))
        configured = bool(getattr(settings, f"{slug}_manifest_url", ""))
        return StremioProviderStatus(
            enabled=enabled and configured,
            available=False,
            error="Stremio addon is disabled" if not enabled else "Stremio addon manifest URL is not configured",
        )
    if not registration.enabled or not isinstance(registration.provider, provider_type):
        return StremioProviderStatus(enabled=False, available=False, error="Stremio addon is disabled")
    return await registration.provider.status()
