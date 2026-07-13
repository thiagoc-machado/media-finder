"""SQLAlchemy engine, metadata and request-scoped sessions."""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all database models."""


def _create_engine() -> Engine:
    settings = get_settings()
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    return create_engine(settings.database_url, connect_args=connect_args, pool_pre_ping=True)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """Yield one SQLAlchemy session for the lifetime of a request."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> bool:
    """Check that SQLite (or the configured database) accepts a simple query."""

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True
