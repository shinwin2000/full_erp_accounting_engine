#!/usr/bin/env python3
"""
Module: cqrs_query_handler_port.py
Layer: Ports (Secondary)
Responsibility: Antarmuka dan implementasi in-memory untuk CQRS Query Handler.
               Mendukung registrasi query handler, query bus, pagination,
               sorting, filtering, caching (opsional), logging, audit,
               timeout, rate limiting, dan metrics.
Audit: Setiap query yang dieksekusi tercatat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class QueryStatus(Enum):
    """Status hasil query."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class QueryCacheStrategy(Enum):
    """Strategi cache untuk query."""

    NONE = "none"
    TTL = "ttl"
    LRU = "lru"


@dataclass
class QueryResult:
    """Hasil query standard."""

    status: QueryStatus
    data: Any
    total_count: int | None
    page: int | None
    page_size: int | None
    execution_time_ms: float
    cached: bool
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "total_count": self.total_count,
            "page": self.page,
            "page_size": self.page_size,
            "execution_time_ms": self.execution_time_ms,
            "cached": self.cached,
            "error_message": self.error_message,
        }


@dataclass
class Query:
    """Query object."""

    query_type: str
    parameters: dict[str, Any]
    user_id: UUID
    legal_entity_id: UUID
    request_id: UUID = field(default_factory=uuid4)
    timeout_seconds: int = 30
    cache_ttl_seconds: int = 0  # 0 = no cache


@dataclass
class Pagination:
    """Pagination parameters."""

    page: int = 1
    page_size: int = 50
    sort_by: str | None = None
    sort_direction: str = "asc"  # asc / desc

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "page_size": self.page_size,
            "sort_by": self.sort_by,
            "sort_direction": self.sort_direction,
        }


@dataclass
class FilterCondition:
    """Filter condition."""

    field: str
    operator: str  # eq, ne, gt, gte, lt, lte, contains, in, between
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "operator": self.operator,
            "value": self.value,
        }


