#!/usr/bin/env python3
"""
Module: event_envelope.py
Layer: Event Gateway
Responsibility: Mendefinisikan EventEnvelope, EventPriority, EventStatus.
Dipisahkan dari event_gate_singleton.py untuk menghindari circular import.
Menjamin integritas forensic audit trail melalui SHA-256 hash chaining.

Metode yang ditambahkan:
- validate(), to_dict(), from_dict(), clone(), snapshot(), version(), audit_trail(), touch()
- Untuk EventEnvelope, EventPriority, EventStatus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class EventPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

    def display_name(self) -> str:
        names = {
            EventPriority.LOW: "Rendah",
            EventPriority.NORMAL: "Normal",
            EventPriority.HIGH: "Tinggi",
            EventPriority.CRITICAL: "Kritis",
        }
        return names.get(self, self.value)


class EventStatus(str, Enum):
    RECEIVED = "received"
    VALIDATED = "validated"
    NORMALIZED = "normalized"
    ROUTED = "routed"
    PROCESSED = "processed"
    FAILED = "failed"
    DUPLICATE = "duplicate"

    def display_name(self) -> str:
        names = {
            EventStatus.RECEIVED: "Diterima",
            EventStatus.VALIDATED: "Tervalidasi",
            EventStatus.NORMALIZED: "Ternormalisasi",
            EventStatus.ROUTED: "Dirutekan",
            EventStatus.PROCESSED: "Diproses",
            EventStatus.FAILED: "Gagal",
            EventStatus.DUPLICATE: "Duplikat",
        }
        return names.get(self, self.value)


@dataclass(kw_only=True)
class EventEnvelope:
    """
    Envelope untuk event yang melewati Event Gate.
    Membungkus event asli dengan metadata.
    """

    id: UUID
    event_type: str
    aggregate_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    metadata: dict[str, Any]
    correlation_id: str
    causation_id: str | None
    previous_hash: str
    event_version: int = 1
    aggregate_id: UUID | None = None
    hash: str = field(default="")
    status: EventStatus = EventStatus.RECEIVED
    priority: EventPriority = EventPriority.NORMAL

    # Fields untuk audit dan versioning
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        if not self.hash:
            self.hash = self._compute_hash()
        self._take_snapshot()
        self._validate()

    def _validate(self):
        if self.event_version < 1:
            raise ValueError("event_version must be >= 1")
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.aggregate_type:
            raise ValueError("aggregate_type is required")
        if not self.correlation_id:
            raise ValueError("correlation_id is required")

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self._version,
                "event_id": str(self.id),
                "event_type": self.event_type,
                "status": self.status.value,
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
                "event_id": str(self.id),
                "details": details,
            }
        )

    def _compute_hash(self) -> str:
        """Compute SHA-256 hash of the envelope content (without hash field for idempotency)."""
        data = {
            "id": str(self.id),
            "event_type": self.event_type,
            "event_version": self.event_version,
            "aggregate_id": str(self.aggregate_id) if self.aggregate_id else None,
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
            "metadata": self.metadata,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "previous_hash": self.previous_hash,
            "priority": self.priority.value,
        }
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if len(self.previous_hash) != 64:
            errors.append("previous_hash must be 64 hex characters")
        if len(self.hash) != 64:
            errors.append("hash must be 64 hex characters")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "event_version": self.event_version,
            "aggregate_id": str(self.aggregate_id) if self.aggregate_id else None,
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
            "metadata": self.metadata,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
            "status": self.status.value,
            "priority": self.priority.value,
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        return cls(
            id=UUID(data["id"]),
            event_type=data["event_type"],
            event_version=data.get("event_version", 1),
            aggregate_id=UUID(data["aggregate_id"]) if data.get("aggregate_id") else None,
            aggregate_type=data["aggregate_type"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            payload=data["payload"],
            metadata=data["metadata"],
            correlation_id=data["correlation_id"],
            causation_id=data.get("causation_id"),
            previous_hash=data["previous_hash"],
            hash=data.get("hash", ""),
            status=EventStatus(data.get("status", "received")),
            priority=EventPriority(data.get("priority", "normal")),
        )

    def clone(self) -> EventEnvelope:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = EventEnvelope(
            id=new_id,
            event_type=self.event_type,
            event_version=self.event_version + 1,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            occurred_at=now,
            payload=self.payload.copy(),
            metadata=self.metadata.copy(),
            correlation_id=self.correlation_id,
            causation_id=str(self.id),
            previous_hash=self.hash,
            priority=self.priority,
            status=EventStatus.RECEIVED,
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "event_id": str(self.id),
            "event_type": self.event_type,
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EventEnvelope:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


__all__ = ["EventEnvelope", "EventPriority", "EventStatus"]
