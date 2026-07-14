"""Alembic env.py — PostgreSQL 迁移配置。

从 DATABASE_URL 环境变量读取连接配置，不依赖 alembic.ini 中的硬编码 URL。
"""
from logging.config import fileConfig
import os

from alembic import context

# Import all models to register them with Base.metadata
import backend.db.models  # noqa: F401

from backend.db.session import Base

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get database URL from environment variable
# This is the PRIMARY source of truth for migration connections
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is required. "
        "Alembic migrations only support PostgreSQL."
    )

# Configure Alembic to use the DATABASE_URL
config.set_main_option("sqlalchemy.url", database_url)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Used for generating migration scripts without a live database connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to PostgreSQL using DATABASE_URL from environment.
    """
    connectable = context.config.get_section(config.config_ini_section)
    if connectable is None:
        connectable = {}

    # Ensure we're using the DATABASE_URL
    connectable["sqlalchemy.url"] = database_url

    from sqlalchemy import engine_from_config

    connectable["pool_pre_ping"] = True
    connectable["pool_size"] = 1
    connectable["max_overflow"] = 0

    engine = engine_from_config(
        connectable,
        prefix="sqlalchemy.",
    )

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
