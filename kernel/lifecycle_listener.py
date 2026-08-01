#!/usr/bin/env python3
"""
Module: lifecycle_listener.py
Layer: 4 - Kernel / Lifecycle Listener
Responsibility: Mendengarkan event lifecycle aplikasi (start, stop, health change).
               Menyediakan mekanisme untuk mendaftarkan callback yang dipanggil
               pada fase-fase tertentu dari siklus hidup aplikasi, seperti
               sebelum shutdown, sesudah startup, saat config reload, dll.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- get_current_phase(), is_running(), is_healthy(), get_event_history(), get_callbacks()
- register_signal_handlers(), wait_for_shutdown(), shutdown(), set_shutdown_timeout()
- get_statistics(), reset()
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===
class LifecycleEventType(Enum):
    STARTING = auto()
    STARTED = auto()
    HEALTHY = auto()
    DEGRADED = auto()
    UNHEALTHY = auto()
    CONFIG_RELOAD_START = auto()
    CONFIG_RELOAD_END = auto()
    SHUTTING_DOWN = auto()
    SHUTDOWN = auto()
    SIGNAL_RECEIVED = auto()


class LifecyclePhase(Enum):
    INITIAL = auto()
    STARTING = auto()
    RUNNING = auto()
    DEGRADED = auto()
    STOPPING = auto()
    STOPPED = auto()


@dataclass
class LifecycleEvent:
    event_type: LifecycleEventType
    timestamp: datetime
    source: str
    details: dict[str, Any] = field(default_factory=dict)

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.event_type, LifecycleEventType):
            errors.append("Invalid event_type")
        if not self.source:
            errors.append("source is required")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleEvent:
        return cls(
            event_type=LifecycleEventType[data["event_type"]],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            source=data["source"],
            details=data.get("details", {}),
        )

    def clone(self) -> LifecycleEvent:
        return LifecycleEvent(
            event_type=self.event_type,
            timestamp=self.timestamp,
            source=self.source,
            details=self.details.copy(),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.name,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> LifecycleEvent:
        new = self.clone()
        new.timestamp = datetime.now(UTC)
        return new


@dataclass
class LifecycleCallback:
    event_type: LifecycleEventType
    callback: Callable[[LifecycleEvent], Any]
    priority: int = 0
    name: str = ""
    async_callback: Callable[[LifecycleEvent], Any] | None = None
    _is_async: bool = False

    def __post_init__(self):
        if self.async_callback is not None:
            self._is_async = True
        elif asyncio.iscoroutinefunction(self.callback):
            self._is_async = True
            self.async_callback = self.callback

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.event_type, LifecycleEventType):
            errors.append("Invalid event_type")
        if not callable(self.callback):
            errors.append("callback is not callable")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.name,
            "priority": self.priority,
            "name": self.name,
            "is_async": self._is_async,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleCallback:
        # Note: callback cannot be reconstructed from dict
        return cls(
            event_type=LifecycleEventType[data["event_type"]],
            callback=lambda e: None,  # placeholder
            priority=data.get("priority", 0),
            name=data.get("name", ""),
        )

    def clone(self) -> LifecycleCallback:
        return LifecycleCallback(
            event_type=self.event_type,
            callback=self.callback,
            priority=self.priority,
            name=self.name,
            async_callback=self.async_callback,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.name,
            "priority": self.priority,
            "name": self.name,
            "is_async": self._is_async,
        }

    def version(self) -> int:
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.to_dict()]

    def touch(self, touched_by: str) -> LifecycleCallback:
        return self.clone()


# ============================================================================
# BASE CLASS ABSTRAK (CONTRACT)
# ============================================================================
class BaseLifecycleListener(ABC):
    """
    Base contract for Lifecycle Listener.
    Semua method yang wajib diimplementasikan oleh subclass.
    """

    @abstractmethod
    def register(
        self,
        event_type: LifecycleEventType,
        callback: Callable[[LifecycleEvent], Any],
        priority: int = 0,
        name: str = "",
        async_callback: Callable[[LifecycleEvent], Any] | None = None,
    ) -> None:
        """Register a callback for a lifecycle event."""
        pass

    @abstractmethod
    async def emit(
        self,
        event_type: LifecycleEventType,
        source: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit a lifecycle event (async)."""
        pass

    @abstractmethod
    def emit_sync(
        self,
        event_type: LifecycleEventType,
        source: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit a lifecycle event (sync)."""
        pass

    @abstractmethod
    def get_current_phase(self) -> LifecyclePhase:
        """Get the current lifecycle phase."""
        pass

    @abstractmethod
    def is_running(self) -> bool:
        """Check if kernel is running."""
        pass

    @abstractmethod
    def is_healthy(self) -> bool:
        """Check if kernel is healthy."""
        pass

    @abstractmethod
    async def shutdown(self, timeout: float | None = None) -> None:
        """Trigger graceful shutdown."""
        pass

    @abstractmethod
    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about lifecycle events."""
        pass


# === 2. LIFECYCLE LISTENER ===
class LifecycleListener(BaseLifecycleListener):
    _instance: LifecycleListener | None = None
    _lock = threading.Lock()

    def __new__(cls) -> LifecycleListener:
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
        self._callbacks: dict[LifecycleEventType, list[LifecycleCallback]] = {}
        self._event_history: list[LifecycleEvent] = []
        self._current_phase: LifecyclePhase = LifecyclePhase.INITIAL
        self._max_history = 1000
        self._signal_handlers_registered = False
        self._shutdown_timeout = 30.0
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._version = 1

    def register(
        self,
        event_type: LifecycleEventType,
        callback: Callable[[LifecycleEvent], Any],
        priority: int = 0,
        name: str = "",
        async_callback: Callable[[LifecycleEvent], Any] | None = None,
    ) -> None:
        cb = LifecycleCallback(
            event_type=event_type,
            callback=callback,
            priority=priority,
            name=name or callback.__name__,
            async_callback=async_callback,
        )
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(cb)
        self._callbacks[event_type].sort(key=lambda x: x.priority, reverse=True)
        self._record_audit("REGISTER", "system", {"event_type": event_type.name, "name": cb.name})
        logger.debug(f"Registered lifecycle callback for {event_type.name}: {cb.name}")

    def register_startup_callback(
        self, callback: Callable, priority: int = 0, name: str = ""
    ) -> None:
        self.register(LifecycleEventType.STARTING, callback, priority, name)

    def register_started_callback(
        self, callback: Callable, priority: int = 0, name: str = ""
    ) -> None:
        self.register(LifecycleEventType.STARTED, callback, priority, name)

    def register_shutdown_callback(
        self, callback: Callable, priority: int = 0, name: str = ""
    ) -> None:
        self.register(LifecycleEventType.SHUTTING_DOWN, callback, priority, name)

    def register_health_callback(
        self, callback: Callable, priority: int = 0, name: str = ""
    ) -> None:
        for event_type in [
            LifecycleEventType.HEALTHY,
            LifecycleEventType.DEGRADED,
            LifecycleEventType.UNHEALTHY,
        ]:
            self.register(event_type, callback, priority, name)

    async def emit(
        self, event_type: LifecycleEventType, source: str = "system", details: dict[str, Any] | None = None
    ) -> None:
        event = LifecycleEvent(
            event_type=event_type,
            timestamp=datetime.now(UTC),
            source=source,
            details=details or {},
        )
        # Update current phase
        if event_type == LifecycleEventType.STARTING:
            self._current_phase = LifecyclePhase.STARTING
        elif event_type == LifecycleEventType.STARTED:
            self._current_phase = LifecyclePhase.RUNNING
        elif event_type == LifecycleEventType.DEGRADED:
            self._current_phase = LifecyclePhase.DEGRADED
        elif event_type == LifecycleEventType.SHUTTING_DOWN:
            self._current_phase = LifecyclePhase.STOPPING
        elif event_type == LifecycleEventType.SHUTDOWN:
            self._current_phase = LifecyclePhase.STOPPED

        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        callbacks = self._callbacks.get(event_type, [])
        logger.info(f"Lifecycle event: {event_type.name} from {source}")

        for cb in callbacks:
            try:
                if cb._is_async:
                    if cb.async_callback:
                        await cb.async_callback(event)
                    else:
                        await cb.callback(event)
                else:
                    if asyncio.iscoroutinefunction(cb.callback):
                        await cb.callback(event)
                    else:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, cb.callback, event)
            except Exception as e:
                logger.error(f"Lifecycle callback {cb.name} failed: {e}")

        self._record_audit("EMIT", "system", {"event_type": event_type.name})

    def emit_sync(
        self, event_type: LifecycleEventType, source: str = "system", details: dict[str, Any] | None = None
    ) -> None:
        event = LifecycleEvent(
            event_type=event_type,
            timestamp=datetime.now(UTC),
            source=source,
            details=details or {},
        )
        if event_type == LifecycleEventType.STARTING:
            self._current_phase = LifecyclePhase.STARTING
        elif event_type == LifecycleEventType.STARTED:
            self._current_phase = LifecyclePhase.RUNNING
        elif event_type == LifecycleEventType.DEGRADED:
            self._current_phase = LifecyclePhase.DEGRADED
        elif event_type == LifecycleEventType.SHUTTING_DOWN:
            self._current_phase = LifecyclePhase.STOPPING
        elif event_type == LifecycleEventType.SHUTDOWN:
            self._current_phase = LifecyclePhase.STOPPED

        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history = self._event_history[-self._max_history :]

        callbacks = self._callbacks.get(event_type, [])
        logger.info(f"Lifecycle event (sync): {event_type.name}")

        for cb in callbacks:
            if cb._is_async:
                logger.warning(f"Skipping async callback {cb.name} in sync context")
            else:
                try:
                    cb.callback(event)
                except Exception as e:
                    logger.error(f"Lifecycle callback {cb.name} failed: {e}")

        self._record_audit("EMIT_SYNC", "system", {"event_type": event_type.name})

    def get_current_phase(self) -> LifecyclePhase:
        return self._current_phase

    def is_running(self) -> bool:
        return self._current_phase in (LifecyclePhase.RUNNING, LifecyclePhase.DEGRADED)

    def is_healthy(self) -> bool:
        return self._current_phase == LifecyclePhase.RUNNING

    def get_event_history(self, limit: int = 100) -> list[LifecycleEvent]:
        return self._event_history[-limit:]

    def get_callbacks(self, event_type: LifecycleEventType | None = None) -> dict[str, list[str]]:
        result = {}
        for et, cbs in self._callbacks.items():
            if event_type is None or et == event_type:
                result[et.name] = [cb.name for cb in cbs]
        return result

    def register_signal_handlers(self) -> None:
        if self._signal_handlers_registered:
            return

        def signal_handler(signum: int, frame: Any) -> None:
            logger.info(f"Received signal {signum}, initiating shutdown...")
            self.emit_sync(LifecycleEventType.SIGNAL_RECEIVED, "signal", {"signum": signum})
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Suppress RUF006: we intentionally don't need to keep the task alive
                    # because the process is shutting down anyway.
                    _ = asyncio.create_task(self.emit(LifecycleEventType.SHUTTING_DOWN, "signal"))  # noqa: RUF006
                else:
                    self.emit_sync(LifecycleEventType.SHUTTING_DOWN, "signal")
            except Exception as e:
                logger.error(f"Failed to emit shutdown event: {e}")
                sys.exit(1)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        self._signal_handlers_registered = True
        self._record_audit("REGISTER_SIGNAL_HANDLERS", "system", {})
        logger.info("Signal handlers registered for graceful shutdown")

    async def wait_for_shutdown(self) -> None:
        shutdown_event = asyncio.Event()

        def signal_handler(signum: int, frame: Any) -> None:
            logger.info(f"Shutdown signal received: {signum}")
            shutdown_event.set()

        original_sigint = signal.signal(signal.SIGINT, signal_handler)
        original_sigterm = signal.signal(signal.SIGTERM, signal_handler)
        try:
            await shutdown_event.wait()
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    async def shutdown(self, timeout: float | None = None) -> None:
        if timeout is None:
            timeout = self._shutdown_timeout
        logger.info("Initiating graceful shutdown...")
        await self.emit(LifecycleEventType.SHUTTING_DOWN, "system", {"timeout": timeout})
        try:
            await asyncio.wait_for(self._wait_for_shutdown_complete(), timeout=timeout)
        except TimeoutError:
            logger.warning(f"Shutdown timed out after {timeout}s, forcing shutdown")
        await self.emit(LifecycleEventType.SHUTDOWN, "system")
        logger.info("Shutdown complete")

    async def _wait_for_shutdown_complete(self) -> None:
        await asyncio.sleep(0.1)

    def set_shutdown_timeout(self, timeout: float) -> None:
        self._shutdown_timeout = timeout

    def get_statistics(self) -> dict[str, Any]:
        return {
            "current_phase": self._current_phase.name,
            "total_events": len(self._event_history),
            "registered_callbacks": sum(len(cbs) for cbs in self._callbacks.values()),
            "callbacks_by_event": {et.name: len(cbs) for et, cbs in self._callbacks.items()},
            "signal_handlers_registered": self._signal_handlers_registered,
            "shutdown_timeout": self._shutdown_timeout,
            "version": self._version,
        }

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._shutdown_timeout <= 0:
            errors.append("shutdown_timeout must be positive")
        for et, cbs in self._callbacks.items():
            for cb in cbs:
                res = cb.validate()
                if not res["is_valid"]:
                    errors.extend([f"{et.name}.{cb.name}: {e}" for e in res["errors"]])
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_phase": self._current_phase.name,
            "total_events": len(self._event_history),
            "registered_callbacks": sum(len(cbs) for cbs in self._callbacks.values()),
            "signal_handlers_registered": self._signal_handlers_registered,
            "shutdown_timeout": self._shutdown_timeout,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LifecycleListener:
        instance = cls()
        instance._current_phase = LifecyclePhase[data.get("current_phase", "INITIAL")]
        instance._signal_handlers_registered = data.get("signal_handlers_registered", False)
        instance._shutdown_timeout = data.get("shutdown_timeout", 30.0)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> LifecycleListener:
        new_instance = LifecycleListener()
        new_instance._current_phase = self._current_phase
        new_instance._signal_handlers_registered = self._signal_handlers_registered
        new_instance._shutdown_timeout = self._shutdown_timeout
        new_instance._version = self._version + 1
        # Callbacks are not cloned (they are references)
        return new_instance

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "current_phase": self._current_phase.name,
            "total_events": len(self._event_history),
            "registered_callbacks": sum(len(cbs) for cbs in self._callbacks.values()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LifecycleListener:
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
        self._callbacks.clear()
        self._event_history.clear()
        self._current_phase = LifecyclePhase.INITIAL
        self._signal_handlers_registered = False
        self._version += 1
        self._audit_trail = []
        self._snapshots = []


# === 3. SINGLETON ACCESSOR ===
_lifecycle_listener_instance: LifecycleListener | None = None


def get_lifecycle_listener() -> LifecycleListener:
    global _lifecycle_listener_instance
    if _lifecycle_listener_instance is None:
        _lifecycle_listener_instance = LifecycleListener()
    return _lifecycle_listener_instance


# === 4. CONVENIENCE FUNCTIONS ===
def on_startup(callback: Callable, priority: int = 0):
    def decorator(func):
        listener = get_lifecycle_listener()
        listener.register_startup_callback(func, priority, func.__name__)
        return func

    return decorator


def on_started(callback: Callable, priority: int = 0):
    def decorator(func):
        listener = get_lifecycle_listener()
        listener.register_started_callback(func, priority, func.__name__)
        return func

    return decorator


def on_shutdown(callback: Callable, priority: int = 0):
    def decorator(func):
        listener = get_lifecycle_listener()
        listener.register_shutdown_callback(func, priority, func.__name__)
        return func

    return decorator


def on_health_change(callback: Callable, priority: int = 0):
    def decorator(func):
        listener = get_lifecycle_listener()
        listener.register_health_callback(func, priority, func.__name__)
        return func

    return decorator


# === 5. EXPORTS ===
__all__ = [
    "LifecycleCallback",
    "LifecycleEvent",
    "LifecycleEventType",
    "LifecycleListener",
    "LifecyclePhase",
    "get_lifecycle_listener",
    "on_health_change",
    "on_shutdown",
    "on_started",
    "on_startup",
]
