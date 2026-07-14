"""Offline tests for the simplified TMDB selection and resolved-search flow."""

import re
import time

import pytest
from sqlalchemy import select

from app import database
from app.clients.tmdb_client import TMDBClient
from app.models.search_history import SearchHistory
from app.schemas.metadata import ExternalIds, MetadataCandidate, MetadataDetails, ResolvedMedia, SeasonSummary
from app.services.metadata_result_store import MetadataResultStore
from app.services.metadata_service import MetadataService
from tests.test_phase8_tmdb import FakeTMDBHTTP, _settings

pytestmark = pytest.mark.asyncio


def _candidate_tokens(html: str) -> list[str]:
    return re.findall(r"/metadata/select/([A-Za-z0-9_-]+)", html)


async def _install_fake_tmdb(client, monkeypatch):
    service = MetadataService(TMDBClient(_settings(), http_client=FakeTMDBHTTP()))
    monkeypatch.setattr(client._transport.app.state, "metadata_service", service)


async def test_metadata_store_namespaces_ttl_limit_and_defensive_copy():
    store = MetadataResultStore(max_items=2, default_ttl_seconds=10)
    candidate = MetadataCandidate(provider="tmdb", provider_id="1", media_type="movie", title="Safe")
    resolved = ResolvedMedia(media_type="movie", title="Safe", tmdb_id=1, imdb_id="tt1234567")

    candidate_token = await store.save_candidate(candidate)
    resolved_token = await store.save_resolved(resolved)
    assert await store.get_candidate(resolved_token) is None
    assert await store.get_resolved(candidate_token) is None
    stored = await store.get_candidate(candidate_token)
    stored.title = "changed"
    assert (await store.get_candidate(candidate_token)).title == "Safe"
    assert await store.get_resolved(resolved_token) is not None

    store._items[f"candidate:{candidate_token}"] = (time.monotonic() - 1, candidate)
    assert await store.get_candidate(candidate_token) is None
    await store.save_candidate(candidate)
    await store.save_candidate(candidate.model_copy(update={"provider_id": "2"}))
    assert await store.size() == 2


async def test_tmdb_candidate_selection_creates_resolved_movie_and_searches(client, monkeypatch):
    await _install_fake_tmdb(client, monkeypatch)

    candidates = await client.get("/metadata/search", params={"query": "Interstellar"})
    assert candidates.status_code == 200
    token = _candidate_tokens(candidates.text)[0]
    assert "tmdb_id" not in candidates.text
    assert 'hx-target="#app-modal-content" hx-swap="innerHTML"' in candidates.text

    selected = await client.get(f"/metadata/select/{token}")
    assert selected.status_code == 200
    assert "Interstellar" in selected.text
    assert "tt0816692" in selected.text
    resolved_token = re.search(r'name="resolved_media_token" value="([A-Za-z0-9_-]+)"', selected.text).group(1)
    assert f'hx-target="#resolved-search-results-{resolved_token}"' in selected.text
    assert f'hx-indicator="#resolved-search-loading-{resolved_token}"' in selected.text
    assert "Consultando providers…" in selected.text

    releases = await client.get(
        "/search/resolved",
        params={"resolved_media_token": resolved_token, "providers": "mock"},
        headers={"HX-Request": "true"},
    )
    assert releases.status_code == 200
    assert "Interstellar" in releases.text or "Brutos:" in releases.text
    assert 'class="result-card-poster"' in releases.text
    with database.SessionLocal() as session:
        row = session.scalar(select(SearchHistory).order_by(SearchHistory.id.desc()))
        assert row is not None
        assert '"tmdb_id": 27205' in row.filters_json
        assert '"imdb_id": "tt0816692"' in row.filters_json


async def test_series_selection_validates_season_episode_and_searches(client, monkeypatch):
    await _install_fake_tmdb(client, monkeypatch)
    response = await client.get(
        "/metadata/search",
        params={"query": "Breaking Bad", "media_type": "series", "age_limit": 18},
    )
    token = _candidate_tokens(response.text)[0]
    selected = await client.get(f"/metadata/select/{token}")
    assert selected.status_code == 200
    resolved_token = re.search(r"/metadata/series/([A-Za-z0-9_-]+)/season/", selected.text).group(1)

    episodes = await client.get(f"/metadata/series/{resolved_token}/season/1")
    assert episodes.status_code == 200
    assert "Pilot" in episodes.text
    assert 'data-select-episode data-season="1" data-episode="1"' in episodes.text
    assert episodes.text.count('class="resolved-release-form"') == 1

    releases = await client.get(
        "/search/resolved",
        params={
            "resolved_media_token": resolved_token,
            "season": "1",
            "episode": "1",
            "providers": "mock",
        },
        headers={"HX-Request": "true"},
    )
    assert releases.status_code == 200
    assert "Brutos:" in releases.text

    invalid_episode = await client.get(
        "/search/resolved",
        params={
            "resolved_media_token": resolved_token,
            "season": "1",
            "episode": "99",
            "providers": "mock",
        },
        headers={"HX-Request": "true"},
    )
    assert invalid_episode.status_code == 200
    assert "Episódio inválido" in invalid_episode.text


async def test_expired_or_cross_namespace_tokens_are_rejected(client):
    response = await client.get("/metadata/select/not-a-token")
    assert response.status_code == 404
    response = await client.get(
        "/search/resolved",
        params={"resolved_media_token": "not-a-token", "providers": "mock"},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 404


async def test_resolution_requires_imdb_and_hides_specials_by_default(monkeypatch):
    service = MetadataService(TMDBClient(_settings(), http_client=FakeTMDBHTTP()))
    candidate = MetadataCandidate(provider="tmdb", provider_id="123", media_type="series", title="Show")
    details = MetadataDetails(
        provider="tmdb",
        provider_id="123",
        media_type="series",
        title="Show",
        external_ids=ExternalIds(imdb_id="tt1234567"),
        seasons=[
            SeasonSummary(season_number=-1, name="Invalid", episode_count=2),
            SeasonSummary(season_number=0, name="Specials", episode_count=2),
            SeasonSummary(season_number=1, name="Season 1", episode_count=3),
            SeasonSummary(season_number=2, name="Empty", episode_count=0),
        ],
    )

    async def fake_get_details(*_args, **_kwargs):
        return details.model_copy(deep=True)

    monkeypatch.setattr(service, "get_details", fake_get_details)

    resolved = await service.resolve_candidate(candidate, poster_url=None, show_specials=False)
    assert [season.season_number for season in resolved.seasons] == [1]

    resolved_with_specials = await service.resolve_candidate(candidate, poster_url=None, show_specials=True)
    assert [season.season_number for season in resolved_with_specials.seasons] == [0, 1]

    details.external_ids = ExternalIds(imdb_id=None)
    with pytest.raises(ValueError, match="IMDb"):
        await service.resolve_candidate(candidate, poster_url=None, show_specials=False)
