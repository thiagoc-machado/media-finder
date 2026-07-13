"""Schemas shared by the HTTP API."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Public service health response."""

    status: Literal["ok", "error"]
    database: Literal["ok", "error"]
    version: str
