
# tests/infrastructure/database/test_transaction_manager.py
"""
Unit tests for transaction_manager.py with comprehensive coverage.
Covers all public methods, error handling, retry logic, propagation, and
idempotency.

Bugs found while auditing the previous version of this file
=============================================================

Two of them are in the *source* (``transaction_manager.py``), not just the
tests -- flagged loudly here and in the accompanying chat reply because they
affect real transaction correctness in a financial/accounting system:

1. **Silent swallow of persistent deadlocks/serialization failures**
   (``retry_on_deadlock``). Inside the retry loop, the deadlock and
   serialization-failure branches ``continue`` without ever setting
   ``last_exception``. If the SAME retryable error keeps occurring for
   *every* attempt (i.e. it never succeeds and never hits a different,
   non-retryable error), the loop exhausts ``range(max_attempts)`` with
   ``last_exception`` still ``None``. ``if last_exception:`` is then False,
   so the function returns ``None`` silently -- no exception raised, no
   alert fired. The previous test (``test_retry_fails_after_max_attempts``)
   assumed the function *would* raise ``OperationalError`` in this exact
   scenario, so it would fail with "DID NOT RAISE" if actually executed.
   This test file now documents the *actual* (buggy) behaviour explicitly
   as ``test_persistent_deadlock_exhausts_retries_and_returns_none_bug``,
   and separately keeps a test for the case that *does* raise correctly
   (a genuinely different, non-retryable error).

2. **``transaction()`` context manager drops its ``isolation_level``
   parameter.** ``transaction(session, isolation_level=...)`` accepts the
   argument but never forwards it to ``TransactionManager.begin()`` --
   ``tm.begin()`` is called with no arguments. Any caller asking for
   ``SERIALIZABLE`` (or any other non-default isolation level) via this
   helper silently gets whatever the session's default isolation level is
   instead. The previous test (``test_transaction_with_isolation``)
   asserted ``session.execute`` was called to set the isolation level --
   it never is, so that assertion would fail. This is now documented
   as ``test_transaction_context_manager_ignores_isolation_level_bug``.

Test-only bugs fixed (mocking mistakes, not source bugs):

3. Several ``TestTransactionalDecorator`` tests tried to simulate "the
   session already has an active transaction" by calling
   ``await tm.begin()`` on a *separate, outer* ``TransactionManager``
   instance before invoking the decorated function. But
   ``transactional()`` always constructs its own fresh
   ``TransactionManager(session)`` internally -- transaction state lives on
   the manager *instance*, not on the session -- so that fresh instance's
   ``_in_transaction`` is always ``False`` on entry, no matter what any
   other manager object did. Concretely this made the old tests wrong in
   different ways:
   - ``test_transactional_required_existing`` asserted
     ``mock_session.begin.assert_not_awaited()`` after the test's own setup
     had *already* awaited it once -- guaranteed to fail regardless of the
     decorator.
   - ``test_transactional_mandatory_success`` expected no exception, but
     the decorator's fresh manager sees no active transaction, so MANDATORY
     actually raises ``TransactionPropagationError``.
   - ``test_transactional_never_with_transaction`` expected
     ``TransactionPropagationError`` to be raised, but the decorator's
     fresh manager sees no active transaction, so NEVER actually succeeds.
   - ``test_transactional_not_supported_with_existing`` asserted
     ``commit`` was awaited, but the decorator's fresh manager never sees
     ``_in_transaction=True`` so it never commits anything.
   These are rewritten below to patch the ``TransactionManager`` class used
   *inside* the decorator so each propagation branch can actually be
   exercised with a controlled ``_in_transaction`` value -- the only way to
   reach those branches given how the decorator is implemented today.
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
def no_real_sleep(monkeypatch):
    """Retry backoff uses asyncio.sleep; don't actually wait in tests."""
    monkeypatch.setattr("asyncio.sleep", AsyncMock())


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
        # TransactionPropagationError must be catchable as TransactionError too.
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

    async def test_begin_nested_increments_depth_without_new_session_begin(
        self, tm, mock_session
    ):
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
        # Only the very first call actually opened a session transaction.
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
        await tm.begin()  # depth 2
        await tm.commit()  # decrement to 1, no real commit yet
        mock_session.commit.assert_not_awaited()
        assert tm._in_transaction is True
        assert tm._transaction_depth == 1

    async def test_commit_outermost_after_nested_actually_commits(self, tm, mock_session):
        await tm.begin()
        await tm.begin()  # depth 2
        await tm.commit()  # depth 1, no commit
        await tm.commit()  # depth 0, real commit
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
        await tm.begin()  # depth 2
        await tm.rollback()  # decrement only
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

    async def test_rollback_to_savepoint_issues_exact_sql_and_decrements_depth(
        self, tm, mock_session
    ):
        await tm.begin()
        await tm.savepoint("sp1")  # depth 2
        mock_session.execute.reset_mock()

        await tm.rollback_to_savepoint("sp1")

        mock_session.execute.assert_awaited_once()
        issued_sql = mock_session.execute.call_args[0][0]
        assert str(issued_sql) == "ROLLBACK TO SAVEPOINT sp1"
        assert tm._transaction_depth == 1

    async def test_rollback_to_savepoint_outside_transaction_raises(self, tm):
        with pytest.raises(TransactionError, match="No active transaction"):
            await tm.rollback_to_savepoint("sp1")

    async def test_release_savepoint_issues_exact_sql_and_decrements_depth(
        self, tm, mock_session
    ):
        await tm.begin()
        await tm.savepoint("sp1")  # depth 2
        mock_session.execute.reset_mock()

        await tm.release_savepoint("sp1")

        mock_session.execute.assert_awaited_once()
        issued_sql = mock_session.execute.call_args[0][0]
        assert str(issued_sql) == "RELEASE SAVEPOINT sp1"
        assert tm._transaction_depth == 1

    async def test_release_savepoint_without_active_transaction_is_unguarded(
        self, tm, mock_session
    ):
        """Design note: unlike rollback_to_savepoint(), release_savepoint()
        never checks ``_in_transaction`` before issuing SQL. Calling it with
        no active transaction still sends ``RELEASE SAVEPOINT`` to the
        database and happily decrements ``_transaction_depth`` below zero.
        This test documents the current behaviour; it likely deserves the
        same guard clause as ``rollback_to_savepoint``.
        """
        assert tm._in_transaction is False
        await tm.release_savepoint("phantom_savepoint")

        mock_session.execute.assert_awaited_once()
        assert tm._transaction_depth == -1

    async def test_nested_savepoint_release_order(self, tm, mock_session):
        await tm.begin()
        sp1 = await tm.savepoint()
        sp2 = await tm.savepoint()
        await tm.release_savepoint(sp2)
        await tm.release_savepoint(sp1)
        assert tm._transaction_depth == 1

    def test_savepoint_name_is_concatenated_unsanitized_security_note(self):
        """Security note (not exploited here, just documented): savepoint
        names are concatenated directly into the SQL string
        (``"SAVEPOINT " + savepoint_name``) rather than passed as a bound
        parameter. If a savepoint name were ever derived from unsanitized
        user input, this would be a SQL-injection vector. Today all call
        sites use auto-generated or hardcoded names, so this is currently
        safe in practice -- flagging it so it stays that way.
        """
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
        mock_trigger_alert.assert_not_awaited()  # recovered, no alert needed

    async def test_serialization_failure_recovers_within_attempt_budget(self):
        mock_func = AsyncMock(side_effect=[make_operational_error("40001"), "ok"])
        decorated = retry_on_deadlock(max_attempts=3)(mock_func)

        result = await decorated()

        assert result == "ok"
        assert mock_func.call_count == 2

    async def test_non_retryable_pgcode_raises_on_first_attempt(self, mock_trigger_alert):
        # e.g. 42601 = syntax error -- not a deadlock/serialization code,
        # so it must NOT be retried.
        error = make_operational_error("42601")
        mock_func = AsyncMock(side_effect=error)
        decorated = retry_on_deadlock(max_attempts=5)(mock_func)

        with pytest.raises(OperationalError):
            await decorated()

        mock_func.assert_awaited_once()
        mock_trigger_alert.assert_awaited_once()
        assert mock_trigger_alert.call_args.kwargs["severity"] == "error"

    async def test_operational_error_without_orig_raises_on_first_attempt(self):
        # hasattr(e, "orig") check fails when orig is falsy/absent -> not retryable.
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

    async def test_persistent_deadlock_exhausts_retries_and_returns_none_bug(
        self, mock_trigger_alert
    ):
        """Documents a real bug in ``retry_on_deadlock`` (see module
        docstring): when the SAME deadlock/serialization error occurs on
        every single attempt, ``last_exception`` is never set (the retry
        branches only ``continue``), so the loop exhausts silently and the
        function returns ``None`` instead of raising. No exception, no
        alert -- a persistent deadlock is swallowed entirely.

        This test pins down the *current* behaviour so a source fix is a
        deliberate, visible change rather than an untested regression. The
        recommended fix is to also set ``last_exception = e`` in the
        deadlock/serialization branches before ``continue``.
        """
        persistent_deadlock = make_operational_error("40P01")
        mock_func = AsyncMock(side_effect=persistent_deadlock)
        decorated = retry_on_deadlock(max_attempts=3, base_delay=0.01)(mock_func)

        result = await decorated()

        assert result is None  # BUG: should raise OperationalError instead
        assert mock_func.call_count == 3
        mock_trigger_alert.assert_not_awaited()  # BUG: failure is not reported at all

    async def test_persistent_serialization_failure_also_exhausts_silently_bug(self):
        persistent_serialization_failure = make_operational_error("40001")
        mock_func = AsyncMock(side_effect=persistent_serialization_failure)
        decorated = retry_on_deadlock(max_attempts=2, base_delay=0.01)(mock_func)

        result = await decorated()

        assert result is None  # Same bug, other retryable code path.
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
            assert 0 <= delay <= 1.5  # respects max_delay cap


