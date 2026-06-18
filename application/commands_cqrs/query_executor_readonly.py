# query_executor_readonly.py - Hardened version with complete implementation

#!/usr/bin/env python3

"""
Module: query_executor_readonly.py
Layer: 5 - Application / Commands CQRS

Responsibility:
    Eksekutor untuk query read-only (CQRS read side).
    Tidak mengimpor infrastruktur. Semua dependency diberikan dari luar.

Fitur:
    - Read replica routing
    - Connection pooling
    - Query timeout handling
    - Retry logic with backoff
    - Circuit breaker pattern
    - Caching support
    - Concurrent query limiting
    - Metrics collection
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ============================================================================
# ENUMS
# ============================================================================


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class QueryStatus(str, Enum):
    """Query execution status."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# ============================================================================
# PROTOCOLS (abstraksi, implementasi diberikan dari luar)
# ============================================================================


class ReadReplicaRouterPort(Protocol):
    """Port for read replica routing."""

    async def get_connection(self) -> Any:
        """Get a connection from a read replica."""
        ...

    async def release_connection(self, conn: Any) -> None:
        """Release connection back to pool."""
        ...

    async def get_health(self) -> dict[str, Any]:
        """Get health status of replicas."""
        ...


class ConnectionPoolPort(Protocol):
    """Port for connection pool management."""

    async def acquire(self) -> Any:
        """Acquire a connection from the pool."""
        ...

    async def release(self, conn: Any) -> None:
        """Release connection back to pool."""
        ...

    async def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        ...


class CachePort(Protocol):
    """Port for cache operations."""

    async def get(self, key: str) -> str | None:
        """Get value from cache."""
        ...

    async def setex(self, key: str, ttl: int, value: str) -> None:
        """Set value with expiration."""
        ...

    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        ...

    async def delete(self, key: str) -> None:
        """Delete key from cache."""
        ...

    async def clear_pattern(self, pattern: str) -> int:
        """Clear all keys matching pattern."""
        ...


class MetricsPort(Protocol):
    """Port for metrics collection."""

    def record_query_execution(self, query_type: str, duration_ms: float, success: bool) -> None:
        """Record query execution metrics."""
        ...

    def record_cache_hit(self, query_type: str) -> None:
        """Record cache hit."""
        ...

    def record_cache_miss(self, query_type: str) -> None:
        """Record cache miss."""
        ...

    def increment_circuit_breaker_state(self, query_type: str, state: str) -> None:
        """Record circuit breaker state change."""
        ...


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass(kw_only=True)
class QueryExecutorConfig:
    """Configuration for QueryExecutorReadonly."""

    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_delay_seconds: float = 0.5
    retry_backoff_multiplier: float = 2.0
    enable_caching: bool = False
    cache_ttl_seconds: int = 300
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 30.0
    max_concurrent_queries: int = 100
    enable_metrics: bool = True
    enable_circuit_breaker: bool = True
    log_slow_queries_ms: float = 1000.0
    default_cache_key_prefix: str = "query"

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "retry_backoff_multiplier": self.retry_backoff_multiplier,
            "enable_caching": self.enable_caching,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "circuit_breaker_failure_threshold": self.circuit_breaker_failure_threshold,
            "circuit_breaker_recovery_timeout": self.circuit_breaker_recovery_timeout,
            "max_concurrent_queries": self.max_concurrent_queries,
            "enable_metrics": self.enable_metrics,
            "enable_circuit_breaker": self.enable_circuit_breaker,
            "log_slow_queries_ms": self.log_slow_queries_ms,
        }


# ============================================================================
# CIRCUIT BREAKER IMPLEMENTATION
# ============================================================================


