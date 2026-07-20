#!/usr/bin/env python3
"""
Module: snapshot_store_aggregate.py
Layer: Infrastructure (Event Store)
Responsibility: Menyediakan penyimpanan snapshot untuk aggregate dalam event sourcing.
               Snapshot digunakan untuk mempercepat rekonstruksi aggregate dengan
               menyimpan state lengkap aggregate pada interval tertentu.
"""

from __future__ import annotations

import json
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import desc, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Internal dependencies
from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory
from infrastructure.event_store.snapshot_compression_service import SnapshotCompressionService
from infrastructure.telemetry.structured_json_logging import get_logger

# Optional security
try:
    from infrastructure.security.field_encryption_aes256_gcm import FieldEncryption
    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

DEFAULT_SNAPSHOT_INTERVAL = 100
DEFAULT_MAX_SNAPSHOTS_PER_AGGREGATE = 5
DEFAULT_COMPRESSION_LEVEL = 6
DEFAULT_SNAPSHOT_TTL_DAYS = 30

SNAPSHOT_STATUS_ACTIVE = "active"
SNAPSHOT_STATUS_ARCHIVED = "archived"
SNAPSHOT_STATUS_DELETED = "deleted"


# ============================================================================
# EXCEPTIONS
# ============================================================================

class SnapshotStoreError(Exception):
    pass


class SnapshotNotFoundError(SnapshotStoreError):
    pass


class SnapshotCorruptedError(SnapshotStoreError):
    pass


class OptimisticLockError(SnapshotStoreError):
    pass


# ============================================================================
# SNAPSHOT STORE AGGREGATE
# ============================================================================

