#!/usr/bin/env python3
"""
Module: coretax_api_latency_metrics.py
Layer: Infrastructure (Telemetry)
Responsibility: Mengumpulkan dan mengekspor metrik latency untuk panggilan API
               ke Coretax DJP. Melacak durasi request, status code, dan error rate.
               Membantu dalam monitoring kesehatan integrasi Coretax dan SLO compliance.
Dependencies:
- time, asyncio
- infrastructure.telemetry.prometheus_registry (PrometheusMetricRegistry)
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Metrik latency Coretax digunakan untuk monitoring SLA dan troubleshooting.
       Latency tinggi atau error rate tinggi memicu alert.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from typing import Any

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

METRIC_PREFIX = "coretax_api"
NAMESPACE = "erp"

# API endpoints
API_ENDPOINTS = {
    "faktur_submit": "/api/v1/faktur-pajak/keluaran",
    "faktur_status": "/api/v1/faktur-pajak/status",
    "faktur_cancel": "/api/v1/faktur-pajak/batal",
    "nsfp_request": "/api/v1/nsfp/request",
    "nsfp_quota": "/api/v1/nsfp/quota",
    "spt_ppn": "/api/v1/spt/ppn",
    "spt_pph21": "/api/v1/spt/pph21",
    "spt_pph23": "/api/v1/spt/pph23",
    "spt_tahunan": "/api/v1/spt/tahunan",
    "bupot_submit": "/api/v1/e-bupot/submit",
    "bupot_cancel": "/api/v1/e-bupot/cancel",
    "ntpn_validate": "/api/v1/ntpn/validate",
    "emeterai_validate": "/api/v1/e-meterai/validate",
    "emeterai_purchase": "/api/v1/e-meterai/purchase",
    "token": "/oauth2/token",
}

# SLO thresholds (seconds)
SLO_TARGET_P95 = 2.0  # 95% of requests within 2 seconds
SLO_TARGET_P99 = 5.0  # 99% within 5 seconds
SLO_WARNING = 10.0  # Warning if > 10 seconds
SLO_CRITICAL = 30.0  # Critical if > 30 seconds

# Error rate thresholds
ERROR_RATE_WARNING = 0.05  # 5% error rate warning
ERROR_RATE_CRITICAL = 0.10  # 10% error rate critical

# ============================================================================
# METRICS
# ============================================================================

# Latency histogram
api_latency = get_histogram(
    f"{METRIC_PREFIX}_latency_seconds",
    "Coretax API call latency",
    ["endpoint", "method"],
    buckets=[0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0, 30.0],
)

# Counters
api_requests_total = get_counter(
    f"{METRIC_PREFIX}_requests_total",
    "Total Coretax API requests",
    ["endpoint", "method", "status_code"],
)

api_errors_total = get_counter(
    f"{METRIC_PREFIX}_errors_total", "Total Coretax API errors", ["endpoint", "error_type"]
)

# Gauges
slo_compliance = get_gauge(
    f"{METRIC_PREFIX}_slo_compliance",
    "SLO compliance status (1=compliant, 0=violated)",
    ["slo_level"],
)

error_rate = get_gauge(
    f"{METRIC_PREFIX}_error_rate", "Current error rate (5-minute window)", ["endpoint"]
)

# Token expiry gauge (seconds until expiry)
token_expiry_seconds = get_gauge(
    f"{METRIC_PREFIX}_token_expiry_seconds", "Seconds until Coretax access token expires"
)

# Rate limit remaining
rate_limit_remaining = get_gauge(
    f"{METRIC_PREFIX}_rate_limit_remaining", "Remaining rate limit for Coretax API", ["endpoint"]
)


# ============================================================================
# METRICS COLLECTOR
# ============================================================================


class CoretaxAPILatencyMetrics:
    """
    Collector untuk metrik latency API Coretax.

    Fitur:
    - Melacak latency per endpoint
    - Menghitung error rate
    - Monitoring token expiry
    - Alert untuk latency tinggi
    """

    def __init__(self):
        self._request_counts: dict[str, int] = {}
        self._error_counts: dict[str, int] = {}
        self._window_start: datetime | None = None
        self._window_requests: dict[str, list[dict]] = {}
        self._last_alert_time: dict[str, datetime] = {}

    def record_request(
        self,
        endpoint: str,
        method: str,
        duration_seconds: float,
        status_code: int,
        error_type: str | None = None,
    ) -> None:
        """
        Record a Coretax API request.
        """
        endpoint_name = self._get_endpoint_name(endpoint)

        # Record latency
        api_latency.labels(endpoint=endpoint_name, method=method).observe(duration_seconds)

        # Record request count
        api_requests_total.labels(
            endpoint=endpoint_name, method=method, status_code=str(status_code)
        ).inc()

        # Record error if any
        if error_type or status_code >= 400:
            error_type_val = error_type or f"http_{status_code}"
            api_errors_total.labels(endpoint=endpoint_name, error_type=error_type_val).inc()

            # Track for error rate calculation
            key = f"{endpoint_name}"
            if key not in self._error_counts:
                self._error_counts[key] = 0
            self._error_counts[key] += 1

        # Track for error rate window
        key = f"{endpoint_name}"
        if key not in self._window_requests:
            self._window_requests[key] = []
        self._window_requests[key].append(
            {
                "timestamp": datetime.now(UTC),
                "is_error": status_code >= 400 or error_type is not None,
            }
        )

        # Clean old window data
        self._clean_window()

        # Update error rate gauge
        self._update_error_rate_gauge()

        # Check SLO
        self._check_slo(duration_seconds, endpoint_name)

        # Alert if too slow
        if duration_seconds > SLO_CRITICAL:
            asyncio.create_task(self._alert_slow_request(endpoint_name, duration_seconds))
        elif duration_seconds > SLO_WARNING:
            asyncio.create_task(
                self._alert_slow_request(endpoint_name, duration_seconds, "warning")
            )

    def _get_endpoint_name(self, endpoint: str) -> str:
        """
        Get friendly endpoint name from URL.
        """
        for name, url in API_ENDPOINTS.items():
            if url in endpoint or endpoint.endswith(name):
                return name
        # Return last part of endpoint
        parts = endpoint.rstrip("/").split("/")
        return parts[-1] if parts else "unknown"

    def _clean_window(self) -> None:
        """
        Clean up window data older than 5 minutes.
        """
        cutoff = datetime.now(UTC) - timedelta(minutes=5)

        for key in list(self._window_requests.keys()):
            self._window_requests[key] = [
                req for req in self._window_requests[key] if req["timestamp"] > cutoff
            ]

    def _update_error_rate_gauge(self) -> None:
        """
        Update error rate gauge for each endpoint.
        """
        for endpoint, requests in self._window_requests.items():
            if not requests:
                error_rate.labels(endpoint=endpoint).set(0)
                continue

            error_count = sum(1 for req in requests if req["is_error"])
            rate = error_count / len(requests)
            error_rate.labels(endpoint=endpoint).set(rate)

            # Check error rate thresholds
            if rate > ERROR_RATE_CRITICAL:
                asyncio.create_task(self._alert_high_error_rate(endpoint, rate, "critical"))
            elif rate > ERROR_RATE_WARNING:
                asyncio.create_task(self._alert_high_error_rate(endpoint, rate, "warning"))

    def _check_slo(self, duration: float, endpoint: str) -> None:
        """
        Check SLO compliance.
        """
        # Simple sliding window check - in production use more sophisticated
        if duration <= SLO_TARGET_P95:
            slo_compliance.labels(slo_level="p95").set(1)
        else:
            slo_compliance.labels(slo_level="p95").set(0)

        if duration <= SLO_TARGET_P99:
            slo_compliance.labels(slo_level="p99").set(1)
        else:
            slo_compliance.labels(slo_level="p99").set(0)

    async def _alert_slow_request(
        self, endpoint: str, duration: float, severity: str = "critical"
    ) -> None:
        """
        Alert for slow Coretax API requests.
        """
        key = f"slow_{endpoint}"
        now = datetime.now(UTC)

        # Rate limit alerts (max 1 per 5 minutes per endpoint)
        if key in self._last_alert_time:
            if (now - self._last_alert_time[key]).total_seconds() < 300:
                return

        self._last_alert_time[key] = now

        await trigger_alert(
            title=f"Coretax API Slow Response ({severity})",
            message=f"Endpoint {endpoint} took {duration:.2f}s",
            severity="critical" if severity == "critical" else "warning",
            source="CoretaxAPILatencyMetrics",
        )

    async def _alert_high_error_rate(self, endpoint: str, rate: float, severity: str) -> None:
        """
        Alert for high error rate.
        """
        key = f"error_rate_{endpoint}"
        now = datetime.now(UTC)

        # Rate limit alerts (max 1 per 5 minutes per endpoint)
        if key in self._last_alert_time:
            if (now - self._last_alert_time[key]).total_seconds() < 300:
                return

        self._last_alert_time[key] = now

        await trigger_alert(
            title=f"Coretax API High Error Rate ({severity})",
            message=f"Endpoint {endpoint} has {rate:.1%} error rate in last 5 minutes",
            severity="critical" if severity == "critical" else "warning",
            source="CoretaxAPILatencyMetrics",
        )

    def update_token_expiry(self, expiry_timestamp: float) -> None:
        """
        Update token expiry gauge.
        """
        seconds_until_expiry = max(0, expiry_timestamp - time.time())
        token_expiry_seconds.set(seconds_until_expiry)

        # Alert if token expires soon
        if seconds_until_expiry < 300:
            asyncio.create_task(
                trigger_alert(
                    title="Coretax Token Expiring Soon",
                    message=f"Coretax access token expires in {seconds_until_expiry:.0f} seconds",
                    severity="warning",
                    source="CoretaxAPILatencyMetrics",
                )
            )

    def update_rate_limit(self, endpoint: str, remaining: int) -> None:
        """
        Update rate limit remaining gauge.
        """
        endpoint_name = self._get_endpoint_name(endpoint)
        rate_limit_remaining.labels(endpoint=endpoint_name).set(remaining)

        # Alert if rate limit low
        if remaining < 10:
            asyncio.create_task(
                trigger_alert(
                    title="Coretax Rate Limit Low",
                    message=f"Rate limit for {endpoint_name} has only {remaining} requests remaining",
                    severity="warning",
                    source="CoretaxAPILatencyMetrics",
                )
            )

    def get_stats(self) -> dict[str, Any]:
        """
        Get current metrics statistics.
        """
        return {
            "slo_target_p95": SLO_TARGET_P95,
            "slo_target_p99": SLO_TARGET_P99,
            "slo_warning": SLO_WARNING,
            "slo_critical": SLO_CRITICAL,
            "error_rate_warning": ERROR_RATE_WARNING,
            "error_rate_critical": ERROR_RATE_CRITICAL,
            "window_requests": {k: len(v) for k, v in self._window_requests.items()},
        }

    def reset(self) -> None:
        """Reset metrics (for testing)."""
        self._request_counts.clear()
        self._error_counts.clear()
        self._window_requests.clear()
        self._last_alert_time.clear()
        logger.info("Coretax API metrics reset")


# ============================================================================
# CONTEXT MANAGER
# ============================================================================


class CoretaxAPIContext:
    """
    Context manager untuk mengukur latency API Coretax.

    Usage:
        async with CoretaxAPIContext(endpoint, method) as ctx:
            response = await client.post(endpoint, data)
            ctx.record_status(response.status_code)
    """

    def __init__(self, endpoint: str, method: str = "POST"):
        self.endpoint = endpoint
        self.method = method
        self._metrics = CoretaxAPILatencyMetrics()
        self._start_time: float | None = None
        self._status_code: int = 0
        self._error_type: str | None = None

    async def __aenter__(self):
        self._start_time = time.time()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self._start_time
        self._metrics.record_request(
            endpoint=self.endpoint,
            method=self.method,
            duration_seconds=duration,
            status_code=self._status_code,
            error_type=self._error_type,
        )

    def record_status(self, status_code: int, error_type: str | None = None) -> None:
        """Record HTTP status code and optional error type."""
        self._status_code = status_code
        self._error_type = error_type

    def record_error(self, error_type: str) -> None:
        """Record an error without HTTP status."""
        self._status_code = 500
        self._error_type = error_type


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_coretax_metrics: CoretaxAPILatencyMetrics | None = None


def get_coretax_metrics() -> CoretaxAPILatencyMetrics:
    """Get singleton instance of CoretaxAPILatencyMetrics."""
    global _coretax_metrics
    if _coretax_metrics is None:
        _coretax_metrics = CoretaxAPILatencyMetrics()
    return _coretax_metrics


# ============================================================================
# DECORATOR
# ============================================================================


def measure_coretax_api(endpoint: str, method: str = "POST"):
    """
    Decorator untuk mengukur latency API Coretax.
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            async with CoretaxAPIContext(endpoint, method) as ctx:
                try:
                    result = await func(*args, **kwargs)
                    # Try to extract status code from result
                    if isinstance(result, dict) and "status_code" in result:
                        ctx.record_status(result["status_code"])
                    else:
                        ctx.record_status(200)
                    return result
                except Exception as e:
                    ctx.record_error(type(e).__name__)
                    raise

        return wrapper

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CoretaxAPIContext",
    "CoretaxAPILatencyMetrics",
    "get_coretax_metrics",
    "measure_coretax_api",
]
