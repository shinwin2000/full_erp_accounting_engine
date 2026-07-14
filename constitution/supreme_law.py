#!/usr/bin/env python3
"""
Module: supreme_law.py
Layer: 1 - Foundation / Constitution
Responsibility: Hukum tertinggi sistem; semua modul tunduk pada aturan ini.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class ConstitutionalPrinciple(Enum):
    DOUBLE_ENTRY = auto()
    ACCRUAL_BASIS = auto()
    GOING_CONCERN = auto()
    CONSERVATISM = auto()
    MATERIALITY = auto()
    SUBSTANCE_OVER_FORM = auto()
    IMMUTABILITY = auto()
    AUDIT_TRAIL_COMPLETENESS = auto()
    TIME_IRREVERSIBILITY = auto()
    CAUSALITY_CHAIN = auto()
    SEGREGATION_OF_DUTIES = auto()
    DUAL_APPROVAL = auto()
    NON_REPUDIATION = auto()
    ZERO_TRUST = auto()
    LEGAL_SUPREMACY = auto()
    REGULATORY_COMPLIANCE = auto()
    TAX_OBEDIENCE = auto()
    PERIOD_CLOSURE = auto()
    GL_SUPREMACY = auto()
    NO_RETROACTIVE_POLICY = auto()


class ConstitutionalSeverity(Enum):
    CRITICAL = 100
    HIGH = 70
    MEDIUM = 40
    LOW = 10
    INFO = 0


class SovereigntyLevel(Enum):
    ABSOLUTE = 3
    ORDINARY = 2
    DEFAULT = 1
    SUGGESTION = 0


class EmergencyOverrideReason(Enum):
    NATURAL_DISASTER = auto()
    REGULATORY_MANDATE = auto()
    COURT_ORDER = auto()
    SYSTEM_MIGRATION = auto()
    AUDIT_CORRECTION = auto()
    TECHNICAL_EMERGENCY = auto()


# === 2. CUSTOM EXCEPTIONS ===


class ConstitutionalViolationError(Exception):
    def __init__(
        self,
        principle: ConstitutionalPrinciple,
        message: str,
        severity: ConstitutionalSeverity,
        offending_module: str,
        violation_id: UUID | None = None,
    ):
        self.principle = principle
        self.severity = severity
        self.offending_module = offending_module
        self.violation_id = violation_id or uuid4()
        self.timestamp = datetime.now(UTC)
        super().__init__(
            f"[{principle.name}] {message} (Severity: {severity.name}, Module: {offending_module}, ID: {self.violation_id})"
        )


class ConstitutionAmendmentError(Exception):
    pass


class SovereigntyViolationError(Exception):
    pass


class EmergencyOverrideError(Exception):
    pass


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class ConstitutionalRule:
    rule_id: UUID
    principle: ConstitutionalPrinciple
    statement: str
    sovereignty: SovereigntyLevel
    severity_on_violation: ConstitutionalSeverity
    effective_from: datetime
    created_by: str
    created_at: datetime
    approved_by: list[str]
    effective_until: datetime | None = None
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    cryptographic_hash: str = ""

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.sovereignty == SovereigntyLevel.ABSOLUTE and len(self.approved_by) < 3:
            raise ValueError("Absolute sovereignty requires at least 3 approvers")
        elif self.sovereignty == SovereigntyLevel.ORDINARY and len(self.approved_by) < 2:
            raise ValueError("Ordinary sovereignty requires at least 2 approvers")
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.effective_from.tzinfo is None:
            object.__setattr__(self, "effective_from", self.effective_from.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        content = f"{self.rule_id}|{self.principle.value}|{self.statement}|{self.sovereignty.value}|{self.effective_from.isoformat()}|{self.effective_until.isoformat() if self.effective_until else ''}|{self.created_by}|{self.created_at.isoformat()}|{','.join(self.approved_by)}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "rule_id": str(self.rule_id),
                "principle": self.principle.name,
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
                "version": self.version,
                "rule_id": str(self.rule_id),
                "details": details,
            }
        )

    # Entity dasar methods
    def create(self, created_by: str) -> ConstitutionalRule:
        return self

    def update(self, updated_by: str, **kwargs) -> ConstitutionalRule:
        new_rule = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_rule, key) and key not in (
                "rule_id",
                "created_at",
                "created_by",
                "version",
            ):
                setattr(new_rule, key, value)
        new_rule.version = self.version + 1
        new_rule._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_rule

    def delete(self, deleted_by: str, reason: str | None = None) -> ConstitutionalRule:
        new_rule = self._copy()
        new_rule.deleted_at = datetime.now(UTC)
        new_rule.deleted_by = deleted_by
        new_rule.effective_until = datetime.now(UTC)
        new_rule.version = self.version + 1
        new_rule._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_rule

    def restore(self, restored_by: str) -> ConstitutionalRule:
        if self.deleted_at is None:
            raise ValueError("Rule not deleted")
        new_rule = self._copy()
        new_rule.deleted_at = None
        new_rule.deleted_by = None
        new_rule.effective_until = None
        new_rule.version = self.version + 1
        new_rule._record_audit("RESTORE", restored_by, {})
        return new_rule

    def activate(self, activated_by: str) -> ConstitutionalRule:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ConstitutionalRule:
        new_rule = self._copy()
        new_rule.effective_until = datetime.now(UTC)
        new_rule.version = self.version + 1
        new_rule._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_rule

    def lock(self, locked_by: str, reason: str) -> ConstitutionalRule:
        return self

    def unlock(self, unlocked_by: str) -> ConstitutionalRule:
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
            "rule_id": str(self.rule_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": str(self.rule_id),
            "principle": self.principle.name,
            "statement": self.statement,
            "sovereignty": self.sovereignty.name,
            "severity_on_violation": self.severity_on_violation.name,
            "effective_from": self.effective_from.isoformat(),
            "effective_until": self.effective_until.isoformat() if self.effective_until else None,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "approved_by": self.approved_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstitutionalRule:
        return cls(
            rule_id=UUID(data["rule_id"]),
            principle=ConstitutionalPrinciple[data["principle"]],
            statement=data["statement"],
            sovereignty=SovereigntyLevel[data["sovereignty"]],
            severity_on_violation=ConstitutionalSeverity[data["severity_on_violation"]],
            effective_from=datetime.fromisoformat(data["effective_from"]),
            effective_until=datetime.fromisoformat(data["effective_until"])
            if data.get("effective_until")
            else None,
            created_by=data["created_by"],
            created_at=datetime.fromisoformat(data["created_at"]),
            approved_by=data["approved_by"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> ConstitutionalRule:
        new_id = uuid4()
        return ConstitutionalRule(
            rule_id=new_id,
            principle=self.principle,
            statement=self.statement,
            sovereignty=self.sovereignty,
            severity_on_violation=self.severity_on_violation,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
            created_by=self.created_by,
            created_at=self.created_at,
            approved_by=self.approved_by.copy(),
            cryptographic_hash="",
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rule_id": str(self.rule_id),
            "principle": self.principle.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConstitutionalRule:
        new_rule = self._copy()
        new_rule.version = self.version + 1
        new_rule._record_audit("TOUCH", touched_by, {})
        return new_rule

    def is_active(self, at_date: datetime | None = None) -> bool:
        check = at_date or datetime.now(UTC)
        if self.deleted_at:
            return False
        if check < self.effective_from:
            return False
        # FIXED: inactive if check >= effective_until (bukan >)
        if self.effective_until and check >= self.effective_until:
            return False
        return True

    def _copy(self) -> ConstitutionalRule:
        return ConstitutionalRule(
            rule_id=self.rule_id,
            principle=self.principle,
            statement=self.statement,
            sovereignty=self.sovereignty,
            severity_on_violation=self.severity_on_violation,
            effective_from=self.effective_from,
            effective_until=self.effective_until,
            created_by=self.created_by,
            created_at=self.created_at,
            approved_by=self.approved_by.copy(),
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class AmendmentRecord:
    amendment_id: UUID
    previous_version_id: UUID
    new_version_id: UUID
    changes_description: str
    proposed_by: str
    proposed_at: datetime
    approved_by: list[str]
    approved_at: datetime
    effective_from: datetime
    justification: str
    impact_assessment: str
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    cryptographic_signature: str = ""

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.proposed_by, {})

    def _validate(self) -> None:
        if len(self.approved_by) < 2:
            raise ValueError("Amendment requires at least 2 approvals")
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.proposed_at.tzinfo is None:
            object.__setattr__(self, "proposed_at", self.proposed_at.replace(tzinfo=UTC))
        if self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))
        if self.effective_from.tzinfo is None:
            object.__setattr__(self, "effective_from", self.effective_from.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "amendment_id": str(self.amendment_id),
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
                "version": self.version,
                "amendment_id": str(self.amendment_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> AmendmentRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> AmendmentRecord:
        raise AttributeError("AmendmentRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> AmendmentRecord:
        new_record = self._copy()
        new_record.deleted_at = datetime.now(UTC)
        new_record.deleted_by = deleted_by
        new_record.version = self.version + 1
        new_record._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_record

    def restore(self, restored_by: str) -> AmendmentRecord:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_record = self._copy()
        new_record.deleted_at = None
        new_record.deleted_by = None
        new_record.version = self.version + 1
        new_record._record_audit("RESTORE", restored_by, {})
        return new_record

    def activate(self, activated_by: str) -> AmendmentRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> AmendmentRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> AmendmentRecord:
        return self

    def unlock(self, unlocked_by: str) -> AmendmentRecord:
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
            "amendment_id": str(self.amendment_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "amendment_id": str(self.amendment_id),
            "previous_version_id": str(self.previous_version_id),
            "new_version_id": str(self.new_version_id),
            "changes_description": self.changes_description,
            "proposed_by": self.proposed_by,
            "proposed_at": self.proposed_at.isoformat(),
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat(),
            "effective_from": self.effective_from.isoformat(),
            "cryptographic_signature": self.cryptographic_signature[:16] + "...",
            "justification": self.justification[:100],
            "impact_assessment": self.impact_assessment[:100],
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AmendmentRecord:
        return cls(
            amendment_id=UUID(data["amendment_id"]),
            previous_version_id=UUID(data["previous_version_id"]),
            new_version_id=UUID(data["new_version_id"]),
            changes_description=data["changes_description"],
            proposed_by=data["proposed_by"],
            proposed_at=datetime.fromisoformat(data["proposed_at"]),
            approved_by=data["approved_by"],
            approved_at=datetime.fromisoformat(data["approved_at"]),
            effective_from=datetime.fromisoformat(data["effective_from"]),
            justification=data.get("justification", ""),
            impact_assessment=data.get("impact_assessment", ""),
            cryptographic_signature=data.get("cryptographic_signature", ""),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> AmendmentRecord:
        new_id = uuid4()
        return AmendmentRecord(
            amendment_id=new_id,
            previous_version_id=self.previous_version_id,
            new_version_id=self.new_version_id,
            changes_description=self.changes_description,
            proposed_by=self.proposed_by,
            proposed_at=self.proposed_at,
            approved_by=self.approved_by.copy(),
            approved_at=self.approved_at,
            effective_from=self.effective_from,
            cryptographic_signature=self.cryptographic_signature,
            justification=self.justification,
            impact_assessment=self.impact_assessment,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "amendment_id": str(self.amendment_id),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> AmendmentRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def compute_signature_content(self) -> str:
        return f"{self.amendment_id}|{self.previous_version_id}|{self.new_version_id}|{self.changes_description}|{self.proposed_by}|{self.proposed_at.isoformat()}|{','.join(self.approved_by)}|{self.approved_at.isoformat()}|{self.effective_from.isoformat()}|{self.justification}"

    def verify_signature(self, public_keys: dict[str, str]) -> bool:
        return len(self.approved_by) >= 2

    def _copy(self) -> AmendmentRecord:
        return AmendmentRecord(
            amendment_id=self.amendment_id,
            previous_version_id=self.previous_version_id,
            new_version_id=self.new_version_id,
            changes_description=self.changes_description,
            proposed_by=self.proposed_by,
            proposed_at=self.proposed_at,
            approved_by=self.approved_by.copy(),
            approved_at=self.approved_at,
            effective_from=self.effective_from,
            cryptographic_signature=self.cryptographic_signature,
            justification=self.justification,
            impact_assessment=self.impact_assessment,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class EmergencyOverride:
    override_id: UUID
    reason: EmergencyOverrideReason
    suspended_principles: set[ConstitutionalPrinciple]
    duration_hours: int
    authorized_by: list[str]
    authorized_at: datetime
    justification_document: str
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    cryptographic_hash: str = ""

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.authorized_by[0] if self.authorized_by else "system", {})

    def _validate(self) -> None:
        if self.duration_hours > 72:
            raise ValueError("Emergency override cannot exceed 72 hours")
        if len(self.authorized_by) < 2:
            raise ValueError("Emergency override requires at least 2 authorizers")
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.authorized_at.tzinfo is None:
            object.__setattr__(self, "authorized_at", self.authorized_at.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        content = f"{self.override_id}|{self.reason.value}|{sorted([p.value for p in self.suspended_principles])}|{self.duration_hours}|{','.join(self.authorized_by)}|{self.authorized_at.isoformat()}|{self.justification_document}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "override_id": str(self.override_id),
                "reason": self.reason.name,
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
                "version": self.version,
                "override_id": str(self.override_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> EmergencyOverride:
        return self

    def update(self, updated_by: str, **kwargs) -> EmergencyOverride:
        raise AttributeError("EmergencyOverride is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> EmergencyOverride:
        new_override = self._copy()
        new_override.deleted_at = datetime.now(UTC)
        new_override.deleted_by = deleted_by
        new_override.version = self.version + 1
        new_override._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_override

    def restore(self, restored_by: str) -> EmergencyOverride:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_override = self._copy()
        new_override.deleted_at = None
        new_override.deleted_by = None
        new_override.version = self.version + 1
        new_override._record_audit("RESTORE", restored_by, {})
        return new_override

    def activate(self, activated_by: str) -> EmergencyOverride:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EmergencyOverride:
        return self

    def lock(self, locked_by: str, reason: str) -> EmergencyOverride:
        return self

    def unlock(self, unlocked_by: str) -> EmergencyOverride:
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
            "override_id": str(self.override_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "override_id": str(self.override_id),
            "reason": self.reason.name,
            "suspended_principles": [p.name for p in self.suspended_principles],
            "duration_hours": self.duration_hours,
            "authorized_by": self.authorized_by,
            "authorized_at": self.authorized_at.isoformat(),
            "justification_document": self.justification_document,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EmergencyOverride:
        return cls(
            override_id=UUID(data["override_id"]),
            reason=EmergencyOverrideReason[data["reason"]],
            suspended_principles={
                ConstitutionalPrinciple[p] for p in data.get("suspended_principles", [])
            },
            duration_hours=data["duration_hours"],
            authorized_by=data["authorized_by"],
            authorized_at=datetime.fromisoformat(data["authorized_at"]),
            justification_document=data["justification_document"],
            cryptographic_hash=data.get("cryptographic_hash", ""),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> EmergencyOverride:
        new_id = uuid4()
        return EmergencyOverride(
            override_id=new_id,
            reason=self.reason,
            suspended_principles=self.suspended_principles.copy(),
            duration_hours=self.duration_hours,
            authorized_by=self.authorized_by.copy(),
            authorized_at=self.authorized_at,
            justification_document=self.justification_document,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "override_id": str(self.override_id),
            "reason": self.reason.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EmergencyOverride:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_still_valid(self) -> bool:
        expiry = self.authorized_at.replace(tzinfo=UTC) + timedelta(hours=self.duration_hours)
        return datetime.now(UTC) < expiry

    def _copy(self) -> EmergencyOverride:
        return EmergencyOverride(
            override_id=self.override_id,
            reason=self.reason,
            suspended_principles=self.suspended_principles.copy(),
            duration_hours=self.duration_hours,
            authorized_by=self.authorized_by.copy(),
            authorized_at=self.authorized_at,
            justification_document=self.justification_document,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class ViolationRecord:
    violation_id: UUID
    rule_id: UUID
    principle: ConstitutionalPrinciple
    severity: ConstitutionalSeverity
    offending_module: str
    message: str
    timestamp: datetime
    offending_user: str | None = None
    offending_command_id: UUID | None = None
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution_action: str | None = None
    version: int = 1

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", self.offending_module, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")
        if self.timestamp.tzinfo is None:
            object.__setattr__(self, "timestamp", self.timestamp.replace(tzinfo=UTC))

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "violation_id": str(self.violation_id),
                "severity": self.severity.name,
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
                "version": self.version,
                "violation_id": str(self.violation_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> ViolationRecord:
        return self

    def update(self, updated_by: str, **kwargs) -> ViolationRecord:
        raise AttributeError("ViolationRecord is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ViolationRecord:
        raise AttributeError("Cannot delete violation record")

    def restore(self, restored_by: str) -> ViolationRecord:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> ViolationRecord:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ViolationRecord:
        return self

    def lock(self, locked_by: str, reason: str) -> ViolationRecord:
        return self

    def unlock(self, unlocked_by: str) -> ViolationRecord:
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
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "rule_id": str(self.rule_id),
            "principle": self.principle.name,
            "severity": self.severity.name,
            "offending_module": self.offending_module,
            "offending_user": self.offending_user,
            "offending_command_id": str(self.offending_command_id)
            if self.offending_command_id
            else None,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged_by": self.acknowledged_by,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_action": self.resolution_action,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ViolationRecord:
        return cls(
            violation_id=UUID(data["violation_id"]),
            rule_id=UUID(data["rule_id"]),
            principle=ConstitutionalPrinciple[data["principle"]],
            severity=ConstitutionalSeverity[data["severity"]],
            offending_module=data["offending_module"],
            offending_user=data.get("offending_user"),
            offending_command_id=UUID(data["offending_command_id"])
            if data.get("offending_command_id")
            else None,
            message=data["message"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            acknowledged_by=data.get("acknowledged_by"),
            acknowledged_at=datetime.fromisoformat(data["acknowledged_at"])
            if data.get("acknowledged_at")
            else None,
            resolved_by=data.get("resolved_by"),
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolution_action=data.get("resolution_action"),
            version=data.get("version", 1),
        )

    def clone(self) -> ViolationRecord:
        new_id = uuid4()
        return ViolationRecord(
            violation_id=new_id,
            rule_id=self.rule_id,
            principle=self.principle,
            severity=self.severity,
            offending_module=self.offending_module,
            offending_user=self.offending_user,
            offending_command_id=self.offending_command_id,
            message=self.message,
            timestamp=self.timestamp,
            acknowledged_by=self.acknowledged_by,
            acknowledged_at=self.acknowledged_at,
            resolved_by=self.resolved_by,
            resolved_at=self.resolved_at,
            resolution_action=self.resolution_action,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ViolationRecord:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    def acknowledge(self, by: str) -> ViolationRecord:
        if self.acknowledged_at is not None:
            raise ValueError("Already acknowledged")
        new_record = self._copy()
        new_record.acknowledged_by = by
        new_record.acknowledged_at = datetime.now(UTC)
        new_record.version = self.version + 1
        new_record._record_audit("ACKNOWLEDGE", by, {})
        return new_record

    def resolve(self, by: str, action: str) -> ViolationRecord:
        if self.resolved_at is not None:
            raise ValueError("Already resolved")
        new_record = self._copy()
        new_record.resolved_by = by
        new_record.resolved_at = datetime.now(UTC)
        new_record.resolution_action = action
        new_record.version = self.version + 1
        new_record._record_audit("RESOLVE", by, {"action": action})
        return new_record

    def _copy(self) -> ViolationRecord:
        return ViolationRecord(
            violation_id=self.violation_id,
            rule_id=self.rule_id,
            principle=self.principle,
            severity=self.severity,
            offending_module=self.offending_module,
            offending_user=self.offending_user,
            offending_command_id=self.offending_command_id,
            message=self.message,
            timestamp=self.timestamp,
            acknowledged_by=self.acknowledged_by,
            acknowledged_at=self.acknowledged_at,
            resolved_by=self.resolved_by,
            resolved_at=self.resolved_at,
            resolution_action=self.resolution_action,
            version=self.version,
        )


@dataclass(kw_only=True)
class ConstitutionalSnapshot:
    snapshot_id: UUID
    effective_as_of: datetime
    active_rules: list[ConstitutionalRule]
    active_overrides: list[EmergencyOverride]
    version: str
    hash_chain_previous: str | None
    version_number: int = 1
    hash_current: str = ""

    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._validate()
        if not self.hash_current:
            object.__setattr__(self, "hash_current", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.version_number < 1:
            raise ValueError("Version must be >= 1")
        if self.effective_as_of.tzinfo is None:
            object.__setattr__(self, "effective_as_of", self.effective_as_of.replace(tzinfo=UTC))

    def compute_hash(self) -> str:
        rules_hash = hashlib.sha3_256(
            "".join(str(r.rule_id) for r in self.active_rules).encode()
        ).hexdigest()
        overrides_hash = hashlib.sha3_256(
            "".join(str(o.override_id) for o in self.active_overrides).encode()
        ).hexdigest()
        content = f"{self.snapshot_id}|{self.effective_as_of.isoformat()}|{rules_hash}|{overrides_hash}|{self.version}|{self.hash_chain_previous or ''}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version_number,
                "snapshot_id": str(self.snapshot_id),
                "hash": self.hash_current[:16] + "...",
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
                "snapshot_id": str(self.snapshot_id),
                "details": details,
            }
        )

    def create(self, created_by: str) -> ConstitutionalSnapshot:
        return self

    def update(self, updated_by: str, **kwargs) -> ConstitutionalSnapshot:
        raise AttributeError("ConstitutionalSnapshot is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> ConstitutionalSnapshot:
        raise AttributeError("Cannot delete snapshot")

    def restore(self, restored_by: str) -> ConstitutionalSnapshot:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> ConstitutionalSnapshot:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ConstitutionalSnapshot:
        return self

    def lock(self, locked_by: str, reason: str) -> ConstitutionalSnapshot:
        return self

    def unlock(self, unlocked_by: str) -> ConstitutionalSnapshot:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
            if self.hash_current != self.compute_hash():
                errors.append("Hash mismatch")
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "snapshot_id": str(self.snapshot_id),
            "version": self.version_number,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "effective_as_of": self.effective_as_of.isoformat(),
            "active_rules_count": len(self.active_rules),
            "active_overrides_count": len(self.active_overrides),
            "version": self.version,
            "hash_chain_previous": self.hash_chain_previous[:16] + "..."
            if self.hash_chain_previous
            else None,
            "hash_current": self.hash_current[:16] + "...",
            "version_number": self.version_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstitutionalSnapshot:
        return cls(
            snapshot_id=UUID(data["snapshot_id"]),
            effective_as_of=datetime.fromisoformat(data["effective_as_of"]),
            active_rules=[ConstitutionalRule.from_dict(r) for r in data.get("active_rules", [])],
            active_overrides=[
                EmergencyOverride.from_dict(o) for o in data.get("active_overrides", [])
            ],
            version=data["version"],
            hash_chain_previous=data.get("hash_chain_previous"),
            hash_current=data.get("hash_current", ""),
            version_number=data.get("version_number", 1),
        )

    def clone(self) -> ConstitutionalSnapshot:
        new_id = uuid4()
        return ConstitutionalSnapshot(
            snapshot_id=new_id,
            effective_as_of=self.effective_as_of,
            active_rules=[r.clone() for r in self.active_rules],
            active_overrides=[o.clone() for o in self.active_overrides],
            version=self.version,
            hash_chain_previous=self.hash_current,
            version_number=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version_number,
            "snapshot_id": str(self.snapshot_id),
            "hash": self.hash_current[:16] + "...",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ConstitutionalSnapshot:
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 4. CONSTITUTION AGGREGATE ===


@dataclass
class Constitution:
    version: str
    rules: dict[UUID, ConstitutionalRule] = field(default_factory=dict)
    amendments: list[AmendmentRecord] = field(default_factory=list)
    overrides: list[EmergencyOverride] = field(default_factory=list)
    violations: list[ViolationRecord] = field(default_factory=list)
    snapshots: list[ConstitutionalSnapshot] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.rules:
            self._load_default_rules()

    def _load_default_rules(self) -> None:
        now = datetime.now(UTC)
        default_rules_data = [
            (
                ConstitutionalPrinciple.DOUBLE_ENTRY,
                SovereigntyLevel.ABSOLUTE,
                "Every transaction must have equal debit and credit totals. The accounting equation (Assets = Liabilities + Equity) must always hold.",
                ConstitutionalSeverity.CRITICAL,
            ),
            (
                ConstitutionalPrinciple.IMMUTABILITY,
                SovereigntyLevel.ABSOLUTE,
                "Once a journal entry is posted, it cannot be modified, deleted, or altered. Corrections must be made via reversal or amendment entries.",
                ConstitutionalSeverity.CRITICAL,
            ),
        ]
        for principle, sovereignty, statement, severity in default_rules_data:
            temp_rule = ConstitutionalRule(
                rule_id=uuid4(),
                principle=principle,
                statement=statement,
                sovereignty=sovereignty,
                severity_on_violation=severity,
                effective_from=now,
                effective_until=None,
                created_by="system_bootstrap",
                created_at=now,
                approved_by=["system_bootstrap", "audit_committee_founder", "ceo_founder"]
                if sovereignty == SovereigntyLevel.ABSOLUTE
                else ["system_bootstrap", "audit_committee_founder"],
                cryptographic_hash="",
            )
            self.rules[temp_rule.rule_id] = temp_rule
            self.rules[temp_rule.rule_id] = temp_rule.update(
                "system", cryptographic_hash=temp_rule.compute_hash()
            )
        self._create_snapshot()

    # Repository methods
    def save_rule(self, rule: ConstitutionalRule) -> None:
        with self._lock:
            self.rules[rule.rule_id] = rule

    def get_rule(self, rule_id: UUID) -> ConstitutionalRule | None:
        return self.rules.get(rule_id)

    def get_all_rules(self) -> list[ConstitutionalRule]:
        return list(self.rules.values())

    def delete_rule(self, rule_id: UUID) -> bool:
        with self._lock:
            if rule_id in self.rules:
                del self.rules[rule_id]
                return True
            return False

    def save_amendment(self, amendment: AmendmentRecord) -> None:
        with self._lock:
            self.amendments.append(amendment)

    def get_amendments(self, limit: int = 100) -> list[AmendmentRecord]:
        return self.amendments[-limit:]

    def delete_amendment(self, amendment_id: UUID) -> bool:
        with self._lock:
            for i, a in enumerate(self.amendments):
                if a.amendment_id == amendment_id:
                    self.amendments.pop(i)
                    return True
            return False

    def save_override(self, override: EmergencyOverride) -> None:
        with self._lock:
            self.overrides.append(override)

    def get_overrides(self, only_valid: bool = True) -> list[EmergencyOverride]:
        result = self.overrides
        if only_valid:
            result = [o for o in result if o.is_still_valid()]
        return result

    def delete_override(self, override_id: UUID) -> bool:
        with self._lock:
            for i, o in enumerate(self.overrides):
                if o.override_id == override_id:
                    self.overrides.pop(i)
                    return True
            return False

    def save_violation(self, violation: ViolationRecord) -> None:
        with self._lock:
            self.violations.append(violation)

    def get_violations(
        self,
        limit: int = 100,
        principle: ConstitutionalPrinciple | None = None,
        resolved_only: bool = False,
        unresolved_only: bool = False,
    ) -> list[ViolationRecord]:
        result = self.violations[-limit:]
        if principle:
            result = [v for v in result if v.principle == principle]
        if resolved_only:
            result = [v for v in result if v.is_resolved()]
        if unresolved_only:
            result = [v for v in result if not v.is_resolved()]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> ViolationRecord | None:
        with self._lock:
            for i, v in enumerate(self.violations):
                if v.violation_id == violation_id and not v.is_resolved():
                    resolved = v.resolve(resolved_by, resolution_action)
                    self.violations[i] = resolved
                    return resolved
            return None

    def save_snapshot(self, snapshot: ConstitutionalSnapshot) -> None:
        with self._lock:
            self.snapshots.append(snapshot)

    def get_snapshots(self, limit: int = 100) -> list[ConstitutionalSnapshot]:
        return self.snapshots[-limit:]

    # Business methods
    def add_rule(self, rule: ConstitutionalRule, authorizer: str) -> None:
        with self._lock:
            for existing in self.rules.values():
                if existing.principle == rule.principle and existing.is_active():
                    raise ConstitutionAmendmentError(
                        f"Rule for principle {rule.principle.name} already exists"
                    )
            if rule.sovereignty == SovereigntyLevel.ABSOLUTE and len(rule.approved_by) < 3:
                raise ConstitutionAmendmentError(
                    "Absolute sovereignty rule requires at least 3 approvers"
                )
            self.rules[rule.rule_id] = rule
            self._create_amendment(
                f"Added rule for principle {rule.principle.name}", authorizer, rule.approved_by
            )
            self._create_snapshot()

    def modify_rule(self, rule_id: UUID, new_rule: ConstitutionalRule, modified_by: str) -> None:
        with self._lock:
            if rule_id not in self.rules:
                raise ConstitutionAmendmentError(f"Rule {rule_id} not found")
            old_rule = self.rules[rule_id]
            # Mark old rule as inactive
            inactive_rule = old_rule.update(modified_by, effective_until=datetime.now(UTC))
            self.rules[rule_id] = inactive_rule
            # Add new rule (will check active principle)
            self.add_rule(new_rule, modified_by)

    def get_active_rules(self, at_date: datetime | None = None) -> list[ConstitutionalRule]:
        check = at_date or datetime.now(UTC)
        active = [r for r in self.rules.values() if r.is_active(check)]
        for override in self.overrides:
            if override.is_still_valid():
                active = [r for r in active if r.principle not in override.suspended_principles]
        return active

    def check_violation(
        self,
        principle: ConstitutionalPrinciple,
        offending_module: str,
        message: str,
        offending_user: str | None = None,
        offending_command_id: UUID | None = None,
    ) -> ViolationRecord:
        rule = next(
            (r for r in self.rules.values() if r.principle == principle and r.is_active()), None
        )
        severity = rule.severity_on_violation if rule else ConstitutionalSeverity.HIGH
        violation = ViolationRecord(
            violation_id=uuid4(),
            rule_id=rule.rule_id if rule else UUID(int=0),
            principle=principle,
            severity=severity,
            offending_module=offending_module,
            offending_user=offending_user,
            offending_command_id=offending_command_id,
            message=message,
            timestamp=datetime.now(UTC),
        )
        self.save_violation(violation)
        if severity == ConstitutionalSeverity.CRITICAL:
            raise ConstitutionalViolationError(
                principle, message, severity, offending_module, violation.violation_id
            )
        return violation

    def apply_emergency_override(
        self,
        reason: EmergencyOverrideReason,
        suspended_principles: set[ConstitutionalPrinciple],
        duration_hours: int,
        authorized_by: list[str],
        justification_document: str,
    ) -> EmergencyOverride:
        if duration_hours > 72:
            raise EmergencyOverrideError("Emergency override cannot exceed 72 hours")
        if len(authorized_by) < 2:
            raise EmergencyOverrideError("Emergency override requires at least 2 authorizers")
        absolute_principles = {
            p
            for p in suspended_principles
            if any(
                r.principle == p and r.sovereignty == SovereigntyLevel.ABSOLUTE
                for r in self.rules.values()
            )
        }
        if absolute_principles:
            raise EmergencyOverrideError(
                f"Cannot suspend absolute principles: {[p.name for p in absolute_principles]}"
            )
        override = EmergencyOverride(
            override_id=uuid4(),
            reason=reason,
            suspended_principles=suspended_principles,
            duration_hours=duration_hours,
            authorized_by=authorized_by,
            authorized_at=datetime.now(UTC),
            justification_document=justification_document,
            cryptographic_hash="",
        )
        self.save_override(override)
        self._create_snapshot()
        return override

    def get_snapshot(self, as_of: datetime) -> ConstitutionalSnapshot:
        active_rules = self.get_active_rules(as_of)
        active_overrides = [
            o for o in self.overrides if o.authorized_at <= as_of and o.is_still_valid()
        ]
        previous_hash = self.snapshots[-1].hash_current if self.snapshots else None
        snapshot = ConstitutionalSnapshot(
            snapshot_id=uuid4(),
            effective_as_of=as_of,
            active_rules=active_rules,
            active_overrides=active_overrides,
            version=self.version,
            hash_chain_previous=previous_hash,
            hash_current="",
        )
        self.save_snapshot(snapshot)
        return snapshot

    def _create_amendment(
        self, changes_description: str, proposed_by: str, approved_by: list[str]
    ) -> AmendmentRecord:
        amendment = AmendmentRecord(
            amendment_id=uuid4(),
            previous_version_id=UUID(int=0),
            new_version_id=uuid4(),
            changes_description=changes_description,
            proposed_by=proposed_by,
            proposed_at=datetime.now(UTC),
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            effective_from=datetime.now(UTC),
            cryptographic_signature="",
            justification=changes_description,
            impact_assessment="Pending",
        )
        self.save_amendment(amendment)
        return amendment

    def _create_snapshot(self) -> None:
        self.get_snapshot(datetime.now(UTC))

    def verify_integrity(self) -> dict[str, Any]:
        snapshots = self.snapshots
        if len(snapshots) <= 1:
            return {"is_valid": True, "message": "Only one snapshot, chain is trivial"}
        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]
            curr = snapshots[i]
            if curr.hash_chain_previous != prev.hash_current:
                return {
                    "is_valid": False,
                    "broken_at_index": i,
                    "expected": prev.hash_current,
                    "actual": curr.hash_chain_previous,
                }
        return {"is_valid": True, "snapshot_count": len(snapshots)}

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_rules = len(self.rules)
            active_rules = len([r for r in self.rules.values() if r.is_active()])
            total_amendments = len(self.amendments)
            total_overrides = len(self.overrides)
            total_violations = len(self.violations)
            unresolved = len([v for v in self.violations if not v.is_resolved()])
            by_severity = {
                sev.name: len([v for v in self.violations if v.severity == sev])
                for sev in ConstitutionalSeverity
            }
            by_principle = {
                p.name: len([v for v in self.violations if v.principle == p])
                for p in ConstitutionalPrinciple
            }
            return {
                "total_rules": total_rules,
                "active_rules": active_rules,
                "total_amendments": total_amendments,
                "total_overrides": total_overrides,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "by_severity": by_severity,
                "by_principle": by_principle,
                "snapshot_count": len(self.snapshots),
            }

    def reset(self) -> None:
        with self._lock:
            self.rules = {}
            self.amendments = []
            self.overrides = []
            self.violations = []
            self.snapshots = []
            self._load_default_rules()


# === 5. SUPREME LAW SERVICE ===


class SupremeLaw:
    _instance: SupremeLaw | None = None
    _lock = threading.Lock()

    def __new__(cls) -> SupremeLaw:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._constitution = Constitution(version="1.0.0")

    # Repository methods (delegasi)
    def save_rule(self, rule: ConstitutionalRule) -> None:
        self._constitution.save_rule(rule)

    def get_rule(self, rule_id: UUID) -> ConstitutionalRule | None:
        return self._constitution.get_rule(rule_id)

    def get_all_rules(self) -> list[ConstitutionalRule]:
        return self._constitution.get_all_rules()

    def delete_rule(self, rule_id: UUID) -> bool:
        return self._constitution.delete_rule(rule_id)

    def save_amendment(self, amendment: AmendmentRecord) -> None:
        self._constitution.save_amendment(amendment)

    def get_amendments(self, limit: int = 100) -> list[AmendmentRecord]:
        return self._constitution.get_amendments(limit)

    def delete_amendment(self, amendment_id: UUID) -> bool:
        return self._constitution.delete_amendment(amendment_id)

    def save_override(self, override: EmergencyOverride) -> None:
        self._constitution.save_override(override)

    def get_overrides(self, only_valid: bool = True) -> list[EmergencyOverride]:
        return self._constitution.get_overrides(only_valid)

    def delete_override(self, override_id: UUID) -> bool:
        return self._constitution.delete_override(override_id)

    def save_violation(self, violation: ViolationRecord) -> None:
        self._constitution.save_violation(violation)

    def get_violations(
        self,
        limit: int = 100,
        principle: ConstitutionalPrinciple | None = None,
        resolved_only: bool = False,
        unresolved_only: bool = False,
    ) -> list[ViolationRecord]:
        return self._constitution.get_violations(limit, principle, resolved_only, unresolved_only)

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> ViolationRecord | None:
        return self._constitution.resolve_violation(violation_id, resolved_by, resolution_action)

    def save_snapshot(self, snapshot: ConstitutionalSnapshot) -> None:
        self._constitution.save_snapshot(snapshot)

    def get_snapshots(self, limit: int = 100) -> list[ConstitutionalSnapshot]:
        return self._constitution.get_snapshots(limit)

    # Business methods
    def enforce(
        self, principle: ConstitutionalPrinciple, context: dict[str, Any], module: str
    ) -> bool:
        active_rules = self._constitution.get_active_rules()
        applicable = [r for r in active_rules if r.principle == principle]
        if not applicable:
            return True
        if principle == ConstitutionalPrinciple.DOUBLE_ENTRY:
            debit = context.get("total_debit", 0)
            credit = context.get("total_credit", 0)
            if abs(debit - credit) > 1e-10:
                self.check_violation(
                    principle,
                    module,
                    f"Debit ({debit}) does not equal Credit ({credit})",
                    context.get("user_id"),
                    context.get("command_id"),
                )
                return False
        return True

    def check_violation(
        self,
        principle: ConstitutionalPrinciple,
        offending_module: str,
        message: str,
        offending_user: str | None = None,
        offending_command_id: UUID | None = None,
    ) -> ViolationRecord:
        return self._constitution.check_violation(
            principle, offending_module, message, offending_user, offending_command_id
        )

    def emergency_override(
        self,
        reason: EmergencyOverrideReason,
        suspended_principles: set[ConstitutionalPrinciple],
        duration_hours: int,
        authorized_by: list[str],
        justification_document: str,
    ) -> EmergencyOverride:
        return self._constitution.apply_emergency_override(
            reason, suspended_principles, duration_hours, authorized_by, justification_document
        )

    def get_active_principles(self) -> list[ConstitutionalPrinciple]:
        rules = self._constitution.get_active_rules()
        return list({r.principle for r in rules})

    def get_constitution_snapshot(self, as_of: datetime | None = None) -> ConstitutionalSnapshot:
        as_of = as_of or datetime.now(UTC)
        return self._constitution.get_snapshot(as_of)

    def verify_integrity(self) -> dict[str, Any]:
        return self._constitution.verify_integrity()

    def add_rule(self, rule: ConstitutionalRule, authorizer: str) -> None:
        self._constitution.add_rule(rule, authorizer)

    def get_statistics(self) -> dict[str, Any]:
        return self._constitution.get_statistics()

    @property
    def constitution(self) -> Constitution:
        return self._constitution

    def reset(self) -> None:
        self._constitution.reset()


# === 6. SINGLETON ACCESSOR ===

_supreme_law_instance: SupremeLaw | None = None


def get_supreme_law() -> SupremeLaw:
    global _supreme_law_instance
    if _supreme_law_instance is None:
        _supreme_law_instance = SupremeLaw()
    return _supreme_law_instance


__all__ = [
    "AmendmentRecord",
    "Constitution",
    "ConstitutionAmendmentError",
    "ConstitutionalPrinciple",
    "ConstitutionalRule",
    "ConstitutionalSeverity",
    "ConstitutionalSnapshot",
    "ConstitutionalViolationError",
    "EmergencyOverride",
    "EmergencyOverrideError",
    "EmergencyOverrideReason",
    "SovereigntyLevel",
    "SovereigntyViolationError",
    "SupremeLaw",
    "ViolationRecord",
    "get_supreme_law",
]
