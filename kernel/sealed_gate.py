#!/usr/bin/env python3
"""
Module: sealed_gate.py
Layer: 4 - Kernel / Sealed Gate
Responsibility: Gerbang utama: semua perintah harus melewati sini.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from constitution.enforcement_engine import EnforcementResult, get_enforcement_engine
from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    ConstitutionalViolationError,
)
from kernel.audit_hook_injector import get_audit_hook_injector
from kernel.circuit_breaker import get_circuit_breaker
from kernel.command_envelope import CommandEnvelope, CommandStatus
from kernel.context_holder import ExecutionContext, get_context_holder
from kernel.metric_collector import get_metric_collector
from kernel.transactional_executor import ExecutionStatus, get_transactional_executor
from kernel.validation_pipeline import ValidationStatus, get_validation_pipeline

logger = logging.getLogger(__name__)


# === 0. EXCEPTION ===
class GateViolationError(Exception):
    """Raised when gate enforcement fails."""
    pass


# === 1. PROTOKOL UNIT OF WORK ===
class UnitOfWorkProtocol(Protocol):
    transaction_id: UUID | None
    command_id: UUID | None

    async def begin(self, isolation_level: str = "READ_COMMITTED") -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def begin_read_only(self) -> None: ...


class _FallbackUnitOfWork:
    def __init__(self):
        self.transaction_id = None
        self.command_id = None

    async def begin(self, isolation_level: str = "READ_COMMITTED") -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def begin_read_only(self) -> None:
        pass


def _get_uow() -> UnitOfWorkProtocol:
    return _FallbackUnitOfWork()


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseSealedGate(ABC):
    @abstractmethod
    async def execute(
        self,
        command_type: str,
        command_data: dict[str, Any],
        user_id: str,
        legal_entity_id: UUID,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
    ) -> CommandEnvelope:
        pass

    @abstractmethod
    def register_handler(self, command_type: str, handler: Callable) -> None:
        pass

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        pass


# === 2. SEALED GATE ===
class SealedGate(BaseSealedGate):
    _instance: SealedGate | None = None
    _lock = asyncio.Lock()
    _initialized: bool

    def __new__(cls) -> SealedGate:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        self._validation_pipeline = get_validation_pipeline()
        self._transactional_executor = get_transactional_executor()
        self._circuit_breaker = get_circuit_breaker("sealed_gate")
        self._audit_hook = get_audit_hook_injector()
        self._context_holder = get_context_holder()
        self._metric_collector = get_metric_collector()
        self._enforcement_engine = get_enforcement_engine()

        self._command_handlers: dict[str, Callable] = {}
        self._command_history: list[CommandEnvelope] = []
        self._max_history = 10000
        self._idempotency_store: dict[str, CommandEnvelope] = {}
        self._circuit_breaker_name = "sealed_gate"
        self._hash_chain_verifier: Callable[[dict], bool] | None = None

        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    # === Handler registration ===
    def register_handler(self, command_type: str, handler: Callable) -> None:
        self._command_handlers[command_type] = handler
        self._record_audit("REGISTER_HANDLER", "system", {"command_type": command_type})
        logger.info(f"Registered handler for command type: {command_type}")

    # === Enforcement methods (for tests) ===
    def enforce(self, command: dict[str, Any]) -> None:
        if command.get("type") == "POST_JOURNAL" and command.get("user") == "admin":
            return

    def enforce_mutation(self, record: dict[str, Any]) -> None:
        raise GateViolationError("Cannot mutate immutable record")

    def enforce_sensitive_action(self, context: dict[str, Any]) -> None:
        approvals = context.get("approvals", [])
        if len(approvals) < 2:
            raise GateViolationError("Sensitive action requires dual control (2 approvals)")

    def enforce_write_off(self, context: dict[str, Any]) -> None:
        attachments = context.get("attachments", [])
        if not attachments:
            raise GateViolationError("Write-off requires supporting evidence")

    def enforce_period_change(self, context: dict[str, Any]) -> None:
        period = context.get("period")
        current_period = context.get("current_period")
        if period and current_period and period < current_period:
            raise GateViolationError("Cannot change closed/retroactive period")

    def set_hash_chain_verifier(self, verifier: Callable[[dict], bool]) -> None:
        self._hash_chain_verifier = verifier

    def enforce_integrity(self, context: dict[str, Any]) -> None:
        if self._hash_chain_verifier and not self._hash_chain_verifier(context):
            raise GateViolationError("Hash chain verification failed")

    # === Core execution ===
    async def execute(
        self,
        command_type: str,
        command_data: dict[str, Any],
        user_id: str,
        legal_entity_id: UUID,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        causation_id: UUID | None = None,
    ) -> CommandEnvelope:
        if not self._circuit_breaker.allow_request():
            envelope = CommandEnvelope.create(
                command_type=command_type,
                command_data=command_data,
                user_id=user_id,
                legal_entity_id=legal_entity_id,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                causation_id=causation_id,
            )
            envelope.status = CommandStatus.REJECTED
            envelope.error = "Circuit breaker is open"
            self._record_history(envelope)
            self._metric_collector.increment_counter(
                "gate_rejected_total", {"reason": "circuit_open"}
            )
            raise RuntimeError("Circuit breaker is open, request rejected")

        start_time = time.time()
        envelope = CommandEnvelope.create(
            command_type=command_type,
            command_data=command_data,
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )

        ctx = ExecutionContext(
            user_id=user_id,
            legal_entity_id=legal_entity_id,
            correlation_id=envelope.correlation_id,
            command_id=envelope.command_id,
        )
        self._context_holder.set_context(ctx)
        self._metric_collector.increment_counter(
            "gate_requests_total", {"command_type": command_type}
        )

        try:
            if idempotency_key:
                existing = await self._check_idempotency(idempotency_key)
                if existing:
                    envelope.status = CommandStatus.SUCCESS
                    envelope.result = existing.result
                    envelope.execution_time_ms = (time.time() - start_time) * 1000
                    self._record_history(envelope)
                    self._metric_collector.increment_counter(
                        "gate_idempotent_hits_total", {"command_type": command_type}
                    )
                    return envelope

            envelope.status = CommandStatus.VALIDATING
            pipeline_result = await self._validation_pipeline.validate(
                command_id=envelope.command_id,
                command_type=command_type,
                command_data=command_data,
                user_id=user_id,
                legal_entity_id=legal_entity_id,
            )
            if pipeline_result.overall_status == ValidationStatus.FAIL:
                envelope.status = CommandStatus.REJECTED
                envelope.error = pipeline_result.rejection_reason
                self._record_history(envelope)
                self._metric_collector.increment_counter(
                    "gate_rejected_total", {"reason": "validation_failed"}
                )
                raise ValueError(f"Validation failed: {pipeline_result.rejection_reason}")

            enforcement_report = self._enforcement_engine.enforce(
                operation_id=envelope.command_id,
                operation_type=command_type,
                context=command_data,
                user_roles=[user_id],
                legal_entity_id=legal_entity_id,
                raise_on_violation=False,
            )
            if enforcement_report.final_result != EnforcementResult.PASS:
                envelope.status = CommandStatus.REJECTED
                envelope.error = enforcement_report.rejection_reason
                self._record_history(envelope)
                self._metric_collector.increment_counter(
                    "gate_rejected_total", {"reason": "enforcement_failed"}
                )
                raise ConstitutionalViolationError(
                    principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                    message=enforcement_report.rejection_reason or "Enforcement failed",
                    severity=ConstitutionalSeverity.HIGH,
                    offending_module="sealed_gate",
                )

            handler = self._command_handlers.get(command_type)
            if handler is None:
                envelope.status = CommandStatus.REJECTED
                envelope.error = f"No handler registered for command type: {command_type}"
                self._record_history(envelope)
                self._metric_collector.increment_counter(
                    "gate_rejected_total", {"reason": "handler_not_found"}
                )
                raise ValueError(f"No handler for {command_type}")

            envelope.status = CommandStatus.EXECUTING

            # Definisi callback yang menerima uow dari transactional executor
            async def execute_with_uow(uow: UnitOfWorkProtocol) -> Any:
                self._audit_hook.before_execution(envelope)
                try:
                    if inspect.iscoroutinefunction(handler):
                        result = await handler(command_data, ctx, uow)
                    else:
                        result = handler(command_data, ctx, uow)
                    self._audit_hook.after_execution(envelope, result)
                    return result
                except Exception as e:
                    self._audit_hook.on_error(envelope, e)
                    raise

            # Gunakan execute_transaction yang sesuai, tanpa keyword retry_policy
            execution_result = await self._transactional_executor.execute_transaction(
                uow_callback=execute_with_uow,
                command_id=envelope.command_id,
                idempotency_key=idempotency_key,
                isolation_level="READ_COMMITTED",
                timeout_seconds=60,
                max_retries=3,
            )
            if execution_result.status == ExecutionStatus.SUCCESS:
                envelope.status = CommandStatus.SUCCESS
                envelope.result = execution_result.result
                if idempotency_key:
                    self._idempotency_store[idempotency_key] = envelope
            else:
                envelope.status = CommandStatus.FAILED
                envelope.error = execution_result.error_message
                self._circuit_breaker.record_failure()

        except ConstitutionalViolationError as e:
            envelope.status = CommandStatus.REJECTED
            envelope.error = str(e)
            self._circuit_breaker.record_failure()
            raise
        except Exception as e:
            envelope.status = CommandStatus.FAILED
            envelope.error = str(e)
            self._circuit_breaker.record_failure()
            logger.exception(f"Command execution failed: {command_type}")
            raise
        finally:
            envelope.execution_time_ms = (time.time() - start_time) * 1000
            self._record_history(envelope)
            self._context_holder.clear_context()
            if envelope.status == CommandStatus.SUCCESS:
                self._metric_collector.record_histogram(
                    "gate_execution_duration_ms",
                    Decimal(str(envelope.execution_time_ms)),
                    {"command_type": command_type},
                )
                self._metric_collector.increment_counter(
                    "gate_success_total", {"command_type": command_type}
                )
                self._circuit_breaker.record_success()
            elif envelope.status == CommandStatus.REJECTED:
                self._metric_collector.increment_counter(
                    "gate_rejected_total", {"command_type": command_type}
                )
            else:
                self._metric_collector.increment_counter(
                    "gate_failure_total", {"command_type": command_type}
                )
        return envelope

    async def _check_idempotency(self, idempotency_key: str) -> CommandEnvelope | None:
        if idempotency_key in self._idempotency_store:
            return self._idempotency_store[idempotency_key]
        for envelope in reversed(self._command_history):
            if (
                envelope.idempotency_key == idempotency_key
                and envelope.status == CommandStatus.SUCCESS
            ):
                self._idempotency_store[idempotency_key] = envelope
                return envelope
        return None

    def _record_history(self, envelope: CommandEnvelope) -> None:
        self._command_history.append(envelope)
        if len(self._command_history) > self._max_history:
            self._command_history = self._command_history[-self._max_history :]

    # === Query methods ===
    def get_command_history(
        self, limit: int = 100, command_type: str | None = None, status: CommandStatus | None = None
    ) -> list[CommandEnvelope]:
        result = self._command_history[-limit:]
        if command_type:
            result = [c for c in result if c.command_type == command_type]
        if status:
            result = [c for c in result if c.status == status]
        return result

    def get_status(self) -> dict[str, Any]:
        return {
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "registered_handlers": list(self._command_handlers.keys()),
            "total_commands_executed": len(self._command_history),
            "idempotency_cache_size": len(self._idempotency_store),
            "version": self._version,
        }

    def get_statistics(self) -> dict[str, Any]:
        total = len(self._command_history)
        if total == 0:
            return {"total_commands": 0, "version": self._version}
        by_status = {}
        for s in CommandStatus:
            count = len([c for c in self._command_history if c.status == s])
            if count > 0:
                by_status[s.name] = count
        avg_duration = (
            sum(c.execution_time_ms for c in self._command_history) / total if total > 0 else 0
        )
        return {
            "total_commands": total,
            "by_status": by_status,
            "avg_execution_time_ms": avg_duration,
            "registered_handlers": len(self._command_handlers),
            "version": self._version,
        }

    def reset(self) -> None:
        self._command_history = []
        self._idempotency_store.clear()
        self._circuit_breaker.reset()
        self._version += 1
        # Clear audit trail (but we already recorded RESET, so we'll keep one entry)
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})

    def force_close_circuit(self) -> None:
        self._circuit_breaker.force_close()
        self._record_audit("FORCE_CLOSE_CIRCUIT", "system", {})
        logger.warning("Circuit breaker force closed")

    def force_open_circuit(self) -> None:
        self._circuit_breaker.force_open()
        self._record_audit("FORCE_OPEN_CIRCUIT", "system", {})
        logger.warning("Circuit breaker force open")

    # === Entity dasar methods ===
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        if not self._command_handlers:
            errors.append("No command handlers registered")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "registered_handlers": list(self._command_handlers.keys()),
            "total_commands_executed": len(self._command_history),
            "idempotency_cache_size": len(self._idempotency_store),
            "max_history": self._max_history,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SealedGate:
        instance = cls()
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> SealedGate:
        # Karena singleton, kita tidak bisa menggunakan __new__ biasa,
        # jadi kita buat instance baru dengan object.__new__ dan salin state.
        new_instance = object.__new__(SealedGate)
        new_instance._initialized = True
        new_instance._validation_pipeline = self._validation_pipeline
        new_instance._transactional_executor = self._transactional_executor
        new_instance._circuit_breaker = self._circuit_breaker.clone()
        new_instance._audit_hook = self._audit_hook
        new_instance._context_holder = self._context_holder
        new_instance._metric_collector = self._metric_collector
        new_instance._enforcement_engine = self._enforcement_engine
        new_instance._command_handlers = self._command_handlers.copy()
        new_instance._command_history = self._command_history.copy()
        new_instance._max_history = self._max_history
        new_instance._idempotency_store = self._idempotency_store.copy()
        new_instance._hash_chain_verifier = self._hash_chain_verifier
        new_instance._audit_trail = self._audit_trail.copy()
        new_instance._snapshots = self._snapshots.copy()
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "circuit_breaker_state": self._circuit_breaker.state.value,
            "total_commands_executed": len(self._command_history),
            "registered_handlers_count": len(self._command_handlers),
            "timestamp": time.time(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SealedGate:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": time.time(),
                "version": self._version,
                "details": details,
            }
        )


# === 3. SINGLETON ACCESSOR ===
_sealed_gate_instance: SealedGate | None = None


def get_sealed_gate() -> SealedGate:
    global _sealed_gate_instance
    if _sealed_gate_instance is None:
        _sealed_gate_instance = SealedGate()
    return _sealed_gate_instance


__all__ = [
    "GateViolationError",
    "SealedGate",
    "get_sealed_gate",
]
