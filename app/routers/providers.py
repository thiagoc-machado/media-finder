"""Provider status routes."""

from fastapi import APIRouter, HTTPException, Request

from app.exceptions import ProviderError
from app.providers.jackett import JackettProvider
from app.providers.prowlarr import ProwlarrProvider
from app.providers.registry import ProviderNotFoundError, ProviderRegistry
from app.schemas.provider import ProviderHealth, ProviderIndexer

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/health", response_model=list[ProviderHealth])
async def provider_health(request: Request) -> list[ProviderHealth]:
    """Return health for all enabled providers in registry priority order."""

    registry: ProviderRegistry = request.app.state.provider_registry
    return await registry.health_checks()


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
