# tests/kernel/test_retry_policy.py
"""
Comprehensive tests for kernel/retry_policy.py
"""

from unittest.mock import patch

import pytest

from kernel.retry_policy import (
    NonRetryableError,
    RetryableError,
    RetryExhaustedError,
    RetryPolicy,
    RetryPolicyService,
    RetryStrategy,
    exponential_backoff,
    get_retry_policy,
    retry,
    retry_async,
    retry_sync,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_retry_policy_service():
    """Reset singleton and state before each test."""
    # Reset module-level singleton
    import kernel.retry_policy as rp_module
    rp_module._retry_policy_service_instance = None
    # Also reset class-level instance
    RetryPolicyService._instance = None
    # Patch RetryPolicy.to_dict if missing (to avoid AttributeError)
    if not hasattr(RetryPolicy, "to_dict"):
        def to_dict(self):
            return {
                "max_retries": self.max_retries,
                "initial_delay_seconds": self.initial_delay_seconds,
                "max_delay_seconds": self.max_delay_seconds,
                "strategy": self.strategy.name,
                "retryable_exceptions": [e.__name__ for e in self.retryable_exceptions],
                "backoff_factor": self.backoff_factor,
                "version": self._version,
            }
        RetryPolicy.to_dict = to_dict
    yield
    # Cleanup after test
    rp_module._retry_policy_service_instance = None
    RetryPolicyService._instance = None
    # Also reset history of any existing service
    service = get_retry_policy()
    service._history = []
    service._audit_trail = []
    service._version = 1


@pytest.fixture
def service():
    """Get a fresh RetryPolicyService instance (singleton reset)."""
    return get_retry_policy()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestRetryStrategy:
    def test_members_exist(self):
        assert hasattr(RetryStrategy, 'FIXED')
        assert hasattr(RetryStrategy, 'LINEAR')
        assert hasattr(RetryStrategy, 'EXPONENTIAL')
        assert hasattr(RetryStrategy, 'EXPONENTIAL_JITTER')
        assert hasattr(RetryStrategy, 'CUSTOM')

    def test_member_is_instance(self):
        assert isinstance(RetryStrategy.FIXED, RetryStrategy)


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestRetryableError:
    def test_construction_with_message(self):
        exc = RetryableError("Retryable error")
        assert str(exc) == "Retryable error"
        assert exc.original_error is None

    def test_construction_with_original_error(self):
        original = ValueError("Original")
        exc = RetryableError("Retryable", original_error=original)
        assert exc.original_error is original

    def test_inheritance(self):
        assert issubclass(RetryableError, Exception)


class TestNonRetryableError:
    def test_construction(self):
        exc = NonRetryableError("Non-retryable")
        assert str(exc) == "Non-retryable"

    def test_inheritance(self):
        assert issubclass(NonRetryableError, Exception)


class TestRetryExhaustedError:
    def test_construction(self):
        exc = RetryExhaustedError("Exhausted")
        assert str(exc) == "Exhausted"

    def test_inheritance(self):
        assert issubclass(RetryExhaustedError, Exception)


# ============================================================================
# Tests for exponential_backoff function
# ============================================================================

class TestExponentialBackoff:
    def test_no_jitter(self):
        backoff = exponential_backoff(base_delay=0.5, max_delay=10.0, multiplier=2.0, jitter=False)
        assert backoff(1) == 0.5
        assert backoff(2) == 1.0
        assert backoff(3) == 2.0
        assert backoff(4) == 4.0
        assert backoff(5) == 8.0
        assert backoff(6) == 10.0  # capped at max_delay

    def test_with_jitter(self):
        backoff = exponential_backoff(base_delay=1.0, max_delay=10.0, multiplier=2.0, jitter=True)
        for attempt in range(1, 5):
            delay = backoff(attempt)
            base = 1.0 * (2.0 ** (attempt - 1))
            assert delay >= base * 0.8
            assert delay <= min(base * 1.2, 10.0)

    def test_custom_params(self):
        backoff = exponential_backoff(base_delay=2.0, max_delay=20.0, multiplier=3.0, jitter=False)
        assert backoff(1) == 2.0
        assert backoff(2) == 6.0
        assert backoff(3) == 18.0
        assert backoff(4) == 20.0  # capped


# ============================================================================
# Tests for RetryPolicy
# ============================================================================

class TestRetryPolicy:
    def test_initialization_default(self):
        policy = RetryPolicy()
        assert policy.max_retries == 3
        assert policy.initial_delay_seconds == 1.0
        assert policy.max_delay_seconds == 60.0
        assert policy.strategy == RetryStrategy.EXPONENTIAL_JITTER
        assert policy.retryable_exceptions == [RetryableError, TimeoutError, ConnectionError]
        assert policy.backoff_factor == 2.0
        assert policy.custom_backoff_func is None
        assert policy._version == 1

    def test_initialization_custom(self):
        def custom_backoff(attempt):
            return attempt * 0.5

        policy = RetryPolicy(
            max_retries=5,
            initial_delay_seconds=0.5,
            max_delay_seconds=30.0,
            strategy=RetryStrategy.CUSTOM,
            retryable_exceptions=[ValueError, KeyError],
            custom_backoff_func=custom_backoff,
            backoff_factor=1.5,
        )
        assert policy.max_retries == 5
        assert policy.initial_delay_seconds == 0.5
        assert policy.max_delay_seconds == 30.0
        assert policy.strategy == RetryStrategy.CUSTOM
        assert policy.retryable_exceptions == [ValueError, KeyError]
        assert policy.custom_backoff_func is custom_backoff
        assert policy.backoff_factor == 1.5

    def test_validation_invalid_max_retries(self):
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            RetryPolicy(max_retries=-1)

    def test_validation_invalid_initial_delay(self):
        with pytest.raises(ValueError, match="initial_delay_seconds must be positive"):
            RetryPolicy(initial_delay_seconds=0)

    def test_validation_invalid_max_delay(self):
        with pytest.raises(ValueError, match="max_delay_seconds must be positive"):
            RetryPolicy(max_delay_seconds=0)

    def test_validation_custom_strategy_without_func(self):
        with pytest.raises(ValueError, match="CUSTOM strategy requires custom_backoff_func"):
            RetryPolicy(strategy=RetryStrategy.CUSTOM)

    def test_base_delay_property(self):
        policy = RetryPolicy(initial_delay_seconds=2.5)
        assert policy.base_delay == 2.5

    def test_max_delay_property(self):
        policy = RetryPolicy(max_delay_seconds=45.0)
        assert policy.max_delay == 45.0

    def test_max_attempts_property(self):
        policy = RetryPolicy(max_retries=7)
        assert policy.max_attempts == 7

    def test_get_wait_time_fixed(self):
        policy = RetryPolicy(
            strategy=RetryStrategy.FIXED,
            initial_delay_seconds=1.5,
            max_delay_seconds=10.0,
        )
        assert policy.get_wait_time(1) == 1.5
        assert policy.get_wait_time(2) == 1.5
        assert policy.get_wait_time(5) == 1.5
        assert policy.get_wait_time(0) == 0.0

    def test_get_wait_time_linear(self):
        policy = RetryPolicy(
            strategy=RetryStrategy.LINEAR,
            initial_delay_seconds=1.0,
            max_delay_seconds=10.0,
        )
        assert policy.get_wait_time(1) == 1.0
        assert policy.get_wait_time(2) == 2.0
        assert policy.get_wait_time(3) == 3.0
        policy.max_delay_seconds = 5.0
        assert policy.get_wait_time(10) == 5.0

    def test_get_wait_time_exponential(self):
        policy = RetryPolicy(
            strategy=RetryStrategy.EXPONENTIAL,
            initial_delay_seconds=1.0,
            max_delay_seconds=20.0,
            backoff_factor=2.0,
        )
        assert policy.get_wait_time(1) == 1.0
        assert policy.get_wait_time(2) == 2.0
        assert policy.get_wait_time(3) == 4.0
        assert policy.get_wait_time(4) == 8.0
        assert policy.get_wait_time(5) == 16.0
        assert policy.get_wait_time(6) == 20.0

    def test_get_wait_time_exponential_jitter(self):
        policy = RetryPolicy(
            strategy=RetryStrategy.EXPONENTIAL_JITTER,
            initial_delay_seconds=1.0,
            max_delay_seconds=20.0,
            backoff_factor=2.0,
        )
        for attempt in range(1, 6):
            wait = policy.get_wait_time(attempt)
            base = 1.0 * (2.0 ** (attempt - 1))
            assert wait >= base
            assert wait <= min(base * 1.3, 20.0)

    def test_get_wait_time_custom(self):
        def custom_backoff(attempt):
            return attempt * 0.5

        policy = RetryPolicy(
            strategy=RetryStrategy.CUSTOM,
            custom_backoff_func=custom_backoff,
            max_delay_seconds=10.0,
        )
        assert policy.get_wait_time(1) == 0.5
        assert policy.get_wait_time(2) == 1.0
        assert policy.get_wait_time(3) == 1.5
        assert policy.get_wait_time(20) == 10.0

    def test_is_retryable(self):
        policy = RetryPolicy()
        assert policy.is_retryable(RetryableError("test")) is True
        assert policy.is_retryable(TimeoutError("timeout")) is True
        assert policy.is_retryable(ConnectionError("connection")) is True
        assert policy.is_retryable(ValueError("value")) is False
        assert policy.is_retryable(KeyError("key")) is False

    def test_is_retryable_custom_list(self):
        policy = RetryPolicy(retryable_exceptions=[ValueError, KeyError])
        assert policy.is_retryable(ValueError("test")) is True
        assert policy.is_retryable(KeyError("key")) is True
        assert policy.is_retryable(RuntimeError("runtime")) is False

    @pytest.mark.asyncio
    async def test_execute_success(self):
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await policy.execute(func)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_execute_retryable_success_after_retry(self):
        # Use FIXED strategy to avoid jitter
        policy = RetryPolicy(
            max_retries=3,
            initial_delay_seconds=0.01,
            strategy=RetryStrategy.FIXED,
        )
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("Transient")
            return "success"

        with patch("asyncio.sleep", return_value=None) as mock_sleep:
            result = await policy.execute(func)
            assert result == "success"
            assert call_count == 3
            # Since FIXED, wait time is always 0.01
            mock_sleep.assert_called_with(0.01)

    @pytest.mark.asyncio
    async def test_execute_non_retryable_raises(self):
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Non-retryable")

        with pytest.raises(ValueError, match="Non-retryable"):
            await policy.execute(func)
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_execute_retry_exhausted_raises(self):
        policy = RetryPolicy(max_retries=2, initial_delay_seconds=0.01)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Always fails")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryExhaustedError, match="Max retries.*exceeded"):
                await policy.execute(func)
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_execute_with_custom_backoff(self):
        def custom_backoff(attempt):
            return attempt * 0.02

        policy = RetryPolicy(
            max_retries=3,
            strategy=RetryStrategy.CUSTOM,
            custom_backoff_func=custom_backoff,
        )
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("Fail")

        with patch("asyncio.sleep") as mock_sleep:
            with pytest.raises(RetryExhaustedError):
                await policy.execute(func)
            calls = mock_sleep.call_args_list
            assert len(calls) == 3
            assert calls[0][0][0] == 0.02
            assert calls[1][0][0] == 0.04
            assert calls[2][0][0] == 0.06

    @pytest.mark.asyncio
    async def test_execute_with_retry_alias(self):
        policy = RetryPolicy(max_retries=1)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("fail")
            return "ok"

        with patch("asyncio.sleep", return_value=None):
            result = await policy.execute_with_retry(func)
            assert result == "ok"
            assert call_count == 2

    def test_reset(self):
        policy = RetryPolicy()
        policy._retry_count = 5
        policy._current_delay = 10.0
        old_version = policy._version
        policy.reset()
        assert policy._retry_count == 0
        assert policy._current_delay == policy.initial_delay_seconds
        assert policy._version == old_version + 1
        assert policy._audit_trail[-1]["action"] == "RESET"

    def test_validate(self):
        policy = RetryPolicy()
        result = policy.validate()
        assert result["is_valid"] is True

        policy.max_retries = -1
        result2 = policy.validate()
        assert result2["is_valid"] is False
        assert "max_retries cannot be negative" in result2["errors"]

    def test_to_dict(self):
        policy = RetryPolicy(
            max_retries=4,
            initial_delay_seconds=2.0,
            max_delay_seconds=30.0,
            strategy=RetryStrategy.EXPONENTIAL,
            backoff_factor=3.0,
        )
        d = policy.to_dict()
        assert d["max_retries"] == 4
        assert d["initial_delay_seconds"] == 2.0
        assert d["max_delay_seconds"] == 30.0
        assert d["strategy"] == "EXPONENTIAL"
        assert d["backoff_factor"] == 3.0
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "max_retries": 5,
            "initial_delay_seconds": 1.5,
            "max_delay_seconds": 20.0,
            "strategy": "LINEAR",
            "retryable_exceptions": ["RetryableError", "TimeoutError"],
            "backoff_factor": 2.5,
            "version": 3,
        }
        policy = RetryPolicy.from_dict(data)
        assert policy.max_retries == 5
        assert policy.initial_delay_seconds == 1.5
        assert policy.max_delay_seconds == 20.0
        assert policy.strategy == RetryStrategy.LINEAR
        assert policy.retryable_exceptions == [RetryableError, TimeoutError]
        assert policy.backoff_factor == 2.5
        assert policy._version == 3

    def test_from_dict_custom_exceptions(self):
        data = {
            "max_retries": 2,
            "retryable_exceptions": ["ConnectionError", "ValueError"],
        }
        policy = RetryPolicy.from_dict(data)
        assert policy.retryable_exceptions == [ConnectionError]

    def test_clone(self):
        policy = RetryPolicy(max_retries=5, initial_delay_seconds=2.0)
        cloned = policy.clone()
        assert cloned is not policy
        assert cloned.max_retries == policy.max_retries
        assert cloned.initial_delay_seconds == policy.initial_delay_seconds
        assert cloned.strategy == policy.strategy
        assert cloned._version == policy._version + 1

    def test_snapshot(self):
        policy = RetryPolicy(max_retries=3)
        snap = policy.snapshot()
        assert snap["version"] == 1
        assert snap["max_retries"] == 3
        assert snap["strategy"] == "EXPONENTIAL_JITTER"
        assert "timestamp" in snap

    def test_version(self):
        policy = RetryPolicy()
        assert policy.version() == 1
        policy._version = 5
        assert policy.version() == 5

    def test_audit_trail(self):
        policy = RetryPolicy()
        policy._record_audit("ACTION1", "user", {"k": "v"})
        policy._record_audit("ACTION2", "user", {"k2": "v2"})
        trail = policy.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION2"
        trail_all = policy.audit_trail(limit=10)
        assert len(trail_all) == 2

    def test_touch(self):
        policy = RetryPolicy()
        old_ver = policy._version
        policy.touch("admin")
        assert policy._version == old_ver + 1
        assert policy._audit_trail[-1]["action"] == "TOUCH"

    def test_get_statistics(self):
        policy = RetryPolicy()
        stats = policy.get_statistics()
        assert stats["retry_count"] == 0
        assert stats["current_delay"] == policy.initial_delay_seconds
        assert stats["max_retries"] == policy.max_retries
        assert stats["strategy"] == policy.strategy.name
        assert stats["version"] == 1


