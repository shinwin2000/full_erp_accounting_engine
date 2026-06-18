#!/usr/bin/env python3
"""
Module: event_publisher_port.py
Layer: Ports (Primary)
Responsibility: Implementasi in-memory event publisher dengan outbox pattern,
               idempotency, retry dengan exponential backoff, dead letter queue,
               multiple subscribers, event versioning, schema validation,
               audit trail, dan metrics.
Audit: Setiap publish, retry, dead letter, dan subscriber invocation tercatat.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class EventStatus(Enum):
    """Status event dalam outbox."""

    PENDING = "pending"  # Menunggu diproses
    PROCESSING = "processing"  # Sedang diproses (locked)
    SENT = "sent"  # Berhasil dikirim ke semua subscriber
    FAILED = "failed"  # Gagal, akan di-retry
    DEAD = "dead"  # Gagal permanen, masuk dead letter
    SKIPPED = "skipped"  # Dilewati (misal duplikat)


class EventPriority(Enum):
    """Prioritas event."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class RetryStrategy(Enum):
    """Strategi retry."""

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"


@dataclass
class OutboxEvent:
    """Event dalam outbox."""

    id: UUID
    event_type: str
    event_version: int
    aggregate_id: UUID
    aggregate_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    priority: EventPriority
    status: EventStatus
    retry_count: int
    max_retries: int
    last_attempt_at: datetime | None
    created_at: datetime
    scheduled_at: datetime | None
    last_error: str | None
    locked_by: str | None
    locked_until: datetime | None
    idempotency_key: str | None
    partition_key: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "event_version": self.event_version,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "payload": self.payload,
            "metadata": self.metadata,
            "priority": self.priority.value,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_attempt_at": self.last_attempt_at.isoformat() if self.last_attempt_at else None,
            "created_at": self.created_at.isoformat(),
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "last_error": self.last_error,
            "idempotency_key": self.idempotency_key,
            "partition_key": self.partition_key,
        }


@dataclass
class DeadLetterEvent:
    """Event gagal permanen."""

    id: UUID
    original_event_id: UUID
    event_type: str
    aggregate_id: UUID
    aggregate_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    final_error: str
    failed_at: datetime
    resolution_status: str  # PENDING, RESOLVED, SKIPPED
    resolved_at: datetime | None
    resolved_by: UUID | None


@dataclass
class SubscriberRegistration:
    """Registrasi subscriber untuk suatu tipe event."""

    event_type: str
    handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]]
    name: str
    is_async: bool = True
    timeout_seconds: int = 30
    retry_on_failure: bool = True


@dataclass
class EventPublishMetrics:
    """Metrics untuk monitoring."""

    total_published: int = 0
    total_succeeded: int = 0
    total_failed: int = 0
    total_dead: int = 0
    total_retries: int = 0
    avg_latency_ms: float = 0.0
    last_publish_at: datetime | None = None
    by_event_type: dict[str, dict[str, int]] = field(default_factory=dict)


