#!/usr/bin/env python3
"""
Module: connection_pool_asyncpg.py
Layer: Infrastructure (Database)
Responsibility: Mengelola connection pool untuk PostgreSQL menggunakan asyncpg.
               Menyediakan koneksi database yang efisien untuk operasi read/write.
               Mendukung connection pooling, health check, retry, dan graceful shutdown.
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
from asyncpg.pool import Pool, create_pool

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.telemetry.alert_manager_router import trigger_alert
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
    "min_size": 10,
    "max_size": 50,
    "max_queries": 50000,
    "max_inactive_connection_lifetime": 300,
    "command_timeout": 60,
    "connection_timeout": 10,
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
# CONNECTION POOL MANAGER
# ============================================================================


class AsyncPGConnectionPool:
    """
    Manager untuk connection pool asyncpg.

    Fitur:
    - Connection pooling untuk performance
    - Health check
    - Auto-reconnect (melalui pool)
    - Transaction support
    - Metrics collection
    - Graceful shutdown
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._pool: Pool | None = None
        self._dsn = self._build_dsn()
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

    def _build_dsn(self) -> str:
        """Build PostgreSQL DSN from config."""
        dsn = f"postgresql://{self.config['user']}@{self.config['host']}:{self.config['port']}/{self.config['database']}"
        if self.config.get("password"):
            dsn = f"postgresql://{self.config['user']}:{self.config['password']}@{self.config['host']}:{self.config['port']}/{self.config['database']}"
        if self.config.get("ssl"):
            dsn += "?sslmode=require"
        return dsn

    async def initialize(self) -> None:
        """Initialize connection pool."""
        async with self._lock:
            if self._initialized:
                return

            try:
                self._pool = await create_pool(
                    dsn=self._dsn,
                    min_size=self.config.get("min_size", 10),
                    max_size=self.config.get("max_size", 50),
                    max_queries=self.config.get("max_queries", 50000),
                    max_inactive_connection_lifetime=self.config.get(
                        "max_inactive_connection_lifetime", 300
                    ),
                    command_timeout=self.config.get("command_timeout", 60),
                    # Perubahan di sini: connection_timeout diubah menjadi timeout
                    timeout=self.config.get("connection_timeout", 10),
                    setup=self._setup_connection,
                )
                self._initialized = True
                logger.info(
                    f"Database connection pool initialized: {self.config.get('host')}:{self.config.get('port')}/{self.config.get('database')}"
                )
            except Exception as e:
                logger.error(f"Failed to initialize database pool: {e}")
                await trigger_alert(
                    title="Database Connection Failed",
                    message=f"Failed to connect to database: {e}",
                    severity="critical",
                    source="AsyncPGConnectionPool",
                )
                raise DatabaseConnectionError(f"Database initialization failed: {e}") from e

    async def _setup_connection(self, conn: asyncpg.Connection) -> None:
        """Setup connection settings (timezone, timeouts, app name)."""
        try:
            # Set timezone to UTC
            await conn.execute("SET TIME ZONE 'UTC'")
            # Set statement timeout (60 seconds)
            await conn.execute("SET statement_timeout = '60s'")
            # Set application name for monitoring
            await conn.execute("SET application_name = 'erp_accounting_engine'")
            # Optional: set default transaction isolation level
            await conn.execute("SET default_transaction_isolation = 'read committed'")
            logger.debug("Database connection configured")
        except Exception as e:
            logger.warning(f"Failed to configure connection: {e}")
            # Non-fatal, connection still usable

    async def close(self) -> None:
        """Close connection pool gracefully."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("Database connection pool closed")

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
        """Context manager for database transaction (automatic commit/rollback)."""
        async with self.connection() as conn, conn.transaction():
            yield conn

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

    async def execute(self, query: str, *args) -> str:
        """Execute query (INSERT, UPDATE, DELETE) and return status."""
        async with self.connection() as conn:
            return await conn.execute(query, *args)

    async def executemany(self, query: str, args_list: list[tuple]) -> None:
        """Execute query multiple times with different arguments."""
        async with self.connection() as conn:
            await conn.executemany(query, args_list)

    async def get_stats(self) -> dict[str, Any]:
        """Get pool statistics."""
        if not self._pool:
            return {"initialized": False}

        return {
            "initialized": self._initialized,
            "min_size": self.config.get("min_size"),
            "max_size": self.config.get("max_size"),
            "current_size": self._pool.get_size(),
            "free_size": self._pool.get_free_size(),
            "dsn": self._dsn.replace(self.config.get("password", ""), "***")
            if self.config.get("password")
            else self._dsn,
            "host": self.config.get("host"),
            "port": self.config.get("port"),
            "database": self.config.get("database"),
        }

    async def health_check(self) -> bool:
        """Check database connectivity and responsiveness."""
        try:
            result = await self.fetchval("SELECT 1")
            return result == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    async def vacuum_analyze(self, table_name: str | None = None) -> None:
        """
        Run VACUUM ANALYZE for maintenance.
        Use with caution; typically called during low activity.
        """
        try:
            if table_name:
                await self.execute(f"VACUUM ANALYZE {table_name}")
            else:
                await self.execute("VACUUM ANALYZE")
            logger.info(f"VACUUM ANALYZE completed on {table_name or 'all tables'}")
        except Exception as e:
            logger.error(f"VACUUM ANALYZE failed: {e}")
            raise DatabasePoolError(f"Maintenance failed: {e}") from e


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_connection_pool: AsyncPGConnectionPool | None = None


async def get_connection_pool() -> AsyncPGConnectionPool:
    """Get singleton instance of AsyncPGConnectionPool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = AsyncPGConnectionPool()
        await _connection_pool.initialize()
    return _connection_pool


# ============================================================================
# BACKWARD COMPATIBILITY ALIAS
# ============================================================================
# Fungsi get_pool() disediakan untuk kompatibilitas dengan kode lama yang
# mengimpor 'get_pool' dari modul ini (misal health_dashboard.py:301).
# Mengembalikan instance pool yang sama dengan get_connection_pool().
async def get_pool() -> AsyncPGConnectionPool:
    """
    Alias untuk get_connection_pool().
    Digunakan untuk kompatibilitas mundur dengan import 'get_pool'.
    """
    return await get_connection_pool()


async def close_connection_pool() -> None:
    """Close connection pool globally."""
    global _connection_pool
    if _connection_pool:
        await _connection_pool.close()
        _connection_pool = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AsyncPGConnectionPool",
    "DatabaseConnectionError",
    "DatabasePoolError",
    "close_connection_pool",
    "get_connection_pool",
    "get_pool",                 
]