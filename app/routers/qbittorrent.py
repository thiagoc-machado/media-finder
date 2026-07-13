"""Read-only qBittorrent health and category capability endpoints."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.exceptions import QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError
from app.schemas.download import QBitTorrentCategoriesResponse, QBitTorrentHealth

router = APIRouter(prefix="/qbittorrent", tags=["qbittorrent"])


@router.get("/health", response_model=QBitTorrentHealth)
async def qbittorrent_health(request: Request) -> QBitTorrentHealth:
    """Return qBittorrent availability without exposing connection details."""

    return await request.app.state.qbittorrent_service.health_check()


@router.get("/categories", response_model=QBitTorrentCategoriesResponse)
async def qbittorrent_categories(request: Request) -> QBitTorrentCategoriesResponse | JSONResponse:
    """Return discovered categories and configured download capabilities."""

    service = request.app.state.qbittorrent_service
    try:
        categories = await service.list_categories()
        validation = await service.validate_configured_categories()
    except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError):
        return JSONResponse(status_code=503, content={"error": "qBittorrent unavailable"})

    valid = [
        item.configured_category
        for item in validation.categories
        if item.available_for_download and item.configured_category
    ]
    missing = [
        item.configured_category for item in validation.categories if item.configured_category and not item.exists
    ]
    return QBitTorrentCategoriesResponse(
        categories=list(categories.values()),
        validation=validation,
        valid_categories=valid,
        missing_categories=missing,
    )
