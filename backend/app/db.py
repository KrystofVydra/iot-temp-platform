"""Database engine and declarative base.

The async engine targets asyncpg. ``DATABASE_URL`` is read lazily so that
importing this module (e.g. from Alembic env.py for ``Base.metadata``) does
not require the env var to be set at import time.
"""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set. Expected an asyncpg URL such as "
            "postgresql+asyncpg://user:pass@host:5432/db"
        )
    return url


def create_engine() -> AsyncEngine:
    return create_async_engine(get_database_url(), pool_pre_ping=True)
