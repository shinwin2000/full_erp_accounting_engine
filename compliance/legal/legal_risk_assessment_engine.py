#!/usr/bin/env python3
"""
Module: legal_risk_assessment_engine.py
Layer: Compliance / Legal

Responsibility:
    Mesin penilaian risiko legal (legal risk assessment) berdasarkan jenis transaksi,
    yurisdiksi, pihak terkait, nilai transaksi, dan faktor lainnya. Mendukung
    scoring risiko (0-100), level risiko (low, medium, high, critical), rekomendasi
    mitigasi, riwayat penilaian, dan integrasi dengan daftar sanksi.

Dependencies:
    - datetime, decimal, enum, typing, hashlib, json, logging, uuid

Audit:
    Setiap penilaian risiko dicatat dengan hash integrity.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from .jurisdiction_definition import JurisdictionDefinition
from .sanction_list_checker import SanctionListChecker, SanctionListEntry

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class LegalRiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TransactionType(Enum):
    CROSS_BORDER_PAYMENT = "cross_border_payment"
    DOMESTIC_PAYMENT = "domestic_payment"
    INVESTMENT = "investment"
    LOAN = "loan"
    TRADE = "trade"
    MERGER_ACQUISITION = "merger_acquisition"
    REAL_ESTATE = "real_estate"
    INTELLECTUAL_PROPERTY = "intellectual_property"
    EMPLOYMENT = "employment"
    TAX_PLANNING = "tax_planning"
    POLITICAL_CONTRIBUTION = "political_contribution"
    OTHER = "other"


class PartyType(Enum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"
    GOVERNMENT = "government"
    PEP = "politically_exposed_person"
    SANCTIONED = "sanctioned"
    RELATED_PARTY = "related_party"


# ============================================================================
# Data Classes
# ============================================================================
class LegalRiskAssessment:
    def __init__(
        self,
        assessment_id: UUID,
        transaction_id: UUID | None,
        risk_level: LegalRiskLevel,
        score: int,  # 0-100
        factors: list[str],
        recommendations: list[str],
        assessed_by: str,
        assessed_at: datetime,
        details: dict | None = None,
    ):
        self.id = assessment_id
        self.transaction_id = transaction_id
        self.risk_level = risk_level
        self.score = score
        self.factors = factors
        self.recommendations = recommendations
        self.assessed_by = assessed_by
        self.assessed_at = assessed_at
        self.details = details or {}
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "id": str(self.id),
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "risk_level": self.risk_level.value,
            "score": self.score,
            "assessed_at": self.assessed_at.isoformat(),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "assessment_id": str(self.id),
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "risk_level": self.risk_level.value,
            "score": self.score,
            "factors": self.factors,
            "recommendations": self.recommendations,
            "assessed_by": self.assessed_by,
            "assessed_at": self.assessed_at.isoformat(),
            "details": self.details,
            "hash": self._hash,
        }


# ============================================================================
# LegalRiskAssessmentEngine Core
# ============================================================================
class LegalRiskAssessmentEngine:
    """
    Mesin penilaian risiko legal transaksi.
    """

    def __init__(self):
        self._assessments: list[LegalRiskAssessment] = []
        self._sanction_checker = SanctionListChecker()
        self._jurisdiction_def = JurisdictionDefinition()

    def assess_transaction(
        self,
        transaction: dict,
        assessed_by: str,
    ) -> LegalRiskAssessment:
        """
        Menilai risiko legal dari sebuah transaksi.
        transaction dictionary minimal berisi: amount, jurisdiction, transaction_type,
        counterparty_name, counterparty_type, related_party.
        """
        score = 0
        factors = []

        # 1. Nilai transaksi (amount)
        amount = transaction.get("amount", 0)
        if amount > 10_000_000_000:  # > 10M IDR
            score += 40
            factors.append("Transaction amount exceeds 10 billion IDR")
        elif amount > 1_000_000_000:
            score += 20
            factors.append("Transaction amount between 1-10 billion IDR")

        # 2. Yurisdiksi berisiko tinggi
        jurisdiction = transaction.get("jurisdiction", "ID")
        high_risk_jurisdictions = self._get_high_risk_jurisdictions()
        if jurisdiction in high_risk_jurisdictions:
            score += 30
            factors.append(f"High-risk jurisdiction: {jurisdiction}")
        elif jurisdiction not in self._jurisdiction_def.get_supported_codes():
            score += 15
            factors.append(f"Unsupported/unknown jurisdiction: {jurisdiction}")

        # 3. Jenis transaksi berisiko
        tx_type_str = transaction.get("transaction_type", "other")
        try:
            tx_type = TransactionType(tx_type_str)
        except ValueError:
            tx_type = TransactionType.OTHER

        high_risk_types = [
            TransactionType.CROSS_BORDER_PAYMENT,
            TransactionType.MERGER_ACQUISITION,
            TransactionType.POLITICAL_CONTRIBUTION,
            TransactionType.TAX_PLANNING,
        ]
        if tx_type in high_risk_types:
            score += 25
            factors.append(f"High-risk transaction type: {tx_type.value}")

        # 4. Pihak terkait (related party)
        if transaction.get("related_party", False):
            score += 15
            factors.append("Involves related party")

        # 5. Screening counterparty terhadap daftar sanksi
        counterparty_name = transaction.get("counterparty_name", "")
        if counterparty_name:
            sanction_hit = self._sanction_checker.check_name(counterparty_name)
            if sanction_hit:
                score += 50  # langsung naik signifikan
                factors.append(
                    f"Counterparty '{counterparty_name}' is on sanction list: {sanction_hit.sanction_list}"
                )

        # 6. Tipe counterparty
        party_type_str = transaction.get("counterparty_type", "corporate")
        if party_type_str == "pep":
            score += 30
            factors.append("Counterparty is a Politically Exposed Person (PEP)")
        elif party_type_str == "government":
            score += 10
            factors.append("Government counterparty - additional scrutiny")

        # 7. Lintas batas (cross-border)
        if tx_type == TransactionType.CROSS_BORDER_PAYMENT:
            score += 10
            factors.append("Cross-border payment - currency control considerations")

        # Batasi skor maksimal 100
        score = min(score, 100)

        # Tentukan level risiko
        if score >= 80:
            risk_level = LegalRiskLevel.CRITICAL
        elif score >= 60:
            risk_level = LegalRiskLevel.HIGH
        elif score >= 30:
            risk_level = LegalRiskLevel.MEDIUM
        else:
            risk_level = LegalRiskLevel.LOW

        # Rekomendasi mitigasi
        recommendations = self._generate_recommendations(
            risk_level, factors, tx_type, sanction_hit if counterparty_name else None
        )

        assessment = LegalRiskAssessment(
            assessment_id=uuid4(),
            transaction_id=transaction.get("id"),
            risk_level=risk_level,
            score=score,
            factors=factors,
            recommendations=recommendations,
            assessed_by=assessed_by,
            assessed_at=datetime.utcnow(),
            details={
                "amount": amount,
                "jurisdiction": jurisdiction,
                "transaction_type": tx_type.value,
                "counterparty_name": counterparty_name,
                "counterparty_type": party_type_str,
            },
        )
        self._assessments.append(assessment)
        logger.info(f"Legal risk assessment completed: score {score}, level {risk_level.value}")
        return assessment

    def _get_high_risk_jurisdictions(self) -> list[str]:
        """Daftar yurisdiksi berisiko tinggi untuk AML/CFT."""
        return [
            "AF",
            "IQ",
            "SY",
            "YE",
            "IR",
            "KP",
            "MM",
            "UA",
            "RU",
            "BY",
            "SO",
            "LY",
            "VE",
            "SD",
            "ER",
            "KG",
            "TJ",
            "TM",
            "UZ",
            "PK",
        ]

    def _generate_recommendations(
        self,
        level: LegalRiskLevel,
        factors: list[str],
        tx_type: TransactionType,
        sanction_hit: SanctionListEntry | None,
    ) -> list[str]:
        recs = []
        if sanction_hit:
            recs.append("Immediately escalate to compliance officer and legal counsel")
            recs.append("Do not proceed with transaction until further review")
        if level in (LegalRiskLevel.HIGH, LegalRiskLevel.CRITICAL):
            recs.append("Consult legal counsel before proceeding")
            recs.append("Perform enhanced due diligence (EDD) on counterparty")
        if any("jurisdiction" in f.lower() for f in factors):
            recs.append("Verify sanctions list for jurisdiction")
        if tx_type == TransactionType.CROSS_BORDER_PAYMENT:
            recs.append("Ensure compliance with cross-border currency reporting requirements")
        if tx_type == TransactionType.POLITICAL_CONTRIBUTION:
            recs.append("Review anti-bribery and corruption policies")
        if not recs:
            recs.append("Standard due diligence sufficient")
        return recs

    def get_assessment(self, assessment_id: UUID) -> LegalRiskAssessment | None:
        for a in self._assessments:
            if a.id == assessment_id:
                return a
        return None

    def get_assessments_by_transaction(self, transaction_id: UUID) -> list[LegalRiskAssessment]:
        return [a for a in self._assessments if a.transaction_id == transaction_id]

    def get_recent_assessments(self, limit: int = 50) -> list[LegalRiskAssessment]:
        return self._assessments[-limit:]

    def generate_report(self) -> dict:
        total = len(self._assessments)
        if total == 0:
            return {"total_assessments": 0}
        by_level = {
            LegalRiskLevel.LOW.value: sum(
                1 for a in self._assessments if a.risk_level == LegalRiskLevel.LOW
            ),
            LegalRiskLevel.MEDIUM.value: sum(
                1 for a in self._assessments if a.risk_level == LegalRiskLevel.MEDIUM
            ),
            LegalRiskLevel.HIGH.value: sum(
                1 for a in self._assessments if a.risk_level == LegalRiskLevel.HIGH
            ),
            LegalRiskLevel.CRITICAL.value: sum(
                1 for a in self._assessments if a.risk_level == LegalRiskLevel.CRITICAL
            ),
        }
        avg_score = sum(a.score for a in self._assessments) / total
        return {
            "total_assessments": total,
            "by_risk_level": by_level,
            "average_score": round(avg_score, 2),
            "high_risk_count": by_level[LegalRiskLevel.HIGH.value]
            + by_level[LegalRiskLevel.CRITICAL.value],
        }

    def export_to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "assessments": [a.to_dict() for a in self._assessments],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    engine = LegalRiskAssessmentEngine()
    tx = {
        "id": uuid4(),
        "amount": 15_000_000_000,
        "jurisdiction": "RU",
        "transaction_type": "cross_border_payment",
        "counterparty_name": "Example Corp",
        "counterparty_type": "corporate",
        "related_party": True,
    }
    assessment = engine.assess_transaction(tx, assessed_by="Compliance Officer")
    print(f"Risk level: {assessment.risk_level.value}, score: {assessment.score}")
    print("Factors:", assessment.factors)
    print("Recommendations:", assessment.recommendations)
    engine.export_to_json("legal_risk_assessments.json")
