#!/usr/bin/env python3
"""
Module: substance_over_form.py
Layer: 2 - Foundation / Axioms
Responsibility: Aksioma: substansi ekonomi mengungguli bentuk hukum.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
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


class SubstanceOverrideType(Enum):
    LEASE = auto()
    SALE_AND_LEASEBACK = auto()
    FACTORING = auto()
    CONSIGNMENT = auto()
    REPURCHASE_AGREEMENT = auto()
    SPECIAL_PURPOSE_ENTITY = auto()
    EQUITY_SETTLEMENT = auto()
    HYBRID_INSTRUMENT = auto()
    RELATED_PARTY = auto()
    NON_MONETARY_EXCHANGE = auto()


class SubstanceAssessmentSeverity(Enum):
    CATASTROPHIC = 100
    CRITICAL = 80
    HIGH = 60
    MEDIUM = 40
    LOW = 20
    INFO = 0


class LeaseClassification(Enum):
    FINANCE_LEASE = auto()
    OPERATING_LEASE = auto()


# === 2. EXCEPTIONS ===


class SubstanceOverFormError(Exception):
    pass


class SubstanceViolationError(Exception):
    def __init__(
        self,
        message: str,
        transaction_id: UUID,
        legal_form_summary: str,
        economic_substance_summary: str,
        severity: SubstanceAssessmentSeverity,
    ):
        self.transaction_id = transaction_id
        self.legal_form_summary = legal_form_summary
        self.economic_substance_summary = economic_substance_summary
        self.severity = severity
        super().__init__(
            f"[{severity.name}] {message} | TX: {transaction_id}, Legal: {legal_form_summary[:50]}, Economic: {economic_substance_summary[:50]}"
        )


# === 3. VALUE OBJECTS / ENTITIES ===


@dataclass(kw_only=True)
class LegalForm:
    contract_type: str
    parties: list[str]
    legal_ownership_transfer: bool
    legal_amount: Decimal
    currency: str
    contract_date: datetime
    contract_terms: dict[str, Any]
    governing_law: str
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
        if not self.parties:
            raise ValueError("At least one party required")
        if self.legal_amount <= 0:
            raise ValueError("Legal amount must be positive")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.contract_type}|{self.legal_ownership_transfer}|{self.legal_amount}|{self.currency}|{self.contract_date.isoformat()}|{self.governing_law}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "contract_type": self.contract_type,
                "legal_amount": str(self.legal_amount),
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
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> LegalForm:
        return self

    def update(self, updated_by: str, **kwargs) -> LegalForm:
        new_form = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_form, key) and key not in ("version"):
                setattr(new_form, key, value)
        new_form.version = self.version + 1
        new_form._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_form

    def delete(self, deleted_by: str, reason: str | None = None) -> LegalForm:
        new_form = self._copy()
        new_form.deleted_at = datetime.now(UTC)
        new_form.deleted_by = deleted_by
        new_form.version = self.version + 1
        new_form._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_form

    def restore(self, restored_by: str) -> LegalForm:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_form = self._copy()
        new_form.deleted_at = None
        new_form.deleted_by = None
        new_form.version = self.version + 1
        new_form._record_audit("RESTORE", restored_by, {})
        return new_form

    def activate(self, activated_by: str) -> LegalForm:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> LegalForm:
        return self

    def lock(self, locked_by: str, reason: str) -> LegalForm:
        return self

    def unlock(self, unlocked_by: str) -> LegalForm:
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
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_type": self.contract_type,
            "parties": self.parties,
            "legal_ownership_transfer": self.legal_ownership_transfer,
            "legal_amount": str(self.legal_amount),
            "currency": self.currency,
            "contract_date": self.contract_date.isoformat(),
            "contract_terms": self.contract_terms,
            "governing_law": self.governing_law,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LegalForm:
        return cls(
            contract_type=data["contract_type"],
            parties=data["parties"],
            legal_ownership_transfer=data["legal_ownership_transfer"],
            legal_amount=Decimal(data["legal_amount"]),
            currency=data["currency"],
            contract_date=datetime.fromisoformat(data["contract_date"]),
            contract_terms=data.get("contract_terms", {}),
            governing_law=data.get("governing_law", "Indonesia"),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> LegalForm:
        return LegalForm(
            contract_type=self.contract_type,
            parties=self.parties.copy(),
            legal_ownership_transfer=self.legal_ownership_transfer,
            legal_amount=self.legal_amount,
            currency=self.currency,
            contract_date=self.contract_date,
            contract_terms=self.contract_terms.copy(),
            governing_law=self.governing_law,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "contract_type": self.contract_type,
            "legal_amount": str(self.legal_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> LegalForm:
        new_form = self._copy()
        new_form.version = self.version + 1
        new_form._record_audit("TOUCH", touched_by, {})
        return new_form

    def _copy(self) -> LegalForm:
        return LegalForm(
            contract_type=self.contract_type,
            parties=self.parties.copy(),
            legal_ownership_transfer=self.legal_ownership_transfer,
            legal_amount=self.legal_amount,
            currency=self.currency,
            contract_date=self.contract_date,
            contract_terms=self.contract_terms.copy(),
            governing_law=self.governing_law,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class EconomicSubstance:
    transaction_type: SubstanceOverrideType
    risks_and_rewards_transferred: bool
    control_transferred: bool
    effective_ownership: str
    economic_amount: Decimal
    economic_currency: str
    effective_date: datetime
    reasoning: str
    supporting_evidence: list[str]
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
        if self.economic_amount <= 0:
            raise ValueError("Economic amount must be positive")
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.transaction_type.value}|{self.risks_and_rewards_transferred}|{self.control_transferred}|{self.effective_ownership}|{self.economic_amount}|{self.economic_currency}|{self.effective_date.isoformat()}|{self.reasoning[:100]}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "transaction_type": self.transaction_type.name,
                "economic_amount": str(self.economic_amount),
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
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> EconomicSubstance:
        return self

    def update(self, updated_by: str, **kwargs) -> EconomicSubstance:
        new_sub = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_sub, key) and key not in ("version"):
                setattr(new_sub, key, value)
        new_sub.version = self.version + 1
        new_sub._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_sub

    def delete(self, deleted_by: str, reason: str | None = None) -> EconomicSubstance:
        new_sub = self._copy()
        new_sub.deleted_at = datetime.now(UTC)
        new_sub.deleted_by = deleted_by
        new_sub.version = self.version + 1
        new_sub._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_sub

    def restore(self, restored_by: str) -> EconomicSubstance:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_sub = self._copy()
        new_sub.deleted_at = None
        new_sub.deleted_by = None
        new_sub.version = self.version + 1
        new_sub._record_audit("RESTORE", restored_by, {})
        return new_sub

    def activate(self, activated_by: str) -> EconomicSubstance:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EconomicSubstance:
        return self

    def lock(self, locked_by: str, reason: str) -> EconomicSubstance:
        return self

    def unlock(self, unlocked_by: str) -> EconomicSubstance:
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
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_type": self.transaction_type.name,
            "risks_and_rewards_transferred": self.risks_and_rewards_transferred,
            "control_transferred": self.control_transferred,
            "effective_ownership": self.effective_ownership,
            "economic_amount": str(self.economic_amount),
            "economic_currency": self.economic_currency,
            "effective_date": self.effective_date.isoformat(),
            "reasoning": self.reasoning,
            "supporting_evidence": self.supporting_evidence,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EconomicSubstance:
        return cls(
            transaction_type=SubstanceOverrideType[data["transaction_type"]],
            risks_and_rewards_transferred=data["risks_and_rewards_transferred"],
            control_transferred=data["control_transferred"],
            effective_ownership=data["effective_ownership"],
            economic_amount=Decimal(data["economic_amount"]),
            economic_currency=data["economic_currency"],
            effective_date=datetime.fromisoformat(data["effective_date"]),
            reasoning=data["reasoning"],
            supporting_evidence=data.get("supporting_evidence", []),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> EconomicSubstance:
        return EconomicSubstance(
            transaction_type=self.transaction_type,
            risks_and_rewards_transferred=self.risks_and_rewards_transferred,
            control_transferred=self.control_transferred,
            effective_ownership=self.effective_ownership,
            economic_amount=self.economic_amount,
            economic_currency=self.economic_currency,
            effective_date=self.effective_date,
            reasoning=self.reasoning,
            supporting_evidence=self.supporting_evidence.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transaction_type": self.transaction_type.name,
            "economic_amount": str(self.economic_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EconomicSubstance:
        new_sub = self._copy()
        new_sub.version = self.version + 1
        new_sub._record_audit("TOUCH", touched_by, {})
        return new_sub

    def _copy(self) -> EconomicSubstance:
        return EconomicSubstance(
            transaction_type=self.transaction_type,
            risks_and_rewards_transferred=self.risks_and_rewards_transferred,
            control_transferred=self.control_transferred,
            effective_ownership=self.effective_ownership,
            economic_amount=self.economic_amount,
            economic_currency=self.economic_currency,
            effective_date=self.effective_date,
            reasoning=self.reasoning,
            supporting_evidence=self.supporting_evidence.copy(),
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class SubstanceOverFormAssessment:
    assessment_id: UUID
    transaction_id: UUID
    legal_form: LegalForm
    economic_substance: EconomicSubstance
    is_different: bool
    difference_description: str
    proper_accounting_treatment: str
    recommended_journal_template: dict[str, Any] | None
    assessed_by: str
    assessed_at: datetime
    approved_by: list[str]
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
        if self.version < 1:
            raise ValueError("Version must be >= 1")

    def _ensure_hash(self) -> None:
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())

    def compute_hash(self) -> str:
        content = f"{self.assessment_id}|{self.transaction_id}|{self.is_different}|{self.proper_accounting_treatment[:100]}|{self.assessed_by}"
        return hashlib.sha3_256(content.encode()).hexdigest()

    def _take_snapshot(self) -> None:
        self._snapshots.append(
            {
                "version": self.version,
                "assessment_id": str(self.assessment_id),
                "is_different": self.is_different,
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
    def create(self, created_by: str) -> SubstanceOverFormAssessment:
        return self

    def update(self, updated_by: str, **kwargs) -> SubstanceOverFormAssessment:
        new_ass = self._copy()
        for key, value in kwargs.items():
            if hasattr(new_ass, key) and key not in ("assessment_id", "transaction_id", "version"):
                setattr(new_ass, key, value)
        new_ass.version = self.version + 1
        new_ass._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_ass

    def delete(self, deleted_by: str, reason: str | None = None) -> SubstanceOverFormAssessment:
        new_ass = self._copy()
        new_ass.deleted_at = datetime.now(UTC)
        new_ass.deleted_by = deleted_by
        new_ass.version = self.version + 1
        new_ass._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_ass

    def restore(self, restored_by: str) -> SubstanceOverFormAssessment:
        if self.deleted_at is None:
            raise ValueError("Not deleted")
        new_ass = self._copy()
        new_ass.deleted_at = None
        new_ass.deleted_by = None
        new_ass.version = self.version + 1
        new_ass._record_audit("RESTORE", restored_by, {})
        return new_ass

    def activate(self, activated_by: str) -> SubstanceOverFormAssessment:
        return self

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> SubstanceOverFormAssessment:
        return self

    def lock(self, locked_by: str, reason: str) -> SubstanceOverFormAssessment:
        return self

    def unlock(self, unlocked_by: str) -> SubstanceOverFormAssessment:
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
            "transaction_id": str(self.transaction_id),
            "legal_form": self.legal_form.to_dict(),
            "economic_substance": self.economic_substance.to_dict(),
            "is_different": self.is_different,
            "difference_description": self.difference_description,
            "proper_accounting_treatment": self.proper_accounting_treatment,
            "recommended_journal_template": self.recommended_journal_template,
            "assessed_by": self.assessed_by,
            "assessed_at": self.assessed_at.isoformat(),
            "approved_by": self.approved_by,
            "version": self.version,
            "deleted_at": self.deleted_at.isoformat() if self.deleted_at else None,
            "deleted_by": self.deleted_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubstanceOverFormAssessment:
        return cls(
            assessment_id=UUID(data["assessment_id"]),
            transaction_id=UUID(data["transaction_id"]),
            legal_form=LegalForm.from_dict(data["legal_form"]),
            economic_substance=EconomicSubstance.from_dict(data["economic_substance"]),
            is_different=data["is_different"],
            difference_description=data["difference_description"],
            proper_accounting_treatment=data["proper_accounting_treatment"],
            recommended_journal_template=data.get("recommended_journal_template"),
            assessed_by=data["assessed_by"],
            assessed_at=datetime.fromisoformat(data["assessed_at"]),
            approved_by=data.get("approved_by", []),
            version=data.get("version", 1),
            deleted_at=datetime.fromisoformat(data["deleted_at"])
            if data.get("deleted_at")
            else None,
            deleted_by=data.get("deleted_by"),
        )

    def clone(self) -> SubstanceOverFormAssessment:
        new_id = uuid4()
        return SubstanceOverFormAssessment(
            assessment_id=new_id,
            transaction_id=self.transaction_id,
            legal_form=self.legal_form.clone(),
            economic_substance=self.economic_substance.clone(),
            is_different=self.is_different,
            difference_description=self.difference_description,
            proper_accounting_treatment=self.proper_accounting_treatment,
            recommended_journal_template=self.recommended_journal_template.copy()
            if self.recommended_journal_template
            else None,
            assessed_by=self.assessed_by,
            assessed_at=datetime.now(UTC),
            approved_by=self.approved_by.copy(),
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "assessment_id": str(self.assessment_id),
            "is_different": self.is_different,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SubstanceOverFormAssessment:
        new_ass = self._copy()
        new_ass.version = self.version + 1
        new_ass._record_audit("TOUCH", touched_by, {})
        return new_ass

    def requires_adjustment(self) -> bool:
        return self.is_different

    def _copy(self) -> SubstanceOverFormAssessment:
        return SubstanceOverFormAssessment(
            assessment_id=self.assessment_id,
            transaction_id=self.transaction_id,
            legal_form=self.legal_form,
            economic_substance=self.economic_substance,
            is_different=self.is_different,
            difference_description=self.difference_description,
            proper_accounting_treatment=self.proper_accounting_treatment,
            recommended_journal_template=self.recommended_journal_template.copy()
            if self.recommended_journal_template
            else None,
            assessed_by=self.assessed_by,
            assessed_at=self.assessed_at,
            approved_by=self.approved_by.copy(),
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
            deleted_at=self.deleted_at,
            deleted_by=self.deleted_by,
        )


@dataclass(kw_only=True)
class SubstanceViolation:
    violation_id: UUID
    transaction_id: UUID
    legal_form_summary: str
    economic_substance_summary: str
    recorded_treatment: str
    proper_treatment: str
    severity: SubstanceAssessmentSeverity
    message: str
    detected_at: datetime
    detected_by: str
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    correction_journal_id: UUID | None
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
        content = (
            f"{self.violation_id}|{self.transaction_id}|{self.severity.value}|{self.message[:100]}"
        )
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
    def create(self, created_by: str) -> SubstanceViolation:
        return self

    def update(self, updated_by: str, **kwargs) -> SubstanceViolation:
        raise AttributeError("SubstanceViolation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> SubstanceViolation:
        raise AttributeError("Cannot delete")

    def restore(self, restored_by: str) -> SubstanceViolation:
        raise AttributeError("Cannot restore")

    def activate(self, activated_by: str) -> SubstanceViolation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SubstanceViolation:
        return self

    def lock(self, locked_by: str, reason: str) -> SubstanceViolation:
        return self

    def unlock(self, unlocked_by: str) -> SubstanceViolation:
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
            "transaction_id": str(self.transaction_id),
            "legal_form_summary": self.legal_form_summary,
            "economic_substance_summary": self.economic_substance_summary,
            "recorded_treatment": self.recorded_treatment,
            "proper_treatment": self.proper_treatment,
            "severity": self.severity.name,
            "message": self.message,
            "detected_at": self.detected_at.isoformat(),
            "detected_by": self.detected_by,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "correction_journal_id": str(self.correction_journal_id)
            if self.correction_journal_id
            else None,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubstanceViolation:
        return cls(
            violation_id=UUID(data["violation_id"]),
            transaction_id=UUID(data["transaction_id"]),
            legal_form_summary=data["legal_form_summary"],
            economic_substance_summary=data["economic_substance_summary"],
            recorded_treatment=data["recorded_treatment"],
            proper_treatment=data["proper_treatment"],
            severity=SubstanceAssessmentSeverity[data["severity"]],
            message=data["message"],
            detected_at=datetime.fromisoformat(data["detected_at"]),
            detected_by=data["detected_by"],
            resolved=data["resolved"],
            resolved_at=datetime.fromisoformat(data["resolved_at"])
            if data.get("resolved_at")
            else None,
            resolved_by=data.get("resolved_by"),
            correction_journal_id=UUID(data["correction_journal_id"])
            if data.get("correction_journal_id")
            else None,
            version=data.get("version", 1),
        )

    def clone(self) -> SubstanceViolation:
        new_id = uuid4()
        return SubstanceViolation(
            violation_id=new_id,
            transaction_id=self.transaction_id,
            legal_form_summary=self.legal_form_summary,
            economic_substance_summary=self.economic_substance_summary,
            recorded_treatment=self.recorded_treatment,
            proper_treatment=self.proper_treatment,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
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

    def touch(self, touched_by: str) -> SubstanceViolation:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def resolve(self, by: str, correction_journal_id: UUID) -> SubstanceViolation:
        if self.resolved:
            raise ValueError("Already resolved")
        new_violation = self._copy()
        new_violation.resolved = True
        new_violation.resolved_at = datetime.now(UTC)
        new_violation.resolved_by = by
        new_violation.correction_journal_id = correction_journal_id
        new_violation.version = self.version + 1
        new_violation._record_audit(
            "RESOLVE", by, {"correction_journal_id": str(correction_journal_id)}
        )
        return new_violation

    def _copy(self) -> SubstanceViolation:
        return SubstanceViolation(
            violation_id=self.violation_id,
            transaction_id=self.transaction_id,
            legal_form_summary=self.legal_form_summary,
            economic_substance_summary=self.economic_substance_summary,
            recorded_treatment=self.recorded_treatment,
            proper_treatment=self.proper_treatment,
            severity=self.severity,
            message=self.message,
            detected_at=self.detected_at,
            detected_by=self.detected_by,
            resolved=self.resolved,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
            correction_journal_id=self.correction_journal_id,
            cryptographic_hash=self.cryptographic_hash,
            version=self.version,
        )


# === 4. VALIDATOR ===


class SubstanceOverFormValidator:
    @classmethod
    def validate_lease(
        cls, legal_form: LegalForm, economic_substance: EconomicSubstance, transaction_id: UUID
    ) -> tuple[bool, SubstanceViolation | None, str | None]:
        lease_term = legal_form.contract_terms.get("lease_term_months", 0)
        is_low_value = legal_form.contract_terms.get("is_low_value", False)
        if lease_term > 12 and not is_low_value:
            if economic_substance.transaction_type != SubstanceOverrideType.LEASE:
                severity = SubstanceAssessmentSeverity.HIGH
                violation = cls._create_violation(
                    transaction_id,
                    f"Lease term {lease_term} months, but recorded as operating lease",
                    "Economic substance indicates finance lease",
                    "Operating lease (off-balance)",
                    "Finance lease (right-of-use asset and liability)",
                    severity,
                    "Lease should be recorded as finance lease per PSAK 73/IFRS 16",
                    "substance_validator",
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation, "Reclassify as finance lease"
        return True, None, None

    @classmethod
    def validate_factoring(
        cls, legal_form: LegalForm, economic_substance: EconomicSubstance, transaction_id: UUID
    ) -> tuple[bool, SubstanceViolation | None]:
        recourse = legal_form.contract_terms.get("recourse", True)
        if recourse and legal_form.legal_ownership_transfer:
            if economic_substance.transaction_type != SubstanceOverrideType.FACTORING:
                violation = cls._create_violation(
                    transaction_id,
                    "Legal sale with recourse",
                    "Economic substance is secured borrowing",
                    "Sale of receivables (derecognition)",
                    "Secured borrowing (liability)",
                    SubstanceAssessmentSeverity.HIGH,
                    "Factoring with recourse should be recorded as borrowing",
                    "substance_validator",
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        return True, None

    @classmethod
    def validate_consignment(
        cls, legal_form: LegalForm, economic_substance: EconomicSubstance, transaction_id: UUID
    ) -> tuple[bool, SubstanceViolation | None]:
        if not legal_form.legal_ownership_transfer:
            if economic_substance.effective_ownership != "consignor":
                violation = cls._create_violation(
                    transaction_id,
                    "Goods on consignment, legal ownership with consignor",
                    "Effective ownership still with consignor",
                    "Recorded as inventory of consignee",
                    "Not inventory of consignee, off-balance sheet",
                    SubstanceAssessmentSeverity.MEDIUM,
                    "Consignment goods not inventory of consignee",
                    "substance_validator",
                )
                cls._log_violation(violation)
                cls._notify_constitution(violation)
                return False, violation
        return True, None

    @classmethod
    def validate_related_party(
        cls,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        transaction_id: UUID,
        tolerance_percent: Decimal = Decimal("5"),
    ) -> tuple[bool, SubstanceViolation | None]:
        diff = abs(economic_substance.economic_amount - legal_form.legal_amount)
        ratio = diff / legal_form.legal_amount * Decimal(100)
        if ratio > tolerance_percent:
            violation = cls._create_violation(
                transaction_id,
                f"Related party at {legal_form.legal_amount}",
                f"Fair value should be {economic_substance.economic_amount}",
                f"Recorded at legal amount {legal_form.legal_amount}",
                f"Should be adjusted to fair value {economic_substance.economic_amount}",
                SubstanceAssessmentSeverity.HIGH,
                f"Related party transaction recorded at {legal_form.legal_amount} but fair value is {economic_substance.economic_amount}",
                "substance_validator",
            )
            cls._log_violation(violation)
            cls._notify_constitution(violation)
            return False, violation
        return True, None

    @classmethod
    def _create_violation(
        cls,
        transaction_id: UUID,
        legal_summary: str,
        economic_summary: str,
        recorded: str,
        proper: str,
        severity: SubstanceAssessmentSeverity,
        message: str,
        detected_by: str,
    ) -> SubstanceViolation:
        return SubstanceViolation(
            violation_id=uuid4(),
            transaction_id=transaction_id,
            legal_form_summary=legal_summary,
            economic_substance_summary=economic_summary,
            recorded_treatment=recorded,
            proper_treatment=proper,
            severity=severity,
            message=message,
            detected_at=datetime.now(UTC),
            detected_by=detected_by,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            correction_journal_id=None,
        )

    @classmethod
    def _log_violation(cls, violation: SubstanceViolation) -> None:
        log_msg = f"[{violation.severity.name}] Substance over form violation: {violation.message}"
        if violation.severity.value >= SubstanceAssessmentSeverity.CRITICAL.value:
            logger.critical(log_msg)
        elif violation.severity.value >= SubstanceAssessmentSeverity.HIGH.value:
            logger.error(log_msg)
        else:
            logger.warning(log_msg)

    @classmethod
    def _notify_constitution(cls, violation: SubstanceViolation) -> None:
        try:
            supreme_law = get_supreme_law()
            const_severity = {
                SubstanceAssessmentSeverity.CATASTROPHIC: ConstitutionalSeverity.CRITICAL,
                SubstanceAssessmentSeverity.CRITICAL: ConstitutionalSeverity.HIGH,
                SubstanceAssessmentSeverity.HIGH: ConstitutionalSeverity.HIGH,
                SubstanceAssessmentSeverity.MEDIUM: ConstitutionalSeverity.MEDIUM,
                SubstanceAssessmentSeverity.LOW: ConstitutionalSeverity.LOW,
            }.get(violation.severity, ConstitutionalSeverity.MEDIUM)
            supreme_law.check_violation(
                principle=ConstitutionalPrinciple.SUBSTANCE_OVER_FORM,
                offending_module="substance_validator",
                message=violation.message,
                offending_command_id=violation.transaction_id,
            )
        except Exception as e:
            logger.error(f"Failed to notify constitution: {e}")


# === 5. AXIOM SERVICE ===


class SubstanceOverFormAxiom:
    _instance: SubstanceOverFormAxiom | None = None
    _assessments: list[SubstanceOverFormAssessment] = []
    _violations: list[SubstanceViolation] = []
    _lock = threading.Lock()

    def __new__(cls) -> SubstanceOverFormAxiom:
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
        self._assessments = []
        self._violations = []

    # ==================== REPOSITORY METHODS ====================
    def save_assessment(self, assessment: SubstanceOverFormAssessment) -> None:
        with self._lock:
            self._assessments.append(assessment)

    def get_assessments(
        self, transaction_id: UUID | None = None, limit: int = 100
    ) -> list[SubstanceOverFormAssessment]:
        result = self._assessments[-limit:]
        if transaction_id:
            result = [a for a in result if a.transaction_id == transaction_id]
        return result

    def delete_assessment(self, assessment_id: UUID) -> bool:
        with self._lock:
            for i, a in enumerate(self._assessments):
                if a.assessment_id == assessment_id:
                    self._assessments.pop(i)
                    return True
            return False

    def save_violation(self, violation: SubstanceViolation) -> None:
        with self._lock:
            self._violations.append(violation)

    def get_violations(
        self, transaction_id: UUID | None = None, unresolved_only: bool = False, limit: int = 100
    ) -> list[SubstanceViolation]:
        result = self._violations[-limit:]
        if transaction_id:
            result = [v for v in result if v.transaction_id == transaction_id]
        if unresolved_only:
            result = [v for v in result if not v.resolved]
        return result

    def resolve_violation(
        self, violation_id: UUID, resolved_by: str, correction_journal_id: UUID
    ) -> SubstanceViolation | None:
        with self._lock:
            for i, v in enumerate(self._violations):
                if v.violation_id == violation_id and not v.resolved:
                    resolved = v.resolve(resolved_by, correction_journal_id)
                    self._violations[i] = resolved
                    return resolved
            return None

    # ==================== BUSINESS METHODS ====================
    def assess_transaction(
        self,
        transaction_id: UUID,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        assessed_by: str,
        approved_by: list[str],
    ) -> SubstanceOverFormAssessment:
        is_different = (
            legal_form.legal_amount != economic_substance.economic_amount
            or legal_form.legal_ownership_transfer
            != economic_substance.risks_and_rewards_transferred
        )
        proper_treatment = (
            self._determine_proper_treatment(economic_substance.transaction_type)
            if is_different
            else "Record according to legal form"
        )
        assessment = SubstanceOverFormAssessment(
            assessment_id=uuid4(),
            transaction_id=transaction_id,
            legal_form=legal_form,
            economic_substance=economic_substance,
            is_different=is_different,
            difference_description="Legal and economic substance differ"
            if is_different
            else "No difference",
            proper_accounting_treatment=proper_treatment,
            recommended_journal_template=None,
            assessed_by=assessed_by,
            assessed_at=datetime.now(UTC),
            approved_by=approved_by,
        )
        self.save_assessment(assessment)
        return assessment

    def enforce_lease(
        self,
        transaction_id: UUID,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        raise_on_violation: bool = True,
    ) -> tuple[bool, SubstanceViolation | None]:
        is_valid, violation, hint = SubstanceOverFormValidator.validate_lease(
            legal_form, economic_substance, transaction_id
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= SubstanceAssessmentSeverity.HIGH.value
            ):
                raise SubstanceViolationError(
                    violation.message,
                    transaction_id,
                    violation.legal_form_summary,
                    violation.economic_substance_summary,
                    violation.severity,
                )
        return is_valid, violation

    def enforce_factoring(
        self,
        transaction_id: UUID,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        raise_on_violation: bool = True,
    ) -> tuple[bool, SubstanceViolation | None]:
        is_valid, violation = SubstanceOverFormValidator.validate_factoring(
            legal_form, economic_substance, transaction_id
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= SubstanceAssessmentSeverity.HIGH.value
            ):
                raise SubstanceViolationError(
                    violation.message,
                    transaction_id,
                    violation.legal_form_summary,
                    violation.economic_substance_summary,
                    violation.severity,
                )
        return is_valid, violation

    def enforce_consignment(
        self,
        transaction_id: UUID,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        raise_on_violation: bool = True,
    ) -> tuple[bool, SubstanceViolation | None]:
        is_valid, violation = SubstanceOverFormValidator.validate_consignment(
            legal_form, economic_substance, transaction_id
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= SubstanceAssessmentSeverity.HIGH.value
            ):
                raise SubstanceViolationError(
                    violation.message,
                    transaction_id,
                    violation.legal_form_summary,
                    violation.economic_substance_summary,
                    violation.severity,
                )
        return is_valid, violation

    def enforce_related_party(
        self,
        transaction_id: UUID,
        legal_form: LegalForm,
        economic_substance: EconomicSubstance,
        raise_on_violation: bool = True,
    ) -> tuple[bool, SubstanceViolation | None]:
        is_valid, violation = SubstanceOverFormValidator.validate_related_party(
            legal_form, economic_substance, transaction_id
        )
        if violation:
            self.save_violation(violation)
            if (
                raise_on_violation
                and violation.severity.value >= SubstanceAssessmentSeverity.HIGH.value
            ):
                raise SubstanceViolationError(
                    violation.message,
                    transaction_id,
                    violation.legal_form_summary,
                    violation.economic_substance_summary,
                    violation.severity,
                )
        return is_valid, violation

    @classmethod
    def _determine_proper_treatment(cls, transaction_type: SubstanceOverrideType) -> str:
        mapping = {
            SubstanceOverrideType.LEASE: "Capitalize right-of-use asset and lease liability",
            SubstanceOverrideType.SALE_AND_LEASEBACK: "Record as financing transaction",
            SubstanceOverrideType.FACTORING: "Record as secured borrowing if recourse exists",
            SubstanceOverrideType.CONSIGNMENT: "Do not record as inventory for consignee",
            SubstanceOverrideType.REPURCHASE_AGREEMENT: "Record as financing, not sale",
            SubstanceOverrideType.SPECIAL_PURPOSE_ENTITY: "Consolidate if control exists",
            SubstanceOverrideType.EQUITY_SETTLEMENT: "Classify based on substance, not legal form",
            SubstanceOverrideType.HYBRID_INSTRUMENT: "Split into equity and liability components",
            SubstanceOverrideType.RELATED_PARTY: "Adjust to fair value",
            SubstanceOverrideType.NON_MONETARY_EXCHANGE: "Record at fair value, not historical cost",
        }
        return mapping.get(transaction_type, "Follow economic substance over legal form")

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total_assessments = len(self._assessments)
            diff_assessments = len([a for a in self._assessments if a.is_different])
            total_violations = len(self._violations)
            unresolved = len([v for v in self._violations if not v.resolved])
            by_severity = {
                sev.name: len([v for v in self._violations if v.severity == sev])
                for sev in SubstanceAssessmentSeverity
            }
            by_type = {}
            for a in self._assessments:
                tt = a.economic_substance.transaction_type.name
                by_type[tt] = by_type.get(tt, 0) + 1
            return {
                "total_assessments": total_assessments,
                "assessments_with_difference": diff_assessments,
                "total_violations": total_violations,
                "unresolved_violations": unresolved,
                "by_severity": by_severity,
                "by_transaction_type": by_type,
            }

    def reset(self) -> None:
        with self._lock:
            self._assessments = []
            self._violations = []


# === 6. SINGLETON ACCESSOR ===

_substance_over_form_axiom_instance: SubstanceOverFormAxiom | None = None


def get_substance_over_form_axiom() -> SubstanceOverFormAxiom:
    global _substance_over_form_axiom_instance
    if _substance_over_form_axiom_instance is None:
        _substance_over_form_axiom_instance = SubstanceOverFormAxiom()
    return _substance_over_form_axiom_instance


# === 7. HELPER FUNCTIONS ===


def create_legal_form(
    contract_type: str,
    parties: list[str],
    legal_ownership_transfer: bool,
    legal_amount: Decimal,
    currency: str,
    contract_date: datetime,
    governing_law: str = "Indonesia",
    **contract_terms,
) -> LegalForm:
    return LegalForm(
        contract_type=contract_type,
        parties=parties,
        legal_ownership_transfer=legal_ownership_transfer,
        legal_amount=legal_amount,
        currency=currency,
        contract_date=contract_date,
        contract_terms=contract_terms,
        governing_law=governing_law,
    )


def create_economic_substance(
    transaction_type: SubstanceOverrideType,
    risks_and_rewards_transferred: bool,
    control_transferred: bool,
    effective_ownership: str,
    economic_amount: Decimal,
    economic_currency: str,
    effective_date: datetime,
    reasoning: str,
    supporting_evidence: list[str] | None = None,
) -> EconomicSubstance:
    return EconomicSubstance(
        transaction_type=transaction_type,
        risks_and_rewards_transferred=risks_and_rewards_transferred,
        control_transferred=control_transferred,
        effective_ownership=effective_ownership,
        economic_amount=economic_amount,
        economic_currency=economic_currency,
        effective_date=effective_date,
        reasoning=reasoning,
        supporting_evidence=supporting_evidence or [],
    )


def get_substance_type_from_string(type_str: str) -> SubstanceOverrideType:
    mapping = {
        "LEASE": SubstanceOverrideType.LEASE,
        "SALE_AND_LEASEBACK": SubstanceOverrideType.SALE_AND_LEASEBACK,
        "FACTORING": SubstanceOverrideType.FACTORING,
        "CONSIGNMENT": SubstanceOverrideType.CONSIGNMENT,
        "REPURCHASE_AGREEMENT": SubstanceOverrideType.REPURCHASE_AGREEMENT,
        "SPECIAL_PURPOSE_ENTITY": SubstanceOverrideType.SPECIAL_PURPOSE_ENTITY,
        "EQUITY_SETTLEMENT": SubstanceOverrideType.EQUITY_SETTLEMENT,
        "HYBRID_INSTRUMENT": SubstanceOverrideType.HYBRID_INSTRUMENT,
        "RELATED_PARTY": SubstanceOverrideType.RELATED_PARTY,
        "NON_MONETARY_EXCHANGE": SubstanceOverrideType.NON_MONETARY_EXCHANGE,
    }
    return mapping.get(type_str.upper(), SubstanceOverrideType.LEASE)


__all__ = [
    "EconomicSubstance",
    "LeaseClassification",
    "LegalForm",
    "SubstanceAssessmentSeverity",
    "SubstanceOverFormAssessment",
    "SubstanceOverFormAxiom",
    "SubstanceOverFormError",
    "SubstanceOverFormValidator",
    "SubstanceOverrideType",
    "SubstanceViolation",
    "SubstanceViolationError",
    "create_economic_substance",
    "create_legal_form",
    "get_substance_over_form_axiom",
    "get_substance_type_from_string",
]
