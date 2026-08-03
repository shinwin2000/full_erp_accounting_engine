#!/usr/bin/env python3
"""
Package: disaster_recovery
Responsibility: Disaster Recovery untuk ERP Accounting Engine.
Mencakup backup, recovery, failover, RTO/RPO verification, cross-region replay,
dan manajemen bencana tingkat enterprise.

Submodules:
    - backup_full_encrypted_s3: Backup database terenkripsi ke AWS S3
    - dr_exceptions: Exception khusus DR
    - dr_rto_rpo_verification_test: Verifikasi RTO/RPO
    - dr_runbook_accounting_failure: Runbook penanganan kegagalan
    - event_store_replay_cross_region: Replay event store antar region
    - pitr_point_in_time_recovery: Point-in-Time Recovery
    - standby_replica_promotion: Promosi standby replica
"""

from __future__ import annotations

from .backup_full_encrypted_s3 import BackupMetadata, BackupStatus, S3EncryptedBackup
from .dr_exceptions import (
    BackupError,
    CrossRegionSyncError,
    DisasterRecoveryError,
    RecoveryError,
    ReplayError,
    RPOViolationError,
    RTOViolationError,
    StandbyPromotionError,
)
from .dr_rto_rpo_verification_test import DRMetrics, RTO_RPO_VerificationTest
from .dr_runbook_accounting_failure import (
    AccountingFailureRunbook,
    FailureScenario,
    RunbookStatus,
    RunbookStep,
)
from .event_store_replay_cross_region import CrossRegionEventStoreReplayer, ReplayCheckpoint
from .pitr_point_in_time_recovery import PITRRestorePoint, PointInTimeRecovery
from .standby_replica_promotion import ReplicaInfo, ReplicaRole, StandbyReplicaPromoter

__all__ = [
    "AccountingFailureRunbook",
    "BackupError",
    "BackupMetadata",
    "BackupStatus",
    "CrossRegionEventStoreReplayer",
    "CrossRegionSyncError",
    "DRMetrics",
    "DisasterRecoveryError",
    "FailureScenario",
    "PITRRestorePoint",
    "PointInTimeRecovery",
    "RPOViolationError",
    "RTOViolationError",
    "RTO_RPO_VerificationTest",
    "RecoveryError",
    "ReplayCheckpoint",
    "ReplayError",
    "ReplicaInfo",
    "ReplicaRole",
    "RunbookStatus",
    "RunbookStep",
    "S3EncryptedBackup",
    "StandbyPromotionError",
    "StandbyReplicaPromoter",
]
