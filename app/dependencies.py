"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator

from sqlalchemy.orm import Session

from app import database


async def database_session() -> AsyncIterator[Session]:
    """Expose a request-scoped session without a threadpool finalizer deadlock."""

    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()
