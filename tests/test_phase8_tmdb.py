"""Offline tests for the Phase 8.1 TMDB metadata layer."""

import pytest

from app.clients.tmdb_client import TMDBClient
from app.config import Settings
from app.exceptions import ProviderTimeoutError
from app.schemas.metadata import MetadataCandidate
from app.services.metadata_service import MetadataService
from app.utils.metadata_images import tmdb_image_url


class FakeTMDBHTTP:
    """Deterministic async transport with no external network access."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict, dict]] = []
        self.error = error

    async def get_json(self, path: str, *, params=None, headers=None):
        params = dict(params or {})
        headers = dict(headers or {})
        self.calls.append((path, params, headers))
        if self.error:
            raise self.error
        if path == "/configuration":
            return {"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}}
        if path == "/search/multi":
            return {
                "results": [
                    {
                        "media_type": "person",
                        "id": 99,
                        "name": "Ignored Person",
                    },
                    {
                        "media_type": "movie",
                        "id": 27205,
                        "title": "Interstellar",
                        "original_title": "Interstellar",
                        "release_date": "2014-11-07",
                        "overview": "<b>Space</b> and a malicious <script>alert(1)</script>.",
                        "poster_path": "/poster.jpg",
                        "backdrop_path": "/backdrop.jpg",
                        "popularity": 100.2,
                        "vote_average": 8.6,
                        "vote_count": 30000,
                        "original_language": "en",
                        "adult": False,
                    },
                    {
                        "media_type": "tv",
                        "id": 123,
                        "name": "Breaking Bad",
                        "original_name": "Breaking Bad",
                        "first_air_date": "invalid",
                        "overview": "A show.",
                        "adult": False,
                    },
                    {
                        "media_type": "movie",
                        "id": 456,
                        "title": "Adult",
                        "adult": True,
                    },
                ]
            }
        if path == "/movie/27205":
            return {
                "id": 27205,
                "title": "Interstellar",
                "original_title": "Interstellar",
                "release_date": "2014-11-07",
                "overview": "A film.",
                "poster_path": "/poster.jpg",
            }
        if path == "/tv/123":
            return {
                "id": 123,
                "name": "Breaking Bad",
                "original_name": "Breaking Bad",
                "first_air_date": "2008-01-20",
                "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 7}],
                "number_of_seasons": 5,
                "number_of_episodes": 62,
            }
        if path.endswith("/external_ids"):
            return {"imdb_id": "tt0816692", "tvdb_id": 81189, "wikidata_id": "Q123"}
        if path == "/tv/123/season/1":
            return {
                "season_number": 1,
                "name": "Season 1",
                "episodes": [
                    {
                        "episode_number": 1,
                        "name": "Pilot",
                        "air_date": "2008-01-20",
                        "overview": "The beginning.",
                        "runtime": 58,
                        "still_path": "/still.jpg",
                    }
                ],
            }
        raise AssertionError(f"Unexpected path: {path}")

    async def close(self) -> None:
        pass


def _settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "tmdb_api_key": "test-secret",
        "tmdb_base_url": "http://tmdb.test/3",
        "tmdb_image_base_url": "https://image.tmdb.org/t/p",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.asyncio
async def test_health_requires_key_and_does_not_make_a_request():
    fake = FakeTMDBHTTP()
    client = TMDBClient(_settings(tmdb_api_key=""), http_client=fake)

    health = await client.health_check()

    assert health.enabled is True
    assert health.available is False
    assert fake.calls == []
    assert "secret" not in (health.error or "")


@pytest.mark.asyncio
async def test_bearer_auth_health_and_api_key_authentication():
    bearer_http = FakeTMDBHTTP()
    bearer = TMDBClient(_settings(tmdb_auth_mode="bearer"), http_client=bearer_http)
    assert (await bearer.health_check()).available is True
    assert bearer_http.calls[0][2] == {"Authorization": "Bearer test-secret"}
    assert "test-secret" not in repr(bearer_http.calls[0][0])

    key_http = FakeTMDBHTTP()
    key_client = TMDBClient(_settings(tmdb_auth_mode="api_key"), http_client=key_http)
    await key_client.search_multi("Interstellar")
    assert key_http.calls[0][1]["api_key"] == "test-secret"
    assert "test-secret" not in str(key_http.calls[0][0])


@pytest.mark.asyncio
async def test_search_normalizes_and_filters_multi_results():
    client = TMDBClient(_settings(), http_client=FakeTMDBHTTP())

    candidates = await client.search_multi("  Interstellar  ")

    assert [candidate.media_type for candidate in candidates] == ["movie", "series"]
    assert candidates[0].year == 2014
    assert "<script>" not in (candidates[0].overview or "")
    assert candidates[1].year is None
    assert candidates[0].poster_path == "/poster.jpg"


@pytest.mark.asyncio
async def test_details_external_ids_seasons_and_cache():
    fake = FakeTMDBHTTP()
    client = TMDBClient(_settings(), http_client=fake)
    service = MetadataService(client)

    movie = await service.get_details("movie", 27205)
    series = await service.get_details("series", 123)
    season = await service.get_tv_season(123, 1)
    await client.get_movie(27205)

    assert movie.external_ids.imdb_id == "tt0816692"
    assert series.seasons[0].episode_count == 7
    assert season.episodes[0].runtime_minutes == 58
    assert sum(path == "/movie/27205" for path, _, _ in fake.calls) == 1


@pytest.mark.asyncio
async def test_metadata_service_filters_by_type_and_reports_provider_errors():
    client = TMDBClient(_settings(), http_client=FakeTMDBHTTP(error=ProviderTimeoutError("timeout")))
    result = await MetadataService(client).search("Movie", "movie")

    assert result.candidates == []
    assert result.providers_requested == ["tmdb"]
    assert result.errors[0].error_type == "ProviderTimeoutError"


def test_images_are_built_only_from_valid_tmdb_paths():
    settings = _settings()
    assert tmdb_image_url(settings, "/poster.jpg", "w342") == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert tmdb_image_url(settings, "https://evil.test/x.jpg", "w342") is None
    assert tmdb_image_url(settings, "/poster.jpg?token=secret", "w342") is None


def test_metadata_candidate_schema_ignores_unknown_fields():
    candidate = MetadataCandidate(
        provider="tmdb",
        provider_id="1",
        media_type="movie",
        title="Safe",
        raw_payload="must not be retained",
    )
    assert "raw_payload" not in candidate.model_dump()
