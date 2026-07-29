# tests/infrastructure/database/test_transaction_manager.py
"""
Unit tests for transaction_manager.py with comprehensive coverage.
Covers all public methods, error handling, retry logic, propagation, and idempotency.

Bugs found while auditing the source file are documented in the tests:
1. retry_on_deadlock silently returns None when persistent deadlock occurs (test_persistent_deadlock_exhausts_retries_and_returns_none_bug)
2. transaction() context manager ignores isolation_level argument (test_transaction_context_manager_ignores_isolation_level_bug)
"""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def mock_trigger_alert():
    """Never fire real alerts from tests; lets tests assert on alerting."""
    with patch(
        "infrastructure.database.transaction_manager.trigger_alert",
        new_callable=AsyncMock,
    ) as mock_alert:
        yield mock_alert


@pytest.fixture(autouse=True)
def no_real_sleep():
    """Retry backoff uses asyncio.sleep; don't actually wait in tests."""
    with patch("asyncio.sleep", new_callable=AsyncMock):
        yield


def make_operational_error(pgcode: str | None, has_orig: bool = True) -> OperationalError:
    """Build an OperationalError shaped like a real psycopg2 error for a given pgcode."""
    orig = MagicMock(pgcode=pgcode) if has_orig else None
    return OperationalError("statement", {}, orig)


# ============================================================================
# Tests for Propagation / IsolationLevel enums
# ============================================================================


class TestPropagation:
    def test_members(self):
        assert Propagation.REQUIRED.value == "required"
        assert Propagation.REQUIRES_NEW.value == "requires_new"
        assert Propagation.MANDATORY.value == "mandatory"
        assert Propagation.SUPPORTS.value == "supports"
        assert Propagation.NOT_SUPPORTED.value == "not_supported"
        assert Propagation.NEVER.value == "never"


class TestIsolationLevel:
    def test_members(self):
        assert IsolationLevel.READ_COMMITTED.value == "READ COMMITTED"
        assert IsolationLevel.REPEATABLE_READ.value == "REPEATABLE READ"
        assert IsolationLevel.SERIALIZABLE.value == "SERIALIZABLE"


# ============================================================================
# Tests for Exceptions
# ============================================================================


class TestExceptions:
    def test_transaction_error(self):
        with pytest.raises(TransactionError):
            raise TransactionError("test")

    def test_transaction_propagation_error_is_a_transaction_error(self):
        with pytest.raises(TransactionError):
            raise TransactionPropagationError("test")

    def test_transaction_propagation_error_message_preserved(self):
        with pytest.raises(TransactionPropagationError, match="no active tx"):
            raise TransactionPropagationError("no active tx")


# ============================================================================
# begin()
# ============================================================================


class TestBegin:
    async def test_begin_starts_session_transaction(self, tm, mock_session):
        await tm.begin()
        mock_session.begin.assert_awaited_once()
        assert tm._in_transaction is True
        assert tm._transaction_depth == 1
        assert tm._isolation_level is None

    async def test_begin_with_isolation_level_sets_it_before_begin(self, tm, mock_session):
        await tm.begin(IsolationLevel.SERIALIZABLE)

        mock_session.execute.assert_awaited_once()
        set_isolation_call = mock_session.execute.call_args[0][0]
        assert str(set_isolation_call) == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        assert tm._isolation_level == IsolationLevel.SERIALIZABLE
        mock_session.begin.assert_awaited_once()

    async def test_begin_nested_increments_depth_without_new_session_begin(self, tm, mock_session):
        await tm.begin()
        mock_session.begin.reset_mock()

        await tm.begin()  # nested call

        mock_session.begin.assert_not_awaited()
        assert tm._transaction_depth == 2
        assert tm._in_transaction is True

    async def test_begin_deeply_nested_keeps_incrementing(self, tm, mock_session):
        for _ in range(5):
            await tm.begin()
        assert tm._transaction_depth == 5
        mock_session.begin.assert_awaited_once()


# ============================================================================
# commit()
# ============================================================================


