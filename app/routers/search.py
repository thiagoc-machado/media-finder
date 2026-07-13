"""HTMX search, history, and temporary-result detail routes."""

import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import database_session
from app.models.search_history import SearchHistory
from app.providers.registry import ProviderNotFoundError, ProviderRegistry
from app.routers.pages import build_page_context, form_state_from_params
from app.schemas.provider import ProcessedSearchResult
from app.schemas.web import SearchQueryParams
from app.services.pipeline_service import process_search_results
from app.services.scoring_service import ScoringPreferences
from app.services.search_service import SearchService
from app.web_templates import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.get("", name="search")
async def search(
    request: Request,
    db: Session = Depends(database_session),
):
    """Validate and execute one search, returning a partial for HTMX requests."""

    settings = get_settings()
    limiter = request.app.state.search_rate_limiter
    client_key = request.client.host if request.client else "unknown"
    if not await limiter.allow(client_key):
        return _search_error_response(
            request,
            db,
            "Muitas buscas em pouco tempo. Aguarde um minuto e tente novamente.",
            status_code=429,
        )

    try:
        params = _parse_query_params(request, settings)
        filters = params.to_filters()
        registry: ProviderRegistry = request.app.state.provider_registry
        _validate_providers(params, registry, settings.search_max_providers)
    except (ValidationError, ValueError, ProviderNotFoundError) as exc:
        message = _friendly_validation_error(exc)
        return _search_error_response(request, db, message, status_code=400)

    try:
        execution = await SearchService(
            request.app.state.provider_registry,
            default_timeout=settings.search_provider_timeout_seconds,
        ).search(params.to_search_request(), params.providers or None)
        processed = await process_search_results(
            execution,
            filters,
            ScoringPreferences(),
            params.sort_by,
            allow_weak_dedup=params.weak_deduplication,
        )
        await _record_history(db, params, filters, processed, execution.providers_requested)
        tokens = await request.app.state.result_store.save_many(processed.results)
        result_views = [
            {"result": result, "result_token": token} for result, token in zip(processed.results, tokens, strict=True)
        ]
    except Exception:
        logger.exception("Search request failed")
        return _search_error_response(
            request,
            db,
            "Não foi possível concluir a busca agora. Tente novamente.",
            status_code=500,
        )

    result_context = {
        "processed": processed,
        "result_views": result_views,
        "search_query": params.query,
        "search_params": form_state_from_params(params),
        "providers_requested": execution.providers_requested,
        "providers_succeeded": execution.providers_succeeded,
    }
    if _is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="partials/results_table.html",
            context={**build_page_context(request, db), **result_context},
        )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_page_context(
            request,
            db,
            form_state=form_state_from_params(params),
            result_context=result_context,
        ),
    )


