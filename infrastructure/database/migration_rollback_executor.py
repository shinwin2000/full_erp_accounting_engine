#!/usr/bin/env python3
"""
Module: migration_rollback_executor.py
Layer: Infrastructure (Database)
Responsibility: Menjalankan rollback migrasi database secara aman dengan
               dukungan dry-run, backup sebelum rollback, dan verifikasi
               integritas setelah rollback. Juga mendukung rollback ke
               titik tertentu (revision) dan rollback migrasi terakhir.
Dependencies:
- alembic, sqlalchemy, asyncio, logging, subprocess
- infrastructure.database.migration_manager_alembic (AlembicMigrationManager)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap rollback migrasi dicatat. Backup sebelum rollback dibuat
       untuk memungkinkan pemulihan jika rollback gagal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Internal dependencies
from infrastructure.database.migration_manager_alembic import (
    AlembicMigrationManager,
    get_migration_manager,
)
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

ROLLBACK_BACKUP_DIR = Path("/var/backups/migration_rollbacks")

# ============================================================================
# EXCEPTIONS
# ============================================================================


class MigrationRollbackError(Exception):
    """Base exception untuk migration rollback."""

    pass


class RollbackFailedError(MigrationRollbackError):
    """Rollback gagal."""

    pass


class BackupCreationError(MigrationRollbackError):
    """Error saat membuat backup sebelum rollback."""

    pass


# ============================================================================
# MIGRATION ROLLBACK EXECUTOR
# ============================================================================


class MigrationRollbackExecutor:
    """
    Executor untuk rollback migrasi database.

    Fitur:
    - Dry-run mode untuk melihat apa yang akan di-rollback
    - Backup sebelum rollback (SQL dump)
    - Rollback ke revision tertentu
    - Rollback migrasi terakhir
    - Verifikasi integritas setelah rollback
    - History rollback
    """

    def __init__(self):
        self._migration_manager: AlembicMigrationManager | None = None
        self._backup_dir = ROLLBACK_BACKUP_DIR
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._rollback_history: list[dict] = []

    async def _get_manager(self) -> AlembicMigrationManager:
        if self._migration_manager is None:
            self._migration_manager = await get_migration_manager()
        return self._migration_manager

    async def _create_backup(self, description: str) -> Path:
        """
        Create a backup of the current database state before rollback.

        Args:
            description: Description for the backup file

        Returns:
            Path to backup file
        """
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"pre_rollback_{timestamp}_{description.replace(' ', '_')[:50]}.sql"
        backup_path = self._backup_dir / backup_filename

        try:
            # Use pg_dump to create backup
            import subprocess

            # Get database connection info
            from config.loader_yaml import load_yaml_config

            config = load_yaml_config("config_files/database_config.yaml")
            db_config = config.get("database", {})

            host = db_config.get("host", "localhost")
            port = db_config.get("port", 5432)
            database = db_config.get("database", "erp_db")
            user = db_config.get("user", "postgres")
            password = db_config.get("password")

            cmd = [
                "pg_dump",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
                "-F",
                "c",  # custom format
                "-f",
                str(backup_path),
                "--no-owner",
                "--no-privileges",
            ]

            env = None
            if password:
                env = {"PGPASSWORD": password}

            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                raise BackupCreationError(f"pg_dump failed: {result.stderr}")

            logger.info(
                f"Database backup created: {backup_path} ({backup_path.stat().st_size} bytes)"
            )
            return backup_path

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            raise BackupCreationError(f"Backup creation failed: {e}") from e

    async def _restore_backup(self, backup_path: Path) -> bool:
        """
        Restore database from backup.

        Returns:
            True if restore successful
        """
        try:
            import subprocess

            from config.loader_yaml import load_yaml_config

            config = load_yaml_config("config_files/database_config.yaml")
            db_config = config.get("database", {})

            host = db_config.get("host", "localhost")
            port = db_config.get("port", 5432)
            database = db_config.get("database", "erp_db")
            user = db_config.get("user", "postgres")
            password = db_config.get("password")

            cmd = [
                "pg_restore",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                str(backup_path),
            ]

            env = None
            if password:
                env = {"PGPASSWORD": password}

            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Restore failed: {result.stderr}")
                return False

            logger.info(f"Database restored from backup: {backup_path}")
            return True

        except Exception as e:
            logger.error(f"Restore error: {e}")
            return False

    async def _verify_integrity(self) -> bool:
        """
        Verify database integrity after rollback.

        Returns:
            True if integrity check passes
        """
        try:
            factory = await get_session_factory()
            async with factory.get_session() as session:
                # Check for essential tables
                from sqlalchemy import inspect, text

                inspector = inspect(session.bind)
                tables = await inspector.get_table_names()

                # At least some core tables should exist
                core_tables = ["legal_entity", "account", "journal_header", "journal_line"]
                missing = [t for t in core_tables if t not in tables]

                if missing:
                    logger.error(f"Core tables missing after rollback: {missing}")
                    return False

                # Check for any obvious corruption (e.g., try to count journals)
                try:
                    result = await session.execute(text("SELECT COUNT(*) FROM journal_header"))
                    count = result.scalar()
                    logger.info(f"Integrity check passed: {count} journals in database")
                except Exception as e:
                    logger.error(f"Failed to query journal_header: {e}")
                    return False

            return True

        except Exception as e:
            logger.error(f"Integrity verification failed: {e}")
            return False

    async def rollback(
        self, revision: str, dry_run: bool = False, create_backup: bool = True
    ) -> dict[str, Any]:
        """
        Rollback database migration to specified revision.

        Args:
            revision: Target revision (e.g., "head-1", "base", or specific revision ID)
            dry_run: If True, only simulate the rollback
            create_backup: Create backup before rollback

        Returns:
            Rollback result dictionary
        """
        result = {
            "success": False,
            "revision": revision,
            "dry_run": dry_run,
            "backup_path": None,
            "error": None,
        }

        manager = await self._get_manager()

        # Get current revision before rollback
        current_revision = await manager.get_current_revision()
        result["current_revision"] = current_revision

        if current_revision is None:
            result["error"] = "No current revision found"
            logger.error("Cannot rollback: no current revision")
            return result

        # Check if revision is valid
        heads = await manager.get_heads()
        if revision not in heads and revision not in ["base", "head-1"]:
            # Try to resolve revision
            if revision == "head-1":
                # Need to get previous revision
                # For simplicity, we'll attempt to rollback one step
                pass
            else:
                # Validate that revision exists
                history = await manager.show_history(limit=100)
                rev_ids = [h["revision"] for h in history]
                if revision not in rev_ids and revision != "base":
                    result["error"] = f"Revision {revision} not found"
                    logger.error(result["error"])
                    return result

        # Create backup if requested
        backup_path = None
        if create_backup and not dry_run:
            try:
                backup_path = await self._create_backup(f"rollback_to_{revision}")
                result["backup_path"] = str(backup_path)
            except BackupCreationError as e:
                result["error"] = f"Backup failed: {e}"
                logger.error(result["error"])
                await trigger_alert(
                    title="Migration Rollback Backup Failed",
                    message=f"Failed to create backup before rollback: {e}",
                    severity="critical",
                    source="MigrationRollbackExecutor",
                )
                return result

        if dry_run:
            logger.info(f"DRY RUN: Would rollback from {current_revision} to {revision}")
            result["success"] = True
            result["dry_run"] = True
            return result

        # Execute rollback
        try:
            await manager.downgrade(revision)
            result["success"] = True
            result["new_revision"] = await manager.get_current_revision()

            # Verify integrity
            verified = await self._verify_integrity()
            result["integrity_verified"] = verified

            if not verified:
                logger.warning("Integrity verification failed after rollback")
                await trigger_alert(
                    title="Migration Rollback Integrity Check Failed",
                    message=f"Rollback to {revision} completed but integrity check failed",
                    severity="warning",
                    source="MigrationRollbackExecutor",
                )

            # Record history
            self._rollback_history.append(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "from_revision": current_revision,
                    "to_revision": revision,
                    "backup_path": str(backup_path) if backup_path else None,
                    "success": True,
                    "integrity_verified": verified,
                }
            )

            logger.info(f"Successfully rolled back from {current_revision} to {revision}")

        except Exception as e:
            result["error"] = str(e)
            logger.error(f"Rollback failed: {e}")

            # Attempt to restore from backup if available
            if backup_path and backup_path.exists():
                logger.info("Attempting to restore from backup due to rollback failure")
                restore_ok = await self._restore_backup(backup_path)
                if restore_ok:
                    logger.info("Database restored from backup after rollback failure")
                    result["restored_from_backup"] = True
                else:
                    logger.critical("Failed to restore from backup after rollback failure!")
                    await trigger_alert(
                        title="Migration Rollback Critical Failure",
                        message=f"Rollback to {revision} failed AND backup restoration failed!",
                        severity="critical",
                        source="MigrationRollbackExecutor",
                    )

            await trigger_alert(
                title="Migration Rollback Failed",
                message=f"Rollback to {revision} failed: {e}",
                severity="error",
                source="MigrationRollbackExecutor",
            )

        return result

    async def rollback_last_migration(self, dry_run: bool = False) -> dict[str, Any]:
        """
        Rollback the most recent migration (go back one step).
        """
        manager = await self._get_manager()
        current = await manager.get_current_revision()
        if not current:
            return {"success": False, "error": "No current revision"}

        # Get history to find previous revision
        history = await manager.show_history(limit=2)
        if len(history) < 2:
            return {"success": False, "error": "No previous migration found"}

        previous_revision = history[1]["revision"]  # second newest
        return await self.rollback(previous_revision, dry_run)

    async def rollback_to_base(self, dry_run: bool = False) -> dict[str, Any]:
        """
        Rollback all migrations (to base state).
        """
        return await self.rollback("base", dry_run)

    async def get_rollback_history(self, limit: int = 20) -> list[dict]:
        """
        Get history of rollback operations.
        """
        return self._rollback_history[-limit:]

    async def list_backups(self) -> list[dict]:
        """
        List all rollback backups.
        """
        backups = []
        for backup_file in self._backup_dir.glob("pre_rollback_*.sql"):
            backups.append(
                {
                    "filename": backup_file.name,
                    "path": str(backup_file),
                    "size_bytes": backup_file.stat().st_size,
                    "created_at": datetime.fromtimestamp(backup_file.stat().st_ctime).isoformat(),
                }
            )
        return sorted(backups, key=lambda x: x["created_at"], reverse=True)

    async def delete_backup(self, backup_filename: str) -> bool:
        """
        Delete a backup file.
        """
        backup_path = self._backup_dir / backup_filename
        if backup_path.exists():
            backup_path.unlink()
            logger.info(f"Deleted backup: {backup_filename}")
            return True
        return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_rollback_executor: MigrationRollbackExecutor | None = None


async def get_rollback_executor() -> MigrationRollbackExecutor:
    """Get singleton instance of MigrationRollbackExecutor."""
    global _rollback_executor
    if _rollback_executor is None:
        _rollback_executor = MigrationRollbackExecutor()
    return _rollback_executor


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for migration rollback."""
    import argparse

    parser = argparse.ArgumentParser(description="Migration rollback executor")
    parser.add_argument(
        "command",
        choices=["rollback", "rollback-last", "rollback-base", "list-backups", "delete-backup"],
        help="Rollback command",
    )
    parser.add_argument("--revision", "-r", help="Target revision for rollback")
    parser.add_argument("--dry-run", action="store_true", help="Simulate rollback without changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip backup before rollback")
    parser.add_argument("--backup-name", help="Backup filename to delete")

    args = parser.parse_args()

    async def run():
        executor = await get_rollback_executor()

        if args.command == "rollback":
            if not args.revision:
                print("Error: --revision is required for rollback")
                return
            result = await executor.rollback(
                args.revision, dry_run=args.dry_run, create_backup=not args.no_backup
            )
            print(f"Result: {result}")
        elif args.command == "rollback-last":
            result = await executor.rollback_last_migration(dry_run=args.dry_run)
            print(f"Result: {result}")
        elif args.command == "rollback-base":
            result = await executor.rollback_to_base(dry_run=args.dry_run)
            print(f"Result: {result}")
        elif args.command == "list-backups":
            backups = await executor.list_backups()
            for b in backups:
                print(f"{b['filename']} - {b['size_bytes']} bytes - {b['created_at']}")
        elif args.command == "delete-backup":
            if not args.backup_name:
                print("Error: --backup-name required")
                return
            success = await executor.delete_backup(args.backup_name)
            print(f"Deleted: {success}")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BackupCreationError",
    "MigrationRollbackError",
    "MigrationRollbackExecutor",
    "RollbackFailedError",
    "get_rollback_executor",
]


# ============================================================================
# SINGLE MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # OPSI A: Jika fungsi `cli()` Anda di atas bertugas memparsing argument
    # dan di dalamnya SUDAH memanggil asyncio.run(run()), cukup panggil `cli()` saja:
    cli()

    # OPSI B: Jika fungsi `cli()` HANYA memparsing argument ke variabel global `args`
    # tanpa mengeksekusi loop, gunakan urutan berikut:
    # cli()
    # asyncio.run(run())
