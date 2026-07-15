"""Read-only public web search provider for academic media discovery tests."""

from __future__ import annotations

from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, unquote, urlsplit

from app.clients.http_client import ProviderHTTPClient
from app.config import Settings, get_settings
from app.exceptions import ProviderInvalidResponseError
from app.providers.real_utils import clean_text, safe_external_url
from app.schemas.provider import ProviderHealth
from app.schemas.search import SearchRequest, SearchResult
from app.services.normalization_service import normalize_result

_PUBLIC_HOSTS = {"drive.google.com", "www.drive.google.com"}
_FILE_EXTENSIONS = {
    "pdf": {".pdf"},
    "torrent": {".torrent"},
    "music": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav", ".wma"},
    "video": {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".ts", ".webm", ".wmv"},
    "zip": {".7z", ".rar", ".zip"},
}
_SEARCH_PAGE_SIZE = 30
_MAX_SEARCH_PAGES = 4
class DuckDuckGoProvider:
    """Search DuckDuckGo's public HTML results for PDFs and torrent files."""

    slug = "duckduckgo"
    name = "DuckDuckGo"
    is_configured = True

    def __init__(self, settings: Settings | None = None, *, http_client: ProviderHTTPClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._http = http_client or ProviderHTTPClient(
            "https://html.duckduckgo.com",
            timeout_seconds=self.settings.duckduckgo_search_timeout_seconds,
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
                ),
            },
        )
        self._proxy_http = ProviderHTTPClient(
            "https://r.jina.ai",
            timeout_seconds=self.settings.duckduckgo_search_timeout_seconds,
            headers={"Accept": "text/plain", "User-Agent": "Media-Finder/0.1.0"},
            allow_nested_url_path=True,
        )
        self._owns_http = http_client is None

    async def health_check(self) -> ProviderHealth:
        if not self.settings.duckduckgo_search_enabled:
            return ProviderHealth(slug=self.slug, available=False, error="DuckDuckGo search is disabled")
        return ProviderHealth(slug=self.slug, available=True)

    async def search(self, request: SearchRequest) -> list[SearchResult]:
        if not self.settings.duckduckgo_search_enabled:
            return []
        results: list[SearchResult] = []
        seen: set[str] = set()
        pages = min(_MAX_SEARCH_PAGES, max(1, (self.settings.duckduckgo_search_max_results + _SEARCH_PAGE_SIZE - 1) // _SEARCH_PAGE_SIZE))
        for page in range(pages):
            page_results = await self._search_html(
                self._http, "/html/", request, params={"s": page * _SEARCH_PAGE_SIZE}
            )
            for result in page_results:
                if result.source_url and result.source_url not in seen:
                    seen.add(result.source_url)
                    results.append(result)
            if len(results) >= self.settings.duckduckgo_search_max_results or not page_results:
                break
        return results[: self.settings.duckduckgo_search_max_results]

    async def _search_html(self, client, path: str, request: SearchRequest, *, params: dict) -> list[SearchResult]:
        response = await client.get_response(
            path,
            params={"q": f"site:drive.google.com {request.query.strip()}", **params},
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            follow_redirects=True,
        )
        if response.status_code == 202:
            proxy_params = {"q": f"site:drive.google.com {request.query.strip()}", **params}
            response = await self._proxy_http.get_response(
                "/http://html.duckduckgo.com/html/",
                params=proxy_params,
                headers={"Accept": "text/plain"},
                follow_redirects=True,
            )
            items = _parse_markdown_results(response.text)
            if not params.get("s"):
                direct_response = await self._proxy_http.get_response(
                    "/http://html.duckduckgo.com/html/",
                    params={"q": f"site:drive.google.com/file/d {request.query.strip()}", **params},
                    headers={"Accept": "text/plain"},
                    follow_redirects=True,
                )
                items.extend(_parse_markdown_results(direct_response.text))
        else:
            parser = _GoogleResultParser()
            try:
                parser.feed(response.text)
                parser.close()
            except (AssertionError, ValueError) as exc:
                raise ProviderInvalidResponseError("Search engine returned invalid search markup") from exc
            items = parser.results
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in items:
            result = _result_from_item(item, request)
            if result is not None and result.source_url not in seen:
                seen.add(result.source_url or "")
                results.append(normalize_result(result))
        return results

    async def close(self) -> None:
        if self._owns_http:
            await self._http.close()
        await self._proxy_http.close()


class _GoogleResultParser(HTMLParser):
    """Extract links only; no scripts, forms or page content are executed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._href is None:
            return
        title = clean_text(" ".join(self._text), max_length=500)
        if title:
            self.results.append((self._href, title))
        self._href = None
        self._text = []


def _parse_markdown_results(markdown: str) -> list[tuple[str, str]]:
    """Parse the link lines returned by the read-only HTML fallback."""

    results: list[tuple[str, str]] = []
    pattern = re.compile(r"^(?:#+\s*)?\[([^\]]+)\]\((https?://[^)]+)\)\s*$")
    for line in markdown.splitlines():
        match = pattern.match(line.strip())
        if match:
            results.append((match.group(2), clean_text(match.group(1), max_length=500)))
    return results


def _result_from_item(item: tuple[str, str], request: SearchRequest) -> SearchResult | None:
    raw_url, title = item
    title = _clean_drive_result_title(title)
    source_url = _unwrap_google_url(raw_url)
    media_kind = _file_kind(title, request.file_type)
    if not source_url or not _is_drive_url(source_url) or media_kind is None:
        return None
    return SearchResult(
        provider="duckduckgo",
        provider_result_id=source_url,
        title=title,
        media_type="other" if media_kind in {"pdf", "zip"} else request.media_type if request.media_type != "all" else None,
        source_url=source_url,
        raw_data={"search_mode": "public_web", "query_scope": "site:drive.google.com", "media_kind": media_kind},
        download_capability="external",
    )


def _clean_drive_result_title(title: str) -> str:
    """Remove the provider suffix appended to public Drive search results."""

    cleaned = clean_text(title, max_length=500)
    suffix = " - google drive"
    if cleaned.casefold().endswith(suffix):
        cleaned = cleaned[: -len(suffix)].rstrip(" -")
    return cleaned


def _unwrap_google_url(value: str) -> str | None:
    parsed = urlsplit(value)
    if parsed.hostname == "duckduckgo.com" and parsed.path.startswith("/l/"):
        value = parse_qs(parsed.query).get("uddg", [None])[0] or ""
    if value.startswith("/"):
        parsed = urlsplit(value)
        target = parse_qs(parsed.query).get("q", [None])[0] or parse_qs(parsed.query).get("url", [None])[0]
        value = unquote(target) if target else ""
    return safe_external_url(value)


def _is_drive_url(value: str) -> bool:
    try:
        return urlsplit(value).hostname in _PUBLIC_HOSTS
    except ValueError:
        return False


def _file_kind(title: str, requested_type: str) -> str | None:
    lowered = title.casefold().rstrip(".")
    for kind, extensions in _FILE_EXTENSIONS.items():
        if any(lowered.endswith(extension) for extension in extensions):
            return kind if requested_type == "all" or requested_type == kind else None
    return None
