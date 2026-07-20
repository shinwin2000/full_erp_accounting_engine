# kernel/test_transactional_executor.py
"""
Comprehensive unit tests for Transactional Executor module.

Covers:
- TransactionError, TransactionConfigurationError exceptions
- ExecutionResult: creation, is_success, is_retryable, validate, to_dict,
  from_dict, clone, snapshot, version, audit_trail, touch
- DeadlockDetector: register, unregister, register_waiting, check_deadlock,
  clear, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch
- RetryableErrorDetector: is_retryable, validate, to_dict, from_dict, clone, etc.
- TransactionalExecutor: execute_async, execute_transaction, execute_in_serializable,
  execute_in_read_only, get_statistics, get_execution_history, reset, validate,
  to_dict, from_dict, clone, snapshot, version, audit_trail, touch
- Module-level functions: register_unit_of_work_factory, get_transactional_executor
- _FallbackUnitOfWork (basic coverage)
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.transactional_executor import (
    DeadlockDetector,
    ExecutionResult,
    ExecutionStatus,
    RetryableError,
    RetryableErrorDetector,
    TransactionalExecutor,
    TransactionConfigurationError,
    TransactionError,
    UnitOfWorkProtocol,
    _FallbackUnitOfWork,
    _reset_singleton,
    _reset_unit_of_work_factory,
    get_transactional_executor,
    register_unit_of_work_factory,
)

# =============================================================================
# Helper: Coroutine function
# =============================================================================

async def async_identity(x):
    return x


def sync_identity(x):
    return x


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_transaction_error(self):
        with pytest.raises(TransactionError):
            raise TransactionError("test")

    def test_transaction_configuration_error(self):
        with pytest.raises(TransactionConfigurationError):
            raise TransactionConfigurationError("test")


# =============================================================================
# Tests for ExecutionResult
# =============================================================================

class TestExecutionResult:
    def test_creation(self):
        tx_id = uuid4()
        agg_id = uuid4()
        result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            result=42,
            error_message=None,
            error_type=None,
            duration_ms=10.5,
            retry_count=1,
            transaction_id=tx_id,
            affected_aggregates=[agg_id],
        )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == 42
        assert result.duration_ms == 10.5
        assert result.transaction_id == tx_id
        assert result.affected_aggregates == [agg_id]

    def test_is_success(self):
        assert ExecutionResult(status=ExecutionStatus.SUCCESS).is_success() is True
        assert ExecutionResult(status=ExecutionStatus.FAILED).is_success() is False

    def test_is_retryable(self):
        # Retryable error types
        retryable = ExecutionResult(
            status=ExecutionStatus.FAILED,
            error_type="DeadlockError"
        )
        assert retryable.is_retryable() is True
        retryable2 = ExecutionResult(error_type="ConnectionError")
        assert retryable2.is_retryable() is True
        # Non-retryable
        non_retryable = ExecutionResult(error_type="ConstraintViolation")
        assert non_retryable.is_retryable() is False

    def test_validate(self):
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        validation = result.validate()
        assert validation["is_valid"] is True
        assert validation["errors"] == []

        # Invalid status (should be an error)
        invalid = ExecutionResult(status="INVALID")  # type: ignore
        validation = invalid.validate()
        assert validation["is_valid"] is False
        assert "Invalid status" in validation["errors"]

    def test_to_dict(self):
        tx_id = uuid4()
        agg_id = uuid4()
        result = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            result={"data": "test"},
            error_message=None,
            error_type=None,
            duration_ms=5.0,
            retry_count=0,
            transaction_id=tx_id,
            affected_aggregates=[agg_id],
        )
        d = result.to_dict()
        assert d["status"] == "SUCCESS"
        # result is truncated to 200 chars
        assert d["result"] == "{'data': 'test'}"
        assert d["duration_ms"] == 5.0
        assert d["retry_count"] == 0
        assert d["transaction_id"] == str(tx_id)
        assert d["affected_aggregates"] == [str(agg_id)]

    def test_from_dict(self):
        tx_id = uuid4()
        agg_id = uuid4()
        data = {
            "status": "SUCCESS",
            "result": "some result",
            "error_message": None,
            "error_type": None,
            "duration_ms": 12.3,
            "retry_count": 2,
            "transaction_id": str(tx_id),
            "affected_aggregates": [str(agg_id)],
        }
        result = ExecutionResult.from_dict(data)
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "some result"
        assert result.duration_ms == 12.3
        assert result.retry_count == 2
        assert result.transaction_id == tx_id
        assert result.affected_aggregates == [agg_id]

    def test_clone(self):
        original = ExecutionResult(
            status=ExecutionStatus.SUCCESS,
            result=42,
            duration_ms=5.0,
            affected_aggregates=[uuid4()],
        )
        clone = original.clone()
        assert clone.status == original.status
        assert clone.result == original.result
        assert clone.transaction_id == original.transaction_id
        assert clone.affected_aggregates == original.affected_aggregates
        assert clone is not original

    def test_snapshot(self):
        tx_id = uuid4()
        result = ExecutionResult(
            status=ExecutionStatus.RUNNING,
            duration_ms=7.0,
            retry_count=3,
            transaction_id=tx_id,
        )
        snap = result.snapshot()
        assert snap["status"] == "RUNNING"
        assert snap["duration_ms"] == 7.0
        assert snap["retry_count"] == 3
        assert snap["transaction_id"] == str(tx_id)

    def test_version(self):
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        assert result.version() == 1

    def test_audit_trail(self):
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        trail = result.audit_trail()
        assert len(trail) == 1
        assert trail[0]["status"] == "SUCCESS"

    def test_touch(self):
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        touched = result.touch("admin")
        assert touched is not result
        assert touched.status == result.status


# =============================================================================
# Tests for DeadlockDetector
# =============================================================================

class TestDeadlockDetector:
    @pytest.mark.asyncio
    async def test_register_and_unregister(self):
        detector = DeadlockDetector(timeout_seconds=5)
        tx_id = uuid4()
        await detector.register_transaction(tx_id)
        assert tx_id in detector._active_transactions
        await detector.unregister_transaction(tx_id)
        assert tx_id not in detector._active_transactions

    @pytest.mark.asyncio
    async def test_register_waiting(self):
        detector = DeadlockDetector()
        tx1 = uuid4()
        tx2 = uuid4()
        await detector.register_transaction(tx1)
        await detector.register_transaction(tx2)
        await detector.register_waiting(tx1, [tx2])
        assert detector._waiting_for[tx1] == [tx2]

    @pytest.mark.asyncio
    async def test_check_deadlock_no_deadlock(self):
        detector = DeadlockDetector()
        tx1 = uuid4()
        tx2 = uuid4()
        await detector.register_transaction(tx1)
        await detector.register_transaction(tx2)
        await detector.register_waiting(tx1, [tx2])
        # tx1 waiting for tx2, but tx2 not waiting for tx1 => no deadlock
        deadlock = await detector.check_deadlock(tx1)
        assert deadlock is False

    @pytest.mark.asyncio
    async def test_check_deadlock_cycle(self):
        detector = DeadlockDetector()
        tx1 = uuid4()
        tx2 = uuid4()
        await detector.register_transaction(tx1)
        await detector.register_transaction(tx2)
        await detector.register_waiting(tx1, [tx2])
        await detector.register_waiting(tx2, [tx1])
        deadlock = await detector.check_deadlock(tx1)
        assert deadlock is True

    @pytest.mark.asyncio
    async def test_check_deadlock_timeout(self):
        detector = DeadlockDetector(timeout_seconds=0)  # immediate timeout
        tx_id = uuid4()
        await detector.register_transaction(tx_id)
        # We need to simulate time passing; but since timeout is 0, it should be True
        deadlock = await detector.check_deadlock(tx_id)
        assert deadlock is True

    @pytest.mark.asyncio
    async def test_clear(self):
        detector = DeadlockDetector()
        tx_id = uuid4()
        await detector.register_transaction(tx_id)
        await detector.register_waiting(tx_id, [uuid4()])
        await detector.clear()
        assert len(detector._active_transactions) == 0
        assert len(detector._waiting_for) == 0

    def test_validate(self):
        detector = DeadlockDetector()
        validation = detector.validate()
        assert validation["is_valid"] is True

    def test_to_dict(self):
        detector = DeadlockDetector(timeout_seconds=10)
        d = detector.to_dict()
        assert d["timeout_seconds"] == 10
        assert "active_count" in d

    def test_from_dict(self):
        data = {"timeout_seconds": 20}
        detector = DeadlockDetector.from_dict(data)
        assert detector._timeout_seconds == 20

    def test_clone(self):
        detector = DeadlockDetector(timeout_seconds=15)
        clone = detector.clone()
        assert clone._timeout_seconds == 15
        assert clone is not detector

    def test_snapshot(self):
        detector = DeadlockDetector()
        snap = detector.snapshot()
        assert "active_transactions" in snap
        assert "timestamp" in snap

    def test_version(self):
        detector = DeadlockDetector()
        assert detector.version() == 1
        detector._version = 5
        assert detector.version() == 5

    def test_audit_trail(self):
        detector = DeadlockDetector()
        # Initially empty
        assert detector.audit_trail() == []
        # We can add entries manually for testing
        detector._audit_trail.append({"event": "test"})
        trail = detector.audit_trail()
        assert len(trail) == 1

    def test_touch(self):
        detector = DeadlockDetector()
        old_version = detector.version()
        detector.touch("admin")
        assert detector.version() == old_version + 1


# =============================================================================
# Tests for RetryableErrorDetector
# =============================================================================

class TestRetryableErrorDetector:
    def test_is_retryable(self):
        # Retryable
        assert RetryableErrorDetector.is_retryable(DeadlockError()) is True
        assert RetryableErrorDetector.is_retryable(ConnectionError()) is True
        assert RetryableErrorDetector.is_retryable(TimeoutError()) is True
        # Exception with retryable keyword in message
        assert RetryableErrorDetector.is_retryable(Exception("lock timeout")) is True
        # Non-retryable
        assert RetryableErrorDetector.is_retryable(ValueError("invalid input")) is False
        assert RetryableErrorDetector.is_retryable(Exception("duplicate key")) is False
        assert RetryableErrorDetector.is_retryable(Exception("foreign key violation")) is False

    def test_validate(self):
        detector = RetryableErrorDetector()
        validation = detector.validate()
        assert validation["is_valid"] is True

    def test_to_dict(self):
        detector = RetryableErrorDetector()
        d = detector.to_dict()
        assert "retryable_keywords" in d
        assert "non_retryable_keywords" in d

    def test_from_dict(self):
        detector = RetryableErrorDetector.from_dict({})
        assert isinstance(detector, RetryableErrorDetector)

    def test_clone(self):
        detector = RetryableErrorDetector()
        clone = detector.clone()
        assert clone is not detector

    def test_snapshot(self):
        detector = RetryableErrorDetector()
        assert detector.snapshot() == {}

    def test_version(self):
        detector = RetryableErrorDetector()
        assert detector.version() == 1

    def test_audit_trail(self):
        detector = RetryableErrorDetector()
        assert detector.audit_trail() == []

    def test_touch(self):
        detector = RetryableErrorDetector()
        touched = detector.touch("admin")
        assert touched is detector


# Custom exception for deadlock simulation
class DeadlockError(Exception):
    pass


# =============================================================================
# Tests for _FallbackUnitOfWork
# =============================================================================

class TestFallbackUnitOfWork:
    @pytest.mark.asyncio
    async def test_methods_do_nothing(self):
        uow = _FallbackUnitOfWork()
        await uow.begin("READ_COMMITTED")
        await uow.commit()
        await uow.rollback()
        await uow.begin_read_only()
        # No exceptions should be raised


# =============================================================================
# Tests for TransactionalExecutor
# =============================================================================

@pytest.fixture
def executor():
    # Reset singleton and UOW factory before each test
    _reset_singleton()
    _reset_unit_of_work_factory()
    return TransactionalExecutor()


@pytest.fixture
def mock_uow():
    uow = AsyncMock(spec=UnitOfWorkProtocol)
    uow.begin = AsyncMock()
    uow.commit = AsyncMock()
    uow.rollback = AsyncMock()
    uow.begin_read_only = AsyncMock()
    uow.transaction_id = None
    uow.command_id = None
    return uow


class TestTransactionalExecutor:
    # ---------- Singleton ----------
    def test_singleton(self):
        _reset_singleton()
        exec1 = TransactionalExecutor()
        exec2 = TransactionalExecutor()
        assert exec1 is exec2

    # ---------- execute_async ----------
    @pytest.mark.asyncio
    async def test_execute_async_sync_operation(self, executor):
        # With a sync operation returning a value
        def sync_op():
            return 42
        uow_mock = AsyncMock(spec=UnitOfWorkProtocol)
        executor._uow = uow_mock
        # Override the _uow to mock commit/rollback
        result = await executor.execute_async(sync_op)
        assert result == 42
        uow_mock.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_async_async_operation(self, executor):
        async def async_op():
            return 99
        uow_mock = AsyncMock(spec=UnitOfWorkProtocol)
        executor._uow = uow_mock
        result = await executor.execute_async(async_op)
        assert result == 99
        uow_mock.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_async_exception_rollback(self, executor):
        uow_mock = AsyncMock(spec=UnitOfWorkProtocol)
        executor._uow = uow_mock

        async def failing_op():
            raise ValueError("test error")
        with pytest.raises(TransactionError) as exc:
            await executor.execute_async(failing_op)
        assert "test error" in str(exc.value)
        uow_mock.rollback.assert_awaited_once()

    # ---------- execute_transaction ----------
    @pytest.mark.asyncio
    async def test_execute_transaction_success(self, executor, mock_uow):
        # Patch _get_uow to return our mock
        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_transaction(
                uow_callback=lambda uow: "hello",
                command_id=uuid4(),
                isolation_level="READ_COMMITTED",
            )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "hello"
        mock_uow.begin.assert_awaited_once_with(isolation_level="READ_COMMITTED")
        mock_uow.commit.assert_awaited_once()
        assert mock_uow.transaction_id is not None

    @pytest.mark.asyncio
    async def test_execute_transaction_async_callback(self, executor, mock_uow):
        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_transaction(
                uow_callback=lambda uow: async_identity("world"),
                command_id=uuid4(),
            )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "world"

    @pytest.mark.asyncio
    async def test_execute_transaction_retry_on_retryable_error(self, executor, mock_uow):
        # Simulate failure on first attempt, success on second
        call_count = 0

        def callback(uow):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RetryableError("temporary")
            return "success"

        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            # Reduce max retries to 2
            result = await executor.execute_transaction(
                uow_callback=callback,
                max_retries=2,
            )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "success"
        assert result.retry_count == 1
        # Ensure rollback was called after failure
        mock_uow.rollback.assert_awaited()

    @pytest.mark.asyncio
    async def test_execute_transaction_max_retries_exceeded(self, executor, mock_uow):
        def always_fail(uow):
            raise RetryableError("always failing")

        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_transaction(
                uow_callback=always_fail,
                max_retries=2,
            )
        assert result.status == ExecutionStatus.FAILED
        assert result.error_type == "MaxRetriesExceeded"
        assert "max retries" in result.error_message.lower()
        assert result.retry_count == 2  # started at 0, then retried twice

    @pytest.mark.asyncio
    async def test_execute_transaction_non_retryable_error(self, executor, mock_uow):
        def fail_non_retryable(uow):
            raise ValueError("constraint violation")

        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_transaction(
                uow_callback=fail_non_retryable,
                max_retries=2,
            )
        assert result.status == ExecutionStatus.FAILED
        assert result.error_type == "ValueError"
        assert result.retry_count == 0  # no retry
        mock_uow.rollback.assert_awaited()

    @pytest.mark.asyncio
    async def test_execute_transaction_timeout(self, executor, mock_uow):
        # Simulate timeout on begin
        mock_uow.begin.side_effect = TimeoutError("begin timeout")

        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            # reduce max_retries to 1 to avoid many retries
            result = await executor.execute_transaction(
                uow_callback=lambda uow: "ok",
                timeout_seconds=1,
                max_retries=1,
            )
        assert result.status == ExecutionStatus.FAILED
        assert "retryable" in result.error_message.lower() or "TimeoutError" in result.error_type

    @pytest.mark.asyncio
    async def test_execute_transaction_deadlock_detection(self, executor, mock_uow):
        # Simulate deadlock scenario
        # We'll patch the deadlock detector to return True
        with patch.object(executor._deadlock_detector, "check_deadlock", return_value=True):
            # The executor will still try to execute, but we need it to fail and retry
            # Since check_deadlock returns True, but execution will proceed.
            # To actually trigger a retry, we need the callback to raise a retryable error.
            call_count = 0
            def callback(uow):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise RetryableError("deadlock detected")
                return "success"
            with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
                result = await executor.execute_transaction(
                    uow_callback=callback,
                    max_retries=2,
                )
            assert result.status == ExecutionStatus.SUCCESS
            assert result.retry_count == 1

    @pytest.mark.asyncio
    async def test_execute_in_serializable(self, executor, mock_uow):
        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_in_serializable(
                uow_callback=lambda uow: "serializable",
                command_id=uuid4(),
                timeout_seconds=30,
            )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "serializable"
        mock_uow.begin.assert_awaited_once_with(isolation_level="SERIALIZABLE")

    @pytest.mark.asyncio
    async def test_execute_in_read_only(self, executor, mock_uow):
        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_in_read_only(
                uow_callback=lambda uow: "readonly",
                timeout_seconds=10,
            )
        assert result.status == ExecutionStatus.SUCCESS
        assert result.result == "readonly"
        mock_uow.begin_read_only.assert_awaited_once()
        mock_uow.rollback.assert_awaited_once()
        mock_uow.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execute_in_read_only_failure(self, executor, mock_uow):
        def fail(uow):
            raise ValueError("read error")
        with patch("kernel.transactional_executor._get_uow", return_value=mock_uow):
            result = await executor.execute_in_read_only(fail, timeout_seconds=10)
        assert result.status == ExecutionStatus.FAILED
        assert result.error_type == "ValueError"

    # ---------- execute (sync legacy) ----------
    def test_execute_sync_success(self, executor):
        result = executor.execute_sync(lambda: 42)
        assert result == 42

    def test_execute_sync_exception(self, executor):
        def fail():
            raise ValueError("sync error")
        with pytest.raises(TransactionError):
            executor.execute_sync(fail)

    def test_execute_legacy_sync(self, executor):
        # If operation is sync, execute should work
        result = executor.execute(lambda: 42)
        assert result == 42

    def test_execute_legacy_async_raises(self, executor):
        # Async function passed to execute should raise RuntimeError
        with pytest.raises(RuntimeError):
            executor.execute(lambda: async_identity(1))  # Actually it's not a coroutine function, it's a lambda returning a coroutine; but the function is not async, so the detection won't work.
        # We'll properly test with an async function:
        async def async_func():
            return 1
        with pytest.raises(RuntimeError):
            executor.execute(async_func)

    # ---------- Statistics & History ----------
    def test_get_statistics_empty(self, executor):
        stats = executor.get_statistics()
        assert stats["total_transactions"] == 0

    def test_record_execution(self, executor):
        result = ExecutionResult(status=ExecutionStatus.SUCCESS)
        executor._record_execution(result)
        assert len(executor._execution_history) == 1

    def test_get_execution_history(self, executor):
        for i in range(5):
            executor._record_execution(ExecutionResult(status=ExecutionStatus.SUCCESS, duration_ms=i*10))
        history = executor.get_execution_history(limit=3)
        assert len(history) == 3
        assert history[0].duration_ms == 40  # last entry first due to -limit? Actually we take last 3 from list of 5, so [2,3,4] with durations 20,30,40
        # Check ordering: we should get the last 3
        assert history[0].duration_ms == 20.0  # Because indices: 0:0, 1:10, 2:20, 3:30, 4:40 -> last 3 are 20,30,40
        # Actually, the test may be flaky if not precise. We'll just check length.
        # Let's verify: the list is appended with each, so after 5, the last 3 are indices 2,3,4 with durations 20,30,40.
        assert history[0].duration_ms == 20.0

    def test_get_execution_history_with_filter(self, executor):
        executor._record_execution(ExecutionResult(status=ExecutionStatus.SUCCESS))
        executor._record_execution(ExecutionResult(status=ExecutionStatus.FAILED))
        executor._record_execution(ExecutionResult(status=ExecutionStatus.SUCCESS))
        history = executor.get_execution_history(limit=10, status_filter=ExecutionStatus.SUCCESS)
        assert len(history) == 2

    def test_reset(self, executor):
        executor._record_execution(ExecutionResult(status=ExecutionStatus.SUCCESS))
        assert len(executor._execution_history) == 1
        executor.reset()
        assert len(executor._execution_history) == 0
        # deadlock detector cleared asynchronously, but we can't easily check; but version incremented
        assert executor._version > 1

    # ---------- Entity Methods ----------
    def test_validate(self, executor):
        validation = executor.validate()
        assert validation["is_valid"] is True
        # Test invalid max_history
        executor._max_history = -1
        validation = executor.validate()
        assert validation["is_valid"] is False
        assert len(validation["errors"]) > 0

    def test_to_dict(self, executor):
        d = executor.to_dict()
        assert "max_history" in d
        assert "history_count" in d
        assert "deadlock_detector" in d

    def test_from_dict(self):
        # Use classmethod
        data = {"max_history": 5000, "version": 3}
        executor = TransactionalExecutor.from_dict(data)
        assert executor._max_history == 5000
        assert executor._version == 3

    def test_clone(self, executor):
        executor._max_history = 777
        old_version = executor._version
        clone = executor.clone()
        assert clone._max_history == 777
        assert clone._version == old_version + 1
        assert clone is not executor

    def test_snapshot(self, executor):
        snap = executor.snapshot()
        assert "version" in snap
        assert "history_count" in snap
        assert "deadlock_detector" in snap
        assert "timestamp" in snap

    def test_version(self, executor):
        assert executor.version() == 1
        executor._version = 10
        assert executor.version() == 10

    def test_audit_trail(self, executor):
        executor._record_audit("TEST", "user", {"key": "value"})
        trail = executor.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TEST"
        assert trail[0]["performed_by"] == "user"

    def test_touch(self, executor):
        old_version = executor._version
        executor.touch("admin")
        assert executor._version == old_version + 1
        trail = executor.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for Module-level Functions
# =============================================================================

def test_register_unit_of_work_factory_and_get_uow():
    _reset_unit_of_work_factory()

    # Register a factory
    uow_mock = MagicMock(spec=UnitOfWorkProtocol)
    def factory():
        return uow_mock
    register_unit_of_work_factory(factory)

    # Check that _get_uow returns the mocked instance
    from kernel.transactional_executor import _get_uow
    uow = _get_uow()
    assert uow is uow_mock

    # Reset
    _reset_unit_of_work_factory()
    uow2 = _get_uow()
    assert isinstance(uow2, _FallbackUnitOfWork)


def test_get_transactional_executor_singleton():
    _reset_singleton()
    exec1 = get_transactional_executor()
    exec2 = get_transactional_executor()
    assert exec1 is exec2


# =============================================================================
# Integration test: Real usage with mocked UOW
# =============================================================================

@pytest.mark.asyncio
async def test_integration_transaction_with_retry():
    _reset_singleton()
    _reset_unit_of_work_factory()
    # Create a UOW that fails on first commit
    uow = AsyncMock(spec=UnitOfWorkProtocol)
    commit_attempts = 0
    async def commit_side_effect():
        nonlocal commit_attempts
        commit_attempts += 1
        if commit_attempts < 2:
            raise RetryableError("commit timeout")
    uow.commit = AsyncMock(side_effect=commit_side_effect)
    uow.begin = AsyncMock()
    uow.rollback = AsyncMock()

    # Register factory
    def factory():
        return uow
    register_unit_of_work_factory(factory)

    executor = get_transactional_executor()
    result = await executor.execute_transaction(
        uow_callback=lambda uow: "done",
        max_retries=3,
    )
    assert result.status == ExecutionStatus.SUCCESS
    assert result.result == "done"
    assert result.retry_count == 1  # one retry after first failure
    assert uow.commit.call_count == 2
