#!/usr/bin/env python3
"""
Module: approval_workflow.py
Layer: 5 - Domain / Intent
Responsibility: Alur persetujuan intent sebelum dieksekusi.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.audit_trail_writer import (
    get_audit_trail_writer,
)
from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    IntentStatus,
    get_immutable_intent_record_service,
)

logger = logging.getLogger(__name__)


class ApprovalLevel(Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4
    LEVEL_5 = 5

    @classmethod
    def from_int(cls, value: int) -> ApprovalLevel:
        for level in cls:
            if level.value == value:
                return level
        raise ValueError(f"Invalid ApprovalLevel value: {value}")


class ApprovalAction(Enum):
    APPROVE = auto()
    REJECT = auto()
    REQUEST_CHANGES = auto()
    ESCALATE = auto()
    DELEGATE = auto()


class ApprovalStatus(Enum):
    PENDING = auto()
    APPROVED = auto()
    REJECTED = auto()
    CHANGES_REQUESTED = auto()
    ESCALATED = auto()
    DELEGATED = auto()
    EXPIRED = auto()


@dataclass
class ApprovalRule:
    min_amount: Decimal
    max_amount: Decimal
    required_level: ApprovalLevel
    required_approvers: int = 1
    approver_roles: list[str] = field(default_factory=list)
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.min_amount < 0:
            raise ValueError("min_amount cannot be negative")
        if self.max_amount < self.min_amount and self.max_amount != Decimal("inf"):
            raise ValueError("max_amount must be >= min_amount")
        if self.required_approvers < 1:
            raise ValueError("required_approvers must be at least 1")
        if not isinstance(self.required_level, ApprovalLevel):
            raise ValueError("required_level must be ApprovalLevel")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "min_amount": float(self.min_amount),
            "max_amount": float(self.max_amount) if self.max_amount != Decimal("inf") else "inf",
            "required_level": self.required_level.name,
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
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ApprovalRule:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> ApprovalRule:
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("version"):
                data[key] = value
        new_rule = ApprovalRule.from_dict(data)
        new_rule.version = self.version + 1
        new_rule._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_rule

    def delete(self, deleted_by: str, reason: str | None = None) -> ApprovalRule:
        new_rule = self._copy()
        # Soft delete tidak diperlukan, cukup return self dengan catatan
        new_rule._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_rule

    def restore(self, restored_by: str) -> ApprovalRule:
        self._record_audit("RESTORE", restored_by, {})
        return self

    def activate(self, activated_by: str) -> ApprovalRule:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ApprovalRule:
        return self

    def lock(self, locked_by: str, reason: str) -> ApprovalRule:
        return self

    def unlock(self, unlocked_by: str) -> ApprovalRule:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_amount": float(self.min_amount),
            "max_amount": float(self.max_amount)
            if self.max_amount != Decimal("inf")
            else float("inf"),
            "required_level": self.required_level.name,
            "required_approvers": self.required_approvers,
            "approver_roles": self.approver_roles,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRule:
        min_amt = Decimal(str(data["min_amount"]))
        max_amt = (
            Decimal(str(data["max_amount"]))
            if data["max_amount"] != float("inf")
            else Decimal("inf")
        )
        return cls(
            min_amount=min_amt,
            max_amount=max_amt,
            required_level=ApprovalLevel[data["required_level"]],
            required_approvers=data["required_approvers"],
            approver_roles=data.get("approver_roles", []),
            version=data.get("version", 1),
        )

    def clone(self) -> ApprovalRule:
        return ApprovalRule(
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            required_level=self.required_level,
            required_approvers=self.required_approvers,
            approver_roles=self.approver_roles.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "min_amount": float(self.min_amount),
            "max_amount": float(self.max_amount) if self.max_amount != Decimal("inf") else "inf",
            "required_level": self.required_level.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ApprovalRule:
        new_rule = self._copy()
        new_rule.version = self.version + 1
        new_rule._record_audit("TOUCH", touched_by, {})
        return new_rule

    def _copy(self) -> ApprovalRule:
        return ApprovalRule(
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            required_level=self.required_level,
            required_approvers=self.required_approvers,
            approver_roles=self.approver_roles.copy(),
            version=self.version,
        )

    def contains_amount(self, amount: Decimal) -> bool:
        return self.min_amount <= amount <= self.max_amount


@dataclass
class ApprovalRecord:
    approval_id: UUID
    intent_id: UUID
    approver_id: str
    action: ApprovalAction
    status: ApprovalStatus
    level: ApprovalLevel
    notes: str
    approved_at: datetime
    escalation_reason: str | None = None
    delegated_to: str | None = None
    version: int = 1
    cryptographic_hash: str = ""

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.approver_id, {})

    def _validate(self) -> None:
        if not isinstance(self.approval_id, UUID):
            raise ValueError("approval_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not self.approver_id:
            raise ValueError("approver_id cannot be empty")
        if not isinstance(self.action, ApprovalAction):
            raise ValueError("action must be ApprovalAction")
        if not isinstance(self.status, ApprovalStatus):
            raise ValueError("status must be ApprovalStatus")
        if not isinstance(self.level, ApprovalLevel):
            raise ValueError("level must be ApprovalLevel")
        if not isinstance(self.approved_at, datetime):
            raise ValueError("approved_at must be datetime")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "approval_id": str(self.approval_id),
            "action": self.action.name,
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
                "approval_id": str(self.approval_id),
                "details": details,
            }
        )

    def compute_hash(self) -> str:
        content = {
            "approval_id": str(self.approval_id),
            "intent_id": str(self.intent_id),
            "approver_id": self.approver_id,
            "action": self.action.name,
            "status": self.status.name,
            "level": self.level.name,
            "approved_at": self.approved_at.isoformat(),
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ApprovalRecord:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> ApprovalRecord:
        # ApprovalRecord immutable
        raise AttributeError("ApprovalRecord cannot be updated")

    def delete(self, deleted_by: str, reason: str | None = None) -> ApprovalRecord:
        raise AttributeError("ApprovalRecord cannot be deleted")

    def restore(self, restored_by: str) -> ApprovalRecord:
        raise AttributeError("ApprovalRecord cannot be restored")

    def activate(self, activated_by: str) -> ApprovalRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ApprovalRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> ApprovalRecord:
        return self

    def unlock(self, unlocked_by: str) -> ApprovalRecord:
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
            "approval_id": str(self.approval_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": str(self.approval_id),
            "intent_id": str(self.intent_id),
            "approver_id": self.approver_id,
            "action": self.action.name,
            "status": self.status.name,
            "level": self.level.name,
            "notes": self.notes,
            "approved_at": self.approved_at.isoformat(),
            "escalation_reason": self.escalation_reason,
            "delegated_to": self.delegated_to,
            "version": self.version,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ApprovalRecord:
        return cls(
            approval_id=UUID(data["approval_id"]),
            intent_id=UUID(data["intent_id"]),
            approver_id=data["approver_id"],
            action=ApprovalAction[data["action"]],
            status=ApprovalStatus[data["status"]],
            level=ApprovalLevel[data["level"]],
            notes=data["notes"],
            approved_at=datetime.fromisoformat(data["approved_at"]),
            escalation_reason=data.get("escalation_reason"),
            delegated_to=data.get("delegated_to"),
            version=data.get("version", 1),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> ApprovalRecord:
        new_id = uuid4()
        return ApprovalRecord(
            approval_id=new_id,
            intent_id=self.intent_id,
            approver_id=self.approver_id,
            action=self.action,
            status=self.status,
            level=self.level,
            notes=self.notes,
            approved_at=self.approved_at,
            escalation_reason=self.escalation_reason,
            delegated_to=self.delegated_to,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "approval_id": str(self.approval_id),
            "action": self.action.name,
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ApprovalRecord:
        # Immutable, just return self
        self._record_audit("TOUCH", touched_by, {})
        return self


DEFAULT_APPROVAL_RULES = [
    ApprovalRule(
        Decimal("0"), Decimal("10000000"), ApprovalLevel.LEVEL_1, 1, ["supervisor", "manager"]
    ),
    ApprovalRule(
        Decimal("10000000"),
        Decimal("100000000"),
        ApprovalLevel.LEVEL_2,
        1,
        ["manager", "finance_manager"],
    ),
    ApprovalRule(
        Decimal("100000000"),
        Decimal("500000000"),
        ApprovalLevel.LEVEL_3,
        1,
        ["director", "finance_director"],
    ),
    ApprovalRule(
        Decimal("500000000"), Decimal("1000000000"), ApprovalLevel.LEVEL_4, 2, ["vp", "cfo"]
    ),
    ApprovalRule(Decimal("1000000000"), Decimal("inf"), ApprovalLevel.LEVEL_5, 2, ["cfo", "ceo"]),
]


class ApprovalWorkflow:
    _instance: ApprovalWorkflow | None = None

    def __new__(cls) -> ApprovalWorkflow:
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
        self._rules: list[ApprovalRule] = DEFAULT_APPROVAL_RULES.copy()
        self._approvals: dict[UUID, list[ApprovalRecord]] = {}
        self._lock = threading.RLock()

    # ==================== RULE MANAGEMENT ====================
    def get_approval_requirement(self, amount: Decimal) -> ApprovalRule:
        for rule in sorted(self._rules, key=lambda r: r.min_amount):
            if rule.contains_amount(amount):
                return rule
        return self._rules[-1]

    def add_approval_rule(self, rule: ApprovalRule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._rules.sort(key=lambda r: r.min_amount)

    def get_all_rules(self) -> list[ApprovalRule]:
        return self._rules.copy()

    # ==================== APPROVAL METHODS ====================
    def submit_for_approval(self, intent_id: UUID, submitted_by: str) -> bool:
        intent = self._record_service.get(intent_id)
        if not intent or intent.status != IntentStatus.DRAFT:
            return False
        amount = Decimal(str(intent.data.get("amount", 0)))
        rule = self.get_approval_requirement(amount)
        updated = ImmutableIntentRecord(
            intent_id=intent.intent_id,
            intent_type=intent.intent_type,
            data=intent.data,
            created_by=intent.created_by,
            created_at=intent.created_at,
            status=IntentStatus.SUBMITTED,
            signed_by=intent.signed_by,
            signature=intent.signature,
            parent_intent_id=intent.parent_intent_id,
            source=intent.source,
            source_id=intent.source_id,
            version=intent.version,
            previous_hash=intent.previous_hash,
            cryptographic_hash=intent.cryptographic_hash,
        )
        self._record_service.store(updated)
        self._audit_writer.write_submitted(intent_id, submitted_by)
        logger.info("Intent %s submitted for approval", intent_id)
        return True

    def approve(
        self, intent_id: UUID, approver_id: str, level: ApprovalLevel, notes: str = ""
    ) -> tuple[bool, str]:
        intent = self._record_service.get(intent_id)
        if not intent or intent.status != IntentStatus.SUBMITTED:
            return False, "Intent not found or not in SUBMITTED state"
        amount = Decimal(str(intent.data.get("amount", 0)))
        rule = self.get_approval_requirement(amount)
        if level.value < rule.required_level.value:
            return False, f"Required level {rule.required_level.name}, got {level.name}"

        with self._lock:
            approval = ApprovalRecord(
                approval_id=uuid4(),
                intent_id=intent_id,
                approver_id=approver_id,
                action=ApprovalAction.APPROVE,
                status=ApprovalStatus.APPROVED,
                level=level,
                notes=notes[:500],
                approved_at=datetime.now(UTC),
            )
            self._approvals.setdefault(intent_id, []).append(approval)

            approvals_at_level = [
                a
                for a in self._approvals[intent_id]
                if a.level == rule.required_level and a.status == ApprovalStatus.APPROVED
            ]
            if len(approvals_at_level) >= rule.required_approvers:
                updated = ImmutableIntentRecord(
                    intent_id=intent.intent_id,
                    intent_type=intent.intent_type,
                    data=intent.data,
                    created_by=intent.created_by,
                    created_at=intent.created_at,
                    status=IntentStatus.APPROVED,
                    signed_by=approver_id,
                    signature=intent.signature,
                    parent_intent_id=intent.parent_intent_id,
                    source=intent.source,
                    source_id=intent.source_id,
                    version=intent.version,
                    previous_hash=intent.previous_hash,
                    cryptographic_hash=intent.cryptographic_hash,
                )
                self._record_service.store(updated)
                self._audit_writer.write_approved(intent_id, approver_id, notes)
                return True, "Intent fully approved"
        return True, f"Approved at level {level.name}, waiting for more approvals"

    def reject(self, intent_id: UUID, approver_id: str, reason: str) -> bool:
        intent = self._record_service.get(intent_id)
        if not intent or intent.status not in (IntentStatus.SUBMITTED, IntentStatus.DRAFT):
            return False
        with self._lock:
            approval = ApprovalRecord(
                approval_id=uuid4(),
                intent_id=intent_id,
                approver_id=approver_id,
                action=ApprovalAction.REJECT,
                status=ApprovalStatus.REJECTED,
                level=ApprovalLevel.LEVEL_1,
                notes=reason[:500],
                approved_at=datetime.now(UTC),
            )
            self._approvals.setdefault(intent_id, []).append(approval)
            updated = ImmutableIntentRecord(
                intent_id=intent.intent_id,
                intent_type=intent.intent_type,
                data=intent.data,
                created_by=intent.created_by,
                created_at=intent.created_at,
                status=IntentStatus.REJECTED,
                signed_by=intent.signed_by,
                signature=intent.signature,
                parent_intent_id=intent.parent_intent_id,
                source=intent.source,
                source_id=intent.source_id,
                version=intent.version,
                previous_hash=intent.previous_hash,
                cryptographic_hash=intent.cryptographic_hash,
            )
            self._record_service.store(updated)
        self._audit_writer.write_rejected(intent_id, approver_id, reason)
        return True

    def request_changes(self, intent_id: UUID, requester_id: str, feedback: str) -> bool:
        intent = self._record_service.get(intent_id)
        if not intent or intent.status != IntentStatus.SUBMITTED:
            return False
        with self._lock:
            approval = ApprovalRecord(
                approval_id=uuid4(),
                intent_id=intent_id,
                approver_id=requester_id,
                action=ApprovalAction.REQUEST_CHANGES,
                status=ApprovalStatus.CHANGES_REQUESTED,
                level=ApprovalLevel.LEVEL_1,
                notes=feedback[:500],
                approved_at=datetime.now(UTC),
            )
            self._approvals.setdefault(intent_id, []).append(approval)
            updated = ImmutableIntentRecord(
                intent_id=intent.intent_id,
                intent_type=intent.intent_type,
                data=intent.data,
                created_by=intent.created_by,
                created_at=intent.created_at,
                status=IntentStatus.DRAFT,
                signed_by=intent.signed_by,
                signature=intent.signature,
                parent_intent_id=intent.parent_intent_id,
                source=intent.source,
                source_id=intent.source_id,
                version=intent.version,
                previous_hash=intent.previous_hash,
                cryptographic_hash=intent.cryptographic_hash,
            )
            self._record_service.store(updated)
        return True

    def get_approval_status(self, intent_id: UUID) -> dict[str, Any]:
        intent = self._record_service.get(intent_id)
        if not intent:
            return {"error": "Intent not found"}
        amount = Decimal(str(intent.data.get("amount", 0)))
        rule = self.get_approval_requirement(amount)
        with self._lock:
            approvals = self._approvals.get(intent_id, [])
            approved = [a for a in approvals if a.status == ApprovalStatus.APPROVED]
        return {
            "intent_id": str(intent_id),
            "current_status": intent.status.name,
            "required_level": rule.required_level.name,
            "required_approvers": rule.required_approvers,
            "approvals_received": len(approved),
            "approvals": [a.to_dict() for a in approvals],
        }

    # ==================== REPOSITORY METHODS ====================
    def save_approval(self, approval: ApprovalRecord) -> None:
        with self._lock:
            self._approvals.setdefault(approval.intent_id, []).append(approval)

    def get_approvals_for_intent(self, intent_id: UUID) -> list[ApprovalRecord]:
        with self._lock:
            return self._approvals.get(intent_id, []).copy()

    def get_approval(self, approval_id: UUID) -> ApprovalRecord | None:
        with self._lock:
            for approvals in self._approvals.values():
                for a in approvals:
                    if a.approval_id == approval_id:
                        return a
            return None

    def delete_approval(self, approval_id: UUID) -> bool:
        with self._lock:
            for intent_id, approvals in self._approvals.items():
                for i, a in enumerate(approvals):
                    if a.approval_id == approval_id:
                        self._approvals[intent_id].pop(i)
                        return True
            return False

    def count_approvals(self, intent_id: UUID) -> int:
        with self._lock:
            return len(self._approvals.get(intent_id, []))

    def reset(self) -> None:
        with self._lock:
            self._rules = DEFAULT_APPROVAL_RULES.copy()
            self._approvals = {}


def get_approval_workflow() -> ApprovalWorkflow:
    global _approval_workflow_instance
    if _approval_workflow_instance is None:
        _approval_workflow_instance = ApprovalWorkflow()
    return _approval_workflow_instance


_approval_workflow_instance: ApprovalWorkflow | None = None

__all__ = [
    "ApprovalAction",
    "ApprovalLevel",
    "ApprovalRecord",
    "ApprovalRule",
    "ApprovalStatus",
    "ApprovalWorkflow",
    "get_approval_workflow",
]
