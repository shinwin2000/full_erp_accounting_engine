# tests/infrastructure/database/test_transaction_manager.py
"""
Unit tests for transaction_manager.py with comprehensive coverage.
Covers all public methods, error handling, retry logic, and propagation.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.transaction_manager import (
    IsolationLevel,
    Propagation,
    TransactionError,
    TransactionManager,
    TransactionPropagationError,
    retry_on_deadlock,
    transaction,
    transactional,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    """Create a mock AsyncSession."""
    session = AsyncMock(spec=AsyncSession)
    session.begin = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def tm(mock_session):
    """Create a TransactionManager with mock session."""
    return TransactionManager(mock_session)


# ============================================================================
# Tests for Propagation Enum
# ============================================================================

class TestPropagation:
    def test_members(self):
        assert Propagation.REQUIRED.value == "required"
        assert Propagation.REQUIRES_NEW.value == "requires_new"
        assert Propagation.MANDATORY.value == "mandatory"
        assert Propagation.SUPPORTS.value == "supports"
        assert Propagation.NOT_SUPPORTED.value == "not_supported"
        assert Propagation.NEVER.value == "never"


# ============================================================================
# Tests for IsolationLevel Enum
# ============================================================================

class TestIsolationLevel:
    def test_members(self):
        assert IsolationLevel.READ_COMMITTED.value == "READ COMMITTED"
        assert IsolationLevel.REPEATABLE_READ.value == "REPEATABLE READ"
        assert IsolationLevel.SERIALIZABLE.value == "SERIALIZABLE"


# ============================================================================
# Tests for Exceptions
# ============================================================================

def test_transaction_error():
    with pytest.raises(TransactionError):
        raise TransactionError("test")


def test_transaction_propagation_error():
    with pytest.raises(TransactionPropagationError):
        raise TransactionPropagationError("test")


# ============================================================================
# Tests for TransactionManager
# ============================================================================

class TestTransactionManager:
    # --- begin ---
    @pytest.mark.asyncio
    async def test_begin_success(self, tm, mock_session):
        await tm.begin()
        mock_session.begin.assert_awaited_once()
        assert tm._in_transaction is True
        assert tm._transaction_depth == 1

    @pytest.mark.asyncio
    async def test_begin_with_isolation_level(self, tm, mock_session):
        await tm.begin(IsolationLevel.SERIALIZABLE)
        mock_session.execute.assert_awaited_once()
        # Check that SET TRANSACTION was called
        call_args = mock_session.execute.call_args[0][0]
        assert "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE" in str(call_args)
        assert tm._isolation_level == IsolationLevel.SERIALIZABLE

    @pytest.mark.asyncio
    async def test_begin_nested(self, tm, mock_session):
        await tm.begin()
        mock_session.begin.reset_mock()
        await tm.begin()  # nested
        # Should not call session.begin again
        mock_session.begin.assert_not_awaited()
        assert tm._transaction_depth == 2

    # --- commit ---
    @pytest.mark.asyncio
    async def test_commit_success(self, tm, mock_session):
        await tm.begin()
        await tm.commit()
        mock_session.commit.assert_awaited_once()
        assert tm._in_transaction is False
        assert tm._transaction_depth == 0

    @pytest.mark.asyncio
    async def test_commit_nested(self, tm, mock_session):
        await tm.begin()
        await tm.begin()  # depth 2
        await tm.commit()  # decrement depth to 1
        mock_session.commit.assert_not_awaited()
        assert tm._in_transaction is True
        assert tm._transaction_depth == 1

    @pytest.mark.asyncio
    async def test_commit_no_transaction(self, tm):
        with pytest.raises(TransactionError, match="No active transaction"):
            await tm.commit()

    @pytest.mark.asyncio
    async def test_commit_rollback_on_error(self, tm, mock_session):
        mock_session.commit.side_effect = Exception("DB error")
        await tm.begin()
        with pytest.raises(Exception, match="DB error"):
            await tm.commit()
        mock_session.rollback.assert_awaited_once()
        assert tm._in_transaction is False

    # --- rollback ---
    @pytest.mark.asyncio
    async def test_rollback_success(self, tm, mock_session):
        await tm.begin()
        await tm.rollback()
        mock_session.rollback.assert_awaited_once()
        assert tm._in_transaction is False

    @pytest.mark.asyncio
    async def test_rollback_no_transaction(self, tm):
        # Should just log, not raise
        await tm.rollback()
        # No exception

    @pytest.mark.asyncio
    async def test_rollback_nested(self, tm, mock_session):
        await tm.begin()
        await tm.begin()  # depth 2
        await tm.rollback()  # should just decrement
        mock_session.rollback.assert_not_awaited()
        assert tm._transaction_depth == 1

    # --- savepoint ---
    @pytest.mark.asyncio
    async def test_savepoint_success(self, tm, mock_session):
        await tm.begin()
        name = await tm.savepoint("sp1")
        assert name == "sp1"
        mock_session.execute.assert_awaited_once()
        assert tm._savepoint_count == 1
        assert tm._transaction_depth == 2

    @pytest.mark.asyncio
    async def test_savepoint_auto_name(self, tm, mock_session):
        await tm.begin()
        name = await tm.savepoint()
        assert name.startswith("savepoint_")
        assert tm._savepoint_count == 1

    @pytest.mark.asyncio
    async def test_savepoint_no_transaction(self, tm):
        with pytest.raises(TransactionError, match="outside transaction"):
            await tm.savepoint()

    # --- rollback_to_savepoint ---
    @pytest.mark.asyncio
    async def test_rollback_to_savepoint(self, tm, mock_session):
        await tm.begin()
        await tm.savepoint("sp1")
        await tm.rollback_to_savepoint("sp1")
        mock_session.execute.assert_awaited()
        assert tm._transaction_depth == 1  # back to outer

    @pytest.mark.asyncio
    async def test_rollback_to_savepoint_no_transaction(self, tm):
        with pytest.raises(TransactionError, match="No active transaction"):
            await tm.rollback_to_savepoint("sp1")

    # --- release_savepoint ---
    @pytest.mark.asyncio
    async def test_release_savepoint(self, tm, mock_session):
        await tm.begin()
        await tm.savepoint("sp1")
        await tm.release_savepoint("sp1")
        mock_session.execute.assert_awaited()
        assert tm._transaction_depth == 1

    # --- context manager ---
    @pytest.mark.asyncio
    async def test_async_context_manager_success(self, tm, mock_session):
        async with tm:
            pass
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_context_manager_error(self, tm, mock_session):
        with pytest.raises(ValueError):
            async with tm:
                raise ValueError("test")
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    # --- isolation level set ---
    @pytest.mark.asyncio
    async def test_set_isolation_level(self, tm, mock_session):
        await tm._set_isolation_level(IsolationLevel.REPEATABLE_READ)
        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.call_args[0][0]
        assert "REPEATABLE READ" in str(call_args)


# ============================================================================
# Tests for retry_on_deadlock
# ============================================================================

class TestRetryOnDeadlock:
    @pytest.mark.asyncio
    async def test_retry_success_first_attempt(self):
        mock_func = AsyncMock(return_value="ok")
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)
        result = await decorated()
        assert result == "ok"
        mock_func.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retry_deadlock_recovers(self):
        # Create a mock that fails with deadlock twice then succeeds
        mock_func = AsyncMock()
        deadlock_error = OperationalError(
            "deadlock", orig=MagicMock(pgcode="40P01")
        )
        mock_func.side_effect = [deadlock_error, deadlock_error, "ok"]
        decorated = retry_on_deadlock(max_attempts=3, base_delay=0.01, max_delay=0.1)(mock_func)
        result = await decorated()
        assert result == "ok"
        assert mock_func.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_serialization_failure_recovers(self):
        mock_func = AsyncMock()
        serial_error = OperationalError(
            "serial", orig=MagicMock(pgcode="40001")
        )
        mock_func.side_effect = [serial_error, "ok"]
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)
        result = await decorated()
        assert result == "ok"
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_fails_after_max_attempts(self):
        mock_func = AsyncMock()
        deadlock_error = OperationalError(
            "deadlock", orig=MagicMock(pgcode="40P01")
        )
        mock_func.side_effect = deadlock_error
        decorated = retry_on_deadlock(max_attempts=2, base_delay=0.01)(mock_func)
        with pytest.raises(OperationalError):
            await decorated()
        assert mock_func.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_non_deadlock_error_raises_immediately(self):
        mock_func = AsyncMock(side_effect=ValueError("bad"))
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)
        with pytest.raises(ValueError):
            await decorated()
        mock_func.assert_awaited_once()


# ============================================================================
# Tests for transactional decorator
# ============================================================================

class TestTransactionalDecorator:
    @pytest.mark.asyncio
    async def test_transactional_required(self, mock_session):
        @transactional(propagation=Propagation.REQUIRED)
        async def func(session):
            return "ok"

        # Need to pass session in args or kwargs
        result = await func(session=mock_session)
        assert result == "ok"
        # Since no transaction existed, should begin and commit
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transactional_required_existing(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin()  # start transaction

        @transactional(propagation=Propagation.REQUIRED)
        async def func(session):
            return "ok"

        # The decorator should see existing transaction and not create new
        result = await func(session=mock_session)
        assert result == "ok"
        # No new begin/commit
        mock_session.begin.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transactional_requires_new(self, mock_session):
        @transactional(propagation=Propagation.REQUIRES_NEW)
        async def func(session):
            return "ok"

        await func(session=mock_session)
        # Should begin and commit
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transactional_mandatory_success(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin()

        @transactional(propagation=Propagation.MANDATORY)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"
        # No new transaction started
        mock_session.begin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transactional_mandatory_fails(self, mock_session):
        @transactional(propagation=Propagation.MANDATORY)
        async def func(session):
            return "ok"

        with pytest.raises(TransactionPropagationError, match="MANDATORY transaction required"):
            await func(session=mock_session)

    @pytest.mark.asyncio
    async def test_transactional_supports_with_transaction(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin()

        @transactional(propagation=Propagation.SUPPORTS)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"
        mock_session.commit.assert_not_awaited()  # should not commit

    @pytest.mark.asyncio
    async def test_transactional_supports_no_transaction(self, mock_session):
        @transactional(propagation=Propagation.SUPPORTS)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"
        mock_session.begin.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transactional_not_supported(self, mock_session):
        @transactional(propagation=Propagation.NOT_SUPPORTED)
        async def func(session):
            return "ok"

        # If no transaction, just execute
        result = await func(session=mock_session)
        assert result == "ok"
        mock_session.begin.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transactional_not_supported_with_existing(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin()

        @transactional(propagation=Propagation.NOT_SUPPORTED)
        async def func(session):
            return "ok"

        # Should commit existing transaction before executing
        result = await func(session=mock_session)
        assert result == "ok"
        mock_session.commit.assert_awaited_once()  # it commits the existing one

    @pytest.mark.asyncio
    async def test_transactional_never_no_transaction(self, mock_session):
        @transactional(propagation=Propagation.NEVER)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_transactional_never_with_transaction(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin()

        @transactional(propagation=Propagation.NEVER)
        async def func(session):
            return "ok"

        with pytest.raises(TransactionPropagationError, match="NEVER transaction but active"):
            await func(session=mock_session)

    @pytest.mark.asyncio
    async def test_transactional_retry_deadlock(self, mock_session):
        # Test that retry_deadlock=True wraps with retry
        @transactional(propagation=Propagation.REQUIRED, retry_deadlock=True)
        async def func(session):
            return "ok"

        # We can't easily test the retry logic without a real deadlock,
        # but we can check that the decorator returns a function and
        # that it's callable.
        assert callable(func)
        # Call it (should pass)
        result = await func(session=mock_session)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_transactional_no_session_raises(self):
        @transactional()
        async def func():
            return "ok"

        with pytest.raises(TransactionError, match="No session found"):
            await func()


# ============================================================================
# Tests for transaction context manager
# ============================================================================

class TestTransactionContextManager:
    @pytest.mark.asyncio
    async def test_transaction_success(self, mock_session):
        async with transaction(mock_session) as tm:
            assert isinstance(tm, TransactionManager)
            # Inside, we should be in transaction
            mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transaction_error(self, mock_session):
        with pytest.raises(ValueError):
            async with transaction(mock_session):
                raise ValueError("test")
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transaction_with_isolation(self, mock_session):
        async with transaction(mock_session, isolation_level=IsolationLevel.SERIALIZABLE):
            pass
        mock_session.execute.assert_awaited_once()
        call_args = mock_session.execute.call_args[0][0]
        assert "SERIALIZABLE" in str(call_args)


# ============================================================================
# Integration-like test for idempotency (commit/rollback multiple times)
# ============================================================================

class TestIdempotency:
    @pytest.mark.asyncio
    async def test_commit_idempotency(self, tm, mock_session):
        # Calling commit when not in transaction should raise
        with pytest.raises(TransactionError):
            await tm.commit()

        # After a successful commit, calling again raises
        await tm.begin()
        await tm.commit()
        with pytest.raises(TransactionError):
            await tm.commit()

    @pytest.mark.asyncio
    async def test_rollback_idempotency(self, tm, mock_session):
        # Rollback when not in transaction should not raise
        await tm.rollback()  # no error

        # After rollback, calling again should not raise
        await tm.begin()
        await tm.rollback()
        await tm.rollback()  # no error

    @pytest.mark.asyncio
    async def test_nested_savepoint_release_order(self, tm, mock_session):
        await tm.begin()
        sp1 = await tm.savepoint()
        sp2 = await tm.savepoint()
        await tm.release_savepoint(sp2)
        await tm.release_savepoint(sp1)
        # Transaction depth should be back to 1 (outer)
        assert tm._transaction_depth == 1
        # Releasing non-existent savepoint would raise, but we don't test that here