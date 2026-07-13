"""Initial server-rendered page tests."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio


async def test_home_page_is_server_rendered(client):
    response = await client.get("/")

    assert response.status_code == 200
    assert "Media Finder" in response.text
    assert "Comece uma busca" in response.text
    assert "/static/css/app.css" in response.text
    assert "/static/vendor/htmx.min.js" in response.text


async def test_navigation_pages_are_available(client):
    for path, heading in [("/downloads", "Downloads"), ("/providers", "Fontes"), ("/settings", "Configurações")]:
        response = await client.get(path)
        assert response.status_code == 200
        assert heading in response.text


async def test_static_assets_are_local(client):
    static_root = Path("app/static")
    assert (static_root / "css/app.css").is_file()
    assert (static_root / "js/app.js").is_file()
    assert (static_root / "vendor/htmx.min.js").is_file()
