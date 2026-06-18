#!/usr/bin/env python3
"""
Module: journal_posting_latency_metrics.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengumpulkan dan mengekspor metrik latency untuk operasi posting jurnal.
               Melacak durasi setiap tahap posting jurnal: validasi, approval,
               posting ke ledger, dan event publishing. Metrik digunakan untuk
               monitoring performance SLO (Service Level Objective) dan alerting.
Dependencies:
- time, asyncio
- infrastructure.telemetry.prometheus_registry (PrometheusMetricRegistry)
- infrastructure.telemetry.structured_json_logging
Audit: Metrik latency digunakan untuk performance monitoring dan capacity planning.
       Pelanggaran SLO memicu alert.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from infrastructure.telemetry.alert_manager_router import trigger_alert

# Internal dependencies
from infrastructure.telemetry.prometheus_registry import (
    get_counter,
    get_gauge,
    get_histogram,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

METRIC_PREFIX = "journal_posting"
NAMESPACE = "erp"

# SLO thresholds (seconds)
SLO_TARGET_P95 = 1.0  # 95% of postings should complete within 1 second
SLO_TARGET_P99 = 2.0  # 99% within 2 seconds
SLO_WARNING = 3.0  # Warning if > 3 seconds
SLO_CRITICAL = 5.0  # Critical if > 5 seconds

# Posting stages
STAGE_VALIDATION = "validation"
STAGE_APPROVAL = "approval"
STAGE_LEDGER_POSTING = "ledger_posting"
STAGE_EVENT_PUBLISHING = "event_publishing"
STAGE_TOTAL = "total"

# ============================================================================
# METRICS
# ============================================================================

# Latency histograms
posting_latency = get_histogram(
    f"{METRIC_PREFIX}_latency_seconds",
    "Journal posting latency by stage",
    ["stage", "legal_entity_id"],
    buckets=[
        0.01,
        0.025,
        0.05,
        0.075,
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        1.5,
        2.0,
        2.5,
        3.0,
        5.0,
        7.5,
        10.0,
    ],
)

# Counters
posting_total = get_counter(
    f"{METRIC_PREFIX}_total", "Total number of journal postings", ["status", "legal_entity_id"]
)

posting_errors = get_counter(
    f"{METRIC_PREFIX}_errors_total",
    "Total number of journal posting errors",
    ["error_type", "legal_entity_id"],
)

# Gauges for SLO compliance
slo_compliance = get_gauge(
    f"{METRIC_PREFIX}_slo_compliance",
    "SLO compliance status (1=compliant, 0=violated)",
    ["slo_level", "legal_entity_id"],
)

concurrent_postings = get_gauge(
    f"{METRIC_PREFIX}_concurrent", "Number of concurrent journal postings", ["legal_entity_id"]
)

queue_size = get_gauge(
    f"{METRIC_PREFIX}_queue_size", "Number of journals waiting to be posted", ["legal_entity_id"]
)


# ============================================================================
# METRICS COLLECTOR
# ============================================================================


class JournalPostingLatencyMetrics:
    """
    Collector untuk metrik latency posting jurnal.

    Fitur:
    - Melacak durasi per stage posting
    - Menghitung SLO compliance
    - Alert untuk pelanggaran SLO
    - Concurrent posting tracking
    """

    def __init__(self):
        self._active_postings: dict[str, dict[str, float]] = {}
        self._stage_times: dict[str, list[float]] = {}
        self._last_slo_check: datetime | None = None

    def start_posting(self, journal_id: UUID, legal_entity_id: UUID) -> str:
        """
        Start tracking a journal posting.
        Returns tracking ID.
        """
        tracking_id = f"{journal_id}_{time.time()}"
        self._active_postings[tracking_id] = {
            "journal_id": str(journal_id),
            "legal_entity_id": str(legal_entity_id),
            "start_time": time.time(),
            "stages": {},
        }

        # Update concurrent gauge
        concurrent_postings.labels(legal_entity_id=str(legal_entity_id)).set(
            len(
                [
                    p
                    for p in self._active_postings.values()
                    if p["legal_entity_id"] == str(legal_entity_id)
                ]
            )
        )

        return tracking_id

    def record_stage(self, tracking_id: str, stage: str) -> None:
        """
        Record completion of a posting stage.
        """
        if tracking_id not in self._active_postings:
            logger.warning(f"Tracking ID {tracking_id} not found")
            return

        posting = self._active_postings[tracking_id]
        current_time = time.time()

        if stage not in posting["stages"]:
            # Calculate duration since last stage or start
            last_time = posting.get("start_time")
            for s in ["validation", "approval", "ledger_posting", "event_publishing"]:
                if s in posting["stages"]:
                    last_time = posting["stages"][s]
                else:
                    break

            duration = current_time - last_time
            posting["stages"][stage] = current_time

            # Record metric
            posting_latency.labels(stage=stage, legal_entity_id=posting["legal_entity_id"]).observe(
                duration
            )

            logger.debug(f"Stage {stage} completed in {duration:.3f}s for {tracking_id}")

    def complete_posting(
        self, tracking_id: str, success: bool = True, error_type: str | None = None
    ) -> None:
        """
        Complete tracking of a journal posting.
        """
        if tracking_id not in self._active_postings:
            return

        posting = self._active_postings[tracking_id]
        total_duration = time.time() - posting["start_time"]

        # Record total latency
        posting_latency.labels(
            stage=STAGE_TOTAL, legal_entity_id=posting["legal_entity_id"]
        ).observe(total_duration)

        # Update counters
        status = "success" if success else "failed"
        posting_total.labels(status=status, legal_entity_id=posting["legal_entity_id"]).inc()

        if not success and error_type:
            posting_errors.labels(
                error_type=error_type, legal_entity_id=posting["legal_entity_id"]
            ).inc()

        # Check SLO
        self._check_slo(total_duration, posting["legal_entity_id"])

        # Alert if too slow
        if total_duration > SLO_CRITICAL:
            asyncio.create_task(
                trigger_alert(
                    title="Journal Posting Slow",
                    message=f"Journal posting took {total_duration:.2f}s (critical: {SLO_CRITICAL}s)",
                    severity="warning",
                    source="JournalPostingLatencyMetrics",
                )
            )
        elif total_duration > SLO_WARNING:
            asyncio.create_task(
                trigger_alert(
                    title="Journal Posting Slow",
                    message=f"Journal posting took {total_duration:.2f}s (warning: {SLO_WARNING}s)",
                    severity="info",
                    source="JournalPostingLatencyMetrics",
                )
            )

        # Remove from active
        del self._active_postings[tracking_id]

        # Update concurrent gauge
        legal_entity_id = posting["legal_entity_id"]
        concurrent_postings.labels(legal_entity_id=legal_entity_id).set(
            len(
                [
                    p
                    for p in self._active_postings.values()
                    if p["legal_entity_id"] == legal_entity_id
                ]
            )
        )

        logger.info(f"Posting {tracking_id} completed in {total_duration:.3f}s, success={success}")

    def _check_slo(self, duration: float, legal_entity_id: str) -> None:
        """
        Check SLO compliance and update gauge.
        """
        # For P95 (simplified - in production use sliding window)
        if duration <= SLO_TARGET_P95:
            slo_compliance.labels(slo_level="p95", legal_entity_id=legal_entity_id).set(1)
        else:
            slo_compliance.labels(slo_level="p95", legal_entity_id=legal_entity_id).set(0)

        if duration <= SLO_TARGET_P99:
            slo_compliance.labels(slo_level="p99", legal_entity_id=legal_entity_id).set(1)
        else:
            slo_compliance.labels(slo_level="p99", legal_entity_id=legal_entity_id).set(0)

    def update_queue_size(self, legal_entity_id: UUID, size: int) -> None:
        """
        Update queue size gauge.
        """
        queue_size.labels(legal_entity_id=str(legal_entity_id)).set(size)

    def get_stats(self) -> dict[str, Any]:
        """
        Get current metrics statistics.
        """
        return {
            "active_postings": len(self._active_postings),
            "active_postings_detail": self._active_postings,
            "slo_target_p95": SLO_TARGET_P95,
            "slo_target_p99": SLO_TARGET_P99,
            "slo_warning": SLO_WARNING,
            "slo_critical": SLO_CRITICAL,
        }

    def reset(self) -> None:
        """Reset metrics (for testing)."""
        self._active_postings.clear()
        self._stage_times.clear()
        logger.info("Journal posting metrics reset")


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class PostingLatencyContext:
    """
    Context manager untuk mengukur latency posting jurnal.

    Usage:
        async with PostingLatencyContext(journal_id, legal_entity_id) as ctx:
            await ctx.record_stage("validation")
            # do validation
            await ctx.record_stage("approval")
            # do approval
            ...
    """

    def __init__(self, journal_id: UUID, legal_entity_id: UUID):
        self.journal_id = journal_id
        self.legal_entity_id = legal_entity_id
        self._metrics = JournalPostingLatencyMetrics()
        self._tracking_id: str | None = None

    async def __aenter__(self):
        self._tracking_id = self._metrics.start_posting(self.journal_id, self.legal_entity_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        success = exc_type is None
        error_type = exc_type.__name__ if exc_type else None
        self._metrics.complete_posting(self._tracking_id, success, error_type)

    async def record_stage(self, stage: str) -> None:
        """
        Record completion of a posting stage.
        """
        if self._tracking_id:
            self._metrics.record_stage(self._tracking_id, stage)


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_journal_metrics: JournalPostingLatencyMetrics | None = None


def get_journal_posting_metrics() -> JournalPostingLatencyMetrics:
    """Get singleton instance of JournalPostingLatencyMetrics."""
    global _journal_metrics
    if _journal_metrics is None:
        _journal_metrics = JournalPostingLatencyMetrics()
    return _journal_metrics


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "STAGE_APPROVAL",
    "STAGE_EVENT_PUBLISHING",
    "STAGE_LEDGER_POSTING",
    "STAGE_TOTAL",
    "STAGE_VALIDATION",
    "JournalPostingLatencyMetrics",
    "PostingLatencyContext",
    "get_journal_posting_metrics",
]
