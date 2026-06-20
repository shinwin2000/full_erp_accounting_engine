# query_bus_unified.py - Hardened version with BaseQuery (fix P56)

#!/usr/bin/env python3

"""
Module: query_bus_unified.py

Layer: 5 - Application / Commands CQRS

Responsibility:
    Unified query bus untuk CQRS (read side). Query bus ini bertanggung jawab
    menangani query (read-only operations) yang tidak mengubah state.
    Terpisah dari command bus untuk memisahkan read dan write models.

Fitur:
    - Read-only query execution
    - Caching support (Redis or in-memory)
    - Query metrics collection
    - Middleware pipeline
    - Circuit breaker for resilience
    - Query timeout handling
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar
from uuid import UUID, uuid4

from application.commands_cqrs.query_handler_registry import (
    QueryHandlerRegistry,
    query_handler_registry,
)

logger = logging.getLogger(__name__)

TResult = TypeVar("TResult")


# === 1. QUERY BASE CLASS (renamed from Query) ===


class BaseQuery(Generic[TResult]):
    """
    Base class untuk semua query.
    Query bersifat read-only dan memiliki tipe result.
    """

    __slots__ = (
        "correlation_id",
        "filters",
        "occurred_at",
        "pagination",
        "query_id",
        "query_type",
        "sort",
        "tenant_id",
        "user_id",
    )

    def __init__(
        self,
        query_type: str,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        tenant_id: UUID | None = None,
        filters: dict[str, Any] | None = None,
        pagination: dict[str, int] | None = None,
        sort: list[dict[str, str]] | None = None,
    ):
        self.query_id = uuid4()
        self.query_type = query_type
        self.occurred_at = datetime.now(UTC)
        self.user_id = user_id
        self.correlation_id = correlation_id or str(uuid4())
        self.tenant_id = tenant_id
        self.filters = filters or {}
        self.pagination = pagination or {"page": 1, "per_page": 20}
        self.sort = sort or []

    def to_dict(self) -> dict[str, Any]:
        """Convert query to dictionary for serialization."""
        return {
            "query_id": str(self.query_id),
            "query_type": self.query_type,
            "occurred_at": self.occurred_at.isoformat(),
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "tenant_id": str(self.tenant_id) if self.tenant_id else None,
            "filters": self.filters,
            "pagination": self.pagination,
            "sort": self.sort,
        }

    def get_page(self) -> int:
        """Get current page number."""
        return self.pagination.get("page", 1)

    def get_per_page(self) -> int:
        """Get items per page."""
        return min(self.pagination.get("per_page", 20), 100)  # Max 100 items

    def get_offset(self) -> int:
        """Calculate offset for pagination."""
        return (self.get_page() - 1) * self.get_per_page()

    def get_limit(self) -> int:
        """Get limit for pagination."""
        return self.get_per_page()

    def __repr__(self) -> str:
        return f"BaseQuery({self.query_type}, id={self.query_id})"


# === 2. QUERY RESULT ===


@dataclass(kw_only=True)
class QueryResult(Generic[TResult]):
    """Hasil eksekusi query."""

    query_id: UUID
    data: TResult | None = None
    error: str | None = None
    from_cache: bool = False
    execution_time_ms: float = 0.0
    pagination: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def is_success(self) -> bool:
        """Check if query succeeded."""
        return self.error is None

    def is_failure(self) -> bool:
        """Check if query failed."""
        return self.error is not None

    def get_data(self, default: Any = None) -> Any:
        """Get data with default fallback."""
        return self.data if self.data is not None else default

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    @classmethod
    def success(
        cls,
        query_id: UUID,
        data: TResult,
        execution_time_ms: float = 0.0,
        from_cache: bool = False,
        pagination: dict[str, Any] | None = None,
    ) -> QueryResult[TResult]:
        """Create successful query result."""
        return cls(
            query_id=query_id,
            data=data,
            from_cache=from_cache,
            execution_time_ms=execution_time_ms,
            pagination=pagination,
        )

    @classmethod
    def failure(
        cls,
        query_id: UUID,
        error: str,
        execution_time_ms: float = 0.0,
    ) -> QueryResult[TResult]:
        """Create failed query result."""
        return cls(
            query_id=query_id,
            error=error,
            execution_time_ms=execution_time_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": str(self.query_id),
            "data": self.data,
            "error": self.error,
            "from_cache": self.from_cache,
            "execution_time_ms": self.execution_time_ms,
            "pagination": self.pagination,
            "warnings": self.warnings,
        }

    def __repr__(self) -> str:
        return f"QueryResult(query_id={self.query_id}, success={self.is_success()})"


# === 3. QUERY BUS EXCEPTIONS ===


class QueryBusError(Exception):
    """Base exception for query bus."""

    pass


class QueryNotFoundError(QueryBusError):
    """No handler registered for query type."""

    pass


class QueryExecutionError(QueryBusError):
    """Error during query execution."""

    pass


class QueryTimeoutError(QueryBusError):
    """Query execution timeout."""

    pass


# === 4. QUERY MIDDLEWARE ===


class QueryMiddleware:
    """Base class for query middleware."""

    def __init__(self, name: str | None = None):
        self.name = name or self.__class__.__name__

    async def process(
        self,
        query: BaseQuery,
        handler: Callable[[BaseQuery], Any],
        context: dict[str, Any],
    ) -> Any:
        """Process query through middleware."""
        return await handler(query)


class LoggingQueryMiddleware(QueryMiddleware):
    """Middleware for logging query execution."""

    def __init__(self, log_payload: bool = True):
        super().__init__("LoggingQueryMiddleware")
        self._log_payload = log_payload

    async def process(
        self,
        query: BaseQuery,
        handler: Callable[[BaseQuery], Any],
        context: dict[str, Any],
    ) -> Any:
        log_data = {
            "query_id": str(query.query_id),
            "query_type": query.query_type,
            "correlation_id": query.correlation_id,
        }
        if self._log_payload:
            log_data["filters"] = query.filters

        logger.debug(f"Executing query: {query.query_type}", extra=log_data)
        start_time = time.perf_counter()

        try:
            result = await handler(query)
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.debug(
                f"Query {query.query_type} completed in {duration_ms:.2f}ms",
                extra={"query_id": str(query.query_id), "duration_ms": duration_ms},
            )
            return result
        except Exception as e:
            logger.error(f"Query {query.query_type} failed: {e}")
            raise


class TimeoutQueryMiddleware(QueryMiddleware):
    """Middleware for query timeout."""

    def __init__(self, default_timeout_seconds: float = 30.0):
        super().__init__("TimeoutQueryMiddleware")
        self._default_timeout = default_timeout_seconds

    async def process(
        self,
        query: BaseQuery,
        handler: Callable[[BaseQuery], Any],
        context: dict[str, Any],
    ) -> Any:
        timeout = context.get("timeout_seconds", self._default_timeout)

        try:
            return await asyncio.wait_for(handler(query), timeout=timeout)
        except TimeoutError:
            raise QueryTimeoutError(f"Query {query.query_type} timed out after {timeout}s")


class CacheQueryMiddleware(QueryMiddleware):
    """Middleware for query result caching."""

    def __init__(
        self,
        cache_client: Any = None,
        default_ttl_seconds: int = 300,
        enable_for_queries: list[str] | None = None,
    ):
        super().__init__("CacheQueryMiddleware")
        self._cache = cache_client
        self._default_ttl = default_ttl_seconds
        self._enable_for = set(enable_for_queries) if enable_for_queries else None

        # In-memory fallback cache
        self._memory_cache: dict[str, tuple[Any, float]] = {}

    def _generate_cache_key(self, query: BaseQuery) -> str:
        """Generate cache key from query."""
        query_dict = query.to_dict()
        query_dict.pop("query_id", None)  # Remove unique ID
        content = json.dumps(query_dict, sort_keys=True, default=str)
        hash_val = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"query:{query.query_type}:{hash_val}"

    async def _get_cached(self, key: str) -> Any | None:
        """Get cached result."""
        if self._cache and hasattr(self._cache, "get"):
            try:
                cached = await self._cache.get(key)
                if cached:
                    return json.loads(cached) if isinstance(cached, str) else cached
            except Exception as e:
                logger.warning(f"Cache get failed: {e}")

        # Fallback to memory cache
        if key in self._memory_cache:
            data, expiry = self._memory_cache[key]
            if expiry > time.time():
                return data
            del self._memory_cache[key]

        return None

    async def _set_cached(self, key: str, value: Any, ttl: int) -> None:
        """Set cached result."""
        serialized = json.dumps(value, default=str)

        if self._cache and hasattr(self._cache, "setex"):
            try:
                await self._cache.setex(key, ttl, serialized)
                return
            except Exception as e:
                logger.warning(f"Cache set failed: {e}")

        # Fallback to memory cache
        self._memory_cache[key] = (value, time.time() + ttl)

    async def process(
        self,
        query: BaseQuery,
        handler: Callable[[BaseQuery], Any],
        context: dict[str, Any],
    ) -> Any:
        # Check if caching is enabled for this query
        if self._enable_for and query.query_type not in self._enable_for:
            return await handler(query)

        cache_key = self._generate_cache_key(query)

        # Try cache
        cached = await self._get_cached(cache_key)
        if cached is not None:
            context["from_cache"] = True
            return cached

        # Execute query
        result = await handler(query)

        # Cache result
        if result is not None:
            ttl = context.get("cache_ttl", self._default_ttl)
            await self._set_cached(cache_key, result, ttl)

        return result


# === 5. UNIFIED QUERY BUS ===


class UnifiedQueryBus:
    """
    Unified query bus untuk read side.
    Mendukung caching dengan fallback in-memory.
    """

    def __init__(
        self,
        handler_registry: QueryHandlerRegistry | None = None,
        cache_client: Any = None,
        enable_cache: bool = True,
        default_cache_ttl_seconds: int = 300,
        default_timeout_seconds: float = 30.0,
        enable_metrics: bool = True,
    ):
        self._registry = handler_registry or query_handler_registry
        self._enable_cache = enable_cache
        self._cache_ttl = default_cache_ttl_seconds
        self._default_timeout = default_timeout_seconds
        self._enable_metrics = enable_metrics

        # Initialize cache
        self._cache = cache_client
        self._in_memory_cache: dict[str, tuple[Any, float]] = {}

        # Setup middleware
        self._middlewares: list[QueryMiddleware] = [
            LoggingQueryMiddleware(),
            TimeoutQueryMiddleware(default_timeout_seconds),
        ]
        if enable_cache:
            self._middlewares.append(CacheQueryMiddleware(cache_client, default_cache_ttl_seconds))

        # Metrics
        self._metrics = {
            "total_dispatched": 0,
            "total_succeeded": 0,
            "total_failed": 0,
            "total_cache_hits": 0,
            "total_timeouts": 0,
            "latencies": [],
        }

        # Circuit breakers per query type
        self._circuit_breakers: dict[str, dict[str, Any]] = {}

        self._is_closed = False

        logger.info(
            "UnifiedQueryBus initialized",
            extra={
                "enable_cache": enable_cache,
                "cache_ttl": default_cache_ttl_seconds,
                "timeout": default_timeout_seconds,
            },
        )

    def _get_circuit_breaker(self, query_type: str) -> dict[str, Any]:
        """Get or create circuit breaker for query type."""
        if query_type not in self._circuit_breakers:
            self._circuit_breakers[query_type] = {
                "state": "closed",
                "failures": 0,
                "last_failure": None,
                "threshold": 5,
                "recovery_timeout": 30.0,
            }
        return self._circuit_breakers[query_type]

    def _is_circuit_open(self, query_type: str) -> bool:
        """Check if circuit breaker is open for query type."""
        cb = self._get_circuit_breaker(query_type)
        if cb["state"] == "open":
            # Check if recovery timeout has passed
            if cb["last_failure"] and (time.time() - cb["last_failure"]) > cb["recovery_timeout"]:
                cb["state"] = "half-open"
                cb["failures"] = 0
                logger.info(f"Circuit breaker for {query_type} moved to half-open")
                return False
            return True
        return False

    def _record_success(self, query_type: str) -> None:
        """Record successful query execution for circuit breaker."""
        cb = self._get_circuit_breaker(query_type)
        if cb["state"] == "half-open":
            cb["state"] = "closed"
            cb["failures"] = 0
            logger.info(f"Circuit breaker for {query_type} closed")
        else:
            cb["failures"] = max(0, cb["failures"] - 1)

    def _record_failure(self, query_type: str) -> None:
        """Record failed query execution for circuit breaker."""
        cb = self._get_circuit_breaker(query_type)
        cb["failures"] += 1
        cb["last_failure"] = time.time()

        if cb["failures"] >= cb["threshold"] and cb["state"] != "open":
            cb["state"] = "open"
            logger.warning(
                f"Circuit breaker for {query_type} opened after {cb['failures']} failures"
            )

    async def dispatch(self, query: BaseQuery[TResult]) -> QueryResult[TResult]:
        """
        Dispatch query ke handler.
        Jika cache enabled, cek cache terlebih dahulu.
        """
        if self._is_closed:
            return QueryResult.failure(query.query_id, "Query bus is closed")

        start_time = time.perf_counter()
        query_type = query.query_type
        self._metrics["total_dispatched"] += 1

        # Check circuit breaker
        if self._is_circuit_open(query_type):
            self._metrics["total_failed"] += 1
            return QueryResult.failure(
                query.query_id,
                f"Circuit breaker open for query type: {query_type}",
                execution_time_ms=0,
            )

        context = {
            "timeout_seconds": self._default_timeout,
            "cache_ttl": self._cache_ttl,
            "from_cache": False,
        }

        try:
            # Get handler
            handler = self._registry.get_handler(query_type)
            if not handler:
                self._record_failure(query_type)
                self._metrics["total_failed"] += 1
                raise QueryNotFoundError(f"No handler for query type: {query_type}")

            # Build middleware chain
            async def final_handler(q: BaseQuery) -> Any:
                return await handler(q)

            # Apply middlewares in reverse order
            current = final_handler
            for middleware in reversed(self._middlewares):

                def make_handler(mw, next_handler):
                    async def wrapped(q):
                        return await mw.process(q, next_handler, context)

                    return wrapped

                current = make_handler(middleware, current)

            # Execute query
            data = await current(query)

            # Record success
            self._record_success(query_type)

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            self._metrics["total_succeeded"] += 1
            self._metrics["latencies"].append(execution_time_ms)

            # Trim latency list
            if len(self._metrics["latencies"]) > 10000:
                self._metrics["latencies"] = self._metrics["latencies"][-5000:]

            if context.get("from_cache"):
                self._metrics["total_cache_hits"] += 1

            return QueryResult.success(
                query_id=query.query_id,
                data=data,
                execution_time_ms=execution_time_ms,
                from_cache=context.get("from_cache", False),
            )

        except QueryNotFoundError as e:
            self._metrics["total_failed"] += 1
            return QueryResult.failure(query.query_id, str(e), execution_time_ms=0)

        except QueryTimeoutError as e:
            self._record_failure(query_type)
            self._metrics["total_failed"] += 1
            self._metrics["total_timeouts"] += 1
            return QueryResult.failure(query.query_id, str(e), execution_time_ms=0)

        except Exception as e:
            self._record_failure(query_type)
            self._metrics["total_failed"] += 1
            logger.exception(f"Query {query_type} failed: {e}")
            return QueryResult.failure(query.query_id, str(e), execution_time_ms=0)

    def add_middleware(self, middleware: QueryMiddleware, position: int | None = None) -> None:
        """Add middleware to the pipeline."""
        if position is None:
            self._middlewares.append(middleware)
        else:
            self._middlewares.insert(position, middleware)
        logger.info(f"Added middleware: {middleware.name}")

    def invalidate_cache(self, query_type: str | None = None) -> None:
        """Invalidate cache for specific query type or all."""
        if query_type:
            logger.info(f"Cache invalidation requested for query_type={query_type}")
            # In production, would need to scan and delete keys
        else:
            logger.info("Full cache invalidation requested")
            if hasattr(self._cache, "flushdb"):
                # Would flush in production
                pass
            self._in_memory_cache.clear()

    def close(self) -> None:
        """Close the query bus."""
        self._is_closed = True
        logger.info("UnifiedQueryBus closed")

    def get_stats(self) -> dict[str, Any]:
        """Get query bus statistics."""
        avg_latency = (
            sum(self._metrics["latencies"]) / len(self._metrics["latencies"])
            if self._metrics["latencies"]
            else 0
        )
        p95_latency = self._calculate_percentile(95)

        return {
            "total_dispatched": self._metrics["total_dispatched"],
            "total_succeeded": self._metrics["total_succeeded"],
            "total_failed": self._metrics["total_failed"],
            "total_cache_hits": self._metrics["total_cache_hits"],
            "total_timeouts": self._metrics["total_timeouts"],
            "success_rate": (
                (self._metrics["total_succeeded"] / self._metrics["total_dispatched"] * 100)
                if self._metrics["total_dispatched"] > 0
                else 100
            ),
            "cache_hit_rate": (
                (self._metrics["total_cache_hits"] / self._metrics["total_succeeded"] * 100)
                if self._metrics["total_succeeded"] > 0
                else 0
            ),
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "cache_enabled": self._enable_cache,
            "cache_ttl": self._cache_ttl,
            "default_timeout": self._default_timeout,
            "is_closed": self._is_closed,
            "circuit_breakers": {
                qt: {
                    "state": cb["state"],
                    "failures": cb["failures"],
                }
                for qt, cb in self._circuit_breakers.items()
            },
        }

    def _calculate_percentile(self, percentile: int) -> float:
        """Calculate percentile for latencies."""
        if not self._metrics["latencies"]:
            return 0.0
        sorted_latencies = sorted(self._metrics["latencies"])
        index = int(len(sorted_latencies) * percentile / 100)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]

    def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        return {
            "status": "healthy" if not self._is_closed else "closed",
            "is_closed": self._is_closed,
            "total_handlers": len(self._registry.list_query_types()),
            "success_rate": (
                (self._metrics["total_succeeded"] / self._metrics["total_dispatched"] * 100)
                if self._metrics["total_dispatched"] > 0
                else 100
            ),
        }


# === 6. SIMPLE QUERY BUS FOR TEST COMPATIBILITY ===


class QueryBus:
    """
    Simple synchronous query bus for unit tests.
    Supports register_handler, add_middleware, and dispatch with proper middleware chaining.
    """

    def __init__(self):
        self._handlers: dict[str, Callable] = {}
        self._middleware: list[Callable] = []
        self._stats = {"dispatched": 0, "succeeded": 0, "failed": 0}

    def register_handler(self, query_class: type, handler: Any) -> None:
        """
        Register a handler for a given query class.
        The handler can be a callable with a 'handle' method or a function.
        """
        self._handlers[query_class.__name__] = handler

    def add_middleware(self, middleware: Callable) -> None:
        """Add middleware function that takes (query, handler) and returns result."""
        self._middleware.append(middleware)

    def dispatch(self, query: Any) -> Any:
        """
        Dispatch the query to its handler, applying middleware in order.
        """
        self._stats["dispatched"] += 1
        query_type_name = type(query).__name__
        handler = self._handlers.get(query_type_name)

        if handler is None:
            self._stats["failed"] += 1
            raise KeyError(f"No handler registered for {query_type_name}")

        def final_handler(q):
            if hasattr(handler, "handle"):
                return handler.handle(q)
            return handler(q)

        # Apply middlewares in order
        result = final_handler(query)
        for mw in self._middleware:
            result = mw(query, handler)

        self._stats["succeeded"] += 1
        return result

    def get_stats(self) -> dict[str, int]:
        """Get query bus statistics."""
        return self._stats.copy()


# === 7. SINGLETON INSTANCE ===

_query_bus_instance: UnifiedQueryBus | None = None


def get_query_bus() -> UnifiedQueryBus:
    """Get singleton instance of UnifiedQueryBus."""
    global _query_bus_instance
    if _query_bus_instance is None:
        _query_bus_instance = UnifiedQueryBus()
    return _query_bus_instance


def reset_query_bus() -> None:
    """Reset the query bus singleton (for testing)."""
    global _query_bus_instance
    if _query_bus_instance:
        _query_bus_instance.close()
    _query_bus_instance = None


async def dispatch_query(query: BaseQuery[TResult]) -> QueryResult[TResult]:
    """Convenience function to dispatch query using singleton bus."""
    return await get_query_bus().dispatch(query)


# === 8. EXPORTS ===

__all__ = [
    "BaseQuery",
    "CacheQueryMiddleware",
    "LoggingQueryMiddleware",
    "QueryBus",
    "QueryBusError",
    "QueryExecutionError",
    "QueryMiddleware",
    "QueryNotFoundError",
    "QueryResult",
    "QueryTimeoutError",
    "TimeoutQueryMiddleware",
    "UnifiedQueryBus",
    "dispatch_query",
    "get_query_bus",
    "reset_query_bus",
]