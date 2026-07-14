"""Shared fixtures for the foundation test suite."""

from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import (
    database,
    models,  # noqa: F401
)
from app.database import Base
from app.main import app
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry


@pytest_asyncio.fixture()
async def client(tmp_path, monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    """Provide an async client backed by an isolated SQLite database."""

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, class_=Session, expire_on_commit=False, autoflush=False)
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(database, "SessionLocal", test_session)
    test_registry = ProviderRegistry()
    test_registry.register(MockProvider(), priority=10)
    monkeypatch.setattr(app.state, "provider_registry", test_registry)
    await app.state.search_rate_limiter.reset()
    await app.state.metadata_rate_limiter.reset()
    await app.state.metadata_result_store.reset()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client

    test_engine.dispose()
