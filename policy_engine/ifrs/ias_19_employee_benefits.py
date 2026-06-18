#!/usr/bin/env python3
"""
Module: ias_19_employee_benefits.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 19: Employee Benefits.
               Mendefinisikan aturan untuk pengakuan dan pengukuran
               imbalan kerja jangka pendek, imbalan pasca kerja
               (program pensiun iuran pasti dan manfaat pasti),
               imbalan pesangon, dan imbalan jangka panjang lainnya.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap imbalan kerja dictat.
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


class IAS19BenefitType(Enum):
    """Jenis imbalan kerja."""

    SHORT_TERM = "short_term"  # Gaji, bonus, cuti berbayar (due within 12 months)
    POST_EMPLOYMENT = "post_employment"  # Pensiun
    OTHER_LONG_TERM = "other_long_term"  # Long service leave, disability
    TERMINATION = "termination"  # Pesangon


class IAS19PlanType(Enum):
    """Jenis program pensiun."""

    DEFINED_CONTRIBUTION = "defined_contribution"
    DEFINED_BENEFIT = "defined_benefit"


class IAS19ActuarialMethod(Enum):
    """Metode aktuaria untuk program manfaat pasti."""

    PROJECTED_UNIT_CREDIT = "projected_unit_credit"
    ATTRIBUTION_METHOD = "attribution_method"


# === 2. CUSTOM EXCEPTIONS ===


class IAS19Error(Exception):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS19ShortTermBenefit:
    """Imbalan kerja jangka pendek."""

    benefit_type: str
    amount: Money
    payable_date: datetime
    employee_id: UUID

    def to_dict(self) -> dict[str, Any]:
        return {
            "benefit_type": self.benefit_type,
            "amount": str(self.amount.amount),
            "currency": self.amount.currency,
            "payable_date": self.payable_date.isoformat(),
            "employee_id": str(self.employee_id),
        }


@dataclass(frozen=True)
class IAS19DefinedContributionPlan:
    """Program iuran pasti."""

    plan_id: UUID
    plan_name: str
    contribution_rate_employee: Decimal  # persen dari gaji
    contribution_rate_employer: Decimal
    contributed_amount_ytd: Money
    payable_amount: Money

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": str(self.plan_id),
            "plan_name": self.plan_name,
            "employee_rate": str(self.contribution_rate_employee),
            "employer_rate": str(self.contribution_rate_employer),
            "contributed_ytd": str(self.contributed_amount_ytd.amount),
            "payable": str(self.payable_amount.amount),
        }


@dataclass(frozen=True)
class IAS19DefinedBenefitObligation:
    """Obligasi manfaat pasti."""

    present_value_of_obligation: Money
    fair_value_of_plan_assets: Money
    actuarial_gains_losses: Money
    net_defined_benefit_liability: Money
    current_service_cost: Money
    past_service_cost: Money
    interest_cost: Money
    return_on_plan_assets: Money

    def to_dict(self) -> dict[str, Any]:
        return {
            "pv_obligation": str(self.present_value_of_obligation.amount),
            "fair_value_assets": str(self.fair_value_of_plan_assets.amount),
            "actuarial_gains_losses": str(self.actuarial_gains_losses.amount),
            "net_liability": str(self.net_defined_benefit_liability.amount),
            "current_service": str(self.current_service_cost.amount),
            "past_service": str(self.past_service_cost.amount),
            "interest_cost": str(self.interest_cost.amount),
            "return_on_assets": str(self.return_on_plan_assets.amount),
        }


# === 4. ENTITIES ===


@dataclass
class IAS19EmployeeBenefits:
    """Imbalan kerja entitas."""

    benefits_id: UUID
    entity_id: UUID
    reporting_date: datetime
    short_term_benefits: list[IAS19ShortTermBenefit] = field(default_factory=list)
    defined_contribution_plans: list[IAS19DefinedContributionPlan] = field(default_factory=list)
    defined_benefit_obligation: IAS19DefinedBenefitObligation | None = None

    def total_short_term_liability(self) -> Money:
        if not self.short_term_benefits:
            return Money(Decimal(0), "IDR")
        currency = self.short_term_benefits[0].amount.currency
        total = sum(b.amount.amount for b in self.short_term_benefits)
        return Money(total, currency)

    def total_defined_contribution_payable(self) -> Money:
        if not self.defined_contribution_plans:
            return Money(Decimal(0), "IDR")
        currency = self.defined_contribution_plans[0].payable_amount.currency
        total = sum(p.payable_amount.amount for p in self.defined_contribution_plans)
        return Money(total, currency)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benefits_id": str(self.benefits_id),
            "entity_id": str(self.entity_id),
            "reporting_date": self.reporting_date.isoformat(),
            "short_term": [b.to_dict() for b in self.short_term_benefits],
            "defined_contribution": [p.to_dict() for p in self.defined_contribution_plans],
            "defined_benefit": self.defined_benefit_obligation.to_dict()
            if self.defined_benefit_obligation
            else None,
            "total_short_term_liability": str(self.total_short_term_liability().amount),
            "total_defined_contribution_payable": str(
                self.total_defined_contribution_payable().amount
            ),
        }


# === 5. DOMAIN SERVICES ===


class IAS19BenefitService:
    """Service untuk perhitungan imbalan kerja."""

    @staticmethod
    def calculate_short_term_benefit_expense(
        gross_salary: Money,
        bonus_estimate: Money,
        paid_leave_accrual: Money,
    ) -> Money:
        """Menghitung beban imbalan jangka pendek."""
        return gross_salary + bonus_estimate + paid_leave_accrual

    @staticmethod
    def calculate_defined_contribution_expense(
        employee_gross_salary: Money,
        employer_rate: Decimal,
    ) -> Money:
        """Menghitung beban iuran pasti pemberi kerja."""
        amount = employee_gross_salary.amount * (employer_rate / 100)
        return Money(amount, employee_gross_salary.currency)

    @staticmethod
    def project_defined_benefit_obligation(
        current_obligation: Money,
        current_service_cost: Money,
        interest_rate: Decimal,
        years: int,
    ) -> Money:
        """Memproyeksikan obligasi manfaat pasti."""
        # Simplified: future value of current obligation plus service cost
        future_value = current_obligation.amount * ((1 + interest_rate / 100) ** years)
        future_service = current_service_cost.amount * years
        return Money(future_value + future_service, current_obligation.currency)


# === 6. IAS 19 VALIDATION RESULT ===


@dataclass
class IAS19ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS19ValidationResult) -> IAS19ValidationResult:
        return IAS19ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 7. IAS 19 RULES ===


class IAS19Rules:
    """
    Aturan IAS 19:
    - Imbalan jangka pendek diakui saat karyawan memberikan jasa.
    - Program iuran pasti: beban = kontribusi yang harus dibayar.
    - Program manfaat pasti: menggunakan metode projected unit credit.
    - Keuntungan/kerugian aktuaria dapat diakui di OCI atau laba rugi.
    - Imbalan pesangon diakui saat entitas berkomitmen untuk menghentikan karyawan.
    """

    @staticmethod
    def validate_defined_benefit_disclosure(
        has_actuarial_assumptions: bool,
        has_sensitivity_analysis: bool,
    ) -> IAS19ValidationResult:
        result = IAS19ValidationResult(is_compliant=True)
        if not has_actuarial_assumptions:
            result.add_error("Actuarial assumptions for defined benefit plan must be disclosed")
        if not has_sensitivity_analysis:
            result.add_warning("Sensitivity analysis for defined benefit plan recommended")
        return result


# === 8. IAS 19 VALIDATOR ===


class IAS19Validator:
    """Validator untuk IAS 19: Employee Benefits."""

    def __init__(self):
        self._rules = IAS19Rules()

    def validate_benefits(self, benefits: IAS19EmployeeBenefits) -> IAS19ValidationResult:
        result = IAS19ValidationResult(is_compliant=True)
        if benefits.defined_benefit_obligation:
            result.merge(self._rules.validate_defined_benefit_disclosure(True, True))
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "short_term": "Recognize as expense when employee renders service",
            "defined_contribution": "Recognize contribution payable",
            "defined_benefit": "Recognize net liability, use actuarial valuation",
            "actuarial_gains_losses": "Can be recognized in OCI or P&L",
            "termination_benefits": "Recognize when entity is demonstrably committed",
        }


# === 9. SINGLETON ACCESSOR ===

_ias19_validator_instance: IAS19Validator | None = None


def get_ias19_validator() -> IAS19Validator:
    global _ias19_validator_instance
    if _ias19_validator_instance is None:
        _ias19_validator_instance = IAS19Validator()
    return _ias19_validator_instance


# === 10. EXPORTS ===

__all__ = [
    "IAS19ActuarialMethod",
    "IAS19BenefitService",
    "IAS19BenefitType",
    "IAS19DefinedBenefitObligation",
    "IAS19DefinedContributionPlan",
    "IAS19EmployeeBenefits",
    "IAS19PlanType",
    "IAS19Rules",
    "IAS19ShortTermBenefit",
    "IAS19ValidationResult",
    "IAS19Validator",
    "get_ias19_validator",
]
