"""Safe TMDB image URL construction without proxying arbitrary URLs."""

from __future__ import annotations

from app.config import Settings


def tmdb_image_url(settings: Settings, path: str | None, size: str) -> str | None:
    """Build an image URL only from the configured TMDB image origin and a path."""

    if size not in {"w300", "w342", "w780"}:
        return None
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    if len(path) > 300 or "//" in path or "?" in path or "#" in path or "://" in path:
        return None
    return f"{settings.tmdb_image_base_url.rstrip('/')}/{size}{path}"
