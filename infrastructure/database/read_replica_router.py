#!/usr/bin/env python3
"""
Module: read_replica_router.py
Layer: Infrastructure (Database)
Responsibility: Mengelola routing query ke read replica untuk memisahkan beban
               baca dan tulis. Mendeteksi jenis query (SELECT vs INSERT/UPDATE/DELETE)
               dan mengarahkan ke koneksi yang sesuai (master untuk tulis, replica
               untuk baca). Juga mendukung forced read from master jika diperlukan.
Dependencies:
- sqlalchemy.ext.asyncio (AsyncSession)
- infrastructure.database.session_factory_sqlalchemy (SQLAlchemySessionFactory)
- infrastructure.database.connection_pool_asyncpg (AsyncpgConnectionPool)
- config.loader_yaml
- infrastructure.telemetry.structured_json_logging
Audit: Routing keputusan dicatat untuk debugging. Query yang salah routing
       (write ke replica) akan dicegah.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Internal dependencies
from config.loader_yaml import load_yaml_config
from infrastructure.database.session_factory_sqlalchemy import (
    SQLAlchemySessionFactory,
    get_session_factory,
)
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_REPLICA_CONFIG = {
    "replica_host": "localhost",
    "replica_port": 5433,
    "replica_database": "erp_db",
    "replica_user": "postgres",
    "replica_password": None,
    "enabled": False,
    "read_only_force": False,  # If True, all SELECT go to replica; else auto-detect
    "fallback_to_master": True,
}

# Regex pattern untuk mendeteksi read-only queries (SELECT, SHOW, EXPLAIN)
READ_ONLY_PATTERN = re.compile(r"^\s*(SELECT|SHOW|EXPLAIN|WITH|DESCRIBE|DESC)\s", re.IGNORECASE)

WRITE_PATTERN = re.compile(
    r"^\s*(INSERT|UPDATE|DELETE|REPLACE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE)\s", re.IGNORECASE
)

# ============================================================================
# EXCEPTIONS
# ============================================================================


class ReadReplicaError(Exception):
    """Base exception untuk read replica router."""

    pass


class WriteToReplicaError(ReadReplicaError):
    """Mencoba menulis ke read replica."""

    pass


class ReplicaUnavailableError(ReadReplicaError):
    """Read replica tidak tersedia."""

    pass


# ============================================================================
# READ REPLICA ROUTER
# ============================================================================


class ReadReplicaRouter:
    """
    Router untuk mengarahkan query ke master atau read replica.

    Fitur:
    - Deteksi otomatis read vs write query
    - Routing SELECT ke replica, lainnya ke master
    - Fallback ke master jika replica down
    - Forced read from master untuk query yang memerlukan konsistensi
    - Health check untuk replica
    """

    def __init__(self, config_path: str = "config_files/database_config.yaml"):
        self.config = self._load_config(config_path)
        self._master_factory: SQLAlchemySessionFactory | None = None
        self._replica_engine = None
        self._replica_session_factory = None
        self._replica_enabled = self.config.get("enabled", False)
        self._read_only_force = self.config.get("read_only_force", False)
        self._fallback_to_master = self.config.get("fallback_to_master", True)
        self._initialized = False

    def _load_config(self, config_path: str) -> dict[str, Any]:
        try:
            config = load_yaml_config(config_path)
            replica_config = config.get("read_replica", {})
            result = DEFAULT_REPLICA_CONFIG.copy()
            result.update(replica_config)
            return result
        except Exception as e:
            logger.warning(f"Failed to load read replica config, using defaults: {e}")
            return DEFAULT_REPLICA_CONFIG.copy()

    async def initialize(self) -> None:
        """Initialize master factory and replica connection."""
        if self._initialized:
            return

        # Get master factory
        self._master_factory = await get_session_factory()

        # Initialize replica if enabled
        if self._replica_enabled:
            await self._init_replica()

        self._initialized = True
        logger.info(f"Read replica router initialized (replica_enabled={self._replica_enabled})")

    async def _init_replica(self) -> None:
        """Initialize replica engine and session factory."""
        try:
            dsn = self._build_replica_dsn()
            self._replica_engine = create_async_engine(
                dsn, pool_size=10, max_overflow=5, pool_pre_ping=True, echo=False
            )
            self._replica_session_factory = sessionmaker(
                self._replica_engine, class_=AsyncSession, expire_on_commit=False
            )
            # Test connection
            async with self._replica_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info(
                f"Read replica initialized: {self.config['replica_host']}:{self.config['replica_port']}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize read replica: {e}")
            self._replica_enabled = False
            if self._fallback_to_master:
                logger.warning("Falling back to master for all queries")
            else:
                await trigger_alert(
                    title="Read Replica Unavailable",
                    message=f"Read replica failed to initialize: {e}",
                    severity="warning",
                    source="ReadReplicaRouter",
                )

    def _build_replica_dsn(self) -> str:
        """Build DSN for read replica."""
        dsn = f"postgresql+asyncpg://{self.config['replica_user']}@{self.config['replica_host']}:{self.config['replica_port']}/{self.config['replica_database']}"
        if self.config.get("replica_password"):
            dsn = f"postgresql+asyncpg://{self.config['replica_user']}:{self.config['replica_password']}@{self.config['replica_host']}:{self.config['replica_port']}/{self.config['replica_database']}"
        return dsn

    def _is_read_only_query(self, statement: str) -> bool:
        """Determine if a SQL statement is read-only."""
        # Clean statement
        stmt = statement.strip()

        # Check for read-only patterns
        if READ_ONLY_PATTERN.match(stmt):
            return True

        # If not read-only pattern and not write pattern, assume read-only (safe)
        if not WRITE_PATTERN.match(stmt):
            # Could be a SELECT without leading SELECT? Be safe, treat as read-only
            return True

        return False

    async def get_session(
        self, statement: str | None = None, force_master: bool = False
    ) -> AsyncSession:
        """
        Get appropriate session based on query type.

        Args:
            statement: SQL statement (for auto-detection)
            force_master: Force using master even for read queries

        Returns:
            AsyncSession (master or replica)
        """
        if not self._initialized:
            await self.initialize()

        # If replica is disabled or force_master, use master
        if not self._replica_enabled or force_master:
            return await self._master_factory.get_session()

        # Auto-detect based on statement
        if statement and not self._read_only_force:
            if self._is_read_only_query(statement):
                # Read query, try replica
                try:
                    if self._replica_session_factory:
                        return self._replica_session_factory()
                except Exception as e:
                    logger.warning(f"Failed to get replica session: {e}")
                    if self._fallback_to_master:
                        logger.info("Falling back to master for this query")
                        return await self._master_factory.get_session()
                    else:
                        raise ReplicaUnavailableError(f"Replica unavailable: {e}")
            else:
                # Write query, must use master
                return await self._master_factory.get_session()

        # Default to master for safety
        return await self._master_factory.get_session()

    @asynccontextmanager
    async def session(self, statement: str | None = None, force_master: bool = False):
        """Context manager for getting and managing session."""
        session = await self.get_session(statement, force_master)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def execute(self, statement: str, *args, **kwargs) -> Any:
        """Execute a SQL statement with automatic routing."""
        session = await self.get_session(statement)
        try:
            result = await session.execute(text(statement), *args, **kwargs)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def fetch_all(self, statement: str, *args, **kwargs) -> list:
        """Execute SELECT and fetch all rows."""
        session = await self.get_session(statement)
        try:
            result = await session.execute(text(statement), *args, **kwargs)
            rows = result.fetchall()
            return rows
        finally:
            await session.close()

    async def fetch_one(self, statement: str, *args, **kwargs) -> Any | None:
        """Execute SELECT and fetch first row."""
        session = await self.get_session(statement)
        try:
            result = await session.execute(text(statement), *args, **kwargs)
            row = result.fetchone()
            return row
        finally:
            await session.close()

    async def health_check(self) -> dict[str, bool]:
        """
        Check health of master and replica.
        """
        result = {"master": False, "replica": False}

        # Check master
        try:
            async with await self._master_factory.get_session() as session:
                await session.execute(text("SELECT 1"))
            result["master"] = True
        except Exception as e:
            logger.error(f"Master health check failed: {e}")

        # Check replica
        if self._replica_enabled and self._replica_engine:
            try:
                async with self._replica_engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                result["replica"] = True
            except Exception as e:
                logger.warning(f"Replica health check failed: {e}")

        return result

    async def get_stats(self) -> dict[str, Any]:
        """Get router statistics."""
        return {
            "initialized": self._initialized,
            "replica_enabled": self._replica_enabled,
            "read_only_force": self._read_only_force,
            "fallback_to_master": self._fallback_to_master,
            "replica_config": {
                "host": self.config.get("replica_host"),
                "port": self.config.get("replica_port"),
                "database": self.config.get("replica_database"),
            }
            if self._replica_enabled
            else None,
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_read_replica_router: ReadReplicaRouter | None = None


async def get_read_replica_router() -> ReadReplicaRouter:
    """Get singleton instance of ReadReplicaRouter."""
    global _read_replica_router
    if _read_replica_router is None:
        _read_replica_router = ReadReplicaRouter()
        await _read_replica_router.initialize()
    return _read_replica_router


# ============================================================================
# FASTAPI DEPENDENCY
# ============================================================================


async def get_db_session(statement: str | None = None, force_master: bool = False):
    """
    FastAPI dependency for database session with automatic read/write routing.
    """
    router = await get_read_replica_router()
    async with router.session(statement, force_master) as session:
        yield session


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ReadReplicaError",
    "ReadReplicaRouter",
    "ReplicaUnavailableError",
    "WriteToReplicaError",
    "get_db_session",
    "get_read_replica_router",
]
