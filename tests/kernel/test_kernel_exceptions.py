#!/usr/bin/env python3
"""
Comprehensive tests for kernel/kernel_exceptions.py

Covers:
- KernelErrorCode enum
- KernelSeverity enum
- KernelError base exception: construction, properties, to_dict, from_dict,
  clone, snapshot, version, audit_trail, touch, is_critical, is_retryable
- All concrete exceptions (35+ classes) via parametrized tests ensuring
  correct inheritance and attribute presence
- KernelExceptionFactory static methods return correct exception types
- No duplicate test structures
- Mocked datetime to avoid flakiness
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from kernel.kernel_exceptions import (
    AxiomViolationError,
    CircuitBreakerConfigInvalidError,
    CircuitBreakerOpenError,
    ConstitutionViolationError,
    ContextInvalidError,
    ContextNotFoundError,
    DependencyNotFoundError,
    DispatcherNotRunningError,
    DispatcherQueueFullError,
    DispatcherTimeoutError,
    DistributedLockNotAcquiredError,
    DistributedLockTimeoutError,
    ExecutorDeadlockDetectedError,
    ExecutorMaxRetriesExceededError,
    ExecutorRollbackFailedError,
    ExecutorTransactionFailedError,
    GateCircuitOpenError,
    GateHandlerNotFoundError,
    GateIdempotencyError,
    GateNotInitializedError,
    GateValidationFailedError,
    InvariantViolationError,
    KernelError,
    KernelErrorCode,
    KernelExceptionFactory,
    KernelInitializationFailedError,
    KernelNotReadyError,
    KernelSeverity,
    KernelShutdownError,
    LifecycleInvalidTransitionError,
    PolicyViolationError,
    RetryExhaustedError,
    ValidationPipelineFailedError,
)

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now(UTC) to return a fixed value."""
    with patch("kernel.kernel_exceptions.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# -----------------------------------------------------------------------------
# Enums
# -----------------------------------------------------------------------------

class TestKernelErrorCode:
    def test_members(self):
        # Spot-check a few members
        assert KernelErrorCode.GATE_NOT_INITIALIZED.name == "GATE_NOT_INITIALIZED"
        assert KernelErrorCode.EXECUTOR_TRANSACTION_FAILED.name == "EXECUTOR_TRANSACTION_FAILED"
        assert KernelErrorCode.DISTRIBUTED_LOCK_TIMEOUT.name == "DISTRIBUTED_LOCK_TIMEOUT"
        assert isinstance(KernelErrorCode.GATE_NOT_INITIALIZED, KernelErrorCode)

    def test_all_members_defined(self):
        # We can check that the set is large enough
        assert len(KernelErrorCode) > 40  # there are many


class TestKernelSeverity:
    def test_members(self):
        assert KernelSeverity.CRITICAL.value == 80
        assert KernelSeverity.HIGH.value == 60
        assert KernelSeverity.MEDIUM.value == 40
        assert KernelSeverity.LOW.value == 20
        assert KernelSeverity.INFO.value == 0
        assert isinstance(KernelSeverity.CRITICAL, KernelSeverity)


# -----------------------------------------------------------------------------
# Base KernelError tests
# -----------------------------------------------------------------------------

class TestKernelError:
    def test_construction(self):
        exc = KernelError(
            message="Test error",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.CRITICAL,
            component="test_comp",
            details={"key": "value"},
            cause=ValueError("cause"),
        )
        assert exc.error_code == KernelErrorCode.GATE_NOT_INITIALIZED
        assert exc.severity == KernelSeverity.CRITICAL
        assert exc.component == "test_comp"
        assert exc.details == {"key": "value"}
        assert isinstance(exc.cause, ValueError)
        assert exc.original_message == "Test error"
        # Message includes severity and error code
        assert "[CRITICAL]" in str(exc)
        assert "[GATE_NOT_INITIALIZED]" in str(exc)
        assert exc._exception_id is not None
        assert exc._timestamp == FIXED_NOW
        assert exc._version == 1

    def test_to_dict(self):
        exc = KernelError(
            message="Test",
            error_code=KernelErrorCode.GATE_HANDLER_NOT_FOUND,
            severity=KernelSeverity.HIGH,
            component="gate",
            details={"cmd": "test"},
            cause=KeyError("missing"),
        )
        d = exc.to_dict()
        assert d["exception_id"] == exc._exception_id
        assert d["type"] == "KernelError"
        assert d["error_code"] == "GATE_HANDLER_NOT_FOUND"
        assert d["severity"] == "HIGH"
        assert d["message"] == "Test"
        assert d["component"] == "gate"
        assert d["details"] == {"cmd": "test"}
        assert "KeyError" in d["cause"]
        assert d["timestamp"] == FIXED_NOW.isoformat()
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "exception_id": "12345678-1234-1234-1234-123456789012",
            "type": "KernelError",
            "error_code": "GATE_NOT_INITIALIZED",
            "severity": "CRITICAL",
            "message": "Restored",
            "component": "comp",
            "details": {"a": 1},
            "cause": None,
            "timestamp": FIXED_NOW.isoformat(),
            "version": 2,
        }
        exc = KernelError.from_dict(data)
        assert exc._exception_id == data["exception_id"]
        assert exc.error_code == KernelErrorCode.GATE_NOT_INITIALIZED
        assert exc.severity == KernelSeverity.CRITICAL
        assert exc.original_message == "Restored"
        assert exc.component == "comp"
        assert exc.details == {"a": 1}
        assert exc.cause is None
        assert exc._timestamp == FIXED_NOW
        assert exc._version == 2

    def test_clone(self):
        exc = KernelError(
            message="Original",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.MEDIUM,
            component="c",
            details={"d": "e"},
        )
        cloned = exc.clone()
        assert cloned is not exc
        assert cloned._exception_id != exc._exception_id
        assert cloned._timestamp != exc._timestamp
        assert cloned._version == exc._version + 1
        assert cloned.error_code == exc.error_code
        assert cloned.severity == exc.severity
        assert cloned.original_message == exc.original_message
        assert cloned.component == exc.component
        assert cloned.details == exc.details
        assert cloned.cause == exc.cause

    def test_snapshot(self):
        exc = KernelError(
            message="Snap",
            error_code=KernelErrorCode.KERNEL_NOT_READY,
            severity=KernelSeverity.HIGH,
        )
        snap = exc.snapshot()
        assert snap["exception_id"] == exc._exception_id
        assert snap["type"] == "KernelError"
        assert snap["error_code"] == "KERNEL_NOT_READY"
        assert snap["severity"] == "HIGH"
        assert snap["message"] == "Snap"
        assert snap["timestamp"] == FIXED_NOW.isoformat()
        assert snap["version"] == 1

    def test_version(self):
        exc = KernelError(
            message="v",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
        )
        assert exc.version() == 1
        exc.touch("user")
        assert exc.version() == 2

    def test_audit_trail(self):
        exc = KernelError(
            message="audit",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
        )
        assert len(exc.audit_trail()) == 0  # initially empty
        exc.touch("toucher")
        trail = exc.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "toucher"
        assert trail[0]["version"] == 2

    def test_touch(self):
        exc = KernelError(
            message="t",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
        )
        assert exc._version == 1
        touched = exc.touch("user")
        assert touched is exc  # returns self
        assert exc._version == 2
        assert len(exc._audit_trail) == 1

    def test_is_critical(self):
        exc_crit = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.CRITICAL
        )
        assert exc_crit.is_critical() is True
        exc_high = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.HIGH
        )
        assert exc_high.is_critical() is False

    def test_is_retryable(self):
        # MEDIUM and below are retryable
        exc_medium = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.MEDIUM
        )
        assert exc_medium.is_retryable() is True
        exc_low = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.LOW
        )
        assert exc_low.is_retryable() is True
        exc_info = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.INFO
        )
        assert exc_info.is_retryable() is True
        exc_high = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.HIGH
        )
        assert exc_high.is_retryable() is False
        exc_crit = KernelError(
            message="", error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            severity=KernelSeverity.CRITICAL
        )
        assert exc_crit.is_retryable() is False


