# publisher_application.py - Hardened version (fixing dataclass syntax error)

#!/usr/bin/env python3

"""
Module: publisher_application.py
Layer: 5 - Application / Events

Responsibility:
    Event publisher untuk application layer. Menerbitkan domain events
    dan integration events ke message broker (Kafka) melalui transactional
    outbox pattern.

Perbaikan presisi (MNY-003):
    - Semua nilai moneter (Decimal) diserialisasi sebagai string, bukan float.
    - Menghapus konversi float() pada nilai moneter di _event_to_dict dan _json_default.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, Protocol
from uuid import UUID, uuid4

from application.events.handler_registry import event_handler_registry

logger = logging.getLogger(__name__)


# ============================================================================
# PROTOCOLS
# ============================================================================


class MessageBrokerPort(Protocol):
    async def send(
        self, topic: str, key: str, value: str, headers: dict[str, str] | None = None
    ) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class OutboxPort(Protocol):
    async def enqueue(
        self,
        event_id: UUID,
        event_type: str,
        payload: str,
        topic: str,
        correlation_id: str,
        idempotency_key: str | None = None,
    ) -> int: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...


class CachePort(Protocol):
    async def exists(self, key: str) -> bool: ...
    async def setex(self, key: str, ttl: int, value: str) -> None: ...
    async def expire(self, key: str, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def get(self, key: str) -> str | None: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...


# ============================================================================
# ENUMS
# ============================================================================


class PublishMode(Enum):
    SYNC = auto()
    ASYNC = auto()
    HYBRID = auto()


class PublishResult(Enum):
    SUCCESS = auto()
    RETRYABLE_FAILURE = auto()
    NON_RETRYABLE_FAILURE = auto()
    CIRCUIT_OPEN = auto()
    OUTBOX_ENQUEUED = auto()


# ============================================================================
# EXCEPTIONS
# ============================================================================


class EventPublishError(Exception):
    pass


class EventPublishRetryableError(EventPublishError):
    pass


class EventPublishFatalError(EventPublishError):
    pass


class CircuitBreakerOpenError(EventPublishError):
    pass


# ============================================================================
# EVENT ENVELOPE (FIXED - removed frozen=True causing conflict)
# ============================================================================


@dataclass(kw_only=True)
class EventEnvelope:
    """Envelope untuk event yang dipublikasikan."""

    event: Any
    event_id: UUID = field(default_factory=uuid4)
    event_type: str = ""  # Now a regular field, can be passed in init
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    causation_id: str | None = None
    user_id: UUID | None = None
    tenant_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    source_system: str = "erp_accounting_engine"
    version: int = 1
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # If event is provided, infer event_type from it
        if hasattr(self, "event") and self.event is not None:
            object.__setattr__(self, "event_type", self.event.__class__.__name__)
        # If event_type is empty and event is None, we keep it empty; but from_json will set it explicitly.

    def to_json(self) -> str:
        event_dict = self._event_to_dict(self.event) if self.event else self.payload
        envelope_dict = {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "user_id": str(self.user_id) if self.user_id else None,
            "tenant_id": self.tenant_id,
            "occurred_at": self.occurred_at.isoformat(),
            "source_system": self.source_system,
            "version": self.version,
            "idempotency_key": self.idempotency_key,
            "payload": event_dict,
        }
        return json.dumps(envelope_dict, default=self._json_default)

    @staticmethod
    def _event_to_dict(event: Any) -> dict[str, Any]:
        if hasattr(event, "to_dict"):
            return event.to_dict()
        result = {}
        for key, value in event.__dict__.items():
            if not key.startswith("_"):
                if isinstance(value, UUID):
                    result[key] = str(value)
                elif isinstance(value, datetime):
                    result[key] = value.isoformat()
                elif isinstance(value, Decimal):
                    # Preserve precision: serialize as string, not float
                    result[key] = str(value)
                else:
                    result[key] = value
        return result

    @staticmethod
    def _json_default(obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            # Preserve precision: serialize as string
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    @classmethod
    def from_json(cls, json_str: str) -> EventEnvelope:
        data = json.loads(json_str)
        return cls(
            event=None,
            event_id=UUID(data["event_id"]),
            event_type=data["event_type"],  # now allowed
            correlation_id=data.get("correlation_id", str(uuid4())),
            causation_id=data.get("causation_id"),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            tenant_id=data.get("tenant_id"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            source_system=data.get("source_system", "erp_accounting_engine"),
            version=data.get("version", 1),
            idempotency_key=data.get("idempotency_key"),
            payload=data.get("payload", {}),
        )


@dataclass
class EventPublishStatus:
    """Status hasil publish event."""

    event_id: UUID
    event_type: str
    result: PublishResult
    attempt: int
    latency_ms: float
    error_message: str | None = None
    kafka_offset: int | None = None
    outbox_record_id: int | None = None


# ============================================================================
# SIMPLE CIRCUIT BREAKER
# ============================================================================


class SimpleCircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures = 0
        self._last_failure_time: float | None = None
        self._state = "closed"

    @property
    def state(self) -> str:
        # SIM102: combine nested if using `and`
        if self._state == "open" and self._last_failure_time and time.time() - self._last_failure_time >= self.recovery_timeout:
            self._state = "half-open"
        return self._state

    def record_success(self) -> None:
        self._failures = 0
        if self._state == "half-open":
            self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold:
            self._state = "open"

    async def __aenter__(self):
        if self.state == "open":
            raise CircuitBreakerOpenError(f"Circuit breaker '{self.name}' is open")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.record_success()
        else:
            self.record_failure()


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
# APPLICATION EVENT PUBLISHER
# ============================================================================


class ApplicationEventPublisher:
    def __init__(
        self,
        message_broker: MessageBrokerPort,
        outbox: OutboxPort | None,
        cache: CachePort | None,
        mode: PublishMode = PublishMode.HYBRID,
        enable_circuit_breaker: bool = True,
        enable_idempotency: bool = True,
        max_retries: int = 3,
        retry_delay_seconds: float = 0.5,
    ):
        if message_broker is None:
            raise ValueError("message_broker is required")
        if mode in (PublishMode.ASYNC, PublishMode.HYBRID) and outbox is None:
            raise ValueError(f"Mode {mode} requires outbox")
        if enable_idempotency and cache is None:
            raise ValueError("Idempotency enabled but cache is None")

        self._broker = message_broker
        self._outbox = outbox
        self._cache = cache
        self._mode = mode
        self._enable_circuit_breaker = enable_circuit_breaker
        self._enable_idempotency = enable_idempotency

        self._circuit_breaker = (
            SimpleCircuitBreaker(name="event_publisher", failure_threshold=5, recovery_timeout=30.0)
            if enable_circuit_breaker
            else None
        )

        self._retry_policy = SimpleRetryPolicy(
            max_attempts=max_retries, base_delay=retry_delay_seconds, max_delay=10.0
        )

        # Use dict[str, Any] for stats to allow mixed types
        self._stats: dict[str, Any] = {
            "total_published": 0,
            "total_failed": 0,
            "total_outbox_enqueued": 0,
            "last_error": None,
            "last_error_time": None,
        }

        logger.info(f"ApplicationEventPublisher initialized (mode={mode.name})")

    async def publish(
        self,
        event: Any,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        user_id: UUID | None = None,
        tenant_id: str | None = None,
        idempotency_key: str | None = None,
        force_sync: bool = False,
    ) -> EventPublishStatus:
        start_time = time.perf_counter()

        # SIM102: combine nested if
        if self._enable_idempotency and idempotency_key and await self._is_event_processed(idempotency_key):
            logger.warning(f"Duplicate event, skipping: {idempotency_key}")
            return EventPublishStatus(
                event_id=uuid4(),
                event_type=event.__class__.__name__,
                result=PublishResult.SUCCESS,
                attempt=0,
                latency_ms=0,
                error_message="Duplicate event, already processed",
            )

        envelope = EventEnvelope(
            event=event,
            correlation_id=correlation_id or str(uuid4()),
            causation_id=causation_id,
            user_id=user_id,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

        effective_mode = self._mode
        if force_sync:
            effective_mode = PublishMode.SYNC

        try:
            if effective_mode == PublishMode.SYNC:
                result = await self._publish_sync(envelope)
            elif effective_mode == PublishMode.ASYNC:
                result = await self._publish_async_outbox(envelope)
            else:
                result = await self._publish_hybrid(envelope)

            latency_ms = (time.perf_counter() - start_time) * 1000
            self._stats["total_published"] += 1

            return EventPublishStatus(
                event_id=envelope.event_id,
                event_type=envelope.event_type,
                result=result,
                attempt=1,
                latency_ms=latency_ms,
            )
        except Exception as e:
            self._stats["total_failed"] += 1
            self._stats["last_error"] = str(e)
            self._stats["last_error_time"] = datetime.now(UTC)
            raise

    async def publish_many(
        self,
        events: list[Any],
        correlation_id: str | None = None,
        user_id: UUID | None = None,
        tenant_id: str | None = None,
    ) -> list[EventPublishStatus]:
        results = []
        for event in events:
            status = await self.publish(event, correlation_id, user_id=user_id, tenant_id=tenant_id)
            results.append(status)
        return results

    async def _publish_sync(self, envelope: EventEnvelope) -> PublishResult:
        topic = self._get_topic_for_event(envelope.event_type)

        async def _do_publish():
            try:
                await self._broker.send(
                    topic=topic,
                    key=str(envelope.event_id),
                    value=envelope.to_json(),
                    headers={
                        "event_type": envelope.event_type,
                        "correlation_id": envelope.correlation_id,
                    },
                )
            except Exception as e:
                # UP038: use X | Y instead of tuple
                if isinstance(e, ConnectionError | TimeoutError):
                    raise EventPublishRetryableError(f"Network error: {e}")
                raise EventPublishFatalError(f"Fatal error: {e}")

        if self._circuit_breaker:
            async with self._circuit_breaker:
                await self._retry_policy.execute(_do_publish)
        else:
            await self._retry_policy.execute(_do_publish)

        await self._trigger_local_handlers(envelope)
        return PublishResult.SUCCESS

    async def _publish_async_outbox(self, envelope: EventEnvelope) -> PublishResult:
        if self._outbox is None:
            raise EventPublishFatalError("Outbox is None but ASYNC mode is used.")

        try:
            # F841: remove unused variable record_id (use _)
            _ = await self._outbox.enqueue(
                event_id=envelope.event_id,
                event_type=envelope.event_type,
                payload=envelope.to_json(),
                topic=self._get_topic_for_event(envelope.event_type),
                correlation_id=envelope.correlation_id,
                idempotency_key=envelope.idempotency_key,
            )
            self._stats["total_outbox_enqueued"] += 1
            await self._trigger_local_handlers(envelope)
            return PublishResult.OUTBOX_ENQUEUED
        except Exception as e:
            logger.error(f"Failed to enqueue event: {e}")
            raise EventPublishRetryableError(f"Outbox enqueue failed: {e}")

    async def _publish_hybrid(self, envelope: EventEnvelope) -> PublishResult:
        await self._trigger_local_handlers(envelope)
        return await self._publish_async_outbox(envelope)

    async def _trigger_local_handlers(self, envelope: EventEnvelope) -> None:
        event_type = envelope.event_type
        handlers = event_handler_registry.get_handlers(event_type)
        if not handlers:
            return

        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(envelope)
                else:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, handler, envelope)
                logger.debug(f"Local handler executed for {event_type}")
            except Exception as e:
                logger.error(f"Local handler for {event_type} failed: {e}", exc_info=True)

    async def _is_event_processed(self, idempotency_key: str) -> bool:
        if self._cache is None:
            return False
        key = f"event:idempotency:{idempotency_key}"
        exists = await self._cache.exists(key)
        if exists:
            await self._cache.expire(key, 86400 * 7)
        return bool(exists)

    def _get_topic_for_event(self, event_type: str) -> str:
        mapping = {
            "Journal": "erp.accounting.journal",
            "ARInvoice": "erp.accounting.ar",
            "ARPayment": "erp.accounting.ar",
            "APInvoice": "erp.accounting.ap",
            "APPayment": "erp.accounting.ap",
            "Inventory": "erp.inventory.movement",
            "FixedAsset": "erp.fixed_asset",
            "Payroll": "erp.payroll",
            "Coretax": "erp.tax.coretax",
        }
        for prefix, topic in mapping.items():
            if event_type.startswith(prefix):
                return topic
        return "erp.accounting.general"

    def get_stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "circuit_breaker_state": self._circuit_breaker.state
            if self._circuit_breaker
            else "disabled",
            "mode": self._mode.name,
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================


async def create_event_publisher(
    message_broker: MessageBrokerPort,
    outbox: OutboxPort | None,
    cache: CachePort | None,
    mode: str = "hybrid",
    enable_circuit_breaker: bool = True,
    enable_idempotency: bool = True,
    max_retries: int = 3,
    retry_delay_seconds: float = 0.5,
) -> ApplicationEventPublisher:
    """Factory untuk membuat ApplicationEventPublisher."""
    mode_enum = {
        "sync": PublishMode.SYNC,
        "async": PublishMode.ASYNC,
        "hybrid": PublishMode.HYBRID,
    }.get(mode.lower(), PublishMode.HYBRID)

    return ApplicationEventPublisher(
        message_broker=message_broker,
        outbox=outbox,
        cache=cache,
        mode=mode_enum,
        enable_circuit_breaker=enable_circuit_breaker,
        enable_idempotency=enable_idempotency,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay_seconds,
    )


__all__ = [
    "ApplicationEventPublisher",
    "CachePort",
    "CircuitBreakerOpenError",
    "EventEnvelope",
    "EventPublishError",
    "EventPublishFatalError",
    "EventPublishRetryableError",
    "EventPublishStatus",
    "MessageBrokerPort",
    "OutboxPort",
    "PublishMode",
    "PublishResult",
    "create_event_publisher",
]