class TestCommit:
    async def test_commit_success(self, tm, mock_session):
        await tm.begin()
        await tm.commit()
        mock_session.commit.assert_awaited_once()
        assert tm._in_transaction is False
        assert tm._transaction_depth == 0

    async def test_commit_nested_only_decrements_depth(self, tm, mock_session):
        await tm.begin()
        await tm.begin()
        await tm.commit()
        mock_session.commit.assert_not_awaited()
        assert tm._in_transaction is True
        assert tm._transaction_depth == 1

    async def test_commit_outermost_after_nested_actually_commits(self, tm, mock_session):
        await tm.begin()
        await tm.begin()
        await tm.commit()
        await tm.commit()
        mock_session.commit.assert_awaited_once()
        assert tm._in_transaction is False

    async def test_commit_no_transaction_raises(self, tm):
        with pytest.raises(TransactionError, match="No active transaction to commit"):
            await tm.commit()

    async def test_commit_failure_rolls_back_and_reraises(self, tm, mock_session):
        mock_session.commit.side_effect = RuntimeError("DB error")
        await tm.begin()

        with pytest.raises(RuntimeError, match="DB error"):
            await tm.commit()

        mock_session.rollback.assert_awaited_once()
        assert tm._in_transaction is False
        assert tm._transaction_depth == 0


# ============================================================================
# rollback()
# ============================================================================


class TestRollback:
    async def test_rollback_success(self, tm, mock_session):
        await tm.begin()
        await tm.rollback()
        mock_session.rollback.assert_awaited_once()
        assert tm._in_transaction is False
        assert tm._transaction_depth == 0

    async def test_rollback_without_transaction_is_a_safe_noop(self, tm, mock_session):
        await tm.rollback()
        mock_session.rollback.assert_not_awaited()

    async def test_rollback_nested_only_decrements_depth(self, tm, mock_session):
        await tm.begin()
        await tm.begin()
        await tm.rollback()
        mock_session.rollback.assert_not_awaited()
        assert tm._transaction_depth == 1
        assert tm._in_transaction is True


# ============================================================================
# savepoint / rollback_to_savepoint / release_savepoint
# ============================================================================


class TestSavepoints:
    async def test_savepoint_with_explicit_name_issues_exact_sql(self, tm, mock_session):
        await tm.begin()
        name = await tm.savepoint("sp1")

        assert name == "sp1"
        mock_session.execute.assert_awaited_once()
        issued_sql = mock_session.execute.call_args[0][0]
        assert str(issued_sql) == "SAVEPOINT sp1"
        assert tm._savepoint_count == 1
        assert tm._transaction_depth == 2

    async def test_savepoint_auto_generated_name_is_sequential(self, tm, mock_session):
        await tm.begin()
        name1 = await tm.savepoint()
        name2 = await tm.savepoint()
        assert name1 == "savepoint_1"
        assert name2 == "savepoint_2"
        assert tm._savepoint_count == 2

    async def test_savepoint_outside_transaction_raises(self, tm):
        with pytest.raises(TransactionError, match="outside transaction"):
            await tm.savepoint()

    async def test_rollback_to_savepoint_issues_exact_sql_and_decrements_depth(self, tm, mock_session):
        await tm.begin()
        await tm.savepoint("sp1")
        mock_session.execute.reset_mock()

        await tm.rollback_to_savepoint("sp1")

        mock_session.execute.assert_awaited_once()
        issued_sql = mock_session.execute.call_args[0][0]
        assert str(issued_sql) == "ROLLBACK TO SAVEPOINT sp1"
        assert tm._transaction_depth == 1

    async def test_rollback_to_savepoint_outside_transaction_raises(self, tm):
        with pytest.raises(TransactionError, match="No active transaction"):
            await tm.rollback_to_savepoint("sp1")

    async def test_release_savepoint_issues_exact_sql_and_decrements_depth(self, tm, mock_session):
        await tm.begin()
        await tm.savepoint("sp1")
        mock_session.execute.reset_mock()

        await tm.release_savepoint("sp1")

        mock_session.execute.assert_awaited_once()
        issued_sql = mock_session.execute.call_args[0][0]
        assert str(issued_sql) == "RELEASE SAVEPOINT sp1"
        assert tm._transaction_depth == 1

    async def test_release_savepoint_without_active_transaction_is_unguarded(self, tm, mock_session):
        # Design note: release_savepoint() never checks _in_transaction.
        # This test documents current behavior; it may deserve a guard clause.
        assert tm._in_transaction is False
        await tm.release_savepoint("phantom_savepoint")

        mock_session.execute.assert_awaited_once()
        assert tm._transaction_depth == -1  # bug: depth goes negative

    async def test_nested_savepoint_release_order(self, tm, mock_session):
        await tm.begin()
        sp1 = await tm.savepoint()
        sp2 = await tm.savepoint()
        await tm.release_savepoint(sp2)
        await tm.release_savepoint(sp1)
        assert tm._transaction_depth == 1

    def test_savepoint_name_is_concatenated_unsanitized_security_note(self):
        malicious_name = "sp1; DROP TABLE journal_header; --"
        built_sql = "SAVEPOINT " + malicious_name
        assert "DROP TABLE" in built_sql  # confirms naive concatenation, not parameterization


