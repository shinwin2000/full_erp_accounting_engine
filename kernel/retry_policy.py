#!/usr/bin/env python3
"""
Module: retry_policy.py
Layer: 4 - Kernel / Retry Policy
Responsibility: Kebijakan retry untuk transient failure.
               Menyediakan strategi retry yang dapat dikonfigurasi
               (exponential backoff, fixed delay, jitter) untuk menangani
               kegagalan sementara seperti deadlock, timeout, atau koneksi
               database terputus.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_statistics(), get_history(), reset()
- exponential_backoff factory function
- decorator @retry
- convenience functions retry_async, retry_sync
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# === 1. CONSTANTS & ENUMS ===
class RetryStrategy(Enum):
    FIXED = auto()
    LINEAR = auto()
    EXPONENTIAL = auto()
    EXPONENTIAL_JITTER = auto()
    CUSTOM = auto()


class RetryableError(Exception):
    """Exception yang menandakan error dapat di-retry."""

    def __init__(self, message: str, original_error: Exception | None = None):
        self.original_error = original_error
        super().__init__(message)


class NonRetryableError(Exception):
    """Exception yang menandakan error tidak dapat di-retry."""

    pass


class RetryExhaustedError(Exception):
    """Exception when max retries exceeded."""

    pass


# === 2. EXPONENTIAL BACKOFF FUNCTION ===
def exponential_backoff(
    base_delay: float = 0.5, max_delay: float = 30.0, multiplier: float = 2.0, jitter: bool = True
) -> Callable[[int], float]:
    """
    Returns a backoff function that calculates exponential delay with optional jitter.
    """

    def backoff(attempt: int) -> float:
        delay = base_delay * (multiplier ** (attempt - 1))
        delay = min(delay, max_delay)
        if jitter:
            delay = delay * random.uniform(0.8, 1.2)
        return delay

    return backoff


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseRetryPolicy(ABC):
    """
    Base contract for Retry Policy.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def is_retryable(self, exception: Exception) -> bool:
        """Check if an exception is retryable."""
        pass

    @abstractmethod
    def get_wait_time(self, retry_count: int) -> float:
        """Get the wait time for the next retry."""
        pass

    @abstractmethod
    async def execute_with_retry(
        self,
        func: Callable[[], T],
        context: dict[str, Any] | None = None,
    ) -> T:
        """Execute a function with retry logic."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about retry attempts."""
        pass


