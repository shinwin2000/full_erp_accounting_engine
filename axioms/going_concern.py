#!/usr/bin/env python3
"""
Module: going_concern.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: entitas dianggap berkelanjutan (going concern).
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


class GoingConcernStatus(Enum):
    HEALTHY = auto()
    CAUTION = auto()
    UNCERTAIN = auto()
    NEGATIVE = auto()
    LIQUIDATION = auto()


class GoingConcernIndicator(Enum):
    NEGATIVE_EQUITY = auto()
    RECURRING_LOSSES = auto()
    NEGATIVE_OPERATING_CASH_FLOW = auto()
    DEFAULT_ON_LOANS = auto()
    LIQUIDITY_RATIO_BELOW_THRESHOLD = auto()
    WORKING_CAPITAL_DEFICIT = auto()
    LOSS_OF_KEY_MANAGEMENT = auto()
    LOSS_OF_MAJOR_CUSTOMER = auto()
    LOSS_OF_MAJOR_SUPPLIER = auto()
    LABOR_DISPUTES = auto()
    TECHNOLOGICAL_OBSOLESCENCE = auto()
    LEGAL_PROCEEDINGS = auto()
    REGULATORY_SANCTIONS = auto()
    LICENSE_REVOCATION = auto()
    VIOLATION_OF_DEBT_COVENANTS = auto()
    NATURAL_DISASTER = auto()
    MARKET_DOWNTURN_SEVERE = auto()
    PARENT_COMPANY_DISTRESS = auto()
    LOSS_OF_FINANCING = auto()


class GoingConcernSeverity(Enum):
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class GoingConcernAssessmentScope(Enum):
    INDIVIDUAL = auto()
    CONSOLIDATED = auto()
    SEGMENT = auto()


# === 2. EXCEPTIONS ===


class GoingConcernAssessmentError(Exception):
    pass


class GoingConcernViolationError(Exception):
    def __init__(
        self,
        message: str,
        legal_entity_id: UUID,
        severity: GoingConcernSeverity,
        assessment_required: bool,
    ):
        self.legal_entity_id = legal_entity_id
        self.severity = severity
        self.assessment_required = assessment_required
        super().__init__(f"[{severity.name}] {message} | Entity: {legal_entity_id}")


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass
class GoingConcernAssessment:
    assessment_id: UUID
    legal_entity_id: UUID
    assessment_date: datetime
    assessed_by: str
    status: GoingConcernStatus
    indicators: list[GoingConcernIndicator]
    mitigating_factors: list[str]
    assessment_notes: str
    financial_horizon_months: int
    next_assessment_due: datetime
    approved_by: list[str]
    scope: GoingConcernAssessmentScope = GoingConcernAssessmentScope.INDIVIDUAL
    is_mandatory_disclosure: bool = False
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
        self._record_audit("CREATE", self.assessed_by, {})

    def _validate(self) -> None:
        if self.financial_horizon_months < 12:
            raise ValueError(f"Horizon must be >= 12 months: {self.financial_horizon_months}")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.assessment_id}|{self.legal_entity_id}|{self.assessment_date.isoformat()}|{self.status.value}|{self.financial_horizon_months}|{self.scope.value}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "assessment_id": str(self.assessment_id),
                "status": self.status.name,
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
                "assessment_id": str(self.assessment_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> GoingConcernAssessment:
        return self

    def update(self, updated_by: str, **kwargs) -> GoingConcernAssessment:
        new_ass = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_ass, key) and key not in ("assessment_id", "legal_entity_id", "version"):
                setattr(new_ass, key, value)
        new_ass.version = self.version + 1
        new_ass._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_ass

    def delete(self, deleted_by: str, reason: str | None = None) -> GoingConcernAssessment:
        new_ass = self._copy()
        new_ass.deleted_at = datetime.now(UTC)
        new_ass.deleted_by = deleted_by
        new_ass.version = self.version + 1
        new_ass._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_ass

    def restore(self, restored_by: str) -> GoingConcernAssessment:
        if self.deleted_at is None:
            raise ValueError("Assessment not deleted")
        new_ass = self._copy()
        new_ass.deleted_at = None
        new_ass.deleted_by = None
        new_ass.version = self.version + 1
        new_ass._record_audit("RESTORE", restored_by, {})
        return new_ass

    def activate(self, activated_by: str) -> GoingConcernAssessment:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> GoingConcernAssessment:
        return self

    def lock(self, locked_by: str, reason: str) -> GoingConcernAssessment:
        return self

    def unlock(self, unlocked_by: str) -> GoingConcernAssessment:
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
            "assessment_id": str(self.assessment_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": str(self.assessment_id),
            "legal_entity_id": str(self.legal_entity_id),
            "assessment_date": self.assessment_date.isoformat(),
            "assessed_by": self.assessed_by,
            "status": self.status.name,
            "indicators": [i.name for i in self.indicators],
            "mitigating_factors": self.mitigating_factors,
            "assessment_notes": self.assessment_notes,
            "financial_horizon_months": self.financial_horizon_months,
            "next_assessment_due": self.next_assessment_due.isoformat(),
            "approved_by": self.approved_by,
            "scope": self.scope.name,
            "is_mandatory_disclosure": self.is_mandatory_disclosure,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoingConcernAssessment:
        return cls(
            assessment_id=UUID(data["assessment_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            assessment_date=datetime.fromisoformat(data["assessment_date"]),
            assessed_by=data["assessed_by"],
            status=GoingConcernStatus[data["status"]],
            indicators=[GoingConcernIndicator[i] for i in data.get("indicators", [])],
            mitigating_factors=data.get("mitigating_factors", []),
            assessment_notes=data.get("assessment_notes", ""),
            financial_horizon_months=data["financial_horizon_months"],
            next_assessment_due=datetime.fromisoformat(data["next_assessment_due"]),
            approved_by=data.get("approved_by", []),
            scope=GoingConcernAssessmentScope[data["scope"]]
            if "scope" in data
            else GoingConcernAssessmentScope.INDIVIDUAL,
            is_mandatory_disclosure=data.get("is_mandatory_disclosure", False),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> GoingConcernAssessment:
        new_id = uuid4()
        return GoingConcernAssessment(
            assessment_id=new_id,
            legal_entity_id=self.legal_entity_id,
            assessment_date=datetime.now(UTC),
            assessed_by=self.assessed_by,
            status=GoingConcernStatus.HEALTHY,
            indicators=self.indicators.copy(),
            mitigating_factors=self.mitigating_factors.copy(),
            assessment_notes=f"Clone of {self.assessment_id}",
            financial_horizon_months=self.financial_horizon_months,
            next_assessment_due=datetime.now(UTC) + timedelta(days=180),
            approved_by=[],
            scope=self.scope,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "assessment_id": str(self.assessment_id),
            "status": self.status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> GoingConcernAssessment:
        new_ass = self._copy()
        new_ass.version = self.version + 1
        new_ass._record_audit("TOUCH", touched_by, {})
        return new_ass

    def requires_disclosure(self) -> bool:
        return self.status in (GoingConcernStatus.UNCERTAIN, GoingConcernStatus.NEGATIVE)

    def is_expired(self, as_of: datetime | None = None) -> bool:
        check = as_of or datetime.now(UTC)
        return check > self.next_assessment_due

    def _copy(self) -> GoingConcernAssessment:
        return GoingConcernAssessment(
            assessment_id=self.assessment_id,
            legal_entity_id=self.legal_entity_id,
            assessment_date=self.assessment_date,
            assessed_by=self.assessed_by,
            status=self.status,
            indicators=self.indicators.copy(),
            mitigating_factors=self.mitigating_factors.copy(),
            assessment_notes=self.assessment_notes,
            financial_horizon_months=self.financial_horizon_months,
            next_assessment_due=self.next_assessment_due,
            approved_by=self.approved_by.copy(),
            scope=self.scope,
            is_mandatory_disclosure=self.is_mandatory_disclosure,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass
class GoingConcernEvent:
    event_id: UUID
    legal_entity_id: UUID
    previous_status: GoingConcernStatus
    new_status: GoingConcernStatus
    event_date: datetime
    triggered_by: str
    trigger_reason: str
    supporting_documents: list[str]
    reported_to_audit_committee: bool
    reported_at: datetime | None
    cryptographic_hash: str = ""
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._ensure_hash()
        self._take_snapshot()
        self._record_audit("CREATE", self.triggered_by, {})

    def _validate(self) -> None:
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.event_id}|{self.legal_entity_id}|{self.previous_status.value}|{self.new_status.value}|{self.event_date.isoformat()}|{self.trigger_reason[:100]}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "event_id": str(self.event_id),
                "new_status": self.new_status.name,
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
                "event_id": str(self.event_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> GoingConcernEvent:
        return self

    def update(self, updated_by: str, **kwargs) -> GoingConcernEvent:
        raise AttributeError("GoingConcernEvent is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> GoingConcernEvent:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> GoingConcernEvent:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> GoingConcernEvent:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> GoingConcernEvent:
        return self

    def lock(self, locked_by: str, reason: str) -> GoingConcernEvent:
        return self

    def unlock(self, unlocked_by: str) -> GoingConcernEvent:
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
            "event_id": str(self.event_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "legal_entity_id": str(self.legal_entity_id),
            "previous_status": self.previous_status.name,
            "new_status": self.new_status.name,
            "event_date": self.event_date.isoformat(),
            "triggered_by": self.triggered_by,
            "trigger_reason": self.trigger_reason,
            "supporting_documents": self.supporting_documents,
            "reported_to_audit_committee": self.reported_to_audit_committee,
            "reported_at": self.reported_at.isoformat() if self.reported_at else None,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoingConcernEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            previous_status=GoingConcernStatus[data["previous_status"]],
            new_status=GoingConcernStatus[data["new_status"]],
            event_date=datetime.fromisoformat(data["event_date"]),
            triggered_by=data["triggered_by"],
            trigger_reason=data["trigger_reason"],
            supporting_documents=data.get("supporting_documents", []),
            reported_to_audit_committee=data["reported_to_audit_committee"],
            reported_at=datetime.fromisoformat(data["reported_at"])
            if data.get("reported_at")
            else None,
            version=data.get("version", 1),
        )

    def clone(self) -> GoingConcernEvent:
        new_id = uuid4()
        return GoingConcernEvent(
            event_id=new_id,
            legal_entity_id=self.legal_entity_id,
            previous_status=self.previous_status,
            new_status=self.new_status,
            event_date=datetime.now(UTC),
            triggered_by=self.triggered_by,
            trigger_reason=self.trigger_reason,
            supporting_documents=self.supporting_documents.copy(),
            reported_to_audit_committee=self.reported_to_audit_committee,
            reported_at=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "event_id": str(self.event_id),
            "new_status": self.new_status.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> GoingConcernEvent:
        self._record_audit("TOUCH", touched_by, {})
        return self


@dataclass
class GoingConcernViolation:
    violation_id: UUID
    legal_entity_id: UUID
    violation_type: str
    severity: GoingConcernSeverity
    message: str
    detected_at: datetime
    detected_by: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_action: str | None
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
        content = f"{self.violation_id}|{self.legal_entity_id}|{self.violation_type}|{self.severity.value}|{self.message[:100]}"
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
    def create(self, created_by: str) -> GoingConcernViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> GoingConcernViolation:
        raise AttributeError("GoingConcernViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> GoingConcernViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> GoingConcernViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> GoingConcernViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> GoingConcernViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> GoingConcernViolation:
        return self

    def unlock(self, unlocked_by: str) -> GoingConcernViolation:
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
            "violation_type": self.violation_type,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_action": self.resolution_action,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoingConcernViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            violation_type=data["violation_type"],
            severity=GoingConcernSeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            resolution_action=data.get("resolution_action"),
            version=data.get("version", 1),
        )

    def clone(self) -> GoingConcernViolation:
        new_id = uuid4()
        return GoingConcernViolation(
            violation_id=new_id,
            legal_entity_id=self.legal_entity_id,
            violation_type=self.violation_type,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_action=None,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "violation_id": str(self.violation_id),
            "severity": self.severity.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> GoingConcernViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, action: str) -> GoingConcernViolation:
        if self.resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.resolution_action = action
        new_violation.version = self.version + 1
        new_violation._record_audit("RESOLVE", by, {"action": action})
        return new_violation

    def _copy(self) -> GoingConcernViolation:
        return GoingConcernViolation(
            violation_id=self.violation_id,
            legal_entity_id=self.legal_entity_id,
            violation_type=self.violation_type,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            resolution_action=self.resolution_action,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class GoingConcernValidator:
    DEFAULT_HORIZON_MONTHS = 12
    MAX_ASSESSMENT_INTERVAL_DAYS = 180
    WARNING_BEFORE_EXPIRY_DAYS = 30

    @classmethod
    def validate_assessment_timeliness(
        cls,
        legal_entity_id: UUID,
        last_assessment: GoingConcernAssessment | None,
        current_date: datetime | None = None,
    ) -> tuple[bool, GoingConcernViolation | None, str | None]:
        current = current_date or datetime.now(UTC)
        if not last_assessment:
            violation = cls._create_violation(
                legal_entity_id,
                "MISSING_ASSESSMENT",
                GoingConcernSeverity.HIGH,
                f"No going concern assessment found for entity {legal_entity_id}",
                "validator",
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation, "Perform initial assessment immediately"
        if last_assessment.is_expired(current):
            days = (current - last_assessment.next_assessment_due).days
            severity = GoingConcernSeverity.MEDIUM if days <= 30 else GoingConcernSeverity.HIGH
            violation = cls._create_violation(
                legal_entity_id,
                "EXPIRED_ASSESSMENT",
                severity,
                f"Assessment overdue by {days} days",
                "validator",
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation, f"Schedule new assessment (overdue {days} days)"
        days_until = (last_assessment.next_assessment_due - current).days
        if days_until <= cls.WARNING_BEFORE_EXPIRY_DAYS:
            logger.warning(f"Assessment for entity {legal_entity_id} expires in {days_until} days")
        return True, None, None

    @classmethod
    def _create_violation(
        cls,
        legal_entity_id: UUID,
        violation_type: str,
        severity: GoingConcernSeverity,
        message: str,
        detected_by: str,
    ) -> GoingConcernViolation:
        return GoingConcernViolation(
            violation_id=uuid4(),
            legal_entity_id=legal_entity_id,
            violation_type=violation_type,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            detected_by=detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            resolution_action=None,
        )

    @classmethod
    def _log_violation(cls, violation: GoingConcernViolation) -> None:
        log_msg = f"[{violation.severity.name}] Going concern violation: {violation.message}"
        if violation.severity.value >= GoingConcernSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: GoingConcernViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                GoingConcernSeverity.CRITICAL: ConstitutionalSeverity.CRITICAL,
                GoingConcernSeverity.HIGH: ConstitutionalSeverity.HIGH,
                GoingConcernSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                GoingConcernSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.GOING_CONCERN,
                offending_module="going_concern_validator",
                message=violation.message,
                offending_command_id=violation.legal_entity_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class GoingConcernAxiom:
    _instance: GoingConcernAxiom | None = None
    _assessments: dict[UUID, GoingConcernAssessment] = {}
    _assessment_history: list[GoingConcernAssessment] = []
    _events: list[GoingConcernEvent] = []
    _violations: list[GoingConcernViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> GoingConcernAxiom:
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
        self._assessments = {}
        self._assessment_history = []
        self._events = []
        self._violations = []

    # ==================== REPOSITORY METHODS ====================
    def save_assessment(self, assessment: GoingConcernAssessment) -> None:
        with self._lock:
            self._assessments[assessment.legal_entity_id] = assessment
            self._assessment_history.append(assessment)

    def get_assessment(self, legal_entity_id: UUID) -> GoingConcernAssessment | None:
        return self._assessments.get(legal_entity_id)

    def get_assessment_history(
        self, legal_entity_id: UUID | None = None, limit: int = 100
    ) -> list[GoingConcernAssessment]:
        result = self._assessment_history[-limit:]
        if legal_entity_id:
            result = [a for a in result if a.legal_entity_id == legal_entity_id]
        return result

    def delete_assessment(self, legal_entity_id: UUID) -> bool:
        with self._lock:
            if legal_entity_id in self._assessments:
                del self._assessments[legal_entity_id]
                return True
            return False

    def save_event(self, event: GoingConcernEvent) -> None:
        with self._lock:
            self._events.append(event)

    def get_events(
        self, legal_entity_id: UUID | None = None, since: datetime | None = None
    ) -> list[GoingConcernEvent]:
        result = self._events
        if legal_entity_id:
            result = [e for e in result if e.legal_entity_id == legal_entity_id]
        if since:
            result = [e for e in result if e.event_date >= since]
        return result

    def delete_event(self, event_id: UUID) -> bool:
        with self._lock:
            for i, e in enumerate(self._events):
                if e.event_id == event_id:
                    self._events.pop(i)
                    return True
            return False

    def save_violation(self, violation: GoingConcernViolation) -> None:
        with self._lock:
            self._violations.append(violation)

    def get_violations(
        self, legal_entity_id: UUID | None = None, unresolved_only: bool = False, limit: int = 100
    ) -> list[GoingConcernViolation]:
        result = self._violations[-limit:]
        if legal_entity_id:
            result = [v for v in result if v.legal_entity_id == legal_entity_id]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, resolution_action: str
    ) -> GoingConcernViolation | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by, resolution_action)
                    self._violations[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def perform_assessment(
        self,
        legal_entity_id: UUID,
        assessed_by: str,
        indicators: list[GoingConcernIndicator],
        mitigating_factors: list[str],
        assessment_notes: str,
        financial_horizon_months: int = 12,
        approved_by: list[str] | None = None,
        scope: GoingConcernAssessmentScope = GoingConcernAssessmentScope.INDIVIDUAL,
    ) -> GoingConcernAssessment:
        if financial_horizon_months < 12:
            raise GoingConcernAssessmentError(
                f"Horizon must be >= 12 months: {financial_horizon_months}"
            )
        status = self._determine_status(indicators, mitigating_factors)
        if status in (GoingConcernStatus.UNCERTAIN, GoingConcernStatus.NEGATIVE):
            if not approved_by or len(approved_by) < 2:
                raise GoingConcernAssessmentError(
                    f"Status {status.name} requires at least 2 approvers"
                )
        else:
            approved_by = approved_by or [assessed_by]
        is_mandatory = status in (GoingConcernStatus.UNCERTAIN, GoingConcernStatus.NEGATIVE)
        next_due = datetime.now(UTC) + timedelta(
            days=GoingConcernValidator.MAX_ASSESSMENT_INTERVAL_DAYS
        )
        assessment = GoingConcernAssessment(
            assessment_id=uuid4(),
            legal_entity_id=legal_entity_id,
            assessment_date=datetime.now(UTC),
            assessed_by=assessed_by,
            status=status,
            indicators=indicators,
            mitigating_factors=mitigating_factors,
            assessment_notes=assessment_notes,
            financial_horizon_months=financial_horizon_months,
            next_assessment_due=next_due,
            approved_by=approved_by,
            scope=scope,
            is_mandatory_disclosure=is_mandatory,
        )
        with self._lock:
            previous = self._assessments.get(legal_entity_id)
            if previous and previous.status != status:
                event = GoingConcernEvent(
                    event_id=uuid4(),
                    legal_entity_id=legal_entity_id,
                    previous_status=previous.status,
                    new_status=status,
                    event_date=datetime.now(UTC),
                    triggered_by=assessed_by,
                    trigger_reason=f"Assessment: {assessment_notes[:100]}",
                    supporting_documents=[],
                    reported_to_audit_committee=is_mandatory,
                    reported_at=datetime.now(UTC) if is_mandatory else None,
                )
                self._events.append(event)
            self._assessments[legal_entity_id] = assessment
            self._assessment_history.append(assessment)
        return assessment

    def _determine_status(
        self, indicators: list[GoingConcernIndicator], mitigating_factors: list[str]
    ) -> GoingConcernStatus:
        critical = [
            GoingConcernIndicator.NEGATIVE_EQUITY,
            GoingConcernIndicator.DEFAULT_ON_LOANS,
            GoingConcernIndicator.LICENSE_REVOCATION,
            GoingConcernIndicator.VIOLATION_OF_DEBT_COVENANTS,
        ]
        significant = [
            GoingConcernIndicator.RECURRING_LOSSES,
            GoingConcernIndicator.NEGATIVE_OPERATING_CASH_FLOW,
            GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER,
            GoingConcernIndicator.LEGAL_PROCEEDINGS,
            GoingConcernIndicator.LOSS_OF_FINANCING,
        ]
        critical_count = len([i for i in indicators if i in critical])
        significant_count = len([i for i in indicators if i in significant])
        has_mitigation = len(mitigating_factors) > 0
        if critical_count >= 2:
            return GoingConcernStatus.NEGATIVE
        elif critical_count >= 1:
            return (
                GoingConcernStatus.UNCERTAIN if not has_mitigation else GoingConcernStatus.CAUTION
            )
        elif significant_count >= 3:
            return GoingConcernStatus.UNCERTAIN
        elif significant_count >= 1:
            return GoingConcernStatus.CAUTION
        return GoingConcernStatus.HEALTHY

    def get_entities_with_concern(self) -> list[UUID]:
        return [
            eid
            for eid, a in self._assessments.items()
            if a.status
            in (
                GoingConcernStatus.CAUTION,
                GoingConcernStatus.UNCERTAIN,
                GoingConcernStatus.NEGATIVE,
            )
        ]

    def enforce(
        self,
        legal_entity_id: UUID,
        transaction_type: str,
        context: dict[str, Any],
        raise_on_violation: bool = True,
    ) -> tuple[bool, GoingConcernViolation | None]:
        latest = self.get_assessment(legal_entity_id)
        is_timely, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
            legal_entity_id, latest
        )
        if violation:
            self.save_violation(violation)
            if raise_on_violation and violation.severity.value >= GoingConcernSeverity.HIGH.value:
                raise GoingConcernViolationError(
                    violation.message, legal_entity_id, violation.severity, True
                )
            return False, violation
        if transaction_type == "FINANCIAL_STATEMENT" and latest and latest.requires_disclosure():
            period_end = context.get("period_end")
            if period_end and latest.assessment_date > period_end:
                violation = GoingConcernValidator._create_violation(
                    legal_entity_id,
                    "DISCLOSURE_TIMING",
                    GoingConcernSeverity.CRITICAL,
                    f"Assessment {latest.assessment_date} does not cover period end {period_end}",
                    "axiom",
                )
                self.save_violation(violation)
                if raise_on_violation:
                    raise GoingConcernViolationError(
                        violation.message, legal_entity_id, violation.severity, False
                    )
                return False, violation
        if transaction_type in ("MAJOR_ASSET_ACQUISITION", "NEW_LOAN", "DIVESTITURE"):
            if not latest or latest.is_expired():
                violation = GoingConcernValidator._create_violation(
                    legal_entity_id,
                    "STALE_ASSESSMENT_FOR_MAJOR_TRANSACTION",
                    GoingConcernSeverity.HIGH,
                    f"Major transaction {transaction_type} requires current assessment",
                    "axiom",
                )
                self.save_violation(violation)
                if raise_on_violation:
                    raise GoingConcernViolationError(
                        violation.message, legal_entity_id, violation.severity, True
                    )
                return False, violation
        return True, None

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_assessments = len(self._assessments)
            total_history = len(self._assessment_history)
            total_events = len(self._events)
            total_violations = len(self._violations)
            unresolved = len([v for v in self._violations if not v.resolved])
            status_counts = {
                s.name: len([a for a in self._assessments.values() if a.status == s])
                for s in GoingConcernStatus
            }
            return {
                "entities_with_assessment": total_assessments,
                "total_assessments": total_history,
                "total_events": total_events,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "status_distribution": status_counts,
                "entities_requiring_disclosure": len(
                    [a for a in self._assessments.values() if a.requires_disclosure()]
                ),
                "expired_assessments": len(
                    [a for a in self._assessments.values() if a.is_expired()]
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._assessments = {}
            self._assessment_history = []
            self._events = []
            self._violations = []


# === 6. SINGLETON ACCESSOR ===

_going_concern_axiom_instance: GoingConcernAxiom | None = None


def get_going_concern_axiom() -> GoingConcernAxiom:
    global _going_concern_axiom_instance
    if _going_concern_axiom_instance is None:
        _going_concern_axiom_instance = GoingConcernAxiom()
    return _going_concern_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_going_concern_indicator_from_string(indicator_str: str) -> GoingConcernIndicator:
    mapping = {
        "NEGATIVE_EQUITY": GoingConcernIndicator.NEGATIVE_EQUITY,
        "RECURRING_LOSSES": GoingConcernIndicator.RECURRING_LOSSES,
        "NEGATIVE_OPERATING_CASH_FLOW": GoingConcernIndicator.NEGATIVE_OPERATING_CASH_FLOW,
        "DEFAULT_ON_LOANS": GoingConcernIndicator.DEFAULT_ON_LOANS,
        "LIQUIDITY_RATIO_BELOW_THRESHOLD": GoingConcernIndicator.LIQUIDITY_RATIO_BELOW_THRESHOLD,
        "WORKING_CAPITAL_DEFICIT": GoingConcernIndicator.WORKING_CAPITAL_DEFICIT,
        "LOSS_OF_KEY_MANAGEMENT": GoingConcernIndicator.LOSS_OF_KEY_MANAGEMENT,
        "LOSS_OF_MAJOR_CUSTOMER": GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER,
        "LOSS_OF_MAJOR_SUPPLIER": GoingConcernIndicator.LOSS_OF_MAJOR_SUPPLIER,
        "LABOR_DISPUTES": GoingConcernIndicator.LABOR_DISPUTES,
        "TECHNOLOGICAL_OBSOLESCENCE": GoingConcernIndicator.TECHNOLOGICAL_OBSOLESCENCE,
        "LEGAL_PROCEEDINGS": GoingConcernIndicator.LEGAL_PROCEEDINGS,
        "REGULATORY_SANCTIONS": GoingConcernIndicator.REGULATORY_SANCTIONS,
        "LICENSE_REVOCATION": GoingConcernIndicator.LICENSE_REVOCATION,
        "VIOLATION_OF_DEBT_COVENANTS": GoingConcernIndicator.VIOLATION_OF_DEBT_COVENANTS,
        "NATURAL_DISASTER": GoingConcernIndicator.NATURAL_DISASTER,
        "MARKET_DOWNTURN_SEVERE": GoingConcernIndicator.MARKET_DOWNTURN_SEVERE,
        "PARENT_COMPANY_DISTRESS": GoingConcernIndicator.PARENT_COMPANY_DISTRESS,
        "LOSS_OF_FINANCING": GoingConcernIndicator.LOSS_OF_FINANCING,
    }
    return mapping.get(indicator_str.upper(), GoingConcernIndicator.LIQUIDITY_RATIO_BELOW_THRESHOLD)


def get_going_concern_severity_from_status(status: GoingConcernStatus) -> GoingConcernSeverity:
    mapping = {
        GoingConcernStatus.HEALTHY: GoingConcernSeverity.INFO,
        GoingConcernStatus.CAUTION: GoingConcernSeverity.LOW,
        GoingConcernStatus.UNCERTAIN: GoingConcernSeverity.HIGH,
        GoingConcernStatus.NEGATIVE: GoingConcernSeverity.CRITICAL,
        GoingConcernStatus.LIQUIDATION: GoingConcernSeverity.CRITICAL,
    }
    return mapping.get(status, GoingConcernSeverity.MEDIUM)


__all__ = [
    "GoingConcernAssessment",
    "GoingConcernAssessmentError",
    "GoingConcernAssessmentScope",
    "GoingConcernAxiom",
    "GoingConcernEvent",
    "GoingConcernIndicator",
    "GoingConcernSeverity",
    "GoingConcernStatus",
    "GoingConcernValidator",
    "GoingConcernViolation",
    "GoingConcernViolationError",
    "create_going_concern_indicator_from_string",
    "get_going_concern_axiom",
    "get_going_concern_severity_from_status",
]
