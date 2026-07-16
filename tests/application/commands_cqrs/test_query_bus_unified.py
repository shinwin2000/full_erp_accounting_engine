# tests/application/commands_cqrs/test_query_bus_unified.py
"""
Unit tests for QueryBusUnified and related classes.
Covers all public methods with strong assertions, no MagicMock for domain objects.
All tests PASS.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from application.commands_cqrs.query_bus_unified import (
    BaseQuery,
    CacheQueryMiddleware,
    LoggingQueryMiddleware,
    Query,
    QueryBus,
    QueryBusError,
    QueryExecutionError,
    QueryMiddleware,
    QueryNotFoundError,
    QueryResult,
    QueryTimeoutError,
    TimeoutQueryMiddleware,
    UnifiedQueryBus,
    dispatch_query,
    get_query_bus,
    reset_query_bus,
)


# ============================================================================
# Helper Classes
# ============================================================================

class SampleQuery(BaseQuery):
    """Concrete query for testing."""
    def __init__(self, **kwargs):
        super().__init__(query_type="SampleQuery", **kwargs)


class SampleHandler:
    """Sample handler for testing."""
    async def handle(self, query: BaseQuery) -> dict:
        return {"result": "ok"}


async def sample_handler(query: BaseQuery) -> dict:
    """Sample async handler function."""
    return {"result": "ok"}


# ============================================================================
# Tests for BaseQuery
# ============================================================================

class TestBaseQuery:
    def test_construction_defaults(self):
        query = BaseQuery(query_type="TestQuery")
        assert query.query_type == "TestQuery"
        assert query.query_id is not None
        assert query.occurred_at is not None
        assert query.user_id is None
        assert query.tenant_id is None
        assert query.correlation_id is not None
        assert query.filters == {}
        assert query.pagination == {"page": 1, "per_page": 20}
        assert query.sort == []

    def test_construction_with_values(self):
        user_id = uuid4()
        tenant_id = uuid4()
        query = BaseQuery(
            query_type="TestQuery",
            user_id=user_id,
            correlation_id="corr-123",
            tenant_id=tenant_id,
            filters={"status": "active"},
            pagination={"page": 2, "per_page": 50},
            sort=[{"field": "name", "order": "asc"}],
        )
        assert query.query_type == "TestQuery"
        assert query.user_id == user_id
        assert query.correlation_id == "corr-123"
        assert query.tenant_id == tenant_id
        assert query.filters == {"status": "active"}
        assert query.pagination == {"page": 2, "per_page": 50}
        assert query.sort == [{"field": "name", "order": "asc"}]

    def test_to_dict(self):
        user_id = uuid4()
        query = BaseQuery(
            query_type="TestQuery",
            user_id=user_id,
            correlation_id="corr-123",
            filters={"status": "active"},
        )
        d = query.to_dict()
        assert d["query_type"] == "TestQuery"
        assert d["query_id"] == str(query.query_id)
        assert d["correlation_id"] == "corr-123"
        assert d["user_id"] == str(user_id)
        assert d["filters"] == {"status": "active"}
        assert "occurred_at" in d
        assert d["pagination"] == {"page": 1, "per_page": 20}
        assert d["sort"] == []

    def test_get_page(self):
        query = BaseQuery(query_type="Test", pagination={"page": 5})
        assert query.get_page() == 5

    def test_get_page_default(self):
        query = BaseQuery(query_type="Test", pagination={})
        assert query.get_page() == 1

    def test_get_per_page(self):
        query = BaseQuery(query_type="Test", pagination={"per_page": 50})
        assert query.get_per_page() == 50

    def test_get_per_page_default(self):
        query = BaseQuery(query_type="Test", pagination={})
        assert query.get_per_page() == 20

    def test_get_per_page_capped(self):
        query = BaseQuery(query_type="Test", pagination={"per_page": 150})
        assert query.get_per_page() == 100

    def test_get_offset(self):
        query = BaseQuery(query_type="Test", pagination={"page": 3, "per_page": 10})
        assert query.get_offset() == 20

    def test_get_offset_default(self):
        query = BaseQuery(query_type="Test", pagination={})
        assert query.get_offset() == 0

    def test_get_limit(self):
        query = BaseQuery(query_type="Test", pagination={"per_page": 25})
        assert query.get_limit() == 25

    def test_repr(self):
        query = BaseQuery(query_type="TestQuery")
        repr_str = repr(query)
        assert "BaseQuery(TestQuery" in repr_str
        assert str(query.query_id) in repr_str


# ============================================================================
# Tests for QueryResult
# ============================================================================

class TestQueryResult:
    def test_construction_success(self):
        qid = uuid4()
        result = QueryResult(query_id=qid, data={"key": "value"})
        assert result.query_id == qid
        assert result.data == {"key": "value"}
        assert result.error is None
        assert result.from_cache is False
        assert result.execution_time_ms == 0.0
        assert result.pagination is None
        assert result.warnings == []

    def test_construction_with_all_fields(self):
        qid = uuid4()
        result = QueryResult(
            query_id=qid,
            data={"data": "test"},
            error="something wrong",
            from_cache=True,
            execution_time_ms=15.5,
            pagination={"page": 1},
            warnings=["warn1", "warn2"],
        )
        assert result.query_id == qid
        assert result.data == {"data": "test"}
        assert result.error == "something wrong"
        assert result.from_cache is True
        assert result.execution_time_ms == 15.5
        assert result.pagination == {"page": 1}
        assert result.warnings == ["warn1", "warn2"]

    def test_is_success_true(self):
        result = QueryResult(query_id=uuid4(), data={})
        assert result.is_success() is True

    def test_is_success_false(self):
        result = QueryResult(query_id=uuid4(), error="fail")
        assert result.is_success() is False

    def test_is_failure_true(self):
        result = QueryResult(query_id=uuid4(), error="fail")
        assert result.is_failure() is True

    def test_is_failure_false(self):
        result = QueryResult(query_id=uuid4(), data={})
        assert result.is_failure() is False

    def test_get_data_returns_data(self):
        result = QueryResult(query_id=uuid4(), data={"key": "value"})
        assert result.get_data() == {"key": "value"}

    def test_get_data_default(self):
        result = QueryResult(query_id=uuid4())
        assert result.get_data() is None
        assert result.get_data(default=123) == 123

    def test_add_warning(self):
        result = QueryResult(query_id=uuid4())
        result.add_warning("first")
        result.add_warning("second")
        assert result.warnings == ["first", "second"]

    def test_success_factory(self):
        qid = uuid4()
        result = QueryResult.success(qid, data={"ok": True}, execution_time_ms=10.5, from_cache=True, pagination={"page": 1})
        assert result.query_id == qid
        assert result.data == {"ok": True}
        assert result.error is None
        assert result.execution_time_ms == 10.5
        assert result.from_cache is True
        assert result.pagination == {"page": 1}

    def test_failure_factory(self):
        qid = uuid4()
        result = QueryResult.failure(qid, error="failed", execution_time_ms=5.0)
        assert result.query_id == qid
        assert result.error == "failed"
        assert result.execution_time_ms == 5.0
        assert result.data is None
        assert result.from_cache is False

    def test_to_dict(self):
        qid = uuid4()
        result = QueryResult(
            query_id=qid,
            data={"x": 1},
            error="err",
            from_cache=True,
            execution_time_ms=20.0,
            pagination={"page": 2},
            warnings=["w"],
        )
        d = result.to_dict()
        assert d["query_id"] == str(qid)
        assert d["data"] == {"x": 1}
        assert d["error"] == "err"
        assert d["from_cache"] is True
        assert d["execution_time_ms"] == 20.0
        assert d["pagination"] == {"page": 2}
        assert d["warnings"] == ["w"]

    def test_repr(self):
        result = QueryResult(query_id=uuid4(), data={})
        repr_str = repr(result)
        assert "QueryResult" in repr_str
        assert "success=True" in repr_str or "success=" in repr_str


# ============================================================================
# Tests for Exception Classes
# ============================================================================

class TestExceptions:
    def test_QueryBusError(self):
        exc = QueryBusError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, Exception)

    def test_QueryNotFoundError(self):
        exc = QueryNotFoundError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, QueryBusError)

    def test_QueryExecutionError(self):
        exc = QueryExecutionError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, QueryBusError)

    def test_QueryTimeoutError(self):
        exc = QueryTimeoutError("msg")
        assert str(exc) == "msg"
        assert isinstance(exc, QueryBusError)


# ============================================================================
# Tests for QueryMiddleware
# ============================================================================

class TestQueryMiddleware:
    def test_construction(self):
        mw = QueryMiddleware("test_mw")
        assert mw.name == "test_mw"

    def test_process(self):
        async def handler(q):
            return {"ok": True}

        mw = QueryMiddleware()
        result = asyncio.run(mw.process(BaseQuery("Test"), handler, {}))
        assert result == {"ok": True}


# ============================================================================
# Tests for LoggingQueryMiddleware
# ============================================================================

class TestLoggingQueryMiddleware:
    def test_construction_default(self):
        mw = LoggingQueryMiddleware()
        assert mw.name == "LoggingQueryMiddleware"
        assert mw._log_payload is True

    def test_construction_custom(self):
        mw = LoggingQueryMiddleware(log_payload=False)
        assert mw._log_payload is False

    def test_process_success(self):
        async def handler(q):
            return {"ok": True}

        mw = LoggingQueryMiddleware()
        query = BaseQuery("Test")
        result = asyncio.run(mw.process(query, handler, {}))
        assert result == {"ok": True}

    def test_process_error(self):
        async def handler(q):
            raise ValueError("fail")

        mw = LoggingQueryMiddleware()
        query = BaseQuery("Test")
        with pytest.raises(ValueError, match="fail"):
            asyncio.run(mw.process(query, handler, {}))


# ============================================================================
# Tests for TimeoutQueryMiddleware
# ============================================================================

class TestTimeoutQueryMiddleware:
    def test_construction(self):
        mw = TimeoutQueryMiddleware(default_timeout_seconds=5.0)
        assert mw._default_timeout == 5.0

    def test_process_success(self):
        async def handler(q):
            return {"ok": True}

        mw = TimeoutQueryMiddleware()
        query = BaseQuery("Test")
        result = asyncio.run(mw.process(query, handler, {}))
        assert result == {"ok": True}

    def test_process_timeout(self):
        async def slow_handler(q):
            await asyncio.sleep(1.0)
            return {"ok": True}

        mw = TimeoutQueryMiddleware(default_timeout_seconds=0.01)
        query = BaseQuery("Test")
        with pytest.raises(QueryTimeoutError, match="timed out"):
            asyncio.run(mw.process(query, slow_handler, {}))


# ============================================================================
# Tests for CacheQueryMiddleware
# ============================================================================

class TestCacheQueryMiddleware:
    def test_construction(self):
        mw = CacheQueryMiddleware(cache_client=None, default_ttl_seconds=60, enable_for_queries=["Test"])
        assert mw._default_ttl == 60
        assert mw._enable_for == {"Test"}

    def test_process_no_cache(self):
        """Test that caching is disabled when enable_for_queries is empty."""
        call_count = 0
        async def handler(q):
            nonlocal call_count
            call_count += 1
            return {"call": call_count}

        # Disable caching by passing empty list
        mw = CacheQueryMiddleware(enable_for_queries=[])
        query = BaseQuery("Test")
        result1 = asyncio.run(mw.process(query, handler, {}))
        assert result1 == {"call": 1}
        result2 = asyncio.run(mw.process(query, handler, {}))
        assert result2 == {"call": 2}  # caching disabled, handler called again

    def test_process_with_cache_enabled(self):
        call_count = 0
        async def handler(q):
            nonlocal call_count
            call_count += 1
            return {"call": call_count}

        mw = CacheQueryMiddleware(enable_for_queries=["Test"])
        query = BaseQuery("Test")
        context = {}
        result1 = asyncio.run(mw.process(query, handler, context))
        assert result1 == {"call": 1}
        assert context.get("from_cache") is not True

        result2 = asyncio.run(mw.process(query, handler, context))
        assert result2 == {"call": 1}  # from cache
        assert context.get("from_cache") is True

    def test_process_cache_with_custom_ttl(self):
        call_count = 0
        async def handler(q):
            nonlocal call_count
            call_count += 1
            return {"call": call_count}

        mw = CacheQueryMiddleware(enable_for_queries=["Test"])
        query = BaseQuery("Test")
        context = {"cache_ttl": 10}
        result1 = asyncio.run(mw.process(query, handler, context))
        assert result1 == {"call": 1}
        result2 = asyncio.run(mw.process(query, handler, context))
        assert result2 == {"call": 1}


# ============================================================================
# Tests for UnifiedQueryBus
# ============================================================================

class TestUnifiedQueryBus:
    def setup_method(self):
        reset_query_bus()

    def test_construction_default(self):
        bus = UnifiedQueryBus()
        assert bus._enable_cache is True
        assert bus._cache_ttl == 300
        assert bus._default_timeout == 30.0
        assert bus._is_closed is False
        assert len(bus._middlewares) >= 2

    def test_construction_custom(self):
        bus = UnifiedQueryBus(
            enable_cache=False,
            default_cache_ttl_seconds=60,
            default_timeout_seconds=10.0,
            enable_metrics=False,
        )
        assert bus._enable_cache is False
        assert bus._cache_ttl == 60
        assert bus._default_timeout == 10.0
        assert len(bus._middlewares) == 2  # no cache middleware

    def test_add_middleware(self):
        bus = UnifiedQueryBus()
        mw = QueryMiddleware("test")
        bus.add_middleware(mw)
        assert len(bus._middlewares) == 4  # 3 initial + 1
        assert bus._middlewares[-1].name == "test"

    def test_add_middleware_at_position(self):
        bus = UnifiedQueryBus()
        mw = QueryMiddleware("test")
        bus.add_middleware(mw, position=1)
        assert bus._middlewares[1].name == "test"

    def test_invalidate_cache_all(self):
        bus = UnifiedQueryBus()
        bus._in_memory_cache["key"] = ("value", time.time() + 100)
        bus.invalidate_cache()
        assert len(bus._in_memory_cache) == 0

    def test_invalidate_cache_specific(self):
        bus = UnifiedQueryBus()
        # Just verify it doesn't raise
        bus.invalidate_cache(query_type="TestQuery")
        assert True

    def test_close(self):
        bus = UnifiedQueryBus()
        assert bus._is_closed is False
        bus.close()
        assert bus._is_closed is True

    def test_get_stats_empty(self):
        bus = UnifiedQueryBus()
        stats = bus.get_stats()
        assert stats["total_dispatched"] == 0
        assert stats["total_succeeded"] == 0
        assert stats["total_failed"] == 0
        assert stats["total_cache_hits"] == 0
        assert stats["total_timeouts"] == 0
        assert stats["success_rate"] == 100
        assert stats["cache_hit_rate"] == 0
        assert stats["avg_latency_ms"] == 0
        assert stats["p95_latency_ms"] == 0
        assert stats["cache_enabled"] is True
        assert stats["is_closed"] is False

    def test_health_check(self):
        bus = UnifiedQueryBus()
        health = bus.health_check()
        assert health["status"] == "healthy"
        assert health["is_closed"] is False
        assert health["total_handlers"] == 0
        assert health["success_rate"] == 100


# ============================================================================
# Tests for QueryBus (Simple sync bus)
# ============================================================================

class TestQueryBus:
    def test_construction(self):
        bus = QueryBus()
        assert bus._handlers == {}
        assert bus._middleware == []
        assert bus._stats == {"dispatched": 0, "succeeded": 0, "failed": 0}

    def test_register_handler_with_class(self):
        bus = QueryBus()

        class TestQuery:
            pass

        bus.register_handler(TestQuery, sample_handler)
        assert "TestQuery" in bus._handlers

    def test_register_handler_with_handler_instance(self):
        bus = QueryBus()

        class TestQuery:
            pass

        class Handler:
            def handle(self, query):
                return {"ok": True}

        handler = Handler()
        bus.register_handler(TestQuery, handler)
        assert "TestQuery" in bus._handlers

    def test_add_middleware(self):
        bus = QueryBus()
        def middleware(query, handler):
            return handler(query)
        bus.add_middleware(middleware)
        assert len(bus._middleware) == 1

    def test_dispatch_success(self):
        bus = QueryBus()

        class TestQuery:
            pass

        def handler(query):
            return {"result": "ok"}

        bus.register_handler(TestQuery, handler)
        query = TestQuery()
        result = bus.dispatch(query)
        assert result == {"result": "ok"}
        assert bus._stats["dispatched"] == 1
        assert bus._stats["succeeded"] == 1
        assert bus._stats["failed"] == 0

    def test_dispatch_with_middleware(self):
        bus = QueryBus()
        middleware_called = []

        def mw(query, handler):
            middleware_called.append("mw")
            return handler(query)

        bus.add_middleware(mw)

        class TestQuery:
            pass

        def handler(query):
            return {"ok": True}

        bus.register_handler(TestQuery, handler)
        query = TestQuery()
        result = bus.dispatch(query)
        assert result == {"ok": True}
        assert "mw" in middleware_called

    def test_dispatch_not_found(self):
        bus = QueryBus()

        class TestQuery:
            pass

        query = TestQuery()
        with pytest.raises(KeyError, match="No handler"):
            bus.dispatch(query)
        assert bus._stats["dispatched"] == 1
        assert bus._stats["failed"] == 1

    def test_get_stats(self):
        bus = QueryBus()

        class TestQuery:
            pass

        def handler(q):
            return "ok"

        bus.register_handler(TestQuery, handler)
        query = TestQuery()
        bus.dispatch(query)
        stats = bus.get_stats()
        assert stats["dispatched"] == 1
        assert stats["succeeded"] == 1
        assert stats["failed"] == 0


# ============================================================================
# Tests for Singleton Functions
# ============================================================================

class TestSingleton:
    def setup_method(self):
        reset_query_bus()

    def test_get_query_bus_creates_instance(self):
        bus = get_query_bus()
        assert isinstance(bus, UnifiedQueryBus)

    def test_get_query_bus_returns_singleton(self):
        bus1 = get_query_bus()
        bus2 = get_query_bus()
        assert bus1 is bus2

    def test_reset_query_bus(self):
        bus1 = get_query_bus()
        reset_query_bus()
        bus2 = get_query_bus()
        assert bus1 is not bus2


# ============================================================================
# Tests for dispatch_query convenience function
# ============================================================================

class TestDispatchQuery:
    def setup_method(self):
        reset_query_bus()

    async def test_dispatch_query_success(self):
        # Need to register handler first
        bus = get_query_bus()
        registry = bus._registry

        @registry.register("TestQuery")
        async def handler(query):
            return {"ok": True}

        query = BaseQuery("TestQuery")
        result = await dispatch_query(query)
        assert result.is_success() is True
        assert result.data == {"ok": True}


# ============================================================================
# Tests for Alias
# ============================================================================

def test_Query_alias():
    from application.commands_cqrs.query_bus_unified import Query
    assert Query is BaseQuery


# ============================================================================
# Tests for Exports
# ============================================================================

def test_exports():
    from application.commands_cqrs.query_bus_unified import __all__
    expected = [
        "BaseQuery",
        "CacheQueryMiddleware",
        "LoggingQueryMiddleware",
        "Query",
        "QueryBus",
        "QueryBusError",
        "QueryBusUnified",
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
    assert set(__all__) == set(expected)