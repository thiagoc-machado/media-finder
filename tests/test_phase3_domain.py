"""Pure unit coverage for the Phase 3 domain layer."""

import base64
from datetime import datetime, timezone

import pytest

from app.exceptions import InvalidMagnetError
from app.schemas.provider import ProviderSearchError, SearchExecutionResult
from app.schemas.search import SearchFilters, SearchRequest, SearchResult, SearchSort
from app.services.deduplication_service import deduplicate_results
from app.services.filter_service import filter_results
from app.services.normalization_service import normalize_result
from app.services.pipeline_service import process_search_results
from app.services.scoring_service import ScoringPreferences, score_result
from app.services.sorting_service import sort_results
from app.utils.magnet import (
    build_magnet,
    extract_info_hash,
    normalize_info_hash,
    normalize_magnet,
    parse_magnet,
    validate_info_hash,
)
from app.utils.release_parser import parse_release
from app.utils.size import format_size, parse_size

HASH = "0123456789abcdef0123456789abcdef01234567"


def result(**overrides) -> SearchResult:
    """Build a compact result fixture."""

    values = {
        "provider": "mock",
        "title": "Movie Name 2026 1080p WEB-DL x265",
        "media_type": "movie",
        "size_bytes": 1_000_000_000,
        "seeders": 10,
        "tracker": "tracker.example",
        "languages": ["PT-BR"],
        "quality": "1080p",
        "codec": "x265",
        "source_type": "WEB-DL",
    }
    values.update(overrides)
    return SearchResult(**values)


class TestReleaseParser:
    @pytest.mark.parametrize("quality", ["480p", "576p", "720p", "1080p", "1080i", "2160p"])
    def test_quality_variants(self, quality: str) -> None:
        assert parse_release(f"Movie.{quality}").quality == quality

    @pytest.mark.parametrize("alias", ["4K", "UHD"])
    def test_quality_aliases(self, alias: str) -> None:
        assert parse_release(f"Movie.{alias}").quality == "2160p"

    def test_languages_and_dual_audio_do_not_invent_english(self) -> None:
        parsed = parse_release("Movie.PTBR.PT-PT.Castellano.Spanish Latino.English.Multi Audio.Dual Audio.Dublado")
        assert parsed.languages == ["PT-BR", "PT-PT", "Castellano", "Latino", "English", "Multi", "Dual Audio"]
        assert "Dubbed" not in parsed.languages
        assert parse_release("Movie.Original").languages == ["Original"]
        assert "English" not in parse_release("Movie.Original").languages
        assert parse_release("Movie.Dublado").languages == ["Dubbed"]

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("H264", "x264"), ("H.264", "x264"), ("AVC", "x264"), ("HEVC", "x265"), ("H.265", "x265"), ("AV1", "AV1")],
    )
    def test_codec_aliases(self, value: str, expected: str) -> None:
        assert parse_release(f"Movie.1080p.{value}").codec == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("WEBDL", "WEB-DL"),
            ("WEB DL", "WEB-DL"),
            ("WEB-Rip", "WEBRip"),
            ("Blu-ray", "BluRay"),
            ("BDRip", "BDRip"),
            ("BRRip", "BRRip"),
            ("DVD-Rip", "DVDRip"),
            ("TELESYNC", "TS"),
            ("HDCAM", "HDCAM"),
        ],
    )
    def test_source_aliases_stay_distinct(self, value: str, expected: str) -> None:
        assert parse_release(f"Movie.1080p.{value}").source_type == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("AC-3", "AC3"), ("E-AC-3", "EAC3"), ("DD+", "DD+"), ("DTS-HD", "DTS-HD"), ("TrueHD", "TrueHD")],
    )
    def test_audio_aliases(self, value: str, expected: str) -> None:
        parsed = parse_release(f"Movie.1080p.{value}.5.1")
        assert parsed.audio_codec == expected
        assert parsed.audio_channels == "5.1"

    def test_release_group_requires_final_hyphenated_evidence(self) -> None:
        assert parse_release("Movie.Name.2026.1080p.WEB-DL.x265-GROUP.mkv").release_group == "GROUP"
        assert parse_release("Movie.Name.2026.1080p.WEB-DL.mkv").release_group is None
        assert parse_release("Movie.123.2026.mkv").quality is None
        assert parse_release("Movie.1080p.WEB-DL.DD+").release_group is None


