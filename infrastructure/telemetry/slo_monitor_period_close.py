#!/usr/bin/env python3
"""
Module: slo_monitor_period_close.py
Layer: Infrastructure (Telemetry)
Responsibility: Memonitor Service Level Objective (SLO) untuk proses period closing.
               Melacak durasi period close, keberhasilan, dan kepatuhan terhadap
               target SLO (misal: period close harus selesai dalam 1 jam setelah
               periode berakhir). Juga mencatat penyebab kegagalan dan delay.
Dependencies:
- asyncio, logging, datetime
- infrastructure.telemetry.alert_manager_router (trigger_alert)
- infrastructure.telemetry.prometheus_registry (metrics)
- infrastructure.telemetry.structured_json_logging
- config.loader_yaml
Audit: Setiap period close dicatat untuk compliance audit trail.
       Pelanggaran SLO period close memicu alert ke finance team.
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

# SLO targets (hours after period end)
DEFAULT_SLO_TARGET_HOURS = 24  # Period close harus selesai dalam 24 jam setelah periode berakhir
DEFAULT_SLO_WARNING_HOURS = 12  # Warning jika lebih dari 12 jam
DEFAULT_SLO_CRITICAL_HOURS = 48  # Critical jika lebih dari 48 jam

# Metrics
period_close_duration = get_histogram(
    "period_close_duration_seconds",
    "Duration of period close process",
    ["legal_entity_id", "fiscal_year", "period", "status"],
    buckets=[60, 300, 600, 1800, 3600, 7200, 14400, 28800, 43200, 86400],
)

period_close_slo_compliance = get_gauge(
    "period_close_slo_compliance",
    "SLO compliance for period close (1=compliant, 0=violated)",
    ["legal_entity_id", "slo_level"],
)

period_close_total = get_counter(
    "period_close_total", "Total period close attempts", ["legal_entity_id", "status"]
)

# ============================================================================
# SLO MONITOR
# ============================================================================


class SLOMonitorPeriodClose:
    """
    Monitor SLO untuk period closing.

    Fitur:
    - Track period close start and end times
    - Calculate completion time relative to period end
    - Alert on SLO violations
    - Store history untuk reporting
    - Integration with Prometheus metrics
    """

    def __init__(self, config_path: str = "config_files/slo_config.yaml"):
        self.config = self._load_config(config_path)
        self._slo_target_hours = self.config.get("period_close", {}).get(
            "target_hours", DEFAULT_SLO_TARGET_HOURS
        )
        self._warning_hours = self.config.get("period_close", {}).get(
            "warning_hours", DEFAULT_SLO_WARNING_HOURS
        )
        self._critical_hours = self.config.get("period_close", {}).get(
            "critical_hours", DEFAULT_SLO_CRITICAL_HOURS
        )
        self._active_closes: dict[str, dict[str, Any]] = {}
        self._close_history: list[dict[str, Any]] = []

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            return load_yaml_config(config_path)
        except Exception:
            return {}

    def _get_key(self, legal_entity_id: UUID, fiscal_year: int, period: int) -> str:
        """Generate unique key for period close."""
        return f"{legal_entity_id}:{fiscal_year}:{period}"

    def start_period_close(
        self, legal_entity_id: UUID, fiscal_year: int, period: int, started_by: UUID | None = None
    ) -> str:
        """
        Start monitoring a period close process.

        Returns:
            Close key for tracking
        """
        key = self._get_key(legal_entity_id, fiscal_year, period)

        # Calculate period end date based on fiscal year and period
        period_end_date = self._calculate_period_end_date(fiscal_year, period)

        self._active_closes[key] = {
            "legal_entity_id": str(legal_entity_id),
            "fiscal_year": fiscal_year,
            "period": period,
            "period_end_date": period_end_date,
            "started_at": datetime.now(UTC),
            "started_by": str(started_by) if started_by else None,
            "status": "in_progress",
            "completed_at": None,
            "completed_by": None,
            "duration_seconds": None,
            "hours_after_period_end": None,
            "errors": [],
        }

        logger.info(f"Period close started for {legal_entity_id} FY{fiscal_year}P{period}")
        return key

    def _calculate_period_end_date(self, fiscal_year: int, period: int) -> datetime:
        """
        Calculate period end date based on fiscal year and period number.
        Assumes calendar year with periods = months (1-12).
        """
        # For period 13 (adjustment period), end date is last day of fiscal year
        if period == 13:
            return datetime(fiscal_year, 12, 31, 23, 59, 59, tzinfo=UTC)

        # Last day of month
        if period == 2:
            last_day = 29 if self._is_leap_year(fiscal_year) else 28
        elif period in [4, 6, 9, 11]:
            last_day = 30
        else:
            last_day = 31

        return datetime(fiscal_year, period, last_day, 23, 59, 59, tzinfo=UTC)

    def _is_leap_year(self, year: int) -> bool:
        """Check if year is leap year."""
        return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

    def complete_period_close(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        completed_by: UUID | None = None,
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Complete period close monitoring and check SLO.

        Returns:
            Result dictionary with SLO compliance info
        """
        key = self._get_key(legal_entity_id, fiscal_year, period)

        if key not in self._active_closes:
            logger.warning(f"Period close {key} not found in active processes")
            return {"error": "not_found"}

        close_data = self._active_closes[key]
        close_data["completed_at"] = datetime.now(UTC)
        close_data["completed_by"] = str(completed_by) if completed_by else None
        close_data["status"] = "completed"
        close_data["errors"] = errors or []

        # Calculate duration
        duration_seconds = (close_data["completed_at"] - close_data["started_at"]).total_seconds()
        close_data["duration_seconds"] = duration_seconds

        # Calculate hours after period end
        period_end = close_data["period_end_date"]
        completed_at = close_data["completed_at"]

        if completed_at > period_end:
            hours_after = (completed_at - period_end).total_seconds() / 3600
            close_data["hours_after_period_end"] = hours_after
        else:
            close_data["hours_after_period_end"] = 0

        # Check SLO compliance
        hours_after = close_data["hours_after_period_end"]
        slo_compliant = hours_after <= self._slo_target_hours
        warning_violated = hours_after > self._warning_hours
        critical_violated = hours_after > self._critical_hours

        close_data["slo_compliant"] = slo_compliant
        close_data["warning_violated"] = warning_violated
        close_data["critical_violated"] = critical_violated

        # Update Prometheus metrics
        status = "success" if slo_compliant else "failed"
        period_close_total.labels(legal_entity_id=str(legal_entity_id), status=status).inc()

        period_close_duration.labels(
            legal_entity_id=str(legal_entity_id),
            fiscal_year=str(fiscal_year),
            period=str(period),
            status=status,
        ).observe(duration_seconds)

        period_close_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id), slo_level="target"
        ).set(1 if slo_compliant else 0)

        period_close_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id), slo_level="warning"
        ).set(1 if not warning_violated else 0)

        period_close_slo_compliance.labels(
            legal_entity_id=str(legal_entity_id), slo_level="critical"
        ).set(1 if not critical_violated else 0)

        # Add to history
        self._close_history.append(close_data.copy())
        if len(self._close_history) > 100:
            self._close_history = self._close_history[-100:]

        # Remove from active
        del self._active_closes[key]

        # Send alert if SLO violated
        if critical_violated:
            asyncio.create_task(
                trigger_alert(
                    title="Period Close SLO Critical Violation",
                    message=f"Period close for FY{fiscal_year}P{period} completed {hours_after:.1f} hours after period end "
                    f"(critical threshold: {self._critical_hours}h)",
                    severity=SEVERITY_CRITICAL,
                    source="SLOMonitorPeriodClose",
                    metadata={
                        "legal_entity_id": str(legal_entity_id),
                        "fiscal_year": fiscal_year,
                        "period": period,
                        "hours_after": hours_after,
                        "duration_seconds": duration_seconds,
                    },
                )
            )
        elif warning_violated:
            asyncio.create_task(
                trigger_alert(
                    title="Period Close SLO Warning",
                    message=f"Period close for FY{fiscal_year}P{period} completed {hours_after:.1f} hours after period end "
                    f"(warning threshold: {self._warning_hours}h)",
                    severity=SEVERITY_WARNING,
                    source="SLOMonitorPeriodClose",
                    metadata={
                        "legal_entity_id": str(legal_entity_id),
                        "fiscal_year": fiscal_year,
                        "period": period,
                        "hours_after": hours_after,
                    },
                )
            )

        logger.info(
            f"Period close completed for {key}: {duration_seconds:.2f}s, "
            f"hours after period end: {hours_after:.2f}, SLO compliant: {slo_compliant}"
        )

        return {
            "key": key,
            "duration_seconds": duration_seconds,
            "hours_after_period_end": hours_after,
            "slo_compliant": slo_compliant,
            "warning_violated": warning_violated,
            "critical_violated": critical_violated,
        }

    def fail_period_close(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        period: int,
        error: str,
        failed_by: UUID | None = None,
    ) -> None:
        """
        Mark period close as failed.
        """
        key = self._get_key(legal_entity_id, fiscal_year, period)

        if key not in self._active_closes:
            logger.warning(f"Period close {key} not found in active processes")
            return

        close_data = self._active_closes[key]
        close_data["status"] = "failed"
        close_data["failed_at"] = datetime.now(UTC)
        close_data["failed_by"] = str(failed_by) if failed_by else None
        close_data["error"] = error

        period_close_total.labels(legal_entity_id=str(legal_entity_id), status="failed").inc()

        asyncio.create_task(
            trigger_alert(
                title="Period Close Failed",
                message=f"Period close for FY{fiscal_year}P{period} failed: {error}",
                severity=SEVERITY_ERROR,
                source="SLOMonitorPeriodClose",
                metadata={
                    "legal_entity_id": str(legal_entity_id),
                    "fiscal_year": fiscal_year,
                    "period": period,
                    "error": error,
                },
            )
        )

        logger.error(f"Period close failed for {key}: {error}")

        # Remove from active
        del self._active_closes[key]

    def get_active_closes(self) -> list[dict[str, Any]]:
        """Get currently active period closes."""
        return list(self._active_closes.values())

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get period close history."""
        return self._close_history[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get SLO statistics."""
        total_closes = len(self._close_history)
        if total_closes == 0:
            return {"total": 0, "slo_compliance_rate": 0}

        compliant_count = sum(1 for c in self._close_history if c.get("slo_compliant", False))

        return {
            "total_period_closes": total_closes,
            "slo_compliant_count": compliant_count,
            "slo_compliance_rate": (compliant_count / total_closes) * 100,
            "target_hours": self._slo_target_hours,
            "warning_hours": self._warning_hours,
            "critical_hours": self._critical_hours,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_slo_period_close_monitor: SLOMonitorPeriodClose | None = None


def get_slo_period_close_monitor() -> SLOMonitorPeriodClose:
    """Get singleton instance of SLOMonitorPeriodClose."""
    global _slo_period_close_monitor
    if _slo_period_close_monitor is None:
        _slo_period_close_monitor = SLOMonitorPeriodClose()
    return _slo_period_close_monitor


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class PeriodCloseSLAMonitor:
    """
    Context manager untuk memonitor SLO period close.

    Usage:
        async with PeriodCloseSLAMonitor(legal_entity_id, fiscal_year, period) as monitor:
            await close_period()
            monitor.complete()
    """

    def __init__(
        self, legal_entity_id: UUID, fiscal_year: int, period: int, started_by: UUID | None = None
    ):
        self.legal_entity_id = legal_entity_id
        self.fiscal_year = fiscal_year
        self.period = period
        self.started_by = started_by
        self._monitor = get_slo_period_close_monitor()
        self._key: str | None = None

    async def __aenter__(self):
        self._key = self._monitor.start_period_close(
            self.legal_entity_id, self.fiscal_year, self.period, self.started_by
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._monitor.fail_period_close(
                self.legal_entity_id, self.fiscal_year, self.period, str(exc_val), self.started_by
            )
        else:
            self._monitor.complete_period_close(
                self.legal_entity_id, self.fiscal_year, self.period, self.started_by
            )


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = ["PeriodCloseSLAMonitor", "SLOMonitorPeriodClose", "get_slo_period_close_monitor"]
