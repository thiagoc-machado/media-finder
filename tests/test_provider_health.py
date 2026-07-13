"""Provider health endpoint tests."""

import pytest

pytestmark = pytest.mark.asyncio


async def test_provider_health_endpoint_returns_registered_mock(client):
    response = await client.get("/providers/health")

    assert response.status_code == 200
    assert response.json()[0]["slug"] == "mock"
    assert response.json()[0]["available"] is True
