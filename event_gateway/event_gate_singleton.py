#!/usr/bin/env python3
"""
Module: event_gate_singleton.py
Layer: Event Gateway
Responsibility: Event Gate Singleton - Pusat routing event seluruh sistem.

Metode yang ditambahkan:
- validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from event_gateway.event_dead_letter_queue_manager import DeadLetterQueueManager
from event_gateway.event_deduplicator_idempotency import EventDeduplicator
from event_gateway.event_envelope import EventEnvelope, EventPriority, EventStatus
from event_gateway.event_normalizer_canonical import EventNormalizer
from event_gateway.event_router_to_transformer import EventRouter
from event_gateway.event_schema_validator import EventSchemaValidator

# ============================================================================
# PERBAIKAN: Hapus import langsung dari infrastructure.event_store.append_only_store
# untuk menghindari circular import. get_audit_store akan diimpor secara lokal
# di dalam metode yang membutuhkannya.
# ============================================================================

logger = logging.getLogger(__name__)


class EventGateError(Exception):
    pass


class EventGateShutdownError(EventGateError):
    pass


class EventProcessingError(EventGateError):
    pass


class EventGate:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._validator = EventSchemaValidator()
        self._normalizer = EventNormalizer()
        self._deduplicator = EventDeduplicator()
        self._router = EventRouter()
        self._dead_letter_queue = DeadLetterQueueManager()
        self._subscribers: dict[str, list] = {}
        self._is_running = True
        self._event_counter = 0
        self._last_hash: str | None = None
        self._router_started = False
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()
        logger.info("Event Gate initialized")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "event_counter": self._event_counter,
                "is_running": self._is_running,
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

    async def _ensure_router_started(self):
        if not self._router_started:
            await self._router.start()
            self._router_started = True

    async def _get_last_hash(self) -> str:
        if self._last_hash:
            return self._last_hash
        try:
            # PERBAIKAN: Import lokal untuk menghindari circular import
            from infrastructure.event_store.append_only_store import get_audit_store

            store = await get_audit_store()
            if store:
                last = await store.get_last_record("event_gate")
                if last and last.get("hash"):
                    self._last_hash = last["hash"]
                    return self._last_hash
        except Exception as e:
            logger.warning(f"Failed to get last hash from audit store: {e}")
        self._last_hash = hashlib.sha256(b"EVENT_GATE_GENESIS_2025").hexdigest()
        return self._last_hash

    async def _update_last_hash(self, new_hash: str) -> None:
        self._last_hash = new_hash

    # ==================== FIX: Parameter order - non-default before defaults ====================
    async def send(
        self,
        event: Any,
        event_type: str,
        aggregate_type: str,  # non-default (moved before optional)
        aggregate_id: UUID | None = None,  # now after non-default
        metadata: dict[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        causation_id: str | None = None,
    ) -> UUID:
        if not self._is_running:
            raise EventGateShutdownError("Event Gate is shutting down")

        event_id = uuid4()
        correlation_id = str(uuid4())
        occurred_at = datetime.now(UTC)
        previous_hash = await self._get_last_hash()

        if hasattr(event, "to_dict"):
            payload = event.to_dict()
        elif hasattr(event, "__dict__"):
            payload = {k: v for k, v in event.__dict__.items() if not k.startswith("_")}
        else:
            payload = event if isinstance(event, dict) else {"value": str(event)}

        envelope = EventEnvelope(
            id=event_id,
            event_type=event_type,
            event_version=1,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            occurred_at=occurred_at,
            payload=payload,
            metadata=metadata or {},
            correlation_id=correlation_id,
            causation_id=causation_id,
            previous_hash=previous_hash,
            priority=priority,
        )

        try:
            envelope.status = EventStatus.VALIDATED
            await self._validator.validate(envelope)

            envelope.status = EventStatus.NORMALIZED
            canonical = await self._normalizer.normalize(envelope)
            envelope.payload = canonical.payload

            if await self._deduplicator.is_duplicate(event_id, event_type, aggregate_id):
                envelope.status = EventStatus.DUPLICATE
                logger.warning(f"Duplicate event detected: {event_type}")
                return event_id
            await self._deduplicator.mark_processed(event_id, event_type, aggregate_id)

            await self._ensure_router_started()
            envelope.status = EventStatus.ROUTED
            await self._router.route(envelope)

            await self._notify_subscribers(envelope)
            await self._update_last_hash(envelope.hash)
            await self._audit_log(envelope)

            envelope.status = EventStatus.PROCESSED
            self._event_counter += 1
            self._take_snapshot()
            self._record_audit(
                "SEND_SUCCESS", "system", {"event_id": str(event_id), "event_type": event_type}
            )
            logger.info(f"Event processed: {event_type} [{event_id}]")
            return event_id

        except Exception as e:
            logger.exception(f"Error processing event {event_id}: {e}")
            await self._dead_letter_queue.enqueue(envelope, str(e))
            self._record_audit(
                "SEND_FAILED", "system", {"event_id": str(event_id), "error": str(e)}
            )
            raise EventProcessingError(f"Event processing failed: {e}") from e

    async def _notify_subscribers(self, envelope: EventEnvelope) -> None:
        subscribers = self._subscribers.get(envelope.event_type, []) + self._subscribers.get(
            "*", []
        )
        if not subscribers:
            return
        await asyncio.gather(*[sub(envelope) for sub in subscribers], return_exceptions=True)

    async def _audit_log(self, envelope: EventEnvelope, error: str | None = None) -> None:
        try:
            # PERBAIKAN: Import lokal untuk menghindari circular import
            from infrastructure.event_store.append_only_store import get_audit_store

            store = await get_audit_store()
            if store:
                record = envelope.to_dict()
                if error:
                    record["error"] = error
                await store.append("event_gate", record)
        except Exception as e:
            logger.error(f"Failed to audit log event {envelope.id}: {e}")

    def subscribe(self, event_type: str, callback) -> None:
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        self._record_audit("SUBSCRIBE", "system", {"event_type": event_type})
        logger.debug(f"Subscriber added for event type: {event_type}")

    def unsubscribe(self, event_type: str, callback) -> None:
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
                self._record_audit("UNSUBSCRIBE", "system", {"event_type": event_type})
            except ValueError:
                pass

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_events_processed": self._event_counter,
            "is_running": self._is_running,
            "subscriber_count": sum(len(v) for v in self._subscribers.values()),
            "event_types": list(self._subscribers.keys()),
            "last_hash": self._last_hash[:16] + "..." if self._last_hash else None,
            "version": self._version,
        }

    async def shutdown(self) -> None:
        logger.info("Event Gate shutting down...")
        self._is_running = False
        await asyncio.sleep(1)
        if self._router_started:
            try:
                await self._router.stop()
            except Exception as e:
                logger.warning(f"Error stopping router: {e}")
        try:
            await self._dead_letter_queue.close()
        except Exception as e:
            logger.warning(f"Error closing dead letter queue: {e}")
        self._record_audit("SHUTDOWN", "system", {})
        logger.info("Event Gate shutdown complete")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not self._is_running and self._event_counter > 0:
            errors.append("Gate is not running but has processed events")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "event_counter": self._event_counter,
            "subscriber_count": sum(len(v) for v in self._subscribers.values()),
            "router_started": self._router_started,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventGate:
        instance = cls()
        instance._is_running = data.get("is_running", True)
        instance._event_counter = data.get("event_counter", 0)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> EventGate:
        new = EventGate()
        new._is_running = self._is_running
        new._event_counter = 0
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "event_counter": self._event_counter,
            "is_running": self._is_running,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventGate:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


_event_gate: EventGate | None = None


async def get_event_gate() -> EventGate:
    global _event_gate
    if _event_gate is None:
        _event_gate = EventGate()
    return _event_gate


async def shutdown_event_gate() -> None:
    global _event_gate
    if _event_gate:
        await _event_gate.shutdown()
        _event_gate = None


async def get_event_gate_dep():
    return await get_event_gate()


def get_instance() -> EventGate:
    global _event_gate
    if _event_gate is None:
        _event_gate = EventGate()
    return _event_gate


async def shutdown() -> None:
    await shutdown_event_gate()


__all__ = [
    "EventGate",
    "EventGateError",
    "EventGateShutdownError",
    "EventProcessingError",
    "get_event_gate",
    "get_instance",
    "shutdown",
    "shutdown_event_gate",
]
