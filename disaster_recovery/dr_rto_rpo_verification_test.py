#!/usr/bin/env python3
"""
Module: dr_rto_rpo_verification_test.py
Layer: Disaster Recovery

Responsibility:
    Melakukan verifikasi RTO (Recovery Time Objective) dan RPO (Recovery Point Objective)
    dengan mensimulasikan kegagalan dan mengukur waktu pemulihan serta kehilangan data.

Metode yang ditambahkan:
- Untuk DRMetrics: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk TestSchedule: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk RTO_RPO_VerificationTest: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# Optional Prometheus metrics
try:
    from prometheus_client import Counter, Gauge, Histogram

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False


# ============================================================================
# Enums
# ============================================================================
class TestScenario(Enum):
    DATABASE_FAILOVER = "database_failover"
    EVENT_STORE_REPLAY = "event_store_replay"
    CROSS_REGION_FAILOVER = "cross_region_failover"
    FULL_SYSTEM_RECOVERY = "full_system_recovery"
    BACKUP_RESTORE = "backup_restore"

    def display_name(self) -> str:
        names = {
            TestScenario.DATABASE_FAILOVER: "Failover Database",
            TestScenario.EVENT_STORE_REPLAY: "Replay Event Store",
            TestScenario.CROSS_REGION_FAILOVER: "Failover Cross Region",
            TestScenario.FULL_SYSTEM_RECOVERY: "Recovery Sistem Penuh",
            TestScenario.BACKUP_RESTORE: "Restore Backup",
        }
        return names.get(self, self.value)


class TestStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"

    def display_name(self) -> str:
        names = {
            TestStatus.PENDING: "Menunggu",
            TestStatus.RUNNING: "Berjalan",
            TestStatus.SUCCESS: "Berhasil",
            TestStatus.FAILED: "Gagal",
            TestStatus.TIMEOUT: "Timeout",
        }
        return names.get(self, self.value)


class ComplianceStatus(Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NOT_TESTED = "not_tested"

    def display_name(self) -> str:
        names = {
            ComplianceStatus.COMPLIANT: "Sesuai",
            ComplianceStatus.NON_COMPLIANT: "Tidak Sesuai",
            ComplianceStatus.PARTIALLY_COMPLIANT: "Sebagian Sesuai",
            ComplianceStatus.NOT_TESTED: "Belum Diuji",
        }
        return names.get(self, self.value)


# ============================================================================
# DRMetrics (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class DRMetrics:
    test_id: str
    scenario: TestScenario
    start_time: datetime
    end_time: datetime
    rto_actual_seconds: float
    rpo_actual_seconds: float
    rto_target_seconds: float
    rpo_target_seconds: float
    rto_met: bool
    rpo_met: bool
    status: TestStatus
    data_loss_bytes: int | None = None
    transaction_loss_count: int | None = None
    data_loss_percentage: float | None = None
    failure_timestamp: datetime | None = None
    recovery_timestamp: datetime | None = None
    details: dict = field(default_factory=dict)
    error_message: str | None = None

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
                "test_id": self.test_id,
                "scenario": self.scenario.value,
                "status": self.status.value,
                "rto_met": self.rto_met,
                "rpo_met": self.rpo_met,
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
                "test_id": self.test_id,
                "details": details,
            }
        )

    def is_compliant(self) -> bool:
        return self.rto_met and self.rpo_met and self.status == TestStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "test_id": self.test_id,
            "scenario": self.scenario.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "rto_actual_seconds": self.rto_actual_seconds,
            "rpo_actual_seconds": self.rpo_actual_seconds,
            "rto_target_seconds": self.rto_target_seconds,
            "rpo_target_seconds": self.rpo_target_seconds,
            "rto_met": self.rto_met,
            "rpo_met": self.rpo_met,
            "status": self.status.value,
            "data_loss_bytes": self.data_loss_bytes,
            "transaction_loss_count": self.transaction_loss_count,
            "data_loss_percentage": self.data_loss_percentage,
            "failure_timestamp": self.failure_timestamp.isoformat()
            if self.failure_timestamp
            else None,
            "recovery_timestamp": self.recovery_timestamp.isoformat()
            if self.recovery_timestamp
            else None,
            "details": self.details,
            "error_message": self.error_message,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DRMetrics:
        instance = cls(
            test_id=data["test_id"],
            scenario=TestScenario(data["scenario"]),
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            rto_actual_seconds=data["rto_actual_seconds"],
            rpo_actual_seconds=data["rpo_actual_seconds"],
            rto_target_seconds=data["rto_target_seconds"],
            rpo_target_seconds=data["rpo_target_seconds"],
            rto_met=data["rto_met"],
            rpo_met=data["rpo_met"],
            status=TestStatus(data["status"]),
            data_loss_bytes=data.get("data_loss_bytes"),
            transaction_loss_count=data.get("transaction_loss_count"),
            data_loss_percentage=data.get("data_loss_percentage"),
            failure_timestamp=datetime.fromisoformat(data["failure_timestamp"])
            if data.get("failure_timestamp")
            else None,
            recovery_timestamp=datetime.fromisoformat(data["recovery_timestamp"])
            if data.get("recovery_timestamp")
            else None,
            details=data.get("details", {}),
            error_message=data.get("error_message"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DRMetrics:
        new = DRMetrics(
            test_id=str(uuid4()),
            scenario=self.scenario,
            start_time=self.start_time,
            end_time=self.end_time,
            rto_actual_seconds=self.rto_actual_seconds,
            rpo_actual_seconds=self.rpo_actual_seconds,
            rto_target_seconds=self.rto_target_seconds,
            rpo_target_seconds=self.rpo_target_seconds,
            rto_met=self.rto_met,
            rpo_met=self.rpo_met,
            status=self.status,
            data_loss_bytes=self.data_loss_bytes,
            transaction_loss_count=self.transaction_loss_count,
            data_loss_percentage=self.data_loss_percentage,
            failure_timestamp=self.failure_timestamp,
            recovery_timestamp=self.recovery_timestamp,
            details=self.details.copy(),
            error_message=self.error_message,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.test_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "test_id": self.test_id,
            "scenario": self.scenario.value,
            "status": self.status.value,
            "rto_met": self.rto_met,
            "rpo_met": self.rpo_met,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DRMetrics:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def to_prometheus_metrics(self) -> None:
        if not HAS_PROMETHEUS:
            return
        try:
            rto_gauge = Gauge(
                "dr_rto_actual_seconds", "Actual RTO in seconds", ["scenario", "test_id"]
            )
            rpo_gauge = Gauge(
                "dr_rpo_actual_seconds", "Actual RPO in seconds", ["scenario", "test_id"]
            )
            rto_gauge.labels(scenario=self.scenario.value, test_id=self.test_id).set(
                self.rto_actual_seconds
            )
            rpo_gauge.labels(scenario=self.scenario.value, test_id=self.test_id).set(
                self.rpo_actual_seconds
            )
        except Exception as e:
            logger.warning(f"Failed to export Prometheus metrics: {e}")


# ============================================================================
# TestSchedule (dengan entity dasar)
# ============================================================================
@dataclass(kw_only=True)
class TestSchedule:
    schedule_id: str
    scenario: TestScenario
    interval_seconds: int
    next_run: datetime
    last_run: datetime | None = None
    last_result: DRMetrics | None = None
    enabled: bool = True
    notification_webhook: str | None = None

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
                "schedule_id": self.schedule_id,
                "scenario": self.scenario.value,
                "enabled": self.enabled,
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
                "schedule_id": self.schedule_id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.schedule_id:
            errors.append("schedule_id is required")
        if not isinstance(self.scenario, TestScenario):
            errors.append("invalid scenario")
        if self.interval_seconds <= 0:
            errors.append("interval_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "scenario": self.scenario.value,
            "interval_seconds": self.interval_seconds,
            "next_run": self.next_run.isoformat(),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "last_result": self.last_result.to_dict() if self.last_result else None,
            "enabled": self.enabled,
            "notification_webhook": self.notification_webhook,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestSchedule:
        instance = cls(
            schedule_id=data["schedule_id"],
            scenario=TestScenario(data["scenario"]),
            interval_seconds=data["interval_seconds"],
            next_run=datetime.fromisoformat(data["next_run"]),
            last_run=datetime.fromisoformat(data["last_run"]) if data.get("last_run") else None,
            last_result=DRMetrics.from_dict(data["last_result"])
            if data.get("last_result")
            else None,
            enabled=data.get("enabled", True),
            notification_webhook=data.get("notification_webhook"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TestSchedule:
        new = TestSchedule(
            schedule_id=str(uuid4()),
            scenario=self.scenario,
            interval_seconds=self.interval_seconds,
            next_run=self.next_run,
            last_run=self.last_run,
            last_result=self.last_result.clone() if self.last_result else None,
            enabled=self.enabled,
            notification_webhook=self.notification_webhook,
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.schedule_id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "schedule_id": self.schedule_id,
            "scenario": self.scenario.value,
            "enabled": self.enabled,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TestSchedule:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# RTO_RPO_VerificationTest Core (dengan entity dasar)
# ============================================================================
class RTO_RPO_VerificationTest:
    """
    Test verifikasi RTO/RPO dengan skenario failover terukur.
    """

    def __init__(
        self,
        rto_target_seconds: float = 300,
        rpo_target_seconds: float = 60,
        max_test_duration_seconds: float = 600,
        enable_prometheus: bool = True,
    ):
        self.rto_target = rto_target_seconds
        self.rpo_target = rpo_target_seconds
        self.max_duration = max_test_duration_seconds
        self.enable_prometheus = enable_prometheus and HAS_PROMETHEUS
        self._metrics_history: list[DRMetrics] = []
        self._schedules: dict[str, TestSchedule] = {}
        self._current_test: threading.Thread | None = None
        self._last_successful_tx_time: datetime | None = None
        self._lock = threading.RLock()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "rto_target": self.rto_target,
                "rpo_target": self.rpo_target,
                "max_duration": self.max_duration,
                "history_count": len(self._metrics_history),
                "schedules_count": len(self._schedules),
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
    # Core Test Execution
    # ------------------------------------------------------------------------
    def simulate_failure(
        self,
        failover_function: Callable[[], Any],
        scenario: TestScenario = TestScenario.DATABASE_FAILOVER,
        pre_failure_hook: Callable | None = None,
        post_recovery_hook: Callable | None = None,
        test_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> DRMetrics:
        test_id = test_id or f"dr_test_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        timeout = timeout_seconds or self.max_duration
        start_time = datetime.utcnow()
        failure_time = start_time

        if pre_failure_hook:
            try:
                pre_failure_hook()
            except Exception as e:
                logger.error(f"Pre-failure hook failed: {e}")

        if self._last_successful_tx_time is None:
            self._last_successful_tx_time = failure_time - timedelta(seconds=self.rpo_target / 2)

        start_recovery = time.time()
        result = None
        error_msg = None
        status = TestStatus.RUNNING

        try:
            result = self._run_with_timeout(failover_function, timeout)
            recovery_time = time.time()
            rto_actual = recovery_time - start_recovery
            status = TestStatus.SUCCESS
        except TimeoutError:
            recovery_time = time.time()
            rto_actual = recovery_time - start_recovery
            status = TestStatus.TIMEOUT
            error_msg = f"Failover timeout after {timeout} seconds"
        except Exception as e:
            recovery_time = time.time()
            rto_actual = recovery_time - start_recovery
            status = TestStatus.FAILED
            error_msg = str(e)

        if post_recovery_hook:
            try:
                post_recovery_hook()
            except Exception as e:
                logger.warning(f"Post-recovery hook failed: {e}")

        recovery_timestamp = datetime.utcnow()
        rpo_actual = (recovery_timestamp - self._last_successful_tx_time).total_seconds()
        if rpo_actual < 0:
            rpo_actual = 0

        if status == TestStatus.SUCCESS:
            self._last_successful_tx_time = recovery_timestamp

        metrics = DRMetrics(
            test_id=test_id,
            scenario=scenario,
            start_time=start_time,
            end_time=recovery_timestamp,
            rto_actual_seconds=rto_actual,
            rpo_actual_seconds=rpo_actual,
            rto_target_seconds=self.rto_target,
            rpo_target_seconds=self.rpo_target,
            rto_met=rto_actual <= self.rto_target,
            rpo_met=rpo_actual <= self.rpo_target,
            status=status,
            failure_timestamp=failure_time,
            recovery_timestamp=recovery_timestamp,
            details={"result": str(result) if result else None},
            error_message=error_msg,
        )

        with self._lock:
            self._metrics_history.append(metrics)

        if self.enable_prometheus:
            metrics.to_prometheus_metrics()

        self._record_audit(
            "SIMULATE_FAILURE", "system", {"test_id": test_id, "status": status.value}
        )
        logger.info(
            f"DR Test {test_id} completed: RTO={rto_actual:.2f}s (target {self.rto_target}s), "
            f"RPO={rpo_actual:.2f}s (target {self.rpo_target}s), status={status.value}"
        )
        return metrics

    def _run_with_timeout(self, func: Callable, timeout: float) -> Any:
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
        return result_container[0] if result_container else None

    # ------------------------------------------------------------------------
    # Historical Metrics & Reporting
    # ------------------------------------------------------------------------
    def get_last_metrics(self, scenario: TestScenario | None = None) -> DRMetrics | None:
        with self._lock:
            if scenario:
                for m in reversed(self._metrics_history):
                    if m.scenario == scenario:
                        return m
                return None
            return self._metrics_history[-1] if self._metrics_history else None

    def get_test_history(
        self, limit: int = 100, scenario: TestScenario | None = None
    ) -> list[DRMetrics]:
        with self._lock:
            filtered = self._metrics_history
            if scenario:
                filtered = [m for m in filtered if m.scenario == scenario]
            return filtered[-limit:]

    def get_compliance_report(self, period_days: int = 30) -> dict:
        cutoff = datetime.utcnow() - timedelta(days=period_days)
        with self._lock:
            recent = [m for m in self._metrics_history if m.end_time >= cutoff]

        if not recent:
            return {
                "period_days": period_days,
                "status": ComplianceStatus.NOT_TESTED.value,
                "total_tests": 0,
                "message": "No tests conducted in period",
            }

        total = len(recent)
        rto_compliant = sum(1 for m in recent if m.rto_met)
        rpo_compliant = sum(1 for m in recent if m.rpo_met)
        both_compliant = sum(1 for m in recent if m.rto_met and m.rpo_met)
        success_count = sum(1 for m in recent if m.status == TestStatus.SUCCESS)

        avg_rto = sum(m.rto_actual_seconds for m in recent) / total
        avg_rpo = sum(m.rpo_actual_seconds for m in recent) / total
        p95_rto = sorted(m.rto_actual_seconds for m in recent)[int(total * 0.95)]
        p95_rpo = sorted(m.rpo_actual_seconds for m in recent)[int(total * 0.95)]

        overall = (
            ComplianceStatus.COMPLIANT
            if both_compliant == total
            else ComplianceStatus.PARTIALLY_COMPLIANT
            if both_compliant > 0
            else ComplianceStatus.NON_COMPLIANT
        )

        return {
            "period_days": period_days,
            "period_end": datetime.utcnow().isoformat(),
            "total_tests": total,
            "successful_tests": success_count,
            "rto_compliant_count": rto_compliant,
            "rpo_compliant_count": rpo_compliant,
            "fully_compliant_count": both_compliant,
            "rto_compliance_rate": round(rto_compliant / total * 100, 2),
            "rpo_compliance_rate": round(rpo_compliant / total * 100, 2),
            "overall_compliance_rate": round(both_compliant / total * 100, 2),
            "avg_rto_seconds": round(avg_rto, 2),
            "avg_rpo_seconds": round(avg_rpo, 2),
            "p95_rto_seconds": round(p95_rto, 2),
            "p95_rpo_seconds": round(p95_rpo, 2),
            "status": overall.value,
            "rto_target": self.rto_target,
            "rpo_target": self.rpo_target,
        }

    def get_by_scenario_summary(self) -> dict[str, dict]:
        summary = {}
        with self._lock:
            for scenario in TestScenario:
                scenario_tests = [m for m in self._metrics_history if m.scenario == scenario]
                if not scenario_tests:
                    continue
                total = len(scenario_tests)
                compliant = sum(1 for m in scenario_tests if m.is_compliant())
                avg_rto = sum(m.rto_actual_seconds for m in scenario_tests) / total
                avg_rpo = sum(m.rpo_actual_seconds for m in scenario_tests) / total
                last = scenario_tests[-1]
                summary[scenario.value] = {
                    "total_tests": total,
                    "compliant_tests": compliant,
                    "compliance_rate": round(compliant / total * 100, 2),
                    "avg_rto": round(avg_rto, 2),
                    "avg_rpo": round(avg_rpo, 2),
                    "last_test_time": last.end_time.isoformat(),
                    "last_test_result": "pass" if last.is_compliant() else "fail",
                }
        return summary

    # ------------------------------------------------------------------------
    # Scheduled Tests
    # ------------------------------------------------------------------------
    def add_scheduled_test(
        self,
        scenario: TestScenario,
        interval_seconds: int,
        failover_function: Callable,
        pre_hook: Callable | None = None,
        post_hook: Callable | None = None,
        notification_webhook: str | None = None,
    ) -> str:
        schedule_id = str(uuid4())
        schedule = TestSchedule(
            schedule_id=schedule_id,
            scenario=scenario,
            interval_seconds=interval_seconds,
            next_run=datetime.utcnow(),
            notification_webhook=notification_webhook,
        )
        self._schedules[schedule_id] = schedule
        self._record_audit(
            "ADD_SCHEDULED_TEST", "system", {"schedule_id": schedule_id, "scenario": scenario.value}
        )
        self._start_scheduled_thread(schedule_id, failover_function, pre_hook, post_hook)
        return schedule_id

    def _start_scheduled_thread(
        self,
        schedule_id: str,
        failover_func: Callable,
        pre_hook: Callable | None,
        post_hook: Callable | None,
    ) -> None:
        schedule = self._schedules.get(schedule_id)
        if not schedule:
            return

        def run_scheduled():
            while schedule.enabled:
                now = datetime.utcnow()
                if now >= schedule.next_run:
                    schedule.next_run = now + timedelta(seconds=schedule.interval_seconds)
                    schedule.last_run = now
                    try:
                        metrics = self.simulate_failure(
                            failover_function=failover_func,
                            scenario=schedule.scenario,
                            pre_failure_hook=pre_hook,
                            post_recovery_hook=post_hook,
                        )
                        schedule.last_result = metrics
                        self._send_notification(schedule, metrics)
                    except Exception as e:
                        logger.error(f"Scheduled test {schedule_id} failed: {e}")
                time.sleep(1)

        thread = threading.Thread(target=run_scheduled, daemon=True)
        thread.start()

    def _send_notification(self, schedule: TestSchedule, metrics: DRMetrics) -> None:
        if not schedule.notification_webhook:
            return
        try:
            import requests

            payload = {
                "schedule_id": schedule.schedule_id,
                "scenario": metrics.scenario.value,
                "rto_met": metrics.rto_met,
                "rpo_met": metrics.rpo_met,
                "rto_actual": metrics.rto_actual_seconds,
                "rpo_actual": metrics.rpo_actual_seconds,
                "status": metrics.status.value,
            }
            requests.post(schedule.notification_webhook, json=payload, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")

    def stop_scheduled_test(self, schedule_id: str) -> bool:
        schedule = self._schedules.get(schedule_id)
        if schedule:
            schedule.enabled = False
            self._record_audit("STOP_SCHEDULED_TEST", "system", {"schedule_id": schedule_id})
            return True
        return False

    # ------------------------------------------------------------------------
    # Export & Reporting
    # ------------------------------------------------------------------------
    def export_to_json(self, file_path: str) -> None:
        with self._lock:
            data = {
                "rto_target": self.rto_target,
                "rpo_target": self.rpo_target,
                "max_test_duration": self.max_duration,
                "total_tests": len(self._metrics_history),
                "history": [m.to_dict() for m in self._metrics_history],
                "compliance_report_30d": self.get_compliance_report(30),
                "scenario_summary": self.get_by_scenario_summary(),
                "version": self._version,
            }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def reset_history(self) -> None:
        with self._lock:
            self._metrics_history.clear()
            self._last_successful_tx_time = None
            self._version += 1
            self._record_audit("RESET_HISTORY", "system", {})

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.rto_target <= 0:
            errors.append("rto_target_seconds must be positive")
        if self.rpo_target <= 0:
            errors.append("rpo_target_seconds must be positive")
        if self.max_duration <= 0:
            errors.append("max_test_duration_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "rto_target_seconds": self.rto_target,
            "rpo_target_seconds": self.rpo_target,
            "max_test_duration_seconds": self.max_duration,
            "enable_prometheus": self.enable_prometheus,
            "total_tests": len(self._metrics_history),
            "schedules_count": len(self._schedules),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RTO_RPO_VerificationTest:
        instance = cls(
            rto_target_seconds=data.get("rto_target_seconds", 300),
            rpo_target_seconds=data.get("rpo_target_seconds", 60),
            max_test_duration_seconds=data.get("max_test_duration_seconds", 600),
            enable_prometheus=data.get("enable_prometheus", True),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RTO_RPO_VerificationTest:
        new = RTO_RPO_VerificationTest(
            rto_target_seconds=self.rto_target,
            rpo_target_seconds=self.rpo_target,
            max_test_duration_seconds=self.max_duration,
            enable_prometheus=self.enable_prometheus,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "rto_target": self.rto_target,
            "rpo_target": self.rpo_target,
            "total_tests": len(self._metrics_history),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RTO_RPO_VerificationTest:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self.reset_history()
        self._schedules.clear()
        self._version = 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    import random

    def mock_failover():
        time.sleep(random.uniform(0.5, 3.0))
        return {"success": True}

    tester = RTO_RPO_VerificationTest(rto_target_seconds=5, rpo_target_seconds=2)
    result = tester.simulate_failure(mock_failover, scenario=TestScenario.DATABASE_FAILOVER)
    print(
        f"Test result: RTO={result.rto_actual_seconds:.2f}s, RPO={result.rpo_actual_seconds:.2f}s, compliant={result.is_compliant()}"
    )
    report = tester.get_compliance_report(period_days=1)
    print("Compliance report:", json.dumps(report, indent=2))
    tester.export_to_json("dr_test_results.json")
    print("Exported to dr_test_results.json")
