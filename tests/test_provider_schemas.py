"""Provider schema tests."""

from app.schemas.search import SearchRequest, SearchResult


def test_search_request_accepts_provider_contract_fields():
    request = SearchRequest(query="Example", media_type="series", tmdb_id=42, season=2, episode=3)

    assert request.query == "Example"
    assert request.media_type == "series"
    assert request.tmdb_id == 42
    assert request.season == 2
    assert request.episode == 3


def test_search_result_mutable_fields_are_not_shared():
    first = SearchResult(provider="one", title="First")
    second = SearchResult(provider="two", title="Second")

    first.languages.append("PT-BR")
    first.trackers.append("tracker.example")
    first.raw_data["source"] = "mock"

    assert second.languages == []
    assert second.trackers == []
    assert second.raw_data == {}