class SnapshotStoreAggregate:
    def __init__(self, session_factory: async_sessionmaker | None = None):
        self._session_factory = session_factory or get_async_session_factory()
        self._compression_service = SnapshotCompressionService(level=DEFAULT_COMPRESSION_LEVEL)
        self._encryption = FieldEncryption() if ENCRYPTION_AVAILABLE else None
        self._cache: dict[str, dict] = {}  # in-memory cache

    async def _get_snapshot_table(self):
        """Lazy import of ORM model to avoid circular dependency."""
        from infrastructure.persistence_orm.snapshot_store_table import SnapshotStoreTable
        return SnapshotStoreTable

    async def save_snapshot(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        state: dict[str, Any],
        version: int,
        metadata: dict[str, Any] | None = None,
        encrypt: bool = False,
    ) -> UUID:
        snapshot_id = uuid4()
        timestamp = datetime.now(UTC)
        metadata = metadata or {}

        state_json = json.dumps(state, default=str)
        compressed = self._compression_service.compress(state_json.encode("utf-8"))

        if encrypt and self._encryption:
            encrypted = self._encryption.encrypt(compressed)
            stored_data = encrypted
            is_encrypted = True
        else:
            stored_data = compressed
            is_encrypted = False

        try:
            async with self._session_factory() as session, session.begin():
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt = insert(SnapshotStoreTable).values(
                    id=snapshot_id,
                    aggregate_id=aggregate_id,
                    aggregate_type=aggregate_type,
                    snapshot_version=version,
                    snapshot_data=stored_data,
                    data_format="json+zlib",
                    is_encrypted=is_encrypted,
                    metadata=metadata,
                    taken_at=timestamp,
                    version=1,
                    status=SNAPSHOT_STATUS_ACTIVE,
                )
                await session.execute(stmt)

                await self._cleanup_old_snapshots(aggregate_id, aggregate_type, session)

                await session.commit()

            cache_key = f"{aggregate_type}:{aggregate_id}"
            self._cache[cache_key] = {
                "snapshot_id": snapshot_id,
                "version": version,
                "state": state,
                "taken_at": timestamp,
            }

            logger.debug(f"Snapshot saved for {aggregate_type}/{aggregate_id} at version {version}")
            return snapshot_id

        except Exception as e:
            logger.error(f"Failed to save snapshot for {aggregate_type}/{aggregate_id}: {e}")
            raise SnapshotStoreError(f"Failed to save snapshot: {e}") from e

    async def load_snapshot(
        self, aggregate_id: UUID, aggregate_type: str, decrypt: bool = True
    ) -> tuple[dict[str, Any], int, datetime] | None:
        cache_key = f"{aggregate_type}:{aggregate_id}"
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return cached["state"], cached["version"], cached["taken_at"]

        try:
            async with self._session_factory() as session:
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt = (
                    select(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.aggregate_id == aggregate_id,
                        SnapshotStoreTable.aggregate_type == aggregate_type,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                    )
                    .order_by(desc(SnapshotStoreTable.snapshot_version))
                    .limit(1)
                )

                result = await session.execute(stmt)
                snapshot = result.scalar_one_or_none()

                if not snapshot:
                    return None

                stored_data = snapshot.snapshot_data

                if snapshot.is_encrypted and decrypt and self._encryption:
                    stored_data = self._encryption.decrypt(stored_data)

                try:
                    decompressed = self._compression_service.decompress(stored_data)
                    state = json.loads(decompressed.decode("utf-8"))
                except (zlib.error, json.JSONDecodeError) as e:
                    raise SnapshotCorruptedError(f"Failed to decompress/parse snapshot: {e}")

                self._cache[cache_key] = {
                    "snapshot_id": snapshot.id,
                    "version": snapshot.snapshot_version,
                    "state": state,
                    "taken_at": snapshot.taken_at,
                }

                logger.debug(
                    f"Snapshot loaded for {aggregate_type}/{aggregate_id} at version {snapshot.snapshot_version}"
                )
                return state, snapshot.snapshot_version, snapshot.taken_at

        except SnapshotCorruptedError:
            raise
        except Exception as e:
            logger.error(f"Failed to load snapshot for {aggregate_type}/{aggregate_id}: {e}")
            raise SnapshotStoreError(f"Failed to load snapshot: {e}") from e

    async def load_snapshot_at_version(
        self, aggregate_id: UUID, aggregate_type: str, version: int, decrypt: bool = True
    ) -> tuple[dict[str, Any], int, datetime] | None:
        try:
            async with self._session_factory() as session:
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt = (
                    select(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.aggregate_id == aggregate_id,
                        SnapshotStoreTable.aggregate_type == aggregate_type,
                        SnapshotStoreTable.snapshot_version <= version,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                    )
                    .order_by(desc(SnapshotStoreTable.snapshot_version))
                    .limit(1)
                )

                result = await session.execute(stmt)
                snapshot = result.scalar_one_or_none()

                if not snapshot:
                    return None

                stored_data = snapshot.snapshot_data
                if snapshot.is_encrypted and decrypt and self._encryption:
                    stored_data = self._encryption.decrypt(stored_data)

                decompressed = self._compression_service.decompress(stored_data)
                state = json.loads(decompressed.decode("utf-8"))

                return state, snapshot.snapshot_version, snapshot.taken_at

        except Exception as e:
            logger.error(f"Failed to load snapshot at version {version}: {e}")
            raise SnapshotStoreError(f"Failed to load snapshot: {e}") from e

    async def delete_snapshot(self, snapshot_id: UUID) -> bool:
        try:
            async with self._session_factory() as session, session.begin():
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt_lock = (
                    select(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.id == snapshot_id,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                    )
                    .with_for_update()
                )
                result = await session.execute(stmt_lock)
                snapshot = result.scalar_one_or_none()
                if not snapshot:
                    return False

                current_version = snapshot.version
                new_version = current_version + 1

                update_stmt = (
                    update(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.id == snapshot_id,
                        SnapshotStoreTable.version == current_version,
                    )
                    .values(
                        status=SNAPSHOT_STATUS_DELETED,
                        deleted_at=datetime.now(UTC),
                        version=new_version,
                    )
                )
                update_result = await session.execute(update_stmt)

                if update_result.rowcount == 0:
                    raise OptimisticLockError(
                        f"Snapshot {snapshot_id} was modified concurrently (version mismatch)"
                    )

                await session.commit()

                for key, val in list(self._cache.items()):
                    if val.get("snapshot_id") == snapshot_id:
                        del self._cache[key]
                        break

                logger.info(f"Snapshot {snapshot_id} deleted")
                return True

        except OptimisticLockError:
            raise
        except Exception as e:
            logger.error(f"Failed to delete snapshot {snapshot_id}: {e}")
            raise SnapshotStoreError(f"Failed to delete snapshot: {e}") from e

    async def get_snapshots_for_aggregate(
        self, aggregate_id: UUID, aggregate_type: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        try:
            async with self._session_factory() as session:
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt = (
                    select(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.aggregate_id == aggregate_id,
                        SnapshotStoreTable.aggregate_type == aggregate_type,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                    )
                    .order_by(desc(SnapshotStoreTable.snapshot_version))
                    .limit(limit)
                )

                result = await session.execute(stmt)
                snapshots = result.scalars().all()

                return [
                    {
                        "id": s.id,
                        "aggregate_id": s.aggregate_id,
                        "aggregate_type": s.aggregate_type,
                        "snapshot_version": s.snapshot_version,
                        "taken_at": s.taken_at,
                        "is_encrypted": s.is_encrypted,
                        "metadata": s.metadata,
                    }
                    for s in snapshots
                ]

        except Exception as e:
            logger.error(f"Failed to list snapshots for {aggregate_type}/{aggregate_id}: {e}")
            raise SnapshotStoreError(f"Failed to list snapshots: {e}") from e

    async def _cleanup_old_snapshots(
        self, aggregate_id: UUID, aggregate_type: str, session: AsyncSession
    ) -> None:
        try:
            SnapshotStoreTable = await self._get_snapshot_table()
            stmt = (
                select(SnapshotStoreTable.id)
                .where(
                    SnapshotStoreTable.aggregate_id == aggregate_id,
                    SnapshotStoreTable.aggregate_type == aggregate_type,
                    SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                )
                .order_by(desc(SnapshotStoreTable.snapshot_version))
                .limit(DEFAULT_MAX_SNAPSHOTS_PER_AGGREGATE)
            )

            result = await session.execute(stmt)
            keep_ids = [row[0] for row in result.all()]

            if keep_ids:
                archive_stmt = (
                    update(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.aggregate_id == aggregate_id,
                        SnapshotStoreTable.aggregate_type == aggregate_type,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                        SnapshotStoreTable.id.not_in(keep_ids),
                    )
                    .values(status=SNAPSHOT_STATUS_ARCHIVED, archived_at=datetime.now(UTC))
                )
                await session.execute(archive_stmt)

        except Exception as e:
            logger.warning(f"Failed to cleanup old snapshots: {e}")

    async def cleanup_expired_snapshots(
        self, older_than_days: int = DEFAULT_SNAPSHOT_TTL_DAYS
    ) -> int:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)

        try:
            async with self._session_factory() as session, session.begin():
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt_select = (
                    select(SnapshotStoreTable)
                    .where(
                        SnapshotStoreTable.taken_at < cutoff,
                        SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                    )
                    .with_for_update()
                )
                result = await session.execute(stmt_select)
                snapshots = result.scalars().all()

                if not snapshots:
                    return 0

                updated_count = 0
                for snapshot in snapshots:
                    current_version = snapshot.version
                    new_version = current_version + 1
                    update_stmt = (
                        update(SnapshotStoreTable)
                        .where(
                            SnapshotStoreTable.id == snapshot.id,
                            SnapshotStoreTable.version == current_version,
                        )
                        .values(
                            status=SNAPSHOT_STATUS_DELETED,
                            deleted_at=datetime.now(UTC),
                            version=new_version,
                        )
                    )
                    update_result = await session.execute(update_stmt)
                    if update_result.rowcount > 0:
                        updated_count += 1

                await session.commit()
                logger.info(
                    f"Cleaned up {updated_count} expired snapshots older than {older_than_days} days"
                )
                return updated_count

        except Exception as e:
            logger.error(f"Failed to cleanup expired snapshots: {e}")
            raise SnapshotStoreError(f"Cleanup failed: {e}") from e

    async def should_take_snapshot(
        self,
        aggregate_id: UUID,
        aggregate_type: str,
        current_version: int,
        interval: int = DEFAULT_SNAPSHOT_INTERVAL,
    ) -> bool:
        try:
            async with self._session_factory() as session:
                SnapshotStoreTable = await self._get_snapshot_table()
                stmt = select(func.max(SnapshotStoreTable.snapshot_version)).where(
                    SnapshotStoreTable.aggregate_id == aggregate_id,
                    SnapshotStoreTable.aggregate_type == aggregate_type,
                    SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE,
                )
                result = await session.execute(stmt)
                last_version = result.scalar() or 0

                return (current_version - last_version) >= interval

        except Exception as e:
            logger.error(f"Failed to check snapshot need: {e}")
            return True

    async def invalidate_cache(self, aggregate_id: UUID, aggregate_type: str) -> None:
        cache_key = f"{aggregate_type}:{aggregate_id}"
        if cache_key in self._cache:
            del self._cache[cache_key]
            logger.debug(f"Cache invalidated for {aggregate_type}/{aggregate_id}")

    async def clear_cache(self) -> None:
        self._cache.clear()
        logger.info("Snapshot cache cleared")

    async def get_stats(self) -> dict[str, Any]:
        try:
            async with self._session_factory() as session:
                SnapshotStoreTable = await self._get_snapshot_table()
                count_stmt = (
                    select(func.count())
                    .select_from(SnapshotStoreTable)
                    .where(SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE)
                )
                count_result = await session.execute(count_stmt)
                total_count = count_result.scalar() or 0

                distinct_stmt = (
                    select(
                        func.count(
                            func.distinct(
                                SnapshotStoreTable.aggregate_id, SnapshotStoreTable.aggregate_type
                            )
                        )
                    )
                    .select_from(SnapshotStoreTable)
                    .where(SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE)
                )
                distinct_result = await session.execute(distinct_stmt)
                distinct_aggregates = distinct_result.scalar() or 0

                age_stmt = select(
                    func.avg(func.extract("epoch", datetime.now(UTC) - SnapshotStoreTable.taken_at))
                ).where(SnapshotStoreTable.status == SNAPSHOT_STATUS_ACTIVE)
                age_result = await session.execute(age_stmt)
                avg_age_seconds = age_result.scalar() or 0

                return {
                    "total_snapshots": total_count,
                    "distinct_aggregates": distinct_aggregates,
                    "average_age_seconds": float(avg_age_seconds),
                    "cache_size": len(self._cache),
                    "compression_enabled": True,
                    "encryption_available": ENCRYPTION_AVAILABLE,
                }

        except Exception as e:
            logger.error(f"Failed to get snapshot stats: {e}")
            return {"error": str(e)}


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_snapshot_store: SnapshotStoreAggregate | None = None

async def get_snapshot_store() -> SnapshotStoreAggregate:
    global _snapshot_store
    if _snapshot_store is None:
        _snapshot_store = SnapshotStoreAggregate()
    return _snapshot_store

__all__ = [
    "DEFAULT_MAX_SNAPSHOTS_PER_AGGREGATE",
    "DEFAULT_SNAPSHOT_INTERVAL",
    "OptimisticLockError",
    "SnapshotCorruptedError",
    "SnapshotNotFoundError",
    "SnapshotStoreAggregate",
    "SnapshotStoreError",
    "get_snapshot_store",
]
