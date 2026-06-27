#!/usr/bin/env python3
"""
Module: health_indicator.py
Layer: 4 - Kernel / Health Indicator
Responsibility: Indikator kesehatan kernel untuk readiness probe.
               Menyediakan informasi kesehatan komponen kernel secara real-time,
               termasuk status circuit breaker, retry policy stats, queue size,
               dan metric collector health. Digunakan oleh health probe endpoint.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_health_report(), wait_for_healthy(), get_circuit_breaker_summary(), get_dispatcher_status()
- is_healthy(), is_ready(), reset(), shutdown()
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# === 1. FALLBACK IMPORTS ===
def _get_circuit_breaker_registry():
    try:
        from kernel.circuit_breaker import get_circuit_breaker_registry
        return get_circuit_breaker_registry()
    except ImportError:
        return None


def _get_command_dispatcher():
    try:
        from kernel.command_dispatcher import get_command_dispatcher
        return get_command_dispatcher()
    except ImportError:
        return None


def _get_metric_collector():
    try:
        from kernel.metric_collector import get_metric_collector
        return get_metric_collector()
    except ImportError:
        return None


def _get_retry_policy():
    try:
        from kernel.retry_policy import get_retry_policy
        return get_retry_policy()
    except ImportError:
        return None


def _get_transactional_executor():
    try:
        from kernel.transactional_executor import get_transactional_executor
        return get_transactional_executor()
    except ImportError:
        return None


def _get_sealed_gate():
    try:
        from kernel.sealed_gate import get_sealed_gate
        return get_sealed_gate()
    except ImportError:
        return None


# === 2. CONSTANTS & ENUMS ===
class KernelHealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealthStatus(Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    name: str
    status: ComponentHealthStatus
    details: dict[str, Any] = field(default_factory=dict)
    last_check: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.name:
            errors.append("Component name is required")
        if not isinstance(self.status, ComponentHealthStatus):
            errors.append("Invalid status")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "details": self.details,
            "last_check": self.last_check.isoformat(),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentHealth:
        return cls(
            name=data["name"],
            status=ComponentHealthStatus(data["status"]),
            details=data.get("details", {}),
            last_check=datetime.fromisoformat(data["last_check"]) if data.get("last_check") else datetime.now(UTC),
            error=data.get("error"),
        )

    def clone(self) -> ComponentHealth:
        return ComponentHealth(
            name=self.name,
            status=self.status,
            details=self.details.copy(),
            last_check=self.last_check,
            error=self.error,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "timestamp": self.last_check.isoformat(),
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> ComponentHealth:
        new = self.clone()
        new.last_check = datetime.now(UTC)
        return new


@dataclass
class KernelHealthReport:
    status: KernelHealthStatus
    timestamp: datetime
    components: dict[str, ComponentHealth] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0.0"

    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.status, KernelHealthStatus):
            errors.append("Invalid status")
        for name, comp in self.components.items():
            res = comp.validate()
            if not res["is_valid"]:
                errors.extend([f"{name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "components": {name: comp.to_dict() for name, comp in self.components.items()},
            "summary": self.summary,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KernelHealthReport:
        components = {}
        for name, comp_data in data.get("components", {}).items():
            components[name] = ComponentHealth.from_dict(comp_data)
        return cls(
            status=KernelHealthStatus(data["status"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            components=components,
            summary=data.get("summary", {}),
            version=data.get("version", "1.0.0"),
        )

    def clone(self) -> KernelHealthReport:
        return KernelHealthReport(
            status=self.status,
            timestamp=self.timestamp,
            components={name: comp.clone() for name, comp in self.components.items()},
            summary=self.summary.copy(),
            version=self.version,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "component_count": len(self.components),
            "version": self.version,
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> KernelHealthReport:
        new = self.clone()
        new.timestamp = datetime.now(UTC)
        return new


# === 3. KERNEL HEALTH INDICATOR ===
class KernelHealthIndicator:
    """
    Indikator kesehatan kernel.
    """

    _instance: KernelHealthIndicator | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> KernelHealthIndicator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._circuit_breaker_registry = _get_circuit_breaker_registry()
        self._command_dispatcher = _get_command_dispatcher()
        self._metric_collector = _get_metric_collector()
        self._retry_policy = _get_retry_policy()
        self._transactional_executor = _get_transactional_executor()
        self._sealed_gate = _get_sealed_gate()
        self._component_health_cache: dict[str, ComponentHealth] = {}
        self._cache_ttl_seconds = 5
        self._last_full_check = datetime.now(UTC)
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    async def get_health_report(self, force_refresh: bool = False) -> KernelHealthReport:
        start_time = time.time()
        now = datetime.now(UTC)
        if (
            not force_refresh
            and (now - self._last_full_check).total_seconds() < self._cache_ttl_seconds
        ):
            return self._build_report_from_cache()

        components = {}
        warnings = []
        errors = []

        # 1. Circuit Breaker Health
        components["circuit_breaker"] = await self._check_circuit_breakers()
        if components["circuit_breaker"].status == ComponentHealthStatus.DEGRADED:
            warnings.append("Circuit breaker degraded - some circuits are open")
        elif components["circuit_breaker"].status == ComponentHealthStatus.DOWN:
            errors.append("Circuit breaker registry unavailable")

        # 2. Command Dispatcher Health
        components["command_dispatcher"] = await self._check_command_dispatcher()
        if components["command_dispatcher"].status == ComponentHealthStatus.DEGRADED:
            warnings.append("Command dispatcher degraded - queue high or workers not running")
        elif components["command_dispatcher"].status == ComponentHealthStatus.DOWN:
            errors.append("Command dispatcher unavailable")

        # 3. Metric Collector Health
        components["metric_collector"] = await self._check_metric_collector()
        if components["metric_collector"].status == ComponentHealthStatus.DEGRADED:
            warnings.append("Metric collector degraded")

        # 4. Retry Policy Health
        components["retry_policy"] = await self._check_retry_policy()

        # 5. Transactional Executor Health
        components["transactional_executor"] = await self._check_transactional_executor()
        if components["transactional_executor"].status == ComponentHealthStatus.DEGRADED:
            warnings.append("Transactional executor degraded - high failure rate")

        # 6. Sealed Gate Health
        components["sealed_gate"] = await self._check_sealed_gate()

        # 7. Dependency Health (overall)
        components["dependencies"] = await self._check_dependencies()

        self._component_health_cache = components
        self._last_full_check = now

        if errors:
            status = KernelHealthStatus.UNHEALTHY
        elif warnings:
            status = KernelHealthStatus.DEGRADED
        else:
            status = KernelHealthStatus.HEALTHY

        summary = {
            "total_components": len(components),
            "healthy_components": sum(1 for c in components.values() if c.status == ComponentHealthStatus.UP),
            "degraded_components": sum(1 for c in components.values() if c.status == ComponentHealthStatus.DEGRADED),
            "down_components": sum(1 for c in components.values() if c.status == ComponentHealthStatus.DOWN),
            "check_duration_ms": (time.time() - start_time) * 1000,
        }

        report = KernelHealthReport(
            status=status,
            timestamp=now,
            components=components,
            summary=summary,
        )
        self._record_audit("HEALTH_CHECK", "system", {"status": status.value})
        return report

    def _build_report_from_cache(self) -> KernelHealthReport:
        degraded = any(c.status == ComponentHealthStatus.DEGRADED for c in self._component_health_cache.values())
        down = any(c.status == ComponentHealthStatus.DOWN for c in self._component_health_cache.values())
        if down:
            status = KernelHealthStatus.UNHEALTHY
        elif degraded:
            status = KernelHealthStatus.DEGRADED
        else:
            status = KernelHealthStatus.HEALTHY
        return KernelHealthReport(
            status=status,
            timestamp=datetime.now(UTC),
            components=self._component_health_cache,
            summary={
                "cached": True,
                "cache_age_seconds": (datetime.now(UTC) - self._last_full_check).total_seconds(),
            },
        )

    async def _check_circuit_breakers(self) -> ComponentHealth:
        if not self._circuit_breaker_registry:
            return ComponentHealth(
                name="circuit_breaker",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Circuit breaker registry not available"},
            )
        try:
            stats = self._circuit_breaker_registry.get_statistics()
            open_count = stats.get("open_count", 0)
            half_open_count = stats.get("half_open_count", 0)
            total = stats.get("total_circuit_breakers", 0)
            status = ComponentHealthStatus.DEGRADED if (open_count > 0 or half_open_count > 0) else ComponentHealthStatus.UP
            return ComponentHealth(
                name="circuit_breaker",
                status=status,
                details={
                    "total_circuits": total,
                    "open_count": open_count,
                    "half_open_count": half_open_count,
                    "closed_count": stats.get("closed_count", 0),
                    "circuit_names": stats.get("circuit_breakers", [])[:10],
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="circuit_breaker",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_command_dispatcher(self) -> ComponentHealth:
        if not self._command_dispatcher:
            return ComponentHealth(
                name="command_dispatcher",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Command dispatcher not available"},
            )
        try:
            stats = self._command_dispatcher.get_statistics()
            queue_size = stats.get("queue_size", 0)
            running = stats.get("running", False)
            total = stats.get("total_dispatches", 0)
            success = stats.get("success_count", 0)
            failed = stats.get("failed_count", 0)
            if not running or queue_size > 5000:
                status = ComponentHealthStatus.DOWN
            elif queue_size > 1000 or (failed > 0 and total > 0 and (failed / total) > 0.1):
                status = ComponentHealthStatus.DEGRADED
            else:
                status = ComponentHealthStatus.UP
            return ComponentHealth(
                name="command_dispatcher",
                status=status,
                details={
                    "queue_size": queue_size,
                    "running": running,
                    "worker_count": stats.get("worker_count", 0),
                    "total_dispatches": total,
                    "success_count": success,
                    "failed_count": failed,
                    "rejected_count": stats.get("rejected_count", 0),
                    "strategy": stats.get("strategy", "unknown"),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="command_dispatcher",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_metric_collector(self) -> ComponentHealth:
        if not self._metric_collector:
            return ComponentHealth(
                name="metric_collector",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Metric collector not available"},
            )
        try:
            stats = self._metric_collector.get_stats_summary()
            counters = stats.get("counters_count", 0)
            gauges = stats.get("gauges_count", 0)
            status = ComponentHealthStatus.UP if (counters > 0 or gauges > 0) else ComponentHealthStatus.DEGRADED
            return ComponentHealth(
                name="metric_collector",
                status=status,
                details={
                    "counters": counters,
                    "gauges": gauges,
                    "histograms": stats.get("histograms_count", 0),
                    "total_samples": stats.get("total_samples", 0),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="metric_collector",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_retry_policy(self) -> ComponentHealth:
        if not self._retry_policy:
            return ComponentHealth(
                name="retry_policy",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Retry policy not available"},
            )
        try:
            stats = self._retry_policy.get_statistics()
            total = stats.get("total_attempts", 0)
            success_rate = stats.get("success_rate", 1.0)
            status = ComponentHealthStatus.DEGRADED if (success_rate < 0.5 and total > 100) else ComponentHealthStatus.UP
            return ComponentHealth(
                name="retry_policy",
                status=status,
                details={
                    "total_attempts": total,
                    "success_count": stats.get("success_count", 0),
                    "retry_count": stats.get("retry_count", 0),
                    "success_rate": success_rate,
                    "avg_duration_ms": stats.get("avg_duration_ms", 0),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="retry_policy",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_transactional_executor(self) -> ComponentHealth:
        if not self._transactional_executor:
            return ComponentHealth(
                name="transactional_executor",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Transactional executor not available"},
            )
        try:
            stats = self._transactional_executor.get_statistics()
            total = stats.get("total_transactions", 0)
            success_rate = stats.get("success_rate", 1.0)
            avg_duration = stats.get("avg_duration_ms", 0)
            status = ComponentHealthStatus.DEGRADED if ((success_rate < 0.8 and total > 100) or avg_duration > 5000) else ComponentHealthStatus.UP
            return ComponentHealth(
                name="transactional_executor",
                status=status,
                details={
                    "total_transactions": total,
                    "success_count": stats.get("success_count", 0),
                    "failed_count": stats.get("failed_count", 0),
                    "success_rate": success_rate,
                    "avg_duration_ms": avg_duration,
                    "avg_retry_count": stats.get("avg_retry_count", 0),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="transactional_executor",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_sealed_gate(self) -> ComponentHealth:
        if not self._sealed_gate:
            return ComponentHealth(
                name="sealed_gate",
                status=ComponentHealthStatus.UNKNOWN,
                details={"error": "Sealed gate not available"},
            )
        try:
            status_info = self._sealed_gate.get_status()
            circuit_state = status_info.get("circuit_breaker_state", "unknown")
            registered_handlers = status_info.get("registered_handlers", [])
            status = ComponentHealthStatus.DEGRADED if circuit_state in ("open", "half_open") else ComponentHealthStatus.UP
            return ComponentHealth(
                name="sealed_gate",
                status=status,
                details={
                    "circuit_breaker_state": circuit_state,
                    "registered_handlers": len(registered_handlers),
                    "handlers": registered_handlers[:10],
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="sealed_gate",
                status=ComponentHealthStatus.DOWN,
                details={"error": str(e)},
                error=str(e),
            )

    async def _check_dependencies(self) -> ComponentHealth:
        components_to_check = ["circuit_breaker", "command_dispatcher", "transactional_executor", "sealed_gate"]
        down_count = 0
        degraded_count = 0
        for comp_name in components_to_check:
            comp = self._component_health_cache.get(comp_name)
            if comp:
                if comp.status == ComponentHealthStatus.DOWN:
                    down_count += 1
                elif comp.status == ComponentHealthStatus.DEGRADED:
                    degraded_count += 1
        if down_count > 0:
            status = ComponentHealthStatus.DOWN
        elif degraded_count > 0:
            status = ComponentHealthStatus.DEGRADED
        else:
            status = ComponentHealthStatus.UP
        return ComponentHealth(
            name="dependencies",
            status=status,
            details={"down_count": down_count, "degraded_count": degraded_count},
        )

    def is_healthy(self) -> bool:
        if not self._component_health_cache:
            return True
        return not any(c.status == ComponentHealthStatus.DOWN for c in self._component_health_cache.values())

    def is_ready(self) -> bool:
        if not self._component_health_cache:
            return True
        return not any(c.status == ComponentHealthStatus.DOWN for c in self._component_health_cache.values())

    async def wait_for_healthy(self, timeout_seconds: float = 30.0, interval_seconds: float = 1.0) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            report = await self.get_health_report(force_refresh=True)
            if report.status == KernelHealthStatus.HEALTHY:
                return True
            await asyncio.sleep(interval_seconds)
        return False

    def get_circuit_breaker_summary(self) -> dict[str, Any]:
        if not self._circuit_breaker_registry:
            return {"error": "Circuit breaker registry not available"}
        try:
            return self._circuit_breaker_registry.get_statistics()
        except Exception as e:
            return {"error": str(e)}

    def get_dispatcher_status(self) -> dict[str, Any]:
        if not self._command_dispatcher:
            return {"error": "Command dispatcher not available"}
        try:
            return self._command_dispatcher.get_statistics()
        except Exception as e:
            return {"error": str(e)}

    def reset(self) -> None:
        self._component_health_cache = {}
        self._last_full_check = datetime.now(UTC)
        self._version += 1
        self._audit_trail = []
        self._snapshots = []

    async def shutdown(self) -> None:
        self.reset()

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._cache_ttl_seconds <= 0:
            errors.append("cache_ttl_seconds must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "cache_ttl_seconds": self._cache_ttl_seconds,
            "cached_components": len(self._component_health_cache),
            "last_full_check": self._last_full_check.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KernelHealthIndicator:
        instance = cls()
        instance._cache_ttl_seconds = data.get("cache_ttl_seconds", 5)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> KernelHealthIndicator:
        new_instance = KernelHealthIndicator()
        new_instance._cache_ttl_seconds = self._cache_ttl_seconds
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "cached_components": len(self._component_health_cache),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> KernelHealthIndicator:
        self._version += 1
        self._audit_trail.append(
            {
                "action": "TOUCH",
                "performed_by": touched_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
            }
        )
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )


# === 4. ADDITIONAL CLASSES FOR BACKWARD COMPATIBILITY ===
class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthStatusResult:
    def __init__(self, status: HealthStatus, details: dict):
        self.status = status
        self.details = details


class HealthIndicator:
    """
    Backward-compatible health indicator.
    Use check_health_async() in async contexts, or check_health_sync() in sync contexts.
    """

    def __init__(self):
        self._checks: dict[str, Callable[[], bool]] = {}
        self._async_checks: dict[str, Callable[[], Awaitable[bool]]] = {}

    def register_check(self, name: str, check: Callable[[], bool]) -> None:
        self._checks[name] = check

    def register_async_check(self, name: str, check: Callable[[], Awaitable[bool]]) -> None:
        self._async_checks[name] = check

    async def check_health_async(self) -> HealthStatusResult:
        """Asynchronous health check."""
        results = {}
        all_healthy = True

        # Run sync checks (in thread pool to avoid blocking)
        try:
            loop = asyncio.get_running_loop()
            for name, check in self._checks.items():
                try:
                    res = await loop.run_in_executor(None, check)
                    results[name] = res
                    if not res:
                        all_healthy = False
                except Exception:
                    results[name] = False
                    all_healthy = False
        except RuntimeError:
            # No running loop, run sync directly
            for name, check in self._checks.items():
                try:
                    res = check()
                    results[name] = res
                    if not res:
                        all_healthy = False
                except Exception:
                    results[name] = False
                    all_healthy = False

        # Run async checks concurrently
        async def _run_async_check(name: str, check: Callable[[], Awaitable[bool]]):
            try:
                return name, await check()
            except Exception:
                return name, False

        if self._async_checks:
            tasks = [_run_async_check(name, check) for name, check in self._async_checks.items()]
            for name, res in await asyncio.gather(*tasks):
                results[name] = res
                if not res:
                    all_healthy = False

        status = HealthStatus.HEALTHY if all_healthy else HealthStatus.DEGRADED
        return HealthStatusResult(status, results)

    def check_health_sync(self) -> HealthStatusResult:
        """
        Synchronous health check.
        Only runs sync checks (no async).
        """
        results = {}
        all_healthy = True
        for name, check in self._checks.items():
            try:
                res = check()
                results[name] = res
                if not res:
                    all_healthy = False
            except Exception:
                results[name] = False
                all_healthy = False
        status = HealthStatus.HEALTHY if all_healthy else HealthStatus.DEGRADED
        return HealthStatusResult(status, results)

    # Legacy sync method (kept for compatibility)
    def check_health(self) -> HealthStatusResult:
        """Legacy synchronous method. Prefer check_health_sync() or check_health_async()."""
        return self.check_health_sync()


class HealthCheckRegistry:
    """
    Backward-compatible health check registry.
    Use run_all_async() in async contexts, or run_all_sync() in sync contexts.
    """

    def __init__(self, timeout: float = 5.0):
        self._checks: dict[str, Callable[[], bool]] = {}
        self._async_checks: dict[str, Callable[[], Awaitable[bool]]] = {}
        self.timeout = timeout

    def register(self, name: str, check: Callable[[], bool]) -> None:
        self._checks[name] = check

    def register_async(self, name: str, check: Callable[[], Awaitable[bool]]) -> None:
        self._async_checks[name] = check

    async def run_all_async(self) -> dict:
        """Asynchronously run all checks."""
        results = {}

        # Run sync checks in thread pool if possible
        try:
            loop = asyncio.get_running_loop()
            for name, check in self._checks.items():
                try:
                    results[name] = await loop.run_in_executor(None, check)
                except Exception:
                    results[name] = False
        except RuntimeError:
            for name, check in self._checks.items():
                try:
                    results[name] = check()
                except Exception:
                    results[name] = False

        # Run async checks with timeout
        async def _run_async_check(name: str, check: Callable[[], Awaitable[bool]]):
            try:
                return name, await asyncio.wait_for(check(), timeout=self.timeout)
            except TimeoutError:
                return name, False
            except Exception:
                return name, False

        if self._async_checks:
            tasks = [_run_async_check(name, check) for name, check in self._async_checks.items()]
            for name, res in await asyncio.gather(*tasks):
                results[name] = res

        return results

    def run_all_sync(self) -> dict:
        """
        Synchronous run of all checks.
        Only runs sync checks (no async).
        """
        results = {}
        for name, check in self._checks.items():
            try:
                results[name] = check()
            except Exception:
                results[name] = False
        return results

    # Legacy sync method
    def run_all(self) -> dict:
        """Legacy synchronous method. Prefer run_all_sync() or run_all_async()."""
        return self.run_all_sync()


# === 5. SINGLETON ACCESSOR ===
_kernel_health_indicator_instance: KernelHealthIndicator | None = None
_health_lock = asyncio.Lock()


async def get_kernel_health_indicator() -> KernelHealthIndicator:
    global _kernel_health_indicator_instance
    if _kernel_health_indicator_instance is None:
        async with _health_lock:
            if _kernel_health_indicator_instance is None:
                _kernel_health_indicator_instance = KernelHealthIndicator()
    return _kernel_health_indicator_instance


def get_kernel_health_indicator_sync() -> KernelHealthIndicator:
    global _kernel_health_indicator_instance
    if _kernel_health_indicator_instance is None:
        _kernel_health_indicator_instance = KernelHealthIndicator()
    return _kernel_health_indicator_instance


__all__ = [
    "ComponentHealth",
    "ComponentHealthStatus",
    "HealthCheckRegistry",
    "HealthIndicator",
    "HealthStatus",
    "HealthStatusResult",
    "KernelHealthIndicator",
    "KernelHealthReport",
    "KernelHealthStatus",
    "get_kernel_health_indicator",
    "get_kernel_health_indicator_sync",
]