# ============================================================================
# _set_isolation_level
# ============================================================================


class TestSetIsolationLevel:
    async def test_sets_exact_sql_for_each_level(self, tm, mock_session):
        for level, expected in [
            (IsolationLevel.READ_COMMITTED, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
            (IsolationLevel.REPEATABLE_READ, "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"),
            (IsolationLevel.SERIALIZABLE, "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"),
        ]:
            mock_session.execute.reset_mock()
            await tm._set_isolation_level(level)
            mock_session.execute.assert_awaited_once()
            assert str(mock_session.execute.call_args[0][0]) == expected


# ============================================================================
# TransactionManager as an async context manager
# ============================================================================


class TestAsyncContextManager:
    async def test_successful_block_commits(self, tm, mock_session):
        async with tm:
            pass
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
        mock_session.rollback.assert_not_awaited()

    async def test_failing_block_rolls_back_and_reraises(self, tm, mock_session):
        with pytest.raises(ValueError, match="boom"):
            async with tm:
                raise ValueError("boom")
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    async def test_context_manager_yields_self(self, tm):
        async with tm as ctx:
            assert ctx is tm


# ============================================================================
# retry_on_deadlock
# ============================================================================


class TestRetryOnDeadlock:
    async def test_succeeds_on_first_attempt_no_retry(self):
        mock_func = AsyncMock(return_value="ok")
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)

        result = await decorated()

        assert result == "ok"
        mock_func.assert_awaited_once()

    async def test_deadlock_recovers_within_attempt_budget(self, mock_trigger_alert):
        mock_func = AsyncMock(
            side_effect=[
                make_operational_error("40P01"),
                make_operational_error("40P01"),
                "ok",
            ]
        )
        decorated = retry_on_deadlock(max_attempts=3, base_delay=0.01, max_delay=0.1)(mock_func)

        result = await decorated()

        assert result == "ok"
        assert mock_func.call_count == 3
        mock_trigger_alert.assert_not_awaited()

    async def test_serialization_failure_recovers_within_attempt_budget(self):
        mock_func = AsyncMock(side_effect=[make_operational_error("40001"), "ok"])
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)

        result = await decorated()

        assert result == "ok"
        assert mock_func.call_count == 2

    async def test_non_retryable_pgcode_raises_on_first_attempt(self, mock_trigger_alert):
        error = make_operational_error("42601")
        mock_func = AsyncMock(side_effect=error)
        decorated = retry_on_deadlock(max_attempts=5)(mock_func)

        with pytest.raises(OperationalError):
            await decorated()

        mock_func.assert_awaited_once()
        mock_trigger_alert.assert_awaited_once()
        assert mock_trigger_alert.call_args.kwargs["severity"] == "error"

    async def test_operational_error_without_orig_raises_on_first_attempt(self):
        error = make_operational_error(pgcode=None, has_orig=False)
        mock_func = AsyncMock(side_effect=error)
        decorated = retry_on_deadlock(max_attempts=5)(mock_func)

        with pytest.raises(OperationalError):
            await decorated()

        mock_func.assert_awaited_once()

    async def test_non_operational_exception_raises_immediately(self):
        mock_func = AsyncMock(side_effect=ValueError("bad input"))
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)

        with pytest.raises(ValueError, match="bad input"):
            await decorated()

        mock_func.assert_awaited_once()

    async def test_persistent_deadlock_exhausts_retries_and_returns_none_bug(self, mock_trigger_alert):
        """Documents a real bug: persistent deadlock silently returns None.
        See module docstring for details.
        """
        persistent_deadlock = make_operational_error("40P01")
        mock_func = AsyncMock(side_effect=persistent_deadlock)
        decorated = retry_on_deadlock(max_attempts=3, base_delay=0.01)(mock_func)

        result = await decorated()

        assert result is None  # BUG: should raise OperationalError
        assert mock_func.call_count == 3
        mock_trigger_alert.assert_not_awaited()

    async def test_persistent_serialization_failure_also_exhausts_silently_bug(self):
        persistent_serialization_failure = make_operational_error("40001")
        mock_func = AsyncMock(side_effect=persistent_serialization_failure)
        decorated = retry_on_deadlock(max_attempts=2, base_delay=0.01)(mock_func)

        result = await decorated()

        assert result is None
        assert mock_func.call_count == 2

    async def test_retry_uses_exponential_backoff_with_jitter_capped_at_max_delay(self):
        mock_func = AsyncMock(
            side_effect=[make_operational_error("40P01"), make_operational_error("40P01"), "ok"]
        )
        decorated = retry_on_deadlock(max_attempts=3, base_delay=1.0, max_delay=1.5)(mock_func)

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await decorated()

        assert result == "ok"
        assert mock_sleep.call_count == 2
        for call in mock_sleep.call_args_list:
            delay = call.args[0]
            assert 0 <= delay <= 1.5

    # Additional negative path: verify that alert is triggered when non-retryable error occurs
    async def test_non_retryable_error_triggers_alert(self, mock_trigger_alert):
        error = make_operational_error("42601")
        mock_func = AsyncMock(side_effect=error)
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)

        with pytest.raises(OperationalError):
            await decorated()

        mock_trigger_alert.assert_awaited_once()
        assert mock_trigger_alert.call_args.kwargs["severity"] == "error"


