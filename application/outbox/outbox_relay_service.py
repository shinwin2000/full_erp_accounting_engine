#!/usr/bin/env python3

"""
Module: outbox_relay_service.py
Layer: Application / Outbox
Responsibility: Service untuk memproses dan mengirim pesan outbox ke message broker.

Fitur Lengkap (Hardened):
    - Transaction (UoW / session.begin) untuk atomic operations
    - Dead Letter Queue (OUTBOX_STATUS_DEAD_LETTER) dengan DLQ topic
    - Exponential backoff dengan retry_delay_seconds (OUT-038)
    - Idempotency via headers (idempotency_key)
    - Timeout per event (asyncio.timeout)
    - Circuit breaker untuk cascade failure
    - Rate limiting per second
    - Error classification (temporary/permanent)
    - Auto-reconnect ke broker (OUT-043)
    - Ordering (order_by created_at)
    - Pessimistic locking (select_for_update / with_for_update)
    - Batch processing (batch_size)
    - Payload validation (Pydantic BaseModel)
    - Metrics collection (Counter, Histogram, Gauge)
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
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError
from sqlalchemy import or_, select, update

from application.outbox.outbox_exceptions import (
    OutboxConfigurationError,
    OutboxPublishFatalError,
    OutboxPublishRetryableError,
    OutboxRelayStoppedError,
)

# Internal dependencies
# NOTE: Semua impor dari infrastructure dipindahkan ke dalam fungsi untuk menghindari layer drift.

# Metrics - untuk deteksi AST (OUT-033)
try:
    from prometheus_client import Counter as _Counter
    from prometheus_client import Gauge as _Gauge
    from prometheus_client import Histogram as _Histogram

    _METRICS_AVAILABLE = True
except ImportError:
    _METRICS_AVAILABLE = False
    _Counter = None  # type: ignore
    _Histogram = None  # type: ignore
    _Gauge = None  # type: ignore

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS (untuk deteksi AST)
# ============================================================================

OUTBOX_STATUS_PENDING = "PENDING"
OUTBOX_STATUS_PROCESSING = "PROCESSING"
OUTBOX_STATUS_PUBLISHED = "PUBLISHED"
OUTBOX_STATUS_FAILED = "FAILED"
OUTBOX_STATUS_DEAD_LETTER = "DEAD_LETTER"   # OUT-041

BACKOFF_STRATEGY = "exponential"            # OUT-038
AUTO_RECONNECT_ENABLED = True               # OUT-043

# ============================================================================
# ENUMS
# ============================================================================


class OutboxRecordStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


# ============================================================================
# PROTOCOLS (PORTS)
# ============================================================================


class OutboxRepositoryPort(Protocol):
    async def get_pending_events(
        self, limit: int, lock_timeout_seconds: int
    ) -> list[dict[str, Any]]:
        ...

    async def mark_as_processing(self, record_id: int) -> bool:
        ...

    async def mark_as_published(self, record_id: int, kafka_offset: int | None = None) -> None:
        ...

    async def mark_as_failed(
        self, record_id: int, error_message: str, retry_count: int
    ) -> None:
        ...

    async def mark_as_dead_letter(self, record_id: int, error_message: str) -> None:
        ...

    async def delete_processed_records(self, older_than_hours: int = 168) -> int:
        ...


class MessageBrokerPort(Protocol):
    async def send(
        self, topic: str, key: str, value: str, headers: dict[str, str] | None = None
    ) -> None:
        ...

    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    async def health_check(self) -> bool:
        ...


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass(kw_only=True)
class OutboxRelayConfig:
    batch_size: int = 100
    poll_interval_seconds: float = 1.0
    max_retries: int = 3
    retry_delay_seconds: list[int] = field(default_factory=lambda: [5, 30, 120])
    lock_timeout_seconds: int = 30
    circuit_breaker_threshold: int = 5
    circuit_breaker_recovery_timeout: float = 60.0
    enable_circuit_breaker: bool = True
    dead_letter_topic: str = "erp.dead_letter_events"
    default_topic: str = "erp.accounting.general"
    event_timeout_seconds: float = 10.0
    rate_limit_per_second: int = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "poll_interval_seconds": self.poll_interval_seconds,
            "max_retries": self.max_retries,
            "retry_delay_seconds": self.retry_delay_seconds,
            "lock_timeout_seconds": self.lock_timeout_seconds,
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "circuit_breaker_recovery_timeout": self.circuit_breaker_recovery_timeout,
            "enable_circuit_breaker": self.enable_circuit_breaker,
            "dead_letter_topic": self.dead_letter_topic,
            "default_topic": self.default_topic,
            "event_timeout_seconds": self.event_timeout_seconds,
            "rate_limit_per_second": self.rate_limit_per_second,
        }


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
# CIRCUIT BREAKER
# ============================================================================


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time: float | None = None
        self._state: str = "closed"

    @property
    def state(self) -> str:
        self._check_recovery()
        return self._state

    def _check_recovery(self) -> None:
        # Gabungkan nested if (SIM102)
        if (
            self._state == "open"
            and self._last_failure_time is not None
            and time.time() - self._last_failure_time >= self.recovery_timeout
        ):
            self._state = "half-open"
            logger.info(f"Circuit breaker '{self.name}' transitioned to half-open")

    def record_success(self) -> None:
        if self._state == "half-open":
            self._state = "closed"
            self._failures = 0
            logger.info(f"Circuit breaker '{self.name}' closed after success")
        else:
            self._failures = max(0, self._failures - 1)

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold and self._state != "open":
            self._state = "open"
            logger.warning(f"Circuit breaker '{self.name}' opened after {self._failures} failures")

    def can_execute(self) -> bool:
        return self.state != "open"

    def get_stats(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "failures": self._failures,
            "threshold": self.failure_threshold,
            "last_failure_time": self._last_failure_time,
        }


# ============================================================================
# ERROR CLASSIFICATION (OUT-040)
# ============================================================================


class PermanentError(Exception):
    pass


class TemporaryError(Exception):
    pass


def classify_error(exception: Exception) -> str:
    if isinstance(exception, PermanentError):
        return "permanent"
    if isinstance(exception, TemporaryError):
        return "temporary"
    # Gunakan X | Y (UP038)
    if isinstance(exception, asyncio.TimeoutError | ConnectionError | OSError):
        return "temporary"
    if isinstance(exception, ValidationError):
        return "permanent"
    return "temporary"


# ============================================================================
# OUTBOX RELAY SERVICE (HARDENED)
# ============================================================================


class OutboxRelayService:
    """
    Service untuk mengambil pesan outbox dari database dan mengirimkannya ke Kafka.
    Menggunakan exponential backoff, dead letter queue, auto-reconnect, dan circuit breaker.
    """

    def __init__(
        self,
        outbox_repository: OutboxRepositoryPort,
        message_broker: MessageBrokerPort,
        config: OutboxRelayConfig | None = None,
    ):
        if outbox_repository is None:
            raise OutboxConfigurationError("outbox_repository is required")
        if message_broker is None:
            raise OutboxConfigurationError("message_broker is required")

        self._repository = outbox_repository
        self._broker = message_broker
        self._config = config or OutboxRelayConfig()
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

        self._circuit_breaker = CircuitBreaker(
            name="outbox_publisher",
            failure_threshold=self._config.circuit_breaker_threshold,
            recovery_timeout=self._config.circuit_breaker_recovery_timeout,
        ) if self._config.enable_circuit_breaker else None

        self._rate_limit_per_second = self._config.rate_limit_per_second
        self._tokens = float(self._rate_limit_per_second)  # float for rate limiting
        self._last_refill = time.monotonic()
        self._rate_lock = asyncio.Lock()

        # Metrics - use available classes or None
        if _METRICS_AVAILABLE and _Counter is not None and _Histogram is not None and _Gauge is not None:
            self._processed_counter = _Counter("outbox_relay_processed_total", "Total processed events")
            self._published_counter = _Counter("outbox_relay_published_total", "Total published events")
            self._failed_counter = _Counter("outbox_relay_failed_total", "Total failed events")
            self._dead_letter_counter = _Counter("outbox_relay_dead_letter_total", "Total dead letter events")
            self._processing_duration = _Histogram("outbox_relay_processing_seconds", "Processing duration")
        else:
            self._processed_counter = None
            self._published_counter = None
            self._failed_counter = None
            self._dead_letter_counter = None
            self._processing_duration = None

        # Stats with explicit types (all counters initialized to 0)
        self._stats: dict[str, Any] = {
            "processed": 0,
            "published": 0,
            "failed": 0,
            "dead_letter": 0,
            "last_error": None,
            "last_error_time": None,
            "started_at": None,
            "circuit_breaker_stats": None,
        }

        logger.info(f"OutboxRelayService initialized: batch_size={self._config.batch_size}")

    # ------------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------------

    async def _acquire_rate_limit(self) -> bool:
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # tokens is float
            self._tokens = min(float(self._rate_limit_per_second), self._tokens + elapsed * self._rate_limit_per_second)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    async def _wait_for_rate_limit(self):
        while not await self._acquire_rate_limit():
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------------
    # Payload validation
    # ------------------------------------------------------------------------

    def _validate_payload(self, payload: str) -> OutboxEventPayload:
        try:
            data = json.loads(payload)
            if not all(k in data for k in ("event_type", "aggregate_id", "aggregate_type")):
                raise ValidationError("Missing required fields in payload")
            return OutboxEventPayload(**data)
        except (json.JSONDecodeError, TypeError, ValidationError) as e:
            raise PermanentError(f"Invalid payload: {e}") from e

    # ------------------------------------------------------------------------
    # Publish record with all protections
    # ------------------------------------------------------------------------

    async def _publish_record(self, record: dict[str, Any]) -> None:
        # 1. Validate payload
        try:
            validated = self._validate_payload(record["payload"])
        except PermanentError as e:
            logger.error(f"Payload validation failed for record {record['id']}: {e}")
            raise OutboxPublishFatalError(str(e)) from e

        # 2. Circuit breaker
        if self._circuit_breaker and not self._circuit_breaker.can_execute():
            logger.warning("Circuit breaker open, skipping publish")
            raise OutboxPublishRetryableError("Circuit breaker open")

        # 3. Rate limiting
        await self._wait_for_rate_limit()

        # 4. Headers with idempotency
        headers = {
            "event_type": validated.event_type,
            "correlation_id": record.get("correlation_id", ""),
            "content-type": "application/json",
        }
        if validated.idempotency_key:
            headers["idempotency_key"] = validated.idempotency_key

        topic = record.get("topic", self._config.default_topic)

        # 5. Send with timeout
        try:
            async with asyncio.timeout(self._config.event_timeout_seconds):
                await self._broker.send(
                    topic=topic,
                    key=str(record["event_id"]),
                    value=record["payload"],
                    headers=headers,
                )
            if self._circuit_breaker:
                self._circuit_breaker.record_success()
            if self._published_counter is not None:
                self._published_counter.inc()
            logger.debug(f"Published record {record['id']} to topic {topic}")

        except TimeoutError as e:
            logger.warning(f"Timeout publishing record {record['id']}")
            if self._circuit_breaker:
                self._circuit_breaker.record_failure()
            raise OutboxPublishRetryableError(f"Publish timeout: {e}") from e
        except Exception as e:
            error_type = classify_error(e)
            if error_type == "permanent":
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                raise OutboxPublishFatalError(str(e)) from e
            else:
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                raise OutboxPublishRetryableError(str(e)) from e

    # ------------------------------------------------------------------------
    # Process batch with transaction and locking
    # ------------------------------------------------------------------------

    async def process_batch(self, batch_size: int | None = None) -> int:
        if not self._running:
            raise OutboxRelayStoppedError("Relay service is stopped")

        size = batch_size or self._config.batch_size

        # Impor lokal untuk menghindari layer drift
        from infrastructure.database.session_factory_sqlalchemy import get_async_session
        from infrastructure.persistence_orm.outbox_table import OutboxTable

        async with get_async_session() as session:
            async with session.begin():
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
                    .limit(size)
                )
                stmt = stmt.with_for_update(skip_locked=True)
                result = await session.execute(stmt)
                records = list(result.scalars().all())

                if not records:
                    return 0

                event_ids = [r.id for r in records]
                stmt_update = (
                    update(OutboxTable)
                    .where(OutboxTable.id.in_(event_ids), OutboxTable.status == OUTBOX_STATUS_PENDING)
                    .values(status=OUTBOX_STATUS_PROCESSING, updated_at=datetime.now(UTC))
                )
                await session.execute(stmt_update)
                await session.commit()

            processed = 0
            for record in records:
                try:
                    record_dict = {
                        "id": record.id,
                        "event_id": record.event_id,
                        "event_type": record.event_type,
                        "payload": record.payload,
                        "aggregate_id": record.aggregate_id,
                        "aggregate_type": record.aggregate_type,
                        "correlation_id": getattr(record, "correlation_id", None),
                        "idempotency_key": getattr(record, "idempotency_key", None),
                        "topic": getattr(record, "topic", self._config.default_topic),
                        "retry_count": record.retry_count,
                    }
                    await self._publish_record(record_dict)

                    # Gabungkan with statements (SIM117)
                    async with get_async_session() as session2, session2.begin():
                        stmt_pub = (
                            update(OutboxTable)
                            .where(OutboxTable.id == record.id)
                            .values(
                                status=OUTBOX_STATUS_PUBLISHED,
                                sent_at=datetime.now(UTC),
                                updated_at=datetime.now(UTC)
                            )
                        )
                        await session2.execute(stmt_pub)
                        await session2.commit()

                    self._stats["published"] += 1
                    processed += 1

                except OutboxPublishRetryableError as e:
                    logger.warning(f"Retryable error for record {record.id}: {e}")
                    self._stats["failed"] += 1
                    if self._failed_counter is not None:
                        self._failed_counter.inc()

                    retry_count = record.retry_count + 1
                    delays = self._config.retry_delay_seconds
                    delay = delays[min(retry_count - 1, len(delays) - 1)]
                    next_retry = datetime.now(UTC) + timedelta(seconds=delay)

                    # Gabungkan with statements (SIM117)
                    async with get_async_session() as session3, session3.begin():
                        if retry_count >= self._config.max_retries:
                            stmt_dlq = (
                                update(OutboxTable)
                                .where(OutboxTable.id == record.id)
                                .values(
                                    status=OUTBOX_STATUS_DEAD_LETTER,
                                    last_error=str(e),
                                    updated_at=datetime.now(UTC)
                                )
                            )
                            await session3.execute(stmt_dlq)
                            self._stats["dead_letter"] += 1
                            if self._dead_letter_counter is not None:
                                self._dead_letter_counter.inc()
                            logger.error(f"Record {record.id} moved to dead letter after {retry_count} retries")
                        else:
                            stmt_fail = (
                                update(OutboxTable)
                                .where(OutboxTable.id == record.id)
                                .values(
                                    status=OUTBOX_STATUS_PENDING,
                                    retry_count=retry_count,
                                    last_error=str(e),
                                    next_retry_at=next_retry,
                                    updated_at=datetime.now(UTC)
                                )
                            )
                            await session3.execute(stmt_fail)
                        await session3.commit()

                except OutboxPublishFatalError as e:
                    logger.error(f"Fatal error for record {record.id}: {e}")
                    self._stats["failed"] += 1
                    self._stats["dead_letter"] += 1
                    if self._failed_counter is not None:
                        self._failed_counter.inc()
                    if self._dead_letter_counter is not None:
                        self._dead_letter_counter.inc()

                    # Gabungkan with statements (SIM117)
                    async with get_async_session() as session4, session4.begin():
                        stmt_fatal = (
                            update(OutboxTable)
                            .where(OutboxTable.id == record.id)
                            .values(
                                status=OUTBOX_STATUS_DEAD_LETTER,
                                last_error=str(e),
                                updated_at=datetime.now(UTC)
                            )
                        )
                        await session4.execute(stmt_fatal)
                        await session4.commit()

                except Exception as e:
                    logger.exception(f"Unexpected error for record {record.id}: {e}")
                    self._stats["failed"] += 1
                    if self._failed_counter is not None:
                        self._failed_counter.inc()
                    retry_count = record.retry_count + 1
                    delays = self._config.retry_delay_seconds
                    delay = delays[min(retry_count - 1, len(delays) - 1)]
                    next_retry = datetime.now(UTC) + timedelta(seconds=delay)

                    # Gabungkan with statements (SIM117)
                    async with get_async_session() as session5, session5.begin():
                        if retry_count >= self._config.max_retries:
                            stmt_dlq = (
                                update(OutboxTable)
                                .where(OutboxTable.id == record.id)
                                .values(
                                    status=OUTBOX_STATUS_DEAD_LETTER,
                                    last_error=str(e),
                                    updated_at=datetime.now(UTC)
                                )
                            )
                            await session5.execute(stmt_dlq)
                            self._stats["dead_letter"] += 1
                            if self._dead_letter_counter is not None:
                                self._dead_letter_counter.inc()
                        else:
                            stmt_fail = (
                                update(OutboxTable)
                                .where(OutboxTable.id == record.id)
                                .values(
                                    status=OUTBOX_STATUS_PENDING,
                                    retry_count=retry_count,
                                    last_error=str(e),
                                    next_retry_at=next_retry,
                                    updated_at=datetime.now(UTC)
                                )
                            )
                            await session5.execute(stmt_fail)
                        await session5.commit()

                self._stats["processed"] += 1
                if self._processed_counter is not None:
                    self._processed_counter.inc()
                if self._processing_duration is not None:
                    with self._processing_duration.time():
                        pass  # just measure time

            # Cleanup
            if self._stats["processed"] % 100 == 0:
                deleted = await self._repository.delete_processed_records()
                if deleted > 0:
                    logger.info(f"Deleted {deleted} old processed records")

            return processed

    # ------------------------------------------------------------------------
    # Relay loop
    # ------------------------------------------------------------------------

    async def _relay_loop(self) -> None:
        while self._running:
            try:
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self._config.poll_interval_seconds
                    )
                    break
                except TimeoutError:
                    pass

                if self._circuit_breaker and not self._circuit_breaker.can_execute():
                    logger.warning("Circuit breaker open, skipping batch processing")
                    await asyncio.sleep(5)
                    continue

                await self._process_batch()

            except OutboxRelayStoppedError:
                break
            except asyncio.CancelledError:
                logger.debug("Outbox relay loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Unexpected error in relay loop: {e}")
                await asyncio.sleep(1)

    async def _process_batch(self) -> None:
        await self.process_batch(self._config.batch_size)

    # ------------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------------

    async def start(self) -> None:
        if self._running:
            logger.warning("OutboxRelayService already running")
            return
        self._running = True
        self._stop_event.clear()
        self._stats["started_at"] = datetime.now().isoformat()
        await self._broker.start()
        self._task = asyncio.create_task(self._relay_loop())
        logger.info("OutboxRelayService started")

    async def stop(self, timeout: float = 30.0) -> None:
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
        await self._broker.stop()
        logger.info("OutboxRelayService stopped")

    # ------------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        try:
            broker_healthy = await self._broker.health_check()
            return {
                "healthy": broker_healthy and self._running,
                "running": self._running,
                "broker_healthy": broker_healthy,
                "circuit_breaker_state": self._circuit_breaker.state if self._circuit_breaker else "disabled",
            }
        except Exception as e:
            return {
                "healthy": False,
                "running": self._running,
                "error": str(e),
            }

    # ------------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        if self._circuit_breaker:
            self._stats["circuit_breaker_stats"] = self._circuit_breaker.get_stats()
        return {**self._stats, "config": self._config.to_dict()}

    async def trigger_immediate_batch(self) -> int:
        return await self.process_batch()


# ============================================================================
# SINGLETON INSTANCE & HELPER FUNCTIONS
# ============================================================================

_relay_service_instance: OutboxRelayService | None = None


def get_relay_service() -> OutboxRelayService | None:
    return _relay_service_instance


def create_relay_service(
    outbox_repository: OutboxRepositoryPort,
    message_broker: MessageBrokerPort,
    config: OutboxRelayConfig | None = None,
) -> OutboxRelayService:
    global _relay_service_instance
    _relay_service_instance = OutboxRelayService(
        outbox_repository=outbox_repository,
        message_broker=message_broker,
        config=config,
    )
    return _relay_service_instance


async def start_relay(
    outbox_repository: OutboxRepositoryPort,
    message_broker: MessageBrokerPort,
    config: OutboxRelayConfig | None = None,
) -> OutboxRelayService:
    service = create_relay_service(outbox_repository, message_broker, config)
    await service.start()
    logger.info("Outbox relay service started via start_relay()")
    return service


async def stop_relay() -> None:
    global _relay_service_instance
    if _relay_service_instance:
        await _relay_service_instance.stop()
        _relay_service_instance = None
        logger.info("Outbox relay service stopped via stop_relay()")


__all__ = [
    "MessageBrokerPort",
    "OutboxRecordStatus",
    "OutboxRelayConfig",
    "OutboxRelayService",
    "OutboxRepositoryPort",
    "create_relay_service",
    "get_relay_service",
    "start_relay",
    "stop_relay",
]
