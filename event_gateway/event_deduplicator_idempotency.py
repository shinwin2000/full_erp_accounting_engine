#!/usr/bin/env python3
"""
Module: event_deduplicator_idempotency.py
Layer: Event Gateway
Responsibility: Mendeteksi dan mencegah pemrosesan event duplikat.

Metode yang ditambahkan:
- Untuk EventDeduplicator: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch, reset_stats.
- Untuk decorator idempotent: tetap dipertahankan.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from infrastructure.caching.redis_manager import get_redis_client

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)

REDIS_IDEMPOTENCY_PREFIX = "event:idempotent:"
REDIS_DEDUP_PREFIX = "event:dedup:"
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 3600
DEFAULT_DEDUP_TTL_SECONDS = 300
DUPLICATE_THRESHOLD_WARNING = 10
DUPLICATE_THRESHOLD_CRITICAL = 50


class DuplicateEventError(Exception):
    def __init__(self, event_id: str, reason: str = "Event already processed"):
        self.event_id = event_id
        self.reason = reason
        super().__init__(f"Duplicate event detected: {event_id} - {reason}")


class IdempotencyKeyError(Exception):
    pass


class EventDeduplicator:
    def __init__(self):
        self._redis = None
        self._duplicate_counter: dict[str, int] = {}
        self._last_alert_time: dict[str, datetime] = {}
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "timestamp": datetime.now(UTC).isoformat(),
                "duplicate_counts": self._duplicate_counter.copy(),
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

    def _generate_content_hash(
        self, payload: dict[str, Any], event_type: str, aggregate_id: str | None = None
    ) -> str:
        content = {"event_type": event_type, "aggregate_id": str(aggregate_id), "payload": payload}
        content_str = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(content_str.encode()).hexdigest()

    def _get_primary_key(self, event_id: UUID) -> str:
        return f"{REDIS_IDEMPOTENCY_PREFIX}{event_id}"

    def _get_content_key(self, content_hash: str) -> str:
        return f"{REDIS_DEDUP_PREFIX}{content_hash}"

    async def is_duplicate(
        self,
        event_id: UUID,
        event_type: str,
        aggregate_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        redis = await self._get_redis()
        primary_key = self._get_primary_key(event_id)
        exists = await redis.exists(primary_key)
        if exists:
            logger.debug(f"Duplicate detected by event_id: {event_id}")
            await self._record_duplicate(event_type, "event_id")
            return True
        if payload:
            content_hash = self._generate_content_hash(payload, event_type, str(aggregate_id))
            content_key = self._get_content_key(content_hash)
            exists = await redis.exists(content_key)
            if exists:
                logger.debug(f"Duplicate detected by content hash for {event_type}")
                await self._record_duplicate(event_type, "content_hash")
                return True
        return False

    async def mark_processed(
        self,
        event_id: UUID,
        event_type: str,
        aggregate_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
        ttl_seconds: int = DEFAULT_IDEMPOTENCY_TTL_SECONDS,
    ) -> None:
        redis = await self._get_redis()
        primary_key = self._get_primary_key(event_id)
        primary_data = {
            "event_type": event_type,
            "aggregate_id": str(aggregate_id),
            "processed_at": datetime.now(UTC).isoformat(),
            "ttl": ttl_seconds,
        }
        await redis.setex(primary_key, ttl_seconds, json.dumps(primary_data))
        if payload:
            content_hash = self._generate_content_hash(payload, event_type, str(aggregate_id))
            content_key = self._get_content_key(content_hash)
            await redis.setex(content_key, ttl_seconds, str(event_id))
        logger.debug(f"Event marked as processed: {event_id} ({event_type})")

    async def _record_duplicate(self, event_type: str, method: str) -> None:
        key = f"{event_type}:{method}"
        current_time = datetime.now(UTC)
        if key not in self._duplicate_counter:
            self._duplicate_counter[key] = 0
        self._duplicate_counter[key] += 1
        last_alert = self._last_alert_time.get(key)
        if last_alert and (current_time - last_alert).total_seconds() > 60:
            self._duplicate_counter[key] = 0
        count = self._duplicate_counter[key]
        if count >= DUPLICATE_THRESHOLD_CRITICAL:
            last_alert = self._last_alert_time.get(key)
            if not last_alert or (current_time - last_alert).total_seconds() > 300:
                logger.critical(
                    f"Massive event duplication: {event_type} {count} duplicates in last minute"
                )
                self._last_alert_time[key] = current_time
        elif count >= DUPLICATE_THRESHOLD_WARNING:
            last_alert = self._last_alert_time.get(f"{key}_warn")
            if not last_alert or (current_time - last_alert).total_seconds() > 300:
                logger.warning(
                    f"High event duplication: {event_type} {count} duplicates in last minute"
                )
                self._last_alert_time[f"{key}_warn"] = current_time

    async def is_idempotent_operation(
        self, operation_id: str, ttl_seconds: int = DEFAULT_IDEMPOTENCY_TTL_SECONDS
    ) -> bool:
        redis = await self._get_redis()
        key = f"{REDIS_IDEMPOTENCY_PREFIX}operation:{operation_id}"
        exists = await redis.exists(key)
        if not exists:
            await redis.setex(key, ttl_seconds, datetime.now(UTC).isoformat())
            return False
        return True

    async def get_event_status(self, event_id: UUID) -> dict[str, Any] | None:
        redis = await self._get_redis()
        key = self._get_primary_key(event_id)
        data = await redis.get(key)
        return json.loads(data) if data else None

    async def expire_event(self, event_id: UUID) -> bool:
        redis = await self._get_redis()
        key = self._get_primary_key(event_id)
        return await redis.delete(key) > 0

    async def cleanup_old_records(self, older_than_hours: int = 168) -> int:
        # Redis handles TTL automatically
        return 0

    async def get_stats(self) -> dict[str, Any]:
        return {
            "duplicate_counts": self._duplicate_counter.copy(),
            "threshold_warning": DUPLICATE_THRESHOLD_WARNING,
            "threshold_critical": DUPLICATE_THRESHOLD_CRITICAL,
            "default_ttl_seconds": DEFAULT_IDEMPOTENCY_TTL_SECONDS,
            "version": self._version,
        }

    async def reset_stats(self) -> None:
        self._duplicate_counter.clear()
        self._last_alert_time.clear()
        self._version += 1
        self._record_audit("RESET_STATS", "system", {})
        logger.info("Deduplicator stats reset")

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if DEFAULT_IDEMPOTENCY_TTL_SECONDS <= 0:
            errors.append("DEFAULT_IDEMPOTENCY_TTL_SECONDS must be positive")
        if DUPLICATE_THRESHOLD_WARNING <= 0:
            errors.append("DUPLICATE_THRESHOLD_WARNING must be positive")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "duplicate_counts": self._duplicate_counter,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventDeduplicator:
        instance = cls()
        instance._version = data.get("version", 1)
        instance._duplicate_counter = data.get("duplicate_counts", {})
        return instance

    def clone(self) -> EventDeduplicator:
        new = EventDeduplicator()
        new._duplicate_counter = self._duplicate_counter.copy()
        new._last_alert_time = self._last_alert_time.copy()
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "duplicate_counts": self._duplicate_counter,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventDeduplicator:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


def idempotent(key_prefix: str = "op", ttl_seconds: int = DEFAULT_IDEMPOTENCY_TTL_SECONDS):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            deduplicator = EventDeduplicator()
            import hashlib
            import json

            content = {
                "function": func.__name__,
                "args": [str(a) for a in args],
                "kwargs": {k: str(v) for k, v in kwargs.items()},
            }
            content_str = json.dumps(content, sort_keys=True)
            operation_hash = hashlib.sha256(content_str.encode()).hexdigest()
            operation_id = f"{key_prefix}:{operation_hash}"
            if await deduplicator.is_idempotent_operation(operation_id, ttl_seconds):
                logger.info(f"Idempotent operation {operation_id} already processed, skipping")
                return None
            result = await func(*args, **kwargs)
            return result

        return wrapper

    return decorator


__all__ = ["DuplicateEventError", "EventDeduplicator", "IdempotencyKeyError", "idempotent"]
