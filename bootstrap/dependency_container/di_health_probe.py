#!/usr/bin/env python3
"""
Module: di_health_probe.py
Layer: Bootstrap (Dependency Container)
Responsibility: Health probe untuk dependency injection container.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bootstrap.dependency_container.dependency_graph_validator import get_dependency_validator
from bootstrap.dependency_container.ioc_container import IoCContainer, get_container
from infrastructure.telemetry.alert_manager_router import trigger_alert

logger = logging.getLogger(__name__)

HEALTH_STATUS_HEALTHY = "healthy"
HEALTH_STATUS_DEGRADED = "degraded"
HEALTH_STATUS_UNHEALTHY = "unhealthy"


class DIHealthProbe:
    """
    Health probe untuk dependency injection container.

    Method Standards:
    - check_dependency_resolution() - Cek resolusi dependensi
    - get_health_status() - Status kesehatan
    - is_healthy() - Apakah sehat
    - get_readiness_status() - Status readiness
    - get_liveness_status() - Status liveness
    - print_report() - Cetak laporan
    - reset() - Reset probe
    """

    def __init__(self, container: IoCContainer | None = None):
        self._container = container or get_container()
        self._validator = get_dependency_validator()
        self._last_check: dict[str, Any] | None = None
        self._logger = logging.getLogger(f"{__name__}.DIHealthProbe")

    async def check_dependency_resolution(self, timeout_seconds: float = 5.0) -> dict[str, Any]:
        """Check if all dependencies can be resolved."""
        results = {"total_checked": 0, "successful": 0, "failed": 0, "failures": []}
        registered_types = self._container.get_registered_types()

        for interface in registered_types:
            results["total_checked"] += 1
            try:
                await asyncio.wait_for(
                    self._container.resolve_async(interface), timeout=timeout_seconds
                )
                results["successful"] += 1
            except TimeoutError:
                results["failed"] += 1
                results["failures"].append(
                    {"interface": interface.__name__, "error": "Resolution timeout"}
                )
            except Exception as e:
                results["failed"] += 1
                results["failures"].append({"interface": interface.__name__, "error": str(e)})

        return results

    async def get_health_status(self) -> dict[str, Any]:
        """Get overall health status of DI container."""
        graph_report = self._validator.get_health_report()
        resolution = await self.check_dependency_resolution()

        if graph_report["healthy"] and resolution["failed"] == 0:
            status = HEALTH_STATUS_HEALTHY
        elif graph_report["circular_dependencies"] or resolution["failed"] > 0:
            status = HEALTH_STATUS_UNHEALTHY
        else:
            status = HEALTH_STATUS_DEGRADED

        self._last_check = {
            "timestamp": asyncio.get_event_loop().time(),
            "status": status,
            "graph": {
                "healthy": graph_report["healthy"],
                "total_nodes": graph_report["total_nodes"],
                "circular_dependencies": len(graph_report["circular_dependencies"]),
                "missing_dependencies": len(graph_report["missing_dependencies"]),
            },
            "resolution": {
                "total": resolution["total_checked"],
                "successful": resolution["successful"],
                "failed": resolution["failed"],
                "failures": resolution["failures"][:10],
            },
        }

        if status == HEALTH_STATUS_UNHEALTHY:
            await trigger_alert(
                title="DI Container Unhealthy",
                message=f"DI container health check failed: {resolution['failed']} resolution failures, "
                f"{len(graph_report['circular_dependencies'])} circular dependencies",
                severity="critical",
                source="DIHealthProbe",
            )

        return self._last_check

    async def is_healthy(self) -> bool:
        """Return True if container is healthy."""
        status = await self.get_health_status()
        return status["status"] == HEALTH_STATUS_HEALTHY

    async def get_readiness_status(self) -> dict[str, Any]:
        """Get readiness status (for k8s readiness probe)."""
        status = await self.get_health_status()
        return {
            "ready": status["status"] == HEALTH_STATUS_HEALTHY,
            "status": status["status"],
            "details": {
                "resolutions_successful": status["resolution"]["successful"],
                "resolutions_failed": status["resolution"]["failed"],
                "graph_healthy": status["graph"]["healthy"],
            },
        }

    async def get_liveness_status(self) -> dict[str, Any]:
        """Get liveness status (for k8s liveness probe)."""
        try:
            registered_count = len(self._container.get_registered_types())
            return {"alive": True, "registered_services": registered_count, "status": "alive"}
        except Exception as e:
            return {"alive": False, "error": str(e), "status": "dead"}

    async def print_report(self) -> None:
        """Print health report to console."""
        status = await self.get_health_status()
        print("\n" + "=" * 60)
        print("DEPENDENCY INJECTION HEALTH REPORT")
        print("=" * 60)
        print(f"Status: {status['status'].upper()}")
        print("\nGraph Health:")
        print(f"  Total Nodes: {status['graph']['total_nodes']}")
        print(f"  Graph Healthy: {status['graph']['healthy']}")
        print(f"  Circular Dependencies: {status['graph']['circular_dependencies']}")
        print(f"  Missing Dependencies: {status['graph']['missing_dependencies']}")
        print("\nResolution Health:")
        print(f"  Total: {status['resolution']['total']}")
        print(f"  Successful: {status['resolution']['successful']}")
        print(f"  Failed: {status['resolution']['failed']}")
        if status["resolution"]["failures"]:
            print("\n  Failures (first 5):")
            for failure in status["resolution"]["failures"][:5]:
                print(f"    - {failure['interface']}: {failure['error']}")
        print("=" * 60 + "\n")

    def reset(self) -> None:
        """Reset health probe state."""
        self._last_check = None
        self._logger.info("DI health probe reset")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_di_health_probe: DIHealthProbe | None = None


def get_di_health_probe() -> DIHealthProbe:
    """Get singleton instance of DIHealthProbe."""
    global _di_health_probe
    if _di_health_probe is None:
        _di_health_probe = DIHealthProbe()
    return _di_health_probe


async def readiness_probe() -> dict[str, Any]:
    """Readiness probe endpoint for FastAPI."""
    probe = get_di_health_probe()
    return await probe.get_readiness_status()


async def liveness_probe() -> dict[str, Any]:
    """Liveness probe endpoint for FastAPI."""
    probe = get_di_health_probe()
    return await probe.get_liveness_status()


__all__ = [
    "HEALTH_STATUS_DEGRADED",
    "HEALTH_STATUS_HEALTHY",
    "HEALTH_STATUS_UNHEALTHY",
    "DIHealthProbe",
    "get_di_health_probe",
    "liveness_probe",
    "readiness_probe",
]