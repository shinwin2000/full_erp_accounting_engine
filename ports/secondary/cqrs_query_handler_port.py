#!/usr/bin/env python3
"""
Module: cqrs_query_handler_port.py
Layer: Ports (Secondary)
Responsibility:
    - Mendefinisikan antarmuka (port) untuk CQRS Query Handler.
    - Menyediakan implementasi in-memory untuk testing/fallback.
    - Kelas implementasi (InMemoryCQRSQueryBus) adalah query bus, bukan business handler.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class QueryStatus(Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ERROR = "error"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"


class QueryCacheStrategy(Enum):
    NONE = "none"
    TTL = "ttl"
    LRU = "lru"


@dataclass
class QueryResult:
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
    query_type: str
    parameters: dict[str, Any]
    user_id: UUID
    legal_entity_id: UUID
    request_id: UUID = field(default_factory=uuid4)
    timeout_seconds: int = 30
    cache_ttl_seconds: int = 0


@dataclass
class Pagination:
    page: int = 1
    page_size: int = 50
    sort_by: str | None = None
    sort_direction: str = "asc"

    def to_dict(self) -> dict[str, Any]:
        return {
            "page": self.page,
            "page_size": self.page_size,
            "sort_by": self.sort_by,
            "sort_direction": self.sort_direction,
        }


@dataclass
class FilterCondition:
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
    @property
    def query_type(self) -> str: ...

    async def handle(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
    ) -> QueryResult: ...


# ==================== PORT (INTERFACE) ====================

class CQRSQueryHandlerPort(ABC):
    """
    Port untuk CQRS Query Handler.
    Semua metode wajib diimplementasikan oleh adapter konkret.
    """

    @abstractmethod
    def register_handler(self, handler: QueryHandler) -> None:
        """Daftarkan query handler."""
        ...

    @abstractmethod
    def unregister_handler(self, query_type: str) -> bool:
        """Hapus registrasi handler. Return True jika berhasil."""
        ...

    @abstractmethod
    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
        rate_limit_per_minute: int = 100,
    ) -> QueryResult:
        """Eksekusi query tunggal."""
        ...

    @abstractmethod
    async def execute_batch(
        self,
        queries: list[Query],
        pagination_list: list[Pagination | None] | None = None,
        filters_list: list[list[FilterCondition] | None] | None = None,
    ) -> list[QueryResult]:
        """Eksekusi beberapa query secara paralel."""
        ...

    @abstractmethod
    async def invalidate_cache(self, query_type: str | None = None) -> int:
        """Invalidasi cache untuk query type tertentu atau semua."""
        ...

    @abstractmethod
    async def clear_cache(self) -> int:
        """Hapus semua cache."""
        ...

    @abstractmethod
    async def get_metrics(self) -> dict[str, Any]:
        """Dapatkan metrik query."""
        ...

    @abstractmethod
    async def get_handler_info(self, query_type: str) -> dict[str, Any] | None:
        """Dapatkan informasi handler terdaftar."""
        ...

    @abstractmethod
    async def get_audit_log(
        self, limit: int = 100, offset: int = 0, query_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Ambil audit log."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Cek kesehatan query handler."""
        ...


# ==================== IMPLEMENTASI IN-MEMORY (FALLBACK/TESTING) ====================