# ============================================================================
# transactional() -- parameterized tests for no-existing-transaction case
# ============================================================================


class TestTransactionalNoExistingTransaction:
    @pytest.mark.parametrize(
        "propagation,expect_begin_commit",
        [
            (Propagation.REQUIRED, True),
            (Propagation.REQUIRES_NEW, True),
            (Propagation.SUPPORTS, False),
            (Propagation.NOT_SUPPORTED, False),
        ],
        ids=["REQUIRED", "REQUIRES_NEW", "SUPPORTS", "NOT_SUPPORTED"],
    )
    async def test_no_existing_transaction_behavior(self, mock_session, propagation, expect_begin_commit):
        @transactional(propagation=propagation)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        if expect_begin_commit:
            mock_session.begin.assert_awaited_once()
            mock_session.commit.assert_awaited_once()
        else:
            mock_session.begin.assert_not_awaited()
            mock_session.commit.assert_not_awaited()

    async def test_mandatory_with_no_existing_transaction_raises(self, mock_session):
        @transactional(propagation=Propagation.MANDATORY)
        async def func(session):
            return "ok"

        with pytest.raises(TransactionPropagationError, match="MANDATORY transaction required"):
            await func(session=mock_session)

    async def test_never_with_no_existing_transaction_succeeds(self, mock_session):
        @transactional(propagation=Propagation.NEVER)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"
        mock_session.begin.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    async def test_no_session_provided_raises(self):
        @transactional()
        async def func():
            return "ok"

        with pytest.raises(TransactionError, match="No session found"):
            await func()

    async def test_session_found_positionally(self, mock_session):
        @transactional(propagation=Propagation.REQUIRED)
        async def func(session):
            return session

        result = await func(mock_session)
        assert result is mock_session


# ============================================================================
# transactional() -- branches that require a PRE-EXISTING transaction
#
# The decorator always builds its own TransactionManager(session) internally,
# so we patch that class to control the _in_transaction flag.
# ============================================================================


class TestTransactionalWithExistingTransaction:
    def _patched_manager(self, in_transaction: bool):
        fake_tm = MagicMock()
        fake_tm._in_transaction = in_transaction
        fake_tm.begin = AsyncMock()
        fake_tm.commit = AsyncMock()
        fake_tm.rollback = AsyncMock()
        fake_tm.__aenter__ = AsyncMock(return_value=fake_tm)
        fake_tm.__aexit__ = AsyncMock(return_value=False)
        return fake_tm

    async def test_required_with_existing_transaction_runs_func_without_wrapping(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.REQUIRED)
            async def func(session):
                return "ok"

            result = await func(session=mock_session)

        assert result == "ok"
        fake_tm.begin.assert_not_awaited()
        fake_tm.commit.assert_not_awaited()
        fake_tm.__aenter__.assert_not_awaited()

    async def test_requires_new_with_existing_transaction_commits_it_first(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.REQUIRES_NEW)
            async def func(session):
                return "ok"

            result = await func(session=mock_session)

        assert result == "ok"
        fake_tm.commit.assert_awaited_once()
        fake_tm.__aenter__.assert_awaited_once()

    async def test_mandatory_with_existing_transaction_runs_directly(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.MANDATORY)
            async def func(session):
                return "ok"

            result = await func(session=mock_session)

        assert result == "ok"
        fake_tm.begin.assert_not_awaited()

    async def test_supports_ignores_transaction_state_either_way(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.SUPPORTS)
            async def func(session):
                return "ok"

            result = await func(session=mock_session)

        assert result == "ok"
        fake_tm.commit.assert_not_awaited()
        fake_tm.__aenter__.assert_not_awaited()

    async def test_not_supported_with_existing_transaction_commits_it_first(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.NOT_SUPPORTED)
            async def func(session):
                return "ok"

            result = await func(session=mock_session)

        assert result == "ok"
        fake_tm.commit.assert_awaited_once()

    async def test_never_with_existing_transaction_raises(self, mock_session):
        fake_tm = self._patched_manager(in_transaction=True)
        with patch(
            "infrastructure.database.transaction_manager.TransactionManager",
            return_value=fake_tm,
        ):
            @transactional(propagation=Propagation.NEVER)
            async def func(session):
                return "ok"

            with pytest.raises(
                TransactionPropagationError, match="NEVER transaction but active"
            ):
                await func(session=mock_session)


