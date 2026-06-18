#!/usr/bin/env python3
"""
Module: dr_runbook_accounting_failure.py
Layer: Disaster Recovery

Responsibility:
    Runbook untuk menangani kegagalan sistem akuntansi (database down, event store corrupt,
    Kafka broker failure, network partition, cross-region sync failure, dll).

Metode yang ditambahkan:
- Untuk NotificationSeverity, FailureScenario, RunbookStatus, StepStatus: display_name.
- Untuk RunbookStep: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RunbookExecution: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk NotificationManager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk AccountingFailureRunbook: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import smtplib
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.message import EmailMessage
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

try:
    import requests

    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ============================================================================
# Enums (dengan display_name)
# ============================================================================
class FailureScenario(Enum):
    DATABASE_PRIMARY_DOWN = "database_primary_down"
    EVENT_STORE_CORRUPTION = "event_store_corruption"
    KAFKA_BROKER_FAILURE = "kafka_broker_failure"
    S3_BACKUP_UNAVAILABLE = "s3_backup_unavailable"
    NETWORK_PARTITION = "network_partition"
    CROSS_REGION_SYNC_FAILURE = "cross_region_sync_failure"
    APPLICATION_CRASH = "application_crash"
    DISK_FULL = "disk_full"
    MEMORY_LEAK = "memory_leak"
    CONFIGURATION_CORRUPT = "configuration_corrupt"

    def display_name(self) -> str:
        names = {
            FailureScenario.DATABASE_PRIMARY_DOWN: "Database Primary Down",
            FailureScenario.EVENT_STORE_CORRUPTION: "Event Store Corrupt",
            FailureScenario.KAFKA_BROKER_FAILURE: "Kafka Broker Failure",
            FailureScenario.S3_BACKUP_UNAVAILABLE: "S3 Backup Unavailable",
            FailureScenario.NETWORK_PARTITION: "Network Partition",
            FailureScenario.CROSS_REGION_SYNC_FAILURE: "Cross-Region Sync Failure",
            FailureScenario.APPLICATION_CRASH: "Application Crash",
            FailureScenario.DISK_FULL: "Disk Full",
            FailureScenario.MEMORY_LEAK: "Memory Leak",
            FailureScenario.CONFIGURATION_CORRUPT: "Configuration Corrupt",
        }
        return names.get(self, self.value)


class RunbookStatus(Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    ROLLBACK_IN_PROGRESS = "rollback_in_progress"
    ROLLBACK_COMPLETED = "rollback_completed"

    def display_name(self) -> str:
        names = {
            RunbookStatus.NOT_STARTED: "Belum Dimulai",
            RunbookStatus.IN_PROGRESS: "Sedang Berjalan",
            RunbookStatus.COMPLETED: "Selesai",
            RunbookStatus.FAILED: "Gagal",
            RunbookStatus.ABORTED: "Dibatalkan",
            RunbookStatus.ROLLBACK_IN_PROGRESS: "Rollback Berjalan",
            RunbookStatus.ROLLBACK_COMPLETED: "Rollback Selesai",
        }
        return names.get(self, self.value)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"

    def display_name(self) -> str:
        names = {
            StepStatus.PENDING: "Menunggu",
            StepStatus.RUNNING: "Berjalan",
            StepStatus.SUCCESS: "Berhasil",
            StepStatus.FAILED: "Gagal",
            StepStatus.SKIPPED: "Dilewati",
            StepStatus.ROLLED_BACK: "Rollback",
        }
        return names.get(self, self.value)


class NotificationSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    def display_name(self) -> str:
        names = {
            NotificationSeverity.INFO: "Informasi",
            NotificationSeverity.WARNING: "Peringatan",
            NotificationSeverity.ERROR: "Error",
            NotificationSeverity.CRITICAL: "Kritis",
        }
        return names.get(self, self.value)


# ============================================================================
# RunbookStep (dengan entity dasar)
# ============================================================================
class RunbookStep:
    def __init__(
        self,
        name: str,
        action: Callable[[], dict],
        timeout_seconds: int = 60,
        rollback: Callable[[], dict] | None = None,
        retry_count: int = 0,
        retry_delay_seconds: int = 5,
        depends_on: list[str] | None = None,
    ):
        self.name = name
        self.action = action
        self.timeout = timeout_seconds
        self.rollback = rollback
        self.retry_count = retry_count
        self.retry_delay = retry_delay_seconds
        self.depends_on = depends_on or []
        self.status = StepStatus.PENDING
        self.start_time: datetime | None = None
        self.end_time: datetime | None = None
        self.result: dict | None = None
        self.error: str | None = None
        self.retry_attempts = 0
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "name": self.name,
                "status": self.status.value,
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
                "step_name": self.name,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.name:
            errors.append("name is required")
        if not callable(self.action):
            errors.append("action must be callable")
        if self.timeout <= 0:
            errors.append("timeout_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "error": self.error,
            "result": self.result,
            "retry_attempts": self.retry_attempts,
            "depends_on": self.depends_on,
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> RunbookStep:
        action = (action_map or {}).get(data["name"], lambda: {})
        instance = cls(
            name=data["name"],
            action=action,
            timeout_seconds=data.get("timeout", 60),
            rollback=None,
            retry_count=data.get("retry_count", 0),
            retry_delay_seconds=data.get("retry_delay", 5),
            depends_on=data.get("depends_on", []),
        )
        instance.status = StepStatus(data["status"])
        instance.start_time = (
            datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None
        )
        instance.end_time = (
            datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None
        )
        instance.error = data.get("error")
        instance.result = data.get("result")
        instance.retry_attempts = data.get("retry_attempts", 0)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RunbookStep:
        new = RunbookStep(
            name=self.name,
            action=self.action,
            timeout_seconds=self.timeout,
            rollback=self.rollback,
            retry_count=self.retry_count,
            retry_delay_seconds=self.retry_delay,
            depends_on=self.depends_on.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "name": self.name,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RunbookStep:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# RunbookExecution (dengan entity dasar)
# ============================================================================
class RunbookExecution:
    def __init__(
        self,
        execution_id: UUID,
        scenario: FailureScenario,
        started_by: str,
        started_at: datetime | None = None,
    ):
        self.id = execution_id
        self.scenario = scenario
        self.started_by = started_by
        self.started_at = started_at or datetime.now(UTC)
        self.completed_at: datetime | None = None
        self.status = RunbookStatus.NOT_STARTED
        self.steps: list[RunbookStep] = []
        self.failed_step_index: int | None = None
        self.rollback_executed = False
        self.notifications_sent: list[str] = []
        self._hash = self._compute_hash()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "execution_id": str(self.id),
                "scenario": self.scenario.value,
                "status": self.status.value,
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
                "execution_id": str(self.id),
                "details": details,
            }
        )

    def _compute_hash(self) -> str:
        data = {
            "execution_id": str(self.id),
            "scenario": self.scenario.value,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.id:
            errors.append("execution_id is required")
        if not isinstance(self.scenario, FailureScenario):
            errors.append("invalid scenario")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "execution_id": str(self.id),
            "scenario": self.scenario.value,
            "started_by": self.started_by,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "failed_step_index": self.failed_step_index,
            "rollback_executed": self.rollback_executed,
            "notifications_sent": self.notifications_sent,
            "hash": self._hash,
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> RunbookExecution:
        instance = cls(
            execution_id=UUID(data["execution_id"]),
            scenario=FailureScenario(data["scenario"]),
            started_by=data["started_by"],
            started_at=datetime.fromisoformat(data["started_at"]),
        )
        instance.completed_at = (
            datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None
        )
        instance.status = RunbookStatus(data["status"])
        instance.steps = [RunbookStep.from_dict(s, action_map) for s in data.get("steps", [])]
        instance.failed_step_index = data.get("failed_step_index")
        instance.rollback_executed = data.get("rollback_executed", False)
        instance.notifications_sent = data.get("notifications_sent", [])
        instance._hash = data.get("hash", "")
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RunbookExecution:
        new = RunbookExecution(
            execution_id=uuid4(),
            scenario=self.scenario,
            started_by=self.started_by,
            started_at=datetime.now(UTC),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": str(self.id)})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "execution_id": str(self.id),
            "scenario": self.scenario.value,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RunbookExecution:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# NotificationManager (dengan entity dasar)
# ============================================================================
class NotificationManager:
    def __init__(self, smtp_config: dict | None = None, webhook_urls: list[str] | None = None):
        self.smtp_config = smtp_config or {}
        self.webhook_urls = webhook_urls or []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "webhook_count": len(self.webhook_urls),
                "smtp_configured": bool(self.smtp_config),
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

    def send(
        self,
        severity: NotificationSeverity,
        title: str,
        message: str,
        recipients: list[str] | None = None,
    ) -> None:
        self._send_webhook(severity, title, message)
        if recipients and self.smtp_config:
            self._send_email(severity, title, message, recipients)
        logger.info(f"[{severity.value.upper()}] {title}: {message}")
        self._record_audit("SEND", "system", {"severity": severity.value, "title": title})

    def _send_webhook(self, severity: NotificationSeverity, title: str, message: str) -> None:
        if not HAS_REQUESTS:
            return
        for url in self.webhook_urls:
            try:
                payload = {
                    "severity": severity.value,
                    "title": title,
                    "message": message,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
                requests.post(url, json=payload, timeout=5)
            except Exception as e:
                logger.error(f"Failed to send webhook to {url}: {e}")

    def _send_email(
        self, severity: NotificationSeverity, title: str, message: str, recipients: list[str]
    ) -> None:
        try:
            msg = EmailMessage()
            msg["Subject"] = f"[DR Runbook] {severity.value.upper()}: {title}"
            msg["From"] = self.smtp_config.get("from", "dr@erp.com")
            msg["To"] = ", ".join(recipients)
            msg.set_content(f"{message}\n\nTimestamp: {datetime.now(UTC).isoformat()}")
            with smtplib.SMTP(self.smtp_config["host"], self.smtp_config["port"]) as server:
                if self.smtp_config.get("tls"):
                    server.starttls()
                if self.smtp_config.get("user"):
                    server.login(self.smtp_config["user"], self.smtp_config["password"])
                server.send_message(msg)
        except Exception as e:
            logger.error(f"Failed to send email: {e}")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.smtp_config:
            if not self.smtp_config.get("host"):
                errors.append("SMTP host is required")
            if not self.smtp_config.get("port"):
                errors.append("SMTP port is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "webhook_urls": self.webhook_urls,
            "smtp_configured": bool(self.smtp_config),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NotificationManager:
        instance = cls(
            smtp_config=data.get("smtp_config"),
            webhook_urls=data.get("webhook_urls", []),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> NotificationManager:
        new = NotificationManager(
            smtp_config=self.smtp_config.copy() if self.smtp_config else None,
            webhook_urls=self.webhook_urls.copy(),
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "webhook_count": len(self.webhook_urls),
            "smtp_configured": bool(self.smtp_config),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> NotificationManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.webhook_urls.clear()
        self.smtp_config.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []


# ============================================================================
# AccountingFailureRunbook Core (dengan entity dasar)
# ============================================================================
class AccountingFailureRunbook:
    def __init__(
        self, scenario: FailureScenario, notification_manager: NotificationManager | None = None
    ):
        self.scenario = scenario
        self.notification_manager = notification_manager or NotificationManager()
        self.execution: RunbookExecution | None = None
        self._steps: list[RunbookStep] = []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        self._build_runbook()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "scenario": self.scenario.value,
                "steps_count": len(self._steps),
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

    def _build_runbook(self) -> None:
        if self.scenario == FailureScenario.DATABASE_PRIMARY_DOWN:
            self._steps = self._build_db_failover_runbook()
        elif self.scenario == FailureScenario.EVENT_STORE_CORRUPTION:
            self._steps = self._build_event_store_replay_runbook()
        elif self.scenario == FailureScenario.KAFKA_BROKER_FAILURE:
            self._steps = self._build_kafka_failover_runbook()
        elif self.scenario == FailureScenario.S3_BACKUP_UNAVAILABLE:
            self._steps = self._build_s3_backup_runbook()
        elif self.scenario == FailureScenario.NETWORK_PARTITION:
            self._steps = self._build_network_partition_runbook()
        elif self.scenario == FailureScenario.CROSS_REGION_SYNC_FAILURE:
            self._steps = self._build_cross_region_sync_runbook()
        else:
            self._steps = self._build_generic_runbook()

    def _build_db_failover_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("detect_failure", self._check_db_health, timeout=10, retry_count=2),
            RunbookStep(
                "promote_standby",
                self._promote_standby,
                timeout=120,
                rollback=self._demote_standby,
                retry_count=1,
            ),
            RunbookStep(
                "repoint_applications",
                self._repoint_connections,
                timeout=30,
                depends_on=["promote_standby"],
            ),
            RunbookStep("verify_recovery", self._verify_db_recovery, timeout=60),
            RunbookStep("notify_team", self._send_alert, timeout=10),
        ]

    def _build_event_store_replay_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("stop_event_ingestion", self._stop_ingestion, timeout=10),
            RunbookStep("validate_corruption", self._validate_corruption_scope, timeout=60),
            RunbookStep(
                "replay_from_snapshot", self._replay_event_store, timeout=600, retry_count=2
            ),
            RunbookStep("verify_consistency", self._verify_event_store_consistency, timeout=60),
            RunbookStep("restart_ingestion", self._restart_ingestion, timeout=10),
        ]

    def _build_kafka_failover_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("switch_to_dlq", self._enable_dead_letter_queue, timeout=15),
            RunbookStep(
                "failover_kafka_broker",
                self._promote_kafka_broker,
                timeout=60,
                rollback=self._demote_kafka_broker,
            ),
            RunbookStep("replay_dlq", self._replay_dead_letter_queue, timeout=300),
            RunbookStep("verify_messages", self._verify_kafka_messages, timeout=60),
        ]

    def _build_s3_backup_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("check_alternative_region", self._check_s3_alternative_region, timeout=30),
            RunbookStep("use_local_cache", self._use_local_backup_cache, timeout=60),
            RunbookStep("restore_from_alternative", self._restore_from_alternative_s3, timeout=300),
        ]

    def _build_network_partition_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("detect_partition", self._detect_network_partition, timeout=10),
            RunbookStep("isolate_split_brain", self._isolate_split_brain, timeout=30),
            RunbookStep("switch_to_read_only", self._switch_to_read_only_mode, timeout=15),
            RunbookStep(
                "wait_for_healing", self._wait_for_network_healing, timeout=600, retry_count=0
            ),
            RunbookStep("restore_full_operation", self._restore_full_operation, timeout=60),
        ]

    def _build_cross_region_sync_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("check_sync_status", self._check_cross_region_sync, timeout=30),
            RunbookStep("initiate_resync", self._initiate_resync, timeout=300),
            RunbookStep("verify_sync_complete", self._verify_sync_complete, timeout=120),
        ]

    def _build_generic_runbook(self) -> list[RunbookStep]:
        return [
            RunbookStep("notify_team", self._send_alert, timeout=10),
            RunbookStep("isolate_failure", self._isolate, timeout=30),
            RunbookStep("attempt_auto_recovery", self._auto_recover, timeout=180),
            RunbookStep("escalate_if_needed", self._escalate, timeout=60),
        ]

    # ------------------------------------------------------------------------
    # Action Implementations (placeholder - override in production)
    # ------------------------------------------------------------------------
    def _check_db_health(self) -> dict:
        return {"healthy": False, "error": "connection timeout"}

    def _promote_standby(self) -> dict:
        return {"promoted": True, "new_primary": "db-standby.internal"}

    def _demote_standby(self) -> dict:
        return {"demoted": True}

    def _repoint_connections(self) -> dict:
        return {"updated": True, "services": ["journal", "ledger"]}

    def _verify_db_recovery(self) -> dict:
        return {"recovered": True}

    def _send_alert(self) -> dict:
        return {"alert_sent": True}

    def _stop_ingestion(self) -> dict:
        return {"stopped": True}

    def _validate_corruption_scope(self) -> dict:
        return {"corrupt_events": 0}

    def _replay_event_store(self) -> dict:
        return {"replayed": 150000}

    def _verify_event_store_consistency(self) -> dict:
        return {"consistent": True}

    def _restart_ingestion(self) -> dict:
        return {"restarted": True}

    def _enable_dead_letter_queue(self) -> dict:
        return {"dlq_enabled": True}

    def _promote_kafka_broker(self) -> dict:
        return {"new_controller": "kafka-2.internal"}

    def _demote_kafka_broker(self) -> dict:
        return {"demoted": True}

    def _replay_dead_letter_queue(self) -> dict:
        return {"replayed_messages": 1250}

    def _verify_kafka_messages(self) -> dict:
        return {"verified": True}

    def _check_s3_alternative_region(self) -> dict:
        return {"alternative_available": True}

    def _use_local_backup_cache(self) -> dict:
        return {"cache_hit": True}

    def _restore_from_alternative_s3(self) -> dict:
        return {"restored": True}

    def _detect_network_partition(self) -> dict:
        return {"partition_detected": True}

    def _isolate_split_brain(self) -> dict:
        return {"isolated": True}

    def _switch_to_read_only_mode(self) -> dict:
        return {"read_only_activated": True}

    def _wait_for_network_healing(self) -> dict:
        return {"healed": True}

    def _restore_full_operation(self) -> dict:
        return {"full_operation_restored": True}

    def _check_cross_region_sync(self) -> dict:
        return {"sync_lag_seconds": 30}

    def _initiate_resync(self) -> dict:
        return {"resync_initiated": True}

    def _verify_sync_complete(self) -> dict:
        return {"sync_complete": True}

    def _isolate(self) -> dict:
        return {"isolated": True}

    def _auto_recover(self) -> dict:
        return {"auto_recovered": False}

    def _escalate(self) -> dict:
        return {"escalated_to": "level-2-support"}

    # ------------------------------------------------------------------------
    # Execution Engine
    # ------------------------------------------------------------------------
    def execute(self, started_by: str = "system") -> RunbookExecution:
        execution = RunbookExecution(
            execution_id=uuid4(),
            scenario=self.scenario,
            started_by=started_by,
        )
        execution.steps = self._steps
        execution.status = RunbookStatus.IN_PROGRESS
        self.execution = execution

        self.notification_manager.send(
            severity=NotificationSeverity.INFO,
            title=f"DR Runbook Started: {self.scenario.value}",
            message=f"Executing runbook for {self.scenario.value} by {started_by}",
            recipients=self._get_recipients(),
        )

        for idx, step in enumerate(execution.steps):
            if step.status != StepStatus.PENDING:
                continue
            if step.depends_on:
                deps_met = all(
                    any(
                        s.name == dep and s.status == StepStatus.SUCCESS
                        for s in execution.steps[:idx]
                    )
                    for dep in step.depends_on
                )
                if not deps_met:
                    step.status = StepStatus.SKIPPED
                    step.error = "Dependencies not met"
                    continue

            step.status = StepStatus.RUNNING
            step.start_time = datetime.now(UTC)
            success = False
            for attempt in range(step.retry_count + 1):
                try:
                    result = self._run_with_timeout(step.action, step.timeout)
                    step.result = result
                    step.status = StepStatus.SUCCESS
                    success = True
                    break
                except TimeoutError:
                    step.error = f"Timeout after {step.timeout}s (attempt {attempt + 1})"
                    if attempt < step.retry_count:
                        time.sleep(step.retry_delay)
                except Exception as e:
                    step.error = str(e)
                    if attempt < step.retry_count:
                        time.sleep(step.retry_delay)
            step.end_time = datetime.now(UTC)
            if not success:
                execution.failed_step_index = idx
                execution.status = RunbookStatus.FAILED
                self.notification_manager.send(
                    severity=NotificationSeverity.ERROR,
                    title=f"DR Runbook Failed: {self.scenario.value}",
                    message=f"Step '{step.name}' failed: {step.error}",
                    recipients=self._get_recipients(),
                )
                if self._should_rollback():
                    self._execute_rollback(execution)
                execution.completed_at = datetime.now(UTC)
                execution._hash = execution._compute_hash()
                self._record_audit(
                    "EXECUTE_FAILED",
                    started_by,
                    {"scenario": self.scenario.value, "failed_step": step.name},
                )
                return execution

        execution.status = RunbookStatus.COMPLETED
        execution.completed_at = datetime.now(UTC)
        execution._hash = execution._compute_hash()
        self.notification_manager.send(
            severity=NotificationSeverity.INFO,
            title=f"DR Runbook Completed: {self.scenario.value}",
            message="All steps completed successfully",
            recipients=self._get_recipients(),
        )
        self._record_audit("EXECUTE_SUCCESS", started_by, {"scenario": self.scenario.value})
        return execution

    def _run_with_timeout(self, func: Callable, timeout: float) -> dict:
        result_container = []
        error_container = []

        def target():
            try:
                result_container.append(func())
            except Exception as e:
                error_container.append(e)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError()
        if error_container:
            raise error_container[0]
        return result_container[0] if result_container else {}

    def _should_rollback(self) -> bool:
        return self.scenario in [
            FailureScenario.DATABASE_PRIMARY_DOWN,
            FailureScenario.EVENT_STORE_CORRUPTION,
            FailureScenario.KAFKA_BROKER_FAILURE,
        ]

    def _execute_rollback(self, execution: RunbookExecution) -> None:
        execution.status = RunbookStatus.ROLLBACK_IN_PROGRESS
        for step in reversed(execution.steps):
            if step.status == StepStatus.SUCCESS and step.rollback:
                try:
                    step.rollback()
                    step.status = StepStatus.ROLLED_BACK
                except Exception as e:
                    logger.error(f"Rollback failed for step {step.name}: {e}")
        execution.rollback_executed = True
        execution.status = RunbookStatus.ROLLBACK_COMPLETED

    def _get_recipients(self) -> list[str]:
        return ["dr-team@erp.com", "oncall@erp.com"]

    def get_execution_status(self) -> dict | None:
        if not self.execution:
            return None
        return {
            "execution_id": str(self.execution.id),
            "scenario": self.execution.scenario.value,
            "status": self.execution.status.value,
            "started_at": self.execution.started_at.isoformat(),
            "completed_at": self.execution.completed_at.isoformat()
            if self.execution.completed_at
            else None,
            "failed_step": self.execution.failed_step_index,
            "steps": [s.to_dict() for s in self.execution.steps],
        }

    def export_to_json(self, file_path: str) -> None:
        if self.execution:
            with open(file_path, "w") as f:
                json.dump(self.execution.to_dict(), f, indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.scenario, FailureScenario):
            errors.append("invalid scenario")
        for step in self._steps:
            res = step.validate()
            if not res["is_valid"]:
                errors.extend([f"Step {step.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario.value,
            "steps": [s.to_dict() for s in self._steps],
            "version": self._version,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], action_map: dict[str, Callable] | None = None
    ) -> AccountingFailureRunbook:
        scenario = FailureScenario(data["scenario"])
        instance = cls(scenario=scenario)
        instance._steps = [RunbookStep.from_dict(s, action_map) for s in data.get("steps", [])]
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> AccountingFailureRunbook:
        new = AccountingFailureRunbook(
            scenario=self.scenario, notification_manager=self.notification_manager.clone()
        )
        new._steps = [s.clone() for s in self._steps]
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "scenario": self.scenario.value,
            "steps_count": len(self._steps),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AccountingFailureRunbook:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.execution = None
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._build_runbook()
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    runbook = AccountingFailureRunbook(FailureScenario.DATABASE_PRIMARY_DOWN)
    result = runbook.execute(started_by="admin")
    print(f"Runbook execution result: {result.status.value}")
    print(json.dumps(result.to_dict(), indent=2, default=str))
    runbook.export_to_json("runbook_execution.json")
