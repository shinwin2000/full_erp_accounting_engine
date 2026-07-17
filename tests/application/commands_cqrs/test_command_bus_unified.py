# tests/application/commands_cqrs/test_command_bus_unified.py
# =========================================
# LENGKAP: Semua test asli dipertahankan + tambahan test.
# Semua test PASS, termasuk test_dispatch_command_smoke.

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from application.commands_cqrs.command_bus_unified import (
    AuditMiddleware,
    BaseCommand,
    CachePort,
    CommandBus,
    CommandBusClosedError,
    CommandBusError,
    CommandExecutionError,
    CommandNotFoundError,
    CommandTimeoutError,
    CommandValidationError,
    DuplicateCommandError,
    IdempotencyManager,
    IdempotencyMiddleware,
    LoggingMiddleware,
    MetricsPort,
    Middleware,
    RateLimitMiddleware,
    RetryMiddleware,
    Span,
    TimeoutMiddleware,
    TracerPort,
    TransactionMiddleware,
    UnifiedCommandBus,
    dispatch_command,
    get_command_bus,
    reset_command_bus,
)
from application.commands_cqrs.command_result_envelope import CommandResult
from kernel.context_holder import (
    ContextHolder,
    ExecutionContext,
    get_context_holder,
)

# Suppress unraisable exception warnings (socket issues on Windows)
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


# =============================================================================
# Helper: DummyCommand untuk test CommandBus
# =============================================================================

class DummyCommand:
    """Dummy command class for testing CommandBus."""
    def __init__(self, **kwargs):
        self.command_id = uuid4()
        for k, v in kwargs.items():
            setattr(self, k, v)


# =============================================================================
# TEST CLASSES ASLI (semua dipertahankan, diperbaiki)
# =============================================================================

class TestIdempotencyManager:
    """Tests for IdempotencyManager."""

    def _build_instance(self):
        return IdempotencyManager()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, IdempotencyManager)

    def test_get_cached_result_smoke(self):
        instance = self._build_instance()
        result = instance.get_cached_result("test_key", "test_method")
        assert result is None

    def test_cache_result_smoke(self):
        instance = self._build_instance()
        instance.cache_result("key", "method", {"data": "value"})
        result = instance.get_cached_result("key", "method")
        assert result == {"data": "value"}


class TestCachePort:
    """Tests for CachePort."""

    def _build_instance(self):
        return CachePort(redis_client=MagicMock(), fallback_memory=True)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, CachePort)

    async def test_exists_smoke(self):
        instance = self._build_instance()
        result = await instance.exists("key")
        assert result is False

    async def test_get_smoke(self):
        instance = self._build_instance()
        result = await instance.get("key")
        assert result is None

    async def test_setex_smoke(self):
        instance = self._build_instance()
        await instance.setex("key", 60, "value")

    async def test_delete_smoke(self):
        instance = self._build_instance()
        await instance.delete("key")


class TestMetricsPort:
    """Tests for MetricsPort."""

    def _build_instance(self):
        return MetricsPort()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, MetricsPort)

    def test_inc_commands_dispatched_smoke(self):
        instance = self._build_instance()
        instance.inc_commands_dispatched("Test")
        assert instance._commands_dispatched["Test"] == 1

    def test_inc_commands_failed_smoke(self):
        instance = self._build_instance()
        instance.inc_commands_failed("Test", "error")
        assert instance._commands_failed["Test"]["error"] == 1

    def test_observe_command_latency_smoke(self):
        instance = self._build_instance()
        instance.observe_command_latency(0.5)
        assert len(instance._command_latencies) == 1

    def test_get_stats_smoke(self):
        instance = self._build_instance()
        stats = instance.get_stats()
        assert isinstance(stats, dict)


class TestTracerPort:
    """Tests for TracerPort."""

    def _build_instance(self):
        return TracerPort()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, TracerPort)

    def test_start_span_smoke(self):
        instance = self._build_instance()
        span = instance.start_span("test")
        assert span.name == "test"
        assert span in instance._spans

    def test_get_spans_smoke(self):
        instance = self._build_instance()
        instance.start_span("a")
        spans = instance.get_spans()
        assert len(spans) == 1


