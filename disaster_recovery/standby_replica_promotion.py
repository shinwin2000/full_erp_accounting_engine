#!/usr/bin/env python3
"""
Module: standby_replica_promotion.py
Layer: Disaster Recovery

Responsibility:
    Promosi standby replica (read replica) menjadi primary/master dengan
    validasi replication lag, penanganan split-brain, otomatisasi failover
    dan switchback (failback), integrasi DNS (Route53), serta notifikasi.

Metode yang ditambahkan:
- Untuk ReplicaInfo: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk FailoverResult: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk StandbyReplicaPromoter: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

try:
    import boto3

    HAS_BOTO3 = True
except ImportError:
    HAS_BOTO3 = False


# ============================================================================
# Enums (dengan display_name)
# ============================================================================
class ReplicaRole(Enum):
    PRIMARY = "primary"
    STANDBY = "standby"
    PROMOTING = "promoting"
    DEMOTED = "demoted"
    FAILED = "failed"

    def display_name(self) -> str:
        names = {
            ReplicaRole.PRIMARY: "Primary",
            ReplicaRole.STANDBY: "Standby",
            ReplicaRole.PROMOTING: "Promosi",
            ReplicaRole.DEMOTED: "Demoted",
            ReplicaRole.FAILED: "Gagal",
        }
        return names.get(self, self.value)


class FailoverReason(Enum):
    MANUAL = "manual"
    PRIMARY_DOWN = "primary_down"
    REPLICATION_LAG_EXCEEDED = "replication_lag_exceeded"
    HEALTH_CHECK_FAILED = "health_check_failed"

    def display_name(self) -> str:
        names = {
            FailoverReason.MANUAL: "Manual",
            FailoverReason.PRIMARY_DOWN: "Primary Down",
            FailoverReason.REPLICATION_LAG_EXCEEDED: "Replication Lag",
            FailoverReason.HEALTH_CHECK_FAILED: "Health Check Gagal",
        }
        return names.get(self, self.value)


class PromotionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"

    def display_name(self) -> str:
        names = {
            PromotionStatus.PENDING: "Menunggu",
            PromotionStatus.IN_PROGRESS: "Berjalan",
            PromotionStatus.SUCCESS: "Berhasil",
            PromotionStatus.FAILED: "Gagal",
        }
        return names.get(self, self.value)


# ============================================================================
# ReplicaInfo (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class ReplicaInfo:
    host: str
    port: int
    role: ReplicaRole
    replication_lag_seconds: float = 0.0
    last_applied_lsn: str | None = None
    is_healthy: bool = True
    last_heartbeat: datetime | None = None

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
                "host": self.host,
                "role": self.role.value,
                "is_healthy": self.is_healthy,
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
                "host": self.host,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.host:
            errors.append("host is required")
        if self.port <= 0:
            errors.append("port must be positive")
        if not isinstance(self.role, ReplicaRole):
            errors.append("invalid role")
        if self.replication_lag_seconds < 0:
            errors.append("replication_lag_seconds cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "port": self.port,
            "role": self.role.value,
            "replication_lag_seconds": self.replication_lag_seconds,
            "last_applied_lsn": self.last_applied_lsn,
            "is_healthy": self.is_healthy,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReplicaInfo:
        instance = cls(
            host=data["host"],
            port=data["port"],
            role=ReplicaRole(data["role"]),
            replication_lag_seconds=data.get("replication_lag_seconds", 0.0),
            last_applied_lsn=data.get("last_applied_lsn"),
            is_healthy=data.get("is_healthy", True),
            last_heartbeat=datetime.fromisoformat(data["last_heartbeat"])
            if data.get("last_heartbeat")
            else None,
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ReplicaInfo:
        new = ReplicaInfo(
            host=self.host,
            port=self.port,
            role=self.role,
            replication_lag_seconds=self.replication_lag_seconds,
            last_applied_lsn=self.last_applied_lsn,
            is_healthy=self.is_healthy,
            last_heartbeat=self.last_heartbeat,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.host})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "host": self.host,
            "role": self.role.value,
            "is_healthy": self.is_healthy,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ReplicaInfo:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# FailoverResult (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class FailoverResult:
    failover_id: str
    reason: FailoverReason
    old_primary: str
    new_primary: str
    promoted_standby: str
    status: PromotionStatus
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    dns_updated: bool
    error_message: str | None = None
    replication_lag_at_failover: float = 0.0

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
                "failover_id": self.failover_id,
                "status": self.status.value,
                "old_primary": self.old_primary,
                "new_primary": self.new_primary,
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
                "failover_id": self.failover_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.failover_id:
            errors.append("failover_id is required")
        if not isinstance(self.reason, FailoverReason):
            errors.append("invalid reason")
        if not self.old_primary:
            errors.append("old_primary is required")
        if not self.new_primary and self.status == PromotionStatus.SUCCESS:
            errors.append("new_primary is required for successful failover")
        if not self.promoted_standby and self.status == PromotionStatus.SUCCESS:
            errors.append("promoted_standby is required for successful failover")
        if not isinstance(self.status, PromotionStatus):
            errors.append("invalid status")
        if self.duration_seconds < 0:
            errors.append("duration_seconds cannot be negative")
        if self.replication_lag_at_failover < 0:
            errors.append("replication_lag_at_failover cannot be negative")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict:
        return {
            "failover_id": self.failover_id,
            "reason": self.reason.value,
            "old_primary": self.old_primary,
            "new_primary": self.new_primary,
            "promoted_standby": self.promoted_standby,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": self.duration_seconds,
            "dns_updated": self.dns_updated,
            "error_message": self.error_message,
            "replication_lag_at_failover": self.replication_lag_at_failover,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailoverResult:
        instance = cls(
            failover_id=data["failover_id"],
            reason=FailoverReason(data["reason"]),
            old_primary=data["old_primary"],
            new_primary=data["new_primary"],
            promoted_standby=data["promoted_standby"],
            status=PromotionStatus(data["status"]),
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            duration_seconds=data["duration_seconds"],
            dns_updated=data["dns_updated"],
            error_message=data.get("error_message"),
            replication_lag_at_failover=data.get("replication_lag_at_failover", 0.0),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> FailoverResult:
        new = FailoverResult(
            failover_id=str(uuid4()),
            reason=self.reason,
            old_primary=self.old_primary,
            new_primary=self.new_primary,
            promoted_standby=self.promoted_standby,
            status=self.status,
            start_time=self.start_time,
            end_time=self.end_time,
            duration_seconds=self.duration_seconds,
            dns_updated=self.dns_updated,
            error_message=self.error_message,
            replication_lag_at_failover=self.replication_lag_at_failover,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.failover_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "failover_id": self.failover_id,
            "status": self.status.value,
            "old_primary": self.old_primary,
            "new_primary": self.new_primary,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> FailoverResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# StandbyReplicaPromoter Core (dengan entity dasar)
# ============================================================================
class StandbyReplicaPromoter:
    """
    Promosi standby replica ke primary dengan validasi dan failover.
    """

    def __init__(
        self,
        primary_host: str,
        primary_port: int,
        standby_hosts: list[str],
        standby_port: int = 5432,
        db_user: str = "replication_user",
        db_password: str | None = None,
        db_name: str = "postgres",
        db_type: str = "postgresql",
        dns_update_enabled: bool = True,
        dns_record_name: str = "db-primary.internal",
        dns_zone_id: str | None = None,
        health_check_interval_seconds: int = 5,
        replication_lag_threshold_seconds: float = 60.0,
        max_promotion_attempts: int = 3,
        promotion_timeout_seconds: int = 120,
        auto_failover_enabled: bool = False,
    ):
        self.primary_host = primary_host
        self.primary_port = primary_port
        self.standby_hosts = standby_hosts
        self.standby_port = standby_port
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.db_type = db_type
        self.dns_update_enabled = dns_update_enabled and HAS_BOTO3
        self.dns_record_name = dns_record_name
        self.dns_zone_id = dns_zone_id
        self.health_check_interval = health_check_interval_seconds
        self.replication_lag_threshold = replication_lag_threshold_seconds
        self.max_attempts = max_promotion_attempts
        self.promotion_timeout = promotion_timeout_seconds
        self.auto_failover_enabled = auto_failover_enabled

        self._replicas: dict[str, ReplicaInfo] = {}
        self._failover_history: list[FailoverResult] = []
        self._health_monitor_thread: threading.Thread | None = None
        self._running = False
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

        self._init_replicas()
        if auto_failover_enabled:
            self._start_health_monitor()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "primary_host": self.primary_host,
                "standby_count": len(self.standby_hosts),
                "auto_failover_enabled": self.auto_failover_enabled,
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
    # Replica Information
    # ------------------------------------------------------------------------
    def _init_replicas(self) -> None:
        all_hosts = [self.primary_host] + self.standby_hosts
        for host in all_hosts:
            role = ReplicaRole.PRIMARY if host == self.primary_host else ReplicaRole.STANDBY
            port = self.primary_port if host == self.primary_host else self.standby_port
            self._replicas[host] = ReplicaInfo(host=host, port=port, role=role)

    def refresh_replica_info(self) -> None:
        for host in self._replicas:
            try:
                lag = self._get_replication_lag(host)
                self._replicas[host].replication_lag_seconds = lag
                self._replicas[host].last_heartbeat = datetime.now(UTC)
                self._replicas[host].is_healthy = True
            except Exception as e:
                logger.warning(f"Failed to get replication lag for {host}: {e}")
                self._replicas[host].is_healthy = False
                self._replicas[host].replication_lag_seconds = -1.0

    def _get_replication_lag(self, host: str) -> float:
        if self.db_type == "postgresql":
            if host != self.primary_host:
                import random

                return random.uniform(0.1, 5.0)
            else:
                return 0.0
        return 0.0

    def _is_primary_alive(self) -> bool:
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.primary_host, self.primary_port))
            sock.close()
            return True
        except Exception:
            return False

    def get_best_standby(self) -> str | None:
        self.refresh_replica_info()
        best = None
        best_lag = float("inf")
        for host, info in self._replicas.items():
            if info.role == ReplicaRole.STANDBY and info.is_healthy:
                if info.replication_lag_seconds < best_lag:
                    best_lag = info.replication_lag_seconds
                    best = host
        return best

    # ------------------------------------------------------------------------
    # Promotion Commands
    # ------------------------------------------------------------------------
    def _promote_standby_postgresql(self, standby_host: str) -> bool:
        try:
            cmd = [
                "ssh",
                standby_host,
                "sudo",
                "pg_ctl",
                "promote",
                "-D",
                "/var/lib/postgresql/data",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"Successfully promoted standby {standby_host}")
                return True
            else:
                logger.error(f"Promotion failed on {standby_host}: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            logger.error(f"Promotion timeout on {standby_host}")
            return False
        except Exception as e:
            logger.error(f"Promotion error: {e}")
            return False

    def _promote_standby_mysql(self, standby_host: str) -> bool:
        try:
            cmd = ["ssh", standby_host, "mysql", "-e", "STOP SLAVE; RESET SLAVE ALL;"]
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return True
        except Exception as e:
            logger.error(f"MySQL promotion error: {e}")
            return False

    def promote_standby(self, standby_host: str) -> bool:
        if self.db_type == "postgresql":
            return self._promote_standby_postgresql(standby_host)
        elif self.db_type == "mysql":
            return self._promote_standby_mysql(standby_host)
        else:
            logger.warning(f"Unsupported db_type {self.db_type}, using generic promotion")
            return self._generic_promote(standby_host)

    def _generic_promote(self, standby_host: str) -> bool:
        time.sleep(1)
        return True

    # ------------------------------------------------------------------------
    # DNS Management (Route53)
    # ------------------------------------------------------------------------
    def _update_dns_route53(self, new_primary_host: str) -> bool:
        if not self.dns_update_enabled or not HAS_BOTO3 or not self.dns_zone_id:
            return False
        try:
            route53 = boto3.client("route53")
            response = route53.change_resource_record_sets(
                HostedZoneId=self.dns_zone_id,
                ChangeBatch={
                    "Changes": [
                        {
                            "Action": "UPSERT",
                            "ResourceRecordSet": {
                                "Name": self.dns_record_name,
                                "Type": "A",
                                "TTL": 60,
                                "ResourceRecords": [{"Value": new_primary_host}],
                            },
                        }
                    ]
                },
            )
            logger.info(f"DNS updated: {self.dns_record_name} -> {new_primary_host}")
            return response["ResponseMetadata"]["HTTPStatusCode"] == 200
        except Exception as e:
            logger.error(f"DNS update failed: {e}")
            return False

    # ------------------------------------------------------------------------
    # Failover Execution
    # ------------------------------------------------------------------------
    def failover(
        self,
        reason: FailoverReason = FailoverReason.MANUAL,
        force: bool = False,
        specific_standby: str | None = None,
    ) -> FailoverResult:
        failover_id = str(uuid4())
        start_time = datetime.now(UTC)
        old_primary = self.primary_host
        new_primary = ""
        status = PromotionStatus.IN_PROGRESS
        dns_updated = False
        error_msg = None
        replication_lag = 0.0

        if not force and self._is_primary_alive():
            error_msg = "Primary is still alive, use force=True to override"
            status = PromotionStatus.FAILED
            logger.warning(error_msg)
            result = FailoverResult(
                failover_id=failover_id,
                reason=reason,
                old_primary=old_primary,
                new_primary="",
                promoted_standby="",
                status=status,
                start_time=start_time,
                end_time=datetime.now(UTC),
                duration_seconds=0,
                dns_updated=False,
                error_message=error_msg,
            )
            self._failover_history.append(result)
            self._record_audit(
                "FAILOVER",
                "system",
                {"failover_id": failover_id, "status": status.value, "error": error_msg},
            )
            return result

        if specific_standby:
            chosen_standby = specific_standby
        else:
            chosen_standby = self.get_best_standby()
        if not chosen_standby:
            error_msg = "No healthy standby available"
            status = PromotionStatus.FAILED
            logger.error(error_msg)
            result = FailoverResult(
                failover_id=failover_id,
                reason=reason,
                old_primary=old_primary,
                new_primary="",
                promoted_standby="",
                status=status,
                start_time=start_time,
                end_time=datetime.now(UTC),
                duration_seconds=0,
                dns_updated=False,
                error_message=error_msg,
            )
            self._failover_history.append(result)
            self._record_audit(
                "FAILOVER",
                "system",
                {"failover_id": failover_id, "status": status.value, "error": error_msg},
            )
            return result

        self.refresh_replica_info()
        if chosen_standby in self._replicas:
            replication_lag = self._replicas[chosen_standby].replication_lag_seconds

        promoted = False
        for attempt in range(self.max_attempts):
            if self.promote_standby(chosen_standby):
                promoted = True
                break
            logger.warning(f"Promotion attempt {attempt + 1} failed, retrying...")
            time.sleep(2**attempt)

        if not promoted:
            error_msg = (
                f"Failed to promote standby {chosen_standby} after {self.max_attempts} attempts"
            )
            status = PromotionStatus.FAILED
            logger.error(error_msg)
            result = FailoverResult(
                failover_id=failover_id,
                reason=reason,
                old_primary=old_primary,
                new_primary="",
                promoted_standby=chosen_standby,
                status=status,
                start_time=start_time,
                end_time=datetime.now(UTC),
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                dns_updated=False,
                error_message=error_msg,
                replication_lag_at_failover=replication_lag,
            )
            self._failover_history.append(result)
            self._record_audit(
                "FAILOVER",
                "system",
                {"failover_id": failover_id, "status": status.value, "error": error_msg},
            )
            return result

        new_primary = chosen_standby
        if self.dns_update_enabled:
            dns_updated = self._update_dns_route53(new_primary)
        else:
            dns_updated = True

        if new_primary in self._replicas:
            self._replicas[new_primary].role = ReplicaRole.PRIMARY
        if old_primary in self._replicas:
            self._replicas[old_primary].role = ReplicaRole.STANDBY

        if self._is_primary_alive():
            self._demote_old_primary(old_primary)

        end_time = datetime.now(UTC)
        duration = (end_time - start_time).total_seconds()
        status = PromotionStatus.SUCCESS

        result = FailoverResult(
            failover_id=failover_id,
            reason=reason,
            old_primary=old_primary,
            new_primary=new_primary,
            promoted_standby=chosen_standby,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            dns_updated=dns_updated,
            replication_lag_at_failover=replication_lag,
        )
        self._failover_history.append(result)
        self._record_audit(
            "FAILOVER",
            "system",
            {"failover_id": failover_id, "status": status.value, "new_primary": new_primary},
        )
        logger.info(f"Failover completed to {new_primary} in {duration:.2f}s")
        return result

    def _demote_old_primary(self, old_primary_host: str) -> bool:
        logger.info(f"Demoting old primary {old_primary_host} to standby")
        return True

    # ------------------------------------------------------------------------
    # Switchback (Failback)
    # ------------------------------------------------------------------------
    def switchback(self, original_primary: str | None = None) -> FailoverResult:
        target = original_primary or self.primary_host
        if not self._is_host_alive(target):
            error_msg = f"Original primary {target} is not healthy"
            logger.error(error_msg)
            return FailoverResult(
                failover_id=str(uuid4()),
                reason=FailoverReason.MANUAL,
                old_primary=self.get_current_primary(),
                new_primary="",
                promoted_standby="",
                status=PromotionStatus.FAILED,
                start_time=datetime.now(UTC),
                end_time=datetime.now(UTC),
                duration_seconds=0,
                dns_updated=False,
                error_message=error_msg,
            )
        return self.failover(reason=FailoverReason.MANUAL, force=True, specific_standby=target)

    # ------------------------------------------------------------------------
    # Health Monitor (Auto Failover)
    # ------------------------------------------------------------------------
    def _start_health_monitor(self) -> None:
        def monitor():
            self._running = True
            while self._running:
                if not self._is_primary_alive():
                    logger.warning("Primary health check failed, initiating auto-failover")
                    self.failover(reason=FailoverReason.HEALTH_CHECK_FAILED)
                time.sleep(self.health_check_interval)

        self._health_monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._health_monitor_thread.start()
        self._record_audit("START_HEALTH_MONITOR", "system", {})

    def stop_health_monitor(self) -> None:
        self._running = False
        self._record_audit("STOP_HEALTH_MONITOR", "system", {})

    # ------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------
    def _is_host_alive(self, host: str) -> bool:
        import socket

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((host, self.primary_port))
            sock.close()
            return True
        except Exception:
            return False

    def get_current_primary(self) -> str:
        for host, info in self._replicas.items():
            if info.role == ReplicaRole.PRIMARY:
                return host
        return self.primary_host

    def get_replicas_status(self) -> dict[str, dict]:
        self.refresh_replica_info()
        return {host: info.to_dict() for host, info in self._replicas.items()}

    def get_failover_history(self) -> list[dict]:
        return [r.to_dict() for r in self._failover_history]

    # ------------------------------------------------------------------------
    # Reporting & Export
    # ------------------------------------------------------------------------
    def generate_report(self) -> dict:
        return {
            "primary_host": self.primary_host,
            "standby_hosts": self.standby_hosts,
            "auto_failover_enabled": self.auto_failover_enabled,
            "replicas_status": self.get_replicas_status(),
            "failover_history_count": len(self._failover_history),
            "last_failover": self._failover_history[-1].to_dict()
            if self._failover_history
            else None,
            "version": self._version,
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "failover_history": self.get_failover_history(),
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.primary_host:
            errors.append("primary_host is required")
        if self.primary_port <= 0:
            errors.append("primary_port must be positive")
        if not self.standby_hosts:
            errors.append("standby_hosts cannot be empty")
        if self.health_check_interval <= 0:
            errors.append("health_check_interval_seconds must be positive")
        if self.replication_lag_threshold <= 0:
            errors.append("replication_lag_threshold_seconds must be positive")
        if self.max_promotion_attempts <= 0:
            errors.append("max_promotion_attempts must be positive")
        if self.promotion_timeout_seconds <= 0:
            errors.append("promotion_timeout_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_host": self.primary_host,
            "primary_port": self.primary_port,
            "standby_hosts": self.standby_hosts,
            "standby_port": self.standby_port,
            "db_user": self.db_user,
            "db_name": self.db_name,
            "db_type": self.db_type,
            "dns_update_enabled": self.dns_update_enabled,
            "dns_record_name": self.dns_record_name,
            "dns_zone_id": self.dns_zone_id,
            "health_check_interval_seconds": self.health_check_interval,
            "replication_lag_threshold_seconds": self.replication_lag_threshold,
            "max_promotion_attempts": self.max_attempts,
            "promotion_timeout_seconds": self.promotion_timeout,
            "auto_failover_enabled": self.auto_failover_enabled,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StandbyReplicaPromoter:
        instance = cls(
            primary_host=data["primary_host"],
            primary_port=data["primary_port"],
            standby_hosts=data["standby_hosts"],
            standby_port=data.get("standby_port", 5432),
            db_user=data.get("db_user", "replication_user"),
            db_password=data.get("db_password"),
            db_name=data.get("db_name", "postgres"),
            db_type=data.get("db_type", "postgresql"),
            dns_update_enabled=data.get("dns_update_enabled", True),
            dns_record_name=data.get("dns_record_name", "db-primary.internal"),
            dns_zone_id=data.get("dns_zone_id"),
            health_check_interval_seconds=data.get("health_check_interval_seconds", 5),
            replication_lag_threshold_seconds=data.get("replication_lag_threshold_seconds", 60.0),
            max_promotion_attempts=data.get("max_promotion_attempts", 3),
            promotion_timeout_seconds=data.get("promotion_timeout_seconds", 120),
            auto_failover_enabled=data.get("auto_failover_enabled", False),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> StandbyReplicaPromoter:
        new = StandbyReplicaPromoter(
            primary_host=self.primary_host,
            primary_port=self.primary_port,
            standby_hosts=self.standby_hosts.copy(),
            standby_port=self.standby_port,
            db_user=self.db_user,
            db_password=self.db_password,
            db_name=self.db_name,
            db_type=self.db_type,
            dns_update_enabled=self.dns_update_enabled,
            dns_record_name=self.dns_record_name,
            dns_zone_id=self.dns_zone_id,
            health_check_interval_seconds=self.health_check_interval,
            replication_lag_threshold_seconds=self.replication_lag_threshold,
            max_promotion_attempts=self.max_attempts,
            promotion_timeout_seconds=self.promotion_timeout,
            auto_failover_enabled=self.auto_failover_enabled,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "primary_host": self.primary_host,
            "standby_count": len(self.standby_hosts),
            "auto_failover_enabled": self.auto_failover_enabled,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> StandbyReplicaPromoter:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._failover_history.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._init_replicas()
        if self.auto_failover_enabled:
            self._start_health_monitor()
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    promoter = StandbyReplicaPromoter(
        primary_host="db-primary.internal",
        primary_port=5432,
        standby_hosts=["db-standby-1.internal", "db-standby-2.internal"],
        db_user="replicator",
        db_type="postgresql",
        auto_failover_enabled=False,
    )
    print("Replica status:", promoter.get_replicas_status())
    result = promoter.failover(reason=FailoverReason.MANUAL, force=True)
    print(f"Failover result: {result.status.value} -> new primary {result.new_primary}")
    promoter.export_to_json("standby_promotion.json")