@router.get("/history", name="search_history")
async def search_history(
    request: Request,
    page: int = 1,
    db: Session = Depends(database_session),
):
    """Render a bounded page of persisted, non-sensitive search metadata."""

    settings = get_settings()
    if page < 1:
        raise HTTPException(status_code=400, detail="Página inválida.")
    page_size = settings.search_history_page_size
    total = db.scalar(select(func.count()).select_from(SearchHistory)) or 0
    rows = db.scalars(
        select(SearchHistory)
        .order_by(desc(SearchHistory.created_at), desc(SearchHistory.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    history = [_history_view(row) for row in rows]
    total_pages = max(1, (total + page_size - 1) // page_size)
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            **build_page_context(request, db),
            "history": history,
            "history_page": page,
            "history_total_pages": total_pages,
        },
    )


@router.get("/result/{result_token}", name="search_result_detail")
async def search_result_detail(request: Request, result_token: str):
    """Render a temporary result detail without exposing its payload in the URL."""

    result = await request.app.state.result_store.get(result_token)
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado expirado ou inexistente.")
    context = {"result": result, "result_token": result_token}
    if _is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="partials/result_detail.html",
            context={**build_page_context(request), **context},
        )
    return templates.TemplateResponse(
        request=request,
        name="result_detail.html",
        context={**build_page_context(request), **context},
    )


def _parse_query_params(request: Request, settings) -> SearchQueryParams:
    """Convert repeated query-string keys into the bounded web schema."""

    list_fields = {"providers", "languages", "qualities", "codecs", "source_types", "trackers"}
    values: dict[str, object] = {}
    for key in request.query_params.keys():
        if key in list_fields:
            values[key] = request.query_params.getlist(key)
        else:
            values[key] = request.query_params.get(key)
    if "q" in values:
        values.setdefault("query", values["q"])
        values.pop("q")
    params = SearchQueryParams(**values)
    if len(params.query) < settings.search_query_min_length:
        raise ValueError(f"A busca deve ter pelo menos {settings.search_query_min_length} caracteres.")
    if len(params.query) > settings.search_query_max_length:
        raise ValueError(f"A busca deve ter no máximo {settings.search_query_max_length} caracteres.")
    return params


def _validate_providers(params: SearchQueryParams, registry: ProviderRegistry, max_providers: int) -> None:
    """Reject unknown or excessive provider selections before execution."""

    if len(params.providers) > max_providers:
        raise ValueError(f"Selecione no máximo {max_providers} providers.")
    registered = {registration.provider.slug for registration in registry.registrations()}
    enabled = {provider.slug for provider in registry.enabled_providers()}
    unknown = [slug for slug in params.providers if slug not in registered]
    if unknown:
        raise ProviderNotFoundError(f"Provider não registrado: {', '.join(unknown)}")
    disabled = [slug for slug in params.providers if slug not in enabled]
    if disabled:
        raise ValueError(f"Provider não habilitado: {', '.join(disabled)}")


async def _record_history(
    db: Session,
    params: SearchQueryParams,
    filters,
    processed: ProcessedSearchResult,
    providers_requested: list[str],
) -> None:
    """Persist only the safe metadata already defined by the initial schema."""

    providers = params.providers or providers_requested
    row = SearchHistory(
        query=params.query,
        media_type=params.media_type,
        providers_json=json.dumps(providers, ensure_ascii=False),
        filters_json=json.dumps(filters.model_dump(), ensure_ascii=False, sort_keys=True),
        results_count=len(processed.results),
        duration_ms=round(processed.duration_ms),
    )
    try:
        db.add(row)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not persist search history")


def _history_view(row: SearchHistory) -> dict:
    """Build a safe history row and reconstruct only a safe search URL."""

    try:
        providers = json.loads(row.providers_json)
    except (TypeError, ValueError):
        providers = []
    providers = providers if isinstance(providers, list) else []
    query = [("query", row.query), ("media_type", row.media_type)]
    query.extend(("providers", provider) for provider in providers if isinstance(provider, str))
    search_url = "/search?" + urlencode(query, doseq=True)
    return {
        "query": row.query,
        "media_type": row.media_type,
        "providers": providers,
        "results_count": row.results_count,
        "duration_ms": row.duration_ms,
        "created_at": row.created_at,
        "search_url": search_url,
    }


def _search_error_response(request: Request, db: Session, message: str, *, status_code: int):
    """Render friendly validation/internal errors in either page mode."""

    if _is_htmx(request):
        return templates.TemplateResponse(
            request=request,
            name="partials/results_table.html",
            context={"processed": None, "result_views": [], "search_error": message},
            status_code=status_code if status_code != 400 else 200,
        )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=build_page_context(request, db, form_error=message),
        status_code=status_code,
    )


def _friendly_validation_error(error: Exception) -> str:
    """Convert validation exceptions into one concise user-facing message."""

    if isinstance(error, ProviderNotFoundError):
        return str(error)
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        return str(first.get("msg", "Parâmetros inválidos.")).replace("Value error, ", "")
    return str(error) or "Parâmetros inválidos."


def _is_htmx(request: Request) -> bool:
    """Identify HTMX requests without trusting arbitrary browser payloads."""

    return request.headers.get("HX-Request", "").casefold() == "true"
