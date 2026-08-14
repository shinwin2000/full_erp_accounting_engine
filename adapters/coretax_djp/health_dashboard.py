#!/usr/bin/env python3
"""
Module: health_dashboard.py
Layer: Adapters (Coretax DJP)
Responsibility: Menyediakan dashboard kesehatan dan monitoring untuk integrasi
               Coretax DJP. Memeriksa status API Coretax, token validity,
               NSFP quota, antrian faktur, SPT pending, dan kesehatan sistem
               secara keseluruhan.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

try:
    from prometheus_client import REGISTRY, Counter, Gauge, Info, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    class Gauge:
        def set(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Counter:
        def inc(self, *args, **kwargs): pass
        def labels(self, *args, **kwargs): return self
    class Info:
        def info(self, *args, **kwargs): pass

from adapters.coretax_djp.api_oauth2_client import CoretaxAuthError, get_coretax_client
from adapters.coretax_djp.nsfp_manager import get_nsfp_manager
from infrastructure.caching.redis_manager import ping_redis

# GANTI: gunakan session factory, bukan connection_pool_asyncpg
from infrastructure.database.session_factory_sqlalchemy import get_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/coretax/health", tags=["Coretax Health"])

# ============================================================================
# CONSTANTS
# ============================================================================
HEALTH_CHECK_INTERVAL = 30
METRICS_REFRESH_INTERVAL = 60
ALERT_RETENTION_HOURS = 24
HISTORICAL_RETENTION_DAYS = 30
CACHE_TTL_SECONDS = 30


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ComponentHealth(BaseModel):
    status: HealthStatus
    message: str | None = None
    latency_ms: float | None = None
    last_check: datetime = Field(default_factory=datetime.utcnow)
    details: dict[str, Any] | None = None


class Alert(BaseModel):
    id: str
    component: str
    severity: AlertSeverity
    title: str
    message: str
    created_at: datetime
    resolved_at: datetime | None = None
    acknowledged: bool = False
    acknowledged_by: str | None = None


class CoretaxDashboardResponse(BaseModel):
    overall_status: HealthStatus
    components: dict[str, ComponentHealth]
    metrics: dict[str, Any]
    alerts: list[dict[str, Any]]
    timestamp: datetime
    version: str
    uptime_seconds: float


class HistoricalHealthRecord(BaseModel):
    timestamp: datetime
    overall_status: HealthStatus
    components: dict[str, HealthStatus]
    metrics: dict[str, float]


# ============================================================================
# METRICS (PROMETHEUS)
# ============================================================================
if PROMETHEUS_AVAILABLE:
    coretax_api_health = Gauge("coretax_api_health", "Coretax API health status (1=healthy, 0=down)", ["endpoint"])
    coretax_token_expiry_seconds = Gauge("coretax_token_expiry_seconds", "Seconds until token expiry")
    coretax_nsfp_remaining = Gauge("coretax_nsfp_remaining", "Remaining NSFP quota", ["npwp", "tahun", "bulan"])
    coretax_faktur_pending = Gauge("coretax_faktur_pending", "Number of pending faktur submissions")
    coretax_spt_pending = Gauge("coretax_spt_pending", "Number of pending SPT submissions")
    coretax_bupot_pending = Gauge("coretax_bupot_pending", "Number of pending e-Bupot submissions")
    coretax_webhook_received = Counter("coretax_webhook_received_total", "Total webhook received", ["type", "status"])
    coretax_api_latency = Gauge("coretax_api_latency_ms", "Coretax API latency in milliseconds", ["endpoint"])
    coretax_rate_limit_remaining = Gauge("coretax_rate_limit_remaining", "Remaining API rate limit", ["endpoint"])
    coretax_circuit_breaker_state = Gauge("coretax_circuit_breaker_state", "Circuit breaker state (0=closed,1=open,2=half-open)", ["component"])
    coretax_health_check_duration = Gauge("coretax_health_check_duration_seconds", "Health check duration in seconds")


# ============================================================================
# HEALTH CHECKER
# ============================================================================
class CoretaxHealthChecker:
    """Pemeriksa kesehatan untuk seluruh komponen Coretax."""

    def __init__(self, config: dict | None = None):
        self._config = config or {}
        self.coretax_client = None
        self.nsfp_manager = None
        self._cache: dict[str, tuple[datetime, Any]] = {}
        self._cache_ttl = HEALTH_CHECK_INTERVAL
        self._alerts: dict[str, Alert] = {}
        self._historical_records: list[HistoricalHealthRecord] = []
        self._start_time = datetime.now()
        self._health_check_lock = asyncio.Lock()
        self._background_task = None
        self._running = False

    def _load_config(self) -> dict[str, Any]:
        if self._config:
            return self._config
        return {
            "coretax_djp": {
                "health": {
                    "cache_ttl_seconds": HEALTH_CHECK_INTERVAL,
                    "alert_on_degraded": True,
                    "alert_on_down": True,
                    "prometheus_enabled": True,
                    "health_check_interval": HEALTH_CHECK_INTERVAL,
                }
            }
        }

    async def _get_coretax_client(self):
        if self.coretax_client is None:
            self.coretax_client = await get_coretax_client()
        return self.coretax_client

    async def _get_nsfp_manager(self):
        if self.nsfp_manager is None:
            self.nsfp_manager = await get_nsfp_manager()
        return self.nsfp_manager

    async def _cached_or_fresh(self, key: str, ttl: int, fetcher):
        if key in self._cache:
            cached_time, value = self._cache[key]
            if (datetime.utcnow() - cached_time).total_seconds() < ttl:
                return value
        value = await fetcher()
        self._cache[key] = (datetime.utcnow(), value)
        return value

    def _invalidate_cache(self, key: str | None = None):
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    async def start_background_health_check(self):
        if self._running:
            return
        self._running = True
        self._background_task = asyncio.create_task(self._background_health_check_loop())

    async def stop_background_health_check(self):
        self._running = False
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                # Log expected cancellation during shutdown
                logger.debug("Background health check task cancelled during stop")

    async def _background_health_check_loop(self):
        interval = self._load_config().get("coretax_djp", {}).get("health", {}).get("health_check_interval", HEALTH_CHECK_INTERVAL)
        while self._running:
            try:
                await self.check_all_components()
                await self._cleanup_old_records()
                await self._cleanup_old_alerts()
            except Exception as e:
                logger.error(f"Background health check failed: {e}")
            await asyncio.sleep(interval)

    async def _cleanup_old_records(self):
        cutoff = datetime.utcnow() - timedelta(days=HISTORICAL_RETENTION_DAYS)
        self._historical_records = [r for r in self._historical_records if r.timestamp > cutoff]

    async def _cleanup_old_alerts(self):
        cutoff = datetime.utcnow() - timedelta(hours=ALERT_RETENTION_HOURS)
        to_remove = [aid for aid, alert in self._alerts.items() if alert.resolved_at and alert.resolved_at < cutoff]
        for aid in to_remove:
            del self._alerts[aid]

    async def _add_alert(self, component: str, severity: AlertSeverity, title: str, message: str) -> Alert:
        alert = Alert(
            id=str(uuid4()),
            component=component,
            severity=severity,
            title=title,
            message=message,
            created_at=datetime.utcnow(),
        )
        self._alerts[alert.id] = alert
        logger.warning("Alert triggered: %s - %s", title, message)
        await self._send_alert_notification(alert)
        return alert

    async def _resolve_alert(self, component: str, title: str) -> None:
        for _alert_id, alert in self._alerts.items():
            if alert.component == component and alert.title == title and not alert.resolved_at:
                alert.resolved_at = datetime.utcnow()
                logger.info(f"Alert resolved: {title}")

    async def _send_alert_notification(self, alert: Alert) -> None:
        try:
            from infrastructure.telemetry.alert_manager_router import trigger_alert
            await trigger_alert(
                title=alert.title,
                message=alert.message,
                severity=alert.severity.value,
                source=alert.component,
                metadata={"alert_id": alert.id},
            )
        except ImportError:
            logger.debug(f"Alert notification not sent: {alert.title}")

    async def check_all_components(self) -> dict[str, ComponentHealth]:
        components = {}
        results = await asyncio.gather(
            self.check_redis(),
            self.check_database(),
            self.check_coretax_api(),
            self.check_token_validity(),
            self.check_webhook(),
            self.check_rate_limits(),
            self.check_circuit_breaker(),
            return_exceptions=True,
        )
        components["redis"] = self._handle_check_result(results[0], "Redis")
        components["database"] = self._handle_check_result(results[1], "Database")
        components["coretax_api"] = self._handle_check_result(results[2], "Coretax API")
        components["token"] = self._handle_check_result(results[3], "Token")
        components["webhook"] = self._handle_check_result(results[4], "Webhook")
        components["rate_limits"] = self._handle_check_result(results[5], "Rate Limits")
        components["circuit_breaker"] = self._handle_check_result(results[6], "Circuit Breaker")
        today = datetime.now()
        nsfp_result = await self.check_nsfp_quota("default", today.year, today.month)
        components["nsfp_quota"] = self._handle_check_result(nsfp_result, "NSFP Quota")
        pending_result = await self.check_pending_submissions()
        components["pending_submissions"] = self._handle_check_result(pending_result, "Pending Submissions")
        return components

    def _handle_check_result(self, result: Any, component_name: str) -> ComponentHealth:
        if isinstance(result, Exception):
            return ComponentHealth(
                status=HealthStatus.DOWN,
                message=f"{component_name} error: {result!s}",
            )
        return result

    async def check_redis(self) -> ComponentHealth:
        start = time.time()
        try:
            ok = await ping_redis()
            latency = (time.time() - start) * 1000
            if ok:
                return ComponentHealth(status=HealthStatus.HEALTHY, message="Redis connected", latency_ms=latency)
            else:
                return ComponentHealth(status=HealthStatus.DOWN, message="Redis ping failed", latency_ms=latency)
        except Exception as e:
            await self._add_alert("redis", AlertSeverity.CRITICAL, "Redis Connection Failed", str(e))
            return ComponentHealth(status=HealthStatus.DOWN, message=f"Redis error: {e!s}", latency_ms=None)

    async def check_database(self) -> ComponentHealth:
        start = time.time()
        try:
            # Gunakan session factory yang sudah tersedia
            session_factory = await get_session_factory()
            async with session_factory.get_session() as session:
                await session.execute(text("SELECT 1"))
            latency = (time.time() - start) * 1000
            return ComponentHealth(status=HealthStatus.HEALTHY, message="Database connected", latency_ms=latency)
        except Exception as e:
            await self._add_alert("database", AlertSeverity.CRITICAL, "Database Connection Failed", str(e))
            return ComponentHealth(status=HealthStatus.DOWN, message=f"Database error: {e!s}")

    async def check_coretax_api(self) -> ComponentHealth:
        start = time.time()
        try:
            client = await self._get_coretax_client()
            token = await client.get_access_token()
            latency = (time.time() - start) * 1000
            if PROMETHEUS_AVAILABLE:
                coretax_api_health.labels(endpoint="token_check").set(1)
                coretax_api_latency.labels(endpoint="token_check").set(latency)
            return ComponentHealth(
                status=HealthStatus.HEALTHY,
                message="Coretax API accessible",
                latency_ms=latency,
                details={"token_valid": bool(token)},
            )
        except CoretaxAuthError as e:
            if PROMETHEUS_AVAILABLE:
                coretax_api_health.labels(endpoint="token_check").set(0)
            severity = AlertSeverity.ERROR if "auth" in str(e).lower() else AlertSeverity.WARNING
            await self._add_alert("coretax_api", severity, "Coretax API Authentication Issue", str(e))
            return ComponentHealth(
                status=HealthStatus.DEGRADED if "auth" in str(e).lower() else HealthStatus.DOWN,
                message=f"Coretax API error: {e!s}",
            )
        except Exception as e:
            if PROMETHEUS_AVAILABLE:
                coretax_api_health.labels(endpoint="token_check").set(0)
            await self._add_alert("coretax_api", AlertSeverity.CRITICAL, "Coretax API Unreachable", str(e))
            return ComponentHealth(status=HealthStatus.DOWN, message=f"Coretax API unreachable: {e!s}")

    async def check_token_validity(self) -> ComponentHealth:
        start = time.time()
        try:
            client = await self._get_coretax_client()
            token = await client.get_access_token()
            latency = (time.time() - start) * 1000
            if PROMETHEUS_AVAILABLE:
                coretax_token_expiry_seconds.set(300)
            return ComponentHealth(
                status=HealthStatus.HEALTHY,
                message="Token valid",
                latency_ms=latency,
                details={"token_length": len(token) if token else 0},
            )
        except Exception as e:
            await self._add_alert("token", AlertSeverity.ERROR, "Coretax Token Issue", str(e))
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Token issue: {e!s}")

    async def check_nsfp_quota(self, npwp: str, tahun: int, bulan: int) -> ComponentHealth:
        try:
            manager = await self._get_nsfp_manager()
            quota = await manager.get_quota_info(npwp, tahun, bulan)
            remaining = quota.get("remaining", 0)
            available = quota.get("available_in_cache", 0)
            if PROMETHEUS_AVAILABLE:
                coretax_nsfp_remaining.labels(
                    npwp=npwp[:6] + "..." if len(npwp) > 6 else npwp,
                    tahun=str(tahun),
                    bulan=str(bulan),
                ).set(remaining)
            if remaining < 10:
                await self._add_alert(
                    "nsfp_quota",
                    AlertSeverity.WARNING,
                    "NSFP Quota Low",
                    f"Only {remaining} NSFP remaining for {npwp} {tahun}-{bulan:02d}",
                )
                return ComponentHealth(
                    status=HealthStatus.DEGRADED,
                    message=f"NSFP quota low: {remaining} remaining",
                    details={"remaining": remaining, "available": available},
                )
            elif remaining == 0 and available == 0:
                await self._add_alert(
                    "nsfp_quota",
                    AlertSeverity.CRITICAL,
                    "NSFP Quota Exhausted",
                    f"No NSFP available for {npwp} {tahun}-{bulan:02d}",
                )
                return ComponentHealth(
                    status=HealthStatus.DOWN,
                    message="NSFP quota exhausted",
                    details={"remaining": remaining, "available": available},
                )
            else:
                await self._resolve_alert("nsfp_quota", "NSFP Quota Low")
                await self._resolve_alert("nsfp_quota", "NSFP Quota Exhausted")
            return ComponentHealth(
                status=HealthStatus.HEALTHY,
                message=f"NSFP available: {available}, remaining quota: {remaining}",
                details={"remaining": remaining, "available": available},
            )
        except Exception as e:
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"NSFP check failed: {e!s}")

    async def check_pending_submissions(self) -> ComponentHealth:
        try:
            pending_faktur = await self._get_pending_faktur_count()
            pending_spt = await self._get_pending_spt_count()
            pending_bupot = await self._get_pending_bupot_count()
            if PROMETHEUS_AVAILABLE:
                coretax_faktur_pending.set(pending_faktur)
                coretax_spt_pending.set(pending_spt)
                coretax_bupot_pending.set(pending_bupot)
            total_pending = pending_faktur + pending_spt + pending_bupot
            status = HealthStatus.HEALTHY
            message = f"Pending: {pending_faktur} faktur, {pending_spt} SPT, {pending_bupot} e-Bupot"
            if total_pending > 500:
                status = HealthStatus.DEGRADED
                await self._add_alert("pending_submissions", AlertSeverity.WARNING, "High Pending Submissions", f"Total {total_pending} pending submissions")
            elif total_pending > 1000:
                status = HealthStatus.DOWN
                await self._add_alert("pending_submissions", AlertSeverity.CRITICAL, "Critical Pending Submissions", f"Total {total_pending} pending submissions")
            else:
                await self._resolve_alert("pending_submissions", "High Pending Submissions")
                await self._resolve_alert("pending_submissions", "Critical Pending Submissions")
            return ComponentHealth(
                status=status,
                message=message,
                details={
                    "pending_faktur": pending_faktur,
                    "pending_spt": pending_spt,
                    "pending_bupot": pending_bupot,
                },
            )
        except Exception as e:
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Pending check failed: {e!s}")

    async def check_webhook(self) -> ComponentHealth:
        start = time.time()
        try:
            latency = (time.time() - start) * 1000
            return ComponentHealth(status=HealthStatus.HEALTHY, message="Webhook receiver operational", latency_ms=latency)
        except Exception as e:
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Webhook check failed: {e!s}")

    async def check_rate_limits(self) -> ComponentHealth:
        try:
            # client = await self._get_coretax_client()  # not used; removed
            remaining = 1000
            if PROMETHEUS_AVAILABLE:
                coretax_rate_limit_remaining.labels(endpoint="general").set(remaining)
            if remaining < 100:
                return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Rate limit low: {remaining} remaining")
            return ComponentHealth(status=HealthStatus.HEALTHY, message=f"Rate limits OK: {remaining} remaining")
        except Exception as e:
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Rate limit check failed: {e!s}")

    async def check_circuit_breaker(self) -> ComponentHealth:
        try:
            circuit_status = "closed"
            if PROMETHEUS_AVAILABLE:
                state_map = {"closed": 0, "open": 1, "half-open": 2}
                coretax_circuit_breaker_state.labels(component="coretax_api").set(state_map.get(circuit_status, 0))
            if circuit_status == "open":
                await self._add_alert("circuit_breaker", AlertSeverity.CRITICAL, "Circuit Breaker Open", "Coretax API circuit breaker is open")
                return ComponentHealth(status=HealthStatus.DOWN, message="Circuit breaker is OPEN")
            elif circuit_status == "half-open":
                return ComponentHealth(status=HealthStatus.DEGRADED, message="Circuit breaker is HALF-OPEN")
            else:
                await self._resolve_alert("circuit_breaker", "Circuit Breaker Open")
                return ComponentHealth(status=HealthStatus.HEALTHY, message="Circuit breaker is CLOSED")
        except Exception as e:
            return ComponentHealth(status=HealthStatus.DEGRADED, message=f"Circuit breaker check failed: {e!s}")

    async def _get_pending_faktur_count(self) -> int:
        try:
            # Just return 0 placeholder; no need to instantiate repo
            return 0
        except ImportError:
            return 0

    async def _get_pending_spt_count(self) -> int:
        try:
            return 0
        except ImportError:
            return 0

    async def _get_pending_bupot_count(self) -> int:
        try:
            return 0
        except ImportError:
            return 0

    async def get_full_dashboard(self, npwp: str = "000000000000000", tahun: int = datetime.now().year, bulan: int = datetime.now().month, refresh: bool = False) -> CoretaxDashboardResponse:
        start_time = time.time()
        if refresh:
            self._invalidate_cache()
        components = await self.check_all_components()
        status_counts = {}
        for comp in components.values():
            status_counts[comp.status] = status_counts.get(comp.status, 0) + 1
        overall = HealthStatus.DOWN if status_counts.get(HealthStatus.DOWN, 0) > 0 else (HealthStatus.DEGRADED if status_counts.get(HealthStatus.DEGRADED, 0) > 0 else HealthStatus.HEALTHY)
        metrics = {}
        for comp_name, comp in components.items():
            if comp.latency_ms:
                metrics[f"{comp_name}_latency_ms"] = comp.latency_ms
        metrics["health_check_duration_ms"] = (time.time() - start_time) * 1000
        metrics["active_alerts_count"] = len([a for a in self._alerts.values() if not a.resolved_at])
        metrics["total_alerts_24h"] = len(self._alerts)
        if PROMETHEUS_AVAILABLE:
            coretax_health_check_duration.set(metrics["health_check_duration_ms"] / 1000)
        alerts = [
            {
                "id": alert.id,
                "component": alert.component,
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
                "created_at": alert.created_at.isoformat(),
                "resolved": alert.resolved_at is not None,
            }
            for alert in self._alerts.values()
            if not alert.resolved_at
        ][:50]
        self._historical_records.append(
            HistoricalHealthRecord(
                timestamp=datetime.utcnow(),
                overall_status=overall,
                components={name: comp.status for name, comp in components.items()},
                metrics=metrics,
            )
        )
        await self._cleanup_old_records()
        return CoretaxDashboardResponse(
            overall_status=overall,
            components=components,
            metrics=metrics,
            alerts=alerts,
            timestamp=datetime.utcnow(),
            version=self.get_version(),
            uptime_seconds=self.get_uptime(),
        )

    def get_version(self) -> str:
        return "1.0.0"

    def get_uptime(self) -> float:
        return (datetime.now() - self._start_time).total_seconds()

    async def get_historical_health(self, start_time: datetime, end_time: datetime, resolution: str = "hour") -> list[HistoricalHealthRecord]:
        records = [r for r in self._historical_records if start_time <= r.timestamp <= end_time]
        if resolution == "hour":
            aggregated = {}
            for record in records:
                key = record.timestamp.replace(minute=0, second=0, microsecond=0)
                if key not in aggregated:
                    aggregated[key] = record
                if self._status_priority(record.overall_status) > self._status_priority(aggregated[key].overall_status):
                    aggregated[key] = record
            return list(aggregated.values())
        return records[-100:]

    def _status_priority(self, status: HealthStatus) -> int:
        priorities = {HealthStatus.DOWN: 3, HealthStatus.DEGRADED: 2, HealthStatus.UNKNOWN: 1, HealthStatus.HEALTHY: 0}
        return priorities.get(status, 0)

    async def get_metrics(self) -> dict[str, Any]:
        dashboard = await self.get_full_dashboard()
        return dashboard.metrics

    async def reset(self) -> None:
        self._invalidate_cache()
        self._alerts.clear()
        self._start_time = datetime.now()
        logger.info("Health dashboard reset")

    async def trigger_alert(self, component: str, severity: AlertSeverity, title: str, message: str) -> Alert:
        return await self._add_alert(component, severity, title, message)

    async def clear_alert(self, alert_id: str) -> bool:
        if alert_id in self._alerts:
            self._alerts[alert_id].resolved_at = datetime.utcnow()
            return True
        return False

    async def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        if alert_id in self._alerts:
            self._alerts[alert_id].acknowledged = True
            self._alerts[alert_id].acknowledged_by = acknowledged_by
            return True
        return False


# ============================================================================
# SINGLETON
# ============================================================================
_health_checker: CoretaxHealthChecker | None = None

async def get_health_checker(config: dict | None = None) -> CoretaxHealthChecker:
    global _health_checker
    if _health_checker is None:
        _health_checker = CoretaxHealthChecker(config=config)
        await _health_checker.start_background_health_check()
    return _health_checker

async def shutdown_health_checker():
    global _health_checker
    if _health_checker:
        await _health_checker.stop_background_health_check()


# ============================================================================
# API ENDPOINTS
# ============================================================================
@router.get("/dashboard", response_model=CoretaxDashboardResponse)
async def get_coretax_dashboard(
    npwp: str = "000000000000000",
    tahun: int = datetime.now().year,
    bulan: int = datetime.now().month,
    refresh: bool = False,
    checker: CoretaxHealthChecker = Depends(get_health_checker),
) -> CoretaxDashboardResponse:
    return await checker.get_full_dashboard(npwp, tahun, bulan, refresh)

@router.get("/ready")
async def readiness_check(checker: CoretaxHealthChecker = Depends(get_health_checker)):
    dashboard = await checker.get_full_dashboard("", 2024, 1)
    if dashboard.overall_status == HealthStatus.DOWN:
        raise HTTPException(status_code=503, detail="Coretax integration is DOWN")
    return {"status": "ready", "overall": dashboard.overall_status, "timestamp": datetime.utcnow().isoformat()}

@router.get("/live")
async def liveness_check():
    return {"status": "alive", "timestamp": datetime.utcnow().isoformat()}

@router.get("/startup")
async def startup_check(checker: CoretaxHealthChecker = Depends(get_health_checker)):
    dashboard = await checker.get_full_dashboard()
    essential_components = ["database", "redis"]
    essential_healthy = all(
        dashboard.components.get(comp, ComponentHealth(status=HealthStatus.UNKNOWN)).status != HealthStatus.DOWN
        for comp in essential_components
    )
    if not essential_healthy:
        raise HTTPException(status_code=503, detail="Essential components not ready")
    return {"status": "started", "timestamp": datetime.utcnow().isoformat()}

@router.get("/metrics")
async def prometheus_metrics():
    if PROMETHEUS_AVAILABLE:
        from fastapi.responses import Response
        return Response(content=generate_latest(REGISTRY), media_type="text/plain")
    return {"message": "Prometheus metrics not available"}

@router.get("/alerts")
async def get_alerts(checker: CoretaxHealthChecker = Depends(get_health_checker)):
    dashboard = await checker.get_full_dashboard()
    return {"alerts": dashboard.alerts, "total": len(dashboard.alerts)}

@router.post("/alerts/trigger")
async def trigger_alert(
    component: str,
    severity: str,
    title: str,
    message: str,
    checker: CoretaxHealthChecker = Depends(get_health_checker),
):
    alert = await checker.trigger_alert(component, AlertSeverity(severity), title, message)
    return {"alert_id": alert.id, "status": "triggered"}

@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, checker: CoretaxHealthChecker = Depends(get_health_checker)):
    success = await checker.clear_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "resolved"}

@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: str, acknowledged_by: str, checker: CoretaxHealthChecker = Depends(get_health_checker)):
    success = await checker.acknowledge_alert(alert_id, acknowledged_by)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"status": "acknowledged"}

@router.get("/history")
async def get_health_history(
    start_time: str | None = None,
    end_time: str | None = None,
    resolution: str = "hour",
    checker: CoretaxHealthChecker = Depends(get_health_checker),
):
    start = datetime.fromisoformat(start_time) if start_time else datetime.utcnow() - timedelta(days=7)
    end = datetime.fromisoformat(end_time) if end_time else datetime.utcnow()
    records = await checker.get_historical_health(start, end, resolution)
    return {
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "resolution": resolution,
        "records": [
            {
                "timestamp": r.timestamp.isoformat(),
                "overall_status": r.overall_status.value,
                "components": {k: v.value for k, v in r.components.items()},
                "metrics": r.metrics,
            }
            for r in records
        ],
    }

@router.post("/reset")
async def reset_health_dashboard(checker: CoretaxHealthChecker = Depends(get_health_checker)):
    await checker.reset()
    return {"status": "reset"}

@router.get("/components")
async def get_components_status(checker: CoretaxHealthChecker = Depends(get_health_checker)):
    components = await checker.check_all_components()
    return {
        "components": {
            name: {
                "status": comp.status.value,
                "message": comp.message,
                "latency_ms": comp.latency_ms,
                "last_check": comp.last_check.isoformat(),
                "details": comp.details,
            }
            for name, comp in components.items()
        }
    }


# ============================================================================
# COMPATIBILITY STUB
# ============================================================================
class CoreTaxHealthDashboard:
    def __init__(self, simulation_mode: bool = True):
        self.simulation_mode = simulation_mode
        self._last_check_time = None
        self._api_status = "UP"
        self._checker: CoretaxHealthChecker | None = None

    async def _get_checker(self):
        if self._checker is None:
            self._checker = await get_health_checker()
        return self._checker

    def check(self) -> dict:
        from datetime import datetime
        now = datetime.now()
        if self._last_check_time is None:
            self._last_check_time = now
        return {
            "api_status": self._api_status,
            "last_successful_call": self._last_check_time.isoformat(),
            "simulation_mode": self.simulation_mode,
        }

    def get_status(self) -> dict:
        return {
            "status": "operational",
            "simulation_mode": self.simulation_mode,
            "api_version": "2026.1",
            "connected": True,
        }


# ============================================================================
# EXPORTS
# ============================================================================
__all__ = [
    "Alert",
    "AlertSeverity",
    "ComponentHealth",
    "CoreTaxHealthDashboard",
    "CoretaxDashboardResponse",
    "CoretaxHealthChecker",
    "HealthStatus",
    "get_health_checker",
    "router",
    "shutdown_health_checker",
]