class TestSize:
    def test_decimal_and_binary_units(self) -> None:
        assert parse_size("1.5 GB") == 1_500_000_000
        assert parse_size("1,5 GB") == 1_500_000_000
        assert parse_size("1 GiB") == 1024**3
        assert parse_size(42) == 42
        assert parse_size(None) is None

    @pytest.mark.parametrize("value", ["-1 GB", "not-a-size", "1 XB", "", True, -1])
    def test_invalid_values_are_rejected(self, value) -> None:
        with pytest.raises(ValueError):
            parse_size(value)

    def test_formatting(self) -> None:
        assert format_size(None) == "Unknown"
        assert format_size(1024) == "1.00 KiB"
        assert format_size(1_500_000, binary=False) == "1.50 MB"


class TestMagnets:
    def test_hex_hash_and_normalized_magnet(self) -> None:
        magnet = build_magnet(
            HASH.upper(),
            display_name="My Film & Friends",
            trackers=["https://tracker.one/announce", "https://tracker.one/announce"],
            params=[("x.custom", "a b"), ("x.custom", "two")],
        )
        parsed = parse_magnet(magnet)
        assert parsed.info_hash == HASH
        assert parsed.trackers == ("https://tracker.one/announce",)
        assert parsed.display_name == "My Film & Friends"
        assert parsed.params == (("x.custom", "a b"), ("x.custom", "two"))
        assert extract_info_hash(magnet) == HASH
        assert normalize_magnet(magnet).startswith(f"magnet:?xt=urn%3Abtih%3A{HASH}")

    def test_base32_hash(self) -> None:
        base32_hash = base64.b32encode(bytes.fromhex(HASH)).decode().rstrip("=")
        assert validate_info_hash(base32_hash)
        assert normalize_info_hash(base32_hash) == HASH

    def test_encoded_input_and_duplicate_trackers(self) -> None:
        magnet = (
            f"magnet:?dn=Movie%20Name&tr=https%3A%2F%2Ftracker.example%2Fa&"
            f"tr=https%3A%2F%2Ftracker.example%2Fa&xt=urn%3Abtih%3A{HASH.upper()}"
        )
        parsed = parse_magnet(magnet)
        assert parsed.info_hash == HASH
        assert parsed.trackers == ("https://tracker.example/a",)

    @pytest.mark.parametrize(
        "value",
        ["http://example", "magnet:?xt=urn:btih:not-a-hash", "magnet:?dn=missing-hash", "magnet:?xt=urn:other:x"],
    )
    def test_invalid_magnets_are_rejected(self, value: str) -> None:
        with pytest.raises(InvalidMagnetError):
            parse_magnet(value)

    def test_oversized_and_control_input_are_rejected(self) -> None:
        with pytest.raises(InvalidMagnetError):
            parse_magnet("magnet:?" + "x" * 16_384)
        with pytest.raises(InvalidMagnetError):
            parse_magnet(f"magnet:?xt=urn:btih:{HASH}\n")


