#!/usr/bin/env python3
"""
Module: test_retry_policy.py
Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk retry policy dengan exponential backoff.
"""

from __future__ import annotations

import pytest

from kernel.retry_policy import RetryExhaustedError, RetryPolicy, RetryStrategy


class TestRetryPolicy:
    @pytest.fixture
    def retry_policy(self):
        return RetryPolicy(
            max_retries=3,
            initial_delay_seconds=0.01,  # kecil agar test cepat
            max_delay_seconds=1.0,
            backoff_factor=2.0,
            strategy=RetryStrategy.EXPONENTIAL_JITTER,
            retryable_exceptions=[ValueError, Exception],  # tambahkan ValueError
        )

    async def test_retry_success_after_retries(self, retry_policy):
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("Temporary failure")
            return "success"

        result = await retry_policy.execute(op)
        assert result == "success"
        assert call_count == 3

    async def test_retry_exhausted(self, retry_policy):
        call_count = 0

        async def op():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fail")

        with pytest.raises(RetryExhaustedError):
            await retry_policy.execute(op)
        assert call_count == retry_policy.max_retries + 1  # 4 attempts total

    async def test_no_retry_on_success(self, retry_policy):
        async def success_op():
            return "ok"

        result = await retry_policy.execute(success_op)
        assert result == "ok"

    async def test_exponential_backoff(self, retry_policy):
        policy = RetryPolicy(
            max_retries=3,
            initial_delay_seconds=0.1,
            max_delay_seconds=1.0,
            backoff_factor=2.0,
            strategy=RetryStrategy.EXPONENTIAL,  # no jitter
        )
        actual_delays = []
        for attempt in range(1, 4):
            actual_delays.append(policy.get_wait_time(attempt))
        assert actual_delays == [0.1, 0.2, 0.4]

    async def test_retry_on_specific_exceptions(self):
        policy = RetryPolicy(
            max_retries=2, initial_delay_seconds=0.01, retryable_exceptions=[ValueError]
        )

        async def op():
            raise TypeError("Not retryable")

        with pytest.raises(TypeError):
            await policy.execute(op)

    def test_reset_policy(self, retry_policy):
        retry_policy._retry_count = 2
        retry_policy._current_delay = 0.5
        retry_policy.reset()
        assert retry_policy._retry_count == 0
        assert retry_policy._current_delay == retry_policy.initial_delay_seconds

    async def test_retryable_error_with_original_exception(self):
        from kernel.retry_policy import RetryableError

        policy = RetryPolicy(max_retries=1, initial_delay_seconds=0.01)
        original = ValueError("DB deadlock")
        error = RetryableError("Transient error", original_error=original)

        async def op():
            raise error

        with pytest.raises(RetryExhaustedError):
            await policy.execute(op)

    async def test_non_retryable_error_immediate_raise(self):
        policy = RetryPolicy(max_retries=2, initial_delay_seconds=0.01)

        async def op():
            raise ValueError("Not retryable")  # ValueError not in default retryable list

        with pytest.raises(ValueError, match="Not retryable"):
            await policy.execute(op)


if __name__ == "__main__":
    pytest.main([__file__])
