# subscriber_application.py - Hardened version with complete implementation and global subscribers registration

#!/usr/bin/env python3

"""
Module: subscriber_application.py
Layer: 5 - Application / Events

Responsibility:
    Event subscriber untuk application layer. Menerima event dari message broker (Kafka)
    dan mengeksekusi handler yang terdaftar.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from application.events.handler_registry import event_handler_registry
from application.events.publisher_application import EventEnvelope
from application.events.global_event_subscribers import register_global_subscribers

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class KafkaConsumerPort(Protocol):
    async def subscribe(self, topics: list[str]) -> None: ...
    async def poll(self, timeout_ms: int, max_records: int) -> list[Any]: ...
    async def commit(self) -> None: ...
    async def commit_offset(self, topic: str, partition: int, offset: int) -> None: ...
    async def close(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class RedisClientPort(Protocol):
    async def exists(self, key: str) -> bool: ...
    async def get(self, key: str) -> str | None: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def expire(self, key: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def ping(self) -> bool: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...


class DeadLetterStorePort(Protocol):
    async def store(
        self,
        envelope: EventEnvelope,
        error: str,
        retry_count: int,
        topic: str,
        partition: int,
        offset: int,
    ) -> None: ...
    async def get_failed_count(self, event_id: UUID) -> int: ...
    async def mark_resolved(self, event_id: UUID) -> None: ...


class MetricsPort(Protocol):
    def events_consumed_total(self, event_type: str, status: str) -> None: ...
    def events_processed_total(self, event_type: str) -> None: ...
    def events_processing_errors_total(self, event_type: str, error_type: str) -> None: ...
    def events_processing_latency_seconds(self, latency: float) -> None: ...
    def dead_letter_events_total(self, event_type: str) -> None: ...


# ============================================================================
# ENUMS
# ============================================================================


class ProcessingStatus(Enum):
    SUCCESS = "success"
    RETRYABLE_ERROR = "retryable_error"
    FATAL_ERROR = "fatal_error"
    DUPLICATE = "duplicate"
    SKIPPED = "skipped"


class SubscriptionMode(Enum):
    KAFKA = "kafka"
    INTERNAL = "internal"
    HYBRID = "hybrid"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class EventProcessingError(Exception):
    pass


class EventProcessingRetryableError(EventProcessingError):
    pass


class EventProcessingFatalError(EventProcessingError):
    pass


class DuplicateEventError(EventProcessingError):
    pass


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass
class SubscriptionConfig:
    topics: list[str]
    group_id: str
    auto_offset_reset: str = "earliest"
    enable_auto_commit: bool = False
    max_poll_records: int = 100
    session_timeout_ms: int = 30000
    heartbeat_interval_ms: int = 3000
    max_poll_interval_ms: int = 300000
    retry_backoff_ms: int = 100
    enable_idempotency: bool = True
    idempotency_ttl_seconds: int = 86400 * 7
    dead_letter_topic: str = "erp.dead_letter_events"
    max_retry_attempts: int = 3
    worker_count: int = 4
    prefetch_count: int = 10
    processing_timeout_seconds: int = 60


# ============================================================================
# IDEMPOTENCY CHECKER
# ============================================================================


class IdempotencyChecker:
    def __init__(self, redis_client: RedisClientPort, ttl_seconds: int = 86400 * 7):
        self._redis = redis_client
        self._ttl = ttl_seconds

    async def is_processed(self, idempotency_key: str) -> bool:
        if not idempotency_key:
            return False
        key = f"event:processed:{idempotency_key}"
        return await self._redis.exists(key)

    async def mark_processed(self, idempotency_key: str) -> None:
        if idempotency_key:
            key = f"event:processed:{idempotency_key}"
            await self._redis.setex(key, self._ttl, "1")


# ============================================================================
# SIMPLE RETRY POLICY
# ============================================================================


def exponential_backoff(attempt: int, base_delay: float = 0.5, max_delay: float = 10.0) -> float:
    return min(base_delay * (2**attempt), max_delay)


class SimpleRetryPolicy:
    def __init__(self, max_attempts: int = 3, base_delay: float = 0.5, max_delay: float = 10.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.attempts = 0

    async def execute(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_attempts):
            self.attempts = attempt + 1
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_attempts - 1:
                    delay = exponential_backoff(attempt, self.base_delay, self.max_delay)
                    await asyncio.sleep(delay)
        raise last_error


# ============================================================================
# EVENT PROCESSOR WORKER
# ============================================================================


class EventProcessorWorker:
    def __init__(
        self,
        worker_id: int,
        handler_registry,
        idempotency_checker: IdempotencyChecker | None,
        dead_letter_store: DeadLetterStorePort | None,
        retry_policy: SimpleRetryPolicy,
        processing_timeout: int,
        metrics: MetricsPort,
    ):
        self.worker_id = worker_id
        self._registry = handler_registry
        self._idempotency = idempotency_checker
        self._dead_letter = dead_letter_store
        self._retry_policy = retry_policy
        self._processing_timeout = processing_timeout
        self._metrics = metrics
        self._running = False
        self._task: asyncio.Task | None = None
        self._queue: asyncio.Queue | None = None
        self._processed_count = 0
        self._error_count = 0
        self._last_processed_at: datetime | None = None

    def set_queue(self, queue: asyncio.Queue) -> None:
        self._queue = queue

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info(f"EventProcessorWorker-{self.worker_id} started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info(f"EventProcessorWorker-{self.worker_id} stopped")

    async def _run(self) -> None:
        while self._running and self._queue is not None:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_item(item)
                self._processed_count += 1
                self._last_processed_at = datetime.now(UTC)
            except Exception as e:
                self._error_count += 1
                logger.exception(f"Worker {self.worker_id} unhandled error: {e}")
            finally:
                self._queue.task_done()

    async def _process_item(self, item: tuple[Any, EventEnvelope]) -> None:
        message, envelope = item
        start_time = time.perf_counter()

        try:
            if self._idempotency and envelope.idempotency_key:
                if await self._idempotency.is_processed(envelope.idempotency_key):
                    logger.info(f"Duplicate event {envelope.event_type} skipped")
                    if self._metrics:
                        self._metrics.events_consumed_total(envelope.event_type, "duplicate")
                    return

            handlers = self._registry.get_handlers(envelope.event_type)
            if not handlers:
                logger.warning(f"No handler for event {envelope.event_type}")
                if self._metrics:
                    self._metrics.events_consumed_total(envelope.event_type, "no_handler")
                return

            async def _process():
                for handler in handlers:
                    await self._execute_handler(handler, envelope)

            await self._retry_policy.execute(_process)

            if self._idempotency and envelope.idempotency_key:
                await self._idempotency.mark_processed(envelope.idempotency_key)

            latency = (time.perf_counter() - start_time) * 1000
            if self._metrics:
                self._metrics.events_consumed_total(envelope.event_type, "success")
                self._metrics.events_processed_total(envelope.event_type)
                self._metrics.events_processing_latency_seconds(latency / 1000)

            logger.info(f"Event {envelope.event_type} processed in {latency:.2f}ms")

        except DuplicateEventError as e:
            if self._metrics:
                self._metrics.events_consumed_total(envelope.event_type, "duplicate")
            logger.info(f"Duplicate event {envelope.event_type}: {e}")
        except EventProcessingRetryableError as e:
            if self._metrics:
                self._metrics.events_processing_errors_total(envelope.event_type, "retryable")
            if self._dead_letter:
                topic = getattr(message, "topic", "unknown")
                partition = getattr(message, "partition", 0)
                offset = getattr(message, "offset", 0)
                await self._dead_letter.store(
                    envelope, str(e), self._retry_policy.attempts, topic, partition, offset
                )
            logger.error(f"Retryable error: {e}")
        except EventProcessingFatalError as e:
            if self._metrics:
                self._metrics.events_processing_errors_total(envelope.event_type, "fatal")
            if self._dead_letter:
                topic = getattr(message, "topic", "unknown")
                partition = getattr(message, "partition", 0)
                offset = getattr(message, "offset", 0)
                await self._dead_letter.store(envelope, str(e), 0, topic, partition, offset)
            logger.error(f"Fatal error: {e}")
        except Exception as e:
            if self._metrics:
                self._metrics.events_processing_errors_total(envelope.event_type, "unknown")
            logger.exception(f"Unexpected error: {e}")
            raise

    async def _execute_handler(self, handler, envelope: EventEnvelope) -> None:
        if asyncio.iscoroutinefunction(handler):
            await asyncio.wait_for(handler(envelope), timeout=self._processing_timeout)
        else:
            loop = asyncio.get_event_loop()
            await asyncio.wait_for(
                loop.run_in_executor(None, handler, envelope), timeout=self._processing_timeout
            )

    def get_stats(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "processed": self._processed_count,
            "errors": self._error_count,
            "last_processed_at": self._last_processed_at.isoformat()
            if self._last_processed_at
            else None,
        }


# ============================================================================
# APPLICATION EVENT SUBSCRIBER
# ============================================================================


class ApplicationEventSubscriber:
    def __init__(
        self,
        config: SubscriptionConfig,
        kafka_consumer: KafkaConsumerPort,
        redis_client: RedisClientPort | None,
        dead_letter_store: DeadLetterStorePort | None,
        idempotency_checker: IdempotencyChecker | None,
        metrics: MetricsPort,
        mode: SubscriptionMode = SubscriptionMode.KAFKA,
    ):
        self._config = config
        self._kafka_consumer = kafka_consumer
        self._redis = redis_client
        self._dead_letter = dead_letter_store
        self._idempotency = idempotency_checker
        self._metrics = metrics
        self._mode = mode
        self._workers: list[EventProcessorWorker] = []
        self._queue: asyncio.Queue | None = None
        self._consumer_task: asyncio.Task | None = None
        self._running = False
        self._last_commit_time = datetime.now(UTC)
        self._stats = {
            "messages_received": 0,
            "messages_committed": 0,
            "last_error": None,
            "last_error_time": None,
        }
        # Register global subscribers once
        self._subscribers_registered = False

    async def start(self) -> None:
        self._running = True
        self._queue = asyncio.Queue(maxsize=self._config.prefetch_count * self._config.worker_count)

        # Register global event subscribers if not already done
        if not self._subscribers_registered:
            register_global_subscribers()
            self._subscribers_registered = True

        retry_policy = SimpleRetryPolicy(
            max_attempts=self._config.max_retry_attempts, base_delay=0.5, max_delay=10.0
        )

        for i in range(self._config.worker_count):
            worker = EventProcessorWorker(
                worker_id=i,
                handler_registry=event_handler_registry,
                idempotency_checker=self._idempotency,
                dead_letter_store=self._dead_letter,
                retry_policy=retry_policy,
                processing_timeout=self._config.processing_timeout_seconds,
                metrics=self._metrics,
            )
            worker.set_queue(self._queue)
            await worker.start()
            self._workers.append(worker)

        if self._mode in (SubscriptionMode.KAFKA, SubscriptionMode.HYBRID):
            await self._kafka_consumer.subscribe(self._config.topics)
            self._consumer_task = asyncio.create_task(self._consume_kafka())

        logger.info(
            f"ApplicationEventSubscriber started (mode={self._mode.value}, workers={self._config.worker_count})"
        )

    async def stop(self, drain_timeout: int = 30) -> None:
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task
        if self._queue:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=drain_timeout)
            except TimeoutError:
                logger.warning(f"Queue drain timeout after {drain_timeout}s")
        await asyncio.gather(*[w.stop() for w in self._workers])
        await self._kafka_consumer.stop()
        logger.info("ApplicationEventSubscriber stopped")

    async def _consume_kafka(self) -> None:
        while self._running:
            try:
                messages = await self._kafka_consumer.poll(
                    timeout_ms=1000, max_records=self._config.max_poll_records
                )
                if not messages:
                    await self._maybe_commit()
                    continue
                for msg in messages:
                    await self._process_kafka_message(msg)
                await self._maybe_commit(force=True)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Kafka consumer error: {e}")
                self._stats["last_error"] = str(e)
                self._stats["last_error_time"] = datetime.now(UTC)
                await asyncio.sleep(1)

    async def _process_kafka_message(self, message: Any) -> None:
        try:
            payload = json.loads(message.value)
            envelope = EventEnvelope.from_json(message.value)
            self._stats["messages_received"] += 1

            try:
                await asyncio.wait_for(self._queue.put((message, envelope)), timeout=5.0)
            except TimeoutError:
                logger.error("Queue full, message will be retried by Kafka")
                raise
        except Exception as e:
            logger.error(f"Failed to parse Kafka message: {e}")
            if self._metrics:
                self._metrics.events_processing_errors_total("parse_error", "fatal")
            await self._kafka_consumer.commit_offset(
                getattr(message, "topic", "unknown"),
                getattr(message, "partition", 0),
                getattr(message, "offset", 0) + 1,
            )

    async def _maybe_commit(self, force: bool = False) -> None:
        if not self._config.enable_auto_commit and not force:
            return
        now = datetime.now(UTC)
        if force or (now - self._last_commit_time).total_seconds() > 5:
            try:
                await self._kafka_consumer.commit()
                self._last_commit_time = now
                self._stats["messages_committed"] = self._stats["messages_received"]
            except Exception as e:
                logger.warning(f"Commit failed: {e}")

    async def publish_internal(self, envelope: EventEnvelope) -> None:
        if self._mode == SubscriptionMode.KAFKA:
            logger.debug("Internal publish ignored in KAFKA mode")
            return
        fake_msg = type(
            "FakeMessage",
            (),
            {
                "topic": "internal",
                "partition": 0,
                "offset": 0,
                "key": None,
                "value": envelope.to_json(),
                "timestamp": datetime.now(UTC),
            },
        )()
        if self._queue:
            await self._queue.put((fake_msg, envelope))

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "workers": [w.get_stats() for w in self._workers],
            "queue_size": self._queue.qsize() if self._queue else 0,
            "running": self._running,
            "mode": self._mode.value,
            "topics": self._config.topics,
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================


async def create_event_subscriber(
    kafka_consumer: KafkaConsumerPort,
    redis_client: RedisClientPort | None,
    dead_letter_store: DeadLetterStorePort | None,
    metrics: MetricsPort,
    topics: list[str] | None = None,
    group_id: str = "erp-accounting-group",
    mode: str = "kafka",
    worker_count: int = 4,
) -> ApplicationEventSubscriber:
    """Factory untuk membuat ApplicationEventSubscriber."""
    config = SubscriptionConfig(
        topics=topics
        or [
            "erp.accounting.journal",
            "erp.accounting.ar",
            "erp.accounting.ap",
            "erp.inventory.movement",
        ],
        group_id=group_id,
        worker_count=worker_count,
    )
    mode_enum = {
        "kafka": SubscriptionMode.KAFKA,
        "internal": SubscriptionMode.INTERNAL,
        "hybrid": SubscriptionMode.HYBRID,
    }.get(mode, SubscriptionMode.KAFKA)

    idempotency_checker = None
    if redis_client and config.enable_idempotency:
        idempotency_checker = IdempotencyChecker(redis_client, config.idempotency_ttl_seconds)

    return ApplicationEventSubscriber(
        config=config,
        kafka_consumer=kafka_consumer,
        redis_client=redis_client,
        dead_letter_store=dead_letter_store,
        idempotency_checker=idempotency_checker,
        metrics=metrics,
        mode=mode_enum,
    )


__all__ = [
    "ApplicationEventSubscriber",
    "DuplicateEventError",
    "EventProcessingError",
    "EventProcessingFatalError",
    "EventProcessingRetryableError",
    "IdempotencyChecker",
    "MetricsPort",
    "SubscriptionConfig",
    "SubscriptionMode",
    "create_event_subscriber",
]