"""Dedicated public-file search flow, separate from media/release searches."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import database_session
from app.exceptions import ProviderError
from app.providers.registry import ProviderNotFoundError
from app.routers.pages import build_page_context
from app.schemas.search import SearchRequest
from app.web_templates import templates

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", name="file_search")
async def file_search(request: Request, q: str = "", db: Session = Depends(database_session)):
    """Search public PDFs and torrent files without invoking media providers."""

    query = " ".join(q.split()).strip()
    file_type: Literal["all", "torrent", "pdf", "music", "video", "zip"] = request.query_params.get("file_type", "all")  # type: ignore[assignment]
    if file_type not in {"all", "torrent", "pdf", "music", "video", "zip"}:
        file_type = "all"
    try:
        page = max(1, min(int(request.query_params.get("page", "1") or 1), 1000))
    except ValueError:
        page = 1
    try:
        limit = max(10, min(int(request.query_params.get("limit", "25") or 25), 100))
    except ValueError:
        limit = 25
    context = {**build_page_context(request, db), "file_query": query, "file_results": [], "file_error": None,
               "file_type": file_type, "file_page": page, "file_limit": limit, "file_total": 0,
               "file_has_next": False}
    if not query:
        return templates.TemplateResponse(request=request, name="files.html", context=context)
    if len(query) < 2:
        context["file_error"] = "Informe pelo menos 2 caracteres."
        return templates.TemplateResponse(request=request, name="files.html", context=context, status_code=400)

    try:
        provider = request.app.state.provider_registry.get("duckduckgo")
        results = await provider.search(SearchRequest(query=query, media_type="all", file_type=file_type))
        tokens = await request.app.state.result_store.save_many(results)
        context["file_total"] = len(results)
        start = (page - 1) * limit
        context["file_results"] = [
            {"result": result, "result_token": token}
            for result, token in zip(results[start : start + limit], tokens[start : start + limit], strict=True)
        ]
        context["file_has_next"] = start + limit < len(results)
    except ProviderNotFoundError:
        context["file_error"] = "A busca de arquivos está desabilitada."
    except ProviderError as exc:
        context["file_error"] = str(exc)
    except Exception:
        context["file_error"] = "Não foi possível consultar a busca de arquivos."
    return templates.TemplateResponse(request=request, name="files.html", context=context)
