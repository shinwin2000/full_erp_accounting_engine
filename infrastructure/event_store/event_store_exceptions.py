#!/usr/bin/env python3
"""
Module: event_store_exceptions.py
Layer: Infrastructure (Event Store)
Responsibility: Mendefinisikan semua exception yang terkait dengan Event Store
               dan komponen pendukungnya (snapshot, backup, hash chain, dll).
               Exception dibagi dalam kategori: append-only violations,
               integrity errors, snapshot errors, backup errors, dan
               compression/encryption errors. Setiap exception membawa metadata
               untuk memudahkan debugging dan audit.
Dependencies:
- none (standalone module)
Audit: Exception yang terjadi di event store dicatat oleh audit logger.
       Beberapa exception (seperti IntegrityViolation) akan memicu alert.
"""

from __future__ import annotations

from typing import Any

# ============================================================================
# BASE EXCEPTION
# ============================================================================


class EventStoreError(Exception):
    """
    Base exception untuk semua error di Event Store.
    """

    def __init__(
        self, message: str, code: str | None = None, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}


# ============================================================================
# APPEND-ONLY STORE EXCEPTIONS
# ============================================================================


class AppendOnlyStoreError(EventStoreError):
    """Error umum di append-only store."""

    pass


class EventNotFoundError(AppendOnlyStoreError):
    """Event tidak ditemukan."""

    def __init__(
        self,
        event_id: str | None = None,
        stream_name: str | None = None,
        sequence: int | None = None,
        **kwargs,
    ):
        msg = "Event not found"
        if event_id:
            msg = f"Event {event_id} not found"
        elif stream_name and sequence:
            msg = f"Event not found in stream {stream_name} at sequence {sequence}"
        elif stream_name:
            msg = f"Event not found in stream {stream_name}"
        super().__init__(msg, code="EVENT_NOT_FOUND", **kwargs)
        self.event_id = event_id
        self.stream_name = stream_name
        self.sequence = sequence


class IntegrityViolationError(AppendOnlyStoreError):
    """Integrity violation (hash chain broken, duplicate sequence, etc)."""

    def __init__(
        self, message: str, stream_name: str | None = None, sequence: int | None = None, **kwargs
    ):
        super().__init__(message, code="INTEGRITY_VIOLATION", **kwargs)
        self.stream_name = stream_name
        self.sequence = sequence


class StoreNotInitializedError(AppendOnlyStoreError):
    """Store belum diinisialisasi."""

    def __init__(self, **kwargs):
        super().__init__(
            "Event store not initialized. Call initialize() first.",
            code="STORE_NOT_INITIALIZED",
            **kwargs,
        )


class DuplicateSequenceError(AppendOnlyStoreError):
    """Duplicate sequence number dalam stream."""

    def __init__(self, stream_name: str, sequence: int, **kwargs):
        super().__init__(
            f"Duplicate sequence {sequence} in stream {stream_name}",
            code="DUPLICATE_SEQUENCE",
            **kwargs,
        )
        self.stream_name = stream_name
        self.sequence = sequence


# ============================================================================
# HASH CHAIN EXCEPTIONS
# ============================================================================


class HashChainError(EventStoreError):
    """Base exception untuk hash chain."""

    pass


class HashChainBrokenError(HashChainError):
    """Hash chain terputus (tampering detected)."""

    def __init__(
        self,
        message: str,
        stream_name: str | None = None,
        broken_at_sequence: int | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        **kwargs,
    ):
        super().__init__(message, code="HASH_CHAIN_BROKEN", **kwargs)
        self.stream_name = stream_name
        self.broken_at_sequence = broken_at_sequence
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


class HashChainValidationError(HashChainError):
    """Error dalam validasi hash chain."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="HASH_CHAIN_VALIDATION_ERROR", **kwargs)


# ============================================================================
# SNAPSHOT STORE EXCEPTIONS
# ============================================================================


class SnapshotStoreError(EventStoreError):
    """Base exception untuk snapshot store."""

    pass


class SnapshotNotFoundError(SnapshotStoreError):
    """Snapshot tidak ditemukan."""

    def __init__(
        self,
        aggregate_id: str | None = None,
        aggregate_type: str | None = None,
        version: int | None = None,
        **kwargs,
    ):
        msg = "Snapshot not found"
        if aggregate_id and aggregate_type:
            msg = f"Snapshot not found for {aggregate_type}/{aggregate_id}"
            if version:
                msg += f" at version {version}"
        super().__init__(msg, code="SNAPSHOT_NOT_FOUND", **kwargs)
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        self.version = version


class SnapshotCorruptedError(SnapshotStoreError):
    """Snapshot corrupted (compression/encryption error)."""

    def __init__(self, message: str, snapshot_id: str | None = None, **kwargs):
        super().__init__(message, code="SNAPSHOT_CORRUPTED", **kwargs)
        self.snapshot_id = snapshot_id


# ============================================================================
# COMPRESSION & ENCRYPTION EXCEPTIONS
# ============================================================================


class CompressionError(EventStoreError):
    """Base exception untuk compression service."""

    pass


class DecompressionError(CompressionError):
    """Gagal melakukan dekompresi data."""

    def __init__(self, message: str, algorithm: str | None = None, **kwargs):
        super().__init__(message, code="DECOMPRESSION_ERROR", **kwargs)
        self.algorithm = algorithm


class UnsupportedAlgorithmError(CompressionError):
    """Algoritma kompresi tidak didukung."""

    def __init__(self, algorithm: str, **kwargs):
        super().__init__(
            f"Unsupported compression algorithm: {algorithm}",
            code="UNSUPPORTED_ALGORITHM",
            **kwargs,
        )
        self.algorithm = algorithm


class IntegrityCheckError(CompressionError):
    """Integrity check failed (hash mismatch)."""

    def __init__(self, message: str = "Hash mismatch after decompression", **kwargs):
        super().__init__(message, code="INTEGRITY_CHECK_FAILED", **kwargs)


class EncryptionError(EventStoreError):
    """Error dalam enkripsi/dekripsi snapshot."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="ENCRYPTION_ERROR", **kwargs)


