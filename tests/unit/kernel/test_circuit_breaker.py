#!/usr/bin/env python3
"""
Module: test_circuit_breaker.py

Unit tests untuk circuit breaker pattern.
"""

from __future__ import annotations

import asyncio

import pytest

from kernel.circuit_breaker import CircuitBreaker, CircuitBreakerState, CircuitOpenError


class TestCircuitBreaker:
    """Test suite untuk CircuitBreaker."""

    @pytest.fixture
    def circuit_breaker(self):
        return CircuitBreaker(
            name="test_cb",
            failure_threshold=3,
            recovery_timeout=0.5,
            half_open_max_calls=2,
        )

        async def successful_operation(self):
            return "success"

            async def failing_operation(self):
                raise ValueError("Operation failed")

                async def test_initial_state_closed(self, circuit_breaker):
                    assert circuit_breaker.state == CircuitBreakerState.CLOSED
                    assert circuit_breaker.failure_count == 0

                    async def test_successful_call_does_not_change_state(self, circuit_breaker):
                        result = await circuit_breaker.call(self.successful_operation)
                        assert result == "success"
                        assert circuit_breaker.state == CircuitBreakerState.CLOSED
                        assert circuit_breaker.failure_count == 0

                        async def test_failure_increments_failure_count(self, circuit_breaker):
                            with pytest.raises(ValueError, match="Operation failed"):
                                await circuit_breaker.call(self.failing_operation)
                                assert circuit_breaker.failure_count == 1
                                assert circuit_breaker.state == CircuitBreakerState.CLOSED

                                async def test_failure_threshold_opens_circuit(
                                    self, circuit_breaker
                                ):
                                    for _ in range(3):
                                        with pytest.raises(ValueError):
                                            await circuit_breaker.call(self.failing_operation)
                                            assert circuit_breaker.failure_count == 3
                                            assert circuit_breaker.state == CircuitBreakerState.OPEN

                                            with pytest.raises(CircuitOpenError):
                                                await circuit_breaker.call(
                                                    self.successful_operation
                                                )

                                                async def test_circuit_opens_and_then_half_open_after_timeout(
                                                    self, circuit_breaker
                                                ):
                                                    # Open circuit
                                                    for _ in range(3):
                                                        with pytest.raises(ValueError):
                                                            await circuit_breaker.call(
                                                                self.failing_operation
                                                            )
                                                            assert (
                                                                circuit_breaker.state
                                                                == CircuitBreakerState.OPEN
                                                            )

                                                            # Wait for recovery timeout
                                                            await asyncio.sleep(0.6)

                                                            # Trigger state update by calling allow_request()
                                                            circuit_breaker.allow_request()
                                                            assert (
                                                                circuit_breaker.state
                                                                == CircuitBreakerState.HALF_OPEN
                                                            )

                                                            # First success in half-open (needs 2 successes to close)
                                                            result = await circuit_breaker.call(
                                                                self.successful_operation
                                                            )
                                                            assert result == "success"
                                                            assert (
                                                                circuit_breaker.state
                                                                == CircuitBreakerState.HALF_OPEN
                                                            )

                                                            # Second success closes the circuit
                                                            result = await circuit_breaker.call(
                                                                self.successful_operation
                                                            )
                                                            assert result == "success"
                                                            assert (
                                                                circuit_breaker.state
                                                                == CircuitBreakerState.CLOSED
                                                            )
                                                            assert (
                                                                circuit_breaker.failure_count == 0
                                                            )

                                                            async def test_half_open_failure_reopens_circuit(
                                                                self, circuit_breaker
                                                            ):
                                                                # Open circuit
                                                                for _ in range(3):
                                                                    with pytest.raises(ValueError):
                                                                        await circuit_breaker.call(
                                                                            self.failing_operation
                                                                        )
                                                                        await asyncio.sleep(0.6)

                                                                        # Trigger transition to half-open
                                                                        circuit_breaker.allow_request()
                                                                        assert (
                                                                            circuit_breaker.state
                                                                            == CircuitBreakerState.HALF_OPEN
                                                                        )

                                                                        # A failure in half-open re-opens the circuit
                                                                        with pytest.raises(
                                                                            ValueError
                                                                        ):
                                                                            await circuit_breaker.call(
                                                                                self.failing_operation
                                                                            )

                                                                            assert (
                                                                                circuit_breaker.state
                                                                                == CircuitBreakerState.OPEN
                                                                            )
                                                                            assert (
                                                                                circuit_breaker.failure_count
                                                                                == 0
                                                                            )  # reset after re-open

                                                                            async def test_half_open_success_closes_circuit(
                                                                                self,
                                                                                circuit_breaker,
                                                                            ):
                                                                                # Open circuit
                                                                                for _ in range(3):
                                                                                    with pytest.raises(
                                                                                        ValueError
                                                                                    ):
                                                                                        await circuit_breaker.call(
                                                                                            self.failing_operation
                                                                                        )
                                                                                        await asyncio.sleep(
                                                                                            0.6
                                                                                        )

                                                                                        # Transition to half-open
                                                                                        circuit_breaker.allow_request()
                                                                                        assert (
                                                                                            circuit_breaker.state
                                                                                            == CircuitBreakerState.HALF_OPEN
                                                                                        )

                                                                                        # First success
                                                                                        result = await circuit_breaker.call(
                                                                                            self.successful_operation
                                                                                        )
                                                                                        assert (
                                                                                            result
                                                                                            == "success"
                                                                                        )
                                                                                        assert (
                                                                                            circuit_breaker.state
                                                                                            == CircuitBreakerState.HALF_OPEN
                                                                                        )

                                                                                        # Second success closes
                                                                                        result = await circuit_breaker.call(
                                                                                            self.successful_operation
                                                                                        )
                                                                                        assert (
                                                                                            result
                                                                                            == "success"
                                                                                        )
                                                                                        assert (
                                                                                            circuit_breaker.state
                                                                                            == CircuitBreakerState.CLOSED
                                                                                        )

                                                                                        async def test_half_open_max_calls_limit(
                                                                                            self,
                                                                                            circuit_breaker,
                                                                                        ):
                                                                                            # Open circuit
                                                                                            for _ in range(
                                                                                                3
                                                                                            ):
                                                                                                with pytest.raises(
                                                                                                    ValueError
                                                                                                ):
                                                                                                    await circuit_breaker.call(
                                                                                                        self.failing_operation
                                                                                                    )
                                                                                                    await asyncio.sleep(
                                                                                                        0.6
                                                                                                    )

                                                                                                    # Transition to half-open
                                                                                                    circuit_breaker.allow_request()
                                                                                                    assert (
                                                                                                        circuit_breaker.state
                                                                                                        == CircuitBreakerState.HALF_OPEN
                                                                                                    )

                                                                                                    # First success (allowed)
                                                                                                    result1 = await circuit_breaker.call(
                                                                                                        self.successful_operation
                                                                                                    )
                                                                                                    assert (
                                                                                                        result1
                                                                                                        == "success"
                                                                                                    )
                                                                                                    assert (
                                                                                                        circuit_breaker.state
                                                                                                        == CircuitBreakerState.HALF_OPEN
                                                                                                    )

                                                                                                    # Second success (allowed, and will close)
                                                                                                    result2 = await circuit_breaker.call(
                                                                                                        self.successful_operation
                                                                                                    )
                                                                                                    assert (
                                                                                                        result2
                                                                                                        == "success"
                                                                                                    )
                                                                                                    assert (
                                                                                                        circuit_breaker.state
                                                                                                        == CircuitBreakerState.CLOSED
                                                                                                    )

                                                                                                    async def test_reset_circuit_breaker(
                                                                                                        self,
                                                                                                        circuit_breaker,
                                                                                                    ):
                                                                                                        for _ in range(
                                                                                                            3
                                                                                                        ):
                                                                                                            with pytest.raises(
                                                                                                                ValueError
                                                                                                            ):
                                                                                                                await circuit_breaker.call(
                                                                                                                    self.failing_operation
                                                                                                                )
                                                                                                                assert (
                                                                                                                    circuit_breaker.state
                                                                                                                    == CircuitBreakerState.OPEN
                                                                                                                )

                                                                                                                circuit_breaker.reset()
                                                                                                                assert (
                                                                                                                    circuit_breaker.state
                                                                                                                    == CircuitBreakerState.CLOSED
                                                                                                                )
                                                                                                                assert (
                                                                                                                    circuit_breaker.failure_count
                                                                                                                    == 0
                                                                                                                )

                                                                                                                async def test_context_manager(
                                                                                                                    self,
                                                                                                                    circuit_breaker,
                                                                                                                ):
                                                                                                                    async with circuit_breaker:
                                                                                                                        result = await self.successful_operation()
                                                                                                                        assert (
                                                                                                                            result
                                                                                                                            == "success"
                                                                                                                        )
                                                                                                                        assert (
                                                                                                                            circuit_breaker.state
                                                                                                                            == CircuitBreakerState.CLOSED
                                                                                                                        )

                                                                                                                        with pytest.raises(
                                                                                                                            ValueError
                                                                                                                        ):
                                                                                                                            async with circuit_breaker:
                                                                                                                                await self.failing_operation()
                                                                                                                                assert (
                                                                                                                                    circuit_breaker.failure_count
                                                                                                                                    == 1
                                                                                                                                )

                                                                                                                                async def test_circuit_breaker_metrics(
                                                                                                                                    self,
                                                                                                                                    circuit_breaker,
                                                                                                                                ):
                                                                                                                                    metrics = circuit_breaker.get_metrics()
                                                                                                                                    assert (
                                                                                                                                        metrics[
                                                                                                                                            "name"
                                                                                                                                        ]
                                                                                                                                        == "test_cb"
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        metrics[
                                                                                                                                            "state"
                                                                                                                                        ]
                                                                                                                                        == CircuitBreakerState.CLOSED.value
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        metrics[
                                                                                                                                            "failure_count"
                                                                                                                                        ]
                                                                                                                                        == 0
                                                                                                                                    )
                                                                                                                                    assert (
                                                                                                                                        metrics[
                                                                                                                                            "success_count"
                                                                                                                                        ]
                                                                                                                                        == 0
                                                                                                                                    )

                                                                                                                                    await circuit_breaker.call(
                                                                                                                                        self.successful_operation
                                                                                                                                    )
                                                                                                                                    with pytest.raises(
                                                                                                                                        ValueError
                                                                                                                                    ):
                                                                                                                                        await circuit_breaker.call(
                                                                                                                                            self.failing_operation
                                                                                                                                        )

                                                                                                                                        metrics = circuit_breaker.get_metrics()
                                                                                                                                        assert (
                                                                                                                                            metrics[
                                                                                                                                                "success_count"
                                                                                                                                            ]
                                                                                                                                            == 1
                                                                                                                                        )
                                                                                                                                        assert (
                                                                                                                                            metrics[
                                                                                                                                                "failure_count"
                                                                                                                                            ]
                                                                                                                                            == 1
                                                                                                                                        )

                                                                                                                                        async def test_concurrent_calls_during_half_open(
                                                                                                                                            self,
                                                                                                                                            circuit_breaker,
                                                                                                                                        ):
                                                                                                                                            # Open circuit
                                                                                                                                            for _ in range(
                                                                                                                                                3
                                                                                                                                            ):
                                                                                                                                                with pytest.raises(
                                                                                                                                                    ValueError
                                                                                                                                                ):
                                                                                                                                                    await circuit_breaker.call(
                                                                                                                                                        self.failing_operation
                                                                                                                                                    )
                                                                                                                                                    await asyncio.sleep(
                                                                                                                                                        0.6
                                                                                                                                                    )

                                                                                                                                                    # Trigger half-open
                                                                                                                                                    circuit_breaker.allow_request()

                                                                                                                                                    async def call_success():
                                                                                                                                                        return await circuit_breaker.call(
                                                                                                                                                            self.successful_operation
                                                                                                                                                        )

                                                                                                                                                        results = await asyncio.gather(
                                                                                                                                                            *[
                                                                                                                                                                call_success()
                                                                                                                                                                for _ in range(
                                                                                                                                                                    5
                                                                                                                                                                )
                                                                                                                                                            ],
                                                                                                                                                            return_exceptions=True,
                                                                                                                                                        )

                                                                                                                                                        for r in results:
                                                                                                                                                            assert not isinstance(
                                                                                                                                                                r,
                                                                                                                                                                CircuitOpenError,
                                                                                                                                                            )
                                                                                                                                                            assert all(
                                                                                                                                                                r
                                                                                                                                                                == "success"
                                                                                                                                                                for r in results
                                                                                                                                                                if not isinstance(
                                                                                                                                                                    r,
                                                                                                                                                                    Exception,
                                                                                                                                                                )
                                                                                                                                                            )

                                                                                                                                                            if (
                                                                                                                                                                __name__
                                                                                                                                                                == "__main__"
                                                                                                                                                            ):
                                                                                                                                                                pytest.main(
                                                                                                                                                                    [
                                                                                                                                                                        __file__
                                                                                                                                                                    ]
                                                                                                                                                                )
