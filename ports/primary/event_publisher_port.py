#!/usr/bin/env python3
"""
Module: event_publisher_port.py
Layer: Ports (Primary)
Responsibility:
    - Mendefinisikan antarmuka (port) untuk Event Publisher (outbox pattern).
    - Menyediakan implementasi in-memory untuk testing/fallback.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ==================== ENUMS & DOMAIN MODELS ====================

class EventPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class EventStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"
    DEAD = "dead"
    SKIPPED = "skipped"


class OutboxEvent:
    def __init__(
        self,
        event_id: UUID,
        event_type: str,
        aggregate_id: UUID,
        aggregate_type: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None,
        priority: EventPriority,
        scheduled_at: datetime | None,
        idempotency_key: str | None,
        partition_key: str | None,
        event_version: int,
        status: EventStatus,
        created_at: datetime,
        updated_at: datetime | None = None,
        processed_at: datetime | None = None,
        retry_count: int = 0,
        error_message: str | None = None,
    ):
        self.id = event_id
        self.event_type = event_type
        self.aggregate_id = aggregate_id
        self.aggregate_type = aggregate_type
        self.payload = payload
        self.metadata = metadata or {}
        self.priority = priority
        self.scheduled_at = scheduled_at
        self.idempotency_key = idempotency_key
        self.partition_key = partition_key
        self.event_version = event_version
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at or created_at
        self.processed_at = processed_at
        self.retry_count = retry_count
        self.error_message = error_message


# ==================== PORT (INTERFACE) ====================

class EventPublisherPort(ABC):
    @abstractmethod
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
        ...

    @abstractmethod
    async def publish_batch(self, events: list[dict[str, Any]]) -> list[UUID]:
        ...

    @abstractmethod
    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]],
        name: str | None = None,
        timeout_seconds: int = 30,
        retry_on_failure: bool = True,
    ) -> None:
        ...

    @abstractmethod
    def unsubscribe(self, event_type: str, name: str) -> bool:
        ...

    @abstractmethod
    async def start_poller(self):
        ...

    @abstractmethod
    async def stop_poller(self):
        ...

    @abstractmethod
    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        ...

    @abstractmethod
    async def get_pending_count(self) -> int:
        ...

    @abstractmethod
    async def get_processing_count(self) -> int:
        ...

    @abstractmethod
    async def get_failed_count(self) -> int:
        ...

    @abstractmethod
    async def get_dead_letter_count(self) -> int:
        ...

    @abstractmethod
    async def get_outbox_size(self) -> int:
        ...

    @abstractmethod
    async def flush(self) -> int:
        ...

    @abstractmethod
    async def purge_outbox(self, older_than_days: int = 30) -> int:
        ...

    @abstractmethod
    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        ...

    @abstractmethod
    async def skip_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> bool:
        ...

    @abstractmethod
    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[Any]:
        ...

    @abstractmethod
    async def purge_dead_letters(self, older_than_days: int = 30) -> int:
        ...

    @abstractmethod
    async def get_statistics(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        ...


# ==================== IMPLEMENTASI IN-MEMORY ====================

class InMemoryEventPublisher(EventPublisherPort):
    def __init__(self, poll_interval_seconds: int = 5):
        self._events: dict[UUID, OutboxEvent] = {}
        self._handlers: dict[str, list[dict[str, Any]]] = {}
        self._dead_letters: list[OutboxEvent] = []
        self._audit_log: list[dict[str, Any]] = []
        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()          # <-- untuk subscribe/unsubscribe
        self._poller_running = False
        self._poller_task: asyncio.Task | None = None
        self._poll_interval = poll_interval_seconds
        self._background_tasks: list[asyncio.Task] = []

    def _add_background_task(self, task: asyncio.Task) -> None:
        self._background_tasks.append(task)
        task.add_done_callback(
            lambda t: self._background_tasks.remove(t) if t in self._background_tasks else None
        )

    async def _log_audit(self, action: str, event_id: UUID, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "event_id": str(event_id),
            "details": details,
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > 10000:
            self._audit_log = self._audit_log[-5000:]

    # ------------------- PUBLISH -------------------

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
        if not isinstance(event, dict):
            try:
                payload = event.to_dict() if hasattr(event, "to_dict") else {"data": event}
            except Exception:
                payload = {"data": event}
        else:
            payload = event

        event_id = uuid4()
        now = datetime.utcnow()

        outbox_event = OutboxEvent(
            event_id=event_id,
            event_type=event_type,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            payload=payload,
            metadata=metadata,
            priority=priority,
            scheduled_at=scheduled_at,
            idempotency_key=idempotency_key,
            partition_key=partition_key,
            event_version=event_version,
            status=EventStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

        async with self._async_lock:
            if idempotency_key:
                for e in self._events.values():
                    if e.idempotency_key == idempotency_key:
                        logger.warning(f"Event with idempotency key {idempotency_key} already exists, skipping.")
                        return e.id
            self._events[event_id] = outbox_event

        await self._log_audit("PUBLISH", event_id, {"event_type": event_type})
        return event_id

    async def publish_batch(self, events: list[dict[str, Any]]) -> list[UUID]:
        ids = []
        for ev in events:
            # Extract required fields with validation
            event_type = ev.get("event_type")
            if not event_type:
                raise ValueError("event_type is required for batch publish")
            aggregate_id = ev.get("aggregate_id")
            if not aggregate_id:
                raise ValueError("aggregate_id is required for batch publish")
            if not isinstance(aggregate_id, UUID):
                raise ValueError(f"aggregate_id must be UUID, got {type(aggregate_id)}")
            aggregate_type = ev.get("aggregate_type")
            if not aggregate_type:
                raise ValueError("aggregate_type is required for batch publish")

            eid = await self.publish(
                event=ev.get("event"),  # may be None
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type=aggregate_type,
                metadata=ev.get("metadata"),
                priority=ev.get("priority", EventPriority.NORMAL),
                scheduled_at=ev.get("scheduled_at"),
                idempotency_key=ev.get("idempotency_key"),
                partition_key=ev.get("partition_key"),
                event_version=ev.get("event_version", 1),
            )
            ids.append(eid)
        return ids

    # ------------------- SUBSCRIBE / UNSUBSCRIBE (SYNC) -------------------

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Awaitable[bool]],
        name: str | None = None,
        timeout_seconds: int = 30,
        retry_on_failure: bool = True,
    ) -> None:
        if name is None:
            name = f"sub-{event_type}-{uuid4().hex[:8]}"
        subscriber = {
            "name": name,
            "handler": handler,
            "timeout": timeout_seconds,
            "retry": retry_on_failure,
        }
        with self._sync_lock:                     # <-- sync lock
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(subscriber)

    def unsubscribe(self, event_type: str, name: str) -> bool:
        with self._sync_lock:                     # <-- sync lock
            if event_type not in self._handlers:
                return False
            original_len = len(self._handlers[event_type])
            self._handlers[event_type] = [s for s in self._handlers[event_type] if s["name"] != name]
            return len(self._handlers[event_type]) < original_len

    # ------------------- POLLER -------------------

    async def start_poller(self):
        if self._poller_running:
            return
        self._poller_running = True
        self._poller_task = asyncio.create_task(self._poller_loop())
        self._add_background_task(self._poller_task)
        logger.info("Event publisher poller started")

    async def _poller_loop(self):
        while self._poller_running:
            try:
                await self._process_pending()
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Poller error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def _process_pending(self):
        now = datetime.utcnow()
        pending_events = []
        async with self._async_lock:
            for e in self._events.values():
                if e.status == EventStatus.PENDING:
                    if e.scheduled_at and e.scheduled_at > now:
                        continue
                    pending_events.append(e.id)
        for eid in pending_events:
            await self._process_event(eid)

    async def _process_event(self, event_id: UUID):
        async with self._async_lock:
            event = self._events.get(event_id)
            if not event or event.status != EventStatus.PENDING:
                return
            event.status = EventStatus.PROCESSING
            event.updated_at = datetime.utcnow()

        handlers = self._handlers.get(event.event_type, [])
        if not handlers:
            async with self._async_lock:
                event.status = EventStatus.SENT
                event.processed_at = datetime.utcnow()
                event.updated_at = datetime.utcnow()
            await self._log_audit("PROCESS_NO_HANDLER", event_id, {})
            return

        success = False
        for subscriber in handlers:
            try:
                result = await asyncio.wait_for(
                    subscriber["handler"](event.payload, event.metadata),
                    timeout=subscriber["timeout"],
                )
                if result:
                    success = True
                    break
            except TimeoutError:
                logger.warning(f"Handler {subscriber['name']} timed out for event {event_id}")
                if subscriber["retry"] and event.retry_count < 3:
                    event.retry_count += 1
                    event.status = EventStatus.PENDING
                    event.updated_at = datetime.utcnow()
                    await self._log_audit("RETRY", event_id, {"retry_count": event.retry_count})
                    return
            except Exception as e:
                logger.error(f"Handler {subscriber['name']} failed: {e}")
                if subscriber["retry"] and event.retry_count < 3:
                    event.retry_count += 1
                    event.status = EventStatus.PENDING
                    event.updated_at = datetime.utcnow()
                    await self._log_audit("RETRY", event_id, {"retry_count": event.retry_count})
                    return

        if success:
            async with self._async_lock:
                event.status = EventStatus.SENT
                event.processed_at = datetime.utcnow()
                event.updated_at = event.processed_at
            await self._log_audit("PROCESS_SUCCESS", event_id, {})
        else:
            async with self._async_lock:
                if event.retry_count >= 3:
                    event.status = EventStatus.DEAD
                    event.error_message = "Max retries exceeded"
                    self._dead_letters.append(event)
                else:
                    event.status = EventStatus.FAILED
                    event.updated_at = datetime.utcnow()
            await self._log_audit("PROCESS_FAILED", event_id, {})

    async def stop_poller(self):
        self._poller_running = False
        if self._poller_task:
            self._poller_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poller_task
            self._poller_task = None
        for task in self._background_tasks:
            if not task.done():
                task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()
        logger.info("Event publisher poller stopped")

    # ------------------- STATUS & QUERY -------------------

    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        async with self._async_lock:
            event = self._events.get(event_id)
            if not event:
                return None
            return {
                "id": str(event.id),
                "event_type": event.event_type,
                "status": event.status.value,
                "created_at": event.created_at.isoformat(),
                "updated_at": event.updated_at.isoformat() if event.updated_at else None,
                "processed_at": event.processed_at.isoformat() if event.processed_at else None,
                "retry_count": event.retry_count,
                "error_message": event.error_message,
            }

    async def get_pending_count(self) -> int:
        async with self._async_lock:
            return sum(1 for e in self._events.values() if e.status == EventStatus.PENDING)

    async def get_processing_count(self) -> int:
        async with self._async_lock:
            return sum(1 for e in self._events.values() if e.status == EventStatus.PROCESSING)

    async def get_failed_count(self) -> int:
        async with self._async_lock:
            return sum(1 for e in self._events.values() if e.status == EventStatus.FAILED)

    async def get_dead_letter_count(self) -> int:
        return len(self._dead_letters)

    async def get_outbox_size(self) -> int:
        return len(self._events)

    async def flush(self) -> int:
        pending = []
        async with self._async_lock:
            for e in self._events.values():
                if e.status == EventStatus.PENDING and (not e.scheduled_at or e.scheduled_at <= datetime.utcnow()):
                    pending.append(e.id)
        for eid in pending:
            await self._process_event(eid)
        return len(pending)

    async def purge_outbox(self, older_than_days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        removed = 0
        async with self._async_lock:
            ids_to_remove = []
            for eid, event in self._events.items():
                if event.status == EventStatus.SENT and event.updated_at and event.updated_at < cutoff:
                    ids_to_remove.append(eid)
            for eid in ids_to_remove:
                del self._events[eid]
                removed += 1
        return removed

    async def retry_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> UUID | None:
        dead_event = None
        idx = -1
        async with self._async_lock:
            for i, e in enumerate(self._dead_letters):
                if e.id == dead_letter_id:
                    dead_event = e
                    idx = i
                    break
            if not dead_event:
                return None
            self._dead_letters.pop(idx)

        dead_event.status = EventStatus.PENDING
        dead_event.retry_count = 0
        dead_event.error_message = None
        dead_event.updated_at = datetime.utcnow()
        async with self._async_lock:
            self._events[dead_event.id] = dead_event
        await self._log_audit("RETRY_DEAD_LETTER", dead_event.id, {"user_id": str(user_id)})
        return dead_event.id

    async def skip_dead_letter(self, dead_letter_id: UUID, user_id: UUID) -> bool:
        async with self._async_lock:
            for i, e in enumerate(self._dead_letters):
                if e.id == dead_letter_id:
                    e.status = EventStatus.SKIPPED
                    self._dead_letters.pop(i)
                    await self._log_audit("SKIP_DEAD_LETTER", e.id, {"user_id": str(user_id)})
                    return True
            return False

    async def list_dead_letters(self, limit: int = 100, offset: int = 0) -> list[Any]:
        result = []
        for e in self._dead_letters[offset:offset+limit]:
            result.append({
                "id": str(e.id),
                "event_type": e.event_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
                "error_message": e.error_message,
                "retry_count": e.retry_count,
            })
        return result

    async def purge_dead_letters(self, older_than_days: int = 30) -> int:
        cutoff = datetime.utcnow() - timedelta(days=older_than_days)
        removed = 0
        async with self._async_lock:
            new_list = []
            for e in self._dead_letters:
                if e.created_at < cutoff:
                    removed += 1
                else:
                    new_list.append(e)
            self._dead_letters = new_list
        return removed

    async def get_statistics(self) -> dict[str, Any]:
        pending = await self.get_pending_count()
        processing = await self.get_processing_count()
        failed = await self.get_failed_count()
        dead = await self.get_dead_letter_count()
        total = await self.get_outbox_size()
        return {
            "total_events": total,
            "pending": pending,
            "processing": processing,
            "failed": failed,
            "dead_letters": dead,
            "handlers": {k: len(v) for k, v in self._handlers.items()},
            "poller_running": self._poller_running,
        }

    async def get_audit_log(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._audit_log[offset:offset+limit]

    async def health_check(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "poller_running": self._poller_running,
            "total_events": len(self._events),
            "dead_letters": len(self._dead_letters),
            "audit_log_size": len(self._audit_log),
        }


# ==================== EXPORTS ====================

__all__ = [
    "EventPriority",
    "EventPublisherPort",
    "EventStatus",
    "InMemoryEventPublisher",
]
