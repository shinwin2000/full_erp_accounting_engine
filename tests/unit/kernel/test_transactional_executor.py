#!/usr/bin/env python3
"""
Unit tests for TransactionalExecutor.
"""

from __future__ import annotations

import pytest

from kernel.transactional_executor import (
    TransactionalExecutor,
    TransactionConfigurationError,
    _reset_singleton,
    _reset_unit_of_work_factory,
    register_unit_of_work_factory,
)


class AsyncMockUnitOfWork:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.transaction_id = None
        self.command_id = None

        async def begin(self, isolation_level: str = "READ_COMMITTED"):
            pass

            async def commit(self):
                self.committed = True

                async def rollback(self):
                    self.rolled_back = True

                    async def begin_read_only(self):
                        pass

                        @pytest.fixture
                        def clean_factory():
                            _reset_unit_of_work_factory()
                            _reset_singleton()
                            yield
                            _reset_unit_of_work_factory()
                            _reset_singleton()

                            @pytest.fixture
                            def uow_factory(clean_factory):
                                def factory():
                                    return AsyncMockUnitOfWork()

                                    register_unit_of_work_factory(factory)
                                    return factory

                                    @pytest.mark.asyncio
                                    async def test_execute_transaction_success(uow_factory):
                                        executor = TransactionalExecutor()
                                        called = False

                                        async def callback(uow):
                                            nonlocal called
                                            called = True
                                            return "success"

                                            result = await executor.execute_transaction(callback)
                                            assert result.is_success()
                                            assert result.result == "success"
                                            assert called

                                            @pytest.mark.asyncio
                                            async def test_execute_transaction_rollback_on_failure(
                                                uow_factory,
                                            ):
                                                executor = TransactionalExecutor()
                                                uow_instance = None

                                                async def callback(uow):
                                                    nonlocal uow_instance
                                                    uow_instance = uow
                                                    raise ValueError("Business error")

                                                    result = await executor.execute_transaction(
                                                        callback
                                                    )
                                                    assert not result.is_success()
                                                    assert "Business error" in result.error_message
                                                    assert uow_instance.rolled_back is True
                                                    assert uow_instance.committed is False

                                                    @pytest.mark.asyncio
                                                    async def test_execute_transaction_retry_on_transient_error(
                                                        uow_factory,
                                                    ):
                                                        executor = TransactionalExecutor()
                                                        attempt = 0

                                                        async def callback(uow):
                                                            nonlocal attempt
                                                            attempt += 1
                                                            if attempt == 1:
                                                                raise Exception("deadlock detected")
                                                                return "retry success"

                                                                result = await executor.execute_transaction(
                                                                    callback, max_retries=3
                                                                )
                                                                assert result.is_success()
                                                                assert (
                                                                    result.result == "retry success"
                                                                )
                                                                assert result.retry_count == 1

                                                                @pytest.mark.asyncio
                                                                async def test_execute_transaction_max_retries_exceeded(
                                                                    uow_factory,
                                                                ):
                                                                    executor = (
                                                                        TransactionalExecutor()
                                                                    )

                                                                    async def callback(uow):
                                                                        raise Exception(
                                                                            "persistent deadlock"
                                                                        )

                                                                        result = await executor.execute_transaction(
                                                                            callback, max_retries=2
                                                                        )
                                                                        assert (
                                                                            not result.is_success()
                                                                        )
                                                                        assert (
                                                                            "Max retries"
                                                                            in result.error_message
                                                                        )
                                                                        assert (
                                                                            result.retry_count == 3
                                                                        )

                                                                        @pytest.mark.asyncio
                                                                        async def test_execute_in_serializable(
                                                                            uow_factory,
                                                                        ):
                                                                            executor = TransactionalExecutor()

                                                                            async def callback(uow):
                                                                                return "serializable ok"

                                                                                result = await executor.execute_in_serializable(
                                                                                    callback
                                                                                )
                                                                                assert result.is_success()
                                                                                assert (
                                                                                    result.result
                                                                                    == "serializable ok"
                                                                                )

                                                                                @pytest.mark.asyncio
                                                                                async def test_execute_in_read_only(
                                                                                    uow_factory,
                                                                                ):
                                                                                    executor = TransactionalExecutor()

                                                                                    async def callback(
                                                                                        uow,
                                                                                    ):
                                                                                        return "read only"

                                                                                        result = await executor.execute_in_read_only(
                                                                                            callback
                                                                                        )
                                                                                        assert result.is_success()
                                                                                        assert (
                                                                                            result.result
                                                                                            == "read only"
                                                                                        )

                                                                                        @pytest.mark.asyncio
                                                                                        async def test_no_factory_raises_error():
                                                                                            _reset_unit_of_work_factory()
                                                                                            _reset_singleton()
                                                                                            executor = TransactionalExecutor()

                                                                                            async def callback(
                                                                                                uow,
                                                                                            ):
                                                                                                pass

                                                                                                result = await executor.execute_transaction(
                                                                                                    callback
                                                                                                )
                                                                                                assert not result.is_success()
                                                                                                assert (
                                                                                                    "No UnitOfWork factory registered"
                                                                                                    in result.error_message
                                                                                                )

                                                                                                @pytest.mark.asyncio
                                                                                                async def test_sync_execute_with_running_loop(
                                                                                                    uow_factory,
                                                                                                ):
                                                                                                    executor = TransactionalExecutor()
                                                                                                    with pytest.raises(
                                                                                                        TransactionConfigurationError,
                                                                                                        match="Cannot use sync execute",
                                                                                                    ):

                                                                                                        def sync_op():
                                                                                                            return "x"

                                                                                                            executor.execute(
                                                                                                                sync_op
                                                                                                            )
