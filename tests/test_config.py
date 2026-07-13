"""Configuration tests."""

from app.config import Settings


def test_settings_defaults_match_deployment_contract():
    settings = Settings()

    assert settings.app_name == "Media Finder"
    assert settings.app_port == 8091
    assert settings.database_url == "sqlite:////config/media-finder.db"
    assert settings.qbittorrent_url == "http://qbittorrent:8080"


def test_settings_can_be_overridden_without_credentials_in_code():
    settings = Settings(app_env="test", app_port=9000, database_url="sqlite:///test.db")

    assert settings.app_env == "test"
    assert settings.app_port == 9000
    assert settings.database_url == "sqlite:///test.db"