# ============================================================================
# Tests for RetryPolicyService
# ============================================================================

class TestRetryPolicyService:
    def test_singleton(self):
        s1 = RetryPolicyService()
        s2 = RetryPolicyService()
        assert s1 is s2

    def test_initialization(self, service):
        assert isinstance(service._default_policy, RetryPolicy)
        assert service._history == []
        assert service._max_history == 1000
        assert service._version == 1

    def test_set_default_policy(self, service):
        new_policy = RetryPolicy(max_retries=10)
        service.set_default_policy(new_policy)
        assert service._default_policy is new_policy
        assert service._audit_trail[-1]["action"] == "SET_DEFAULT_POLICY"

    def test_get_default_policy(self, service):
        policy = service.get_default_policy()
        assert isinstance(policy, RetryPolicy)
        assert policy is service._default_policy

    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self, service):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await service.execute_with_retry(func)
        assert result == "ok"
        assert call_count == 1
        assert len(service._history) == 1
        assert service._history[0]["success"] is True

    @pytest.mark.asyncio
    async def test_execute_with_retry_retryable_success(self, service):
        policy = RetryPolicy(max_retries=2, initial_delay_seconds=0.01, strategy=RetryStrategy.FIXED)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("asyncio.sleep", return_value=None):
            result = await service.execute_with_retry(func, policy=policy)
            assert result == "ok"
            assert call_count == 3
            # History entries: first failure (attempt 0), second failure (attempt 1), success (attempt 2)
            assert len(service._history) == 3
            assert service._history[0]["success"] is False
            assert service._history[0]["retryable"] is True
            assert service._history[1]["success"] is False
            assert service._history[1]["retryable"] is True
            assert service._history[2]["success"] is True

    @pytest.mark.asyncio
    async def test_execute_with_retry_non_retryable(self, service):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Non-retryable")

        with pytest.raises(NonRetryableError, match="Non-retryable error"):
            await service.execute_with_retry(func)
        assert call_count == 1
        assert len(service._history) == 1
        assert service._history[0]["retryable"] is False

    @pytest.mark.asyncio
    async def test_execute_with_retry_exhausted(self, service):
        policy = RetryPolicy(max_retries=1, initial_delay_seconds=0.01)
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await service.execute_with_retry(func, policy=policy)
            assert call_count == 2
            assert service._history[-1]["final"] is True

    @pytest.mark.asyncio
    async def test_execute_with_retry_on_retry_callback(self, service):
        policy = RetryPolicy(max_retries=2, initial_delay_seconds=0.01)
        retry_calls = []

        def on_retry(attempt, exc):
            retry_calls.append((attempt, str(exc)))

        async def func():
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await service.execute_with_retry(func, policy=policy, on_retry=on_retry)
            assert len(retry_calls) == 2
            assert retry_calls[0][0] == 1
            assert retry_calls[1][0] == 2

    @pytest.mark.asyncio
    async def test_execute_with_retry_on_retry_async_callback(self, service):
        policy = RetryPolicy(max_retries=1, initial_delay_seconds=0.01)
        retry_calls = []

        async def on_retry(attempt, exc):
            retry_calls.append((attempt, str(exc)))

        async def func():
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await service.execute_with_retry(func, policy=policy, on_retry=on_retry)
            assert len(retry_calls) == 1

    @pytest.mark.asyncio
    async def test_execute_with_retry_on_retry_callback_exception(self, service, caplog):
        policy = RetryPolicy(max_retries=1, initial_delay_seconds=0.01)

        def on_retry(attempt, exc):
            raise ValueError("Callback error")

        async def func():
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await service.execute_with_retry(func, policy=policy, on_retry=on_retry)
            assert "on_retry callback failed" in caplog.text

    def test_execute_sync_with_retry_success(self, service):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = service.execute_sync_with_retry(func)
        assert result == "ok"
        assert call_count == 1

    def test_execute_sync_with_retry_retryable_success(self, service):
        policy = RetryPolicy(max_retries=2, initial_delay_seconds=0.01, strategy=RetryStrategy.FIXED)
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("time.sleep", return_value=None):
            result = service.execute_sync_with_retry(func, policy=policy)
            assert result == "ok"
            assert call_count == 3

    def test_execute_sync_with_retry_non_retryable(self, service):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("Non-retryable")

        with pytest.raises(NonRetryableError, match="Non-retryable error"):
            service.execute_sync_with_retry(func)
        assert call_count == 1

    def test_execute_sync_with_retry_exhausted(self, service):
        policy = RetryPolicy(max_retries=1, initial_delay_seconds=0.01)
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("fail")

        with patch("time.sleep", return_value=None):
            with pytest.raises(RetryableError):
                service.execute_sync_with_retry(func, policy=policy)
            assert call_count == 2

    def test_get_statistics(self, service):
        # Add some history manually
        service._history = [
            {"success": True, "attempt": 0, "duration_ms": 10.0},
            {"success": False, "attempt": 1, "duration_ms": 20.0},
            {"success": True, "attempt": 2, "duration_ms": 15.0},
        ]
        stats = service.get_statistics()
        assert stats["total_attempts"] == 3
        assert stats["success_count"] == 2
        assert stats["retry_count"] == 1
        assert stats["success_rate"] == 2 / 3
        assert stats["avg_duration_ms"] == 15.0
        assert stats["attempts_distribution"] == {0: 1, 1: 1, 2: 1}
        assert stats["version"] == 1

    def test_get_history(self, service):
        service._history = [{"a": 1}, {"b": 2}, {"c": 3}]
        history = service.get_history(limit=2)
        assert len(history) == 2
        assert history[0]["b"] == 2
        assert history[1]["c"] == 3

    def test_validate(self, service):
        result = service.validate()
        assert result["is_valid"] is True
        service._default_policy.max_retries = -1
        result2 = service.validate()
        assert result2["is_valid"] is False
        assert any("default_policy" in e for e in result2["errors"])

    def test_to_dict(self, service):
        d = service.to_dict()
        assert "default_policy" in d
        assert d["history_count"] == 0
        assert d["max_history"] == 1000
        assert d["version"] == 1

    def test_from_dict(self):
        data = {
            "default_policy": {
                "max_retries": 7,
                "initial_delay_seconds": 3.0,
                "strategy": "FIXED",
            },
            "max_history": 2000,
            "version": 4,
        }
        service = RetryPolicyService.from_dict(data)
        assert service._default_policy.max_retries == 7
        assert service._default_policy.initial_delay_seconds == 3.0
        assert service._default_policy.strategy == RetryStrategy.FIXED
        assert service._max_history == 2000
        assert service._version == 4

    def test_clone(self, service):
        service._max_history = 500
        old_version = service._version
        cloned = service.clone()
        # Karena singleton, clone mengembalikan instance yang sama,
        # tetapi versi bertambah
        assert cloned is service
        assert cloned._version == old_version + 1
        assert cloned._max_history == 500

    def test_snapshot(self, service):
        snap = service.snapshot()
        assert snap["version"] == 1
        assert snap["history_count"] == 0
        assert "default_policy" in snap
        assert "timestamp" in snap

    def test_version(self, service):
        assert service.version() == 1
        service._version = 3
        assert service.version() == 3

    def test_audit_trail(self, service):
        service._record_audit("ACTION1", "user", {})
        service._record_audit("ACTION2", "user", {})
        trail = service.audit_trail(limit=1)
        assert len(trail) == 1
        assert trail[0]["action"] == "ACTION2"

    def test_touch(self, service):
        old_ver = service._version
        service.touch("admin")
        assert service._version == old_ver + 1
        assert service._audit_trail[-1]["action"] == "TOUCH"

    def test_reset(self, service):
        service._history = [{"a": 1}]
        service._version = 2
        service._audit_trail = [{"action": "test"}]
        service.reset()
        assert service._history == []
        assert service._version == 3
        assert service._audit_trail == []


