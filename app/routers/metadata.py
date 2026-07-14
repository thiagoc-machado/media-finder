"""HTMX and JSON metadata routes for the TMDB title-resolution subphase."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from app.exceptions import ProviderError
from app.routers.pages import build_page_context
from app.schemas.metadata import MetadataProviderHealth
from app.utils.metadata_images import tmdb_image_url
from app.web_templates import templates

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/search")
async def metadata_search(
    request: Request,
    query: str = Query(default=""),
    media_type: Literal["movie", "series", "all"] = "all",
    age_limit: int = Query(default=13, ge=0, le=18),
):
    """Search TMDB and return safe candidate cards as an HTMX partial."""

    settings = request.app.state.settings_config
    if not await _allow_metadata_request(request):
        return templates.TemplateResponse(
            request=request,
            name="partials/media_candidates.html",
            context={"metadata_error": "Muitas buscas de catálogo em pouco tempo. Aguarde e tente novamente."},
            status_code=429,
        )
    try:
        normalized_query = _validate_query(
            query,
            settings.metadata_search_min_length,
            settings.metadata_search_max_length,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/media_candidates.html",
            context={"metadata_error": str(exc), "metadata_candidates": []},
            status_code=400,
        )
    result = await request.app.state.metadata_service.search(normalized_query, media_type, max_age=age_limit)
    candidates = []
    for candidate in result.candidates:
        token = await request.app.state.metadata_result_store.save_candidate(
            candidate,
            ttl_seconds=settings.metadata_result_token_ttl_seconds,
        )
        candidates.append(
            {
                "candidate": candidate,
                "candidate_token": token,
                "poster_url": tmdb_image_url(settings, candidate.poster_path, "w342"),
                "backdrop_url": tmdb_image_url(settings, candidate.backdrop_path, "w780"),
            }
        )
    return templates.TemplateResponse(
        request=request,
        name="partials/media_candidates.html",
        context={
            "metadata_candidates": candidates,
            "metadata_errors": result.errors,
            "metadata_query": normalized_query,
            "metadata_media_type": media_type,
            "metadata_duration_ms": result.duration_ms,
            "metadata_age_limit": age_limit,
        },
    )


@router.get("/select/{candidate_token}")
async def metadata_select(request: Request, candidate_token: str):
    """Resolve one stored candidate without trusting browser-supplied IDs."""

    if not await _allow_metadata_request(request):
        return templates.TemplateResponse(
            request=request,
            name="partials/selected_media.html",
            context={"metadata_error": "Muitas buscas de catálogo em pouco tempo. Aguarde e tente novamente."},
            status_code=429,
        )
    candidate = await request.app.state.metadata_result_store.get_candidate(candidate_token)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidato expirado ou inexistente.")
    settings = request.app.state.settings_config
    try:
        resolved = await request.app.state.metadata_service.resolve_candidate(
            candidate,
            poster_url=tmdb_image_url(settings, candidate.poster_path, "w342"),
            show_specials=settings.metadata_show_specials,
        )
        resolved_token = await request.app.state.metadata_result_store.save_resolved(
            resolved,
            ttl_seconds=settings.metadata_result_token_ttl_seconds,
        )
    except (ValueError, ProviderError) as exc:
        return templates.TemplateResponse(
            request=request,
            name="partials/selected_media.html",
            context={"metadata_error": _friendly_metadata_error(exc)},
            status_code=_error_status(exc),
        )
    return templates.TemplateResponse(
        request=request,
        name="partials/selected_media.html",
        context={
            **build_page_context(request),
            "resolved_media": resolved,
            "resolved_media_token": resolved_token,
            "metadata_show_specials": settings.metadata_show_specials,
        },
    )


@router.get("/series/{resolved_token}/season/{season_number}")
async def resolved_series_season(request: Request, resolved_token: str, season_number: int):
    """Load episodes only for a season belonging to stored resolved media."""

    resolved = await request.app.state.metadata_result_store.get_resolved(resolved_token)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Mídia resolvida expirada ou inexistente.")
    if resolved.media_type != "series":
        raise HTTPException(status_code=400, detail="A mídia selecionada não é uma série.")
    if season_number < 0 or season_number > 1000:
        raise HTTPException(status_code=400, detail="Temporada inválida.")
    valid_seasons = {season.season_number for season in resolved.seasons}
    if season_number not in valid_seasons:
        raise HTTPException(status_code=400, detail="Temporada inválida para esta série.")
    try:
        season = await request.app.state.metadata_service.get_tv_season(resolved.tmdb_id, season_number)
    except (ValueError, ProviderError) as exc:
        raise HTTPException(status_code=_error_status(exc), detail=_friendly_metadata_error(exc)) from exc
    settings = request.app.state.settings_config
    episodes = [
        {
            "episode": episode,
            "still_url": tmdb_image_url(settings, episode.still_path, "w300"),
            "resolved_media_token": resolved_token,
        }
        for episode in season.episodes
        if episode.episode_number > 0
    ]
    return templates.TemplateResponse(
        request=request,
        name="partials/episode_list.html",
        context={
            **build_page_context(request),
            "season": season,
            "episode_views": episodes,
            "resolved_media": resolved,
            "resolved_media_token": resolved_token,
        },
    )


@router.get("/tmdb/health", response_model=MetadataProviderHealth)
async def tmdb_health(request: Request) -> MetadataProviderHealth:
    """Return TMDB availability without performing a broad search."""

    return await request.app.state.metadata_service.tmdb.health_check()


@router.get("/tmdb/{tmdb_id}/season/{season_number}")
async def tmdb_season(request: Request, tmdb_id: int, season_number: int):
    """Return episodes for one TMDB TV season."""

    try:
        season = await request.app.state.metadata_service.get_tv_season(tmdb_id, season_number)
    except (ValueError, ProviderError) as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    settings = request.app.state.settings_config
    episodes = [
        {
            "episode": episode,
            "still_url": tmdb_image_url(settings, episode.still_path, "w300"),
        }
        for episode in season.episodes
    ]
    return templates.TemplateResponse(
        request=request,
        name="partials/media_episodes.html",
        context={"season": season, "episode_views": episodes},
    )


@router.get("/tmdb/{media_type}/{tmdb_id}")
async def tmdb_details(request: Request, media_type: Literal["movie", "series"], tmdb_id: int):
    """Return selected TMDB details without trusting client-supplied metadata."""

    try:
        details = await request.app.state.metadata_service.get_details(media_type, tmdb_id)
    except (ValueError, ProviderError) as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    settings = request.app.state.settings_config
    return templates.TemplateResponse(
        request=request,
        name="partials/media_details.html",
        context={
            "metadata": details,
            "poster_url": tmdb_image_url(settings, details.poster_path, "w342"),
            "backdrop_url": tmdb_image_url(settings, details.backdrop_path, "w780"),
        },
    )


def _validate_query(query: str, minimum: int, maximum: int) -> str:
    if not isinstance(query, str):
        raise ValueError("Informe um título válido.")
    normalized = " ".join(query.split())
    if len(normalized) < minimum:
        raise ValueError(f"O título deve ter pelo menos {minimum} caracteres.")
    if len(normalized) > maximum:
        raise ValueError(f"O título deve ter no máximo {maximum} caracteres.")
    return normalized


async def _allow_metadata_request(request: Request) -> bool:
    client_key = request.client.host if request.client else "unknown"
    return await request.app.state.metadata_rate_limiter.allow(client_key)


def _error_status(error: Exception) -> int:
    return 400 if isinstance(error, ValueError) else 503


def _friendly_metadata_error(error: Exception) -> str:
    message = str(error) or "Não foi possível resolver a mídia."
    if "IMDb" in message or "imdb" in message:
        return "O TMDB não informou um IMDb válido para esta mídia."
    if "credentials" in message.casefold():
        return "O catálogo TMDB está sem credencial configurada."
    return message