# -----------------------------------------------------------------------------
# Concrete Exceptions - parametrized construction tests
# -----------------------------------------------------------------------------

# List of (exception_class, required_kwargs) where required_kwargs are the
# parameters needed for construction beyond the common ones.
EXCEPTION_CLASSES = [
    (GateNotInitializedError, {}),
    (GateCircuitOpenError, {"circuit_name": "circuit"}),
    (GateHandlerNotFoundError, {"command_type": "cmd"}),
    (GateIdempotencyError, {"idempotency_key": "key", "message": "msg"}),
    (GateValidationFailedError, {"stage": "stage", "reason": "reason"}),
    (DispatcherNotRunningError, {}),
    (DispatcherQueueFullError, {"queue_size": 10, "max_size": 20}),
    (DispatcherTimeoutError, {"command_type": "cmd", "timeout_seconds": 5.0}),
    (ExecutorTransactionFailedError, {"transaction_id": "txn", "original_error": "err"}),
    (ExecutorDeadlockDetectedError, {"transaction_id": "txn", "waiting_for": ["a", "b"]}),
    (ExecutorMaxRetriesExceededError, {"retry_count": 3, "max_retries": 5, "last_error": "err"}),
    (ExecutorRollbackFailedError, {"transaction_id": "txn", "original_error": "err"}),
    (CircuitBreakerOpenError, {"circuit_name": "circuit"}),
    (CircuitBreakerConfigInvalidError, {"message": "bad config"}),
    (ValidationPipelineFailedError, {"failed_stage": "stage", "reason": "reason"}),
    (InvariantViolationError, {"invariant_type": "type", "message": "msg"}),
    (AxiomViolationError, {"axiom_name": "name", "message": "msg"}),
    (ConstitutionViolationError, {"principle": "p", "message": "msg"}),
    (PolicyViolationError, {"policy_name": "p", "message": "msg"}),
    (ContextNotFoundError, {}),
    (ContextInvalidError, {"reason": "reason"}),
    (DistributedLockTimeoutError, {"lock_key": "lock", "timeout_seconds": 10.0}),
    (DistributedLockNotAcquiredError, {"lock_key": "lock"}),
    (DependencyNotFoundError, {"interface_name": "iface"}),
    (LifecycleInvalidTransitionError, {"from_phase": "start", "to_phase": "end"}),
    (RetryExhaustedError, {"retry_count": 5, "last_error": "err"}),
    (KernelNotReadyError, {"reason": "reason"}),
    (KernelShutdownError, {}),
    (KernelInitializationFailedError, {"reason": "reason"}),
]