# ============================================================================
# transactional() -- branches reachable with NO pre-existing transaction
# ============================================================================


class TestTransactionalNoExistingTransaction:
    async def test_required_with_no_existing_transaction_begins_and_commits(self, mock_session):
        @transactional(propagation=Propagation.REQUIRED)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_requires_new_begins_and_commits(self, mock_session):
        @transactional(propagation=Propagation.REQUIRES_NEW)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        mock_session.begin.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_mandatory_with_no_existing_transaction_raises(self, mock_session):
        @transactional(propagation=Propagation.MANDATORY)
        async def func(session):
            return "ok"

        with pytest.raises(TransactionPropagationError, match="MANDATORY transaction required"):
            await func(session=mock_session)

    async def test_supports_with_no_existing_transaction_runs_without_one(self, mock_session):
        @transactional(propagation=Propagation.SUPPORTS)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        mock_session.begin.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    async def test_not_supported_with_no_existing_transaction_runs_directly(self, mock_session):
        @transactional(propagation=Propagation.NOT_SUPPORTED)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)

        assert result == "ok"
        mock_session.begin.assert_not_awaited()
        mock_session.commit.assert_not_awaited()

    async def test_never_with_no_existing_transaction_succeeds(self, mock_session):
        @transactional(propagation=Propagation.NEVER)
        async def func(session):
            return "ok"

        result = await func(session=mock_session)
        assert result == "ok"

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
# The decorator always builds its own `TransactionManager(session)`
# internally, so the only way to reliably put it into the
# "already in a transaction" state for a unit test is to replace that class
# with a controllable stand-in -- see the module docstring for why the
# previous approach (starting an unrelated outer TransactionManager) didn't
# work.
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

    async def test_required_with_existing_transaction_runs_func_without_wrapping(
        self, mock_session
    ):
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
        fake_tm.commit.assert_awaited_once()  # commits the "existing" transaction
        fake_tm.__aenter__.assert_awaited_once()  # then opens the new one

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
        # Each attempt opens its own fresh TransactionManager -> begin/commit
        # is called once per attempt (2 failed + 1 succeeded).
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

        # No retry wrapper -> exactly one attempt, error propagates raw.
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
        """Documents a real bug (see module docstring): `transaction()`
        accepts `isolation_level` but never passes it to `tm.begin()`, so
        it has no effect at all. This test pins the current (buggy)
        behaviour -- `execute` is never called to set the isolation level.
        """
        async with transaction(mock_session, isolation_level=IsolationLevel.SERIALIZABLE):
            pass

        # BUG: should have set SERIALIZABLE via session.execute; it doesn't.
        mock_session.execute.assert_not_awaited()

    async def test_direct_begin_call_does_apply_isolation_level_for_contrast(self, mock_session):
        """Contrast case: calling `TransactionManager.begin()` directly
        (bypassing the buggy `transaction()` wrapper) DOES set the
        isolation level correctly -- confirming the bug is specifically in
        how `transaction()` forwards (or fails to forward) the argument.
        """
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
        # Calling it again in the same (still not-in-transaction) state
        # raises the identical error -- no hidden state accumulates.
        with pytest.raises(TransactionError, match="No active transaction to commit"):
            await tm.commit()

    async def test_commit_twice_after_begin_raises_on_second_call(self, tm, mock_session):
        await tm.begin()
        await tm.commit()
        with pytest.raises(TransactionError):
            await tm.commit()
        # Only one real commit ever reached the session.
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
        # Rolling back again afterwards must not raise or double-call.
        await tm.rollback()
        mock_session.rollback.assert_awaited_once()

    async def test_begin_commit_cycle_repeated_is_stable(self, tm, mock_session):
        """Running a full begin/commit cycle twice in a row on the same
        manager instance must behave identically both times."""
        await tm.begin()
        await tm.commit()
        first_state = (tm._in_transaction, tm._transaction_depth)

        await tm.begin()
        await tm.commit()
        second_state = (tm._in_transaction, tm._transaction_depth)

        assert first_state == second_state == (False, 0)
        assert mock_session.commit.await_count == 2

    async def test_nested_savepoint_release_is_idempotent_in_depth_accounting(
        self, tm, mock_session
    ):
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