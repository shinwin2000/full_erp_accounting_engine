#!/usr/bin/env python3
from __future__ import annotations

"""
Package: bootstrap
Layer: 3 - Bootstrap & Config

Startup orchestration, phased startup, rollback, health probe, dan exceptions.
Menyediakan mekanisme untuk memulai sistem secara bertahap dengan graceful degradation,
rollback jika terjadi kegagalan, serta probe kesehatan untuk liveness, readiness, dan startup.

Fitur lengkap sesuai standar ERP:
- Entity dasar untuk semua komponen: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Startup orchestrator dengan dependency resolution dan rollback.
- Phased startup dengan level (CORE, BASIC, FULL, ALL).
- Health probe untuk liveness, readiness, startup.
- Rollback handler dengan berbagai scope.
"""

from bootstrap.bootstrap_exceptions import (
    APIPortInUseError,
    APIStartError,
    AxiomLoadError,
    BootstrapError,
    BootstrapErrorCode,
    BootstrapExceptionFactory,
    BootstrapSeverity,
    CircularDependencyError,
    ComponentDependencyMissingError,
    ComponentInitError,
    ComponentTimeoutError,
    ConfigError,
    ConfigNotFoundError,
    ConfigValidationError,
    ConstitutionIntegrityError,
    ConstitutionLoadError,
    DatabaseConnectionError,
    DatabaseMigrationError,
    HealthCheckFailedError,
    KernelInitError,
    RollbackFailedError,
    StartupTimeoutError,
)
from bootstrap.health_probe import (
    ComponentHealth,
    HealthProbe,
    HealthReport,
    HealthStatus,
    ProbeType,
    create_liveness_endpoint,
    create_readiness_endpoint,
    create_startup_endpoint,
    get_health_probe,
)
from bootstrap.orchestrator import (
    BootstrapOrchestrator,
    StartupContext,
    StartupOrchestrator,
    StartupPhase,
    StartupStatus,
    StartupStep,
    get_startup_orchestrator,
    register_signal_handlers,
    run_startup,
    shutdown,
)
from bootstrap.phased_startup import (
    PhasedStartup,
    PhasedStartupContext,
    PhasedStartupLevel,
    PhasedStartupManager,
    PhaseError,
    PhaseResult,
    StartupStage,
    get_phased_startup_manager,
    startup_all,
    startup_basic_only,
    startup_core_only,
    startup_full,
)
from bootstrap.rollback_handler import (
    RollbackHandler,
    RollbackReason,
    RollbackRecord,
    RollbackScope,
    RollbackStatus,
    RollbackStep,
    get_rollback_handler,
    rollback_on_failure,
)

__all__ = [
    # Exceptions
    "APIPortInUseError",
    "APIStartError",
    "AxiomLoadError",
    "BootstrapError",
    "BootstrapErrorCode",
    "BootstrapExceptionFactory",
    "BootstrapSeverity",
    "CircularDependencyError",
    "ComponentDependencyMissingError",
    "ComponentInitError",
    "ComponentTimeoutError",
    "ConfigError",
    "ConfigNotFoundError",
    "ConfigValidationError",
    "ConstitutionIntegrityError",
    "ConstitutionLoadError",
    "DatabaseConnectionError",
    "DatabaseMigrationError",
    "HealthCheckFailedError",
    "KernelInitError",
    "RollbackFailedError",
    "StartupTimeoutError",
    # Health Probe
    "ComponentHealth",
    "HealthProbe",
    "HealthReport",
    "HealthStatus",
    "ProbeType",
    "create_liveness_endpoint",
    "create_readiness_endpoint",
    "create_startup_endpoint",
    "get_health_probe",
    # Orchestrator
    "BootstrapOrchestrator",
    "StartupContext",
    "StartupOrchestrator",
    "StartupPhase",
    "StartupStatus",
    "StartupStep",
    "get_startup_orchestrator",
    "register_signal_handlers",
    "run_startup",
    "shutdown",
    # Phased Startup
    "PhaseError",
    "PhaseResult",
    "PhasedStartup",
    "PhasedStartupContext",
    "PhasedStartupLevel",
    "PhasedStartupManager",
    "StartupStage",
    "get_phased_startup_manager",
    "startup_all",
    "startup_basic_only",
    "startup_core_only",
    "startup_full",
    # Rollback Handler
    "RollbackHandler",
    "RollbackReason",
    "RollbackRecord",
    "RollbackScope",
    "RollbackStatus",
    "RollbackStep",
    "get_rollback_handler",
    "rollback_on_failure",
]