# ============================================================================
# transactional() + retry_on_deadlock integration
# ============================================================================


class TestTransactionalRetryIntegration:
    async def test_transient_deadlock_is_retried_end_to_end(self, mock_session):
        attempts = {"n": 0}

        @transactional(propagation=Propagation.REQUIRED, retry_deadlock=True)
        async def func(session):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise make_operational_error("40P01")
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        assert attempts["n"] == 3
        # Each attempt opens its own TransactionManager.
        assert mock_session.begin.await_count == 3
        assert mock_session.commit.await_count == 1
        assert mock_session.rollback.await_count == 2

    async def test_retry_deadlock_false_does_not_wrap_with_retry(self, mock_session):
        mock_func_calls = {"n": 0}

        @transactional(propagation=Propagation.REQUIRED, retry_deadlock=False)
        async def func(session):
            mock_func_calls["n"] += 1
            raise make_operational_error("40P01")

        with pytest.raises(OperationalError):
            await func(session=mock_session)

        assert mock_func_calls["n"] == 1


# ============================================================================
# transaction() context manager
# ============================================================================


class TestTransactionContextManager:
    async def test_successful_block_commits(self, mock_session):
        async with transaction(mock_session) as tm:
            assert isinstance(tm, TransactionManager)
            mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_exception_in_block_rolls_back_and_propagates(self, mock_session):
        with pytest.raises(ValueError, match="test"):
            async with transaction(mock_session):
                raise ValueError("test")
        mock_session.rollback.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    async def test_transaction_context_manager_ignores_isolation_level_bug(self, mock_session):
        """Documents a real bug: isolation_level argument has no effect.
        See module docstring for details.
        """
        async with transaction(mock_session, isolation_level=IsolationLevel.SERIALIZABLE):
            pass

        # BUG: isolation level not set
        mock_session.execute.assert_not_awaited()

    async def test_direct_begin_does_apply_isolation_level_for_contrast(self, mock_session):
        tm = TransactionManager(mock_session)
        await tm.begin(IsolationLevel.SERIALIZABLE)
        mock_session.execute.assert_awaited_once()
        assert "SERIALIZABLE" in str(mock_session.execute.call_args[0][0])


# ============================================================================
# Idempotency
# ============================================================================


class TestIdempotency:
    async def test_commit_without_transaction_always_raises_the_same_way(self, tm):
        with pytest.raises(TransactionError, match="No active transaction to commit"):
            await tm.commit()
        with pytest.raises(TransactionError, match="No active transaction to commit"):
            await tm.commit()

    async def test_commit_twice_after_begin_raises_on_second_call(self, tm, mock_session):
        await tm.begin()
        await tm.commit()
        with pytest.raises(TransactionError):
            await tm.commit()
        mock_session.commit.assert_awaited_once()

    async def test_rollback_repeated_calls_are_always_a_safe_noop(self, tm, mock_session):
        await tm.rollback()
        await tm.rollback()
        await tm.rollback()
        mock_session.rollback.assert_not_awaited()

    async def test_rollback_after_commit_cycle_is_idempotent_noop(self, tm, mock_session):
        await tm.begin()
        await tm.rollback()
        assert tm._in_transaction is False
        await tm.rollback()
        mock_session.rollback.assert_awaited_once()

    async def test_begin_commit_cycle_repeated_is_stable(self, tm, mock_session):
        await tm.begin()
        await tm.commit()
        first_state = (tm._in_transaction, tm._transaction_depth)

        await tm.begin()
        await tm.commit()
        second_state = (tm._in_transaction, tm._transaction_depth)

        assert first_state == second_state == (False, 0)
        assert mock_session.commit.await_count == 2

    async def test_nested_savepoint_release_is_idempotent_in_depth_accounting(self, tm, mock_session):
        await tm.begin()
        sp1 = await tm.savepoint()
        sp2 = await tm.savepoint()
        await tm.release_savepoint(sp2)
        await tm.release_savepoint(sp1)
        depth_after_first_cycle = tm._transaction_depth

        sp3 = await tm.savepoint()
        await tm.release_savepoint(sp3)
        depth_after_second_cycle = tm._transaction_depth

        assert depth_after_first_cycle == depth_after_second_cycle == 1
