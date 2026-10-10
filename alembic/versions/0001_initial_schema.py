"""Initial schema: guilds, servers, users, audit_log, server_sessions.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- guilds ---------------------------------------------------------
    op.create_table(
        "guilds",
        sa.Column("id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False, server_default="grass"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("tier IN ('grass', 'iron', 'gold', 'diamond')", name="ck_guilds_tier"),
        sa.PrimaryKeyConstraint("id", name="pk_guilds"),
    )

    # --- servers ---------------------------------------------------------
    op.create_table(
        "servers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("pterodactyl_uuid", sa.String(length=36), nullable=False),
        sa.Column("pterodactyl_numeric_id", sa.BigInteger(), nullable=False),
        sa.Column("mc_version", sa.String(length=16), nullable=False, server_default="1.20.4"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["guild_id"], ["guilds.id"], name="fk_servers_guild_id_guilds", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_servers"),
        sa.UniqueConstraint("pterodactyl_uuid", name="uq_servers_pterodactyl_uuid"),
        sa.UniqueConstraint("guild_id", "name", name="uq_servers_guild_id_name"),
    )
    # Partial unique index: at most one default server per guild.
    op.create_index(
        "uq_servers_one_default_per_guild",
        "servers",
        ["guild_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    # --- users -------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("discord_id", sa.BigInteger(), autoincrement=False, nullable=False),
        # Stored lowercased by the application layer (see UserRepository.link),
        # which is what makes this UNIQUE constraint behave case-insensitively.
        sa.Column("minecraft_username", sa.String(length=16), nullable=False),
        sa.Column("minecraft_uuid", sa.String(length=36), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("discord_id", name="pk_users"),
        sa.UniqueConstraint("minecraft_username", name="uq_users_minecraft_username"),
    )

    # --- audit_log ---------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("discord_id", sa.BigInteger(), nullable=False),
        sa.Column("command_name", sa.String(length=64), nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name="fk_audit_log_server_id_servers", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
    )
    op.create_index(
        "ix_audit_log_guild_id_created_at",
        "audit_log",
        ["guild_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_audit_log_discord_id_created_at",
        "audit_log",
        ["discord_id", sa.text("created_at DESC")],
    )

    # --- server_sessions -----------------------------------------------------
    op.create_table(
        "server_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("server_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by_discord_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["server_id"], ["servers.id"], name="fk_server_sessions_server_id_servers", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_server_sessions"),
    )
    op.create_index(
        "ix_server_sessions_server_id_started_at",
        "server_sessions",
        ["server_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_server_sessions_server_id_started_at", table_name="server_sessions")
    op.drop_table("server_sessions")

    op.drop_index("ix_audit_log_discord_id_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_guild_id_created_at", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("users")

    op.drop_index("uq_servers_one_default_per_guild", table_name="servers")
    op.drop_table("servers")

    op.drop_table("guilds")
