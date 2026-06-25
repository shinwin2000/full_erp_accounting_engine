#!/usr/bin/env python3
"""
Module: void_processor.py
Layer: 5 - Domain / Intent
Responsibility: Memproses pembatalan intent (void) tanpa menghapus data.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.audit_trail_writer import (
    IntentAuditAction,
    IntentAuditSeverity,
    get_audit_trail_writer,
)
from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    IntentStatus,
    get_immutable_intent_record_service,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy helper untuk menghindari AST drift (domain -> kernel)
# ============================================================================

def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_current_user = getattr(mod, "get_current_user")
        return get_current_user()
    except Exception:
        return None


# ============================================================================
# Enums & Classes
# ============================================================================

class VoidReason(Enum):
    USER_CANCELLED = auto()
    DUPLICATE = auto()
    ERROR = auto()
    EXPIRED = auto()
    SUPERSEDED = auto()
    COMPLIANCE = auto()
    FRAUD_SUSPECTED = auto()


class VoidScope(Enum):
    SINGLE = auto()
    BATCH = auto()
    CHAIN = auto()


@dataclass
class VoidRecord:
    void_id: UUID
    intent_id: UUID
    voided_by: str
    voided_at: datetime
    reason: VoidReason
    reason_description: str
    scope: VoidScope
    related_intents: list[UUID] = field(default_factory=list)
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.voided_by, {})

    def _validate(self) -> None:
        if not isinstance(self.void_id, UUID):
            raise ValueError("void_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not self.voided_by:
            raise ValueError("voided_by cannot be empty")
        if not isinstance(self.voided_at, datetime):
            raise ValueError("voided_at must be datetime")
        if not isinstance(self.reason, VoidReason):
            raise ValueError("reason must be VoidReason")
        if not self.reason_description:
            raise ValueError("reason_description cannot be empty")
        if not isinstance(self.scope, VoidScope):
            raise ValueError("scope must be VoidScope")
        if not isinstance(self.related_intents, list):
            raise ValueError("related_intents must be list")
        for rid in self.related_intents:
            if not isinstance(rid, UUID):
                raise ValueError("related_intents must contain UUIDs")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def compute_hash(self) -> str:
        content = {
            "void_id": str(self.void_id),
            "intent_id": str(self.intent_id),
            "voided_by": self.voided_by,
            "voided_at": self.voided_at.isoformat(),
            "reason": self.reason.name,
            "scope": self.scope.name,
            "related_intents": [str(i) for i in self.related_intents],
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "void_id": str(self.void_id),
            "intent_id": str(self.intent_id),
            "reason": self.reason.name,
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
                "void_id": str(self.void_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> VoidRecord:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> VoidRecord:
        raise AttributeError("VoidRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> VoidRecord:
        raise AttributeError("VoidRecord cannot be deleted")

    def restore(self, restored_by: str) -> VoidRecord:
        raise AttributeError("VoidRecord cannot be restored")

    def activate(self, activated_by: str) -> VoidRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> VoidRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> VoidRecord:
        return self

    def unlock(self, unlocked_by: str) -> VoidRecord:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.cryptographic_hash != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "void_id": str(self.void_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "void_id": str(self.void_id),
            "intent_id": str(self.intent_id),
            "voided_by": self.voided_by,
            "voided_at": self.voided_at.isoformat(),
            "reason": self.reason.name,
            "reason_description": self.reason_description,
            "scope": self.scope.name,
            "related_intents": [str(i) for i in self.related_intents],
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoidRecord:
        return cls(
            void_id=UUID(data["void_id"]),
            intent_id=UUID(data["intent_id"]),
            voided_by=data["voided_by"],
            voided_at=datetime.fromisoformat(data["voided_at"]),
            reason=VoidReason[data["reason"]],
            reason_description=data["reason_description"],
            scope=VoidScope[data["scope"]],
            related_intents=[UUID(i) for i in data.get("related_intents", [])],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
        )

    def clone(self) -> VoidRecord:
        new_id = uuid4()
        return VoidRecord(
            void_id=new_id,
            intent_id=self.intent_id,
            voided_by=self.voided_by,
            voided_at=datetime.now(UTC),
            reason=self.reason,
            reason_description=self.reason_description,
            scope=self.scope,
            related_intents=self.related_intents.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "void_id": str(self.void_id),
            "intent_id": str(self.intent_id),
            "reason": self.reason.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> VoidRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self


# ============================================================================
# VoidProcessor
# ============================================================================

class VoidProcessor:
    _instance: VoidProcessor | None = None

    def __new__(cls) -> VoidProcessor:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._record_service = get_immutable_intent_record_service()
        self._audit_writer = get_audit_trail_writer()
        self._void_records: dict[UUID, VoidRecord] = {}
        self._lock = threading.RLock()

    # ==================== VOID METHODS ====================
    def can_void(self, intent: ImmutableIntentRecord) -> tuple[bool, str]:
        if intent.status in (IntentStatus.EXECUTED, IntentStatus.CANCELLED):
            return False, f"Cannot void intent in {intent.status.name} status"
        if intent.status == IntentStatus.APPROVED:
            return True, "Approved intent requires justification"
        return True, ""

    def void_intent(
        self,
        intent_id: UUID,
        reason: VoidReason,
        reason_description: str,
        voided_by: str | None = None,
        scope: VoidScope = VoidScope.SINGLE,
        related_intents: list[UUID] | None = None,
    ) -> tuple[bool, str]:
        intent = self._record_service.get(intent_id)
        if not intent:
            return False, f"Intent {intent_id} not found"
        can_void, msg = self.can_void(intent)
        if not can_void:
            return False, msg
        voided_by = voided_by or _get_current_user() or "unknown"
        void_record = VoidRecord(
            void_id=uuid4(),
            intent_id=intent_id,
            voided_by=voided_by,
            voided_at=datetime.now(UTC),
            reason=reason,
            reason_description=reason_description[:500],
            scope=scope,
            related_intents=related_intents or [],
        )
        updated = ImmutableIntentRecord(
            intent_id=intent.intent_id,
            intent_type=intent.intent_type,
            data=intent.data,
            created_by=intent.created_by,
            created_at=intent.created_at,
            status=IntentStatus.CANCELLED,
            signed_by=intent.signed_by,
            signature=intent.signature,
            parent_intent_id=intent.parent_intent_id,
            source=intent.source,
            source_id=intent.source_id,
            version=intent.version,
            previous_hash=intent.previous_hash,
            cryptographic_hash=intent.cryptographic_hash,
        )
        with self._lock:
            self._record_service.store(updated)
            self._void_records[intent_id] = void_record
        severity = (
            IntentAuditSeverity.WARNING
            if reason == VoidReason.FRAUD_SUSPECTED
            else IntentAuditSeverity.INFO
        )
        self._audit_writer.write(
            intent_id=intent_id,
            action=IntentAuditAction.CANCELLED,
            changed_by=voided_by,
            notes=f"Voided: {reason.name} - {reason_description}",
            severity=severity,
        )
        if scope == VoidScope.CHAIN and related_intents:
            for child_id in related_intents:
                self.void_intent(
                    child_id,
                    reason,
                    f"Voided as part of chain from {intent_id}: {reason_description}",
                    voided_by,
                    VoidScope.SINGLE,
                )
        logger.info(f"Intent {intent_id} voided by {voided_by}: {reason.name}")
        return True, f"Intent {intent_id} successfully voided"

    def void_batch(
        self,
        intent_ids: list[UUID],
        reason: VoidReason,
        reason_description: str,
        voided_by: str | None = None,
    ) -> dict[UUID, tuple[bool, str]]:
        voided_by = voided_by or _get_current_user() or "unknown"
        results = {}
        for iid in intent_ids:
            success, msg = self.void_intent(
                iid, reason, reason_description, voided_by, VoidScope.BATCH, intent_ids
            )
            results[iid] = (success, msg)
        logger.info(
            f"Batch void completed: {len([r for r in results.values() if r[0]])} successful, {len([r for r in results.values() if not r[0]])} failed"
        )
        return results

    def void_chain(
        self,
        root_intent_id: UUID,
        reason: VoidReason,
        reason_description: str,
        voided_by: str | None = None,
    ) -> dict[UUID, tuple[bool, str]]:
        all_records = self._record_service.get_all()
        child_intents = [i for i in all_records if i.parent_intent_id == root_intent_id]
        all_ids = [root_intent_id] + [i.intent_id for i in child_intents]
        return self.void_batch(all_ids, reason, reason_description, voided_by)

    # ==================== QUERY METHODS ====================
    def get_void_record(self, intent_id: UUID) -> VoidRecord | None:
        with self._lock:
            return self._void_records.get(intent_id)

    def is_voided(self, intent_id: UUID) -> bool:
        with self._lock:
            return intent_id in self._void_records

    def get_voided_intents(
        self, reason: VoidReason | None = None, voided_by: str | None = None, limit: int = 100
    ) -> list[VoidRecord]:
        with self._lock:
            records = list(self._void_records.values())
            if reason:
                records = [r for r in records if r.reason == reason]
            if voided_by:
                records = [r for r in records if r.voided_by == voided_by]
            records.sort(key=lambda r: r.voided_at, reverse=True)
            return records[:limit]

    # ==================== REPOSITORY METHODS ====================
    def save_void_record(self, record: VoidRecord) -> None:
        with self._lock:
            self._void_records[record.intent_id] = record

    def get_all_void_records(self) -> list[VoidRecord]:
        with self._lock:
            return list(self._void_records.values())

    def delete_void_record(self, intent_id: UUID) -> bool:
        with self._lock:
            if intent_id in self._void_records:
                del self._void_records[intent_id]
                return True
            return False

    def count_void_records(self) -> int:
        with self._lock:
            return len(self._void_records)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._void_records)
            if total == 0:
                return {"total_voided_intents": 0}
            by_reason = {}
            by_user = {}
            for r in self._void_records.values():
                by_reason[r.reason.name] = by_reason.get(r.reason.name, 0) + 1
                by_user[r.voided_by] = by_user.get(r.voided_by, 0) + 1
            latest = (
                max(self._void_records.values(), key=lambda r: r.voided_at)
                if self._void_records
                else None
            )
            return {
                "total_voided_intents": total,
                "by_reason": by_reason,
                "by_user": by_user,
                "latest_void": latest.voided_at.isoformat() if latest else None,
            }

    def reset(self) -> None:
        with self._lock:
            self._void_records = {}


def get_void_processor() -> VoidProcessor:
    global _void_processor_instance
    if _void_processor_instance is None:
        _void_processor_instance = VoidProcessor()
    return _void_processor_instance


_void_processor_instance: VoidProcessor | None = None

__all__ = [
    "VoidProcessor",
    "VoidReason",
    "VoidRecord",
    "VoidScope",
    "get_void_processor",
]