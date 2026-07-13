#!/usr/bin/env python3
"""
Module: pitr_point_in_time_recovery.py
Layer: Disaster Recovery

Responsibility:
    Point-in-Time Recovery (PITR) untuk database dan event store.
    Memungkinkan recovery ke detik tertentu sebelum kegagalan menggunakan
    base backup + WAL replay. Mendukung PostgreSQL, validasi backup,
    daftar titik restore yang tersedia, dry-run, dan integrasi dengan S3.

Metode yang ditambahkan:
- Untuk PITRRestorePoint: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PITRRestoreResult: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk PointInTimeRecovery: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError

from .dr_exceptions import RecoveryError

logger = logging.getLogger(__name__)


# ============================================================================
# PITRRestorePoint (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class PITRRestorePoint:
    restore_id: str
    base_backup_id: str
    backup_time: datetime
    earliest_restore_time: datetime
    latest_restore_time: datetime
    wal_archive_path: str
    total_size_bytes: int
    is_valid: bool = True
    details: dict = field(default_factory=dict)

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "restore_id": self.restore_id,
                "base_backup_id": self.base_backup_id,
                "backup_time": self.backup_time.isoformat(),
                "is_valid": self.is_valid,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "restore_id": self.restore_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.restore_id:
            errors.append("restore_id is required")
        if not self.base_backup_id:
            errors.append("base_backup_id is required")
        if self.backup_time > datetime.now(UTC):
            errors.append("backup_time cannot be in the future")
        if self.earliest_restore_time > self.latest_restore_time:
            errors.append("earliest_restore_time cannot be after latest_restore_time")
        if self.total_size_bytes < 0:
            errors.append("total_size_bytes cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "restore_id": self.restore_id,
            "base_backup_id": self.base_backup_id,
            "backup_time": self.backup_time.isoformat(),
            "earliest_restore_time": self.earliest_restore_time.isoformat(),
            "latest_restore_time": self.latest_restore_time.isoformat(),
            "wal_archive_path": self.wal_archive_path,
            "total_size_bytes": self.total_size_bytes,
            "is_valid": self.is_valid,
            "details": self.details,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PITRRestorePoint:
        instance = cls(
            restore_id=data["restore_id"],
            base_backup_id=data["base_backup_id"],
            backup_time=datetime.fromisoformat(data["backup_time"]),
            earliest_restore_time=datetime.fromisoformat(data["earliest_restore_time"]),
            latest_restore_time=datetime.fromisoformat(data["latest_restore_time"]),
            wal_archive_path=data["wal_archive_path"],
            total_size_bytes=data["total_size_bytes"],
            is_valid=data.get("is_valid", True),
            details=data.get("details", {}),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PITRRestorePoint:
        new = PITRRestorePoint(
            restore_id=str(uuid4()),
            base_backup_id=self.base_backup_id,
            backup_time=self.backup_time,
            earliest_restore_time=self.earliest_restore_time,
            latest_restore_time=self.latest_restore_time,
            wal_archive_path=self.wal_archive_path,
            total_size_bytes=self.total_size_bytes,
            is_valid=self.is_valid,
            details=self.details.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.restore_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "restore_id": self.restore_id,
            "base_backup_id": self.base_backup_id,
            "backup_time": self.backup_time.isoformat(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PITRRestorePoint:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# PITRRestoreResult (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class PITRRestoreResult:
    restore_id: str
    target_time: datetime
    restored_path: str
    success: bool
    duration_seconds: float
    wal_files_restored: int
    data_loss_seconds: float | None = None
    error_message: str | None = None
    restored_lsn: str | None = None

    # Fields untuk audit dan versioning
    _version: int = field(default=1, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "restore_id": self.restore_id,
                "success": self.success,
                "duration_seconds": self.duration_seconds,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "restore_id": self.restore_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.restore_id:
            errors.append("restore_id is required")
        if self.target_time > datetime.now(UTC):
            errors.append("target_time cannot be in the future")
        if self.duration_seconds < 0:
            errors.append("duration_seconds cannot be negative")
        if self.wal_files_restored < 0:
            errors.append("wal_files_restored cannot be negative")
        if not self.success and not self.error_message:
            errors.append("error_message is required when success=False")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "restore_id": self.restore_id,
            "target_time": self.target_time.isoformat(),
            "restored_path": self.restored_path,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "wal_files_restored": self.wal_files_restored,
            "data_loss_seconds": self.data_loss_seconds,
            "error_message": self.error_message,
            "restored_lsn": self.restored_lsn,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PITRRestoreResult:
        instance = cls(
            restore_id=data["restore_id"],
            target_time=datetime.fromisoformat(data["target_time"]),
            restored_path=data["restored_path"],
            success=data["success"],
            duration_seconds=data["duration_seconds"],
            wal_files_restored=data["wal_files_restored"],
            data_loss_seconds=data.get("data_loss_seconds"),
            error_message=data.get("error_message"),
            restored_lsn=data.get("restored_lsn"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PITRRestoreResult:
        new = PITRRestoreResult(
            restore_id=str(uuid4()),
            target_time=self.target_time,
            restored_path=self.restored_path,
            success=self.success,
            duration_seconds=self.duration_seconds,
            wal_files_restored=self.wal_files_restored,
            data_loss_seconds=self.data_loss_seconds,
            error_message=self.error_message,
            restored_lsn=self.restored_lsn,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.restore_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "restore_id": self.restore_id,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PITRRestoreResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# PointInTimeRecovery Core (dengan entity dasar)
# ============================================================================
class PointInTimeRecovery:
    """
    Point-in-Time Recovery untuk database PostgreSQL.
    """

    def __init__(
        self,
        db_type: str = "postgresql",
        db_host: str = "localhost",
        db_port: int = 5432,
        db_name: str = "erp_db",
        db_user: str = "recovery_user",
        db_password: str | None = None,
        wal_archive_path: str = "s3://erp-wal-archive/wal/",
        backup_bucket: str = "erp-backups",
        backup_prefix: str = "base_backups/",
        restore_temp_dir: str = "/tmp/pitr_restore",
        use_physical_backup: bool = True,
    ):
        self.db_type = db_type
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.wal_archive_path = wal_archive_path.rstrip("/")
        self.backup_bucket = backup_bucket
        self.backup_prefix = backup_prefix.rstrip("/") + "/"
        self.restore_temp_dir = restore_temp_dir
        self.use_physical_backup = use_physical_backup
        self.s3_client = boto3.client("s3")
        self._restore_points: dict[str, PITRRestorePoint] = {}

        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "db_host": self.db_host,
                "db_name": self.db_name,
                "backup_bucket": self.backup_bucket,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ------------------------------------------------------------------------
    # Backup Management
    # ------------------------------------------------------------------------
    def list_available_base_backups(self) -> list[dict]:
        backups = []
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.backup_bucket, Prefix=self.backup_prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith(".tar.gz") or key.endswith(".backup"):
                        backups.append(
                            {
                                "key": key,
                                "last_modified": obj["LastModified"].replace(tzinfo=None),
                                "size_bytes": obj["Size"],
                                "backup_id": os.path.basename(key)
                                .replace(".tar.gz", "")
                                .replace(".backup", ""),
                            }
                        )
        except ClientError as e:
            logger.error(f"Failed to list backups: {e}")
        return sorted(backups, key=lambda x: x["last_modified"], reverse=True)

    def get_restore_points(self) -> list[PITRRestorePoint]:
        backups = self.list_available_base_backups()
        restore_points = []
        for b in backups:
            backup_time = b["last_modified"]
            earliest = backup_time + timedelta(minutes=5)
            latest = datetime.utcnow()
            restore_point = PITRRestorePoint(
                restore_id=str(uuid4()),
                base_backup_id=b["backup_id"],
                backup_time=backup_time,
                earliest_restore_time=earliest,
                latest_restore_time=latest,
                wal_archive_path=self.wal_archive_path,
                total_size_bytes=b["size_bytes"],
            )
            restore_points.append(restore_point)
            self._restore_points[restore_point.restore_id] = restore_point
        self._record_audit("GET_RESTORE_POINTS", "system", {"count": len(restore_points)})
        return restore_points

    # ------------------------------------------------------------------------
    # WAL Management
    # ------------------------------------------------------------------------
    def _list_wal_files_since(self, since_time: datetime) -> list[str]:
        prefix = self._get_wal_prefix()
        wal_files = []
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._get_wal_bucket(), Prefix=prefix):
                for obj in page.get("Contents", []):
                    last_modified = obj["LastModified"].replace(tzinfo=None)
                    if last_modified >= since_time:
                        wal_files.append(obj["Key"])
        except ClientError as e:
            logger.error(f"Failed to list WAL files: {e}")
        return sorted(wal_files)

    def _get_wal_bucket(self) -> str:
        return self.wal_archive_path.replace("s3://", "").split("/")[0]

    def _get_wal_prefix(self) -> str:
        parts = self.wal_archive_path.replace("s3://", "").split("/")[1:]
        return "/".join(parts).rstrip("/") + "/" if parts else ""

    def _download_wal_file(self, wal_key: str, target_dir: str) -> str:
        local_path = os.path.join(target_dir, os.path.basename(wal_key))
        self.s3_client.download_file(self._get_wal_bucket(), wal_key, local_path)
        return local_path

    # ------------------------------------------------------------------------
    # Physical Restore (PostgreSQL native)
    # ------------------------------------------------------------------------
    def _restore_physical_backup(self, backup_key: str, restore_dir: str) -> str:
        local_tar = os.path.join(restore_dir, "base_backup.tar.gz")
        self.s3_client.download_file(self.backup_bucket, backup_key, local_tar)
        data_dir = os.path.join(restore_dir, "data")
        os.makedirs(data_dir, exist_ok=True)
        import tarfile

        with tarfile.open(local_tar, "r:gz") as tar:
            tar.extractall(data_dir)
        recovery_signal = os.path.join(data_dir, "recovery.signal")
        with open(recovery_signal, "w") as f:
            f.write("")
        return data_dir

    def _configure_recovery(self, data_dir: str, target_time: datetime, wal_dir: str) -> None:
        conf_path = os.path.join(data_dir, "postgresql.conf")
        with open(conf_path, "a") as f:
            f.write("\n# PITR recovery configuration\n")
            f.write(f"recovery_target_time = '{target_time.isoformat()}'\n")
            f.write("recovery_target_action = 'promote'\n")
            f.write(f"restore_command = 'cp {wal_dir}/%f %p'\n")
            f.write("recovery_target_inclusive = false\n")

    # ------------------------------------------------------------------------
    # Logical Restore (pg_restore)
    # ------------------------------------------------------------------------
    def _restore_logical_backup(self, backup_key: str, target_time: datetime) -> str:
        with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as tmp:
            local_dump = tmp.name
        self.s3_client.download_file(self.backup_bucket, backup_key, local_dump)
        env = os.environ.copy()
        if self.db_password:
            env["PGPASSWORD"] = self.db_password
        cmd = [
            "pg_restore",
            f"--host={self.db_host}",
            f"--port={self.db_port}",
            f"--username={self.db_user}",
            f"--dbname={self.db_name}",
            "--clean",
            "--if-exists",
            "--no-owner",
            local_dump,
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        os.unlink(local_dump)
        if result.returncode != 0:
            raise RecoveryError(f"Logical restore failed: {result.stderr}")
        return self.db_name

    # ------------------------------------------------------------------------
    # Main Restore Method
    # ------------------------------------------------------------------------
    def restore_to_timestamp(
        self,
        target_time: datetime,
        restore_point_id: str | None = None,
        restore_dir: str | None = None,
        dry_run: bool = False,
    ) -> PITRRestoreResult:
        start_time = datetime.utcnow()
        restore_id = str(uuid4())
        restore_path = restore_dir or os.path.join(self.restore_temp_dir, restore_id)
        os.makedirs(restore_path, exist_ok=True)

        restore_point = None
        if restore_point_id:
            restore_point = self._restore_points.get(restore_point_id)
        else:
            points = self.get_restore_points()
            for p in points:
                if p.backup_time <= target_time:
                    restore_point = p
                    break
        if not restore_point:
            raise RecoveryError("No suitable base backup found for target time")

        logger.info(f"Restoring to {target_time} using base backup {restore_point.base_backup_id}")
        data_loss_seconds = (target_time - restore_point.backup_time).total_seconds()
        if data_loss_seconds < 0:
            data_loss_seconds = 0

        if dry_run:
            wal_files_needed = self._list_wal_files_since(restore_point.backup_time)
            logger.info(f"DRY RUN: Would restore base backup + {len(wal_files_needed)} WAL files")
            self._record_audit(
                "DRY_RUN_RESTORE",
                "system",
                {"restore_id": restore_id, "target_time": target_time.isoformat()},
            )
            return PITRRestoreResult(
                restore_id=restore_id,
                target_time=target_time,
                restored_path=restore_path,
                success=True,
                duration_seconds=0,
                wal_files_restored=len(wal_files_needed),
                data_loss_seconds=data_loss_seconds,
            )

        try:
            if self.use_physical_backup:
                backup_key = f"{self.backup_prefix}{restore_point.base_backup_id}.tar.gz"
                data_dir = self._restore_physical_backup(backup_key, restore_path)
                wal_dir = os.path.join(restore_path, "wal")
                os.makedirs(wal_dir, exist_ok=True)
                wal_keys = self._list_wal_files_since(restore_point.backup_time)
                wal_restored = 0
                for wal_key in wal_keys:
                    self._download_wal_file(wal_key, wal_dir)
                    wal_restored += 1
                self._configure_recovery(data_dir, target_time, wal_dir)
                logger.info(
                    f"Physical restore prepared at {data_dir} with {wal_restored} WAL files"
                )
            else:
                backup_key = f"{self.backup_prefix}{restore_point.base_backup_id}.dump"
                self._restore_logical_backup(backup_key, target_time)
                wal_restored = 0

            duration = (datetime.utcnow() - start_time).total_seconds()
            result = PITRRestoreResult(
                restore_id=restore_id,
                target_time=target_time,
                restored_path=restore_path if self.use_physical_backup else self.db_name,
                success=True,
                duration_seconds=duration,
                wal_files_restored=wal_restored if self.use_physical_backup else 0,
                data_loss_seconds=data_loss_seconds,
                restored_lsn=None,
            )
            self._record_audit(
                "RESTORE_TO_TIMESTAMP", "system", {"restore_id": restore_id, "success": True}
            )
            logger.info(f"Restore completed in {duration:.2f}s, data loss ~{data_loss_seconds}s")
            return result
        except Exception as e:
            logger.exception("Restore failed")
            duration = (datetime.utcnow() - start_time).total_seconds()
            result = PITRRestoreResult(
                restore_id=restore_id,
                target_time=target_time,
                restored_path="",
                success=False,
                duration_seconds=duration,
                wal_files_restored=0,
                error_message=str(e),
            )
            self._record_audit(
                "RESTORE_TO_TIMESTAMP",
                "system",
                {"restore_id": restore_id, "success": False, "error": str(e)},
            )
            return result
        finally:
            if not dry_run and self.use_physical_backup and restore_dir is None:
                shutil.rmtree(restore_path, ignore_errors=True)

    # ------------------------------------------------------------------------
    # Dry Run & Validation
    # ------------------------------------------------------------------------
    def dry_run_recovery(self, target_time: datetime) -> dict:
        points = self.get_restore_points()
        suitable = None
        for p in points:
            if p.backup_time <= target_time <= p.latest_restore_time:
                suitable = p
                break
        if not suitable:
            return {"can_recover": False, "reason": "No suitable base backup or WAL gap"}
        wal_files = self._list_wal_files_since(suitable.backup_time)
        return {
            "can_recover": True,
            "base_backup_id": suitable.base_backup_id,
            "backup_time": suitable.backup_time.isoformat(),
            "target_time": target_time.isoformat(),
            "wal_files_required": len(wal_files),
            "estimated_data_loss_seconds": (target_time - suitable.backup_time).total_seconds(),
        }

    def validate_restore(self, result: PITRRestoreResult) -> bool:
        if not result.success:
            return False
        try:
            env = os.environ.copy()
            if self.db_password:
                env["PGPASSWORD"] = self.db_password
            cmd = [
                "psql",
                f"--host={self.db_host}",
                f"--port={self.db_port}",
                f"--username={self.db_user}",
                f"--dbname={self.db_name}",
                "-c",
                "SELECT 1 AS pitr_test;",
            ]
            subprocess.run(cmd, env=env, capture_output=True, check=True)
            return True
        except subprocess.CalledProcessError as e:
            # Log the error before returning False
            logger.error(f"Validation restore failed: {e}")
            return False

    # ------------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------------
    def get_restore_points_report(self) -> dict:
        restore_points = self.get_restore_points()
        return {
            "total_restore_points": len(restore_points),
            "latest_backup_time": restore_points[0].backup_time.isoformat()
            if restore_points
            else None,
            "earliest_restore_time": restore_points[-1].earliest_restore_time.isoformat()
            if restore_points
            else None,
            "restore_points": [
                {
                    "restore_id": r.restore_id,
                    "base_backup_id": r.base_backup_id,
                    "backup_time": r.backup_time.isoformat(),
                    "earliest_restore": r.earliest_restore_time.isoformat(),
                    "latest_restore": r.latest_restore_time.isoformat(),
                }
                for r in restore_points
            ],
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "db_type": self.db_type,
            "wal_archive_path": self.wal_archive_path,
            "backup_bucket": self.backup_bucket,
            "restore_points_report": self.get_restore_points_report(),
            "version": self._version,
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.db_host:
            errors.append("db_host is required")
        if self.db_port <= 0:
            errors.append("db_port must be positive")
        if not self.db_name:
            errors.append("db_name is required")
        if not self.db_user:
            errors.append("db_user is required")
        if not self.backup_bucket:
            errors.append("backup_bucket is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "db_type": self.db_type,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_user": self.db_user,
            "wal_archive_path": self.wal_archive_path,
            "backup_bucket": self.backup_bucket,
            "backup_prefix": self.backup_prefix,
            "restore_temp_dir": self.restore_temp_dir,
            "use_physical_backup": self.use_physical_backup,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PointInTimeRecovery:
        instance = cls(
            db_type=data.get("db_type", "postgresql"),
            db_host=data.get("db_host", "localhost"),
            db_port=data.get("db_port", 5432),
            db_name=data.get("db_name", "erp_db"),
            db_user=data.get("db_user", "recovery_user"),
            db_password=data.get("db_password"),
            wal_archive_path=data.get("wal_archive_path", "s3://erp-wal-archive/wal/"),
            backup_bucket=data.get("backup_bucket", "erp-backups"),
            backup_prefix=data.get("backup_prefix", "base_backups/"),
            restore_temp_dir=data.get("restore_temp_dir", "/tmp/pitr_restore"),
            use_physical_backup=data.get("use_physical_backup", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> PointInTimeRecovery:
        new = PointInTimeRecovery(
            db_type=self.db_type,
            db_host=self.db_host,
            db_port=self.db_port,
            db_name=self.db_name,
            db_user=self.db_user,
            db_password=self.db_password,
            wal_archive_path=self.wal_archive_path,
            backup_bucket=self.backup_bucket,
            backup_prefix=self.backup_prefix,
            restore_temp_dir=self.restore_temp_dir,
            use_physical_backup=self.use_physical_backup,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "db_host": self.db_host,
            "db_name": self.db_name,
            "backup_bucket": self.backup_bucket,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PointInTimeRecovery:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._restore_points.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    pitr = PointInTimeRecovery(
        db_type="postgresql",
        db_host="localhost",
        db_name="erp_production",
        db_user="postgres",
        wal_archive_path="s3://erp-wal-archive/wal/",
        backup_bucket="erp-backups",
        use_physical_backup=True,
    )
    print("Restore points:", pitr.get_restore_points_report())
    target = datetime.utcnow() - timedelta(hours=1)
    dry = pitr.dry_run_recovery(target)
    print("Dry run:", dry)
