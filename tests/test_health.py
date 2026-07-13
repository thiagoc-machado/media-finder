"""Health endpoint tests."""

import pytest

from app import database

pytestmark = pytest.mark.asyncio


async def test_health_returns_service_status(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "version": "0.1.0"}


async def test_health_returns_service_unavailable_when_database_fails(client, monkeypatch):
    monkeypatch.setattr(database, "check_database", lambda: False)

    response = await client.get("/health")

    assert response.status_code == 503
    assert response.json()["database"] == "error"
