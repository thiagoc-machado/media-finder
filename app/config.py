"""Application configuration loaded from environment variables."""

import re
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__


class QBitTorrentCategorySettings(BaseModel):
    """Configured qBittorrent categories used by the application."""

    movie: str | None = "movies"
    series: str | None = "series"
    anime: str | None = None
    other: str | None = None

    @field_validator("movie", "series", "anime", "other", mode="before")
    @classmethod
    def validate_category(cls, value: str | None) -> str | None:
        """Normalize empty values and reject unsafe category names."""

        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            raise ValueError("qBittorrent category must be a string")
        normalized = value.strip()
        if len(normalized) > 40 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,39}", normalized):
            raise ValueError("qBittorrent category has an invalid format")
        return normalized

    def get_category_for_media_type(self, media_type: str) -> str | None:
        """Return the configured category for one supported media type."""

        return getattr(self, media_type, None) if media_type in {"movie", "series", "anime", "other"} else None


class Settings(BaseSettings):
    """Runtime settings for the Media Finder service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Media Finder"
    app_env: str = "production"
    app_host: str = "0.0.0.0"
    app_port: int = 8091
    app_secret_key: str = ""
    database_url: str = "sqlite:////config/media-finder.db"
    log_level: str = "INFO"

    search_query_min_length: int = 2
    search_query_max_length: int = 200
    search_max_providers: int = 10
    search_provider_timeout_seconds: float = 5
    search_result_token_ttl_seconds: int = 900
    search_result_store_max_items: int = 2000
    search_rate_limit_requests: int = 20
    search_rate_limit_window_seconds: int = 60
    search_history_page_size: int = 25
    provider_rate_limit_requests: int = Field(default=20, ge=1, le=1000)
    provider_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    provider_cache_max_items: int = Field(default=512, ge=1, le=10_000)

    tmdb_enabled: bool = True
    tmdb_api_key: str = ""
    tmdb_auth_mode: Literal["bearer", "api_key"] = "bearer"
    tmdb_allow_http: bool = False
    tmdb_base_url: str = "https://api.themoviedb.org/3"
    tmdb_image_base_url: str = "https://image.tmdb.org/t/p"
    tmdb_language: str = "pt-BR"
    tmdb_region: str = "ES"
    tmdb_timeout_seconds: float = Field(default=10, ge=1, le=120)
    tmdb_cache_ttl_seconds: int = Field(default=3600, ge=0, le=86_400)
    tmdb_max_results: int = Field(default=20, ge=1, le=100)
    tmdb_max_concurrency: int = Field(default=3, ge=1, le=32)

    metadata_search_min_length: int = Field(default=2, ge=1, le=20)
    metadata_search_max_length: int = Field(default=200, ge=20, le=500)
    metadata_result_token_ttl_seconds: int = Field(default=900, ge=0, le=86_400)
    metadata_result_store_max_items: int = Field(default=1000, ge=1, le=10_000)
    metadata_rate_limit_requests: int = Field(default=30, ge=1, le=1000)
    metadata_rate_limit_window_seconds: int = Field(default=60, ge=1, le=86_400)
    metadata_show_specials: bool = False

    qbittorrent_url: str = "http://qbittorrent:8080"
    qbittorrent_username: str = ""
    qbittorrent_password: str = ""
    qbittorrent_category_movie: str | None = "movies"
    qbittorrent_category_series: str | None = "series"
    qbittorrent_category_anime: str | None = None
    qbittorrent_category_other: str | None = None
    qbittorrent_connect_timeout_seconds: float = Field(default=5, gt=0)
    qbittorrent_operation_timeout_seconds: float = Field(default=15, gt=0)
    qbittorrent_health_timeout_seconds: float = Field(default=5, gt=0)

    prowlarr_url: str = "http://prowlarr:9696"
    prowlarr_api_key: str = ""
    prowlarr_enabled: bool = True
    prowlarr_timeout_seconds: float = Field(default=15, ge=1, le=120)
    prowlarr_max_results: int = Field(default=200, ge=1, le=1000)
    prowlarr_cache_ttl_seconds: int = Field(default=60, ge=0, le=86_400)
    prowlarr_max_concurrency: int = Field(default=3, ge=1, le=32)

    jackett_url: str = "http://jackett:9117"
    jackett_api_key: str = ""
    jackett_enabled: bool = True
    jackett_timeout_seconds: float = Field(default=20, ge=1, le=120)
    jackett_max_results: int = Field(default=200, ge=1, le=1000)
    jackett_cache_ttl_seconds: int = Field(default=60, ge=0, le=86_400)
    jackett_max_concurrency: int = Field(default=3, ge=1, le=32)
    jackett_indexers: str = "all"

    duckduckgo_search_enabled: bool = False
    duckduckgo_search_timeout_seconds: float = Field(default=10, ge=1, le=120)
    duckduckgo_search_max_results: int = Field(default=10, ge=1, le=1000)

    books_dir: str = "/books"
    books_max_size_bytes: int = Field(default=104_857_600, ge=1_048_576, le=1_073_741_824)
    books_download_timeout_seconds: float = Field(default=60, ge=1, le=300)
    torrent_file_max_size_bytes: int = Field(default=20_971_520, ge=1_048_576, le=104_857_600)

    torrentio_enabled: bool = False
    torrentio_manifest_url: str = ""
    torrentio_timeout_seconds: float = Field(default=20, ge=1, le=120)
    torrentio_cache_ttl_seconds: int = Field(default=120, ge=0, le=86_400)
    torrentio_max_results: int = Field(default=200, ge=1, le=1000)
    torrentio_max_concurrency: int = Field(default=2, ge=1, le=32)

    mediafusion_enabled: bool = False
    mediafusion_manifest_url: str = ""
    mediafusion_timeout_seconds: float = Field(default=20, ge=1, le=120)
    mediafusion_cache_ttl_seconds: int = Field(default=120, ge=0, le=86_400)
    mediafusion_max_results: int = Field(default=200, ge=1, le=1000)
    mediafusion_max_concurrency: int = Field(default=2, ge=1, le=32)

    stremio_addon_max_response_bytes: int = Field(default=5_242_880, ge=1024, le=50_000_000)
    stremio_addon_max_redirects: int = Field(default=2, ge=0, le=5)
    stremio_addon_allowed_schemes: str = "http,https"
    stremio_addon_allow_private_hosts: bool = False

    @field_validator(
        "qbittorrent_category_movie",
        "qbittorrent_category_series",
        "qbittorrent_category_anime",
        "qbittorrent_category_other",
        mode="before",
    )
    @classmethod
    def validate_qbittorrent_category(cls, value: str | None) -> str | None:
        """Apply the same safe category rules to environment settings."""

        return QBitTorrentCategorySettings.validate_category(value)

    @field_validator("prowlarr_url", "jackett_url", mode="before")
    @classmethod
    def validate_provider_url(cls, value: str) -> str:
        """Accept only absolute HTTP(S) provider URLs without credentials."""

        if not isinstance(value, str) or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Provider URL is invalid")
        normalized = value.strip().rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Provider URL must use http or https")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("Provider URL cannot contain credentials, query parameters or fragments")
        return normalized

    @field_validator("tmdb_base_url", "tmdb_image_base_url", mode="before")
    @classmethod
    def validate_tmdb_url(cls, value: str, info) -> str:
        """Require HTTPS for TMDB endpoints unless HTTP is explicitly allowed."""

        allow_http = bool(info.data.get("tmdb_allow_http")) or info.data.get("app_env", "").casefold() == "test"
        return _validate_metadata_url(value, allow_http, "TMDB")

    @field_validator("torrentio_manifest_url", "mediafusion_manifest_url", mode="before")
    @classmethod
    def validate_stremio_manifest_url(cls, value: str) -> str:
        """Accept an optional absolute manifest URL without rewriting its path."""

        if value is None or (isinstance(value, str) and not value.strip()):
            return ""
        if not isinstance(value, str) or any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Stremio manifest URL is invalid")
        normalized = value.strip()
        try:
            parsed = urlsplit(normalized)
            parsed.port
        except ValueError as exc:
            raise ValueError("Stremio manifest URL is invalid") from exc
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Stremio manifest URL must use http or https")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("Stremio manifest URL cannot contain credentials, query parameters or fragments")
        if not parsed.path.endswith("/manifest.json"):
            raise ValueError("Stremio manifest URL must end with /manifest.json")
        return normalized

    @field_validator("stremio_addon_allowed_schemes", mode="before")
    @classmethod
    def validate_stremio_schemes(cls, value: str) -> str:
        """Restrict addon URL schemes to the explicitly supported protocols."""

        if not isinstance(value, str):
            raise ValueError("Stremio addon schemes must be text")
        schemes = [item.strip().casefold() for item in value.split(",") if item.strip()]
        if not schemes or any(item not in {"http", "https"} for item in schemes):
            raise ValueError("Stremio addon schemes must contain only http and https")
        return ",".join(dict.fromkeys(schemes))

    @field_validator("jackett_indexers", mode="before")
    @classmethod
    def validate_jackett_indexers(cls, value: str) -> str:
        """Normalize the configured Jackett indexer list without broad input."""

        if value is None:
            return "all"
        if not isinstance(value, str):
            raise ValueError("Jackett indexers must be text")
        normalized = value.strip()
        if len(normalized) > 500 or any(ord(character) < 32 or ord(character) == 127 for character in normalized):
            raise ValueError("Jackett indexers are invalid")
        if not normalized:
            return "all"
        indexers = [item.strip() for item in normalized.split(",")]
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", item) for item in indexers):
            raise ValueError("Jackett indexers are invalid")
        return ",".join(indexers)

    @property
    def version(self) -> str:
        """Return the application version exposed by the health endpoint."""

        return __version__

    @property
    def qbittorrent_categories(self) -> QBitTorrentCategorySettings:
        """Return validated category configuration as a typed value object."""

        return QBitTorrentCategorySettings(
            movie=self.qbittorrent_category_movie,
            series=self.qbittorrent_category_series,
            anime=self.qbittorrent_category_anime,
            other=self.qbittorrent_category_other,
        )

    def get_category_for_media_type(self, media_type: str) -> str | None:
        """Return the configured category without accepting request data."""

        return self.qbittorrent_categories.get_category_for_media_type(media_type)

    def validate_security(self) -> None:
        """Fail production startup when the session signing secret is unsafe."""

        if self.app_env.casefold() != "production":
            return
        insecure_values = {
            "",
            "change-me",
            "change-me-in-production",
            "replace-with-a-random-64-character-secret",
            "secret",
            "secret-key",
        }
        if self.app_secret_key.casefold() in insecure_values or len(self.app_secret_key) < 32:
            raise ValueError("APP_SECRET_KEY must be a strong value of at least 32 characters in production")


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings."""

    return Settings()


def _validate_metadata_url(value: str, allow_http: bool, label: str) -> str:
    """Validate an external metadata origin without credentials or URL data."""

    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(f"{label} URL is invalid")
    normalized = value.strip().rstrip("/")
    try:
        parsed = urlsplit(normalized)
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} URL is invalid") from exc
    allowed = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme.casefold() not in allowed or not parsed.hostname:
        raise ValueError(f"{label} URL must use https by default")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{label} URL cannot contain credentials, query parameters or fragments")
    return normalized
