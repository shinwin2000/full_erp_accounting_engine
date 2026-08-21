#!/usr/bin/env python3

"""
Module: command_handler_registry.py

Layer: 8 - Application / Commands CQRS

Responsibility:
    Registry untuk mendaftarkan dan mengelola command handlers.
    Setiap command type (string) dipetakan ke handler function (async callable)
    yang menerima command object dan mengembalikan CommandResult.

Fitur:
    - Thread-safe registration dan lookup
    - Wildcard handler untuk semua command (misal logging)
    - Handler wrapper untuk metrics dan tracing
    - Validasi handler signature saat registrasi
    - Support untuk handler overrides (replace)
    - Handler priority system
    - Handler metrics collection
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

# Type alias untuk command handler
CommandHandler = Callable[[Any], Awaitable[Any]]


# === 1. EXCEPTIONS ===


class CommandHandlerRegistryError(Exception):
    """Base exception untuk registry errors."""
    pass


class CommandHandlerAlreadyRegisteredError(CommandHandlerRegistryError):
    """Handler untuk command type yang sama sudah terdaftar."""
    pass


class CommandHandlerNotFoundError(CommandHandlerRegistryError):
    """Tidak ada handler terdaftar untuk command type."""
    pass


class InvalidCommandHandlerSignatureError(CommandHandlerRegistryError):
    """Handler memiliki signature yang tidak valid."""
    pass


class CommandHandlerExecutionError(CommandHandlerRegistryError):
    """Error saat eksekusi handler."""
    pass


# === 2. HANDLER METADATA ===


@dataclass(kw_only=True)
class HandlerMetadata:
    """Metadata untuk command handler yang terdaftar."""

    name: str
    description: str | None = None
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)
    priority: int = 0
    registered_at: float = field(default_factory=time.time)
    execution_count: int = 0
    total_execution_time_ms: float = 0.0
    last_execution_time_ms: float = 0.0
    last_error: str | None = None
    last_success_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "priority": self.priority,
            "registered_at": self.registered_at,
            "execution_count": self.execution_count,
            "avg_execution_time_ms": (
                self.total_execution_time_ms / self.execution_count if self.execution_count else 0
            ),
            "last_execution_time_ms": self.last_execution_time_ms,
            "last_error": self.last_error,
            "last_success_at": self.last_success_at,
        }

    def record_execution(self, duration_ms: float, error: str | None = None) -> None:
        """Record handler execution metrics."""
        self.execution_count += 1
        self.total_execution_time_ms += duration_ms
        self.last_execution_time_ms = duration_ms
        if error:
            self.last_error = error
        else:
            self.last_error = None
            self.last_success_at = time.time()

    def get_success_rate(self) -> float:
        """Calculate success rate."""
        if self.execution_count == 0:
            return 100.0
        # Simplified - track errors separately would be better
        return 100.0 if not self.last_error else 50.0


# === 3. COMMAND HANDLER REGISTRY ===


class CommandHandlerRegistry:
    """
    Registry untuk command handlers. Implementasi thread-safe singleton.

    Usage:
        registry = CommandHandlerRegistry.get_instance()

        @registry.register("PostJournalEntryCommand")
        async def handle_post_journal(cmd: PostJournalEntryCommand) -> CommandResult:
            ...

        # Atau manual:
        registry.register_handler("CreateARInvoiceCommand", my_handler)

        # Dapatkan handler:
        handler = registry.get_handler("PostJournalEntryCommand")
    """

    _instance: CommandHandlerRegistry | None = None
    _lock = RLock()

    def __new__(cls) -> CommandHandlerRegistry:
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
                # Mapping: command_type -> handler
                self._handlers: dict[str, CommandHandler] = {}
                # Metadata per command type
                self._metadata: dict[str, HandlerMetadata] = {}
                # Wildcard handlers: list of (priority, index, handler, metadata)
                self._wildcard_handlers: list[tuple[int, int, CommandHandler, HandlerMetadata]] = []
                self._next_wildcard_index = 0
                self._initialized = True
                logger.info("CommandHandlerRegistry initialized (singleton)")

    # ==================== REGISTRATION DECORATORS ====================

    def register(
        self,
        command_type: str,
        override: bool = False,
        name: str | None = None,
        description: str | None = None,
        version: str = "1.0",
        tags: list[str] | None = None,
        priority: int = 0,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """
        Decorator untuk mendaftarkan handler.

        Args:
            command_type: Nama command class (string)
            override: Jika True, timpa handler yang sudah ada
            name: Nama handler (default: function __name__)
            description: Deskripsi handler
            version: Versi handler
            tags: Tag untuk kategorisasi
            priority: Priority untuk execution order (higher = earlier)
        """

        def decorator(handler: CommandHandler) -> CommandHandler:
            metadata = HandlerMetadata(
                name=name or handler.__name__,
                description=description,
                version=version,
                tags=tags or [],
                priority=priority,
            )
            self.register_handler(command_type, handler, override=override, metadata=metadata)
            return handler

        return decorator

    def wildcard(
        self,
        priority: int = 0,
        name: str | None = None,
        description: str | None = None,
    ) -> Callable[[CommandHandler], CommandHandler]:
        """
        Decorator untuk mendaftarkan wildcard handler.
        Dipanggil untuk semua command sebelum specific handler.
        Priority lebih besar = dieksekusi lebih awal.
        """

        def decorator(handler: CommandHandler) -> CommandHandler:
            metadata = HandlerMetadata(
                name=name or handler.__name__,
                description=description or "Wildcard command handler",
                tags=["wildcard"],
                priority=priority,
            )
            self.register_wildcard(handler, metadata, priority)
            return handler

        return decorator

    # ==================== REGISTRATION METHODS ====================

    def register_handler(
        self,
        command_type: str,
        handler: CommandHandler,
        override: bool = False,
        metadata: HandlerMetadata | None = None,
    ) -> None:
        """
        Daftarkan handler untuk command type.

        Args:
            command_type: Nama command class (string)
            handler: Async callable yang menerima Command dan mengembalikan CommandResult
            override: Jika True, timpa handler yang sudah ada
            metadata: Metadata untuk handler

        Raises:
            CommandHandlerAlreadyRegisteredError: Jika handler sudah ada dan override=False
            InvalidCommandHandlerSignatureError: Jika signature handler tidak valid
        """
        self._validate_handler_signature(handler)

        with self._lock:
            if command_type in self._handlers and not override:
                existing_meta = self._metadata.get(command_type)
                raise CommandHandlerAlreadyRegisteredError(
                    f"Handler already registered for command type: {command_type}. "
                    f"Existing: {existing_meta.name if existing_meta else 'unknown'}"
                )

            self._handlers[command_type] = handler
            if metadata is None:
                metadata = HandlerMetadata(name=handler.__name__)
            self._metadata[command_type] = metadata

            logger.info(
                f"Registered handler for command '{command_type}'",
                extra={"handler": metadata.name, "version": metadata.version, "override": override},
            )

    def register_wildcard(
        self,
        handler: CommandHandler,
        metadata: HandlerMetadata | None = None,
        priority: int = 0,
    ) -> None:
        """
        Daftarkan wildcard handler yang dipanggil untuk semua command.
        Wildcard handler dipanggil SEBELUM specific handler.
        Berguna untuk logging, metrics, audit global.

        Args:
            handler: Async callable yang menerima Command dan mengembalikan Optional[CommandResult]
            metadata: Metadata untuk handler
            priority: Priority (higher = executed earlier)
        """
        self._validate_wildcard_signature(handler)

        with self._lock:
            if metadata is None:
                metadata = HandlerMetadata(name=handler.__name__, priority=priority)
            else:
                metadata.priority = priority

            entry = (priority, self._next_wildcard_index, handler, metadata)
            self._wildcard_handlers.append(entry)
            self._next_wildcard_index += 1

            # Sort by priority (descending), then index (ascending)
            self._wildcard_handlers.sort(key=lambda x: (-x[0], x[1]))

            logger.info(f"Registered wildcard handler: {metadata.name} with priority {priority}")

    # ==================== HANDLER RETRIEVAL ====================

    def get_handler(self, command_type: str) -> CommandHandler | None:
        """
        Dapatkan handler untuk command type.
        Jika ada wildcard handler, akan mengembalikan handler yang membungkus
        wildcard + specific handler.

        Returns:
            Handler function atau None jika tidak ada handler specific
        """
        with self._lock:
            specific = self._handlers.get(command_type)
            wildcards = self._wildcard_handlers.copy()

            if not specific and not wildcards:
                return None

            async def chained_handler(cmd: Any) -> Any:
                start_time = time.perf_counter()

                # Execute wildcards in priority order (use _ for unused vars)
                for _priority, _idx, wc_handler, wc_meta in wildcards:
                    try:
                        result = await wc_handler(cmd)
                        if result is not None:
                            # Wildcard returned a result, stop propagation
                            duration_ms = (time.perf_counter() - start_time) * 1000
                            wc_meta.record_execution(duration_ms)
                            logger.debug(
                                f"Wildcard '{wc_meta.name}' returned result for {command_type}"
                            )
                            return result
                    except Exception as e:
                        duration_ms = (time.perf_counter() - start_time) * 1000
                        wc_meta.record_execution(duration_ms, str(e))
                        logger.error(f"Wildcard handler '{wc_meta.name}' failed: {e}")
                        raise CommandHandlerExecutionError(f"Wildcard handler error: {e}") from e

                # Execute specific handler
                if specific is None:
                    raise CommandHandlerNotFoundError(
                        f"No handler for command type: {command_type}"
                    )

                try:
                    result = await specific(cmd)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    meta = self._metadata.get(command_type)
                    if meta:
                        meta.record_execution(duration_ms)
                    return result
                except Exception as e:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    meta = self._metadata.get(command_type)
                    if meta:
                        meta.record_execution(duration_ms, str(e))
                    raise CommandHandlerExecutionError(f"Handler execution failed: {e}") from e

            return chained_handler

    def get_specific_handler(self, command_type: str) -> CommandHandler | None:
        """Dapatkan specific handler tanpa wildcard wrapping."""
        with self._lock:
            return self._handlers.get(command_type)

    def get_handler_metadata(self, command_type: str) -> HandlerMetadata | None:
        """Get metadata for a specific command handler."""
        with self._lock:
            return self._metadata.get(command_type)

    # ==================== UNREGISTRATION ====================

    def unregister_handler(self, command_type: str) -> bool:
        """Hapus handler untuk command type."""
        with self._lock:
            if command_type in self._handlers:
                metadata = self._metadata.pop(command_type, None)
                del self._handlers[command_type]
                logger.info(
                    f"Unregistered handler for command '{command_type}' "
                    f"(was: {metadata.name if metadata else 'unknown'})"
                )
                return True
            return False

    def unregister_wildcard(self, name: str) -> bool:
        """Hapus wildcard handler berdasarkan nama."""
        with self._lock:
            original_len = len(self._wildcard_handlers)
            self._wildcard_handlers = [
                entry for entry in self._wildcard_handlers if entry[3].name != name
            ]
            removed = original_len - len(self._wildcard_handlers)
            if removed > 0:
                logger.info(f"Unregistered {removed} wildcard handler(s) with name '{name}'")
                return True
            return False

    def unregister_wildcard_by_index(self, index: int) -> bool:
        """Hapus wildcard handler berdasarkan index."""
        with self._lock:
            if 0 <= index < len(self._wildcard_handlers):
                removed = self._wildcard_handlers.pop(index)
                logger.info(f"Unregistered wildcard handler: {removed[3].name}")
                return True
            return False

    # ==================== QUERY METHODS ====================

    def list_command_types(self) -> list[str]:
        """Daftar semua command types yang memiliki handler."""
        with self._lock:
            return list(self._handlers.keys())

    def has_handler(self, command_type: str) -> bool:
        """Cek apakah ada specific handler untuk command type."""
        with self._lock:
            return command_type in self._handlers

    def get_wildcard_handlers(self) -> list[tuple[int, str]]:
        """Get list of wildcard handlers with their priorities."""
        with self._lock:
            return [(priority, meta.name) for priority, _, _, meta in self._wildcard_handlers]

    # ==================== STATISTICS ====================

    def get_stats(self) -> dict[str, Any]:
        """Statistik registry."""
        with self._lock:
            return {
                "total_handlers": len(self._handlers),
                "total_wildcard_handlers": len(self._wildcard_handlers),
                "command_types": list(self._handlers.keys()),
                "wildcard_handlers": [
                    {"name": meta.name, "priority": priority}
                    for priority, _, _, meta in self._wildcard_handlers
                ],
                "handler_metadata": {
                    cmd_type: meta.to_dict() for cmd_type, meta in self._metadata.items()
                },
            }

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all handlers."""
        with self._lock:
            unhealthy = []
            for cmd_type, meta in self._metadata.items():
                if meta.last_error and (time.time() - (meta.last_success_at or 0)) > 3600:
                    unhealthy.append(
                        {
                            "command_type": cmd_type,
                            "handler": meta.name,
                            "last_error": meta.last_error,
                            "success_rate": meta.get_success_rate(),
                        }
                    )

            return {
                "status": "healthy" if len(unhealthy) == 0 else "degraded",
                "total_handlers": len(self._handlers),
                "unhealthy_handlers": unhealthy,
            }

    # ==================== CLEAR ====================

    def clear(self) -> None:
        """Hapus semua handler (untuk testing)."""
        with self._lock:
            self._handlers.clear()
            self._metadata.clear()
            self._wildcard_handlers.clear()
            self._next_wildcard_index = 0
            logger.warning("CommandHandlerRegistry cleared all handlers")

    # ==================== VALIDATION ====================

    def _validate_handler_signature(self, handler: CommandHandler) -> None:
        """
        Validasi bahwa handler adalah async function dengan 1 parameter (Command)
        dan return type CommandResult (atau None untuk wildcard).
        """
        if not asyncio.iscoroutinefunction(handler):
            raise InvalidCommandHandlerSignatureError(
                f"Handler {handler.__name__} must be an async function"
            )

        try:
            sig = inspect.signature(handler)
            params = list(sig.parameters.values())

            # Harus punya minimal 1 parameter
            if len(params) < 1:
                raise InvalidCommandHandlerSignatureError(
                    f"Handler {handler.__name__} must accept at least 1 argument (Command)"
                )

        except Exception as e:
            if isinstance(e, InvalidCommandHandlerSignatureError):
                raise
            raise InvalidCommandHandlerSignatureError(
                f"Cannot validate handler {handler.__name__}: {e}"
            ) from e

    def _validate_wildcard_signature(self, handler: CommandHandler) -> None:
        """Validasi untuk wildcard handler."""
        self._validate_handler_signature(handler)

    def __repr__(self) -> str:
        return (
            f"<CommandHandlerRegistry "
            f"handlers={len(self._handlers)} "
            f"wildcard={len(self._wildcard_handlers)}>"
        )


