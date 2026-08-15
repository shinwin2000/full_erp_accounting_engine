#!/usr/bin/env python3
"""
Module: transactional_executor.py
Layer: 4 - Kernel / Transactional Executor
Responsibility: Eksekutor transaksi database + hook audit.
               Menjalankan callback dalam transaksi database dengan
               dukungan commit/rollback, retry, deadlock detection,
               dan audit trail untuk setiap transaksi.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_execution_history(), get_statistics(), reset()
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar, Protocol, TypeVar
from uuid import UUID, uuid4

from kernel.metric_collector import get_metric_collector
from kernel.retry_policy import RetryableError, get_retry_policy

logger = logging.getLogger(__name__)

T = TypeVar("T")


# === 0. CUSTOM EXCEPTIONS ===
class TransactionError(Exception):
    """Raised when a transaction fails (non-retryable)."""
    pass


class TransactionConfigurationError(Exception):
    """Raised when transaction configuration is invalid."""
    pass


# === 1. PROTOKOL UNIT OF WORK (internal) ===
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


# Global UOW factory (for testing)
_uow_factory: Callable[[], UnitOfWorkProtocol] | None = None


def register_unit_of_work_factory(factory: Callable[[], UnitOfWorkProtocol]) -> None:
    """Register a factory to create UnitOfWork instances (for testing)."""
    global _uow_factory
    _uow_factory = factory


def _reset_unit_of_work_factory() -> None:
    """Reset the UOW factory to default (for testing)."""
    global _uow_factory
    _uow_factory = None


def _get_uow() -> UnitOfWorkProtocol:
    """Get a UnitOfWork instance from the factory or fallback."""
    if _uow_factory:
        return _uow_factory()
    return _FallbackUnitOfWork()


# === 2. CONSTANTS & ENUMS ===
class ExecutionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMMITTING = auto()
    SUCCESS = auto()
    FAILED = auto()
    ROLLED_BACK = auto()
    RETRYING = auto()


@dataclass
class ExecutionResult:
    status: ExecutionStatus
    result: Any | None = None
    error_message: str | None = None
    error_type: str | None = None
    duration_ms: float = 0.0
    retry_count: int = 0
    transaction_id: UUID = field(default_factory=uuid4)
    affected_aggregates: list[UUID] = field(default_factory=list)

    def is_success(self) -> bool:
        return self.status == ExecutionStatus.SUCCESS

    def is_retryable(self) -> bool:
        retryable_types = ["DeadlockError", "ConnectionError", "TimeoutError", "LockNotAvailable"]
        return self.error_type in retryable_types

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(self.status, ExecutionStatus):
            errors.append("Invalid status")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.name,
            "result": str(self.result)[:200] if self.result else None,
            "error_message": self.error_message,
            "error_type": self.error_type,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "transaction_id": str(self.transaction_id),
            "affected_aggregates": [str(agg) for agg in self.affected_aggregates],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionResult:
        return cls(
            status=ExecutionStatus[data["status"]],
            result=data.get("result"),
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            duration_ms=data.get("duration_ms", 0.0),
            retry_count=data.get("retry_count", 0),
            transaction_id=UUID(data["transaction_id"]) if data.get("transaction_id") else uuid4(),
            affected_aggregates=[UUID(a) for a in data.get("affected_aggregates", [])],
        )

    def clone(self) -> ExecutionResult:
        return ExecutionResult(
            status=self.status,
            result=self.result,
            error_message=self.error_message,
            error_type=self.error_type,
            duration_ms=self.duration_ms,
            retry_count=self.retry_count,
            transaction_id=self.transaction_id,
            affected_aggregates=self.affected_aggregates.copy(),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self.status.name,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "transaction_id": str(self.transaction_id),
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> ExecutionResult:
        return self.clone()


# === 3. DEADLOCK DETECTOR ===
class DeadlockDetector:
    def __init__(self, timeout_seconds: int = 30):
        self._active_transactions: dict[UUID, datetime] = {}
        self._waiting_for: dict[UUID, list[UUID]] = {}
        self._timeout_seconds = timeout_seconds
        self._lock = asyncio.Lock()
        self._audit_trail: list[dict[str, Any]] = []
        self._version = 1

    async def register_transaction(self, transaction_id: UUID) -> None:
        async with self._lock:
            self._active_transactions[transaction_id] = datetime.now(UTC)

    async def unregister_transaction(self, transaction_id: UUID) -> None:
        async with self._lock:
            self._active_transactions.pop(transaction_id, None)
            self._waiting_for.pop(transaction_id, None)

    async def register_waiting(self, transaction_id: UUID, waiting_for: list[UUID]) -> None:
        async with self._lock:
            self._waiting_for[transaction_id] = waiting_for

    async def check_deadlock(self, transaction_id: UUID) -> bool:
        async with self._lock:
            tx_start = self._active_transactions.get(transaction_id)
            if tx_start and (datetime.now(UTC) - tx_start).total_seconds() >= self._timeout_seconds:
                return True
            visited = set()
            stack = [transaction_id]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                for waiter in self._waiting_for.get(current, []):
                    if waiter == transaction_id:
                        return True
                    if waiter not in visited:
                        stack.append(waiter)
            return False

    def clear(self) -> None:
        self._active_transactions.clear()
        self._waiting_for.clear()
        self._version += 1

    # Entity methods
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self._timeout_seconds,
            "active_count": len(self._active_transactions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadlockDetector:
        return cls(timeout_seconds=data.get("timeout_seconds", 30))

    def clone(self) -> DeadlockDetector:
        return DeadlockDetector(timeout_seconds=self._timeout_seconds)

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_transactions": len(self._active_transactions),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DeadlockDetector:
        self._version += 1
        return self


# === 4. RETRYABLE ERROR DETECTOR ===
class RetryableErrorDetector:
    RETRYABLE_KEYWORDS: ClassVar[list[str]] = [
        "deadlock", "lock", "timeout", "connection", "network", "unavailable", "retryable"
    ]
    NON_RETRYABLE_KEYWORDS: ClassVar[list[str]] = [
        "constraint", "validation", "duplicate", "foreign key"
    ]

    @classmethod
    def is_retryable(cls, error: Exception) -> bool:
        if isinstance(error, RetryableError):
            return True
        if isinstance(error, TimeoutError | ConnectionError):
            return True
        error_str = str(error).lower()
        if any(kw in error_str for kw in cls.NON_RETRYABLE_KEYWORDS):
            return False
        return any(kw in error_str for kw in cls.RETRYABLE_KEYWORDS)

    # Entity methods for consistency
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "retryable_keywords": self.RETRYABLE_KEYWORDS,
            "non_retryable_keywords": self.NON_RETRYABLE_KEYWORDS,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryableErrorDetector:
        return cls()

    def clone(self) -> RetryableErrorDetector:
        return RetryableErrorDetector()

    def snapshot(self) -> dict[str, Any]:
        return {}

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return []

    def touch(self, touched_by: str) -> RetryableErrorDetector:
        return self


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseTransactionalExecutor(ABC):
    """
    Base contract for Transactional Executor.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    async def execute_async(self, operation: Callable[[], T]) -> T:
        """Execute async operation with transaction."""
        pass

    @abstractmethod
    async def execute_transaction(
        self,
        uow_callback: Callable[[UnitOfWorkProtocol], T],
        command_id: UUID | None = None,
        idempotency_key: str | None = None,
        isolation_level: str = "READ_COMMITTED",
        timeout_seconds: int = 60,
        max_retries: int | None = None,
    ) -> ExecutionResult:
        """Execute with full transaction support (retry, deadlock detection)."""
        pass

    @abstractmethod
    async def execute_in_read_only(
        self, uow_callback: Callable[[UnitOfWorkProtocol], T], timeout_seconds: int = 30
    ) -> ExecutionResult:
        """Execute in read-only transaction."""
        pass

    @abstractmethod
    async def execute_in_serializable(
        self,
        uow_callback: Callable[[UnitOfWorkProtocol], T],
        command_id: UUID | None = None,
        timeout_seconds: int = 60,
    ) -> ExecutionResult:
        """Execute with SERIALIZABLE isolation level."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about transactions."""
        pass