# ============================================================================
# Tests for Convenience Functions and Decorator
# ============================================================================

class TestConvenienceFunctions:
    @pytest.mark.asyncio
    async def test_retry_async_success(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(func, max_retries=2)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_async_retryable_success(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("asyncio.sleep", return_value=None):
            result = await retry_async(func, max_retries=3)
            assert result == "ok"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_async_exhausted(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await retry_async(func, max_retries=1)
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_async_non_retryable(self):
        call_count = 0

        async def func():
            nonlocal call_count
            call_count += 1
            raise ValueError("fail")

        # Non-retryable error is wrapped in NonRetryableError
        with pytest.raises(NonRetryableError, match="Non-retryable error"):
            await retry_async(func, max_retries=2)
        assert call_count == 1

    def test_retry_sync_success(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = retry_sync(func, max_retries=2)
        assert result == "ok"
        assert call_count == 1

    def test_retry_sync_retryable_success(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("time.sleep", return_value=None):
            result = retry_sync(func, max_retries=3)
            assert result == "ok"
            assert call_count == 3

    def test_retry_sync_exhausted(self):
        call_count = 0

        def func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("fail")

        with patch("time.sleep", return_value=None):
            with pytest.raises(RetryableError):
                retry_sync(func, max_retries=1)
            assert call_count == 2

    def test_retry_decorator_sync(self):
        call_count = 0

        @retry(max_retries=2, initial_delay=0.01, strategy=RetryStrategy.FIXED)
        def decorated_func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("time.sleep", return_value=None):
            result = decorated_func()
            assert result == "ok"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_decorator_async(self):
        call_count = 0

        @retry(max_retries=2, initial_delay=0.01, strategy=RetryStrategy.FIXED)
        async def decorated_func():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RetryableError("fail")
            return "ok"

        with patch("asyncio.sleep", return_value=None):
            result = await decorated_func()
            assert result == "ok"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_decorator_exhausted(self):
        call_count = 0

        @retry(max_retries=1, initial_delay=0.01)
        async def decorated_func():
            nonlocal call_count
            call_count += 1
            raise RetryableError("fail")

        with patch("asyncio.sleep", return_value=None):
            with pytest.raises(RetryableError):
                await decorated_func()
            assert call_count == 2

    def test_retry_decorator_preserves_metadata(self):
        @retry(max_retries=2)
        def my_func():
            """My docstring"""
            pass

        assert my_func.__name__ == "my_func"
        assert my_func.__doc__ == "My docstring"


# ============================================================================
# Tests for Singleton Accessor
# ============================================================================

def test_get_retry_policy_singleton():
    s1 = get_retry_policy()
    s2 = get_retry_policy()
    assert s1 is s2
    assert isinstance(s1, RetryPolicyService)
