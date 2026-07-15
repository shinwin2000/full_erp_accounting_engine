# tests/application/commands_cqrs/test_command_handler_registry.py
"""
Unit tests for CommandHandlerRegistry and related classes.
Covers all public methods, including singleton behavior, registration,
wildcards, metadata, statistics, and convenience functions.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, AsyncMock

import pytest

from application.commands_cqrs.command_handler_registry import (
    CommandHandlerAlreadyRegisteredError,
    CommandHandlerExecutionError,
    CommandHandlerNotFoundError,
    CommandHandlerRegistry,
    CommandHandlerRegistryError,
    HandlerMetadata,
    InvalidCommandHandlerSignatureError,
    clear_command_handlers,
    command_handler_registry,
    default_logging_wildcard,
    default_metrics_wildcard,
    get_all_command_types,
    get_command_handler,
    get_command_handler_registry,
    has_command_handler,
    register_command_handler,
    register_default_wildcards,
    reset_command_handler_registry,
    unregister_command_handler,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_registry() -> None:
    """Reset singleton registry before each test."""
    reset_command_handler_registry()
    yield
    reset_command_handler_registry()


@pytest.fixture
def registry() -> CommandHandlerRegistry:
    """Return a fresh registry instance (singleton)."""
    return get_command_handler_registry()


@pytest.fixture
def sample_handler() -> AsyncMock:
    """Async mock handler that returns a dict."""
    mock = AsyncMock()
    mock.__name__ = "sample_handler"
    mock.return_value = {"status": "ok"}
    return mock


@pytest.fixture
def sample_wildcard() -> AsyncMock:
    """Async mock wildcard handler that returns None."""
    mock = AsyncMock()
    mock.__name__ = "sample_wildcard"
    mock.return_value = None
    return mock


# ============================================================================
# Test Exception Classes
# ============================================================================

def test_CommandHandlerRegistryError() -> None:
    exc = CommandHandlerRegistryError("msg")
    assert str(exc) == "msg"
    assert isinstance(exc, Exception)


def test_CommandHandlerAlreadyRegisteredError() -> None:
    exc = CommandHandlerAlreadyRegisteredError("msg")
    assert str(exc) == "msg"
    assert isinstance(exc, CommandHandlerRegistryError)


def test_CommandHandlerNotFoundError() -> None:
    exc = CommandHandlerNotFoundError("msg")
    assert str(exc) == "msg"
    assert isinstance(exc, CommandHandlerRegistryError)


def test_InvalidCommandHandlerSignatureError() -> None:
    exc = InvalidCommandHandlerSignatureError("msg")
    assert str(exc) == "msg"
    assert isinstance(exc, CommandHandlerRegistryError)


def test_CommandHandlerExecutionError() -> None:
    exc = CommandHandlerExecutionError("msg")
    assert str(exc) == "msg"
    assert isinstance(exc, CommandHandlerRegistryError)


# ============================================================================
# Test HandlerMetadata
# ============================================================================

def test_HandlerMetadata_to_dict() -> None:
    """Test HandlerMetadata.to_dict() – method call."""
    meta = HandlerMetadata(
        name="test_handler",
        description="a handler",
        version="2.0",
        tags=["tag1", "tag2"],
        priority=10,
        registered_at=1000.0,
        execution_count=5,
        total_execution_time_ms=500.0,
        last_execution_time_ms=100.0,
        last_error=None,
        last_success_at=2000.0,
    )
    d = meta.to_dict()
    assert d["name"] == "test_handler"
    assert d["description"] == "a handler"
    assert d["version"] == "2.0"
    assert d["tags"] == ["tag1", "tag2"]
    assert d["priority"] == 10
    assert "registered_at" in d
    assert d["execution_count"] == 5
    assert d["avg_execution_time_ms"] == 100.0  # 500/5
    assert d["last_execution_time_ms"] == 100.0
    assert d["last_error"] is None
    assert d["last_success_at"] == 2000.0


def test_HandlerMetadata_record_execution_no_error() -> None:
    """Test HandlerMetadata.record_execution() – method call."""
    meta = HandlerMetadata(name="test")
    meta.record_execution(duration_ms=42.0, error=None)
    assert meta.execution_count == 1
    assert meta.total_execution_time_ms == 42.0
    assert meta.last_execution_time_ms == 42.0
    assert meta.last_error is None
    assert meta.last_success_at is not None


def test_HandlerMetadata_record_execution_with_error() -> None:
    """Test HandlerMetadata.record_execution() with error."""
    meta = HandlerMetadata(name="test")
    meta.record_execution(duration_ms=50.0, error="something went wrong")
    assert meta.execution_count == 1
    assert meta.total_execution_time_ms == 50.0
    assert meta.last_error == "something went wrong"
    assert meta.last_success_at is None


def test_HandlerMetadata_get_success_rate() -> None:
    """Test HandlerMetadata.get_success_rate() – method call."""
    meta = HandlerMetadata(name="test")
    # No executions
    assert meta.get_success_rate() == 100.0

    meta.record_execution(10.0)  # success
    assert meta.get_success_rate() == 100.0

    meta.record_execution(20.0, "error")  # error
    assert meta.get_success_rate() == 50.0


# ============================================================================
# Test CommandHandlerRegistry Singleton
# ============================================================================

def test_CommandHandlerRegistry___new__() -> None:
    """Test CommandHandlerRegistry.__new__ returns same instance."""
    reg1 = CommandHandlerRegistry()
    reg2 = CommandHandlerRegistry()
    assert reg1 is reg2


def test_get_command_handler_registry() -> None:
    """Test module function get_command_handler_registry."""
    reg = get_command_handler_registry()
    assert isinstance(reg, CommandHandlerRegistry)


def test_reset_command_handler_registry() -> None:
    """Test module function reset_command_handler_registry."""
    reg1 = get_command_handler_registry()
    reg1.register_handler("TestCmd", AsyncMock())
    assert reg1.has_handler("TestCmd") is True

    reset_command_handler_registry()
    reg2 = get_command_handler_registry()
    assert reg2.has_handler("TestCmd") is False
    # Verify it's a new singleton instance (or reset)
    assert reg2 is not reg1


# ============================================================================
# Test Registration & Decorators
# ============================================================================

async def test_CommandHandlerRegistry_register_decorator(registry: CommandHandlerRegistry) -> None:
    """Test @register decorator – method call."""
    @registry.register("TestCommand", name="my_handler", description="desc", tags=["a"], priority=5)
    async def handler(cmd: dict) -> dict:
        return {"result": "ok"}

    # Handler should be registered
    assert registry.has_handler("TestCommand") is True
    meta = registry.get_handler_metadata("TestCommand")
    assert meta is not None
    assert meta.name == "my_handler"
    assert meta.description == "desc"
    assert meta.tags == ["a"]
    assert meta.priority == 5

    # Get handler and execute
    h = registry.get_handler("TestCommand")
    result = await h({"cmd": "data"})
    assert result == {"result": "ok"}


async def test_CommandHandlerRegistry_wildcard_decorator(registry: CommandHandlerRegistry) -> None:
    """Test @wildcard decorator – method call."""
    @registry.wildcard(priority=100, name="log_all", description="log all commands")
    async def log_handler(cmd: dict) -> None:
        return None

    wildcards = registry.get_wildcard_handlers()
    assert len(wildcards) == 1
    assert wildcards[0][0] == 100
    assert wildcards[0][1] == "log_all"


def test_CommandHandlerRegistry_register_handler(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test register_handler() – method call."""
    registry.register_handler("TestCmd", sample_handler, override=False, metadata=HandlerMetadata(name="test_meta"))
    assert registry.has_handler("TestCmd") is True
    meta = registry.get_handler_metadata("TestCmd")
    assert meta is not None
    assert meta.name == "test_meta"


