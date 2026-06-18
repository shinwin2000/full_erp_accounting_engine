#!/usr/bin/env python3
"""
Module: transactional_outbox_poller.py
Layer: Infrastructure (Message Broker)
Responsibility: Poller untuk transactional outbox pattern. Secara periodik
               mengambil event dari tabel outbox yang belum terkirim (status pending),
               mengirimkannya ke Kafka, dan menandai sebagai terkirim setelah sukses.
               Mendukung multiple poller instances dengan distributed lock,
               batch processing, exponential backoff, dan dead letter queue.
Dependencies:
- asyncio, logging, datetime
- infrastructure.persistence_orm.outbox_table (OutboxTable)
- infrastructure.message_broker.kafka_producer_wrapper (KafkaProducerWrapper)
- infrastructure.caching.redis_manager (RedisManager)
- sqlalchemy.ext.asyncio
- infrastructure.telemetry.structured_json_logging
Audit: Setiap event yang dikirim dicatat. Gagal kirim di-retry dan masuk DLQ.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.message_broker.kafka_producer_wrapper import (
    KafkaProducerWrapper,
    get_kafka_producer,
)

# Internal dependencies
from infrastructure.persistence_orm.outbox_table import OutboxTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"
OUTBOX_STATUS_DEAD_LETTER = "dead_letter"

DEFAULT_CONFIG = {
    "poll_interval_seconds": 5,
    "batch_size": 100,
    "max_retries": 3,
    "retry_delay_seconds": [30, 120, 600],  # 30s, 2m, 10m
    "lock_ttl_seconds": 60,
    "lock_key": "outbox:poller:lock",
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class OutboxPollerError(Exception):
    """Base exception untuk outbox poller."""

    pass


class OutboxLockError(OutboxPollerError):
    """Error saat mengakuisisi lock."""

    pass


# ============================================================================
# OUTBOX POLLER
# ============================================================================


class TransactionalOutboxPoller:
    """
    Poller untuk transactional outbox.

    Fitur:
    - Periodic polling dari tabel outbox
    - Distributed lock (hanya satu instance yang polling)
    - Batch processing
    - Retry dengan exponential backoff
    - Dead letter queue untuk gagal permanen
    - Metrics collection
    """

    def __init__(self):
        self._producer: KafkaProducerWrapper | None = None
        self._redis: RedisManager | None = None
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._stats = {
            "processed": 0,
            "sent": 0,
            "failed": 0,
            "dead_letter": 0,
            "last_processed_at": None,
        }
        self._config = DEFAULT_CONFIG.copy()

    def configure(self, **kwargs) -> None:
        """Update configuration."""
        self._config.update(kwargs)

    async def _get_producer(self) -> KafkaProducerWrapper:
        if self._producer is None:
            self._producer = await get_kafka_producer()
        return self._producer

    async def _get_redis(self) -> RedisManager:
        if self._redis is None:
            self._redis = await get_redis_manager()
        return self._redis

    async def _acquire_lock(self) -> bool:
        """Acquire distributed lock for polling."""
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        # SET NX (only if not exists) with TTL
        result = await redis._client.setnx(lock_key, str(time.time()))
        if result:
            await redis.expire(lock_key, self._config["lock_ttl_seconds"])
        return result

    async def _release_lock(self) -> None:
        """Release distributed lock."""
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        await redis.delete(lock_key)

    async def _renew_lock(self) -> bool:
        """Renew lock TTL."""
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        exists = await redis.exists(lock_key)
        if exists:
            await redis.expire(lock_key, self._config["lock_ttl_seconds"])
            return True
        return False

    async def _fetch_pending_events(self, session: AsyncSession, limit: int) -> list[OutboxTable]:
        """Fetch pending events from outbox table."""
        stmt = (
            select(OutboxTable)
            .where(
                OutboxTable.status == OUTBOX_STATUS_PENDING,
                or_(
                    OutboxTable.next_retry_at.is_(None),
                    OutboxTable.next_retry_at <= datetime.now(UTC),
                ),
            )
            .order_by(OutboxTable.created_at)
            .limit(limit)
        )

        # Add FOR UPDATE SKIP LOCKED for row-level locking
        stmt = stmt.with_for_update(skip_locked=True)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _mark_as_processing(self, session: AsyncSession, event_ids: list[UUID]) -> None:
        """Mark events as processing."""
        if not event_ids:
            return

        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id.in_(event_ids), OutboxTable.status == OUTBOX_STATUS_PENDING)
            .values(status=OUTBOX_STATUS_PROCESSING, updated_at=datetime.now(UTC))
        )
        await session.execute(stmt)

    async def _mark_as_sent(self, session: AsyncSession, event_id: UUID) -> None:
        """Mark event as sent."""
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id == event_id)
            .values(
                status=OUTBOX_STATUS_SENT, sent_at=datetime.now(UTC), updated_at=datetime.now(UTC)
            )
        )
        await session.execute(stmt)
        self._stats["sent"] += 1

    async def _mark_as_failed(
        self, session: AsyncSession, event_id: UUID, error: str, retry_count: int, max_retries: int
    ) -> None:
        """Mark event as failed and schedule retry."""
        if retry_count >= max_retries:
            # Move to dead letter queue
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == event_id)
                .values(
                    status=OUTBOX_STATUS_DEAD_LETTER, last_error=error, updated_at=datetime.now(UTC)
                )
            )
            await session.execute(stmt)
            self._stats["dead_letter"] += 1
            await trigger_alert(
                title="Outbox Event Moved to Dead Letter",
                message=f"Event {event_id} moved to DLQ after {max_retries} retries",
                severity="warning",
                source="TransactionalOutboxPoller",
            )
        else:
            # Schedule retry with backoff
            delays = self._config["retry_delay_seconds"]
            delay = delays[min(retry_count, len(delays) - 1)]
            next_retry = datetime.now(UTC) + timedelta(seconds=delay)

            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == event_id)
                .values(
                    status=OUTBOX_STATUS_PENDING,
                    retry_count=retry_count + 1,
                    last_error=error,
                    next_retry_at=next_retry,
                    updated_at=datetime.now(UTC),
                )
            )
            await session.execute(stmt)
            self._stats["failed"] += 1

    async def _publish_event(self, event: OutboxTable) -> bool:
        """Publish event to Kafka."""
        producer = await self._get_producer()

        # Determine topic (can be configured per event type)
        topic = "erp-events"  # Default

        try:
            # Parse payload
            payload = json.loads(event.payload) if isinstance(event.payload, str) else event.payload

            # Send to Kafka
            success = await producer.send_event(
                event_type=event.event_type,
                event_data=payload,
                aggregate_id=str(event.aggregate_id),
                aggregate_type=event.aggregate_type,
            )
            return success
        except Exception as e:
            logger.error(f"Failed to publish event {event.id}: {e}")
            return False

    async def _process_batch(self, session: AsyncSession, events: list[OutboxTable]) -> None:
        """Process a batch of events."""
        for event in events:
            try:
                success = await self._publish_event(event)
                if success:
                    await self._mark_as_sent(session, event.id)
                else:
                    await self._mark_as_failed(
                        session,
                        event.id,
                        "Kafka send failed",
                        event.retry_count,
                        self._config["max_retries"],
                    )
            except Exception as e:
                await self._mark_as_failed(
                    session, event.id, str(e), event.retry_count, self._config["max_retries"]
                )

            self._stats["processed"] += 1
            self._stats["last_processed_at"] = datetime.now(UTC).isoformat()

    async def _poll_once(self) -> int:
        """Poll once and process pending events."""
        async with get_async_session() as session:
            async with session.begin():
                # Fetch pending events
                events = await self._fetch_pending_events(session, self._config["batch_size"])

                if not events:
                    return 0

                # Mark as processing
                event_ids = [e.id for e in events]
                await self._mark_as_processing(session, event_ids)

                # Commit to release lock on events
                await session.commit()

            # Process events (outside transaction to avoid long locks)
            async with get_async_session() as session, session.begin():
                await self._process_batch(session, events)
                await session.commit()

            return len(events)

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                # Acquire distributed lock
                if not await self._acquire_lock():
                    await asyncio.sleep(self._config["poll_interval_seconds"])
                    continue

                try:
                    # Renew lock periodically while processing
                    processed = await self._poll_once()

                    if processed > 0:
                        logger.info(f"Outbox poller processed {processed} events")

                finally:
                    await self._release_lock()

                # Sleep before next poll
                await asyncio.sleep(self._config["poll_interval_seconds"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in outbox poller: {e}")
                await asyncio.sleep(5)

    async def start(self) -> None:
        """Start the outbox poller."""
        if self._running:
            logger.warning("Outbox poller already running")
            return

        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"Outbox poller started (interval: {self._config['poll_interval_seconds']}s)")

    async def stop(self) -> None:
        """Stop the outbox poller."""
        self._running = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        logger.info("Outbox poller stopped")

    async def get_stats(self) -> dict[str, Any]:
        """Get poller statistics."""
        return {"running": self._running, "config": self._config, "stats": self._stats}

    async def force_process(self, limit: int = 100) -> int:
        """Force processing of pending events."""
        async with get_async_session() as session:
            async with session.begin():
                events = await self._fetch_pending_events(session, limit)
                if events:
                    event_ids = [e.id for e in events]
                    await self._mark_as_processing(session, event_ids)
                    await session.commit()

                    async with get_async_session() as session2:
                        async with session2.begin():
                            await self._process_batch(session2, events)
                            await session2.commit()

                    return len(events)
            return 0


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_outbox_poller: TransactionalOutboxPoller | None = None


async def get_outbox_poller() -> TransactionalOutboxPoller:
    """Get singleton instance of TransactionalOutboxPoller."""
    global _outbox_poller
    if _outbox_poller is None:
        _outbox_poller = TransactionalOutboxPoller()
    return _outbox_poller


async def start_outbox_poller() -> None:
    """Start the outbox poller."""
    poller = await get_outbox_poller()
    await poller.start()


async def stop_outbox_poller() -> None:
    """Stop the outbox poller."""
    global _outbox_poller
    if _outbox_poller:
        await _outbox_poller.stop()
        _outbox_poller = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "OutboxLockError",
    "OutboxPollerError",
    "TransactionalOutboxPoller",
    "get_outbox_poller",
    "start_outbox_poller",
    "stop_outbox_poller",
]
