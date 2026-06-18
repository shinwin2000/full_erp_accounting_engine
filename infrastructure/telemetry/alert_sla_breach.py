#!/usr/bin/env python3
"""
Module: alert_sla_breach.py
Layer: Infrastructure (Telemetry)
Responsibility: Mendeteksi dan mengirim alert untuk pelanggaran SLA (Service Level
               Agreement) pada berbagai proses bisnis seperti period closing,
               bank reconciliation, posting jurnal, dan report generation.
               Memonitor durasi proses dan membandingkan dengan target SLA.
Dependencies:
- asyncio, logging, datetime
- infrastructure.telemetry.alert_manager_router (trigger_alert)
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml
Audit: Setiap pelanggaran SLA dicatat untuk compliance dan performance review.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import (
    SEVERITY_CRITICAL,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    trigger_alert,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================


class SLAProcessType(str, Enum):
    PERIOD_CLOSE = "period_close"
    BANK_RECONCILIATION = "bank_reconciliation"
    JOURNAL_POSTING = "journal_posting"
    REPORT_GENERATION = "report_generation"
    DEPRECIATION_RUN = "depreciation_run"
    PAYROLL_RUN = "payroll_run"
    TAX_FILING = "tax_filing"
    DATA_MIGRATION = "data_migration"
    CACHE_WARMING = "cache_warming"
    INTEGRATION_SYNC = "integration_sync"


class SLASeverity(str, Enum):
    WARNING = "warning"  # Exceeded warning threshold
    ERROR = "error"  # Exceeded error threshold
    CRITICAL = "critical"  # Exceeded critical threshold


# Default SLA thresholds (seconds)
DEFAULT_SLA_THRESHOLDS = {
    SLAProcessType.PERIOD_CLOSE: {
        "warning": 300,  # 5 minutes
        "error": 600,  # 10 minutes
        "critical": 1800,  # 30 minutes
    },
    SLAProcessType.BANK_RECONCILIATION: {
        "warning": 60,  # 1 minute
        "error": 180,  # 3 minutes
        "critical": 300,  # 5 minutes
    },
    SLAProcessType.JOURNAL_POSTING: {
        "warning": 2,  # 2 seconds
        "error": 5,  # 5 seconds
        "critical": 10,  # 10 seconds
    },
    SLAProcessType.REPORT_GENERATION: {
        "warning": 30,  # 30 seconds
        "error": 60,  # 1 minute
        "critical": 120,  # 2 minutes
    },
    SLAProcessType.DEPRECIATION_RUN: {
        "warning": 120,  # 2 minutes
        "error": 300,  # 5 minutes
        "critical": 600,  # 10 minutes
    },
    SLAProcessType.PAYROLL_RUN: {
        "warning": 180,  # 3 minutes
        "error": 600,  # 10 minutes
        "critical": 1200,  # 20 minutes
    },
    SLAProcessType.TAX_FILING: {
        "warning": 60,  # 1 minute
        "error": 180,  # 3 minutes
        "critical": 300,  # 5 minutes
    },
}


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class SLAProcess:
    """Data untuk proses yang dimonitor SLA."""

    process_type: SLAProcessType
    process_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    end_time: datetime | None = None
    duration_seconds: float | None = None
    legal_entity_id: str | None = None
    user_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def complete(self) -> None:
        """Mark process as completed and calculate duration."""
        self.end_time = datetime.now(UTC)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()


# ============================================================================
# SLA ALERTER
# ============================================================================


class SLABreachAlerter:
    """
    Detector dan alerter untuk pelanggaran SLA.

    Fitur:
    - Monitor durasi proses bisnis
    - Bandingkan dengan threshold SLA
    - Kirim alert jika melebihi threshold
    - Track SLA compliance rate
    - Support custom thresholds per legal entity
    """

    def __init__(self, config_path: str = "config_files/sla_config.yaml"):
        self.config = self._load_config(config_path)
        self._thresholds = self._load_thresholds()
        self._active_processes: dict[str, SLAProcess] = {}
        self._compliance_stats: dict[str, dict[str, Any]] = {}
        self._alert_history: list[dict] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {}

    def _load_thresholds(self) -> dict[str, dict[str, int]]:
        """Load SLA thresholds from config or use defaults."""
        config_thresholds = self.config.get("sla_thresholds", {})
        thresholds = DEFAULT_SLA_THRESHOLDS.copy()

        for process_type, process_thresholds in config_thresholds.items():
            if process_type in thresholds:
                thresholds[process_type].update(process_thresholds)

        return thresholds

    def _get_thresholds(
        self, process_type: SLAProcessType, legal_entity_id: str | None = None
    ) -> dict[str, int]:
        """Get thresholds for process type (with legal entity override)."""
        # Check legal entity specific thresholds
        if legal_entity_id:
            entity_thresholds = self.config.get("legal_entity_thresholds", {}).get(
                legal_entity_id, {}
            )
            if process_type.value in entity_thresholds:
                return entity_thresholds[process_type.value]

        return self._thresholds.get(process_type, {"warning": 60, "error": 120, "critical": 300})

    def start_process(
        self,
        process_type: SLAProcessType,
        process_id: str,
        legal_entity_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """
        Start monitoring a process.

        Args:
            process_type: Type of process
            process_id: Unique identifier for this process instance
            legal_entity_id: Legal entity context
            user_id: User who initiated the process
            metadata: Additional metadata

        Returns:
            Process key for tracking
        """
        process_key = f"{process_type.value}:{process_id}"

        self._active_processes[process_key] = SLAProcess(
            process_type=process_type,
            process_id=process_id,
            start_time=datetime.now(UTC),
            legal_entity_id=legal_entity_id,
            user_id=user_id,
            metadata=metadata or {},
        )

        logger.debug(f"SLA monitoring started for {process_key}")
        return process_key

    def complete_process(self, process_key: str) -> SLAProcess | None:
        """
        Complete monitoring and check SLA.

        Returns:
            SLAProcess if completed, None if not found
        """
        if process_key not in self._active_processes:
            logger.warning(f"Process {process_key} not found in active processes")
            return None

        process = self._active_processes[process_key]
        process.complete()

        # Check SLA breach
        self._check_sla_breach(process)

        # Update compliance stats
        self._update_compliance_stats(process)

        # Remove from active
        del self._active_processes[process_key]

        logger.info(f"SLA monitoring completed for {process_key}: {process.duration_seconds:.2f}s")
        return process

    def _check_sla_breach(self, process: SLAProcess) -> None:
        """
        Check if process breached SLA thresholds.
        """
        thresholds = self._get_thresholds(process.process_type, process.legal_entity_id)
        duration = process.duration_seconds

        if duration is None:
            return

        # Determine severity level
        severity = None
        if duration > thresholds.get("critical", 300):
            severity = SLASeverity.CRITICAL
        elif duration > thresholds.get("error", 120):
            severity = SLASeverity.ERROR
        elif duration > thresholds.get("warning", 60):
            severity = SLASeverity.WARNING

        if severity:
            # Send alert
            self._send_alert(process, severity, thresholds)

            # Store in history
            self._alert_history.append(
                {
                    "process_key": f"{process.process_type.value}:{process.process_id}",
                    "process_type": process.process_type.value,
                    "duration_seconds": duration,
                    "severity": severity.value,
                    "threshold_warning": thresholds.get("warning"),
                    "threshold_error": thresholds.get("error"),
                    "threshold_critical": thresholds.get("critical"),
                    "legal_entity_id": process.legal_entity_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )

    def _send_alert(
        self, process: SLAProcess, severity: SLASeverity, thresholds: dict[str, int]
    ) -> None:
        """
        Send alert for SLA breach.
        """
        alert_severity = {
            SLASeverity.WARNING: SEVERITY_WARNING,
            SLASeverity.ERROR: SEVERITY_ERROR,
            SLASeverity.CRITICAL: SEVERITY_CRITICAL,
        }.get(severity, SEVERITY_WARNING)

        title = f"SLA Breach: {process.process_type.value}"
        message = (
            f"Process {process.process_id} of type {process.process_type.value} "
            f"took {process.duration_seconds:.2f}s to complete.\n"
            f"SLA thresholds: Warning: {thresholds.get('warning')}s, "
            f"Error: {thresholds.get('error')}s, Critical: {thresholds.get('critical')}s\n"
            f"Legal entity: {process.legal_entity_id or 'N/A'}\n"
            f"Started at: {process.start_time.isoformat()}"
        )

        asyncio.create_task(
            trigger_alert(
                title=title,
                message=message,
                severity=alert_severity,
                source="SLABreachAlerter",
                metadata={
                    "process_type": process.process_type.value,
                    "process_id": process.process_id,
                    "duration_seconds": process.duration_seconds,
                    "severity": severity.value,
                    "thresholds": thresholds,
                },
            )
        )

    def _update_compliance_stats(self, process: SLAProcess) -> None:
        """
        Update SLA compliance statistics.
        """
        key = f"{process.process_type.value}:{process.legal_entity_id or 'global'}"

        if key not in self._compliance_stats:
            self._compliance_stats[key] = {
                "total": 0,
                "compliant": 0,
                "breaches": {"warning": 0, "error": 0, "critical": 0},
            }

        stats = self._compliance_stats[key]
        stats["total"] += 1

        thresholds = self._get_thresholds(process.process_type, process.legal_entity_id)
        duration = process.duration_seconds

        if duration <= thresholds.get("warning", 60):
            stats["compliant"] += 1
        elif duration <= thresholds.get("error", 120):
            stats["breaches"]["warning"] += 1
        elif duration <= thresholds.get("critical", 300):
            stats["breaches"]["error"] += 1
        else:
            stats["breaches"]["critical"] += 1

        # Update compliance rate
        stats["compliance_rate"] = (stats["compliant"] / stats["total"]) * 100

    def get_compliance_stats(
        self, process_type: SLAProcessType | None = None, legal_entity_id: str | None = None
    ) -> dict[str, Any]:
        """
        Get SLA compliance statistics.
        """
        results = {}
        for key, stats in self._compliance_stats.items():
            key_parts = key.split(":")
            key_type = key_parts[0]
            key_entity = key_parts[1] if len(key_parts) > 1 else None

            if process_type and key_type != process_type.value:
                continue
            if legal_entity_id and key_entity != legal_entity_id:
                continue

            results[key] = stats

        return results

    def get_alert_history(self, limit: int = 100) -> list[dict]:
        """Get SLA breach alert history."""
        return self._alert_history[-limit:]

    def update_thresholds(
        self,
        process_type: SLAProcessType,
        warning_seconds: int,
        error_seconds: int,
        critical_seconds: int,
        legal_entity_id: str | None = None,
    ) -> None:
        """
        Update SLA thresholds dynamically.
        """
        if legal_entity_id:
            if "legal_entity_thresholds" not in self.config:
                self.config["legal_entity_thresholds"] = {}
            if legal_entity_id not in self.config["legal_entity_thresholds"]:
                self.config["legal_entity_thresholds"][legal_entity_id] = {}
            self.config["legal_entity_thresholds"][legal_entity_id][process_type.value] = {
                "warning": warning_seconds,
                "error": error_seconds,
                "critical": critical_seconds,
            }
        else:
            if process_type not in self._thresholds:
                self._thresholds[process_type] = {}
            self._thresholds[process_type]["warning"] = warning_seconds
            self._thresholds[process_type]["error"] = error_seconds
            self._thresholds[process_type]["critical"] = critical_seconds

        logger.info(
            f"SLA thresholds updated for {process_type.value}: "
            f"warning={warning_seconds}s, error={error_seconds}s, critical={critical_seconds}s"
        )

    def reset_stats(self) -> None:
        """Reset compliance statistics."""
        self._compliance_stats.clear()
        logger.info("SLA compliance stats reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_sla_alerter: SLABreachAlerter | None = None


def get_sla_alerter() -> SLABreachAlerter:
    """Get singleton instance of SLABreachAlerter."""
    global _sla_alerter
    if _sla_alerter is None:
        _sla_alerter = SLABreachAlerter()
    return _sla_alerter


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class SLAMonitor:
    """
    Context manager untuk memonitor SLA process.

    Usage:
        async with SLAMonitor(SLAProcessType.JOURNAL_POSTING, journal_id) as monitor:
            await post_journal()
            monitor.complete()
    """

    def __init__(
        self,
        process_type: SLAProcessType,
        process_id: str,
        legal_entity_id: str | None = None,
        user_id: str | None = None,
        metadata: dict | None = None,
    ):
        self.process_type = process_type
        self.process_id = process_id
        self.legal_entity_id = legal_entity_id
        self.user_id = user_id
        self.metadata = metadata
        self._process_key: str | None = None
        self._alerter = get_sla_alerter()

    async def __aenter__(self):
        self._process_key = self._alerter.start_process(
            self.process_type, self.process_id, self.legal_entity_id, self.user_id, self.metadata
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._process_key:
            self._alerter.complete_process(self._process_key)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["SLABreachAlerter", "SLAMonitor", "SLAProcessType", "SLASeverity", "get_sla_alerter"]
