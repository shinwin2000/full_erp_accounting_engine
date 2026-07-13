#!/usr/bin/env python3
"""
Module: event_store_backup_archiver.py
Layer: Infrastructure (Event Store)
Responsibility: Mengelola backup dan archive dari event store untuk disaster recovery,
               compliance, dan long-term retention. Mendukung full backup,
               incremental backup (based on WAL), dan archive ke cold storage (S3/Glacier).
               Juga menyediakan mekanisme restore point-in-time (PITR) dan verifikasi
               integritas backup.
Dependencies:
- asyncio, subprocess, shutil, pathlib, logging, datetime
- infrastructure.file_storage.s3_adapter (S3FileStorageAdapter)
- infrastructure.file_storage.glacier_cold_storage_adapter
- infrastructure.database.connection_pool_asyncpg (untuk pg_dump)
- infrastructure.telemetry.alert_manager_router
- config.loader_yaml
Audit: Setiap backup dan archive dicatat. Restore juga diaudit.
       Backup integrity di-verify secara periodik.
"""

from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aiofiles

from config.loader_yaml import load_yaml_config
from infrastructure.file_storage.glacier_cold_storage_adapter import GlacierColdStorageAdapter

# Internal dependencies
from infrastructure.file_storage.s3_adapter import S3FileStorageAdapter
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

BACKUP_CONFIG_PATH = "config_files/backup_config.yaml"
DEFAULT_BACKUP_DIR = Path("/var/backups/eventstore")
DEFAULT_RETENTION_DAYS = 30
DEFAULT_ARCHIVE_AFTER_DAYS = 7

BACKUP_TYPE_FULL = "full"
BACKUP_TYPE_INCREMENTAL = "incremental"
BACKUP_TYPE_WAL = "wal"

BACKUP_STATUS_PENDING = "pending"
BACKUP_STATUS_RUNNING = "running"
BACKUP_STATUS_SUCCESS = "success"
BACKUP_STATUS_FAILED = "failed"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class BackupArchiverError(Exception):
    pass


class BackupNotFoundError(BackupArchiverError):
    pass


class RestoreError(BackupArchiverError):
    pass


class VerificationError(BackupArchiverError):
    pass


# ============================================================================
# BACKUP METADATA
# ============================================================================


class BackupMetadata:
    __slots__ = (
        "backup_id",
        "backup_type",
        "checksum",
        "completed_at",
        "error_message",
        "file_path",
        "size_bytes",
        "started_at",
        "status",
        "wal_end_lsn",
        "wal_start_lsn",
    )

    def __init__(self, backup_id: UUID, backup_type: str, started_at: datetime):
        self.backup_id = backup_id
        self.backup_type = backup_type
        self.started_at = started_at
        self.completed_at: datetime | None = None
        self.size_bytes: int = 0
        self.file_path: str | None = None
        self.checksum: str | None = None
        self.wal_start_lsn: str | None = None
        self.wal_end_lsn: str | None = None
        self.status: str = BACKUP_STATUS_PENDING
        self.error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": str(self.backup_id),
            "backup_type": self.backup_type,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "size_bytes": self.size_bytes,
            "file_path": self.file_path,
            "checksum": self.checksum,
            "wal_start_lsn": self.wal_start_lsn,
            "wal_end_lsn": self.wal_end_lsn,
            "status": self.status,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupMetadata:
        bm = cls(
            backup_id=UUID(data["backup_id"]),
            backup_type=data["backup_type"],
            started_at=datetime.fromisoformat(data["started_at"]),
        )
        if data.get("completed_at"):
            bm.completed_at = datetime.fromisoformat(data["completed_at"])
        bm.size_bytes = data.get("size_bytes", 0)
        bm.file_path = data.get("file_path")
        bm.checksum = data.get("checksum")
        bm.wal_start_lsn = data.get("wal_start_lsn")
        bm.wal_end_lsn = data.get("wal_end_lsn")
        bm.status = data.get("status", BACKUP_STATUS_PENDING)
        bm.error_message = data.get("error_message")
        return bm


# ============================================================================
# BACKUP ARCHIVER
# ============================================================================


