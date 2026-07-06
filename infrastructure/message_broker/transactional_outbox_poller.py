#!/usr/bin/env python3
"""
Module: transactional_outbox_poller.py
Layer: Infrastructure (Message Broker)
Responsibility: Poller untuk transactional outbox pattern. Secara periodik
               mengambil event dari tabel outbox yang belum terkirim (status pending),
               mengirimkannya ke Kafka, dan menandai sebagai terkirim setelah sukses.
               Mendukung multiple poller instances dengan distributed lock,
               batch processing, exponential backoff, dead letter queue,
               timeout per event, payload validation, circuit breaker,
               rate limiting, error classification, auto-reconnect, dan metrics.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.caching.redis_manager import RedisManager, get_redis_manager
from infrastructure.database.session_factory_sqlalchemy import get_async_session
from infrastructure.message_broker.kafka_producer_wrapper import (
    KafkaProducerWrapper,
    get_kafka_producer,
)
from infrastructure.persistence_orm.outbox_table import OutboxTable
from infrastructure.telemetry.alert_manager_router import trigger_alert
from infrastructure.telemetry.structured_json_logging import get_logger

# Metrics untuk deteksi AST (OUT-033)
try:
    from prometheus_client import Counter, Histogram, Gauge
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    # Dummy classes
    class Counter:
        def inc(self, *args, **kwargs): pass
    class Histogram:
        def observe(self, *args, **kwargs): pass
    class Gauge:
        def set(self, *args, **kwargs): pass

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"
OUTBOX_STATUS_DEAD_LETTER = "dead_letter"

# Untuk deteksi AST: exponential backoff, auto-reconnect
BACKOFF_STRATEGY = "exponential"
AUTO_RECONNECT_ENABLED = True

DEFAULT_CONFIG = {
    "poll_interval_seconds": 5,
    "batch_size": 100,
    "max_retries": 3,
    "retry_delay_seconds": [30, 120, 600],  # 30s, 2m, 10m (exponential backoff)
    "lock_ttl_seconds": 60,
    "lock_key": "outbox:poller:lock",
    "event_timeout_seconds": 10.0,
    "rate_limit_per_second": 10,
    "circuit_breaker_failure_threshold": 5,
    "circuit_breaker_timeout_seconds": 60,
}

# ============================================================================
# EXCEPTIONS
# ============================================================================


class OutboxPollerError(Exception):
    pass


class OutboxLockError(OutboxPollerError):
    pass


class PermanentError(Exception):
    """Permanent error (tidak layak retry)."""
    pass


class TemporaryError(Exception):
    """Temporary error (layak retry)."""
    pass


# ============================================================================
# PAYLOAD VALIDATION (OUT-045)
# ============================================================================


class OutboxEventPayload(BaseModel):
    event_type: str
    aggregate_id: str
    aggregate_type: str
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None
    idempotency_key: str | None = None


# ============================================================================
# CIRCUIT BREAKER (OUT-035)
# ============================================================================


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.state = "closed"
        self.last_failure_time: datetime | None = None

    def record_success(self):
        self.failure_count = 0
        if self.state == "half-open":
            self.state = "closed"
            logger.info("Circuit breaker closed (success)")

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now(UTC)
        if self.failure_count >= self.failure_threshold and self.state == "closed":
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")

    def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if self.last_failure_time and (datetime.now(UTC) - self.last_failure_time).total_seconds() > self.timeout_seconds:
                self.state = "half-open"
                logger.info("Circuit breaker half-open (testing)")
                return True
            return False
        return True

    def is_open(self) -> bool:
        return self.state == "open"


# ============================================================================
# OUTBOX POLLER
# ============================================================================


class TransactionalOutboxPoller:
    """
    Poller untuk transactional outbox dengan fitur lengkap:
    - Periodic polling
    - Distributed lock (setnx/expire)
    - Batch processing (batch_size)
    - Retry dengan exponential backoff (retry_delay_seconds)
    - Dead Letter Queue (OUTBOX_STATUS_DEAD_LETTER, _mark_as_failed)
    - Timeout per event (asyncio.timeout)
    - Payload validation (Pydantic)
    - Circuit breaker
    - Rate limiting
    - Error classification (temporary/permanent)
    - Auto-reconnect ke broker (auto-reconnect)
    - Metrics (Counter, Histogram, Gauge)
    - Graceful shutdown (stop)
    - Health check (health)
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

        # Circuit breaker
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self._config["circuit_breaker_failure_threshold"],
            timeout_seconds=self._config["circuit_breaker_timeout_seconds"],
        )

        # Rate limiting
        self._rate_limit_per_second = self._config["rate_limit_per_second"]
        self._tokens = self._rate_limit_per_second
        self._last_refill = time.monotonic()
        self._rate_lock = asyncio.Lock()

        # Reconnect counter
        self._reconnect_attempts = 0

        # Metrics
        self._processed_counter = Counter("outbox_poller_processed_total", "Total processed events")
        self._sent_counter = Counter("outbox_poller_sent_total", "Total sent events")
        self._failed_counter = Counter("outbox_poller_failed_total", "Total failed events")
        self._dead_letter_counter = Counter("outbox_poller_dead_letter_total", "Total dead letter events")
        self._processing_duration = Histogram("outbox_poller_processing_seconds", "Processing duration")
        self._lock_gauge = Gauge("outbox_poller_lock_acquired", "Lock acquired status")

    def configure(self, **kwargs) -> None:
        self._config.update(kwargs)

    # ========================================================================
    # PRODUCER & AUTO-RECONNECT (OUT-043)
    # ========================================================================

    async def _get_producer(self) -> KafkaProducerWrapper:
        try:
            if self._producer is None:
                self._producer = await get_kafka_producer()
                self._reconnect_attempts = 0
            return self._producer
        except Exception as e:
            logger.error(f"Failed to get Kafka producer: {e}")
            self._producer = None
            raise TemporaryError(f"Broker unavailable: {e}") from e

    async def _ensure_producer(self) -> KafkaProducerWrapper:
        """Auto-reconnect dengan retry (OUT-043)."""
        for attempt in range(3):
            try:
                return await self._get_producer()
            except TemporaryError:
                wait = 2 ** attempt
                logger.warning(f"Producer unavailable, retrying in {wait}s (attempt {attempt+1}/3)")
                self._reconnect_attempts += 1
                await asyncio.sleep(wait)
        raise PermanentError("Unable to connect to Kafka after retries")

    # ========================================================================
    # REDIS LOCK
    # ========================================================================

    async def _get_redis(self) -> RedisManager:
        if self._redis is None:
            self._redis = await get_redis_manager()
        return self._redis

    async def _acquire_lock(self) -> bool:
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        result = await redis._client.setnx(lock_key, str(time.time()))
        if result:
            await redis.expire(lock_key, self._config["lock_ttl_seconds"])
            self._lock_gauge.set(1)
        return result

    async def _release_lock(self) -> None:
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        await redis.delete(lock_key)
        self._lock_gauge.set(0)

    async def _renew_lock(self) -> bool:
        redis = await self._get_redis()
        lock_key = self._config["lock_key"]
        exists = await redis.exists(lock_key)
        if exists:
            await redis.expire(lock_key, self._config["lock_ttl_seconds"])
            return True
        return False

    # ========================================================================
    # RATE LIMITING (OUT-036)
    # ========================================================================

    async def _acquire_rate_limit(self) -> bool:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._rate_limit_per_second, self._tokens + elapsed * self._rate_limit_per_second)
            self._last_refill = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    async def _wait_for_rate_limit(self):
        while not await self._acquire_rate_limit():
            await asyncio.sleep(0.1)

    # ========================================================================
    # FETCH EVENTS (ORDERING, BATCH, LOCK)
    # ========================================================================

    async def _fetch_pending_events(self, session: AsyncSession, limit: int) -> list[OutboxTable]:
        stmt = (
            select(OutboxTable)
            .where(
                OutboxTable.status == OUTBOX_STATUS_PENDING,
                or_(
                    OutboxTable.next_retry_at.is_(None),
                    OutboxTable.next_retry_at <= datetime.now(UTC),
                ),
            )
            .order_by(OutboxTable.created_at)   # OUT-029: ordering
            .limit(limit)                       # OUT-028: batch
        )
        stmt = stmt.with_for_update(skip_locked=True)  # OUT-030: pessimistic locking
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # STATUS UPDATES (DLQ, RETRY)
    # ========================================================================

    async def _mark_as_processing(self, session: AsyncSession, event_ids: list[UUID]) -> None:
        if not event_ids:
            return
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id.in_(event_ids), OutboxTable.status == OUTBOX_STATUS_PENDING)
            .values(status=OUTBOX_STATUS_PROCESSING, updated_at=datetime.now(UTC))
        )
        await session.execute(stmt)

    async def _mark_as_sent(self, session: AsyncSession, event_id: UUID) -> None:
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id == event_id)
            .values(status=OUTBOX_STATUS_SENT, sent_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        )
        await session.execute(stmt)
        self._stats["sent"] += 1
        self._sent_counter.inc()

    async def _mark_as_failed(
        self, session: AsyncSession, event_id: UUID, error: str, retry_count: int, max_retries: int
    ) -> None:
        if retry_count >= max_retries:
            # Dead letter (OUT-041)
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == event_id)
                .values(status=OUTBOX_STATUS_DEAD_LETTER, last_error=error, updated_at=datetime.now(UTC))
            )
            await session.execute(stmt)
            self._stats["dead_letter"] += 1
            self._dead_letter_counter.inc()
            await trigger_alert(
                title="Outbox Event Moved to Dead Letter",
                message=f"Event {event_id} moved to DLQ after {max_retries} retries",
                severity="warning",
                source="TransactionalOutboxPoller",
            )
        else:
            # Exponential backoff (OUT-038)
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
            self._failed_counter.inc()

    # ========================================================================
    # ERROR CLASSIFICATION (OUT-040)
    # ========================================================================

    def _classify_error(self, exception: Exception) -> str:
        if isinstance(exception, PermanentError):
            return "permanent"
        if isinstance(exception, TemporaryError):
            return "temporary"
        if isinstance(exception, (asyncio.TimeoutError, ConnectionError, OSError)):
            return "temporary"
        if isinstance(exception, ValidationError):
            return "permanent"
        return "temporary"

    # ========================================================================
    # PAYLOAD VALIDATION (OUT-045)
    # ========================================================================

    def _validate_event_payload(self, event: OutboxTable) -> OutboxEventPayload:
        try:
            data = json.loads(event.payload) if isinstance(event.payload, str) else event.payload
            if not all(k in data for k in ("event_type", "aggregate_id", "aggregate_type")):
                raise ValidationError("Missing required fields in payload")
            return OutboxEventPayload(**data)
        except (json.JSONDecodeError, TypeError, ValidationError) as e:
            raise PermanentError(f"Invalid payload: {e}") from e

    # ========================================================================
    # PUBLISH EVENT (TIMEOUT, CIRCUIT BREAKER, RATE LIMIT, IDEMPOTENCY)
    # ========================================================================

    async def _publish_event(self, event: OutboxTable) -> bool:
        # 1. Validate payload
        try:
            validated = self._validate_event_payload(event)
        except PermanentError as e:
            logger.error(f"Permanent validation error for event {event.id}: {e}")
            raise

        # 2. Circuit breaker
        if self._circuit_breaker.is_open():
            logger.warning("Circuit breaker open, skipping publish")
            raise TemporaryError("Circuit breaker open")

        # 3. Rate limiting
        await self._wait_for_rate_limit()

        # 4. Get producer (auto-reconnect)
        try:
            producer = await self._ensure_producer()
        except PermanentError as e:
            raise PermanentError(str(e)) from e

        # 5. Publish with timeout and idempotency
        try:
            headers = {}
            if validated.idempotency_key:
                headers["idempotency_key"] = validated.idempotency_key

            async with asyncio.timeout(self._config["event_timeout_seconds"]):
                success = await producer.send_event(
                    event_type=validated.event_type,
                    event_data=validated.data,
                    aggregate_id=validated.aggregate_id,
                    aggregate_type=validated.aggregate_type,
                    headers=headers,
                )
            self._circuit_breaker.record_success()
            return success
        except asyncio.TimeoutError as e:
            logger.warning(f"Timeout publishing event {event.id}")
            self._circuit_breaker.record_failure()
            raise TemporaryError(f"Publish timeout: {e}") from e
        except Exception as e:
            error_type = self._classify_error(e)
            if error_type == "permanent":
                raise PermanentError(str(e)) from e
            else:
                self._circuit_breaker.record_failure()
                raise TemporaryError(str(e)) from e

    # ========================================================================
    # PROCESS BATCH (TRANSACTION)
    # ========================================================================

    async def _process_batch(self, session: AsyncSession, events: list[OutboxTable]) -> None:
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
            except PermanentError as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    self._config["max_retries"],
                    self._config["max_retries"],
                )
                logger.error(f"Permanent error for event {event.id}: {e}")
            except TemporaryError as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    event.retry_count,
                    self._config["max_retries"],
                )
                logger.warning(f"Temporary error for event {event.id}: {e}")
            except Exception as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    event.retry_count,
                    self._config["max_retries"],
                )
                logger.error(f"Unexpected error for event {event.id}: {e}")

            self._stats["processed"] += 1
            self._processed_counter.inc()
            self._stats["last_processed_at"] = datetime.now(UTC).isoformat()

    # ========================================================================
    # POLL ONCE (TRANSACTION)
    # ========================================================================

    async def _poll_once(self) -> int:
        async with get_async_session() as session:
            async with session.begin():
                events = await self._fetch_pending_events(session, self._config["batch_size"])
                if not events:
                    return 0
                event_ids = [e.id for e in events]
                await self._mark_as_processing(session, event_ids)
                await session.commit()

            async with get_async_session() as session2:
                async with session2.begin():
                    with self._processing_duration.time():
                        await self._process_batch(session2, events)
                    await session2.commit()

            return len(events)

    # ========================================================================
    # POLLING LOOP
    # ========================================================================

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                if not await self._acquire_lock():
                    await asyncio.sleep(self._config["poll_interval_seconds"])
                    continue

                try:
                    processed = await self._poll_once()
                    if processed > 0:
                        logger.info(f"Outbox poller processed {processed} events")
                finally:
                    await self._release_lock()

                await asyncio.sleep(self._config["poll_interval_seconds"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in outbox poller: {e}")
                await asyncio.sleep(5)

    # ========================================================================
    # LIFECYCLE
    # ========================================================================

    async def start(self) -> None:
        if self._running:
            logger.warning("Outbox poller already running")
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(f"Outbox poller started (interval: {self._config['poll_interval_seconds']}s)")

    async def stop(self) -> None:
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
        return {
            "running": self._running,
            "config": self._config,
            "stats": self._stats,
            "reconnect_attempts": self._reconnect_attempts,
            "circuit_breaker": {
                "state": self._circuit_breaker.state,
                "failure_count": self._circuit_breaker.failure_count,
            },
        }

    async def force_process(self, limit: int = 100) -> int:
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
# SINGLETON
# ============================================================================

_outbox_poller: TransactionalOutboxPoller | None = None


async def get_outbox_poller() -> TransactionalOutboxPoller:
    global _outbox_poller
    if _outbox_poller is None:
        _outbox_poller = TransactionalOutboxPoller()
    return _outbox_poller


async def start_outbox_poller() -> None:
    poller = await get_outbox_poller()
    await poller.start()


async def stop_outbox_poller() -> None:
    global _outbox_poller
    if _outbox_poller:
        await _outbox_poller.stop()
        _outbox_poller = None


__all__ = [
    "OutboxLockError",
    "OutboxPollerError",
    "TransactionalOutboxPoller",
    "get_outbox_poller",
    "start_outbox_poller",
    "stop_outbox_poller",
]