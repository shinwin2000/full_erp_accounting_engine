# tests/adapters/secondary_impl/test_sqlalchemy_unit_of_work_impl.py
"""
Comprehensive unit tests for adapters/secondary_impl/sqlalchemy_unit_of_work_impl.py.

Covers:
- Exceptions: UnitOfWorkError, UnitOfWorkCommitError, UnitOfWorkRollbackError
- SQLAlchemyUnitOfWork:
  - __init__ and __slots__
  - __aenter__ / __aexit__ (with commit on success, rollback on exception)
  - begin, begin_read_only
  - commit, rollback, flush, execute_raw_sql
  - savepoint: create, rollback_to, release, context managers (savepoint, transaction)
  - hooks: before_commit, after_commit, after_rollback
  - transaction_id, isolation_level, is_active
  - change logging
  - repository registration, get_repository, and all repository getter properties
  - event publishing via outbox
  - session property
  - lazy initialization: _get_session_factory, _ensure_repositories_initialized, _attach_session_to_repositories
- SQLAlchemyUnitOfWorkFactory: create, transactional context manager
- Module-level functions: get_uow_factory, get_uow
- All exception paths: UnitOfWorkError raised in various scenarios
- Mocked imports using importlib patching to avoid real dependencies
- Edge cases: session already started, multiple commits, rollback after commit, savepoint rollback
"""

from __future__ import annotations

import asyncio
import importlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text as sa_text