class TestNormalizationAndDeduplication:
    def test_normalization_preserves_raw_data_and_fills_evidence(self) -> None:
        original = {
            "size": "1,5 GB",
            "provider_token": "keep-me",
        }
        source = result(
            provider=" mock ",
            title="  Film.Name.4K.PTBR.WEBDL.HEVC-GRP  ",
            quality=None,
            languages=[],
            codec=None,
            source_type=None,
            size_bytes=None,
            tracker="TRACKER.example",
            trackers=["tracker.example"],
            raw_data=original,
        )
        normalized = normalize_result(source)
        assert normalized.title == "Film.Name.4K.PTBR.WEBDL.HEVC-GRP"
        assert normalized.quality == "2160p"
        assert normalized.languages == ["PT-BR"]
        assert normalized.codec == "x265"
        assert normalized.source_type == "WEB-DL"
        assert normalized.size_bytes == 1_500_000_000
        assert normalized.trackers == ["tracker.example", "TRACKER.example"][:1]
        assert normalized.raw_data == original
        assert normalized.raw_data is not original

    def test_strong_dedup_merges_evidence(self) -> None:
        first = result(
            provider="one",
            title="Film 1080p",
            info_hash=HASH.upper(),
            magnet_url=build_magnet(HASH),
            trackers=["tracker.one"],
            seeders=3,
            leechers=2,
            raw_data={"from": "one"},
        )
        second = result(
            provider="two",
            title="Film 1080p better metadata",
            info_hash=HASH,
            magnet_url=build_magnet(HASH, display_name="Film", trackers=["tracker.two"]),
            trackers=["tracker.two"],
            seeders=30,
            leechers=5,
            size_bytes=2_000_000_000,
            languages=["English"],
            raw_data={"from": "two"},
        )
        merged = deduplicate_results([normalize_result(first), normalize_result(second)])
        assert len(merged) == 1
        item = merged[0]
        assert item.deduplication_type == "strong"
        assert item.providers == ["one", "two"]
        assert item.seeders == 30
        assert item.leechers == 5
        assert item.languages == ["PT-BR", "English"]
        assert set(item.trackers) == {"tracker.example", "tracker.one", "tracker.two"}
        assert "Conflicting sizes" in item.deduplication_warnings[0]
        assert item.raw_data["_provider_sources"]["one"][0]["from"] == "one"
        assert item.raw_data["_provider_sources"]["two"][0]["from"] == "two"
        assert "dn=Film" in item.magnet_url

    def test_weak_dedup_is_conservative_and_configurable(self) -> None:
        first = result(provider="one", title="Film.Name.1080p", info_hash=None)
        second = result(provider="two", title="Film Name 1080P", info_hash=None)
        episode = result(provider="three", title="Film Name S01E02 1080p", info_hash=None)
        assert len(deduplicate_results([first, second])) == 1
        assert deduplicate_results([first, second])[0].deduplication_type == "weak"
        assert len(deduplicate_results([first, second], allow_weak=False)) == 2
        assert len(deduplicate_results([first, episode])) == 2


class TestFilters:
    def test_category_or_and_terms(self) -> None:
        item = result(languages=["PT-BR", "English"], trackers=["tracker.example"], tracker=None)
        filters = SearchFilters(
            providers=["MOCK", "other"],
            languages=["portuguese br", "castellano"],
            qualities=["4K", "1080p"],
            codecs=["H.265"],
            source_types=["webdl"],
            trackers=["TRACKER.EXAMPLE"],
            required_terms=["movie", "name"],
        )
        assert filter_results([item], filters) == [item]
        assert filter_results([item], filters.model_copy(update={"providers": ["other"]})) == []
        assert filter_results([item], SearchFilters(excluded_terms=["1080p"])) == []

    def test_missing_size_and_seeders_are_excluded_when_bounds_are_set(self) -> None:
        item = result(size_bytes=None, seeders=None)
        assert filter_results([item], SearchFilters()) == [item]
        assert filter_results([item], SearchFilters(min_size_bytes=1)) == []
        assert filter_results([item], SearchFilters(min_seeders=1)) == []


