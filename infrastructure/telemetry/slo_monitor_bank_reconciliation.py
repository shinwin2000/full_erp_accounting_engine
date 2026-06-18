#!/usr/bin/env python3
"""
Module: slo_monitor_bank_reconciliation.py
Layer: Infrastructure (Telemetry)
Responsibility: Memonitor Service Level Objective (SLO) untuk proses bank reconciliation.
               Melacak durasi rekonsiliasi bank, ketepatan waktu (apakah dilakukan
               dalam X hari setelah statement date), keberhasilan, dan kepatuhan
               terhadap target SLO. Mendukung monitoring untuk multiple bank accounts.
Dependencies:
- asyncio, logging, datetime
- infrastructure.telemetry.alert_manager_router (trigger_alert)
- infrastructure.telemetry.prometheus_registry (metrics)
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml
Audit: Setiap rekonsiliasi bank dicatat untuk compliance audit trail.
       Pelanggaran SLO rekonsiliasi bank memicu alert ke finance team.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    trigger_alert,
)
from infrastructure.telemetry.prometheus_registry import get_counter, get_gauge, get_histogram
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# SLO targets (days after statement date)
DEFAULT_SLO_TARGET_DAYS = 15  # Rekonsiliasi harus selesai dalam 15 hari setelah statement date
DEFAULT_SLO_WARNING_DAYS = 7  # Warning jika lebih dari 7 hari
DEFAULT_SLO_CRITICAL_DAYS = 30  # Critical jika lebih dari 30 hari

# Metrics
reconciliation_duration = get_histogram(
    "bank_reconciliation_duration_seconds",
    "Duration of bank reconciliation process",
    ["legal_entity_id", "bank_account_id", "status"],
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400, 28800],
)

reconciliation_slo_compliance = get_gauge(
    "bank_reconciliation_slo_compliance",
    "SLO compliance for bank reconciliation (1=compliant, 0=violated)",
    ["legal_entity_id", "bank_account_id", "slo_level"],
)

reconciliation_total = get_counter(
    "bank_reconciliation_total",
    "Total bank reconciliation attempts",
    ["legal_entity_id", "bank_account_id", "status"],
)

reconciliation_outstanding_days = get_gauge(
    "bank_reconciliation_outstanding_days",
    "Days since statement date without reconciliation",
    ["legal_entity_id", "bank_account_id"],
)

# ============================================================================
# SLO MONITOR
# ============================================================================


class SLOMonitorBankReconciliation:
    """
    Monitor SLO untuk bank reconciliation.

    Fitur:
    - Track reconciliation start and completion
    - Calculate completion time relative to statement date
    - Alert on SLO violations
    - Monitor outstanding reconciliations
    - Store history untuk reporting
    """

    def __init__(self, config_path: str = "config_files/slo_config.yaml"):
        self.config = self._load_config(config_path)
        self._slo_target_days = self.config.get("bank_reconciliation", {}).get(
            "target_days", DEFAULT_SLO_TARGET_DAYS
        )
        self._warning_days = self.config.get("bank_reconciliation", {}).get(
            "warning_days", DEFAULT_SLO_WARNING_DAYS
        )
        self._critical_days = self.config.get("bank_reconciliation", {}).get(
            "critical_days", DEFAULT_SLO_CRITICAL_DAYS
        )
        self._active_reconciliations: dict[str, dict[str, Any]] = {}
        self._reconciliation_history: list[dict[str, Any]] = []
        self._outstanding_alerts_sent: dict[str, datetime] = {}

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {}

    def _get_key(self, legal_entity_id: UUID, bank_account_id: UUID, statement_date: str) -> str:
        """Generate unique key for reconciliation."""
        return f"{legal_entity_id}:{bank_account_id}:{statement_date}"

    def start_reconciliation(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID,
        statement_date: date,
        started_by: UUID | None = None,
    ) -> str:
        """
        Start monitoring a bank reconciliation process.

        Returns:
            Reconciliation key for tracking
        """
        key = self._get_key(legal_entity_id, bank_account_id, statement_date.isoformat())

        self._active_reconciliations[key] = {
            "legal_entity_id": str(legal_entity_id),
            "bank_account_id": str(bank_account_id),
            "statement_date": statement_date.isoformat(),
            "started_at": datetime.now(UTC),
            "started_by": str(started_by) if started_by else None,
            "status": "in_progress",
            "completed_at": None,
            "completed_by": None,
            "duration_seconds": None,
            "days_after_statement": None,
            "errors": [],
        }

        logger.info(
            f"Bank reconciliation started for account {bank_account_id} statement {statement_date}"
        )
        return key

    def complete_reconciliation(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID,
        statement_date: date,
        completed_by: UUID | None = None,
        errors: list[str] | None = None,
        difference_amount: Decimal | None = None,
    ) -> dict[str, Any]:
        """
        Complete bank reconciliation monitoring and check SLO.

        Returns:
            Result dictionary with SLO compliance info
        """
        key = self._get_key(legal_entity_id, bank_account_id, statement_date.isoformat())

        if key not in self._active_reconciliations:
            logger.warning(f"Reconciliation {key} not found in active processes")
            return {"error": "not_found"}

        recon_data = self._active_reconciliations[key]
        recon_data["completed_at"] = datetime.now(UTC)
        recon_data["completed_by"] = str(completed_by) if completed_by else None
        recon_data["status"] = "completed"
        recon_data["errors"] = errors or []
        if difference_amount is not None:
            recon_data["difference_amount"] = float(difference_amount)

        # Calculate duration
        duration_seconds = (recon_data["completed_at"] - recon_data["started_at"]).total_seconds()
        recon_data["duration_seconds"] = duration_seconds

        # Calculate days after statement date
        statement_date_obj = datetime.fromisoformat(recon_data["statement_date"]).date()
        completed_date = recon_data["completed_at"].date()

        if completed_date > statement_date_obj:
            days_after = (completed_date - statement_date_obj).days
            recon_data["days_after_statement"] = days_after
        else:
            recon_data["days_after_statement"] = 0

        # Check SLO compliance
        days_after = recon_data["days_after_statement"]
        slo_compliant = days_after <= self._slo_target_days
        warning_violated = days_after > self._warning_days
        critical_violated = days_after > self._critical_days

        recon_data["slo_compliant"] = slo_compliant
        recon_data["warning_violated"] = warning_violated
        recon_data["critical_violated"] = critical_violated

        # Update Prometheus metrics
        status = "success" if slo_compliant else "failed"
        reconciliation_total.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            status=status,
        ).inc()

        reconciliation_duration.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            status=status,
        ).observe(duration_seconds)

        reconciliation_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            slo_level="target",
        ).set(1 if slo_compliant else 0)

        reconciliation_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            slo_level="warning",
        ).set(1 if not warning_violated else 0)

        reconciliation_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            slo_level="critical",
        ).set(1 if not critical_violated else 0)

        # Add to history
        self._reconciliation_history.append(recon_data.copy())
        if len(self._reconciliation_history) > 500:
            self._reconciliation_history = self._reconciliation_history[-500:]

        # Remove from active
        del self._active_reconciliations[key]

        # Send alert if SLO violated
        if critical_violated:
            asyncio.create_task(
                trigger_alert(
                    title="Bank Reconciliation SLO Critical Violation",
                    message=f"Reconciliation for account {bank_account_id} (statement {statement_date}) completed {days_after} days after statement date "
                    f"(critical threshold: {self._critical_days}d)",
                    severity=SEVERITY_CRITICAL,
                    source="SLOMonitorBankReconciliation",
                    metadata={
                        "legal_entity_id": str(legal_entity_id),
                        "bank_account_id": str(bank_account_id),
                        "statement_date": statement_date.isoformat(),
                        "days_after": days_after,
                        "duration_seconds": duration_seconds,
                    },
                )
            )
        elif warning_violated:
            asyncio.create_task(
                trigger_alert(
                    title="Bank Reconciliation SLO Warning",
                    message=f"Reconciliation for account {bank_account_id} (statement {statement_date}) completed {days_after} days after statement date "
                    f"(warning threshold: {self._warning_days}d)",
                    severity=SEVERITY_WARNING,
                    source="SLOMonitorBankReconciliation",
                    metadata={
                        "legal_entity_id": str(legal_entity_id),
                        "bank_account_id": str(bank_account_id),
                        "statement_date": statement_date.isoformat(),
                        "days_after": days_after,
                    },
                )
            )

        logger.info(
            f"Bank reconciliation completed for {key}: {duration_seconds:.2f}s, "
            f"days after statement: {days_after}, SLO compliant: {slo_compliant}"
        )

        return {
            "key": key,
            "duration_seconds": duration_seconds,
            "days_after_statement": days_after,
            "slo_compliant": slo_compliant,
            "warning_violated": warning_violated,
            "critical_violated": critical_violated,
            "difference_amount": recon_data.get("difference_amount"),
        }

    def fail_reconciliation(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID,
        statement_date: date,
        error: str,
        failed_by: UUID | None = None,
    ) -> None:
        """
        Mark bank reconciliation as failed.
        """
        key = self._get_key(legal_entity_id, bank_account_id, statement_date.isoformat())

        if key not in self._active_reconciliations:
            logger.warning(f"Reconciliation {key} not found in active processes")
            return

        recon_data = self._active_reconciliations[key]
        recon_data["status"] = "failed"
        recon_data["failed_at"] = datetime.now(UTC)
        recon_data["failed_by"] = str(failed_by) if failed_by else None
        recon_data["error"] = error

        reconciliation_total.labels(
            legal_entity_id=str(legal_entity_id),
            bank_account_id=str(bank_account_id),
            status="failed",
        ).inc()

        asyncio.create_task(
            trigger_alert(
                title="Bank Reconciliation Failed",
                message=f"Reconciliation for account {bank_account_id} (statement {statement_date}) failed: {error}",
                severity=SEVERITY_ERROR,
                source="SLOMonitorBankReconciliation",
                metadata={
                    "legal_entity_id": str(legal_entity_id),
                    "bank_account_id": str(bank_account_id),
                    "statement_date": statement_date.isoformat(),
                    "error": error,
                },
            )
        )

        logger.error(f"Bank reconciliation failed for {key}: {error}")

        # Remove from active
        del self._active_reconciliations[key]

    def check_outstanding_reconciliations(
        self, legal_entity_id: UUID, bank_account_id: UUID, statement_date: date
    ) -> None:
        """
        Check if a reconciliation is outstanding and send alerts.
        """
        key = self._get_key(legal_entity_id, bank_account_id, statement_date.isoformat())

        # If already reconciled, skip
        if key in self._active_reconciliations or key in [
            h.get("key") for h in self._reconciliation_history
        ]:
            return

        today = datetime.now(UTC).date()
        statement_date_obj = statement_date
        days_outstanding = (today - statement_date_obj).days

        # Update gauge
        reconciliation_outstanding_days.labels(
            legal_entity_id=str(legal_entity_id), bank_account_id=str(bank_account_id)
        ).set(days_outstanding)

        # Check if alert needed
        alert_key = f"{legal_entity_id}:{bank_account_id}:{statement_date}"
        last_alert = self._outstanding_alerts_sent.get(alert_key)

        should_alert = False
        severity = None

        if days_outstanding > self._critical_days:
            should_alert = True
            severity = SEVERITY_CRITICAL
        elif days_outstanding > self._warning_days:
            should_alert = True
            severity = SEVERITY_WARNING

        if should_alert:
            # Rate limit alerts (max 1 per day per account)
            if last_alert and (datetime.now(UTC) - last_alert).total_seconds() < 86400:
                return

            self._outstanding_alerts_sent[alert_key] = datetime.now(UTC)

            asyncio.create_task(
                trigger_alert(
                    title=f"Outstanding Bank Reconciliation ({severity})",
                    message=f"Bank account {bank_account_id} has outstanding reconciliation for {statement_date} "
                    f"({days_outstanding} days outstanding)",
                    severity=severity,
                    source="SLOMonitorBankReconciliation",
                    metadata={
                        "legal_entity_id": str(legal_entity_id),
                        "bank_account_id": str(bank_account_id),
                        "statement_date": statement_date.isoformat(),
                        "days_outstanding": days_outstanding,
                    },
                )
            )

    def get_active_reconciliations(self) -> list[dict[str, Any]]:
        """Get currently active reconciliations."""
        return list(self._active_reconciliations.values())

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get reconciliation history."""
        return self._reconciliation_history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get SLO statistics."""
        total_reconciliations = len(self._reconciliation_history)
        if total_reconciliations == 0:
            return {"total": 0, "slo_compliance_rate": 0}

        compliant_count = sum(
            1 for r in self._reconciliation_history if r.get("slo_compliant", False)
        )

        return {
            "total_reconciliations": total_reconciliations,
            "slo_compliant_count": compliant_count,
            "slo_compliance_rate": (compliant_count / total_reconciliations) * 100,
            "target_days": self._slo_target_days,
            "warning_days": self._warning_days,
            "critical_days": self._critical_days,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_slo_bank_reconciliation_monitor: SLOMonitorBankReconciliation | None = None


def get_slo_bank_reconciliation_monitor() -> SLOMonitorBankReconciliation:
    """Get singleton instance of SLOMonitorBankReconciliation."""
    global _slo_bank_reconciliation_monitor
    if _slo_bank_reconciliation_monitor is None:
        _slo_bank_reconciliation_monitor = SLOMonitorBankReconciliation()
    return _slo_bank_reconciliation_monitor


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class BankReconciliationSLAMonitor:
    """
    Context manager untuk memonitor SLO bank reconciliation.

    Usage:
        async with BankReconciliationSLAMonitor(legal_entity_id, bank_account_id, statement_date) as monitor:
            await reconcile()
            monitor.complete(difference_amount=0)
    """

    def __init__(
        self,
        legal_entity_id: UUID,
        bank_account_id: UUID,
        statement_date: date,
        started_by: UUID | None = None,
    ):
        self.legal_entity_id = legal_entity_id
        self.bank_account_id = bank_account_id
        self.statement_date = statement_date
        self.started_by = started_by
        self._monitor = get_slo_bank_reconciliation_monitor()
        self._key: str | None = None
        self._difference_amount: Decimal | None = None

    async def __aenter__(self):
        self._key = self._monitor.start_reconciliation(
            self.legal_entity_id, self.bank_account_id, self.statement_date, self.started_by
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._monitor.fail_reconciliation(
                self.legal_entity_id,
                self.bank_account_id,
                self.statement_date,
                str(exc_val),
                self.started_by,
            )
        else:
            self._monitor.complete_reconciliation(
                self.legal_entity_id,
                self.bank_account_id,
                self.statement_date,
                self.started_by,
                None,
                self._difference_amount,
            )

    def complete(self, difference_amount: Decimal | None = None) -> None:
        """Mark reconciliation as complete with difference amount."""
        self._difference_amount = difference_amount


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "BankReconciliationSLAMonitor",
    "SLOMonitorBankReconciliation",
    "get_slo_bank_reconciliation_monitor",
]