class QueryHandler(Protocol):
    """Protocol untuk query handler."""

    @property
    def query_type(self) -> str: ...
    async def handle(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> QueryResult: ...


class CQRSQueryHandlerPort:
    """
    In-memory query bus untuk CQRS.
    """

    def __init__(self, enable_cache: bool = True, default_cache_ttl: int = 300):
        self._handlers: dict[str, QueryHandler] = {}
        self._cache: dict[str, dict[str, Any]] = {}  # cache_key -> (data, expiry)
        self._enable_cache = enable_cache
        self._default_cache_ttl = default_cache_ttl
        self._rate_limits: dict[str, list[float]] = {}  # query_type -> list of timestamps
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()

    # ==================== HELPER ====================

    async def _log_audit(
        self, action: str, query_type: str, request_id: UUID, details: dict[str, Any]
    ):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "query_type": query_type,
            "request_id": str(request_id),
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"CQRS QUERY AUDIT: {action} for {query_type} (req={request_id})")

    async def _generate_cache_key(
        self,
        query_type: str,
        parameters: dict[str, Any],
        pagination: Pagination | None,
        filters: list[FilterCondition] | None,
    ) -> str:
        """Generate cache key dari query."""
        # Hash dari parameter, pagination, filters
        param_str = json.dumps(parameters, sort_keys=True)
        pagination_str = json.dumps(pagination.to_dict() if pagination else {}, sort_keys=True)
        filters_str = json.dumps([f.to_dict() for f in filters] if filters else [], sort_keys=True)
        combined = f"{query_type}:{param_str}:{pagination_str}:{filters_str}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def _check_rate_limit(self, query_type: str, max_per_minute: int = 100) -> bool:
        """Check rate limit per query type."""
        now = time.time()
        key = query_type
        async with self._lock:
            if key not in self._rate_limits:
                self._rate_limits[key] = []
            # Clean old entries
            self._rate_limits[key] = [ts for ts in self._rate_limits[key] if now - ts < 60]
            if len(self._rate_limits[key]) >= max_per_minute:
                return False
            self._rate_limits[key].append(now)
        return True

    # ==================== HANDLER REGISTRATION ====================

    def register_handler(self, handler: QueryHandler) -> None:
        """Daftarkan query handler."""
        if handler.query_type in self._handlers:
            raise ValueError(f"Handler for query type {handler.query_type} already registered")
        self._handlers[handler.query_type] = handler
        logger.info(f"Query handler registered for {handler.query_type}")

    def unregister_handler(self, query_type: str) -> bool:
        if query_type in self._handlers:
            del self._handlers[query_type]
            return True
        return False

    # ==================== QUERY EXECUTION ====================

    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
        rate_limit_per_minute: int = 100,
    ) -> QueryResult:
        """Execute a query."""
        start_time = time.perf_counter()
        request_id = query.request_id

        # Rate limit check
        if not await self._check_rate_limit(query.query_type, rate_limit_per_minute):
            await self._log_audit(
                "RATE_LIMITED",
                query.query_type,
                request_id,
                {
                    "parameters": query.parameters,
                },
            )
            return QueryResult(
                status=QueryStatus.RATE_LIMITED,
                data=None,
                total_count=None,
                page=pagination.page if pagination else None,
                page_size=pagination.page_size if pagination else None,
                execution_time_ms=0,
                cached=False,
                error_message="Rate limit exceeded",
            )

        # Cache check
        cache_key = None
        if self._enable_cache and query.cache_ttl_seconds > 0:
            cache_key = await self._generate_cache_key(
                query.query_type, query.parameters, pagination, filters
            )
            async with self._cache_lock:
                cached = self._cache.get(cache_key)
                if cached and cached.get("expiry", 0) > time.time():
                    await self._log_audit("CACHE_HIT", query.query_type, request_id, {})
                    return QueryResult(
                        status=QueryStatus.SUCCESS,
                        data=cached["data"],
                        total_count=cached.get("total_count"),
                        page=pagination.page if pagination else None,
                        page_size=pagination.page_size if pagination else None,
                        execution_time_ms=0,
                        cached=True,
                        error_message=None,
                    )

        # Find handler
        handler = self._handlers.get(query.query_type)
        if not handler:
            await self._log_audit("HANDLER_NOT_FOUND", query.query_type, request_id, {})
            return QueryResult(
                status=QueryStatus.ERROR,
                data=None,
                total_count=None,
                page=pagination.page if pagination else None,
                page_size=pagination.page_size if pagination else None,
                execution_time_ms=0,
                cached=False,
                error_message=f"No handler for query type {query.query_type}",
            )

        # Execute with timeout
        try:
            result = await asyncio.wait_for(
                handler.handle(query, pagination, filters), timeout=query.timeout_seconds
            )
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Cache result
            if cache_key and result.status == QueryStatus.SUCCESS and query.cache_ttl_seconds > 0:
                async with self._cache_lock:
                    self._cache[cache_key] = {
                        "data": result.data,
                        "total_count": result.total_count,
                        "expiry": time.time() + query.cache_ttl_seconds,
                    }

            await self._log_audit(
                "EXECUTE",
                query.query_type,
                request_id,
                {
                    "status": result.status.value,
                    "execution_time_ms": execution_time_ms,
                    "cached": result.cached,
                },
            )
            return result

        except TimeoutError:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            await self._log_audit(
                "TIMEOUT", query.query_type, request_id, {"timeout": query.timeout_seconds}
            )
            return QueryResult(
                status=QueryStatus.TIMEOUT,
                data=None,
                total_count=None,
                page=pagination.page if pagination else None,
                page_size=pagination.page_size if pagination else None,
                execution_time_ms=execution_time_ms,
                cached=False,
                error_message=f"Query timeout after {query.timeout_seconds}s",
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            await self._log_audit("ERROR", query.query_type, request_id, {"error": str(e)})
            return QueryResult(
                status=QueryStatus.ERROR,
                data=None,
                total_count=None,
                page=pagination.page if pagination else None,
                page_size=pagination.page_size if pagination else None,
                execution_time_ms=execution_time_ms,
                cached=False,
                error_message=str(e),
            )

    # ==================== BATCH EXECUTION ====================

    async def execute_batch(
        self,
        queries: list[Query],
        pagination_list: list[Pagination | None] | None = None,
        filters_list: list[list[FilterCondition] | None] | None = None,
    ) -> list[QueryResult]:
        """Execute multiple queries in parallel (batch)."""
        if pagination_list is None:
            pagination_list = [None] * len(queries)
        if filters_list is None:
            filters_list = [None] * len(queries)
        tasks = []
        for i, q in enumerate(queries):
            tasks.append(self.execute(q, pagination_list[i], filters_list[i]))
        return await asyncio.gather(*tasks, return_exceptions=True)

    # ==================== CACHE MANAGEMENT ====================

    async def invalidate_cache(self, query_type: str | None = None) -> int:
        """Invalidate cache for specific query type or all."""
        if query_type is None:
            count = len(self._cache)
            async with self._cache_lock:
                self._cache.clear()
            await self._log_audit("INVALIDATE_CACHE_ALL", "system", UUID(int=0), {"count": count})
            return count
        else:
            count = 0
            keys_to_remove = []
            async with self._cache_lock:
                for key in self._cache:
                    if key.startswith(f"{query_type}:"):
                        keys_to_remove.append(key)
                for key in keys_to_remove:
                    del self._cache[key]
                    count += 1
            await self._log_audit(
                "INVALIDATE_CACHE_TYPE", query_type, UUID(int=0), {"count": count}
            )
            return count

    async def clear_cache(self) -> int:
        return await self.invalidate_cache(None)

    # ==================== METRICS ====================

    async def get_metrics(self) -> dict[str, Any]:
        """Get query metrics."""
        handlers_count = len(self._handlers)
        cache_size = len(self._cache)
        # Aggregated rate limits
        rate_limit_stats = {}
        now = time.time()
        for qtype, timestamps in self._rate_limits.items():
            rate_limit_stats[qtype] = len([ts for ts in timestamps if now - ts < 60])
        return {
            "registered_handlers": handlers_count,
            "query_types": list(self._handlers.keys()),
            "cache_enabled": self._enable_cache,
            "cache_size": cache_size,
            "default_cache_ttl_seconds": self._default_cache_ttl,
            "rate_limits": rate_limit_stats,
            "audit_log_size": len(self._audit_log),
        }

    async def get_handler_info(self, query_type: str) -> dict[str, Any] | None:
        """Get information about registered handler."""
        handler = self._handlers.get(query_type)
        if not handler:
            return None
        return {
            "query_type": handler.query_type,
            "handler_class": handler.__class__.__name__,
        }

    # ==================== AUDIT ====================

    async def get_audit_log(
        self, limit: int = 100, offset: int = 0, query_type: str | None = None
    ) -> list[dict[str, Any]]:
        result = self._audit_log
        if query_type:
            result = [log for log in result if log.get("query_type") == query_type]
        return result[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "registered_handlers": len(self._handlers),
            "cache_size": len(self._cache),
            "cache_enabled": self._enable_cache,
            "audit_log_size": len(self._audit_log),
        }


# ==================== BASE QUERY HANDLER ====================


class BaseQueryHandler:
    """Base class untuk query handler (bisa di-extends)."""

    def __init__(self, query_type: str):
        self._query_type = query_type

    @property
    def query_type(self) -> str:
        return self._query_type

    async def handle(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> QueryResult:
        """Override this method."""
        raise NotImplementedError("Subclasses must implement handle")


# ==================== FILTER HELPER ====================


def apply_filters(
    data: list[dict[str, Any]], filters: list[FilterCondition]
) -> list[dict[str, Any]]:
    """Apply filters to list of dict data."""
    result = data
    for f in filters:
        field = f.field
        operator = f.operator
        value = f.value
        if operator == "eq":
            result = [item for item in result if item.get(field) == value]
        elif operator == "ne":
            result = [item for item in result if item.get(field) != value]
        elif operator == "gt":
            result = [item for item in result if item.get(field) > value]
        elif operator == "gte":
            result = [item for item in result if item.get(field) >= value]
        elif operator == "lt":
            result = [item for item in result if item.get(field) < value]
        elif operator == "lte":
            result = [item for item in result if item.get(field) <= value]
        elif operator == "contains":
            result = [item for item in result if value in str(item.get(field, ""))]
        elif operator == "in":
            result = [item for item in result if item.get(field) in value]
        elif operator == "between":
            min_val, max_val = value
            result = [item for item in result if min_val <= item.get(field) <= max_val]
    return result


def apply_sorting(
    data: list[dict[str, Any]], sort_by: str | None, sort_direction: str
) -> list[dict[str, Any]]:
    """Apply sorting to list of dict data."""
    if not sort_by:
        return data
    reverse = sort_direction.lower() == "desc"
    return sorted(data, key=lambda x: x.get(sort_by), reverse=reverse)


def apply_pagination(data: list[dict[str, Any]], page: int, page_size: int) -> list[dict[str, Any]]:
    """Apply pagination to list of dict data."""
    start = (page - 1) * page_size
    end = start + page_size
    return data[start:end]
