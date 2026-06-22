#!/usr/bin/env python3

"""
Module: handler_registry.py

Layer: 8 - Application / Events

Responsibility:
    Registry untuk mendaftarkan dan mengelola event handlers di application layer.
    Mendukung multiple handler per event type dengan priority-based execution.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

# Type aliases
EventHandler = Callable[..., None | Awaitable[None]]
AsyncEventHandler = Callable[..., Awaitable[None]]
SyncEventHandler = Callable[..., None]


# === 1. ENUMS ===


class HandlerPriority(IntEnum):
    """Priority untuk eksekusi handler. Nilai lebih kecil = lebih dulu."""

    CRITICAL = 0   # Harus jalan pertama (misal audit, security)
    HIGH = 10      # High priority (misal update read model penting)
    NORMAL = 50    # Default priority
    LOW = 90       # Low priority (misal logging, analytics)
    MONITORING = 100  # Terakhir (metrics, tracing)
    LOWEST = 110 

# === 2. EXCEPTIONS ===


class HandlerRegistryError(Exception):
    """Base exception untuk registry errors."""
    pass


class HandlerAlreadyRegisteredError(HandlerRegistryError):
    """Handler dengan event type dan priority yang sama sudah terdaftar."""
    pass


class HandlerNotFoundError(HandlerRegistryError):
    """Tidak ada handler terdaftar untuk event type tertentu."""
    pass


class InvalidHandlerSignatureError(HandlerRegistryError):
    """Handler memiliki signature yang tidak valid."""
    pass


# === 3. HANDLER ENTRY ===


@dataclass(frozen=True)
class HandlerEntry:
    """Entry untuk handler yang terdaftar. Immutable."""

    handler: EventHandler
    event_type: str
    priority: HandlerPriority
    is_async: bool
    name: str
    registered_at: float = field(default_factory=time.time)
    execution_count: int = 0
    total_execution_time_ms: float = 0.0
    last_error: str | None = None

    def __post_init__(self):
        if not callable(self.handler):
            raise InvalidHandlerSignatureError(
                f"Handler must be callable, got {type(self.handler)}"
            )

    def record_execution(self, duration_ms: float, error: str | None = None) -> None:
        """Record handler execution metrics (mutable, but we create a new instance)."""
        # Since this is frozen, we need to use object.__setattr__ or return new instance
        # For simplicity in registry, we'll handle metrics separately
        pass

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "event_type": self.event_type,
            "priority": self.priority.name,
            "is_async": self.is_async,
            "registered_at": self.registered_at,
            "execution_count": self.execution_count,
            "avg_execution_time_ms": self.total_execution_time_ms / self.execution_count
            if self.execution_count
            else 0,
            "last_error": self.last_error,
        }


# === 4. EVENT HANDLER REGISTRY (SINGLETON) ===


class EventHandlerRegistry:
    """
    Registry untuk event handlers. Implementasi thread-safe singleton.

    Usage:
        registry = EventHandlerRegistry.get_instance()

        @registry.register("JournalPosted", priority=HandlerPriority.HIGH)
        async def handle_journal_posted(event_envelope):
            ...
    """

    _instance: EventHandlerRegistry | None = None
    _lock = RLock()

    def __new__(cls) -> EventHandlerRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        with self._lock:
            if not self._initialized:
                self._handlers: dict[str, list[HandlerEntry]] = defaultdict(list)
                self._wildcard_handlers: list[HandlerEntry] = []
                self._handler_metrics: dict[str, dict[str, Any]] = {}
                self._initialized = True
                logger.info("EventHandlerRegistry initialized (singleton)")

                # =============================================================
                # 🔥 REGISTRASI SEMUA EVENT HANDLER DARI all_event_handlers.py
                # =============================================================
                try:
                    from application.events.all_event_handlers import register_all_handlers
                    register_all_handlers(self)
                    logger.info(
                        "Successfully registered all event handlers from all_event_handlers.py"
                    )
                except ImportError as e:
                    logger.warning(
                        f"all_event_handlers.py not found or not importable: {e}. "
                        "Run generate_all_handlers.py to create it."
                    )
                except Exception as e:
                    logger.error(f"Failed to register all event handlers: {e}")

    # ===== REGISTER METHODS (existing) =====

    def register(
        self,
        event_type: str | None = None,
        priority: HandlerPriority = HandlerPriority.NORMAL,
        name: str | None = None,
        wildcard: bool = False,
    ) -> Callable[[EventHandler], EventHandler]:
        """Decorator untuk mendaftarkan handler."""

        def decorator(handler: EventHandler) -> EventHandler:
            nonlocal name
            if name is None:
                name = handler.__name__

            if wildcard:
                self.register_wildcard_handler(handler, priority=priority, name=name)
            elif event_type:
                self.register_handler(event_type, handler, priority=priority, name=name)
            else:
                raise InvalidHandlerSignatureError(
                    "Either event_type or wildcard=True must be specified"
                )

            return handler

        return decorator

    def register_handler(
        self,
        event_type: str,
        handler: EventHandler,
        priority: HandlerPriority = HandlerPriority.NORMAL,
        name: str | None = None,
    ) -> None:
        """Daftarkan handler untuk event type tertentu."""
        self._validate_handler_signature(handler)

        entry = HandlerEntry(
            handler=handler,
            event_type=event_type,
            priority=priority,
            is_async=asyncio.iscoroutinefunction(handler),
            name=name or handler.__name__,
        )

        with self._lock:
            handlers_list = self._handlers[event_type]

            # Cek duplikasi
            for existing in handlers_list:
                if existing.handler == handler and existing.priority == priority:
                    raise HandlerAlreadyRegisteredError(
                        f"Handler {entry.name} already registered for event {event_type} with priority {priority}"
                    )

            handlers_list.append(entry)
            handlers_list.sort(key=lambda e: (e.priority.value, e.name))

        logger.debug(
            f"Registered handler '{entry.name}' for event '{event_type}' (priority={priority.name})"
        )

    def register_wildcard_handler(
        self,
        handler: EventHandler,
        priority: HandlerPriority = HandlerPriority.MONITORING,
        name: str | None = None,
    ) -> None:
        """Daftarkan handler yang dipanggil untuk SEMUA event."""
        self._validate_handler_signature(handler)

        entry = HandlerEntry(
            handler=handler,
            event_type="*",
            priority=priority,
            is_async=asyncio.iscoroutinefunction(handler),
            name=name or handler.__name__,
        )

        with self._lock:
            self._wildcard_handlers.append(entry)
            self._wildcard_handlers.sort(key=lambda e: (e.priority.value, e.name))

        logger.debug(f"Registered wildcard handler '{entry.name}' (priority={priority.name})")

    def unregister_handler(
        self, event_type: str, handler: EventHandler | None = None, name: str | None = None
    ) -> bool:
        """Hapus handler dari registry."""
        with self._lock:
            if event_type not in self._handlers:
                return False

            if handler is None and name is None:
                del self._handlers[event_type]
                return True

            original_list = self._handlers[event_type]
            new_list = []
            removed = False

            for entry in original_list:
                if handler is not None and entry.handler == handler:
                    removed = True
                    continue
                if name is not None and entry.name == name:
                    removed = True
                    continue
                new_list.append(entry)

            if new_list:
                self._handlers[event_type] = new_list
            else:
                del self._handlers[event_type]

            return removed

    def unregister_wildcard_handler(
        self, handler: EventHandler | None = None, name: str | None = None
    ) -> bool:
        """Hapus wildcard handler."""
        with self._lock:
            original = self._wildcard_handlers
            new_list = []
            removed = False

            for entry in original:
                if handler is not None and entry.handler == handler:
                    removed = True
                    continue
                if name is not None and entry.name == name:
                    removed = True
                    continue
                new_list.append(entry)

            self._wildcard_handlers = new_list
            return removed

    def get_handlers(self, event_type: str) -> list[EventHandler]:
        """Dapatkan daftar handler untuk event type tertentu (termasuk wildcard)."""
        with self._lock:
            specific = self._handlers.get(event_type, [])
            specific_handlers = [entry.handler for entry in specific]
            wildcard_handlers = [entry.handler for entry in self._wildcard_handlers]
            return specific_handlers + wildcard_handlers

    def get_handler_entries(self, event_type: str) -> list[HandlerEntry]:
        """Dapatkan HandlerEntry objects untuk event type."""
        with self._lock:
            specific = self._handlers.get(event_type, []).copy()
            wildcard = self._wildcard_handlers.copy()
            return specific + wildcard

    def has_handlers(self, event_type: str) -> bool:
        """Cek apakah ada handler untuk event type."""
        with self._lock:
            return bool(self._handlers.get(event_type)) or bool(self._wildcard_handlers)

    def list_registered_event_types(self) -> list[str]:
        """Daftar semua event type yang memiliki specific handlers."""
        with self._lock:
            return list(self._handlers.keys())

    def get_stats(self) -> dict[str, Any]:
        """Statistik registry untuk monitoring."""
        with self._lock:
            total_specific = sum(len(h) for h in self._handlers.values())
            return {
                "event_types": len(self._handlers),
                "total_specific_handlers": total_specific,
                "total_wildcard_handlers": len(self._wildcard_handlers),
                "handlers_by_event": {
                    event_type: [e.name for e in entries]
                    for event_type, entries in self._handlers.items()
                },
                "wildcard_handlers": [e.name for e in self._wildcard_handlers],
            }

    def clear(self) -> None:
        """Hapus semua handler (untuk testing)."""
        with self._lock:
            self._handlers.clear()
            self._wildcard_handlers.clear()
            logger.warning("EventHandlerRegistry cleared all handlers")

    def _validate_handler_signature(self, handler: EventHandler) -> None:
        """Validasi signature handler."""
        try:
            sig = inspect.signature(handler)
            params = list(sig.parameters.values())

            if len(params) < 1:
                raise InvalidHandlerSignatureError(
                    f"Handler {handler.__name__} must accept at least 1 argument (EventEnvelope)"
                )

            required_params = [
                p
                for p in params
                if p.default == inspect.Parameter.empty
                and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            ]
            if len(required_params) > 1:
                raise InvalidHandlerSignatureError(
                    f"Handler {handler.__name__} has {len(required_params)} required parameters"
                )
        except Exception as e:
            if isinstance(e, InvalidHandlerSignatureError):
                raise
            raise InvalidHandlerSignatureError(f"Cannot validate handler {handler.__name__}: {e}")

    def __repr__(self) -> str:
        return f"<EventHandlerRegistry handlers={self.get_stats()['total_specific_handlers']}>"


# === 5. GLOBAL INSTANCE ===

event_handler_registry = EventHandlerRegistry()


# === 6. CONVENIENCE FUNCTIONS ===


def register_handler(
    event_type: str, priority: HandlerPriority = HandlerPriority.NORMAL, name: str | None = None
) -> Callable[[EventHandler], EventHandler]:
    """Convenience decorator using global registry."""
    return event_handler_registry.register(event_type=event_type, priority=priority, name=name)


def register_wildcard(
    priority: HandlerPriority = HandlerPriority.MONITORING, name: str | None = None
) -> Callable[[EventHandler], EventHandler]:
    """Convenience decorator for wildcard handlers."""
    return event_handler_registry.register(wildcard=True, priority=priority, name=name)


def get_handlers(event_type: str) -> list[EventHandler]:
    """Get handlers for event type from global registry."""
    return event_handler_registry.get_handlers(event_type)


def has_handlers(event_type: str) -> bool:
    """Check if any handlers exist for event type."""
    return event_handler_registry.has_handlers(event_type)


# === 7. DEFAULT LOGGING HANDLER ===


def register_default_logging_handler() -> None:
    """Daftarkan handler default untuk logging semua event."""

    @register_wildcard(priority=HandlerPriority.MONITORING, name="default_logging_handler")
    def log_event(envelope) -> None:
        """Log event yang diterima/dipublikasikan."""
        logger.info(
            f"Event: {getattr(envelope, 'event_type', 'unknown')}",
            extra={
                "event_id": str(getattr(envelope, "event_id", "none")),
                "correlation_id": getattr(envelope, "correlation_id", "none"),
            },
        )


# === 8. EXPORTS ===

__all__ = [
    "AsyncEventHandler",
    "EventHandler",
    "EventHandlerRegistry",
    "HandlerAlreadyRegisteredError",
    "HandlerEntry",
    "HandlerNotFoundError",
    "HandlerPriority",
    "HandlerRegistryError",
    "InvalidHandlerSignatureError",
    "SyncEventHandler",
    "event_handler_registry",
    "get_handlers",
    "has_handlers",
    "register_default_logging_handler",
    "register_handler",
    "register_wildcard",
]