#!/usr/bin/env python3
"""
Module: materiality_threshold_qualitative.py
Layer: Compliance / Ethics

Responsibility:
    Ambang batas materialitas berdasarkan faktor kualitatif sesuai PSAK 25.
    Menilai apakah suatu kesalahan atau salah saji bersifat material secara
    kualitatif dengan mempertimbangkan dampak terhadap kepatuhan, tren laba,
    rasio keuangan, pengungkapan, persepsi publik, dan faktor lainnya.

Dependencies:
    - datetime, decimal, enum, typing, json, logging

Audit:
    Setiap penilaian materialitas kualitatif dicatat dengan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class QualitativeMaterialityLevel(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QualitativeImpactArea(Enum):
    REGULATORY_COMPLIANCE = "regulatory_compliance"
    DEBT_COVENANTS = "debt_covenants"
    PROFIT_TREND = "profit_trend"
    KEY_PERFORMANCE_INDICATORS = "key_performance_indicators"
    RELATED_PARTY = "related_party"
    SEGMENT_REPORTING = "segment_reporting"
    EXECUTIVE_COMPENSATION = "executive_compensation"
    PUBLIC_PERCEPTION = "public_perception"
    HIDDEN_ILLEGAL_TRANSACTION = "hidden_illegal_transaction"
    MULTIPLE_PERIODS = "multiple_periods"


# ============================================================================
# Data Classes
# ============================================================================
class QualitativeAssessmentResult:
    def __init__(
        self,
        level: QualitativeMaterialityLevel,
        score: int,
        triggering_factors: list[QualitativeImpactArea],
        description: str,
        assessed_by: str,
        assessed_at: datetime | None = None,
    ):
        self.level = level
        self.score = score
        self.triggering_factors = triggering_factors
        self.description = description
        self.assessed_by = assessed_by
        self.assessed_at = assessed_at or datetime.utcnow()
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "level": self.level.value,
            "score": self.score,
            "factors": [f.value for f in self.triggering_factors],
            "assessed_at": self.assessed_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def is_material(self) -> bool:
        return self.level in (QualitativeMaterialityLevel.HIGH, QualitativeMaterialityLevel.MEDIUM)

    def to_dict(self) -> dict:
        return {
            "level": self.level.value,
            "score": self.score,
            "triggering_factors": [f.value for f in self.triggering_factors],
            "description": self.description,
            "assessed_by": self.assessed_by,
            "assessed_at": self.assessed_at.isoformat(),
            "hash": self._hash,
        }


# ============================================================================
# QualitativeMateriality Core
# ============================================================================
class QualitativeMateriality:
    """
    Penilaian materialitas berdasarkan faktor kualitatif (PSAK 25).
    """

    def __init__(self):
        self._factor_weights = self._init_factor_weights()
        self._history: list[QualitativeAssessmentResult] = []

    def _init_factor_weights(self) -> dict[QualitativeImpactArea, int]:
        return {
            QualitativeImpactArea.REGULATORY_COMPLIANCE: 30,
            QualitativeImpactArea.DEBT_COVENANTS: 25,
            QualitativeImpactArea.PROFIT_TREND: 20,
            QualitativeImpactArea.KEY_PERFORMANCE_INDICATORS: 15,
            QualitativeImpactArea.RELATED_PARTY: 20,
            QualitativeImpactArea.SEGMENT_REPORTING: 15,
            QualitativeImpactArea.EXECUTIVE_COMPENSATION: 20,
            QualitativeImpactArea.PUBLIC_PERCEPTION: 25,
            QualitativeImpactArea.HIDDEN_ILLEGAL_TRANSACTION: 50,
            QualitativeImpactArea.MULTIPLE_PERIODS: 15,
        }

    def assess(
        self,
        error_description: str,
        triggering_factors: list[QualitativeImpactArea],
        assessed_by: str,
    ) -> QualitativeAssessmentResult:
        """
        Menilai level materialitas berdasarkan faktor kualitatif yang terpicu.
        """
        total_score = 0
        for factor in triggering_factors:
            total_score += self._factor_weights.get(factor, 0)
        # Cap at 100
        total_score = min(total_score, 100)

        if total_score >= 60:
            level = QualitativeMaterialityLevel.HIGH
        elif total_score >= 30:
            level = QualitativeMaterialityLevel.MEDIUM
        else:
            level = QualitativeMaterialityLevel.LOW

        result = QualitativeAssessmentResult(
            level=level,
            score=total_score,
            triggering_factors=triggering_factors,
            description=f"Assessment for: {error_description[:200]}",
            assessed_by=assessed_by,
        )
        self._history.append(result)
        return result

    def assess_from_description(
        self,
        error_description: str,
        assessed_by: str,
    ) -> QualitativeAssessmentResult:
        """
        Otomatis menentukan faktor yang terpicu berdasarkan kata kunci dalam deskripsi.
        """
        desc_lower = error_description.lower()
        triggered_factors = []

        factor_keywords = {
            QualitativeImpactArea.REGULATORY_COMPLIANCE: [
                "regulasi",
                "compliance",
                "peraturan",
                "legal",
                "audit",
            ],
            QualitativeImpactArea.DEBT_COVENANTS: [
                "covenant",
                "utang",
                "loan",
                "kredit",
                "perjanjian",
            ],
            QualitativeImpactArea.PROFIT_TREND: [
                "profit",
                "laba",
                "rugi",
                "trend",
                "penurunan",
                "kenaikan",
            ],
            QualitativeImpactArea.KEY_PERFORMANCE_INDICATORS: [
                "kpi",
                "indikator",
                "target",
                "bonus",
            ],
            QualitativeImpactArea.RELATED_PARTY: [
                "pihak berelasi",
                "related party",
                "afiliasi",
                "keluarga",
            ],
            QualitativeImpactArea.SEGMENT_REPORTING: ["segmen", "segment", "divisi", "unit bisnis"],
            QualitativeImpactArea.EXECUTIVE_COMPENSATION: [
                "direksi",
                "komisaris",
                "eksekutif",
                "kompensasi",
            ],
            QualitativeImpactArea.PUBLIC_PERCEPTION: ["publik", "media", "reputasi", "citra"],
            QualitativeImpactArea.HIDDEN_ILLEGAL_TRANSACTION: [
                "ilegal",
                "fraud",
                "penipuan",
                "suap",
                "korupsi",
            ],
            QualitativeImpactArea.MULTIPLE_PERIODS: [
                "beberapa periode",
                "multiple periods",
                "tahun lalu",
            ],
        }

        for factor, keywords in factor_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                triggered_factors.append(factor)

        if not triggered_factors:
            triggered_factors = [QualitativeImpactArea.PUBLIC_PERCEPTION]  # default

        return self.assess(error_description, triggered_factors, assessed_by)

    def is_material(self, error_description: str, assessed_by: str = "system") -> bool:
        result = self.assess_from_description(error_description, assessed_by)
        return result.is_material()

    def get_history(self) -> list[QualitativeAssessmentResult]:
        return self._history

    def generate_report(self) -> dict:
        total = len(self._history)
        if total == 0:
            return {"total_assessments": 0}
        high = sum(1 for r in self._history if r.level == QualitativeMaterialityLevel.HIGH)
        medium = sum(1 for r in self._history if r.level == QualitativeMaterialityLevel.MEDIUM)
        low = sum(1 for r in self._history if r.level == QualitativeMaterialityLevel.LOW)
        return {
            "total_assessments": total,
            "high_material": high,
            "medium_material": medium,
            "low_material": low,
            "material_percentage": round((high + medium) / total * 100, 2),
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "assessments": [r.to_dict() for r in self._history],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    qual = QualitativeMateriality()

    # Contoh 1: Pelanggaran regulasi
    result1 = qual.assess(
        error_description="Sales revenue overstated by IDR 10 billion to avoid debt covenant breach",
        triggering_factors=[
            QualitativeImpactArea.DEBT_COVENANTS,
            QualitativeImpactArea.REGULATORY_COMPLIANCE,
        ],
        assessed_by="Auditor",
    )
    print(f"Assessment 1: {result1.level.value} (score {result1.score})")

    # Contoh 2: Otomatis dari deskripsi
    result2 = qual.assess_from_description(
        error_description="Misclassification of related party transaction that affects executive bonus calculation",
        assessed_by="System",
    )
    print(
        f"Assessment 2: {result2.level.value} - factors: {[f.value for f in result2.triggering_factors]}"
    )

    # Contoh 3: Is material?
    is_mat = qual.is_material("Small adjustment to office supplies (IDR 500,000)", "System")
    print(f"Is material: {is_mat}")

    qual.to_json("qualitative_materiality.json")
