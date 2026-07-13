"""Non-blocking qBittorrent client and the application's safe torrent contract."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import qbittorrentapi
from requests.exceptions import Timeout as RequestsTimeout

from app.config import Settings, get_settings
from app.exceptions import (
    CategoryNotConfiguredError,
    CategoryNotFoundError,
    InvalidMagnetError,
    QBitTorrentAuthenticationError,
    QBitTorrentTimeoutError,
    QBitTorrentUnavailableError,
    UnsupportedMediaTypeError,
)
from app.schemas.download import (
    AddTorrentResult,
    CategoryValidationItem,
    CategoryValidationResult,
    QBitTorrentCategory,
    QBitTorrentHealth,
    TorrentStatus,
)
from app.utils.magnet import normalize_info_hash, normalize_magnet, parse_magnet

ClientFactory = Callable[..., Any]
_SUPPORTED_MEDIA_TYPES = ("movie", "series", "anime", "other")
_TAG_MAX_LENGTH = 64
_TAG_MAX_COUNT = 8
_TAG_COMPONENT = re.compile(r"[^a-z0-9]+")


class QBitTorrentService:
    """Serialize access to one authenticated qBittorrent client.

    ``qbittorrent-api`` is synchronous. Every network operation goes through
    ``asyncio.to_thread`` and has an explicit timeout at the async boundary.
    The private client is intentionally not included in the service repr.
    """

    def __init__(self, settings: Settings | None = None, client_factory: ClientFactory | None = None) -> None:
        self.settings = settings or get_settings()
        self._client_factory = client_factory or qbittorrentapi.Client
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()

    def get_category_for_media_type(self, media_type: str) -> str | None:
        """Resolve categories exclusively from server configuration."""

        return self.settings.get_category_for_media_type(media_type)

    async def health_check(self) -> QBitTorrentHealth:
        """Check authentication and application availability without failing boot."""

        started = time.perf_counter()
        try:
            version = await self._execute(self._read_version, self.settings.qbittorrent_health_timeout_seconds)
        except Exception as exc:  # expected service failures become safe health data
            return QBitTorrentHealth(available=False, error=_safe_error(exc))
        return QBitTorrentHealth(
            available=True,
            version=str(version) if version is not None else None,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    async def list_categories(self) -> dict[str, QBitTorrentCategory]:
        """Read category definitions without creating or changing any category."""

        raw_categories = await self._execute(
            self._read_categories,
            self.settings.qbittorrent_operation_timeout_seconds,
        )
        if not isinstance(raw_categories, Mapping):
            return {}
        return {
            str(name): QBitTorrentCategory(name=str(name), save_path=_category_save_path(value))
            for name, value in raw_categories.items()
        }

    async def validate_configured_categories(self) -> CategoryValidationResult:
        """Report configured categories and deliberately disabled media types."""

        try:
            categories = await self.list_categories()
        except Exception as exc:
            error = _safe_error(exc)
            return CategoryValidationResult(
                categories=[
                    CategoryValidationItem(
                        media_type=media_type,
                        configured_category=self.get_category_for_media_type(media_type),
                        error=error if self.get_category_for_media_type(media_type) else None,
                    )
                    for media_type in _SUPPORTED_MEDIA_TYPES
                ]
            )

        category_names = {name.casefold() for name in categories}
        items = []
        for media_type in _SUPPORTED_MEDIA_TYPES:
            configured = self.get_category_for_media_type(media_type)
            exists = bool(configured and configured.casefold() in category_names)
            items.append(
                CategoryValidationItem(
                    media_type=media_type,
                    configured_category=configured,
                    exists=exists,
                    available_for_download=bool(configured and exists),
                    error=("Configured category not found in qBittorrent" if configured and not exists else None),
                )
            )
        return CategoryValidationResult(categories=items)

    async def torrent_exists(self, info_hash: str) -> bool:
        """Return whether qBittorrent already knows a normalized info hash."""

        normalized = normalize_info_hash(info_hash)
        torrents = await self._execute(
            lambda client: client.torrents_info(torrent_hashes=normalized),
            self.settings.qbittorrent_operation_timeout_seconds,
        )
        return bool(torrents)

    async def add_torrent(
        self,
        magnet_url: str,
        media_type: str,
        provider: str,
        quality: str | None = None,
        languages: list[str] | None = None,
        paused: bool = False,
    ) -> AddTorrentResult:
        """Validate, deduplicate, categorize, tag, and add one magnet."""

        if media_type not in _SUPPORTED_MEDIA_TYPES:
            raise UnsupportedMediaTypeError("Unsupported media type")
        category = self.get_category_for_media_type(media_type)
        if not category:
            raise CategoryNotConfiguredError("No qBittorrent category is configured for this media type")

        try:
            normalized_magnet = normalize_magnet(magnet_url)
            info_hash = parse_magnet(normalized_magnet).info_hash
        except InvalidMagnetError:
            raise

        categories = await self.list_categories()
        if category.casefold() not in {name.casefold() for name in categories}:
            raise CategoryNotFoundError("Configured qBittorrent category was not found")
        if await self.torrent_exists(info_hash):
            return AddTorrentResult(
                status="duplicate",
                info_hash=info_hash,
                category=category,
                message="Torrent already exists in qBittorrent",
            )

        tags = build_qbittorrent_tags(provider, media_type, quality, languages)
        try:
            response = await self._execute(
                lambda client: client.torrents_add(
                    urls=normalized_magnet,
                    category=category,
                    tags=tags,
                    is_paused=paused,
                ),
                self.settings.qbittorrent_operation_timeout_seconds,
            )
        except Exception:
            raise

        # qBittorrent's response has differed between versions. An explicit
        # failure is accepted only when the hash is visible after the call.
        exists_after_add = await self.torrent_exists(info_hash)
        if exists_after_add:
            return AddTorrentResult(
                status="queued",
                info_hash=info_hash,
                category=category,
                message="Added to qBittorrent",
            )
        if _add_response_failed(response):
            message = "qBittorrent rejected the torrent"
        else:
            message = "Torrent was not confirmed in qBittorrent"
        return AddTorrentResult(status="failed", info_hash=info_hash, category=category, message=message)

    async def get_torrent(self, info_hash: str) -> TorrentStatus | None:
        """Read one torrent by its locally stored hash."""

        normalized = normalize_info_hash(info_hash)
        torrents = await self._execute(
            lambda client: client.torrents_info(torrent_hashes=normalized),
            self.settings.qbittorrent_operation_timeout_seconds,
        )
        if not torrents:
            return None
        return _torrent_status(torrents[0], normalized)

    async def _execute(self, operation: Callable[[Any], Any], timeout: float) -> Any:
        """Authenticate once and execute a synchronous API call in a worker."""

        async with self._operation_lock:
            client = await self._get_client()
            try:
                # Keep the worker callable argument-free. Besides making the
                # handoff explicit, this avoids binding qBittorrent client
                # objects into the executor callback's argument tuple.
                return await asyncio.wait_for(asyncio.to_thread(lambda: operation(client)), timeout=timeout)
            except Exception as exc:
                mapped = _map_qbit_exception(exc)
                if mapped is not None:
                    self._client = None
                    raise mapped from None
                raise QBitTorrentUnavailableError("qBittorrent operation failed") from None

    async def _get_client(self) -> Any:
        """Create and authenticate the reusable client in a worker thread."""

        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is not None:
                return self._client
            try:
                client = await asyncio.wait_for(
                    asyncio.to_thread(self._create_and_login),
                    timeout=self.settings.qbittorrent_connect_timeout_seconds,
                )
            except Exception as exc:
                raise _map_qbit_exception(exc) or QBitTorrentUnavailableError("qBittorrent is unavailable") from None
            self._client = client
            return client

    def _create_and_login(self) -> Any:
        """Construct and authenticate a client without ever logging secrets."""

        client = self._client_factory(
            host=self.settings.qbittorrent_url,
            username=self.settings.qbittorrent_username,
            password=self.settings.qbittorrent_password,
            REQUESTS_ARGS={
                "timeout": (
                    self.settings.qbittorrent_connect_timeout_seconds,
                    self.settings.qbittorrent_operation_timeout_seconds,
                )
            },
            DISABLE_LOGGING_DEBUG_OUTPUT=True,
            VERBOSE_RESPONSE_LOGGING=False,
        )
        login = getattr(client, "auth_log_in", None)
        if callable(login):
            login()
        return client

    @staticmethod
    def _read_version(client: Any) -> Any:
        method = getattr(client, "app_version", None)
        if callable(method):
            return method()
        return client.app.version()

    @staticmethod
    def _read_categories(client: Any) -> Any:
        return client.torrents_categories()


def build_qbittorrent_tags(
    provider: str,
    media_type: str,
    quality: str | None = None,
    languages: Iterable[str] | None = None,
) -> list[str]:
    """Build bounded, lowercase tags from trusted result metadata."""

    raw_values = [
        ("media-finder", None),
        ("provider", provider),
        ("type", media_type),
        ("quality", quality),
    ]
    raw_values.extend(("language", language) for language in languages or [])
    tags: list[str] = []
    for prefix, value in raw_values:
        if value is None and prefix != "media-finder":
            continue
        component = _sanitize_tag_component(str(value or ""))
        candidate = prefix if prefix == "media-finder" else f"{prefix}:{component}"
        candidate = candidate[:_TAG_MAX_LENGTH].rstrip(":-")
        if candidate and candidate not in tags:
            tags.append(candidate)
        if len(tags) >= _TAG_MAX_COUNT:
            break
    return tags


def _sanitize_tag_component(value: str) -> str:
    """Keep tags readable while removing whitespace, URLs, hashes, and punctuation."""

    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value.strip(), flags=re.IGNORECASE)
    normalized = _TAG_COMPONENT.sub("-", value.strip().casefold()).strip("-")
    return normalized[: _TAG_MAX_LENGTH - 10].rstrip("-")


def _category_save_path(value: Any) -> str | None:
    if isinstance(value, Mapping):
        path = value.get("savePath", value.get("save_path"))
    else:
        path = getattr(value, "save_path", getattr(value, "savePath", None))
    return str(path) if path else None


def _value(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        value = getattr(source, name, None)
        if value is not None:
            return value
    return default


def _torrent_status(torrent: Any, normalized_hash: str) -> TorrentStatus:
    raw_tags = _value(torrent, "tags", default="")
    if isinstance(raw_tags, str):
        tags = [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
    else:
        tags = [str(tag).strip() for tag in raw_tags or [] if str(tag).strip()]
    return TorrentStatus(
        info_hash=normalize_info_hash(str(_value(torrent, "hash", default=normalized_hash))),
        name=str(_value(torrent, "name", default="")),
        state=str(_value(torrent, "state", default="unknown")),
        progress=float(_value(torrent, "progress", default=0) or 0),
        downloaded_bytes=int(_value(torrent, "downloaded", default=0) or 0),
        total_size_bytes=int(_value(torrent, "size", default=0) or 0),
        download_speed=int(_value(torrent, "dlspeed", default=0) or 0),
        eta_seconds=_optional_int(_value(torrent, "eta", default=None)),
        category=_value(torrent, "category", default=None) or None,
        tags=tags,
    )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _add_response_failed(response: Any) -> bool:
    if isinstance(response, str):
        return response.strip().casefold() in {"fails", "fail", "error"} or response.casefold().startswith("fail")
    return False


def _map_qbit_exception(exc: Exception) -> Exception | None:
    name = type(exc).__name__.casefold()
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, RequestsTimeout)) or "timeout" in name:
        return QBitTorrentTimeoutError("qBittorrent operation timed out")
    if "401" in name or "unauthor" in name or "auth" in name or "login" in name:
        return QBitTorrentAuthenticationError("qBittorrent authentication failed")
    return QBitTorrentUnavailableError("qBittorrent is unavailable")


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, QBitTorrentAuthenticationError):
        return "Authentication failed"
    if isinstance(exc, QBitTorrentTimeoutError):
        return "Operation timed out"
    return "qBittorrent unavailable"
