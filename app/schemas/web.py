"""Validated query models used by the server-rendered search interface."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.search import SearchFilters, SearchRequest, SearchSort
from app.utils.size import parse_size


class SearchQueryParams(BaseModel):
    """Safe, bounded representation of query-string search parameters."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=200)
    media_type: Literal["movie", "series", "anime", "other", "all"] = "all"
    providers: list[str] = Field(default_factory=list, max_length=10)
    season: int | None = Field(default=None, ge=1, le=1000)
    episode: int | None = Field(default=None, ge=1, le=1000)
    languages: list[str] = Field(default_factory=list, max_length=20)
    qualities: list[str] = Field(default_factory=list, max_length=20)
    codecs: list[str] = Field(default_factory=list, max_length=20)
    source_types: list[str] = Field(default_factory=list, max_length=20)
    trackers: list[str] = Field(default_factory=list, max_length=20)
    min_size: str | None = None
    max_size: str | None = None
    min_seeders: int | None = Field(default=None, ge=0, le=10_000_000)
    required_terms: str | None = None
    excluded_terms: str | None = None
    sort_by: SearchSort = SearchSort.SCORE_DESC
    weak_deduplication: bool = True

    @field_validator("query", mode="before")
    @classmethod
    def clean_query(cls, value: object) -> str:
        """Collapse whitespace before applying query length limits."""

        if not isinstance(value, str):
            raise ValueError("Informe uma busca válida.")
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("A busca deve ter pelo menos 2 caracteres.")
        return cleaned

    @field_validator("providers", "languages", "qualities", "codecs", "source_types", "trackers", mode="before")
    @classmethod
    def clean_lists(cls, values: object) -> list[str]:
        """Strip list values, remove duplicates, and reject control characters."""

        if values is None:
            return []
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            raise ValueError("Lista de filtros inválida.")
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                raise ValueError("Lista de filtros inválida.")
            for candidate in value.split(","):
                cleaned = candidate.strip()
                if not cleaned:
                    continue
                if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
                    raise ValueError("Os filtros não podem conter caracteres de controle.")
                key = cleaned.casefold()
                if key not in seen:
                    seen.add(key)
                    result.append(cleaned)
        return result

    @field_validator("min_size", "max_size", mode="before")
    @classmethod
    def validate_size_text(cls, value: object) -> str | None:
        """Validate textual sizes early while retaining their display value."""

        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("Tamanho inválido.")
        try:
            parse_size(value)
        except ValueError as exc:
            raise ValueError("Use um tamanho como 700 MB ou 1.5 GB.") from exc
        return value.strip()

    @field_validator("required_terms", "excluded_terms", mode="before")
    @classmethod
    def validate_terms(cls, value: object) -> str | None:
        """Normalize comma-separated terms and bound their count and length."""

        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise ValueError("Termos inválidos.")
        terms = _split_terms(value)
        if len(terms) > 20 or any(len(term) > 80 for term in terms):
            raise ValueError("Informe no máximo 20 termos de até 80 caracteres.")
        return ", ".join(terms) if terms else None

    @model_validator(mode="after")
    def validate_media_context(self) -> "SearchQueryParams":
        """Only series and anime searches accept season and episode values."""

        if self.media_type not in {"series", "anime"} and (self.season is not None or self.episode is not None):
            raise ValueError("Temporada e episódio só estão disponíveis para séries e anime.")
        if (self.season is None) != (self.episode is None) and self.media_type in {"series", "anime"}:
            raise ValueError("Informe temporada e episódio juntos.")
        return self

    def to_search_request(self) -> SearchRequest:
        """Convert validated web parameters to the provider contract."""

        return SearchRequest(
            query=self.query,
            media_type=self.media_type,
            season=self.season,
            episode=self.episode,
        )

    def to_filters(self) -> SearchFilters:
        """Convert validated web values to Phase 3 filter fields."""

        min_size_bytes = parse_size(self.min_size)
        max_size_bytes = parse_size(self.max_size)
        if min_size_bytes is not None and max_size_bytes is not None and min_size_bytes > max_size_bytes:
            raise ValueError("O tamanho mínimo não pode ser maior que o máximo.")
        return SearchFilters(
            providers=self.providers,
            languages=self.languages,
            qualities=self.qualities,
            codecs=self.codecs,
            source_types=self.source_types,
            trackers=self.trackers,
            min_size_bytes=min_size_bytes,
            max_size_bytes=max_size_bytes,
            min_seeders=self.min_seeders,
            required_terms=_split_terms(self.required_terms),
            excluded_terms=_split_terms(self.excluded_terms),
        )


def _split_terms(value: str | None) -> list[str]:
    """Split and normalize comma-separated user terms."""

    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for term in value.split(","):
        cleaned = " ".join(term.split())
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result