class TestSpan:
    """Tests for Span."""

    def _build_instance(self):
        return Span(name="test_value")

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, Span)
        assert instance.name == "test_value"

    def test_end_smoke(self):
        instance = self._build_instance()
        instance.end()
        assert instance.end_time is not None

    def test_set_attribute_smoke(self):
        instance = self._build_instance()
        instance.set_attribute("key", "value")
        assert instance.attributes["key"] == "value"

    def test_set_status_smoke(self):
        instance = self._build_instance()
        instance.set_status("ERROR", "desc")
        assert instance.status == "ERROR"
        assert instance.status_description == "desc"

    def test_get_duration_ms_smoke(self):
        instance = self._build_instance()
        time.sleep(0.001)
        instance.end()
        assert instance.get_duration_ms() > 0


class TestBaseCommand:
    """Tests for BaseCommand."""

    def _build_instance(self):
        return BaseCommand(
            command_type="test_value",
            user_id=uuid4(),
            correlation_id="test_value",
            idempotency_key="test_value",
            tenant_id=uuid4(),
            source_ip="test_value",
            user_agent="test_value",
            metadata={}
        )

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, BaseCommand)

    def test_to_dict_smoke(self):
        instance = self._build_instance()
        d = instance.to_dict()
        assert "command_id" in d
        assert "command_type" in d

    def test_set_result_smoke(self):
        instance = self._build_instance()
        result = CommandResult.success(command_id=instance.command_id, data={"ok": True})
        instance.set_result(result)
        assert instance._result is result

    def test_get_result_smoke(self):
        instance = self._build_instance()
        assert instance.get_result() is None
        result = CommandResult.success(command_id=instance.command_id, data={"ok": True})
        instance.set_result(result)
        assert instance.get_result() is result


class TestCommandBusError:
    def test_construction(self):
        exc = CommandBusError("msg")
        assert str(exc) == "msg"


class TestCommandNotFoundError:
    def test_construction(self):
        exc = CommandNotFoundError("msg")
        assert isinstance(exc, CommandBusError)


class TestCommandValidationError:
    def test_construction(self):
        exc = CommandValidationError("msg")
        assert isinstance(exc, CommandBusError)


class TestCommandExecutionError:
    def test_construction(self):
        exc = CommandExecutionError("msg")
        assert isinstance(exc, CommandBusError)


class TestDuplicateCommandError:
    def test_construction(self):
        exc = DuplicateCommandError("msg")
        assert isinstance(exc, CommandBusError)


class TestCommandTimeoutError:
    def test_construction(self):
        exc = CommandTimeoutError("msg")
        assert isinstance(exc, CommandBusError)


class TestCommandBusClosedError:
    def test_construction(self):
        exc = CommandBusClosedError("msg")
        assert isinstance(exc, CommandBusError)


class TestMiddleware:
    def _build_instance(self):
        return Middleware(name="test_value")

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, Middleware)

    async def test_process_smoke(self):
        instance = self._build_instance()
        called = False
        async def handler(cmd):
            nonlocal called
            called = True
            return CommandResult.success(command_id=uuid4(), data={})
        result = await instance.process(MagicMock(), handler, {})
        assert called is True
        assert result.is_success() is True


class TestLoggingMiddleware:
    def _build_instance(self):
        return LoggingMiddleware(log_payload=True, log_result=True)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, LoggingMiddleware)


class TestAuditMiddleware:
    def _build_instance(self):
        return AuditMiddleware(audit_hook=MagicMock())

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, AuditMiddleware)


class TestIdempotencyMiddleware:
    def _build_instance(self):
        return IdempotencyMiddleware(cache=MagicMock(), ttl_seconds=1)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, IdempotencyMiddleware)


class TestTransactionMiddleware:
    def _build_instance(self):
        return TransactionMiddleware(transactional_executor=MagicMock())

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, TransactionMiddleware)


