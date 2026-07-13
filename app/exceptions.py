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
