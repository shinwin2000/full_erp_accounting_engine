# tests/application/events/test_handler_registry.py
"""
Comprehensive tests for application/events/handler_registry.py
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from application.events.handler_registry import (
    EventHandlerRegistry,
    HandlerAlreadyRegisteredError,
    HandlerEntry,
    HandlerNotFoundError,
    HandlerPriority,
    HandlerRegistryError,
    InvalidHandlerSignatureError,
    event_handler_registry,
    get_handlers,
    has_handlers,
    register_default_logging_handler,
    register_handler,
    register_wildcard,
)


# ============================================================================
# Tests for Enums
# ============================================================================

class TestHandlerPriority:
    def test_members_exist(self):
        assert hasattr(HandlerPriority, 'CRITICAL')
        assert hasattr(HandlerPriority, 'HIGH')
        assert hasattr(HandlerPriority, 'NORMAL')
        assert hasattr(HandlerPriority, 'LOW')
        assert hasattr(HandlerPriority, 'MONITORING')
        assert hasattr(HandlerPriority, 'LOWEST')

    def test_member_is_instance(self):
        assert isinstance(HandlerPriority.CRITICAL, HandlerPriority)

    def test_values_are_int(self):
        assert HandlerPriority.CRITICAL.value == 0
        assert HandlerPriority.HIGH.value == 10
        assert HandlerPriority.NORMAL.value == 50
        assert HandlerPriority.LOW.value == 90
        assert HandlerPriority.MONITORING.value == 100
        assert HandlerPriority.LOWEST.value == 110


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestHandlerRegistryError:
    def test_raise(self):
        with pytest.raises(HandlerRegistryError):
            raise HandlerRegistryError("test")


class TestHandlerAlreadyRegisteredError:
    def test_raise(self):
        with pytest.raises(HandlerAlreadyRegisteredError):
            raise HandlerAlreadyRegisteredError("duplicate")


class TestHandlerNotFoundError:
    def test_raise(self):
        with pytest.raises(HandlerNotFoundError):
            raise HandlerNotFoundError("not found")


class TestInvalidHandlerSignatureError:
    def test_raise(self):
        with pytest.raises(InvalidHandlerSignatureError):
            raise InvalidHandlerSignatureError("invalid")


# ============================================================================
# Tests for HandlerEntry
# ============================================================================

class TestHandlerEntry:
    def test_construction(self):
        def sync_handler(event):
            pass

        entry = HandlerEntry(
            handler=sync_handler,
            event_type="TestEvent",
            priority=HandlerPriority.NORMAL,
            is_async=False,
            name="sync_handler",
        )
        assert entry.handler is sync_handler
        assert entry.event_type == "TestEvent"
        assert entry.priority == HandlerPriority.NORMAL
        assert entry.is_async is False
        assert entry.name == "sync_handler"
        assert entry.registered_at > 0
        assert entry.execution_count == 0
        assert entry.total_execution_time_ms == 0.0
        assert entry.last_error is None

    def test_construction_invalid_handler_raises(self):
        with pytest.raises(InvalidHandlerSignatureError, match="must be callable"):
            HandlerEntry(
                handler="not_callable",  # type: ignore
                event_type="Test",
                priority=HandlerPriority.NORMAL,
                is_async=False,
                name="test",
            )

    def test_to_dict(self):
        def sync_handler(event):
            pass

        entry = HandlerEntry(
            handler=sync_handler,
            event_type="TestEvent",
            priority=HandlerPriority.HIGH,
            is_async=False,
            name="sync_handler",
            registered_at=100.0,
            execution_count=5,
            total_execution_time_ms=25.0,
            last_error="error",
        )
        d = entry.to_dict()
        assert d["name"] == "sync_handler"
        assert d["event_type"] == "TestEvent"
        assert d["priority"] == "HIGH"
        assert d["is_async"] is False
        assert d["registered_at"] == 100.0
        assert d["execution_count"] == 5
        assert d["avg_execution_time_ms"] == 5.0
        assert d["last_error"] == "error"

    def test_to_dict_zero_execution_count(self):
        def sync_handler(event):
            pass

        entry = HandlerEntry(
            handler=sync_handler,
            event_type="TestEvent",
            priority=HandlerPriority.NORMAL,
            is_async=False,
            name="sync_handler",
            execution_count=0,
            total_execution_time_ms=0.0,
        )
        d = entry.to_dict()
        assert d["avg_execution_time_ms"] == 0

    def test_record_execution_does_nothing(self):
        # record_execution is a no-op method (it's frozen, so we can't modify)
        # We'll call it and ensure it doesn't raise.
        def sync_handler(event):
            pass

        entry = HandlerEntry(
            handler=sync_handler,
            event_type="Test",
            priority=HandlerPriority.NORMAL,
            is_async=False,
            name="test",
        )
        entry.record_execution(100.0, error=None)
        # No state change, but we can verify it didn't raise
        assert entry.execution_count == 0  # unchanged


# ============================================================================
# Tests for EventHandlerRegistry
# ============================================================================

class TestEventHandlerRegistry:
    def test_singleton(self):
        r1 = EventHandlerRegistry()
        r2 = EventHandlerRegistry()
        assert r1 is r2

    def test_init_clears_on_new_instance(self):
        # Since it's a singleton, we can't create a new instance with different state.
        # But we can clear and check.
        registry = EventHandlerRegistry()
        registry.clear()
        assert len(registry._handlers) == 0
        assert len(registry._wildcard_handlers) == 0

    # ---- register_handler ----
    def test_register_handler_sync(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def sync_handler(event):
            pass

        registry.register_handler("TestEvent", sync_handler, priority=HandlerPriority.HIGH, name="sync")
        entries = registry._handlers.get("TestEvent", [])
        assert len(entries) == 1
        assert entries[0].name == "sync"
        assert entries[0].handler is sync_handler
        assert entries[0].priority == HandlerPriority.HIGH
        assert entries[0].is_async is False

    def test_register_handler_async(self):
        registry = EventHandlerRegistry()
        registry.clear()

        async def async_handler(event):
            pass

        registry.register_handler("TestEvent", async_handler)
        entries = registry._handlers["TestEvent"]
        assert len(entries) == 1
        assert entries[0].is_async is True

    def test_register_handler_duplicate_raises(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def handler1(event):
            pass

        def handler2(event):
            pass

        registry.register_handler("TestEvent", handler1, priority=HandlerPriority.NORMAL)
        # Same handler, same priority -> raises
        with pytest.raises(HandlerAlreadyRegisteredError, match="already registered"):
            registry.register_handler("TestEvent", handler1, priority=HandlerPriority.NORMAL)

        # Different handler, same priority -> allowed
        registry.register_handler("TestEvent", handler2, priority=HandlerPriority.NORMAL)
        entries = registry._handlers["TestEvent"]
        assert len(entries) == 2

    def test_register_handler_sorts_by_priority(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        def h3(event):
            pass

        registry.register_handler("Test", h1, priority=HandlerPriority.LOW)
        registry.register_handler("Test", h2, priority=HandlerPriority.HIGH)
        registry.register_handler("Test", h3, priority=HandlerPriority.NORMAL)

        entries = registry._handlers["Test"]
        assert entries[0].priority == HandlerPriority.HIGH
        assert entries[1].priority == HandlerPriority.NORMAL
        assert entries[2].priority == HandlerPriority.LOW

    def test_register_handler_invalid_signature_raises(self):
        registry = EventHandlerRegistry()
        registry.clear()

        # Handler with no parameters (invalid)
        def invalid_handler():
            pass

        with pytest.raises(InvalidHandlerSignatureError, match="accept at least 1 argument"):
            registry.register_handler("Test", invalid_handler)

        # Handler with 2 required parameters (invalid)
        def invalid_handler2(a, b):
            pass

        with pytest.raises(InvalidHandlerSignatureError, match="2 required parameters"):
            registry.register_handler("Test", invalid_handler2)

        # Handler with 1 required and 1 optional is fine
        def valid_handler(event, optional=None):
            pass

        registry.register_handler("Test", valid_handler)
        assert len(registry._handlers["Test"]) == 1

    # ---- register_wildcard_handler ----
    def test_register_wildcard_handler(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def wildcard_handler(event):
            pass

        registry.register_wildcard_handler(wildcard_handler, priority=HandlerPriority.MONITORING, name="wild")
        assert len(registry._wildcard_handlers) == 1
        entry = registry._wildcard_handlers[0]
        assert entry.name == "wild"
        assert entry.handler is wildcard_handler
        assert entry.priority == HandlerPriority.MONITORING
        assert entry.event_type == "*"

    def test_register_wildcard_handler_sorts_by_priority(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        registry.register_wildcard_handler(h1, priority=HandlerPriority.LOW)
        registry.register_wildcard_handler(h2, priority=HandlerPriority.HIGH)
        entries = registry._wildcard_handlers
        assert entries[0].priority == HandlerPriority.HIGH
        assert entries[1].priority == HandlerPriority.LOW

    # ---- register decorator ----
    def test_register_decorator_specific(self):
        registry = EventHandlerRegistry()
        registry.clear()

        @registry.register(event_type="TestEvent", priority=HandlerPriority.CRITICAL, name="decorated")
        def decorated_handler(event):
            pass

        entries = registry._handlers["TestEvent"]
        assert len(entries) == 1
        assert entries[0].name == "decorated"
        assert entries[0].handler is decorated_handler
        assert entries[0].priority == HandlerPriority.CRITICAL

    def test_register_decorator_wildcard(self):
        registry = EventHandlerRegistry()
        registry.clear()

        @registry.register(wildcard=True, priority=HandlerPriority.HIGH, name="wild_decorated")
        def wild_handler(event):
            pass

        assert len(registry._wildcard_handlers) == 1
        entry = registry._wildcard_handlers[0]
        assert entry.name == "wild_decorated"
        assert entry.handler is wild_handler
        assert entry.priority == HandlerPriority.HIGH

    def test_register_decorator_missing_event_type_raises(self):
        registry = EventHandlerRegistry()
        registry.clear()

        with pytest.raises(InvalidHandlerSignatureError, match="Either event_type or wildcard"):

            @registry.register()
            def handler(event):
                pass

    # ---- unregister_handler ----
    def test_unregister_handler_by_handler(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        registry.register_handler("Test", h1)
        registry.register_handler("Test", h2)

        result = registry.unregister_handler("Test", handler=h1)
        assert result is True
        entries = registry._handlers.get("Test", [])
        assert len(entries) == 1
        assert entries[0].handler is h2

    def test_unregister_handler_by_name(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        registry.register_handler("Test", h1, name="h1")
        result = registry.unregister_handler("Test", name="h1")
        assert result is True
        assert "Test" not in registry._handlers

    def test_unregister_handler_all(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        registry.register_handler("Test", h1)
        result = registry.unregister_handler("Test")
        assert result is True
        assert "Test" not in registry._handlers

    def test_unregister_handler_not_found(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        result = registry.unregister_handler("NonExistent")
        assert result is False

        registry.register_handler("Test", h1)
        result2 = registry.unregister_handler("Test", handler=lambda x: None)
        assert result2 is False

    # ---- unregister_wildcard_handler ----
    def test_unregister_wildcard_handler_by_handler(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def w1(event):
            pass

        def w2(event):
            pass

        registry.register_wildcard_handler(w1)
        registry.register_wildcard_handler(w2)

        result = registry.unregister_wildcard_handler(handler=w1)
        assert result is True
        assert len(registry._wildcard_handlers) == 1
        assert registry._wildcard_handlers[0].handler is w2

    def test_unregister_wildcard_handler_by_name(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def w1(event):
            pass

        registry.register_wildcard_handler(w1, name="w1")
        result = registry.unregister_wildcard_handler(name="w1")
        assert result is True
        assert len(registry._wildcard_handlers) == 0

    def test_unregister_wildcard_handler_not_found(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def w1(event):
            pass

        result = registry.unregister_wildcard_handler(handler=w1)
        assert result is False

    # ---- get_handlers ----
    def test_get_handlers(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        def wild(event):
            pass

        registry.register_handler("Test", h1)
        registry.register_handler("Test", h2)
        registry.register_wildcard_handler(wild)

        handlers = registry.get_handlers("Test")
        # Should include h1, h2, and wildcard handler
        assert len(handlers) == 3
        assert h1 in handlers
        assert h2 in handlers
        assert wild in handlers

    def test_get_handlers_no_specific(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def wild(event):
            pass

        registry.register_wildcard_handler(wild)

        handlers = registry.get_handlers("NonExistent")
        assert len(handlers) == 1
        assert handlers[0] is wild

    def test_get_handlers_empty(self):
        registry = EventHandlerRegistry()
        registry.clear()

        handlers = registry.get_handlers("Test")
        assert handlers == []

    # ---- get_handler_entries ----
    def test_get_handler_entries(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def wild(event):
            pass

        registry.register_handler("Test", h1, name="h1")
        registry.register_wildcard_handler(wild, name="wild")

        entries = registry.get_handler_entries("Test")
        assert len(entries) == 2
        names = [e.name for e in entries]
        assert "h1" in names
        assert "wild" in names

    # ---- has_handlers ----
    def test_has_handlers_specific(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        assert registry.has_handlers("Test") is False
        registry.register_handler("Test", h1)
        assert registry.has_handlers("Test") is True

    def test_has_handlers_wildcard(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def wild(event):
            pass

        assert registry.has_handlers("Any") is False
        registry.register_wildcard_handler(wild)
        assert registry.has_handlers("Any") is True

    # ---- list_registered_event_types ----
    def test_list_registered_event_types(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        registry.register_handler("A", h1)
        registry.register_handler("B", h2)

        types = registry.list_registered_event_types()
        assert sorted(types) == ["A", "B"]

    # ---- get_stats ----
    def test_get_stats(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        def h2(event):
            pass

        def wild(event):
            pass

        registry.register_handler("A", h1, name="h1")
        registry.register_handler("A", h2, name="h2")
        registry.register_handler("B", h1, name="h1b")
        registry.register_wildcard_handler(wild, name="wild")

        stats = registry.get_stats()
        assert stats["event_types"] == 2
        assert stats["total_specific_handlers"] == 3
        assert stats["total_wildcard_handlers"] == 1
        assert "A" in stats["handlers_by_event"]
        assert len(stats["handlers_by_event"]["A"]) == 2
        assert stats["wildcard_handlers"] == ["wild"]

    # ---- clear ----
    def test_clear(self):
        registry = EventHandlerRegistry()
        registry.clear()

        def h1(event):
            pass

        registry.register_handler("Test", h1)
        registry.register_wildcard_handler(h1)

        assert len(registry._handlers) == 1
        assert len(registry._wildcard_handlers) == 1

        registry.clear()
        assert len(registry._handlers) == 0
        assert len(registry._wildcard_handlers) == 0

    # ---- _validate_handler_signature ----
    def test_validate_handler_signature_valid(self):
        registry = EventHandlerRegistry()

        def valid_sync(event):
            pass

        async def valid_async(event):
            pass

        def valid_with_default(event, optional=None):
            pass

        # Should not raise
        registry._validate_handler_signature(valid_sync)
        registry._validate_handler_signature(valid_async)
        registry._validate_handler_signature(valid_with_default)

    def test_validate_handler_signature_no_params(self):
        registry = EventHandlerRegistry()

        def no_params():
            pass

        with pytest.raises(InvalidHandlerSignatureError, match="accept at least 1 argument"):
            registry._validate_handler_signature(no_params)

    def test_validate_handler_signature_two_required(self):
        registry = EventHandlerRegistry()

        def two_params(a, b):
            pass

        with pytest.raises(InvalidHandlerSignatureError, match="2 required parameters"):
            registry._validate_handler_signature(two_params)

    def test_validate_handler_signature_exception_handling(self):
        registry = EventHandlerRegistry()

        class BadHandler:
            pass

        # This should cause the except block to catch a generic exception
        with pytest.raises(InvalidHandlerSignatureError, match="Cannot validate handler"):
            registry._validate_handler_signature(BadHandler)  # type: ignore


# ============================================================================
# Tests for Module-level Functions
# ============================================================================

class TestModuleFunctions:
    def test_register_handler_decorator(self):
        # Clear global registry
        event_handler_registry.clear()

        @register_handler("TestEvent", priority=HandlerPriority.HIGH, name="global_handler")
        def global_handler(event):
            pass

        entries = event_handler_registry._handlers.get("TestEvent", [])
        assert len(entries) == 1
        assert entries[0].name == "global_handler"
        assert entries[0].handler is global_handler

    def test_register_wildcard_decorator(self):
        event_handler_registry.clear()

        @register_wildcard(priority=HandlerPriority.MONITORING, name="global_wild")
        def global_wild(event):
            pass

        wild_entries = event_handler_registry._wildcard_handlers
        assert len(wild_entries) == 1
        assert wild_entries[0].name == "global_wild"
        assert wild_entries[0].handler is global_wild

    def test_get_handlers_function(self):
        event_handler_registry.clear()

        def h1(event):
            pass

        event_handler_registry.register_handler("Test", h1)

        handlers = get_handlers("Test")
        assert len(handlers) == 1
        assert handlers[0] is h1

    def test_has_handlers_function(self):
        event_handler_registry.clear()

        def h1(event):
            pass

        assert has_handlers("Test") is False
        event_handler_registry.register_handler("Test", h1)
        assert has_handlers("Test") is True

    def test_register_default_logging_handler(self):
        event_handler_registry.clear()

        # Register the default logging handler
        register_default_logging_handler()

        # Should have added a wildcard handler
        wild_entries = event_handler_registry._wildcard_handlers
        assert len(wild_entries) == 1
        assert wild_entries[0].name == "default_logging_handler"

        # Call it to ensure it works
        mock_envelope = MagicMock()
        mock_envelope.event_type = "TestEvent"
        mock_envelope.event_id = "123"
        mock_envelope.correlation_id = "corr"

        # The handler logs info, we can't easily assert without capturing logs
        # But we can verify it's callable
        handler = wild_entries[0].handler
        handler(mock_envelope)  # should not raise


# ============================================================================
# Integration Tests for Registry Workflow
# ============================================================================

class TestIntegration:
    def test_full_workflow(self):
        registry = EventHandlerRegistry()
        registry.clear()

        # Register handlers
        def sync_handler(event):
            return "sync"

        async def async_handler(event):
            return "async"

        def wild_handler(event):
            return "wild"

        registry.register_handler("OrderCreated", sync_handler, priority=HandlerPriority.HIGH, name="sync")
        registry.register_handler("OrderCreated", async_handler, priority=HandlerPriority.NORMAL, name="async")
        registry.register_wildcard_handler(wild_handler, priority=HandlerPriority.LOW, name="wild")

        # Get handlers
        handlers = registry.get_handlers("OrderCreated")
        assert len(handlers) == 3
        assert sync_handler in handlers
        assert async_handler in handlers
        assert wild_handler in handlers

        # Check entries ordering
        entries = registry.get_handler_entries("OrderCreated")
        assert entries[0].name == "sync"
        assert entries[1].name == "async"
        assert entries[2].name == "wild"

        # Unregister one
        result = registry.unregister_handler("OrderCreated", handler=async_handler)
        assert result is True

        # Verify
        remaining = registry.get_handlers("OrderCreated")
        assert len(remaining) == 2
        assert sync_handler in remaining
        assert wild_handler in remaining

        # Stats
        stats = registry.get_stats()
        assert stats["event_types"] == 1
        assert stats["total_specific_handlers"] == 1
        assert stats["total_wildcard_handlers"] == 1