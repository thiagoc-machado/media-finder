"""qBittorrent handoff and local download history routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.dependencies import database_session
from app.exceptions import (
    CategoryNotConfiguredError,
    CategoryNotFoundError,
    InvalidMagnetError,
    QBitTorrentAuthenticationError,
    QBitTorrentTimeoutError,
    QBitTorrentUnavailableError,
)
from app.models.download_history import DownloadHistory
from app.routers.pages import build_page_context
from app.schemas.download import DownloadView
from app.security import validate_csrf_token
from app.services.book_download_service import BookDownloadError, BookDownloadService
from app.services.qbittorrent_service import QBitTorrentService
from app.utils.magnet import build_magnet, normalize_magnet, parse_magnet
from app.web_templates import templates

router = APIRouter(prefix="/downloads", tags=["downloads"])


@router.post("/books", name="save_book")
async def save_book(
    request: Request,
    result_token: str = Form(...),
    csrf_token: str | None = Form(None),
    db: Session = Depends(database_session),
):
    """Save one public PDF result in the mounted books directory."""

    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token inválido.")
    result = await request.app.state.result_store.get(result_token)
    if result is None:
        return _feedback(request, "failed", "Resultado expirado", http_status=410)
    if result.provider != "duckduckgo" or result.raw_data.get("media_kind") != "pdf" or not result.source_url:
        return _feedback(request, "failed", "Somente resultados PDF públicos podem ser salvos", http_status=400)
    try:
        filename = await BookDownloadService().save_pdf(result.source_url, result.title)
    except BookDownloadError as exc:
        return _feedback(request, "failed", str(exc), category="books")
    row = DownloadHistory(
        title=result.title,
        provider=result.provider,
        media_type="other",
        category="books",
        status="completed",
        size_bytes=result.size_bytes,
    )
    db.add(row)
    _commit(db)
    return _feedback(request, "completed", f"PDF salvo em /books/{filename}", category="books", download_id=row.id)


@router.post("/torrent", name="send_torrent_file")
async def send_torrent_file(
    request: Request,
    result_token: str = Form(...),
    paused: bool = Form(False),
    csrf_token: str | None = Form(None),
    db: Session = Depends(database_session),
):
    """Fetch one public .torrent file and upload it to qBittorrent."""

    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token inválido.")
    result = await request.app.state.result_store.get(result_token)
    if result is None:
        return _feedback(request, "failed", "Resultado expirado", http_status=410)
    if result.provider != "duckduckgo" or result.raw_data.get("media_kind") != "torrent" or not result.source_url:
        return _feedback(request, "failed", "Somente resultados .torrent públicos podem ser enviados", http_status=400)

    media_type = result.media_type or "other"
    service: QBitTorrentService = request.app.state.qbittorrent_service
    category = service.get_category_for_media_type(media_type) or "unconfigured"
    try:
        content = await BookDownloadService().fetch_torrent(
            result.source_url,
            max_bytes=get_settings().torrent_file_max_size_bytes,
        )
        message = await service.add_torrent_file(
            content,
            result.title if result.title.casefold().endswith(".torrent") else f"{result.title}.torrent",
            media_type,
            result.provider,
            quality=result.quality,
            languages=result.languages,
            paused=paused,
        )
    except BookDownloadError as exc:
        return _feedback(request, "failed", str(exc), category=category)
    except (CategoryNotConfiguredError, CategoryNotFoundError) as exc:
        return _feedback(request, "failed", _safe_exception_message(exc), category=category)
    except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError) as exc:
        return _feedback(request, "failed", _safe_exception_message(exc), category=category)
    row = DownloadHistory(
        title=result.title,
        provider=result.provider,
        media_type=media_type,
        category=category,
        status="queued",
        size_bytes=result.size_bytes,
    )
    db.add(row)
    _commit(db)
    return _feedback(request, "queued", message, category=category, download_id=row.id)


@router.post("", name="create_download")
async def create_download(
    request: Request,
    result_token: str = Form(...),
    paused: bool = Form(False),
    csrf_token: str | None = Form(None),
    db: Session = Depends(database_session),
):
    """Recover one server-side result and hand it to qBittorrent."""

    if not validate_csrf_token(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token inválido.")

    result = await request.app.state.result_store.get(result_token)
    if result is None:
        return _feedback(request, "failed", "Result expired", http_status=410)

    try:
        magnet_url = _result_magnet(result)
        parsed = parse_magnet(magnet_url)
        normalized_magnet = normalize_magnet(magnet_url)
    except InvalidMagnetError:
        return _feedback(request, "failed", "Invalid magnet", http_status=400)

    media_type = result.media_type
    service: QBitTorrentService = request.app.state.qbittorrent_service
    category = service.get_category_for_media_type(media_type or "") or "unconfigured"
    if media_type not in {"movie", "series", "anime", "other"}:
        return _feedback(request, "failed", "Unsupported media type", category=category, http_status=400)
    if not service.get_category_for_media_type(media_type):
        outcome = _failed_outcome(
            parsed.info_hash,
            category,
            "No qBittorrent category is configured for this media type.",
        )
        row = _save_history(db, result, parsed.info_hash, category, outcome)
        return _feedback_from_outcome(request, outcome, row, http_status=400)

    try:
        categories = await service.list_categories()
    except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError) as exc:
        outcome = _failed_outcome(parsed.info_hash, category, _safe_exception_message(exc))
        row = _save_history(db, result, parsed.info_hash, category, outcome)
        return _feedback_from_outcome(request, outcome, row)
    if category.casefold() not in {name.casefold() for name in categories}:
        outcome = _failed_outcome(parsed.info_hash, category, "Configured qBittorrent category was not found")
        row = _save_history(db, result, parsed.info_hash, category, outcome)
        return _feedback_from_outcome(request, outcome, row)

    try:
        qbit_exists = await service.torrent_exists(parsed.info_hash)
    except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError) as exc:
        outcome = _failed_outcome(parsed.info_hash, category, _safe_exception_message(exc))
        row = _save_history(db, result, parsed.info_hash, category, outcome)
        return _feedback_from_outcome(request, outcome, row)

    if qbit_exists:
        outcome = _duplicate_outcome(parsed.info_hash, category)
        row = _save_history(db, result, parsed.info_hash, category, outcome)
        return _feedback_from_outcome(request, outcome, row)

    try:
        outcome = await service.add_torrent(
            normalized_magnet,
            media_type,
            result.provider,
            quality=result.quality,
            languages=result.languages,
            paused=paused,
        )
    except (CategoryNotConfiguredError, CategoryNotFoundError) as exc:
        outcome = _failed_outcome(parsed.info_hash, category, _safe_exception_message(exc))
    except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError) as exc:
        outcome = _failed_outcome(parsed.info_hash, category, _safe_exception_message(exc))
    except InvalidMagnetError:
        outcome = _failed_outcome(parsed.info_hash, category, "Invalid magnet")
    row = _save_history(db, result, parsed.info_hash, category, outcome)
    return _feedback_from_outcome(request, outcome, row)


@router.get("", name="downloads")
async def download_history(
    request: Request,
    page: int = 1,
    db: Session = Depends(database_session),
):
    """Render paginated local download history."""

    if page < 1:
        raise HTTPException(status_code=400, detail="Página inválida.")
    page_size = 25
    total = db.scalar(select(func.count()).select_from(DownloadHistory)) or 0
    rows = db.scalars(
        select(DownloadHistory)
        .order_by(desc(DownloadHistory.created_at), desc(DownloadHistory.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    total_pages = max(1, (total + page_size - 1) // page_size)
    context = {
        **build_page_context(request, db),
        "downloads": [_download_view(row) for row in rows],
        "downloads_page": page,
        "downloads_total_pages": total_pages,
    }
    return templates.TemplateResponse(request=request, name="downloads.html", context=context)


@router.get("/{download_id}/status", name="download_status")
async def download_status(
    request: Request,
    download_id: int,
    db: Session = Depends(database_session),
):
    """Refresh one local history record from qBittorrent by its stored hash."""

    row = db.get(DownloadHistory, download_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Download não encontrado.")
    error_message = None
    torrent = None
    if row.qbittorrent_hash or row.info_hash:
        try:
            torrent = await request.app.state.qbittorrent_service.get_torrent(row.qbittorrent_hash or row.info_hash)
        except (QBitTorrentAuthenticationError, QBitTorrentTimeoutError, QBitTorrentUnavailableError) as exc:
            error_message = _safe_exception_message(exc)

    if torrent is None:
        row.status = "unknown" if error_message is None else "failed"
        row.error_message = error_message
    else:
        row.status = _local_status_for_qbit_state(torrent.state)
        row.error_message = None
        row.qbittorrent_hash = torrent.info_hash
    _commit(db)
    view = _download_view(row)
    if request.headers.get("HX-Request", "").casefold() == "true":
        return templates.TemplateResponse(
            request=request,
            name="partials/download_status.html",
            context={"download": view, "torrent": torrent},
        )
    return JSONResponse(content={"download": view, "torrent": torrent.model_dump() if torrent else None})


def _result_magnet(result) -> str:
    """Build a tracker-free magnet when a stored result only has its hash."""

    if result.magnet_url:
        return result.magnet_url
    if result.info_hash:
        return build_magnet(result.info_hash, trackers=result.trackers)
    raise InvalidMagnetError("Result has no magnet or info hash")


def _save_history(db: Session, result, info_hash: str, category: str, outcome) -> DownloadHistory:
    """Persist handoff metadata while deliberately leaving magnet_url NULL."""

    row = DownloadHistory(
        title=result.title,
        provider=result.provider,
        info_hash=info_hash,
        magnet_url=None,
        media_type=result.media_type,
        quality=result.quality,
        language=", ".join(result.languages)[:120] if result.languages else None,
        size_bytes=result.size_bytes,
        seeders=result.seeders,
        category=category,
        qbittorrent_hash=info_hash if outcome.status in {"queued", "duplicate"} else None,
        status=outcome.status,
        error_message=outcome.message if outcome.status == "failed" else None,
    )
    db.add(row)
    _commit(db)
    return row


def _commit(db: Session) -> None:
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()


def _duplicate_outcome(info_hash: str, category: str):
    from app.schemas.download import AddTorrentResult

    return AddTorrentResult(
        status="duplicate",
        info_hash=info_hash,
        category=category,
        message="Already exists in qBittorrent",
    )


def _failed_outcome(info_hash: str, category: str, message: str):
    from app.schemas.download import AddTorrentResult

    return AddTorrentResult(status="failed", info_hash=info_hash, category=category, message=message)


def _feedback_from_outcome(request: Request, outcome, row: DownloadHistory, *, http_status: int = 200):
    return _feedback(
        request,
        outcome.status,
        outcome.message,
        category=outcome.category,
        info_hash=outcome.info_hash,
        download_id=row.id,
        http_status=http_status,
    )


def _feedback(
    request: Request,
    status: str,
    message: str,
    *,
    category: str | None = None,
    info_hash: str | None = None,
    download_id: int | None = None,
    http_status: int = 200,
):
    return templates.TemplateResponse(
        request=request,
        name="partials/download_feedback.html",
        context={
            "download_status": status,
            "download_message": message,
            "download_category": category,
            "download_info_hash": info_hash,
            "download_id": download_id,
        },
        status_code=http_status,
    )


def _download_view(row: DownloadHistory) -> dict:
    return DownloadView(
        id=row.id,
        title=row.title,
        provider=row.provider,
        media_type=row.media_type,
        quality=row.quality,
        language=row.language,
        category=row.category,
        status=row.status,
        error_message=row.error_message,
        created_at=(row.created_at.isoformat() if isinstance(row.created_at, datetime) else ""),
        info_hash=row.info_hash,
        qbittorrent_hash=row.qbittorrent_hash,
    ).model_dump()


def _local_status_for_qbit_state(state: str) -> str:
    normalized = state.casefold()
    if normalized in {"metadl"}:
        return "metadata"
    if normalized in {"stalleddl"}:
        return "stalled"
    if normalized in {"downloading", "forceddl"}:
        return "downloading"
    if normalized in {"uploading", "stalledup", "pausedup", "completed"}:
        return "completed"
    if normalized in {"missingfiles", "error"}:
        return "failed"
    return "unknown"


def _safe_exception_message(exc: Exception) -> str:
    if isinstance(exc, CategoryNotConfiguredError):
        return "No qBittorrent category is configured for this media type."
    if isinstance(exc, CategoryNotFoundError):
        return "Configured qBittorrent category was not found"
    if isinstance(exc, QBitTorrentAuthenticationError):
        return "qBittorrent authentication failed"
    if isinstance(exc, QBitTorrentTimeoutError):
        return "qBittorrent operation timed out"
    return "qBittorrent unavailable"
