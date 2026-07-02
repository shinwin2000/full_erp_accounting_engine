#!/usr/bin/env python3
"""
Module: append_only_store.py
Layer: Infrastructure (Event Store)
Responsibility: Implementasi immutable append-only store untuk event sourcing.
               Tidak mengimpor tamper_detection_scanner.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, desc, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.session_factory_sqlalchemy import get_async_session_factory
from infrastructure.event_store.hash_chain_builder import HashChainBuilder
from infrastructure.persistence_orm.event_store_table import EventStoreTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

GENESIS_HASH = hashlib.sha256(b"EVENT_STORE_GENESIS_2025").hexdigest()
EVENT_TYPE_DOMAIN = "domain"
EVENT_TYPE_INTEGRATION = "integration"
EVENT_TYPE_AUDIT = "audit"
EVENT_TYPE_SYSTEM = "system"


class AppendOnlyStoreError(Exception):
    pass


class EventNotFoundError(AppendOnlyStoreError):
    pass


class IntegrityViolationError(AppendOnlyStoreError):
    pass


class StoreNotInitializedError(AppendOnlyStoreError):
    pass


class AppendOnlyStore:
    def __init__(self, session_factory: async_sessionmaker | None = None):
        # CATATAN: get_async_session_factory() adalah fungsi async, jadi
        # tidak bisa dipanggil (dan di-await) di __init__ yang sinkron.
        # Kalau session_factory tidak diberikan, resolusinya ditunda
        # sampai initialize() (lihat di bawah), supaya bisa di-await
        # dengan benar.
        self._session_factory = session_factory
        self._hash_builder = HashChainBuilder()
        self._initialized = False
        self._cache: dict[str, list[dict]] = {}
        self._last_hashes: dict[str, str] = {}

    async def initialize(self) -> None:
        try:
            if self._session_factory is None:
                self._session_factory = await get_async_session_factory()
            async with self._session_factory() as session:
                stmt = select(func.count()).select_from(EventStoreTable).limit(1)
                result = await session.execute(stmt)
                count = result.scalar()
                if count == 0:
                    genesis_event = {
                        "id": str(uuid4()),
                        "stream_name": "__system__",
                        "event_type": "system.genesis",
                        "event_version": 1,
                        "data": {"message": "Event Store Genesis"},
                        "event_metadata": {"created_by": "system"},
                        "timestamp": datetime.now(UTC),  # objek datetime asli, bukan string (kolom TIMESTAMPTZ)
                        "sequence_number": 1,
                        "previous_hash": GENESIS_HASH,
                        "hash": GENESIS_HASH,
                    }
                    # CATATAN: pakai EventStoreTable.__table__ (Core Table),
                    # bukan EventStoreTable (ORM class) langsung. Insert ORM
                    # mencoba meresolusi key dict ke atribut Python kelas,
                    # dan key 'metadata' di sini bentrok dengan atribut
                    # bawaan SQLAlchemy `Base.metadata` (objek MetaData),
                    # menyebabkan AttributeError saat insert genesis event.
                    stmt = insert(EventStoreTable.__table__).values(**genesis_event)
                    await session.execute(stmt)
                    await session.commit()
                    logger.info("Event store initialized with genesis record")
                self._initialized = True
                logger.info("AppendOnlyStore initialized")
        except Exception as e:
            logger.error(f"Failed to initialize event store: {e}")
            raise AppendOnlyStoreError(f"Initialization failed: {e}") from e

    async def append(
        self,
        stream_name: str,
        event_data: dict[str, Any],
        event_type: str = EVENT_TYPE_DOMAIN,
        metadata: dict[str, Any] | None = None,
    ) -> UUID:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        event_id = uuid4()
        timestamp = datetime.now(UTC)
        metadata = metadata or {}
        last_hash = await self._get_last_hash_for_stream(stream_name)
        event_record = {
            "id": str(event_id),
            "stream_name": stream_name,
            "event_type": event_type,
            "event_version": 1,
            "data": event_data,
            "event_metadata": metadata,
            "timestamp": timestamp,  # objek datetime asli, bukan string (kolom TIMESTAMPTZ)
            "sequence_number": await self._get_next_sequence(stream_name),
            "previous_hash": last_hash,
            "hash": self._compute_hash(event_data, metadata, timestamp, last_hash),
        }
        try:
            async with self._session_factory() as session, session.begin():
                stmt = insert(EventStoreTable.__table__).values(**event_record)
                await session.execute(stmt)
                await session.commit()
            if stream_name not in self._cache:
                self._cache[stream_name] = []
            self._cache[stream_name].append(event_record)
            if len(self._cache[stream_name]) > 100:
                self._cache[stream_name] = self._cache[stream_name][-100:]
            self._last_hashes[stream_name] = event_record["hash"]
            logger.debug(f"Event appended: {event_type} to {stream_name} (id={event_id})")
            return event_id
        except IntegrityError as e:
            logger.error(f"Integrity error while appending event: {e}")
            raise IntegrityViolationError(f"Duplicate sequence or constraint violation: {e}") from e
        except Exception as e:
            logger.error(f"Failed to append event: {e}")
            raise AppendOnlyStoreError(f"Failed to append event: {e}") from e

    async def append_batch(self, events: list[tuple[str, dict, str, dict | None]]) -> list[UUID]:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        event_ids = []
        try:
            async with self._session_factory() as session, session.begin():
                for stream_name, event_data, event_type, metadata in events:
                    event_id = uuid4()
                    timestamp = datetime.now(UTC)
                    metadata = metadata or {}
                    last_hash = await self._get_last_hash_for_stream(stream_name, session)
                    event_record = {
                        "id": str(event_id),
                        "stream_name": stream_name,
                        "event_type": event_type,
                        "event_version": 1,
                        "data": event_data,
                        "event_metadata": metadata,
                        "timestamp": timestamp,  # objek datetime asli, bukan string (kolom TIMESTAMPTZ)
                        "sequence_number": await self._get_next_sequence(stream_name, session),
                        "previous_hash": last_hash,
                        "hash": self._compute_hash(event_data, metadata, timestamp, last_hash),
                    }
                    stmt = insert(EventStoreTable.__table__).values(**event_record)
                    await session.execute(stmt)
                    event_ids.append(event_id)
                    if stream_name not in self._cache:
                        self._cache[stream_name] = []
                    self._cache[stream_name].append(event_record)
                    self._last_hashes[stream_name] = event_record["hash"]
                await session.commit()
            logger.info(f"Batch of {len(events)} events appended")
            return event_ids
        except IntegrityError as e:
            logger.error(f"Integrity error in batch append: {e}")
            raise IntegrityViolationError(f"Batch append failed: {e}") from e
        except Exception as e:
            logger.error(f"Failed to append batch: {e}")
            raise AppendOnlyStoreError(f"Batch append failed: {e}") from e

    async def read_stream(
        self, stream_name: str, from_sequence: int = 1, limit: int = 1000
    ) -> list[dict[str, Any]]:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        cached = self._cache.get(stream_name, [])
        if cached and from_sequence <= len(cached):
            return [e for e in cached if e.get("sequence_number", 0) >= from_sequence][:limit]
        try:
            async with self._session_factory() as session:
                stmt = (
                    select(EventStoreTable)
                    .where(
                        EventStoreTable.stream_name == stream_name,
                        EventStoreTable.sequence_number >= from_sequence,
                    )
                    .order_by(EventStoreTable.sequence_number)
                    .limit(limit)
                )
                result = await session.execute(stmt)
                events = result.scalars().all()
                return [
                    {
                        "id": e.id,
                        "stream_name": e.stream_name,
                        "event_type": e.event_type,
                        "event_version": e.event_version,
                        "data": e.data,
                        "metadata": e.event_metadata,
                        "timestamp": e.timestamp,
                        "sequence_number": e.sequence_number,
                        "previous_hash": e.previous_hash,
                        "hash": e.hash,
                    }
                    for e in events
                ]
        except Exception as e:
            logger.error(f"Failed to read stream {stream_name}: {e}")
            raise AppendOnlyStoreError(f"Failed to read stream: {e}") from e

    async def get_last_event(self, stream_name: str) -> dict[str, Any] | None:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        cached = self._cache.get(stream_name, [])
        if cached:
            return cached[-1]
        try:
            async with self._session_factory() as session:
                stmt = (
                    select(EventStoreTable)
                    .where(EventStoreTable.stream_name == stream_name)
                    .order_by(desc(EventStoreTable.sequence_number))
                    .limit(1)
                )
                result = await session.execute(stmt)
                event = result.scalar_one_or_none()
                if not event:
                    return None
                return {
                    "id": event.id,
                    "stream_name": event.stream_name,
                    "event_type": event.event_type,
                    "event_version": event.event_version,
                    "data": event.data,
                    "metadata": event.event_metadata,
                    "timestamp": event.timestamp,
                    "sequence_number": event.sequence_number,
                    "previous_hash": event.previous_hash,
                    "hash": event.hash,
                }
        except Exception as e:
            logger.error(f"Failed to get last event for {stream_name}: {e}")
            raise AppendOnlyStoreError(f"Failed to get last event: {e}") from e

    async def get_last_record(self, store_name: str) -> dict[str, Any] | None:
        return await self.get_last_event(store_name)

    async def verify_integrity(self, stream_name: str | None = None) -> dict[str, Any]:
        """Verifikasi integritas hash chain tanpa menggunakan scanner eksternal."""
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        try:
            async with self._session_factory() as session:
                if stream_name:
                    stmt = (
                        select(EventStoreTable)
                        .where(EventStoreTable.stream_name == stream_name)
                        .order_by(EventStoreTable.sequence_number)
                    )
                    result = await session.execute(stmt)
                    events = result.scalars().all()
                    event_dicts = [
                        {
                            "data": e.data,
                            "metadata": e.event_metadata,
                            "timestamp": e.timestamp,
                            "previous_hash": e.previous_hash,
                            "hash": e.hash,
                            "sequence_number": e.sequence_number,
                        }
                        for e in events
                    ]
                    is_valid, broken_at, error = await self._hash_builder.verify_chain(event_dicts)
                    return {
                        "stream_name": stream_name,
                        "is_valid": is_valid,
                        "events_checked": len(events),
                        "broken_at_sequence": broken_at if not is_valid else None,
                        "error": error if not is_valid else None,
                    }
                else:
                    stmt = select(EventStoreTable.stream_name).distinct()
                    result = await session.execute(stmt)
                    stream_names = result.scalars().all()
                    results = {}
                    total_valid = 0
                    total_invalid = 0
                    for name in stream_names:
                        stream_result = await self.verify_integrity(name)
                        results[name] = stream_result
                        if stream_result["is_valid"]:
                            total_valid += 1
                        else:
                            total_invalid += 1
                            await trigger_alert(
                                title="Hash Chain Integrity Violation",
                                message=f"Stream {name} has broken hash chain!",
                                severity="critical",
                                source="AppendOnlyStore",
                            )
                    return {
                        "all_streams": results,
                        "total_streams": len(stream_names),
                        "valid_streams": total_valid,
                        "invalid_streams": total_invalid,
                        "overall_valid": total_invalid == 0,
                    }
        except Exception as e:
            logger.error(f"Failed to verify integrity: {e}")
            raise AppendOnlyStoreError(f"Integrity verification failed: {e}") from e

    async def _get_last_hash_for_stream(
        self, stream_name: str, session: AsyncSession | None = None
    ) -> str:
        if stream_name in self._last_hashes:
            return self._last_hashes[stream_name]
        close_session = False
        if session is None:
            session = self._session_factory()
            close_session = True
        try:
            stmt = (
                select(EventStoreTable.hash)
                .where(EventStoreTable.stream_name == stream_name)
                .order_by(desc(EventStoreTable.sequence_number))
                .limit(1)
            )
            result = await session.execute(stmt)
            last_hash = result.scalar_one_or_none()
            if last_hash:
                self._last_hashes[stream_name] = last_hash
                return last_hash
            return GENESIS_HASH
        finally:
            if close_session:
                await session.close()

    async def _get_next_sequence(
        self, stream_name: str, session: AsyncSession | None = None
    ) -> int:
        close_session = False
        if session is None:
            session = self._session_factory()
            close_session = True
        try:
            stmt = select(func.max(EventStoreTable.sequence_number)).where(
                EventStoreTable.stream_name == stream_name
            )
            result = await session.execute(stmt)
            max_seq = result.scalar()
            return (max_seq or 0) + 1
        finally:
            if close_session:
                await session.close()

    def _compute_hash(
        self, data: dict, metadata: dict, timestamp: datetime, previous_hash: str
    ) -> str:
        content = {
            "data": data,
            "metadata": metadata,
            "timestamp": timestamp.isoformat(),
            "previous_hash": previous_hash,
        }
        json_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    async def get_stream_info(self, stream_name: str) -> dict[str, Any]:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        try:
            async with self._session_factory() as session:
                count_stmt = (
                    select(func.count())
                    .select_from(EventStoreTable)
                    .where(EventStoreTable.stream_name == stream_name)
                )
                count_result = await session.execute(count_stmt)
                event_count = count_result.scalar() or 0
                first_stmt = (
                    select(EventStoreTable)
                    .where(EventStoreTable.stream_name == stream_name)
                    .order_by(EventStoreTable.sequence_number)
                    .limit(1)
                )
                first_result = await session.execute(first_stmt)
                first_event = first_result.scalar_one_or_none()
                last_stmt = (
                    select(EventStoreTable)
                    .where(EventStoreTable.stream_name == stream_name)
                    .order_by(desc(EventStoreTable.sequence_number))
                    .limit(1)
                )
                last_result = await session.execute(last_stmt)
                last_event = last_result.scalar_one_or_none()
                return {
                    "stream_name": stream_name,
                    "event_count": event_count,
                    "first_sequence": first_event.sequence_number if first_event else None,
                    "last_sequence": last_event.sequence_number if last_event else None,
                    "first_timestamp": first_event.timestamp if first_event else None,
                    "last_timestamp": last_event.timestamp if last_event else None,
                    "last_hash": self._last_hashes.get(stream_name, GENESIS_HASH),
                }
        except Exception as e:
            logger.error(f"Failed to get stream info for {stream_name}: {e}")
            raise AppendOnlyStoreError(f"Failed to get stream info: {e}") from e

    async def search_events(
        self,
        event_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not self._initialized:
            raise StoreNotInitializedError("Event store not initialized.")
        try:
            async with self._session_factory() as session:
                conditions = []
                if event_type:
                    conditions.append(EventStoreTable.event_type == event_type)
                if start_time:
                    conditions.append(EventStoreTable.timestamp >= start_time.isoformat())
                if end_time:
                    conditions.append(EventStoreTable.timestamp <= end_time.isoformat())
                stmt = (
                    select(EventStoreTable)
                    .where(and_(*conditions) if conditions else True)
                    .order_by(desc(EventStoreTable.timestamp))
                    .limit(limit)
                )
                result = await session.execute(stmt)
                events = result.scalars().all()
                return [
                    {
                        "id": e.id,
                        "stream_name": e.stream_name,
                        "event_type": e.event_type,
                        "data": e.data,
                        "metadata": e.event_metadata,
                        "timestamp": e.timestamp,
                        "sequence_number": e.sequence_number,
                    }
                    for e in events
                ]
        except Exception as e:
            logger.error(f"Failed to search events: {e}")
            raise AppendOnlyStoreError(f"Failed to search events: {e}") from e


_event_store: AppendOnlyStore | None = None


async def get_event_store() -> AppendOnlyStore:
    global _event_store
    if _event_store is None:
        _event_store = AppendOnlyStore()
        await _event_store.initialize()
    return _event_store


async def get_audit_store() -> AppendOnlyStore:
    return await get_event_store()


AppendOnlyEventStore = AppendOnlyStore

__all__ = [
    "EVENT_TYPE_AUDIT",
    "EVENT_TYPE_DOMAIN",
    "EVENT_TYPE_INTEGRATION",
    "EVENT_TYPE_SYSTEM",
    "AppendOnlyEventStore",
    "AppendOnlyStore",
    "AppendOnlyStoreError",
    "EventNotFoundError",
    "IntegrityViolationError",
    "StoreNotInitializedError",
    "get_audit_store",
    "get_event_store",
]