class EventStoreBackupArchiver:
    def __init__(self, config_path: str = BACKUP_CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.backup_dir = Path(self.config.get("backup_dir", DEFAULT_BACKUP_DIR))
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.s3_storage: S3FileStorageAdapter | None = None
        self.glacier_storage: GlacierColdStorageAdapter | None = None
        self._init_storage()

        self._backups: dict[UUID, BackupMetadata] = {}
        self._running_backup: UUID | None = None

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {
                "backup_dir": "/var/backups/eventstore",
                "retention_days": 30,
                "archive_after_days": 7,
                "s3_bucket": "erp-eventstore-backup",
                "glacier_vault": "erp-archive",
                "database_name": "erp_db",
                "database_user": "postgres",
            }

    def _init_storage(self):
        try:
            bucket = self.config.get("s3_bucket", "erp-eventstore-backup")
            self.s3_storage = S3FileStorageAdapter(bucket_name=bucket)
            logger.info(f"S3 storage initialized for bucket {bucket}")
        except Exception as e:
            logger.warning(f"Failed to initialize S3 storage: {e}")

        try:
            vault = self.config.get("glacier_vault", "erp-archive")
            self.glacier_storage = GlacierColdStorageAdapter(vault_name=vault)
            logger.info(f"Glacier storage initialized for vault {vault}")
        except Exception as e:
            logger.warning(f"Failed to initialize Glacier storage: {e}")

    # ========================================================================
    # PERBAIKAN: compress dan decompress dengan aiofiles + asyncio.to_thread
    # ========================================================================

    async def _compress_file(self, src_path: Path, dst_path: Path) -> None:
        """Compress file using gzip."""
        async with aiofiles.open(src_path, "rb") as f:
            data = await f.read()
        compressed_data = await asyncio.to_thread(lambda: gzip.compress(data, compresslevel=6))
        async with aiofiles.open(dst_path, "wb") as f:
            await f.write(compressed_data)
        logger.debug(f"Compressed {src_path} to {dst_path}")

    async def _decompress_file(self, src_path: Path, dst_path: Path) -> None:
        """Decompress gzip file."""
        async with aiofiles.open(src_path, "rb") as f:
            data = await f.read()
        decompressed_data = await asyncio.to_thread(lambda: gzip.decompress(data))
        async with aiofiles.open(dst_path, "wb") as f:
            await f.write(decompressed_data)
        logger.debug(f"Decompressed {src_path} to {dst_path}")

    async def _compute_file_checksum(self, file_path: Path) -> str:
        sha256 = hashlib.sha256()
        async with aiofiles.open(file_path, "rb") as f:
            while True:
                chunk = await f.read(65536)
                if not chunk:
                    break
                sha256.update(chunk)
        return sha256.hexdigest()

    async def _delete_file(self, file_path: Path, ignore_missing: bool = True) -> None:
        def _delete_sync():
            if ignore_missing:
                file_path.unlink(missing_ok=True)
            else:
                file_path.unlink()
        await asyncio.to_thread(_delete_sync)

    # ========================================================================
    # BACKUP CREATION
    # ========================================================================

    async def create_full_backup(self) -> BackupMetadata:
        backup_id = uuid4()
        backup = BackupMetadata(backup_id, BACKUP_TYPE_FULL, datetime.now(UTC))
        backup.status = BACKUP_STATUS_RUNNING
        self._backups[backup_id] = backup
        self._running_backup = backup_id

        logger.info(f"Starting full backup {backup_id}")

        try:
            with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
                dump_path = Path(tmp.name)

            db_name = self.config.get("database_name", "erp_db")
            db_user = self.config.get("database_user", "postgres")
            db_host = self.config.get("database_host", "localhost")
            db_port = self.config.get("database_port", 5432)

            cmd = [
                "pg_dump",
                "-h",
                db_host,
                "-p",
                str(db_port),
                "-U",
                db_user,
                "-d",
                db_name,
                "-F",
                "c",
                "-f",
                str(dump_path),
                "--no-owner",
                "--no-privileges",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise BackupArchiverError(f"pg_dump failed: {stderr.decode()}")

            compressed_path = self.backup_dir / f"full_{backup_id}.sql.gz"
            await self._compress_file(dump_path, compressed_path)

            checksum = await self._compute_file_checksum(compressed_path)
            size_bytes = compressed_path.stat().st_size

            backup.completed_at = datetime.now(UTC)
            backup.size_bytes = size_bytes
            backup.file_path = str(compressed_path)
            backup.checksum = checksum
            backup.status = BACKUP_STATUS_SUCCESS

            if self.s3_storage:
                s3_key = f"backups/full_{backup_id}.sql.gz"
                async with aiofiles.open(compressed_path, "rb") as f:
                    file_content = await f.read()
                await self.s3_storage.upload(
                    file_content,
                    s3_key,
                    "application/gzip",
                    metadata={"backup_id": str(backup_id), "type": "full"},
                )
                logger.info(f"Full backup uploaded to S3: {s3_key}")

            logger.info(f"Full backup {backup_id} completed: {size_bytes / 1024 / 1024:.2f} MB")
            await self._cleanup_old_backups()

            return backup

        except Exception as e:
            backup.status = BACKUP_STATUS_FAILED
            backup.error_message = str(e)
            logger.error(f"Full backup {backup_id} failed: {e}")
            await trigger_alert(
                title="Event Store Backup Failed",
                message=f"Full backup {backup_id} failed: {e}",
                severity="critical",
                source="EventStoreBackupArchiver",
            )
            raise BackupArchiverError(f"Backup failed: {e}") from e
        finally:
            self._running_backup = None
            if "dump_path" in locals():
                await self._delete_file(dump_path, ignore_missing=True)

    async def _cleanup_old_backups(self) -> None:
        retention_days = self.config.get("retention_days", DEFAULT_RETENTION_DAYS)
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        for backup_file in self.backup_dir.glob("*.sql.gz"):
            try:
                parts = backup_file.stem.split("_")
                if len(parts) >= 2:
                    backup_id_str = parts[1]
                    backup_id = UUID(backup_id_str)
                    backup = self._backups.get(backup_id)
                    if backup and backup.completed_at and backup.completed_at < cutoff:
                        await self._delete_file(backup_file, ignore_missing=True)
                        logger.info(f"Deleted old backup: {backup_file.name}")
            except (ValueError, IndexError):
                continue

    async def archive_to_cold_storage(self, backup_id: UUID) -> bool:
        backup = await self.get_backup(backup_id)
        if not backup:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        if not self.glacier_storage:
            logger.warning("Glacier storage not configured, skipping archive")
            return False

        if not backup.file_path or not Path(backup.file_path).exists():
            return False

        try:
            archive_id = await self.glacier_storage.archive(
                Path(backup.file_path), description=f"Event store backup {backup_id}"
            )
            logger.info(f"Backup {backup_id} archived to Glacier with ID {archive_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to archive backup {backup_id}: {e}")
            return False

    async def get_backup(self, backup_id: UUID) -> BackupMetadata | None:
        if backup_id in self._backups:
            return self._backups[backup_id]

        metadata_file = self.backup_dir / f"metadata_{backup_id}.json"
        if metadata_file.exists():
            async with aiofiles.open(metadata_file) as f:
                content = await f.read()
                data = json.loads(content)
                backup = BackupMetadata.from_dict(data)
                self._backups[backup_id] = backup
                return backup
        return None

    async def restore_backup(self, backup_id: UUID, target_database: str | None = None) -> bool:
        backup = await self.get_backup(backup_id)
        if not backup or not backup.file_path:
            raise BackupNotFoundError(f"Backup {backup_id} not found or missing file")

        backup_path = Path(backup.file_path)
        if not backup_path.exists():
            if self.s3_storage:
                s3_key = f"backups/full_{backup_id}.sql.gz"
                backup_path = self.backup_dir / f"restore_{backup_id}.sql.gz"
                content = await self.s3_storage.download(s3_key)
                async with aiofiles.open(backup_path, "wb") as f:
                    await f.write(content)
            else:
                raise BackupNotFoundError(f"Backup file not found: {backup.file_path}")

        db_name = target_database or self.config.get("database_name", "erp_db")
        db_user = self.config.get("database_user", "postgres")
        db_host = self.config.get("database_host", "localhost")
        db_port = self.config.get("database_port", 5432)

        logger.info(f"Restoring backup {backup_id} to database {db_name}")

        try:
            decompressed_path = self.backup_dir / f"restore_{backup_id}.sql"
            await self._decompress_file(backup_path, decompressed_path)

            cmd = [
                "pg_restore",
                "-h",
                db_host,
                "-p",
                str(db_port),
                "-U",
                db_user,
                "-d",
                db_name,
                "--clean",
                "--if-exists",
                "--no-owner",
                "--no-privileges",
                str(decompressed_path),
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RestoreError(f"pg_restore failed: {stderr.decode()}")

            logger.info(f"Restore {backup_id} completed successfully")

            await self._delete_file(decompressed_path, ignore_missing=True)
            if backup_path != Path(backup.file_path):
                await self._delete_file(backup_path, ignore_missing=True)

            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            raise RestoreError(f"Restore failed: {e}") from e

    async def verify_backup(self, backup_id: UUID) -> bool:
        backup = await self.get_backup(backup_id)
        if not backup or not backup.file_path:
            raise BackupNotFoundError(f"Backup {backup_id} not found")

        backup_path = Path(backup.file_path)
        if not backup_path.exists():
            return False

        actual_checksum = await self._compute_file_checksum(backup_path)
        if actual_checksum != backup.checksum:
            logger.error(
                f"Backup {backup_id} checksum mismatch: expected {backup.checksum}, got {actual_checksum}"
            )
            return False

        try:
            cmd = ["pg_restore", "--list", str(backup_path)]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                logger.info(f"Backup {backup_id} verified successfully")
                return True
            else:
                logger.error(f"Backup {backup_id} verification failed: {stderr.decode()}")
                return False
        except Exception as e:
            logger.error(f"Verification error: {e}")
            return False

    async def list_backups(self) -> list[BackupMetadata]:
        backups = list(self._backups.values())

        for metadata_file in self.backup_dir.glob("metadata_*.json"):
            try:
                async with aiofiles.open(metadata_file) as f:
                    content = await f.read()
                    data = json.loads(content)
                    backup = BackupMetadata.from_dict(data)
                    if backup.backup_id not in self._backups:
                        self._backups[backup.backup_id] = backup
                        backups.append(backup)
            except Exception:
                continue

        backups.sort(key=lambda b: b.completed_at or b.started_at, reverse=True)
        return backups

    async def get_backup_stats(self) -> dict[str, Any]:
        backups = await self.list_backups()
        successful = [b for b in backups if b.status == BACKUP_STATUS_SUCCESS]

        total_size = sum(b.size_bytes for b in successful)
        latest = successful[0] if successful else None

        return {
            "total_backups": len(backups),
            "successful_backups": len(successful),
            "failed_backups": len([b for b in backups if b.status == BACKUP_STATUS_FAILED]),
            "total_size_mb": total_size / (1024 * 1024),
            "latest_backup": latest.to_dict() if latest else None,
            "backup_dir": str(self.backup_dir),
            "retention_days": self.config.get("retention_days", DEFAULT_RETENTION_DAYS),
        }

    async def cancel_running_backup(self) -> bool:
        if self._running_backup:
            backup = self._backups.get(self._running_backup)
            if backup:
                backup.status = BACKUP_STATUS_FAILED
                backup.error_message = "Cancelled by user"
                self._running_backup = None
                logger.info(f"Backup {backup.backup_id} cancelled")
                return True
        return False

    async def schedule_daily_backup(self) -> None:
        logger.info("Running scheduled daily backup")
        await self.create_full_backup()


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_backup_archiver: EventStoreBackupArchiver | None = None


async def get_backup_archiver() -> EventStoreBackupArchiver:
    global _backup_archiver
    if _backup_archiver is None:
        _backup_archiver = EventStoreBackupArchiver()
    return _backup_archiver


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BACKUP_STATUS_SUCCESS",
    "BACKUP_TYPE_FULL",
    "BACKUP_TYPE_INCREMENTAL",
    "BackupArchiverError",
    "BackupMetadata",
    "BackupNotFoundError",
    "EventStoreBackupArchiver",
    "RestoreError",
    "VerificationError",
    "get_backup_archiver",
]
