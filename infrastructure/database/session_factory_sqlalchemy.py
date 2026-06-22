#!/usr/bin/env python3
"""
Module: session_factory_sqlalchemy.py
Layer: Infrastructure (Database)
Responsibility: Menyediakan factory untuk SQLAlchemy AsyncSession. Mengelola
                session factory dan engine untuk koneksi database async.
                Juga menyediakan dependency injection untuk FastAPI.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession, async_sessionmaker, create_async_engine)
- sqlalchemy.orm (declarative_base)
- sqlalchemy.sql (text)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Session creation dicatat. Engine configuration untuk production.
"""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import text  # WAJIB untuk eksekusi query mentah pada driver async

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "database": "erp_db",
    "user": "postgres",
    "password": None,
    "pool_size": 20,
    "max_overflow": 10,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "echo": False,
    "ssl": False,
}

Base = declarative_base()

# ============================================================================
# EXCEPTIONS
# ============================================================================


class SessionFactoryError(Exception):
    """Error saat membuat session factory."""

    pass


# ============================================================================
# SESSION FACTORY
# ============================================================================


class SQLAlchemySessionFactory:
    """
    Factory untuk SQLAlchemy AsyncSession.

    Fitur:
    - Async engine dengan connection pooling
    - Session factory dengan scoped sessions
    - Health check aman dari driver leak (menggunakan text())
    - Graceful shutdown
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._engine = None
        self._session_factory = None
        self._initialized = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            db_config = config.get("database", {})
            result = DEFAULT_DB_CONFIG.copy()
            result.update(db_config)

            # DEFENSIVE GUARD: Prioritaskan membaca environment variable jika tersedia
            if os.getenv("DATABASE_URL"):
                logger.info(
                    "DATABASE_URL environment variable detected, overriding YAML credentials."
                )

            return result
        except Exception as e:
            logger.warning(f"Failed to load database config, using defaults: {e}")
            return DEFAULT_DB_CONFIG.copy()

    def _build_async_dsn(self) -> str:
        """Build async PostgreSQL DSN for SQLAlchemy."""
        # 1. Prioritaskan .env secara real-time saat fungsi dipanggil
        env_dsn = os.getenv("DATABASE_URL")
        if env_dsn:
            if env_dsn.startswith("postgresql://"):
                return env_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif "postgresql+psycopg2://" in env_dsn:
                return env_dsn.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
            return env_dsn

        # 2. ABSOLUTE GUARD: Jika .env belum terbaca dan sistem jatuh ke fallback YAML/Default Config,
        #    paksa bangun DSN menggunakan dialek +asyncpg secara eksplisit.
        password_part = ""
        if self.config.get("password"):
            password_part = f":{self.config['password']}"

        dsn = f"postgresql+asyncpg://{self.config['user']}{password_part}@{self.config['host']}:{self.config['port']}/{self.config['database']}"

        if self.config.get("ssl"):
            dsn += "?sslmode=require"

        logger.warning(
            f"DATABASE_URL not found in environment. Built async DSN from config: {self.config['host']}/{self.config['database']}"
        )
        return dsn

    async def initialize(self) -> None:
        """Initialize engine and session factory."""
        if self._initialized:
            return

        dsn = self._build_async_dsn()

        try:
            # Create engine dengan connection pooling murni asinkronus
            self._engine = create_async_engine(
                dsn,
                pool_size=self.config.get("pool_size", 20),
                max_overflow=self.config.get("max_overflow", 10),
                pool_timeout=self.config.get("pool_timeout", 30),
                pool_recycle=self.config.get("pool_recycle", 3600),
                pool_pre_ping=True,
                echo=self.config.get("echo", False),
                future=True,
            )

            # Create session factory khusus async_sessionmaker
            self._session_factory = async_sessionmaker(
                self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autocommit=False,
                autoflush=False,
            )

            self._initialized = True
            logger.info(
                f"SQLAlchemy session factory initialized successfully for target: {self.config['host']}/{self.config['database']}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize SQLAlchemy engine: {e}")
            raise SessionFactoryError(f"Engine initialization failed: {e}") from e

    async def close(self) -> None:
        """Close engine and dispose connections gracefully."""
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            logger.info("SQLAlchemy engine disposed")

    async def get_session(self) -> AsyncSession:
        """Get a new session from factory."""
        if not self._initialized:
            await self.initialize()

        if not self._session_factory:
            raise SessionFactoryError("Session factory not initialized")

        return self._session_factory()

    async def get_readonly_session(self) -> AsyncSession:
        """
        Get a new session configured for read-only operations.
        Bungkus query mentah dengan text() untuk mencegah fallback ke psycopg2.
        """
        session = await self.get_session()
        # FIX: Menggunakan text() untuk menjamin eksekusi lewat driver asinkronus (asyncpg)
        await session.execute(text("SET TRANSACTION READ ONLY"))
        return session

    async def create_all_tables(self) -> None:
        """Create all tables (for development/testing)."""
        if not self._initialized:
            await self.initialize()

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("All database tables created")

    async def drop_all_tables(self) -> None:
        """Drop all tables (for testing)."""
        if not self._initialized:
            await self.initialize()

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        logger.info("All database tables dropped")

    async def health_check(self) -> bool:
        """Check database connectivity."""
        if not self._initialized:
            try:
                await self.initialize()
            except Exception:
                return False
        try:
            async with self._engine.connect() as conn:
                # FIX: String query dibungkus dengan text() agar dieksekusi secara async murni
                result = await conn.execute(text("SELECT 1"))
                return result.scalar() == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    def get_engine(self):
        """Get SQLAlchemy engine (for migrations, etc.)."""
        return self._engine

    def get_session_factory(self):
        """Get async session factory (async_sessionmaker)."""
        return self._session_factory


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_session_factory: SQLAlchemySessionFactory | None = None


def _ensure_initialized_sync() -> None:
    """
    Synchronous initialization wrapper for tools/checks that cannot use async.
    Handles running loop environments gracefully by offloading to a dedicated
    worker thread when necessary to avoid nested loop conflicts.
    """
    global _session_factory
    if _session_factory is not None and _session_factory._initialized:
        return

    # If factory exists but not initialized, initialize it
    if _session_factory is None:
        _session_factory = SQLAlchemySessionFactory()

    # If already initialized, return
    if _session_factory._initialized:
        return

    try:
        # Check if an event loop is already running in the current thread
        asyncio.get_running_loop()

        # An active event loop is detected. To prevent nested event loop RuntimeError,
        # offload the async initialization to an isolated thread with its own loop.
        def _run_in_thread():
            thread_loop = asyncio.new_event_loop()
            try:
                thread_loop.run_until_complete(_session_factory.initialize())
            finally:
                thread_loop.close()

        worker = threading.Thread(target=_run_in_thread, name="DBFactoryInitWorker")
        worker.start()
        worker.join()  # Block current thread until initialization finishes completely

    except RuntimeError:
        # No running event loop detected, safe to spin up a local loop directly
        sub_loop = asyncio.new_event_loop()
        try:
            sub_loop.run_until_complete(_session_factory.initialize())
        finally:
            sub_loop.close()


async def get_session_factory() -> SQLAlchemySessionFactory:
    """Get singleton instance of SQLAlchemySessionFactory (async)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = SQLAlchemySessionFactory()
        await _session_factory.initialize()
    return _session_factory


