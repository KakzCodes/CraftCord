"""SQLAlchemy declarative base shared by every ORM model.

Kept in its own module (rather than inside `models.py`) so Alembic's
`env.py` can import `Base.metadata` without pulling in the full model
module graph, and so there is a single, unambiguous `Base` that every
model subclasses.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for all CraftCord ORM models."""
