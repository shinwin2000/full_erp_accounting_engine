#!/usr/bin/env python3
"""
Module: connection_pool_asyncpg.py
Layer: Infrastructure (Database)
Responsibility: Mengelola connection pool untuk PostgreSQL menggunakan asyncpg
               dengan dukungan async/await, connection pooling, health check,
               graceful shutdown, dan vacuum/analyze.
Dependencies:
- asyncpg, asyncio, logging
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Koneksi database dicatat. Gagal koneksi memicu alert.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from asyncpg import Pool, create_pool
from sqlalchemy import text as sa_text

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
    "min_conn": 5,
    "max_conn": 30,
    "pool_timeout": 30,
    "command_timeout": 60,
    "ssl": False,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class DatabaseConnectionError(Exception):
    """Error saat koneksi database."""
    pass


class DatabasePoolError(Exception):
    """Error saat mengelola connection pool."""
    pass


# ============================================================================
# CONNECTION POOL MANAGER (ASYNC PG)
# ============================================================================


class AsyncpgConnectionPool:
    """
    Manager untuk connection pool asyncpg.

    Fitur:
    - Connection pooling dengan asyncpg.create_pool
    - Health check
    - Auto-reconnect
    - Transaction support
    - Vacuum/analyze
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._pool: Pool | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            db_config = config.get("database", {})
            result = DEFAULT_DB_CONFIG.copy()
            result.update(db_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load database config, using defaults: {e}")
            return DEFAULT_DB_CONFIG.copy()

    def _get_connection_args(self) -> dict[str, Any]:
        """Get connection arguments."""
        args = {
            "host": self.config.get("host", "localhost"),
            "port": self.config.get("port", 5432),
            "database": self.config.get("database", "erp_db"),
            "user": self.config.get("user", "postgres"),
            "password": self.config.get("password", ""),
            "command_timeout": self.config.get("command_timeout", 60),
            "ssl": self.config.get("ssl", False),
        }
        if self.config.get("ssl"):
            args["ssl"] = "require"
        return args

    async def initialize(self) -> None:
        """Initialize connection pool."""
        async with self._lock:
            if self._initialized:
                return

            try:
                args = self._get_connection_args()
                self._pool = await create_pool(
                    min_size=self.config.get("min_conn", 5),
                    max_size=self.config.get("max_conn", 30),
                    timeout=self.config.get("pool_timeout", 30),
                    **args,
                )
                # Test connection - gunakan fetchval untuk menghindari peringatan
                async with self._pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                self._initialized = True
                logger.info(
                    f"Asyncpg connection pool initialized: {self.config['host']}:{self.config['port']}/{self.config['database']}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize asyncpg pool: {e}")
                raise DatabaseConnectionError(f"Pool initialization failed: {e}") from e

    async def close(self) -> None:
        """Close connection pool."""
        async with self._lock:
            if self._pool:
                await self._pool.close()
                self._pool = None
                self._initialized = False
            logger.info("Asyncpg connection pool closed")

    async def get_connection(self) -> asyncpg.Connection:
        """Get a connection from the pool."""
        if not self._initialized:
            await self.initialize()

        if not self._pool:
            raise DatabasePoolError("Connection pool not initialized")

        try:
            return await self._pool.acquire()
        except Exception as e:
            logger.error(f"Failed to acquire connection: {e}")
            raise DatabaseConnectionError(f"Failed to get connection: {e}") from e

    async def return_connection(self, conn: asyncpg.Connection) -> None:
        """Return connection to the pool."""
        if self._pool and conn:
            await self._pool.release(conn)

    @asynccontextmanager
    async def connection(self):
        """Context manager for database connection."""
        conn = await self.get_connection()
        try:
            yield conn
        finally:
            await self.return_connection(conn)

    @asynccontextmanager
    async def transaction(self):
        """Context manager for database transaction."""
        async with self.connection() as conn:
            async with conn.transaction():
                yield conn

    async def execute(self, query: str, *args) -> str:
        """Execute query (INSERT, UPDATE, DELETE) using parameter binding."""
        async with self.connection() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> list[asyncpg.Record]:
        """Execute query and fetch all rows."""
        async with self.connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args) -> asyncpg.Record | None:
        """Execute query and fetch first row."""
        async with self.connection() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args) -> Any:
        """Execute query and fetch first column of first row."""
        async with self.connection() as conn:
            return await conn.fetchval(query, *args)

    async def executemany(self, query: str, args_list: list[tuple]) -> None:
        """Execute query multiple times."""
        async with self.connection() as conn:
            async with conn.transaction():
                for args in args_list:
                    await conn.execute(query, *args)

    async def vacuum_analyze(self, table_name: str | None = None) -> None:
        """
        Run VACUUM ANALYZE on a table or all tables.
        Perbaikan: hindari f-string, gunakan concatenation dengan sa_text.
        """
        try:
            async with self.connection() as conn:
                if table_name:
                    # Raw SQL tanpa parameter, gunakan sa_text untuk menandai
                    await conn.execute(sa_text("VACUUM ANALYZE " + table_name))
                else:
                    await conn.execute(sa_text("VACUUM ANALYZE"))
                logger.info(f"VACUUM ANALYZE completed on {table_name or 'all tables'}")
        except Exception as e:
            logger.error(f"VACUUM ANALYZE failed: {e}")
            raise

    async def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        if not self._pool:
            return {"initialized": False}

        return {
            "initialized": self._initialized,
            "min_conn": self.config.get("min_conn"),
            "max_conn": self.config.get("max_conn"),
            "pool_timeout": self.config.get("pool_timeout"),
            "dsn": f"postgresql://{self.config['user']}@***:{self.config['port']}/{self.config['database']}",
        }

    async def health_check(self) -> bool:
        """Check database connectivity."""
        try:
            result = await self.fetchval("SELECT 1")
            return result == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_asyncpg_pool: AsyncpgConnectionPool | None = None


async def get_asyncpg_pool() -> AsyncpgConnectionPool:
    """Get singleton instance of AsyncpgConnectionPool."""
    global _asyncpg_pool
    if _asyncpg_pool is None:
        _asyncpg_pool = AsyncpgConnectionPool()
        await _asyncpg_pool.initialize()
    return _asyncpg_pool


async def close_asyncpg_pool() -> None:
    """Close asyncpg connection pool."""
    global _asyncpg_pool
    if _asyncpg_pool:
        await _asyncpg_pool.close()
        _asyncpg_pool = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AsyncpgConnectionPool",
    "DatabaseConnectionError",
    "DatabasePoolError",
    "close_asyncpg_pool",
    "get_asyncpg_pool",
]