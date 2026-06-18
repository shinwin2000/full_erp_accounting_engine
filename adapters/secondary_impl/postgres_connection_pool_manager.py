#!/usr/bin/env python3
"""
Module: postgres_connection_pool_manager.py
Layer: Adapters (Secondary Implementation)
Responsibility: Mengelola koneksi pool ke PostgreSQL (async) dengan method acquire, initialize, close.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)


class AsyncPGConnectionPoolManager:
    """
    Manager connection pool PostgreSQL async.
    Menyediakan method yang dibutuhkan oleh application layer.
    """

    def __init__(self, dsn: str, min_size: int = 10, max_size: int = 50):
        """
        Args:
            dsn: Database connection string (postgresql+asyncpg://...)
            min_size: Minimum pool size (alias pool_size)
            max_size: Maximum pool size (alias max_overflow)
        """
        self.dsn = dsn
        self.min_size = min_size
        self.max_size = max_size
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker | None = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the connection pool."""
        if self._initialized:
            return
        self._engine = create_async_engine(
            self.dsn,
            pool_size=self.min_size,
            max_overflow=self.max_size - self.min_size if self.max_size > self.min_size else 0,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
        )
        self._session_factory = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )
        # Test connection
        async with self._engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        self._initialized = True
        logger.info(f"AsyncPGConnectionPoolManager initialized for {self.dsn}")

    async def close(self) -> None:
        """Close all connections and dispose the engine."""
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            logger.info("AsyncPGConnectionPoolManager closed")

    async def acquire(self) -> AsyncSession:
        """
        Acquire a session from the pool.
        Returns an AsyncSession that can be used directly.
        """
        if not self._initialized:
            await self.initialize()
        # session_factory is callable, returns a session
        # The session is an async context manager, but here we just return it
        # The caller will use it as: async with pool.acquire() as session:
        # However acquire() should return a session that can be used in async with?
        # We'll return the session directly, caller is responsible for closing.
        session = self._session_factory()
        return session

    async def get_connection(self) -> AsyncConnection:
        """Get a raw connection (for low-level operations)."""
        if not self._initialized:
            await self.initialize()
        return await self._engine.connect()

    @property
    def engine(self) -> AsyncEngine:
        if not self._initialized:
            raise RuntimeError("Pool not initialized")
        return self._engine
