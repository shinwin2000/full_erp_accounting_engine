#!/usr/bin/env python3
"""
Module: kernel_exceptions.py
Layer: 4 - Kernel / Kernel Exceptions
Responsibility: Exception khusus kernel untuk semua operasi di kernel layer.
               Mendefinisikan hierarchy exception untuk error yang terjadi
               di sealed gate, command dispatcher, transactional executor,
               circuit breaker, validation pipeline, dan komponen kernel lainnya.

Metode yang ditambahkan untuk setiap exception:
- to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- is_retryable(), is_critical()
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4


# === 1. CONSTANTS & ENUMS ===
class KernelErrorCode(Enum):
    """Kode error untuk kernel."""

    GATE_NOT_INITIALIZED = auto()
    GATE_CIRCUIT_OPEN = auto()
    GATE_IDEMPOTENCY_FAILED = auto()
    GATE_HANDLER_NOT_FOUND = auto()
    GATE_EXECUTION_FAILED = auto()
    GATE_VALIDATION_FAILED = auto()
    DISPATCHER_NOT_RUNNING = auto()
    DISPATCHER_QUEUE_FULL = auto()
    DISPATCHER_TIMEOUT = auto()
    DISPATCHER_PRIORITY_INVALID = auto()
    EXECUTOR_TRANSACTION_FAILED = auto()
    EXECUTOR_DEADLOCK_DETECTED = auto()
    EXECUTOR_TIMEOUT = auto()
    EXECUTOR_ROLLBACK_FAILED = auto()
    EXECUTOR_MAX_RETRIES_EXCEEDED = auto()
    EXECUTOR_ISOLATION_LEVEL_INVALID = auto()
    CIRCUIT_BREAKER_OPEN = auto()
    CIRCUIT_BREAKER_CONFIG_INVALID = auto()
    CIRCUIT_BREAKER_STATE_TRANSITION_FAILED = auto()
    VALIDATION_PIPELINE_FAILED = auto()
    VALIDATION_STAGE_FAILED = auto()
    VALIDATION_INVARIANT_VIOLATION = auto()
    VALIDATION_AXIOM_VIOLATION = auto()
    VALIDATION_CONSTITUTION_VIOLATION = auto()
    VALIDATION_POLICY_VIOLATION = auto()
    CONTEXT_NOT_FOUND = auto()
    CONTEXT_INVALID = auto()
    CONTEXT_NESTING_ERROR = auto()
    AUDIT_HOOK_FAILED = auto()
    AUDIT_EVENT_STORE_UNAVAILABLE = auto()
    METRIC_COLLECTOR_DISABLED = auto()
    METRIC_NOT_FOUND = auto()
    RETRY_POLICY_INVALID = auto()
    RETRY_EXHAUSTED = auto()
    DISTRIBUTED_LOCK_TIMEOUT = auto()
    DISTRIBUTED_LOCK_NOT_ACQUIRED = auto()
    DISTRIBUTED_LOCK_RELEASE_FAILED = auto()
    DEPENDENCY_NOT_FOUND = auto()
    DEPENDENCY_CIRCULAR = auto()
    LIFECYCLE_INVALID_TRANSITION = auto()
    LIFECYCLE_CALLBACK_FAILED = auto()
    KERNEL_NOT_READY = auto()
    KERNEL_SHUTDOWN = auto()
    KERNEL_INITIALIZATION_FAILED = auto()
    UNKNOWN_KERNEL_ERROR = auto()


class KernelSeverity(Enum):
    """Severity error kernel."""

    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


# === 2. BASE EXCEPTION ===
class KernelError(Exception):
    """Base exception untuk semua error kernel."""

    _exception_id: str
    _timestamp: datetime
    _version: int
    _audit_trail: list[dict[str, Any]]
    _snapshots: list[dict[str, Any]]

    def __init__(
        self,
        message: str,
        error_code: KernelErrorCode,
        severity: KernelSeverity = KernelSeverity.MEDIUM,
        component: str | None = None,
        details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.error_code = error_code
        self.severity = severity
        self.component = component
        self.details = details or {}
        self.cause = cause
        # Untuk entity methods
        self._exception_id = str(uuid4())
        self._timestamp = datetime.now(UTC)
        self._version = 1
        self._audit_trail = []
        self._snapshots = []

        full_message = f"[{severity.name}][{error_code.name}] {message}"
        if component:
            full_message = f"[{component}] {full_message}"
        super().__init__(full_message)
        self._original_message = message

    @property
    def original_message(self) -> str:
        return self._original_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_id": self._exception_id,
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message,
            "component": self.component,
            "details": self.details,
            "cause": str(self.cause) if self.cause else None,
            "timestamp": self._timestamp.isoformat(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KernelError:
        error_code = KernelErrorCode[data["error_code"]]
        severity = KernelSeverity[data["severity"]]
        instance = cls(
            message=data["message"],
            error_code=error_code,
            severity=severity,
            component=data.get("component"),
            details=data.get("details"),
        )
        instance._exception_id = data.get("exception_id", str(uuid4()))
        instance._timestamp = (
            datetime.fromisoformat(data["timestamp"])
            if data.get("timestamp")
            else datetime.now(UTC)
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> KernelError:
        new_exc = self.__class__(
            message=self._original_message,
            error_code=self.error_code,
            severity=self.severity,
            component=self.component,
            details=self.details.copy(),
            cause=self.cause,
        )
        new_exc._exception_id = str(uuid4())
        new_exc._timestamp = datetime.now(UTC)
        new_exc._version = self._version + 1
        return new_exc

    def snapshot(self) -> dict[str, Any]:
        return {
            "exception_id": self._exception_id,
            "type": self.__class__.__name__,
            "error_code": self.error_code.name,
            "severity": self.severity.name,
            "message": self._original_message[:200],
            "timestamp": self._timestamp.isoformat(),
            "version": self._version,
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> KernelError:
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

    def is_critical(self) -> bool:
        return self.severity == KernelSeverity.CRITICAL

    def is_retryable(self) -> bool:
        return self.severity.value <= KernelSeverity.MEDIUM.value


# === 3. CONCRETE EXCEPTIONS (semua mewarisi KernelError) ===
# Sealed Gate Exceptions
class GateNotInitializedError(KernelError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            message="Sealed gate not initialized. Call initialize() first.",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.CRITICAL,
            component="sealed_gate",
            **kwargs,
        )


class GateCircuitOpenError(KernelError):
    circuit_name: str

    def __init__(self, circuit_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Circuit breaker '{circuit_name}' is open. Request rejected.",
            error_code=KernelErrorCode.GATE_CIRCUIT_OPEN,
            severity=KernelSeverity.HIGH,
            component="sealed_gate",
            details={"circuit_name": circuit_name},
            **kwargs,
        )
        self.circuit_name = circuit_name


class GateHandlerNotFoundError(KernelError):
    command_type: str

    def __init__(self, command_type: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Handler not found for command type: {command_type}",
            error_code=KernelErrorCode.GATE_HANDLER_NOT_FOUND,
            severity=KernelSeverity.HIGH,
            component="sealed_gate",
            details={"command_type": command_type},
            **kwargs,
        )
        self.command_type = command_type


class GateIdempotencyError(KernelError):
    idempotency_key: str

    def __init__(self, idempotency_key: str, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Idempotency error for key {idempotency_key}: {message}",
            error_code=KernelErrorCode.GATE_IDEMPOTENCY_FAILED,
            severity=KernelSeverity.MEDIUM,
            component="sealed_gate",
            details={"idempotency_key": idempotency_key},
            **kwargs,
        )
        self.idempotency_key = idempotency_key


class GateValidationFailedError(KernelError):
    stage: str
    reason: str

    def __init__(self, stage: str, reason: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Validation failed at {stage}: {reason}",
            error_code=KernelErrorCode.GATE_VALIDATION_FAILED,
            severity=KernelSeverity.HIGH,
            component="sealed_gate",
            details={"stage": stage, "reason": reason},
            **kwargs,
        )
        self.stage = stage
        self.reason = reason


# Command Dispatcher Exceptions
class DispatcherNotRunningError(KernelError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            message="Command dispatcher is not running. Start workers first.",
            error_code=KernelErrorCode.DISPATCHER_NOT_RUNNING,
            severity=KernelSeverity.CRITICAL,
            component="command_dispatcher",
            **kwargs,
        )


class DispatcherQueueFullError(KernelError):
    queue_size: int
    max_size: int

    def __init__(self, queue_size: int, max_size: int, **kwargs: Any) -> None:
        super().__init__(
            message=f"Command queue is full: {queue_size}/{max_size}",
            error_code=KernelErrorCode.DISPATCHER_QUEUE_FULL,
            severity=KernelSeverity.HIGH,
            component="command_dispatcher",
            details={"queue_size": queue_size, "max_size": max_size},
            **kwargs,
        )
        self.queue_size = queue_size
        self.max_size = max_size


class DispatcherTimeoutError(KernelError):
    command_type: str
    timeout_seconds: float

    def __init__(self, command_type: str, timeout_seconds: float, **kwargs: Any) -> None:
        super().__init__(
            message=f"Command {command_type} timed out after {timeout_seconds}s",
            error_code=KernelErrorCode.DISPATCHER_TIMEOUT,
            severity=KernelSeverity.MEDIUM,
            component="command_dispatcher",
            details={"command_type": command_type, "timeout_seconds": timeout_seconds},
            **kwargs,
        )
        self.command_type = command_type
        self.timeout_seconds = timeout_seconds


# Transactional Executor Exceptions
class ExecutorTransactionFailedError(KernelError):
    transaction_id: str

    def __init__(self, transaction_id: str, original_error: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Transaction {transaction_id} failed: {original_error}",
            error_code=KernelErrorCode.EXECUTOR_TRANSACTION_FAILED,
            severity=KernelSeverity.HIGH,
            component="transactional_executor",
            details={"transaction_id": transaction_id, "original_error": original_error},
            **kwargs,
        )
        self.transaction_id = transaction_id


class ExecutorDeadlockDetectedError(KernelError):
    transaction_id: str
    waiting_for: list[Any]

    def __init__(self, transaction_id: str, waiting_for: list[Any], **kwargs: Any) -> None:
        super().__init__(
            message=f"Deadlock detected in transaction {transaction_id}. Waiting for: {waiting_for}",
            error_code=KernelErrorCode.EXECUTOR_DEADLOCK_DETECTED,
            severity=KernelSeverity.HIGH,
            component="transactional_executor",
            details={"transaction_id": transaction_id, "waiting_for": waiting_for},
            **kwargs,
        )
        self.transaction_id = transaction_id
        self.waiting_for = waiting_for


class ExecutorMaxRetriesExceededError(KernelError):
    retry_count: int
    max_retries: int

    def __init__(self, retry_count: int, max_retries: int, last_error: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Max retries ({max_retries}) exceeded after {retry_count} attempts. Last error: {last_error}",
            error_code=KernelErrorCode.EXECUTOR_MAX_RETRIES_EXCEEDED,
            severity=KernelSeverity.HIGH,
            component="transactional_executor",
            details={
                "retry_count": retry_count,
                "max_retries": max_retries,
                "last_error": last_error,
            },
            **kwargs,
        )
        self.retry_count = retry_count
        self.max_retries = max_retries


class ExecutorRollbackFailedError(KernelError):
    transaction_id: str

    def __init__(self, transaction_id: str, original_error: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Rollback failed for transaction {transaction_id}: {original_error}",
            error_code=KernelErrorCode.EXECUTOR_ROLLBACK_FAILED,
            severity=KernelSeverity.CRITICAL,
            component="transactional_executor",
            details={"transaction_id": transaction_id, "original_error": original_error},
            **kwargs,
        )
        self.transaction_id = transaction_id


# Circuit Breaker Exceptions
class CircuitBreakerOpenError(KernelError):
    circuit_name: str

    def __init__(self, circuit_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Circuit breaker '{circuit_name}' is open",
            error_code=KernelErrorCode.CIRCUIT_BREAKER_OPEN,
            severity=KernelSeverity.HIGH,
            component="circuit_breaker",
            details={"circuit_name": circuit_name},
            **kwargs,
        )
        self.circuit_name = circuit_name


class CircuitBreakerConfigInvalidError(KernelError):
    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Invalid circuit breaker configuration: {message}",
            error_code=KernelErrorCode.CIRCUIT_BREAKER_CONFIG_INVALID,
            severity=KernelSeverity.MEDIUM,
            component="circuit_breaker",
            **kwargs,
        )


# Validation Pipeline Exceptions
class ValidationPipelineFailedError(KernelError):
    failed_stage: str

    def __init__(self, failed_stage: str, reason: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Validation pipeline failed at stage {failed_stage}: {reason}",
            error_code=KernelErrorCode.VALIDATION_PIPELINE_FAILED,
            severity=KernelSeverity.HIGH,
            component="validation_pipeline",
            details={"failed_stage": failed_stage, "reason": reason},
            **kwargs,
        )
        self.failed_stage = failed_stage


class InvariantViolationError(ValidationPipelineFailedError):
    invariant_type: str

    def __init__(self, invariant_type: str, message: str, **kwargs: Any) -> None:
        super().__init__(
            failed_stage="INVARIANTS",
            reason=f"Invariant {invariant_type} violated: {message}",
            component="invariants",
            details={"invariant_type": invariant_type},
            **kwargs,
        )
        self.invariant_type = invariant_type


class AxiomViolationError(ValidationPipelineFailedError):
    axiom_name: str

    def __init__(self, axiom_name: str, message: str, **kwargs: Any) -> None:
        super().__init__(
            failed_stage="AXIOMS",
            reason=f"Axiom {axiom_name} violated: {message}",
            component="axioms",
            details={"axiom_name": axiom_name},
            **kwargs,
        )
        self.axiom_name = axiom_name


class ConstitutionViolationError(ValidationPipelineFailedError):
    principle: str

    def __init__(self, principle: str, message: str, **kwargs: Any) -> None:
        super().__init__(
            failed_stage="CONSTITUTION",
            reason=f"Constitution principle {principle} violated: {message}",
            component="constitution",
            details={"principle": principle},
            **kwargs,
        )
        self.principle = principle


class PolicyViolationError(ValidationPipelineFailedError):
    policy_name: str

    def __init__(self, policy_name: str, message: str, **kwargs: Any) -> None:
        super().__init__(
            failed_stage="POLICY",
            reason=f"Policy {policy_name} violated: {message}",
            component="policy_engine",
            details={"policy_name": policy_name},
            **kwargs,
        )
        self.policy_name = policy_name


# Context Holder Exceptions
class ContextNotFoundError(KernelError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            message="No execution context found. Set context before calling this operation.",
            error_code=KernelErrorCode.CONTEXT_NOT_FOUND,
            severity=KernelSeverity.MEDIUM,
            component="context_holder",
            **kwargs,
        )


class ContextInvalidError(KernelError):
    def __init__(self, reason: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Invalid execution context: {reason}",
            error_code=KernelErrorCode.CONTEXT_INVALID,
            severity=KernelSeverity.MEDIUM,
            component="context_holder",
            **kwargs,
        )


# Distributed Lock Exceptions
class DistributedLockTimeoutError(KernelError):
    lock_key: str
    timeout_seconds: float

    def __init__(self, lock_key: str, timeout_seconds: float, **kwargs: Any) -> None:
        super().__init__(
            message=f"Failed to acquire lock '{lock_key}' after {timeout_seconds}s",
            error_code=KernelErrorCode.DISTRIBUTED_LOCK_TIMEOUT,
            severity=KernelSeverity.MEDIUM,
            component="distributed_lock",
            details={"lock_key": lock_key, "timeout_seconds": timeout_seconds},
            **kwargs,
        )
        self.lock_key = lock_key
        self.timeout_seconds = timeout_seconds


class DistributedLockNotAcquiredError(KernelError):
    lock_key: str

    def __init__(self, lock_key: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Failed to acquire lock '{lock_key}' (non-blocking)",
            error_code=KernelErrorCode.DISTRIBUTED_LOCK_NOT_ACQUIRED,
            severity=KernelSeverity.LOW,
            component="distributed_lock",
            details={"lock_key": lock_key},
            **kwargs,
        )
        self.lock_key = lock_key


# Dependency Injector Exceptions
class DependencyNotFoundError(KernelError):
    interface_name: str

    def __init__(self, interface_name: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Dependency not found for interface: {interface_name}",
            error_code=KernelErrorCode.DEPENDENCY_NOT_FOUND,
            severity=KernelSeverity.CRITICAL,
            component="dependency_injector",
            details={"interface": interface_name},
            **kwargs,
        )
        self.interface_name = interface_name


# Lifecycle Exceptions
class LifecycleInvalidTransitionError(KernelError):
    from_phase: str
    to_phase: str

    def __init__(self, from_phase: str, to_phase: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Invalid lifecycle transition from {from_phase} to {to_phase}",
            error_code=KernelErrorCode.LIFECYCLE_INVALID_TRANSITION,
            severity=KernelSeverity.HIGH,
            component="lifecycle_listener",
            details={"from_phase": from_phase, "to_phase": to_phase},
            **kwargs,
        )
        self.from_phase = from_phase
        self.to_phase = to_phase


# Retry Policy Exceptions
class RetryExhaustedError(KernelError):
    retry_count: int

    def __init__(self, retry_count: int, last_error: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Retry exhausted after {retry_count} attempts. Last error: {last_error}",
            error_code=KernelErrorCode.RETRY_EXHAUSTED,
            severity=KernelSeverity.MEDIUM,
            component="retry_policy",
            details={"retry_count": retry_count, "last_error": last_error},
            **kwargs,
        )
        self.retry_count = retry_count


# General Kernel Exceptions
class KernelNotReadyError(KernelError):
    reason: str

    def __init__(self, reason: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Kernel not ready: {reason}",
            error_code=KernelErrorCode.KERNEL_NOT_READY,
            severity=KernelSeverity.CRITICAL,
            component="kernel",
            details={"reason": reason},
            **kwargs,
        )
        self.reason = reason


class KernelShutdownError(KernelError):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            message="Kernel is shutting down. New requests rejected.",
            error_code=KernelErrorCode.KERNEL_SHUTDOWN,
            severity=KernelSeverity.CRITICAL,
            component="kernel",
            **kwargs,
        )


class KernelInitializationFailedError(KernelError):
    def __init__(self, reason: str, **kwargs: Any) -> None:
        super().__init__(
            message=f"Kernel initialization failed: {reason}",
            error_code=KernelErrorCode.KERNEL_INITIALIZATION_FAILED,
            severity=KernelSeverity.CRITICAL,
            component="kernel",
            details={"reason": reason},
            **kwargs,
        )


# === 4. EXCEPTION FACTORY ===
class KernelExceptionFactory:
    """Factory untuk membuat kernel exceptions dengan konsistensi."""

    @staticmethod
    def gate_circuit_open(circuit_name: str, **kwargs: Any) -> GateCircuitOpenError:
        return GateCircuitOpenError(circuit_name=circuit_name, **kwargs)

    @staticmethod
    def gate_handler_not_found(command_type: str, **kwargs: Any) -> GateHandlerNotFoundError:
        return GateHandlerNotFoundError(command_type=command_type, **kwargs)

    @staticmethod
    def dispatcher_queue_full(queue_size: int, max_size: int, **kwargs: Any) -> DispatcherQueueFullError:
        return DispatcherQueueFullError(queue_size=queue_size, max_size=max_size, **kwargs)

    @staticmethod
    def transaction_failed(
        transaction_id: str, error: str, **kwargs: Any
    ) -> ExecutorTransactionFailedError:
        return ExecutorTransactionFailedError(
            transaction_id=transaction_id, original_error=error, **kwargs
        )

    @staticmethod
    def deadlock_detected(
        transaction_id: str, waiting_for: list[Any], **kwargs: Any
    ) -> ExecutorDeadlockDetectedError:
        return ExecutorDeadlockDetectedError(
            transaction_id=transaction_id, waiting_for=waiting_for, **kwargs
        )

    @staticmethod
    def validation_failed(stage: str, reason: str, **kwargs: Any) -> ValidationPipelineFailedError:
        return ValidationPipelineFailedError(failed_stage=stage, reason=reason, **kwargs)

    @staticmethod
    def invariant_violation(invariant_type: str, message: str, **kwargs: Any) -> InvariantViolationError:
        return InvariantViolationError(invariant_type=invariant_type, message=message, **kwargs)

    @staticmethod
    def axiom_violation(axiom_name: str, message: str, **kwargs: Any) -> AxiomViolationError:
        return AxiomViolationError(axiom_name=axiom_name, message=message, **kwargs)

    @staticmethod
    def constitution_violation(
        principle: str, message: str, **kwargs: Any
    ) -> ConstitutionViolationError:
        return ConstitutionViolationError(principle=principle, message=message, **kwargs)

    @staticmethod
    def kernel_not_ready(reason: str, **kwargs: Any) -> KernelNotReadyError:
        return KernelNotReadyError(reason=reason, **kwargs)

    @staticmethod
    def distributed_lock_timeout(
        lock_key: str, timeout_seconds: float, **kwargs: Any
    ) -> DistributedLockTimeoutError:
        return DistributedLockTimeoutError(
            lock_key=lock_key, timeout_seconds=timeout_seconds, **kwargs
        )

    @staticmethod
    def dependency_not_found(interface_name: str, **kwargs: Any) -> DependencyNotFoundError:
        return DependencyNotFoundError(interface_name=interface_name, **kwargs)


# === 5. EXPORTS ===
__all__ = [
    "AxiomViolationError",
    "CircuitBreakerConfigInvalidError",
    "CircuitBreakerOpenError",
    "ConstitutionViolationError",
    "ContextInvalidError",
    "ContextNotFoundError",
    "DependencyNotFoundError",
    "DispatcherNotRunningError",
    "DispatcherQueueFullError",
    "DispatcherTimeoutError",
    "DistributedLockNotAcquiredError",
    "DistributedLockTimeoutError",
    "ExecutorDeadlockDetectedError",
    "ExecutorMaxRetriesExceededError",
    "ExecutorRollbackFailedError",
    "ExecutorTransactionFailedError",
    "GateCircuitOpenError",
    "GateHandlerNotFoundError",
    "GateIdempotencyError",
    "GateNotInitializedError",
    "GateValidationFailedError",
    "InvariantViolationError",
    "KernelError",
    "KernelErrorCode",
    "KernelExceptionFactory",
    "KernelInitializationFailedError",
    "KernelNotReadyError",
    "KernelSeverity",
    "KernelShutdownError",
    "LifecycleInvalidTransitionError",
    "PolicyViolationError",
    "RetryExhaustedError",
    "ValidationPipelineFailedError",
]
