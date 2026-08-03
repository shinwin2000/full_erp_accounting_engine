# tests/kernel/test_circuit_breaker.py
"""
Comprehensive tests for kernel/circuit_breaker.py
Covers all classes, methods, edge cases, exceptions, and private methods.
"""

import time
from decimal import Decimal
from unittest.mock import patch

import pytest

from kernel.circuit_breaker import (
    BaseCircuitBreaker,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerError,
    CircuitBreakerRegistry,
    CircuitOpenError,
    CircuitState,
    _FallbackMetricCollector,
    get_circuit_breaker,
    get_circuit_breaker_registry,
    with_circuit_breaker,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_circuit_breaker_registry():
    """Reset the singleton registry and clear state before each test."""
    import kernel.circuit_breaker as cb_module
    # Reset both module-level and class-level singletons
    cb_module._registry_instance = None
    CircuitBreakerRegistry._instance = None
    yield
    # Cleanup after test
    cb_module._registry_instance = None
    CircuitBreakerRegistry._instance = None


@pytest.fixture
def registry():
    """Get a fresh CircuitBreakerRegistry instance with clean state."""
    reg = get_circuit_breaker_registry()
    # Ensure it's completely clean
    reg._breakers.clear()
    reg._version = 1
    reg._audit_trail.clear()
    return reg


# ============================================================================
# Tests for _FallbackMetricCollector
# ============================================================================

class TestFallbackMetricCollector:
    def test_construction(self):
        collector = _FallbackMetricCollector()
        assert isinstance(collector, _FallbackMetricCollector)

    def test_increment_counter(self, caplog):
        collector = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            collector.increment_counter("test_counter", {"tag": "value"}, 5)
            assert "[METRIC] counter test_counter: +5" in caplog.text

    def test_set_gauge(self, caplog):
        collector = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            collector.set_gauge("test_gauge", Decimal("3.14"), {"tag": "value"})
            assert "[METRIC] gauge test_gauge: 3.14" in caplog.text

    def test_record_histogram(self, caplog):
        collector = _FallbackMetricCollector()
        with caplog.at_level("DEBUG"):
            collector.record_histogram("test_hist", Decimal("2.718"), {"tag": "value"})
            assert "[METRIC] histogram test_hist: 2.718" in caplog.text


# ============================================================================
# Tests for CircuitState Enum
# ============================================================================

class TestCircuitState:
    def test_members(self):
        assert CircuitState.CLOSED.value == "closed"
        assert CircuitState.OPEN.value == "open"
        assert CircuitState.HALF_OPEN.value == "half_open"

    def test_member_instances(self):
        assert isinstance(CircuitState.CLOSED, CircuitState)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestCircuitBreakerError:
    def test_construction_with_message(self):
        exc = CircuitBreakerError("test")
        assert str(exc) == "test"
        assert isinstance(exc, Exception)

    def test_inheritance(self):
        assert issubclass(CircuitOpenError, CircuitBreakerError)


class TestCircuitOpenError:
    def test_construction(self):
        exc = CircuitOpenError("circuit open")
        assert str(exc) == "circuit open"

    def test_raise(self):
        with pytest.raises(CircuitOpenError, match="circuit open"):
            raise CircuitOpenError("circuit open")


# ============================================================================
# Tests for CircuitBreakerConfig
# ============================================================================

class TestCircuitBreakerConfig:
    def test_default_values(self):
        config = CircuitBreakerConfig()
        assert config.failure_threshold == 5
        assert config.success_threshold == 2
        assert config.timeout_seconds == 60.0
        assert config.half_open_max_calls == 1
        assert config.record_failure_timeout_seconds == 120.0

    def test_custom_values(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            success_threshold=1,
            timeout_seconds=30.0,
            half_open_max_calls=2,
            record_failure_timeout_seconds=60.0,
        )
        assert config.failure_threshold == 3
        assert config.success_threshold == 1
        assert config.timeout_seconds == 30.0
        assert config.half_open_max_calls == 2
        assert config.record_failure_timeout_seconds == 60.0

    def test_validation_failure_threshold_zero(self):
        with pytest.raises(ValueError, match="failure_threshold must be positive"):
            CircuitBreakerConfig(failure_threshold=0)

    def test_validation_success_threshold_zero(self):
        with pytest.raises(ValueError, match="success_threshold must be positive"):
            CircuitBreakerConfig(success_threshold=0)

    def test_validation_timeout_zero(self):
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            CircuitBreakerConfig(timeout_seconds=0)

    def test_validation_half_open_max_calls_zero(self):
        with pytest.raises(ValueError, match="half_open_max_calls must be positive"):
            CircuitBreakerConfig(half_open_max_calls=0)


# ============================================================================
# Tests for BaseCircuitBreaker (abstract)
# ============================================================================

class TestBaseCircuitBreaker:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseCircuitBreaker()

    def test_abstract_methods_exist(self):
        assert hasattr(BaseCircuitBreaker, "allow_request")
        assert hasattr(BaseCircuitBreaker, "record_success")
        assert hasattr(BaseCircuitBreaker, "record_failure")
        assert hasattr(BaseCircuitBreaker, "get_state_info")
        assert hasattr(BaseCircuitBreaker, "get_metrics")
        assert hasattr(BaseCircuitBreaker, "force_close")
        assert hasattr(BaseCircuitBreaker, "force_open")
        assert hasattr(BaseCircuitBreaker, "reset")


# ============================================================================
# Tests for CircuitBreaker
# ============================================================================

class TestCircuitBreaker:
    # ---- Construction ----
    def test_construction_defaults(self):
        cb = CircuitBreaker("test")
        assert cb.name == "test"
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb.config.failure_threshold == 5

    def test_construction_with_config(self):
        config = CircuitBreakerConfig(failure_threshold=3, timeout_seconds=30.0)
        cb = CircuitBreaker("test", config=config)
        assert cb.config.failure_threshold == 3
        assert cb.config.timeout_seconds == 30.0

    def test_construction_with_params(self):
        cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=10.0, half_open_max_calls=3)
        assert cb.config.failure_threshold == 2
        assert cb.config.timeout_seconds == 10.0
        assert cb.config.half_open_max_calls == 3

    # ---- Properties ----
    def test_state_property(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        cb._state = CircuitState.OPEN
        assert cb.state == CircuitState.OPEN

    def test_failure_count_property(self):
        cb = CircuitBreaker("test")
        assert cb.failure_count == 0
        cb._failure_count = 5
        assert cb.failure_count == 5

    def test_success_count_property(self):
        cb = CircuitBreaker("test")
        assert cb.success_count == 0
        cb._success_count = 10
        assert cb.success_count == 10

    # ---- allow_request ----
    def test_allow_request_closed(self):
        cb = CircuitBreaker("test")
        assert cb.allow_request() is True

    def test_allow_request_open(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_allow_request_half_open(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        with patch.object(cb, '_update_state'):
            cb._state = CircuitState.HALF_OPEN
            cb._half_open_calls = 0
            assert cb.allow_request() is True
            assert cb._half_open_calls == 1
            assert cb.allow_request() is False
            assert cb._half_open_calls == 1

    # ---- record_success ----
    def test_record_success_closed(self):
        cb = CircuitBreaker("test")
        cb.record_success()
        assert cb.success_count == 1
        assert cb.failure_count == 0

    def test_record_success_half_open_threshold_not_reached(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 0
        cb._success_count = 0
        cb.config.success_threshold = 2
        cb.record_success()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.success_count == 1

    def test_record_success_half_open_threshold_reached(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.1)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 0
        cb._success_count = 1
        cb.config.success_threshold = 1
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.success_count == 0
        assert cb.failure_count == 0

    def test_record_success_closed_resets_failure_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb._failure_count = 2
        cb._failure_timestamps = [time.time() - 10, time.time() - 5]
        cb.record_success()
        assert cb.failure_count == 0
        assert cb._failure_timestamps == []

    # ---- record_failure ----
    def test_record_failure_closed_does_not_open(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 1

    def test_record_failure_closed_opens_when_threshold_reached(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb._open_time is not None

    def test_record_failure_half_open_opens_immediately(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb._state = CircuitState.HALF_OPEN
        cb._half_open_calls = 0
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb._half_open_calls == 0
        assert cb.failure_count == 0

    def test_record_failure_respects_time_window(self):
        cb = CircuitBreaker("test", failure_threshold=2)
        old_time = time.time() - 200
        cb._failure_timestamps = [old_time]
        cb._failure_count = 1
        cb.record_failure()
        assert cb.failure_count == 1
        assert len(cb._failure_timestamps) == 1

    # ---- _update_state ----
    def test_update_state_does_nothing_if_not_open(self):
        cb = CircuitBreaker("test")
        cb._state = CircuitState.CLOSED
        cb._update_state()
        assert cb.state == CircuitState.CLOSED

    def test_update_state_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", recovery_timeout=0.1)
        cb._state = CircuitState.OPEN
        cb._open_time = time.time() - 0.2
        cb._update_state()
        assert cb.state == CircuitState.HALF_OPEN
        assert cb._success_count == 0
        assert cb._half_open_calls == 0

    def test_update_state_does_not_transition_if_not_enough_time(self):
        cb = CircuitBreaker("test", recovery_timeout=10.0)
        cb._state = CircuitState.OPEN
        cb._open_time = time.time()
        cb._update_state()
        assert cb.state == CircuitState.OPEN

    # ---- _transition_to ----
    def test_transition_to_same_state_does_nothing(self):
        cb = CircuitBreaker("test")
        initial_history_len = len(cb._state_history)
        cb._transition_to(CircuitState.CLOSED)
        assert cb.state == CircuitState.CLOSED
        assert len(cb._state_history) == initial_history_len

    def test_transition_to_records_history(self):
        cb = CircuitBreaker("test")
        cb._transition_to(CircuitState.OPEN)
        assert cb.state == CircuitState.OPEN
        assert len(cb._state_history) == 1
        entry = cb._state_history[0]
        assert entry["from_state"] == "closed"
        assert entry["to_state"] == "open"
        assert entry["failure_count"] == cb._failure_count
        assert entry["success_count"] == cb._success_count
        assert entry["half_open_calls"] == cb._half_open_calls

    def test_transition_to_trims_history(self):
        cb = CircuitBreaker("test")
        cb._max_history = 2
        for i in range(5):
            cb._transition_to(CircuitState.OPEN if i % 2 == 0 else CircuitState.CLOSED)
        assert len(cb._state_history) == 2

    def test_transition_to_calls_metric_collector(self):
        cb = CircuitBreaker("test")
        with patch.object(cb._metric_collector, 'set_gauge') as mock_set_gauge:
            cb._transition_to(CircuitState.OPEN)
            mock_set_gauge.assert_called_once()
            args, _kwargs = mock_set_gauge.call_args
            assert args[1] == Decimal("1.0")
            assert args[2]["state"] == "open"

    # ---- _state_to_gauge ----
    def test_state_to_gauge_closed(self):
        cb = CircuitBreaker("test")
        result = cb._state_to_gauge(CircuitState.CLOSED)
        assert result == Decimal("0.0")

    def test_state_to_gauge_half_open(self):
        cb = CircuitBreaker("test")
        result = cb._state_to_gauge(CircuitState.HALF_OPEN)
        assert result == Decimal("0.5")

    def test_state_to_gauge_open(self):
        cb = CircuitBreaker("test")
        result = cb._state_to_gauge(CircuitState.OPEN)
        assert result == Decimal("1.0")

    def test_state_to_gauge_unknown(self):
        cb = CircuitBreaker("test")
        result = cb._state_to_gauge("UNKNOWN")  # type: ignore
        assert result == Decimal("0.0")

    # ---- call ----
    @pytest.mark.asyncio
    async def test_call_success(self):
        cb = CircuitBreaker("test")
        async def func():
            return "success"
        result = await cb.call(func)
        assert result == "success"
        assert cb.success_count == 1

    @pytest.mark.asyncio
    async def test_call_failure(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        async def func():
            raise ValueError("fail")
        with pytest.raises(ValueError, match="fail"):
            await cb.call(func)
        assert cb.failure_count == 1
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_call_open_raises(self):
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN
        async def func():
            return "ok"
        with pytest.raises(CircuitOpenError, match="is open"):
            await cb.call(func)

    # ---- async context manager ----
    @pytest.mark.asyncio
    async def test_async_context_manager_success(self):
        cb = CircuitBreaker("test")
        async with cb as ctx:
            assert ctx is cb
        assert cb.success_count == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_failure(self):
        cb = CircuitBreaker("test")
        with pytest.raises(ValueError, match="fail"):
            async with cb:
                raise ValueError("fail")
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_async_context_manager_open_raises(self):
        cb = CircuitBreaker("test")
        cb._state = CircuitState.OPEN
        with pytest.raises(CircuitOpenError, match="is open"):
            async with cb:
                pass

    # ---- get_state_info ----
    def test_get_state_info(self):
        cb = CircuitBreaker("test")
        info = cb.get_state_info()
        assert info["name"] == "test"
        assert info["state"] == "closed"
        assert info["failure_count"] == 0
        assert info["success_count"] == 0
        assert info["failure_threshold"] == cb.config.failure_threshold
        assert info["success_threshold"] == cb.config.success_threshold
        assert info["timeout_seconds"] == cb.config.timeout_seconds
        assert info["half_open_max_calls"] == cb.config.half_open_max_calls
        assert info["record_failure_window_seconds"] == cb.config.record_failure_timeout_seconds
        assert info["last_failure_time"] is None
        assert info["open_time"] is None
        assert info["half_open_calls"] == 0
        assert "creation_time" in info
        assert "uptime_seconds" in info

    # ---- get_metrics ----
    def test_get_metrics(self):
        cb = CircuitBreaker("test")
        metrics = cb.get_metrics()
        assert "name" in metrics
        assert "state" in metrics
        assert "failure_count" in metrics
        assert "success_count" in metrics
        assert "failure_threshold" in metrics
        assert "success_threshold" in metrics
        assert "timeout_seconds" in metrics
        assert "half_open_max_calls" in metrics

    # ---- get_state_history ----
    def test_get_state_history_default_limit(self):
        cb = CircuitBreaker("test")
        cb._state_history = [{"entry": i} for i in range(60)]
        history = cb.get_state_history()
        assert len(history) == 50

    def test_get_state_history_custom_limit(self):
        cb = CircuitBreaker("test")
        cb._state_history = [{"entry": i} for i in range(100)]
        history = cb.get_state_history(limit=20)
        assert len(history) == 20

    # ---- force_close ----
    def test_force_close(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.force_close()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb._half_open_calls == 0
        assert cb._failure_timestamps == []

    # ---- force_open ----
    def test_force_open(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        cb.force_open()
        assert cb.state == CircuitState.OPEN
        assert cb._open_time is not None

    # ---- reset ----
    def test_reset(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        cb.record_success()
        assert cb.state == CircuitState.OPEN
        assert cb._open_time is not None
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.success_count == 0
        assert cb._last_failure_time is None
        assert cb._open_time is None
        assert cb._half_open_calls == 0
        assert cb._failure_timestamps == []
        assert cb._state_history == []

    # ---- get_failure_rate ----
    def test_get_failure_rate_zero_requests(self):
        cb = CircuitBreaker("test")
        assert cb.get_failure_rate() == 0.0

    def test_get_failure_rate_only_successes(self):
        cb = CircuitBreaker("test")
        cb.record_success()
        cb.record_success()
        assert cb.get_failure_rate() == 0.0

    def test_get_failure_rate_with_failures(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.get_failure_rate() == pytest.approx(2/2, rel=1e-9)

    # ---- Entity methods ----
    def test_validate(self):
        cb = CircuitBreaker("test")
        result = cb.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self):
        cb = CircuitBreaker("test")
        data = cb.to_dict()
        assert data["name"] == "test"
        assert data["state"] == "closed"
        assert data["version"] == 1

    def test_from_dict(self):
        data = {
            "name": "restored",
            "state": "open",
            "failure_count": 3,
            "success_count": 1,
            "failure_threshold": 2,
            "success_threshold": 1,
            "timeout_seconds": 10.0,
            "half_open_max_calls": 2,
            "record_failure_window_seconds": 60.0,
            "last_failure_time": 1234567890.0,
            "open_time": 1234567895.0,
            "version": 2,
        }
        cb = CircuitBreaker.from_dict(data)
        assert cb.name == "restored"
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3
        assert cb.config.failure_threshold == 2
        assert cb.config.timeout_seconds == 10.0
        assert cb._version == 2

    def test_clone(self):
        cb = CircuitBreaker("test")
        cb._version = 5
        cloned = cb.clone()
        assert cloned is not cb
        assert cloned.name == "test_clone"
        assert cloned.config == cb.config
        assert cloned._version == 6

    def test_snapshot(self):
        cb = CircuitBreaker("test")
        snap = cb.snapshot()
        assert snap["version"] == 1
        assert snap["name"] == "test"
        assert snap["state"] == "closed"
        assert "timestamp" in snap

    def test_version(self):
        cb = CircuitBreaker("test")
        assert cb.version() == 1
        cb._version = 10
        assert cb.version() == 10

    def test_audit_trail(self):
        cb = CircuitBreaker("test")
        assert cb.audit_trail() == []
        cb._record_audit("TEST", "user", {"detail": "value"})
        trail = cb.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"

    def test_touch(self):
        cb = CircuitBreaker("test")
        initial = cb.version()
        result = cb.touch("tester")
        assert result is cb
        assert cb.version() == initial + 1
        trail = cb.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# Tests for CircuitBreakerRegistry
# ============================================================================

class TestCircuitBreakerRegistry:
    def test_singleton(self, registry):
        r1 = CircuitBreakerRegistry()
        r2 = CircuitBreakerRegistry()
        assert r1 is r2

    def test_get_or_create_new(self, registry):
        cb = registry.get_or_create("new", CircuitBreakerConfig(failure_threshold=3))
        assert isinstance(cb, CircuitBreaker)
        assert cb.name == "new"
        assert cb.config.failure_threshold == 3

    def test_get_or_create_existing(self, registry):
        cb1 = registry.get_or_create("existing")
        cb2 = registry.get_or_create("existing")
        assert cb1 is cb2

    def test_get_existing(self, registry):
        registry.get_or_create("get_test")
        cb = registry.get("get_test")
        assert isinstance(cb, CircuitBreaker)

    def test_get_nonexistent(self, registry):
        cb = registry.get("nonexistent")
        assert cb is None

    def test_record_success(self, registry):
        registry.get_or_create("success_cb")
        registry.record_success("success_cb")
        cb = registry.get("success_cb")
        assert cb.success_count == 1

    def test_record_success_nonexistent_does_nothing(self, registry):
        registry.record_success("nonexistent")

    def test_record_failure(self, registry):
        registry.get_or_create("fail_cb", CircuitBreakerConfig(failure_threshold=1))
        registry.record_failure("fail_cb")
        cb = registry.get("fail_cb")
        assert cb.state == CircuitState.OPEN

    def test_allow_request(self, registry):
        registry.get_or_create("allow_cb")
        assert registry.allow_request("allow_cb") is True
        assert registry.allow_request("unknown") is True

    def test_get_all_states(self, registry):
        registry.get_or_create("cb1")
        registry.get_or_create("cb2")
        states = registry.get_all_states()
        assert "cb1" in states
        assert "cb2" in states
        assert states["cb1"]["state"] == "closed"

    def test_force_close(self, registry):
        cb = registry.get_or_create("force_close_cb", CircuitBreakerConfig(failure_threshold=1))
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        registry.force_close("force_close_cb")
        assert cb.state == CircuitState.CLOSED

    def test_force_close_nonexistent_returns_false(self, registry):
        assert registry.force_close("unknown") is False

    def test_force_open(self, registry):
        cb = registry.get_or_create("force_open_cb")
        registry.force_open("force_open_cb")
        assert cb.state == CircuitState.OPEN

    def test_remove(self, registry):
        registry.get_or_create("to_remove")
        assert registry.remove("to_remove") is True
        assert registry.get("to_remove") is None

    def test_remove_nonexistent(self, registry):
        assert registry.remove("unknown") is False

    def test_reset_all(self, registry):
        registry.get_or_create("cb1")
        registry.get_or_create("cb2")
        registry._version = 5
        registry.reset_all()
        assert len(registry._breakers) == 0
        assert registry._version == 6

    def test_get_statistics(self, registry):
        registry.get_or_create("cb1")
        cb2 = registry.get_or_create("cb2")
        cb2.force_open()
        stats = registry.get_statistics()
        assert stats["total_circuit_breakers"] == 2
        assert stats["open_count"] == 1
        assert stats["half_open_count"] == 0
        assert stats["closed_count"] == 1
        assert "cb1" in stats["circuit_breakers"]
        assert "cb2" in stats["circuit_breakers"]

    # ---- Entity methods ----
    def test_validate(self, registry):
        result = registry.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, registry):
        registry.get_or_create("cb1")
        data = registry.to_dict()
        assert "breakers" in data
        assert "cb1" in data["breakers"]
        assert data["version"] == 1

    def test_from_dict(self, registry):
        data = {
            "breakers": {
                "restored_cb": {
                    "name": "restored_cb",
                    "state": "open",
                    "failure_count": 1,
                    "success_count": 0,
                    "failure_threshold": 2,
                    "success_threshold": 2,
                    "timeout_seconds": 60.0,
                    "half_open_max_calls": 1,
                    "record_failure_window_seconds": 120.0,
                    "last_failure_time": None,
                    "open_time": None,
                    "version": 1,
                }
            },
            "version": 3,
        }
        new_registry = CircuitBreakerRegistry.from_dict(data)
        assert "restored_cb" in new_registry._breakers
        cb = new_registry.get("restored_cb")
        assert cb.state == CircuitState.OPEN
        assert new_registry._version == 3

    def test_clone(self, registry):
        registry.get_or_create("cb1")
        old_version = registry._version
        cloned = registry.clone()
        # clone should return a new instance (or same? but we don't care about identity)
        # Just verify that the cloned registry has the same breakers and incremented version
        assert cloned is not registry  # clone creates a new instance (non-singleton)
        assert len(cloned._breakers) == 1
        assert "cb1" in cloned._breakers
        assert cloned._version == old_version + 1

    def test_snapshot(self, registry):
        registry.get_or_create("cb1")
        snap = registry.snapshot()
        assert snap["version"] == 1
        assert snap["total_breakers"] == 1
        assert "timestamp" in snap

    def test_version(self, registry):
        assert registry.version() == 1
        registry._version = 10
        assert registry.version() == 10

    def test_audit_trail(self, registry):
        assert registry.audit_trail() == []
        registry._audit_trail.append({"action": "TEST"})
        trail = registry.audit_trail()
        assert len(trail) == 1

    def test_touch(self, registry):
        initial = registry.version()
        result = registry.touch("tester")
        assert result is registry
        assert registry.version() == initial + 1
        trail = registry.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "tester"


# ============================================================================
# Tests for Singleton Accessors
# ============================================================================

def test_get_circuit_breaker_registry_singleton():
    r1 = get_circuit_breaker_registry()
    r2 = get_circuit_breaker_registry()
    assert r1 is r2


def test_get_circuit_breaker():
    config = CircuitBreakerConfig(failure_threshold=2)
    cb1 = get_circuit_breaker("global_cb", config)
    cb2 = get_circuit_breaker("global_cb", config)
    assert cb1 is cb2
    assert cb1.config.failure_threshold == 2


# ============================================================================
# Tests for with_circuit_breaker decorator
# ============================================================================

def test_with_circuit_breaker_sync_success():
    @with_circuit_breaker(name="decorator_sync")
    def sync_success():
        return "ok"
    result = sync_success()
    assert result == "ok"

    cb = get_circuit_breaker("decorator_sync")
    assert cb.success_count == 1


def test_with_circuit_breaker_sync_failure():
    @with_circuit_breaker(name="decorator_fail")
    def sync_fail():
        raise ValueError("fail")
    with pytest.raises(ValueError, match="fail"):
        sync_fail()
    cb = get_circuit_breaker("decorator_fail")
    assert cb.failure_count == 1


def test_with_circuit_breaker_sync_open_raises():
    cb = get_circuit_breaker("open_raise")
    cb.config.failure_threshold = 1
    cb.record_failure()

    @with_circuit_breaker(name="open_raise")
    def sync_func():
        return "ok"
    with pytest.raises(CircuitOpenError, match="is open"):
        sync_func()


def test_with_circuit_breaker_sync_fallback():
    cb = get_circuit_breaker("fallback_breaker")
    cb.config.failure_threshold = 1
    cb.record_failure()

    @with_circuit_breaker(name="fallback_breaker", fallback_value="fallback")
    def sync_func():
        return "should not reach"
    result = sync_func()
    assert result == "fallback"


@pytest.mark.asyncio
async def test_with_circuit_breaker_async_success():
    @with_circuit_breaker(name="decorator_async")
    async def async_success():
        return "ok"
    result = await async_success()
    assert result == "ok"
    cb = get_circuit_breaker("decorator_async")
    assert cb.success_count == 1


@pytest.mark.asyncio
async def test_with_circuit_breaker_async_failure():
    @with_circuit_breaker(name="decorator_async_fail")
    async def async_fail():
        raise ValueError("fail")
    with pytest.raises(ValueError, match="fail"):
        await async_fail()
    cb = get_circuit_breaker("decorator_async_fail")
    assert cb.failure_count == 1


@pytest.mark.asyncio
async def test_with_circuit_breaker_async_open_raises():
    cb = get_circuit_breaker("async_open_raise")
    cb.config.failure_threshold = 1
    cb.record_failure()

    @with_circuit_breaker(name="async_open_raise")
    async def async_func():
        return "ok"
    with pytest.raises(CircuitOpenError, match="is open"):
        await async_func()


@pytest.mark.asyncio
async def test_with_circuit_breaker_async_fallback():
    cb = get_circuit_breaker("async_fallback")
    cb.config.failure_threshold = 1
    cb.record_failure()

    @with_circuit_breaker(name="async_fallback", fallback_value="fallback")
    async def async_func():
        return "should not reach"
    result = await async_func()
    assert result == "fallback"