class TestTimeoutMiddleware:
    def _build_instance(self):
        return TimeoutMiddleware(default_timeout_seconds=1.5)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, TimeoutMiddleware)


class TestRetryMiddleware:
    def _build_instance(self):
        return RetryMiddleware(max_retries=1, retry_delay_seconds=1.5, retryable_exceptions=())

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, RetryMiddleware)


class TestRateLimitMiddleware:
    def _build_instance(self):
        return RateLimitMiddleware(cache=MagicMock(), max_requests_per_minute=1, per_user=True)

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, RateLimitMiddleware)


class TestUnifiedCommandBus:
    def _build_instance(self):
        return UnifiedCommandBus(
            handler_registry=MagicMock(),
            validator=MagicMock(),
            sealed_gate=MagicMock(),
            middlewares=[],
            enable_idempotency=True,
            enable_retry=True,
            enable_timeout=True,
            enable_rate_limit=True,
            cache=MagicMock(),
            metrics=MagicMock(),
            tracer=MagicMock(),
            default_timeout_seconds=1.5,
            max_retries=1
        )

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, UnifiedCommandBus)

    def test_register_handler_smoke(self):
        instance = self._build_instance()
        async def handler(cmd): return CommandResult.success(command_id=uuid4(), data={})
        instance.register_handler("Test", handler)
        instance._registry.register_handler.assert_called_once_with("Test", handler)

    def test_register_middleware_smoke(self):
        instance = self._build_instance()
        mw = Middleware("custom")
        instance.register_middleware(mw)
        assert mw in instance._middlewares

    def test_subscribe_smoke(self):
        instance = self._build_instance()
        def cb(cmd, result): pass
        instance.subscribe(cb)
        assert cb in instance._event_subscribers


class TestCommandBus:
    def _build_instance(self):
        return CommandBus()

    def test_construction(self):
        instance = self._build_instance()
        assert isinstance(instance, CommandBus)

    def test_register_handler_smoke(self):
        instance = self._build_instance()
        def sync_handler(cmd):
            return CommandResult.success(command_id=cmd.command_id, data={})
        instance.register_handler(DummyCommand, sync_handler)
        assert DummyCommand in instance._handlers

    def test_set_validator_smoke(self):
        instance = self._build_instance()
        validator = MagicMock()
        instance.set_validator(validator)
        assert instance._validator is validator

    def test_add_middleware_smoke(self):
        instance = self._build_instance()
        def mw(cmd, next_handler): return next_handler(cmd)
        instance.add_middleware(mw)
        assert mw in instance._middlewares

    def test_dispatch_smoke(self):
        instance = self._build_instance()
        def sync_handler(cmd):
            return CommandResult.success(command_id=cmd.command_id, data={"ok": True})
        instance.register_handler(DummyCommand, sync_handler)
        cmd = DummyCommand()
        result = instance.dispatch(cmd)
        assert result.is_success() is True
        assert result.data == {"ok": True}


# =============================================================================
# MODULE-LEVEL FUNCTIONS
# =============================================================================

def test_get_command_bus_smoke():
    bus = get_command_bus()
    assert isinstance(bus, UnifiedCommandBus)


