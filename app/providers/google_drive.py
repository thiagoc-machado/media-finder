"""Read-only Google Drive folder provider for user-authorized shared content."""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

from app.clients.http_client import ProviderHTTPClient
from app.config import Settings, get_settings
from app.exceptions import ProviderConfigurationError, ProviderError, ProviderInvalidResponseError
from app.providers.real_utils import clean_text, safe_datetime, safe_external_url, safe_int
from app.schemas.provider import ProviderHealth
from app.schemas.search import SearchRequest, SearchResult
from app.services.normalization_service import normalize_result

_FOLDER_RE = re.compile(r"/folders/([A-Za-z0-9_-]+)")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
_DRIVE_MIME = "application/vnd.google-apps.folder"


class GoogleDriveProvider:
    """Search only the explicitly configured Google Drive folder."""

    slug = "google_drive"
    name = "Google Drive"

    def __init__(self, settings: Settings | None = None, *, http_client: ProviderHTTPClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._api_key = self.settings.google_drive_api_key.strip()
        self._folder_id = _folder_id_from_url(self.settings.google_drive_folder_url)
        self._http = http_client or ProviderHTTPClient(
            "https://www.googleapis.com/drive/v3",
            timeout_seconds=self.settings.google_drive_timeout_seconds,
        )
        self._owns_http = http_client is None

    async def health_check(self) -> ProviderHealth:
        """Check API access to the configured folder without listing its contents."""

        if not self.settings.google_drive_enabled:
            return ProviderHealth(slug=self.slug, available=False, error="Google Drive is disabled")
        try:
            if not self._api_key or not self._folder_id:
                raise ProviderConfigurationError("Google Drive folder URL and API key are required")
            started = time.perf_counter()
            await self._list_files("", page_size=1)
            return ProviderHealth(
                slug=self.slug,
                available=True,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except ProviderError as exc:
            return ProviderHealth(slug=self.slug, available=False, error=str(exc))

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        """Search file names in the configured folder; never download or recurse globally."""

        if not self._api_key or not self._folder_id:
            raise ProviderConfigurationError("Google Drive folder URL and API key are required")
        rows = await self._list_files(request.query, page_size=self.settings.google_drive_max_results)
        results = [_result_from_file(row, request) for row in rows]
        return [normalize_result(result) for result in results if result is not None]

    async def close(self) -> None:
        if self._owns_http:
            await self._http.close()

    async def _list_files(self, query: str, *, page_size: int) -> list[dict[str, Any]]:
        if not self._folder_id:
            raise ProviderConfigurationError("Google Drive folder URL is invalid")
        parent = self._folder_id.replace("'", "\\'")
        clauses = [f"'{parent}' in parents", "trashed = false", f"mimeType != '{_DRIVE_MIME}'"]
        if query.strip():
            escaped = query.replace("\\", "\\\\").replace("'", "\\'")
            clauses.append(f"name contains '{escaped}'")
        payload = await self._http.get_json(
            "/files",
            params={
                "key": self._api_key,
                "q": " and ".join(clauses),
                "pageSize": min(page_size, 1000),
                "orderBy": "name_natural",
                "fields": "files(id,name,mimeType,size,modifiedTime,webViewLink,webContentLink)",
            },
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("files", []), list):
            raise ProviderInvalidResponseError("Google Drive returned an invalid file list")
        return [item for item in payload["files"] if isinstance(item, dict)]


def _folder_id_from_url(value: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or parsed.hostname not in {"drive.google.com", "www.drive.google.com"}:
        return None
    match = _FOLDER_RE.search(parsed.path)
    candidate = match.group(1) if match else parse_qs(parsed.query).get("id", [None])[0]
    return candidate if isinstance(candidate, str) and _ID_RE.fullmatch(candidate) else None


def _result_from_file(payload: dict[str, Any], request: SearchRequest) -> SearchResult | None:
    file_id = clean_text(payload.get("id"), max_length=200)
    title = clean_text(payload.get("name"), max_length=500)
    source_url = safe_external_url(payload.get("webViewLink"))
    if not file_id or not title or not source_url:
        return None
    return SearchResult(
        provider="google_drive",
        provider_result_id=file_id,
        title=title,
        media_type=request.media_type if request.media_type != "all" else None,
        source_url=source_url,
        size_bytes=safe_int(payload.get("size")),
        published_at=safe_datetime(payload.get("modifiedTime")),
        raw_data={"file_id": file_id, "mime_type": clean_text(payload.get("mimeType"), max_length=120)},
        download_capability="external",
    )
