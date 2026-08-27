#!/usr/bin/env python3
# ruff: noqa: UP006
"""
Module: capture_service.py
Layer: 5 - Reality, Intent, Causality / Intent
Responsibility: Menangkap maksud pengguna sebelum menjadi event (draft).
"""

from __future__ import annotations

import importlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, List  # noqa: UP035
from uuid import UUID, uuid4

from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    IntentStatus,
    get_immutable_intent_record_service,
)
from domain.intent.immutable_record import (
    IntentSource as ImmutableIntentSource,
)
from domain.intent.intent_type import IntentType

logger = logging.getLogger(__name__)


# ============================================================================
# Lazy helper untuk menghindari AST drift (domain -> kernel)
# ============================================================================

def _get_current_user() -> str | None:
    """Lazy import kernel.context_holder.get_current_user."""
    try:
        mod = importlib.import_module("kernel.context_holder")
        get_current_user = mod.get_current_user
        return get_current_user()
    except Exception:
        return None


# ============================================================================
# CapturedIntent
# ============================================================================

@dataclass
class CapturedIntent:
    intent_id: UUID
    intent_type: IntentType
    data: dict[str, Any]
    captured_by: str
    captured_at: datetime
    status: IntentStatus
    parent_intent_id: UUID | None = None
    notes: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.captured_by, {})

    def _validate(self) -> None:
        if not self.captured_by or not isinstance(self.captured_by, str):
            raise ValueError("captured_by must be a non-empty string")
        if not isinstance(self.data, dict):
            raise ValueError("data must be a dictionary")
        if self.parent_intent_id is not None and not isinstance(self.parent_intent_id, UUID):
            raise ValueError("parent_intent_id must be UUID or None")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

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

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CapturedIntent:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> CapturedIntent:
        if self.status != IntentStatus.DRAFT:
            raise ValueError(f"Cannot update intent in status {self.status.name}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in (
                "intent_id",
                "captured_at",
                "captured_by",
                "version",
            ):
                data[key] = value
        new_intent = CapturedIntent.from_dict(data)
        new_intent.version = self.version + 1
        new_intent._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_intent

    def delete(self, deleted_by: str, reason: str | None = None) -> CapturedIntent:
        if self.status not in (IntentStatus.DRAFT, IntentStatus.SUBMITTED):
            raise ValueError(f"Cannot delete intent in status {self.status.name}")
        new_intent = self._copy()
        new_intent.status = IntentStatus.CANCELLED
        new_intent.deleted_at = datetime.now(UTC)
        new_intent.deleted_by = deleted_by
        new_intent.version = self.version + 1
        new_intent._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_intent

    def restore(self, restored_by: str) -> CapturedIntent:
        if self.status != IntentStatus.CANCELLED:
            raise ValueError("Cannot restore non-cancelled intent")
        new_intent = self._copy()
        new_intent.status = IntentStatus.DRAFT
        new_intent.deleted_at = None
        new_intent.deleted_by = None
        new_intent.version = self.version + 1
        new_intent._record_audit("RESTORE", restored_by, {})
        return new_intent

    def activate(self, activated_by: str) -> CapturedIntent:
        if self.status != IntentStatus.DRAFT:
            raise ValueError(f"Cannot activate intent in status {self.status.name}")
        new_intent = self._copy()
        new_intent.status = IntentStatus.SUBMITTED
        new_intent.version = self.version + 1
        new_intent._record_audit("ACTIVATE", activated_by, {})
        return new_intent

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CapturedIntent:
        if self.status != IntentStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate intent in status {self.status.name}")
        new_intent = self._copy()
        new_intent.status = IntentStatus.DRAFT
        new_intent.version = self.version + 1
        new_intent._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_intent

    def lock(self, locked_by: str, reason: str) -> CapturedIntent:
        new_intent = self._copy()
        new_intent.data = {
            **self.data,
            "_locked": True,
            "_lock_reason": reason,
            "_locked_by": locked_by,
        }
        new_intent.version = self.version + 1
        new_intent._record_audit("LOCK", locked_by, {"reason": reason})
        return new_intent

    def unlock(self, unlocked_by: str) -> CapturedIntent:
        new_intent = self._copy()
        new_intent.data.pop("_locked", None)
        new_intent.data.pop("_lock_reason", None)
        new_intent.data.pop("_locked_by", None)
        new_intent.version = self.version + 1
        new_intent._record_audit("UNLOCK", unlocked_by, {})
        return new_intent

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if self.status == IntentStatus.DRAFT and (datetime.now(UTC) - self.captured_at).days > 7:
            warnings.append("Intent has been in DRAFT for over 7 days")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "intent_id": str(self.intent_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_id": str(self.intent_id),
            "intent_type": self.intent_type.name,
            "data": self.data,
            "captured_by": self.captured_by,
            "captured_at": self.captured_at.isoformat(),
            "status": self.status.name,
            "parent_intent_id": str(self.parent_intent_id) if self.parent_intent_id else None,
            "notes": self.notes,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapturedIntent:
        return cls(
            intent_id=UUID(data["intent_id"]),
            intent_type=IntentType[data["intent_type"]],
            data=data["data"],
            captured_by=data["captured_by"],
            captured_at=datetime.fromisoformat(data["captured_at"]),
            status=IntentStatus[data["status"]],
            parent_intent_id=UUID(data["parent_intent_id"])
            if data.get("parent_intent_id")
            else None,
            notes=data.get("notes", ""),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> CapturedIntent:
        new_id = uuid4()
        return CapturedIntent(
            intent_id=new_id,
            intent_type=self.intent_type,
            data=self.data.copy(),
            captured_by=self.captured_by,
            captured_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            parent_intent_id=self.intent_id,
            notes=self.notes,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "intent_id": str(self.intent_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CapturedIntent:
        new_intent = self._copy()
        new_intent.version = self.version + 1
        new_intent._record_audit("TOUCH", touched_by, {})
        return new_intent

    def _copy(self) -> CapturedIntent:
        return CapturedIntent(
            intent_id=self.intent_id,
            intent_type=self.intent_type,
            data=self.data.copy(),
            captured_by=self.captured_by,
            captured_at=self.captured_at,
            status=self.status,
            parent_intent_id=self.parent_intent_id,
            notes=self.notes,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )

    def to_immutable(
        self,
        signed_by: str,
        signature: str,
        source: ImmutableIntentSource | None = None,
        source_id: str | None = None,
    ) -> ImmutableIntentRecord:
        return ImmutableIntentRecord(
            intent_id=self.intent_id,
            intent_type=self.intent_type,
            data=self.data.copy(),
            created_by=self.captured_by,
            created_at=self.captured_at,
            status=self.status,
            signed_by=signed_by,
            signature=signature,
            parent_intent_id=self.parent_intent_id,
            source=source or ImmutableIntentSource.USER,
            source_id=source_id,
        )


# ============================================================================
# IntentCaptureService
# ============================================================================

class IntentCaptureService:
    _instance: IntentCaptureService | None = None
    _initialized: bool = False

    def __new__(cls) -> IntentCaptureService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._record_service = get_immutable_intent_record_service()
        self._captured_intents: dict[UUID, CapturedIntent] = {}
        self._lock = threading.RLock()

    def capture(
        self,
        intent_type: IntentType,
        data: dict[str, Any],
        captured_by: str | None = None,
        parent_intent_id: UUID | None = None,
        notes: str = "",
    ) -> CapturedIntent:
        if captured_by is None:
            captured_by = _get_current_user() or "unknown"
        intent = CapturedIntent(
            intent_id=uuid4(),
            intent_type=intent_type,
            data=data,
            captured_by=captured_by,
            captured_at=datetime.now(UTC),
            status=IntentStatus.DRAFT,
            parent_intent_id=parent_intent_id,
            notes=notes[:500],
        )
        with self._lock:
            self._captured_intents[intent.intent_id] = intent
        logger.info(f"Intent captured: {intent_type.name} (id={intent.intent_id})")
        return intent

    def get_intent(self, intent_id: UUID) -> CapturedIntent | None:
        with self._lock:
            return self._captured_intents.get(intent_id)

    def update_intent(
        self,
        intent_id: UUID,
        data: dict[str, Any],
        updated_by: str | None = None,
        notes: str | None = None,
    ) -> CapturedIntent | None:
        with self._lock:
            intent = self._captured_intents.get(intent_id)
            if not intent or intent.status != IntentStatus.DRAFT:
                return None
            updated_by = updated_by or _get_current_user() or "unknown"
            new_notes = notes if notes is not None else intent.notes
            updated = intent.update(updated_by, data=data, notes=new_notes)
            self._captured_intents[intent_id] = updated
            return updated

    def submit_for_approval(
        self, intent_id: UUID, submitted_by: str | None = None
    ) -> CapturedIntent | None:
        with self._lock:
            intent = self._captured_intents.get(intent_id)
            if not intent or intent.status != IntentStatus.DRAFT:
                return None
            submitted_by = submitted_by or _get_current_user() or "unknown"
            submitted_intent = intent.activate(submitted_by)
            self._captured_intents[intent_id] = submitted_intent
            return submitted_intent

    def cancel_intent(
        self, intent_id: UUID, cancelled_by: str | None = None, reason: str = ""
    ) -> bool:
        with self._lock:
            intent = self._captured_intents.get(intent_id)
            if not intent or intent.status not in (IntentStatus.DRAFT, IntentStatus.SUBMITTED):
                return False
            cancelled_by = cancelled_by or _get_current_user() or "unknown"
            cancelled = intent.delete(cancelled_by, reason)
            self._captured_intents[intent_id] = cancelled
            return True

    def get_intents_by_user(
        self, user_id: str, status_filter: IntentStatus | None = None, limit: int = 50
    ) -> List[CapturedIntent]:
        with self._lock:
            result = [i for i in self._captured_intents.values() if i.captured_by == user_id]
            if status_filter:
                result = [i for i in result if i.status == status_filter]
            result.sort(key=lambda i: i.captured_at, reverse=True)
            return result[:limit]

    def get_intents_by_type(
        self, intent_type: IntentType, status_filter: IntentStatus | None = None, limit: int = 50
    ) -> List[CapturedIntent]:
        with self._lock:
            result = [i for i in self._captured_intents.values() if i.intent_type == intent_type]
            if status_filter:
                result = [i for i in result if i.status == status_filter]
            result.sort(key=lambda i: i.captured_at, reverse=True)
            return result[:limit]

    def get_pending_intents(self, limit: int = 50) -> List[CapturedIntent]:
        return self.get_intents_by_type(
            IntentType.APPROVE_TRANSACTION, status_filter=IntentStatus.DRAFT, limit=limit
        )

    # ==================== REPOSITORY METHODS ====================
    def save(self, intent: CapturedIntent) -> None:
        with self._lock:
            self._captured_intents[intent.intent_id] = intent

    def update(self, intent: CapturedIntent) -> None:
        self.save(intent)

    def delete(self, intent_id: UUID) -> None:
        with self._lock:
            if intent_id in self._captured_intents:
                del self._captured_intents[intent_id]

    def exists(self, intent_id: UUID) -> bool:
        return self.get_intent(intent_id) is not None

    def get_all(self) -> List[CapturedIntent]:
        with self._lock:
            return list(self._captured_intents.values())

    def search(self, query: str, fields: List[str] | None = None) -> List[CapturedIntent]:
        query_lower = query.lower()
        results: List[CapturedIntent] = []
        with self._lock:
            for intent in self._captured_intents.values():
                if query_lower in intent.captured_by.lower() or any(
                    query_lower in str(intent.data.get(f, "")).lower()
                    for f in (fields or ["description", "notes"])
                ):
                    results.append(intent)
        return results

    def count(self) -> int:
        with self._lock:
            return len(self._captured_intents)

    def list(self, limit: int = 100, offset: int = 0) -> List[CapturedIntent]:
        intents = self.get_all()
        intents.sort(key=lambda i: i.captured_at, reverse=True)
        return intents[offset : offset + limit]

    def paginate(self, page: int = 1, per_page: int = 20) -> tuple[List[CapturedIntent], int]:
        intents = self.get_all()
        total = len(intents)
        intents.sort(key=lambda i: i.captured_at, reverse=True)
        start = (page - 1) * per_page
        end = start + per_page
        return intents[start:end], total

    def lock(self, intent_id: UUID, locked_by: str, reason: str) -> CapturedIntent:
        intent = self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent {intent_id} not found")
        locked = intent.lock(locked_by, reason)
        self.save(locked)
        return locked

    def unlock(self, intent_id: UUID, unlocked_by: str) -> CapturedIntent:
        intent = self.get_intent(intent_id)
        if not intent:
            raise ValueError(f"Intent {intent_id} not found")
        unlocked = intent.unlock(unlocked_by)
        self.save(unlocked)
        return unlocked

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._captured_intents)
            by_status: dict[str, int] = {}
            for i in self._captured_intents.values():
                by_status[i.status.name] = by_status.get(i.status.name, 0) + 1
            return {"total_intents": total, "by_status": by_status}

    def reset(self) -> None:
        with self._lock:
            self._captured_intents.clear()


def get_intent_capture_service() -> IntentCaptureService:
    global _intent_capture_service_instance
    if _intent_capture_service_instance is None:
        _intent_capture_service_instance = IntentCaptureService()
    return _intent_capture_service_instance


_intent_capture_service_instance: IntentCaptureService | None = None

__all__ = [
    "CapturedIntent",
    "IntentCaptureService",
    "IntentType",
    "get_intent_capture_service",
]
