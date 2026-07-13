"""Bounded, reusable HTTP transport for real search providers."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.exceptions import (
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderInvalidResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

MAX_PROVIDER_RESPONSE_BYTES = 8 * 1024 * 1024


class ProviderHTTPClient:
    """One provider-scoped AsyncClient with safe error boundaries."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
    ) -> None:
        self.base_url = base_url
        self._max_response_bytes = max_response_bytes
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            headers={"Accept": "application/json, application/xml, text/xml", **(headers or {})},
        )

    def __repr__(self) -> str:
        return f"ProviderHTTPClient(base_url={self.base_url!r})"

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET and decode a bounded JSON response without leaking body data."""

        response = await self._get(path, params=params, headers=headers)
        try:
            return response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ProviderInvalidResponseError("Provider returned invalid JSON") from exc

    async def get_xml(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET and parse XML with external entities disabled by defusedxml."""

        response = await self._get(path, params=params, headers=headers)
        try:
            return ElementTree.fromstring(response.content)
        except (DefusedXmlException, ElementTree.ParseError, ValueError, UnicodeDecodeError) as exc:
            raise ProviderInvalidResponseError("Provider returned invalid XML") from exc

    async def get_response(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Return a bounded response, including redirects for a caller to inspect."""

        return await self._get(path, params=params, headers=headers, reject_redirect=False)

    async def close(self) -> None:
        """Close only clients owned by this transport."""

        if self._owns_client:
            await self._client.aclose()

    async def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None,
        reject_redirect: bool = True,
    ) -> httpx.Response:
        if not path.startswith("/") or "//" in path[1:] or any(ord(char) < 32 for char in path):
            raise ProviderConnectionError("Provider request path is invalid")
        request_headers = {"X-Request-ID": uuid.uuid4().hex, **(headers or {})}
        try:
            response = await self._client.get(path, params=params, headers=request_headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Provider request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError("Provider connection failed") from exc

        if reject_redirect and response.is_redirect:
            raise ProviderConnectionError("Provider redirect was not allowed")
        if response.status_code in {401, 403}:
            raise ProviderAuthenticationError("Provider authentication failed")
        if response.status_code == 429:
            raise ProviderRateLimitError("Provider rate limit reached")
        if response.status_code >= 500:
            raise ProviderConnectionError("Provider server error")
        if response.status_code >= 400:
            raise ProviderInvalidResponseError("Provider rejected the request")
        content_length = response.headers.get("content-length")
        if content_length and _safe_content_length(content_length) > self._max_response_bytes:
            raise ProviderInvalidResponseError("Provider response is too large")
        if len(response.content) > self._max_response_bytes:
            raise ProviderInvalidResponseError("Provider response is too large")
        return response


def _safe_content_length(value: str) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return MAX_PROVIDER_RESPONSE_BYTES + 1
