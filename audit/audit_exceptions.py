#!/usr/bin/env python3
"""
Module: audit_exceptions.py
Layer: Audit
Responsibility: Mendefinisikan semua exception untuk audit module.
"""

from __future__ import annotations


class AuditError(Exception):
    """Base exception untuk audit module."""

    pass


class HashChainError(AuditError):
    """Base exception untuk hash chain."""

    pass


class HashChainBrokenError(HashChainError):
    """Hash chain terputus."""

    pass


class TamperDetectionError(AuditError):
    """Error saat deteksi tampering."""

    pass


class ForensicReplayError(AuditError):
    """Error saat forensic replay."""

    pass


class StreamNotFoundError(ForensicReplayError):
    """Stream tidak ditemukan."""

    pass


class GapDetectionError(AuditError):
    """Error saat gap detection."""

    pass


class DuplicateDetectionError(AuditError):
    """Error saat duplicate detection."""

    pass


class ForensicReportError(AuditError):
    """Error saat generate forensic report."""

    pass


class IntentRecorderError(AuditError):
    """Error saat intent recorder."""

    pass


class IntentNotFoundError(IntentRecorderError):
    """Intent tidak ditemukan."""

    pass


class AttestationError(AuditError):
    """Error saat attestation."""

    pass


class AttestationNotFoundError(AttestationError):
    """Attestation tidak ditemukan."""

    pass


class AttestationVerificationError(AttestationError):
    """Verifikasi attestation gagal."""

    pass


class AuditMetricsError(AuditError):
    """Error saat audit metrics."""

    pass


__all__ = [
    "AttestationError",
    "AttestationNotFoundError",
    "AttestationVerificationError",
    "AuditError",
    "AuditMetricsError",
    "DuplicateDetectionError",
    "ForensicReplayError",
    "ForensicReportError",
    "GapDetectionError",
    "HashChainBrokenError",
    "HashChainError",
    "IntentNotFoundError",
    "IntentRecorderError",
    "StreamNotFoundError",
    "TamperDetectionError",
]