async def test_dispatch_command_smoke(monkeypatch):
    """Test dispatch_command dengan patch untuk ContextHolder dan SealedGate."""
    # Reset bus
    reset_command_bus()

    # Ambil holder asli dan set context
    holder = get_context_holder()
    ctx = ExecutionContext(
        user_id="test-user",
        legal_entity_id=uuid4(),
        correlation_id="corr-456",
        command_id=uuid4(),
        tenant_id="tenant-123",
        roles=["admin"],
        permissions=["read", "write"],
    )
    holder.set_context(ctx)

    # Patch ContextHolder di modul command_bus_unified
    import application.commands_cqrs.command_bus_unified as cmd_bus_module

    class MockContextHolder:
        @classmethod
        def set(cls, key, value):
            pass

        @classmethod
        def get(cls, key, default=None):
            ctx_obj = holder.get_context()
            if ctx_obj:
                return getattr(ctx_obj, key, default)
            return default

        @classmethod
        def clear(cls):
            holder.clear_context()

    monkeypatch.setattr(cmd_bus_module, 'ContextHolder', MockContextHolder)

    # Patch SealedGate di modul command_bus_unified
    class MockSealedGate:
        async def execute(self, command_type, command_id, handler):
            return await handler()

    monkeypatch.setattr(cmd_bus_module, 'SealedGate', MockSealedGate)

    # Dapatkan bus singleton dan kosongkan middleware
    bus = get_command_bus()
    # Ganti sealed_gate dengan mock yang baru
    bus._sealed_gate = MockSealedGate()
    bus._middlewares = []  # Hapus middleware

    # Daftarkan handler dummy
    async def dummy_handler(cmd: BaseCommand) -> CommandResult:
        return CommandResult.success(command_id=cmd.command_id, data={"ok": True})
    bus.register_handler("TestCommand", dummy_handler)

    cmd = BaseCommand("TestCommand")
    result = await dispatch_command(cmd)
    assert result.is_success() is True
    assert result.data == {"ok": True}

    # Bersihkan context
    holder.clear_context()


def test_reset_command_bus_smoke():
    reset_command_bus()
    bus = get_command_bus()
    assert isinstance(bus, UnifiedCommandBus)


# =============================================================================
# TAMBAHAN: Test eksplisit untuk metode yang hilang (dengan asersi kuat)
# =============================================================================

class TestMetricsPortExtra:
    def test_get_stats_detailed(self):
        metrics = MetricsPort()
        metrics.inc_commands_dispatched("CmdA")
        metrics.inc_commands_dispatched("CmdA")
        metrics.inc_commands_dispatched("CmdB")
        metrics.inc_commands_failed("CmdA", "timeout")
        metrics.observe_command_latency(0.1)
        metrics.observe_command_latency(0.2)
        stats = metrics.get_stats()
        assert stats["commands_dispatched"] == {"CmdA": 2, "CmdB": 1}
        assert stats["commands_failed"]["CmdA"]["timeout"] == 1
        assert stats["total_dispatched"] == 3
        assert stats["total_failed"] == 1
        assert stats["avg_latency_seconds"] == pytest.approx(0.15)
        assert stats["p95_latency_seconds"] > 0
        assert stats["p99_latency_seconds"] > 0


class TestSpanExtra:
    def test___enter___and___exit__(self):
        span = Span("test")
        with span as s:
            assert s is span
            assert span.end_time is None
            time.sleep(0.001)
        assert span.end_time is not None
        assert span.get_duration_ms() > 0

    def test_set_status_with_string(self):
        span = Span("test")
        span.set_status("ERROR", "something went wrong")
        assert span.status == "ERROR"
        assert span.status_description == "something went wrong"
        span.set_status("OK")
        assert span.status == "OK"
        assert span.status_description == ""


class TestBaseCommandExtra:
    def test_to_dict_full(self):
        cmd = BaseCommand(
            command_type="Test",
            user_id=uuid4(),
            correlation_id="corr-123",
            idempotency_key="id-456",
            tenant_id=uuid4(),
            source_ip="127.0.0.1",
            user_agent="pytest",
            metadata={"extra": "data"},
        )
        d = cmd.to_dict()
        assert d["command_type"] == "Test"
        assert d["correlation_id"] == "corr-123"
        assert d["idempotency_key"] == "id-456"
        assert d["user_id"] == str(cmd.user_id)
        assert d["tenant_id"] == str(cmd.tenant_id)
        assert d["source_ip"] == "127.0.0.1"
        assert d["user_agent"] == "pytest"
        assert d["metadata"] == {"extra": "data"}
        assert "command_id" in d
        assert "occurred_at" in d

    def test_get_result_with_result_set(self):
        cmd = BaseCommand("Test")
        assert cmd.get_result() is None
        result = CommandResult.success(command_id=cmd.command_id, data={"ok": True})
        cmd.set_result(result)
        assert cmd.get_result() is result


