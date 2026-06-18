#!/usr/bin/env python3
from __future__ import annotations

"""
Module: dr_exceptions.py
Layer: Disaster Recovery

Responsibility:
    Exception khusus untuk modul disaster recovery dengan error codes
    dan detail konteks untuk memudahkan debugging.
"""


class DisasterRecoveryError(Exception):
    """Base exception untuk semua error disaster recovery."""

    def __init__(self, message: str, error_code: str = "DR-0000", details: dict | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}


class BackupError(DisasterRecoveryError):
    """Error saat melakukan backup."""

    def __init__(self, message: str, error_code: str = "DR-BKP-001", details: dict | None = None):
        super().__init__(message, error_code, details)


class RecoveryError(DisasterRecoveryError):
    """Error saat melakukan recovery."""

    def __init__(self, message: str, error_code: str = "DR-RCV-001", details: dict | None = None):
        super().__init__(message, error_code, details)


class RTOViolationError(DisasterRecoveryError):
    """RTO (Recovery Time Objective) tidak terpenuhi."""

    def __init__(self, rto_actual: float, rto_target: float, message: str | None = None):
        msg = message or f"RTO violation: actual {rto_actual}s > target {rto_target}s"
        super().__init__(
            msg,
            error_code="DR-RTO-001",
            details={"rto_actual": rto_actual, "rto_target": rto_target},
        )


class RPOViolationError(DisasterRecoveryError):
    """RPO (Recovery Point Objective) tidak terpenuhi."""

    def __init__(self, rpo_actual: float, rpo_target: float, message: str | None = None):
        msg = message or f"RPO violation: actual {rpo_actual}s > target {rpo_target}s"
        super().__init__(
            msg,
            error_code="DR-RPO-001",
            details={"rpo_actual": rpo_actual, "rpo_target": rpo_target},
        )


class ReplayError(DisasterRecoveryError):
    """Error saat replay event store."""

    def __init__(self, message: str, stream_name: str | None = None, sequence: int | None = None):
        super().__init__(
            message,
            error_code="DR-RPL-001",
            details={"stream_name": stream_name, "sequence": sequence},
        )


class StandbyPromotionError(DisasterRecoveryError):
    """Error saat mempromosikan standby replica."""

    def __init__(self, message: str, standby_host: str | None = None):
        super().__init__(message, error_code="DR-PRM-001", details={"standby_host": standby_host})


class CrossRegionSyncError(DisasterRecoveryError):
    """Error saat sinkronisasi cross-region."""

    def __init__(
        self, message: str, source_region: str | None = None, target_region: str | None = None
    ):
        super().__init__(
            message,
            error_code="DR-CRS-001",
            details={"source_region": source_region, "target_region": target_region},
        )
