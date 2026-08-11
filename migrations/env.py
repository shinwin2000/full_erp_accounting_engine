"""
migrations/env.py
~~~~~~~~~~~~~~~~~
Alembic environment configuration - safe for both CLI and import.
"""

from __future__ import annotations
import importlib
import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic imports
from alembic import context

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# METADATA LOADING (safe, done at module level)
# ============================================================================
target_metadata = None

try:
    from infrastructure.persistence_orm.base_model import Base
    target_metadata = Base.metadata
    print("[OK] Loaded Base metadata from infrastructure.persistence_orm.base_model")
except ImportError as e:
    print(f"[WARNING] Could not import Base metadata: {e}")

# Register all table models - dynamic approach
if target_metadata is not None:
    import pkgutil
    import infrastructure.persistence_orm as orm_pkg
    
    # Import semua modul dalam package persistence_orm
    for importer, modname, ispkg in pkgutil.walk_packages(
        path=orm_pkg.__path__,
        prefix=orm_pkg.__name__ + ".",
        onerror=lambda x: None
    ):
        # Hanya import modul yang namanya berakhiran "_table" atau "table"
        if not modname.endswith("_table") and not modname.endswith("table"):
            continue
        try:
            importlib.import_module(modname)
            print(f"[OK] Imported {modname}")
        except Exception as e:
            print(f"[WARNING] Could not import {modname}: {e}")

    # Pastikan UomTable terdaftar (jika belum)
    try:
        import infrastructure.persistence_orm.uom_table
    except ImportError:
        pass


# ============================================================================
# MIGRATION FUNCTIONS (called by Alembic)
# ============================================================================

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    config = context.config
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=False,  # Diperbaiki: Set ke False untuk mengabaikan drift timestamp
        # Abaikan foreign key yang tidak ditemukan? Tidak, kita biarkan error agar jelas.
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,  # Diperbaiki: Set ke False untuk mengabaikan drift timestamp
        # Abaikan foreign key yang tidak ditemukan? Tidak, kita biarkan error agar jelas.
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run async migrations."""
    config = context.config
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


# ============================================================================
# MAIN ENTRY POINT - only executed when Alembic calls this script
# ============================================================================

# Alembic sets 'context' environment only when running migrations.
# We check if context has the required attributes before proceeding.
if hasattr(context, 'config') and context.config is not None:
    # Override database URL from environment if needed
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        context.config.set_main_option("sqlalchemy.url", db_url)
    
    # Configure logging if alembic.ini has loggers
    if context.config.config_file_name:
        fileConfig(context.config.config_file_name)

    # Determine mode and run
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()