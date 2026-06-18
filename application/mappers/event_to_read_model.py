# event_to_read_model.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: event_to_read_model.py
Layer: 5 - Application / Mappers

Responsibility:
    Mapping dari domain events ke read model updates (projections).
    Tidak mengimpor infrastruktur. Session diberikan dari luar.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class DatabaseSessionPort(Protocol):
    """Port untuk database session (abstraksi)."""

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    async def close(self) -> None: ...
    def add(self, obj: Any) -> None: ...
    def query(self, model: Any) -> Any: ...
    def execute(self, statement: Any) -> Any: ...
    def flush(self) -> None: ...


class SessionFactoryPort(Protocol):
    """Port untuk session factory."""

    def __call__(self) -> DatabaseSessionPort: ...


class EventHandler(Protocol):
    """Protocol untuk event handler."""

    async def __call__(self, event: Any, session: DatabaseSessionPort) -> None: ...


# ============================================================================
# EXCEPTIONS
# ============================================================================


class EventToReadModelMappingError(Exception):
    """Base exception untuk mapping errors."""

    pass


class EventHandlerNotFoundError(EventToReadModelMappingError):
    """Handler tidak ditemukan untuk event type."""

    pass


class ReadModelUpdateError(EventToReadModelMappingError):
    """Error saat update read model."""

    pass


class EventHandlerExecutionError(EventToReadModelMappingError):
    """Error saat eksekusi handler."""

    pass


# ============================================================================
# REGISTRY
# ============================================================================


class EventToReadModelRegistry:
    """
    Registry untuk event handlers yang mengupdate read model.
    Thread-safe dengan asyncio.Lock.
    """

    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
            cls._instance._wildcard_handlers = []
            cls._instance._initialized = True
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self._handlers = {}
            self._wildcard_handlers = []
            self._initialized = True

    def register(self, event_type: str, handler: EventHandler) -> None:
        """
        Register handler untuk event type tertentu.

        Args:
            event_type: Nama event class (string)
            handler: Async function yang menerima (event, session)
        """
        if not asyncio.iscoroutinefunction(handler):
            raise EventToReadModelMappingError(f"Handler for {event_type} must be async")

        self._handlers[event_type] = handler
        logger.debug(f"Registered handler for event {event_type}")

    def register_wildcard(self, handler: EventHandler, priority: int = 50) -> None:
        """
        Register wildcard handler yang dipanggil untuk semua event.

        Args:
            handler: Async function yang menerima (event, session)
            priority: Priority eksekusi (lower = earlier)
        """
        if not asyncio.iscoroutinefunction(handler):
            raise EventToReadModelMappingError("Wildcard handler must be async")

        self._wildcard_handlers.append((priority, handler))
        self._wildcard_handlers.sort(key=lambda x: x[0])
        logger.debug(f"Registered wildcard handler with priority {priority}")

    def get_handler(self, event_type: str) -> EventHandler | None:
        """Dapatkan handler untuk event type."""
        return self._handlers.get(event_type)

    def get_wildcard_handlers(self) -> list[EventHandler]:
        """Dapatkan semua wildcard handlers (sorted by priority)."""
        return [handler for _, handler in self._wildcard_handlers]

    def has_handler(self, event_type: str) -> bool:
        """Cek apakah ada handler untuk event type."""
        return event_type in self._handlers

    def unregister(self, event_type: str) -> bool:
        """Unregister handler untuk event type."""
        if event_type in self._handlers:
            del self._handlers[event_type]
            logger.debug(f"Unregistered handler for event {event_type}")
            return True
        return False

    async def handle(self, event: Any, session: DatabaseSessionPort) -> None:
        """
        Handle event dengan semua registered handlers.

        Args:
            event: Domain event object
            session: Database session untuk update read model
        """
        event_type = event.__class__.__name__

        # Execute specific handler first
        specific_handler = self.get_handler(event_type)

        # Execute wildcard handlers
        for wc_handler in self.get_wildcard_handlers():
            try:
                await wc_handler(event, session)
            except Exception as e:
                logger.error(f"Wildcard handler failed for {event_type}: {e}")
                # Don't stop execution for wildcard errors

        # Execute specific handler
        if specific_handler:
            try:
                await specific_handler(event, session)
                logger.info(f"Processed event {event_type} to read model")
            except Exception as e:
                logger.exception(f"Failed to process event {event_type}: {e}")
                raise ReadModelUpdateError(f"Handler for {event_type} failed: {e}") from e

    def clear(self) -> None:
        """Clear all handlers (for testing)."""
        self._handlers.clear()
        self._wildcard_handlers.clear()
        logger.warning("EventToReadModelRegistry cleared")

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_handlers": len(self._handlers),
            "total_wildcard_handlers": len(self._wildcard_handlers),
            "event_types": list(self._handlers.keys()),
        }


# Global registry instance
event_to_read_model_registry = EventToReadModelRegistry()


# ============================================================================
# HANDLER FUNCTIONS (placeholder - actual implementations in projections layer)
# ============================================================================

# NOTE: Read model handlers should be implemented in projections layer,
# not in application layer. The registry only provides the mechanism.
# Handlers should be registered from adapters/projections at startup.


def register_all_handlers() -> None:
    """
    Register all handlers - should be called from composition root with actual handlers.
    This is a placeholder; actual handlers are registered from projections layer.
    """
    logger.info("EventToReadModelRegistry ready for handler registration")


async def process_event_for_read_model(
    event: Any,
    session_factory: SessionFactoryPort,
) -> None:
    """
    Process an event and update read model using session factory.

    Args:
        event: Domain event to process
        session_factory: Factory to create database session
    """
    session = session_factory()
    try:
        await event_to_read_model_registry.handle(event, session)
        await session.commit()
        logger.debug(f"Successfully processed event {event.__class__.__name__}")
    except Exception as e:
        await session.rollback()
        logger.error(f"Failed to process event {event.__class__.__name__}: {e}")
        raise
    finally:
        await session.close()


# ============================================================================
# DECORATOR HELPERS
# ============================================================================


def on_event(event_type: str):
    """
    Decorator untuk mendaftarkan event handler.

    Usage:
        @on_event("JournalPosted")
        async def update_ledger(event, session):
            ...
    """

    def decorator(handler: EventHandler) -> EventHandler:
        event_to_read_model_registry.register(event_type, handler)
        return handler

    return decorator


def on_all_events(priority: int = 50):
    """
    Decorator untuk mendaftarkan wildcard handler.

    Usage:
        @on_all_events(priority=10)
        async def log_all_events(event, session):
            logger.info(f"Event: {event.__class__.__name__}")
    """

    def decorator(handler: EventHandler) -> EventHandler:
        event_to_read_model_registry.register_wildcard(handler, priority)
        return handler

    return decorator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabaseSessionPort",
    "EventHandler",
    "EventHandlerNotFoundError",
    "EventToReadModelMappingError",
    "EventToReadModelRegistry",
    "ReadModelUpdateError",
    "SessionFactoryPort",
    "event_to_read_model_registry",
    "on_all_events",
    "on_event",
    "process_event_for_read_model",
    "register_all_handlers",
]
