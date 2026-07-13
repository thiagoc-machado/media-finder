"""Tolerant, typed projections of the Stremio addon protocol."""

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class StremioManifestResource(BaseModel):
    """One resource declaration from a Stremio manifest."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    types: list[str] = Field(default_factory=list)
    id_prefixes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("id_prefixes", "idPrefixes"),
    )


class StremioManifest(BaseModel):
    """Manifest fields needed to consume stream resources safely."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    version: str | None = None
    name: str
    description: str | None = None
    resources: list[str | StremioManifestResource] = Field(default_factory=list)
    types: list[str] = Field(default_factory=list)
    id_prefixes: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("id_prefixes", "idPrefixes"),
    )
    catalogs: list[dict[str, Any]] = Field(default_factory=list)
    behavior_hints: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("behavior_hints", "behaviorHints"),
    )


class StremioStreamBehaviorHints(BaseModel):
    """Optional hints attached to one stream."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    binge_group: str | None = Field(
        default=None,
        validation_alias=AliasChoices("binge_group", "bingeGroup"),
    )
    not_web_ready: bool | None = Field(
        default=None,
        validation_alias=AliasChoices("not_web_ready", "notWebReady"),
    )
    filename: str | None = None
    video_size: int | None = Field(
        default=None,
        validation_alias=AliasChoices("video_size", "videoSize"),
    )


class StremioStream(BaseModel):
    """Safe stream projection accepted from an addon response."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    title: str | None = None
    description: str | None = None
    info_hash: str | None = Field(default=None, validation_alias=AliasChoices("info_hash", "infoHash"))
    file_idx: int | None = Field(default=None, validation_alias=AliasChoices("file_idx", "fileIdx"))
    url: str | None = None
    external_url: str | None = Field(default=None, validation_alias=AliasChoices("external_url", "externalUrl"))
    yt_id: str | None = Field(default=None, validation_alias=AliasChoices("yt_id", "ytId"))
    sources: list[str] = Field(default_factory=list)
    behavior_hints: StremioStreamBehaviorHints = Field(
        default_factory=StremioStreamBehaviorHints,
        validation_alias=AliasChoices("behavior_hints", "behaviorHints"),
    )
    raw_data: dict[str, Any] = Field(default_factory=dict)


class StremioStreamResponse(BaseModel):
    """Stream endpoint response with protocol cache hints."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    streams: list[StremioStream] = Field(default_factory=list)
    cache_max_age: int | None = Field(default=None, validation_alias=AliasChoices("cache_max_age", "cacheMaxAge"))
    stale_revalidate: int | None = Field(
        default=None,
        validation_alias=AliasChoices("stale_revalidate", "staleRevalidate"),
    )
    stale_error: int | None = Field(default=None, validation_alias=AliasChoices("stale_error", "staleError"))