# ============================================================================
# BACKUP & ARCHIVE EXCEPTIONS
# ============================================================================


class BackupArchiverError(EventStoreError):
    """Base exception untuk backup archiver."""

    pass


class BackupNotFoundError(BackupArchiverError):
    """Backup tidak ditemukan."""

    def __init__(self, backup_id: str | None = None, **kwargs):
        msg = f"Backup {backup_id} not found" if backup_id else "Backup not found"
        super().__init__(msg, code="BACKUP_NOT_FOUND", **kwargs)
        self.backup_id = backup_id


class RestoreError(BackupArchiverError):
    """Error saat restore backup."""

    def __init__(self, message: str, backup_id: str | None = None, **kwargs):
        super().__init__(message, code="RESTORE_ERROR", **kwargs)
        self.backup_id = backup_id


class VerificationError(BackupArchiverError):
    """Error verifikasi backup."""

    def __init__(self, message: str, backup_id: str | None = None, **kwargs):
        super().__init__(message, code="VERIFICATION_ERROR", **kwargs)
        self.backup_id = backup_id


# ============================================================================
# TAMPER DETECTION EXCEPTIONS
# ============================================================================


class TamperDetectionError(EventStoreError):
    """Base exception untuk tamper detection."""

    pass


class ScanInterruptedError(TamperDetectionError):
    """Scan interrupted by user or system."""

    def __init__(self, message: str = "Scan was interrupted", **kwargs):
        super().__init__(message, code="SCAN_INTERRUPTED", **kwargs)


# ============================================================================
# INTEGRITY ATTESTATION EXCEPTIONS
# ============================================================================


class IntegrityAttestationError(EventStoreError):
    """Base exception untuk integrity attestation."""

    pass


class AttestationNotFoundError(IntegrityAttestationError):
    """Attestation tidak ditemukan."""

    def __init__(self, attestation_id: str | None = None, **kwargs):
        msg = (
            f"Attestation {attestation_id} not found" if attestation_id else "Attestation not found"
        )
        super().__init__(msg, code="ATTESTATION_NOT_FOUND", **kwargs)
        self.attestation_id = attestation_id


class AttestationVerificationError(IntegrityAttestationError):
    """Gagal memverifikasi attestation."""

    def __init__(self, message: str, attestation_id: str | None = None, **kwargs):
        super().__init__(message, code="ATTESTATION_VERIFICATION_FAILED", **kwargs)
        self.attestation_id = attestation_id


class SigningError(IntegrityAttestationError):
    """Gagal menandatangani attestation."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="SIGNING_ERROR", **kwargs)


# ============================================================================
# METRICS EXCEPTIONS
# ============================================================================


class MetricsCollectionError(EventStoreError):
    """Error saat mengumpulkan metrik."""

    def __init__(self, message: str, **kwargs):
        super().__init__(message, code="METRICS_COLLECTION_ERROR", **kwargs)


# ============================================================================
# SNAPSHOT COMPRESSION EXCEPTIONS (alias untuk kompatibilitas)
# ============================================================================

SnapshotCompressionError = CompressionError


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Base
    "EventStoreError",
    # Append-only store
    "AppendOnlyStoreError",
    "EventNotFoundError",
    "IntegrityViolationError",
    "StoreNotInitializedError",
    "DuplicateSequenceError",
    # Hash chain
    "HashChainError",
    "HashChainBrokenError",
    "HashChainValidationError",
    # Snapshot
    "SnapshotStoreError",
    "SnapshotNotFoundError",
    "SnapshotCorruptedError",
    # Compression
    "CompressionError",
    "DecompressionError",
    "UnsupportedAlgorithmError",
    "IntegrityCheckError",
    "EncryptionError",
    "SnapshotCompressionError",
    # Backup
    "BackupArchiverError",
    "BackupNotFoundError",
    "RestoreError",
    "VerificationError",
    # Tamper detection
    "TamperDetectionError",
    "ScanInterruptedError",
    # Integrity attestation
    "IntegrityAttestationError",
    "AttestationNotFoundError",
    "AttestationVerificationError",
    "SigningError",
    # Metrics
    "MetricsCollectionError",
]