class TestSorting:
    def test_quality_and_none_last(self) -> None:
        items = [
            result(title="unknown", quality=None),
            result(title="low", quality="480p"),
            result(title="interlace", quality="1080i"),
            result(title="high", quality="4K"),
        ]
        assert [item.title for item in sort_results(items, SearchSort.QUALITY_DESC)] == [
            "high",
            "interlace",
            "low",
            "unknown",
        ]

    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (SearchSort.SCORE_DESC, ["high", "low"]),
            (SearchSort.SEEDERS_DESC, ["high", "low"]),
            (SearchSort.SIZE_ASC, ["high", "low"]),
            (SearchSort.SIZE_DESC, ["low", "high"]),
            (SearchSort.PROVIDER_ASC, ["high", "low"]),
            (SearchSort.TRACKER_ASC, ["high", "low"]),
            (SearchSort.PUBLISHED_AT_DESC, ["high", "low"]),
        ],
    )
    def test_all_other_modes(self, mode: SearchSort, expected: list[str]) -> None:
        items = [
            result(
                title="low",
                score=1,
                seeders=1,
                size_bytes=2,
                provider="z-provider",
                tracker="z-tracker",
                published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            result(
                title="high",
                score=2,
                seeders=2,
                size_bytes=1,
                provider="a-provider",
                tracker="a-tracker",
                published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
        ]
        assert [item.title for item in sort_results(items, mode)] == expected

    def test_sort_is_stable_for_ties(self) -> None:
        items = [result(title="first", score=1), result(title="second", score=1)]
        assert [item.title for item in sort_results(items, "score_desc")] == ["first", "second"]


class TestScoring:
    def test_preferences_cap_and_breakdown_without_mutation(self) -> None:
        item = result(seeders=500, size_bytes=3_000_000_000)
        preferences = ScoringPreferences(
            preferred_languages=["Portuguese BR"],
            preferred_qualities=["1080p"],
            preferred_codecs=["HEVC"],
            preferred_sources=["WEBDL"],
            preferred_max_size_bytes=2_000_000_000,
            excluded_terms=["cam"],
        )
        scored = score_result(item, preferences)
        assert scored.score == 285
        assert scored.score_breakdown == [
            "+100.0 Preferred language: PT-BR",
            "+60.0 Preferred quality: 1080p",
            "+20.0 Preferred codec: x265",
            "+20.0 Preferred source: WEB-DL",
            "+100.0 Seed availability: 100/100",
            "-15.0 Size above preferred range",
        ]
        assert item.score == 0
        assert item.score_breakdown == []

    def test_low_seeders_and_excluded_terms_penalize_without_filtering(self) -> None:
        scored = score_result(
            result(title="Movie CAM", seeders=2),
            ScoringPreferences(low_seeders_threshold=5, excluded_terms=["cam"]),
        )
        assert scored.score == -1018
        assert any("Low seed availability" in line for line in scored.score_breakdown)
        assert any("Excluded term: cam" in line for line in scored.score_breakdown)

    def test_no_preferences_is_deterministic(self) -> None:
        item = result(seeders=7)
        first = score_result(item, ScoringPreferences())
        second = score_result(item, ScoringPreferences())
        assert first.model_dump() == second.model_dump()


@pytest.mark.asyncio
async def test_processing_pipeline_counts_and_preserves_provider_errors() -> None:
    execution = SearchExecutionResult(
        results=[
            result(provider="one", info_hash=HASH.upper(), title="Film.1080p.WEB-DL"),
            result(provider="two", info_hash=HASH, title="Film.1080p.WEB-DL", seeders=20),
            result(provider="three", title="Other.720p", info_hash=None, size_bytes=2_000_000_000),
        ],
        errors=[ProviderSearchError(provider="broken", error_type="timeout", message="timed out")],
        duration_ms=4,
    )
    processed = await process_search_results(
        execution,
        SearchFilters(min_seeders=15),
        ScoringPreferences(preferred_qualities=["1080p"]),
        SearchSort.SCORE_DESC,
    )
    assert processed.raw_count == 3
    assert processed.normalized_count == 3
    assert processed.deduplicated_count == 2
    assert processed.filtered_count == 1
    assert len(processed.results) == 1
    assert processed.results[0].providers == ["one", "two"]
    assert processed.provider_errors == execution.errors
    assert processed.duration_ms >= 4


def test_phase3_does_not_change_search_request_contract() -> None:
    assert SearchRequest(query="movie").media_type == "all"
