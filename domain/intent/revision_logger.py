#!/usr/bin/env python3
"""
Module: revision_logger.py
Layer: 5 - Domain / Intent
Responsibility: Log perubahan revisi intent (sebelum posting).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.audit_trail_writer import (
    IntentAuditAction,
    IntentAuditSeverity,
    get_audit_trail_writer,
)
from domain.intent.immutable_record import IntentStatus

logger = logging.getLogger(__name__)


class RevisionChangeType(Enum):
    CREATE = auto()
    UPDATE = auto()
    DELETE = auto()
    STATUS_CHANGE = auto()


@dataclass
class RevisionChange:
    field_name: str
    change_type: RevisionChangeType
    old_value: Any | None
    new_value: Any | None

    def __post_init__(self) -> None:
        if not self.field_name:
            raise ValueError("field_name cannot be empty")
        if not isinstance(self.change_type, RevisionChangeType):
            raise ValueError("change_type must be RevisionChangeType")

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "change_type": self.change_type.name,
            "old_value": str(self.old_value)[:200] if self.old_value is not None else None,
            "new_value": str(self.new_value)[:200] if self.new_value is not None else None,
        }


@dataclass
class IntentRevision:
    revision_id: UUID
    intent_id: UUID
    revision_number: int
    changed_by: str
    changed_at: datetime
    changes: list[RevisionChange]
    snapshot: dict[str, Any]
    reason: str = ""
    previous_hash: str | None = None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.changed_by, {})

    def _validate(self) -> None:
        if not isinstance(self.revision_id, UUID):
            raise ValueError("revision_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if self.revision_number < 1:
            raise ValueError("revision_number must be >= 1")
        if not self.changed_by:
            raise ValueError("changed_by cannot be empty")
        if not isinstance(self.changed_at, datetime):
            raise ValueError("changed_at must be datetime")
        if not isinstance(self.changes, list):
            raise ValueError("changes must be list")
        if not isinstance(self.snapshot, dict):
            raise ValueError("snapshot must be dict")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def compute_hash(self) -> str:
        content = {
            "revision_id": str(self.revision_id),
            "intent_id": str(self.intent_id),
            "revision_number": self.revision_number,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
            "reason": self.reason[:200],
            "previous_hash": self.previous_hash,
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "revision_id": str(self.revision_id),
            "intent_id": str(self.intent_id),
            "revision_number": self.revision_number,
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
                "revision_id": str(self.revision_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> IntentRevision:
        return self

    def update(self, updated_by: str, **kwargs) -> IntentRevision:
        raise AttributeError("IntentRevision is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> IntentRevision:
        raise AttributeError("IntentRevision cannot be deleted")

    def restore(self, restored_by: str) -> IntentRevision:
        raise AttributeError("IntentRevision cannot be restored")

    def activate(self, activated_by: str) -> IntentRevision:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntentRevision:
        return self

    def lock(self, locked_by: str, reason: str) -> IntentRevision:
        return self

    def unlock(self, unlocked_by: str) -> IntentRevision:
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
            "revision_id": str(self.revision_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "revision_id": str(self.revision_id),
            "intent_id": str(self.intent_id),
            "revision_number": self.revision_number,
            "changed_by": self.changed_by,
            "changed_at": self.changed_at.isoformat(),
            "changes": [c.to_dict() for c in self.changes],
            "reason": self.reason,
            "previous_hash": self.previous_hash[:16] + "..." if self.previous_hash else None,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentRevision:
        changes = [
            RevisionChange(
                field_name=c["field_name"],
                change_type=RevisionChangeType[c["change_type"]],
                old_value=c.get("old_value"),
                new_value=c.get("new_value"),
            )
            for c in data.get("changes", [])
        ]
        return cls(
            revision_id=UUID(data["revision_id"]),
            intent_id=UUID(data["intent_id"]),
            revision_number=data["revision_number"],
            changed_by=data["changed_by"],
            changed_at=datetime.fromisoformat(data["changed_at"]),
            changes=changes,
            snapshot={},  # snapshot tidak disimpan dalam dict
            reason=data.get("reason", ""),
            previous_hash=data.get("previous_hash"),
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
        )

    def clone(self) -> IntentRevision:
        return IntentRevision(
            revision_id=uuid4(),
            intent_id=self.intent_id,
            revision_number=self.revision_number + 1,
            changed_by=self.changed_by,
            changed_at=datetime.now(UTC),
            changes=self.changes.copy(),
            snapshot=self.snapshot.copy(),
            reason=f"Clone of revision {self.revision_number}",
            previous_hash=self.cryptographic_hash,
            version=1,
        )

    # Method renamed to avoid conflict with field 'snapshot'
    def get_snapshot_summary(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "revision_id": str(self.revision_id),
            "intent_id": str(self.intent_id),
            "revision_number": self.revision_number,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntentRevision:
        self._record_audit("TOUCH", touched_by, {})
        return self


class RevisionLogger:
    _instance: RevisionLogger | None = None
    _initialized: bool = False  # Tambahan untuk mypy

    def __new__(cls) -> RevisionLogger:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._audit_writer = get_audit_trail_writer()
        self._revisions: dict[UUID, list[IntentRevision]] = {}
        self._current_revision_numbers: dict[UUID, int] = {}
        self._lock = threading.RLock()
        self._max_revisions_per_intent = 1000

    # ==================== REVISION LOGGING ====================
    def _calculate_changes(
        self, old_data: dict[str, Any], new_data: dict[str, Any]
    ) -> list[RevisionChange]:
        changes = []
        all_keys = set(old_data.keys()) | set(new_data.keys())
        for key in all_keys:
            old_val = old_data.get(key)
            new_val = new_data.get(key)
            if old_val == new_val:
                continue
            if key in old_data and key not in new_data:
                change_type = RevisionChangeType.DELETE
            elif key not in old_data and key in new_data:
                change_type = RevisionChangeType.CREATE
            else:
                change_type = RevisionChangeType.UPDATE
            if key.startswith("_") and change_type == RevisionChangeType.UPDATE:
                continue
            changes.append(RevisionChange(key, change_type, old_val, new_val))
        return changes

    def log_revision(
        self,
        intent_id: UUID,
        changed_by: str,
        old_data: dict[str, Any],
        new_data: dict[str, Any],
        reason: str = "",
    ) -> IntentRevision | None:
        changes = self._calculate_changes(old_data, new_data)
        if not changes:
            return None
        with self._lock:
            next_rev_num = self._current_revision_numbers.get(intent_id, 0) + 1
            self._current_revision_numbers[intent_id] = next_rev_num
            previous_hash = (
                self._revisions.get(intent_id, [])[-1].cryptographic_hash
                if self._revisions.get(intent_id)
                else None
            )
            revision = IntentRevision(
                revision_id=uuid4(),
                intent_id=intent_id,
                revision_number=next_rev_num,
                changed_by=changed_by,
                changed_at=datetime.now(UTC),
                changes=changes,
                snapshot=new_data.copy(),
                reason=reason[:500],
                previous_hash=previous_hash,
            )
            self._revisions.setdefault(intent_id, []).append(revision)
            if len(self._revisions[intent_id]) > self._max_revisions_per_intent:
                self._revisions[intent_id].pop(0)
        self._audit_writer.write(
            intent_id=intent_id,
            action=IntentAuditAction.REVISION_LOGGED,
            changed_by=changed_by,
            old_value=old_data,
            new_value=new_data,
            notes=f"Revision {next_rev_num}: {len(changes)} change(s). Reason: {reason[:100]}",
            severity=IntentAuditSeverity.INFO,
        )
        logger.info(
            "Revision %d logged for intent %s by %s (%d changes)",
            next_rev_num,
            intent_id,
            changed_by,
            len(changes),
        )
        return revision

    def log_status_change(
        self,
        intent_id: UUID,
        changed_by: str,
        old_status: IntentStatus,
        new_status: IntentStatus,
        reason: str = "",
    ) -> IntentRevision | None:
        change = RevisionChange(
            "status", RevisionChangeType.STATUS_CHANGE, old_status.name, new_status.name
        )
        with self._lock:
            next_rev_num = self._current_revision_numbers.get(intent_id, 0) + 1
            self._current_revision_numbers[intent_id] = next_rev_num
            previous_hash = (
                self._revisions.get(intent_id, [])[-1].cryptographic_hash
                if self._revisions.get(intent_id)
                else None
            )
            snapshot = {"status": new_status.name}
            if self._revisions.get(intent_id):
                snapshot = self._revisions[intent_id][-1].snapshot.copy()
                snapshot["status"] = new_status.name
            revision = IntentRevision(
                revision_id=uuid4(),
                intent_id=intent_id,
                revision_number=next_rev_num,
                changed_by=changed_by,
                changed_at=datetime.now(UTC),
                changes=[change],
                snapshot=snapshot,
                reason=reason[:500],
                previous_hash=previous_hash,
            )
            self._revisions.setdefault(intent_id, []).append(revision)
        severity = (
            IntentAuditSeverity.WARNING
            if new_status == IntentStatus.REJECTED
            else IntentAuditSeverity.INFO
        )
        self._audit_writer.write(
            intent_id=intent_id,
            action=IntentAuditAction.REVISION_LOGGED,
            changed_by=changed_by,
            notes=f"Status change: {old_status.name} -> {new_status.name}. Reason: {reason[:100]}",
            severity=severity,
        )
        logger.info(
            "Status change revision %d for intent %s: %s -> %s",
            next_rev_num,
            intent_id,
            old_status.name,
            new_status.name,
        )
        return revision

    # ==================== QUERY METHODS ====================
    def get_revisions(self, intent_id: UUID, limit: int = 50) -> list[IntentRevision]:
        with self._lock:
            revs = self._revisions.get(intent_id, [])
            return revs[-limit:][::-1]

    def get_revision(self, intent_id: UUID, revision_number: int) -> IntentRevision | None:
        with self._lock:
            for rev in self._revisions.get(intent_id, []):
                if rev.revision_number == revision_number:
                    return rev
            return None

    def get_latest_revision(self, intent_id: UUID) -> IntentRevision | None:
        with self._lock:
            revs = self._revisions.get(intent_id, [])
            return revs[-1] if revs else None

    def get_revision_diff(
        self, intent_id: UUID, from_revision: int, to_revision: int
    ) -> list[RevisionChange]:
        from_rev = self.get_revision(intent_id, from_revision)
        to_rev = self.get_revision(intent_id, to_revision)
        if not from_rev or not to_rev:
            return []
        return self._calculate_changes(from_rev.snapshot, to_rev.snapshot)

    def rollback_to_revision(
        self, intent_id: UUID, target_revision: int, rolled_back_by: str, reason: str = ""
    ) -> IntentRevision | None:
        target_rev = self.get_revision(intent_id, target_revision)
        if not target_rev:
            return None
        latest_rev = self.get_latest_revision(intent_id)
        if not latest_rev:
            return None
        return self.log_revision(
            intent_id,
            rolled_back_by,
            latest_rev.snapshot,
            target_rev.snapshot,
            f"Rollback to revision {target_revision}: {reason[:400]}",
        )

    # ==================== REPOSITORY METHODS ====================
    def save_revision(self, revision: IntentRevision) -> None:
        with self._lock:
            self._revisions.setdefault(revision.intent_id, []).append(revision)
            if len(self._revisions[revision.intent_id]) > self._max_revisions_per_intent:
                self._revisions[revision.intent_id].pop(0)

    def get_all_revisions(self) -> list[IntentRevision]:
        with self._lock:
            result = []
            for revs in self._revisions.values():
                result.extend(revs)
            return result

    def delete_revisions_for_intent(self, intent_id: UUID) -> bool:
        with self._lock:
            if intent_id in self._revisions:
                del self._revisions[intent_id]
                del self._current_revision_numbers[intent_id]
                return True
            return False

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_intents = len(self._revisions)
            total_revisions = sum(len(revs) for revs in self._revisions.values())
            avg = total_revisions / total_intents if total_intents else 0
            max_revs = max((len(revs) for revs in self._revisions.values()), default=0)
            return {
                "total_intents_with_revisions": total_intents,
                "total_revisions": total_revisions,
                "average_revisions_per_intent": avg,
                "max_revisions_per_intent": max_revs,
            }

    def reset(self) -> None:
        with self._lock:
            self._revisions.clear()
            self._current_revision_numbers.clear()


def get_revision_logger() -> RevisionLogger:
    global _revision_logger_instance
    if _revision_logger_instance is None:
        _revision_logger_instance = RevisionLogger()
    return _revision_logger_instance


_revision_logger_instance: RevisionLogger | None = None

__all__ = [
    "IntentRevision",
    "RevisionChange",
    "RevisionChangeType",
    "RevisionLogger",
    "get_revision_logger",
]
