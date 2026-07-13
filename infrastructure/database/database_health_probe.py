#!/usr/bin/env python3
"""
Module: database_health_probe.py
Layer: Infrastructure (Database)
Responsibility: Menyediakan probe kesehatan untuk database PostgreSQL. Memeriksa
               konektivitas, latency, replicasi lag (jika ada), dan status transaksi.
               Digunakan untuk Kubernetes readiness/liveness probes dan monitoring.
Dependencies:
- asyncpg or SQLAlchemy, asyncio, logging, time
- infrastructure.database.session_factory_sqlalchemy (get_session_factory)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Hasil health check dicatat secara periodik. Gagal probe memicu alert.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from config.loader_yaml import load_yaml_config

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_session_factory
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_HEALTH_CONFIG = {
    "enabled": True,
    "check_interval_seconds": 30,
    "connection_timeout_seconds": 5,
    "query_timeout_seconds": 10,
    "slow_query_threshold_ms": 100,
    "replication_lag_threshold_seconds": 60,
    "alert_on_failure": True,
}

HEALTH_STATUS_HEALTHY = "healthy"
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_STATUS_UNHEALTHY = "unhealthy"

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DatabaseHealthError(Exception):
    """Base exception untuk database health probe."""

    pass


# ============================================================================
# DATABASE HEALTH PROBE
# ============================================================================


class DatabaseHealthProbe:
    """
    Probe kesehatan database.

    Fitur:
    - Konektivitas check (ping)
    - Query latency monitoring
    - Transaction status
    - Replication lag check (if replica configured)
    - Connection pool status
    - Slow query detection
    - Periodic health checks with alerting
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._enabled = self.config.get("enabled", True)
        self._check_interval = self.config.get("check_interval_seconds", 30)
        self._connection_timeout = self.config.get("connection_timeout_seconds", 5)
        self._query_timeout = self.config.get("query_timeout_seconds", 10)
        self._slow_query_threshold_ms = self.config.get("slow_query_threshold_ms", 100)
        self._replication_lag_threshold = self.config.get("replication_lag_threshold_seconds", 60)
        self._last_check: dict | None = None
        self._health_task: asyncio.Task | None = None
        self._running = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            health_config = config.get("health", {})
            result = DEFAULT_HEALTH_CONFIG.copy()
            result.update(health_config)
            return result
        except Exception:
            return DEFAULT_HEALTH_CONFIG.copy()

    async def _get_session(self):
        """Get database session."""
        factory = await get_session_factory()
        return await factory.get_session()

    async def check_connectivity(self) -> dict[str, Any]:
        """
        Check basic database connectivity (ping).

        Returns:
            Dict with status, latency_ms, error (if any)
        """
        start_time = time.time()
        try:
            session = await self._get_session()
            async with session:
                result = await session.execute(text("SELECT 1"))
                await result.fetchone()
                latency_ms = (time.time() - start_time) * 1000
                return {
                    "status": HEALTH_STATUS_HEALTHY,
                    "latency_ms": round(latency_ms, 2),
                    "message": "Database reachable",
                }
        except TimeoutError:
            return {
                "status": HEALTH_STATUS_UNHEALTHY,
                "latency_ms": None,
                "error": "Connection timeout",
            }
        except Exception as e:
            return {"status": HEALTH_STATUS_UNHEALTHY, "latency_ms": None, "error": str(e)}

    async def check_query_performance(self) -> dict[str, Any]:
        """
        Check query performance (simple SELECT).

        Returns:
            Dict with query_time_ms, status
        """
        queries = [
            ("SELECT COUNT(*) FROM pg_class", "catalog_count"),
            ("SELECT EXTRACT(EPOCH FROM NOW())", "timestamp"),
            ("SELECT version()", "version"),
        ]

        results = []
        overall_status = HEALTH_STATUS_HEALTHY

        for query, name in queries:
            start_time = time.time()
            try:
                session = await self._get_session()
                async with session:
                    result = await session.execute(text(query))
                    await result.fetchall()
                    query_time_ms = (time.time() - start_time) * 1000

                    status = HEALTH_STATUS_HEALTHY
                    if query_time_ms > self._slow_query_threshold_ms:
                        status = HEALTH_STATUS_DEGRADED
                        overall_status = HEALTH_STATUS_DEGRADED

                    results.append(
                        {"query": name, "time_ms": round(query_time_ms, 2), "status": status}
                    )
            except Exception as e:
                results.append({"query": name, "error": str(e), "status": HEALTH_STATUS_UNHEALTHY})
                overall_status = HEALTH_STATUS_UNHEALTHY

        return {"status": overall_status, "queries": results}

    async def check_replication_lag(self) -> dict[str, Any]:
        """
        Check replication lag if in replication setup.

        Returns:
            Dict with lag_seconds, is_replica, status
        """
        try:
            session = await self._get_session()
            async with session:
                # Check if this is a replica
                result = await session.execute(text("SELECT pg_is_in_recovery()"))
                is_replica = result.scalar()

                if not is_replica:
                    return {
                        "is_replica": False,
                        "status": HEALTH_STATUS_HEALTHY,
                        "message": "Primary node, no replication lag",
                    }

                # Get replication lag
                result = await session.execute(text("""
                    SELECT 
                        EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) as lag_seconds
                """))
                lag_seconds = result.scalar() or 0

                status = HEALTH_STATUS_HEALTHY
                if lag_seconds > self._replication_lag_threshold:
                    status = HEALTH_STATUS_DEGRADED
                if lag_seconds > self._replication_lag_threshold * 2:
                    status = HEALTH_STATUS_UNHEALTHY

                return {
                    "is_replica": True,
                    "lag_seconds": round(lag_seconds, 2),
                    "status": status,
                    "threshold_seconds": self._replication_lag_threshold,
                }
        except Exception as e:
            return {"is_replica": None, "status": HEALTH_STATUS_DEGRADED, "error": str(e)}

    async def check_connection_pool(self) -> dict[str, Any]:
        """
        Check connection pool status.

        Returns:
            Dict with pool stats
        """
        try:
            factory = await get_session_factory()
            engine = factory.get_engine()
            pool = engine.pool

            # Get pool statistics
            pool_status = {
                "size": pool.size(),
                "checked_in": pool.checkedin(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow(),
                "total": pool.size() + pool.overflow(),
            }

            # Determine status based on usage
            usage_ratio = pool_status["checked_out"] / max(pool_status["total"], 1)
            if usage_ratio > 0.9:
                status = HEALTH_STATUS_DEGRADED
            elif usage_ratio > 0.95:
                status = HEALTH_STATUS_UNHEALTHY
            else:
                status = HEALTH_STATUS_HEALTHY

            return {"status": status, "pool": pool_status, "usage_ratio": round(usage_ratio, 2)}
        except Exception as e:
            return {"status": HEALTH_STATUS_DEGRADED, "error": str(e)}

    async def check_transaction_isolation(self) -> dict[str, Any]:
        """
        Check transaction isolation level.
        """
        try:
            session = await self._get_session()
            async with session:
                result = await session.execute(text("SHOW transaction_isolation"))
                isolation = result.scalar()
                return {"status": HEALTH_STATUS_HEALTHY, "isolation_level": isolation}
        except Exception as e:
            return {"status": HEALTH_STATUS_DEGRADED, "error": str(e)}

    async def run_full_health_check(self) -> dict[str, Any]:
        """
        Run all health checks and return comprehensive status.
        """
        start_time = time.time()

        connectivity = await self.check_connectivity()
        if connectivity["status"] == HEALTH_STATUS_UNHEALTHY:
            # If can't connect, skip other checks
            overall_status = HEALTH_STATUS_UNHEALTHY
            result = {
                "status": overall_status,
                "timestamp": datetime.now(UTC).isoformat(),
                "connectivity": connectivity,
                "error": "Database unreachable",
            }
            self._last_check = result
            return result

        # Run other checks concurrently
        performance = await self.check_query_performance()
        replication = await self.check_replication_lag()
        pool = await self.check_connection_pool()
        isolation = await self.check_transaction_isolation()

        # Determine overall status
        statuses = [
            connectivity["status"],
            performance["status"],
            replication["status"],
            pool["status"],
        ]
        if HEALTH_STATUS_UNHEALTHY in statuses:
            overall_status = HEALTH_STATUS_UNHEALTHY
        elif HEALTH_STATUS_DEGRADED in statuses:
            overall_status = HEALTH_STATUS_DEGRADED
        else:
            overall_status = HEALTH_STATUS_HEALTHY

        duration_ms = (time.time() - start_time) * 1000

        result = {
            "status": overall_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "duration_ms": round(duration_ms, 2),
            "connectivity": connectivity,
            "performance": performance,
            "replication": replication,
            "connection_pool": pool,
            "isolation": isolation,
        }

        self._last_check = result

        # Alert if unhealthy
        if overall_status == HEALTH_STATUS_UNHEALTHY and self.config.get("alert_on_failure", True):
            await trigger_alert(
                title="Database Health Check Failed",
                message=f"Database health check failed: {result}",
                severity="critical",
                source="DatabaseHealthProbe",
            )
        elif overall_status == HEALTH_STATUS_DEGRADED and self.config.get("alert_on_failure", True):
            await trigger_alert(
                title="Database Health Check Degraded",
                message=f"Database health check degraded: {result}",
                severity="warning",
                source="DatabaseHealthProbe",
            )

        return result

    async def start_periodic_checks(self) -> None:
        """
        Start periodic health checks.
        """
        if not self._enabled:
            logger.info("Database health probe disabled")
            return

        if self._running:
            logger.warning("Health probe already running")
            return

        self._running = True

        async def _health_loop():
            while self._running:
                try:
                    await self.run_full_health_check()
                    await asyncio.sleep(self._check_interval)
                except asyncio.CancelledError:
                    logger.debug("Database health probe loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Health check error: {e}")
                    await asyncio.sleep(5)

        self._health_task = asyncio.create_task(_health_loop())
        logger.info(f"Database health probe started (interval: {self._check_interval}s)")

    async def stop_periodic_checks(self) -> None:
        """Stop periodic health checks."""
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                logger.debug("Database health probe task cancelled during stop")
                # Expected cancellation; continue
            self._health_task = None
        logger.info("Database health probe stopped")

    async def get_last_check(self) -> dict | None:
        """Get last health check result."""
        return self._last_check

    async def get_readiness_status(self) -> dict[str, Any]:
        """
        Get readiness status for Kubernetes readiness probe.
        """
        # Run a quick connectivity check
        conn = await self.check_connectivity()
        if conn["status"] != HEALTH_STATUS_HEALTHY:
            return {
                "ready": False,
                "status": conn["status"],
                "message": conn.get("error", "Database not reachable"),
            }

        # Also check if we can perform a simple query
        perf = await self.check_query_performance()
        if perf["status"] == HEALTH_STATUS_UNHEALTHY:
            return {
                "ready": False,
                "status": perf["status"],
                "message": "Query performance check failed",
            }

        return {"ready": True, "status": HEALTH_STATUS_HEALTHY, "message": "Database ready"}

    async def get_liveness_status(self) -> dict[str, Any]:
        """
        Get liveness status for Kubernetes liveness probe.
        """
        conn = await self.check_connectivity()
        return {
            "alive": conn["status"] == HEALTH_STATUS_HEALTHY,
            "status": conn["status"],
            "message": conn.get("message", conn.get("error", "Unknown")),
        }

    async def get_metrics(self) -> dict[str, Any]:
        """
        Get health metrics for monitoring.
        """
        last_check = self._last_check
        if not last_check:
            return {"message": "No health check performed yet"}

        return {
            "last_check_timestamp": last_check.get("timestamp"),
            "last_check_status": last_check.get("status"),
            "last_check_duration_ms": last_check.get("duration_ms"),
            "connectivity_latency_ms": last_check.get("connectivity", {}).get("latency_ms"),
            "slow_queries": [
                q
                for q in last_check.get("performance", {}).get("queries", [])
                if q.get("status") == HEALTH_STATUS_DEGRADED
            ],
            "replication_lag_seconds": last_check.get("replication", {}).get("lag_seconds"),
            "pool_usage_ratio": last_check.get("connection_pool", {}).get("usage_ratio"),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_health_probe: DatabaseHealthProbe | None = None


async def get_health_probe() -> DatabaseHealthProbe:
    """Get singleton instance of DatabaseHealthProbe."""
    global _health_probe
    if _health_probe is None:
        _health_probe = DatabaseHealthProbe()
    return _health_probe


# ============================================================================
# FASTAPI DEPENDENCIES (for readiness/liveness endpoints)
# ============================================================================


async def readiness_probe() -> dict[str, Any]:
    """Readiness probe endpoint for FastAPI."""
    probe = await get_health_probe()
    return await probe.get_readiness_status()


async def liveness_probe() -> dict[str, Any]:
    """Liveness probe endpoint for FastAPI."""
    probe = await get_health_probe()
    return await probe.get_liveness_status()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "HEALTH_STATUS_DEGRADED",
    "HEALTH_STATUS_HEALTHY",
    "HEALTH_STATUS_UNHEALTHY",
    "DatabaseHealthError",
    "DatabaseHealthProbe",
    "get_health_probe",
    "liveness_probe",
    "readiness_probe",
]
