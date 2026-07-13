"""Application-specific exception types."""


class MediaFinderError(Exception):
    """Base exception for expected application errors."""


class DatabaseUnavailableError(MediaFinderError):
    """Raised when the configured database cannot be reached."""


class InvalidMagnetError(MediaFinderError, ValueError):
    """Raised when a magnet URI or info hash is invalid."""


class QBitTorrentUnavailableError(MediaFinderError):
    """Raised when qBittorrent cannot be reached."""


class QBitTorrentAuthenticationError(MediaFinderError):
    """Raised when qBittorrent rejects the configured credentials."""


class QBitTorrentTimeoutError(MediaFinderError):
    """Raised when a qBittorrent operation exceeds its timeout."""


class DuplicateTorrentError(MediaFinderError):
    """Raised when an info hash is already known to qBittorrent or locally."""


class CategoryNotConfiguredError(MediaFinderError):
    """Raised when the media type has no configured qBittorrent category."""


class CategoryNotFoundError(MediaFinderError):
    """Raised when a configured category does not exist in qBittorrent."""


class UnsupportedMediaTypeError(MediaFinderError):
    """Raised when a result has no supported media type."""


class ExpiredResultTokenError(MediaFinderError):
    """Raised when a temporary search result is no longer available."""


class ProviderError(MediaFinderError):
    """Base class for safe, expected external-provider failures."""


class ProviderAuthenticationError(ProviderError):
    """Raised when a provider rejects its configured API key."""


class ProviderConnectionError(ProviderError):
    """Raised when a provider cannot be reached or redirects unexpectedly."""


class ProviderTimeoutError(ProviderError):
    """Raised when a provider request exceeds its configured timeout."""


class ProviderInvalidResponseError(ProviderError):
    """Raised when a provider returns malformed or oversized data."""


class ProviderRateLimitError(ProviderError):
    """Raised when the local per-provider limiter denies a request."""


class ProviderConfigurationError(ProviderError):
    """Raised when a provider is enabled but cannot be configured safely."""
