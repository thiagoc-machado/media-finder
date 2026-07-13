"""Generic, bounded client for the Stremio manifest and stream resources."""

from __future__ import annotations

import asyncio
import socket
import time
from copy import deepcopy
from urllib.parse import urljoin, urlsplit

from pydantic import ValidationError

from app.clients.http_client import ProviderHTTPClient
from app.exceptions import (
    ProviderConfigurationError,
    ProviderConnectionError,
    ProviderError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
)
from app.providers.real_utils import clean_text
from app.schemas.provider import ProviderHealth
from app.schemas.stremio import StremioManifest, StremioManifestResource, StremioStreamResponse
from app.services.provider_runtime import AsyncTTLCache, ProviderRateLimiter
from app.utils.stremio_url import addon_fingerprint, is_private_host, validate_manifest_url


class StremioAddonClient:
    """Consume one configured addon without following untrusted URLs."""

    def __init__(
        self,
        manifest_url: str,
        *,
        provider_slug: str,
        timeout_seconds: float,
        cache_ttl_seconds: int,
        max_items: int,
        max_response_bytes: int,
        max_redirects: int,
        allowed_schemes: str = "http,https",
        allow_private_hosts: bool = False,
        max_concurrency: int = 2,
        rate_limit_requests: int = 20,
        rate_limit_window_seconds: int = 60,
        http_client: ProviderHTTPClient | None = None,
    ) -> None:
        schemes = {item.strip().casefold() for item in allowed_schemes.split(",") if item.strip()}
        validate_manifest_url(manifest_url, allowed_schemes=schemes)
        parsed = urlsplit(manifest_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        self.manifest_url = manifest_url
        self.provider_slug = provider_slug
        self._allow_private_hosts = allow_private_hosts
        self._max_redirects = max(0, max_redirects)
        self._allowed_schemes = schemes
        self._owns_http = http_client is None
        self._http = http_client or ProviderHTTPClient(
            origin,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        self._manifest_cache = AsyncTTLCache(ttl_seconds=cache_ttl_seconds, max_items=max_items)
        self._stream_cache = AsyncTTLCache(ttl_seconds=cache_ttl_seconds, max_items=max_items)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self._rate_limiter = ProviderRateLimiter(
            requests=max(1, rate_limit_requests),
            window_seconds=max(1, rate_limit_window_seconds),
        )

    @property
    def fingerprint(self) -> str:
        """Return a safe addon cache/log identifier."""

        return addon_fingerprint(self.manifest_url)

    async def get_manifest(self) -> StremioManifest:
        """Fetch and validate manifest.json, using a short in-memory cache."""

        cached = await self._manifest_cache.get("manifest")
        if cached is not None:
            return cached
        payload = await self._get_json(self.manifest_url)
        try:
            manifest = StremioManifest.model_validate(payload)
        except ValidationError as exc:
            raise ProviderInvalidResponseError("Stremio addon returned an invalid manifest") from exc
        if not manifest.id or not manifest.name:
            raise ProviderInvalidResponseError("Stremio addon manifest is incomplete")
        await self._manifest_cache.set("manifest", manifest)
        return manifest

    async def get_streams(self, media_type: str, external_id: str) -> StremioStreamResponse:
        """Fetch one stream resource for a resolved external media ID."""

        manifest = await self.get_manifest()
        if not self.supports_resource(manifest, "stream"):
            raise ProviderConfigurationError("Stremio addon does not support stream resources")
        if not self.supports_type(manifest, media_type):
            raise ProviderConfigurationError(f"Stremio addon does not support media type: {media_type}")
        cache_key = f"{self.fingerprint}:{media_type}:{external_id}"
        cached = await self._stream_cache.get(cache_key)
        if cached is not None:
            return cached
        from app.utils.stremio_url import build_stremio_resource_url

        resource_url = build_stremio_resource_url(self.manifest_url, "stream", media_type, external_id)
        payload = await self._get_json(resource_url)
        if not isinstance(payload, dict):
            raise ProviderInvalidResponseError("Stremio addon returned an invalid stream response")
        try:
            response = StremioStreamResponse.model_validate(payload)
        except ValidationError as exc:
            raise ProviderInvalidResponseError("Stremio addon returned invalid streams") from exc
        ttl = self._cache_ttl_seconds
        if response.cache_max_age is not None and response.cache_max_age >= 0:
            ttl = min(ttl, response.cache_max_age)
        await self._stream_cache.set(cache_key, response, ttl_seconds=ttl)
        return deepcopy(response)

    async def health_check(self) -> ProviderHealth:
        """Validate only the manifest and stream capabilities, never streams."""

        started = time.perf_counter()
        try:
            manifest = await self.get_manifest()
            if not self.supports_resource(manifest, "stream"):
                raise ProviderConfigurationError("Stremio addon has no stream resource")
            if not self.supports_type(manifest, "movie") and not self.supports_type(manifest, "series"):
                raise ProviderConfigurationError("Stremio addon supports neither movie nor series")
            return ProviderHealth(
                slug=self.provider_slug,
                available=True,
                version=clean_text(manifest.version, max_length=80),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except ProviderError as exc:
            return ProviderHealth(
                slug=self.provider_slug,
                available=False,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )

    def supports_resource(self, manifest: StremioManifest, resource: str) -> bool:
        """Check string and object resource declarations."""

        return any(
            item == resource or (isinstance(item, StremioManifestResource) and item.name == resource)
            for item in manifest.resources
        )

    def supports_type(self, manifest: StremioManifest, media_type: str) -> bool:
        """Check a media type on the stream resource or top-level manifest."""

        for item in manifest.resources:
            if isinstance(item, StremioManifestResource) and item.name == "stream" and item.types:
                return media_type in item.types
        return media_type in manifest.types

    async def reset_runtime(self) -> None:
        """Clear caches and rate-limit state between tests or configuration changes."""

        await self._manifest_cache.reset()
        await self._stream_cache.reset()
        await self._rate_limiter.reset()

    async def close(self) -> None:
        """Close only the HTTP client owned by this addon client."""

        if self._owns_http:
            await self._http.close()

    async def _get_json(self, url: str):
        current_url = url
        for redirect_count in range(self._max_redirects + 1):
            await self._validate_request_url(current_url)
            parsed = urlsplit(current_url)
            if not await self._rate_limiter.allow():
                raise ProviderRateLimitError("Provider rate limit reached")
            async with self._semaphore:
                response = await self._http.get_response(parsed.path, params=None)
            if response.is_redirect:
                if redirect_count >= self._max_redirects:
                    raise ProviderConnectionError("Stremio addon redirect limit reached")
                location = response.headers.get("location")
                if not location:
                    raise ProviderConnectionError("Stremio addon returned an invalid redirect")
                next_url = urljoin(current_url, location)
                try:
                    next_parsed = urlsplit(next_url)
                    next_parsed.port
                except ValueError as exc:
                    raise ProviderConnectionError("Stremio addon redirect URL was invalid") from exc
                if next_parsed.hostname != parsed.hostname or next_parsed.port != parsed.port:
                    raise ProviderConnectionError("Stremio addon redirect host was not allowed")
                current_url = next_url
                continue
            try:
                return response.json()
            except (ValueError, UnicodeDecodeError) as exc:
                raise ProviderInvalidResponseError("Stremio addon returned invalid JSON") from exc
        raise ProviderConnectionError("Stremio addon redirect limit reached")

    async def _validate_request_url(self, url: str) -> None:
        try:
            parsed = urlsplit(url)
            parsed.port
        except ValueError as exc:
            raise ProviderConfigurationError("Stremio addon URL is invalid") from exc
        if parsed.scheme.casefold() not in self._allowed_schemes or not parsed.hostname:
            raise ProviderConfigurationError("Stremio addon URL uses an unsupported scheme")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ProviderConfigurationError("Stremio addon URL contains unsafe components")
        if not self._allow_private_hosts:
            if is_private_host(parsed.hostname):
                raise ProviderConfigurationError("Stremio addon private host is not allowed")
            try:
                addresses = await asyncio.wait_for(
                    asyncio.to_thread(socket.getaddrinfo, parsed.hostname, parsed.port, type=socket.SOCK_STREAM),
                    timeout=2,
                )
            except (OSError, TimeoutError):
                addresses = []
            for address in addresses:
                if is_private_host(address[4][0]):
                    raise ProviderConfigurationError("Stremio addon resolved to a private host")
