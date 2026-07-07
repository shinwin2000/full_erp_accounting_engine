# infrastructure/event_store/snapshot_manager.py
"""
Module: snapshot_manager.py
Layer: Infrastructure (Event Store)
Responsibility: Manajemen snapshot untuk event sourcing. Membuat dan memuat snapshot
               dari aggregate untuk mempercepat recovery tanpa harus memutar semua event.
Dependencies:
- asyncio, datetime, json, pickle (opsional), zlib
- infrastructure.database.session_factory_sqlalchemy
- infrastructure.event_store.append_only_store (untuk membaca event terbaru)
Audit: Setiap pembuatan snapshot dicatat.
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
from infrastructure.event_store.append_only_store import AppendOnlyStore

logger = logging.getLogger(__name__)


class SnapshotManager:
    """
    Manajer snapshot untuk event sourcing.

    Fitur:
    - Membuat snapshot dari state aggregate pada version tertentu
    - Menyimpan snapshot ke database (PostgreSQL) dengan kompresi
    - Memuat snapshot terbaru untuk aggregate
    - Mendukung versioning dan pruning snapshot lama
    """

    def __init__(self, event_store: AppendOnlyStore | None = None):
        self._event_store = event_store
        self._session_factory = None
        self._lock = asyncio.Lock()

    async def _get_session(self):
        if self._session_factory is None:
            self._session_factory = await get_session_factory()
        return self._session_factory.get_session()

    async def _compress_state(self, state: dict[str, Any]) -> bytes:
        """Kompres state menggunakan zlib untuk menghemat ruang."""
        json_str = json.dumps(state, default=str, ensure_ascii=False)
        return zlib.compress(json_str.encode("utf-8"))

    async def _decompress_state(self, compressed: bytes) -> dict[str, Any]:
        """Dekompres state."""
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
        """
        Membuat snapshot untuk aggregate.

        Args:
            aggregate_id: ID aggregate (string)
            aggregate_type: Tipe aggregate (misal "JournalAggregate")
            version: Version aggregate saat snapshot
            state: State aggregate yang akan disimpan
            metadata: Metadata tambahan (opsional)

        Returns:
            UUID snapshot yang dibuat
        """
        snapshot_id = uuid4()
        created_at = datetime.now(UTC)

        # Kompres state
        compressed_state = await self._compress_state(state)

        # Metadata default
        if metadata is None:
            metadata = {}
        metadata["aggregate_type"] = aggregate_type
        metadata["version"] = version
        metadata["created_at"] = created_at.isoformat()

        # Simpan ke database
        try:
            async with await self._get_session() as session, session.begin():
                # Hapus snapshot yang lebih lama jika sudah ada (optional: keep last N)
                await session.execute(
                    "DELETE FROM snapshot WHERE aggregate_id = $1 AND aggregate_type = $2 AND version <= $3",
                    aggregate_id,
                    aggregate_type,
                    version,
                )

                # Insert snapshot baru
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
        """
        Mendapatkan snapshot terbaru untuk aggregate.

        Args:
            aggregate_id: ID aggregate
            aggregate_type: Tipe aggregate
            max_version: Batas maksimum version (opsional)

        Returns:
            Dictionary dengan snapshot info atau None jika tidak ada
        """
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
        """
        Menghapus snapshot lama, hanya menyisakan keep_count terbaru per aggregate.

        Args:
            aggregate_type: Tipe aggregate
            keep_count: Jumlah snapshot terbaru yang disimpan

        Returns:
            Jumlah snapshot yang dihapus
        """
        try:
            async with await self._get_session() as session, session.begin():
                # Subquery untuk mendapatkan snapshot yang akan dihapus
                result = await session.execute(
                    """
                    DELETE FROM snapshot
                    WHERE (aggregate_id, aggregate_type, version) IN (
                        SELECT aggregate_id, aggregate_type, version
                        FROM snapshot
                        WHERE aggregate_type = $1
                        ORDER BY version DESC
                        OFFSET $2
                    )
                    """,
                    aggregate_type,
                    keep_count,
                )
                deleted = result.rowcount
                await session.commit()
                logger.info(f"Deleted {deleted} old snapshots for type {aggregate_type}")
                return deleted

        except Exception as e:
            logger.error(f"Failed to prune snapshots for {aggregate_type}: {e}")
            return 0

    async def create_table_if_not_exists(self) -> None:
        """Membuat tabel snapshot jika belum ada."""
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