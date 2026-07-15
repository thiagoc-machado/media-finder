"""Server-rendered application pages."""

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import database_session
from app.models.search_history import SearchHistory
from app.schemas.search import SearchSort
from app.security import get_csrf_token
from app.web_templates import templates

router = APIRouter(tags=["pages"])


QUALITY_OPTIONS = ["2160p", "1080p", "1080i", "720p", "576p", "480p"]
LANGUAGE_OPTIONS = ["PT-BR", "PT-PT", "Castellano", "Latino", "English", "Multi", "Dual Audio", "Dubbed"]
CODEC_OPTIONS = ["x264", "x265", "AV1"]
SOURCE_OPTIONS = ["WEB-DL", "WEBRip", "BluRay", "BDRip", "BRRip", "HDTV", "DVDRip", "CAM", "TS"]
SORT_OPTIONS = [
    (SearchSort.SCORE_DESC.value, "Score"),
    (SearchSort.SEEDERS_DESC.value, "Seeders"),
    (SearchSort.QUALITY_DESC.value, "Quality"),
    (SearchSort.SIZE_ASC.value, "Smallest size"),
    (SearchSort.SIZE_DESC.value, "Largest size"),
    (SearchSort.PROVIDER_ASC.value, "Provider"),
    (SearchSort.TRACKER_ASC.value, "Tracker"),
    (SearchSort.PUBLISHED_AT_DESC.value, "Newest"),
]


@router.get("/", name="home")
async def home(request: Request, db: Session = Depends(database_session)):
    """Render the initial search workspace."""

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_page_context(request, db),
    )


@router.get("/providers", name="providers")
async def providers(request: Request):
    """Render the provider configuration placeholder."""

    return templates.TemplateResponse(request=request, name="providers.html", context=_page_context())


@router.get("/settings", name="settings")
async def settings(request: Request):
    """Render the application settings placeholder."""

    return templates.TemplateResponse(request=request, name="settings.html", context=_page_context())


def build_page_context(
    request: Request,
    db: Session | None = None,
    *,
    form_state: dict | None = None,
    form_error: str | None = None,
    result_context: dict | None = None,
) -> dict:
    """Build shared page data without exposing provider payloads."""

    settings = get_settings()
    provider_registry = request.app.state.provider_registry
    providers = [
        {
            "slug": provider.slug,
            "name": provider.name,
            "configured": getattr(provider, "is_configured", True),
        }
        for provider in provider_registry.enabled_providers()
        if provider.slug != "duckduckgo"
    ]
    state = form_state or _default_form_state([provider["slug"] for provider in providers if provider["configured"]])
    recent_history = _recent_history(db, limit=5) if db is not None else []
    context = {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "version": settings.version,
        "providers": providers,
        "form_state": state,
        "form_error": form_error,
        "quality_options": QUALITY_OPTIONS,
        "language_options": LANGUAGE_OPTIONS,
        "codec_options": CODEC_OPTIONS,
        "source_options": SOURCE_OPTIONS,
        "sort_options": SORT_OPTIONS,
        "recent_history": recent_history,
        "csrf_token": get_csrf_token(request),
        "download_categories": {
            media_type: settings.get_category_for_media_type(media_type)
            for media_type in ("movie", "series", "anime", "other")
        },
    }
    if result_context:
        context.update(result_context)
    return context


def _page_context() -> dict[str, str]:
    """Build the context used by the non-search placeholder pages."""

    settings = get_settings()
    return {"app_name": settings.app_name, "app_env": settings.app_env, "version": settings.version}


def _default_form_state(provider_slugs: list[str]) -> dict:
    """Return safe defaults for the first page render."""

    return {
        "query": "",
        "media_type": "all",
        "imdb_id": "",
        "providers": provider_slugs,
        "prowlarr_indexers": ["all"],
        "jackett_indexers": ["all"],
        "season": "",
        "episode": "",
        "languages": [],
        "qualities": [],
        "codecs": [],
        "source_types": [],
        "trackers": [],
        "min_size": "",
        "max_size": "",
        "min_seeders": "",
        "required_terms": "",
        "excluded_terms": "",
        "sort_by": SearchSort.SCORE_DESC.value,
        "weak_deduplication": True,
    }


def form_state_from_params(params) -> dict:
    """Convert validated query parameters into template-friendly values."""

    return {
        "query": params.query,
        "media_type": params.media_type,
        "imdb_id": params.imdb_id or "",
        "providers": params.providers,
        "prowlarr_indexers": params.prowlarr_indexers,
        "jackett_indexers": params.jackett_indexers,
        "season": params.season or "",
        "episode": params.episode or "",
        "languages": params.languages,
        "qualities": params.qualities,
        "codecs": params.codecs,
        "source_types": params.source_types,
        "trackers": params.trackers,
        "min_size": params.min_size or "",
        "max_size": params.max_size or "",
        "min_seeders": params.min_seeders if params.min_seeders is not None else "",
        "required_terms": params.required_terms or "",
        "excluded_terms": params.excluded_terms or "",
        "sort_by": params.sort_by.value,
        "weak_deduplication": params.weak_deduplication,
    }


def _recent_history(db: Session, *, limit: int) -> list[dict]:
    """Read a small, sanitized recent-history projection."""

    rows = db.scalars(select(SearchHistory).order_by(desc(SearchHistory.created_at)).limit(limit)).all()
    return [_history_view(row) for row in rows]


def _history_view(row: SearchHistory) -> dict:
    """Convert one history row to template data without sensitive fields."""

    try:
        providers = json.loads(row.providers_json)
    except (TypeError, ValueError):
        providers = []
    return {
        "id": row.id,
        "query": row.query,
        "media_type": row.media_type,
        "providers": providers if isinstance(providers, list) else [],
        "results_count": row.results_count,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
    }
