"""Safe URL construction and host checks for Stremio addons."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from urllib.parse import quote, urlsplit, urlunsplit

from app.exceptions import ProviderConfigurationError

_SAFE_SEGMENT = re.compile(r"^[^/\\?#\x00-\x1f\x7f]+$")
_MAX_URL_LENGTH = 4096


def validate_manifest_url(manifest_url: str, *, allowed_schemes: set[str] | None = None) -> None:
    """Validate the immutable manifest URL without exposing its opaque path."""

    if (
        not isinstance(manifest_url, str)
        or len(manifest_url) > _MAX_URL_LENGTH
        or any(ord(char) < 32 or ord(char) == 127 for char in manifest_url)
    ):
        raise ProviderConfigurationError("Stremio manifest URL is invalid")
    try:
        parsed = urlsplit(manifest_url.strip())
        parsed.port
    except ValueError as exc:
        raise ProviderConfigurationError("Stremio manifest URL is invalid") from exc
    schemes = allowed_schemes or {"http", "https"}
    if parsed.scheme.casefold() not in schemes or not parsed.hostname:
        raise ProviderConfigurationError("Stremio manifest URL uses an unsupported scheme")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ProviderConfigurationError("Stremio manifest URL contains unsafe URL components")
    if not parsed.path.endswith("/manifest.json"):
        raise ProviderConfigurationError("Stremio manifest URL must end with /manifest.json")


def build_stremio_resource_url(
    manifest_url: str,
    resource: str,
    media_type: str,
    external_id: str,
) -> str:
    """Build a resource URL while preserving the configured addon path."""

    validate_manifest_url(manifest_url)
    parsed = urlsplit(manifest_url)
    for value, label in ((resource, "resource"), (media_type, "media type"), (external_id, "external ID")):
        if not isinstance(value, str) or not value or not _SAFE_SEGMENT.fullmatch(value) or ".." in value:
            raise ProviderConfigurationError(f"Stremio {label} is invalid")
    base_path = parsed.path[: -len("manifest.json")]
    path = f"{base_path}{quote(resource, safe='')}/{quote(media_type, safe='')}/{quote(external_id, safe='')}.json"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def addon_fingerprint(manifest_url: str) -> str:
    """Return a non-reversible identifier suitable for cache keys and logs."""

    return hashlib.sha256(manifest_url.encode("utf-8")).hexdigest()[:16]


def is_private_host(host: str) -> bool:
    """Detect loopback, private, link-local, reserved and metadata IP literals."""

    if host.casefold() in {"localhost", "localhost.localdomain"} or host.casefold().endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def abbreviated_external_id(external_id: str) -> str:
    """Keep observability IDs short without logging opaque addon paths."""

    return external_id[:24] + "…" if len(external_id) > 24 else external_id
