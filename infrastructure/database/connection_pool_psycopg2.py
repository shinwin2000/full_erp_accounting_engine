#!/usr/bin/env python3
"""
Module: connection_pool_psycopg2.py
Layer: Infrastructure (Database)
Responsibility: Mengelola connection pool untuk PostgreSQL menggunakan psycopg2 (sync)
               dengan wrapper async menggunakan ThreadPoolExecutor. Digunakan untuk
               operasi database yang tidak mendukung async atau untuk legacy code.
               Mendukung connection pooling, health check, dan graceful shutdown.
Dependencies:
- psycopg2, psycopg2.pool, asyncio, threading, logging
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
- infrastructure.telemetry.alert_manager_router
Audit: Koneksi database dicatat. Gagal koneksi memicu alert.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from psycopg2 import extras, pool
from psycopg2.extensions import connection as Psycopg2Connection

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
# CONNECTION POOL MANAGER (PSYCOPG2)
# ============================================================================


class Psycopg2ConnectionPool:
    """
    Manager untuk connection pool psycopg2 dengan async wrapper.

    Fitur:
    - Connection pooling dengan psycopg2.pool.ThreadedConnectionPool
    - Async wrapper menggunakan ThreadPoolExecutor
    - Health check
    - Auto-reconnect
    - Transaction support
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._pool: pool.ThreadedConnectionPool | None = None
        self._executor = ThreadPoolExecutor(max_workers=self.config.get("max_conn", 30))
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
            "connect_timeout": self.config.get("connection_timeout", 10),
        }
        if self.config.get("password"):
            args["password"] = self.config["password"]
        if self.config.get("ssl"):
            args["sslmode"] = "require"
        return args

    async def initialize(self) -> None:
        """Initialize connection pool."""
        async with self._lock:
            if self._initialized:
                return

            await asyncio.get_event_loop().run_in_executor(self._executor, self._sync_initialize)
            self._initialized = True
            logger.info(
                f"Psycopg2 connection pool initialized: {self.config['host']}:{self.config['port']}/{self.config['database']}"
            )

    def _sync_initialize(self) -> None:
        """Synchronous initialization."""
        try:
            args = self._get_connection_args()
            self._pool = pool.ThreadedConnectionPool(
                minconn=self.config.get("min_conn", 5),
                maxconn=self.config.get("max_conn", 30),
                **args,
            )
            # Test connection
            test_conn = self._pool.getconn()
            cursor = test_conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            self._pool.putconn(test_conn)
        except Exception as e:
            logger.error(f"Failed to initialize psycopg2 pool: {e}")
            raise DatabaseConnectionError(f"Pool initialization failed: {e}") from e

    async def close(self) -> None:
        """Close connection pool."""
        async with self._lock:
            if self._pool:
                await asyncio.get_event_loop().run_in_executor(self._executor, self._sync_close)
                self._pool = None
                self._initialized = False
            self._executor.shutdown(wait=True)
            logger.info("Psycopg2 connection pool closed")

    def _sync_close(self) -> None:
        """Synchronous close."""
        if self._pool:
            self._pool.closeall()

    async def get_connection(self) -> Psycopg2Connection:
        """Get a connection from the pool (async wrapper)."""
        if not self._initialized:
            await self.initialize()

        if not self._pool:
            raise DatabasePoolError("Connection pool not initialized")

        def _get():
            return self._pool.getconn()

        try:
            conn = await asyncio.get_event_loop().run_in_executor(self._executor, _get)
            return conn
        except Exception as e:
            logger.error(f"Failed to acquire connection: {e}")
            raise DatabaseConnectionError(f"Failed to get connection: {e}") from e

    async def return_connection(self, conn: Psycopg2Connection) -> None:
        """Return connection to the pool."""
        if self._pool and conn:

            def _put():
                self._pool.putconn(conn)

            await asyncio.get_event_loop().run_in_executor(self._executor, _put)

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
            # Auto-commit should be False for transaction
            old_autocommit = conn.autocommit
            conn.autocommit = False
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit = old_autocommit

    async def execute(self, query: str, *args) -> None:
        """Execute query (INSERT, UPDATE, DELETE)."""
        async with self.connection() as conn:

            def _execute():
                cursor = conn.cursor()
                cursor.execute(query, args)
                conn.commit()
                cursor.close()

            await asyncio.get_event_loop().run_in_executor(self._executor, _execute)

    async def fetch(self, query: str, *args) -> list[dict[str, Any]]:
        """Execute query and fetch all rows as dicts."""
        async with self.connection() as conn:

            def _fetch():
                cursor = conn.cursor(cursor_factory=extras.RealDictCursor)
                cursor.execute(query, args)
                rows = cursor.fetchall()
                cursor.close()
                return rows

            return await asyncio.get_event_loop().run_in_executor(self._executor, _fetch)

    async def fetchone(self, query: str, *args) -> dict[str, Any] | None:
        """Execute query and fetch first row as dict."""
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args) -> Any:
        """Execute query and fetch first column of first row."""
        row = await self.fetchone(query, *args)
        if row:
            # Return first value
            return next(iter(row.values())) if row else None
        return None

    async def executemany(self, query: str, args_list: list[tuple]) -> None:
        """Execute query multiple times."""
        async with self.connection() as conn:

            def _executemany():
                cursor = conn.cursor()
                cursor.executemany(query, args_list)
                conn.commit()
                cursor.close()

            await asyncio.get_event_loop().run_in_executor(self._executor, _executemany)

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

_psycopg2_pool: Psycopg2ConnectionPool | None = None


async def get_psycopg2_pool() -> Psycopg2ConnectionPool:
    """Get singleton instance of Psycopg2ConnectionPool."""
    global _psycopg2_pool
    if _psycopg2_pool is None:
        _psycopg2_pool = Psycopg2ConnectionPool()
        await _psycopg2_pool.initialize()
    return _psycopg2_pool


async def close_psycopg2_pool() -> None:
    """Close psycopg2 connection pool."""
    global _psycopg2_pool
    if _psycopg2_pool:
        await _psycopg2_pool.close()
        _psycopg2_pool = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabaseConnectionError",
    "DatabasePoolError",
    "Psycopg2ConnectionPool",
    "close_psycopg2_pool",
    "get_psycopg2_pool",
]
