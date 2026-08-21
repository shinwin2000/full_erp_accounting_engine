#!/usr/bin/env python3

"""
Module: query_handler_registry.py

Layer: 8 - Application / Commands CQRS

Responsibility:
    Registry untuk mendaftarkan dan mengelola query handlers (CQRS read side).
    Query handler menerima Query object dan mengembalikan QueryResult (read-only data).

Fitur:
    - Thread-safe registration dengan RLock
    - Wildcard handler untuk semua query (logging, security)
    - Priority-based execution order
    - Handler metadata untuk dokumentasi dan monitoring
    - Validasi signature handler saat registrasi
    - Handler versioning
    - Query type discovery
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

# Type aliases
QueryHandler = Callable[[Any], Awaitable[Any]]
WildcardQueryHandler = Callable[[Any], Awaitable[Any | None]]


# === 1. EXCEPTIONS ===


class QueryHandlerRegistryError(Exception):
    """Base exception untuk registry errors."""

    pass


class QueryHandlerAlreadyRegisteredError(QueryHandlerRegistryError):
    """Handler untuk query type yang sama sudah terdaftar."""

    pass


class QueryHandlerNotFoundError(QueryHandlerRegistryError):
    """Tidak ada handler terdaftar untuk query type."""

    pass


class InvalidQueryHandlerSignatureError(QueryHandlerRegistryError):
    """Handler memiliki signature yang tidak valid."""

    pass


class QueryHandlerVersionError(QueryHandlerRegistryError):
    """Version mismatch for query handler."""

    pass


# === 2. HANDLER METADATA ===


@dataclass(kw_only=True)
class QueryHandlerMetadata:
    """Metadata untuk query handler yang terdaftar."""

    name: str
    description: str | None = None
    version: str = "1.0"
    tags: list[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)
    execution_count: int = 0
    total_execution_time_ms: float = 0.0
    last_execution_time_ms: float = 0.0
    last_error: str | None = None
    last_success_at: float | None = None
    deprecated: bool = False
    deprecated_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "registered_at": self.registered_at,
            "execution_count": self.execution_count,
            "avg_execution_time_ms": (
                self.total_execution_time_ms / self.execution_count if self.execution_count else 0
            ),
            "last_execution_time_ms": self.last_execution_time_ms,
            "last_error": self.last_error,
            "last_success_at": self.last_success_at,
            "deprecated": self.deprecated,
            "deprecated_message": self.deprecated_message,
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
        """Calculate success rate percentage."""
        if self.execution_count == 0:
            return 100.0
        # Simplified - in production would track actual successes
        error_count = 1 if self.last_error else 0
        return ((self.execution_count - error_count) / self.execution_count) * 100


# === 3. QUERY HANDLER REGISTRY ===


class QueryHandlerRegistry:
    """
    Registry untuk query handlers. Implementasi thread-safe singleton.

    Usage:
        registry = QueryHandlerRegistry.get_instance()

        @registry.register("GetJournalEntryQuery")
        async def handle_get_journal(query: GetJournalEntryQuery) -> QueryResult:
            ...

        # Wildcard handler (dipanggil untuk semua query)
        @registry.wildcard(priority=10)
        async def log_all_queries(query: Query) -> Optional[QueryResult]:
            logger.info(f"Query: {query.query_type}")
            return None  # continue to specific handler
    """

    _instance: QueryHandlerRegistry | None = None
    _lock = RLock()

    def __new__(cls) -> QueryHandlerRegistry:
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
                # Mapping: query_type -> handler
                self._handlers: dict[str, QueryHandler] = {}
                # Metadata per query type
                self._metadata: dict[str, QueryHandlerMetadata] = {}
                # Wildcard handlers: list of (priority, index, handler, metadata)
                self._wildcard_handlers: list[
                    tuple[int, int, WildcardQueryHandler, QueryHandlerMetadata]
                ] = []
                self._next_wildcard_index = 0
                self._initialized = True
                logger.info("QueryHandlerRegistry initialized (singleton)")

    # ==================== REGISTRATION DECORATORS ====================

    def register(
        self,
        query_type: str,
        override: bool = False,
        name: str | None = None,
        description: str | None = None,
        version: str = "1.0",
        tags: list[str] | None = None,
        deprecated: bool = False,
        deprecated_message: str | None = None,
    ) -> Callable[[QueryHandler], QueryHandler]:
        """
        Decorator untuk mendaftarkan query handler.

        Args:
            query_type: Nama query class (string)
            override: Jika True, timpa handler yang sudah ada
            name: Nama handler (default: function __name__)
            description: Deskripsi handler
            version: Versi handler
            tags: Tag untuk kategorisasi
            deprecated: Mark handler as deprecated
            deprecated_message: Deprecation message
        """

        def decorator(handler: QueryHandler) -> QueryHandler:
            metadata = QueryHandlerMetadata(
                name=name or handler.__name__,
                description=description,
                version=version,
                tags=tags or [],
                deprecated=deprecated,
                deprecated_message=deprecated_message,
            )
            self.register_handler(query_type, handler, override, metadata)
            return handler

        return decorator

    def wildcard(
        self,
        priority: int = 0,
        name: str | None = None,
        description: str | None = None,
        version: str = "1.0",
    ) -> Callable[[WildcardQueryHandler], WildcardQueryHandler]:
        """
        Decorator untuk mendaftarkan wildcard query handler.
        Dipanggil untuk semua query sebelum specific handler.
        Priority lebih besar = dieksekusi lebih awal.
        """

        def decorator(handler: WildcardQueryHandler) -> WildcardQueryHandler:
            metadata = QueryHandlerMetadata(
                name=name or handler.__name__,
                description=description or "Wildcard query handler",
                version=version,
                tags=["wildcard"],
            )
            self.register_wildcard(handler, metadata, priority)
            return handler

        return decorator

    # ==================== REGISTRATION METHODS ====================

    def register_handler(
        self,
        query_type: str,
        handler: QueryHandler,
        override: bool = False,
        metadata: QueryHandlerMetadata | None = None,
    ) -> None:
        """
        Daftarkan handler untuk query type.
        """
        self._validate_handler_signature(handler)

        with self._lock:
            if query_type in self._handlers and not override:
                existing_meta = self._metadata.get(query_type)
                raise QueryHandlerAlreadyRegisteredError(
                    f"Query handler already registered for: {query_type}. "
                    f"Existing: {existing_meta.name if existing_meta else 'unknown'}. "
                    f"Use override=True to replace."
                )

            self._handlers[query_type] = handler
            if metadata is None:
                metadata = QueryHandlerMetadata(name=handler.__name__)
            self._metadata[query_type] = metadata

            logger.info(
                f"Registered query handler for '{query_type}'",
                extra={"handler": metadata.name, "version": metadata.version},
            )

    def register_wildcard(
        self,
        handler: WildcardQueryHandler,
        metadata: QueryHandlerMetadata | None = None,
        priority: int = 0,
    ) -> None:
        """
        Daftarkan wildcard handler.
        """
        self._validate_wildcard_signature(handler)

        with self._lock:
            if metadata is None:
                metadata = QueryHandlerMetadata(name=handler.__name__)

            entry = (priority, self._next_wildcard_index, handler, metadata)
            self._wildcard_handlers.append(entry)
            self._next_wildcard_index += 1

            # Sort by priority (descending), then index (ascending)
            self._wildcard_handlers.sort(key=lambda x: (-x[0], x[1]))

            logger.info(
                f"Registered wildcard query handler '{metadata.name}' with priority {priority}"
            )

    # ==================== HANDLER RETRIEVAL ====================

    def get_handler(self, query_type: str) -> QueryHandler | None:
        """
        Dapatkan handler untuk query type (dengan wildcard chain).
        """
        with self._lock:
            specific = self._handlers.get(query_type)
            wildcards = self._wildcard_handlers.copy()

            if not specific and not wildcards:
                return None

            async def chained_handler(query: Any) -> Any:
                start_time = time.perf_counter()

                # Check if deprecated
                meta = self._metadata.get(query_type)
                if meta and meta.deprecated:
                    logger.warning(
                        f"Using deprecated query handler: {query_type}. "
                        f"{meta.deprecated_message or 'No message provided'}"
                    )

                # Execute wildcards in priority order (use _ for unused variables)
                for _priority, _idx, wc_handler, wc_meta in wildcards:
                    try:
                        result = await wc_handler(query)
                        if result is not None:
                            # Wildcard returned a result, stop propagation
                            duration_ms = (time.perf_counter() - start_time) * 1000
                            wc_meta.record_execution(duration_ms)
                            logger.debug(
                                f"Wildcard '{wc_meta.name}' returned result for {query_type}"
                            )
                            return result
                    except Exception as e:
                        duration_ms = (time.perf_counter() - start_time) * 1000
                        wc_meta.record_execution(duration_ms, str(e))
                        logger.error(f"Wildcard handler '{wc_meta.name}' failed: {e}")
                        raise QueryHandlerRegistryError(f"Wildcard handler error: {e}") from e

                # Execute specific handler
                if specific is None:
                    raise QueryHandlerNotFoundError(f"No handler for query type: {query_type}")

                try:
                    result = await specific(query)
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    handler_meta = self._metadata.get(query_type)
                    if handler_meta:
                        handler_meta.record_execution(duration_ms)
                    return result
                except Exception as e:
                    duration_ms = (time.perf_counter() - start_time) * 1000
                    handler_meta = self._metadata.get(query_type)
                    if handler_meta:
                        handler_meta.record_execution(duration_ms, str(e))
                    raise

            return chained_handler

    def get_specific_handler(self, query_type: str) -> QueryHandler | None:
        """Dapatkan specific handler tanpa wildcard wrapping."""
        with self._lock:
            return self._handlers.get(query_type)

    def get_handler_metadata(self, query_type: str) -> QueryHandlerMetadata | None:
        """Get metadata for specific query handler."""
        with self._lock:
            return self._metadata.get(query_type)

    def get_all_metadata(self) -> dict[str, dict[str, Any]]:
        """Get all handler metadata."""
        with self._lock:
            return {qt: meta.to_dict() for qt, meta in self._metadata.items()}

    # ==================== UNREGISTRATION ====================

    def unregister_handler(self, query_type: str) -> bool:
        """Unregister handler for query type."""
        with self._lock:
            if query_type in self._handlers:
                meta = self._metadata.pop(query_type, None)
                del self._handlers[query_type]
                logger.info(
                    f"Unregistered query handler for '{query_type}' "
                    f"(was: {meta.name if meta else 'unknown'})"
                )
                return True
            return False

    def unregister_wildcard(self, name: str) -> bool:
        """Unregister wildcard handler by name."""
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

    # ==================== QUERY METHODS ====================

    def list_query_types(self) -> list[str]:
        """List all registered query types."""
        with self._lock:
            return list(self._handlers.keys())

    def has_handler(self, query_type: str) -> bool:
        """Check if handler exists for query type."""
        with self._lock:
            return query_type in self._handlers

    def get_deprecated_handlers(self) -> list[tuple[str, QueryHandlerMetadata]]:
        """Get all deprecated handlers."""
        with self._lock:
            return [(qt, meta) for qt, meta in self._metadata.items() if meta.deprecated]

    # ==================== STATISTICS ====================

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        with self._lock:
            total_executions = sum(meta.execution_count for meta in self._metadata.values())
            total_time = sum(meta.total_execution_time_ms for meta in self._metadata.values())

            return {
                "total_query_handlers": len(self._handlers),
                "total_wildcard_handlers": len(self._wildcard_handlers),
                "query_types": list(self._handlers.keys()),
                "wildcard_handlers": [
                    {"name": meta.name, "priority": priority}
                    for priority, _, _, meta in self._wildcard_handlers
                ],
                "handler_metadata": {qt: meta.to_dict() for qt, meta in self._metadata.items()},
                "total_executions": total_executions,
                "avg_execution_time_ms": total_time / total_executions if total_executions else 0,
                "deprecated_count": len(self.get_deprecated_handlers()),
            }

    def get_health_status(self) -> dict[str, Any]:
        """Get health status of all handlers."""
        with self._lock:
            unhealthy = []
            for qt, meta in self._metadata.items():
                if meta.last_error:
                    unhealthy.append(
                        {
                            "query_type": qt,
                            "handler": meta.name,
                            "last_error": meta.last_error,
                            "success_rate": meta.get_success_rate(),
                        }
                    )

            return {
                "status": "healthy" if len(unhealthy) == 0 else "degraded",
                "total_handlers": len(self._handlers),
                "unhealthy_handlers": unhealthy,
                "deprecated_handlers": [qt for qt, _ in self.get_deprecated_handlers()],
            }

    # ==================== CLEAR ====================

    def clear(self) -> None:
        """Clear all handlers (for testing)."""
        with self._lock:
            self._handlers.clear()
            self._metadata.clear()
            self._wildcard_handlers.clear()
            self._next_wildcard_index = 0
            logger.warning("QueryHandlerRegistry cleared")

    # ==================== VALIDATION ====================

    def _validate_handler_signature(self, handler: QueryHandler) -> None:
        """Validasi bahwa handler adalah async function dengan 1 parameter (Query)."""
        if not asyncio.iscoroutinefunction(handler):
            raise InvalidQueryHandlerSignatureError(
                f"Query handler {handler.__name__} must be async"
            )

        sig = inspect.signature(handler)
        params = list(sig.parameters.values())

        if len(params) != 1:
            raise InvalidQueryHandlerSignatureError(
                f"Query handler must accept exactly 1 argument (Query), got {len(params)}"
            )

    def _validate_wildcard_signature(self, handler: WildcardQueryHandler) -> None:
        """Validasi bahwa wildcard handler adalah async function dengan 1 parameter (Query)."""
        if not asyncio.iscoroutinefunction(handler):
            raise InvalidQueryHandlerSignatureError(
                f"Wildcard handler {handler.__name__} must be async"
            )

        sig = inspect.signature(handler)
        params = list(sig.parameters.values())

        if len(params) != 1:
            raise InvalidQueryHandlerSignatureError(
                f"Wildcard handler must accept exactly 1 argument (Query), got {len(params)}"
            )

    def __repr__(self) -> str:
        return (
            f"<QueryHandlerRegistry "
            f"handlers={len(self._handlers)} "
            f"wildcard={len(self._wildcard_handlers)}>"
        )


# === 4. SINGLETON INSTANCE ===

_query_handler_registry_instance: QueryHandlerRegistry | None = None


def get_query_handler_registry() -> QueryHandlerRegistry:
    """Get singleton instance."""
    global _query_handler_registry_instance
    if _query_handler_registry_instance is None:
        _query_handler_registry_instance = QueryHandlerRegistry()
    return _query_handler_registry_instance


def reset_query_handler_registry() -> None:
    """Reset the query handler registry singleton (for testing)."""
    global _query_handler_registry_instance
    if _query_handler_registry_instance:
        _query_handler_registry_instance.clear()
    _query_handler_registry_instance = None


# Convenience alias
query_handler_registry = get_query_handler_registry()


# === 5. CONVENIENCE FUNCTIONS (untuk kemudahan import) ===

def get_query_handler(query_type: str) -> QueryHandler | None:
    """
    Get handler for a specific query type.
    Convenience function that delegates to the singleton registry.

    Args:
        query_type: Name of the query class (string)

    Returns:
        Handler function or None if not found
    """
    return query_handler_registry.get_handler(query_type)


def register_query_handler(
    query_type: str,
    handler: QueryHandler,
    override: bool = False,
    name: str | None = None,
    description: str | None = None,
    version: str = "1.0",
    tags: list[str] | None = None,
    deprecated: bool = False,
    deprecated_message: str | None = None,
) -> None:
    """
    Register a query handler.

    Convenience function that delegates to the singleton registry.

    Args:
        query_type: Name of the query class (string)
        handler: Async callable
        override: If True, replace existing handler
        name: Handler name (default: function __name__)
        description: Handler description
        version: Handler version
        tags: List of tags
        deprecated: Mark handler as deprecated
        deprecated_message: Deprecation message
    """
    metadata = QueryHandlerMetadata(
        name=name or handler.__name__,
        description=description,
        version=version,
        tags=tags or [],
        deprecated=deprecated,
        deprecated_message=deprecated_message,
    )
    query_handler_registry.register_handler(query_type, handler, override=override, metadata=metadata)


def has_query_handler(query_type: str) -> bool:
    """
    Check if a handler exists for the query type.

    Convenience function that delegates to the singleton registry.
    """
    return query_handler_registry.has_handler(query_type)


def clear_query_handlers() -> None:
    """
    Clear all registered query handlers.

    Convenience function that delegates to the singleton registry.
    """
    query_handler_registry.clear()


def unregister_query_handler(query_type: str) -> bool:
    """
    Unregister a query handler.

    Convenience function that delegates to the singleton registry.
    """
    return query_handler_registry.unregister_handler(query_type)


def get_all_query_types() -> list[str]:
    """
    Get all registered query types.

    Convenience function that delegates to the singleton registry.
    """
    return query_handler_registry.list_query_types()


# === 6. DEFAULT WILDCARD HANDLERS ===


async def default_logging_wildcard(query: Any) -> Any | None:
    """Default wildcard handler for logging."""
    logger.debug(
        f"Query executed: {getattr(query, 'query_type', 'unknown')} | "
        f"id={getattr(query, 'query_id', 'none')}"
    )
    return None


async def default_metrics_wildcard(query: Any) -> Any | None:
    """Default wildcard handler for metrics collection."""
    # In production, send to Prometheus
    return None


def register_default_query_wildcards() -> None:
    """Register default wildcard handlers for logging and metrics."""
    registry = get_query_handler_registry()

    # Only register if not already registered
    if not registry._wildcard_handlers:
        registry.register_wildcard(default_logging_wildcard, priority=10)
        registry.register_wildcard(default_metrics_wildcard, priority=5)
        logger.info("Registered default query wildcard handlers")


# === 7. EXPORTS ===

__all__ = [
    "InvalidQueryHandlerSignatureError",
    # Exceptions
    "QueryHandlerAlreadyRegisteredError",
    "QueryHandlerMetadata",
    "QueryHandlerNotFoundError",
    "QueryHandlerRegistry",
    "QueryHandlerRegistryError",
    "QueryHandlerVersionError",
    # Convenience functions
    "clear_query_handlers",
    "get_all_query_types",
    "get_query_handler",
    "get_query_handler_registry",
    "has_query_handler",
    "query_handler_registry",
    "register_default_query_wildcards",
    "register_query_handler",
    "reset_query_handler_registry",
    "unregister_query_handler",
]
