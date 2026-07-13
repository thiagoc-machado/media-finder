"""Database metadata tests."""

from app.database import Base


def test_initial_metadata_contains_required_tables():
    assert set(Base.metadata.tables) == {
        "providers",
        "search_history",
        "download_history",
        "settings",
    }