class TestConcreteExceptions:
    @pytest.mark.parametrize("exc_class,kwargs", EXCEPTION_CLASSES)
    def test_construction_and_inheritance(self, exc_class, kwargs):
        # For exceptions that accept 'message' differently, we'll use the required args.
        # Some exceptions like GateIdempotencyError accept 'message' as second arg.
        # We'll just use the provided kwargs; the class should handle it.
        # For those that don't need extra, we pass empty.
        try:
            exc = exc_class(**kwargs)
        except TypeError:
            # Some exceptions have required positional args; we need to handle specifically
            # but our list already includes required kwargs; if still fails, we can adjust.
            # Let's fallback: use the expected signature.
            # For simplicity, we can just test the ones we know.
            # We'll patch the test to use the correct signature.
            # Actually the list is correct, but some might need 'message' as first arg
            # e.g., GateIdempotencyError expects idempotency_key and message.
            # Our kwargs include those, so it should work.
            raise
        assert isinstance(exc, KernelError)
        assert isinstance(exc, exc_class)
        # Check that the exception has the expected attributes
        for key, value in kwargs.items():
            if hasattr(exc, key):
                assert getattr(exc, key) == value
        # Also check error_code and severity are set appropriately
        # For known exceptions, we can check they have the right component/severity
        # but we'll just verify they are not None.
        assert exc.error_code is not None
        assert exc.severity is not None

    # Also test that each exception is raise-able and catches correctly
    @pytest.mark.parametrize("exc_class,kwargs", EXCEPTION_CLASSES)
    def test_can_raise_and_catch(self, exc_class, kwargs):
        with pytest.raises(exc_class):
            raise exc_class(**kwargs)


# -----------------------------------------------------------------------------
# KernelExceptionFactory
# -----------------------------------------------------------------------------