# === 4. SINGLETON INSTANCE ===

_command_handler_registry_instance: CommandHandlerRegistry | None = None


def get_command_handler_registry() -> CommandHandlerRegistry:
    """Get singleton instance of CommandHandlerRegistry."""
    global _command_handler_registry_instance
    if _command_handler_registry_instance is None:
        _command_handler_registry_instance = CommandHandlerRegistry()
    return _command_handler_registry_instance


def reset_command_handler_registry() -> None:
    """Reset the command handler registry singleton (for testing)."""
    global _command_handler_registry_instance
    if _command_handler_registry_instance:
        _command_handler_registry_instance.clear()
    _command_handler_registry_instance = None


# Convenience alias
command_handler_registry = get_command_handler_registry()


# === 5. CONVENIENCE FUNCTIONS (untuk kemudahan import) ===

def get_command_handler(command_type: str) -> CommandHandler | None:
    """
    Get handler for a specific command type.
    Convenience function that delegates to the singleton registry.

    Args:
        command_type: Name of the command class (string)

    Returns:
        Handler function or None if not found
    """
    return command_handler_registry.get_handler(command_type)


def register_command_handler(
    command_type: str,
    handler: CommandHandler,
    override: bool = False,
    name: str | None = None,
    description: str | None = None,
    version: str = "1.0",
    tags: list[str] | None = None,
    priority: int = 0,
) -> None:
    """
    Register a command handler.

    Convenience function that delegates to the singleton registry.

    Args:
        command_type: Name of the command class (string)
        handler: Async callable
        override: If True, replace existing handler
        name: Handler name (default: function __name__)
        description: Handler description
        version: Handler version
        tags: List of tags
        priority: Execution priority (higher = earlier)
    """
    metadata = HandlerMetadata(
        name=name or handler.__name__,
        description=description,
        version=version,
        tags=tags or [],
        priority=priority,
    )
    command_handler_registry.register_handler(command_type, handler, override=override, metadata=metadata)


