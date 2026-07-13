"""Health check endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app import __version__, database
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, responses={503: {"model": HealthResponse}})
async def health_check() -> HealthResponse | JSONResponse:
    """Return service and database health."""

    if not database.check_database():
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "error", "version": __version__},
        )
    return HealthResponse(status="ok", database="ok", version=__version__)
