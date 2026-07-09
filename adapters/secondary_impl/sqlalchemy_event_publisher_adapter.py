#!/usr/bin/env python3
"""
Module: sqlalchemy_event_publisher_adapter.py
Layer: Adapters (Secondary Implementation)
Responsibility: Implementasi EventPublisherPort dengan SQLAlchemy (outbox pattern).

FIX: Kolom 'metadata' diganti menjadi 'extra_metadata' karena 'metadata' adalah reserved
attribute pada SQLAlchemy Declarative API.
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
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    select,
    update,
    delete,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base

from ports.primary.event_publisher_port import EventPublisherPort, EventPriority, EventStatus

logger = logging.getLogger(__name__)

Base = declarative_base()


class OutboxEventTable(Base):
    __tablename__ = "outbox_events"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(String(100), nullable=False, unique=True)
    event_type = Column(String(100), nullable=False)
    event_version = Column(Integer, nullable=False, default=1)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type = Column(String(100), nullable=False)
    payload = Column(Text, nullable=False)  # JSON string
    extra_metadata = Column(Text, nullable=True)  # JSON string (renamed from 'metadata')
    priority = Column(Integer, nullable=False, default=1)  # 0=LOW, 1=NORMAL, 2=HIGH, 3=CRITICAL
    status = Column(String(20), nullable=False, default="pending")
    retry_count = Column(Integer, nullable=False, default=0)
    max_retries = Column(Integer, nullable=False, default=5)
    last_attempt_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    locked_by = Column(String(50), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    idempotency_key = Column(String(100), nullable=True, unique=True)
    partition_key = Column(String(50), nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)


class DeadLetterTable(Base):
    __tablename__ = "dead_letter_events"
    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    original_event_id = Column(PGUUID(as_uuid=True), nullable=False, unique=True)
    event_type = Column(String(100), nullable=False)
    aggregate_id = Column(PGUUID(as_uuid=True), nullable=False)
    aggregate_type = Column(String(100), nullable=False)
    payload = Column(Text, nullable=False)
    extra_metadata = Column(Text, nullable=True)  # renamed from 'metadata'
    final_error = Column(Text, nullable=False)
    failed_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    resolution_status = Column(String(20), nullable=False, default="PENDING")
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(PGUUID(as_uuid=True), nullable=True)


class SQLAlchemyEventPublisherAdapter(EventPublisherPort):
    """
    Implementasi EventPublisherPort dengan SQLAlchemy outbox table.
    """

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
        self._subscribers: dict[str, list[Callable]] = {}  # event_type -> list of handlers

    async def _get_session(self) -> AsyncSession:
        if self._session is None:
            from infrastructure.database.session_factory_sqlalchemy import get_async_session
            self._session = await get_async_session()
        return self._session

    # -------------------- HELPER --------------------
    def _compute_idempotency_key(self, event_type: str, aggregate_id: UUID, payload_hash: str) -> str:
        return hashlib.sha256(f"{event_type}:{aggregate_id}:{payload_hash}".encode()).hexdigest()

    async def _calculate_retry_delay(self, retry_count: int) -> float:
        delay = self._base_delay * (2 ** (retry_count - 1))
        return min(delay, self._max_delay)

    # -------------------- PUBLISH --------------------
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
    ) -> UUID:
        session = await self._get_session()
        if hasattr(event, "to_dict"):
            payload = event.to_dict()
        elif isinstance(event, dict):
            payload = event
        else:
            payload = {"_raw": str(event)}

        if not idempotency_key:
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            idempotency_key = self._compute_idempotency_key(event_type, aggregate_id, payload_hash)

        event_id = str(uuid4())
        now = datetime.now(UTC)

        # Check idempotency
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
            payload=json.dumps(payload, default=str),
            extra_metadata=json.dumps(metadata or {}),  # renamed field
            priority=priority.value,
            status="pending",
            max_retries=self._default_max_retries,
            created_at=now,
            scheduled_at=scheduled_at,
            idempotency_key=idempotency_key,
            partition_key=partition_key,
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
            )
            ids.append(eid)
        return ids

    # -------------------- SUBSCRIBER --------------------
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
        # Simplified: remove all handlers for event_type
        if event_type in self._subscribers:
            del self._subscribers[event_type]
            return True
        return False

    # -------------------- POLLER --------------------
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
                pass
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
        # Lock and fetch pending events
        stmt = (
            select(OutboxEventTable)
            .where(
                OutboxEventTable.status == "pending",
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
            # Mark as processing
            event.status = "processing"
            event.locked_by = self._instance_id
            event.locked_until = now + timedelta(seconds=self._lock_timeout)
            await session.flush()
            # Process
            await self._process_single_event(event, session)

    async def _process_single_event(self, event: OutboxEventTable, session: AsyncSession):
        start_time = time.perf_counter()
        success = True
        error_msg = None

        try:
            payload = json.loads(event.payload)
            metadata = json.loads(event.extra_metadata) if event.extra_metadata else {}  # renamed
            handlers = self._subscribers.get(event.event_type, [])
            if not handlers:
                # No subscribers, mark as sent
                pass
            else:
                for handler in handlers:
                    try:
                        handler_success = await asyncio.wait_for(
                            handler(payload, metadata), timeout=30
                        )
                        if not handler_success:
                            success = False
                            error_msg = f"Handler returned False"
                            break
                    except Exception as e:
                        success = False
                        error_msg = f"Handler error: {e!s}"
                        break
        except Exception as e:
            success = False
            error_msg = str(e)

        latency_ms = (time.perf_counter() - start_time) * 1000

        if success:
            event.status = "sent"
            event.sent_at = datetime.now(UTC)
            event.locked_by = None
            event.locked_until = None
        else:
            event.retry_count += 1
            event.last_attempt_at = datetime.now(UTC)
            event.last_error = error_msg
            if event.retry_count >= event.max_retries:
                # Move to dead letter
                await self._move_to_dead_letter(event, error_msg, session)
                await session.delete(event)
            else:
                delay = await self._calculate_retry_delay(event.retry_count)
                event.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
                event.status = "pending"
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
            extra_metadata=event.extra_metadata,  # renamed
            final_error=error_msg,
        )
        session.add(dead)

    # -------------------- DEAD LETTER OPERATIONS --------------------
    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        session = await self._get_session()
        stmt = select(DeadLetterTable).where(DeadLetterTable.id == dead_letter_id).with_for_update()
        result = await session.execute(stmt)
        dead = result.scalar_one_or_none()
        if not dead or dead.resolution_status != "PENDING":
            return None
        # Republish
        payload = json.loads(dead.payload)
        metadata = json.loads(dead.extra_metadata) if dead.extra_metadata else {}  # renamed
        new_id = await self.publish(
            event=payload,
            event_type=dead.event_type,
            aggregate_id=dead.aggregate_id,
            aggregate_type=dead.aggregate_type,
            metadata=metadata,
            priority=EventPriority.NORMAL,
            scheduled_at=datetime.now(UTC) + timedelta(seconds=1),
            event_version=2,
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

    # -------------------- QUERY --------------------
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
            }
        # Check dead letter
        stmt_dl = select(DeadLetterTable).where(DeadLetterTable.original_event_id == event_id)
        result = await session.execute(stmt_dl)
        dl = result.scalar_one_or_none()
        if dl:
            return {
                "event_id": str(event_id),
                "status": "DEAD_LETTER",
                "error": dl.final_error,
                "failed_at": dl.failed_at.isoformat(),
            }
        return None

    async def get_pending_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == "pending")
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_processing_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == "processing")
        result = await session.execute(stmt)
        return result.scalar() or 0

    async def get_failed_count(self) -> int:
        session = await self._get_session()
        stmt = select(func.count()).select_from(OutboxEventTable).where(OutboxEventTable.status == "failed")
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
            OutboxEventTable.status == "sent",
            OutboxEventTable.sent_at < cutoff,
        )
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount

    # -------------------- STATISTICS & AUDIT & HEALTH --------------------
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
        # We don't have audit log table, return empty list or query from a log table if exists
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


__all__ = ["SQLAlchemyEventPublisherAdapter", "OutboxEventTable", "DeadLetterTable"]