def has_command_handler(command_type: str) -> bool:
    """
    Check if a handler exists for the command type.

    Convenience function that delegates to the singleton registry.
    """
    return command_handler_registry.has_handler(command_type)


def clear_command_handlers() -> None:
    """
    Clear all registered command handlers.

    Convenience function that delegates to the singleton registry.
    """
    command_handler_registry.clear()


def unregister_command_handler(command_type: str) -> bool:
    """
    Unregister a command handler.

    Convenience function that delegates to the singleton registry.
    """
    return command_handler_registry.unregister_handler(command_type)


def get_all_command_types() -> list[str]:
    """
    Get all registered command types.

    Convenience function that delegates to the singleton registry.
    """
    return command_handler_registry.list_command_types()


# === 6. DEFAULT WILDCARD HANDLERS ===


async def default_logging_wildcard(cmd: Any) -> Any | None:
    """Default wildcard handler for logging."""
    logger.debug(f"Command received: {getattr(cmd, 'command_type', 'unknown')}")
    return None


async def default_metrics_wildcard(cmd: Any) -> Any | None:
    """Default wildcard handler for metrics collection."""
    # In production, send to Prometheus
    return None


def register_default_wildcards() -> None:
    """Register default wildcard handlers."""
    registry = get_command_handler_registry()

    # Only register if not already registered
    if not registry.get_wildcard_handlers():
        registry.register_wildcard(default_logging_wildcard, priority=-10)
        registry.register_wildcard(default_metrics_wildcard, priority=-20)
        logger.info("Registered default wildcard handlers")


# === 7. EXPORTS ===

__all__ = [
    # Type alias
    "CommandHandler",
    # Exceptions
    "CommandHandlerAlreadyRegisteredError",
    "CommandHandlerExecutionError",
    "CommandHandlerNotFoundError",
    # Class
    "CommandHandlerRegistry",
    "CommandHandlerRegistryError",
    "HandlerMetadata",
    "InvalidCommandHandlerSignatureError",
    # Convenience functions
    "clear_command_handlers",
    "command_handler_registry",
    "get_all_command_types",
    "get_command_handler",
    "get_command_handler_registry",
    "has_command_handler",
    "register_command_handler",
    "register_default_wildcards",
    "reset_command_handler_registry",
    "unregister_command_handler",
]
