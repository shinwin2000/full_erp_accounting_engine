#!/usr/bin/env python3
"""
Module: materiality.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: informasi material wajib diungkapkan.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalSeverity,
    get_supreme_law,
)

logger = logging.getLogger(__name__)


# === 1. ENUMS ===


class MaterialityDimension(Enum):
    QUANTITATIVE = auto()
    QUALITATIVE = auto()
    BOTH = auto()


class MaterialityThresholdType(Enum):
    ABSOLUTE = auto()
    PERCENTAGE_OF_ASSETS = auto()
    PERCENTAGE_OF_EQUITY = auto()
    PERCENTAGE_OF_REVENUE = auto()
    PERCENTAGE_OF_PROFIT = auto()
    CUSTOM = auto()


class MaterialitySeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class QualitativeMaterialityFactor(Enum):
    FRAUD_OR_ILLEGAL_ACT = auto()
    REGULATORY_COMPLIANCE = auto()
    DEBT_COVENANT_VIOLATION = auto()
    TREND_REVERSAL = auto()
    SEGMENT_REPORTING = auto()
    RELATED_PARTY = auto()
    EXECUTIVE_COMPENSATION = auto()
    PUBLIC_PERCEPTION = auto()
    GOING_CONCERN = auto()
    ROLLOVER_EFFECT = auto()


# === 2. EXCEPTIONS ===


class MaterialityError(Exception):
    pass


class MaterialityViolationError(Exception):
    def __init__(
        self,
        message: str,
        legal_entity_id: UUID,
        fiscal_year: int,
        item_amount: Decimal,
        threshold: Decimal,
        severity: MaterialitySeverity,
    ):
        self.legal_entity_id = legal_entity_id
        self.fiscal_year = fiscal_year
        self.item_amount = item_amount
        self.threshold = threshold
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | Entity: {legal_entity_id}, FY: {fiscal_year}, Amount: {item_amount}, Threshold: {threshold}"
        )


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class MaterialityThreshold:
    threshold_id: UUID
    legal_entity_id: UUID
    fiscal_year: int
    threshold_type: MaterialityThresholdType
    value: Decimal
    reference_value: Decimal | None = None
    percentage: Decimal | None = None
    description: str = ""
    approved_by: list[str] = field(default_factory=list)
    effective_date: datetime = field(default_factory=lambda: datetime.now(UTC))
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if self.value <= 0:
            raise ValueError("Threshold value must be positive")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.threshold_id}|{self.legal_entity_id}|{self.fiscal_year}|{self.threshold_type.value}|{self.value}|{self.percentage or ''}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "threshold_id": str(self.threshold_id),
                "value": str(self.value),
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
                "threshold_id": str(self.threshold_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MaterialityThreshold:
        return self

    def update(self, updated_by: str, **kwargs) -> MaterialityThreshold:
        new_th = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_th, key) and key not in (
                "threshold_id",
                "legal_entity_id",
                "fiscal_year",
                "version",
            ):
                setattr(new_th, key, value)
        new_th.version = self.version + 1
        new_th._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_th

    def delete(self, deleted_by: str, reason: str | None = None) -> MaterialityThreshold:
        new_th = self._copy()
        new_th.deleted_at = datetime.now(UTC)
        new_th.deleted_by = deleted_by
        new_th.version = self.version + 1
        new_th._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_th

    def restore(self, restored_by: str) -> MaterialityThreshold:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_th = self._copy()
        new_th.deleted_at = None
        new_th.deleted_by = None
        new_th.version = self.version + 1
        new_th._record_audit("RESTORE", restored_by, {})
        return new_th

    def activate(self, activated_by: str) -> MaterialityThreshold:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MaterialityThreshold:
        return self

    def lock(self, locked_by: str, reason: str) -> MaterialityThreshold:
        return self

    def unlock(self, unlocked_by: str) -> MaterialityThreshold:
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
            "threshold_id": str(self.threshold_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold_id": str(self.threshold_id),
            "legal_entity_id": str(self.legal_entity_id),
            "fiscal_year": self.fiscal_year,
            "threshold_type": self.threshold_type.name,
            "value": str(self.value),
            "reference_value": str(self.reference_value) if self.reference_value else None,
            "percentage": str(self.percentage) if self.percentage else None,
            "description": self.description,
            "approved_by": self.approved_by,
            "effective_date": self.effective_date.isoformat(),
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialityThreshold:
        return cls(
            threshold_id=UUID(data["threshold_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            fiscal_year=data["fiscal_year"],
            threshold_type=MaterialityThresholdType[data["threshold_type"]],
            value=Decimal(data["value"]),
            reference_value=Decimal(data["reference_value"])
            if data.get("reference_value")
            else None,
            percentage=Decimal(data["percentage"]) if data.get("percentage") else None,
            description=data.get("description", ""),
            approved_by=data.get("approved_by", []),
            effective_date=datetime.fromisoformat(data["effective_date"]),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> MaterialityThreshold:
        new_id = uuid4()
        return MaterialityThreshold(
            threshold_id=new_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            threshold_type=self.threshold_type,
            value=self.value,
            reference_value=self.reference_value,
            percentage=self.percentage,
            description=f"Clone of {self.threshold_id}",
            approved_by=self.approved_by.copy(),
            effective_date=datetime.now(UTC),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "threshold_id": str(self.threshold_id),
            "value": str(self.value),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MaterialityThreshold:
        new_th = self._copy()
        new_th.version = self.version + 1
        new_th._record_audit("TOUCH", touched_by, {})
        return new_th

    def get_absolute_threshold(self) -> Decimal:
        if self.threshold_type == MaterialityThresholdType.ABSOLUTE:
            return self.value
        elif self.percentage is not None and self.reference_value is not None:
            return self.reference_value * self.percentage / Decimal(100)
        return self.value

    def is_material(self, amount: Decimal) -> bool:
        return abs(amount) >= self.get_absolute_threshold()

    def _copy(self) -> MaterialityThreshold:
        return MaterialityThreshold(
            threshold_id=self.threshold_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            threshold_type=self.threshold_type,
            value=self.value,
            reference_value=self.reference_value,
            percentage=self.percentage,
            description=self.description,
            approved_by=self.approved_by.copy(),
            effective_date=self.effective_date,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class MaterialityJudgment:
    judgment_id: UUID
    legal_entity_id: UUID
    fiscal_year: int
    item_description: str
    item_amount: Decimal
    threshold_applied: Decimal
    is_material: bool
    qualitative_factors: list[str]
    justification: str
    decided_by: str
    decided_at: datetime
    approved_by: list[str]
    referenced_standard: str
    cryptographic_hash: str = ""
    version: int = 1
    deleted_at: datetime | None = None
    deleted_by: str | None = None

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.decided_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.judgment_id}|{self.legal_entity_id}|{self.fiscal_year}|{self.item_amount}|{self.is_material}|{self.justification[:100]}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "judgment_id": str(self.judgment_id),
                "is_material": self.is_material,
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
                "judgment_id": str(self.judgment_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MaterialityJudgment:
        return self

    def update(self, updated_by: str, **kwargs) -> MaterialityJudgment:
        raise AttributeError("MaterialityJudgment is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> MaterialityJudgment:
        new_jud = self._copy()
        new_jud.deleted_at = datetime.now(UTC)
        new_jud.deleted_by = deleted_by
        new_jud.version = self.version + 1
        new_jud._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_jud

    def restore(self, restored_by: str) -> MaterialityJudgment:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_jud = self._copy()
        new_jud.deleted_at = None
        new_jud.deleted_by = None
        new_jud.version = self.version + 1
        new_jud._record_audit("RESTORE", restored_by, {})
        return new_jud

    def activate(self, activated_by: str) -> MaterialityJudgment:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MaterialityJudgment:
        return self

    def lock(self, locked_by: str, reason: str) -> MaterialityJudgment:
        return self

    def unlock(self, unlocked_by: str) -> MaterialityJudgment:
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
            "judgment_id": str(self.judgment_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "judgment_id": str(self.judgment_id),
            "legal_entity_id": str(self.legal_entity_id),
            "fiscal_year": self.fiscal_year,
            "item_description": self.item_description,
            "item_amount": str(self.item_amount),
            "threshold_applied": str(self.threshold_applied),
            "is_material": self.is_material,
            "qualitative_factors": self.qualitative_factors,
            "justification": self.justification,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at.isoformat(),
            "approved_by": self.approved_by,
            "referenced_standard": self.referenced_standard,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialityJudgment:
        return cls(
            judgment_id=UUID(data["judgment_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            fiscal_year=data["fiscal_year"],
            item_description=data["item_description"],
            item_amount=Decimal(data["item_amount"]),
            threshold_applied=Decimal(data["threshold_applied"]),
            is_material=data["is_material"],
            qualitative_factors=data.get("qualitative_factors", []),
            justification=data["justification"],
            decided_by=data["decided_by"],
            decided_at=datetime.fromisoformat(data["decided_at"]),
            approved_by=data.get("approved_by", []),
            referenced_standard=data.get("referenced_standard", "PSAK 1 / IFRS"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> MaterialityJudgment:
        new_id = uuid4()
        return MaterialityJudgment(
            judgment_id=new_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            item_description=self.item_description,
            item_amount=self.item_amount,
            threshold_applied=self.threshold_applied,
            is_material=self.is_material,
            qualitative_factors=self.qualitative_factors.copy(),
            justification=self.justification,
            decided_by=self.decided_by,
            decided_at=datetime.now(UTC),
            approved_by=self.approved_by.copy(),
            referenced_standard=self.referenced_standard,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "judgment_id": str(self.judgment_id),
            "is_material": self.is_material,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MaterialityJudgment:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def _copy(self) -> MaterialityJudgment:
        return MaterialityJudgment(
            judgment_id=self.judgment_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            item_description=self.item_description,
            item_amount=self.item_amount,
            threshold_applied=self.threshold_applied,
            is_material=self.is_material,
            qualitative_factors=self.qualitative_factors.copy(),
            justification=self.justification,
            decided_by=self.decided_by,
            decided_at=self.decided_at,
            approved_by=self.approved_by.copy(),
            referenced_standard=self.referenced_standard,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class MaterialityViolation:
    violation_id: UUID
    legal_entity_id: UUID
    fiscal_year: int
    item_amount: Decimal
    threshold_that_should_apply: Decimal
    failure_type: str
    severity: MaterialitySeverity
    message: str
    detected_at: datetime
    detected_by: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    corrective_action: str | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.detected_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.violation_id}|{self.legal_entity_id}|{self.fiscal_year}|{self.failure_type}|{self.severity.value}"
        return hashlib.sha3_256(content.encode()).hexdigest()

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

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MaterialityViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> MaterialityViolation:
        raise AttributeError("MaterialityViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> MaterialityViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> MaterialityViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> MaterialityViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MaterialityViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> MaterialityViolation:
        return self

    def unlock(self, unlocked_by: str) -> MaterialityViolation:
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
            "violation_id": str(self.violation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": str(self.violation_id),
            "legal_entity_id": str(self.legal_entity_id),
            "fiscal_year": self.fiscal_year,
            "item_amount": str(self.item_amount),
            "threshold_that_should_apply": str(self.threshold_that_should_apply),
            "failure_type": self.failure_type,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "corrective_action": self.corrective_action,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialityViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            fiscal_year=data["fiscal_year"],
            item_amount=Decimal(data["item_amount"]),
            threshold_that_should_apply=Decimal(data["threshold_that_should_apply"]),
            failure_type=data["failure_type"],
            severity=MaterialitySeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            corrective_action=data.get("corrective_action"),
            version=data.get("version", 1),
        )

    def clone(self) -> MaterialityViolation:
        new_id = uuid4()
        return MaterialityViolation(
            violation_id=new_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            item_amount=self.item_amount,
            threshold_that_should_apply=self.threshold_that_should_apply,
            failure_type=self.failure_type,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            corrective_action=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MaterialityViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, action: str) -> MaterialityViolation:
        if self.resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.corrective_action = action
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {"action": action})
        return new_violation

    def _copy(self) -> MaterialityViolation:
        return MaterialityViolation(
            violation_id=self.violation_id,
            legal_entity_id=self.legal_entity_id,
            fiscal_year=self.fiscal_year,
            item_amount=self.item_amount,
            threshold_that_should_apply=self.threshold_that_should_apply,
            failure_type=self.failure_type,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            corrective_action=self.corrective_action,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class MaterialityValidator:
    DEFAULT_THRESHOLD_PERCENTAGE = Decimal("5")

    @classmethod
    def validate_disclosure(
        cls,
        legal_entity_id: UUID,
        fiscal_year: int,
        item_amount: Decimal,
        item_description: str,
        threshold: MaterialityThreshold,
        qualitative_factors: list[QualitativeMaterialityFactor],
        was_disclosed_separately: bool,
    ) -> tuple[bool, MaterialityViolation | None]:
        threshold_value = threshold.get_absolute_threshold()
        is_quantitatively_material = abs(item_amount) >= threshold_value
        is_qualitatively_material = len(qualitative_factors) > 0
        is_material = is_quantitatively_material or is_qualitatively_material
        if is_material and not was_disclosed_separately:
            severity = cls._determine_severity(item_amount, threshold_value, qualitative_factors)
            violation = cls._create_violation(
                legal_entity_id,
                fiscal_year,
                item_amount,
                threshold_value,
                "NON_DISCLOSURE",
                severity,
                f"Item '{item_description}' of amount {item_amount} exceeds threshold {threshold_value} and/or has qualitative factors but not disclosed",
                "validator",
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation
        return True, None

    @classmethod
    def _determine_severity(
        cls,
        amount: Decimal,
        threshold: Decimal,
        qualitative_factors: list[QualitativeMaterialityFactor],
    ) -> MaterialitySeverity:
        if any(
            f in qualitative_factors
            for f in [
                QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT,
                QualitativeMaterialityFactor.REGULATORY_COMPLIANCE,
                QualitativeMaterialityFactor.GOING_CONCERN,
            ]
        ):
            return MaterialitySeverity.CATASTROPHIC
        if amount > threshold * 2:
            return MaterialitySeverity.CRITICAL
        if amount > threshold or qualitative_factors:
            return MaterialitySeverity.HIGH
        return MaterialitySeverity.MEDIUM

    @classmethod
    def _create_violation(
        cls,
        legal_entity_id: UUID,
        fiscal_year: int,
        item_amount: Decimal,
        threshold: Decimal,
        failure_type: str,
        severity: MaterialitySeverity,
        message: str,
        detected_by: str,
    ) -> MaterialityViolation:
        return MaterialityViolation(
            violation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            item_amount=item_amount,
            threshold_that_should_apply=threshold,
            failure_type=failure_type,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            detected_by=detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            corrective_action=None,
        )

    @classmethod
    def _log_violation(cls, violation: MaterialityViolation) -> None:
        log_msg = f"[{violation.severity.name}] Materiality violation: {violation.message}"
        if violation.severity.value >= MaterialitySeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= MaterialitySeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: MaterialityViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                MaterialitySeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                MaterialitySeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                MaterialitySeverity.HIGH: ConstitutionalSeverity.HIGH,
                MaterialitySeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                MaterialitySeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.MATERIALITY,
                offending_module="materiality_validator",
                message=violation.message,
                offending_command_id=violation.legal_entity_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class MaterialityAxiom:
    _instance: MaterialityAxiom | None = None
    _thresholds: dict[tuple[UUID, int], MaterialityThreshold] = {}
    _judgments: list[MaterialityJudgment] = []
    _violations: list[MaterialityViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> MaterialityAxiom:
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
        self._thresholds = {}
        self._judgments = []
        self._violations = []

    # ==================== REPOSITORY METHODS ====================
    def save_threshold(self, threshold: MaterialityThreshold) -> None:
        with self._lock:
            self._thresholds[(threshold.legal_entity_id, threshold.fiscal_year)] = threshold

    def get_threshold(self, legal_entity_id: UUID, fiscal_year: int) -> MaterialityThreshold | None:
        return self._thresholds.get((legal_entity_id, fiscal_year))

    def get_all_thresholds(self) -> list[MaterialityThreshold]:
        return list(self._thresholds.values())

    def delete_threshold(self, legal_entity_id: UUID, fiscal_year: int) -> bool:
        with self._lock:
            key = (legal_entity_id, fiscal_year)
            if key in self._thresholds:
                del self._thresholds[key]
                return True
            return False

    def save_judgment(self, judgment: MaterialityJudgment) -> None:
        with self._lock:
            self._judgments.append(judgment)

    def get_judgments(
        self, legal_entity_id: UUID | None = None, fiscal_year: int | None = None, limit: int = 100
    ) -> list[MaterialityJudgment]:
        result = self._judgments[-limit:]
        if legal_entity_id:
            result = [j for j in result if j.legal_entity_id == legal_entity_id]
        if fiscal_year:
            result = [j for j in result if j.fiscal_year == fiscal_year]
        return result

    def delete_judgment(self, judgment_id: UUID) -> bool:
        with self._lock:
            for i, j in enumerate(self._judgments):
                if j.judgment_id == judgment_id:
                    self._judgments.pop(i)
                    return True
            return False

    def save_violation(self, violation: MaterialityViolation) -> None:
        with self._lock:
            self._violations.append(violation)

    def get_violations(
        self,
        legal_entity_id: UUID | None = None,
        fiscal_year: int | None = None,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> list[MaterialityViolation]:
        result = self._violations[-limit:]
        if legal_entity_id:
            result = [v for v in result if v.legal_entity_id == legal_entity_id]
        if fiscal_year:
            result = [v for v in result if v.fiscal_year == fiscal_year]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, corrective_action: str
    ) -> MaterialityViolation | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by, corrective_action)
                    self._violations[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def set_threshold(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        threshold_type: MaterialityThresholdType,
        value: Decimal,
        reference_value: Decimal | None = None,
        percentage: Decimal | None = None,
        description: str = "",
        approved_by: list[str] | None = None,
    ) -> MaterialityThreshold:
        threshold = MaterialityThreshold(
            threshold_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            threshold_type=threshold_type,
            value=value,
            reference_value=reference_value,
            percentage=percentage,
            description=description,
            approved_by=approved_by or [],
        )
        self.save_threshold(threshold)
        return threshold

    def get_or_create_default_threshold(
        self, legal_entity_id: UUID, fiscal_year: int, reference_profit: Decimal | None = None
    ) -> MaterialityThreshold:
        existing = self.get_threshold(legal_entity_id, fiscal_year)
        if existing:
            return existing
        if reference_profit and reference_profit > 0:
            value = reference_profit * Decimal("5") / Decimal("100")
            threshold_type = MaterialityThresholdType.PERCENTAGE_OF_PROFIT
            percentage = Decimal("5")
        else:
            value = Decimal("100000000")
            threshold_type = MaterialityThresholdType.ABSOLUTE
            percentage = None
        return self.set_threshold(
            legal_entity_id,
            fiscal_year,
            threshold_type,
            value,
            reference_value=reference_profit,
            percentage=percentage,
            description=f"Default threshold for FY{fiscal_year}",
        )

    def is_material(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        amount: Decimal,
        qualitative_factors: list[QualitativeMaterialityFactor] | None = None,
    ) -> bool:
        threshold = self.get_threshold(legal_entity_id, fiscal_year)
        if not threshold:
            threshold = self.get_or_create_default_threshold(legal_entity_id, fiscal_year)
        quantitative = threshold.is_material(amount)
        qualitative = qualitative_factors and len(qualitative_factors) > 0
        return quantitative or qualitative

    def record_judgment(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        item_description: str,
        item_amount: Decimal,
        threshold_applied: Decimal,
        is_material: bool,
        qualitative_factors: list[str],
        justification: str,
        decided_by: str,
        approved_by: list[str],
        referenced_standard: str = "PSAK 1 / IFRS",
    ) -> MaterialityJudgment:
        judgment = MaterialityJudgment(
            judgment_id=uuid4(),
            legal_entity_id=legal_entity_id,
            fiscal_year=fiscal_year,
            item_description=item_description,
            item_amount=item_amount,
            threshold_applied=threshold_applied,
            is_material=is_material,
            qualitative_factors=qualitative_factors,
            justification=justification,
            decided_by=decided_by,
            decided_at=datetime.now(UTC),
            approved_by=approved_by,
            referenced_standard=referenced_standard,
        )
        self.save_judgment(judgment)
        return judgment

    def enforce_disclosure(
        self,
        legal_entity_id: UUID,
        fiscal_year: int,
        item_amount: Decimal,
        item_description: str,
        was_disclosed_separately: bool,
        qualitative_factors: list[QualitativeMaterialityFactor] | None = None,
        raise_on_violation: bool = True,
    ) -> tuple[bool, MaterialityViolation | None]:
        threshold = self.get_threshold(legal_entity_id, fiscal_year)
        if not threshold:
            threshold = self.get_or_create_default_threshold(legal_entity_id, fiscal_year)
        is_valid, violation = MaterialityValidator.validate_disclosure(
            legal_entity_id,
            fiscal_year,
            item_amount,
            item_description,
            threshold,
            qualitative_factors or [],
            was_disclosed_separately,
        )
        if violation:
            self.save_violation(violation)
            if raise_on_violation and violation.severity.value >= MaterialitySeverity.HIGH.value:
                raise MaterialityViolationError(
                    violation.message,
                    legal_entity_id,
                    fiscal_year,
                    item_amount,
                    violation.threshold_that_should_apply,
                    violation.severity,
                )
        return is_valid, violation

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_thresholds = len(self._thresholds)
            total_judgments = len(self._judgments)
            total_violations = len(self._violations)
            unresolved = len([v for v in self._violations if not v.resolved])
            return {
                "thresholds_defined": total_thresholds,
                "judgments_recorded": total_judgments,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "by_severity": {
                    sev.name: len([v for v in self._violations if v.severity == sev])
                    for sev in MaterialitySeverity
                },
                "by_failure_type": {
                    ft: len([v for v in self._violations if v.failure_type == ft])
                    for ft in set(v.failure_type for v in self._violations)
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._thresholds = {}
            self._judgments = []
            self._violations = []


# === 6. SINGLETON ACCESSOR ===

_materiality_axiom_instance: MaterialityAxiom | None = None


def get_materiality_axiom() -> MaterialityAxiom:
    global _materiality_axiom_instance
    if _materiality_axiom_instance is None:
        _materiality_axiom_instance = MaterialityAxiom()
    return _materiality_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_qualitative_factor_from_string(factor_str: str) -> QualitativeMaterialityFactor:
    mapping = {
        "FRAUD_OR_ILLEGAL_ACT": QualitativeMaterialityFactor.FRAUD_OR_ILLEGAL_ACT,
        "REGULATORY_COMPLIANCE": QualitativeMaterialityFactor.REGULATORY_COMPLIANCE,
        "DEBT_COVENANT_VIOLATION": QualitativeMaterialityFactor.DEBT_COVENANT_VIOLATION,
        "TREND_REVERSAL": QualitativeMaterialityFactor.TREND_REVERSAL,
        "SEGMENT_REPORTING": QualitativeMaterialityFactor.SEGMENT_REPORTING,
        "RELATED_PARTY": QualitativeMaterialityFactor.RELATED_PARTY,
        "EXECUTIVE_COMPENSATION": QualitativeMaterialityFactor.EXECUTIVE_COMPENSATION,
        "PUBLIC_PERCEPTION": QualitativeMaterialityFactor.PUBLIC_PERCEPTION,
        "GOING_CONCERN": QualitativeMaterialityFactor.GOING_CONCERN,
        "ROLLOVER_EFFECT": QualitativeMaterialityFactor.ROLLOVER_EFFECT,
    }
    return mapping.get(factor_str.upper(), QualitativeMaterialityFactor.PUBLIC_PERCEPTION)


def calculate_materiality_threshold(
    threshold_type: MaterialityThresholdType,
    base_value: Decimal,
    percentage: Decimal = Decimal("5"),
) -> Decimal:
    if threshold_type == MaterialityThresholdType.ABSOLUTE:
        return base_value
    elif threshold_type in (
        MaterialityThresholdType.PERCENTAGE_OF_ASSETS,
        MaterialityThresholdType.PERCENTAGE_OF_EQUITY,
        MaterialityThresholdType.PERCENTAGE_OF_REVENUE,
        MaterialityThresholdType.PERCENTAGE_OF_PROFIT,
    ):
        return base_value * percentage / Decimal(100)
    return base_value


__all__ = [
    "MaterialityAxiom",
    "MaterialityDimension",
    "MaterialityError",
    "MaterialityJudgment",
    "MaterialitySeverity",
    "MaterialityThreshold",
    "MaterialityThresholdType",
    "MaterialityValidator",
    "MaterialityViolation",
    "MaterialityViolationError",
    "QualitativeMaterialityFactor",
    "calculate_materiality_threshold",
    "create_qualitative_factor_from_string",
    "get_materiality_axiom",
]
