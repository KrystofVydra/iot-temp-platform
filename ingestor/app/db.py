"""Async SQLAlchemy engine, session factory, and declarative base.

Engine and session factory are lazily constructed via cached getters so that
importing this module does not require ``DATABASE_URL`` to be set.
"""

from __future__ import annotations

from functools import cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    """Declarative base for ingestor ORM models."""


@cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().DATABASE_URL, pool_size=5)


@cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)