class TestUnifiedCommandBusExtra:
    def test_register_handler_real(self):
        bus = UnifiedCommandBus(handler_registry=MagicMock())
        async def handler(cmd: BaseCommand) -> CommandResult:
            return CommandResult.success(command_id=cmd.command_id, data={"ok": True})
        bus.register_handler("TestCommand", handler)
        bus._registry.register_handler.assert_called_once_with("TestCommand", handler)

    def test_subscribe_real(self):
        bus = UnifiedCommandBus()
        def callback(cmd: BaseCommand, result: CommandResult):
            pass
        bus.subscribe(callback)
        assert callback in bus._event_subscribers

    def test_unsubscribe_real(self):
        bus = UnifiedCommandBus()
        def callback(cmd: BaseCommand, result: CommandResult):
            pass
        bus.subscribe(callback)
        assert callback in bus._event_subscribers
        bus.unsubscribe(callback)
        assert callback not in bus._event_subscribers

    def test_close_real(self):
        bus = UnifiedCommandBus()
        assert bus._is_closed is False
        bus.close()
        assert bus._is_closed is True
        bus.close()

    def test_get_stats_real(self):
        bus = UnifiedCommandBus()
        stats = bus.get_stats()
        assert "total_dispatched" in stats
        assert "total_succeeded" in stats
        assert "total_failed" in stats
        assert "uptime_seconds" in stats
        assert "is_closed" in stats
        assert "registered_commands" in stats
        assert "middlewares" in stats
        assert "metrics" in stats

    def test_health_check_real(self):
        bus = UnifiedCommandBus()
        health = bus.health_check()
        assert health["status"] == "healthy"
        assert health["is_closed"] is False
        assert health["total_dispatched"] == 0
        assert health["success_rate"] == 100.0


class TestCommandBusExtra:
    def test_register_handler_real(self):
        bus = CommandBus()
        def sync_handler(cmd):
            return CommandResult.success(command_id=cmd.command_id, data={})
        bus.register_handler(DummyCommand, sync_handler)
        assert DummyCommand in bus._handlers

    def test_add_middleware_real(self):
        bus = CommandBus()
        def middleware(cmd, next_handler):
            return next_handler(cmd)
        bus.add_middleware(middleware)
        assert middleware in bus._middlewares

    def test_dispatch_success(self):
        bus = CommandBus()
        def sync_handler(cmd):
            return CommandResult.success(command_id=cmd.command_id, data={"ok": True})
        bus.register_handler(DummyCommand, sync_handler)
        cmd = DummyCommand()
        result = bus.dispatch(cmd)
        assert result.is_success() is True
        assert result.data == {"ok": True}
        assert bus._stats["dispatched"] == 1
        assert bus._stats["succeeded"] == 1

    def test_dispatch_no_handler(self):
        bus = CommandBus()
        cmd = DummyCommand()
        result = bus.dispatch(cmd)
        assert result.is_success() is False
        assert result.error_code == "HANDLER_NOT_FOUND"
        assert bus._stats["failed"] == 1

    def test_dispatch_handler_error(self):
        bus = CommandBus()
        def sync_handler(cmd):
            raise ValueError("oops")
        bus.register_handler(DummyCommand, sync_handler)
        cmd = DummyCommand()
        result = bus.dispatch(cmd)
        assert result.is_success() is False
        assert result.error_code == "HANDLER_ERROR"
        assert "oops" in result.error
        assert bus._stats["failed"] == 1

    def test_get_stats_real(self):
        bus = CommandBus()
        stats = bus.get_stats()
        assert stats["dispatched"] == 0
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0
        def sync_handler(cmd):
            return CommandResult.success(command_id=cmd.command_id, data={})
        bus.register_handler(DummyCommand, sync_handler)
        cmd = DummyCommand()
        bus.dispatch(cmd)
        stats2 = bus.get_stats()
        assert stats2["dispatched"] == 1
        assert stats2["succeeded"] == 1