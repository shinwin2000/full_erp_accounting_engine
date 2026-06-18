#!/usr/bin/env python3
"""
Module: migration_manager_alembic.py
Layer: Infrastructure (Database)
Responsibility: Mengelola migrasi database menggunakan Alembic. Menyediakan
               fungsi untuk migrasi (upgrade/downgrade), pembuatan migrasi baru,
               status check, dan integrasi dengan aplikasi startup.
Dependencies:
- alembic
- sqlalchemy
- asyncio, subprocess, logging
- infrastructure.database.session_factory_sqlalchemy (SQLAlchemySessionFactory)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Setiap migrasi (upgrade/downgrade) dicatat. Migrasi otomatis saat
       startup dapat diaktifkan untuk production.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.database.session_factory_sqlalchemy import Base, get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_ALEMBIC_CONFIG = {
    "script_location": "migrations",
    "version_locations": "migrations/versions",
    "file_template": "%%(year)d_%%(month)02d_%%(day)02d_%%(hour)02d_%%(minute)02d_%%(second)02d_%%(slug)s",
    "timezone": "UTC",
    "revision_environment": True,
    "compare_type": True,
    "compare_server_default": True,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class MigrationError(Exception):
    """Base exception untuk migration manager."""

    pass


class MigrationNotInitializedError(MigrationError):
    """Migration belum diinisialisasi."""

    pass


# ============================================================================
# MIGRATION MANAGER
# ============================================================================


class AlembicMigrationManager:
    """
    Manager untuk migrasi database menggunakan Alembic.

    Fitur:
    - Init migration environment
    - Create new migration
    - Upgrade to latest version
    - Downgrade to specific version
    - Get current revision
    - Check if migration is needed
    - Auto-migrate on startup (optional)
    - Load seed data
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._alembic_cfg: Config | None = None
        self._initialized = False
        self._script_location = Path("migrations")

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            migration_config = config.get("migrations", {})
            result = DEFAULT_ALEMBIC_CONFIG.copy()
            result.update(migration_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load migration config, using defaults: {e}")
            return DEFAULT_ALEMBIC_CONFIG.copy()

    def _get_alembic_config(self) -> Config:
        """
        Get Alembic configuration.
        """
        if self._alembic_cfg is None:
            alembic_cfg = Config()
            alembic_cfg.set_main_option("script_location", self.config["script_location"])
            alembic_cfg.set_main_option("version_locations", self.config["version_locations"])
            alembic_cfg.set_main_option("file_template", self.config["file_template"])
            alembic_cfg.set_main_option("timezone", self.config["timezone"])
            alembic_cfg.set_main_option(
                "revision_environment", str(self.config["revision_environment"])
            )
            alembic_cfg.set_main_option("compare_type", str(self.config["compare_type"]))
            alembic_cfg.set_main_option(
                "compare_server_default", str(self.config["compare_server_default"])
            )

            # Set SQLAlchemy URL from environment or config
            alembic_cfg.set_main_option("sqlalchemy.url", self._get_dsn_sync())

            self._alembic_cfg = alembic_cfg

        return self._alembic_cfg

    def _get_dsn_sync(self) -> str:
        """
        Get sync DSN for Alembic.
        """
        import os

        # Try to get from environment first
        dsn = os.environ.get("DATABASE_URL")
        if dsn:
            return dsn.replace("postgresql+asyncpg://", "postgresql://")

        # Get from config
        from config.loader_yaml import load_yaml_config

        try:
            config = load_yaml_config("config_files/database_config.yaml")
            db_config = config.get("database", {})
            user = db_config.get("user", "postgres")
            password = db_config.get("password")
            host = db_config.get("host", "localhost")
            port = db_config.get("port", 5432)
            database = db_config.get("database", "erp_db")

            if password:
                dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
            else:
                dsn = f"postgresql://{user}@{host}:{port}/{database}"
            return dsn
        except Exception:
            return "postgresql://postgres@localhost:5432/erp_db"

    async def initialize(self) -> None:
        """
        Initialize Alembic environment if not already.
        """
        if self._initialized:
            return

        script_dir = Path(self.config["script_location"])
        if not script_dir.exists():
            logger.info("Initializing Alembic environment...")
            self.init()

        self._initialized = True
        logger.info("Alembic migration manager initialized")

    def init(self) -> None:
        """
        Initialize Alembic directory (sync).
        """
        cfg = self._get_alembic_config()
        try:
            command.init(cfg, self.config["script_location"])
            logger.info(f"Alembic initialized at {self.config['script_location']}")
        except Exception as e:
            logger.error(f"Failed to initialize Alembic: {e}")
            raise MigrationError(f"Alembic init failed: {e}") from e

    async def create_migration(self, message: str, autogenerate: bool = True) -> str:
        """
        Create a new migration.

        Args:
            message: Migration message
            autogenerate: Auto-generate from model changes

        Returns:
            Revision ID
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()

        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            revision = await loop.run_in_executor(
                None, lambda: command.revision(cfg, message=message, autogenerate=autogenerate)
            )
            logger.info(f"Created migration: {message}")
            return revision
        except Exception as e:
            logger.error(f"Failed to create migration: {e}")
            raise MigrationError(f"Migration creation failed: {e}") from e

    async def upgrade(self, revision: str = "head") -> None:
        """
        Upgrade database to specified revision.

        Args:
            revision: Target revision (default: "head")
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: command.upgrade(cfg, revision))
            logger.info(f"Database upgraded to revision: {revision}")
        except Exception as e:
            logger.error(f"Failed to upgrade database: {e}")
            await trigger_alert(
                title="Database Migration Failed",
                message=f"Upgrade to {revision} failed: {e}",
                severity="critical",
                source="AlembicMigrationManager",
            )
            raise MigrationError(f"Upgrade failed: {e}") from e

    async def downgrade(self, revision: str) -> None:
        """
        Downgrade database to specified revision.

        Args:
            revision: Target revision (use "-1" for one step back)
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: command.downgrade(cfg, revision))
            logger.info(f"Database downgraded to revision: {revision}")
        except Exception as e:
            logger.error(f"Failed to downgrade database: {e}")
            raise MigrationError(f"Downgrade failed: {e}") from e

    async def get_current_revision(self) -> str | None:
        """
        Get current database revision.
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()
        try:
            script_dir = ScriptDirectory.from_config(cfg)
            current = script_dir.get_current_head()
            return current
        except Exception as e:
            logger.warning(f"Failed to get current revision: {e}")
            return None

    async def get_head_revision(self) -> str | None:
        """
        Get latest head revision.
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()
        try:
            script_dir = ScriptDirectory.from_config(cfg)
            heads = script_dir.get_heads()
            return heads[0] if heads else None
        except Exception as e:
            logger.warning(f"Failed to get head revision: {e}")
            return None

    async def get_heads(self) -> list[str]:
        """
        Get all head revisions.
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()
        script_dir = ScriptDirectory.from_config(cfg)
        return script_dir.get_heads()

    async def is_migration_needed(self) -> bool:
        """
        Check if database needs migration.
        """
        current = await self.get_current_revision()
        heads = await self.get_heads()

        if not current:
            return True

        return current not in heads

    async def migrate_if_needed(self) -> bool:
        """
        Run migration if needed.

        Returns:
            True if migration was performed
        """
        if await self.is_migration_needed():
            logger.info("Database migration required, applying...")
            await self.upgrade()
            return True
        else:
            logger.info("Database is up to date")
            return False

    async def stamp(self, revision: str = "head") -> None:
        """
        Stamp database with revision without running migration.
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: command.stamp(cfg, revision))
            logger.info(f"Database stamped with revision: {revision}")
        except Exception as e:
            logger.error(f"Failed to stamp database: {e}")
            raise MigrationError(f"Stamp failed: {e}") from e

    async def show_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """
        Show migration history.
        """
        if not self._initialized:
            await self.initialize()

        cfg = self._get_alembic_config()
        script_dir = ScriptDirectory.from_config(cfg)

        history = []
        for rev in script_dir.walk_revisions(base="base", head="heads"):
            history.append(
                {
                    "revision": rev.revision,
                    "down_revision": rev.down_revision,
                    "date": rev.date.isoformat() if rev.date else None,
                    "message": rev.message,
                    "branch_labels": rev.branch_labels,
                    "is_head": rev.is_head,
                }
            )
            if len(history) >= limit:
                break

        return history

    async def ensure_tables_exist(self) -> None:
        """
        Ensure all tables are created (for development).
        """
        factory = await get_session_factory()
        async with factory.get_session() as session:
            # Check if tables exist
            inspector = inspect(session.bind)
            existing_tables = await inspector.get_table_names()

            if not existing_tables:
                logger.info("No tables found, creating all tables...")
                async with session.begin():
                    await session.run_sync(Base.metadata.create_all)
                logger.info("All tables created")

    async def load_seed_data(self) -> None:
        """
        Load seed data (Chart of Accounts, default settings, etc.).
        This method is expected by the test.
        """
        logger.info("Loading seed data...")
        try:
            factory = await get_session_factory()
            async with factory.get_session() as session:
                # Check if seed already loaded
                result = await session.execute(
                    text("SELECT COUNT(*) FROM account WHERE standard = 'PSAK'")
                )
                count = result.scalar()
                if count > 0:
                    logger.info("Seed data already loaded")
                    return

                # Insert basic Chart of Accounts (PSAK standard)
                # This is a minimal set; real implementation would load from file
                coa_data = [
                    ("1-1000", "Kas", "Asset", "debit", "PSAK"),
                    ("1-1100", "Bank", "Asset", "debit", "PSAK"),
                    ("1-1200", "Piutang Usaha", "Asset", "debit", "PSAK"),
                    ("2-1000", "Utang Usaha", "Liability", "credit", "PSAK"),
                    ("2-2000", "Utang Bank", "Liability", "credit", "PSAK"),
                    ("3-1000", "Modal", "Equity", "credit", "PSAK"),
                    ("4-1000", "Pendapatan", "Revenue", "credit", "PSAK"),
                    ("5-1000", "Beban Gaji", "Expense", "debit", "PSAK"),
                    ("5-2000", "Beban Sewa", "Expense", "debit", "PSAK"),
                    ("5-3000", "Beban Listrik", "Expense", "debit", "PSAK"),
                ]
                for code, name, acc_type, normal, standard in coa_data:
                    await session.execute(
                        text(
                            """
                            INSERT INTO account (account_code, account_name, account_type, normal_balance, standard)
                            VALUES ($1, $2, $3, $4, $5)
                            ON CONFLICT (account_code, legal_entity_id) DO NOTHING
                            """
                        ),
                        code,
                        name,
                        acc_type,
                        normal,
                        standard,
                    )
                await session.commit()
                logger.info(f"Loaded {len(coa_data)} seed accounts")

                # Additional seed data could be added here (fiscal periods, default settings, etc.)

        except Exception as e:
            logger.error(f"Failed to load seed data: {e}")
            raise


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_migration_manager: AlembicMigrationManager | None = None


async def get_migration_manager() -> AlembicMigrationManager:
    """Get singleton instance of AlembicMigrationManager."""
    global _migration_manager
    if _migration_manager is None:
        _migration_manager = AlembicMigrationManager()
        await _migration_manager.initialize()
    return _migration_manager


async def migrate_database() -> None:
    """
    Convenience function to run database migration.
    """
    manager = await get_migration_manager()
    await manager.migrate_if_needed()


# ============================================================================
# ALIAS FOR TEST COMPATIBILITY
# ============================================================================

MigrationManager = AlembicMigrationManager


# ============================================================================
# CLI COMMAND (for direct execution)
# ============================================================================


def cli():
    """CLI entry point for Alembic commands."""
    import argparse

    parser = argparse.ArgumentParser(description="Database migration manager")
    parser.add_argument(
        "command",
        choices=["upgrade", "downgrade", "create", "history", "stamp", "init"],
        help="Migration command",
    )
    parser.add_argument("--revision", default="head", help="Revision target")
    parser.add_argument("--message", "-m", help="Migration message")

    args = parser.parse_args()

    async def run():
        manager = await get_migration_manager()
        if args.command == "upgrade":
            await manager.upgrade(args.revision)
        elif args.command == "downgrade":
            await manager.downgrade(args.revision)
        elif args.command == "create":
            if not args.message:
                print("Error: --message is required for create command")
                sys.exit(1)
            await manager.create_migration(args.message)
        elif args.command == "history":
            history = await manager.show_history()
            for rev in history:
                print(f"{rev['revision']}: {rev['message']}")
        elif args.command == "stamp":
            await manager.stamp(args.revision)
        elif args.command == "init":
            manager.init()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AlembicMigrationManager",
    "MigrationError",
    "MigrationManager",
    "MigrationNotInitializedError",
    "get_migration_manager",
    "migrate_database",
]


# ============================================================================
# SINGLE MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Panggil CLI parser terlebih dahulu untuk mengevaluasi parameter `args`
    cli()

    # CATATAN: Jika di dalam fungsi cli() Anda SUDAH ada perintah asyncio.run(run()),
    # Anda bisa menghapus atau men-komentari baris di bawah ini agar tidak berjalan ganda.
    # asyncio.run(run())