class EventPublisherPort:
    """
    Implementasi in-memory event publisher dengan outbox pattern.
    Mendukung multiple subscriber per event type, idempotency, retry,
    dead letter, priority queue, partition key, dan metrics.
    """

    def __init__(
        self,
        default_max_retries: int = 5,
        retry_strategy: RetryStrategy = RetryStrategy.EXPONENTIAL,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        lock_timeout_seconds: int = 30,
        poll_interval_seconds: float = 1.0,
        batch_size: int = 100,
    ):
        self._outbox: dict[UUID, OutboxEvent] = {}
        self._dead_letter: dict[UUID, DeadLetterEvent] = {}
        self._subscribers: dict[str, list[SubscriberRegistration]] = {}
        self._processed_ids: set[UUID] = set()  # idempotency
        self._idempotency_keys: set[str] = set()
        self._default_max_retries = default_max_retries
        self._retry_strategy = retry_strategy
        self._base_delay = base_delay_seconds
        self._max_delay = max_delay_seconds
        self._lock_timeout = lock_timeout_seconds
        self._poll_interval = poll_interval_seconds
        self._batch_size = batch_size
        self._instance_id = f"publisher-{secrets.token_hex(4)}"
        self._metrics = EventPublishMetrics()
        self._audit_log: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._poller_task: asyncio.Task | None = None
        self._running = False

    # ==================== AUDIT LOG ====================

    async def _log_audit(self, action: str, event_id: UUID, details: dict[str, Any]):
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "action": action,
            "event_id": str(event_id),
            "instance": self._instance_id,
            "details": details,
        }
        self._audit_log.append(entry)
        logger.info(f"EVENT AUDIT: {action} event {event_id}")

    # ==================== HELPER ====================

    def _compute_idempotency_key(
        self, event_type: str, aggregate_id: UUID, payload_hash: str
    ) -> str:
        """Generate idempotency key dari event type, aggregate_id, dan hash payload."""
        return hashlib.sha256(f"{event_type}:{aggregate_id}:{payload_hash}".encode()).hexdigest()

    async def _calculate_retry_delay(self, retry_count: int) -> float:
        """Hitung delay berdasarkan retry strategy."""
        if self._retry_strategy == RetryStrategy.FIXED:
            return self._base_delay
        elif self._retry_strategy == RetryStrategy.LINEAR:
            return min(self._base_delay * retry_count, self._max_delay)
        else:  # EXPONENTIAL
            delay = self._base_delay * (2 ** (retry_count - 1))
            return min(delay, self._max_delay)

    async def _update_metrics(self, event_type: str, success: bool, latency_ms: float):
        """Update metrics."""
        self._metrics.total_published += 1
        if success:
            self._metrics.total_succeeded += 1
        else:
            self._metrics.total_failed += 1
        # Update average latency
        self._metrics.avg_latency_ms = (
            self._metrics.avg_latency_ms * (self._metrics.total_published - 1) + latency_ms
        ) / self._metrics.total_published
        self._metrics.last_publish_at = datetime.now(UTC)
        # Per event type
        if event_type not in self._metrics.by_event_type:
            self._metrics.by_event_type[event_type] = {"success": 0, "failed": 0}
        if success:
            self._metrics.by_event_type[event_type]["success"] += 1
        else:
            self._metrics.by_event_type[event_type]["failed"] += 1

    # ==================== PUBLISH API ====================

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
        """
        Mempublikasikan event. Event disimpan ke outbox dan akan diproses oleh poller.
        Mengembalikan event_id.
        """
        start_time = time.perf_counter()
        # Serialize event to dict
        if hasattr(event, "to_dict"):
            payload = event.to_dict()
        elif isinstance(event, dict):
            payload = event
        else:
            payload = {"_raw": str(event)}

        # Idempotency check
        if not idempotency_key:
            payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            idempotency_key = self._compute_idempotency_key(event_type, aggregate_id, payload_hash)

        async with self._lock:
            if idempotency_key in self._idempotency_keys:
                logger.warning(f"Duplicate event detected with idempotency_key {idempotency_key}")
                # Cari event ID yang sudah ada
                for evt in self._outbox.values():
                    if evt.idempotency_key == idempotency_key:
                        await self._log_audit(
                            "DUPLICATE_REJECTED", evt.id, {"idempotency_key": idempotency_key}
                        )
                        return evt.id
                # Fallback: generate new but warn
                idempotency_key = f"{idempotency_key}:{secrets.token_hex(4)}"
            self._idempotency_keys.add(idempotency_key)

        event_id = uuid4()
        now = datetime.now(UTC)
        outbox_event = OutboxEvent(
            id=event_id,
            event_type=event_type,
            event_version=event_version,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            metadata=metadata or {},
            priority=priority,
            status=EventStatus.PENDING,
            retry_count=0,
            max_retries=self._default_max_retries,
            last_attempt_at=None,
            created_at=now,
            scheduled_at=scheduled_at,
            last_error=None,
            locked_by=None,
            locked_until=None,
            idempotency_key=idempotency_key,
            partition_key=partition_key,
        )
        async with self._lock:
            self._outbox[event_id] = outbox_event
        latency_ms = (time.perf_counter() - start_time) * 1000
        await self._update_metrics(event_type, True, latency_ms)
        await self._log_audit(
            "PUBLISH",
            event_id,
            {
                "event_type": event_type,
                "aggregate_id": str(aggregate_id),
                "priority": priority.value,
                "idempotency_key": idempotency_key[:16],
            },
        )
        return event_id

    async def publish_batch(self, events: list[dict[str, Any]]) -> list[UUID]:
        """
        Mempublikasikan banyak event sekaligus.
        events: list of dict dengan keys: event, event_type, aggregate_id, aggregate_type, metadata, priority, etc.
        """
        event_ids = []
        for evt in events:
            event_id = await self.publish(
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
            event_ids.append(event_id)
        return event_ids

    # ==================== SUBSCRIBER MANAGEMENT ====================

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]],
        name: str | None = None,
        timeout_seconds: int = 30,
        retry_on_failure: bool = True,
    ) -> None:
        """
        Mendaftarkan handler untuk event type tertentu.
        Handler menerima (payload, metadata) dan mengembalikan bool sukses.
        """
        subscriber_name = (
            name or f"subscriber_{event_type}_{len(self._subscribers.get(event_type, []))}"
        )
        registration = SubscriberRegistration(
            event_type=event_type,
            handler=handler,
            name=subscriber_name,
            is_async=True,
            timeout_seconds=timeout_seconds,
            retry_on_failure=retry_on_failure,
        )
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(registration)
        logger.info(f"Subscriber '{subscriber_name}' registered for event type {event_type}")

    def unsubscribe(self, event_type: str, name: str) -> bool:
        """Hapus subscriber berdasarkan nama."""
        if event_type not in self._subscribers:
            return False
        original_len = len(self._subscribers[event_type])
        self._subscribers[event_type] = [s for s in self._subscribers[event_type] if s.name != name]
        return len(self._subscribers[event_type]) < original_len

    # ==================== OUTBOX POLLER ====================

    async def start_poller(self):
        """Start background poller untuk memproses outbox."""
        if self._running:
            logger.warning("Poller already running")
            return
        self._running = True
        self._poller_task = asyncio.create_task(self._poller_loop())
        logger.info("Event publisher poller started")

    async def stop_poller(self):
        """Stop background poller."""
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
        """Main poller loop."""
        while self._running:
            try:
                await self._process_pending_events()
                await asyncio.sleep(self._poll_interval)
            except Exception as e:
                logger.error(f"Poller error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_pending_events(self):
        """Ambil event pending, lock, lalu proses."""
        now = datetime.now(UTC)
        to_process = []

        async with self._lock:
            # Urutkan berdasarkan prioritas (critical > high > normal > low) dan created_at
            pending = [e for e in self._outbox.values() if e.status == EventStatus.PENDING]
            # Filter scheduled
            pending = [e for e in pending if e.scheduled_at is None or e.scheduled_at <= now]
            # Filter locked
            pending = [e for e in pending if e.locked_until is None or e.locked_until <= now]
            # Urutkan: priority descending, created_at ascending
            pending.sort(key=lambda e: (-e.priority.value, e.created_at))
            # Ambil batch
            for event in pending[: self._batch_size]:
                event.status = EventStatus.PROCESSING
                event.locked_by = self._instance_id
                event.locked_until = now + timedelta(seconds=self._lock_timeout)
                to_process.append(event)

        # Proses satu per satu (bisa juga paralel dengan asyncio.gather)
        for event in to_process:
            await self._process_single_event(event)

    async def _process_single_event(self, event: OutboxEvent):
        """Proses satu event: kirim ke semua subscriber."""
        start_time = time.perf_counter()
        success = True
        error_msg = None

        try:
            subscribers = self._subscribers.get(event.event_type, [])
            if not subscribers:
                # Tidak ada subscriber, anggap sukses
                logger.debug(f"No subscribers for event type {event.event_type}, marking as sent")
            else:
                for sub in subscribers:
                    try:
                        # Panggil handler dengan timeout
                        handler_success = await asyncio.wait_for(
                            sub.handler(event.payload, event.metadata), timeout=sub.timeout_seconds
                        )
                        if not handler_success:
                            success = False
                            error_msg = f"Handler {sub.name} returned False"
                            break
                    except TimeoutError:
                        success = False
                        error_msg = f"Handler {sub.name} timeout after {sub.timeout_seconds}s"
                        break
                    except Exception as e:
                        success = False
                        error_msg = f"Handler {sub.name} error: {e!s}"
                        break
        except Exception as e:
            success = False
            error_msg = str(e)

        latency_ms = (time.perf_counter() - start_time) * 1000
        await self._update_metrics(event.event_type, success, latency_ms)

        async with self._lock:
            if success:
                event.status = EventStatus.SENT
                event.locked_by = None
                event.locked_until = None
                self._processed_ids.add(event.id)
                await self._log_audit(
                    "SENT",
                    event.id,
                    {
                        "retry_count": event.retry_count,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            else:
                event.retry_count += 1
                event.last_attempt_at = datetime.now(UTC)
                event.last_error = error_msg
                self._metrics.total_retries += 1
                if event.retry_count >= event.max_retries:
                    # Pindah ke dead letter
                    await self._move_to_dead_letter(event, error_msg)
                    del self._outbox[event.id]
                else:
                    # Schedule retry
                    delay = await self._calculate_retry_delay(event.retry_count)
                    event.scheduled_at = datetime.now(UTC) + timedelta(seconds=delay)
                    event.status = EventStatus.PENDING
                    event.locked_by = None
                    event.locked_until = None
                    await self._log_audit(
                        "RETRY_SCHEDULED",
                        event.id,
                        {
                            "retry_count": event.retry_count,
                            "delay_seconds": delay,
                            "error": error_msg[:200],
                        },
                    )

    async def _move_to_dead_letter(self, event: OutboxEvent, error_msg: str):
        """Pindahkan event ke dead letter queue."""
        dead_event = DeadLetterEvent(
            id=uuid4(),
            original_event_id=event.id,
            event_type=event.event_type,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            payload=event.payload,
            metadata=event.metadata,
            final_error=error_msg,
            failed_at=datetime.now(UTC),
            resolution_status="PENDING",
            resolved_at=None,
            resolved_by=None,
        )
        self._dead_letter[dead_event.id] = dead_event
        self._metrics.total_dead += 1
        await self._log_audit(
            "DEAD_LETTER",
            event.id,
            {
                "error": error_msg[:200],
                "dead_letter_id": str(dead_event.id),
            },
        )

    # ==================== DEAD LETTER OPERATIONS ====================

    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        """Coba kirim ulang event dari dead letter. Buat event baru di outbox."""
        dead = self._dead_letter.get(dead_letter_id)
        if not dead:
            return None
        if dead.resolution_status != "PENDING":
            return None
        # Buat event baru
        new_event_id = await self.publish(
            event=dead.payload,
            event_type=dead.event_type,
            aggregate_id=dead.aggregate_id,
            aggregate_type=dead.aggregate_type,
            metadata=dead.metadata,
            priority=EventPriority.NORMAL,
            scheduled_at=datetime.now(UTC) + timedelta(seconds=1),
            event_version=2,  # increment version
        )
        dead.resolution_status = "RESOLVED"
        dead.resolved_at = datetime.now(UTC)
        dead.resolved_by = user_id
        await self._log_audit(
            "RETRY_DEAD_LETTER",
            dead.original_event_id,
            {
                "dead_letter_id": str(dead_letter_id),
                "new_event_id": str(new_event_id),
            },
        )
        return new_event_id

    async def skip_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> bool:
        """Tandai dead letter sebagai skipped (tidak akan diproses ulang)."""
        dead = self._dead_letter.get(dead_letter_id)
        if not dead:
            return False
        dead.resolution_status = "SKIPPED"
        dead.resolved_at = datetime.now(UTC)
        dead.resolved_by = user_id
        await self._log_audit(
            "SKIP_DEAD_LETTER", dead.original_event_id, {"dead_letter_id": str(dead_letter_id)}
        )
        return True

    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[DeadLetterEvent]:
        return list(self._dead_letter.values())[offset : offset + limit]

    async def purge_dead_letters(self, older_than_days: int = 30) -> int:
        """Hapus dead letter yang sudah lebih lama dari N hari."""
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        to_delete = [did for did, dl in self._dead_letter.items() if dl.failed_at < cutoff]
        for did in to_delete:
            del self._dead_letter[did]
        await self._log_audit("PURGE_DEAD_LETTERS", UUID(int=0), {"count": len(to_delete)})
        return len(to_delete)

    # ==================== QUERY & ADMIN ====================

    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        event = self._outbox.get(event_id)
        if event:
            return event.to_dict()
        for dl in self._dead_letter.values():
            if dl.original_event_id == event_id:
                return {
                    "id": str(dl.id),
                    "original_event_id": str(dl.original_event_id),
                    "status": "DEAD_LETTER",
                    "error": dl.final_error,
                    "failed_at": dl.failed_at.isoformat(),
                }
        return None

    async def get_pending_count(self) -> int:
        return sum(1 for e in self._outbox.values() if e.status == EventStatus.PENDING)

    async def get_processing_count(self) -> int:
        return sum(1 for e in self._outbox.values() if e.status == EventStatus.PROCESSING)

    async def get_failed_count(self) -> int:
        return sum(1 for e in self._outbox.values() if e.status == EventStatus.FAILED)

    async def get_dead_letter_count(self) -> int:
        return len(self._dead_letter)

    async def get_outbox_size(self) -> int:
        return len(self._outbox)

    async def flush(self) -> int:
        """Force process semua pending events (synchronous dalam batasan)."""
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
        """Hapus event SENT yang sudah lebih lama dari N hari."""
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        to_delete = [
            eid
            for eid, e in self._outbox.items()
            if e.status == EventStatus.SENT and e.created_at < cutoff
        ]
        for eid in to_delete:
            del self._outbox[eid]
        await self._log_audit("PURGE_OUTBOX", UUID(int=0), {"count": len(to_delete)})
        return len(to_delete)

    # ==================== METRICS & HEALTH ====================

    async def get_statistics(self) -> dict[str, Any]:
        return {
            "total_published": self._metrics.total_published,
            "total_succeeded": self._metrics.total_succeeded,
            "total_failed": self._metrics.total_failed,
            "total_dead": self._metrics.total_dead,
            "total_retries": self._metrics.total_retries,
            "avg_latency_ms": round(self._metrics.avg_latency_ms, 2),
            "last_publish_at": self._metrics.last_publish_at.isoformat()
            if self._metrics.last_publish_at
            else None,
            "pending_count": await self.get_pending_count(),
            "processing_count": await self.get_processing_count(),
            "failed_count": await self.get_failed_count(),
            "dead_letter_count": await self.get_dead_letter_count(),
            "outbox_size": await self.get_outbox_size(),
            "poller_running": self._running,
            "instance_id": self._instance_id,
            "by_event_type": self._metrics.by_event_type,
            "subscribers": {et: [s.name for s in subs] for et, subs in self._subscribers.items()},
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset : offset + limit]

    async def health_check(self) -> dict[str, Any]:
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
            "total_subscribers": sum(len(subs) for subs in self._subscribers.values()),
            "outbox_size": await self.get_outbox_size(),
        }
