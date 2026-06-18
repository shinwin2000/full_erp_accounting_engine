#!/usr/bin/env python3
"""
Module: database_exceptions.py
Layer: Infrastructure (Database)
Responsibility: Mendefinisikan semua exception yang terkait dengan database
               operations, termasuk koneksi, transaksi, migrasi, backup,
               partition, dan PITR.
Dependencies:
- none (standalone module)
Audit: Exception yang terjadi di database layer dicatat oleh audit logger.
"""

from __future__ import annotations

# ============================================================================
# BASE EXCEPTION
# ============================================================================


class DatabaseError(Exception):
    """Base exception untuk semua error database."""

    pass


# ============================================================================
# CONNECTION & POOL EXCEPTIONS
# ============================================================================


class DatabaseConnectionError(DatabaseError):
    """Error saat koneksi database."""

    pass


class DatabasePoolError(DatabaseError):
    """Error saat mengelola connection pool."""

    pass


class SessionFactoryError(DatabaseError):
    """Error saat membuat session factory."""

    pass


# ============================================================================
# TRANSACTION EXCEPTIONS
# ============================================================================


class TransactionError(DatabaseError):
    """Base exception untuk transaksi."""

    pass


class TransactionPropagationError(TransactionError):
    """Error terkait propagation behavior."""

    pass


# ============================================================================
# MIGRATION EXCEPTIONS
# ============================================================================


class MigrationError(DatabaseError):
    """Base exception untuk migration."""

    pass


class MigrationNotInitializedError(MigrationError):
    """Migration belum diinisialisasi."""

    pass


class MigrationRollbackError(DatabaseError):
    """Base exception untuk migration rollback."""

    pass


class RollbackFailedError(MigrationRollbackError):
    """Rollback gagal."""

    pass


class BackupCreationError(MigrationRollbackError):
    """Error saat membuat backup sebelum rollback."""

    pass


# ============================================================================
# SEED DATA EXCEPTIONS
# ============================================================================


class SeedDataError(DatabaseError):
    """Base exception untuk seed data."""

    pass


class SeedDataNotFoundError(SeedDataError):
    """File seed data tidak ditemukan."""

    pass


class SeedDataValidationError(SeedDataError):
    """Data seed tidak valid."""

    pass


class ValidationError(SeedDataValidationError):
    """Error validasi data."""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__(f"Validation failed with {len(errors)} error(s)")


# ============================================================================
# TDE EXCEPTIONS
# ============================================================================


class TDEError(DatabaseError):
    """Base exception untuk TDE."""

    pass


class EncryptionKeyError(TDEError):
    """Error terkait kunci enkripsi."""

    pass


# ============================================================================
# AUDIT TRIGGER EXCEPTIONS
# ============================================================================


class AuditTriggerError(DatabaseError):
    """Error saat menginstall audit trigger."""

    pass


# ============================================================================
# PARTITION EXCEPTIONS
# ============================================================================


class PartitionManagerError(DatabaseError):
    """Base exception untuk partition manager."""

    pass


class PartitionCreateError(PartitionManagerError):
    """Error saat membuat partisi."""

    pass


class PartitionMaintenanceError(PartitionManagerError):
    """Error saat maintenance partisi."""

    pass


class PartitionArchiverError(DatabaseError):
    """Base exception untuk partition archiver."""

    pass


class ArchiveCreateError(PartitionArchiverError):
    """Error saat membuat arsip."""

    pass


class ArchiveRestoreError(PartitionArchiverError):
    """Error saat restore arsip."""

    pass


# ============================================================================
# BACKUP EXCEPTIONS
# ============================================================================


class DatabaseBackupError(DatabaseError):
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
# PITR EXCEPTIONS
# ============================================================================


class PITRError(DatabaseError):
    """Base exception untuk PITR."""

    pass


class PITRRestoreError(PITRError):
    """Error saat restore PITR."""

    pass


class WALArchiveError(PITRError):
    """Error terkait WAL archive."""

    pass


# ============================================================================
# HEALTH PROBE EXCEPTIONS
# ============================================================================


class DatabaseHealthError(DatabaseError):
    """Base exception untuk health probe."""

    pass


# ============================================================================
# READ REPLICA EXCEPTIONS
# ============================================================================


class ReadReplicaError(DatabaseError):
    """Base exception untuk read replica."""

    pass


class WriteToReplicaError(ReadReplicaError):
    """Mencoba menulis ke read replica."""

    pass


class ReplicaUnavailableError(ReadReplicaError):
    """Read replica tidak tersedia."""

    pass


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Base
    "DatabaseError",
    # Connection
    "DatabaseConnectionError",
    "DatabasePoolError",
    "SessionFactoryError",
    # Transaction
    "TransactionError",
    "TransactionPropagationError",
    # Migration
    "MigrationError",
    "MigrationNotInitializedError",
    "MigrationRollbackError",
    "RollbackFailedError",
    "BackupCreationError",
    # Seed data
    "SeedDataError",
    "SeedDataNotFoundError",
    "SeedDataValidationError",
    "ValidationError",
    # TDE
    "TDEError",
    "EncryptionKeyError",
    # Audit
    "AuditTriggerError",
    # Partition
    "PartitionManagerError",
    "PartitionCreateError",
    "PartitionMaintenanceError",
    "PartitionArchiverError",
    "ArchiveCreateError",
    "ArchiveRestoreError",
    # Backup
    "DatabaseBackupError",
    "BackupCreateError",
    "BackupRestoreError",
    "BackupNotFoundError",
    # PITR
    "PITRError",
    "PITRRestoreError",
    "WALArchiveError",
    # Health
    "DatabaseHealthError",
    # Read replica
    "ReadReplicaError",
    "WriteToReplicaError",
    "ReplicaUnavailableError",
]