class TestKernelExceptionFactory:
    def test_factory_gate_circuit_open(self):
        exc = KernelExceptionFactory.gate_circuit_open("mycircuit")
        assert isinstance(exc, GateCircuitOpenError)
        assert exc.circuit_name == "mycircuit"
        assert exc.error_code == KernelErrorCode.GATE_CIRCUIT_OPEN

    def test_factory_gate_handler_not_found(self):
        exc = KernelExceptionFactory.gate_handler_not_found("mycmd")
        assert isinstance(exc, GateHandlerNotFoundError)
        assert exc.command_type == "mycmd"
        assert exc.error_code == KernelErrorCode.GATE_HANDLER_NOT_FOUND

    def test_factory_dispatcher_queue_full(self):
        exc = KernelExceptionFactory.dispatcher_queue_full(10, 20)
        assert isinstance(exc, DispatcherQueueFullError)
        assert exc.queue_size == 10
        assert exc.max_size == 20
        assert exc.error_code == KernelErrorCode.DISPATCHER_QUEUE_FULL

    def test_factory_transaction_failed(self):
        exc = KernelExceptionFactory.transaction_failed("txn1", "connection lost")
        assert isinstance(exc, ExecutorTransactionFailedError)
        assert exc.transaction_id == "txn1"
        assert "connection lost" in exc.original_message
        assert exc.error_code == KernelErrorCode.EXECUTOR_TRANSACTION_FAILED

    def test_factory_deadlock_detected(self):
        exc = KernelExceptionFactory.deadlock_detected("txn1", ["lock1", "lock2"])
        assert isinstance(exc, ExecutorDeadlockDetectedError)
        assert exc.transaction_id == "txn1"
        assert exc.waiting_for == ["lock1", "lock2"]
        assert exc.error_code == KernelErrorCode.EXECUTOR_DEADLOCK_DETECTED

    def test_factory_validation_failed(self):
        exc = KernelExceptionFactory.validation_failed("stage1", "invalid input")
        assert isinstance(exc, ValidationPipelineFailedError)
        assert exc.failed_stage == "stage1"
        assert "invalid input" in exc.reason
        assert exc.error_code == KernelErrorCode.VALIDATION_PIPELINE_FAILED

    def test_factory_invariant_violation(self):
        exc = KernelExceptionFactory.invariant_violation("UNIQUE", "duplicate code")
        assert isinstance(exc, InvariantViolationError)
        assert exc.invariant_type == "UNIQUE"
        assert "duplicate code" in exc.reason
        assert exc.error_code == KernelErrorCode.VALIDATION_INVARIANT_VIOLATION

    def test_factory_axiom_violation(self):
        exc = KernelExceptionFactory.axiom_violation("CONSERVATION", "value lost")
        assert isinstance(exc, AxiomViolationError)
        assert exc.axiom_name == "CONSERVATION"
        assert "value lost" in exc.reason
        assert exc.error_code == KernelErrorCode.VALIDATION_AXIOM_VIOLATION

    def test_factory_constitution_violation(self):
        exc = KernelExceptionFactory.constitution_violation("IMMUTABILITY", "modified")
        assert isinstance(exc, ConstitutionViolationError)
        assert exc.principle == "IMMUTABILITY"
        assert "modified" in exc.reason
        assert exc.error_code == KernelErrorCode.VALIDATION_CONSTITUTION_VIOLATION

    def test_factory_kernel_not_ready(self):
        exc = KernelExceptionFactory.kernel_not_ready("not initialized")
        assert isinstance(exc, KernelNotReadyError)
        assert exc.reason == "not initialized"
        assert exc.error_code == KernelErrorCode.KERNEL_NOT_READY

    def test_factory_distributed_lock_timeout(self):
        exc = KernelExceptionFactory.distributed_lock_timeout("lockA", 3.5)
        assert isinstance(exc, DistributedLockTimeoutError)
        assert exc.lock_key == "lockA"
        assert exc.timeout_seconds == 3.5
        assert exc.error_code == KernelErrorCode.DISTRIBUTED_LOCK_TIMEOUT

    def test_factory_dependency_not_found(self):
        exc = KernelExceptionFactory.dependency_not_found("ISomeService")
        assert isinstance(exc, DependencyNotFoundError)
        assert exc.interface_name == "ISomeService"
        assert exc.error_code == KernelErrorCode.DEPENDENCY_NOT_FOUND


# -----------------------------------------------------------------------------
# Additional edge cases for KernelError and subclasses
# -----------------------------------------------------------------------------

