#!/usr/bin/env python3
"""
Module: health_probe.py
Layer: 3 - Bootstrap & Config
Responsibility: Probe kesehatan awal sebelum sistem menerima beban.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from bootstrap.orchestrator import get_startup_orchestrator
from bootstrap.phased_startup import get_phased_startup_manager

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    NOT_READY = "not_ready"


class ProbeType(Enum):
    LIVENESS = "liveness"
    READINESS = "readiness"
    STARTUP = "startup"


@dataclass(kw_only=True)
class ComponentHealth:
    # --- Non-default fields (wajib) ---
    name: str
    status: HealthStatus
    message: str
    last_check: datetime
    response_time_ms: float
    # --- Default fields ---
    details: dict[str, Any] = field(default_factory=dict)
    _version: int = 1
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._take_snapshot()
        self._validate()

    def _validate(self) -> None:
        if not self.name:
            raise ValueError("name is required")
        if not isinstance(self.status, HealthStatus):
            raise ValueError("invalid status")
        if not self.message:
            raise ValueError("message is required")
        if self.response_time_ms < 0:
            raise ValueError("response_time_ms cannot be negative")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._version,
                "name": self.name,
                "status": self.status.value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "component": self.name,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "last_check": self.last_check.isoformat(),
            "response_time_ms": self.response_time_ms,
            "details": self.details,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentHealth:
        instance = cls(
            name=data["name"],
            status=HealthStatus(data["status"]),
            message=data["message"],
            last_check=datetime.fromisoformat(data["last_check"]),
            response_time_ms=data["response_time_ms"],
            details=data.get("details", {}),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> ComponentHealth:
        new = ComponentHealth(
            name=self.name,
            status=self.status,
            message=self.message,
            last_check=datetime.now(UTC),
            response_time_ms=self.response_time_ms,
            details=self.details.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self.name})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "name": self.name,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ComponentHealth:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass(kw_only=True)
class HealthReport:
    # --- Non-default fields ---
    timestamp: datetime
    overall_status: HealthStatus
    probe_type: ProbeType
    components: list[ComponentHealth]
    uptime_seconds: float
    summary: dict[str, int]
    # --- Default fields ---
    display_version: str = "1.0.0"  # renamed from "version" to avoid conflict with method
    _report_version: int = 1
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._take_snapshot()
        self._validate()

    def _validate(self) -> None:
        if not isinstance(self.overall_status, HealthStatus):
            raise ValueError("invalid overall_status")
        if not isinstance(self.probe_type, ProbeType):
            raise ValueError("invalid probe_type")
        if self.uptime_seconds < 0:
            raise ValueError("uptime_seconds cannot be negative")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._report_version,
                "overall_status": self.overall_status.value,
                "probe_type": self.probe_type.value,
                "component_count": len(self.components),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._report_version,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        for c in self.components:
            res = c.validate()
            if not res["is_valid"]:
                errors.extend([f"Component {c.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status.value,
            "probe_type": self.probe_type.value,
            "components": [c.to_dict() for c in self.components],
            "uptime_seconds": self.uptime_seconds,
            "summary": self.summary,
            "display_version": self.display_version,
            "report_version": self._report_version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthReport:
        components = [ComponentHealth.from_dict(c) for c in data.get("components", [])]
        instance = cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            overall_status=HealthStatus(data["overall_status"]),
            probe_type=ProbeType(data["probe_type"]),
            components=components,
            uptime_seconds=data["uptime_seconds"],
            summary=data.get("summary", {}),
            display_version=data.get("display_version", "1.0.0"),
        )
        instance._report_version = data.get("report_version", 1)
        return instance

    def clone(self) -> HealthReport:
        new = HealthReport(
            timestamp=datetime.now(UTC),
            overall_status=self.overall_status,
            probe_type=self.probe_type,
            components=[c.clone() for c in self.components],
            uptime_seconds=self.uptime_seconds,
            summary=self.summary.copy(),
            display_version=self.display_version,
        )
        new._report_version = self._report_version + 1
        new._record_audit("CLONE", "system", {"source": self.probe_type.value})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._report_version,
            "overall_status": self.overall_status.value,
            "probe_type": self.probe_type.value,
            "component_count": len(self.components),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._report_version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> HealthReport:
        self._report_version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class HealthProbe:
    _instance: HealthProbe | None = None
    _start_time: datetime
    _last_readiness_check: dict[str, ComponentHealth]

    def __new__(cls) -> HealthProbe:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._start_time = datetime.now(UTC)
        self._last_readiness_check = {}
        self._orchestrator = get_startup_orchestrator()
        self._phased_manager = get_phased_startup_manager()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self._version,
                "start_time": self._start_time.isoformat(),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

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

    async def check_liveness(self) -> HealthReport:
        components = []
        # Process
        components.append(
            ComponentHealth(
                name="process",
                status=HealthStatus.HEALTHY,
                message="Process is running",
                last_check=datetime.now(UTC),
                response_time_ms=0,
            )
        )
        # Event loop
        try:
            start = time.time()
            await asyncio.sleep(0)
            response_time = (time.time() - start) * 1000
            components.append(
                ComponentHealth(
                    name="event_loop",
                    status=HealthStatus.HEALTHY,
                    message="Event loop responsive",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
            )
        except Exception as e:
            components.append(
                ComponentHealth(
                    name="event_loop",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Event loop error: {e}",
                    last_check=datetime.now(UTC),
                    response_time_ms=0,
                )
            )
        # Constitution (lazy import)
        try:
            # Lazy import constitution.supreme_law
            supreme_law_mod = importlib.import_module("constitution.supreme_law")
            get_supreme_law = supreme_law_mod.get_supreme_law
            supreme_law = get_supreme_law()
            integrity = supreme_law.verify_integrity()
            if integrity.get("is_valid"):
                components.append(
                    ComponentHealth(
                        name="constitution",
                        status=HealthStatus.HEALTHY,
                        message="Constitution integrity verified",
                        last_check=datetime.now(UTC),
                        response_time_ms=0,
                    )
                )
            else:
                components.append(
                    ComponentHealth(
                        name="constitution",
                        status=HealthStatus.UNHEALTHY,
                        message=f"Constitution integrity failed: {integrity}",
                        last_check=datetime.now(UTC),
                        response_time_ms=0,
                    )
                )
        except Exception as e:
            components.append(
                ComponentHealth(
                    name="constitution",
                    status=HealthStatus.UNHEALTHY,
                    message=str(e),
                    last_check=datetime.now(UTC),
                    response_time_ms=0,
                )
            )
        overall = (
            HealthStatus.HEALTHY
            if all(c.status == HealthStatus.HEALTHY for c in components)
            else HealthStatus.UNHEALTHY
        )
        report = self._build_report(overall, ProbeType.LIVENESS, components)
        self._record_audit("CHECK_LIVENESS", "system", {"overall_status": overall.value})
        return report

    async def check_readiness(self) -> HealthReport:
        components = []
        capabilities = self._phased_manager.get_current_capabilities()
        # Database
        db_health = await self._check_database()
        components.append(db_health)
        # Kernel
        kernel_health = await self._check_kernel()
        components.append(kernel_health)
        # Services
        if capabilities.get("can_use_api", False):
            services_health = await self._check_services()
            components.append(services_health)
        # API
        if capabilities.get("can_use_api", False):
            api_health = await self._check_api()
            components.append(api_health)
        # Migrations
        migrations_health = await self._check_migrations()
        components.append(migrations_health)

        critical_components = ["database", "kernel", "migrations"]
        critical_unhealthy = any(
            c.name in critical_components and c.status == HealthStatus.UNHEALTHY for c in components
        )
        if critical_unhealthy:
            overall = HealthStatus.UNHEALTHY
        elif any(c.status == HealthStatus.DEGRADED for c in components):
            overall = HealthStatus.DEGRADED
        elif all(c.status == HealthStatus.HEALTHY for c in components):
            overall = HealthStatus.HEALTHY
        else:
            overall = HealthStatus.NOT_READY

        self._last_readiness_check = {c.name: c for c in components}
        report = self._build_report(overall, ProbeType.READINESS, components)
        self._record_audit("CHECK_READINESS", "system", {"overall_status": overall.value})
        return report

    async def check_startup(self) -> HealthReport:
        components = []
        orch_status = self._orchestrator.get_status()
        phased_status = self._phased_manager.get_status()
        startup_complete = orch_status["status"] == "SUCCESS"
        current_level = phased_status["current_level"]
        target_reached = current_level in ["LEVEL_2_FULL", "LEVEL_3_ALL", "COMPLETE"]
        if startup_complete and target_reached:
            overall = HealthStatus.HEALTHY
            message = "Startup completed successfully"
        elif orch_status["status"] == "IN_PROGRESS":
            overall = HealthStatus.NOT_READY
            message = "Startup still in progress"
        elif orch_status["status"] == "PARTIAL":
            overall = HealthStatus.DEGRADED
            message = "Startup completed in degraded mode"
        else:
            overall = HealthStatus.UNHEALTHY
            message = f"Startup failed: {orch_status['status']}"
        components.append(
            ComponentHealth(
                name="startup",
                status=overall,
                message=message,
                last_check=datetime.now(UTC),
                response_time_ms=0,
                details={
                    "orchestrator_status": orch_status["status"],
                    "current_level": current_level,
                    "errors": orch_status.get("errors", [])[:5],
                },
            )
        )
        report = self._build_report(overall, ProbeType.STARTUP, components)
        self._record_audit("CHECK_STARTUP", "system", {"overall_status": overall.value})
        return report

    async def _check_database(self) -> ComponentHealth:
        start = time.time()
        try:
            context = self._orchestrator.get_context()
            pool = context.components.get("db_pool")
            if not pool:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    message="Database pool not available",
                    last_check=datetime.now(UTC),
                    response_time_ms=0,
                )
            result = await pool.fetchval("SELECT 1 as health_check")
            response_time = (time.time() - start) * 1000
            if result == 1:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    message="Database responsive",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
            else:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    message=f"Unexpected query result: {result}",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
        except Exception as e:
            response_time = (time.time() - start) * 1000
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )

    async def _check_kernel(self) -> ComponentHealth:
        start = time.time()
        try:
            # Lazy import kernel.sealed_gate
            gate_mod = importlib.import_module("kernel.sealed_gate")
            get_sealed_gate = gate_mod.get_sealed_gate
            gate = get_sealed_gate()
            response_time = (time.time() - start) * 1000
            is_healthy = gate is not None
            return ComponentHealth(
                name="kernel",
                status=HealthStatus.HEALTHY if is_healthy else HealthStatus.UNHEALTHY,
                message="Kernel available" if is_healthy else "Kernel not available",
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )
        except Exception as e:
            response_time = (time.time() - start) * 1000
            return ComponentHealth(
                name="kernel",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )

    async def _check_services(self) -> ComponentHealth:
        start = time.time()
        try:
            context = self._orchestrator.get_context()
            services = context.components.get("services", {})
            response_time = (time.time() - start) * 1000
            service_count = len(services)
            if service_count > 0:
                return ComponentHealth(
                    name="services",
                    status=HealthStatus.HEALTHY,
                    message=f"{service_count} services available",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                    details={"service_count": service_count},
                )
            else:
                return ComponentHealth(
                    name="services",
                    status=HealthStatus.DEGRADED,
                    message="No services initialized",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
        except Exception as e:
            response_time = (time.time() - start) * 1000
            return ComponentHealth(
                name="services",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )

    async def _check_api(self) -> ComponentHealth:
        start = time.time()
        try:
            context = self._orchestrator.get_context()
            app = context.components.get("api_app")
            response_time = (time.time() - start) * 1000
            if app:
                return ComponentHealth(
                    name="api",
                    status=HealthStatus.HEALTHY,
                    message="API application available",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
            else:
                return ComponentHealth(
                    name="api",
                    status=HealthStatus.NOT_READY,
                    message="API not started",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
        except Exception as e:
            response_time = (time.time() - start) * 1000
            return ComponentHealth(
                name="api",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )

    async def _check_migrations(self) -> ComponentHealth:
        start = time.time()
        try:
            # Lazy import migration manager
            mig_mod = importlib.import_module("infrastructure.database.migration_manager_alembic")
            get_migration_manager = mig_mod.get_migration_manager
            manager = get_migration_manager()
            current_rev = manager.get_current_revision()
            head_rev = manager.get_head_revision()
            response_time = (time.time() - start) * 1000
            if current_rev == head_rev:
                return ComponentHealth(
                    name="migrations",
                    status=HealthStatus.HEALTHY,
                    message=f"Migrations up to date: {current_rev[:8]}",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
            else:
                return ComponentHealth(
                    name="migrations",
                    status=HealthStatus.DEGRADED,
                    message=f"Pending migrations: current={current_rev[:8]}, head={head_rev[:8]}",
                    last_check=datetime.now(UTC),
                    response_time_ms=response_time,
                )
        except Exception as e:
            response_time = (time.time() - start) * 1000
            return ComponentHealth(
                name="migrations",
                status=HealthStatus.DEGRADED,
                message=f"Cannot check migrations: {e}",
                last_check=datetime.now(UTC),
                response_time_ms=response_time,
            )

    async def check_component(self, component_name: str) -> ComponentHealth:
        check_map = {
            "database": self._check_database,
            "kernel": self._check_kernel,
            "services": self._check_services,
            "api": self._check_api,
            "migrations": self._check_migrations,
        }
        check_func = check_map.get(component_name)
        if check_func:
            return await check_func()
        else:
            return ComponentHealth(
                name=component_name,
                status=HealthStatus.UNKNOWN,
                message=f"Unknown component: {component_name}",
                last_check=datetime.now(UTC),
                response_time_ms=0,
            )

    def _build_report(
        self, overall: HealthStatus, probe_type: ProbeType, components: list[ComponentHealth]
    ) -> HealthReport:
        summary = {}
        for c in components:
            summary[c.status.value] = summary.get(c.status.value, 0) + 1
        uptime = (datetime.now(UTC) - self._start_time).total_seconds()
        return HealthReport(
            timestamp=datetime.now(UTC),
            overall_status=overall,
            probe_type=probe_type,
            components=components,
            summary=summary,
            display_version="1.0.0",
            uptime_seconds=uptime,
        )

    def get_uptime(self) -> float:
        return (datetime.now(UTC) - self._start_time).total_seconds()

    async def is_ready(self) -> bool:
        """Async version of readiness check."""
        report = await self.check_readiness()
        return report.overall_status == HealthStatus.HEALTHY

    def is_ready_sync(self) -> bool:
        """
        Sync version of readiness check.
        Uses asyncio.run() only when no event loop is running.
        """
        try:
            asyncio.get_running_loop()
            # If loop is running, return cached result or False
            if self._last_readiness_check:
                return all(
                    c.status == HealthStatus.HEALTHY
                    for c in self._last_readiness_check.values()
                    if c.name in ["database", "kernel"]
                )
            return False
        except RuntimeError:
            # No loop running, use asyncio.run
            return asyncio.run(self.is_ready())

    def reset(self) -> None:
        self._start_time = datetime.now(UTC)
        self._last_readiness_check = {}
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._take_snapshot()
        self._record_audit("RESET", "system", {})

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self._start_time.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HealthProbe:
        instance = cls()
        instance._start_time = datetime.fromisoformat(
            data.get("start_time", datetime.now(UTC).isoformat())
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> HealthProbe:
        new = HealthProbe()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "start_time": self._start_time.isoformat(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> HealthProbe:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


_health_probe_instance: HealthProbe | None = None


def get_health_probe() -> HealthProbe:
    global _health_probe_instance
    if _health_probe_instance is None:
        _health_probe_instance = HealthProbe()
    return _health_probe_instance


def create_liveness_endpoint():
    async def liveness():
        probe = get_health_probe()
        report = await probe.check_liveness()
        return {"status": report.overall_status.value, "timestamp": report.timestamp.isoformat()}

    return liveness


def create_readiness_endpoint():
    async def readiness():
        probe = get_health_probe()
        report = await probe.check_readiness()
        return {
            "status": report.overall_status.value,
            "timestamp": report.timestamp.isoformat(),
            "components": [
                {"name": c.name, "status": c.status.value, "message": c.message}
                for c in report.components
            ],
        }

    return readiness


def create_startup_endpoint():
    async def startup():
        probe = get_health_probe()
        report = await probe.check_startup()
        return {"status": report.overall_status.value, "details": report.components[0].details}

    return startup


__all__ = [
    "ComponentHealth",
    "HealthProbe",
    "HealthReport",
    "HealthStatus",
    "ProbeType",
    "create_liveness_endpoint",
    "create_readiness_endpoint",
    "create_startup_endpoint",
    "get_health_probe",
]