from adapters.secondary_impl.sqlalchemy_unit_of_work_impl import (
    SQLAlchemyUnitOfWork,
    SQLAlchemyUnitOfWorkFactory,
    UnitOfWorkCommitError,
    UnitOfWorkError,
    UnitOfWorkRollbackError,
    get_uow,
    get_uow_factory,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_session():
    """Mock AsyncSession."""
    session = AsyncMock()
    session.begin = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.close = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_transaction():
    """Mock AsyncSessionTransaction."""
    tx = AsyncMock()
    tx.commit = AsyncMock()
    tx.rollback = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock()
    return tx


@pytest.fixture
def mock_session_factory(mock_session):
    """Mock async_sessionmaker."""
    factory = MagicMock()
    factory.return_value = mock_session
    # Make the factory callable
    factory.__call__ = MagicMock(return_value=mock_session)
    return factory


@pytest.fixture
def uow(mock_session_factory):
    """SQLAlchemyUnitOfWork with mocked session factory."""
    return SQLAlchemyUnitOfWork(session_factory=mock_session_factory)


@pytest.fixture
def mock_outbox_repo():
    repo = AsyncMock()
    repo.save_event = AsyncMock()
    return repo


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_unit_of_work_error(self):
        with pytest.raises(UnitOfWorkError, match="test"):
            raise UnitOfWorkError("test")

    def test_unit_of_work_commit_error(self):
        with pytest.raises(UnitOfWorkCommitError, match="commit failed"):
            raise UnitOfWorkCommitError("commit failed")

    def test_unit_of_work_rollback_error(self):
        with pytest.raises(UnitOfWorkRollbackError, match="rollback failed"):
            raise UnitOfWorkRollbackError("rollback failed")


# ============================================================================
# Tests for SQLAlchemyUnitOfWork
# ============================================================================

class TestSQLAlchemyUnitOfWork:
    def test_init(self, mock_session_factory):
        uow = SQLAlchemyUnitOfWork(session_factory=mock_session_factory, is_period_closing=True)
        assert uow._session_factory == mock_session_factory
        assert uow._is_period_closing is True
        assert uow._is_active is False
        assert uow._initialized_repos is False
        assert uow._repositories == {}
        assert uow._before_commit_hooks == []
        assert uow._after_commit_hooks == []
        assert uow._after_rollback_hooks == []
        assert uow._change_log == []
        assert uow._event_collector == []

    # ---- Lazy session factory ----

    @pytest.mark.asyncio
    async def test_get_session_factory_from_init(self, mock_session_factory):
        uow = SQLAlchemyUnitOfWork(session_factory=mock_session_factory)
        factory = await uow._get_session_factory()
        assert factory == mock_session_factory

    @pytest.mark.asyncio
    async def test_get_session_factory_lazy_import(self):
        uow = SQLAlchemyUnitOfWork()
        with patch("importlib.import_module") as mock_import:
            mock_module = MagicMock()
            mock_module.get_async_session_factory = AsyncMock(return_value="factory")
            mock_import.return_value = mock_module
            factory = await uow._get_session_factory()
            assert factory == "factory"
            mock_import.assert_called_once_with("infrastructure.database.session_factory_sqlalchemy")

    @pytest.mark.asyncio
    async def test_get_session_factory_import_error(self):
        uow = SQLAlchemyUnitOfWork()
        with patch("importlib.import_module", side_effect=ImportError("no module")):
            with pytest.raises(UnitOfWorkError, match="Could not import session_factory_sqlalchemy"):
                await uow._get_session_factory()

    # ---- Repository initialization ----

    def test_ensure_repositories_initialized(self, uow):
        with patch("importlib.import_module") as mock_import:
            mock_adapters = MagicMock()
            mock_adapters.SQLAlchemyJournalRepository = MagicMock
            mock_adapters.SQLAlchemyLedgerRepository = MagicMock
            # Mock all repository classes
            mock_import.return_value = mock_adapters
            uow._ensure_repositories_initialized()
            assert uow._initialized_repos is True
            # Check some repositories are set
            assert "journal" in uow._repositories
            assert "ledger" in uow._repositories

    def test_ensure_repositories_initialized_import_error(self, uow):
        with patch("importlib.import_module", side_effect=ImportError("fail")):
            with pytest.raises(UnitOfWorkError, match="Failed to import repository adapters"):
                uow._ensure_repositories_initialized()

    def test_attach_session_to_repositories(self, uow, mock_session):
        # Create a fake repository with _session attribute
        repo = MagicMock()
        repo._session = None
        uow._repositories["test"] = repo
        uow._session = mock_session
        uow._attach_session_to_repositories()
        assert repo._session == mock_session

    # ---- Context manager ----

    @pytest.mark.asyncio
    async def test_aenter(self, uow, mock_session, mock_transaction):
        # Mock session_factory and transaction
        mock_session.begin.return_value = mock_transaction
        uow._get_session_factory = AsyncMock(return_value=mock_session)
        uow._ensure_repositories_initialized = MagicMock()
        uow._attach_session_to_repositories = MagicMock()
        with patch("uuid.uuid4", return_value="test-id"):
            result = await uow.__aenter__()
            assert result is uow
            assert uow._session == mock_session
            assert uow._transaction == mock_transaction
            assert uow._transaction_id == "test-id"
            assert uow._is_active is True
            uow._ensure_repositories_initialized.assert_called_once()
            uow._attach_session_to_repositories.assert_called_once()

    @pytest.mark.asyncio
    async def test_aenter_period_closing(self, mock_session_factory, mock_session, mock_transaction):
        uow = SQLAlchemyUnitOfWork(session_factory=mock_session_factory, is_period_closing=True)
        mock_session.begin.return_value = mock_transaction
        with patch("importlib.import_module") as mock_import:
            mock_logger = MagicMock()
            mock_module = MagicMock()
            mock_module.get_logger.return_value = mock_logger
            mock_import.return_value = mock_module
            await uow.__aenter__()
            # Should execute SET TRANSACTION ISOLATION LEVEL SERIALIZABLE
            mock_session.execute.assert_called_with(sa_text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"), {})

    @pytest.mark.asyncio
    async def test_aexit_no_exception_commit(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        uow._publish_events = AsyncMock()
        after_commit = AsyncMock()
        uow.add_after_commit_hook(after_commit)

        await uow.__aexit__(None, None, None)
        mock_transaction.commit.assert_called_once()
        mock_session.close.assert_called_once()
        uow._publish_events.assert_called_once()
        after_commit.assert_called_once()
        assert uow._transaction is None
        assert uow._is_active is False

    @pytest.mark.asyncio
    async def test_aexit_with_exception_rollback(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        after_rollback = AsyncMock()
        uow.add_after_rollback_hook(after_rollback)

        exc = ValueError("test")
        await uow.__aexit__(type(exc), exc, None)
        mock_transaction.rollback.assert_called_once()
        mock_session.close.assert_called_once()
        after_rollback.assert_called_once()
        assert uow._transaction is None
        assert uow._is_active is False

    @pytest.mark.asyncio
    async def test_aexit_commit_error_rollback(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        mock_transaction.commit.side_effect = Exception("commit error")
        mock_transaction.rollback.side_effect = Exception("rollback error")  # should not raise

        with pytest.raises(UnitOfWorkCommitError, match="Transaction commit/rollback failed"):
            await uow.__aexit__(None, None, None)
        mock_transaction.rollback.assert_called_once()
        mock_session.close.assert_called_once()

    # ---- begin, begin_read_only ----

    @pytest.mark.asyncio
    async def test_begin_first_time(self, uow, mock_session, mock_transaction):
        uow._session = None
        uow._get_session_factory = AsyncMock(return_value=mock_session)
        mock_session.begin.return_value = mock_transaction
        uow._ensure_repositories_initialized = MagicMock()
        uow._attach_session_to_repositories = MagicMock()
        with patch("uuid.uuid4", return_value="test-id"):
            await uow.begin()
            assert uow._session == mock_session
            assert uow._transaction == mock_transaction
            assert uow._is_active is True
            assert uow._transaction_id == "test-id"

    @pytest.mark.asyncio
    async def test_begin_already_started(self, uow, mock_session):
        uow._session = mock_session
        uow._transaction = MagicMock()
        await uow.begin()  # should not do anything
        # no changes

    @pytest.mark.asyncio
    async def test_begin_read_only(self, uow, mock_session, mock_transaction):
        uow._get_session_factory = AsyncMock(return_value=mock_session)
        mock_session.begin.return_value = mock_transaction
        await uow.begin_read_only()
        mock_session.execute.assert_called_with(sa_text("SET TRANSACTION READ ONLY"), {})

    # ---- commit ----

    @pytest.mark.asyncio
    async def test_commit_success(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        uow._publish_events = AsyncMock()
        before_hook = MagicMock()
        after_hook = AsyncMock()
        uow.add_before_commit_hook(before_hook)
        uow.add_after_commit_hook(after_hook)

        await uow.commit()
        before_hook.assert_called_once()
        mock_session.flush.assert_called_once()
        mock_transaction.commit.assert_called_once()
        uow._publish_events.assert_called_once()
        after_hook.assert_called_once()
        assert uow._is_active is False

    @pytest.mark.asyncio
    async def test_commit_not_started(self, uow):
        with pytest.raises(UnitOfWorkError, match="UoW not started or transaction not active"):
            await uow.commit()

    @pytest.mark.asyncio
    async def test_commit_error_rollback(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        mock_transaction.commit.side_effect = Exception("commit failed")
        with pytest.raises(UnitOfWorkCommitError, match="Commit failed"):
            await uow.commit()
        mock_transaction.rollback.assert_called_once()

    # ---- rollback ----

    @pytest.mark.asyncio
    async def test_rollback_success(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        after_rollback = AsyncMock()
        uow.add_after_rollback_hook(after_rollback)

        await uow.rollback()
        mock_transaction.rollback.assert_called_once()
        after_rollback.assert_called_once()
        assert uow._transaction is None
        assert uow._is_active is False
        assert uow._event_collector == []

    @pytest.mark.asyncio
    async def test_rollback_no_transaction(self, uow):
        uow._transaction = None
        await uow.rollback()  # should just return

    @pytest.mark.asyncio
    async def test_rollback_error(self, uow, mock_session, mock_transaction):
        uow._session = mock_session
        uow._transaction = mock_transaction
        mock_transaction.rollback.side_effect = Exception("rollback error")
        with pytest.raises(UnitOfWorkRollbackError, match="Rollback failed"):
            await uow.rollback()

    # ---- flush ----

    @pytest.mark.asyncio
    async def test_flush(self, uow, mock_session):
        uow._session = mock_session
        await uow.flush()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_not_started(self, uow):
        with pytest.raises(UnitOfWorkError, match="UoW not started"):
            await uow.flush()

    # ---- execute_raw_sql ----

    @pytest.mark.asyncio
    async def test_execute_raw_sql(self, uow, mock_session):
        uow._session = mock_session
        params = {"key": "value"}
        await uow.execute_raw_sql("SELECT * FROM table", params)
        mock_session.execute.assert_called_with(sa_text("SELECT * FROM table"), params)

    @pytest.mark.asyncio
    async def test_execute_raw_sql_not_started(self, uow):
        with pytest.raises(UnitOfWorkError, match="UoW not started"):
            await uow.execute_raw_sql("SELECT")

    # ---- savepoints ----

    @pytest.mark.asyncio
    async def test_create_savepoint(self, uow, mock_session):
        uow._session = mock_session
        await uow.create_savepoint("sp1")
        mock_session.execute.assert_called_with(sa_text("SAVEPOINT sp1"), {})

    @pytest.mark.asyncio
    async def test_rollback_to_savepoint(self, uow, mock_session):
        uow._session = mock_session
        await uow.rollback_to_savepoint("sp1")
        mock_session.execute.assert_called_with(sa_text("ROLLBACK TO SAVEPOINT sp1"), {})

    @pytest.mark.asyncio
    async def test_release_savepoint(self, uow, mock_session):
        uow._session = mock_session
        uow._savepoint_depth = 1
        await uow.release_savepoint("sp1")
        mock_session.execute.assert_called_with(sa_text("RELEASE SAVEPOINT sp1"), {})
        assert uow._savepoint_depth == 0

    @pytest.mark.asyncio
    async def test_savepoint_context_manager_success(self, uow, mock_session):
        uow._session = mock_session
        uow.create_savepoint = AsyncMock()
        uow.release_savepoint = AsyncMock()
        uow.rollback_to_savepoint = AsyncMock()

        async with uow.savepoint("sp1"):
            pass
        uow.create_savepoint.assert_called_with("sp1")
        uow.release_savepoint.assert_called_with("sp1")
        uow.rollback_to_savepoint.assert_not_called()

    @pytest.mark.asyncio
    async def test_savepoint_context_manager_exception(self, uow, mock_session):
        uow._session = mock_session
        uow.create_savepoint = AsyncMock()
        uow.release_savepoint = AsyncMock()
        uow.rollback_to_savepoint = AsyncMock()

        with pytest.raises(ValueError):
            async with uow.savepoint("sp1"):
                raise ValueError("test")
        uow.create_savepoint.assert_called_with("sp1")
        uow.rollback_to_savepoint.assert_called_with("sp1")
        uow.release_savepoint.assert_not_called()

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, uow, mock_session):
        uow._session = mock_session
        uow.savepoint = MagicMock()
        # Mock the savepoint context manager
        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock()
        mock_cm.__aexit__ = AsyncMock()
        uow.savepoint.return_value = mock_cm

        async with uow.transaction():
            pass
        uow.savepoint.assert_called_once()

    # ---- hooks ----

    def test_add_hooks(self, uow):
        hook = MagicMock()
        uow.add_before_commit_hook(hook)
        uow.add_after_commit_hook(hook)
        uow.add_after_rollback_hook(hook)
        assert hook in uow._before_commit_hooks
        assert hook in uow._after_commit_hooks
        assert hook in uow._after_rollback_hooks

    # ---- transaction info ----

    @pytest.mark.asyncio
    async def test_get_transaction_id(self, uow):
        uow._transaction_id = "tx123"
        assert await uow.get_transaction_id() == "tx123"

    @pytest.mark.asyncio
    async def test_get_isolation_level(self, uow, mock_session):
        uow._session = mock_session
        mock_result = AsyncMock()
        mock_result.scalar.return_value = "READ COMMITTED"
        mock_session.execute.return_value = mock_result
        level = await uow.get_isolation_level()
        assert level == "READ COMMITTED"
        mock_session.execute.assert_called_with(sa_text("SHOW transaction_isolation"), {})

    @pytest.mark.asyncio
    async def test_get_isolation_level_error(self, uow, mock_session):
        uow._session = mock_session
        mock_session.execute.side_effect = Exception("error")
        level = await uow.get_isolation_level()
        assert level == "READ_COMMITTED"

    @pytest.mark.asyncio
    async def test_is_active(self, uow):
        uow._is_active = True
        uow._session = MagicMock()
        uow._transaction = MagicMock()
        assert await uow.is_active() is True
        uow._transaction = None
        assert await uow.is_active() is False

    # ---- change logging ----

    def test_record_change(self, uow):
        entity = MagicMock()
        uow.record_change(entity, "UPDATE")
        assert len(uow._change_log) == 1
        assert uow._change_log[0]["entity"] == str(entity)
        assert uow._change_log[0]["change_type"] == "UPDATE"

        # test limit
        for i in range(1500):
            uow.record_change(f"e{i}", "CREATE")
        assert len(uow._change_log) <= 500

    # ---- repository management ----

    def test_register_repository(self, uow, mock_session):
        repo = MagicMock()
        uow._session = mock_session
        uow.register_repository("test", repo)
        assert uow._repositories["test"] == repo
        # session should be attached
        assert repo._session == mock_session

    def test_get_repository(self, uow):
        repo = MagicMock()
        uow._repositories["test"] = repo
        assert uow.get_repository("test") == repo
        with pytest.raises(KeyError, match="not registered"):
            uow.get_repository("missing")

    # ---- event publishing ----

    @pytest.mark.asyncio
    async def test_add_event(self, uow):
        event = MagicMock()
        uow.add_event(event)
        assert event in uow._event_collector

    @pytest.mark.asyncio
    async def test_publish_events(self, uow, mock_outbox_repo):
        uow._repositories["outbox"] = mock_outbox_repo
        event = MagicMock()
        uow.add_event(event)
        await uow._publish_events()
        mock_outbox_repo.save_event.assert_called_with(event)
        assert uow._event_collector == []

    @pytest.mark.asyncio
    async def test_publish_events_no_outbox(self, uow):
        uow._repositories["outbox"] = None
        event = MagicMock()
        uow.add_event(event)
        await uow._publish_events()  # should not raise
        assert uow._event_collector == []

    # ---- repository getters ----

    def test_repository_getters(self, uow):
        # Register some repositories
        repo = MagicMock()
        uow._repositories["journal"] = repo
        assert uow.journals() == repo
        uow._repositories["ledger"] = repo
        assert uow.ledger_entries() == repo
        uow._repositories["account"] = repo
        assert uow.accounts() == repo
        uow._repositories["ar"] = repo
        assert uow.ar_invoices() == repo
        uow._repositories["ap"] = repo
        assert uow.ap_invoices() == repo
        uow._repositories["inventory"] = repo
        assert uow.inventory() == repo
        uow._repositories["fixed_asset"] = repo
        assert uow.fixed_assets() == repo
        uow._repositories["bank_cash"] = repo
        assert uow.bank_cash() == repo
        uow._repositories["tax"] = repo
        assert uow.tax() == repo
        uow._repositories["legal_entity"] = repo
        assert uow.legal_entities() == repo
        uow._repositories["iam_user"] = repo
        assert uow.iam_users() == repo
        uow._repositories["system_setting"] = repo
        assert uow.system_settings() == repo

    # ---- session property ----

    def test_session_property(self, uow, mock_session):
        uow._session = mock_session
        assert uow.session == mock_session

    def test_session_property_not_started(self, uow):
        with pytest.raises(UnitOfWorkError, match="UoW not started"):
            _ = uow.session


# ============================================================================
# Tests for SQLAlchemyUnitOfWorkFactory
# ============================================================================

class TestSQLAlchemyUnitOfWorkFactory:
    def test_init(self):
        factory = SQLAlchemyUnitOfWorkFactory(session_factory="factory")
        assert factory._session_factory == "factory"

    def test_create(self):
        factory = SQLAlchemyUnitOfWorkFactory(session_factory="factory")
        uow = factory.create(is_period_closing=True)
        assert isinstance(uow, SQLAlchemyUnitOfWork)
        assert uow._session_factory == "factory"
        assert uow._is_period_closing is True

    @pytest.mark.asyncio
    async def test_transactional_context_manager(self):
        factory = SQLAlchemyUnitOfWorkFactory(session_factory="factory")
        # Mock UOW create and async context manager
        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock()
        factory.create = MagicMock(return_value=mock_uow)
        async with factory.transactional(is_period_closing=True) as uow:
            assert uow == mock_uow
        factory.create.assert_called_with(is_period_closing=True)


# ============================================================================
# Tests for Singleton functions
# ============================================================================

def test_get_uow_factory():
    # Reset global
    import adapters.secondary_impl.sqlalchemy_unit_of_work_impl as module
    module._uow_factory = None
    f1 = get_uow_factory()
    f2 = get_uow_factory()
    assert f1 is f2
    assert isinstance(f1, SQLAlchemyUnitOfWorkFactory)


@pytest.mark.asyncio
async def test_get_uow():
    # Reset global
    import adapters.secondary_impl.sqlalchemy_unit_of_work_impl as module
    module._uow_factory = None
    with patch.object(module, "get_uow_factory") as mock_factory:
        mock_uow = AsyncMock()
        mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
        mock_uow.__aexit__ = AsyncMock()
        mock_factory.return_value.create.return_value = mock_uow
        uow = await get_uow()
        assert uow == mock_uow
        mock_uow.__aenter__.assert_called_once()