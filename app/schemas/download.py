"""Schemas for qBittorrent handoff, category validation, and status views."""

from typing import Literal

from pydantic import BaseModel, Field


class QBitTorrentHealth(BaseModel):
    """Safe qBittorrent availability information."""

    available: bool
    version: str | None = None
    latency_ms: float | None = None
    error: str | None = None


class QBitTorrentCategory(BaseModel):
    """One category reported by qBittorrent."""

    name: str
    save_path: str | None = None


class CategoryValidationItem(BaseModel):
    """Configured category status for one media type."""

    media_type: str
    configured_category: str | None = None
    exists: bool = False
    available_for_download: bool = False
    error: str | None = None


class CategoryValidationResult(BaseModel):
    """All configured and intentionally disabled media categories."""

    categories: list[CategoryValidationItem] = Field(default_factory=list)


class AddTorrentResult(BaseModel):
    """Outcome of an idempotent qBittorrent add operation."""

    status: Literal["queued", "duplicate", "failed"]
    info_hash: str
    category: str
    message: str


class TorrentStatus(BaseModel):
    """Normalized qBittorrent torrent status."""

    info_hash: str
    name: str
    state: str
    progress: float
    downloaded_bytes: int
    total_size_bytes: int
    download_speed: int
    eta_seconds: int | None = None
    category: str | None = None
    tags: list[str] = Field(default_factory=list)


class DownloadView(BaseModel):
    """Safe projection of a local download history record for HTML."""

    id: int
    title: str
    provider: str
    media_type: str
    quality: str | None = None
    language: str | None = None
    category: str
    status: str
    error_message: str | None = None
    created_at: str
    info_hash: str | None = None
    qbittorrent_hash: str | None = None


class DownloadPage(BaseModel):
    """Paginated download history response used by templates and tests."""

    items: list[DownloadView] = Field(default_factory=list)
    page: int
    total_pages: int


class QBitTorrentCategoriesResponse(BaseModel):
    """Safe JSON response for the category capability endpoint."""

    categories: list[QBitTorrentCategory] = Field(default_factory=list)
    validation: CategoryValidationResult
    valid_categories: list[str] = Field(default_factory=list)
    missing_categories: list[str] = Field(default_factory=list)
