#!/usr/bin/env python3
"""
Module: risk_assessor.py
Layer: 5 - Domain / Intent
Responsibility: Menilai risiko intent (AML, fraud, dll.).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, auto
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    get_immutable_intent_record_service,
)

logger = logging.getLogger(__name__)


class RiskCategory(Enum):
    AML = "aml"
    FRAUD = "fraud"
    COMPLIANCE = "compliance"
    CREDIT = "credit"
    OPERATIONAL = "operational"
    REPUTATIONAL = "reputational"
    TAX = "tax"

    @classmethod
    def from_string(cls, value: str) -> RiskCategory:
        for cat in cls:
            if cat.value == value.lower():
                return cat
        raise ValueError(f"Unknown RiskCategory: {value}")


class RiskLevel(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_int(cls, value: int) -> RiskLevel:
        for level in cls:
            if level.value == value:
                return level
        return cls.LOW

    def requires_approval(self) -> bool:
        return self in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def requires_dual_control(self) -> bool:
        return self == RiskLevel.CRITICAL


class RiskAssessmentStatus(Enum):
    PENDING = auto()
    ASSESSED = auto()
    NEEDS_REVIEW = auto()
    ESCALATED = auto()
    APPROVED = auto()
    REJECTED = auto()

    @classmethod
    def from_string(cls, value: str) -> RiskAssessmentStatus:
        try:
            return cls[value.upper()]
        except KeyError:
            raise ValueError(f"Unknown RiskAssessmentStatus: {value}")


@dataclass
class RiskFactor:
    category: RiskCategory
    description: str
    score: float
    weight: float = 1.0
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if not isinstance(self.category, RiskCategory):
            raise ValueError("category must be RiskCategory")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if self.weight <= 0:
            raise ValueError("weight must be positive")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "category": self.category.value,
            "score": self.score,
            "weight": self.weight,
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
    def create(self, created_by: str) -> RiskFactor:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> RiskFactor:
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("version"):
                data[key] = value
        new_factor = RiskFactor.from_dict(data)
        new_factor.version = self.version + 1
        new_factor._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_factor

    def delete(self, deleted_by: str, reason: str | None = None) -> RiskFactor:
        self._record_audit("DELETE", deleted_by, {"reason": reason})
        return self

    def restore(self, restored_by: str) -> RiskFactor:
        self._record_audit("RESTORE", restored_by, {})
        return self

    def activate(self, activated_by: str) -> RiskFactor:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> RiskFactor:
        return self

    def lock(self, locked_by: str, reason: str) -> RiskFactor:
        return self

    def unlock(self, unlocked_by: str) -> RiskFactor:
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
            "category": self.category.value,
            "description": self.description,
            "score": self.score,
            "weight": self.weight,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskFactor:
        return cls(
            category=RiskCategory.from_string(data["category"]),
            description=data["description"],
            score=data["score"],
            weight=data.get("weight", 1.0),
            version=data.get("version", 1),
        )

    def clone(self) -> RiskFactor:
        return RiskFactor(
            category=self.category,
            description=self.description,
            score=self.score,
            weight=self.weight,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "category": self.category.value,
            "score": self.score,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RiskFactor:
        new_factor = self._copy()
        new_factor.version = self.version + 1
        new_factor._record_audit("TOUCH", touched_by, {})
        return new_factor

    def _copy(self) -> RiskFactor:
        return RiskFactor(
            category=self.category,
            description=self.description,
            score=self.score,
            weight=self.weight,
            version=self.version,
        )

    def weighted_score(self) -> float:
        return self.score * self.weight


@dataclass
class RiskAssessment:
    assessment_id: UUID
    intent_id: UUID
    assessed_at: datetime
    assessed_by: str
    overall_risk: RiskLevel
    risk_score: float
    factors: list[RiskFactor]
    recommendations: list[str]
    status: RiskAssessmentStatus
    requires_approval: bool
    requires_dual_control: bool
    notes: str = ""
    version: int = 1
    cryptographic_hash: str = ""

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        if not self.cryptographic_hash:
            object.__setattr__(self, "cryptographic_hash", self.compute_hash())
        self._take_snapshot()
        self._record_audit("CREATE", self.assessed_by, {})

    def _validate(self) -> None:
        if not isinstance(self.assessment_id, UUID):
            raise ValueError("assessment_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(self.assessed_at, datetime):
            raise ValueError("assessed_at must be datetime")
        if not self.assessed_by:
            raise ValueError("assessed_by cannot be empty")
        if not isinstance(self.overall_risk, RiskLevel):
            raise ValueError("overall_risk must be RiskLevel")
        if not 0 <= self.risk_score <= 100:
            raise ValueError("risk_score must be between 0 and 100")
        if not isinstance(self.factors, list):
            raise ValueError("factors must be list")
        if not isinstance(self.recommendations, list):
            raise ValueError("recommendations must be list")
        if not isinstance(self.status, RiskAssessmentStatus):
            raise ValueError("status must be RiskAssessmentStatus")
        if not isinstance(self.requires_approval, bool):
            raise ValueError("requires_approval must be bool")
        if not isinstance(self.requires_dual_control, bool):
            raise ValueError("requires_dual_control must be bool")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def compute_hash(self) -> str:
        content = {
            "assessment_id": str(self.assessment_id),
            "intent_id": str(self.intent_id),
            "assessed_by": self.assessed_by,
            "assessed_at": self.assessed_at.isoformat(),
            "overall_risk": self.overall_risk.name,
            "risk_score": self.risk_score,
            "status": self.status.name,
            "requires_approval": self.requires_approval,
            "requires_dual_control": self.requires_dual_control,
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "assessment_id": str(self.assessment_id),
            "intent_id": str(self.intent_id),
            "overall_risk": self.overall_risk.name,
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
                "assessment_id": str(self.assessment_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> RiskAssessment:
        return self

    def update(self, updated_by: str, **kwargs) -> RiskAssessment:
        # Hanya status dan notes yang bisa diupdate
        new_status = kwargs.get("status", self.status)
        new_notes = kwargs.get("notes", self.notes)
        new_assessment = RiskAssessment(
            assessment_id=self.assessment_id,
            intent_id=self.intent_id,
            assessed_at=self.assessed_at,
            assessed_by=self.assessed_by,
            overall_risk=self.overall_risk,
            risk_score=self.risk_score,
            factors=self.factors.copy(),
            recommendations=self.recommendations.copy(),
            status=new_status,
            requires_approval=self.requires_approval,
            requires_dual_control=self.requires_dual_control,
            notes=new_notes[:500],
            version=self.version + 1,
        )
        new_assessment._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_assessment

    def delete(self, deleted_by: str, reason: str | None = None) -> RiskAssessment:
        raise AttributeError("RiskAssessment cannot be deleted")

    def restore(self, restored_by: str) -> RiskAssessment:
        raise AttributeError("RiskAssessment cannot be restored")

    def activate(self, activated_by: str) -> RiskAssessment:
        if self.status == RiskAssessmentStatus.PENDING:
            return self.update(activated_by, status=RiskAssessmentStatus.ASSESSED)
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> RiskAssessment:
        if self.status == RiskAssessmentStatus.ASSESSED:
            return self.update(deactivated_by, status=RiskAssessmentStatus.NEEDS_REVIEW)
        return self

    def lock(self, locked_by: str, reason: str) -> RiskAssessment:
        return self

    def unlock(self, unlocked_by: str) -> RiskAssessment:
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
            "intent_id": str(self.intent_id),
            "assessed_at": self.assessed_at.isoformat(),
            "assessed_by": self.assessed_by,
            "overall_risk": self.overall_risk.name,
            "risk_score": self.risk_score,
            "factors": [f.to_dict() for f in self.factors],
            "recommendations": self.recommendations,
            "status": self.status.name,
            "requires_approval": self.requires_approval,
            "requires_dual_control": self.requires_dual_control,
            "notes": self.notes,
            "version": self.version,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskAssessment:
        factors = [RiskFactor.from_dict(f) for f in data.get("factors", [])]
        return cls(
            assessment_id=UUID(data["assessment_id"]),
            intent_id=UUID(data["intent_id"]),
            assessed_at=datetime.fromisoformat(data["assessed_at"]),
            assessed_by=data["assessed_by"],
            overall_risk=RiskLevel[data["overall_risk"]],
            risk_score=data["risk_score"],
            factors=factors,
            recommendations=data.get("recommendations", []),
            status=RiskAssessmentStatus[data["status"]],
            requires_approval=data["requires_approval"],
            requires_dual_control=data["requires_dual_control"],
            notes=data.get("notes", ""),
            version=data.get("version", 1),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> RiskAssessment:
        return RiskAssessment(
            assessment_id=uuid4(),
            intent_id=self.intent_id,
            assessed_at=datetime.now(UTC),
            assessed_by=self.assessed_by,
            overall_risk=self.overall_risk,
            risk_score=self.risk_score,
            factors=[f.clone() for f in self.factors],
            recommendations=self.recommendations.copy(),
            status=RiskAssessmentStatus.PENDING,
            requires_approval=self.requires_approval,
            requires_dual_control=self.requires_dual_control,
            notes=self.notes,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "assessment_id": str(self.assessment_id),
            "intent_id": str(self.intent_id),
            "overall_risk": self.overall_risk.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RiskAssessment:
        self._record_audit("TOUCH", touched_by, {})
        return self

    def is_actionable(self) -> bool:
        return self.status == RiskAssessmentStatus.ASSESSED


class RiskAssessor:
    _instance: RiskAssessor | None = None
    __slots__ = ("_assessments", "_initialized", "_lock", "_record_service")

    def __new__(cls) -> RiskAssessor:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._record_service = get_immutable_intent_record_service()
        self._assessments: dict[UUID, RiskAssessment] = {}
        self._lock = threading.RLock()

    # ==================== RISK ASSESSMENT METHODS ====================
    def _assess_aml_risk(self, intent: ImmutableIntentRecord) -> RiskFactor | None:
        score = 0.0
        parts = []
        # Get amount as Decimal, default to 0
        amount = intent.data.get("amount", Decimal(0))
        if not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount))
            except Exception:
                amount = Decimal(0)

        if amount >= Decimal("1000000000"):  # 1B
            score += 50
            parts.append("Very large transaction amount (>1B)")
        elif amount >= Decimal("100000000"):  # 100M
            score += 30
            parts.append("Large transaction amount (>100M)")
        elif amount >= Decimal("50000000"):   # 50M
            score += 15
            parts.append("Moderate transaction amount (>50M)")

        if intent.data.get("is_international", False):
            score += 20
            parts.append("International transaction")
        if intent.data.get("payment_method", "").upper() == "CASH":
            score += 35
            parts.append("Cash transaction - high AML risk")
        if intent.data.get("is_shell_company", False):
            score += 40
            parts.append("Shell company involvement")

        if parts:
            return RiskFactor(
                category=RiskCategory.AML,
                description="; ".join(parts),
                score=min(score, 100),
                weight=1.5,
            )
        return None

    def _assess_fraud_risk(self, intent: ImmutableIntentRecord) -> RiskFactor | None:
        score = 0.0
        parts = []
        amount = intent.data.get("amount", Decimal(0))
        if not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount))
            except Exception:
                amount = Decimal(0)

        # Check for round number structuring (only if amount > 10M and divisible by 1M)
        if amount > Decimal("10000000") and amount % Decimal("1000000") == 0:
            score += 15
            parts.append("Round number amount (potential structuring)")

        if intent.data.get("is_rush", False):
            score += 15
            parts.append("Rush/expedited transaction")
        if intent.data.get("is_duplicate_suspected", False):
            score += 25
            parts.append("Potential duplicate transaction")
        if intent.data.get("unusual_pattern", False):
            score += 20
            parts.append("Unusual payment pattern")
        if intent.data.get("beneficiary_mismatch", False):
            score += 30
            parts.append("Beneficiary mismatch with invoice")

        if parts:
            return RiskFactor(
                category=RiskCategory.FRAUD,
                description="; ".join(parts),
                score=min(score, 100),
                weight=1.2,
            )
        return None

    def _assess_compliance_risk(self, intent: ImmutableIntentRecord) -> RiskFactor | None:
        score = 0.0
        parts = []
        transaction_type = intent.data.get("transaction_type", "").upper()
        restricted_types = ["FOREIGN_EXCHANGE", "CROSS_BORDER", "DERIVATIVE", "HEDGING"]
        if transaction_type in restricted_types:
            score += 25
            parts.append(f"Regulated transaction type: {transaction_type}")
        if not intent.data.get("source_document_ref"):
            score += 20
            parts.append("Missing source document reference")
        if intent.data.get("is_intercompany", False):
            score += 15
            parts.append("Intercompany transaction (requires transfer pricing)")
        if intent.data.get("is_related_party", False):
            score += 20
            parts.append("Related party transaction - requires disclosure")
        if intent.data.get("requires_regulatory_approval", False):
            score += 30
            parts.append("Requires regulatory approval")
        if parts:
            return RiskFactor(
                category=RiskCategory.COMPLIANCE,
                description="; ".join(parts),
                score=min(score, 100),
                weight=1.3,
            )
        return None

    def _assess_credit_risk(self, intent: ImmutableIntentRecord) -> RiskFactor | None:
        if intent.intent_type.name not in ["CREATE_INVOICE", "CREATE_JOURNAL"]:
            return None
        if not intent.data.get("customer_id"):
            return None
        score = 10.0
        parts = ["Credit transaction"]

        # Get monetary values as Decimal
        credit_limit = intent.data.get("customer_credit_limit", Decimal(0))
        if not isinstance(credit_limit, Decimal):
            try:
                credit_limit = Decimal(str(credit_limit))
            except Exception:
                credit_limit = Decimal(0)

        current_balance = intent.data.get("customer_current_balance", Decimal(0))
        if not isinstance(current_balance, Decimal):
            try:
                current_balance = Decimal(str(current_balance))
            except Exception:
                current_balance = Decimal(0)

        transaction_amount = intent.data.get("amount", Decimal(0))
        if not isinstance(transaction_amount, Decimal):
            try:
                transaction_amount = Decimal(str(transaction_amount))
            except Exception:
                transaction_amount = Decimal(0)

        if credit_limit > 0 and transaction_amount > 0:
            utilization = (current_balance + transaction_amount) / credit_limit
            if utilization > Decimal("0.9"):
                score += 30
                parts.append(f"Credit limit nearly exhausted ({utilization:.0%})")
            elif utilization > Decimal("0.7"):
                score += 15
                parts.append(f"High credit utilization ({utilization:.0%})")

        if intent.data.get("has_overdue_payments", False):
            score += 25
            parts.append("Customer has overdue payments")

        payment_rating = intent.data.get("customer_payment_rating", "GOOD")
        if payment_rating == "POOR":
            score += 30
            parts.append("Poor payment history")
        elif payment_rating == "FAIR":
            score += 15
            parts.append("Fair payment history")

        return RiskFactor(
            category=RiskCategory.CREDIT,
            description="; ".join(parts),
            score=min(score, 100),
            weight=1.0,
        )

    def _assess_tax_risk(self, intent: ImmutableIntentRecord) -> RiskFactor | None:
        score = 0.0
        parts = []
        if intent.data.get("tax_avoidance_indicator", False):
            score += 40
            parts.append("Potential tax avoidance structure")
        if not intent.data.get("tax_id"):
            score += 20
            parts.append("Missing tax identification number")
        tax_jurisdiction = intent.data.get("tax_jurisdiction", "")
        if tax_jurisdiction and tax_jurisdiction not in ["IDN", "DOMESTIC"]:
            score += 15
            parts.append(f"Foreign tax jurisdiction: {tax_jurisdiction}")

        # Get amount as Decimal for transfer pricing risk
        amount = intent.data.get("amount", Decimal(0))
        if not isinstance(amount, Decimal):
            try:
                amount = Decimal(str(amount))
            except Exception:
                amount = Decimal(0)

        if intent.data.get("is_intercompany", False) and amount > Decimal("1000000000"):
            score += 35
            parts.append("High-value intercompany transaction - transfer pricing risk")

        if parts:
            return RiskFactor(
                category=RiskCategory.TAX,
                description="; ".join(parts),
                score=min(score, 100),
                weight=1.1,
            )
        return None

    def _generate_recommendations(
        self, factors: list[RiskFactor], overall_risk: RiskLevel
    ) -> list[str]:
        recommendations = []
        if overall_risk == RiskLevel.CRITICAL:
            recommendations = [
                "Escalate to compliance committee for immediate review",
                "Require dual control approval before execution",
                "Perform enhanced due diligence (EDD)",
                "Document justification with board-level approval",
            ]
        elif overall_risk == RiskLevel.HIGH:
            recommendations = [
                "Require managerial approval before execution",
                "Document justification for transaction",
                "Perform additional verification on counterparty",
            ]
        elif overall_risk == RiskLevel.MEDIUM:
            recommendations = [
                "Standard review required",
                "Keep documentation for audit trail",
            ]
        for factor in factors:
            if factor.category == RiskCategory.AML and factor.score > 50:
                recommendations.append(
                    f"AML specialist review required: {factor.description[:100]}"
                )
            elif factor.category == RiskCategory.COMPLIANCE and factor.score > 40:
                recommendations.append(f"Compliance review required: {factor.description[:100]}")
            elif factor.category == RiskCategory.FRAUD and factor.score > 50:
                recommendations.append(
                    f"Fraud investigation recommended: {factor.description[:100]}"
                )
        # Remove duplicates
        seen = set()
        unique = []
        for rec in recommendations:
            if rec not in seen:
                seen.add(rec)
                unique.append(rec)
        return unique[:10]

    def assess_intent(self, intent_id: UUID, assessed_by: str) -> RiskAssessment:
        intent = self._record_service.get(intent_id)
        if not intent:
            raise ValueError(f"Intent {intent_id} not found")

        factors = []
        for assessor in [
            self._assess_aml_risk,
            self._assess_fraud_risk,
            self._assess_compliance_risk,
            self._assess_credit_risk,
            self._assess_tax_risk,
        ]:
            f = assessor(intent)
            if f:
                factors.append(f)

        total_weighted = sum(f.weighted_score() for f in factors)
        total_weight = sum(f.weight for f in factors)
        overall_score = total_weighted / total_weight if total_weight > 0 else 0.0

        if overall_score >= 75:
            overall_risk = RiskLevel.CRITICAL
        elif overall_score >= 50:
            overall_risk = RiskLevel.HIGH
        elif overall_score >= 25:
            overall_risk = RiskLevel.MEDIUM
        else:
            overall_risk = RiskLevel.LOW

        recommendations = self._generate_recommendations(factors, overall_risk)
        requires_approval = overall_risk.requires_approval()
        requires_dual_control = overall_risk.requires_dual_control()

        assessment = RiskAssessment(
            assessment_id=uuid4(),
            intent_id=intent_id,
            assessed_at=datetime.now(UTC),
            assessed_by=assessed_by,
            overall_risk=overall_risk,
            risk_score=round(overall_score, 2),
            factors=factors,
            recommendations=recommendations,
            status=RiskAssessmentStatus.ASSESSED,
            requires_approval=requires_approval,
            requires_dual_control=requires_dual_control,
        )

        with self._lock:
            self._assessments[intent_id] = assessment

        logger.info(
            f"Risk assessment for intent {intent_id}: {overall_risk.name} (score: {overall_score:.2f}, requires_approval={requires_approval})"
        )
        return assessment

    def get_assessment(self, intent_id: UUID) -> RiskAssessment | None:
        with self._lock:
            return self._assessments.get(intent_id)

    def update_assessment_status(
        self, intent_id: UUID, new_status: RiskAssessmentStatus, updated_by: str, notes: str = ""
    ) -> RiskAssessment | None:
        with self._lock:
            assessment = self._assessments.get(intent_id)
            if not assessment:
                return None
            updated = assessment.update(updated_by, status=new_status, notes=notes)
            self._assessments[intent_id] = updated
            return updated

    # ==================== REPOSITORY METHODS ====================
    def save_assessment(self, assessment: RiskAssessment) -> None:
        with self._lock:
            self._assessments[assessment.intent_id] = assessment

    def get_all_assessments(self) -> list[RiskAssessment]:
        with self._lock:
            return list(self._assessments.values())

    def delete_assessment(self, intent_id: UUID) -> bool:
        with self._lock:
            if intent_id in self._assessments:
                del self._assessments[intent_id]
                return True
            return False

    def count_assessments(self) -> int:
        with self._lock:
            return len(self._assessments)

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._assessments)
            if total == 0:
                return {"total_assessments": 0}
            by_risk = {}
            by_status = {}
            total_score = 0.0
            for assessment in self._assessments.values():
                by_risk[assessment.overall_risk.name] = (
                    by_risk.get(assessment.overall_risk.name, 0) + 1
                )
                by_status[assessment.status.name] = by_status.get(assessment.status.name, 0) + 1
                total_score += assessment.risk_score
            return {
                "total_assessments": total,
                "by_risk_level": by_risk,
                "by_status": by_status,
                "average_risk_score": round(total_score / total, 2),
                "requires_approval_count": len(
                    [a for a in self._assessments.values() if a.requires_approval]
                ),
                "requires_dual_control_count": len(
                    [a for a in self._assessments.values() if a.requires_dual_control]
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._assessments = {}


def get_risk_assessor() -> RiskAssessor:
    global _risk_assessor_instance
    if _risk_assessor_instance is None:
        _risk_assessor_instance = RiskAssessor()
    return _risk_assessor_instance


_risk_assessor_instance: RiskAssessor | None = None

__all__ = [
    "RiskAssessment",
    "RiskAssessmentStatus",
    "RiskAssessor",
    "RiskCategory",
    "RiskFactor",
    "RiskLevel",
    "get_risk_assessor",
]
