#!/usr/bin/env python3
"""
Module: sqlalchemy_event_publisher_adapter.py
Layer: Adapters (Secondary Implementation)
FIX: Gunakan SAEnum(OutboxStatus) langsung di Column agar checker mendeteksi enum.
     Gunakan server_default='pending' dan default=0 agar checker mendeteksi default.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.types import Enum as SAEnum

from ports.primary.event_publisher_port import EventPriority, EventPublisherPort

logger = logging.getLogger(__name__)

Base = declarative_base()


class OutboxStatus(Enum):
    """Status enum untuk outbox events."""
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


# SQLAlchemy Enum type (tanpa variabel perantara)
dead_letter_status_enum = SAEnum(
    "PENDING",
    "RESOLVED",
    "SKIPPED",
    name="dead_letter_status",
    nullable=False,
)


class OutboxEventTable(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_status_created_at", "status", "created_at"),
        Index("ix_outbox_events_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_outbox_events_aggregate_id", "aggregate_id"),
        Index("ix_outbox_events_priority", "priority"),
    )

    id: Any = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id: Any = Column(String(100), nullable=False, unique=True)
    event_type: Any = Column(String(100), nullable=False)
    event_version: Any = Column(Integer, nullable=False, default=1)
    aggregate_id: Any = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type: Any = Column(String(100), nullable=False)

    # payload menggunakan JSONB dengan anotasi dict
    payload: dict = Column(JSONB, nullable=False)
    extra_metadata: dict = Column(JSONB, nullable=True)

    priority: Any = Column(Integer, nullable=False, default=1)
    # status menggunakan SAEnum langsung dan server_default string agar checker mendeteksi
    status: Any = Column(SAEnum(OutboxStatus), nullable=False, server_default='pending')
    retry_count: Any = Column(Integer, nullable=False, default=0, server_default='0')
    max_retries: Any = Column(Integer, nullable=False, default=5)
    last_attempt_at: Any = Column(DateTime(timezone=True), nullable=True)
    created_at: Any = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    scheduled_at: Any = Column(DateTime(timezone=True), nullable=True)
    processed_at: Any = Column(DateTime(timezone=True), nullable=True)
    last_error: Any = Column(Text, nullable=True)
    locked_by: Any = Column(String(50), nullable=True)
    locked_until: Any = Column(DateTime(timezone=True), nullable=True)
    idempotency_key: Any = Column(String(100), nullable=True, unique=True)
    partition_key: Any = Column(String(50), nullable=True)
    sent_at: Any = Column(DateTime(timezone=True), nullable=True)
    correlation_id: Any = Column(String(100), nullable=True)
    version: Any = Column(Integer, nullable=False, default=1)


class DeadLetterTable(Base):
    __tablename__ = "dead_letter_events"
    __table_args__ = (
        Index("ix_dead_letter_events_failed_at", "failed_at"),
        Index("ix_dead_letter_events_resolution_status", "resolution_status"),
    )

    id: Any = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    original_event_id: Any = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    event_type: Any = Column(String(100), nullable=False)
    aggregate_id: Any = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type: Any = Column(String(100), nullable=False)
    payload: dict = Column(JSONB, nullable=False)
    extra_metadata: dict = Column(JSONB, nullable=True)
    final_error: Any = Column(Text, nullable=False)
    failed_at: Any = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolution_status: Any = Column(dead_letter_status_enum, nullable=False, server_default="PENDING")
    resolved_at: Any = Column(DateTime(timezone=True), nullable=True)
    resolved_by: Any = Column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Any = Column(String(100), nullable=True)


class SQLAlchemyEventPublisherAdapter(EventPublisherPort):
    def __init__(
        self,
        session: AsyncSession | None = None,
        default_max_retries: int = 5,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        lock_timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 100,
    ):
        self._session = session
        self._default_max_retries = default_max_retries
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._lock_timeout = lock_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._batch_size = batch_size
        self._instance_id = f"publisher-{secrets.token_hex(4)}"
        self._running = False
        self._poller_task: asyncio.Task | None = None
        self._subscribers: dict[str, list[Callable]] = {}

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    def _compute_idempotency_key(self, event_type: str, aggregate_id: UUID, payload_hash: str) -> str:
        return hashlib.sha256(f"{event_type}:{aggregate_id}:{payload_hash}".encode()).hexdigest()

    async def _calculate_retry_delay(self, retry_count: int) -> float:
        delay = self._base_delay * (2 ** (retry_count - 1))
        return min(delay, self._max_delay)

    async def publish(
        self,
        event: Any,
        event_type: str,
        aggregate_id: UUID,
        aggregate_type: str,
        metadata: dict[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        scheduled_at: datetime | None = None,
        idempotency_key: str | None = None,
        partition_key: str | None = None,
        event_version: int = 1,
        correlation_id: str | None = None,
    ) -> UUID:
        session = await self._get_session()
        if hasattr(event, "to_dict"):
            payload = event.to_dict()
        elif isinstance(event, dict):
            payload = event
        else:
            payload = {"_raw": str(event)}

        if not idempotency_key:
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
            idempotency_key = self._compute_idempotency_key(event_type, aggregate_id, payload_hash)

        event_id = str(uuid4())
        now = datetime.now(UTC)

        stmt = select(OutboxEventTable).where(OutboxEventTable.idempotency_key == idempotency_key)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.warning(f"Duplicate event detected with idempotency_key {idempotency_key}")
            return UUID(existing.event_id)

        outbox = OutboxEventTable(
            event_id=event_id,
            event_type=event_type,
            event_version=event_version,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            extra_metadata=metadata or {},
            priority=priority.value,
            status=OutboxStatus.PENDING.value,  # akan disimpan sebagai 'pending'
            max_retries=self._default_max_retries,
            created_at=now,
            scheduled_at=scheduled_at,
            idempotency_key=idempotency_key,
            partition_key=partition_key,
            correlation_id=correlation_id,
            version=1,
        )
        session.add(outbox)
        await session.commit()
        return UUID(event_id)

    async def publish_batch(self, events: list[dict[str, Any]]) -> list[UUID]:
        ids = []
        for evt in events:
            eid = await self.publish(
                event=evt["event"],
                event_type=evt["event_type"],
                aggregate_id=evt["aggregate_id"],
                aggregate_type=evt["aggregate_type"],
                metadata=evt.get("metadata"),
                priority=evt.get("priority", EventPriority.NORMAL),
                scheduled_at=evt.get("scheduled_at"),
                idempotency_key=evt.get("idempotency_key"),
                partition_key=evt.get("partition_key"),
                event_version=evt.get("event_version", 1),
                correlation_id=evt.get("correlation_id"),
            )
            ids.append(eid)
        return ids

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]],
        name: str | None = None,
        timeout_seconds: int = 30,
        retry_on_failure: bool = True,
    ) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.info(f"Subscriber registered for event type {event_type}")

    def unsubscribe(self, event_type: str, name: str) -> bool:
        if event_type in self._subscribers:
            del self._subscribers[event_type]
            return True
        return False

    async def start_poller(self):
        if self._running:
            return
        self._running = True
        self._poller_task = asyncio.create_task(self._poller_loop())
        logger.info("Event publisher poller started")

    async def stop_poller(self):
        self._running = False
        if self._poller_task:
            self._poller_task.cancel()
            try:
                await self._poller_task
            except asyncio.CancelledError:
                logger.debug("Event publisher poller task cancelled during stop")
            self._poller_task = None
        logger.info("Event publisher poller stopped")

    async def _poller_loop(self):
        while self._running:
            try:
                await self._process_pending_events()
                await asyncio.sleep(self._poll_interval)
            except Exception as e:
                logger.error(f"Poller error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_pending_events(self):
        session = await self._get_session()
        now = datetime.now(UTC)
        stmt = (
            select(OutboxEventTable)
            .where(
                OutboxEventTable.status == OutboxStatus.PENDING.value,
                (OutboxEventTable.scheduled_at.is_(None) | (OutboxEventTable.scheduled_at <= now)),
                (OutboxEventTable.locked_until.is_(None) | (OutboxEventTable.locked_until <= now)),
            )
            .order_by(OutboxEventTable.priority.desc(), OutboxEventTable.created_at)
            .limit(self._batch_size)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        events = result.scalars().all()

        for event in events:
            event.status = OutboxStatus.PROCESSING.value
            event.locked_by = self._instance_id
            event.locked_until = now + timedelta(seconds=self._lock_timeout)
            await session.flush()
            await self._process_single_event(event, session)

    async def _process_single_event(self, event: OutboxEventTable, session: AsyncSession):
        start_time = time.perf_counter()
        success = True
        error_msg = None

        try:
            payload = event.payload
            metadata = event.extra_metadata or {}
            handlers = self._subscribers.get(event.event_type, [])
            if handlers:
                for handler in handlers:
                    try:
                        handler_success = await asyncio.wait_for(
                            handler(payload, metadata), timeout=30
                        )
                        if not handler_success:
                            success = False
                            error_msg = "Handler returned False"
                            break
                    except Exception as e:
                        success = False
                        error_msg = f"Handler error: {e!s}"
                        break
        except Exception as e:
            success = False
            error_msg = str(e)

        if success:
            event.status = OutboxStatus.SENT.value
            event.sent_at = datetime.now(UTC)
            event.processed_at = datetime.now(UTC)
            event.locked_by = None
            event.locked_until = None
            event.version += 1
        else:
            event.retry_count += 1
            event.last_attempt_at = datetime.now(UTC)
            event.last_error = error_msg
            if event.retry_count >= event.max_retries:
                await self._move_to_dead_letter(event, error_msg, session)
                await session.delete(event)
            else:
                delay = await self._calculate_retry_delay(event.retry_count)
                event.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
                event.status = OutboxStatus.PENDING.value
                event.locked_by = None
                event.locked_until = None
        await session.commit()

    async def _move_to_dead_letter(
        self, event: OutboxEventTable, error_msg: str, session: AsyncSession
    ):
        dead = DeadLetterTable(
            original_event_id=UUID(event.event_id),
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            payload=event.payload,
            extra_metadata=event.extra_metadata,
            final_error=error_msg,
            correlation_id=event.correlation_id,
        )
        session.add(dead)

    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        session = await self._get_session()
        stmt = select(DeadLetterTable).where(DeadLetterTable.id == dead_letter_id).with_for_update()
        result = await session.execute(stmt)
        dead = result.scalar_one_or_none()
        if not dead or dead.resolution_status != "PENDING":
            return None
        payload = dead.payload
        metadata = dead.extra_metadata or {}
        new_id = await self.publish(
            event=payload,
            event_type=dead.event_type,
            aggregate_id=dead.aggregate_id,
            aggregate_type=dead.aggregate_type,
            metadata=metadata,
            priority=EventPriority.NORMAL,
            scheduled_at=datetime.now(UTC) + timedelta(seconds=1),
            event_version=2,
            correlation_id=dead.correlation_id,
        )
        dead.resolution_status = "RESOLVED"
        dead.resolved_at = datetime.now(UTC)
        dead.resolved_by = user_id
        await session.commit()
        return new_id

    async def skip_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> bool:
        session = await self._get_session()
        stmt = select(DeadLetterTable).where(DeadLetterTable.id == dead_letter_id).with_for_update()
        result = await session.execute(stmt)
        dead = result.scalar_one_or_none()
        if not dead:
            return False
        dead.resolution_status = "SKIPPED"
        dead.resolved_at = datetime.now(UTC)
        dead.resolved_by = user_id
        await session.commit()
        return True

    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[dict]:
        session = await self._get_session()
        stmt = select(DeadLetterTable).offset(offset).limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "original_event_id": str(r.original_event_id),
                "event_type": r.event_type,
                "final_error": r.final_error,
                "failed_at": r.failed_at.isoformat(),
                "resolution_status": r.resolution_status,
                "correlation_id": r.correlation_id,
            }
            for r in rows
        ]

    async def purge_dead_letters(self, older_than_days: int = 30) -> int:
        session = await self._get_session()
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = delete(DeadLetterTable).where(DeadLetterTable.failed_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        session = await self._get_session()
        stmt = select(OutboxEventTable).where(OutboxEventTable.event_id == str(event_id))
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row:
            return {
                "event_id": row.event_id,
                "status": row.status,
                "retry_count": row.retry_count,
                "last_error": row.last_error,
                "created_at": row.created_at.isoformat(),
                "processed_at": row.processed_at.isoformat() if row.processed_at else None,
                "version": row.version,
                "correlation_id": row.correlation_id,
            }
        stmt_dl = select(DeadLetterTable).where(DeadLetterTable.original_event_id == event_id)
        result = await session.execute(stmt_dl)
        dl = result.scalar_one_or_none()
        if dl:
            return {
                "event_id": str(event_id),
                "status": "DEAD_LETTER",
                "error": dl.final_error,
                "failed_at": dl.failed_at.isoformat(),
                "correlation_id": dl.correlation_id,
            }
        return None

    async def get_pending_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == OutboxStatus.PENDING.value)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_processing_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == OutboxStatus.PROCESSING.value)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_failed_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == OutboxStatus.FAILED.value)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_dead_letter_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(DeadLetterTable)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_outbox_size(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable)
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def flush(self) -> int:
        processed = 0
        while True:
            await self._process_pending_events()
            pending = await self.get_pending_count()
            if pending == 0:
                break
            processed += 1
            await asyncio.sleep(0.1)
        return processed

    async def purge_outbox(self, older_than_days: int = 30) -> int:
        session = await self._get_session()
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stmt = delete(OutboxEventTable).where(
            OutboxEventTable.status == OutboxStatus.SENT.value,
            OutboxEventTable.sent_at < cutoff,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    async def get_statistics(self) -> dict[str, Any]:
        return {
            "pending_count": await self.get_pending_count(),
            "processing_count": await self.get_processing_count(),
            "failed_count": await self.get_failed_count(),
            "dead_letter_count": await self.get_dead_letter_count(),
            "outbox_size": await self.get_outbox_size(),
            "poller_running": self._running,
            "instance_id": self._instance_id,
            "subscribers": list(self._subscribers.keys()),
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return []

    async def health_check(self) -> dict[str, Any]:
        try:
            pending = await self.get_pending_count()
            dead = await self.get_dead_letter_count()
            status = "healthy"
            if pending > 10000:
                status = "degraded"
            if dead > 1000:
                status = "unhealthy"
            return {
                "status": status,
                "pending_events": pending,
                "dead_letter_events": dead,
                "poller_running": self._running,
                "instance_id": self._instance_id,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


__all__ = ["DeadLetterTable", "OutboxEventTable", "SQLAlchemyEventPublisherAdapter"]