def test_CommandHandlerRegistry_register_handler_already_registered(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test register_handler raises if already exists and override=False."""
    registry.register_handler("TestCmd", sample_handler)
    with pytest.raises(CommandHandlerAlreadyRegisteredError):
        registry.register_handler("TestCmd", sample_handler, override=False)


def test_CommandHandlerRegistry_register_handler_override(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test register_handler with override=True replaces existing."""
    async def old_handler(cmd: dict) -> dict:
        return {"old": True}
    registry.register_handler("TestCmd", old_handler)
    registry.register_handler("TestCmd", sample_handler, override=True)
    assert registry.get_specific_handler("TestCmd") is sample_handler


def test_CommandHandlerRegistry_register_handler_invalid_signature(registry: CommandHandlerRegistry) -> None:
    """Test register_handler validates signature – method call."""
    # Not async
    def sync_handler(cmd: dict) -> dict:
        return {}
    with pytest.raises(InvalidCommandHandlerSignatureError, match="must be an async function"):
        registry.register_handler("TestCmd", sync_handler)

    # Too many parameters? Actually no, we only check min 1 param. But we can test if param count > 0.
    # We'll test that it passes with one param.
    async def valid_handler(cmd: dict) -> dict:
        return {}
    registry.register_handler("TestCmd", valid_handler)  # Should not raise


def test_CommandHandlerRegistry_register_wildcard(registry: CommandHandlerRegistry, sample_wildcard: AsyncMock) -> None:
    """Test register_wildcard() – method call."""
    meta = HandlerMetadata(name="wc_meta", priority=42)
    registry.register_wildcard(sample_wildcard, metadata=meta, priority=42)
    wildcards = registry.get_wildcard_handlers()
    assert len(wildcards) == 1
    assert wildcards[0][0] == 42
    assert wildcards[0][1] == "wc_meta"


# ============================================================================
# Test Handler Retrieval
# ============================================================================

async def test_CommandHandlerRegistry_get_handler_no_specific(registry: CommandHandlerRegistry) -> None:
    """Test get_handler returns None when no specific handler exists and no wildcard."""
    h = registry.get_handler("NonExistent")
    assert h is None


async def test_CommandHandlerRegistry_get_handler_with_specific(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test get_handler returns specific handler."""
    registry.register_handler("TestCmd", sample_handler)
    h = registry.get_handler("TestCmd")
    assert h is not None
    result = await h({})
    sample_handler.assert_awaited_once()


async def test_CommandHandlerRegistry_get_handler_with_wildcard(registry: CommandHandlerRegistry, sample_handler: AsyncMock, sample_wildcard: AsyncMock) -> None:
    """Test get_handler chains wildcard before specific."""
    registry.register_wildcard(sample_wildcard, priority=10)
    registry.register_handler("TestCmd", sample_handler)

    h = registry.get_handler("TestCmd")
    await h({})

    # Wildcard called first, then specific
    sample_wildcard.assert_awaited_once()
    sample_handler.assert_awaited_once()


async def test_CommandHandlerRegistry_get_handler_wildcard_returns_result(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test get_handler stops propagation if wildcard returns non-None."""
    async def wc_returns(cmd: dict) -> dict:
        return {"wildcard": "result"}

    registry.register_wildcard(wc_returns, priority=10)
    registry.register_handler("TestCmd", sample_handler)

    h = registry.get_handler("TestCmd")
    result = await h({})

    # Specific handler should NOT be called
    sample_handler.assert_not_awaited()
    assert result == {"wildcard": "result"}


async def test_CommandHandlerRegistry_get_handler_wildcard_error(registry: CommandHandlerRegistry) -> None:
    """Test get_handler propagates wildcard errors."""
    async def failing_wc(cmd: dict) -> None:
        raise ValueError("wildcard fail")

    registry.register_wildcard(failing_wc)
    registry.register_handler("TestCmd", AsyncMock())

    h = registry.get_handler("TestCmd")
    with pytest.raises(CommandHandlerExecutionError, match="Wildcard handler error"):
        await h({})


async def test_CommandHandlerRegistry_get_handler_specific_error(registry: CommandHandlerRegistry) -> None:
    """Test get_handler propagates specific handler errors."""
    async def failing_handler(cmd: dict) -> None:
        raise ValueError("handler fail")

    registry.register_handler("TestCmd", failing_handler)
    h = registry.get_handler("TestCmd")
    with pytest.raises(CommandHandlerExecutionError, match="Handler execution failed"):
        await h({})


def test_CommandHandlerRegistry_get_specific_handler(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test get_specific_handler returns raw handler without wrapping."""
    registry.register_handler("TestCmd", sample_handler)
    h = registry.get_specific_handler("TestCmd")
    assert h is sample_handler


def test_CommandHandlerRegistry_get_handler_metadata(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test get_handler_metadata returns metadata."""
    meta = HandlerMetadata(name="test_meta")
    registry.register_handler("TestCmd", sample_handler, metadata=meta)
    retrieved = registry.get_handler_metadata("TestCmd")
    assert retrieved is meta


# ============================================================================
# Test Unregistration
# ============================================================================

def test_CommandHandlerRegistry_unregister_handler(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test unregister_handler() – method call."""
    registry.register_handler("TestCmd", sample_handler)
    assert registry.has_handler("TestCmd") is True
    result = registry.unregister_handler("TestCmd")
    assert result is True
    assert registry.has_handler("TestCmd") is False

    # Try unregister non-existent
    result = registry.unregister_handler("NonExistent")
    assert result is False


def test_CommandHandlerRegistry_unregister_wildcard_by_name(registry: CommandHandlerRegistry, sample_wildcard: AsyncMock) -> None:
    """Test unregister_wildcard() – method call."""
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="to_remove"))
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="keep"))
    assert len(registry.get_wildcard_handlers()) == 2

    removed = registry.unregister_wildcard("to_remove")
    assert removed is True
    wildcards = registry.get_wildcard_handlers()
    assert len(wildcards) == 1
    assert wildcards[0][1] == "keep"

    # Try remove non-existent
    removed = registry.unregister_wildcard("not_found")
    assert removed is False


def test_CommandHandlerRegistry_unregister_wildcard_by_index(registry: CommandHandlerRegistry, sample_wildcard: AsyncMock) -> None:
    """Test unregister_wildcard_by_index() – method call."""
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="first"))
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="second"))
    # Remove by index (should be sorted by priority, so index 0 is first)
    removed = registry.unregister_wildcard_by_index(0)
    assert removed is True
    wildcards = registry.get_wildcard_handlers()
    assert len(wildcards) == 1
    assert wildcards[0][1] == "second"

    # Invalid index
    removed = registry.unregister_wildcard_by_index(99)
    assert removed is False


# ============================================================================
# Test Query Methods
# ============================================================================

def test_CommandHandlerRegistry_list_command_types(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test list_command_types() – method call."""
    registry.register_handler("Cmd1", sample_handler)
    registry.register_handler("Cmd2", sample_handler)
    types = registry.list_command_types()
    assert set(types) == {"Cmd1", "Cmd2"}


def test_CommandHandlerRegistry_has_handler(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test has_handler() – method call."""
    registry.register_handler("TestCmd", sample_handler)
    assert registry.has_handler("TestCmd") is True
    assert registry.has_handler("Unknown") is False


def test_CommandHandlerRegistry_get_wildcard_handlers(registry: CommandHandlerRegistry, sample_wildcard: AsyncMock) -> None:
    """Test get_wildcard_handlers() – method call."""
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="wc1"), priority=5)
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="wc2"), priority=10)
    wildcards = registry.get_wildcard_handlers()
    # Should be sorted by priority descending
    assert wildcards == [(10, "wc2"), (5, "wc1")]


def test_CommandHandlerRegistry_get_stats(registry: CommandHandlerRegistry, sample_handler: AsyncMock, sample_wildcard: AsyncMock) -> None:
    """Test get_stats() – method call."""
    registry.register_handler("Cmd1", sample_handler, metadata=HandlerMetadata(name="h1"))
    registry.register_handler("Cmd2", sample_handler, metadata=HandlerMetadata(name="h2"))
    registry.register_wildcard(sample_wildcard, metadata=HandlerMetadata(name="w1"), priority=1)

    stats = registry.get_stats()
    assert stats["total_handlers"] == 2
    assert stats["total_wildcard_handlers"] == 1
    assert set(stats["command_types"]) == {"Cmd1", "Cmd2"}
    assert len(stats["wildcard_handlers"]) == 1
    assert stats["wildcard_handlers"][0]["name"] == "w1"
    assert "handler_metadata" in stats


def test_CommandHandlerRegistry_get_health_status(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test get_health_status() – method call."""
    registry.register_handler("Healthy", sample_handler, metadata=HandlerMetadata(name="h1"))
    registry.register_handler("Unhealthy", sample_handler, metadata=HandlerMetadata(name="h2"))
    # Simulate unhealthy: set last_error and no success
    meta = registry.get_handler_metadata("Unhealthy")
    if meta:
        meta.last_error = "error"
        meta.last_success_at = None

    status = registry.get_health_status()
    assert status["status"] == "degraded"
    assert len(status["unhealthy_handlers"]) == 1
    assert status["unhealthy_handlers"][0]["command_type"] == "Unhealthy"


def test_CommandHandlerRegistry_clear(registry: CommandHandlerRegistry, sample_handler: AsyncMock, sample_wildcard: AsyncMock) -> None:
    """Test clear() – method call."""
    registry.register_handler("Cmd1", sample_handler)
    registry.register_wildcard(sample_wildcard)
    assert len(registry.list_command_types()) == 1
    assert len(registry.get_wildcard_handlers()) == 1

    registry.clear()
    assert len(registry.list_command_types()) == 0
    assert len(registry.get_wildcard_handlers()) == 0


# ============================================================================
# Test Convenience Functions
# ============================================================================

async def test_get_command_handler_function(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test module function get_command_handler."""
    registry.register_handler("TestCmd", sample_handler)
    h = get_command_handler("TestCmd")
    assert h is not None
    await h({})
    sample_handler.assert_awaited_once()

    # Non-existent returns None
    assert get_command_handler("Unknown") is None


def test_register_command_handler_function(sample_handler: AsyncMock) -> None:
    """Test module function register_command_handler."""
    register_command_handler(
        "TestCmd",
        sample_handler,
        override=False,
        name="my_func",
        description="desc",
        version="1.2",
        tags=["a", "b"],
        priority=99,
    )
    registry = get_command_handler_registry()
    assert registry.has_handler("TestCmd") is True
    meta = registry.get_handler_metadata("TestCmd")
    assert meta is not None
    assert meta.name == "my_func"
    assert meta.description == "desc"
    assert meta.version == "1.2"
    assert meta.tags == ["a", "b"]
    assert meta.priority == 99


def test_has_command_handler_function(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test module function has_command_handler."""
    registry.register_handler("TestCmd", sample_handler)
    assert has_command_handler("TestCmd") is True
    assert has_command_handler("Unknown") is False


def test_clear_command_handlers_function(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test module function clear_command_handlers."""
    registry.register_handler("Cmd1", sample_handler)
    clear_command_handlers()
    assert registry.has_handler("Cmd1") is False


def test_unregister_command_handler_function(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test module function unregister_command_handler."""
    registry.register_handler("TestCmd", sample_handler)
    result = unregister_command_handler("TestCmd")
    assert result is True
    assert registry.has_handler("TestCmd") is False

    result = unregister_command_handler("Unknown")
    assert result is False


def test_get_all_command_types_function(registry: CommandHandlerRegistry, sample_handler: AsyncMock) -> None:
    """Test module function get_all_command_types."""
    registry.register_handler("Cmd1", sample_handler)
    registry.register_handler("Cmd2", sample_handler)
    types = get_all_command_types()
    assert set(types) == {"Cmd1", "Cmd2"}


async def test_default_logging_wildcard() -> None:
    """Test default_logging_wildcard returns None."""
    result = await default_logging_wildcard({"cmd": "data"})
    assert result is None


async def test_default_metrics_wildcard() -> None:
    """Test default_metrics_wildcard returns None."""
    result = await default_metrics_wildcard({"cmd": "data"})
    assert result is None


def test_register_default_wildcards() -> None:
    """Test register_default_wildcards registers default wildcards."""
    registry = get_command_handler_registry()
    # Initially no wildcards
    assert len(registry.get_wildcard_handlers()) == 0

    register_default_wildcards()
    wildcards = registry.get_wildcard_handlers()
    assert len(wildcards) >= 2  # at least two wildcards

    # Calling again should not duplicate
    register_default_wildcards()
    assert len(registry.get_wildcard_handlers()) == len(wildcards)


# ============================================================================
# Test Real Handler Execution with Metadata Recording
# ============================================================================

async def test_get_handler_records_metrics(registry: CommandHandlerRegistry) -> None:
    """Test that get_handler records execution metrics in metadata."""
    async def handler(cmd: dict) -> dict:
        return {"result": "ok"}

    meta = HandlerMetadata(name="test_handler")
    registry.register_handler("TestCmd", handler, metadata=meta)
    h = registry.get_handler("TestCmd")
    await h({})

    assert meta.execution_count == 1
    assert meta.last_execution_time_ms > 0
    assert meta.last_success_at is not None
    assert meta.last_error is None


async def test_get_handler_records_error_metrics(registry: CommandHandlerRegistry) -> None:
    """Test that get_handler records error in metadata when handler fails."""
    async def failing_handler(cmd: dict) -> None:
        raise ValueError("intentional fail")

    meta = HandlerMetadata(name="failing")
    registry.register_handler("TestCmd", failing_handler, metadata=meta)
    h = registry.get_handler("TestCmd")
    with pytest.raises(CommandHandlerExecutionError):
        await h({})

    assert meta.execution_count == 1
    assert meta.last_execution_time_ms > 0
    assert meta.last_success_at is None
    assert meta.last_error is not None
    assert "intentional fail" in meta.last_error