#!/usr/bin/env python3
"""
Module: forbidden_states.py
Layer: 1 - Foundation / Constitution
Responsibility: Mendefinisikan daftar state terlarang yang tidak boleh terjadi.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class ForbiddenStateCategory(Enum):
    NEGATIVE_CASH = auto()
    NEGATIVE_INVENTORY = auto()
    NEGATIVE_RECEIVABLE = auto()
    NEGATIVE_PAYABLE = auto()
    NEGATIVE_EQUITY = auto()
    IMBALANCED_JOURNAL = auto()
    BACKDATED_TRANSACTION = auto()
    FUTURE_TRANSACTION = auto()
    PERIOD_MIXING = auto()
    CROSS_ENTITY_POSTING = auto()
    UNAUTHORIZED_CONSOLIDATION = auto()
    BROKEN_HASH_CHAIN = auto()
    MISSING_AUDIT_EVENT = auto()
    UNAUTHORIZED_ACCESS = auto()
    PRIVILEGE_ESCALATION = auto()
    TAX_MISMATCH = auto()
    PERIOD_CLOSURE_VIOLATION = auto()


class ForbiddenStateSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20


class StateDetectionMethod(Enum):
    PRE_TRANSACTION_VALIDATION = auto()
    POST_TRANSACTION_VALIDATION = auto()
    PERIODIC_SCAN = auto()
    REAL_TIME_MONITOR = auto()
    AUDIT_TIME_DETECTION = auto()


class ForbiddenStateAction(Enum):
    REJECT = auto()
    WARN = auto()
    AUTO_CORRECT = auto()
    FREEZE_SYSTEM = auto()
    NOTIFY_ADMIN = auto()
    LOG_ONLY = auto()


# === 2. EXCEPTIONS ===


class ForbiddenStateError(Exception):
    pass


class ForbiddenStateDetectedError(ForbiddenStateError):
    def __init__(
        self, category: ForbiddenStateCategory, message: str, severity: ForbiddenStateSeverity
    ):
        self.category = category
        self.severity = severity
        super().__init__(f"[{category.name}:{severity.name}] {message}")


class ForbiddenStateRecoveryError(ForbiddenStateError):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class ForbiddenStateDefinition:
    # Required fields (no defaults)
    state_id: UUID
    category: ForbiddenStateCategory
    name: str
    description: str
    severity: ForbiddenStateSeverity
    detection_method: StateDetectionMethod
    default_action: ForbiddenStateAction
    recovery_action: str
    auto_correct: bool
    is_active: bool
    created_at: datetime
    created_by: str
    approved_by: list[str]
    version: str
    # Optional fields (with defaults)
    cryptographic_hash: str = ""
    override_allowed: bool = False
    override_roles: list[str] = field(default_factory=list)
    version_number: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")
        if self.override_allowed and not self.override_roles:
            raise ValueError("Override roles required if override allowed")

    def compute_hash(self) -> str:
        content = f"{self.state_id}|{self.category.value}|{self.name}|{self.description}|{self.severity.value}|{self.detection_method.value}|{self.default_action.value}|{self.recovery_action}|{self.auto_correct}|{self.is_active}|{self.created_at.isoformat()}|{self.created_by}|{','.join(self.approved_by)}|{self.version}|{self.override_allowed}|{','.join(self.override_roles)}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "state_id": str(self.state_id),
                "category": self.category.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "state_id": str(self.state_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ForbiddenStateDefinition:
        return self

    def update(self, updated_by: str, **kwargs) -> ForbiddenStateDefinition:
        new_def = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_def, key) and key not in (
                "state_id",
                "created_at",
                "created_by",
                "version_number",
            ):
                setattr(new_def, key, value)
        new_def.version_number = self.version_number + 1
        new_def._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_def

    def delete(self, deleted_by: str, reason: str | None = None) -> ForbiddenStateDefinition:
        new_def = self._copy()
        new_def.deleted_at = datetime.now(UTC)
        new_def.deleted_by = deleted_by
        new_def.is_active = False
        new_def.version_number = self.version_number + 1
        new_def._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_def

    def restore(self, restored_by: str) -> ForbiddenStateDefinition:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_def = self._copy()
        new_def.deleted_at = None
        new_def.deleted_by = None
        new_def.is_active = True
        new_def.version_number = self.version_number + 1
        new_def._record_audit("RESTORE", restored_by, {})
        return new_def

    def activate(self, activated_by: str) -> ForbiddenStateDefinition:
        if self.is_active:
            return self
        new_def = self._copy()
        new_def.is_active = True
        new_def.version_number = self.version_number + 1
        new_def._record_audit("ACTIVATE", activated_by, {})
        return new_def

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> ForbiddenStateDefinition:
        if not self.is_active:
            return self
        new_def = self._copy()
        new_def.is_active = False
        new_def.version_number = self.version_number + 1
        new_def._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_def

    def lock(self, locked_by: str, reason: str) -> ForbiddenStateDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("LOCK", locked_by, {"reason": reason})
        return new_def

    def unlock(self, unlocked_by: str) -> ForbiddenStateDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("UNLOCK", unlocked_by, {})
        return new_def

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
            "state_id": str(self.state_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "state_id": str(self.state_id),
            "category": self.category.name,
            "name": self.name,
            "description": self.description,
            "severity": self.severity.name,
            "detection_method": self.detection_method.name,
            "default_action": self.default_action.name,
            "recovery_action": self.recovery_action,
            "auto_correct": self.auto_correct,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "approved_by": self.approved_by,
            "version": self.version,
            "override_allowed": self.override_allowed,
            "override_roles": self.override_roles,
            "version_number": self.version_number,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForbiddenStateDefinition:
        return cls(
            state_id=UUID(data["state_id"]),
            category=ForbiddenStateCategory[data["category"]],
            name=data["name"],
            description=data["description"],
            severity=ForbiddenStateSeverity[data["severity"]],
            detection_method=StateDetectionMethod[data["detection_method"]],
            default_action=ForbiddenStateAction[data["default_action"]],
            recovery_action=data["recovery_action"],
            auto_correct=data["auto_correct"],
            is_active=data["is_active"],
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data["created_by"],
            approved_by=data["approved_by"],
            version=data["version"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            override_allowed=data.get("override_allowed", False),
            override_roles=data.get("override_roles", []),
            version_number=data.get("version_number", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> ForbiddenStateDefinition:
        new_id = uuid4()
        return ForbiddenStateDefinition(
            state_id=new_id,
            category=self.category,
            name=self.name,
            description=self.description,
            severity=self.severity,
            detection_method=self.detection_method,
            default_action=self.default_action,
            recovery_action=self.recovery_action,
            auto_correct=self.auto_correct,
            is_active=False,
            created_at=datetime.now(UTC),
            created_by=self.created_by,
            approved_by=self.approved_by.copy(),
            version=self.version,
            cryptographic_hash="",
            override_allowed=self.override_allowed,
            override_roles=self.override_roles.copy(),
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "state_id": str(self.state_id),
            "category": self.category.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # FIX: rename method to avoid conflict with attribute 'version'
    def get_version_number(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ForbiddenStateDefinition:
        new_def = self._copy()
        new_def.version_number = self.version_number + 1
        new_def._record_audit("TOUCH", touched_by, {})
        return new_def

    def _copy(self) -> ForbiddenStateDefinition:
        return ForbiddenStateDefinition(
            state_id=self.state_id,
            category=self.category,
            name=self.name,
            description=self.description,
            severity=self.severity,
            detection_method=self.detection_method,
            default_action=self.default_action,
            recovery_action=self.recovery_action,
            auto_correct=self.auto_correct,
            is_active=self.is_active,
            created_at=self.created_at,
            created_by=self.created_by,
            approved_by=self.approved_by.copy(),
            version=self.version,
            cryptographic_hash=self.cryptographic_hash,
            override_allowed=self.override_allowed,
            override_roles=self.override_roles.copy(),
            version_number=self.version_number,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ForbiddenStateDetection:
    # Required fields (no defaults)
    detection_id: UUID
    state_id: UUID
    category: ForbiddenStateCategory
    severity: ForbiddenStateSeverity
    detected_at: datetime
    detection_method: StateDetectionMethod
    current_state: dict[str, Any]
    attempted_action: dict[str, Any]
    prevented: bool
    action_taken: ForbiddenStateAction
    source_module: str
    resolved: bool
    # Optional fields (with defaults)
    transaction_id: UUID | None = None
    legal_entity_id: UUID | None = None
    prevention_action: str | None = None
    source_user: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    override_used: bool = False
    override_authorized_by: str | None = None
    version_number: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.source_module, {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version number must be >= 1")

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "detection_id": str(self.detection_id),
                "category": self.category.name,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version_number,
                "detection_id": str(self.detection_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ForbiddenStateDetection:
        return self

    def update(self, updated_by: str, **kwargs) -> ForbiddenStateDetection:
        raise AttributeError("ForbiddenStateDetection is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ForbiddenStateDetection:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> ForbiddenStateDetection:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> ForbiddenStateDetection:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ForbiddenStateDetection:
        return self

    def lock(self, locked_by: str, reason: str) -> ForbiddenStateDetection:
        return self

    def unlock(self, unlocked_by: str) -> ForbiddenStateDetection:
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
            "detection_id": str(self.detection_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "detection_id": str(self.detection_id),
            "state_id": str(self.state_id),
            "category": self.category.name,
            "severity": self.severity.name,
            "detected_at": self.detected_at.isoformat(),
            "detection_method": self.detection_method.name,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "legal_entity_id": str(self.legal_entity_id) if self.legal_entity_id else None,
            "current_state": self.current_state,
            "attempted_action": self.attempted_action,
            "prevented": self.prevented,
            "prevention_action": self.prevention_action,
            "action_taken": self.action_taken.name,
            "source_module": self.source_module,
            "source_user": self.source_user,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "override_used": self.override_used,
            "override_authorized_by": self.override_authorized_by,
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForbiddenStateDetection:
        return cls(
            detection_id=UUID(data["detection_id"]),
            state_id=UUID(data["state_id"]),
            category=ForbiddenStateCategory[data["category"]],
            severity=ForbiddenStateSeverity[data["severity"]],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detection_method=StateDetectionMethod[data["detection_method"]],
            transaction_id=UUID(data["transaction_id"]) if data.get("transaction_id") else None,
            legal_entity_id=UUID(data["legal_entity_id"]) if data.get("legal_entity_id") else None,
            current_state=data["current_state"],
            attempted_action=data["attempted_action"],
            prevented=data["prevented"],
            prevention_action=data.get("prevention_action"),
            action_taken=ForbiddenStateAction[data["action_taken"]],
            source_module=data["source_module"],
            source_user=data.get("source_user"),
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            override_used=data.get("override_used", False),
            override_authorized_by=data.get("override_authorized_by"),
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> ForbiddenStateDetection:
        new_id = uuid4()
        return ForbiddenStateDetection(
            detection_id=new_id,
            state_id=self.state_id,
            category=self.category,
            severity=self.severity,
            detected_at=self.detected_at,
            detection_method=self.detection_method,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            current_state=self.current_state.copy(),
            attempted_action=self.attempted_action.copy(),
            prevented=self.prevented,
            prevention_action=self.prevention_action,
            action_taken=self.action_taken,
            source_module=self.source_module,
            source_user=self.source_user,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            override_used=False,
            override_authorized_by=None,
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "detection_id": str(self.detection_id),
            "category": self.category.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # FIX: rename method to avoid conflict with attribute 'version'
    def get_version_number(self) -> int:
        return self.version_number

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ForbiddenStateDetection:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def compute_fingerprint(self) -> str:
        content = f"{self.category.value}|{self.legal_entity_id!s}|{json.dumps(self.current_state, sort_keys=True, default=str)[:500]}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def resolve(self, by: str, action: str) -> ForbiddenStateDetection:
        if self.resolved:
            raise ValueError("Already resolved")
        new_detection = self._copy()
        new_detection.resolved = True
        new_detection.resolved_at = datetime.now(UTC)
        new_detection.resolved_by = by
        new_detection.version_number = self.version_number + 1
        new_detection._record_audit("RESOLVE", by, {"action": action})
        return new_detection

    def _copy(self) -> ForbiddenStateDetection:
        return ForbiddenStateDetection(
            detection_id=self.detection_id,
            state_id=self.state_id,
            category=self.category,
            severity=self.severity,
            detected_at=self.detected_at,
            detection_method=self.detection_method,
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            current_state=self.current_state.copy(),
            attempted_action=self.attempted_action.copy(),
            prevented=self.prevented,
            prevention_action=self.prevention_action,
            action_taken=self.action_taken,
            source_module=self.source_module,
            source_user=self.source_user,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            override_used=self.override_used,
            override_authorized_by=self.override_authorized_by,
            version_number=self.version_number,
        )


# === 4. DETECTOR FUNCTIONS ===


class ForbiddenStateDetector:
    @staticmethod
    def detect_negative_cash(
        current_balance: Decimal,
        proposed_change: Decimal,
        allow_overdraft: bool = False,
        overdraft_limit: Decimal = Decimal(0),
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        new_balance = current_balance + proposed_change
        if new_balance < 0:
            if not allow_overdraft:
                return (
                    True,
                    {
                        "current_balance": str(current_balance),
                        "proposed_change": str(proposed_change),
                        "new_balance": str(new_balance),
                        "deficit": str(abs(new_balance)),
                        "allow_overdraft": False,
                    },
                    ForbiddenStateAction.REJECT,
                )
            elif new_balance < -overdraft_limit:
                return (
                    True,
                    {
                        "current_balance": str(current_balance),
                        "proposed_change": str(proposed_change),
                        "new_balance": str(new_balance),
                        "overdraft_limit": str(overdraft_limit),
                        "excess": str(abs(new_balance) - overdraft_limit),
                    },
                    ForbiddenStateAction.REJECT,
                )
        return False, {}, None

    @staticmethod
    def detect_negative_inventory(
        current_quantity: Decimal, proposed_change: Decimal, allow_backorder: bool = False
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        new_qty = current_quantity + proposed_change
        if new_qty < 0:
            if not allow_backorder:
                return (
                    True,
                    {
                        "current_quantity": str(current_quantity),
                        "proposed_change": str(proposed_change),
                        "new_quantity": str(new_qty),
                        "shortage": str(abs(new_qty)),
                    },
                    ForbiddenStateAction.REJECT,
                )
            else:
                return (
                    True,
                    {
                        "current_quantity": str(current_quantity),
                        "proposed_change": str(proposed_change),
                        "new_quantity": str(new_qty),
                        "shortage": str(abs(new_qty)),
                    },
                    ForbiddenStateAction.WARN,
                )
        return False, {}, None

    @staticmethod
    def detect_negative_receivable(
        current_balance: Decimal, proposed_payment: Decimal
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        new_balance = current_balance - proposed_payment
        if new_balance < 0:
            return (
                True,
                {
                    "current_receivable": str(current_balance),
                    "proposed_payment": str(proposed_payment),
                    "overpayment": str(abs(new_balance)),
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None

    @staticmethod
    def detect_imbalanced_journal(
        total_debit: Decimal, total_credit: Decimal, tolerance: Decimal = Decimal("0.0001")
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        diff = total_debit - total_credit
        if abs(diff) > tolerance:
            return (
                True,
                {
                    "total_debit": str(total_debit),
                    "total_credit": str(total_credit),
                    "difference": str(diff),
                    "tolerance": str(tolerance),
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None

    @staticmethod
    def detect_backdated_transaction(
        transaction_date: datetime, current_period_start: datetime, max_backdate_days: int = 30
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if transaction_date < current_period_start:
            days_back = (current_period_start - transaction_date).days
            if days_back > max_backdate_days:
                return (
                    True,
                    {
                        "transaction_date": transaction_date.isoformat(),
                        "period_start": current_period_start.isoformat(),
                        "days_back": days_back,
                        "max_allowed": max_backdate_days,
                    },
                    ForbiddenStateAction.REJECT,
                )
        return False, {}, None

    @staticmethod
    def detect_future_transaction(
        transaction_date: datetime, current_period_end: datetime, max_forward_days: int = 7
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if transaction_date > current_period_end:
            days_forward = (transaction_date - current_period_end).days
            if days_forward > max_forward_days:
                return (
                    True,
                    {
                        "transaction_date": transaction_date.isoformat(),
                        "period_end": current_period_end.isoformat(),
                        "days_forward": days_forward,
                        "max_allowed": max_forward_days,
                    },
                    ForbiddenStateAction.REJECT,
                )
        return False, {}, None

    @staticmethod
    def detect_cross_entity_posting(
        transaction_legal_entity_id: UUID,
        journal_line_legal_entity_ids: list[UUID],
        authorized_inter_entities: set[UUID],
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        unique = set(journal_line_legal_entity_ids)
        unique.add(transaction_legal_entity_id)
        if len(unique) > 1:
            for entity in unique:
                if entity != transaction_legal_entity_id:
                    pair = frozenset([transaction_legal_entity_id, entity])
                    if pair not in authorized_inter_entities:
                        return (
                            True,
                            {
                                "transaction_entity": str(transaction_legal_entity_id),
                                "involved_entities": [str(e) for e in unique],
                                "unauthorized_pair": str(entity),
                            },
                            ForbiddenStateAction.REJECT,
                        )
        return False, {}, None

    @staticmethod
    def detect_broken_hash_chain(
        expected_previous_hash: str, actual_previous_hash: str
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if expected_previous_hash != actual_previous_hash:
            return (
                True,
                {
                    "expected_hash": expected_previous_hash[:16] + "...",
                    "actual_hash": actual_previous_hash[:16] + "...",
                },
                ForbiddenStateAction.FREEZE_SYSTEM,
            )
        return False, {}, None

    @staticmethod
    def detect_missing_audit_event(
        expected_sequence: int, actual_sequence: int
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if actual_sequence > expected_sequence + 1:
            missing = list(range(expected_sequence + 1, actual_sequence))
            return (
                True,
                {
                    "expected_next": expected_sequence + 1,
                    "actual_next": actual_sequence,
                    "missing_count": len(missing),
                    "missing_sequences": missing[:10],
                },
                ForbiddenStateAction.REJECT,  # FIX: Ganti CRITICAL dengan REJECT
            )
        return False, {}, None

    @staticmethod
    def detect_tax_mismatch(
        calculated_tax: Decimal, reported_tax: Decimal, tolerance: Decimal = Decimal("0.01")
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        diff = calculated_tax - reported_tax
        if abs(diff) > tolerance:
            return (
                True,
                {
                    "calculated_tax": str(calculated_tax),
                    "reported_tax": str(reported_tax),
                    "difference": str(diff),
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None

    @staticmethod
    def detect_period_closure_violation(
        period_status: str, transaction_date: datetime, period_start: datetime, period_end: datetime
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if period_status == "CLOSED":
            return (
                True,
                {
                    "period_status": "CLOSED",
                    "transaction_date": transaction_date.isoformat(),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None

    @staticmethod
    def detect_privilege_escalation(
        user_roles: list[str],
        required_roles: list[str],
        user_permissions: set[str],
        required_permissions: set[str],
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        role_match = any(r in required_roles for r in user_roles)
        perm_match = required_permissions.issubset(user_permissions)
        if not role_match and not perm_match:
            return (
                True,
                {
                    "user_roles": user_roles,
                    "required_roles": required_roles,
                    "missing_permissions": list(required_permissions - user_permissions),
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None

    @staticmethod
    def detect_negative_equity(
        total_equity: Decimal, minimum_equity: Decimal = Decimal(0)
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        if total_equity < minimum_equity:
            return (
                True,
                {
                    "total_equity": str(total_equity),
                    "minimum_equity": str(minimum_equity),
                    "deficit": str(abs(total_equity - minimum_equity)),
                },
                ForbiddenStateAction.FREEZE_SYSTEM,
            )
        return False, {}, None

    @staticmethod
    def detect_period_mixing(
        transaction_dates: list[datetime], period_boundaries: list[tuple[datetime, datetime]]
    ) -> tuple[bool, dict[str, Any], ForbiddenStateAction | None]:
        periods = set()
        for tx_date in transaction_dates:
            for start, end in period_boundaries:
                if start <= tx_date <= end:
                    periods.add(f"{start.date()}-{end.date()}")
                    break
        if len(periods) > 1:
            return (
                True,
                {
                    "periods_found": list(periods),
                    "transaction_dates": [d.isoformat() for d in transaction_dates],
                },
                ForbiddenStateAction.REJECT,
            )
        return False, {}, None


_FORBIDDEN_STATE_DETECTOR_MAP: dict[ForbiddenStateCategory, Callable] = {
    ForbiddenStateCategory.NEGATIVE_CASH: ForbiddenStateDetector.detect_negative_cash,
    ForbiddenStateCategory.NEGATIVE_INVENTORY: ForbiddenStateDetector.detect_negative_inventory,
    ForbiddenStateCategory.NEGATIVE_RECEIVABLE: ForbiddenStateDetector.detect_negative_receivable,
    ForbiddenStateCategory.NEGATIVE_EQUITY: ForbiddenStateDetector.detect_negative_equity,
    ForbiddenStateCategory.IMBALANCED_JOURNAL: ForbiddenStateDetector.detect_imbalanced_journal,
    ForbiddenStateCategory.BACKDATED_TRANSACTION: ForbiddenStateDetector.detect_backdated_transaction,
    ForbiddenStateCategory.FUTURE_TRANSACTION: ForbiddenStateDetector.detect_future_transaction,
    ForbiddenStateCategory.PERIOD_MIXING: ForbiddenStateDetector.detect_period_mixing,
    ForbiddenStateCategory.CROSS_ENTITY_POSTING: ForbiddenStateDetector.detect_cross_entity_posting,
    ForbiddenStateCategory.BROKEN_HASH_CHAIN: ForbiddenStateDetector.detect_broken_hash_chain,
    ForbiddenStateCategory.MISSING_AUDIT_EVENT: ForbiddenStateDetector.detect_missing_audit_event,
    ForbiddenStateCategory.TAX_MISMATCH: ForbiddenStateDetector.detect_tax_mismatch,
    ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION: ForbiddenStateDetector.detect_period_closure_violation,
    ForbiddenStateCategory.PRIVILEGE_ESCALATION: ForbiddenStateDetector.detect_privilege_escalation,
}


def get_detector_for_state(category: ForbiddenStateCategory) -> Callable | None:
    return _FORBIDDEN_STATE_DETECTOR_MAP.get(category)


# === 5. FORBIDDEN STATES REGISTRY ===


@dataclass
class ForbiddenStatesRegistry:
    states: dict[UUID, ForbiddenStateDefinition] = field(default_factory=dict)
    detections: list[ForbiddenStateDetection] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.states:
            self._load_default_states()

    def _load_default_states(self) -> None:
        now = datetime.now(UTC)
        default_data = [
            (
                ForbiddenStateCategory.NEGATIVE_CASH,
                "Negative Cash Balance",
                "Cash must never be negative without overdraft",
                ForbiddenStateSeverity.CRITICAL,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.REJECT,
                "Reject transaction and notify treasury",
                False,
                True,
                True,
                ["cfo", "treasurer"],
            ),
            (
                ForbiddenStateCategory.NEGATIVE_INVENTORY,
                "Negative Inventory",
                "Inventory quantity must never be negative",
                ForbiddenStateSeverity.HIGH,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.REJECT,
                "Reject goods issue, review stock movement",
                False,
                True,
                True,
                ["warehouse_manager"],
            ),
            (
                ForbiddenStateCategory.IMBALANCED_JOURNAL,
                "Imbalanced Journal Entry",
                "Journal must have equal debit and credit",
                ForbiddenStateSeverity.CRITICAL,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.REJECT,
                "Reject journal entry, require correction",
                False,
                True,
                False,
                [],
            ),
            (
                ForbiddenStateCategory.BACKDATED_TRANSACTION,
                "Backdated Transaction Exceeds Limit",
                "No backdating beyond limit",
                ForbiddenStateSeverity.MEDIUM,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.WARN,
                "Warn user, require managerial approval",
                False,
                True,
                True,
                ["finance_manager", "auditor"],
            ),
            (
                ForbiddenStateCategory.BROKEN_HASH_CHAIN,
                "Broken Cryptographic Hash Chain",
                "Hash chain integrity failed",
                ForbiddenStateSeverity.CATASTROPHIC,
                StateDetectionMethod.PERIODIC_SCAN,
                ForbiddenStateAction.FREEZE_SYSTEM,
                "Freeze system, trigger security incident response",
                False,
                True,
                False,
                [],
            ),
            (
                ForbiddenStateCategory.CROSS_ENTITY_POSTING,
                "Unauthorized Cross-Entity Posting",
                "Cross-entity posting requires authorization",
                ForbiddenStateSeverity.HIGH,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.REJECT,
                "Reject transaction, require inter-entity approval",
                False,
                True,
                True,
                ["cfo", "legal"],
            ),
            (
                ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION,
                "Period Closure Violation",
                "Cannot post to closed period",
                ForbiddenStateSeverity.HIGH,
                StateDetectionMethod.PRE_TRANSACTION_VALIDATION,
                ForbiddenStateAction.REJECT,
                "Reject transaction, notify period is closed",
                False,
                True,
                True,
                ["auditor", "cfo"],
            ),
            (
                ForbiddenStateCategory.NEGATIVE_EQUITY,
                "Negative Equity (Insolvency)",
                "Total equity must never be negative",
                ForbiddenStateSeverity.CATASTROPHIC,
                StateDetectionMethod.PERIODIC_SCAN,
                ForbiddenStateAction.FREEZE_SYSTEM,
                "Immediate management notification, system freeze",
                False,
                True,
                False,
                [],
            ),
        ]
        for (
            cat,
            name,
            desc,
            sev,
            method,
            action,
            recovery,
            auto_correct,
            is_active,
            override_allowed,
            roles,
        ) in default_data:
            state = ForbiddenStateDefinition(
                state_id=uuid4(),
                category=cat,
                name=name,
                description=desc,
                severity=sev,
                detection_method=method,
                default_action=action,
                recovery_action=recovery,
                auto_correct=auto_correct,
                is_active=is_active,
                created_at=now,
                created_by="system_bootstrap",
                approved_by=["audit_committee_founder"],
                version="1.0.0",
                cryptographic_hash="",
                override_allowed=override_allowed,
                override_roles=roles,
                version_number=1,
            )
            self.states[state.state_id] = state

    # ==================== REPOSITORY METHODS ====================
    def save_state(self, state: ForbiddenStateDefinition) -> None:
        with self._lock:
            self.states[state.state_id] = state

    def get_state(self, state_id: UUID) -> ForbiddenStateDefinition | None:
        return self.states.get(state_id)

    def get_all_states(self) -> list[ForbiddenStateDefinition]:
        return list(self.states.values())

    def delete_state(self, state_id: UUID) -> bool:
        with self._lock:
            if state_id in self.states:
                del self.states[state_id]
                return True
            return False

    def save_detection(self, detection: ForbiddenStateDetection) -> None:
        with self._lock:
            self.detections.append(detection)

    def get_detections(
        self,
        limit: int = 100,
        category: ForbiddenStateCategory | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        resolved_only: bool = False,
        unresolved_only: bool = False,
        prevented_only: bool | None = None,
    ) -> list[ForbiddenStateDetection]:
        result = self.detections[-limit:]
        if category:
            result = [d for d in result if d.category == category]
        if from_date:
            result = [d for d in result if d.detected_at >= from_date]
        if to_date:
            result = [d for d in result if d.detected_at <= to_date]
        if resolved_only:
            result = [d for d in result if d.resolved]
        if unresolved_only:
            result = [d for d in result if not d.resolved]
        if prevented_only is not None:
            result = [d for d in result if d.prevented == prevented_only]
        return result

    def resolve_detection(
        self, detection_id: UUID, resolved_by: str, resolution_action: str
    ) -> ForbiddenStateDetection | None:
        with self._lock:
            for i, d in enumerate(self.detections):
                if d.detection_id == detection_id and not d.resolved:
                    resolved = d.resolve(resolved_by, resolution_action)
                    self.detections[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def check(
        self,
        category: ForbiddenStateCategory,
        context: dict[str, Any],
        transaction_id: UUID | None = None,
        legal_entity_id: UUID | None = None,
        source_module: str = "unknown",
        source_user: str | None = None,
        override: bool = False,
        override_authorized_by: str | None = None,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        state_def = next(
            (s for s in self.states.values() if s.category == category and s.is_active), None
        )
        if not state_def:
            return False, None, None
        detector = get_detector_for_state(category)
        if not detector:
            logger.error(f"No detector for {category}")
            return False, None, None
        is_forbidden, details, suggested = detector(**context)
        if not is_forbidden:
            return False, None, None
        action_taken = suggested or state_def.default_action
        prevented = action_taken not in [ForbiddenStateAction.WARN, ForbiddenStateAction.LOG_ONLY]
        if (
            override
            and state_def.override_allowed
            and override_authorized_by in state_def.override_roles
        ):
            action_taken = ForbiddenStateAction.WARN
            prevented = False
            logger.warning(f"Override used for {category.name} by {override_authorized_by}")
        detection = ForbiddenStateDetection(
            detection_id=uuid4(),
            state_id=state_def.state_id,
            category=category,
            severity=state_def.severity,
            detected_at=datetime.now(UTC),
            detection_method=state_def.detection_method,
            current_state=context.get("current_state", {}),
            attempted_action=context,
            prevented=prevented,
            action_taken=action_taken,
            source_module=source_module,
            resolved=False,
            transaction_id=transaction_id,
            legal_entity_id=legal_entity_id,
            prevention_action=state_def.recovery_action if prevented else None,
            source_user=source_user,
            override_used=override and state_def.override_allowed,
            override_authorized_by=override_authorized_by if override else None,
        )
        self.save_detection(detection)
        self._notify_supreme_law(detection, state_def)
        if state_def.severity == ForbiddenStateSeverity.CATASTROPHIC:
            self._handle_catastrophic_detection(detection)
        return True, detection, action_taken

    def _notify_supreme_law(
        self, detection: ForbiddenStateDetection, state_def: ForbiddenStateDefinition
    ) -> None:
        try:
            supreme_law = get_supreme_law()
            supreme_law.check_violation(
                ConstitutionalPrinciple.IMMUTABILITY,
                detection.source_module,
                f"Forbidden state detected: {state_def.name}",
                detection.source_user,
                detection.transaction_id,
            )
        except Exception as e:
            logger.critical(f"Failed to notify supreme law: {e}")

    def _handle_catastrophic_detection(self, detection: ForbiddenStateDetection) -> None:
        logger.critical(
            f"CATASTROPHIC FORBIDDEN STATE: {detection.category.name}. System freeze recommended."
        )

    def is_action_forbidden(
        self, category: ForbiddenStateCategory, context: dict[str, Any], **kwargs
    ) -> bool:
        is_forbidden, _, _ = self.check(category, context, **kwargs)
        return is_forbidden

    def get_unresolved_detections(self) -> list[ForbiddenStateDetection]:
        return [d for d in self.detections if not d.resolved]

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_states = len(self.states)
            active_states = len(
                [s for s in self.states.values() if s.is_active and s.deleted_at is None]
            )
            total_detections = len(self.detections)
            unresolved = len([d for d in self.detections if not d.resolved])
            prevented = len([d for d in self.detections if d.prevented])
            overrides = len([d for d in self.detections if d.override_used])
            by_category = {
                cat.name: len([d for d in self.detections if d.category == cat])
                for cat in ForbiddenStateCategory
                if any(d.category == cat for d in self.detections)
            }
            by_severity = {
                sev.name: len([d for d in self.detections if d.severity == sev])
                for sev in ForbiddenStateSeverity
                if any(d.severity == sev for d in self.detections)
            }
            return {
                "total_states": total_states,
                "active_states": active_states,
                "total_detections": total_detections,
                "unresolved_detections": unresolved,
                "prevented_detections": prevented,
                "overrides_used": overrides,
                "by_category": by_category,
                "by_severity": by_severity,
                "latest_detection": self.detections[-1].detected_at.isoformat()
                if self.detections
                else None,
            }

    def reset(self) -> None:
        with self._lock:
            self.states = {}
            self.detections = []
            self._load_default_states()


# === 6. FORBIDDEN STATES SERVICE ===


class ForbiddenStatesService:
    _instance: ForbiddenStatesService | None = None
    _initialized: bool  # FIX: deklarasikan
    _registry: ForbiddenStatesRegistry  # FIX: ganti dari optional ke non-optional

    def __new__(cls) -> ForbiddenStatesService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._registry = ForbiddenStatesRegistry()

    # ==================== REPOSITORY METHODS ====================
    def get_registry(self) -> ForbiddenStatesRegistry:
        return self._registry

    def save_state(self, state: ForbiddenStateDefinition) -> None:
        self._registry.save_state(state)

    def get_state(self, state_id: UUID) -> ForbiddenStateDefinition | None:
        return self._registry.get_state(state_id)

    def get_all_states(self) -> list[ForbiddenStateDefinition]:
        return self._registry.get_all_states()

    def delete_state(self, state_id: UUID) -> bool:
        return self._registry.delete_state(state_id)

    def save_detection(self, detection: ForbiddenStateDetection) -> None:
        self._registry.save_detection(detection)

    def get_detections(self, limit: int = 100, **filters) -> list[ForbiddenStateDetection]:
        return self._registry.get_detections(limit, **filters)

    def resolve_detection(
        self, detection_id: UUID, resolved_by: str, resolution_action: str
    ) -> ForbiddenStateDetection | None:
        return self._registry.resolve_detection(detection_id, resolved_by, resolution_action)

    # ==================== BUSINESS METHODS ====================
    def check_negative_cash(
        self,
        current_balance: Decimal,
        proposed_change: Decimal,
        allow_overdraft: bool = False,
        overdraft_limit: Decimal = Decimal(0),
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "current_balance": current_balance,
            "proposed_change": proposed_change,
            "allow_overdraft": allow_overdraft,
            "overdraft_limit": overdraft_limit,
            "current_state": {"cash_balance": str(current_balance)},
        }
        return self._registry.check(ForbiddenStateCategory.NEGATIVE_CASH, context, **kwargs)

    def check_negative_inventory(
        self,
        current_quantity: Decimal,
        proposed_change: Decimal,
        allow_backorder: bool = False,
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "current_quantity": current_quantity,
            "proposed_change": proposed_change,
            "allow_backorder": allow_backorder,
            "current_state": {"inventory_quantity": str(current_quantity)},
        }
        return self._registry.check(ForbiddenStateCategory.NEGATIVE_INVENTORY, context, **kwargs)

    def check_negative_receivable(
        self, current_balance: Decimal, proposed_payment: Decimal, **kwargs
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "current_balance": current_balance,
            "proposed_payment": proposed_payment,
            "current_state": {"receivable_balance": str(current_balance)},
        }
        return self._registry.check(ForbiddenStateCategory.NEGATIVE_RECEIVABLE, context, **kwargs)

    def check_imbalanced_journal(
        self,
        total_debit: Decimal,
        total_credit: Decimal,
        tolerance: Decimal = Decimal("0.0001"),
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "tolerance": tolerance,
            "current_state": {"total_debit": str(total_debit), "total_credit": str(total_credit)},
        }
        return self._registry.check(ForbiddenStateCategory.IMBALANCED_JOURNAL, context, **kwargs)

    def check_backdated_transaction(
        self,
        transaction_date: datetime,
        current_period_start: datetime,
        max_backdate_days: int = 30,
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "transaction_date": transaction_date,
            "current_period_start": current_period_start,
            "max_backdate_days": max_backdate_days,
            "current_state": {"period_start": current_period_start.isoformat()},
        }
        return self._registry.check(ForbiddenStateCategory.BACKDATED_TRANSACTION, context, **kwargs)

    def check_cross_entity_posting(
        self,
        transaction_legal_entity_id: UUID,
        journal_line_legal_entity_ids: list[UUID],
        authorized_inter_entities: set[UUID],
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "transaction_legal_entity_id": transaction_legal_entity_id,
            "journal_line_legal_entity_ids": journal_line_legal_entity_ids,
            "authorized_inter_entities": authorized_inter_entities,
            "current_state": {"transaction_entity": str(transaction_legal_entity_id)},
        }
        return self._registry.check(ForbiddenStateCategory.CROSS_ENTITY_POSTING, context, **kwargs)

    def check_period_closure(
        self,
        period_status: str,
        transaction_date: datetime,
        period_start: datetime,
        period_end: datetime,
        **kwargs,
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "period_status": period_status,
            "transaction_date": transaction_date,
            "period_start": period_start,
            "period_end": period_end,
            "current_state": {"period_status": period_status},
        }
        return self._registry.check(
            ForbiddenStateCategory.PERIOD_CLOSURE_VIOLATION, context, **kwargs
        )

    def check_broken_hash_chain(
        self, expected_previous_hash: str, actual_previous_hash: str, **kwargs
    ) -> tuple[bool, ForbiddenStateDetection | None, ForbiddenStateAction | None]:
        context = {
            "expected_previous_hash": expected_previous_hash,
            "actual_previous_hash": actual_previous_hash,
        }
        return self._registry.check(ForbiddenStateCategory.BROKEN_HASH_CHAIN, context, **kwargs)

    def get_detection_history(self, **filters) -> list[ForbiddenStateDetection]:
        return self._registry.get_detections(**filters)

    def get_statistics(self) -> dict[str, Any]:
        return self._registry.get_statistics()


def get_forbidden_states_service() -> ForbiddenStatesService:
    global _forbidden_states_service_instance
    if _forbidden_states_service_instance is None:
        _forbidden_states_service_instance = ForbiddenStatesService()
    return _forbidden_states_service_instance


_forbidden_states_service_instance: ForbiddenStatesService | None = None

__all__ = [
    "ForbiddenStateAction",
    "ForbiddenStateCategory",
    "ForbiddenStateDefinition",
    "ForbiddenStateDetectedError",
    "ForbiddenStateDetection",
    "ForbiddenStateDetector",
    "ForbiddenStateError",
    "ForbiddenStateRecoveryError",
    "ForbiddenStateSeverity",
    "ForbiddenStatesRegistry",
    "ForbiddenStatesService",
    "StateDetectionMethod",
    "get_detector_for_state",
    "get_forbidden_states_service",
]
