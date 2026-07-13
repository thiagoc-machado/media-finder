"""Search history database model."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SearchHistory(Base):
    """Record of a search request and its aggregate result counts."""

    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(30), nullable=False)
    providers_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    filters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    results_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
