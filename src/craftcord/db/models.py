"""SQLAlchemy 2.0 declarative ORM models.

These map 1:1 onto the schema created by
`alembic/versions/0001_initial_schema.py`. If you change a model here, add
a corresponding Alembic migration — this module itself never creates or
alters tables (`Base.metadata.create_all()` is deliberately never called;
see `db/session.py`).

All Discord-snowflake columns use `BigInteger` (snowflakes overflow 32-bit
int). All timestamps are timezone-aware (`TIMESTAMPTZ`).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from craftcord.db.base import Base

VALID_TIERS = ("grass", "iron", "gold", "diamond")


class Guild(Base):
    """A Discord guild (server) that has interacted with CraftCord.

    `id` is the Discord guild snowflake itself, not a surrogate key — a
    guild only ever needs one row, created lazily on first interaction via
    `@ensure_guild_registered`.
    """

    __tablename__ = "guilds"
    __table_args__ = (
        CheckConstraint(f"tier IN {VALID_TIERS!r}", name="ck_guilds_tier"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(16), nullable=False, server_default="grass")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),  # NOTE: ORM-side onupdate; not a DB trigger. Only fires on
        # UPDATE statements issued through this ORM instance (which is the only write
        # path in this codebase), so it's sufficient without adding migration complexity.
    )

    servers: Mapped[list[Server]] = relationship(
        back_populates="guild", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"Guild(id={self.id}, name={self.name!r}, tier={self.tier!r})"


class Server(Base):
    """A Minecraft server registered to a guild, backed by a Pterodactyl instance."""

    __tablename__ = "servers"
    __table_args__ = (
        UniqueConstraint("guild_id", "name", name="uq_servers_guild_id_name"),
        Index(
            "uq_servers_one_default_per_guild",
            "guild_id",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    pterodactyl_uuid: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    pterodactyl_numeric_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mc_version: Mapped[str] = mapped_column(String(16), nullable=False, server_default="1.20.4")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    guild: Mapped[Guild] = relationship(back_populates="servers", lazy="selectin")
    sessions: Mapped[list[ServerSession]] = relationship(
        back_populates="server", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"Server(id={self.id}, guild_id={self.guild_id}, "
            f"name={self.name!r}, default={self.is_default})"
        )


class User(Base):
    """A Discord user's link to a Minecraft account. Global, not per-guild.

    `minecraft_username` is always stored lowercased by the repository
    layer so the UNIQUE constraint behaves case-insensitively; see
    `UserRepository.link`.
    """

    __tablename__ = "users"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    minecraft_username: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    minecraft_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"User(discord_id={self.discord_id}, minecraft_username={self.minecraft_username!r})"


class AuditLog(Base):
    """An immutable record of a single slash-command invocation."""

    __tablename__ = "audit_log"
    # NOTE: these are plain ascending composite indexes at the ORM-metadata level.
    # The Alembic migration (the actual source of DDL truth) creates them with an
    # explicit DESC clause on created_at, matching the query pattern ("most recent
    # N entries for this guild/user"). Postgres can still use an ascending index
    # efficiently for a DESC scan, so this divergence is cosmetic, not functional.
    __table_args__ = (
        Index("ix_audit_log_guild_id_created_at", "guild_id", "created_at"),
        Index("ix_audit_log_discord_id_created_at", "discord_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    command_name: Mapped[str] = mapped_column(String(64), nullable=False)
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="SET NULL"), nullable=True
    )
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return (
            f"AuditLog(id={self.id}, guild_id={self.guild_id}, "
            f"command_name={self.command_name!r}, success={self.success})"
        )


class ServerSession(Base):
    """A single start→stop window for a server, used to compute uptime."""

    __tablename__ = "server_sessions"
    __table_args__ = (Index("ix_server_sessions_server_id_started_at", "server_id", "started_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_by_discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)

    server: Mapped[Server] = relationship(back_populates="sessions", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ServerSession(id={self.id}, server_id={self.server_id}, stopped_at={self.stopped_at})"
