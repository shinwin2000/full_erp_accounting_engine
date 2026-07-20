# ============================================================================
# infrastructure/event_store/snapshot_manager.py
# ============================================================================
"""
Module: snapshot_manager.py
Layer: Infrastructure (Event Store)
Responsibility: Manajemen snapshot untuk event sourcing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import zlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from infrastructure.database.session_factory_sqlalchemy import get_session_factory

logger = logging.getLogger(__name__)


class SnapshotManager:
    def __init__(self, event_store=None):
        self._event_store = event_store
        self._session_factory = None
        self._lock = asyncio.Lock()

    async def _get_session(self):
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _get_event_store(self):
        if self._event_store is None:
            # Impor lokal di dalam fungsi
            from infrastructure.event_store.append_only_store import get_event_store
            self._event_store = await get_event_store()
        return self._event_store

    async def _compress_state(self, state: dict[str, Any]) -> bytes:
        json_str = json.dumps(state, default=str, ensure_ascii=False)
        return zlib.compress(json_str.encode("utf-8"))

    async def _decompress_state(self, compressed: bytes) -> dict[str, Any]:
        json_str = zlib.decompress(compressed).decode("utf-8")
        return json.loads(json_str)

    async def create_snapshot(
        self,
        aggregate_id: str,
        aggregate_type: str,
        version: int,
        state: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        snapshot_id = uuid4()
        created_at = datetime.now(UTC)
        compressed_state = await self._compress_state(state)
        if metadata is None:
            metadata = {}
        metadata["aggregate_type"] = aggregate_type
        metadata["version"] = version
        metadata["created_at"] = created_at.isoformat()
        try:
            async with await self._get_session() as session, session.begin():
                await session.execute(
                    "DELETE FROM snapshot WHERE aggregate_id = $1 AND aggregate_type = $2 AND version <= $3",
                    aggregate_id,
                    aggregate_type,
                    version,
                )
                await session.execute(
                    """
                    INSERT INTO snapshot (id, aggregate_id, aggregate_type, version, state, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    snapshot_id,
                    aggregate_id,
                    aggregate_type,
                    version,
                    compressed_state,
                    json.dumps(metadata, default=str),
                    created_at,
                )
                await session.commit()
            logger.info(
                f"Snapshot created: {aggregate_type}/{aggregate_id} v{version} (id={snapshot_id})"
            )
            return snapshot_id
        except Exception as e:
            logger.error(f"Failed to create snapshot for {aggregate_type}/{aggregate_id}: {e}")
            raise

    async def get_latest_snapshot(
        self, aggregate_id: str, aggregate_type: str, max_version: int | None = None
    ) -> dict[str, Any] | None:
        try:
            async with await self._get_session() as session:
                query = """
                    SELECT id, aggregate_id, aggregate_type, version, state, metadata, created_at
                    FROM snapshot
                    WHERE aggregate_id = $1 AND aggregate_type = $2
                """
                params = [aggregate_id, aggregate_type]
                if max_version is not None:
                    query += " AND version <= $3"
                    params.append(max_version)
                query += " ORDER BY version DESC LIMIT 1"
                row = await session.fetchrow(query, *params)
                if not row:
                    return None
                state = await self._decompress_state(row["state"])
                metadata = json.loads(row["metadata"]) if row["metadata"] else {}
                return {
                    "id": row["id"],
                    "aggregate_id": row["aggregate_id"],
                    "aggregate_type": row["aggregate_type"],
                    "version": row["version"],
                    "state": state,
                    "metadata": metadata,
                    "created_at": row["created_at"],
                }
        except Exception as e:
            logger.error(f"Failed to get snapshot for {aggregate_type}/{aggregate_id}: {e}")
            return None

    async def delete_old_snapshots(self, aggregate_type: str, keep_count: int = 5) -> int:
        try:
            async with await self._get_session() as session, session.begin():
                select_ids_sql = """
                    SELECT id FROM snapshot
                    WHERE aggregate_type = $1
                    ORDER BY version DESC
                    OFFSET $2
                    FOR UPDATE
                """
                rows = await session.fetch(select_ids_sql, aggregate_type, keep_count)
                ids_to_delete = [row["id"] for row in rows]
                if not ids_to_delete:
                    return 0
                delete_sql = "DELETE FROM snapshot WHERE id = ANY($1)"
                result = await session.execute(delete_sql, ids_to_delete)
                deleted = result.rowcount
                await session.commit()
                logger.info(f"Deleted {deleted} old snapshots for type {aggregate_type}")
                return deleted
        except Exception as e:
            logger.error(f"Failed to prune snapshots for {aggregate_type}: {e}")
            return 0

    async def create_table_if_not_exists(self) -> None:
        try:
            async with await self._get_session() as session:
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS snapshot (
                        id UUID PRIMARY KEY,
                        aggregate_id VARCHAR(255) NOT NULL,
                        aggregate_type VARCHAR(100) NOT NULL,
                        version INTEGER NOT NULL,
                        state BYTEA NOT NULL,
                        metadata JSONB,
                        created_at TIMESTAMP WITH TIME ZONE NOT NULL
                    )
                """))
                await session.execute(text("""
                    CREATE INDEX IF NOT EXISTS idx_snapshot_agg
                    ON snapshot (aggregate_id, aggregate_type, version)
                """))
                await session.commit()
                logger.info("Snapshot table created/verified")
        except Exception as e:
            logger.warning(f"Could not create snapshot table (maybe already exists): {e}")
