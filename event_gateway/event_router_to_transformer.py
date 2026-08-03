#!/usr/bin/env python3
"""
Module: event_router_to_transformer.py
Layer: Event Gateway
Responsibility: Mengirim event yang sudah dinormalisasi ke transformer yang terdaftar.

Metode yang ditambahkan:
- Untuk QueuedEvent: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk TransformerRegistry: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk EventRouter: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch,
  reset, flush_queue, get_queue_stats, get_metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from event_gateway.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = [1, 5, 30]
MAX_QUEUE_SIZE = 10000
QUEUE_PROCESS_BATCH_SIZE = 10
PROCESSING_TIMEOUT_SECONDS = 30


class TransformerNotFoundError(Exception):
    pass


class TransformerExecutionError(Exception):
    pass


class QueueFullError(Exception):
    pass


@dataclass(order=True)
class QueuedEvent:
    # --- Non-default fields MUST come before default fields ---
    envelope: EventEnvelope = field(compare=False)  # required, no default
    # --- Default fields ---
    priority: int = 10
    timestamp: float = field(default_factory=time.time)
    retry_count: int = field(default=0, compare=False)
    transformer_names: list[str] = field(default_factory=list, compare=False)

    # Audit & versioning fields (all have defaults, placed last)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1
    _id: str = field(default_factory=lambda: str(uuid4()), repr=False)

    def __post_init__(self):
        self._validate()
        self._take_snapshot()

    def _validate(self):
        if self.priority < 0:
            raise ValueError("priority cannot be negative")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")
        if not self.envelope:
            raise ValueError("envelope is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "queued_id": self._id,
                "priority": self.priority,
                "retry_count": self.retry_count,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "queued_id": self._id,
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self._id,
            "priority": self.priority,
            "envelope_id": str(self.envelope.id) if self.envelope else None,
            "timestamp": self.timestamp,
            "retry_count": self.retry_count,
            "transformer_names": self.transformer_names,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], envelope: EventEnvelope) -> QueuedEvent:
        instance = cls(
            envelope=envelope,
            priority=data.get("priority", 10),
            timestamp=data.get("timestamp", time.time()),
            retry_count=data.get("retry_count", 0),
            transformer_names=data.get("transformer_names", []),
        )
        instance._id = data.get("id", str(uuid4()))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> QueuedEvent:
        import copy

        new = QueuedEvent(
            envelope=copy.deepcopy(self.envelope),
            priority=self.priority,
            timestamp=time.time(),
            retry_count=0,
            transformer_names=self.transformer_names.copy(),
        )
        new._version = self._version + 1
        new._record_audit("CLONE", "system", {"source": self._id})
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "id": self._id,
            "priority": self.priority,
            "retry_count": self.retry_count,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> QueuedEvent:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class TransformerRegistry:
    def __init__(self):
        self._transformers: dict[str, list[Callable[[EventEnvelope], Awaitable[None]]]] = {}
        self._priority: dict[str, int] = {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "event_types": list(self._transformers.keys()),
                "total_transformers": sum(len(v) for v in self._transformers.values()),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def register(
        self,
        event_type: str,
        transformer: Callable[[EventEnvelope], Awaitable[None]],
        priority: int = 10,
    ):
        if event_type not in self._transformers:
            self._transformers[event_type] = []
        self._transformers[event_type].append(transformer)
        self._priority[transformer.__name__] = priority
        self._transformers[event_type].sort(key=lambda t: self._priority.get(t.__name__, 10))
        self._record_audit("REGISTER", "system", {"event_type": event_type, "priority": priority})
        logger.info(f"Transformer registered for event type: {event_type} (priority={priority})")

    def unregister(self, event_type: str, transformer: Callable) -> bool:
        if event_type in self._transformers:
            try:
                self._transformers[event_type].remove(transformer)
                self._record_audit("UNREGISTER", "system", {"event_type": event_type})
                logger.info(f"Transformer unregistered for event type: {event_type}")
                return True
            except ValueError:
                pass
        return False

    def get_transformers(self, event_type: str) -> list[Callable[[EventEnvelope], Awaitable[None]]]:
        transformers = []
        if event_type in self._transformers:
            transformers.extend(self._transformers[event_type])
        if "*" in self._transformers:
            transformers.extend(self._transformers["*"])
        return transformers

    def has_transformer(self, event_type: str) -> bool:
        return (
            event_type in self._transformers and self._transformers[event_type]
        ) or "*" in self._transformers

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_types": list(self._transformers.keys()),
            "transformers_count": sum(len(v) for v in self._transformers.values()),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransformerRegistry:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> TransformerRegistry:
        new = TransformerRegistry()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "event_types": list(self._transformers.keys()),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TransformerRegistry:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


class EventRouter:
    def __init__(self, max_queue_size: int = MAX_QUEUE_SIZE):
        self._registry = TransformerRegistry()
        self._queue: list[QueuedEvent] = []
        self._queue_lock = asyncio.Lock()
        self._processing = True
        self._max_queue_size = max_queue_size
        self._retry_config = DEFAULT_RETRY_DELAY_SECONDS
        self._batch_size = QUEUE_PROCESS_BATCH_SIZE
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._metrics = {
            "processed_total": 0,
            "failed_total": 0,
            "retried_total": 0,
            "last_processed_at": None,
        }
        # ===== SEMUA TASK DISIMPAN DI SINI =====
        self._pending_tasks: list[asyncio.Task] = []
        self._worker_task: asyncio.Task | None = None
        self._take_snapshot()

    def _add_pending_task(self, task: asyncio.Task) -> None:
        """Tambahkan task ke daftar pending dan daftarkan callback untuk menghapusnya."""
        self._pending_tasks.append(task)
        task.add_done_callback(
            lambda t: self._pending_tasks.remove(t) if t in self._pending_tasks else None
        )

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "queue_size": len(self._queue),
                "processing": self._processing,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    # ========================================================================
    # LIFECYCLE
    # ========================================================================

    async def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._processing = True
            self._worker_task = asyncio.create_task(self._process_queue())
            self._add_pending_task(self._worker_task)  # worker juga dikelola
            self._record_audit("START", "system", {})
            logger.info("Event router started")

    async def stop(self) -> None:
        self._processing = False
        # Batalkan semua task pending (termasuk worker)
        if self._pending_tasks:
            for task in self._pending_tasks:
                if not task.done():
                    task.cancel()
            # Tunggu hingga semua task selesai
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.gather(*self._pending_tasks, return_exceptions=True)
            self._pending_tasks.clear()
        self._worker_task = None
        self._record_audit("STOP", "system", {})
        logger.info("Event router stopped")

    # ========================================================================
    # ROUTING
    # ========================================================================

    async def route(self, envelope: EventEnvelope, priority: int = 10) -> None:
        if not self._registry.has_transformer(envelope.event_type):
            logger.warning(f"No transformer for event type: {envelope.event_type}")
            return
        queued = QueuedEvent(
            envelope=envelope,
            priority=priority,
            transformer_names=self._get_transformer_names(envelope.event_type),
        )
        async with self._queue_lock:
            if len(self._queue) >= self._max_queue_size:
                raise QueueFullError(
                    f"Event queue size {len(self._queue)} exceeds limit {self._max_queue_size}"
                )
            heapq.heappush(self._queue, queued)
            logger.debug(
                f"Event queued: {envelope.event_type} (priority={priority}, queue_size={len(self._queue)})"
            )

    def _get_transformer_names(self, event_type: str) -> list[str]:
        transformers = self._registry.get_transformers(event_type)
        return [t.__name__ for t in transformers]

    # ========================================================================
    # QUEUE PROCESSING
    # ========================================================================

    async def _process_queue(self) -> None:
        logger.info("Router worker started")
        while self._processing:
            try:
                batch = await self._get_batch()
                if not batch:
                    await asyncio.sleep(0.1)
                    continue
                tasks = []
                for queued in batch:
                    task = asyncio.create_task(self._process_event_with_timeout(queued))
                    self._add_pending_task(task)
                    tasks.append(task)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            except asyncio.CancelledError:
                logger.debug("Router worker loop cancelled")
                break
            except Exception as e:
                logger.exception(f"Error in router worker: {e}")
                await asyncio.sleep(1)
        logger.info("Router worker stopped")

    async def _get_batch(self) -> list[QueuedEvent]:
        async with self._queue_lock:
            batch = []
            for _ in range(self._batch_size):
                if not self._queue:
                    break
                batch.append(heapq.heappop(self._queue))
            return batch

    # ========================================================================
    # EVENT PROCESSING
    # ========================================================================

    async def _process_event_with_timeout(self, queued: QueuedEvent) -> None:
        try:
            await asyncio.wait_for(self._process_event(queued), timeout=PROCESSING_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.error(
                f"Event {queued.envelope.id} processing timed out after {PROCESSING_TIMEOUT_SECONDS}s"
            )
            await self._handle_failure(queued, TimeoutError("Processing timeout"))
        except Exception as e:
            await self._handle_failure(queued, e)

    async def _process_event(self, queued: QueuedEvent) -> None:
        envelope = queued.envelope
        start_time = time.time()
        transformers = self._registry.get_transformers(envelope.event_type)
        if not transformers:
            return

        for transformer in transformers:
            try:
                await transformer(envelope)
                logger.debug(f"Event {envelope.id} processed by {transformer.__name__}")
            except Exception as e:
                logger.error(
                    f"Transformer {transformer.__name__} failed for event {envelope.id}: {e}"
                )
                raise TransformerExecutionError(
                    f"Transformer {transformer.__name__} failed: {e}"
                ) from e

        latency = time.time() - start_time
        self._metrics["processed_total"] += 1
        self._metrics["last_processed_at"] = datetime.now(UTC).isoformat()
        logger.debug(f"Event {envelope.id} routed successfully in {latency:.3f}s")

    # ========================================================================
    # FAILURE HANDLING
    # ========================================================================

    async def _handle_failure(self, queued: QueuedEvent, error: Exception) -> None:
        envelope = queued.envelope
        if queued.retry_count < DEFAULT_MAX_RETRIES:
            delay = self._retry_config[min(queued.retry_count, len(self._retry_config) - 1)]
            queued.retry_count += 1
            queued.priority += 5  # lower priority on retry
            logger.info(
                f"Retrying event {envelope.id} in {delay}s (attempt {queued.retry_count}/{DEFAULT_MAX_RETRIES})"
            )
            task = asyncio.create_task(self._requeue_with_delay(queued, delay))
            self._add_pending_task(task)
            self._metrics["retried_total"] += 1
        else:
            logger.error(f"Event {envelope.id} failed after {DEFAULT_MAX_RETRIES} retries: {error}")
            self._metrics["failed_total"] += 1

    async def _requeue_with_delay(self, queued: QueuedEvent, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._queue_lock:
            heapq.heappush(self._queue, queued)
            logger.debug(f"Event {queued.envelope.id} requeued after delay")

    # ========================================================================
    # TRANSFORMER REGISTRATION
    # ========================================================================

    def register_transformer(
        self,
        event_type: str,
        transformer: Callable[[EventEnvelope], Awaitable[None]],
        priority: int = 10,
    ) -> None:
        self._registry.register(event_type, transformer, priority)

    def unregister_transformer(
        self, event_type: str, transformer: Callable[[EventEnvelope], Awaitable[None]]
    ) -> bool:
        return self._registry.unregister(event_type, transformer)

    def has_transformers(self, event_type: str) -> bool:
        return self._registry.has_transformer(event_type)

    # ========================================================================
    # STATUS & METRICS
    # ========================================================================

    async def get_queue_stats(self) -> dict[str, Any]:
        async with self._queue_lock:
            size = len(self._queue)
            return {
                "queue_size": size,
                "max_queue_size": self._max_queue_size,
                "utilization_percent": (size / self._max_queue_size) * 100
                if self._max_queue_size
                else 0,
                "processing": self._processing,
                "version": self._version,
            }

    async def get_metrics(self) -> dict[str, Any]:
        return {
            **self._metrics,
            "queue_size": len(self._queue),
            "max_retries": DEFAULT_MAX_RETRIES,
        }

    async def flush_queue(self, timeout_seconds: int = 60) -> int:
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            async with self._queue_lock:
                if len(self._queue) == 0:
                    return 0
            await asyncio.sleep(0.5)
        async with self._queue_lock:
            remaining = len(self._queue)
            logger.warning(f"Flush timeout, {remaining} events still in queue")
            return remaining

    def reset(self) -> None:
        self._queue.clear()
        self._processing = True
        self._version += 1
        self._audit_trail = []
        self._snapshots = []
        self._metrics = {
            "processed_total": 0,
            "failed_total": 0,
            "retried_total": 0,
            "last_processed_at": None,
        }
        self._record_audit("RESET", "system", {})

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._max_queue_size <= 0:
            errors.append("max_queue_size must be positive")
        if self._batch_size <= 0:
            errors.append("batch_size must be positive")
        if self._batch_size > self._max_queue_size:
            errors.append("batch_size cannot exceed max_queue_size")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_queue_size": self._max_queue_size,
            "batch_size": self._batch_size,
            "processing": self._processing,
            "queue_size": len(self._queue),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventRouter:
        instance = cls(max_queue_size=data.get("max_queue_size", MAX_QUEUE_SIZE))
        instance._batch_size = data.get("batch_size", QUEUE_PROCESS_BATCH_SIZE)
        instance._processing = data.get("processing", True)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EventRouter:
        new = EventRouter(max_queue_size=self._max_queue_size)
        new._batch_size = self._batch_size
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "queue_size": len(self._queue),
            "processing": self._processing,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventRouter:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


__all__ = [
    "EventRouter",
    "QueueFullError",
    "TransformerExecutionError",
    "TransformerNotFoundError",
    "TransformerRegistry",
]