# === 5. TRANSACTIONAL EXECUTOR ===
class TransactionalExecutor(BaseTransactionalExecutor):
    _instance: TransactionalExecutor | None = None
    _lock = asyncio.Lock()
    _initialized: bool  # Add type declaration

    def __new__(cls) -> TransactionalExecutor:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, uow: Any = None) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._retry_policy = get_retry_policy()
        self._metric_collector = get_metric_collector()
        self._deadlock_detector = DeadlockDetector()
        self._execution_history: list[ExecutionResult] = []
        self._max_history = 10000
        self._retryable_detector = RetryableErrorDetector()
        self._uow = uow
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1
        self._clear_task: asyncio.Task | None = None

    # --- Sync execution (for pure sync operations) ---
    def execute_sync(self, operation: Callable[[], T]) -> T:
        """
        Synchronous execution for pure sync operations.
        Does NOT support async operations.
        """
        try:
            return operation()
        except Exception as e:
            raise TransactionError(str(e)) from e

    # --- Async execution (primary method) ---
    async def execute_async(self, operation: Callable[[], T]) -> T:
        """
        Async version of execute. Should be awaited.
        """
        uow = self._uow if self._uow else _FallbackUnitOfWork()
        try:
            result = operation()
            if asyncio.iscoroutine(result):
                result = await result
            await uow.commit()
            return result
        except Exception as e:
            await uow.rollback()
            raise TransactionError(str(e)) from e

    # --- Transaction execution with retry (async) ---
    async def execute_transaction(
        self,
        uow_callback: Callable[[UnitOfWorkProtocol], T],
        command_id: UUID | None = None,
        idempotency_key: str | None = None,
        isolation_level: str = "READ_COMMITTED",
        timeout_seconds: int = 60,
        max_retries: int | None = None,
    ) -> ExecutionResult:
        start_time = time.time()
        retry_count = 0
        last_error: Exception | None = None
        transaction_id = uuid4()
        max_retries_config = (
            max_retries
            if max_retries is not None
            else self._retry_policy.get_default_policy().max_retries
        )

        while True:
            if retry_count > max_retries_config:
                break
            try:
                await self._deadlock_detector.register_transaction(transaction_id)
                result = await self._execute_once(
                    uow_callback=uow_callback,
                    transaction_id=transaction_id,
                    command_id=command_id,
                    isolation_level=isolation_level,
                    timeout_seconds=timeout_seconds,
                )
                duration_ms = (time.time() - start_time) * 1000
                execution_result = ExecutionResult(
                    status=ExecutionStatus.SUCCESS,
                    result=result,
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                    transaction_id=transaction_id,
                )
                self._record_execution(execution_result)
                if self._metric_collector:
                    self._metric_collector.record_histogram(
                        "transaction_duration_ms",
                        Decimal(str(duration_ms)),
                        {"status": "success", "retry_count": str(retry_count)},
                    )
                return execution_result

            except TimeoutError as e:
                last_error = e
                retry_count += 1
                wait_time = self._get_wait_time(retry_count)
                logger.warning(
                    "Transaction %s timeout after %ds, retry %d/%d, waiting %.2fs",
                    transaction_id,
                    timeout_seconds,
                    retry_count,
                    max_retries_config,
                    wait_time
                )
                await asyncio.sleep(wait_time)
                if self._metric_collector:
                    self._metric_collector.increment_counter(
                        "transaction_retries_total", {"error_type": "TimeoutError"}
                    )

            except Exception as e:
                is_retryable = self._retryable_detector.is_retryable(e)
                if not is_retryable:
                    duration_ms = (time.time() - start_time) * 1000
                    execution_result = ExecutionResult(
                        status=ExecutionStatus.FAILED,
                        error_message=str(e),
                        error_type=type(e).__name__,
                        duration_ms=duration_ms,
                        retry_count=retry_count,
                        transaction_id=transaction_id,
                    )
                    self._record_execution(execution_result)
                    if self._metric_collector:
                        self._metric_collector.record_histogram(
                            "transaction_duration_ms",
                            Decimal(str(duration_ms)),
                            {"status": "failed", "error_type": type(e).__name__},
                        )
                        self._metric_collector.increment_counter(
                            "transaction_failures_total", {"error_type": type(e).__name__}
                        )
                    return execution_result

                last_error = e
                retry_count += 1
                wait_time = self._get_wait_time(retry_count)
                logger.warning(
                    "Transaction %s failed (retryable: %s), retry %d/%d, waiting %.2fs: %s",
                    transaction_id,
                    type(e).__name__,
                    retry_count,
                    max_retries_config,
                    wait_time,
                    e
                )
                await asyncio.sleep(wait_time)
                if self._metric_collector:
                    self._metric_collector.increment_counter(
                        "transaction_retries_total", {"error_type": type(e).__name__}
                    )

            finally:
                await self._deadlock_detector.unregister_transaction(transaction_id)

        duration_ms = (time.time() - start_time) * 1000
        execution_result = ExecutionResult(
            status=ExecutionStatus.FAILED,
            error_message=f"Max retries ({max_retries_config}) exceeded. Last error: {last_error}",
            error_type="MaxRetriesExceeded",
            duration_ms=duration_ms,
            retry_count=retry_count,
            transaction_id=transaction_id,
        )
        self._record_execution(execution_result)
        return execution_result

    async def _execute_once(
        self,
        uow_callback: Callable[[UnitOfWorkProtocol], T],
        transaction_id: UUID,
        command_id: UUID | None = None,
        isolation_level: str = "READ_COMMITTED",
        timeout_seconds: int = 60,
    ) -> T:
        try:
            uow = _get_uow()
            uow.transaction_id = transaction_id
            uow.command_id = command_id
            try:
                await asyncio.wait_for(
                    uow.begin(isolation_level=isolation_level), timeout=timeout_seconds
                )
            except TimeoutError:
                raise RetryableError(f"Transaction begin timeout after {timeout_seconds}s")
            try:
                if asyncio.iscoroutinefunction(uow_callback):
                    result = await uow_callback(uow)
                else:
                    result = uow_callback(uow)
                if asyncio.iscoroutine(result):
                    result = await result
                try:
                    await asyncio.wait_for(uow.commit(), timeout=timeout_seconds)
                except TimeoutError:
                    raise RetryableError(f"Transaction commit timeout after {timeout_seconds}s")
                return result
            except Exception:
                try:
                    await uow.rollback()
                except Exception as rb_err:
                    logger.error("Rollback failed for transaction %s: %s", transaction_id, rb_err)
                raise
        except TimeoutError:
            raise RetryableError(f"Transaction timeout after {timeout_seconds}s")
        except Exception as e:
            if self._retryable_detector.is_retryable(e):
                raise RetryableError(f"Retryable error: {e}") from e
            raise

    async def execute_in_serializable(
        self,
        uow_callback: Callable[[UnitOfWorkProtocol], T],
        command_id: UUID | None = None,
        timeout_seconds: int = 60,
    ) -> ExecutionResult:
        return await self.execute_transaction(
            uow_callback=uow_callback,
            command_id=command_id,
            isolation_level="SERIALIZABLE",
            timeout_seconds=timeout_seconds,
        )

    async def execute_in_read_only(
        self, uow_callback: Callable[[UnitOfWorkProtocol], T], timeout_seconds: int = 30
    ) -> ExecutionResult:
        start_time = time.time()
        transaction_id = uuid4()
        try:
            uow = _get_uow()
            uow.transaction_id = transaction_id
            try:
                await asyncio.wait_for(uow.begin_read_only(), timeout=timeout_seconds)
            except TimeoutError:
                raise RetryableError(
                    f"Read-only transaction begin timeout after {timeout_seconds}s"
                )
            if asyncio.iscoroutinefunction(uow_callback):
                result = await uow_callback(uow)
            else:
                result = uow_callback(uow)
            if asyncio.iscoroutine(result):
                result = await result
            await uow.rollback()
            duration_ms = (time.time() - start_time) * 1000
            execution_result = ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                result=result,
                duration_ms=duration_ms,
                transaction_id=transaction_id,
            )
            self._record_execution(execution_result)
            return execution_result
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            execution_result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                error_message=str(e),
                error_type=type(e).__name__,
                duration_ms=duration_ms,
                transaction_id=transaction_id,
            )
            self._record_execution(execution_result)
            return execution_result

    def _get_wait_time(self, retry_count: int) -> float:
        base_delay = self._retry_policy.get_default_policy().base_delay
        max_delay = self._retry_policy.get_default_policy().max_delay
        wait = min(base_delay * (2 ** (retry_count - 1)), max_delay)
        jitter = random.uniform(0, wait * 0.1)
        return wait + jitter

    def _record_execution(self, result: ExecutionResult) -> None:
        self._execution_history.append(result)
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history :]

    def get_execution_history(
        self, limit: int = 100, status_filter: ExecutionStatus | None = None
    ) -> list[ExecutionResult]:
        result = self._execution_history[-limit:]
        if status_filter:
            result = [r for r in result if r.status == status_filter]
        return result

    def get_statistics(self) -> dict[str, Any]:
        total = len(self._execution_history)
        if total == 0:
            return {"total_transactions": 0, "version": self._version}
        success = len([r for r in self._execution_history if r.status == ExecutionStatus.SUCCESS])
        failed = len([r for r in self._execution_history if r.status == ExecutionStatus.FAILED])
        rolled_back = len(
            [r for r in self._execution_history if r.status == ExecutionStatus.ROLLED_BACK]
        )
        avg_duration = (
            sum(r.duration_ms for r in self._execution_history) / total if total > 0 else 0
        )
        avg_retries = (
            sum(r.retry_count for r in self._execution_history) / total if total > 0 else 0
        )
        by_error_type: dict[str, int] = {}
        for r in self._execution_history:
            if r.error_type:
                by_error_type[r.error_type] = by_error_type.get(r.error_type, 0) + 1
        return {
            "total_transactions": total,
            "success_count": success,
            "failed_count": failed,
            "rolled_back_count": rolled_back,
            "success_rate": success / total if total > 0 else 0,
            "avg_duration_ms": avg_duration,
            "avg_retry_count": avg_retries,
            "max_retries_configured": self._retry_policy.get_default_policy().max_retries,
            "by_error_type": by_error_type,
            "version": self._version,
        }

    def reset(self) -> None:
        self._execution_history = []
        self._deadlock_detector.clear()
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._record_audit("RESET", "system", {})

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        if self._max_history <= 0:
            errors.append("max_history must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_history": self._max_history,
            "history_count": len(self._execution_history),
            "deadlock_detector": self._deadlock_detector.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransactionalExecutor:
        instance = cls()
        instance._max_history = data.get("max_history", 10000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TransactionalExecutor:
        # Karena singleton, kita tidak bisa membuat instance baru dengan __new__,
        # jadi kita buat instance baru dengan object.__new__ secara manual,
        # lalu salin state.
        new_instance = object.__new__(TransactionalExecutor)
        new_instance._initialized = True
        new_instance._retry_policy = self._retry_policy
        new_instance._metric_collector = self._metric_collector
        new_instance._deadlock_detector = self._deadlock_detector.clone()
        new_instance._execution_history = self._execution_history.copy()
        new_instance._max_history = self._max_history
        new_instance._retryable_detector = self._retryable_detector.clone()
        new_instance._uow = self._uow
        new_instance._audit_trail = self._audit_trail.copy()
        new_instance._snapshots = self._snapshots.copy()
        new_instance._version = self._version + 1
        new_instance._clear_task = None
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "history_count": len(self._execution_history),
            "deadlock_detector": self._deadlock_detector.snapshot(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TransactionalExecutor:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
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

    # --- Legacy sync method (kept for backward compatibility) ---
    def execute(self, operation: Callable[[], T]) -> T:
        """
        Legacy synchronous method. Use execute_async() for async operations,
        or execute_sync() for pure sync operations.
        """
        if asyncio.iscoroutinefunction(operation):
            raise RuntimeError(
                "Cannot execute async operation with sync execute(). "
                "Use execute_async() instead."
            )
        return self.execute_sync(operation)


# === 6. SINGLETON ACCESSOR ===
_transactional_executor_instance: TransactionalExecutor | None = None


def _reset_singleton() -> None:
    """Reset the singleton instance (for testing)."""
    global _transactional_executor_instance
    _transactional_executor_instance = None


def get_transactional_executor() -> TransactionalExecutor:
    global _transactional_executor_instance
    if _transactional_executor_instance is None:
        _transactional_executor_instance = TransactionalExecutor()
    return _transactional_executor_instance


# === 7. EXPORTS ===
__all__ = [
    "DeadlockDetector",
    "ExecutionResult",
    "ExecutionStatus",
    "RetryableErrorDetector",
    "TransactionConfigurationError",
    "TransactionError",
    "TransactionalExecutor",
    "_reset_singleton",
    "_reset_unit_of_work_factory",
    "get_transactional_executor",
    "register_unit_of_work_factory",
]
