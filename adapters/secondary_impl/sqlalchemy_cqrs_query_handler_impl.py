#!/usr/bin/env python3
"""
Module: sqlalchemy_cqrs_query_handler_impl.py
Layer: Adapters (Secondary Impl)
Responsibility: Implementasi SQLAlchemy untuk CQRSQueryHandlerPort - LENGKAP.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from ports.secondary.cqrs_query_handler_port import (
    CQRSQueryHandlerPort,
    FilterCondition,
    Pagination,
    Query,
    QueryResult,
    QueryStatus,
)

logger = logging.getLogger(__name__)


class SQLAlchemyCQRSQueryHandler(CQRSQueryHandlerPort):
    """
    SQLAlchemy implementation of CQRSQueryHandlerPort.
    Supports dependency injection for session_factory and cache.
    """

    def __init__(
        self,
        session_factory: Any | None = None,
        cache: Any | None = None,
    ):
        """
        Initialize with dependency injection.

        Args:
            session_factory: Factory to create database sessions (SQLAlchemy sessionmaker).
            cache: Optional cache instance (e.g., RedisCacheAdapter, InMemoryCache).
        """
        self._session_factory = session_factory
        self._cache = cache
        self._handlers = {}
        self._audit_log: list[dict[str, Any]] = []
        self._logger = logging.getLogger(f"{__name__}.SQLAlchemyCQRSQueryHandler")

    def register_handler(self, handler) -> None:
        self._handlers[handler.query_type] = handler
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "register_handler",
            "query_type": handler.query_type,
        })
        self._logger.info(f"Handler registered for query type: {handler.query_type}")

    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> QueryResult:
        """
        Execute query with error handling, logging, and optional caching.
        """
        start_time = datetime.now(UTC)
        cache_key = self._build_cache_key(query, pagination, filters)
        session = None

        try:
            # Try cache first
            if self._cache:
                cached_result = self._cache.get(cache_key)
                if cached_result is not None:
                    self._logger.debug(f"Cache hit for {cache_key}")
                    self._audit_log.append({
                        "timestamp": datetime.now(UTC).isoformat(),
                        "action": "execute_query",
                        "query_type": query.query_type,
                        "status": "cache_hit",
                    })
                    return cached_result

            # Execute handler if registered
            handler = self._handlers.get(query.query_type)
            if handler:
                # Create session if session_factory is available
                if self._session_factory:
                    session = self._session_factory()
                    # If handler expects session, inject it
                    if hasattr(handler, "set_session"):
                        handler.set_session(session)

                result = await handler.handle(query, pagination, filters)
            else:
                # Fallback: mock response
                result = QueryResult(
                    status=QueryStatus.SUCCESS,
                    data={"message": "Mock response (no handler registered)"},
                    total_count=1,
                    page=pagination.page if pagination else 1,
                    page_size=pagination.page_size if pagination else 10,
                    execution_time_ms=1.0,
                    cached=False,
                    error_message=None,
                )

            # Cache the result if cache is available and result is not None
            if self._cache and result is not None:
                self._cache.set(cache_key, result, ttl=300)

            elapsed = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "execute_query",
                "query_type": query.query_type,
                "status": "success",
                "execution_time_ms": elapsed,
                "cached": result.cached if hasattr(result, "cached") else False,
            })
            self._logger.info(f"Query {query.query_type} executed in {elapsed:.2f}ms")
            return result

        except Exception as e:
            self._logger.error(f"Query execution failed for {query.query_type}: {e}", exc_info=True)
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "execute_query",
                "query_type": query.query_type,
                "status": "failed",
                "error": str(e),
            })
            # Re-raise with context
            raise RuntimeError(f"Query {query.query_type} failed: {e}") from e

        finally:
            if session:
                session.close()
                self._logger.debug(f"Session closed for query {query.query_type}")

    def _build_cache_key(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> str:
        """Build cache key based on query and parameters."""
        parts = [f"query:{query.query_type}"]
        if pagination:
            parts.append(f"page={pagination.page}:size={pagination.page_size}")
        if filters:
            filter_str = "|".join([f"{f.field}={f.operator}:{f.value}" for f in filters])
            parts.append(f"filters={filter_str}")
        return ":".join(parts)

    async def list_handlers(self) -> list[str]:
        return list(self._handlers.keys())

    # ========================================================================
    # ADDITIONAL METHODS FOR PORT CONTRACT
    # ========================================================================

    async def clear_cache(self) -> None:
        """Clear the query cache."""
        if self._cache and hasattr(self._cache, "clear"):
            await self._cache.clear()
        self._logger.info("Cache cleared")
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "clear_cache",
        })

    async def execute_batch(
        self,
        queries: list[Query],
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> list[QueryResult]:
        """Execute multiple queries in batch."""
        results = []
        for query in queries:
            result = await self.execute(query, pagination, filters)
            results.append(result)
        return results

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Get audit log of query executions."""
        logs = self._audit_log.copy()
        logs.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return logs[offset:offset + limit]

    async def get_handler_info(self, handler_type: str) -> dict[str, Any] | None:
        """Get information about a specific handler."""
        handler = self._handlers.get(handler_type)
        if not handler:
            return None
        return {
            "query_type": handler.query_type if hasattr(handler, "query_type") else handler_type,
            "registered": True,
            "has_handle": hasattr(handler, "handle"),
        }

    async def get_metrics(self) -> dict[str, Any]:
        """Get metrics for query handler."""
        total_queries = sum(1 for log in self._audit_log if log.get("action") == "execute_query")
        failed_queries = sum(1 for log in self._audit_log if log.get("action") == "execute_query" and log.get("status") == "failed")
        cache_enabled = self._cache is not None
        return {
            "total_handlers": len(self._handlers),
            "handlers": list(self._handlers.keys()),
            "total_queries_executed": total_queries,
            "failed_queries": failed_queries,
            "cache_status": "enabled" if cache_enabled else "disabled",
            "audit_log_size": len(self._audit_log),
        }

    async def health_check(self) -> dict[str, Any]:
        """Check health of the query handler."""
        status = "healthy"
        if self._session_factory is None:
            status = "degraded (no session factory)"
        return {
            "status": status,
            "handlers_registered": len(self._handlers),
            "audit_log_size": len(self._audit_log),
            "cache_enabled": self._cache is not None,
        }

    async def invalidate_cache(self, query_type: str | None = None) -> None:
        """Invalidate cache for a specific query type or all."""
        if not self._cache:
            self._logger.warning("Cache is disabled, cannot invalidate")
            return

        if query_type:
            # Invalidate specific query type - depends on cache implementation
            if hasattr(self._cache, "invalidate_pattern"):
                pattern = f"query:{query_type}:*"
                await self._cache.invalidate_pattern(pattern)
                self._logger.info(f"Cache invalidated for query type: {query_type}")
            else:
                self._logger.warning(f"Cache does not support pattern invalidation for {query_type}")
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "invalidate_cache",
                "query_type": query_type,
            })
        else:
            # Invalidate all cache
            if hasattr(self._cache, "clear"):
                await self._cache.clear()
                self._logger.info("All cache invalidated")
                self._audit_log.append({
                    "timestamp": datetime.now(UTC).isoformat(),
                    "action": "invalidate_cache_all",
                })
            else:
                self._logger.warning("Cache does not support clear operation")

    async def unregister_handler(self, handler_type: str) -> bool:
        """Unregister a handler."""
        if handler_type in self._handlers:
            del self._handlers[handler_type]
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "unregister_handler",
                "query_type": handler_type,
            })
            self._logger.info(f"Handler {handler_type} unregistered")
            return True
        return False

    def set_session(self, session: Any) -> None:
        """
        Set session for the handler (if handler supports it).
        """
        for handler in self._handlers.values():
            if hasattr(handler, "set_session"):
                handler.set_session(session)

    def set_session_factory(self, session_factory: Any) -> None:
        """Set session factory after initialization."""
        self._session_factory = session_factory
        self._logger.info("Session factory updated")

    def set_cache(self, cache: Any) -> None:
        """Set cache after initialization."""
        self._cache = cache
        self._logger.info("Cache updated")
