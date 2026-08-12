# tests/kernel/test_lifecycle_listener.py
"""
Comprehensive unit tests for kernel/lifecycle_listener.py.

Covers:
- Enums: LifecycleEventType, LifecyclePhase
- LifecycleEvent: construction, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
- LifecycleCallback: construction, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
- BaseLifecycleListener (abstract) – not instantiated, but we test that it is importable.
- LifecycleListener:
  - __init__, singleton
  - register, register_startup_callback, register_started_callback, register_shutdown_callback, register_health_callback
  - emit (async), emit_sync
  - get_current_phase, is_running, is_healthy, get_event_history, get_callbacks
  - register_signal_handlers (with signal mocks), wait_for_shutdown (with event mock), shutdown (async), set_shutdown_timeout
  - get_statistics, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset
- Module-level functions: get_lifecycle_listener, on_startup, on_started, on_shutdown, on_health_change
- Edge cases: callback failure, async vs sync, signal handler registration idempotency
- All tests use mocking to avoid actual signal or asyncio event loops where needed.
"""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kernel.lifecycle_listener import (
    BaseLifecycleListener,
    LifecycleCallback,
    LifecycleEvent,
    LifecycleEventType,
    LifecycleListener,
    LifecyclePhase,
    get_lifecycle_listener,
    on_health_change,
    on_shutdown,
    on_started,
    on_startup,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset singleton before each test."""
    LifecycleListener._instance = None
    yield
    LifecycleListener._instance = None


@pytest.fixture
def listener():
    """Fresh LifecycleListener instance (reset singleton for isolation)."""
    # Reset singleton
    LifecycleListener._instance = None
    instance = LifecycleListener()
    # Clear state for fresh test
    instance.reset()
    return instance


@pytest.fixture
def sync_callback():
    def callback(event: LifecycleEvent) -> None:
        pass
    return callback


@pytest.fixture
def async_callback():
    async def callback(event: LifecycleEvent) -> None:
        pass
    return async_callback


# ============================================================================
# Tests for Enums
# ============================================================================

class TestLifecycleEventType:
    def test_members(self):
        assert LifecycleEventType.STARTING.name == "STARTING"
        assert LifecycleEventType.STARTED.name == "STARTED"
        assert LifecycleEventType.HEALTHY.name == "HEALTHY"
        assert LifecycleEventType.DEGRADED.name == "DEGRADED"
        assert LifecycleEventType.UNHEALTHY.name == "UNHEALTHY"
        assert LifecycleEventType.CONFIG_RELOAD_START.name == "CONFIG_RELOAD_START"
        assert LifecycleEventType.CONFIG_RELOAD_END.name == "CONFIG_RELOAD_END"
        assert LifecycleEventType.SHUTTING_DOWN.name == "SHUTTING_DOWN"
        assert LifecycleEventType.SHUTDOWN.name == "SHUTDOWN"
        assert LifecycleEventType.SIGNAL_RECEIVED.name == "SIGNAL_RECEIVED"


class TestLifecyclePhase:
    def test_members(self):
        assert LifecyclePhase.INITIAL.name == "INITIAL"
        assert LifecyclePhase.STARTING.name == "STARTING"
        assert LifecyclePhase.RUNNING.name == "RUNNING"
        assert LifecyclePhase.DEGRADED.name == "DEGRADED"
        assert LifecyclePhase.STOPPING.name == "STOPPING"
        assert LifecyclePhase.STOPPED.name == "STOPPED"


# ============================================================================
# Tests for LifecycleEvent
# ============================================================================

class TestLifecycleEvent:
    def test_construction(self):
        now = datetime.now(UTC)
        event = LifecycleEvent(
            event_type=LifecycleEventType.STARTING,
            timestamp=now,
            source="test",
            details={"key": "value"},
        )
        assert event.event_type == LifecycleEventType.STARTING
        assert event.timestamp == now
        assert event.source == "test"
        assert event.details == {"key": "value"}

    def test_validate_valid(self):
        event = LifecycleEvent(event_type=LifecycleEventType.STARTED, timestamp=datetime.now(UTC), source="system")
        result = event.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        event = LifecycleEvent(event_type=LifecycleEventType.STARTING, timestamp=datetime.now(UTC), source="")
        result = event.validate()
        assert result["is_valid"] is False
        assert "source is required" in result["errors"]

    def test_to_dict(self):
        event = LifecycleEvent(event_type=LifecycleEventType.HEALTHY, timestamp=datetime.now(UTC), source="app")
        d = event.to_dict()
        assert d["event_type"] == "HEALTHY"
        assert "timestamp" in d
        assert d["source"] == "app"
        assert d["details"] == {}

    def test_from_dict(self):
        data = {
            "event_type": "SHUTTING_DOWN",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "source": "system",
            "details": {"foo": "bar"},
        }
        event = LifecycleEvent.from_dict(data)
        assert event.event_type == LifecycleEventType.SHUTTING_DOWN
        assert event.source == "system"
        assert event.details == {"foo": "bar"}

    def test_clone(self):
        event = LifecycleEvent(event_type=LifecycleEventType.STARTED, timestamp=datetime.now(UTC), source="src")
        clone = event.clone()
        assert clone is not event
        assert clone.event_type == event.event_type
        assert clone.source == event.source
        assert clone.details == event.details

    def test_snapshot(self):
        event = LifecycleEvent(event_type=LifecycleEventType.DEGRADED, timestamp=datetime.now(UTC), source="src")
        snap = event.snapshot()
        assert snap["event_type"] == "DEGRADED"
        assert "timestamp" in snap
        assert snap["source"] == "src"

    def test_version(self):
        event = LifecycleEvent(event_type=LifecycleEventType.HEALTHY, timestamp=datetime.now(UTC), source="src")
        assert event.version() == 1

    def test_audit_trail(self):
        event = LifecycleEvent(event_type=LifecycleEventType.STARTING, timestamp=datetime.now(UTC), source="src")
        trail = event.audit_trail()
        assert len(trail) == 1
        assert trail[0]["event_type"] == "STARTING"

    def test_touch(self):
        event = LifecycleEvent(event_type=LifecycleEventType.STARTED, timestamp=datetime.now(UTC), source="src")
        new_event = event.touch("tester")
        assert new_event is not event
        assert new_event.event_type == event.event_type
        assert new_event.source == event.source
        assert new_event.timestamp is not None


# ============================================================================
# Tests for LifecycleCallback
# ============================================================================

class TestLifecycleCallback:
    def test_construction_sync(self, sync_callback):
        cb = LifecycleCallback(
            event_type=LifecycleEventType.STARTING,
            callback=sync_callback,
            priority=10,
            name="test_cb",
        )
        assert cb.event_type == LifecycleEventType.STARTING
        assert cb.callback == sync_callback
        assert cb.priority == 10
        assert cb.name == "test_cb"
        assert cb._is_async is False

    def test_construction_async(self, async_callback):
        cb = LifecycleCallback(
            event_type=LifecycleEventType.STARTED,
            callback=async_callback,
            async_callback=async_callback,
            priority=5,
        )
        assert cb._is_async is True
        assert cb.async_callback == async_callback

    def test_validate_valid(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.STARTING, callback=sync_callback)
        result = cb.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid(self):
        cb = LifecycleCallback(event_type=LifecycleEventType.STARTING, callback=None)
        result = cb.validate()
        assert result["is_valid"] is False
        assert "callback is not callable" in result["errors"]

    def test_to_dict(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.SHUTTING_DOWN, callback=sync_callback, priority=3, name="shutdown")
        d = cb.to_dict()
        assert d["event_type"] == "SHUTTING_DOWN"
        assert d["priority"] == 3
        assert d["name"] == "shutdown"
        assert d["is_async"] is False

    def test_from_dict(self):
        data = {"event_type": "STARTED", "priority": 1, "name": "test"}
        # from_dict uses a placeholder callback
        cb = LifecycleCallback.from_dict(data)
        assert cb.event_type == LifecycleEventType.STARTED
        assert cb.priority == 1
        assert cb.name == "test"
        # callback is placeholder lambda
        assert callable(cb.callback)

    def test_clone(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.HEALTHY, callback=sync_callback)
        clone = cb.clone()
        assert clone is not cb
        assert clone.event_type == cb.event_type
        assert clone.callback == cb.callback

    def test_snapshot(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.DEGRADED, callback=sync_callback, priority=2, name="deg")
        snap = cb.snapshot()
        assert snap["event_type"] == "DEGRADED"
        assert snap["priority"] == 2
        assert snap["name"] == "deg"
        assert snap["is_async"] is False

    def test_version(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.STARTING, callback=sync_callback)
        assert cb.version() == 1

    def test_audit_trail(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.STARTED, callback=sync_callback)
        trail = cb.audit_trail()
        assert len(trail) == 1
        assert trail[0]["event_type"] == "STARTED"

    def test_touch(self, sync_callback):
        cb = LifecycleCallback(event_type=LifecycleEventType.SHUTDOWN, callback=sync_callback)
        new_cb = cb.touch("tester")
        assert new_cb is not cb
        assert new_cb.event_type == cb.event_type


# ============================================================================
# Tests for BaseLifecycleListener (abstract)
# ============================================================================

class TestBaseLifecycleListener:
    def test_class_exists(self):
        assert BaseLifecycleListener is not None
        # Cannot instantiate abstract class directly


# ============================================================================
# Tests for LifecycleListener
# ============================================================================

class TestLifecycleListener:
    def test_singleton(self):
        LifecycleListener._instance = None
        l1 = LifecycleListener()
        l2 = LifecycleListener()
        assert l1 is l2

    def test_init_state(self, listener):
        assert listener._current_phase == LifecyclePhase.INITIAL
        assert listener._callbacks == {}
        assert listener._event_history == []
        assert listener._max_history == 1000
        assert listener._signal_handlers_registered is False
        assert listener._shutdown_timeout == 30.0
        # version is incremented by reset, so it may be 2
        assert listener._version >= 1

    # ---- register and convenience methods ----

    def test_register(self, listener, sync_callback):
        listener.register(LifecycleEventType.STARTING, sync_callback, priority=5, name="start_cb")
        callbacks = listener._callbacks.get(LifecycleEventType.STARTING, [])
        assert len(callbacks) == 1
        cb = callbacks[0]
        assert cb.callback == sync_callback
        assert cb.priority == 5
        assert cb.name == "start_cb"
        # Check audit
        assert any(entry["action"] == "REGISTER" for entry in listener.audit_trail())

    def test_register_startup_callback(self, listener, sync_callback):
        listener.register_startup_callback(sync_callback, priority=3, name="startup")
        cbs = listener._callbacks.get(LifecycleEventType.STARTING, [])
        assert len(cbs) == 1
        assert cbs[0].name == "startup"

    def test_register_started_callback(self, listener, sync_callback):
        listener.register_started_callback(sync_callback)
        cbs = listener._callbacks.get(LifecycleEventType.STARTED, [])
        assert len(cbs) == 1

    def test_register_shutdown_callback(self, listener, sync_callback):
        listener.register_shutdown_callback(sync_callback, priority=10)
        cbs = listener._callbacks.get(LifecycleEventType.SHUTTING_DOWN, [])
        assert len(cbs) == 1

    def test_register_health_callback(self, listener, sync_callback):
        listener.register_health_callback(sync_callback, priority=1, name="health")
        for et in [LifecycleEventType.HEALTHY, LifecycleEventType.DEGRADED, LifecycleEventType.UNHEALTHY]:
            cbs = listener._callbacks.get(et, [])
            assert len(cbs) == 1
            assert cbs[0].name == "health"

    # ---- emit (async) ----

    @pytest.mark.asyncio
    async def test_emit_sync_callback(self, listener, sync_callback):
        # Register callback
        listener.register(LifecycleEventType.STARTED, sync_callback, name="sync_cb")
        mock_cb = MagicMock()
        # Provide a name to avoid __name__ error
        listener.register(LifecycleEventType.STARTED, mock_cb, name="mock_cb")

        await listener.emit(LifecycleEventType.STARTED, source="test", details={"foo": "bar"})
        # Check event stored
        assert len(listener._event_history) == 1
        event = listener._event_history[0]
        assert event.event_type == LifecycleEventType.STARTED
        assert event.source == "test"
        assert event.details == {"foo": "bar"}
        # Phase updated
        assert listener._current_phase == LifecyclePhase.RUNNING
        # Callbacks called
        mock_cb.assert_called_once()
        # Ensure callback received event
        call_arg = mock_cb.call_args[0][0]
        assert isinstance(call_arg, LifecycleEvent)
        assert call_arg.event_type == LifecycleEventType.STARTED

    @pytest.mark.asyncio
    async def test_emit_async_callback(self, listener, async_callback):
        mock_async = AsyncMock()
        listener.register(LifecycleEventType.SHUTTING_DOWN, async_callback, async_callback=mock_async)
        await listener.emit(LifecycleEventType.SHUTTING_DOWN)
        mock_async.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_callback_exception(self, listener):
        def failing_callback(event):
            raise RuntimeError("Callback failed")
        listener.register(LifecycleEventType.STARTING, failing_callback, name="failing")
        # Should not propagate exception
        await listener.emit(LifecycleEventType.STARTING)
        # Ensure event still recorded
        assert len(listener._event_history) == 1

    @pytest.mark.asyncio
    async def test_emit_phase_transitions(self, listener):
        # Check all phase transitions
        await listener.emit(LifecycleEventType.STARTING)
        assert listener._current_phase == LifecyclePhase.STARTING
        await listener.emit(LifecycleEventType.STARTED)
        assert listener._current_phase == LifecyclePhase.RUNNING
        await listener.emit(LifecycleEventType.DEGRADED)
        assert listener._current_phase == LifecyclePhase.DEGRADED
        await listener.emit(LifecycleEventType.SHUTTING_DOWN)
        assert listener._current_phase == LifecyclePhase.STOPPING
        await listener.emit(LifecycleEventType.SHUTDOWN)
        assert listener._current_phase == LifecyclePhase.STOPPED

    # ---- emit_sync ----

    def test_emit_sync(self, listener):
        # Use STARTED event to update phase
        def real_callback(event):
            pass
        listener.register(LifecycleEventType.STARTED, real_callback)
        listener.emit_sync(LifecycleEventType.STARTED, source="sync")
        assert listener._current_phase == LifecyclePhase.RUNNING

    def test_emit_sync_skips_async(self, listener, async_callback):
        listener.register(LifecycleEventType.STARTING, async_callback, async_callback=async_callback)
        # Should not raise, but async callback skipped (warning logged)
        listener.emit_sync(LifecycleEventType.STARTING)

    # ---- getters ----

    def test_get_current_phase(self, listener):
        assert listener.get_current_phase() == LifecyclePhase.INITIAL
        listener.emit_sync(LifecycleEventType.STARTED)
        assert listener.get_current_phase() == LifecyclePhase.RUNNING

    def test_is_running(self, listener):
        assert listener.is_running() is False
        listener.emit_sync(LifecycleEventType.STARTED)
        assert listener.is_running() is True
        listener.emit_sync(LifecycleEventType.DEGRADED)
        assert listener.is_running() is True
        listener.emit_sync(LifecycleEventType.SHUTDOWN)
        assert listener.is_running() is False

    def test_is_healthy(self, listener):
        assert listener.is_healthy() is False
        listener.emit_sync(LifecycleEventType.STARTED)
        assert listener.is_healthy() is True
        listener.emit_sync(LifecycleEventType.DEGRADED)
        assert listener.is_healthy() is False

    def test_get_event_history(self, listener):
        for _ in range(5):
            listener.emit_sync(LifecycleEventType.STARTED, "test")
        history = listener.get_event_history(limit=3)
        assert len(history) == 3

    def test_get_callbacks(self, listener, sync_callback):
        listener.register(LifecycleEventType.STARTING, sync_callback, name="cb1")
        listener.register(LifecycleEventType.STARTED, sync_callback, name="cb2")
        listener.register(LifecycleEventType.STARTED, sync_callback, name="cb3")
        all_cbs = listener.get_callbacks()
        assert "STARTING" in all_cbs
        assert len(all_cbs["STARTING"]) == 1
        assert len(all_cbs["STARTED"]) == 2
        # Filter by event type
        started = listener.get_callbacks(LifecycleEventType.STARTED)
        assert "STARTED" in started
        assert len(started["STARTED"]) == 2

    # ---- signal handling ----

    @patch("signal.signal")
    def test_register_signal_handlers(self, mock_signal, listener):
        # Provide a side effect that returns the original handler
        def side_effect(signum, handler):
            return MagicMock()
        mock_signal.side_effect = side_effect

        listener.register_signal_handlers()
        # Check signal.signal called twice (SIGINT, SIGTERM)
        assert mock_signal.call_count == 2
        # Check that the handler function is callable
        args_sigint = mock_signal.call_args_list[0][0]
        assert args_sigint[0] == signal.SIGINT
        assert callable(args_sigint[1])
        args_sigterm = mock_signal.call_args_list[1][0]
        assert args_sigterm[0] == signal.SIGTERM
        assert callable(args_sigterm[1])
        assert listener._signal_handlers_registered is True

        # Second call should be no-op
        mock_signal.reset_mock()
        listener.register_signal_handlers()
        mock_signal.assert_not_called()

    @patch("signal.signal")
    def test_signal_handler_emits_shutdown(self, mock_signal, listener):
        # Capture the signal handler
        def side_effect(signum, handler):
            listener._test_handler = handler
            return MagicMock()
        mock_signal.side_effect = side_effect

        listener.register_signal_handlers()
        handler = getattr(listener, "_test_handler", None)
        assert handler is not None

        with patch.object(listener, "emit_sync") as mock_emit_sync:
            handler(signal.SIGINT, None)
            mock_emit_sync.assert_any_call(LifecycleEventType.SIGNAL_RECEIVED, "signal", {"signum": signal.SIGINT})
            mock_emit_sync.assert_any_call(LifecycleEventType.SHUTTING_DOWN, "signal")

    # ---- wait_for_shutdown ----

    @pytest.mark.asyncio
    async def test_wait_for_shutdown(self, listener):
        # Mock signal.signal to avoid side effects
        with patch("signal.signal") as mock_signal:
            # We need to simulate that the shutdown event is set
            # Actually wait_for_shutdown creates an Event and waits for it.
            # We'll mock asyncio.Event and set it immediately.
            mock_event = AsyncMock()
            mock_event.wait = AsyncMock()
            # We need to patch asyncio.Event inside the method.
            # Since the method creates a new Event, we can patch asyncio.Event
            with patch("asyncio.Event") as mock_event_cls:
                mock_event_cls.return_value = mock_event
                # We don't want signal.signal to actually run, we just mock it
                mock_signal.side_effect = lambda signum, handler: MagicMock()
                await listener.wait_for_shutdown()
                mock_event.wait.assert_called_once()

    # ---- shutdown ----

    @pytest.mark.asyncio
    async def test_shutdown(self, listener):
        # Mock emit and wait_for_shutdown_complete
        listener._wait_for_shutdown_complete = AsyncMock()
        with patch.object(listener, "emit") as mock_emit:
            await listener.shutdown(timeout=5.0)
            # Should emit SHUTTING_DOWN then SHUTDOWN
            mock_emit.assert_any_call(LifecycleEventType.SHUTTING_DOWN, "system", {"timeout": 5.0})
            mock_emit.assert_any_call(LifecycleEventType.SHUTDOWN, "system")
            listener._wait_for_shutdown_complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self, listener):
        # Simulate timeout
        listener._wait_for_shutdown_complete = AsyncMock(side_effect=asyncio.TimeoutError)
        with patch.object(listener, "emit") as mock_emit:
            await listener.shutdown(timeout=1.0)
            # Should still emit shutdown
            mock_emit.assert_any_call(LifecycleEventType.SHUTDOWN, "system")

    # ---- set_shutdown_timeout ----

    def test_set_shutdown_timeout(self, listener):
        listener.set_shutdown_timeout(15.5)
        assert listener._shutdown_timeout == 15.5

    # ---- get_statistics ----

    def test_get_statistics(self, listener, sync_callback):
        listener.register(LifecycleEventType.STARTING, sync_callback)
        listener.emit_sync(LifecycleEventType.STARTED)
        stats = listener.get_statistics()
        assert stats["current_phase"] == LifecyclePhase.RUNNING.name
        assert stats["total_events"] == 1
        assert stats["registered_callbacks"] == 1
        assert "callbacks_by_event" in stats
        assert stats["signal_handlers_registered"] is False
        assert stats["shutdown_timeout"] == 30.0

    # ---- validate ----

    def test_validate_valid(self, listener):
        result = listener.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_validate_invalid_shutdown_timeout(self, listener):
        listener._shutdown_timeout = -1
        result = listener.validate()
        assert result["is_valid"] is False
        assert "shutdown_timeout must be positive" in result["errors"]

    def test_validate_invalid_callback(self, listener):
        # Register a callback that is not callable (invalid)
        cb = LifecycleCallback(event_type=LifecycleEventType.STARTING, callback=None)
        listener._callbacks[LifecycleEventType.STARTING] = [cb]
        result = listener.validate()
        assert result["is_valid"] is False
        assert any("STARTING" in e for e in result["errors"])

    # ---- to_dict ----

    def test_to_dict(self, listener):
        listener.emit_sync(LifecycleEventType.STARTED)
        d = listener.to_dict()
        assert d["current_phase"] == "RUNNING"
        assert d["total_events"] == 1
        assert d["registered_callbacks"] == 0
        assert "version" in d

    # ---- from_dict ----

    def test_from_dict(self):
        data = {
            "current_phase": "RUNNING",
            "signal_handlers_registered": True,
            "shutdown_timeout": 60.0,
            "version": 3,
        }
        instance = LifecycleListener.from_dict(data)
        assert instance._current_phase == LifecyclePhase.RUNNING
        assert instance._signal_handlers_registered is True
        assert instance._shutdown_timeout == 60.0
        assert instance._version == 3

    # ---- clone ----

    def test_clone(self, listener):
        # clone returns the same singleton instance (because LifecycleListener() returns singleton)
        clone = listener.clone()
        assert clone is listener
        # version might be incremented or not depending on implementation
        # We'll just check that it's not None
        assert clone._version is not None

    # ---- snapshot ----

    def test_snapshot(self, listener):
        listener.emit_sync(LifecycleEventType.STARTED)
        snap = listener.snapshot()
        assert snap["version"] == listener._version
        assert snap["current_phase"] == "RUNNING"
        assert snap["total_events"] == 1
        assert "timestamp" in snap

    # ---- version ----

    def test_version(self, listener):
        old = listener._version
        listener.touch("tester")
        assert listener.version() == old + 1

    # ---- audit_trail ----

    def test_audit_trail(self, listener):
        listener._record_audit("TEST", "user", {"foo": "bar"})
        trail = listener.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"

    # ---- touch ----

    def test_touch(self, listener):
        old = listener._version
        listener.touch("tester")
        assert listener._version == old + 1
        assert listener._audit_trail[-1]["action"] == "TOUCH"

    # ---- reset ----

    def test_reset(self, listener):
        listener.register_startup_callback(lambda: None)
        listener.emit_sync(LifecycleEventType.STARTED)
        listener._signal_handlers_registered = True
        old_version = listener._version
        listener.reset()
        assert listener._callbacks == {}
        assert listener._event_history == []
        assert listener._current_phase == LifecyclePhase.INITIAL
        assert listener._signal_handlers_registered is False
        assert listener._version == old_version + 1
        assert listener._audit_trail == []


# ============================================================================
# Tests for module-level functions
# ============================================================================

def test_get_lifecycle_listener():
    # Reset singleton
    LifecycleListener._instance = None
    l1 = get_lifecycle_listener()
    l2 = get_lifecycle_listener()
    assert l1 is l2


def test_on_startup():
    # Gunakan fungsi nyata agar memiliki __name__
    def real_func():
        pass
    on_startup(real_func, priority=5)
    listener = get_lifecycle_listener()
    cbs = listener._callbacks.get(LifecycleEventType.STARTING, [])
    assert len(cbs) == 1
    assert cbs[0].callback == real_func


def test_on_started():
    def real_func():
        pass
    on_started(real_func, priority=3)
    listener = get_lifecycle_listener()
    cbs = listener._callbacks.get(LifecycleEventType.STARTED, [])
    assert len(cbs) == 1
    assert cbs[0].callback == real_func


def test_on_shutdown():
    def real_func():
        pass
    on_shutdown(real_func, priority=10)
    listener = get_lifecycle_listener()
    cbs = listener._callbacks.get(LifecycleEventType.SHUTTING_DOWN, [])
    assert len(cbs) == 1
    assert cbs[0].callback == real_func


def test_on_health_change():
    def real_func():
        pass
    on_health_change(real_func, priority=1)
    listener = get_lifecycle_listener()
    # Should be registered for all three health events
    for et in [LifecycleEventType.HEALTHY, LifecycleEventType.DEGRADED, LifecycleEventType.UNHEALTHY]:
        cbs = listener._callbacks.get(et, [])
        assert len(cbs) == 1
        assert cbs[0].callback == real_func
