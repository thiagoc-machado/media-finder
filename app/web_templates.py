"""Shared Jinja environment and presentation-only filters."""

from datetime import datetime

from fastapi.templating import Jinja2Templates

from app.utils.magnet import InvalidMagnetError, normalize_info_hash, parse_magnet
from app.utils.size import format_size

templates = Jinja2Templates(directory="app/templates")


def mask_magnet(value: str | None) -> str:
    """Expose only a short, non-actionable magnet preview."""

    if not value:
        return "Unknown"
    try:
        parsed = parse_magnet(value)
    except InvalidMagnetError:
        return "magnet:?xt=urn:btih:unknown"
    return f"magnet:?xt=urn:btih:{parsed.info_hash[:4]}…{parsed.info_hash[-4:]}"


def short_hash(value: str | None) -> str:
    """Abbreviate a hash for visual display without exposing the full value."""

    if not value:
        return "Unknown"
    try:
        normalized = normalize_info_hash(value)
    except InvalidMagnetError:
        normalized = value.strip()
    if len(normalized) <= 12:
        return normalized
    return f"{normalized[:8]}…{normalized[-8:]}"


def display_datetime(value: datetime | None) -> str:
    """Render timestamps consistently and safely."""

    return value.strftime("%Y-%m-%d %H:%M") if value else "Unknown"


templates.env.filters["filesize"] = format_size
templates.env.filters["mask_magnet"] = mask_magnet
templates.env.filters["short_hash"] = short_hash
templates.env.filters["display_datetime"] = display_datetime
