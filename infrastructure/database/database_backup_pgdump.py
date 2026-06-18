#!/usr/bin/env python3
"""
Module: database_backup_pgdump.py
Layer: Infrastructure (Database)
Responsibility: Mengelola backup database menggunakan pg_dump. Mendukung full backup,
               scheduled backup, kompresi, enkripsi, upload ke cloud storage (S3/Glacier),
               dan manajemen retensi backup. Juga menyediakan fungsi restore untuk
               disaster recovery.
Dependencies:
- subprocess, asyncio, logging, datetime
- config.loader_yaml
- infrastructure.file_storage.s3_adapter (optional)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Setiap backup dan restore dicatat. Gagal backup memicu alert.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

# Optional file storage
try:
    from infrastructure.file_storage.glacier_cold_storage_adapter import (
        get_glacier_cold_storage_adapter,
    )
    from infrastructure.file_storage.s3_adapter import get_s3_storage_adapter

    FILE_STORAGE_AVAILABLE = True
except ImportError:
    FILE_STORAGE_AVAILABLE = False

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_BACKUP_CONFIG = {
    "enabled": True,
    "backup_dir": "/var/backups/postgres",
    "retention_days": 30,
    "backup_schedule": "0 2 * * *",  # Daily at 2 AM
    "compress": True,
    "encrypt": False,
    "encryption_key": None,
    "upload_to_s3": False,
    "s3_bucket": "erp-database-backup",
    "s3_prefix": "backups/",
    "upload_to_glacier": False,
    "glacier_vault": "erp-database-archive",
    "glacier_archive_days": 90,
    "parallel_jobs": 4,
    "blobs": True,
    "format": "custom",  # custom, directory, tar
}

BACKUP_FORMATS = ["custom", "directory", "tar"]
COMPRESSION_FORMATS = ["gzip", "zstd", "none"]

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DatabaseBackupError(Exception):
    """Base exception untuk database backup."""

    pass


class BackupCreateError(DatabaseBackupError):
    """Error saat membuat backup."""

    pass


class BackupRestoreError(DatabaseBackupError):
    """Error saat restore backup."""

    pass


class BackupNotFoundError(DatabaseBackupError):
    """Backup tidak ditemukan."""

    pass


# ============================================================================
# BACKUP MANAGER
# ============================================================================


class DatabaseBackupPgDump:
    """
    Manajer backup database menggunakan pg_dump.

    Fitur:
    - Full database backup
    - Scheduled backup (cron)
    - Kompresi (gzip, zstd)
    - Enkripsi (AES-256, opsional)
    - Upload ke S3/Glacier
    - Manajemen retensi backup
    - Restore dari backup
    - Verifikasi integritas backup
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._backup_dir = Path(self.config.get("backup_dir", "/var/backups/postgres"))
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self._retention_days = self.config.get("retention_days", 30)
        self._enabled = self.config.get("enabled", True)
        self._backup_task: asyncio.Task | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            backup_config = config.get("backup", {})
            result = DEFAULT_BACKUP_CONFIG.copy()
            result.update(backup_config)
            return result
        except Exception:
            return DEFAULT_BACKUP_CONFIG.copy()

    async def _get_db_connection_info(self) -> dict:
        """Get database connection info from config."""
        config = load_yaml_config("config_files/database_config.yaml")
        db_config = config.get("database", {})
        return {
            "host": db_config.get("host", "localhost"),
            "port": db_config.get("port", 5432),
            "database": db_config.get("database", "erp_db"),
            "user": db_config.get("user", "postgres"),
            "password": db_config.get("password"),
        }

    async def _compute_checksum(self, file_path: Path) -> str:
        """Compute SHA-256 checksum of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    async def create_backup(
        self, backup_name: str | None = None, description: str | None = None
    ) -> dict[str, Any]:
        """
        Create a full database backup.
        """
        if not self._enabled:
            logger.info("Database backup is disabled")
            return {"success": False, "error": "Backup disabled"}

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        if backup_name is None:
            backup_name = f"full_backup_{timestamp}"

        db_info = await self._get_db_connection_info()
        backup_file = self._backup_dir / f"{backup_name}.dump"

        logger.info(f"Starting database backup to {backup_file}")

        try:
            # Build pg_dump command
            cmd = [
                "pg_dump",
                "-h",
                db_info["host"],
                "-p",
                str(db_info["port"]),
                "-U",
                db_info["user"],
                "-d",
                db_info["database"],
                "-F",
                self.config.get("format", "custom"),
                "-f",
                str(backup_file),
                "--no-owner",
                "--no-privileges",
            ]

            # Add parallel jobs if format is directory
            if self.config.get("format") == "directory":
                cmd.extend(["-j", str(self.config.get("parallel_jobs", 4))])

            # Add blobs if needed
            if self.config.get("blobs", True):
                cmd.append("--blobs")

            env = None
            if db_info.get("password"):
                env = {"PGPASSWORD": db_info["password"]}

            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise BackupCreateError(f"pg_dump failed: {stderr.decode()}")

            # Get file size
            file_size = backup_file.stat().st_size

            # Compute checksum
            checksum = await self._compute_checksum(backup_file)

            # Compress if enabled
            compressed_path = None
            if self.config.get("compress", True):
                compressed_path = await self._compress_backup(backup_file)
                if compressed_path != backup_file:
                    backup_file.unlink()
                    backup_file = compressed_path
                    file_size = backup_file.stat().st_size

            # Upload to cloud storage if enabled
            cloud_uri = None
            if self.config.get("upload_to_s3", False) and FILE_STORAGE_AVAILABLE:
                cloud_uri = await self._upload_to_s3(backup_file, backup_name)
            elif self.config.get("upload_to_glacier", False) and FILE_STORAGE_AVAILABLE:
                cloud_uri = await self._upload_to_glacier(backup_file, backup_name)

            # Create metadata
            metadata = {
                "success": True,
                "backup_name": backup_name,
                "backup_file": str(backup_file),
                "created_at": datetime.now(UTC).isoformat(),
                "size_bytes": file_size,
                "checksum": checksum,
                "format": self.config.get("format", "custom"),
                "compressed": self.config.get("compress", True),
                "cloud_uri": cloud_uri,
                "description": description,
            }

            # Save metadata
            metadata_file = backup_file.with_suffix(".metadata.json")
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"Backup completed: {backup_name} ({file_size / 1024 / 1024:.2f} MB)")

            # Clean old backups
            await self.cleanup_old_backups()

            return metadata

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            await trigger_alert(
                title="Database Backup Failed",
                message=f"Backup {backup_name} failed: {e}",
                severity="error",
                source="DatabaseBackupPgDump",
            )
            raise BackupCreateError(f"Backup failed: {e}") from e

    async def _compress_backup(self, backup_file: Path) -> Path:
        """Compress backup file using gzip."""
        compressed_file = backup_file.with_suffix(backup_file.suffix + ".gz")
        logger.info(f"Compressing backup: {backup_file} -> {compressed_file}")

        with open(backup_file, "rb") as f_in:
            with gzip.open(compressed_file, "wb", compresslevel=6) as f_out:
                shutil.copyfileobj(f_in, f_out)

        return compressed_file

    async def _upload_to_s3(self, backup_file: Path, backup_name: str) -> str:
        """Upload backup to S3."""
        s3 = await get_s3_storage_adapter()
        s3_key = f"{self.config.get('s3_prefix', 'backups/')}{backup_name}.dump.gz"
        uri = await s3.upload(
            file_content=open(backup_file, "rb"),
            file_name=backup_file.name,
            bucket=self.config.get("s3_bucket", "erp-database-backup"),
        )
        logger.info(f"Backup uploaded to S3: {uri}")
        return uri

    async def _upload_to_glacier(self, backup_file: Path, backup_name: str) -> str:
        """Upload backup to Glacier."""
        glacier = await get_glacier_cold_storage_adapter()
        uri = await glacier.upload(
            file_content=open(backup_file, "rb"),
            file_name=backup_file.name,
            description=f"Database backup: {backup_name}",
        )
        logger.info(f"Backup uploaded to Glacier: {uri}")
        return uri

    async def restore_backup(self, backup_name: str, target_database: str | None = None) -> bool:
        """Restore database from backup."""
        db_info = await self._get_db_connection_info()
        target_db = target_database or db_info["database"]

        backup_file = self._backup_dir / f"{backup_name}.dump"
        if not backup_file.exists():
            backup_file = self._backup_dir / f"{backup_name}.dump.gz"
            if not backup_file.exists():
                if self.config.get("upload_to_s3", False):
                    backup_file = await self._download_from_s3(backup_name)

        if not backup_file or not backup_file.exists():
            raise BackupNotFoundError(f"Backup {backup_name} not found")

        if backup_file.suffix == ".gz":
            decompressed_file = backup_file.with_suffix("")
            with gzip.open(backup_file, "rb") as f_in:
                with open(decompressed_file, "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            backup_file = decompressed_file

        logger.info(f"Restoring database from {backup_file}")

        try:
            cmd = [
                "pg_restore",
                "-h",
                db_info["host"],
                "-p",
                str(db_info["port"]),
                "-U",
                db_info["user"],
                "-d",
                target_db,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                str(backup_file),
            ]

            env = None
            if db_info.get("password"):
                env = {"PGPASSWORD": db_info["password"]}

            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise BackupRestoreError(f"pg_restore failed: {stderr.decode()}")

            logger.info(f"Database restored successfully from {backup_name}")

            if backup_file != self._backup_dir / f"{backup_name}.dump":
                backup_file.unlink()

            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            await trigger_alert(
                title="Database Restore Failed",
                message=f"Restore from {backup_name} failed: {e}",
                severity="critical",
                source="DatabaseBackupPgDump",
            )
            raise BackupRestoreError(f"Restore failed: {e}") from e

    async def _download_from_s3(self, backup_name: str) -> Path:
        """Download backup from S3."""
        s3 = await get_s3_storage_adapter()
        s3_key = f"{self.config.get('s3_prefix', 'backups/')}{backup_name}.dump.gz"
        local_path = self._backup_dir / f"{backup_name}.dump.gz"
        logger.info(f"Downloading backup from S3: {s3_key}")
        return local_path

    async def list_backups(self) -> list[dict[str, Any]]:
        """List all available backups."""
        backups = []
        for file_path in self._backup_dir.glob("*.dump*"):
            metadata_file = file_path.with_suffix(".metadata.json")
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                backups.append(metadata)
            else:
                backups.append(
                    {
                        "backup_name": file_path.stem,
                        "backup_file": str(file_path),
                        "size_bytes": file_path.stat().st_size,
                        "created_at": datetime.fromtimestamp(file_path.stat().st_ctime).isoformat(),
                    }
                )

        backups.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return backups

    async def cleanup_old_backups(self) -> int:
        """Delete backups older than retention period."""
        cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
        deleted = 0

        for file_path in self._backup_dir.glob("*.dump*"):
            metadata_file = file_path.with_suffix(".metadata.json")
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                created_at = datetime.fromisoformat(metadata.get("created_at", "2000-01-01"))
            else:
                created_at = datetime.fromtimestamp(file_path.stat().st_ctime)

            if created_at < cutoff:
                file_path.unlink(missing_ok=True)
                metadata_file.unlink(missing_ok=True)
                deleted += 1
                logger.info(f"Deleted old backup: {file_path.name}")

        return deleted

    async def verify_backup(self, backup_name: str) -> bool:
        """Verify backup integrity."""
        try:
            backup_file = self._backup_dir / f"{backup_name}.dump"
            if not backup_file.exists():
                backup_file = self._backup_dir / f"{backup_name}.dump.gz"

            if not backup_file.exists():
                raise BackupNotFoundError(f"Backup {backup_name} not found")

            metadata_file = backup_file.with_suffix(".metadata.json")
            if metadata_file.exists():
                with open(metadata_file) as f:
                    metadata = json.load(f)
                expected_checksum = metadata.get("checksum")
                if expected_checksum:
                    actual_checksum = await self._compute_checksum(backup_file)
                    if actual_checksum != expected_checksum:
                        logger.error(f"Backup {backup_name} checksum mismatch")
                        return False

            db_info = await self._get_db_connection_info()
            cmd = ["pg_restore", "--list", str(backup_file)]

            env = None
            if db_info.get("password"):
                env = {"PGPASSWORD": db_info["password"]}

            process = await asyncio.create_subprocess_exec(
                *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            return process.returncode == 0

        except Exception as e:
            logger.error(f"Backup verification failed: {e}")
            return False

    async def start_scheduled_backup(self) -> None:
        """Start scheduled backup based on cron schedule."""
        if self._backup_task is not None:
            logger.warning("Scheduled backup already running")
            return

        async def _backup_loop():
            while True:
                try:
                    await self.create_backup(description="Scheduled daily backup")
                    await asyncio.sleep(86400)
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Scheduled backup error: {e}")
                    await asyncio.sleep(3600)

        self._backup_task = asyncio.create_task(_backup_loop())
        logger.info("Scheduled database backup started (daily)")

    async def stop_scheduled_backup(self) -> None:
        """Stop scheduled backup."""
        if self._backup_task:
            self._backup_task.cancel()
            self._backup_task = None
            logger.info("Scheduled database backup stopped")

    async def get_stats(self) -> dict[str, Any]:
        """Get backup statistics."""
        backups = await self.list_backups()
        total_size = sum(b.get("size_bytes", 0) for b in backups)

        return {
            "enabled": self._enabled,
            "backup_dir": str(self._backup_dir),
            "retention_days": self._retention_days,
            "total_backups": len(backups),
            "total_size_bytes": total_size,
            "total_size_mb": total_size / 1024 / 1024,
            "latest_backup": backups[0] if backups else None,
            "backup_schedule": self.config.get("backup_schedule"),
            "upload_to_s3": self.config.get("upload_to_s3", False),
            "upload_to_glacier": self.config.get("upload_to_glacier", False),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_backup_manager: DatabaseBackupPgDump | None = None


async def get_backup_manager() -> DatabaseBackupPgDump:
    """Get singleton instance of DatabaseBackupPgDump."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = DatabaseBackupPgDump()
    return _backup_manager


