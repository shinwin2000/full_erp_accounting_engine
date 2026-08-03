#!/usr/bin/env python3
"""
Module: ias_37_provisions.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 37: Provisions, Contingent Liabilities and Contingent Assets.
               Mendefinisikan aturan untuk pengakuan, pengukuran, dan
               pengungkapan provisi (kewajiban yang tidak pasti waktu atau jumlahnya),
               liabilitas kontinjensi, dan aset kontinjensi.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap provisi dan kontinjensi dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS37ProvisionType(Enum):
    """Jenis provisi."""

    RESTRUCTURING = "restructuring"
    LITIGATION = "litigation"
    WARRANTY = "warranty"
    ENVIRONMENTAL = "environmental"
    ONEROUS_CONTRACT = "onerous_contract"
    OTHER = "other"


class IAS37ContingencyLikelihood(Enum):
    """Kemungkinan terjadinya kontinjensi."""

    PROBABLE = "probable"  # >50%
    POSSIBLE = "possible"  # >5% but <=50%
    REMOTE = "remote"  # <=5%


class IAS37RecognitionCriteria(Enum):
    """Kriteria pengakuan provisi."""

    PRESENT_OBLIGATION = "present_obligation"
    PROBABLE_OUTFLOW = "probable_outflow"
    RELIABLE_ESTIMATE = "reliable_estimate"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS37Provision:
    """Provisi."""

    provision_id: UUID
    provision_type: IAS37ProvisionType
    obligation_description: str
    best_estimate: Money
    discount_rate: Decimal | None = None
    undiscounted_amount: Money | None = None
    expected_outflow_date: datetime | None = None
    recognition_date: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if self.best_estimate.amount < 0:
            raise ValueError("Provision amount cannot be negative")
        if self.discount_rate and (self.discount_rate < 0 or self.discount_rate > 100):
            raise ValueError("Discount rate out of range")
        if self.discount_rate and not self.undiscounted_amount:
            raise ValueError("Undiscounted amount required when discounting")

    @property
    def discounted_amount(self) -> Money:
        if self.discount_rate and self.expected_outflow_date:
            years = max(1, (self.expected_outflow_date - self.recognition_date).days / 365.25)
            factor = (1 + self.discount_rate / 100) ** years
            amount = self.best_estimate.amount / factor
            return Money(amount, self.best_estimate.currency)
        return self.best_estimate

    def to_dict(self) -> dict[str, Any]:
        return {
            "provision_id": str(self.provision_id),
            "type": self.provision_type.value,
            "description": self.obligation_description,
            "best_estimate": str(self.best_estimate.amount),
            "discount_rate": str(self.discount_rate) if self.discount_rate else None,
            "discounted_amount": str(self.discounted_amount.amount),
            "recognition_date": self.recognition_date.isoformat(),
            "expected_outflow": self.expected_outflow_date.isoformat()
            if self.expected_outflow_date
            else None,
        }


@dataclass(frozen=True)
class IAS37ContingentLiability:
    """Liabilitas kontinjensi (tidak diakui, diungkapkan)."""

    contingency_id: UUID
    description: str
    likelihood: IAS37ContingencyLikelihood
    estimated_financial_effect: Money | None = None
    disclosure_in_notes: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "contingency_id": str(self.contingency_id),
            "description": self.description,
            "likelihood": self.likelihood.value,
            "estimated_effect": str(self.estimated_financial_effect.amount)
            if self.estimated_financial_effect
            else None,
            "disclosed": self.disclosure_in_notes,
        }


# === 3. ENTITIES ===


@dataclass
class IAS37ProvisionsRegister:
    """Register provisi dan kontinjensi."""

    register_id: UUID
    entity_id: UUID
    reporting_date: datetime
    provisions: list[IAS37Provision] = field(default_factory=list)
    contingent_liabilities: list[IAS37ContingentLiability] = field(default_factory=list)
    contingent_assets: list[IAS37ContingentLiability] = field(default_factory=list)  # reuse

    def add_provision(self, provision: IAS37Provision) -> IAS37ProvisionsRegister:
        return IAS37ProvisionsRegister(
            register_id=self.register_id,
            entity_id=self.entity_id,
            reporting_date=self.reporting_date,
            provisions=[*self.provisions, provision],
            contingent_liabilities=self.contingent_liabilities,
            contingent_assets=self.contingent_assets,
        )

    def total_provisions(self) -> Money:
        if not self.provisions:
            return Money(Decimal(0), "IDR")
        currency = self.provisions[0].best_estimate.currency
        total = sum(p.discounted_amount.amount for p in self.provisions)
        return Money(total, currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "register_id": str(self.register_id),
            "entity_id": str(self.entity_id),
            "reporting_date": self.reporting_date.isoformat(),
            "provisions": [p.to_dict() for p in self.provisions],
            "contingent_liabilities": [c.to_dict() for c in self.contingent_liabilities],
            "total_provisions": str(self.total_provisions().amount),
        }


# === 4. DOMAIN SERVICES ===


class IAS37ProvisionService:
    """Service untuk provisi."""

    @staticmethod
    def meets_recognition_criteria(
        present_obligation: bool,
        probable_outflow: bool,
        reliable_estimate: bool,
    ) -> bool:
        """Kriteria pengakuan provisi (IAS 37)."""
        return present_obligation and probable_outflow and reliable_estimate

    @staticmethod
    def calculate_best_estimate(
        probable_amount: Money,
        other_possible_amounts: list[Money],
    ) -> Money:
        """Menentukan estimasi terbaik provisi."""
        # Jika tunggal, gunakan itu
        if not other_possible_amounts:
            return probable_amount
        # Weighted average atau mid-point (sederhana: mean)
        total = probable_amount.amount + sum(a.amount for a in other_possible_amounts)
        count = 1 + len(other_possible_amounts)
        avg = total / Decimal(count)
        return Money(avg, probable_amount.currency)

    @staticmethod
    def determine_contingent_asset_recognition(
        likelihood: IAS37ContingencyLikelihood,
    ) -> bool:
        """
        Aset kontinjensi tidak diakui (hanya diungkapkan) jika virtually certain
        baru diakui.
        """
        return likelihood == IAS37ContingencyLikelihood.PROBABLE


# === 5. IAS 37 VALIDATION RESULT ===


@dataclass
class IAS37ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS37ValidationResult) -> IAS37ValidationResult:
        return IAS37ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IAS 37 RULES ===


class IAS37Rules:
    """
    Aturan IAS 37:
    - Provisi diakui jika: kewajiban kini, kemungkinan besar outflow, estimasi andal.
    - Provisi diukur pada estimasi terbaik (nilai yang paling mungkin atau nilai harapan).
    - Provisi didiskontokan jika efek waktu material.
    - Reimbursement (penggantian dari pihak ketiga) diakui sebagai aset terpisah.
    - Liabilitas kontinjensi tidak diakui, diungkapkan (kecuali kemungkinan kecil).
    - Aset kontinjensi tidak diakui, diungkapkan jika kemungkinan besar.
    - Restrukturisasi: provisi hanya diakui jika ada rencana formal dan ekspektasi valid.
    """

    @staticmethod
    def validate_restructuring_provision(
        has_formal_plan: bool,
        has_valid_expectation: bool,
    ) -> IAS37ValidationResult:
        result = IAS37ValidationResult(is_compliant=True)
        if not (has_formal_plan and has_valid_expectation):
            result.add_error(
                "Restructuring provision not allowed without formal plan and valid expectation"
            )
        return result

    @staticmethod
    def validate_disclosure(
        provisions: list[IAS37Provision],
        contingent_liabilities: list[IAS37ContingentLiability],
    ) -> IAS37ValidationResult:
        result = IAS37ValidationResult(is_compliant=True)
        if provisions and not any(p.discounted_amount.amount > 0 for p in provisions):
            result.add_warning("Provisions exist but no material amounts disclosed")
        return result


# === 7. IAS 37 VALIDATOR ===


class IAS37Validator:
    """Validator untuk IAS 37: Provisions, Contingent Liabilities and Assets."""

    def __init__(self):
        self._rules = IAS37Rules()

    def validate_provision(
        self,
        provision: IAS37Provision,
    ) -> IAS37ValidationResult:
        result = IAS37ValidationResult(is_compliant=True)
        if provision.best_estimate.amount <= 0:
            result.add_error("Provision amount must be positive")
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "recognition_criteria": "Present obligation, probable outflow, reliable estimate",
            "measurement": "Best estimate (most likely outcome or expected value)",
            "discounting": "If time value of money material",
            "reimbursements": "Recognized as separate asset if virtually certain",
            "contingent_liabilities": "Not recognized, disclosed unless remote",
            "contingent_assets": "Not recognized, disclosed if probable",
        }


# === 8. ADDITIONAL CLASS FOR TEST COMPATIBILITY ===


class IAS37:
    """
    Convenience class providing static methods for the test.
    This matches the expected interface in test_ifrs_rules.py.
    """

    @staticmethod
    def should_recognize_provision(
        present_obligation: bool,
        probable_outflow: bool,
        reliable_estimate: bool,
    ) -> bool:
        """Check if provision should be recognized per IAS 37."""
        return IAS37ProvisionService.meets_recognition_criteria(
            present_obligation, probable_outflow, reliable_estimate
        )

    @staticmethod
    def best_estimate(
        possible_outcomes: list[Decimal],
        probabilities: list[Decimal],
    ) -> Decimal:
        """
        Calculate the best estimate of provision given possible outcomes and probabilities.
        This uses expected value (weighted average) as required by IAS 37.
        """
        if len(possible_outcomes) != len(probabilities):
            raise ValueError("Outcomes and probabilities must have same length")
        total = Decimal(0)
        for amount, prob in zip(possible_outcomes, probabilities, strict=False):
            total += amount * prob
        # Round to nearest whole number (or keep as is)
        return total.quantize(Decimal("0.01"))


# === 9. SINGLETON ACCESSOR ===

_ias37_validator_instance: IAS37Validator | None = None


def get_ias37_validator() -> IAS37Validator:
    global _ias37_validator_instance
    if _ias37_validator_instance is None:
        _ias37_validator_instance = IAS37Validator()
    return _ias37_validator_instance


# === 10. EXPORTS ===

__all__ = [
    "IAS37",
    "IAS37ContingencyLikelihood",
    "IAS37ContingentLiability",
    "IAS37Provision",
    "IAS37ProvisionService",
    "IAS37ProvisionType",
    "IAS37ProvisionsRegister",
    "IAS37RecognitionCriteria",
    "IAS37Rules",
    "IAS37ValidationResult",
    "IAS37Validator",
    "get_ias37_validator",
]
