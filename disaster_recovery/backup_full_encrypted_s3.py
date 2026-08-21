#!/usr/bin/env python3
"""
Module: backup_full_encrypted_s3.py
Layer: Disaster Recovery

Responsibility:
    Melakukan full backup database (PostgreSQL/MySQL) dengan enkripsi client-side
    menggunakan AWS KMS atau master key lokal, kompresi, upload ke S3 dengan SSE,
    manajemen retensi, integrity check (SHA256), dan notifikasi.

Metode yang ditambahkan:
- Untuk BackupMetadata: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk S3EncryptedBackup: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    from .dr_exceptions import BackupError
except ImportError:
    # FIX: tambahkan # type: ignore untuk menghindari error mypy no-redef
    class BackupError(Exception):  # type: ignore
        pass


logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class BackupStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"

    def display_name(self) -> str:
        names = {
            BackupStatus.PENDING: "Menunggu",
            BackupStatus.RUNNING: "Berjalan",
            BackupStatus.SUCCESS: "Berhasil",
            BackupStatus.FAILED: "Gagal",
            BackupStatus.PARTIAL: "Sebagian",
        }
        return names.get(self, self.value)


class EncryptionMethod(Enum):
    NONE = "none"
    AWS_KMS = "aws_kms"
    LOCAL_AES = "local_aes"
    FERNET = "fernet"

    def display_name(self) -> str:
        names = {
            EncryptionMethod.NONE: "Tidak dienkripsi",
            EncryptionMethod.AWS_KMS: "AWS KMS",
            EncryptionMethod.LOCAL_AES: "AES-256 Lokal",
            EncryptionMethod.FERNET: "Fernet",
        }
        return names.get(self, self.value)


BACKUP_RETENTION_DAYS_DEFAULT = 30
COMPRESSION_LEVEL_DEFAULT = 6
CHUNK_SIZE = 1024 * 1024  # 1MB
MAX_PARALLEL_UPLOADS = 5


# ============================================================================
# BackupMetadata (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class BackupMetadata:
    backup_id: str
    timestamp: datetime
    database_size_bytes: int
    compressed_size_bytes: int
    encrypted_size_bytes: int
    checksum: str
    encryption_method: EncryptionMethod
    encryption_key_id: str
    s3_bucket: str
    s3_key: str
    status: BackupStatus
    duration_seconds: float
    error_message: str | None = None
    wal_segment_count: int | None = None
    db_version: str = "unknown"
    hostname: str | None = None

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
                "backup_id": self.backup_id,
                "status": self.status.value,
                "timestamp": self.timestamp.isoformat(),
                "timestamp_now": datetime.now(UTC).isoformat(),
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
                "backup_id": self.backup_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.backup_id:
            errors.append("backup_id is required")
        if self.database_size_bytes < 0:
            errors.append("database_size_bytes cannot be negative")
        if self.compressed_size_bytes < 0:
            errors.append("compressed_size_bytes cannot be negative")
        if self.encrypted_size_bytes < 0:
            errors.append("encrypted_size_bytes cannot be negative")
        if not self.checksum:
            errors.append("checksum is required")
        if not isinstance(self.encryption_method, EncryptionMethod):
            errors.append("invalid encryption_method")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "timestamp": self.timestamp.isoformat(),
            "database_size_bytes": self.database_size_bytes,
            "compressed_size_bytes": self.compressed_size_bytes,
            "encrypted_size_bytes": self.encrypted_size_bytes,
            "checksum": self.checksum,
            "encryption_method": self.encryption_method.value,
            "encryption_key_id": self.encryption_key_id,
            "s3_bucket": self.s3_bucket,
            "s3_key": self.s3_key,
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "error_message": self.error_message,
            "wal_segment_count": self.wal_segment_count,
            "db_version": self.db_version,
            "hostname": self.hostname,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupMetadata:
        instance = cls(
            backup_id=data["backup_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            database_size_bytes=data["database_size_bytes"],
            compressed_size_bytes=data["compressed_size_bytes"],
            encrypted_size_bytes=data["encrypted_size_bytes"],
            checksum=data["checksum"],
            encryption_method=EncryptionMethod(data["encryption_method"]),
            encryption_key_id=data["encryption_key_id"],
            s3_bucket=data["s3_bucket"],
            s3_key=data["s3_key"],
            status=BackupStatus(data["status"]),
            duration_seconds=data["duration_seconds"],
            error_message=data.get("error_message"),
            wal_segment_count=data.get("wal_segment_count"),
            db_version=data.get("db_version", "unknown"),
            hostname=data.get("hostname"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> BackupMetadata:
        new = BackupMetadata(
            backup_id=str(uuid4()),
            timestamp=self.timestamp,
            database_size_bytes=self.database_size_bytes,
            compressed_size_bytes=self.compressed_size_bytes,
            encrypted_size_bytes=self.encrypted_size_bytes,
            checksum=self.checksum,
            encryption_method=self.encryption_method,
            encryption_key_id=self.encryption_key_id,
            s3_bucket=self.s3_bucket,
            s3_key=self.s3_key,
            status=BackupStatus.PENDING,
            duration_seconds=0,
            error_message=self.error_message,
            wal_segment_count=self.wal_segment_count,
            db_version=self.db_version,
            hostname=self.hostname,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.backup_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "backup_id": self.backup_id,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BackupMetadata:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# S3EncryptedBackup Core (dengan entity dasar)
# ============================================================================
class S3EncryptedBackup:
    """
    Backup database dengan enkripsi client-side atau server-side (KMS) ke S3.
    """

    def __init__(
        self,
        s3_bucket: str,
        s3_prefix: str = "backups/",
        region: str = "ap-southeast-1",
        kms_key_id: str | None = None,
        use_server_side_encryption: bool = True,
        db_type: str = "postgresql",
        db_host: str = "localhost",
        db_port: int = 5432,
        db_name: str = "erp_db",
        db_user: str = "backup_user",
        db_password: str | None = None,
        retention_days: int = BACKUP_RETENTION_DAYS_DEFAULT,
        compression_level: int = COMPRESSION_LEVEL_DEFAULT,
        encryption_method: EncryptionMethod = EncryptionMethod.AWS_KMS,
        parallel_uploads: int = MAX_PARALLEL_UPLOADS,
        enable_encryption: bool = True,
        temp_dir: str | None = None,
    ):
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip("/") + "/"
        self.region = region
        self.kms_key_id = kms_key_id
        self.use_sse = use_server_side_encryption
        self.db_type = db_type
        self.db_host = db_host
        self.db_port = db_port
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.retention_days = retention_days
        self.compression_level = compression_level
        self.encryption_method = encryption_method
        self.parallel_uploads = parallel_uploads
        self.enable_encryption = enable_encryption
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.s3_client = boto3.client("s3", region_name=region)
        self.kms_client = boto3.client("kms", region_name=region) if kms_key_id else None
        self._master_key: bytes | None = None
        if encryption_method == EncryptionMethod.LOCAL_AES:
            self._master_key = self._load_or_create_master_key()

        # Fields untuk versioning dan audit
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "s3_bucket": self.s3_bucket,
                "db_name": self.db_name,
                "encryption_method": self.encryption_method.value,
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

    def _load_or_create_master_key(self) -> bytes:
        key_file = Path(self.temp_dir) / ".backup_master_key"
        if key_file.exists():
            with open(key_file, "rb") as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(key_file, "wb") as f:
                f.write(key)
            os.chmod(key_file, 0o600)
            logger.warning(
                f"Generated new master key at {key_file}. Ensure it is backed up securely."
            )
            return key

    def _get_db_dump_command(self, output_file: str) -> list[str]:
        if self.db_type == "postgresql":
            cmd = [
                "pg_dump",
                f"--host={self.db_host}",
                f"--port={self.db_port!s}",
                f"--username={self.db_user}",
                f"--dbname={self.db_name}",
                "--format=custom",
                "--compress=0",
                f"--file={output_file}",
            ]
            if self.db_password:
                os.environ["PGPASSWORD"] = self.db_password
        elif self.db_type == "mysql":
            cmd = [
                "mysqldump",
                f"--host={self.db_host}",
                f"--port={self.db_port!s}",
                f"--user={self.db_user}",
                f"--databases={self.db_name}",
                "--single-transaction",
                "--routines",
                "--triggers",
                f"--result-file={output_file}",
            ]
            if self.db_password:
                cmd.append(f"--password={self.db_password}")
        else:
            raise BackupError(f"Unsupported database type: {self.db_type}")
        return cmd

    def _get_db_version(self) -> str:
        try:
            if self.db_type == "postgresql":
                cmd = [
                    "psql",
                    "-h",
                    self.db_host,
                    "-p",
                    str(self.db_port),
                    "-U",
                    self.db_user,
                    "-d",
                    self.db_name,
                    "-c",
                    "SELECT version();",
                ]
                if self.db_password:
                    os.environ["PGPASSWORD"] = self.db_password
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "PostgreSQL" in line:
                            return line.strip()
            elif self.db_type == "mysql":
                cmd = [
                    "mysql",
                    "-h",
                    self.db_host,
                    "-P",
                    str(self.db_port),
                    "-u",
                    self.db_user,
                    "-e",
                    "SELECT VERSION();",
                ]
                if self.db_password:
                    cmd.append(f"-p{self.db_password}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode == 0:
                    return result.stdout.strip().splitlines()[-1]
        except Exception as e:
            logger.warning(f"Could not get DB version: {e}")
        return "unknown"

    def _compress_file(self, input_path: str, output_path: str) -> None:
        with open(input_path, "rb") as f_in, gzip.open(
            output_path, "wb", compresslevel=self.compression_level
        ) as f_out:
            shutil.copyfileobj(f_in, f_out, length=65536)

    def _calculate_checksum(self, file_path: str, chunk_size: int = CHUNK_SIZE) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _encrypt_file(self, input_path: str, output_path: str) -> str:
        if not self.enable_encryption:
            shutil.copy2(input_path, output_path)
            return "none"
        if self.encryption_method == EncryptionMethod.AWS_KMS and self.kms_key_id:
            if self.kms_client is None:
                raise BackupError("KMS client not initialized (missing kms_key_id?)")
            with open(input_path, "rb") as f:
                plaintext = f.read()
            try:
                response = self.kms_client.encrypt(
                    KeyId=self.kms_key_id,
                    Plaintext=plaintext,
                    EncryptionAlgorithm="SYMMETRIC_DEFAULT",
                )
                ciphertext = response["CiphertextBlob"]
                with open(output_path, "wb") as f:
                    f.write(ciphertext)
                return self.kms_key_id
            except (ClientError, BotoCoreError) as e:
                raise BackupError(f"KMS encryption failed: {e}")
        elif self.encryption_method == EncryptionMethod.LOCAL_AES and self._master_key:
            salt = os.urandom(16)
            iv = os.urandom(16)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=salt,
                iterations=100000,
                backend=default_backend(),
            )
            key = kdf.derive(self._master_key)
            cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
            encryptor = cipher.encryptor()
            with open(input_path, "rb") as f_in:
                plaintext = f_in.read()
            pad_len = 16 - (len(plaintext) % 16)
            plaintext += bytes([pad_len] * pad_len)
            ciphertext = encryptor.update(plaintext) + encryptor.finalize()
            with open(output_path, "wb") as f_out:
                f_out.write(salt + iv + ciphertext)
            return "local-aes"
        elif self.encryption_method == EncryptionMethod.FERNET:
            fernet = Fernet(self._load_or_create_master_key())
            with open(input_path, "rb") as f:
                ciphertext = fernet.encrypt(f.read())
            with open(output_path, "wb") as f:
                f.write(ciphertext)
            return "fernet"
        else:
            shutil.copy2(input_path, output_path)
            return "none"

    def _upload_to_s3(self, file_path: str, s3_key: str, metadata: dict) -> None:
        extra_args: dict[str, Any] = {"Metadata": metadata}
        if self.use_sse and self.kms_key_id:
            extra_args["ServerSideEncryption"] = "aws:kms"
            extra_args["SSEKMSKeyId"] = self.kms_key_id
        elif self.use_sse:
            extra_args["ServerSideEncryption"] = "AES256"
        try:
            self.s3_client.upload_file(file_path, self.s3_bucket, s3_key, ExtraArgs=extra_args)
        except ClientError as e:
            raise BackupError(f"Failed to upload to S3: {e}")

    def _delete_old_backups(self) -> int:
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted = 0
        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=self.s3_prefix):
                for obj in page.get("Contents", []):
                    if obj["LastModified"].replace(tzinfo=None) < cutoff:
                        self.s3_client.delete_object(Bucket=self.s3_bucket, Key=obj["Key"])
                        deleted += 1
        except ClientError as e:
            logger.error(f"Cleanup failed: {e}")
        return deleted

    def _get_file_size(self, path: str) -> int:
        return os.path.getsize(path) if os.path.exists(path) else 0

    def create_backup(self, backup_id: str | None = None) -> BackupMetadata:
        start_time = time.time()
        backup_id = backup_id or f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        status = BackupStatus.RUNNING
        error_msg = None
        db_dump_path: str | None = None
        compressed_path: str | None = None
        encrypted_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(
                suffix=".dump", delete=False, dir=self.temp_dir
            ) as tmp:
                db_dump_path = tmp.name
            dump_cmd = self._get_db_dump_command(db_dump_path)
            logger.info(f"Starting database dump: {' '.join(dump_cmd)}")
            result = subprocess.run(dump_cmd, capture_output=True, text=True, timeout=7200)
            if result.returncode != 0:
                raise BackupError(f"Database dump failed: {result.stderr}")
            db_size = self._get_file_size(db_dump_path)
            db_version = self._get_db_version()
            logger.info(f"Dump completed: size {db_size / (1024**2):.2f} MB")

            compressed_path = db_dump_path + ".gz"
            self._compress_file(db_dump_path, compressed_path)
            compressed_size = self._get_file_size(compressed_path)
            logger.info(f"Compressed: {compressed_size / (1024**2):.2f} MB")

            encrypted_path = compressed_path + ".enc"
            encryption_key = self._encrypt_file(compressed_path, encrypted_path)
            encrypted_size = self._get_file_size(encrypted_path)
            logger.info(f"Encrypted: {encrypted_size / (1024**2):.2f} MB")

            checksum = self._calculate_checksum(encrypted_path)

            s3_key = f"{self.s3_prefix}{backup_id}.enc"
            metadata = {
                "backup_id": backup_id,
                "timestamp": datetime.utcnow().isoformat(),
                "db_type": self.db_type,
                "db_name": self.db_name,
                "db_version": db_version,
                "compression": "gzip",
                "encryption": self.encryption_method.value,
                "checksum": checksum,
                "original_size": str(db_size),
                "compressed_size": str(compressed_size),
            }
            self._upload_to_s3(encrypted_path, s3_key, metadata)
            logger.info(f"Uploaded to s3://{self.s3_bucket}/{s3_key}")

            duration = time.time() - start_time
            metadata_obj = BackupMetadata(
                backup_id=backup_id,
                timestamp=datetime.utcnow(),
                database_size_bytes=db_size,
                compressed_size_bytes=compressed_size,
                encrypted_size_bytes=encrypted_size,
                checksum=checksum,
                encryption_method=self.encryption_method,
                encryption_key_id=encryption_key,
                s3_bucket=self.s3_bucket,
                s3_key=s3_key,
                status=BackupStatus.SUCCESS,
                duration_seconds=duration,
                db_version=db_version,
                hostname=os.uname().nodename if hasattr(os, "uname") else "unknown",
            )
            status = BackupStatus.SUCCESS
            logger.info(f"Backup {backup_id} completed in {duration:.2f}s")

            paths_to_clean = [p for p in (db_dump_path, compressed_path, encrypted_path) if p is not None]
            for path in paths_to_clean:
                if os.path.exists(path):
                    os.unlink(path)

            deleted = self._delete_old_backups()
            if deleted > 0:
                logger.info(f"Deleted {deleted} old backups")

            self._record_audit(
                "CREATE_BACKUP", "system", {"backup_id": backup_id, "status": status.value}
            )
            return metadata_obj

        except Exception as e:
            status = BackupStatus.FAILED
            error_msg = str(e)
            logger.exception("Backup failed")
            self._record_audit("CREATE_BACKUP_FAILED", "system", {"error": error_msg})
            raise BackupError(f"Backup failed: {error_msg}") from e
        finally:
            paths_to_clean = [p for p in (db_dump_path, compressed_path, encrypted_path) if p is not None]
            for path in paths_to_clean:
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except Exception as cleanup_err:
                        logger.warning(f"Cleanup failed for {path}: {cleanup_err}")

    def restore_backup(self, backup_metadata: BackupMetadata, target_path: str) -> str:
        if backup_metadata.status != BackupStatus.SUCCESS:
            raise BackupError("Cannot restore from failed backup")
        encrypted_local = os.path.join(target_path, f"{backup_metadata.backup_id}.enc")
        decrypted_local = encrypted_local.replace(".enc", ".gz")
        uncompressed_local = decrypted_local.replace(".gz", ".dump")

        try:
            self.s3_client.download_file(
                backup_metadata.s3_bucket, backup_metadata.s3_key, encrypted_local
            )
            if backup_metadata.encryption_method == EncryptionMethod.AWS_KMS and self.kms_key_id:
                if self.kms_client is None:
                    raise BackupError("KMS client not initialized for decryption")
                with open(encrypted_local, "rb") as f:
                    ciphertext = f.read()
                response = self.kms_client.decrypt(
                    CiphertextBlob=ciphertext, EncryptionAlgorithm="SYMMETRIC_DEFAULT"
                )
                plaintext = response["Plaintext"]
                with open(decrypted_local, "wb") as f:
                    f.write(plaintext)
            elif (
                backup_metadata.encryption_method == EncryptionMethod.LOCAL_AES and self._master_key
            ):
                with open(encrypted_local, "rb") as f:
                    data = f.read()
                salt = data[:16]
                iv = data[16:32]
                ciphertext = data[32:]
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=salt,
                    iterations=100000,
                    backend=default_backend(),
                )
                key = kdf.derive(self._master_key)
                cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
                decryptor = cipher.decryptor()
                decrypted = decryptor.update(ciphertext) + decryptor.finalize()
                pad_len = decrypted[-1]
                decrypted = decrypted[:-pad_len]
                with open(decrypted_local, "wb") as f:
                    f.write(decrypted)
            elif backup_metadata.encryption_method == EncryptionMethod.FERNET:
                fernet = Fernet(self._load_or_create_master_key())
                with open(encrypted_local, "rb") as f:
                    decrypted = fernet.decrypt(f.read())
                with open(decrypted_local, "wb") as f:
                    f.write(decrypted)
            else:
                shutil.copy2(encrypted_local, decrypted_local)

            with gzip.open(decrypted_local, "rb") as f_in, open(uncompressed_local, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

            self._record_audit("RESTORE_BACKUP", "system", {"backup_id": backup_metadata.backup_id})
            logger.info(f"Restore completed to {uncompressed_local}")
            return uncompressed_local
        except Exception as e:
            raise BackupError(f"Restore failed: {e}") from e

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.s3_bucket:
            errors.append("s3_bucket is required")
        if self.retention_days <= 0:
            errors.append("retention_days must be positive")
        if self.compression_level < 0 or self.compression_level > 9:
            errors.append("compression_level must be between 0 and 9")
        if self.parallel_uploads <= 0:
            errors.append("parallel_uploads must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "s3_bucket": self.s3_bucket,
            "s3_prefix": self.s3_prefix,
            "region": self.region,
            "kms_key_id": self.kms_key_id,
            "use_server_side_encryption": self.use_sse,
            "db_type": self.db_type,
            "db_host": self.db_host,
            "db_port": self.db_port,
            "db_name": self.db_name,
            "db_user": self.db_user,
            "retention_days": self.retention_days,
            "compression_level": self.compression_level,
            "encryption_method": self.encryption_method.value,
            "parallel_uploads": self.parallel_uploads,
            "enable_encryption": self.enable_encryption,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> S3EncryptedBackup:
        instance = cls(
            s3_bucket=data["s3_bucket"],
            s3_prefix=data.get("s3_prefix", "backups/"),
            region=data.get("region", "ap-southeast-1"),
            kms_key_id=data.get("kms_key_id"),
            use_server_side_encryption=data.get("use_server_side_encryption", True),
            db_type=data.get("db_type", "postgresql"),
            db_host=data.get("db_host", "localhost"),
            db_port=data.get("db_port", 5432),
            db_name=data.get("db_name", "erp_db"),
            db_user=data.get("db_user", "backup_user"),
            db_password=None,
            retention_days=data.get("retention_days", BACKUP_RETENTION_DAYS_DEFAULT),
            compression_level=data.get("compression_level", COMPRESSION_LEVEL_DEFAULT),
            encryption_method=EncryptionMethod(data.get("encryption_method", "aws_kms")),
            parallel_uploads=data.get("parallel_uploads", MAX_PARALLEL_UPLOADS),
            enable_encryption=data.get("enable_encryption", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> S3EncryptedBackup:
        new = S3EncryptedBackup(
            s3_bucket=self.s3_bucket,
            s3_prefix=self.s3_prefix,
            region=self.region,
            kms_key_id=self.kms_key_id,
            use_server_side_encryption=self.use_sse,
            db_type=self.db_type,
            db_host=self.db_host,
            db_port=self.db_port,
            db_name=self.db_name,
            db_user=self.db_user,
            db_password=self.db_password,
            retention_days=self.retention_days,
            compression_level=self.compression_level,
            encryption_method=self.encryption_method,
            parallel_uploads=self.parallel_uploads,
            enable_encryption=self.enable_encryption,
            temp_dir=self.temp_dir,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "s3_bucket": self.s3_bucket,
            "db_name": self.db_name,
            "encryption_method": self.encryption_method.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> S3EncryptedBackup:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo / CLI Entry Point
# ============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="S3 Encrypted Backup Tool")
    parser.add_argument("--action", choices=["backup", "restore"], required=True)
    parser.add_argument("--backup-id", help="Backup ID for restore")
    parser.add_argument("--target-path", default="./restore", help="Restore target directory")
    parser.add_argument("--s3-bucket", required=True)
    parser.add_argument("--s3-prefix", default="backups/")
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument("--db-type", default="postgresql")
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--db-port", default="5432")
    parser.add_argument("--db-name", required=True)
    parser.add_argument("--db-user", required=True)
    parser.add_argument("--db-password", help="Database password")
    parser.add_argument("--kms-key-id", help="AWS KMS key ID")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    backup = S3EncryptedBackup(
        s3_bucket=args.s3_bucket,
        s3_prefix=args.s3_prefix,
        region=args.region,
        kms_key_id=args.kms_key_id,
        db_type=args.db_type,
        db_host=args.db_host,
        db_port=int(args.db_port),
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
    )

    if args.action == "backup":
        metadata = backup.create_backup()
        print(json.dumps(metadata.to_dict(), indent=2, default=str))
    elif args.action == "restore":
        if not args.backup_id:
            print("Error: --backup-id required for restore")
            exit(1)
        print("Restore not fully implemented in CLI demo")
        