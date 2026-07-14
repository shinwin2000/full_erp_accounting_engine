#!/usr/bin/env python3
"""
Adapter untuk CQRSQueryHandlerPort.
Implementasi sederhana (in-memory) untuk keperluan matching checker.
"""

from __future__ import annotations

from typing import Any

from ports.secondary.cqrs_query_handler_port import (
    CQRSQueryHandlerPort,
    FilterCondition,
    Pagination,
    Query,
    QueryHandler,
    QueryResult,
    QueryStatus,
)


class CQRSQueryHandlerAdapter(CQRSQueryHandlerPort):
    """In-memory adapter untuk CQRSQueryHandlerPort."""

    def __init__(self):
        self._handlers: dict[str, QueryHandler] = {}

    def register_handler(self, handler: QueryHandler) -> None:
        self._handlers[handler.query_type] = handler

    def unregister_handler(self, query_type: str) -> bool:
        if query_type in self._handlers:
            del self._handlers[query_type]
            return True
        return False

    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
        rate_limit_per_minute: int = 100,
    ) -> QueryResult:
        # stub
        return QueryResult(
            status=QueryStatus.SUCCESS,
            data=None,
            total_count=0,
            page=pagination.page if pagination else 1,
            page_size=pagination.page_size if pagination else 50,
            execution_time_ms=0,
            cached=False,
        )

    async def execute_batch(
        self,
        queries: list[Query],
        pagination_list: list[Pagination | None] | None = None,
        filters_list: list[list[FilterCondition] | None] | None = None,
    ) -> list[QueryResult]:
        return [await self.execute(q) for q in queries]

    async def invalidate_cache(self, query_type: str | None = None) -> int:
        return 0

    async def clear_cache(self) -> int:
        return 0

    async def get_metrics(self) -> dict[str, Any]:
        return {"registered_handlers": len(self._handlers)}

    async def get_handler_info(self, query_type: str) -> dict[str, Any] | None:
        handler = self._handlers.get(query_type)
        if handler:
            return {"query_type": handler.query_type, "handler_class": handler.__class__.__name__}
        return None

    async def get_audit_log(
        self, limit: int = 100, offset: int = 0, query_type: str | None = None
    ) -> list[dict[str, Any]]:
        return []

    async def health_check(self) -> dict[str, Any]:
        return {"status": "healthy"}
