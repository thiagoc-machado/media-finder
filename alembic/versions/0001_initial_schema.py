"""Create the initial Media Finder schema."""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the initial application tables and indexes."""

    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("provider_type", sa.String(length=40), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_providers_slug", "providers", ["slug"], unique=False)

    op.create_table(
        "search_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(length=500), nullable=False),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("providers_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("filters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "download_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("info_hash", sa.String(length=64), nullable=True),
        sa.Column("magnet_url", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=30), nullable=False),
        sa.Column("quality", sa.String(length=30), nullable=True),
        sa.Column("language", sa.String(length=120), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("seeders", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("qbittorrent_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_download_history_info_hash", "download_history", ["info_hash"], unique=False)
    op.create_index("ix_download_history_qbittorrent_hash", "download_history", ["qbittorrent_hash"], unique=False)

    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_settings_key", "settings", ["key"], unique=False)


def downgrade() -> None:
    """Drop all initial application tables."""

    op.drop_index("ix_settings_key", table_name="settings")
    op.drop_table("settings")
    op.drop_index("ix_download_history_qbittorrent_hash", table_name="download_history")
    op.drop_index("ix_download_history_info_hash", table_name="download_history")
    op.drop_table("download_history")
    op.drop_table("search_history")
    op.drop_index("ix_providers_slug", table_name="providers")
    op.drop_table("providers")
