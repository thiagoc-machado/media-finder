"""Bounded downloads of explicitly identified public PDF files."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from app.config import Settings, get_settings

_DRIVE_HOSTS = {"drive.google.com", "www.drive.google.com"}
_DOWNLOAD_HOSTS = _DRIVE_HOSTS | {"drive.usercontent.google.com"}
_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9À-ÖØ-öø-ÿ._()\[\] -]+")
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024


class BookDownloadError(Exception):
    """Raised when a public PDF cannot be safely saved."""


class BookDownloadService:
    """Download one public Drive PDF into the configured books directory."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def save_pdf(self, source_url: str, title: str) -> str:
        file_id = _drive_file_id(source_url)
        if not file_id:
            raise BookDownloadError("Fonte de PDF pública inválida")
        books_dir = Path(self.settings.books_dir)
        if not books_dir.is_absolute():
            raise BookDownloadError("A pasta de e-books precisa ser um caminho absoluto")
        books_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_pdf_name(title)
        destination = _unique_destination(books_dir, filename)
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        max_bytes = self.settings.books_max_size_bytes
        temporary_path: Path | None = None
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.books_download_timeout_seconds),
                follow_redirects=True,
                trust_env=False,
                headers={"User-Agent": "Media-Finder/0.1.0", "Accept": "application/pdf,*/*"},
            ) as client:
                async with client.stream("GET", download_url) as response:
                    _validate_response(response, max_bytes)
                    _validate_redirect_hosts(response, label="PDF")
                    with tempfile.NamedTemporaryFile(
                        mode="wb", dir=books_dir, prefix=".media-finder-", suffix=".part", delete=False
                    ) as temporary:
                        temporary_path = Path(temporary.name)
                        total = 0
                        first_chunk = True
                        async for chunk in response.aiter_bytes(64 * 1024):
                            if not chunk:
                                continue
                            if first_chunk and not chunk.startswith(b"%PDF-"):
                                raise BookDownloadError("A fonte não retornou um PDF válido")
                            first_chunk = False
                            total += len(chunk)
                            if total > max_bytes:
                                raise BookDownloadError("O PDF excede o tamanho máximo permitido")
                            temporary.write(chunk)
                        if first_chunk:
                            raise BookDownloadError("A fonte retornou um arquivo vazio")
            temporary_path.replace(destination)
            temporary_path = None
            return destination.name
        except httpx.HTTPError as exc:
            raise BookDownloadError("Não foi possível acessar a fonte do PDF") from exc
        except OSError as exc:
            raise BookDownloadError("Não foi possível gravar o PDF em /books") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    async def fetch_torrent(self, source_url: str, *, max_bytes: int) -> bytes:
        """Fetch one public torrent file into bounded memory for qBittorrent."""

        file_id = _drive_file_id(source_url)
        if not file_id:
            raise BookDownloadError("Fonte de torrent pública inválida")
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        content = bytearray()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.books_download_timeout_seconds),
                follow_redirects=True,
                trust_env=False,
                headers={"User-Agent": "Media-Finder/0.1.0", "Accept": "application/x-bittorrent,*/*"},
            ) as client:
                async with client.stream("GET", download_url) as response:
                    _validate_response(response, max_bytes)
                    _validate_redirect_hosts(response, label="torrent")
                    async for chunk in response.aiter_bytes(64 * 1024):
                        content.extend(chunk)
                        if len(content) > max_bytes:
                            raise BookDownloadError("O arquivo .torrent excede o tamanho máximo permitido")
        except httpx.HTTPError as exc:
            raise BookDownloadError("Não foi possível acessar a fonte do torrent") from exc
        if not content.startswith(b"d"):
            raise BookDownloadError("A fonte não retornou um arquivo .torrent válido")
        return bytes(content)


def _drive_file_id(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in _DRIVE_HOSTS:
        return None
    parts = parsed.path.split("/")
    candidate = parts[parts.index("d") + 1] if "d" in parts and parts.index("d") + 1 < len(parts) else None
    candidate = candidate or parse_qs(parsed.query).get("id", [None])[0]
    return candidate if isinstance(candidate, str) and _FILE_ID_RE.fullmatch(candidate) else None


def _safe_pdf_name(title: str) -> str:
    name = Path(title.strip()).name
    name = _SAFE_NAME_RE.sub("_", name).strip(" .") or "documento"
    if not name.casefold().endswith(".pdf"):
        name += ".pdf"
    return name[:240]


def _unique_destination(directory: Path, filename: str) -> Path:
    destination = directory / filename
    if not destination.exists():
        return destination
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    for index in range(1, 10_000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
    raise BookDownloadError("Não foi possível criar um nome de arquivo disponível")


def _validate_response(response: httpx.Response, max_bytes: int) -> None:
    if response.status_code >= 400:
        raise BookDownloadError("A fonte rejeitou o download do PDF")
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise BookDownloadError("O PDF excede o tamanho máximo permitido")
        except ValueError as exc:
            raise BookDownloadError("A fonte retornou um tamanho inválido") from exc


def _validate_redirect_hosts(response: httpx.Response, *, label: str) -> None:
    if any(urlsplit(item.url).hostname not in _DOWNLOAD_HOSTS for item in response.history):
        raise BookDownloadError(f"O download foi redirecionado para um host não permitido ({label})")
    if urlsplit(response.url).hostname not in _DOWNLOAD_HOSTS:
        raise BookDownloadError(f"A fonte final do {label} não é permitida")
