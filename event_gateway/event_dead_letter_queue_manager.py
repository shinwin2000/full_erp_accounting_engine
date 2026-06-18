#!/usr/bin/env python3
"""
Module: event_dead_letter_queue_manager.py
Layer: Event Gateway
Responsibility: Mengelola Dead Letter Queue (DLQ) untuk event yang gagal diproses.

Metode yang ditambahkan:
- Untuk DLQItem: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Untuk DeadLetterQueueManager: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from infrastructure.caching.redis_manager import get_redis_client

if TYPE_CHECKING:
    from event_gateway.event_envelope import EventEnvelope

logger = logging.getLogger(__name__)

REDIS_DLQ_PREFIX = "event:dlq:"
REDIS_DLQ_INDEX_PREFIX = "event:dlq:index:"
DEFAULT_MAX_DLQ_SIZE = 10000
DEFAULT_DLQ_TTL_DAYS = 30

DLQ_STATUS_PENDING = "pending"
DLQ_STATUS_PROCESSING = "processing"
DLQ_STATUS_REPLAYED = "replayed"
DLQ_STATUS_SKIPPED = "skipped"


@dataclass(kw_only=True)
class DLQItem:
    id: str
    event_id: str
    event_type: str
    aggregate_type: str
    payload: dict[str, Any]
    metadata: dict[str, Any]
    error_message: str
    failed_at: str
    retry_count: int
    aggregate_id: str | None = None
    status: str = DLQ_STATUS_PENDING
    replayed_at: str | None = None
    notes: str | None = None

    # Fields untuk audit dan versioning
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if not self.id:
            raise ValueError("id is required")
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        if self.retry_count < 0:
            raise ValueError("retry_count cannot be negative")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "item_id": self.id,
                "event_type": self.event_type,
                "status": self.status,
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
                "item_id": self.id,
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
            "id": self.id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "payload": self.payload,
            "metadata": self.metadata,
            "error_message": self.error_message,
            "failed_at": self.failed_at,
            "retry_count": self.retry_count,
            "status": self.status,
            "replayed_at": self.replayed_at,
            "notes": self.notes,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DLQItem:
        instance = cls(
            id=data["id"],
            event_id=data["event_id"],
            event_type=data["event_type"],
            aggregate_type=data["aggregate_type"],
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
            error_message=data["error_message"],
            failed_at=data["failed_at"],
            retry_count=data["retry_count"],
            aggregate_id=data.get("aggregate_id"),
            status=data.get("status", DLQ_STATUS_PENDING),
            replayed_at=data.get("replayed_at"),
            notes=data.get("notes"),
        )
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DLQItem:
        new_id = str(uuid4())
        cloned = DLQItem(
            id=new_id,
            event_id=self.event_id,
            event_type=self.event_type,
            aggregate_type=self.aggregate_type,
            payload=self.payload.copy(),
            metadata=self.metadata.copy(),
            error_message=self.error_message,
            failed_at=self.failed_at,
            retry_count=self.retry_count,
            aggregate_id=self.aggregate_id,
            status=DLQ_STATUS_PENDING,
            replayed_at=None,
            notes=f"Cloned from {self.id}",
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": self.id})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "id": self.id,
            "event_type": self.event_type,
            "status": self.status,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DLQItem:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    @classmethod
    def from_envelope(cls, envelope: EventEnvelope, error_message: str) -> DLQItem:
        return cls(
            id=str(uuid4()),
            event_id=str(envelope.id),
            event_type=envelope.event_type,
            aggregate_id=str(envelope.aggregate_id),
            aggregate_type=envelope.aggregate_type,
            payload=envelope.payload,
            metadata=envelope.metadata,
            failed_at=datetime.now(UTC).isoformat(),
            retry_count=0,
            status=DLQ_STATUS_PENDING,
            error_message=error_message,
        )


class DeadLetterQueueManager:
    def __init__(self):
        self._redis = None
        self._config = {"max_size": DEFAULT_MAX_DLQ_SIZE, "ttl_days": DEFAULT_DLQ_TTL_DAYS}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
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

    async def _get_redis(self):
        if self._redis is None:
            self._redis = await get_redis_client()
        return self._redis

    async def enqueue(self, envelope: EventEnvelope, error_message: str) -> None:
        dlq_item = DLQItem.from_envelope(envelope, error_message)
        redis = await self._get_redis()
        dlq_key = f"{REDIS_DLQ_PREFIX}{dlq_item.id}"
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        ttl = self._config["ttl_days"] * 24 * 3600
        await redis.setex(dlq_key, ttl, json.dumps(dlq_item.to_dict()))
        score = datetime.now(UTC).timestamp()
        await redis.zadd(index_key, {dlq_item.id: score})
        self._record_audit(
            "ENQUEUE", "system", {"item_id": dlq_item.id, "event_id": str(envelope.id)}
        )
        logger.warning(f"Event {envelope.id} added to DLQ: {error_message[:100]}")

    async def dequeue(self, item_id: str) -> DLQItem | None:
        redis = await self._get_redis()
        dlq_key = f"{REDIS_DLQ_PREFIX}{item_id}"
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        data = await redis.get(dlq_key)
        if not data:
            return None
        await redis.delete(dlq_key)
        await redis.zrem(index_key, item_id)
        self._record_audit("DEQUEUE", "system", {"item_id": item_id})
        return DLQItem.from_dict(json.loads(data))

    async def get_item(self, item_id: str) -> DLQItem | None:
        redis = await self._get_redis()
        dlq_key = f"{REDIS_DLQ_PREFIX}{item_id}"
        data = await redis.get(dlq_key)
        if not data:
            return None
        return DLQItem.from_dict(json.loads(data))

    async def list_items(
        self, limit: int = 100, offset: int = 0, event_type: str | None = None
    ) -> list[DLQItem]:
        redis = await self._get_redis()
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        item_ids = await redis.zrevrange(index_key, offset, offset + limit - 1)
        items = []
        for item_id in item_ids:
            item = await self.get_item(item_id)
            if item and (event_type is None or item.event_type == event_type):
                items.append(item)
        return items

    async def get_size(self) -> int:
        redis = await self._get_redis()
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        return await redis.zcard(index_key)

    async def replay_event(self, item_id: str, event_gate) -> bool:
        item = await self.get_item(item_id)
        if not item:
            logger.warning(f"DLQ item {item_id} not found")
            return False
        item.status = DLQ_STATUS_PROCESSING
        await self._update_item(item)
        try:
            from uuid import UUID

            from event_gateway.event_envelope import EventEnvelope

            envelope = EventEnvelope(
                id=UUID(item.event_id),
                event_type=item.event_type,
                event_version=1,
                aggregate_id=UUID(item.aggregate_id) if item.aggregate_id else None,
                aggregate_type=item.aggregate_type,
                occurred_at=datetime.fromisoformat(item.failed_at),
                payload=item.payload,
                metadata=item.metadata,
                correlation_id=item.metadata.get("correlation_id", str(uuid4())),
                causation_id=item.metadata.get("causation_id"),
                previous_hash="",
                priority="normal",
            )
            await event_gate.send(
                event=envelope.payload,
                event_type=envelope.event_type,
                aggregate_id=envelope.aggregate_id,
                aggregate_type=envelope.aggregate_type,
                metadata=envelope.metadata,
                causation_id=envelope.causation_id,
            )
            item.status = DLQ_STATUS_REPLAYED
            item.replayed_at = datetime.now(UTC).isoformat()
            await self._update_item(item)
            self._record_audit("REPLAY_SUCCESS", "system", {"item_id": item_id})
            logger.info(f"Event {item.event_id} replayed successfully from DLQ")
            return True
        except Exception as e:
            logger.error(f"Failed to replay event {item.event_id}: {e}")
            item.status = DLQ_STATUS_PENDING
            item.error_message = f"Replay failed: {e!s}"
            await self._update_item(item)
            self._record_audit("REPLAY_FAILED", "system", {"item_id": item_id, "error": str(e)})
            return False

    async def _update_item(self, item: DLQItem) -> None:
        redis = await self._get_redis()
        dlq_key = f"{REDIS_DLQ_PREFIX}{item.id}"
        ttl = self._config["ttl_days"] * 24 * 3600
        await redis.setex(dlq_key, ttl, json.dumps(item.to_dict()))

    async def delete_item(self, item_id: str) -> bool:
        redis = await self._get_redis()
        dlq_key = f"{REDIS_DLQ_PREFIX}{item_id}"
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        data = await redis.get(dlq_key)
        if not data:
            return False
        await redis.delete(dlq_key)
        await redis.zrem(index_key, item_id)
        self._record_audit("DELETE_ITEM", "system", {"item_id": item_id})
        logger.info(f"DLQ item {item_id} deleted")
        return True

    async def delete_all(self, event_type: str | None = None) -> int:
        items = await self.list_items(limit=10000)
        deleted = 0
        for item in items:
            if event_type is None or item.event_type == event_type:
                if await self.delete_item(item.id):
                    deleted += 1
        self._record_audit("DELETE_ALL", "system", {"event_type": event_type, "deleted": deleted})
        logger.info(
            f"Deleted {deleted} items from DLQ"
            + (f" (event_type={event_type})" if event_type else "")
        )
        return deleted

    async def get_stats(self) -> dict[str, Any]:
        size = await self.get_size()
        items = await self.list_items(limit=1000)
        by_type: dict[str, int] = {}
        for item in items:
            by_type[item.event_type] = by_type.get(item.event_type, 0) + 1
        oldest_age = await self._get_oldest_age_days()
        return {
            "size": size,
            "max_size": self._config["max_size"],
            "ttl_days": self._config["ttl_days"],
            "utilization_percent": (size / self._config["max_size"] * 100)
            if self._config["max_size"]
            else 0,
            "by_event_type": by_type,
            "oldest_item_age_days": oldest_age,
            "version": self._version,
        }

    async def _get_oldest_age_days(self) -> float | None:
        redis = await self._get_redis()
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        oldest_ids = await redis.zrange(index_key, 0, 0, withscores=True)
        if not oldest_ids:
            return None
        _, score = oldest_ids[0]
        age_seconds = datetime.now(UTC).timestamp() - score
        return age_seconds / (24 * 3600)

    async def cleanup_expired(self) -> int:
        redis = await self._get_redis()
        index_key = f"{REDIS_DLQ_INDEX_PREFIX}list"
        item_ids = await redis.zrange(index_key, 0, -1)
        deleted = 0
        for item_id in item_ids:
            dlq_key = f"{REDIS_DLQ_PREFIX}{item_id}"
            exists = await redis.exists(dlq_key)
            if not exists:
                await redis.zrem(index_key, item_id)
                deleted += 1
        if deleted:
            self._record_audit("CLEANUP_EXPIRED", "system", {"deleted": deleted})
            logger.info(f"Cleaned up {deleted} expired DLQ items")
        return deleted

    async def export_to_file(self, format: str = "json") -> bytes:
        items = await self.list_items(limit=10000)
        if format == "json":
            return json.dumps([item.to_dict() for item in items], indent=2, default=str).encode()
        elif format == "csv":
            import csv
            from io import StringIO

            output = StringIO()
            if items:
                writer = csv.DictWriter(output, fieldnames=items[0].to_dict().keys())
                writer.writeheader()
                for item in items:
                    writer.writerow(item.to_dict())
            return output.getvalue().encode()
        else:
            raise ValueError(f"Unsupported format: {format}")

    async def close(self) -> None:
        self._redis = None
        self._record_audit("CLOSE", "system", {})
        logger.info("DeadLetterQueueManager closed")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self._config["max_size"] <= 0:
            errors.append("max_size must be positive")
        if self._config["ttl_days"] <= 0:
            errors.append("ttl_days must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_size": self._config["max_size"],
            "ttl_days": self._config["ttl_days"],
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeadLetterQueueManager:
        instance = cls()
        instance._config["max_size"] = data.get("max_size", DEFAULT_MAX_DLQ_SIZE)
        instance._config["ttl_days"] = data.get("ttl_days", DEFAULT_DLQ_TTL_DAYS)
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> DeadLetterQueueManager:
        new = DeadLetterQueueManager()
        new._config = self._config.copy()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "max_size": self._config["max_size"],
            "ttl_days": self._config["ttl_days"],
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DeadLetterQueueManager:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


__all__ = ["DLQItem", "DeadLetterQueueManager"]
