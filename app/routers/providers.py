"""Provider status routes."""

from fastapi import APIRouter, Request

from app.providers.registry import ProviderRegistry
from app.schemas.provider import ProviderHealth

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/health", response_model=list[ProviderHealth])
async def provider_health(request: Request) -> list[ProviderHealth]:
    """Return health for all enabled providers in registry priority order."""

    registry: ProviderRegistry = request.app.state.provider_registry
    return await registry.health_checks()
