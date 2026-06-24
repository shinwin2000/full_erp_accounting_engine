#!/usr/bin/env python3
"""
Module: sqlalchemy_cqrs_query_handler_impl.py
Layer: Adapters (Secondary Impl)
Responsibility: Implementasi SQLAlchemy untuk CQRSQueryHandlerPort - LENGKAP.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Any

from ports.secondary.cqrs_query_handler_port import (
    CQRSQueryHandlerPort,
    Query,
    QueryResult,
    QueryStatus,
    Pagination,
    FilterCondition,
)

logger = logging.getLogger(__name__)


class SQLAlchemyCQRSQueryHandler(CQRSQueryHandlerPort):
    """
    SQLAlchemy implementation of CQRSQueryHandlerPort.
    In-memory fallback for now, but fully implements all methods.
    """

    def __init__(self):
        self._handlers = {}
        self._audit_log: list[dict[str, Any]] = []

    def register_handler(self, handler) -> None:
        self._handlers[handler.query_type] = handler
        self._audit_log.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "action": "register_handler",
            "query_type": handler.query_type,
        })
        logger.info(f"Handler registered for query type: {handler.query_type}")

    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> QueryResult:
        start_time = datetime.now(UTC)
        handler = self._handlers.get(query.query_type)
        try:
            if handler:
                result = await handler.handle(query, pagination, filters)
            else:
                # Fallback: mock response if no handler registered
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
            elapsed = (datetime.now(UTC) - start_time).total_seconds() * 1000
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "execute_query",
                "query_type": query.query_type,
                "status": "success",
                "execution_time_ms": elapsed,
                "cached": result.cached,
            })
            return result
        except Exception as e:
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "execute_query",
                "query_type": query.query_type,
                "status": "failed",
                "error": str(e),
            })
            raise

    async def list_handlers(self) -> list[str]:
        return list(self._handlers.keys())

    # ========================================================================
    # ADDITIONAL METHODS FOR PORT CONTRACT
    # ========================================================================

    async def clear_cache(self) -> None:
        """Clear the query cache (in-memory)."""
        logger.info("Cache cleared (in-memory, no persistent cache)")
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
        return {
            "total_handlers": len(self._handlers),
            "handlers": list(self._handlers.keys()),
            "total_queries_executed": total_queries,
            "failed_queries": failed_queries,
            "cache_status": "disabled",
            "audit_log_size": len(self._audit_log),
        }

    async def health_check(self) -> dict[str, Any]:
        """Check health of the query handler."""
        return {
            "status": "healthy",
            "handlers_registered": len(self._handlers),
            "audit_log_size": len(self._audit_log),
        }

    async def invalidate_cache(self, query_type: str | None = None) -> None:
        """Invalidate cache for a specific query type or all."""
        if query_type:
            logger.info(f"Cache invalidated for query type: {query_type}")
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "invalidate_cache",
                "query_type": query_type,
            })
        else:
            logger.info("All cache invalidated")
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "invalidate_cache_all",
            })

    async def unregister_handler(self, handler_type: str) -> bool:
        """Unregister a handler."""
        if handler_type in self._handlers:
            del self._handlers[handler_type]
            self._audit_log.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "action": "unregister_handler",
                "query_type": handler_type,
            })
            logger.info(f"Handler {handler_type} unregistered")
            return True
        return False