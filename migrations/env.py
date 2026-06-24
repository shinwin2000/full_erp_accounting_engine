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
import pkgutil
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from dotenv import load_dotenv

# Load env variables
load_dotenv()

# Add project root to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# METADATA LOADING (Dynamic Automatic Discovery)
# ============================================================================

target_metadata = None

try:
    from infrastructure.persistence_orm.base_model import Base
    target_metadata = Base.metadata
    print("[OK] Loaded Base metadata from infrastructure.persistence_orm.base_model")
except ImportError as e:
    print(f"[WARNING] Could not import Base metadata: {e}")

# Automatically import all models in infrastructure.persistence_orm
if target_metadata is not None:
    import infrastructure.persistence_orm
    
    path = infrastructure.persistence_orm.__path__
    
    for _, name, is_pkg in pkgutil.iter_modules(path):
        # Skip if it's a sub-package or the base_model itself (to avoid double import)
        if not is_pkg and name != "base_model":
            module_path = f"infrastructure.persistence_orm.{name}"
            try:
                importlib.import_module(module_path)
                print(f"[INFO] Dynamically loaded: {module_path}")
            except Exception as e:
                print(f"[!!!] FAILED TO LOAD {module_path}: {e}")
                continue


# ============================================================================
# OBJECT FILTER HOOK (Mencegah modifikasi tabel & indeks partisi dinamis)
# ============================================================================

def include_object(object, name, type_, reflected, compare_to):
    """Filter out dynamically generated child partition tables and their indexes."""
    if type_ == "table":
        # Abaikan tabel anak dari klaster ledger atau journal terpartisi
        if ("ledger_entry_" in name and name != "ledger_entry_partitioned") or \
           ("journal_line_" in name and name != "journal_line_partitioned"):
            return False
    elif type_ == "index":
        # Abaikan indeks yang melekat pada partisi dinamis berdasarkan nama indeks atau relasi tabel
        if name and ("ledger_entry_20" in name or "journal_line_20" in name):
            return False
        if hasattr(object, "table") and object.table is not None:
            tname = object.table.name
            if ("ledger_entry_" in tname and tname != "ledger_entry_partitioned") or \
               ("journal_line_" in tname and tname != "journal_line_partitioned"):
                return False
    return True


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
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with a given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
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
# MAIN ENTRY POINT
# ============================================================================

if hasattr(context, "config") and context.config is not None:
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        context.config.set_main_option("sqlalchemy.url", db_url)
    
    if context.config.config_file_name:
        fileConfig(context.config.config_file_name)

    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()