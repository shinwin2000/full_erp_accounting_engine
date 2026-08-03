#!/usr/bin/env python3
"""
Module: ifrs_for_smes.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IFRS for SMEs (International Financial Reporting Standard for Small and Medium-sized Entities).
               Mendefinisikan aturan yang disederhanakan untuk entitas
               yang tidak memiliki akuntabilitas publik. IFRS for SMEs
               memiliki 35 bagian dengan pengukuran yang lebih sederhana
               dibandingkan IFRS penuh.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap keputusan menggunakan IFRS for SMEs dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IFRSForSMESSection(Enum):
    """Bagian dalam IFRS for SMEs."""

    SCOPE = 1
    CONCEPTS = 2
    FINANCIAL_STATEMENT_PRESENTATION = 3
    STATEMENT_OF_FINANCIAL_POSITION = 4
    STATEMENT_OF_COMPREHENSIVE_INCOME = 5
    STATEMENT_OF_CHANGES_IN_EQUITY = 6
    STATEMENT_OF_CASH_FLOWS = 7
    NOTES = 8
    CONSOLIDATED_FINANCIAL_STATEMENTS = 9
    ACCOUNTING_POLICIES = 10
    FINANCIAL_INSTRUMENTS = 11
    INVENTORIES = 12
    PROPERTY_PLANT_EQUIPMENT = 13
    INTANGIBLE_ASSETS = 14
    BUSINESS_COMBINATIONS = 15
    LEASES = 20
    PROVISIONS = 21
    REVENUE = 23
    GOVERNMENT_GRANTS = 24
    BORROWING_COSTS = 25
    INCOME_TAX = 29
    FOREIGN_EXCHANGE = 30
    IMPAIRMENT = 27


class IFRSForSMESMeasurementBasis(Enum):
    """Dasar pengukuran yang disederhanakan."""

    COST = "cost"
    REVALUATION = "revaluation"  # Limited
    FAIR_VALUE = "fair_value"  # Untuk instrumen keuangan tertentu


class IFRSForSMESExemption(Enum):
    """Pengecualian untuk SMEs."""

    DEFERRED_TAX = "deferred_tax"  # Tidak wajib untuk SMEs
    EARNINGS_PER_SHARE = "earnings_per_share"
    SEGMENT_REPORTING = "segment_reporting"
    INTERIM_REPORTING = "interim_reporting"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IFRSForSMESOption:
    """Opsionalitas dalam IFRS for SMEs."""

    section: IFRSForSMESSection
    option_description: str
    is_elected: bool
    election_date: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section.value,
            "description": self.option_description,
            "elected": self.is_elected,
            "election_date": self.election_date.isoformat() if self.election_date else None,
        }


# === 3. ENTITIES ===


@dataclass
class IFRSForSMESEntityStatus:
    """Status entitas terkait IFRS for SMEs."""

    entity_id: UUID
    entity_name: str
    is_publicly_accountable: bool  # Jika ya, tidak bisa pakai IFRS for SMEs
    is_sme: bool
    adoption_date: datetime
    applied_sections: list[IFRSForSMESSection] = field(default_factory=list)
    elected_options: list[IFRSForSMESOption] = field(default_factory=list)
    exemptions_taken: list[IFRSForSMESExemption] = field(default_factory=list)

    def __post_init__(self):
        if self.is_publicly_accountable:
            raise ValueError("Publicly accountable entities cannot use IFRS for SMEs")

    def add_elected_option(self, option: IFRSForSMESOption) -> IFRSForSMESEntityStatus:
        return IFRSForSMESEntityStatus(
            entity_id=self.entity_id,
            entity_name=self.entity_name,
            is_publicly_accountable=self.is_publicly_accountable,
            is_sme=self.is_sme,
            adoption_date=self.adoption_date,
            applied_sections=self.applied_sections,
            elected_options=[*self.elected_options, option],
            exemptions_taken=self.exemptions_taken,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "is_publicly_accountable": self.is_publicly_accountable,
            "is_sme": self.is_sme,
            "adoption_date": self.adoption_date.isoformat(),
            "applied_sections": [s.value for s in self.applied_sections],
            "elected_options": [o.to_dict() for o in self.elected_options],
            "exemptions": [e.value for e in self.exemptions_taken],
        }


# === 4. DOMAIN SERVICES ===


class IFRSForSMESService:
    """Service untuk IFRS for SMEs."""

    @staticmethod
    def is_eligible(
        is_publicly_accountable: bool,
        is_sme_by_local_definition: bool,
    ) -> bool:
        """Entitas memenuhi syarat IFRS for SMEs jika tidak memiliki akuntabilitas publik dan memenuhi definisi SME."""
        return not is_publicly_accountable and is_sme_by_local_definition

    @staticmethod
    def measure_inventory_simplified(
        cost: Money,
        nrv: Money,
    ) -> Money:
        """Persediaan: lower of cost and NRV (sama seperti IAS 2 penuh)."""
        if nrv.amount < cost.amount:
            return nrv
        return cost

    @staticmethod
    def amortize_intangible(
        cost: Money,
        useful_life_years: int,
        residual: Money = Money(Decimal(0), "IDR"),
    ) -> Money:
        """Amortisasi garis lurus (tanpa impairment test terpisah)."""
        if useful_life_years <= 0:
            return Money(Decimal(0), cost.currency)
        annual = (cost.amount - residual.amount) / Decimal(useful_life_years)
        return Money(annual, cost.currency)

    @staticmethod
    def recognize_financial_instruments_simplified(
        cost: Money,
        is_trading: bool,
    ) -> Money:
        """Instrumen keuangan: untuk SMEs, dapat menggunakan biaya perolehan diamortisasi atau fair value through P&L."""
        if is_trading:
            return cost
        return cost


# === 5. IFRS FOR SMES VALIDATION RESULT ===


@dataclass
class IFRSForSMESValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IFRSForSMESValidationResult) -> IFRSForSMESValidationResult:
        return IFRSForSMESValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IFRS FOR SMES RULES ===


class IFRSForSMESRules:
    """
    Aturan IFRS for SMEs:
    - Tidak ada deferred tax (pajak tangguhan) kecuali jika memilih.
    - Tidak ada EPS, segment reporting, interim reporting.
    - Biaya pinjaman langsung diakui beban (tidak dikapitalisasi).
    - Goodwill diamortisasi selama masa manfaat (max 10 tahun).
    - Persediaan: LCNRV.
    - Aset tetap: model biaya atau revaluasi dengan kondisi tertentu.
    """

    @staticmethod
    def validate_goodwill_amortization(
        goodwill_amount: Money,
        useful_life_years: int,
    ) -> IFRSForSMESValidationResult:
        result = IFRSForSMESValidationResult(is_compliant=True)
        if useful_life_years > 10:
            result.add_warning("IFRS for SMEs requires goodwill amortization over max 10 years")
        return result


# === 7. IFRS FOR SMES VALIDATOR ===


class IFRSForSMESValidator:
    """Validator untuk IFRS for SMEs."""

    def __init__(self):
        self._rules = IFRSForSMESRules()

    def validate_entity_status(
        self, status: IFRSForSMESEntityStatus
    ) -> IFRSForSMESValidationResult:
        result = IFRSForSMESValidationResult(is_compliant=True)
        if status.is_publicly_accountable:
            result.add_error("Publicly accountable entity cannot apply IFRS for SMEs")
        if not status.applied_sections:
            result.add_warning("No sections identified; consider full IFRS")
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "eligibility": "Entities without public accountability",
            "simplifications": [
                "No deferred tax (optional)",
                "No EPS/segment/interim reporting",
                "Goodwill amortized over max 10 years",
                "Borrowing costs expensed",
            ],
            "measurement_bases": ["Cost", "Fair value (limited)", "Revaluation (limited)"],
        }


# === 8. SINGLETON ACCESSOR ===

_ifrs_for_smes_validator_instance: IFRSForSMESValidator | None = None


def get_ifrs_for_smes_validator() -> IFRSForSMESValidator:
    global _ifrs_for_smes_validator_instance
    if _ifrs_for_smes_validator_instance is None:
        _ifrs_for_smes_validator_instance = IFRSForSMESValidator()
    return _ifrs_for_smes_validator_instance


# === 9. ALIAS UNTUK KOMPATIBILITAS ===
IFRSForSMESection = IFRSForSMESSection  # alias untuk berjaga-jaga jika ada typo


# === 10. EXPORTS ===

__all__ = [
    "IFRSForSMESEntityStatus",
    "IFRSForSMESExemption",
    "IFRSForSMESMeasurementBasis",
    "IFRSForSMESOption",
    "IFRSForSMESRules",
    "IFRSForSMESSection",
    "IFRSForSMESService",
    "IFRSForSMESValidationResult",
    "IFRSForSMESValidator",
    "IFRSForSMESection",
    "get_ifrs_for_smes_validator",
]
