"""Repository layer: one class per aggregate, all SQL lives here.

`BaseRepository` is the shared parent for every concrete repository. It
exists to hold the `AsyncSession` and to document the project's single most
important data-access rule:

    Repositories must NEVER call `session.commit()` (or `rollback()`).
    The caller owns the transaction boundary. In practice "the caller" is
    `db.session.get_session()`'s context manager, which commits on clean
    exit and rolls back on exception. This lets a single command handler
    compose multiple repository calls (e.g. register a server AND write an
    audit log row) inside one atomic transaction.

Concrete repositories are imported here so callers can do
`from craftcord.db.repositories import GuildRepository` instead of reaching
into the individual submodules.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    """Shared base for all repositories.

    Holds the `AsyncSession` the repository operates on. Subclasses add
    their own query methods; the base class deliberately exposes no
    `commit`/`rollback` helpers, because repositories must never manage the
    transaction themselves — see module docstring.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Store the session this repository will issue queries against.

        Args:
            session: An active `AsyncSession`, typically obtained from
                `craftcord.db.session.get_session()`.
        """
        self.session = session


from craftcord.db.repositories.audit_repo import AuditRepository  # noqa: E402
from craftcord.db.repositories.guild_repo import GuildRepository  # noqa: E402
from craftcord.db.repositories.server_repo import ServerRepository  # noqa: E402
from craftcord.db.repositories.session_repo import SessionRepository  # noqa: E402
from craftcord.db.repositories.user_repo import UserRepository  # noqa: E402

__all__ = [
    "BaseRepository",
    "GuildRepository",
    "ServerRepository",
    "UserRepository",
    "AuditRepository",
    "SessionRepository",
]