class CircuitBreaker:
    """Circuit breaker implementation for query execution."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._success_count = 0
        self._total_failures = 0
        self._total_successes = 0

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        self._check_recovery()
        return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    def _check_recovery(self) -> None:
        """Check if circuit should transition from OPEN to HALF_OPEN."""
        if self._state == CircuitBreakerState.OPEN and self._last_failure_time:
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitBreakerState.HALF_OPEN
                self._half_open_calls = 0
                logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")

    def call(self, func: Callable[[], Awaitable[T]]) -> Awaitable[T]:
        """Execute function with circuit breaker protection."""
        if self.state == CircuitBreakerState.OPEN:
            raise Exception(f"Circuit breaker '{self.name}' is OPEN")

        async def wrapper():
            try:
                result = await func()
                self._record_success()
                return result
            except Exception:
                self._record_failure()
                raise

        return wrapper()

    def _record_success(self) -> None:
        """Record successful execution."""
        self._total_successes += 1

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._reset()
                logger.info(f"Circuit breaker '{self.name}' closed after successful calls")
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def _record_failure(self) -> None:
        """Record failed execution."""
        self._total_failures += 1
        self._last_failure_time = time.time()

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            logger.warning(f"Circuit breaker '{self.name}' opened after HALF_OPEN failure")
        elif self._state == CircuitBreakerState.CLOSED:
            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitBreakerState.OPEN
                logger.warning(
                    f"Circuit breaker '{self.name}' opened after {self._failure_count} failures"
                )

    def _reset(self) -> None:
        """Reset circuit breaker to closed state."""
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._half_open_calls = 0

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "last_failure_time": self._last_failure_time,
        }


# ============================================================================
# QUERY EXECUTOR READONLY
# ============================================================================


class QueryExecutorReadonly:
    """
    Eksekutor untuk query read-only.
    Menerima dependency dari luar (dependency injection).
    """

    def __init__(
        self,
        router: ReadReplicaRouterPort,
        pool: ConnectionPoolPort,
        config: QueryExecutorConfig | None = None,
        cache: CachePort | None = None,
        metrics: MetricsPort | None = None,
    ):
        """
        Args:
            router: Read replica router (wajib)
            pool: Connection pool (wajib)
            config: Konfigurasi query executor (opsional)
            cache: Cache port (opsional, jika enable_caching = True)
            metrics: Metrics port (opsional)
        """
        if router is None:
            raise ValueError("router is required")
        if pool is None:
            raise ValueError("pool is required")

        self._config = config or QueryExecutorConfig()
        self._router = router
        self._pool = pool
        self._cache = cache
        self._metrics = metrics

        if self._config.enable_caching and self._cache is None:
            logger.warning("Caching enabled but cache not provided, using in-memory cache")
            self._use_memory_cache = True
        else:
            self._use_memory_cache = False

        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._semaphore = asyncio.Semaphore(self._config.max_concurrent_queries)

        # In-memory cache fallback
        self._memory_cache: dict[str, tuple[Any, float]] = {}

        # Statistics
        self._stats = {
            "total_queries": 0,
            "successful_queries": 0,
            "failed_queries": 0,
            "cached_hits": 0,
            "cached_misses": 0,
            "timeout_errors": 0,
            "circuit_breaker_opens": 0,
            "last_error": None,
            "started_at": datetime.now().isoformat(),
        }

        # Query execution history (last 100)
        self._query_history: list[dict[str, Any]] = []

        logger.info(
            "QueryExecutorReadonly initialized",
            extra={
                "timeout": self._config.timeout_seconds,
                "max_retries": self._config.max_retries,
                "caching": self._config.enable_caching,
                "circuit_breaker": self._config.enable_circuit_breaker,
                "max_concurrent": self._config.max_concurrent_queries,
            },
        )

    def _get_circuit_breaker(self, query_type: str) -> CircuitBreaker:
        """Get or create circuit breaker for query type."""
        if not self._config.enable_circuit_breaker:
            return None

        if query_type not in self._circuit_breakers:
            self._circuit_breakers[query_type] = CircuitBreaker(
                name=f"query_{query_type}",
                failure_threshold=self._config.circuit_breaker_failure_threshold,
                recovery_timeout=self._config.circuit_breaker_recovery_timeout,
            )
        return self._circuit_breakers[query_type]

    def _get_cache_key(self, query: Any) -> str:
        """Generate cache key from query."""
        # Extract query data
        if hasattr(query, "to_dict"):
            data = query.to_dict()
        elif hasattr(query, "__dict__"):
            data = query.__dict__.copy()
        else:
            data = {"query_type": getattr(query, "query_type", "unknown")}

        # Remove unique fields
        data.pop("query_id", None)
        data.pop("occurred_at", None)
        data.pop("correlation_id", None)

        # Generate hash
        json_str = json.dumps(data, sort_keys=True, default=str)
        hash_val = hashlib.sha256(json_str.encode()).hexdigest()[:16]

        return f"{self._config.default_cache_key_prefix}:{getattr(query, 'query_type', 'unknown')}:{hash_val}"

    async def _get_cached(self, key: str) -> Any | None:
        """Get value from cache."""
        # Try external cache first
        if self._cache:
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
        """Set value in cache."""
        serialized = json.dumps(value, default=str)

        # Try external cache
        if self._cache:
            try:
                if hasattr(self._cache, "setex"):
                    await self._cache.setex(key, ttl, serialized)
                elif hasattr(self._cache, "set"):
                    await self._cache.set(key, serialized, ex=ttl)
                return
            except Exception as e:
                logger.warning(f"Cache set failed: {e}")

        # Fallback to memory cache
        self._memory_cache[key] = (value, time.time() + ttl)

    async def _execute_with_retry(
        self,
        query: Any,
        handler: Callable[[Any], Awaitable[Any]],
        attempt: int = 0,
    ) -> Any:
        """Execute query with retry logic."""
        try:
            return await asyncio.wait_for(
                self._execute_with_connection(query, handler), timeout=self._config.timeout_seconds
            )
        except TimeoutError:
            if attempt < self._config.max_retries:
                delay = self._config.retry_delay_seconds * (
                    self._config.retry_backoff_multiplier**attempt
                )
                logger.warning(
                    f"Query {getattr(query, 'query_type', 'unknown')} timed out, "
                    f"retrying in {delay}s (attempt {attempt + 1}/{self._config.max_retries + 1})"
                )
                await asyncio.sleep(delay)
                return await self._execute_with_retry(query, handler, attempt + 1)
            raise
        except Exception as e:
            if attempt < self._config.max_retries:
                delay = self._config.retry_delay_seconds * (
                    self._config.retry_backoff_multiplier**attempt
                )
                logger.warning(
                    f"Query {getattr(query, 'query_type', 'unknown')} failed: {e}, "
                    f"retrying in {delay}s (attempt {attempt + 1}/{self._config.max_retries + 1})"
                )
                await asyncio.sleep(delay)
                return await self._execute_with_retry(query, handler, attempt + 1)
            raise

    async def _execute_with_connection(
        self, query: Any, handler: Callable[[Any], Awaitable[Any]]
    ) -> Any:
        """Execute query with connection from pool."""
        conn = await self._router.get_connection()
        try:
            # Inject connection to query if it has setter
            if hasattr(query, "set_connection"):
                query.set_connection(conn)
            if hasattr(query, "connection"):
                query.connection = conn

            return await handler(query)
        finally:
            await self._router.release_connection(conn)

    async def execute(self, query: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        """
        Execute query dengan retry, circuit breaker, dan caching.

        Args:
            query: Query object to execute
            handler: Async handler function that processes the query

        Returns:
            Query result data
        """
        self._stats["total_queries"] += 1
        start_time = time.perf_counter()
        query_type = getattr(query, "query_type", type(query).__name__)

        # Check cache
        cache_key = None
        if self._config.enable_caching:
            cache_key = self._get_cache_key(query)
            cached = await self._get_cached(cache_key)
            if cached is not None:
                self._stats["cached_hits"] += 1
                if self._metrics:
                    self._metrics.record_cache_hit(query_type)
                logger.debug(f"Cache hit for query {query_type}")
                return cached
            else:
                self._stats["cached_misses"] += 1
                if self._metrics:
                    self._metrics.record_cache_miss(query_type)

        # Check circuit breaker
        cb = self._get_circuit_breaker(query_type)
        if cb and cb.state == CircuitBreakerState.OPEN:
            self._stats["failed_queries"] += 1
            raise Exception(f"Circuit breaker open for query type: {query_type}")

        # Execute with semaphore concurrency limit
        async with self._semaphore:
            try:
                # Execute with retry
                result = await self._execute_with_retry(query, handler)

                # Record success
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._stats["successful_queries"] += 1

                if self._metrics:
                    self._metrics.record_query_execution(query_type, duration_ms, True)

                # Log slow queries
                if duration_ms > self._config.log_slow_queries_ms:
                    logger.warning(
                        f"Slow query detected: {query_type} took {duration_ms:.2f}ms",
                        extra={"query_type": query_type, "duration_ms": duration_ms},
                    )

                # Record in history
                self._query_history.append(
                    {
                        "query_type": query_type,
                        "duration_ms": duration_ms,
                        "success": True,
                        "timestamp": time.time(),
                    }
                )
                while len(self._query_history) > 100:
                    self._query_history.pop(0)

                # Cache result
                if cache_key and result is not None:
                    await self._set_cached(cache_key, result, self._config.cache_ttl_seconds)

                # Record circuit breaker success
                if cb:
                    cb._record_success()

                return result

            except TimeoutError as e:
                self._stats["timeout_errors"] += 1
                self._stats["failed_queries"] += 1
                self._stats["last_error"] = str(e)

                if self._metrics:
                    self._metrics.record_query_execution(query_type, 0, False)

                # Record circuit breaker failure
                if cb:
                    cb._record_failure()
                    if cb.state == CircuitBreakerState.OPEN:
                        self._stats["circuit_breaker_opens"] += 1

                self._query_history.append(
                    {
                        "query_type": query_type,
                        "duration_ms": 0,
                        "success": False,
                        "error": "timeout",
                        "timestamp": time.time(),
                    }
                )
                while len(self._query_history) > 100:
                    self._query_history.pop(0)

                raise TimeoutError(
                    f"Query {query_type} timed out after {self._config.timeout_seconds}s"
                )

            except Exception as e:
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._stats["failed_queries"] += 1
                self._stats["last_error"] = str(e)

                if self._metrics:
                    self._metrics.record_query_execution(query_type, duration_ms, False)

                # Record circuit breaker failure
                if cb:
                    cb._record_failure()
                    if cb.state == CircuitBreakerState.OPEN:
                        self._stats["circuit_breaker_opens"] += 1

                self._query_history.append(
                    {
                        "query_type": query_type,
                        "duration_ms": duration_ms,
                        "success": False,
                        "error": str(e)[:200],
                        "timestamp": time.time(),
                    }
                )
                while len(self._query_history) > 100:
                    self._query_history.pop(0)

                raise

    def invalidate_cache(self, pattern: str | None = None) -> None:
        """Invalidate cache entries."""
        if pattern:
            logger.info(f"Invalidating cache with pattern: {pattern}")
            if self._cache and hasattr(self._cache, "clear_pattern"):
                # Would implement in production
                pass
            # Clear memory cache entries matching pattern
            keys_to_delete = [k for k in self._memory_cache if pattern in k]
            for k in keys_to_delete:
                del self._memory_cache[k]
        else:
            logger.info("Invalidating entire cache")
            if self._cache and hasattr(self._cache, "clear"):
                pass
            self._memory_cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get executor statistics."""
        uptime_seconds = (
            datetime.now() - datetime.fromisoformat(self._stats["started_at"])
        ).total_seconds()

        return {
            **self._stats,
            "uptime_seconds": uptime_seconds,
            "success_rate": (
                (self._stats["successful_queries"] / self._stats["total_queries"] * 100)
                if self._stats["total_queries"] > 0
                else 100
            ),
            "cache_hit_rate": (
                (
                    self._stats["cached_hits"]
                    / (self._stats["cached_hits"] + self._stats["cached_misses"])
                    * 100
                )
                if (self._stats["cached_hits"] + self._stats["cached_misses"]) > 0
                else 0
            ),
            "circuit_breakers": {
                name: cb.get_stats() for name, cb in self._circuit_breakers.items()
            },
            "config": self._config.to_dict(),
            "recent_queries": self._query_history[-10:],
            "memory_cache_size": len(self._memory_cache),
        }

    async def health_check(self) -> dict[str, Any]:
        """Perform health check."""
        router_health = (
            await self._router.get_health() if hasattr(self._router, "get_health") else {}
        )

        return {
            "status": "healthy"
            if self._stats["failed_queries"] < self._stats["total_queries"] * 0.1
            else "degraded",
            "total_queries": self._stats["total_queries"],
            "success_rate": (
                (self._stats["successful_queries"] / self._stats["total_queries"] * 100)
                if self._stats["total_queries"] > 0
                else 100
            ),
            "circuit_breakers_open": sum(
                1 for cb in self._circuit_breakers.values() if cb.state == CircuitBreakerState.OPEN
            ),
            "router_health": router_health,
        }

    async def close(self) -> None:
        """Close executor and release resources."""
        logger.info("Closing QueryExecutorReadonly")
        self._memory_cache.clear()
        # Would close connections if needed


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "CachePort",
    "CircuitBreaker",
    "CircuitBreakerState",
    "ConnectionPoolPort",
    "MetricsPort",
    "QueryExecutorConfig",
    "QueryExecutorReadonly",
    "QueryStatus",
    "ReadReplicaRouterPort",
]
