#!/usr/bin/env python3
"""
Module: materiality_evaluator.py
Layer: 5 - Domain / Intent
Responsibility: Mengevaluasi materialitas intent.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intent.immutable_record import (
    ImmutableIntentRecord,
    get_immutable_intent_record_service,
)
from domain.intent.risk_assessor import RiskLevel, get_risk_assessor

logger = logging.getLogger(__name__)


class MaterialityLevel(Enum):
    IMMATERIAL = 1
    MATERIAL = 2
    HIGHLY_MATERIAL = 3
    CRITICAL = 4


class MaterialityDimension(Enum):
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    BOTH = "both"


@dataclass
class MaterialityThreshold:
    level: MaterialityLevel
    min_amount: Decimal
    max_amount: Decimal
    requires_approval: bool
    required_approvers: int
    required_documentation: list[str]
    escalation_level: str | None = None
    version: int = 1

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()
        self._record_audit("CREATE", "system", {})

    def _validate(self) -> None:
        if not isinstance(self.level, MaterialityLevel):
            raise ValueError("level must be MaterialityLevel")
        if not isinstance(self.min_amount, Decimal):
            raise ValueError("min_amount must be Decimal")
        if not isinstance(self.max_amount, Decimal):
            raise ValueError("max_amount must be Decimal")
        if self.min_amount < 0:
            raise ValueError("min_amount cannot be negative")
        # Perbandingan aman untuk Decimal('inf')
        if self.max_amount != Decimal("inf") and self.max_amount < self.min_amount:
            raise ValueError("max_amount must be >= min_amount")
        if not isinstance(self.required_approvers, int) or self.required_approvers < 0:
            raise ValueError("required_approvers must be non-negative integer")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "level": self.level.name,
            "min_amount": str(self.min_amount),
            "max_amount": str(self.max_amount),
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
    def create(self, created_by: str) -> MaterialityThreshold:
        self._record_audit("CREATE", created_by, {})
        return self

    def update(self, updated_by: str, **kwargs) -> MaterialityThreshold:
        data = self.to_dict()
        for key, value in kwargs.items():
            if hasattr(self, key) and key not in ("version", "_snapshots", "_audit_trail"):
                data[key] = value
        new_threshold = MaterialityThreshold.from_dict(data)
        new_threshold.version = self.version + 1
        new_threshold._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_threshold

    def delete(self, deleted_by: str, reason: str | None = None) -> MaterialityThreshold:
        self._record_audit("DELETE", deleted_by, {"reason": reason})
        return self

    def restore(self, restored_by: str) -> MaterialityThreshold:
        self._record_audit("RESTORE", restored_by, {})
        return self

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
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "level": self.level.name,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.name,
            "min_amount": str(self.min_amount),
            "max_amount": str(self.max_amount) if self.max_amount != Decimal("inf") else "inf",
            "requires_approval": self.requires_approval,
            "required_approvers": self.required_approvers,
            "required_documentation": self.required_documentation,
            "escalation_level": self.escalation_level,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialityThreshold:
        max_amount = data["max_amount"]
        return cls(
            level=MaterialityLevel[data["level"]],
            min_amount=Decimal(data["min_amount"]),
            max_amount=Decimal("inf") if max_amount == "inf" else Decimal(max_amount),
            requires_approval=data["requires_approval"],
            required_approvers=data["required_approvers"],
            required_documentation=data.get("required_documentation", []),
            escalation_level=data.get("escalation_level"),
            version=data.get("version", 1),
        )

    def clone(self) -> MaterialityThreshold:
        return MaterialityThreshold(
            level=self.level,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            requires_approval=self.requires_approval,
            required_approvers=self.required_approvers,
            required_documentation=self.required_documentation.copy(),
            escalation_level=self.escalation_level,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "level": self.level.name,
            "min_amount": str(self.min_amount),
            "max_amount": str(self.max_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MaterialityThreshold:
        new_threshold = self._copy()
        new_threshold.version = self.version + 1
        new_threshold._record_audit("TOUCH", touched_by, {})
        return new_threshold

    def _copy(self) -> MaterialityThreshold:
        return MaterialityThreshold(
            level=self.level,
            min_amount=self.min_amount,
            max_amount=self.max_amount,
            requires_approval=self.requires_approval,
            required_approvers=self.required_approvers,
            required_documentation=self.required_documentation.copy(),
            escalation_level=self.escalation_level,
            version=self.version,
        )

    def contains_amount(self, amount: Decimal) -> bool:
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        return self.min_amount <= amount <= self.max_amount


@dataclass
class MaterialityEvaluation:
    evaluation_id: UUID
    intent_id: UUID
    evaluated_at: datetime
    evaluated_by: str
    materiality_level: MaterialityLevel
    quantitative_score: Decimal
    qualitative_factors: list[str]
    justification: str
    requires_board_approval: bool
    requires_disclosure: bool
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
        self._record_audit("CREATE", self.evaluated_by, {})

    def _validate(self) -> None:
        if not isinstance(self.evaluation_id, UUID):
            raise ValueError("evaluation_id must be UUID")
        if not isinstance(self.intent_id, UUID):
            raise ValueError("intent_id must be UUID")
        if not isinstance(self.evaluated_at, datetime):
            raise ValueError("evaluated_at must be datetime")
        if not self.evaluated_by:
            raise ValueError("evaluated_by cannot be empty")
        if not isinstance(self.materiality_level, MaterialityLevel):
            raise ValueError("materiality_level must be MaterialityLevel")
        if not isinstance(self.quantitative_score, Decimal):
            raise ValueError("quantitative_score must be Decimal")
        if self.quantitative_score < 0 or self.quantitative_score > 100:
            raise ValueError("quantitative_score must be between 0 and 100")
        if self.version < 1:
            raise ValueError("version must be >= 1")

    def compute_hash(self) -> str:
        content = {
            "evaluation_id": str(self.evaluation_id),
            "intent_id": str(self.intent_id),
            "evaluated_by": self.evaluated_by,
            "evaluated_at": self.evaluated_at.isoformat(),
            "materiality_level": self.materiality_level.name,
            "quantitative_score": str(self.quantitative_score),
            "requires_board_approval": self.requires_board_approval,
            "requires_disclosure": self.requires_disclosure,
            "version": self.version,
        }
        return hashlib.sha3_256(json.dumps(content, sort_keys=True).encode()).hexdigest()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "evaluation_id": str(self.evaluation_id),
            "intent_id": str(self.intent_id),
            "materiality_level": self.materiality_level.name,
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
                "evaluation_id": str(self.evaluation_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> MaterialityEvaluation:
        return self

    def update(self, updated_by: str, **kwargs) -> MaterialityEvaluation:
        raise AttributeError("MaterialityEvaluation is immutable")

    def delete(self, deleted_by: str, reason: str | None = None) -> MaterialityEvaluation:
        raise AttributeError("MaterialityEvaluation cannot be deleted")

    def restore(self, restored_by: str) -> MaterialityEvaluation:
        raise AttributeError("MaterialityEvaluation cannot be restored")

    def activate(self, activated_by: str) -> MaterialityEvaluation:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> MaterialityEvaluation:
        return self

    def lock(self, locked_by: str, reason: str) -> MaterialityEvaluation:
        return self

    def unlock(self, unlocked_by: str) -> MaterialityEvaluation:
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
            "evaluation_id": str(self.evaluation_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": str(self.evaluation_id),
            "intent_id": str(self.intent_id),
            "evaluated_at": self.evaluated_at.isoformat(),
            "evaluated_by": self.evaluated_by,
            "materiality_level": self.materiality_level.name,
            "quantitative_score": str(self.quantitative_score),
            "qualitative_factors": self.qualitative_factors,
            "justification": self.justification,
            "requires_board_approval": self.requires_board_approval,
            "requires_disclosure": self.requires_disclosure,
            "notes": self.notes,
            "version": self.version,
            "cryptographic_hash": self.cryptographic_hash[:16] + "...",
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialityEvaluation:
        return cls(
            evaluation_id=UUID(data["evaluation_id"]),
            intent_id=UUID(data["intent_id"]),
            evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
            evaluated_by=data["evaluated_by"],
            materiality_level=MaterialityLevel[data["materiality_level"]],
            quantitative_score=Decimal(data["quantitative_score"]),
            qualitative_factors=data.get("qualitative_factors", []),
            justification=data.get("justification", ""),
            requires_board_approval=data["requires_board_approval"],
            requires_disclosure=data["requires_disclosure"],
            notes=data.get("notes", ""),
            version=data.get("version", 1),
            cryptographic_hash=data.get("cryptographic_hash", ""),
        )

    def clone(self) -> MaterialityEvaluation:
        return MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=self.intent_id,
            evaluated_at=datetime.now(UTC),
            evaluated_by=self.evaluated_by,
            materiality_level=self.materiality_level,
            quantitative_score=self.quantitative_score,
            qualitative_factors=self.qualitative_factors.copy(),
            justification=self.justification,
            requires_board_approval=self.requires_board_approval,
            requires_disclosure=self.requires_disclosure,
            notes=self.notes,
            version=1,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "evaluation_id": str(self.evaluation_id),
            "materiality_level": self.materiality_level.name,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> MaterialityEvaluation:
        self._record_audit("TOUCH", touched_by, {})
        return self


DEFAULT_MATERIALITY_THRESHOLDS = [
    MaterialityThreshold(
        MaterialityLevel.IMMATERIAL, Decimal(0), Decimal(10_000_000), False, 0, []
    ),
    MaterialityThreshold(
        MaterialityLevel.MATERIAL,
        Decimal(10_000_000),
        Decimal(100_000_000),
        True,
        1,
        ["justification_memo", "supporting_calculation"],
    ),
    MaterialityThreshold(
        MaterialityLevel.HIGHLY_MATERIAL,
        Decimal(100_000_000),
        Decimal(1_000_000_000),
        True,
        2,
        ["justification_memo", "supporting_calculation", "management_approval"],
        "CFO",
    ),
    MaterialityThreshold(
        MaterialityLevel.CRITICAL,
        Decimal(1_000_000_000),
        Decimal("inf"),
        True,
        2,
        ["justification_memo", "supporting_calculation", "board_approval"],
        "BOARD",
    ),
]


class MaterialityEvaluator:
    _instance: MaterialityEvaluator | None = None

    def __new__(cls) -> MaterialityEvaluator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._record_service = get_immutable_intent_record_service()
        self._risk_assessor = get_risk_assessor()
        self._thresholds: list[MaterialityThreshold] = DEFAULT_MATERIALITY_THRESHOLDS.copy()
        self._evaluations: dict[UUID, MaterialityEvaluation] = {}
        self._lock = threading.RLock()

    # ==================== THRESHOLD MANAGEMENT ====================
    def set_thresholds(self, thresholds: list[MaterialityThreshold]) -> None:
        with self._lock:
            self._thresholds = sorted(thresholds, key=lambda t: t.min_amount)

    def get_threshold_for_amount(self, amount: Decimal) -> MaterialityThreshold:
        for threshold in self._thresholds:
            if threshold.contains_amount(amount):
                return threshold
        return self._thresholds[-1]

    def add_threshold(self, threshold: MaterialityThreshold) -> None:
        with self._lock:
            self._thresholds.append(threshold)
            self._thresholds.sort(key=lambda t: t.min_amount)

    def get_all_thresholds(self) -> list[MaterialityThreshold]:
        return self._thresholds.copy()

    # ==================== EVALUATION METHODS ====================
    def evaluate(self, intent_id: UUID, evaluated_by: str) -> MaterialityEvaluation:
        intent = self._record_service.get(intent_id)
        if not intent:
            raise ValueError(f"Intent {intent_id} not found")
        amount = Decimal(str(intent.data.get("amount", 0)))
        threshold = self.get_threshold_for_amount(amount)
        # quantitative_score: persentase dari batas atas (cap 100)
        if threshold.max_amount != Decimal("inf"):
            quantitative_score = (amount / threshold.max_amount) * 100
        else:
            quantitative_score = Decimal(100)
        quantitative_score = min(Decimal(100), max(Decimal(0), quantitative_score))

        qualitative_factors = self._identify_qualitative_factors(intent)
        materiality_level = threshold.level
        if qualitative_factors:
            if materiality_level == MaterialityLevel.IMMATERIAL:
                materiality_level = MaterialityLevel.MATERIAL
            elif materiality_level == MaterialityLevel.MATERIAL and len(qualitative_factors) >= 2:
                materiality_level = MaterialityLevel.HIGHLY_MATERIAL

        requires_board_approval = materiality_level == MaterialityLevel.CRITICAL
        requires_disclosure = materiality_level in (
            MaterialityLevel.MATERIAL,
            MaterialityLevel.HIGHLY_MATERIAL,
            MaterialityLevel.CRITICAL,
        )
        justification = self._generate_justification(intent, amount, threshold, qualitative_factors)

        evaluation = MaterialityEvaluation(
            evaluation_id=uuid4(),
            intent_id=intent_id,
            evaluated_at=datetime.now(UTC),
            evaluated_by=evaluated_by,
            materiality_level=materiality_level,
            quantitative_score=quantitative_score,
            qualitative_factors=qualitative_factors,
            justification=justification,
            requires_board_approval=requires_board_approval,
            requires_disclosure=requires_disclosure,
        )
        with self._lock:
            self._evaluations[intent_id] = evaluation
        logger.info(
            f"Materiality evaluation for intent {intent_id}: {materiality_level.name} (amount: {amount})"
        )
        return evaluation

    def _identify_qualitative_factors(self, intent: ImmutableIntentRecord) -> list[str]:
        factors = []
        if intent.data.get("is_correction") or intent.data.get("is_amendment"):
            factors.append("Correction/amendment of prior period")
        if intent.data.get("is_related_party"):
            factors.append("Related party transaction")
        if intent.data.get("affects_compliance"):
            factors.append("Affects regulatory compliance")
        if intent.data.get("affects_covenants"):
            factors.append("May affect debt covenant compliance")
        risk = self._risk_assessor.get_assessment(intent.intent_id)
        if risk and risk.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            factors.append(f"High risk transaction ({risk.overall_risk.name})")
        if intent.data.get("reverses_trend"):
            factors.append("Reverses earnings trend")
        return factors

    def _generate_justification(
        self,
        intent: ImmutableIntentRecord,
        amount: Decimal,
        threshold: MaterialityThreshold,
        qualitative_factors: list[str],
    ) -> str:
        parts = [f"Transaction amount: {amount}"]
        if threshold.max_amount != Decimal("inf"):
            parts.append(f"Materiality threshold: {threshold.min_amount} - {threshold.max_amount}")
        else:
            parts.append(f"Materiality threshold: {threshold.min_amount} - unlimited")
        if threshold.level == MaterialityLevel.IMMATERIAL:
            parts.append("Transaction is immaterial - standard processing applies")
        else:
            parts.append(
                f"Transaction is {threshold.level.name} - requires {threshold.required_approvers} approval(s)"
            )
        if qualitative_factors:
            parts.append(f"Qualitative factors: {', '.join(qualitative_factors)}")
        return " | ".join(parts)

    def get_evaluation(self, intent_id: UUID) -> MaterialityEvaluation | None:
        with self._lock:
            return self._evaluations.get(intent_id)

    def get_required_approvals(self, intent_id: UUID) -> dict[str, Any]:
        evaluation = self.get_evaluation(intent_id)
        if not evaluation:
            return {"error": "No materiality evaluation found"}
        # Gunakan nilai amount dari evaluation? Lebih tepat pakai threshold dari amount asli.
        # Di sini kita ambil threshold berdasarkan quantitative_score (bukan amount asli, tapi aman)
        amount = (
            evaluation.quantitative_score
        )  # ini dalam persen, bukan nilai uang. Sebaiknya simpan amount asli.
        # Karena kita tidak simpan amount asli, fallback ke threshold pertama yang sesuai dengan level.
        threshold = next(
            (t for t in self._thresholds if t.level == evaluation.materiality_level),
            self._thresholds[-1],
        )
        return {
            "materiality_level": evaluation.materiality_level.name,
            "requires_approval": threshold.requires_approval,
            "required_approvers": threshold.required_approvers,
            "required_documentation": threshold.required_documentation,
            "requires_board_approval": evaluation.requires_board_approval,
            "requires_disclosure": evaluation.requires_disclosure,
            "escalation_level": threshold.escalation_level,
        }

    # ==================== REPOSITORY METHODS ====================
    def save_evaluation(self, evaluation: MaterialityEvaluation) -> None:
        with self._lock:
            self._evaluations[evaluation.intent_id] = evaluation

    def get_evaluations_by_intent(self, intent_id: UUID) -> list[MaterialityEvaluation]:
        with self._lock:
            ev = self._evaluations.get(intent_id)
            return [ev] if ev else []

    def get_all_evaluations(self) -> list[MaterialityEvaluation]:
        with self._lock:
            return list(self._evaluations.values())

    def delete_evaluation(self, intent_id: UUID) -> bool:
        with self._lock:
            if intent_id in self._evaluations:
                del self._evaluations[intent_id]
                return True
            return False

    def get_statistics(self) -> dict[str, Any]:
        with self._lock:
            total = len(self._evaluations)
            if total == 0:
                return {"total_evaluations": 0}
            by_level = {}
            for e in self._evaluations.values():
                by_level[e.materiality_level.name] = by_level.get(e.materiality_level.name, 0) + 1
            return {
                "total_evaluations": total,
                "by_materiality_level": by_level,
                "board_approval_count": len(
                    [e for e in self._evaluations.values() if e.requires_board_approval]
                ),
                "disclosure_required_count": len(
                    [e for e in self._evaluations.values() if e.requires_disclosure]
                ),
            }

    def reset(self) -> None:
        with self._lock:
            self._thresholds = DEFAULT_MATERIALITY_THRESHOLDS.copy()
            self._evaluations = {}


def get_materiality_evaluator() -> MaterialityEvaluator:
    global _materiality_evaluator_instance
    if _materiality_evaluator_instance is None:
        _materiality_evaluator_instance = MaterialityEvaluator()
    return _materiality_evaluator_instance


_materiality_evaluator_instance: MaterialityEvaluator | None = None

__all__ = [
    "MaterialityDimension",
    "MaterialityEvaluation",
    "MaterialityEvaluator",
    "MaterialityLevel",
    "MaterialityThreshold",
    "get_materiality_evaluator",
]
