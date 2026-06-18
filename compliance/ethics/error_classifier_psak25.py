#!/usr/bin/env python3
"""
Module: error_classifier_psak25.py
Layer: Compliance / Ethics

Responsibility:
    Klasifikasi error akuntansi sesuai PSAK 25: Kebijakan Akuntansi,
    Perubahan Estimasi Akuntansi, dan Kesalahan. Mendukung analisis mendalam
    berdasarkan faktor kualitatif dan kuantitatif, penentuan apakah restatement
    diperlukan, serta rekomendasi perlakuan akuntansi.

Dependencies:
    - datetime, decimal, enum, typing, hashlib, json, logging

Audit:
    Setiap klasifikasi error dicatat dengan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class ErrorType(Enum):
    CHANGE_IN_ACCOUNTING_POLICY = "change_in_accounting_policy"
    CHANGE_IN_ACCOUNTING_ESTIMATE = "change_in_accounting_estimate"
    ERROR_IN_APPLYING_POLICIES = "error_in_applying_policies"
    OMISSION_OR_MISSTATEMENT = "omission_or_misstatement"
    FRAUD = "fraud"


class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CorrectionTreatment(Enum):
    RETROSPECTIVE = "retrospective"
    PROSPECTIVE = "prospective"
    CURRENT_PERIOD = "current_period"


# ============================================================================
# Data Classes
# ============================================================================
class ErrorClassification:
    def __init__(
        self,
        error_type: ErrorType,
        description: str,
        retrospective_required: bool,
        prior_period_adjustment: bool,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        correction_treatment: CorrectionTreatment = CorrectionTreatment.RETROSPECTIVE,
        accounting_impact: str = "",
        disclosure_required: bool = True,
        quantitative_threshold_met: bool = False,
        qualitative_factors: list[str] = None,
    ):
        self.error_type = error_type
        self.description = description
        self.retrospective_required = retrospective_required
        self.prior_period_adjustment = prior_period_adjustment
        self.severity = severity
        self.correction_treatment = correction_treatment
        self.accounting_impact = accounting_impact
        self.disclosure_required = disclosure_required
        self.quantitative_threshold_met = quantitative_threshold_met
        self.qualitative_factors = qualitative_factors or []
        self.classified_at = datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "error_type": self.error_type.value,
            "retrospective_required": self.retrospective_required,
            "severity": self.severity.value,
            "correction_treatment": self.correction_treatment.value,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "error_type": self.error_type.value,
            "description": self.description,
            "retrospective_required": self.retrospective_required,
            "prior_period_adjustment": self.prior_period_adjustment,
            "severity": self.severity.value,
            "correction_treatment": self.correction_treatment.value,
            "accounting_impact": self.accounting_impact,
            "disclosure_required": self.disclosure_required,
            "quantitative_threshold_met": self.quantitative_threshold_met,
            "qualitative_factors": self.qualitative_factors,
            "classified_at": self.classified_at.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# ErrorClassifierPSAK25 Core
# ============================================================================
class ErrorClassifierPSAK25:
    """
    Klasifikasi error akuntansi sesuai PSAK 25.
    """

    def __init__(self, materiality_percentage: Decimal = Decimal("0.005")):
        self.materiality_percentage = materiality_percentage
        self._criteria = self._init_criteria()
        self._classification_history: list[ErrorClassification] = []

    def _init_criteria(self) -> dict[ErrorType, dict]:
        return {
            ErrorType.CHANGE_IN_ACCOUNTING_POLICY: {
                "retrospective_required": False,
                "prior_period_adjustment": False,
                "default_severity": ErrorSeverity.MEDIUM,
                "correction_treatment": CorrectionTreatment.RETROSPECTIVE,
                "accounting_impact": "Adjustment to retained earnings of earliest period presented",
                "disclosure_required": True,
            },
            ErrorType.CHANGE_IN_ACCOUNTING_ESTIMATE: {
                "retrospective_required": False,
                "prior_period_adjustment": False,
                "default_severity": ErrorSeverity.LOW,
                "correction_treatment": CorrectionTreatment.PROSPECTIVE,
                "accounting_impact": "Recognized in current and future periods",
                "disclosure_required": True,
            },
            ErrorType.ERROR_IN_APPLYING_POLICIES: {
                "retrospective_required": True,
                "prior_period_adjustment": True,
                "default_severity": ErrorSeverity.HIGH,
                "correction_treatment": CorrectionTreatment.RETROSPECTIVE,
                "accounting_impact": "Restate prior period financial statements",
                "disclosure_required": True,
            },
            ErrorType.OMISSION_OR_MISSTATEMENT: {
                "retrospective_required": True,
                "prior_period_adjustment": True,
                "default_severity": ErrorSeverity.HIGH,
                "correction_treatment": CorrectionTreatment.RETROSPECTIVE,
                "accounting_impact": "Correct prior period errors retrospectively",
                "disclosure_required": True,
            },
            ErrorType.FRAUD: {
                "retrospective_required": True,
                "prior_period_adjustment": True,
                "default_severity": ErrorSeverity.CRITICAL,
                "correction_treatment": CorrectionTreatment.RETROSPECTIVE,
                "accounting_impact": "Restate, investigate controls, report to authorities",
                "disclosure_required": True,
            },
        }

    def classify(
        self,
        error_description: str,
        intentional: bool = False,
        policy_change: bool = False,
        estimate_change: bool = False,
        error_amount: Decimal | None = None,
        reference_amount: Decimal | None = None,
        qualitative_factors: list[str] | None = None,
    ) -> ErrorClassification:
        # Determine base type
        if intentional:
            error_type = ErrorType.FRAUD
        elif policy_change:
            error_type = ErrorType.CHANGE_IN_ACCOUNTING_POLICY
        elif estimate_change:
            error_type = ErrorType.CHANGE_IN_ACCOUNTING_ESTIMATE
        else:
            # Distinguish between error application and omission
            if "omission" in error_description.lower() or "missing" in error_description.lower():
                error_type = ErrorType.OMISSION_OR_MISSTATEMENT
            else:
                error_type = ErrorType.ERROR_IN_APPLYING_POLICIES

        criteria = self._criteria[error_type]
        severity = criteria["default_severity"]

        # Adjust severity based on quantitative materiality
        quantitative_threshold_met = False
        if error_amount is not None and reference_amount is not None and reference_amount > 0:
            error_ratio = abs(error_amount / reference_amount)
            if error_ratio > self.materiality_percentage:
                quantitative_threshold_met = True
                if severity == ErrorSeverity.LOW:
                    severity = ErrorSeverity.MEDIUM
                elif severity == ErrorSeverity.MEDIUM:
                    severity = ErrorSeverity.HIGH
                elif severity == ErrorSeverity.HIGH:
                    severity = ErrorSeverity.CRITICAL

        # Adjust severity based on qualitative factors
        qf = qualitative_factors or []
        if any("regulatory" in f.lower() or "compliance" in f.lower() for f in qf):
            severity = ErrorSeverity.HIGH
        if any("fraud" in f.lower() or "illegal" in f.lower() for f in qf):
            severity = ErrorSeverity.CRITICAL

        classification = ErrorClassification(
            error_type=error_type,
            description=error_description,
            retrospective_required=criteria["retrospective_required"],
            prior_period_adjustment=criteria["prior_period_adjustment"],
            severity=severity,
            correction_treatment=criteria["correction_treatment"],
            accounting_impact=criteria["accounting_impact"],
            disclosure_required=criteria["disclosure_required"],
            quantitative_threshold_met=quantitative_threshold_met,
            qualitative_factors=qf,
        )
        self._classification_history.append(classification)
        return classification

    def classify_with_materiality_assessment(
        self,
        error_description: str,
        error_amount: Decimal,
        revenue: Decimal,
        total_assets: Decimal,
        equity: Decimal,
        intentional: bool = False,
        policy_change: bool = False,
        estimate_change: bool = False,
        qualitative_factors: list[str] | None = None,
    ) -> ErrorClassification:
        # Use the highest of revenue, assets, or equity as reference (conservative)
        reference = max(revenue, total_assets, equity)
        if reference == 0:
            reference = Decimal("1")
        return self.classify(
            error_description=error_description,
            intentional=intentional,
            policy_change=policy_change,
            estimate_change=estimate_change,
            error_amount=error_amount,
            reference_amount=reference,
            qualitative_factors=qualitative_factors,
        )

    def requires_restatement(self, classification: ErrorClassification) -> bool:
        return classification.retrospective_required

    def get_disclosure_requirements(self, classification: ErrorClassification) -> list[str]:
        if not classification.disclosure_required:
            return []
        base_disclosures = [
            "Nature of the error",
            "Amount of correction for each prior period presented",
            "Adjustment to opening balance of retained earnings",
        ]
        if classification.error_type == ErrorType.CHANGE_IN_ACCOUNTING_POLICY:
            base_disclosures.append("Reasons for change and that new policy is preferable")
        if classification.error_type == ErrorType.CHANGE_IN_ACCOUNTING_ESTIMATE:
            base_disclosures.append(
                "Effect on current and future periods, if impracticable to estimate"
            )
        return base_disclosures

    def get_classification_history(self) -> list[dict]:
        return [c.to_dict() for c in self._classification_history]

    def generate_summary(self) -> dict:
        if not self._classification_history:
            return {"total_classifications": 0}
        total = len(self._classification_history)
        by_type = {
            t.value: sum(1 for c in self._classification_history if c.error_type == t)
            for t in ErrorType
        }
        by_severity = {
            s.value: sum(1 for c in self._classification_history if c.severity == s)
            for s in ErrorSeverity
        }
        restatements_required = sum(
            1 for c in self._classification_history if c.retrospective_required
        )
        return {
            "total_classifications": total,
            "by_error_type": by_type,
            "by_severity": by_severity,
            "restatements_required": restatements_required,
            "fraud_cases": sum(
                1 for c in self._classification_history if c.error_type == ErrorType.FRAUD
            ),
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "summary": self.generate_summary(),
            "classifications": [c.to_dict() for c in self._classification_history],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    classifier = ErrorClassifierPSAK25(materiality_percentage=Decimal("0.005"))

    # Example 1: Change in estimate
    est_class = classifier.classify(
        error_description="Revised useful life of machinery from 10 to 12 years",
        estimate_change=True,
        qualitative_factors=["No prior misstatement", "Based on new information"],
    )
    print(
        f"Estimate change: {est_class.error_type.value}, restatement required: {est_class.retrospective_required}"
    )

    # Example 2: Material error
    error_class = classifier.classify_with_materiality_assessment(
        error_description="Sales revenue understated by IDR 5 billion",
        error_amount=Decimal("5_000_000_000"),
        revenue=Decimal("100_000_000_000"),
        total_assets=Decimal("200_000_000_000"),
        equity=Decimal("80_000_000_000"),
        qualitative_factors=["Affects bonus calculation", "Misleading trend"],
    )
    print(
        f"Error: {error_class.error_type.value}, severity: {error_class.severity.value}, restatement: {error_class.retrospective_required}"
    )

    # Summary
    print(classifier.generate_summary())
    classifier.to_json("error_classifications.json")
