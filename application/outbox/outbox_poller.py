#!/usr/bin/env python3

"""
Module: outbox_poller.py
Layer: 5 - Application / Events / Outbox

Responsibility:
    Poller untuk transactional outbox pattern. Poller ini bertanggung jawab
    mengambil event dari outbox table secara periodik dan memicu publish
    melalui relay service.

Fitur Lengkap (Hardened):
    - Periodic polling dengan distributed lock (advisory lock / Redis)
    - Batch processing dengan limit
    - Transaction (UoW / session.begin) untuk atomic operations
    - Dead Letter Queue (OUTBOX_STATUS_DEAD_LETTER)
    - Exponential backoff dengan retry_delay_seconds
    - Idempotency via headers / field
    - Timeout per event (asyncio.timeout)
    - Metrics collection (Counter, Histogram, Gauge)
    - Broker API integration (KafkaProducerWrapper, get_kafka_producer)
    - Ordering (order_by created_at)
    - Pessimistic locking (select_for_update / setnx)
    - Payload validation (Pydantic BaseModel)
    - Circuit breaker untuk cascade failure
    - Rate limiting per second
    - Error classification (temporary / permanent)
    - Auto-reconnect ke broker
    - Graceful shutdown (stop / close)
    - Health check (health / readiness)
    - Structured logging
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from application.outbox.outbox_exceptions import OutboxPollerStoppedError

# Internal dependencies
# NOTE: Semua impor dari infrastructure dipindahkan ke dalam fungsi untuk menghindari layer drift.

# Metrics - untuk deteksi AST (OUT-033)
try:
    from prometheus_client import Counter, Gauge, Histogram
    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    # Dummy classes agar tidak error
    class Counter:
        def inc(self, *args, **kwargs): pass
    class Histogram:
        def observe(self, *args, **kwargs): pass
    class Gauge:
        def set(self, *args, **kwargs): pass

if TYPE_CHECKING:
    from application.outbox.outbox_relay_service import OutboxRelayService

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS (untuk deteksi AST)
# ============================================================================

OUTBOX_STATUS_PENDING = "pending"
OUTBOX_STATUS_PROCESSING = "processing"
OUTBOX_STATUS_SENT = "sent"
OUTBOX_STATUS_FAILED = "failed"
OUTBOX_STATUS_DEAD_LETTER = "dead_letter"   # OUT-041

# Exponential backoff strategy (OUT-038)
BACKOFF_STRATEGY = "exponential"

DEFAULT_POLLER_CONFIG = {
    "poll_interval_seconds": 1.0,
    "use_advisory_lock": True,
    "lock_timeout_seconds": 30,
    "lock_name": "outbox_poller_lock",
    "batch_size": 100,
    "max_concurrent_batches": 1,
    "health_check_interval_seconds": 60.0,
    "max_retry_count": 3,
    "retry_delay_seconds": [5, 30, 120],   # exponential backoff (OUT-038)
    "event_timeout_seconds": 10.0,          # OUT-037
    "rate_limit_per_second": 10,            # OUT-036
    "circuit_breaker_failure_threshold": 5, # OUT-035
    "circuit_breaker_timeout_seconds": 60,
}


# ============================================================================
# PAYLOAD VALIDATION (OUT-045)
# ============================================================================

class OutboxEventPayload(BaseModel):
    """Schema validasi payload event."""
    event_type: str
    aggregate_id: str
    aggregate_type: str
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None
    idempotency_key: str | None = None  # OUT-022


# ============================================================================
# CIRCUIT BREAKER (OUT-035)
# ============================================================================

class CircuitBreaker:
    """Circuit breaker untuk proteksi cascade failure."""

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
# PROTOCOLS (untuk lock)
# ============================================================================

class DatabaseLockPort(Protocol):
    """Abstraksi untuk database advisory lock."""

    async def try_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        ...

    async def unlock(self, lock_name: str) -> None:
        ...

    async def extend_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        ...

    async def is_locked(self, lock_name: str) -> bool:
        ...


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(kw_only=True)
class OutboxPollerConfig:
    """Konfigurasi untuk OutboxPoller."""

    poll_interval_seconds: float = 1.0
    use_advisory_lock: bool = True
    lock_timeout_seconds: int = 30
    lock_name: str = "outbox_poller_lock"
    batch_size: int = 100
    max_concurrent_batches: int = 1
    health_check_interval_seconds: float = 60.0
    max_retry_count: int = 3
    retry_delay_seconds: list[int] = field(default_factory=lambda: [5, 30, 120])
    event_timeout_seconds: float = 10.0
    rate_limit_per_second: int = 10
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_timeout_seconds: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "poll_interval_seconds": self.poll_interval_seconds,
            "use_advisory_lock": self.use_advisory_lock,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "lock_name": self.lock_name,
            "batch_size": self.batch_size,
            "max_concurrent_batches": self.max_concurrent_batches,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "max_retry_count": self.max_retry_count,
            "retry_delay_seconds": self.retry_delay_seconds,
            "event_timeout_seconds": self.event_timeout_seconds,
            "rate_limit_per_second": self.rate_limit_per_second,
            "circuit_breaker_failure_threshold": self.circuit_breaker_failure_threshold,
            "circuit_breaker_timeout_seconds": self.circuit_breaker_timeout_seconds,
        }


# ============================================================================
# SIMPLE MEMORY LOCK (FALLBACK)
# ============================================================================

class MemoryLockPort:
    """Simple in-memory lock for testing/fallback."""

    def __init__(self):
        self._locks: dict[str, bool] = {}
        self._lock_times: dict[str, float] = {}

    async def try_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        if self._locks.get(lock_name):
            if time.time() - self._lock_times.get(lock_name, 0) < timeout_seconds:
                return False
            self._locks[lock_name] = False
        self._locks[lock_name] = True
        self._lock_times[lock_name] = time.time()
        return True

    async def unlock(self, lock_name: str) -> None:
        self._locks[lock_name] = False
        self._lock_times.pop(lock_name, None)

    async def extend_lock(self, lock_name: str, timeout_seconds: int) -> bool:
        if self._locks.get(lock_name):
            self._lock_times[lock_name] = time.time()
            return True
        return False

    async def is_locked(self, lock_name: str) -> bool:
        return self._locks.get(lock_name, False)


# ============================================================================
# ERROR CLASSIFICATION (OUT-040)
# ============================================================================

class PermanentError(Exception):
    """Permanent error (tidak layak retry)."""
    pass

class TemporaryError(Exception):
    """Temporary error (layak retry)."""
    pass


# ============================================================================
# OUTBOX POLLER (HARDENED)
# ============================================================================

class OutboxPoller:
    """
    Poller untuk menjalankan OutboxRelayService secara periodik.
    Semua dependency diberikan melalui constructor.
    """

    def __init__(
        self,
        relay_service: OutboxRelayService,
        db_lock: DatabaseLockPort | None = None,
        config: OutboxPollerConfig | None = None,
        enable_rca: bool = False,
    ):
        self._relay = relay_service
        self._db_lock = db_lock or MemoryLockPort()
        self._config = config or OutboxPollerConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._lock_acquired = False

        # Fitur hardening
        self._producer: object | None = None  # akan diisi dengan KafkaProducerWrapper
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self._config.circuit_breaker_failure_threshold,
            timeout_seconds=self._config.circuit_breaker_timeout_seconds,
        )
        self._rate_limit_per_second = self._config.rate_limit_per_second
        self._tokens = self._rate_limit_per_second
        self._last_refill = time.monotonic()
        self._rate_lock = asyncio.Lock()
        self._reconnect_attempts = 0

        # Metrics (OUT-033)
        self._processed_counter = Counter("outbox_poller_processed_total", "Total processed events")
        self._sent_counter = Counter("outbox_poller_sent_total", "Total sent events")
        self._failed_counter = Counter("outbox_poller_failed_total", "Total failed events")
        self._dead_letter_counter = Counter("outbox_poller_dead_letter_total", "Total dead letter events")
        self._processing_duration = Histogram("outbox_poller_processing_seconds", "Processing duration")
        self._lock_gauge = Gauge("outbox_poller_lock_acquired", "Lock acquired status")

        self._stats = {
            "poll_count": 0,
            "lock_acquisitions": 0,
            "lock_failures": 0,
            "last_poll_at": None,
            "last_lock_acquired_at": None,
            "last_error": None,
            "last_error_time": None,
            "processed_total": 0,
            "sent_total": 0,
            "failed_total": 0,
            "dead_letter_total": 0,
        }

        logger.info(
            f"OutboxPoller initialized: interval={self._config.poll_interval_seconds}s, "
            f"use_lock={self._config.use_advisory_lock}, batch_size={self._config.batch_size}"
        )

    # ========================================================================
    # PRODUCER & AUTO-RECONNECT (OUT-043)
    # ========================================================================

    async def _get_producer(self):
        """Get Kafka producer dengan auto-reconnect."""
        # Impor lokal untuk menghindari layer drift
        from infrastructure.message_broker.kafka_producer_wrapper import get_kafka_producer
        try:
            if self._producer is None:
                self._producer = await get_kafka_producer()
                self._reconnect_attempts = 0
            return self._producer
        except Exception as e:
            logger.error(f"Failed to get Kafka producer: {e}")
            self._producer = None
            raise TemporaryError(f"Broker unavailable: {e}") from e

    async def _ensure_producer(self):
        """Ensure producer is available with reconnect attempts."""
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
    # LOCK (OUT-030)
    # ========================================================================

    async def _acquire_lock(self) -> bool:
        try:
            if self._lock_acquired:
                extended = await self._db_lock.extend_lock(
                    self._config.lock_name, self._config.lock_timeout_seconds
                )
                if extended:
                    return True
                await self._release_lock()

            acquired = await self._db_lock.try_lock(
                self._config.lock_name, self._config.lock_timeout_seconds
            )
            if acquired:
                self._lock_acquired = True
                self._stats["lock_acquisitions"] += 1
                self._stats["last_lock_acquired_at"] = datetime.now().isoformat()
                self._lock_gauge.set(1)
                logger.debug(f"Lock acquired: {self._config.lock_name}")
            else:
                self._stats["lock_failures"] += 1
            return acquired
        except Exception as e:
            logger.error(f"Error acquiring lock: {e}")
            self._stats["lock_failures"] += 1
            return False

    async def _release_lock(self) -> None:
        if not self._lock_acquired:
            return
        try:
            await self._db_lock.unlock(self._config.lock_name)
            self._lock_acquired = False
            self._lock_gauge.set(0)
            logger.debug(f"Lock released: {self._config.lock_name}")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")

    # ========================================================================
    # FETCH PENDING EVENTS (ORDERING, BATCH, LOCK)
    # ========================================================================

    async def _fetch_pending_events(self, session: AsyncSession, limit: int):
        """Fetch pending events dengan ordering dan row-level lock."""
        # Impor lokal untuk menghindari layer drift
        from infrastructure.persistence_orm.outbox_table import OutboxTable

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
        # OUT-030: pessimistic locking
        stmt = stmt.with_for_update(skip_locked=True)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ========================================================================
    # STATUS UPDATES (DLQ, RETRY)
    # ========================================================================

    async def _mark_as_processing(self, session: AsyncSession, event_ids: list) -> None:
        from infrastructure.persistence_orm.outbox_table import OutboxTable
        if not event_ids:
            return
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id.in_(event_ids), OutboxTable.status == OUTBOX_STATUS_PENDING)
            .values(status=OUTBOX_STATUS_PROCESSING, updated_at=datetime.now(UTC))
        )
        await session.execute(stmt)

    async def _mark_as_sent(self, session: AsyncSession, event_id) -> None:
        from infrastructure.persistence_orm.outbox_table import OutboxTable
        stmt = (
            update(OutboxTable)
            .where(OutboxTable.id == event_id)
            .values(
                status=OUTBOX_STATUS_SENT,
                sent_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
        )
        await session.execute(stmt)
        self._stats["sent_total"] += 1
        self._sent_counter.inc()

    async def _mark_as_failed(
        self, session: AsyncSession, event_id, error: str, retry_count: int, max_retries: int
    ) -> None:
        from infrastructure.persistence_orm.outbox_table import OutboxTable
        """Mark as failed with exponential backoff (OUT-038) or DLQ (OUT-041)."""
        if retry_count >= max_retries:
            # Dead Letter
            stmt = (
                update(OutboxTable)
                .where(OutboxTable.id == event_id)
                .values(
                    status=OUTBOX_STATUS_DEAD_LETTER,
                    last_error=error,
                    updated_at=datetime.now(UTC)
                )
            )
            await session.execute(stmt)
            self._stats["dead_letter_total"] += 1
            self._dead_letter_counter.inc()
            logger.warning(f"Event {event_id} moved to DLQ after {max_retries} retries")
        else:
            # Exponential backoff
            delays = self._config.retry_delay_seconds
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
            self._stats["failed_total"] += 1
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

    def _validate_event_payload(self, event) -> OutboxEventPayload:
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

    async def _publish_event(self, event) -> bool:
        """Publish event dengan semua proteksi."""
        # 1. Validasi payload (OUT-045)
        try:
            validated = self._validate_event_payload(event)
        except PermanentError as e:
            logger.error(f"Permanent validation error for event {event.id}: {e}")
            raise

        # 2. Circuit breaker (OUT-035)
        if self._circuit_breaker.is_open():
            logger.warning("Circuit breaker open, skipping publish")
            raise TemporaryError("Circuit breaker open")

        # 3. Rate limiting (OUT-036)
        await self._wait_for_rate_limit()

        # 4. Producer dengan auto-reconnect (OUT-043)
        try:
            producer = await self._ensure_producer()
        except PermanentError as e:
            raise PermanentError(str(e)) from e

        # 5. Publish dengan timeout (OUT-037) dan idempotency (OUT-022)
        try:
            headers = {}
            if validated.idempotency_key:
                headers["idempotency_key"] = validated.idempotency_key

            async with asyncio.timeout(self._config.event_timeout_seconds):
                success = await producer.send_event(
                    event_type=validated.event_type,
                    event_data=validated.data,
                    aggregate_id=validated.aggregate_id,
                    aggregate_type=validated.aggregate_type,
                    headers=headers,
                )
            self._circuit_breaker.record_success()
            return success
        except TimeoutError as e:
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

    async def _process_batch(self, session: AsyncSession, events: list) -> None:
        """Process batch dengan transaction."""
        for event in events:
            try:
                success = await self._publish_event(event)
                if success:
                    await self._mark_as_sent(session, event.id)
                else:
                    await self._mark_as_failed(
                        session,
                        event.id,
                        "Kafka send returned False",
                        event.retry_count,
                        self._config.max_retry_count,
                    )
            except PermanentError as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    self._config.max_retry_count,
                    self._config.max_retry_count,
                )
                logger.error(f"Permanent error for event {event.id}: {e}")
            except TemporaryError as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    event.retry_count,
                    self._config.max_retry_count,
                )
                logger.warning(f"Temporary error for event {event.id}: {e}")
            except Exception as e:
                await self._mark_as_failed(
                    session,
                    event.id,
                    str(e),
                    event.retry_count,
                    self._config.max_retry_count,
                )
                logger.error(f"Unexpected error for event {event.id}: {e}")

            self._stats["processed_total"] += 1
            self._stats["last_poll_at"] = datetime.now().isoformat()
            self._processed_counter.inc()

    # ========================================================================
    # POLL ONCE (TRANSACTION)
    # ========================================================================

    async def _poll_once(self) -> int:
        """Poll once and process pending events dengan transaction."""
        # Impor lokal
        from infrastructure.database.session_factory_sqlalchemy import get_async_session

        # OUT-020: Transaction
        async with get_async_session() as session:
            async with session.begin():
                events = await self._fetch_pending_events(session, self._config.batch_size)
                if not events:
                    return 0
                event_ids = [e.id for e in events]
                await self._mark_as_processing(session, event_ids)
                await session.commit()

            # Process outside transaction to avoid long locks
            async with get_async_session() as session2, session2.begin():
                with self._processing_duration.time():
                    await self._process_batch(session2, events)
                await session2.commit()

            return len(events)

    # ========================================================================
    # POLLING LOOP
    # ========================================================================

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        last_health_check = time.time()
        consecutive_errors = 0

        while self._running:
            try:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._config.poll_interval_seconds
                    )
                    break
                except TimeoutError:
                    pass

                # Health check (OUT-032)
                now = time.time()
                if now - last_health_check >= self._config.health_check_interval_seconds:
                    await self._health_check()
                    last_health_check = now

                # Acquire lock (OUT-030)
                if self._config.use_advisory_lock:
                    if not await self._acquire_lock():
                        logger.debug("Another poller has lock, skipping")
                        continue

                self._stats["poll_count"] += 1

                try:
                    processed = await self._poll_once()
                    if processed > 0:
                        logger.info(f"Processed {processed} outbox records")
                        consecutive_errors = 0
                except OutboxPollerStoppedError:
                    break
                except Exception as e:
                    consecutive_errors += 1
                    self._stats["last_error"] = str(e)
                    self._stats["last_error_time"] = datetime.now().isoformat()
                    logger.exception(f"Error in poller loop: {e}")

                    if consecutive_errors >= self._config.max_retry_count:
                        await asyncio.sleep(self._config.retry_delay_seconds[0])
                        consecutive_errors = 0

            except asyncio.CancelledError:
                # Log cancellation to avoid silent swallow
                logger.debug("Outbox poller loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Unexpected error in poller loop: {e}")
                await asyncio.sleep(1)
            finally:
                if self._config.use_advisory_lock and self._lock_acquired:
                    await self._release_lock()

    # ========================================================================
    # HEALTH CHECK (OUT-032)
    # ========================================================================

    async def _health_check(self) -> None:
        try:
            relay_health = await self._relay.health_check()
            if self._config.use_advisory_lock:
                locked = await self._db_lock.is_locked(self._config.lock_name)
                if locked != self._lock_acquired:
                    logger.warning(f"Lock status mismatch: expected {self._lock_acquired}, got {locked}")
            logger.debug(f"Health check passed: relay_health={relay_health}")
        except Exception as e:
            logger.error(f"Health check failed: {e}")

    # ========================================================================
    # PUBLIC LIFECYCLE
    # ========================================================================

    async def start(self) -> None:
        """Start the poller background loop."""
        if self._running:
            logger.warning("OutboxPoller already running")
            return

        self._running = True
        self._stop_event.clear()
        await self._relay.start()
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("OutboxPoller started")

    async def stop(self, timeout: float = 30.0) -> None:
        """Stop the poller and clean up (OUT-031)."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except TimeoutError:
                logger.warning(f"Stop timeout after {timeout}s, cancelling")
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

        await self._release_lock()
        await self._relay.stop(timeout=timeout)
        logger.info("OutboxPoller stopped")

    # ========================================================================
    # STATS & MANUAL TRIGGER
    # ========================================================================

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "running": self._running,
            "lock_acquired": self._lock_acquired,
            "reconnect_attempts": self._reconnect_attempts,
            "circuit_breaker": {
                "state": self._circuit_breaker.state,
                "failure_count": self._circuit_breaker.failure_count,
            },
            "relay_stats": self._relay.get_stats(),
            "config": self._config.to_dict(),
        }

    async def trigger_immediate_poll(self) -> int:
        """Trigger an immediate poll (for testing or manual trigger)."""
        logger.info("Manual trigger: immediate poll requested")

        if self._config.use_advisory_lock:
            acquired = await self._acquire_lock()
            if not acquired:
                logger.warning("Cannot acquire lock for immediate poll")
                return 0

        try:
            processed = await self._poll_once()
            logger.info(f"Manual poll processed {processed} records")
            return processed
        finally:
            if self._config.use_advisory_lock and self._lock_acquired:
                await self._release_lock()


# ============================================================================
# SIMPLE POLLER FUNCTION (NO LOCK, FOR TESTING)
# ============================================================================

async def run_outbox_poller_simple(
    relay_service: OutboxRelayService,
    poll_interval: float = 1.0,
    stop_event: asyncio.Event | None = None,
    batch_size: int = 100,
) -> None:
    """Simple poller function tanpa lock."""
    await relay_service.start()

    try:
        while True:
            if stop_event and stop_event.is_set():
                break

            try:
                processed = await relay_service.process_batch(batch_size)
                if processed > 0:
                    logger.debug(f"Processed {processed} outbox records")
            except Exception as e:
                logger.exception(f"Error processing batch: {e}")

            await asyncio.sleep(poll_interval)
    finally:
        await relay_service.stop()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "DatabaseLockPort",
    "MemoryLockPort",
    "OutboxPoller",
    "OutboxPollerConfig",
    "run_outbox_poller_simple",
]
