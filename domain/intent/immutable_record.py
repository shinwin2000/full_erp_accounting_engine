#!/usr/bin/env python3
# ruff: noqa: UP006
"""
Module: immutable_record.py
Layer: 5 - Reality, Intent, Causality / Intent
Responsibility: Rekaman maksud yang tidak bisa diubah.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, List  # noqa: UP035
from uuid import UUID, uuid4

from domain.intent.intent_type import IntentType

logger = logging.getLogger(__name__)


class IntentStatus(Enum):
    DRAFT = auto()
    SUBMITTED = auto()
    APPROVED = auto()
    REJECTED = auto()
    EXECUTED = auto()
    CANCELLED = auto()


class IntentSource(Enum):
    USER = auto()
    API = auto()
    SYSTEM = auto()
    IMPORT = auto()
    WEBHOOK = auto()


@dataclass(frozen=True)
class ImmutableIntentRecord:
    intent_id: UUID
    intent_type: IntentType
    data: dict[str, Any]
    created_by: str
    created_at: datetime
    status: IntentStatus
    signed_by: str
    signature: str
    parent_intent_id: UUID | None = None
    source: IntentSource = IntentSource.USER
    source_id: str | None = None
    version: int = 1
    previous_hash: str | None = None
    cryptographic_hash: str = ""

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if not isinstance(self.intent_id, UUID):
            raise TypeError("intent_id must be UUID")
        if not isinstance(self.data, dict):
            raise TypeError("data must be dict")
        if not self.created_by or not isinstance(self.created_by, str):
            raise ValueError("created_by must be non-empty string")
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be datetime")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if not isinstance(self.status, IntentStatus):
            raise TypeError("status must be IntentStatus")
        if not self.signed_by or not isinstance(self.signed_by, str):
            raise ValueError("signed_by must be non-empty string")
        if not self.signature or not isinstance(self.signature, str):
            raise ValueError("signature must be non-empty string")
        if self.parent_intent_id is not None and not isinstance(self.parent_intent_id, UUID):
            raise TypeError("parent_intent_id must be UUID or None")
        if not isinstance(self.source, IntentSource):
            raise TypeError("source must be IntentSource")
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.previous_hash is not None and not isinstance(self.previous_hash, str):
            raise TypeError("previous_hash must be str or None")
        if self.cryptographic_hash and self.cryptographic_hash != self.compute_hash():
            raise ValueError("Cryptographic hash mismatch")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "intent_id": str(self.intent_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "intent_id": str(self.intent_id),
                "details": details,
            }
        )

    def compute_hash(self) -> str:
        content = {
            "intent_id": str(self.intent_id),
            "intent_type": self.intent_type.name,
            "data": self.data,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "status": self.status.name,
            "signed_by": self.signed_by,
            "signature": self.signature[:32] + "..."
            if len(self.signature) > 32
            else self.signature,
            "parent_intent_id": str(self.parent_intent_id) if self.parent_intent_id else None,
            "version": self.version,
            "previous_hash": self.previous_hash,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ImmutableIntentRecord:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> ImmutableIntentRecord:
        raise AttributeError("ImmutableIntentRecord cannot be updated. Create amendment instead.")

    def delete(self, deleted_by: str, reason: str | None = None) -> ImmutableIntentRecord:
        raise AttributeError("ImmutableIntentRecord cannot be deleted. Cancel instead.")

    def restore(self, restored_by: str) -> ImmutableIntentRecord:
        raise AttributeError("ImmutableIntentRecord cannot be restored.")

    def activate(self, activated_by: str) -> ImmutableIntentRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ImmutableIntentRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> ImmutableIntentRecord:
        return self

    def unlock(self, unlocked_by: str) -> ImmutableIntentRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except (ValueError, TypeError) as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "intent_id": str(self.intent_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": str(self.intent_id),
            "intent_type": self.intent_type.name,
            "data": self.data,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "status": self.status.name,
            "signed_by": self.signed_by,
            "signature": self.signature[:16] + "..."
            if len(self.signature) > 16
            else self.signature,
            "parent_intent_id": str(self.parent_intent_id) if self.parent_intent_id else None,
            "source": self.source.name,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImmutableIntentRecord:
        return cls(
            intent_id=UUID(data["intent_id"]),
            intent_type=IntentType.from_string(data["intent_type"]),
            data=data["data"],
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            status=IntentStatus[data["status"]],
            signed_by=data["signed_by"],
            signature=data["signature"],
            parent_intent_id=UUID(data["parent_intent_id"])
            if data.get("parent_intent_id")
            else None,
            source=IntentSource[data["source"]] if data.get("source") else IntentSource.USER,
            version=data.get("version", 1),
            previous_hash=data.get("previous_hash"),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> ImmutableIntentRecord:
        new_id = uuid4()
        return ImmutableIntentRecord(
            intent_id=new_id,
            intent_type=self.intent_type,
            data=self.data.copy(),
            created_by=self.created_by,
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by=self.signed_by,
            signature=self.signature,
            parent_intent_id=self.intent_id,
            source=self.source,
            source_id=self.source_id,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "intent_id": str(self.intent_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ImmutableIntentRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_approved(self) -> bool:
        return self.status == IntentStatus.APPROVED

    def is_executable(self) -> bool:
        return self.status == IntentStatus.APPROVED

    def create_amendment(
        self, new_data: dict[str, Any], created_by: str, signed_by: str, signature: str, reason: str
    ) -> ImmutableIntentRecord:
        amended_data = self.data.copy()
        amended_data.update(new_data)
        amended_data["amendment_reason"] = reason
        amended_data["original_intent_id"] = str(self.intent_id)
        return ImmutableIntentRecord(
            intent_id=uuid4(),
            intent_type=self.intent_type,
            data=amended_data,
            created_by=created_by,
            created_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            signed_by=signed_by,
            signature=signature,
            parent_intent_id=self.intent_id,
            source=self.source,
            source_id=self.source_id,
            version=self.version + 1,
            previous_hash=self.cryptographic_hash,
        )


class ImmutableIntentRecordService:
    _instance: ImmutableIntentRecordService | None = None
    _initialized: bool = False

    def __new__(cls) -> ImmutableIntentRecordService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._records: dict[UUID, ImmutableIntentRecord] = {}
        self._lock = threading.RLock()

    def store(self, record: ImmutableIntentRecord) -> None:
        with self._lock:
            if record.intent_id in self._records:
                raise ValueError(f"Record with intent_id {record.intent_id} already exists")
            self._records[record.intent_id] = record

    def get(self, intent_id: UUID) -> ImmutableIntentRecord | None:
        with self._lock:
            return self._records.get(intent_id)

    def get_chain(self, intent_id: UUID) -> List[ImmutableIntentRecord]:
        with self._lock:
            chain: List[ImmutableIntentRecord] = []
            current = self._records.get(intent_id)
            while current:
                chain.insert(0, current)
                if current.parent_intent_id:
                    current = self._records.get(current.parent_intent_id)
                else:
                    break
            return chain

    def get_by_status(self, status: IntentStatus, limit: int = 100) -> List[ImmutableIntentRecord]:
        with self._lock:
            result = [r for r in self._records.values() if r.status == status]
            result.sort(key=lambda r: r.created_at, reverse=True)
            return result[:limit]

    def get_all(self) -> List[ImmutableIntentRecord]:
        with self._lock:
            return list(self._records.values())

    def count(self) -> int:
        with self._lock:
            return len(self._records)

    def list(self, limit: int = 100, offset: int = 0) -> List[ImmutableIntentRecord]:
        records = self.get_all()
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[offset : offset + limit]

    def paginate(
        self, page: int = 1, per_page: int = 20
    ) -> tuple[List[ImmutableIntentRecord], int]:
        records = self.get_all()
        total = len(records)
        records.sort(key=lambda r: r.created_at, reverse=True)
        start = (page - 1) * per_page
        end = start + per_page
        return records[start:end], total

    def exists(self, intent_id: UUID) -> bool:
        return self.get(intent_id) is not None

    def search(self, query: str, fields: List[str] | None = None) -> List[ImmutableIntentRecord]:
        query_lower = query.lower()
        results: List[ImmutableIntentRecord] = []
        with self._lock:
            for rec in self._records.values():
                if query_lower in rec.created_by.lower() or any(
                    query_lower in str(rec.data.get(f, "")).lower()
                    for f in (fields or ["description", "notes"])
                ):
                    results.append(rec)
        return results

    def save(self, record: ImmutableIntentRecord) -> None:
        self.store(record)

    def update(self, record: ImmutableIntentRecord) -> None:
        self.store(record)

    def delete(self, intent_id: UUID) -> None:
        with self._lock:
            if intent_id in self._records:
                del self._records[intent_id]

    def lock(self, intent_id: UUID, locked_by: str, reason: str) -> ImmutableIntentRecord:
        record = self.get(intent_id)
        if not record:
            raise ValueError(f"Intent {intent_id} not found")
        return record

    def unlock(self, intent_id: UUID, unlocked_by: str) -> ImmutableIntentRecord:
        record = self.get(intent_id)
        if not record:
            raise ValueError(f"Intent {intent_id} not found")
        return record

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._records)
            by_status: dict[str, int] = {}
            for r in self._records.values():
                by_status[r.status.name] = by_status.get(r.status.name, 0) + 1
            return {"total_records": total, "by_status": by_status}

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


def get_immutable_intent_record_service() -> ImmutableIntentRecordService:
    global _immutable_intent_record_service_instance
    if _immutable_intent_record_service_instance is None:
        _immutable_intent_record_service_instance = ImmutableIntentRecordService()
    return _immutable_intent_record_service_instance


_immutable_intent_record_service_instance: ImmutableIntentRecordService | None = None

__all__ = [
    "ImmutableIntentRecord",
    "ImmutableIntentRecordService",
    "IntentSource",
    "IntentStatus",
    "IntentType",
    "get_immutable_intent_record_service",
]