class TestKernelErrorAdditional:
    def test_default_severity(self):
        # When not provided, should default to MEDIUM
        exc = KernelError(
            message="test", error_code=KernelErrorCode.GATE_NOT_INITIALIZED
        )
        assert exc.severity == KernelSeverity.MEDIUM

    def test_default_component_none(self):
        exc = KernelError(
            message="test", error_code=KernelErrorCode.GATE_NOT_INITIALIZED
        )
        assert exc.component is None

    def test_original_message_property(self):
        exc = KernelError(
            message="Original",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED
        )
        assert exc.original_message == "Original"
        # The full message should contain the original but with prefix
        assert "Original" in str(exc)

    def test_from_dict_missing_fields_uses_defaults(self):
        # Minimal dict
        data = {
            "error_code": "GATE_NOT_INITIALIZED",
            "severity": "CRITICAL",
            "message": "test"
        }
        exc = KernelError.from_dict(data)
        assert exc.error_code == KernelErrorCode.GATE_NOT_INITIALIZED
        assert exc.severity == KernelSeverity.CRITICAL
        assert exc.original_message == "test"
        assert exc.component is None
        assert exc.details == {}
        assert exc.cause is None
        # exception_id will be generated
        assert exc._exception_id is not None
        # timestamp will be now (mocked)
        assert exc._timestamp == FIXED_NOW
        assert exc._version == 1

    def test_clone_preserves_cause(self):
        cause = ValueError("root cause")
        exc = KernelError(
            message="test",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED,
            cause=cause
        )
        cloned = exc.clone()
        assert cloned.cause is cause  # same reference

    def test_audit_trail_limit(self):
        exc = KernelError(
            message="test",
            error_code=KernelErrorCode.GATE_NOT_INITIALIZED
        )
        for i in range(150):
            exc.touch(f"user{i}")
        trail = exc.audit_trail(limit=10)
        assert len(trail) == 10
        # Should be the most recent 10
        assert trail[-1]["performed_by"] == "user149"
        assert trail[0]["performed_by"] == "user140"

    def test_to_dict_from_dict_roundtrip(self):
        exc = KernelError(
            message="Roundtrip",
            error_code=KernelErrorCode.EXECUTOR_DEADLOCK_DETECTED,
            severity=KernelSeverity.HIGH,
            component="executor",
            details={"txn": "txn1", "locks": ["a"]},
            cause=RuntimeError("cause")
        )
        d = exc.to_dict()
        restored = KernelError.from_dict(d)
        assert restored.error_code == exc.error_code
        assert restored.severity == exc.severity
        assert restored.original_message == exc.original_message
        assert restored.component == exc.component
        assert restored.details == exc.details
        # cause is not restored in from_dict (we don't reconstruct)
        assert restored.cause is None
        assert restored._exception_id == exc._exception_id
        assert restored._timestamp == exc._timestamp
        assert restored._version == exc._version


# -----------------------------------------------------------------------------
# Ensure all exceptions are in the factory and have correct error_code
# -----------------------------------------------------------------------------

class TestFactoryCompleteness:
    # Verify that factory methods produce exceptions with the correct error_code
    def test_factory_error_codes(self):
        factory_methods = [
            (KernelExceptionFactory.gate_circuit_open, ("circuit",), KernelErrorCode.GATE_CIRCUIT_OPEN),
            (KernelExceptionFactory.gate_handler_not_found, ("cmd",), KernelErrorCode.GATE_HANDLER_NOT_FOUND),
            (KernelExceptionFactory.dispatcher_queue_full, (10, 20), KernelErrorCode.DISPATCHER_QUEUE_FULL),
            (KernelExceptionFactory.transaction_failed, ("txn", "err"), KernelErrorCode.EXECUTOR_TRANSACTION_FAILED),
            (KernelExceptionFactory.deadlock_detected, ("txn", ["a"]), KernelErrorCode.EXECUTOR_DEADLOCK_DETECTED),
            (KernelExceptionFactory.validation_failed, ("stage", "reason"), KernelErrorCode.VALIDATION_PIPELINE_FAILED),
            (KernelExceptionFactory.invariant_violation, ("type", "msg"), KernelErrorCode.VALIDATION_INVARIANT_VIOLATION),
            (KernelExceptionFactory.axiom_violation, ("name", "msg"), KernelErrorCode.VALIDATION_AXIOM_VIOLATION),
            (KernelExceptionFactory.constitution_violation, ("p", "msg"), KernelErrorCode.VALIDATION_CONSTITUTION_VIOLATION),
            (KernelExceptionFactory.kernel_not_ready, ("reason",), KernelErrorCode.KERNEL_NOT_READY),
            (KernelExceptionFactory.distributed_lock_timeout, ("lock", 1.0), KernelErrorCode.DISTRIBUTED_LOCK_TIMEOUT),
            (KernelExceptionFactory.dependency_not_found, ("iface",), KernelErrorCode.DEPENDENCY_NOT_FOUND),
        ]
        for method, args, expected_code in factory_methods:
            exc = method(*args)
            assert exc.error_code == expected_code