# ============================================================================
# CLI COMMAND
# ============================================================================


def cli():
    """CLI entry point for database backup (Parsing Only)."""
    import argparse

    parser = argparse.ArgumentParser(description="Database backup manager")
    parser.add_argument(
        "command", choices=["backup", "restore", "list", "cleanup", "verify"], help="Backup command"
    )
    parser.add_argument("--name", "-n", help="Backup name")
    parser.add_argument("--target-db", help="Target database for restore")

    return parser.parse_args()


async def run_backup_cli(args):
    """Menjalankan operasi backup secara asynchronous berdasarkan argumen CLI."""
    manager = await get_backup_manager()

    if args.command == "backup":
        result = await manager.create_backup(backup_name=args.name)
        print(f"Backup created: {result['backup_name']} ({result['size_bytes']} bytes)")
    elif args.command == "restore":
        if not args.name:
            print("Error: --name required for restore")
            return
        success = await manager.restore_backup(args.name, args.target_db)
        print(f"Restore {'successful' if success else 'failed'}")
    elif args.command == "list":
        backups = await manager.list_backups()
        for b in backups:
            print(f"{b['backup_name']} - {b['size_bytes']} bytes - {b['created_at']}")
    elif args.command == "cleanup":
        deleted = await manager.cleanup_old_backups()
        print(f"Deleted {deleted} old backups")
    elif args.command == "verify":
        if not args.name:
            print("Error: --name required for verify")
            return
        valid = await manager.verify_backup(args.name)
        print(f"Backup verification: {'PASSED' if valid else 'FAILED'}")


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BackupCreateError",
    "BackupNotFoundError",
    "BackupRestoreError",
    "DatabaseBackupError",
    "DatabaseBackupPgDump",
    "get_backup_manager",
]


# ============================================================================
# SINGLE MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # 1. Parsing argumen secara sinkronus
    args = cli()

    # 2. Eksekusi event loop utama HANYA ketika file dijalankan langsung via terminal.
    #    Menggunakan thread offloading jika event loop lain sudah berjalan untuk menghindari RuntimeError.
    try:
        asyncio.get_running_loop()

        # Deteksi loop aktif: alihkan coroutine CLI ke thread terisolasi dengan loop-nya sendiri
        def _run_in_thread():
            thread_loop = asyncio.new_event_loop()
            try:
                thread_loop.run_until_complete(run_backup_cli(args))
            finally:
                thread_loop.close()

        worker = threading.Thread(target=_run_in_thread, name="BackupCLIEngineWorker")
        worker.start()
        worker.join()  # Blokir thread saat ini hingga eksekusi CLI selesai sempurna

    except RuntimeError:
        # Tidak ada event loop aktif, aman untuk memutar loop utama secara langsung
        asyncio.run(run_backup_cli(args))