"""Alembic environment.

Reads the database URL from the DATABASE_URL environment variable so the
same migrations work locally, in CI, and in Coolify without checking any
secret into git.

Async engine: SQLAlchemy 2.0 + asyncpg. Alembic itself is sync, so we run
the migration body inside an async connection via ``run_sync``.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app import models  # noqa: F401  ensures models register with Base.metadata
from app.db import Base

# Alembic Config object provides access to .ini values.
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the DATABASE_URL from the environment into the Alembic config so
# downstream code (engine_from_config, autogenerate, etc.) sees it.
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Alembic needs an asyncpg URL such as "
        "postgresql+asyncpg://user:pass@host:5432/db"
    )
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render migrations as SQL without a live database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live database via an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
