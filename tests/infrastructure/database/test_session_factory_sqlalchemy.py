# tests/infrastructure/database/test_session_factory_sqlalchemy.py
# Perbaikan kualitas assertions: mengganti semua assert True dengan
# assertion yang memeriksa nilai aktual, efek samping, dan interaksi mock.
# Tests ini menggunakan mock untuk menghindari koneksi database nyata.

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.session_factory_sqlalchemy import (
    SessionFactoryError,
    SQLAlchemySessionFactory,
    create_session_factory,
    dispose,
    get_async_session,
    get_async_session_factory,
    get_engine,
    get_read_session,
    get_session,
    get_session_factory,
    get_session_factory_sync,
    get_test_session,
)


# ============================================================================
# SessionFactoryError tests
# ============================================================================
class TestSessionFactoryError:
    def test_construction(self):
        error = SessionFactoryError("test message")
        assert isinstance(error, Exception)
        assert str(error) == "test message"

    def test_default_construction(self):
        error = SessionFactoryError()
        assert isinstance(error, SessionFactoryError)


# ============================================================================
# SQLAlchemySessionFactory tests (with mocks)
# ============================================================================
class TestSQLAlchemySessionFactory:
    @pytest.fixture
    def factory(self):
        # Use a dummy config path to avoid real file loading
        with patch("infrastructure.database.session_factory_sqlalchemy.load_yaml_config") as mock_load:
            mock_load.return_value = {
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "database": "test_db",
                    "user": "test_user",
                    "password": "test_pass",
                    "pool_size": 5,
                    "max_overflow": 2,
                    "pool_timeout": 10,
                    "pool_recycle": 600,
                    "echo": False,
                    "ssl": False,
                }
            }
            factory = SQLAlchemySessionFactory("dummy_config.yaml")
            return factory

    async def test_initialization_success(self, factory):
        # Mock create_async_engine and async_sessionmaker
        mock_engine = AsyncMock()
        mock_engine.begin = AsyncMock()
        mock_session_maker = MagicMock()
        mock_session_maker.return_value = AsyncMock(spec=AsyncSession)

        with patch("infrastructure.database.session_factory_sqlalchemy.create_async_engine") as mock_create_engine:
            mock_create_engine.return_value = mock_engine
            with patch("infrastructure.database.session_factory_sqlalchemy.async_sessionmaker") as mock_sessionmaker:
                mock_sessionmaker.return_value = mock_session_maker

                await factory.initialize()

                assert factory._initialized is True
                assert factory._engine == mock_engine
                assert factory._session_factory == mock_session_maker
                mock_create_engine.assert_called_once()
                mock_sessionmaker.assert_called_once_with(
                    mock_engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autocommit=False,
                    autoflush=False,
                )

    async def test_initialization_already_initialized(self, factory):
        factory._initialized = True
        with patch("infrastructure.database.session_factory_sqlalchemy.create_async_engine") as mock_create:
            await factory.initialize()
            mock_create.assert_not_called()

    async def test_initialization_failure_raises(self, factory):
        with patch("infrastructure.database.session_factory_sqlalchemy.create_async_engine") as mock_create:
            mock_create.side_effect = Exception("DB error")
            with pytest.raises(SessionFactoryError, match="Engine initialization failed"):
                await factory.initialize()

    async def test_close(self, factory):
        factory._engine = AsyncMock()
        factory._initialized = True
        await factory.close()
        factory._engine.dispose.assert_awaited_once()
        assert factory._initialized is False

    async def test_close_no_engine(self, factory):
        factory._engine = None
        await factory.close()  # Should not raise
        assert factory._initialized is False

    async def test_get_session(self, factory):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_maker = MagicMock()
        mock_session_maker.return_value = mock_session
        factory._session_factory = mock_session_maker
        factory._initialized = True

        session = await factory.get_session()
        assert session == mock_session
        mock_session_maker.assert_called_once()

    async def test_get_session_not_initialized(self, factory):
        factory._initialized = False
        with patch.object(factory, "initialize") as mock_init:
            mock_session = AsyncMock()
            mock_init.return_value = None
            factory._session_factory = MagicMock(return_value=mock_session)
            session = await factory.get_session()
            mock_init.assert_awaited_once()
            assert session == mock_session

    async def test_get_readonly_session(self, factory):
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session.execute = AsyncMock()
        factory._initialized = True
        factory._session_factory = MagicMock(return_value=mock_session)

        session = await factory.get_readonly_session()
        assert session == mock_session
        mock_session.execute.assert_awaited_once()
        # Check that text() was used (we can't inspect easily, but we can check the call)
        args, _ = mock_session.execute.call_args
        # args[0] should be a SQLAlchemy TextClause
        assert hasattr(args[0], "string")  # text() returns TextClause with string attribute
        assert "SET TRANSACTION READ ONLY" in args[0].string

    async def test_create_all_tables(self, factory):
        mock_engine = AsyncMock()
        mock_engine.begin = AsyncMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn
        factory._engine = mock_engine
        factory._initialized = True

        with patch("infrastructure.database.session_factory_sqlalchemy.Base") as mock_base:
            await factory.create_all_tables()
            mock_conn.run_sync.assert_awaited_once_with(mock_base.metadata.create_all)

    async def test_drop_all_tables(self, factory):
        mock_engine = AsyncMock()
        mock_engine.begin = AsyncMock()
        mock_conn = AsyncMock()
        mock_engine.begin.return_value.__aenter__.return_value = mock_conn
        factory._engine = mock_engine
        factory._initialized = True

        with patch("infrastructure.database.session_factory_sqlalchemy.Base") as mock_base:
            await factory.drop_all_tables()
            mock_conn.run_sync.assert_awaited_once_with(mock_base.metadata.drop_all)

    async def test_health_check_success(self, factory):
        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.execute.return_value.scalar.return_value = 1
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn
        factory._engine = mock_engine
        factory._initialized = True

        result = await factory.health_check()
        assert result is True
        mock_conn.execute.assert_awaited_once()

    async def test_health_check_failure(self, factory):
        mock_engine = AsyncMock()
        mock_engine.connect.side_effect = Exception("DB down")
        factory._engine = mock_engine
        factory._initialized = True

        result = await factory.health_check()
        assert result is False

    async def test_health_check_not_initialized(self, factory):
        factory._initialized = False
        with patch.object(factory, "initialize") as mock_init:
            mock_init.side_effect = Exception("init error")
            result = await factory.health_check()
            assert result is False

    def test_get_engine(self, factory):
        mock_engine = AsyncMock()
        factory._engine = mock_engine
        assert factory.get_engine() == mock_engine

    def test_get_session_factory(self, factory):
        mock_sm = MagicMock()
        factory._session_factory = mock_sm
        assert factory.get_session_factory() == mock_sm

    def test_load_config_from_env_dsn(self, factory, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@prod:5432/db")
        factory.config = {}  # force reload
        # We'll test the _build_async_dsn method
        dsn = factory._build_async_dsn()
        # Should replace with asyncpg
        assert dsn.startswith("postgresql+asyncpg://")
        assert "prod" in dsn
        assert "db" in dsn

    def test_load_config_fallback_default(self):
        with patch("infrastructure.database.session_factory_sqlalchemy.load_yaml_config") as mock_load:
            mock_load.side_effect = Exception("no config")
            factory = SQLAlchemySessionFactory("dummy.yaml")
            assert factory.config["host"] == "localhost"
            assert factory.config["port"] == 5432


# ============================================================================
# Singleton and module-level function tests (with mocks)
# ============================================================================
async def test_get_session_factory_singleton():
    # Reset global
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    mock_factory = AsyncMock()
    mock_factory.initialize = AsyncMock()
    with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
        mock_class.return_value = mock_factory
        factory1 = await get_session_factory()
        factory2 = await get_session_factory()
        assert factory1 is factory2
        # initialize should be called only once
        mock_factory.initialize.assert_awaited_once()
        mock_class.assert_called_once()

async def test_get_session_factory_already_initialized():
    import infrastructure.database.session_factory_sqlalchemy as module
    mock_factory = MagicMock()
    mock_factory._initialized = True
    module._session_factory = mock_factory

    with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
        factory = await get_session_factory()
        assert factory is mock_factory
        mock_class.assert_not_called()


def test_get_session_factory_sync_with_initialized():
    import infrastructure.database.session_factory_sqlalchemy as module
    mock_factory = MagicMock()
    mock_factory._initialized = True
    module._session_factory = mock_factory

    factory = get_session_factory_sync()
    assert factory is mock_factory

def test_get_session_factory_sync_not_initialized():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    mock_factory = MagicMock()
    mock_factory.initialize = AsyncMock()

    with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
        mock_class.return_value = mock_factory
        # We need to simulate the async init in sync context
        # The sync wrapper uses threading, but we can patch asyncio behavior
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.side_effect = RuntimeError("no loop")
            # The sync function will create a new loop and run_until_complete
            with patch("asyncio.new_event_loop") as mock_new_loop:
                mock_loop_obj = AsyncMock()
                mock_new_loop.return_value = mock_loop_obj
                mock_loop_obj.run_until_complete = MagicMock()

                factory = get_session_factory_sync()
                assert factory is mock_factory
                mock_loop_obj.run_until_complete.assert_called_once()
                mock_factory.initialize.assert_awaited_once()

def test_get_session_factory_sync_with_running_loop():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    mock_factory = MagicMock()
    mock_factory.initialize = AsyncMock()

    with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
        mock_class.return_value = mock_factory
        # Simulate a running loop, so it uses threading
        with patch("asyncio.get_running_loop") as mock_loop:
            mock_loop.return_value = "loop"
            with patch("threading.Thread") as mock_thread:
                thread_instance = MagicMock()
                mock_thread.return_value = thread_instance
                # Need to patch start and join
                thread_instance.start = MagicMock()
                thread_instance.join = MagicMock()

                factory = get_session_factory_sync()
                assert factory is mock_factory
                mock_thread.assert_called_once()
                thread_instance.start.assert_called_once()
                thread_instance.join.assert_called_once()
                mock_factory.initialize.assert_awaited_once()

def test_get_session_factory_sync_raises_if_factory_none():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    with patch("infrastructure.database.session_factory_sqlalchemy._ensure_initialized_sync") as mock_ensure:
        # We need to simulate that after _ensure_initialized_sync, _session_factory is still None
        # But _ensure_initialized_sync is called, and if it raises, we catch.
        # Actually _ensure_initialized_sync will call initialize, which might fail.
        # We'll test the case where initialization fails.
        # But easier: we can patch SQLAlchemySessionFactory to fail.
        with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
            mock_class.side_effect = Exception("init error")
            with pytest.raises(SessionFactoryError):
                get_session_factory_sync()

async def test_get_async_session_factory():
    import infrastructure.database.session_factory_sqlalchemy as module
    mock_factory = MagicMock()
    mock_factory.get_session_factory = MagicMock(return_value="session_maker")
    module._session_factory = mock_factory

    result = await get_async_session_factory()
    assert result == "session_maker"
    mock_factory.get_session_factory.assert_called_once()

async def test_get_async_session_factory_none():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    mock_factory = AsyncMock()
    mock_factory.get_session_factory = MagicMock(return_value="session_maker")
    with patch("infrastructure.database.session_factory_sqlalchemy.SQLAlchemySessionFactory") as mock_class:
        mock_class.return_value = mock_factory
        result = await get_async_session_factory()
        assert result == "session_maker"
        mock_factory.initialize.assert_awaited_once()

async def test_get_async_session():
    mock_session = AsyncMock()
    mock_factory = AsyncMock()
    mock_factory.get_session = AsyncMock(return_value=mock_session)
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = mock_factory

    # Use async generator
    gen = get_async_session()
    session = await gen.__anext__()
    assert session == mock_session

    # Simulate no exception -> commit
    # We need to exhaust the generator to trigger commit
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    mock_session.commit.assert_awaited_once()
    mock_session.close.assert_awaited_once()

async def test_get_async_session_with_exception():
    mock_session = AsyncMock()
    mock_session.commit.side_effect = Exception("commit error")
    mock_factory = AsyncMock()
    mock_factory.get_session = AsyncMock(return_value=mock_session)
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = mock_factory

    gen = get_async_session()
    session = await gen.__anext__()
    assert session == mock_session

    # Simulate exception during processing
    # The generator will yield, then if exception occurs in the block, it rolls back
    # We need to simulate the context manager behavior: the user code runs between yield and finally.
    # But we can just raise an exception and see rollback.
    # Since we can't easily raise inside the generator, we'll test by simulating a manual rollback.
    # Instead, we'll just test that rollback is called if an exception occurs after yield.
    # To trigger rollback, we need to throw an exception into the generator.
    # We'll do that.
    with pytest.raises(ValueError):
        gen.throw(ValueError("test error"))
    mock_session.rollback.assert_awaited_once()
    mock_session.close.assert_awaited_once()

async def test_get_async_session_alias():
    # get_session is alias for get_async_session
    with patch("infrastructure.database.session_factory_sqlalchemy.get_async_session") as mock:
        async for _ in get_session():
            pass
        mock.assert_called_once()

async def test_get_read_session():
    mock_session = AsyncMock()
    mock_factory = AsyncMock()
    mock_factory.get_readonly_session = AsyncMock(return_value=mock_session)
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = mock_factory

    gen = get_read_session()
    session = await gen.__anext__()
    assert session == mock_session

    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    mock_session.close.assert_awaited_once()


def test_get_engine():
    import infrastructure.database.session_factory_sqlalchemy as module
    mock_factory = MagicMock()
    mock_factory._initialized = True
    mock_factory.get_engine = MagicMock(return_value="engine")
    module._session_factory = mock_factory

    engine = get_engine()
    assert engine == "engine"

def test_get_engine_not_initialized():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None

    with patch("infrastructure.database.session_factory_sqlalchemy._ensure_initialized_sync") as mock_ensure:
        # Simulate that after ensure, factory exists but engine is None
        mock_factory = MagicMock()
        mock_factory.get_engine = MagicMock(return_value=None)
        module._session_factory = mock_factory
        with pytest.raises(SessionFactoryError, match="Engine is not available"):
            get_engine()


async def test_dispose():
    import infrastructure.database.session_factory_sqlalchemy as module
    mock_factory = AsyncMock()
    module._session_factory = mock_factory

    await dispose()
    mock_factory.close.assert_awaited_once()
    assert module._session_factory is None

async def test_dispose_no_factory():
    import infrastructure.database.session_factory_sqlalchemy as module
    module._session_factory = None
    await dispose()  # Should not raise


def test_get_test_session():
    # get_test_session uses SQLite in-memory, should work without DB
    session = get_test_session()
    assert session is not None
    # Check it's a SQLAlchemy session
    assert hasattr(session, "execute")
    # Should be the same session if called again (singleton)
    session2 = get_test_session()
    assert session is session2


async def test_create_session_factory():
    with patch("infrastructure.database.session_factory_sqlalchemy.get_async_session_factory") as mock:
        mock.return_value = "async_session_maker"
        result = await create_session_factory()
        assert result == "async_session_maker"
        mock.assert_awaited_once()


# ============================================================================
# Integration-like tests (still with mocks) for factory configuration
# ============================================================================
def test_factory_uses_environment_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg2://user:pass@remote:5432/db")
    with patch("infrastructure.database.session_factory_sqlalchemy.load_yaml_config") as mock_load:
        mock_load.return_value = {"database": {}}
        factory = SQLAlchemySessionFactory("dummy.yaml")
        # _build_async_dsn called inside initialize
        # We can test the logic directly
        dsn = factory._build_async_dsn()
        # Should replace psycopg2 with asyncpg
        assert dsn.startswith("postgresql+asyncpg://")
        assert "remote" in dsn
        assert "db" in dsn