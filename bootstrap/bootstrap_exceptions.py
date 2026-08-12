#!/usr/bin/env python3
"""
Module: bootstrap_exceptions.py
Layer: 3 - Bootstrap & Config
Responsibility: Exception khusus saat bootstrap gagal.
               Mendefinisikan hierarchy exception untuk semua error yang
               terjadi selama proses startup dan inisialisasi sistem.

Metode yang ditambahkan:
- Untuk BootstrapError: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Semua turunan exception mewarisi method tersebut.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4

# === 1. CONSTANTS & ENUMS ===


class BootstrapErrorCode(Enum):
    CONFIG_NOT_FOUND = auto()
    CONFIG_PARSE_ERROR = auto()
    CONFIG_VALIDATION_FAILED = auto()
    CONFIG_ENCRYPTION_FAILED = auto()
    DATABASE_CONNECTION_FAILED = auto()
    DATABASE_MIGRATION_FAILED = auto()
    DATABASE_POOL_ERROR = auto()
    DATABASE_SSL_ERROR = auto()
    COMPONENT_INIT_FAILED = auto()
    COMPONENT_DEPENDENCY_MISSING = auto()
    COMPONENT_CIRCULAR_DEPENDENCY = auto()
    COMPONENT_TIMEOUT = auto()
    CONSTITUTION_LOAD_FAILED = auto()
    CONSTITUTION_INTEGRITY_CHECK_FAILED = auto()
    AXIOM_LOAD_FAILED = auto()
    AXIOM_VIOLATION_DURING_STARTUP = auto()
    KERNEL_INIT_FAILED = auto()
    KERNEL_GATE_NOT_READY = auto()
    API_START_FAILED = auto()
    API_PORT_IN_USE = auto()
    STARTUP_TIMEOUT = auto()
    HEALTH_CHECK_FAILED = auto()
    ROLLBACK_FAILED = auto()
    UNKNOWN_ERROR = auto()

    def display_name(self) -> str:
        names = {
            BootstrapErrorCode.CONFIG_NOT_FOUND: "Config Not Found",
            BootstrapErrorCode.CONFIG_PARSE_ERROR: "Config Parse Error",
            BootstrapErrorCode.CONFIG_VALIDATION_FAILED: "Config Validation Failed",
            BootstrapErrorCode.CONFIG_ENCRYPTION_FAILED: "Config Encryption Failed",
            BootstrapErrorCode.DATABASE_CONNECTION_FAILED: "Database Connection Failed",
            BootstrapErrorCode.DATABASE_MIGRATION_FAILED: "Database Migration Failed",
            BootstrapErrorCode.DATABASE_POOL_ERROR: "Database Pool Error",
            BootstrapErrorCode.DATABASE_SSL_ERROR: "Database SSL Error",
            BootstrapErrorCode.COMPONENT_INIT_FAILED: "Component Init Failed",
            BootstrapErrorCode.COMPONENT_DEPENDENCY_MISSING: "Component Dependency Missing",
            BootstrapErrorCode.COMPONENT_CIRCULAR_DEPENDENCY: "Circular Dependency",
            BootstrapErrorCode.COMPONENT_TIMEOUT: "Component Timeout",
            BootstrapErrorCode.CONSTITUTION_LOAD_FAILED: "Constitution Load Failed",
            BootstrapErrorCode.CONSTITUTION_INTEGRITY_CHECK_FAILED: "Constitution Integrity Failed",
            BootstrapErrorCode.AXIOM_LOAD_FAILED: "Axiom Load Failed",
            BootstrapErrorCode.AXIOM_VIOLATION_DURING_STARTUP: "Axiom Violation",
            BootstrapErrorCode.KERNEL_INIT_FAILED: "Kernel Init Failed",
            BootstrapErrorCode.KERNEL_GATE_NOT_READY: "Kernel Gate Not Ready",
            BootstrapErrorCode.API_START_FAILED: "API Start Failed",
            BootstrapErrorCode.API_PORT_IN_USE: "API Port In Use",
            BootstrapErrorCode.STARTUP_TIMEOUT: "Startup Timeout",
            BootstrapErrorCode.HEALTH_CHECK_FAILED: "Health Check Failed",
            BootstrapErrorCode.ROLLBACK_FAILED: "Rollback Failed",
            BootstrapErrorCode.UNKNOWN_ERROR: "Unknown Error",
        }
        return names.get(self, self.name)


class BootstrapSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0

    def display_name(self) -> str:
        names = {
            BootstrapSeverity.CRITICAL: "Critical",
            BootstrapSeverity.HIGH: "High",
            BootstrapSeverity.MEDIUM: "Medium",
            BootstrapSeverity.LOW: "Low",
            BootstrapSeverity.INFO: "Info",
        }
        return names.get(self, self.name)


# === 2. BASE EXCEPTION ===


class BootstrapError(Exception):
    """
    Base exception untuk semua error bootstrap.
    """

    def __init__(
        self,
        message: str,
        error_code: BootstrapErrorCode,
        severity: BootstrapSeverity = BootstrapSeverity.HIGH,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._exception_id = uuid4()
        self.timestamp = datetime.now(UTC)
        self._hash = self._compute_hash()
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "exception_id": str(self._exception_id),
                "error_code": self.error_code.name,
                "severity": self.severity.name,
                "timestamp": self.timestamp.isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "exception_id": str(self._exception_id),
                "details": details,
            }
        )

    def _compute_hash(self) -> str:
        data = {
            "exception_id": str(self._exception_id),
            "error_code": self.error_code.name,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "component": self.component,
            "details": self.details,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    @property
    def original_message(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self.original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
            "exception_id": str(self._exception_id),
            "timestamp": self.timestamp.isoformat(),
            "hash": self._hash,
            "version": self._version,
        }

    def is_critical(self) -> bool:
        return self.severity == BootstrapSeverity.CRITICAL

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self.message:
            errors.append("Message is required")
        if not isinstance(self.error_code, BootstrapErrorCode):
            errors.append("Invalid error_code")
        return {"is_valid": len(errors) == 0, "errors": errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BootstrapError:
        instance = cls(
            message=data["message"],
            error_code=BootstrapErrorCode[data["error_code"]],
            severity=BootstrapSeverity[data.get("severity", "HIGH")],
            component=data.get("component"),
            details=data.get("details"),
            cause=None,
        )
        instance._version = data.get("version", 1)
        instance._exception_id = uuid4()
        instance.timestamp = datetime.fromisoformat(
            data.get("timestamp", datetime.now(UTC).isoformat())
        )
        return instance

    def clone(self) -> BootstrapError:
        new = BootstrapError(
            message=self.message,
            error_code=self.error_code,
            severity=self.severity,
            component=self.component,
            details=self.details.copy(),
            cause=self.cause,
        )
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "exception_id": str(self._exception_id),
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "timestamp": self.timestamp.isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BootstrapError:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. CONCRETE EXCEPTIONS (semua mewarisi BootstrapError) ===


class ConfigError(BootstrapError):
    def __init__(
        self, message: str, config_key: str | None = None, file_path: str | None = None, **kwargs
    ):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.CONFIG_PARSE_ERROR,
            component="config",
            details={"config_key": config_key, "file_path": file_path},
            **kwargs,
        )
        self.config_key = config_key
        self.file_path = file_path


class ConfigNotFoundError(ConfigError):
    def __init__(self, file_path: str, **kwargs):
        super().__init__(
            message=f"Configuration file not found: {file_path}",
            file_path=file_path,
            error_code=BootstrapErrorCode.CONFIG_NOT_FOUND,
            **kwargs,
        )


class ConfigValidationError(ConfigError):
    def __init__(self, message: str, validation_errors: dict[str, str], **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.CONFIG_VALIDATION_FAILED,
            details={"validation_errors": validation_errors},
            **kwargs,
        )
        self.validation_errors = validation_errors


class DatabaseConnectionError(BootstrapError):
    def __init__(
        self, message: str, host: str | None = None, database: str | None = None, **kwargs
    ):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.DATABASE_CONNECTION_FAILED,
            component="database",
            details={"host": host, "database": database},
            **kwargs,
        )


class DatabaseMigrationError(BootstrapError):
    def __init__(self, message: str, migration_version: str | None = None, **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.DATABASE_MIGRATION_FAILED,
            component="database",
            details={"migration_version": migration_version},
            **kwargs,
        )


class ComponentInitError(BootstrapError):
    def __init__(
        self, component_name: str, message: str, dependency_chain: list | None = None, **kwargs
    ):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.COMPONENT_INIT_FAILED,
            component=component_name,
            details={"dependency_chain": dependency_chain},
            **kwargs,
        )
        self.component_name = component_name
        self.dependency_chain = dependency_chain


class ComponentDependencyMissingError(ComponentInitError):
    def __init__(self, component_name: str, missing_dependency: str, **kwargs):
        super().__init__(
            component_name=component_name,
            message=f"Missing dependency: {missing_dependency}",
            error_code=BootstrapErrorCode.COMPONENT_DEPENDENCY_MISSING,
            details={"missing_dependency": missing_dependency},
            **kwargs,
        )
        self.missing_dependency = missing_dependency


class CircularDependencyError(ComponentInitError):
    def __init__(self, component_name: str, cycle: list, **kwargs):
        super().__init__(
            component_name=component_name,
            message=f"Circular dependency detected: {' -> '.join(cycle)}",
            error_code=BootstrapErrorCode.COMPONENT_CIRCULAR_DEPENDENCY,
            details={"cycle": cycle},
            **kwargs,
        )
        self.cycle = cycle


class ComponentTimeoutError(ComponentInitError):
    def __init__(self, component_name: str, timeout_seconds: int, **kwargs):
        super().__init__(
            component_name=component_name,
            message=f"Component initialization timed out after {timeout_seconds}s",
            error_code=BootstrapErrorCode.COMPONENT_TIMEOUT,
            details={"timeout_seconds": timeout_seconds},
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds


class ConstitutionLoadError(BootstrapError):
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.CONSTITUTION_LOAD_FAILED,
            component="constitution",
            **kwargs,
        )


class ConstitutionIntegrityError(ConstitutionLoadError):
    def __init__(
        self,
        message: str,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
        **kwargs,
    ):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.CONSTITUTION_INTEGRITY_CHECK_FAILED,
            details={"expected_hash": expected_hash, "actual_hash": actual_hash},
            **kwargs,
        )
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


class AxiomLoadError(BootstrapError):
    def __init__(self, axiom_name: str, message: str, **kwargs):
        super().__init__(
            message=f"Failed to load axiom '{axiom_name}': {message}",
            error_code=BootstrapErrorCode.AXIOM_LOAD_FAILED,
            component="axioms",
            details={"axiom_name": axiom_name},
            **kwargs,
        )
        self.axiom_name = axiom_name


class KernelInitError(BootstrapError):
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.KERNEL_INIT_FAILED,
            component="kernel",
            **kwargs,
        )


class APIStartError(BootstrapError):
    def __init__(self, message: str, port: int | None = None, **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.API_START_FAILED,
            component="api",
            details={"port": port},
            **kwargs,
        )
        self.port = port


class APIPortInUseError(APIStartError):
    def __init__(self, port: int, **kwargs):
        super().__init__(
            message=f"Port {port} is already in use",
            port=port,
            error_code=BootstrapErrorCode.API_PORT_IN_USE,
            **kwargs,
        )


class StartupTimeoutError(BootstrapError):
    def __init__(self, timeout_seconds: int, current_phase: str, **kwargs):
        super().__init__(
            message=f"Startup timed out after {timeout_seconds}s during phase {current_phase}",
            error_code=BootstrapErrorCode.STARTUP_TIMEOUT,
            component="orchestrator",
            details={"timeout_seconds": timeout_seconds, "current_phase": current_phase},
            severity=BootstrapSeverity.CRITICAL,
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds
        self.current_phase = current_phase


class HealthCheckFailedError(BootstrapError):
    def __init__(self, failed_components: dict[str, str], **kwargs):
        super().__init__(
            message=f"Health check failed for components: {list(failed_components.keys())}",
            error_code=BootstrapErrorCode.HEALTH_CHECK_FAILED,
            component="health_probe",
            details={"failed_components": failed_components},
            severity=BootstrapSeverity.HIGH,
            **kwargs,
        )
        self.failed_components = failed_components


class RollbackFailedError(BootstrapError):
    def __init__(self, message: str, failed_rollback_step: str, **kwargs):
        super().__init__(
            message=message,
            error_code=BootstrapErrorCode.ROLLBACK_FAILED,
            component="rollback_handler",
            details={"failed_step": failed_rollback_step},
            severity=BootstrapSeverity.CRITICAL,
            **kwargs,
        )
        self.failed_rollback_step = failed_rollback_step


# === 4. EXCEPTION FACTORY ===


class BootstrapExceptionFactory:
    @staticmethod
    def config_not_found(file_path: str, **kwargs) -> ConfigNotFoundError:
        return ConfigNotFoundError(file_path=file_path, **kwargs)

    @staticmethod
    def config_validation_error(
        message: str, errors: dict[str, str], **kwargs
    ) -> ConfigValidationError:
        return ConfigValidationError(message=message, validation_errors=errors, **kwargs)

    @staticmethod
    def database_connection_error(
        message: str, host: str | None = None, db: str | None = None, **kwargs
    ) -> DatabaseConnectionError:
        return DatabaseConnectionError(message=message, host=host, database=db, **kwargs)

    @staticmethod
    def component_init_error(component: str, message: str, **kwargs) -> ComponentInitError:
        return ComponentInitError(component_name=component, message=message, **kwargs)

    @staticmethod
    def circular_dependency(component: str, cycle: list, **kwargs) -> CircularDependencyError:
        return CircularDependencyError(component_name=component, cycle=cycle, **kwargs)

    @staticmethod
    def constitution_integrity_error(
        message: str, expected: str, actual: str, **kwargs
    ) -> ConstitutionIntegrityError:
        return ConstitutionIntegrityError(
            message=message, expected_hash=expected, actual_hash=actual, **kwargs
        )

    @staticmethod
    def kernel_init_error(message: str, **kwargs) -> KernelInitError:
        return KernelInitError(message=message, **kwargs)

    @staticmethod
    def startup_timeout(seconds: int, phase: str, **kwargs) -> StartupTimeoutError:
        return StartupTimeoutError(timeout_seconds=seconds, current_phase=phase, **kwargs)

    @staticmethod
    def health_check_failed(components: dict[str, str], **kwargs) -> HealthCheckFailedError:
        return HealthCheckFailedError(failed_components=components, **kwargs)


# === 5. EXPORTS ===

__all__ = [
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
]
