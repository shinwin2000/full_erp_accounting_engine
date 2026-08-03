#!/usr/bin/env python3
"""
Module: psak_24_employee_benefits.py
Layer: 7 - Policy Engine & Standards / PSAK

Responsibility:
    PSAK 24: Imbalan Kerja (setara dengan IAS 19).
    Mengatur perlakuan akuntansi dan pengungkapan untuk imbalan kerja,
    termasuk imbalan kerja jangka pendek (gaji, bonus, cuti berbayar),
    imbalan pasca kerja (program iuran pasti dan program manfaat pasti),
    imbalan jangka panjang lainnya (cuti panjang, penghargaan masa kerja),
    dan imbalan pemutusan hubungan kerja (pesangon).
    Untuk program manfaat pasti, menggunakan metode projected unit credit
    untuk menentukan nilai kini kewajiban dan biaya jasa kini.

Dependencies:
    - datetime, decimal, enum, typing, dataclasses, uuid, hashlib, logging, math

Audit:
    Setiap imbalan kerja, perhitungan aktuaria, dan pembayaran dicatat dengan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PSAK24BenefitType(Enum):
    SHORT_TERM = "jangka_pendek"  # due within 12 months
    POST_EMPLOYMENT = "pasca_kerja"  # pensiun
    OTHER_LONG_TERM = "jangka_panjang_lain"
    TERMINATION = "pemutusan_kerja"  # pesangon


class PSAK24PlanType(Enum):
    DEFINED_CONTRIBUTION = "iuran_pasti"
    DEFINED_BENEFIT = "manfaat_pasti"


class PSAK24ActuarialMethod(Enum):
    PROJECTED_UNIT_CREDIT = "proyeksi_unit_kredit"
    ATTRIBUTION_METHOD = "atribusi"


class PSAK24ValuationFrequency(Enum):
    ANNUALLY = "tahunan"
    EVERY_3_YEARS = "3_tahun"
    EVERY_5_YEARS = "5_tahun"


class PSAK24ComplianceLevel(Enum):
    FULL = "penuh"
    SUBSTANTIAL = "substansial"
    PARTIAL = "sebagian"
    NON_COMPLIANT = "tidak_patuh"


# ============================================================================
# Exceptions
# ============================================================================
class PSAK24Error(Exception):
    pass


class ActuarialValuationError(PSAK24Error):
    pass


class PlanNotFoundError(PSAK24Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class PSAK24ShortTermBenefit:
    """Imbalan kerja jangka pendek (gaji, bonus, cuti berbayar, dll)."""

    benefit_id: UUID
    employee_id: UUID
    employee_name: str
    benefit_type: str  # gaji, bonus, cuti, THR, dll
    amount: Decimal
    currency: str
    period_start: date
    period_end: date
    payable_date: date
    is_accrued: bool = True
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "benefit_id": str(self.benefit_id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "benefit_type": self.benefit_type,
            "amount": str(self.amount),
            "currency": self.currency,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "payable_date": self.payable_date.isoformat(),
            "is_accrued": self.is_accrued,
            "notes": self.notes,
        }


@dataclass
class PSAK24DefinedContributionPlan:
    """Program iuran pasti."""

    plan_id: UUID
    plan_name: str
    plan_number: str
    contribution_rate_employee: Decimal  # persen dari gaji
    contribution_rate_employer: Decimal
    contribution_amount_ytd_employee: Decimal
    contribution_amount_ytd_employer: Decimal
    payable_employee: Decimal
    payable_employer: Decimal
    currency: str
    notes: str = ""

    def total_contribution_ytd(self) -> Decimal:
        return self.contribution_amount_ytd_employee + self.contribution_amount_ytd_employer

    def total_payable(self) -> Decimal:
        return self.payable_employee + self.payable_employer

    def to_dict(self) -> dict:
        return {
            "plan_id": str(self.plan_id),
            "plan_name": self.plan_name,
            "plan_number": self.plan_number,
            "employee_rate": str(self.contribution_rate_employee),
            "employer_rate": str(self.contribution_rate_employer),
            "employee_ytd": str(self.contribution_amount_ytd_employee),
            "employer_ytd": str(self.contribution_amount_ytd_employer),
            "payable_employee": str(self.payable_employee),
            "payable_employer": str(self.payable_employer),
            "total_ytd": str(self.total_contribution_ytd()),
            "total_payable": str(self.total_payable()),
            "currency": self.currency,
            "notes": self.notes,
        }


@dataclass
class PSAK24ActuarialAssumption:
    """Asumsi aktuaria untuk program manfaat pasti."""

    discount_rate: Decimal  # persen
    future_salary_increase_rate: Decimal  # persen
    pension_increase_rate: Decimal  # persen
    mortality_table: str
    employee_turnover_rate: Decimal  # persen
    retirement_age: int
    mortality_adjustment_factor: Decimal = Decimal(1)
    disability_rate: Decimal = Decimal("0.001")

    def to_dict(self) -> dict:
        return {
            "discount_rate": str(self.discount_rate),
            "salary_increase": str(self.future_salary_increase_rate),
            "pension_increase": str(self.pension_increase_rate),
            "mortality_table": self.mortality_table,
            "turnover_rate": str(self.employee_turnover_rate),
            "retirement_age": self.retirement_age,
            "mortality_factor": str(self.mortality_adjustment_factor),
            "disability_rate": str(self.disability_rate),
        }


@dataclass
class PSAK24DefinedBenefitObligation:
    """Obligasi manfaat pasti."""

    obligation_id: UUID
    plan_id: UUID
    valuation_date: date
    present_value_of_obligation: Decimal  # DBO (defined benefit obligation)
    fair_value_of_plan_assets: Decimal
    net_defined_benefit_liability: Decimal
    current_service_cost: Decimal
    past_service_cost: Decimal
    interest_cost: Decimal
    actuarial_gains_losses: Decimal
    return_on_plan_assets: Decimal
    contributions_paid: Decimal
    benefits_paid: Decimal
    actuarial_assumptions: PSAK24ActuarialAssumption
    valuation_performed_by: str
    next_valuation_date: date | None = None
    notes: str = ""

    def surplus_deficit(self) -> Decimal:
        return self.fair_value_of_plan_assets - self.present_value_of_obligation

    def to_dict(self) -> dict:
        return {
            "obligation_id": str(self.obligation_id),
            "plan_id": str(self.plan_id),
            "valuation_date": self.valuation_date.isoformat(),
            "pvo": str(self.present_value_of_obligation),
            "fv_assets": str(self.fair_value_of_plan_assets),
            "net_liability": str(self.net_defined_benefit_liability),
            "surplus_deficit": str(self.surplus_deficit()),
            "current_service": str(self.current_service_cost),
            "past_service": str(self.past_service_cost),
            "interest_cost": str(self.interest_cost),
            "actuarial_gains_losses": str(self.actuarial_gains_losses),
            "return_on_assets": str(self.return_on_plan_assets),
            "contributions": str(self.contributions_paid),
            "benefits_paid": str(self.benefits_paid),
            "assumptions": self.actuarial_assumptions.to_dict(),
            "valuator": self.valuation_performed_by,
            "next_valuation": self.next_valuation_date.isoformat()
            if self.next_valuation_date
            else None,
        }


@dataclass
class PSAK24TerminationBenefit:
    """Imbalan pemutusan hubungan kerja (pesangon)."""

    benefit_id: UUID
    employee_id: UUID
    employee_name: str
    termination_date: date
    years_of_service: int
    last_salary: Decimal
    severance_pay: Decimal
    compensation_for_leave: Decimal
    other_benefits: Decimal
    total_amount: Decimal
    currency: str
    is_accrued: bool = True
    approved_by: UUID | None = None
    approval_date: date | None = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "benefit_id": str(self.benefit_id),
            "employee_id": str(self.employee_id),
            "employee_name": self.employee_name,
            "termination_date": self.termination_date.isoformat(),
            "years_of_service": self.years_of_service,
            "last_salary": str(self.last_salary),
            "severance": str(self.severance_pay),
            "leave_comp": str(self.compensation_for_leave),
            "other": str(self.other_benefits),
            "total": str(self.total_amount),
            "currency": self.currency,
            "is_accrued": self.is_accrued,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approval_date": self.approval_date.isoformat() if self.approval_date else None,
        }


@dataclass
class PSAK24EmployeeBenefitsSummary:
    """Ringkasan imbalan kerja entitas."""

    summary_id: UUID
    entity_id: UUID
    entity_name: str
    reporting_date: date
    short_term_benefits: list[PSAK24ShortTermBenefit] = field(default_factory=list)
    defined_contribution_plans: list[PSAK24DefinedContributionPlan] = field(default_factory=list)
    defined_benefit_obligations: list[PSAK24DefinedBenefitObligation] = field(default_factory=list)
    termination_benefits: list[PSAK24TerminationBenefit] = field(default_factory=list)

    def total_short_term_liability(self) -> Decimal:
        return sum(b.amount for b in self.short_term_benefits if b.is_accrued)

    def total_defined_contribution_payable(self) -> Decimal:
        return sum(p.total_payable() for p in self.defined_contribution_plans)

    def total_defined_benefit_liability(self) -> Decimal:
        return sum(o.net_defined_benefit_liability for o in self.defined_benefit_obligations)

    def total_termination_liability(self) -> Decimal:
        return sum(t.total_amount for t in self.termination_benefits if t.is_accrued)

    def total_employee_benefits_liability(self) -> Decimal:
        return (
            self.total_short_term_liability()
            + self.total_defined_contribution_payable()
            + self.total_defined_benefit_liability()
            + self.total_termination_liability()
        )

    def to_dict(self) -> dict:
        return {
            "summary_id": str(self.summary_id),
            "entity_id": str(self.entity_id),
            "entity_name": self.entity_name,
            "reporting_date": self.reporting_date.isoformat(),
            "short_term": [b.to_dict() for b in self.short_term_benefits],
            "defined_contribution": [p.to_dict() for p in self.defined_contribution_plans],
            "defined_benefit": [o.to_dict() for o in self.defined_benefit_obligations],
            "termination": [t.to_dict() for t in self.termination_benefits],
            "total_short_term": str(self.total_short_term_liability()),
            "total_dc_payable": str(self.total_defined_contribution_payable()),
            "total_db_liability": str(self.total_defined_benefit_liability()),
            "total_termination": str(self.total_termination_liability()),
            "total_benefits_liability": str(self.total_employee_benefits_liability()),
        }


@dataclass
class PSAK24ValidationResult:
    is_compliant: bool
    compliance_level: PSAK24ComplianceLevel
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "is_compliant": self.is_compliant,
            "level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False
        if self.compliance_level != PSAK24ComplianceLevel.NON_COMPLIANT:
            self.compliance_level = PSAK24ComplianceLevel.NON_COMPLIANT

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)
        if self.compliance_level == PSAK24ComplianceLevel.FULL:
            self.compliance_level = PSAK24ComplianceLevel.SUBSTANTIAL

    def to_dict(self) -> dict:
        return {
            "is_compliant": self.is_compliant,
            "compliance_level": self.compliance_level.value,
            "errors": self.errors,
            "warnings": self.warnings,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Domain Services (Actuarial Calculation)
# ============================================================================
class PSAK24ActuarialService:
    """Service untuk perhitungan aktuaria program manfaat pasti (metode projected unit credit)."""

    @staticmethod
    def calculate_present_value_factor(rate: Decimal, years: int) -> Decimal:
        """Faktor nilai tunai: 1 / (1 + rate)^years."""
        if years == 0:
            return Decimal(1)
        return Decimal(1) / ((Decimal(1) + rate / 100) ** years)

    @staticmethod
    def projected_unit_credit(
        current_salary: Decimal,
        years_to_retirement: int,
        salary_growth_rate: Decimal,
        discount_rate: Decimal,
        benefit_formula_factor: Decimal,
        mortality_factor: Decimal = Decimal(1),
    ) -> Decimal:
        """
        Menghitung nilai kini kewajiban manfaat pasti menggunakan metode projected unit credit.
        benefit = final_salary * years_of_service * benefit_formula_factor
        """
        # Proyeksikan gaji akhir
        final_salary = current_salary * (
            (Decimal(1) + salary_growth_rate / 100) ** years_to_retirement
        )
        # Benefit yang akan diterima (per tahun)
        annual_benefit = final_salary * benefit_formula_factor
        # Nilai tunai dari benefit (asumsi benefit dibayar selama 15 tahun setelah pensiun)
        # Sederhanakan: annuity factor untuk 15 tahun
        annuity_factor = sum(
            PSAK24ActuarialService.calculate_present_value_factor(discount_rate, t)
            for t in range(1, 16)
        )
        pv_benefit = annual_benefit * annuity_factor * mortality_factor
        return pv_benefit.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    @staticmethod
    def calculate_current_service_cost(
        benefit_pv: Decimal,
        years_worked: int,
        total_years: int,
    ) -> Decimal:
        """Biaya jasa kini: alokasi nilai manfaat ke tahun berjalan."""
        if total_years == 0:
            return Decimal(0)
        return (benefit_pv * Decimal(years_worked) / Decimal(total_years)).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def compute_interest_cost(obligation_begin: Decimal, discount_rate: Decimal) -> Decimal:
        return (obligation_begin * discount_rate / 100).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )

    @staticmethod
    def compute_return_on_plan_assets(
        assets_begin: Decimal, expected_return_rate: Decimal
    ) -> Decimal:
        return (assets_begin * expected_return_rate / 100).quantize(
            Decimal("0"), rounding=ROUND_HALF_EVEN
        )


# ============================================================================
# Rules
# ============================================================================
class PSAK24Rules:
    """Aturan PSAK 24."""

    @staticmethod
    def validate_actuarial_assumptions(
        assumptions: PSAK24ActuarialAssumption,
    ) -> PSAK24ValidationResult:
        result = PSAK24ValidationResult(
            is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL
        )
        if assumptions.discount_rate < 0 or assumptions.discount_rate > 20:
            result.add_warning("Tingkat diskonto di luar kisaran normal (0-20%)")
        if (
            assumptions.future_salary_increase_rate < 0
            or assumptions.future_salary_increase_rate > 20
        ):
            result.add_warning("Tingkat kenaikan gaji tidak realistis")
        if assumptions.retirement_age < 50 or assumptions.retirement_age > 70:
            result.add_warning("Usia pensiun di luar kisaran normal")
        return result

    @staticmethod
    def validate_plan_asset(
        plan: PSAK24DefinedContributionPlan, obligation: PSAK24DefinedBenefitObligation
    ) -> PSAK24ValidationResult:
        result = PSAK24ValidationResult(
            is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL
        )
        if obligation.fair_value_of_plan_assets < 0:
            result.add_error("Nilai wajar aset program tidak boleh negatif")
        return result

    @staticmethod
    def validate_disclosure(liability: Decimal, plan_assets: Decimal) -> PSAK24ValidationResult:
        result = PSAK24ValidationResult(
            is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL
        )
        if liability > 0 and plan_assets == 0:
            result.add_warning("Kewajiban manfaat pasti ada tetapi tidak ada aset program")
        return result


# ============================================================================
# Validator
# ============================================================================
class PSAK24Validator:
    def __init__(self):
        self._rules = PSAK24Rules()
        self._actuarial_service = PSAK24ActuarialService()

    # Short-term benefits
    def create_short_term_benefit(
        self,
        employee_id: UUID,
        employee_name: str,
        benefit_type: str,
        amount: Decimal,
        currency: str,
        period_start: date,
        period_end: date,
        payable_date: date,
        notes: str = "",
    ) -> PSAK24ShortTermBenefit:
        return PSAK24ShortTermBenefit(
            benefit_id=uuid4(),
            employee_id=employee_id,
            employee_name=employee_name,
            benefit_type=benefit_type,
            amount=amount,
            currency=currency,
            period_start=period_start,
            period_end=period_end,
            payable_date=payable_date,
            notes=notes,
        )

    # Defined contribution plan
    def create_defined_contribution_plan(
        self,
        plan_name: str,
        plan_number: str,
        contribution_rate_employee: Decimal,
        contribution_rate_employer: Decimal,
        currency: str,
        notes: str = "",
    ) -> PSAK24DefinedContributionPlan:
        return PSAK24DefinedContributionPlan(
            plan_id=uuid4(),
            plan_name=plan_name,
            plan_number=plan_number,
            contribution_rate_employee=contribution_rate_employee,
            contribution_rate_employer=contribution_rate_employer,
            contribution_amount_ytd_employee=Decimal(0),
            contribution_amount_ytd_employer=Decimal(0),
            payable_employee=Decimal(0),
            payable_employer=Decimal(0),
            currency=currency,
            notes=notes,
        )

    def record_dc_contribution(
        self,
        plan: PSAK24DefinedContributionPlan,
        employee_contribution: Decimal,
        employer_contribution: Decimal,
        is_payable: bool = False,
    ) -> PSAK24DefinedContributionPlan:
        new_employee_ytd = plan.contribution_amount_ytd_employee + employee_contribution
        new_employer_ytd = plan.contribution_amount_ytd_employer + employer_contribution
        new_payable_employee = plan.payable_employee + (employee_contribution if is_payable else 0)
        new_payable_employer = plan.payable_employer + (employer_contribution if is_payable else 0)
        return PSAK24DefinedContributionPlan(
            plan_id=plan.plan_id,
            plan_name=plan.plan_name,
            plan_number=plan.plan_number,
            contribution_rate_employee=plan.contribution_rate_employee,
            contribution_rate_employer=plan.contribution_rate_employer,
            contribution_amount_ytd_employee=new_employee_ytd,
            contribution_amount_ytd_employer=new_employer_ytd,
            payable_employee=new_payable_employee,
            payable_employer=new_payable_employer,
            currency=plan.currency,
            notes=plan.notes,
        )

    # Defined benefit obligation (simplified actuarial)
    def create_actuarial_assumptions(
        self,
        discount_rate: Decimal,
        salary_increase_rate: Decimal,
        pension_increase_rate: Decimal,
        mortality_table: str,
        turnover_rate: Decimal,
        retirement_age: int,
    ) -> PSAK24ActuarialAssumption:
        return PSAK24ActuarialAssumption(
            discount_rate=discount_rate,
            future_salary_increase_rate=salary_increase_rate,
            pension_increase_rate=pension_increase_rate,
            mortality_table=mortality_table,
            employee_turnover_rate=turnover_rate,
            retirement_age=retirement_age,
        )

    def create_defined_benefit_obligation(
        self,
        plan_id: UUID,
        valuation_date: date,
        present_value_obligation: Decimal,
        fair_value_assets: Decimal,
        current_service_cost: Decimal,
        past_service_cost: Decimal,
        interest_cost: Decimal,
        actuarial_gains_losses: Decimal,
        return_on_assets: Decimal,
        contributions_paid: Decimal,
        benefits_paid: Decimal,
        assumptions: PSAK24ActuarialAssumption,
        valuator: str,
    ) -> PSAK24DefinedBenefitObligation:
        net_liability = present_value_obligation - fair_value_assets
        return PSAK24DefinedBenefitObligation(
            obligation_id=uuid4(),
            plan_id=plan_id,
            valuation_date=valuation_date,
            present_value_of_obligation=present_value_obligation,
            fair_value_of_plan_assets=fair_value_assets,
            net_defined_benefit_liability=net_liability,
            current_service_cost=current_service_cost,
            past_service_cost=past_service_cost,
            interest_cost=interest_cost,
            actuarial_gains_losses=actuarial_gains_losses,
            return_on_plan_assets=return_on_assets,
            contributions_paid=contributions_paid,
            benefits_paid=benefits_paid,
            actuarial_assumptions=assumptions,
            valuation_performed_by=valuator,
        )

    # Termination benefits
    def create_termination_benefit(
        self,
        employee_id: UUID,
        employee_name: str,
        termination_date: date,
        years_of_service: int,
        last_salary: Decimal,
        severance_pay: Decimal,
        compensation_for_leave: Decimal,
        other_benefits: Decimal,
        currency: str,
        approved_by: UUID | None = None,
    ) -> PSAK24TerminationBenefit:
        total = severance_pay + compensation_for_leave + other_benefits
        return PSAK24TerminationBenefit(
            benefit_id=uuid4(),
            employee_id=employee_id,
            employee_name=employee_name,
            termination_date=termination_date,
            years_of_service=years_of_service,
            last_salary=last_salary,
            severance_pay=severance_pay,
            compensation_for_leave=compensation_for_leave,
            other_benefits=other_benefits,
            total_amount=total,
            currency=currency,
            approved_by=approved_by,
        )

    # Summary
    def create_summary(
        self,
        entity_id: UUID,
        entity_name: str,
        reporting_date: date,
    ) -> PSAK24EmployeeBenefitsSummary:
        return PSAK24EmployeeBenefitsSummary(
            summary_id=uuid4(),
            entity_id=entity_id,
            entity_name=entity_name,
            reporting_date=reporting_date,
        )

    def add_short_term_benefit(
        self, summary: PSAK24EmployeeBenefitsSummary, benefit: PSAK24ShortTermBenefit
    ) -> PSAK24EmployeeBenefitsSummary:
        new_list = [*summary.short_term_benefits, benefit]
        return PSAK24EmployeeBenefitsSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            reporting_date=summary.reporting_date,
            short_term_benefits=new_list,
            defined_contribution_plans=summary.defined_contribution_plans,
            defined_benefit_obligations=summary.defined_benefit_obligations,
            termination_benefits=summary.termination_benefits,
        )

    def add_defined_contribution_plan(
        self, summary: PSAK24EmployeeBenefitsSummary, plan: PSAK24DefinedContributionPlan
    ) -> PSAK24EmployeeBenefitsSummary:
        new_list = [*summary.defined_contribution_plans, plan]
        return PSAK24EmployeeBenefitsSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            reporting_date=summary.reporting_date,
            short_term_benefits=summary.short_term_benefits,
            defined_contribution_plans=new_list,
            defined_benefit_obligations=summary.defined_benefit_obligations,
            termination_benefits=summary.termination_benefits,
        )

    def add_defined_benefit_obligation(
        self, summary: PSAK24EmployeeBenefitsSummary, obligation: PSAK24DefinedBenefitObligation
    ) -> PSAK24EmployeeBenefitsSummary:
        new_list = [*summary.defined_benefit_obligations, obligation]
        return PSAK24EmployeeBenefitsSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            reporting_date=summary.reporting_date,
            short_term_benefits=summary.short_term_benefits,
            defined_contribution_plans=summary.defined_contribution_plans,
            defined_benefit_obligations=new_list,
            termination_benefits=summary.termination_benefits,
        )

    def add_termination_benefit(
        self, summary: PSAK24EmployeeBenefitsSummary, benefit: PSAK24TerminationBenefit
    ) -> PSAK24EmployeeBenefitsSummary:
        new_list = [*summary.termination_benefits, benefit]
        return PSAK24EmployeeBenefitsSummary(
            summary_id=summary.summary_id,
            entity_id=summary.entity_id,
            entity_name=summary.entity_name,
            reporting_date=summary.reporting_date,
            short_term_benefits=summary.short_term_benefits,
            defined_contribution_plans=summary.defined_contribution_plans,
            defined_benefit_obligations=summary.defined_benefit_obligations,
            termination_benefits=new_list,
        )

    def validate_summary(self, summary: PSAK24EmployeeBenefitsSummary) -> PSAK24ValidationResult:
        result = PSAK24ValidationResult(
            is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL
        )
        for ob in summary.defined_benefit_obligations:
            result = self._merge_results(
                result, self._rules.validate_actuarial_assumptions(ob.actuarial_assumptions)
            )
        total_db_liability = summary.total_defined_benefit_liability()
        total_assets = sum(o.fair_value_of_plan_assets for o in summary.defined_benefit_obligations)
        result = self._merge_results(
            result, self._rules.validate_disclosure(total_db_liability, total_assets)
        )
        return result

    def _merge_results(
        self, main: PSAK24ValidationResult, other: PSAK24ValidationResult
    ) -> PSAK24ValidationResult:
        main.errors.extend(other.errors)
        main.warnings.extend(other.warnings)
        main.is_compliant = main.is_compliant and other.is_compliant
        level_order = [
            PSAK24ComplianceLevel.FULL,
            PSAK24ComplianceLevel.SUBSTANTIAL,
            PSAK24ComplianceLevel.PARTIAL,
            PSAK24ComplianceLevel.NON_COMPLIANT,
        ]
        main_idx = level_order.index(main.compliance_level)
        other_idx = level_order.index(other.compliance_level)
        if other_idx > main_idx:
            main.compliance_level = level_order[other_idx]
        return main

    def get_requirements_summary(self) -> dict:
        return {
            "short_term": "Diakui sebagai liabilitas saat karyawan memberikan jasa, dibayarkan dalam 12 bulan",
            "defined_contribution": "Beban = kontribusi yang harus dibayar",
            "defined_benefit": "Menggunakan metode projected unit credit; nilai kini kewajiban diakui",
            "actuarial_gains_losses": "Dapat diakui di OCI (PSAK 24 revisi 2015) atau P&L",
            "plan_assets": "Aset program diukur pada nilai wajar",
            "termination_benefits": "Diakui saat entitas berkomitmen untuk menghentikan karyawan",
            "disclosures": [
                "Kebijakan akuntansi",
                "Jenis program",
                "Rekonsiliasi kewajiban dan aset",
                "Asumsi aktuaria utama",
                "Sensitivitas terhadap perubahan asumsi",
                "Kontribusi yang diharapkan tahun depan",
            ],
        }


# ============================================================================
# Singleton Accessor
# ============================================================================
_psak24_validator_instance: PSAK24Validator | None = None


def get_psak24_validator() -> PSAK24Validator:
    global _psak24_validator_instance
    if _psak24_validator_instance is None:
        _psak24_validator_instance = PSAK24Validator()
    return _psak24_validator_instance


EmployeeBenefitType = PSAK24BenefitType
ShortTermBenefit = PSAK24ShortTermBenefit
PostEmploymentBenefit = PSAK24DefinedBenefitObligation

# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    validator = get_psak24_validator()
    entity_id = uuid4()

    summary = validator.create_summary(
        entity_id=entity_id,
        entity_name="PT Sumber Daya Manusia",
        reporting_date=date(2026, 12, 31),
    )

    # Short-term benefit
    stb = validator.create_short_term_benefit(
        employee_id=uuid4(),
        employee_name="Budi Santoso",
        benefit_type="gaji",
        amount=Decimal("15000000"),
        currency="IDR",
        period_start=date(2026, 12, 1),
        period_end=date(2026, 12, 31),
        payable_date=date(2027, 1, 5),
    )
    summary = validator.add_short_term_benefit(summary, stb)

    # Defined contribution plan
    dc_plan = validator.create_defined_contribution_plan(
        plan_name="BPJS Ketenagakerjaan JHT",
        plan_number="BPJS-001",
        contribution_rate_employee=Decimal("2"),
        contribution_rate_employer=Decimal("3.7"),
        currency="IDR",
    )
    summary = validator.add_defined_contribution_plan(summary, dc_plan)

    # Actuarial assumptions
    assumptions = validator.create_actuarial_assumptions(
        discount_rate=Decimal("7.5"),
        salary_increase_rate=Decimal("6"),
        pension_increase_rate=Decimal("3"),
        mortality_table="TMI IV",
        turnover_rate=Decimal("5"),
        retirement_age=56,
    )

    # Defined benefit obligation (simplified)
    db_obligation = validator.create_defined_benefit_obligation(
        plan_id=uuid4(),
        valuation_date=date(2026, 12, 31),
        present_value_obligation=Decimal("5000000000"),
        fair_value_assets=Decimal("3000000000"),
        current_service_cost=Decimal("200000000"),
        past_service_cost=Decimal(0),
        interest_cost=Decimal("250000000"),
        actuarial_gains_losses=Decimal("30000000"),
        return_on_assets=Decimal("150000000"),
        contributions_paid=Decimal("100000000"),
        benefits_paid=Decimal("50000000"),
        assumptions=assumptions,
        valuator="Kantor Aktuaria ABC",
    )
    summary = validator.add_defined_benefit_obligation(summary, db_obligation)

    # Termination benefit
    term_benefit = validator.create_termination_benefit(
        employee_id=uuid4(),
        employee_name="Siti Aminah",
        termination_date=date(2026, 9, 30),
        years_of_service=12,
        last_salary=Decimal("20000000"),
        severance_pay=Decimal("300000000"),
        compensation_for_leave=Decimal("20000000"),
        other_benefits=Decimal(0),
        currency="IDR",
    )
    summary = validator.add_termination_benefit(summary, term_benefit)

    result = validator.validate_summary(summary)
    print("Validation Result:")
    print(json.dumps(result.to_dict(), indent=2))
    print("\nEmployee Benefits Summary:")
    print(json.dumps(summary.to_dict(), indent=2, default=str))