def get_session_factory_sync() -> SQLAlchemySessionFactory:
    """
    Get singleton instance of SQLAlchemySessionFactory (synchronous).
    Use this ONLY in synchronous contexts (e.g., scripts, checkers).
    """
    _ensure_initialized_sync()
    if _session_factory is None:
        raise SessionFactoryError("Session factory not initialized.")
    return _session_factory


async def get_async_session_factory() -> async_sessionmaker:
    """
    Get async session factory (async_sessionmaker) for direct use.
    """
    factory = await get_session_factory()
    session_maker = factory.get_session_factory()
    if session_maker is None:
        raise SessionFactoryError("Session factory not available")
    return session_maker


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database session.
    """
    factory = await get_session_factory()
    async with factory.get_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Alias for get_async_session() for backward compatibility.
    """
    async for session in get_async_session():
        yield session


async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for read-only database session.
    """
    factory = await get_session_factory()
    async with factory.get_readonly_session() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# ============================================================================

def get_engine():
    """
    Get the SQLAlchemy engine from the singleton session factory.
    This is a synchronous function; it ensures initialization is done first.
    """
    _ensure_initialized_sync()
    if _session_factory is None:
        raise SessionFactoryError("Session factory not initialized.")
    engine = _session_factory.get_engine()
    if engine is None:
        raise SessionFactoryError("Engine is not available.")
    return engine


async def dispose() -> None:
    """Dispose singleton instance of SQLAlchemySessionFactory gracefully."""
    global _session_factory
    if _session_factory is not None:
        await _session_factory.close()
        _session_factory = None


# TEST SESSION FACTORY (SYNC, IN-MEMORY SQLITE)
# ============================================================================

_test_engine = None
_test_session_factory = None


def get_test_session():
    """
    Return a sync SQLAlchemy session for testing (SQLite in-memory).
    """
    global _test_engine, _test_session_factory
    if _test_engine is None:
        _test_engine = create_engine("sqlite:///:memory:", echo=False)
        _test_session_factory = sessionmaker(bind=_test_engine)
        Base.metadata.create_all(_test_engine)
    return _test_session_factory()


# ============================================================================
# EXPORTS
# ============================================================================
# Alias for compatibility with __init__.py
async def create_session_factory() -> async_sessionmaker:
    """Create and return the async session factory."""
    return await get_async_session_factory()


__all__ = [
    "Base",
    "SQLAlchemySessionFactory",
    "SessionFactoryError",
    "create_session_factory",
    "dispose",
    "get_async_session",
    "get_async_session_factory",
    "get_engine",           # fixed to auto-initialize
    "get_read_session",
    "get_session",
    "get_session_factory",
    "get_session_factory_sync",  # synchronous version for checker
    "get_test_session",
]