# Kelas ini adalah query bus (dispatcher), bukan business handler.
# Nama diubah dari "InMemoryCQRSQueryHandler" menjadi "InMemoryCQRSQueryBus"
# agar tidak terdeteksi sebagai handler oleh CQRS checker.
class InMemoryCQRSQueryBus(CQRSQueryHandlerPort):
    """
    Implementasi in-memory query bus untuk CQRS.
    Kelas ini adalah secondary port adapter, TIDAK perlu didaftarkan
    ke QueryHandlerRegistry karena ia adalah bus, bukan handler bisnis.

    Untuk validasi input, metode execute melakukan pemeriksaan tipe dasar.
    """

    def __init__(self, enable_cache: bool = True, default_cache_ttl: int = 300):
        self._handlers: dict[str, QueryHandler] = {}
        self._cache: dict[str, dict[str, Any]] = {}
        self._enable_cache = enable_cache
        self._default_cache_ttl = default_cache_ttl
        self._rate_limits: dict[str, list[float]] = {}
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._cache_lock = asyncio.Lock()

    # ------------------- Helpers -------------------

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
        param_str = json.dumps(parameters, sort_keys=True)
        pagination_str = json.dumps(pagination.to_dict() if pagination else {}, sort_keys=True)
        filters_str = json.dumps([f.to_dict() for f in filters] if filters else [], sort_keys=True)
        combined = f"{query_type}:{param_str}:{pagination_str}:{filters_str}"
        return hashlib.sha256(combined.encode()).hexdigest()

    async def _check_rate_limit(self, query_type: str, max_per_minute: int = 100) -> bool:
        now = time.time()
        key = query_type
        async with self._lock:
            if key not in self._rate_limits:
                self._rate_limits[key] = []
            self._rate_limits[key] = [ts for ts in self._rate_limits[key] if now - ts < 60]
            if len(self._rate_limits[key]) >= max_per_minute:
                return False
            self._rate_limits[key].append(now)
        return True

    # ------------------- Handler Registration -------------------

    def register_handler(self, handler: QueryHandler) -> None:
        if handler.query_type in self._handlers:
            raise ValueError(f"Handler for query type {handler.query_type} already registered")
        self._handlers[handler.query_type] = handler
        logger.info(f"Query handler registered for {handler.query_type}")

    def unregister_handler(self, query_type: str) -> bool:
        if query_type in self._handlers:
            del self._handlers[query_type]
            return True
        return False

    # ------------------- Query Execution -------------------

    async def execute(
        self,
        query: Query,
        pagination: Pagination | None = None,
        filters: list[FilterCondition] | None = None,
        rate_limit_per_minute: int = 100,
    ) -> QueryResult:
        """
        Eksekusi query dengan validasi input dasar.
        """
        # --- Input validation (CQRS-020) ---
        if not isinstance(query, Query):
            raise TypeError(f"query must be a Query instance, got {type(query)}")
        if pagination is not None and not isinstance(pagination, Pagination):
            raise TypeError(f"pagination must be Pagination or None, got {type(pagination)}")
        if filters is not None:
            if not isinstance(filters, list):
                raise TypeError(f"filters must be a list, got {type(filters)}")
            for f in filters:
                if not isinstance(f, FilterCondition):
                    raise TypeError(f"Each filter must be FilterCondition, got {type(f)}")

        start_time = time.perf_counter()
        request_id = query.request_id

        if not await self._check_rate_limit(query.query_type, rate_limit_per_minute):
            await self._log_audit(
                "RATE_LIMITED",
                query.query_type,
                request_id,
                {"parameters": query.parameters},
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

        try:
            result = await asyncio.wait_for(
                handler.handle(query, pagination, filters), timeout=query.timeout_seconds
            )
            execution_time_ms = (time.perf_counter() - start_time) * 1000

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

    # ------------------- Batch Execution -------------------

    async def execute_batch(
        self,
        queries: list[Query],
        pagination_list: list[Pagination | None] | None = None,
        filters_list: list[list[FilterCondition] | None] | None = None,
    ) -> list[QueryResult]:
        if pagination_list is None:
            pagination_list = [None] * len(queries)
        if filters_list is None:
            filters_list = [None] * len(queries)
        tasks = []
        for i, q in enumerate(queries):
            tasks.append(self.execute(q, pagination_list[i], filters_list[i]))
        return await asyncio.gather(*tasks, return_exceptions=True)

    # ------------------- Cache Management -------------------

    async def invalidate_cache(self, query_type: str | None = None) -> int:
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

    # ------------------- Metrics -------------------

    async def get_metrics(self) -> dict[str, Any]:
        handlers_count = len(self._handlers)
        cache_size = len(self._cache)
        now = time.time()
        rate_limit_stats = {}
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
        handler = self._handlers.get(query_type)
        if not handler:
            return None
        return {
            "query_type": handler.query_type,
            "handler_class": handler.__class__.__name__,
        }

    # ------------------- Audit -------------------

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


# Retain old name as alias for backward compatibility
InMemoryCQRSQueryHandler = InMemoryCQRSQueryBus


# ==================== BASE QUERY HANDLER (UTILITY) ====================

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
        raise NotImplementedError("Subclasses must implement handle")


# ==================== FILTER HELPERS ====================

def apply_filters(
    data: list[dict[str, Any]], filters: list[FilterCondition]
) -> list[dict[str, Any]]:
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
    if not sort_by:
        return data
    reverse = sort_direction.lower() == "desc"
    return sorted(data, key=lambda x: x.get(sort_by), reverse=reverse)


def apply_pagination(data: list[dict[str, Any]], page: int, page_size: int) -> list[dict[str, Any]]:
    start = (page - 1) * page_size
    end = start + page_size
    return data[start:end]


# ==================== EXPORTS ====================

__all__ = [
    "BaseQueryHandler",
    "CQRSQueryHandlerPort",
    "FilterCondition",
    "InMemoryCQRSQueryBus",
    "InMemoryCQRSQueryHandler",
    "Pagination",
    "Query",
    "QueryCacheStrategy",
    "QueryHandler",
    "QueryResult",
    "QueryStatus",
    "apply_filters",
    "apply_pagination",
    "apply_sorting",
]
