#!/usr/bin/env python3
"""
Module: disclosure_requirement_checker.py
Layer: Compliance / Ethics

Responsibility:
    Pengecekan kewajiban pengungkapan (disclosure) dalam laporan keuangan
    sesuai standar akuntansi (PSAK/IFRS) dan regulasi OJK. Mendukung checklist
    pengungkapan, tracking status pemenuhan, gap analysis, rekomendasi,
    dan export laporan kepatuhan pengungkapan.

Dependencies:
    - datetime, enum, typing, json, hashlib, logging

Audit:
    Setiap perubahan status pengungkapan dicatat dengan timestamp dan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================
class DisclosureTopic(Enum):
    ACCOUNTING_POLICIES = "accounting_policies"
    CHANGE_IN_ESTIMATES = "change_in_estimates"
    CORRECTION_OF_ERRORS = "correction_of_errors"
    RELATED_PARTY_TRANSACTIONS = "related_party_transactions"
    CONTINGENT_LIABILITIES = "contingent_liabilities"
    EVENTS_AFTER_REPORTING_PERIOD = "events_after_reporting_period"
    SEGMENT_INFORMATION = "segment_information"
    FAIR_VALUE_MEASUREMENT = "fair_value_measurement"
    FINANCIAL_INSTRUMENTS = "financial_instruments"
    LEASES = "leases"
    REVENUE = "revenue"
    TAXES = "taxes"
    EARNINGS_PER_SHARE = "earnings_per_share"
    GOING_CONCERN = "going_concern"
    SUBSEQUENT_EVENTS = "subsequent_events"
    BUSINESS_COMBINATIONS = "business_combinations"
    INTANGIBLE_ASSETS = "intangible_assets"
    INVENTORIES = "inventories"
    PROPERTY_PLANT_EQUIPMENT = "property_plant_equipment"
    IMPAIRMENT = "impairment"
    PROVISIONS = "provisions"
    SHARE_BASED_PAYMENT = "share_based_payment"
    GOVERNMENT_GRANTS = "government_grants"
    BORROWING_COSTS = "borrowing_costs"
    INVESTMENT_PROPERTY = "investment_property"
    NON_CURRENT_ASSETS_HELD_FOR_SALE = "non_current_assets_held_for_sale"


class DisclosureStatus(Enum):
    COMPLIANT = "compliant"
    PARTIALLY_COMPLIANT = "partially_compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    UNDER_REVIEW = "under_review"


class RegulatoryFramework(Enum):
    PSAK = "psak"
    IFRS = "ifrs"
    OJK = "ojk"
    GAAP = "gaap"


# ============================================================================
# Data Classes
# ============================================================================
class DisclosureRequirement:
    def __init__(
        self,
        topic: DisclosureTopic,
        required: bool,
        description: str,
        regulation_reference: str,
        regulatory_framework: RegulatoryFramework = RegulatoryFramework.PSAK,
        detailed_criteria: list[str] | None = None,
    ):
        self.topic = topic
        self.required = required
        self.description = description
        self.regulation_reference = regulation_reference
        self.regulatory_framework = regulatory_framework
        self.detailed_criteria = detailed_criteria or []
        self.disclosed: bool = False
        self.disclosure_text: str = ""
        self.status: DisclosureStatus = (
            DisclosureStatus.NOT_APPLICABLE if not required else DisclosureStatus.NON_COMPLIANT
        )
        self.assessed_by: str | None = None
        self.assessed_date: date | None = None
        self.notes: str = ""
        self.evidence: str | None = None
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "topic": self.topic.value,
            "disclosed": self.disclosed,
            "status": self.status.value,
            "assessed_date": self.assessed_date.isoformat() if self.assessed_date else None,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def mark_compliant(
        self, assessed_by: str, disclosure_text: str, evidence: str | None = None
    ) -> None:
        self.disclosed = True
        self.disclosure_text = disclosure_text
        self.status = DisclosureStatus.COMPLIANT
        self.assessed_by = assessed_by
        self.assessed_date = date.today()
        self.evidence = evidence
        self._hash = self._compute_hash()

    def mark_non_compliant(self, assessed_by: str, notes: str) -> None:
        self.disclosed = False
        self.status = DisclosureStatus.NON_COMPLIANT
        self.assessed_by = assessed_by
        self.assessed_date = date.today()
        self.notes = notes
        self._hash = self._compute_hash()

    def mark_partial(self, assessed_by: str, notes: str) -> None:
        self.disclosed = True
        self.status = DisclosureStatus.PARTIALLY_COMPLIANT
        self.assessed_by = assessed_by
        self.assessed_date = date.today()
        self.notes = notes
        self._hash = self._compute_hash()

    def to_dict(self) -> dict:
        return {
            "topic": self.topic.value,
            "required": self.required,
            "description": self.description,
            "regulation_reference": self.regulation_reference,
            "framework": self.regulatory_framework.value,
            "criteria": self.detailed_criteria,
            "disclosed": self.disclosed,
            "disclosure_text": self.disclosure_text[:500] if self.disclosure_text else "",
            "status": self.status.value,
            "assessed_by": self.assessed_by,
            "assessed_date": self.assessed_date.isoformat() if self.assessed_date else None,
            "notes": self.notes,
            "hash": self._hash,
        }


# ============================================================================
# DisclosureRequirementChecker Core
# ============================================================================
class DisclosureRequirementChecker:
    """
    Pengecekan kewajiban pengungkapan laporan keuangan.
    """

    def __init__(self, framework: RegulatoryFramework = RegulatoryFramework.PSAK):
        self.framework = framework
        self._requirements: list[DisclosureRequirement] = []
        self._init_requirements()
        self._assessment_history: list[dict] = []

    def _init_requirements(self) -> None:
        """Initialize default disclosure requirements based on regulatory framework."""
        if self.framework == RegulatoryFramework.PSAK:
            self._requirements = [
                DisclosureRequirement(
                    DisclosureTopic.ACCOUNTING_POLICIES,
                    True,
                    "Summary of significant accounting policies",
                    "PSAK 1",
                    self.framework,
                    ["Basis of preparation", "Measurement bases", "Critical accounting estimates"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.CHANGE_IN_ESTIMATES,
                    True,
                    "Nature and amount of change in accounting estimate",
                    "PSAK 25",
                    self.framework,
                    ["Effect on current period", "Effect on future periods"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.CORRECTION_OF_ERRORS,
                    True,
                    "Nature of error and amount of correction",
                    "PSAK 25",
                    self.framework,
                    ["Prior period adjustment", "Impact on retained earnings"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.RELATED_PARTY_TRANSACTIONS,
                    True,
                    "Key management compensation and transactions",
                    "PSAK 7",
                    self.framework,
                    ["Nature of relationship", "Transaction amounts", "Outstanding balances"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.CONTINGENT_LIABILITIES,
                    True,
                    "Nature and estimate of contingent liabilities",
                    "PSAK 57",
                    self.framework,
                    ["Description", "Possible financial impact"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.EVENTS_AFTER_REPORTING_PERIOD,
                    True,
                    "Non-adjusting events after reporting period",
                    "PSAK 8",
                    self.framework,
                    ["Nature of event", "Financial effect"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.REVENUE,
                    True,
                    "Revenue recognition policies and disaggregation",
                    "PSAK 72",
                    self.framework,
                    ["Revenue categories", "Contract balances", "Performance obligations"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.LEASES,
                    True,
                    "Right-of-use assets and lease liabilities",
                    "PSAK 73",
                    self.framework,
                    ["Maturity analysis", "Expense breakdown", "Cash flow impact"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.FINANCIAL_INSTRUMENTS,
                    True,
                    "Financial instruments disclosures",
                    "PSAK 71",
                    self.framework,
                    ["Classification", "Fair value", "Credit risk", "Liquidity risk"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.TAXES,
                    True,
                    "Income tax disclosures",
                    "PSAK 46",
                    self.framework,
                    ["Reconciliation", "Deferred tax", "Unrecognized tax losses"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.FAIR_VALUE_MEASUREMENT,
                    True,
                    "Fair value hierarchy and measurements",
                    "IFRS 13",
                    self.framework,
                    ["Level 1,2,3 inputs", "Valuation techniques", "Sensitivity analysis"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.SEGMENT_INFORMATION,
                    True,
                    "Operating segment disclosures",
                    "PSAK 5",
                    self.framework,
                    ["Segment revenue", "Profit/loss", "Assets and liabilities"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.EARNINGS_PER_SHARE,
                    True,
                    "Basic and diluted EPS",
                    "PSAK 33",
                    self.framework,
                    ["Calculation", "Reconciliation", "Dilutive instruments"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.GOING_CONCERN,
                    True,
                    "Going concern assessment",
                    "PSAK 1",
                    self.framework,
                    ["Assumptions", "Uncertainties", "Management plans"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.BUSINESS_COMBINATIONS,
                    False,
                    "Business combinations disclosures",
                    "PSAK 22",
                    self.framework,
                ),
                DisclosureRequirement(
                    DisclosureTopic.INTANGIBLE_ASSETS,
                    True,
                    "Intangible assets",
                    "PSAK 19",
                    self.framework,
                    ["Useful lives", "Amortization", "Impairment"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.INVENTORIES,
                    True,
                    "Inventory accounting policies",
                    "PSAK 14",
                    self.framework,
                    ["Cost formula", "Write-downs", "Pledged inventory"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.PROPERTY_PLANT_EQUIPMENT,
                    True,
                    "Property, plant and equipment",
                    "PSAK 16",
                    self.framework,
                    ["Depreciation methods", "Revaluations", "Asset lives"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.IMPAIRMENT,
                    True,
                    "Impairment of assets",
                    "PSAK 48",
                    self.framework,
                    ["CGUs", "Key assumptions", "Sensitivity"],
                ),
                DisclosureRequirement(
                    DisclosureTopic.PROVISIONS,
                    True,
                    "Provisions and contingencies",
                    "PSAK 57",
                    self.framework,
                    ["Legal cases", "Warranties", "Restructuring"],
                ),
            ]
        else:
            # Simplified for other frameworks
            self._requirements = []

    def add_custom_requirement(self, requirement: DisclosureRequirement) -> None:
        self._requirements.append(requirement)

    def get_requirement(self, topic: DisclosureTopic) -> DisclosureRequirement | None:
        for req in self._requirements:
            if req.topic == topic:
                return req
        return None

    def mark_disclosure_compliant(
        self,
        topic: DisclosureTopic,
        assessed_by: str,
        disclosure_text: str,
        evidence: str | None = None,
    ) -> bool:
        req = self.get_requirement(topic)
        if not req:
            return False
        req.mark_compliant(assessed_by, disclosure_text, evidence)
        self._record_assessment(topic, DisclosureStatus.COMPLIANT, assessed_by)
        return True

    def mark_disclosure_non_compliant(
        self, topic: DisclosureTopic, assessed_by: str, notes: str
    ) -> bool:
        req = self.get_requirement(topic)
        if not req:
            return False
        req.mark_non_compliant(assessed_by, notes)
        self._record_assessment(topic, DisclosureStatus.NON_COMPLIANT, assessed_by)
        return True

    def mark_disclosure_partial(self, topic: DisclosureTopic, assessed_by: str, notes: str) -> bool:
        req = self.get_requirement(topic)
        if not req:
            return False
        req.mark_partial(assessed_by, notes)
        self._record_assessment(topic, DisclosureStatus.PARTIALLY_COMPLIANT, assessed_by)
        return True

    def _record_assessment(
        self, topic: DisclosureTopic, status: DisclosureStatus, assessed_by: str
    ) -> None:
        self._assessment_history.append(
            {
                "topic": topic.value,
                "status": status.value,
                "assessed_by": assessed_by,
                "assessed_at": datetime.utcnow().isoformat(),
            }
        )

    def missing_disclosures(self) -> list[DisclosureRequirement]:
        return [
            req
            for req in self._requirements
            if req.required and req.status != DisclosureStatus.COMPLIANT
        ]

    def is_compliant(self) -> bool:
        return len(self.missing_disclosures()) == 0

    def get_compliance_percentage(self) -> float:
        required = [r for r in self._requirements if r.required]
        if not required:
            return 100.0
        compliant = sum(1 for r in required if r.status == DisclosureStatus.COMPLIANT)
        return (compliant / len(required)) * 100

    def generate_disclosure_report(self) -> dict:
        required = [r for r in self._requirements if r.required]
        compliant = [r for r in required if r.status == DisclosureStatus.COMPLIANT]
        partial = [r for r in required if r.status == DisclosureStatus.PARTIALLY_COMPLIANT]
        non_compliant = [r for r in required if r.status == DisclosureStatus.NON_COMPLIANT]
        return {
            "framework": self.framework.value,
            "assessment_date": date.today().isoformat(),
            "total_required": len(required),
            "compliant": len(compliant),
            "partially_compliant": len(partial),
            "non_compliant": len(non_compliant),
            "compliance_percentage": round(self.get_compliance_percentage(), 2),
            "missing_details": [
                {
                    "topic": r.topic.value,
                    "description": r.description,
                    "regulation": r.regulation_reference,
                    "notes": r.notes,
                }
                for r in non_compliant + partial
            ],
            "recommendations": self._generate_recommendations(non_compliant, partial),
        }

    def _generate_recommendations(self, non_compliant: list, partial: list) -> list[str]:
        recs = []
        for r in non_compliant:
            recs.append(
                f"Implement disclosure for {r.topic.value}: {r.description} per {r.regulation_reference}"
            )
        for r in partial:
            recs.append(f"Complete disclosure for {r.topic.value}: missing criteria {r.notes}")
        return recs

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_disclosure_report(),
            "requirements": [r.to_dict() for r in self._requirements],
            "history": self._assessment_history,
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def reset_assessment(self) -> None:
        for req in self._requirements:
            req.disclosed = False
            req.disclosure_text = ""
            req.status = (
                DisclosureStatus.NOT_APPLICABLE
                if not req.required
                else DisclosureStatus.NON_COMPLIANT
            )
            req.assessed_by = None
            req.assessed_date = None
            req.notes = ""
            req._hash = req._compute_hash()
        self._assessment_history.clear()


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    checker = DisclosureRequirementChecker(RegulatoryFramework.PSAK)
    checker.mark_disclosure_compliant(
        DisclosureTopic.ACCOUNTING_POLICIES,
        "Audit Team",
        "Company uses historical cost basis except for financial instruments at FVTPL",
    )
    checker.mark_disclosure_non_compliant(
        DisclosureTopic.RELATED_PARTY_TRANSACTIONS,
        "Audit Team",
        "No disclosure of key management compensation",
    )
    report = checker.generate_disclosure_report()
    print("Disclosure Report:")
    print(json.dumps(report, indent=2))
    checker.to_json("disclosure_report.json")
