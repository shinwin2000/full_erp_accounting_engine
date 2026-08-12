#!/usr/bin/env python3
"""
Module: circuit_breaker.py
Layer: 4 - Kernel / Circuit Breaker
Responsibility: Circuit breaker: mencegah eskalasi kegagalan beruntun.
               Melindungi sistem dari cascading failures dengan memutus
               aliran request ke komponen yang sedang bermasalah. Mendukung
               three-state model (CLOSED, OPEN, HALF_OPEN) dan auto-recovery.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_state_info(), get_metrics(), get_state_history(), force_close(), force_open(), reset()
- get_failure_rate(), get_statistics()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# === 1. FALLBACK METRIC COLLECTOR ===
class _FallbackMetricCollector:
    """Fallback metric collector when real collector is unavailable."""

    def increment_counter(
        self, name: str, tags: dict[str, str] | None = None, value: int = 1
    ) -> None:
        logger.debug(f"[METRIC] counter {name}: +{value}")

    def set_gauge(self, name: str, metric_value: Decimal, tags: dict[str, str] | None = None) -> None:
        """Set gauge metric (non-monetary, e.g., counts, time)."""
        logger.debug(f"[METRIC] gauge {name}: {metric_value}")

    def record_histogram(
        self, name: str, metric_value: Decimal, tags: dict[str, str] | None = None
    ) -> None:
        """Record histogram metric (non-monetary)."""
        logger.debug(f"[METRIC] histogram {name}: {metric_value}")


def _get_metric_collector():
    try:
        from kernel.metric_collector import get_metric_collector
        return get_metric_collector()
    except ImportError:
        return _FallbackMetricCollector()


# === 2. CONSTANTS & ENUMS ===
class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


CircuitBreakerState = CircuitState


class CircuitBreakerError(Exception):
    pass


class CircuitOpenError(CircuitBreakerError):
    pass


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    success_threshold: int = 2
    timeout_seconds: float = 60.0
    half_open_max_calls: int = 1
    record_failure_timeout_seconds: float = 120.0

    def __post_init__(self):
        if self.failure_threshold <= 0:
            raise ValueError("failure_threshold must be positive")
        if self.success_threshold <= 0:
            raise ValueError("success_threshold must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.half_open_max_calls <= 0:
            raise ValueError("half_open_max_calls must be positive")


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseCircuitBreaker(ABC):
    """
    Base contract for Circuit Breaker.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def allow_request(self) -> bool:
        """Check if request is allowed through the circuit."""
        pass

    @abstractmethod
    def record_success(self) -> None:
        """Record a successful execution."""
        pass

    @abstractmethod
    def record_failure(self) -> None:
        """Record a failed execution."""
        pass

    @abstractmethod
    def get_state_info(self) -> dict[str, Any]:
        """Get current state information."""
        pass

    @abstractmethod
    def get_metrics(self) -> dict[str, Any]:
        """Get metrics data."""
        pass

    @abstractmethod
    def force_close(self) -> None:
        """Force circuit to closed state."""
        pass

    @abstractmethod
    def force_open(self) -> None:
        """Force circuit to open state."""
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset circuit to initial state."""
        pass


# === 3. CIRCUIT BREAKER ===
class CircuitBreaker(BaseCircuitBreaker):
    """
    Circuit breaker with three-state model (CLOSED, OPEN, HALF_OPEN).
    Tracks failures and successes, transitions states automatically.
    """

    __slots__ = (
        "_audit_trail",
        "_creation_time",
        "_failure_count",
        "_failure_timestamps",
        "_half_open_calls",
        "_last_failure_time",
        "_lock",
        "_max_history",
        "_metric_collector",
        "_open_time",
        "_snapshots",
        "_state",
        "_state_history",
        "_success_count",
        "_version",
        "config",
        "name",
    )

    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
        half_open_max_calls: int | None = None,
        config: CircuitBreakerConfig | None = None,
        metric_collector=None,
    ):
        self.name = name
        if config is None:
            ft = failure_threshold if failure_threshold is not None else 5
            rt = recovery_timeout if recovery_timeout is not None else 60.0
            homc = half_open_max_calls if half_open_max_calls is not None else 1
            self.config = CircuitBreakerConfig(
                failure_threshold=ft,
                timeout_seconds=rt,
                half_open_max_calls=homc,
                success_threshold=2,
                record_failure_timeout_seconds=120.0,
            )
        else:
            self.config = config
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._open_time: float | None = None
        self._half_open_calls = 0
        self._lock = threading.RLock()
        self._metric_collector = metric_collector or _get_metric_collector()
        self._state_history: list[dict[str, Any]] = []
        self._max_history = 100
        self._failure_timestamps: list[float] = []
        self._creation_time = time.time()
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._state

    @property
    def failure_count(self) -> int:
        with self._lock:
            return self._failure_count

    @property
    def success_count(self) -> int:
        with self._lock:
            return self._success_count

    def allow_request(self) -> bool:
        with self._lock:
            self._update_state()
            if self._state == CircuitState.CLOSED:
                return True
            elif self._state == CircuitState.OPEN:
                return False
            else:  # HALF_OPEN
                if self._half_open_calls < self.config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

    def record_success(self) -> None:
        with self._lock:
            self._update_state()
            self._metric_collector.increment_counter(
                f"circuit_breaker_{self.name}_success_total", {"state": self._state.value}
            )
            if self._state == CircuitState.CLOSED:
                self._failure_count = 0
                self._failure_timestamps.clear()
                self._success_count += 1
                if self._success_count > 100:
                    self._success_count = 100
            elif self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                self._half_open_calls = max(0, self._half_open_calls - 1)
                if self._success_count >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
                    self._failure_count = 0
                    self._success_count = 0
                    self._failure_timestamps.clear()

    def record_failure(self) -> None:
        with self._lock:
            self._update_state()
            now = time.time()
            self._last_failure_time = now
            self._failure_timestamps.append(now)
            window_start = now - self.config.record_failure_timeout_seconds
            self._failure_timestamps = [ts for ts in self._failure_timestamps if ts >= window_start]
            self._metric_collector.increment_counter(
                f"circuit_breaker_{self.name}_failure_total", {"state": self._state.value}
            )
            if self._state == CircuitState.CLOSED:
                self._failure_count = len(self._failure_timestamps)
                if self._failure_count >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
                    self._open_time = now
            elif self._state == CircuitState.HALF_OPEN:
                self._half_open_calls = max(0, self._half_open_calls - 1)
                self._transition_to(CircuitState.OPEN)
                self._open_time = now
                self._failure_count = 0
                self._failure_timestamps.clear()

    def _update_state(self) -> None:
        # Gabungkan dua kondisi sesuai saran SIM102
        if (
            self._state == CircuitState.OPEN
            and self._open_time is not None
            and (time.time() - self._open_time) >= self.config.timeout_seconds
        ):
            self._transition_to(CircuitState.HALF_OPEN)
            self._success_count = 0
            self._half_open_calls = 0

    def _transition_to(self, new_state: CircuitState) -> None:
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        self._state_history.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "from_state": old_state.value,
                "to_state": new_state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "half_open_calls": self._half_open_calls,
            }
        )
        if len(self._state_history) > self._max_history:
            self._state_history = self._state_history[-self._max_history :]
        self._metric_collector.set_gauge(
            f"circuit_breaker_{self.name}_state",
            self._state_to_gauge(new_state),
            {"state": new_state.value},
        )
        logger.warning(
            f"Circuit breaker '{self.name}' transitioned: {old_state.value} -> {new_state.value}"
        )

    def _state_to_gauge(self, state: CircuitState) -> Decimal:
        mapping = {
            CircuitState.CLOSED: Decimal("0.0"),
            CircuitState.HALF_OPEN: Decimal("0.5"),
            CircuitState.OPEN: Decimal("1.0"),
        }
        return mapping.get(state, Decimal("0.0"))

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        """Execute an async function with circuit breaker protection."""
        if not self.allow_request():
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is open")
        try:
            result = await func()
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def get_metrics(self) -> dict[str, Any]:
        info = self.get_state_info()
        return {
            "name": info["name"],
            "state": info["state"],
            "failure_count": info["failure_count"],
            "success_count": info["success_count"],
            "failure_threshold": info["failure_threshold"],
            "success_threshold": info["success_threshold"],
            "timeout_seconds": info["timeout_seconds"],
            "half_open_max_calls": info["half_open_max_calls"],
            "record_failure_window_seconds": info["record_failure_window_seconds"],
            "last_failure_time": info["last_failure_time"],
            "open_time": info["open_time"],
        }

    def get_state_info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "failure_threshold": self.config.failure_threshold,
                "success_threshold": self.config.success_threshold,
                "timeout_seconds": self.config.timeout_seconds,
                "half_open_max_calls": self.config.half_open_max_calls,
                "record_failure_window_seconds": self.config.record_failure_timeout_seconds,
                "last_failure_time": self._last_failure_time,
                "open_time": self._open_time,
                "half_open_calls": self._half_open_calls,
                "creation_time": self._creation_time,
                "uptime_seconds": time.time() - self._creation_time,
            }

    def get_state_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return self._state_history[-limit:]

    def force_close(self) -> None:
        with self._lock:
            self._transition_to(CircuitState.CLOSED)
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._failure_timestamps.clear()
            logger.warning(f"Circuit breaker '{self.name}' force closed")

    def force_open(self) -> None:
        with self._lock:
            self._transition_to(CircuitState.OPEN)
            self._open_time = time.time()
            logger.warning(f"Circuit breaker '{self.name}' force open")

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None
            self._open_time = None
            self._half_open_calls = 0
            self._failure_timestamps.clear()
            self._state_history.clear()
            self._version += 1
            logger.info(f"Circuit breaker '{self.name}' reset")

    def get_failure_rate(self) -> float:
        with self._lock:
            now = time.time()
            window_start = now - self.config.record_failure_timeout_seconds
            recent_failures = len([ts for ts in self._failure_timestamps if ts >= window_start])
            total_requests = self._success_count + recent_failures
            if total_requests == 0:
                return 0.0
            return recent_failures / total_requests

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.config.failure_threshold <= 0:
            errors.append("Invalid failure_threshold")
        if self.config.timeout_seconds <= 0:
            errors.append("Invalid timeout_seconds")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "failure_threshold": self.config.failure_threshold,
            "success_threshold": self.config.success_threshold,
            "timeout_seconds": self.config.timeout_seconds,
            "half_open_max_calls": self.config.half_open_max_calls,
            "record_failure_window_seconds": self.config.record_failure_timeout_seconds,
            "last_failure_time": self._last_failure_time,
            "open_time": self._open_time,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircuitBreaker:
        config = CircuitBreakerConfig(
            failure_threshold=data.get("failure_threshold", 5),
            success_threshold=data.get("success_threshold", 2),
            timeout_seconds=data.get("timeout_seconds", 60.0),
            half_open_max_calls=data.get("half_open_max_calls", 1),
            record_failure_timeout_seconds=data.get("record_failure_window_seconds", 120.0),
        )
        cb = cls(name=data["name"], config=config)
        cb._state = CircuitState(data["state"])
        cb._failure_count = data.get("failure_count", 0)
        cb._success_count = data.get("success_count", 0)
        cb._last_failure_time = data.get("last_failure_time")
        cb._open_time = data.get("open_time")
        cb._version = data.get("version", 1)
        return cb

    def clone(self) -> CircuitBreaker:
        new_cb = CircuitBreaker(name=f"{self.name}_clone", config=self.config)
        new_cb._version = self._version + 1
        return new_cb

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CircuitBreaker:
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

    # ==================== ASYNC CONTEXT MANAGER ====================
    async def __aenter__(self):
        if not self.allow_request():
            raise CircuitOpenError(f"Circuit breaker '{self.name}' is open")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()
        return False


# === 4. CIRCUIT BREAKER REGISTRY ===
class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    _instance: CircuitBreakerRegistry | None = None
    _lock = threading.Lock()
    __slots__ = ("_audit_trail", "_breakers", "_initialized", "_registry_lock", "_version")
    _initialized: bool  # type declaration

    def __new__(cls) -> CircuitBreakerRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._breakers: dict[str, CircuitBreaker] = {}
        self._registry_lock = threading.RLock()
        self._audit_trail: list[dict[str, Any]] = []
        self._version = 1

    def get_or_create(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        with self._registry_lock:
            if name not in self._breakers:
                self._breakers[name] = CircuitBreaker(name, config=config)
            return self._breakers[name]

    def get(self, name: str) -> CircuitBreaker | None:
        with self._registry_lock:
            return self._breakers.get(name)

    def record_success(self, name: str) -> None:
        cb = self.get(name)
        if cb:
            cb.record_success()

    def record_failure(self, name: str) -> None:
        cb = self.get(name)
        if cb:
            cb.record_failure()

    def allow_request(self, name: str) -> bool:
        cb = self.get(name)
        return cb.allow_request() if cb else True

    def get_all_states(self) -> dict[str, dict[str, Any]]:
        with self._registry_lock:
            return {name: cb.get_state_info() for name, cb in self._breakers.items()}

    def force_close(self, name: str) -> bool:
        cb = self.get(name)
        if cb:
            cb.force_close()
            return True
        return False

    def force_open(self, name: str) -> bool:
        cb = self.get(name)
        if cb:
            cb.force_open()
            return True
        return False

    def remove(self, name: str) -> bool:
        with self._registry_lock:
            if name in self._breakers:
                del self._breakers[name]
                return True
            return False

    def reset_all(self) -> None:
        with self._registry_lock:
            for cb in self._breakers.values():
                cb.reset()
            self._breakers.clear()
            self._version += 1

    def get_statistics(self) -> dict[str, Any]:
        with self._registry_lock:
            total = len(self._breakers)
            open_count = 0
            half_open_count = 0
            closed_count = 0
            for cb in self._breakers.values():
                state = cb.state
                if state == CircuitState.OPEN:
                    open_count += 1
                elif state == CircuitState.HALF_OPEN:
                    half_open_count += 1
                else:
                    closed_count += 1
            return {
                "total_circuit_breakers": total,
                "open_count": open_count,
                "half_open_count": half_open_count,
                "closed_count": closed_count,
                "circuit_breakers": list(self._breakers.keys()),
            }

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        for name, cb in self._breakers.items():
            res = cb.validate()
            if not res["is_valid"]:
                errors.extend([f"{name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "breakers": {name: cb.to_dict() for name, cb in self._breakers.items()},
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CircuitBreakerRegistry:
        registry = cls()
        for name, cb_data in data.get("breakers", {}).items():
            registry._breakers[name] = CircuitBreaker.from_dict(cb_data)
        registry._version = data.get("version", 1)
        return registry

    def clone(self) -> CircuitBreakerRegistry:
        new_reg = CircuitBreakerRegistry()
        new_reg._breakers = {name: cb.clone() for name, cb in self._breakers.items()}
        new_reg._version = self._version + 1
        return new_reg

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "total_breakers": len(self._breakers),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CircuitBreakerRegistry:
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


# === 5. SINGLETON ACCESSORS ===
_circuit_breaker_registry_instance: CircuitBreakerRegistry | None = None


def get_circuit_breaker_registry() -> CircuitBreakerRegistry:
    global _circuit_breaker_registry_instance
    if _circuit_breaker_registry_instance is None:
        _circuit_breaker_registry_instance = CircuitBreakerRegistry()
    return _circuit_breaker_registry_instance


def get_circuit_breaker(name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
    registry = get_circuit_breaker_registry()
    return registry.get_or_create(name, config)


# === 6. DECORATOR ===
def with_circuit_breaker(name: str, fallback_value: T | None = None):
    def decorator(func: Callable) -> Callable:
        async def async_wrapper(*args, **kwargs):
            cb = get_circuit_breaker(name)
            if not cb.allow_request():
                if fallback_value is not None:
                    logger.warning(f"Circuit breaker '{name}' is open, using fallback value")
                    return fallback_value
                raise CircuitOpenError(f"Circuit breaker '{name}' is open")
            try:
                result = await func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception:
                cb.record_failure()
                raise

        def sync_wrapper(*args, **kwargs):
            cb = get_circuit_breaker(name)
            if not cb.allow_request():
                if fallback_value is not None:
                    logger.warning(f"Circuit breaker '{name}' is open, using fallback value")
                    return fallback_value
                raise CircuitOpenError(f"Circuit breaker '{name}' is open")
            try:
                result = func(*args, **kwargs)
                cb.record_success()
                return result
            except Exception:
                cb.record_failure()
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerError",
    "CircuitBreakerRegistry",
    "CircuitBreakerState",
    "CircuitOpenError",
    "CircuitState",
    "get_circuit_breaker",
    "get_circuit_breaker_registry",
    "with_circuit_breaker",
]
