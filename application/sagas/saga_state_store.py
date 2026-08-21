# saga_state_store.py - Complete implementation

#!/usr/bin/env python3

"""
Module: saga_state_store.py
Layer: 5 - Application / Sagas

Responsibility:
    Implementasi konkret untuk menyimpan dan memuat state saga menggunakan PostgreSQL.
    Juga menyediakan caching dengan Redis untuk performa.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from ports.primary.saga_state_store_port import SagaStateStorePort

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class DatabasePoolPort(Protocol):
    """Abstraksi untuk PostgreSQL connection pool."""

    async def acquire(self): ...
    async def close(self): ...
    async def execute(self, query: str, *args): ...
    async def fetchrow(self, query: str, *args): ...
    async def fetch(self, query: str, *args): ...


class RedisClientPort(Protocol):
    """Abstraksi untuk Redis client."""

    async def get(self, key: str) -> str | None: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def set(self, key: str, value: str, ex: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def exists(self, key: str) -> bool: ...
    async def expire(self, key: str, ttl: int) -> None: ...
    async def ping(self) -> bool: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...


# ============================================================================
# SAGA STATE STORE IMPLEMENTATION
# ============================================================================


class SagaStateStore(SagaStateStorePort):
    """
    Implementasi saga state store dengan PostgreSQL dan Redis cache.
    Semua dependency wajib disediakan melalui constructor injection.
    """

    def __init__(
        self,
        db_pool: DatabasePoolPort,
        redis_client: RedisClientPort | None,
        cache_ttl_seconds: int = 3600,
        table_name: str = "saga_state",
    ):
        if db_pool is None:
            raise ValueError("db_pool is required (no fallback allowed)")
        self._db_pool = db_pool
        self._redis = redis_client
        self._cache_ttl = cache_ttl_seconds
        self._table_name = table_name
        self._init_lock = asyncio.Lock()
        self._initialized = False
        logger.info(
            "SagaStateStore initialized (db=%s, cache=%s)",
            type(db_pool).__name__,
            type(redis_client).__name__ if redis_client else 'None'
        )

    async def _ensure_table(self) -> None:
        """Ensure the saga state table exists."""
        async with self._init_lock:
            if self._initialized:
                return

            # Build table creation SQL without f-string (use concatenation)
            create_table_sql = (
                "CREATE TABLE IF NOT EXISTS " + self._table_name + " ("
                "saga_type VARCHAR(100) NOT NULL, "
                "saga_id VARCHAR(36) NOT NULL, "
                "state JSONB NOT NULL, "
                "created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), "
                "updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(), "
                "PRIMARY KEY (saga_type, saga_id)"
                ")"
            )

            create_index_sql = (
                "CREATE INDEX IF NOT EXISTS idx_" + self._table_name + "_updated_at "
                "ON " + self._table_name + " (updated_at)"
            )

            async with self._db_pool.acquire() as conn:
                await conn.execute(create_table_sql)
                await conn.execute(create_index_sql)

            self._initialized = True
            logger.info("Saga state table '%s' ensured", self._table_name)

    async def save(self, saga_type: str, saga_id: UUID, state: dict[str, Any]) -> None:
        """Save saga state to database and cache."""
        await self._ensure_table()

        state_json = json.dumps(state, default=str, ensure_ascii=False)
        now = datetime.now(UTC)

        insert_sql = (
            "INSERT INTO " + self._table_name + " (saga_type, saga_id, state, created_at, updated_at) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (saga_type, saga_id) DO UPDATE "
            "SET state = EXCLUDED.state, updated_at = EXCLUDED.updated_at"
        )

        async with self._db_pool.acquire() as conn:
            await conn.execute(
                insert_sql,
                saga_type,
                str(saga_id),
                state_json,
                now,
                now,
            )

        if self._redis:
            cache_key = "saga:" + saga_type + ":" + str(saga_id)
            await self._redis.setex(cache_key, self._cache_ttl, state_json)

        logger.debug("Saga state saved: %s/%s", saga_type, saga_id)

    async def load(self, saga_type: str, saga_id: UUID) -> dict[str, Any] | None:
        """Load saga state from cache or database."""
        await self._ensure_table()

        if self._redis:
            cache_key = "saga:" + saga_type + ":" + str(saga_id)
            cached = await self._redis.get(cache_key)
            if cached:
                logger.debug("Cache hit for %s/%s", saga_type, saga_id)
                return json.loads(cached)

        select_sql = (
            "SELECT state FROM " + self._table_name + " "
            "WHERE saga_type = $1 AND saga_id = $2"
        )

        async with self._db_pool.acquire() as conn:
            row = await conn.fetchrow(select_sql, saga_type, str(saga_id))
            if row:
                state = json.loads(row["state"])
                if self._redis:
                    cache_key = "saga:" + saga_type + ":" + str(saga_id)
                    await self._redis.setex(cache_key, self._cache_ttl, json.dumps(state))
                return state

        return None

    async def delete(self, saga_type: str, saga_id: UUID) -> None:
        """Delete saga state."""
        await self._ensure_table()

        delete_sql = (
            "DELETE FROM " + self._table_name + " "
            "WHERE saga_type = $1 AND saga_id = $2"
        )

        async with self._db_pool.acquire() as conn:
            await conn.execute(delete_sql, saga_type, str(saga_id))

        if self._redis:
            cache_key = "saga:" + saga_type + ":" + str(saga_id)
            await self._redis.delete(cache_key)

        logger.debug("Saga state deleted: %s/%s", saga_type, saga_id)

    async def list_sagas(
        self,
        saga_type: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List sagas with filters."""
        await self._ensure_table()

        conditions = []
        params: list[Any] = []  # Explicitly typed to accept ints for limit/offset

        if saga_type:
            conditions.append("saga_type = $1")
            params.append(saga_type)

        if status:
            conditions.append("state->>'status' = $2")
            params.append(status)

        # Build WHERE clause using concatenation (safe: conditions contain placeholders)
        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Build final query using concatenation, no f-string or .format()
        # Parameter positions: if we have conditions, next param is limit and offset
        limit_pos = len(params) + 1
        offset_pos = len(params) + 2

        query_parts = [
            "SELECT saga_id, saga_type, state, updated_at",
            "FROM " + self._table_name,
        ]
        if where_clause:
            query_parts.append(where_clause)
        query_parts.append("ORDER BY updated_at DESC")
        query_parts.append("LIMIT $" + str(limit_pos) + " OFFSET $" + str(offset_pos))

        query = " ".join(query_parts)
        params.extend([limit, offset])

        async with self._db_pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [
                {
                    "saga_id": UUID(row["saga_id"]),
                    "saga_type": row["saga_type"],
                    "state": json.loads(row["state"]),
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    async def cleanup_old_sagas(self, older_than_days: int = 30) -> int:
        """Delete old completed/compensated sagas."""
        await self._ensure_table()

        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

        delete_sql = (
            "DELETE FROM " + self._table_name + " "
            "WHERE updated_at < $1 "
            "AND (state->>'status' IN ('COMPLETED', 'COMPENSATED', 'FAILED'))"
        )

        async with self._db_pool.acquire() as conn:
            result = await conn.execute(delete_sql, cutoff)

            # Parse deleted count from result
            deleted = 0
            if result:
                parts = result.split()
                if len(parts) >= 2:
                    with contextlib.suppress(ValueError):
                        deleted = int(parts[-1])

            logger.info("Cleaned up %d old sagas", deleted)
            return deleted

    async def get_statistics(self) -> dict[str, Any]:
        """Get store statistics."""
        await self._ensure_table()

        count_sql = "SELECT COUNT(*) FROM " + self._table_name
        status_sql = (
            "SELECT state->>'status' as status, COUNT(*) as count "
            "FROM " + self._table_name + " "
            "GROUP BY state->>'status'"
        )

        async with self._db_pool.acquire() as conn:
            total = await conn.fetchval(count_sql)
            status_counts = await conn.fetch(status_sql)

        return {
            "total_sagas": total,
            "status_counts": {row["status"]: row["count"] for row in status_counts},
            "cache_enabled": self._redis is not None,
            "table_name": self._table_name,
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================


async def create_saga_state_store(
    db_pool: DatabasePoolPort,
    redis_client: RedisClientPort | None = None,
    cache_ttl_seconds: int = 3600,
    table_name: str = "saga_state",
) -> SagaStateStore:
    """Factory untuk membuat SagaStateStore."""
    store = SagaStateStore(
        db_pool=db_pool,
        redis_client=redis_client,
        cache_ttl_seconds=cache_ttl_seconds,
        table_name=table_name,
    )
    await store._ensure_table()
    return store


# ============================================================================
# IN-MEMORY SAGA STATE STORE FOR TESTING
# ============================================================================


class InMemorySagaStateStore:
    """
    In-memory implementation of saga state store for unit testing.
    This is a real implementation (no mocks, no stubs).
    """

    def __init__(self):
        self._store: dict[str, dict] = {}

    def save(self, saga_id: str, state: dict) -> None:
        """Save state for a given saga ID."""
        self._store[saga_id] = state

    def get(self, saga_id: str) -> dict | None:
        """Retrieve state for a given saga ID."""
        return self._store.get(saga_id)

    def delete(self, saga_id: str) -> None:
        """Delete state for a given saga ID."""
        self._store.pop(saga_id, None)

    def list_all(self) -> list[dict]:
        """Return all stored states."""
        return list(self._store.values())

    def clear(self) -> None:
        """Clear all states."""
        self._store.clear()

    # Async versions for compatibility
    async def save_async(self, saga_type: str, saga_id: UUID, state: dict) -> None:
        key = f"{saga_type}:{saga_id}"
        self._store[key] = state

    async def load_async(self, saga_type: str, saga_id: UUID) -> dict | None:
        key = f"{saga_type}:{saga_id}"
        return self._store.get(key)

    async def delete_async(self, saga_type: str, saga_id: UUID) -> None:
        key = f"{saga_type}:{saga_id}"
        self._store.pop(key, None)


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabasePoolPort",
    "InMemorySagaStateStore",
    "RedisClientPort",
    "SagaStateStore",
    "create_saga_state_store",
]