# === 3. RETRY POLICY CONFIGURATION ===
@dataclass
class RetryPolicy(BaseRetryPolicy):
    """
    Kebijakan retry.
    """

    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER
    retryable_exceptions: list[type] = field(
        default_factory=lambda: [RetryableError, TimeoutError, ConnectionError]
    )
    custom_backoff_func: Callable[[int], float] | None = None
    backoff_factor: float = 2.0

    def __post_init__(self):
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.initial_delay_seconds <= 0:
            raise ValueError("initial_delay_seconds must be positive")
        if self.max_delay_seconds <= 0:
            raise ValueError("max_delay_seconds must be positive")
        if self.strategy == RetryStrategy.CUSTOM and self.custom_backoff_func is None:
            raise ValueError("CUSTOM strategy requires custom_backoff_func")
        self._retry_count = 0
        self._current_delay = self.initial_delay_seconds
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    @property
    def base_delay(self) -> float:
        return self.initial_delay_seconds

    @property
    def max_delay(self) -> float:
        return self.max_delay_seconds

    @property
    def max_attempts(self) -> int:
        return self.max_retries

    def get_wait_time(self, retry_count: int) -> float:
        if retry_count <= 0:
            return 0.0
        if self.strategy == RetryStrategy.FIXED:
            wait = self.initial_delay_seconds
        elif self.strategy == RetryStrategy.LINEAR:
            wait = self.initial_delay_seconds * retry_count
        elif self.strategy == RetryStrategy.EXPONENTIAL:
            wait = self.initial_delay_seconds * (self.backoff_factor ** (retry_count - 1))
        elif self.strategy == RetryStrategy.EXPONENTIAL_JITTER:
            base = self.initial_delay_seconds * (self.backoff_factor ** (retry_count - 1))
            jitter = random.uniform(0, base * 0.3)
            wait = base + jitter
        elif self.strategy == RetryStrategy.CUSTOM and self.custom_backoff_func:
            wait = self.custom_backoff_func(retry_count)
        else:
            wait = self.initial_delay_seconds
        wait = min(wait, self.max_delay_seconds)
        self._current_delay = wait
        return wait

    def is_retryable(self, exception: Exception) -> bool:
        for exc_type in self.retryable_exceptions:
            if isinstance(exception, exc_type):
                return True
        return False

    async def execute(self, func: Callable[[], T]) -> T:
        self._retry_count = 0
        last_exception = None
        for attempt in range(1, self.max_retries + 2):
            try:
                return await func()
            except Exception as e:
                last_exception = e
                if not self.is_retryable(e):
                    raise
                if attempt > self.max_retries:
                    raise RetryExhaustedError(f"Max retries ({self.max_retries}) exceeded") from e
                wait_time = self.get_wait_time(attempt)
                await asyncio.sleep(wait_time)
        raise RetryExhaustedError("Max retries exceeded") from last_exception

    async def execute_with_retry(self, func: Callable[[], T]) -> T:
        return await self.execute(func)

    def reset(self) -> None:
        self._retry_count = 0
        self._current_delay = self.initial_delay_seconds
        self._version += 1
        self._record_audit("RESET", "system", {})

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.max_retries < 0:
            errors.append("max_retries cannot be negative")
        if self.initial_delay_seconds <= 0:
            errors.append("initial_delay_seconds must be positive")
        if self.max_delay_seconds <= 0:
            errors.append("max_delay_seconds must be positive")
        if self.strategy == RetryStrategy.CUSTOM and self.custom_backoff_func is None:
            errors.append("CUSTOM strategy requires custom_backoff_func")
        return {"is_valid": len(errors) == 0, "errors": errors}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryPolicy:
        strategy = RetryStrategy[data.get("strategy", "EXPONENTIAL_JITTER")]
        retryable_exceptions = []
        for exc_name in data.get("retryable_exceptions", []):
            if exc_name == "RetryableError":
                retryable_exceptions.append(RetryableError)
            elif exc_name == "TimeoutError":
                retryable_exceptions.append(TimeoutError)
            elif exc_name == "ConnectionError":
                retryable_exceptions.append(ConnectionError)
        instance = cls(
            max_retries=data.get("max_retries", 3),
            initial_delay_seconds=data.get("initial_delay_seconds", 1.0),
            max_delay_seconds=data.get("max_delay_seconds", 60.0),
            strategy=strategy,
            retryable_exceptions=retryable_exceptions
            or [RetryableError, TimeoutError, ConnectionError],
            backoff_factor=data.get("backoff_factor", 2.0),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RetryPolicy:
        new_policy = RetryPolicy(
            max_retries=self.max_retries,
            initial_delay_seconds=self.initial_delay_seconds,
            max_delay_seconds=self.max_delay_seconds,
            strategy=self.strategy,
            retryable_exceptions=self.retryable_exceptions.copy(),
            custom_backoff_func=self.custom_backoff_func,
            backoff_factor=self.backoff_factor,
        )
        new_policy._version = self._version + 1
        return new_policy

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "max_retries": self.max_retries,
            "strategy": self.strategy.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RetryPolicy:
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

    # ==================== IMPLEMENTASI get_statistics ====================
    def get_statistics(self) -> dict[str, Any]:
        """Kembalikan statistik retry untuk instance ini."""
        return {
            "retry_count": self._retry_count,
            "current_delay": self._current_delay,
            "max_retries": self.max_retries,
            "strategy": self.strategy.name,
            "version": self._version,
        }


# === 4. RETRY POLICY SERVICE ===
class RetryPolicyService:
    """
    Service untuk kebijakan retry.
    """

    _instance: RetryPolicyService | None = None
    _lock = asyncio.Lock()

    def __new__(cls) -> RetryPolicyService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._default_policy = RetryPolicy()
        self._history: list[dict[str, Any]] = []
        self._max_history = 1000
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def set_default_policy(self, policy: RetryPolicy) -> None:
        self._default_policy = policy
        self._record_audit("SET_DEFAULT_POLICY", "system", policy.to_dict())
        logger.info(
            f"Default retry policy set: {policy.strategy.name}, max_retries={policy.max_retries}"
        )

    async def execute_with_retry(
        self,
        func: Callable[[], T],
        policy: RetryPolicy | None = None,
        on_retry: Callable[[int, Exception], None] | None = None,
        context: dict[str, Any] | None = None,
    ) -> T:
        policy = policy or self._default_policy
        last_exception = None
        start_time = time.time()
        for attempt in range(policy.max_retries + 1):
            try:
                result = await func()
                self._record_attempt(
                    success=True,
                    attempt=attempt,
                    duration_ms=(time.time() - start_time) * 1000,
                    context=context,
                )
                return result
            except Exception as e:
                last_exception = e
                if not policy.is_retryable(e):
                    self._record_attempt(
                        success=False,
                        attempt=attempt,
                        error=str(e),
                        retryable=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        context=context,
                    )
                    raise NonRetryableError(f"Non-retryable error: {e}") from e
                if attempt == policy.max_retries:
                    self._record_attempt(
                        success=False,
                        attempt=attempt,
                        error=str(e),
                        retryable=True,
                        final=True,
                        duration_ms=(time.time() - start_time) * 1000,
                        context=context,
                    )
                    logger.error(f"Max retries ({policy.max_retries}) exceeded: {e}")
                    raise
                wait_time = policy.get_wait_time(attempt + 1)
                if on_retry:
                    try:
                        if asyncio.iscoroutinefunction(on_retry):
                            await on_retry(attempt + 1, e)
                        else:
                            on_retry(attempt + 1, e)
                    except Exception as cb_err:
                        logger.warning(f"on_retry callback failed: {cb_err}")
                logger.warning(
                    f"Retry {attempt + 1}/{policy.max_retries} after {wait_time:.2f}s due to: {e}"
                )
                self._record_attempt(
                    success=False,
                    attempt=attempt,
                    error=str(e),
                    retryable=True,
                    wait_time=wait_time,
                    duration_ms=(time.time() - start_time) * 1000,
                    context=context,
                )
                await asyncio.sleep(wait_time)
        raise last_exception if last_exception else RuntimeError("Unexpected retry exit")

    def execute_sync_with_retry(
        self,
        func: Callable[[], T],
        policy: RetryPolicy | None = None,
        on_retry: Callable[[int, Exception], None] | None = None,
        context: dict[str, Any] | None = None,
    ) -> T:
        policy = policy or self._default_policy
        last_exception = None
        start_time = time.time()
        for attempt in range(policy.max_retries + 1):
            try:
                result = func()
                self._record_attempt(
                    success=True,
                    attempt=attempt,
                    duration_ms=(time.time() - start_time) * 1000,
                    context=context,
                )
                return result
            except Exception as e:
                last_exception = e
                if not policy.is_retryable(e):
                    self._record_attempt(
                        success=False,
                        attempt=attempt,
                        error=str(e),
                        retryable=False,
                        duration_ms=(time.time() - start_time) * 1000,
                        context=context,
                    )
                    raise NonRetryableError(f"Non-retryable error: {e}") from e
                if attempt == policy.max_retries:
                    self._record_attempt(
                        success=False,
                        attempt=attempt,
                        error=str(e),
                        retryable=True,
                        final=True,
                        duration_ms=(time.time() - start_time) * 1000,
                        context=context,
                    )
                    logger.error(f"Max retries ({policy.max_retries}) exceeded: {e}")
                    raise
                wait_time = policy.get_wait_time(attempt + 1)
                if on_retry:
                    try:
                        on_retry(attempt + 1, e)
                    except Exception as cb_err:
                        logger.warning(f"on_retry callback failed: {cb_err}")
                logger.warning(
                    f"Retry {attempt + 1}/{policy.max_retries} after {wait_time:.2f}s: {e}"
                )
                self._record_attempt(
                    success=False,
                    attempt=attempt,
                    error=str(e),
                    retryable=True,
                    wait_time=wait_time,
                    duration_ms=(time.time() - start_time) * 1000,
                    context=context,
                )
                time.sleep(wait_time)
        raise last_exception if last_exception else RuntimeError("Unexpected retry exit")

    def _record_attempt(
        self,
        success: bool,
        attempt: int,
        error: str | None = None,
        retryable: bool = True,
        final: bool = False,
        wait_time: float = 0.0,
        duration_ms: float = 0.0,
        context: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "timestamp": time.time(),
            "success": success,
            "attempt": attempt,
            "error": error,
            "retryable": retryable,
            "final": final,
            "wait_time": wait_time,
            "duration_ms": duration_ms,
            "context": context,
        }
        self._history.append(record)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]

    def get_statistics(self) -> dict[str, Any]:
        total = len(self._history)
        if total == 0:
            return {"total_attempts": 0, "version": self._version}
        successes = len([r for r in self._history if r["success"]])
        retries = len([r for r in self._history if r["attempt"] > 0 and not r["success"]])
        avg_duration = sum(r["duration_ms"] for r in self._history) / total if total > 0 else 0
        attempts_distribution = {}
        for r in self._history:
            att = r["attempt"]
            attempts_distribution[att] = attempts_distribution.get(att, 0) + 1
        return {
            "total_attempts": total,
            "success_count": successes,
            "retry_count": retries,
            "success_rate": successes / total if total > 0 else 0,
            "avg_duration_ms": avg_duration,
            "attempts_distribution": attempts_distribution,
            "version": self._version,
        }

    def get_default_policy(self) -> RetryPolicy:
        return self._default_policy

    def get_history(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._history[-limit:]

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        res = self._default_policy.validate()
        if not res["is_valid"]:
            errors.extend([f"default_policy: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_policy": self._default_policy.to_dict(),
            "history_count": len(self._history),
            "max_history": self._max_history,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetryPolicyService:
        instance = cls()
        if "default_policy" in data:
            instance._default_policy = RetryPolicy.from_dict(data["default_policy"])
        instance._max_history = data.get("max_history", 1000)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> RetryPolicyService:
        new_instance = RetryPolicyService()
        new_instance._default_policy = self._default_policy.clone()
        new_instance._max_history = self._max_history
        new_instance._version = self._version + 1
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "history_count": len(self._history),
            "default_policy": self._default_policy.snapshot(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RetryPolicyService:
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

    def reset(self) -> None:
        self._history = []
        self._version += 1
        self._audit_trail = []
        self._snapshots = []


# === 5. SINGLETON ACCESSOR ===
_retry_policy_service_instance: RetryPolicyService | None = None


def get_retry_policy() -> RetryPolicyService:
    global _retry_policy_service_instance
    if _retry_policy_service_instance is None:
        _retry_policy_service_instance = RetryPolicyService()
    return _retry_policy_service_instance


# === 6. CONVENIENCE FUNCTIONS ===
async def retry_async(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER,
    retryable_exceptions: list[type] | None = None,
) -> T:
    policy = RetryPolicy(
        max_retries=max_retries,
        initial_delay_seconds=initial_delay,
        strategy=strategy,
        retryable_exceptions=retryable_exceptions
        or [RetryableError, TimeoutError, ConnectionError],
    )
    service = get_retry_policy()
    return await service.execute_with_retry(func, policy)


def retry_sync(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER,
    retryable_exceptions: list[type] | None = None,
) -> T:
    policy = RetryPolicy(
        max_retries=max_retries,
        initial_delay_seconds=initial_delay,
        strategy=strategy,
        retryable_exceptions=retryable_exceptions
        or [RetryableError, TimeoutError, ConnectionError],
    )
    service = get_retry_policy()
    return service.execute_sync_with_retry(func, policy)


# === 7. DECORATOR FOR RETRY ===
def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_JITTER,
    retryable_exceptions: list[type] | None = None,
):
    def decorator(func: Callable) -> Callable:
        policy = RetryPolicy(
            max_retries=max_retries,
            initial_delay_seconds=initial_delay,
            strategy=strategy,
            retryable_exceptions=retryable_exceptions
            or [RetryableError, TimeoutError, ConnectionError],
        )
        service = get_retry_policy()

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            async def wrapped():
                return await func(*args, **kwargs)

            return await service.execute_with_retry(wrapped, policy)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            def wrapped():
                return func(*args, **kwargs)

            return service.execute_sync_with_retry(wrapped, policy)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


# === 8. EXPORTS ===
__all__ = [
    "NonRetryableError",
    "RetryExhaustedError",
    "RetryPolicy",
    "RetryPolicyService",
    "RetryStrategy",
    "RetryableError",
    "exponential_backoff",
    "get_retry_policy",
    "retry",
    "retry_async",
    "retry_sync",
]