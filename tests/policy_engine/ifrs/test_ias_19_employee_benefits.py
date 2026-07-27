# tests/policy_engine/ifrs/test_ias_19_employee_benefits.py
"""
Comprehensive tests for IAS 19: Employee Benefits.
Covers all methods including aggregations, validation, and service calculations.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.shared_value_objects.money_vo import Money
from policy_engine.ifrs.ias_19_employee_benefits import (
    IAS19ActuarialMethod,
    IAS19BenefitService,
    IAS19BenefitType,
    IAS19DefinedBenefitObligation,
    IAS19DefinedContributionPlan,
    IAS19EmployeeBenefits,
    IAS19Error,
    IAS19PlanType,
    IAS19Rules,
    IAS19ShortTermBenefit,
    IAS19ValidationResult,
    IAS19Validator,
    get_ias19_validator,
)


# ============================================================================
# Enum tests
# ============================================================================

class TestIAS19BenefitType:
    def test_members_exist(self):
        assert hasattr(IAS19BenefitType, 'SHORT_TERM')
        assert hasattr(IAS19BenefitType, 'POST_EMPLOYMENT')
        assert hasattr(IAS19BenefitType, 'OTHER_LONG_TERM')
        assert hasattr(IAS19BenefitType, 'TERMINATION')
        assert IAS19BenefitType.SHORT_TERM.value == "short_term"
        assert IAS19BenefitType.POST_EMPLOYMENT.value == "post_employment"
        assert IAS19BenefitType.OTHER_LONG_TERM.value == "other_long_term"
        assert IAS19BenefitType.TERMINATION.value == "termination"


class TestIAS19PlanType:
    def test_members_exist(self):
        assert hasattr(IAS19PlanType, 'DEFINED_CONTRIBUTION')
        assert hasattr(IAS19PlanType, 'DEFINED_BENEFIT')
        assert IAS19PlanType.DEFINED_CONTRIBUTION.value == "defined_contribution"
        assert IAS19PlanType.DEFINED_BENEFIT.value == "defined_benefit"


class TestIAS19ActuarialMethod:
    def test_members_exist(self):
        assert hasattr(IAS19ActuarialMethod, 'PROJECTED_UNIT_CREDIT')
        assert hasattr(IAS19ActuarialMethod, 'ATTRIBUTION_METHOD')
        assert IAS19ActuarialMethod.PROJECTED_UNIT_CREDIT.value == "projected_unit_credit"
        assert IAS19ActuarialMethod.ATTRIBUTION_METHOD.value == "attribution_method"


# ============================================================================
# Custom exception
# ============================================================================

class TestIAS19Error:
    def test_construction(self):
        error = IAS19Error("Test message")
        assert str(error) == "Test message"
        assert isinstance(error, Exception)


# ============================================================================
# IAS19ShortTermBenefit tests
# ============================================================================

class TestIAS19ShortTermBenefit:
    def test_construction(self):
        employee_id = uuid4()
        payable_date = datetime(2026, 12, 31, tzinfo=UTC)
        amount = Money(Decimal("1500000"), "IDR")
        benefit = IAS19ShortTermBenefit(
            benefit_type="salary",
            amount=amount,
            payable_date=payable_date,
            employee_id=employee_id,
        )
        assert benefit.benefit_type == "salary"
        assert benefit.amount == amount
        assert benefit.payable_date == payable_date
        assert benefit.employee_id == employee_id

    def test_to_dict(self):
        employee_id = uuid4()
        payable_date = datetime(2026, 12, 31, tzinfo=UTC)
        amount = Money(Decimal("1500000"), "IDR")
        benefit = IAS19ShortTermBenefit(
            benefit_type="salary",
            amount=amount,
            payable_date=payable_date,
            employee_id=employee_id,
        )
        d = benefit.to_dict()
        assert d["benefit_type"] == "salary"
        assert d["amount"] == "1500000"
        assert d["currency"] == "IDR"
        assert d["payable_date"] == "2026-12-31T00:00:00+00:00"
        assert d["employee_id"] == str(employee_id)


# ============================================================================
# IAS19DefinedContributionPlan tests
# ============================================================================

class TestIAS19DefinedContributionPlan:
    def test_construction(self):
        plan_id = uuid4()
        amount_ytd = Money(Decimal("5000000"), "IDR")
        payable = Money(Decimal("1000000"), "IDR")
        plan = IAS19DefinedContributionPlan(
            plan_id=plan_id,
            plan_name="DPLK",
            contribution_rate_employee=Decimal("2"),
            contribution_rate_employer=Decimal("5"),
            contributed_amount_ytd=amount_ytd,
            payable_amount=payable,
        )
        assert plan.plan_id == plan_id
        assert plan.contribution_rate_employer == Decimal("5")
        assert plan.payable_amount == payable

    def test_to_dict(self):
        plan_id = uuid4()
        plan = IAS19DefinedContributionPlan(
            plan_id=plan_id,
            plan_name="DPLK",
            contribution_rate_employee=Decimal("2"),
            contribution_rate_employer=Decimal("5"),
            contributed_amount_ytd=Money(Decimal("5000000"), "IDR"),
            payable_amount=Money(Decimal("1000000"), "IDR"),
        )
        d = plan.to_dict()
        assert d["plan_id"] == str(plan_id)
        assert d["plan_name"] == "DPLK"
        assert d["employee_rate"] == "2"
        assert d["employer_rate"] == "5"
        assert d["contributed_ytd"] == "5000000"
        assert d["payable"] == "1000000"


# ============================================================================
# IAS19DefinedBenefitObligation tests
# ============================================================================

class TestIAS19DefinedBenefitObligation:
    def test_construction(self):
        pv = Money(Decimal("100000000"), "IDR")
        fv = Money(Decimal("80000000"), "IDR")
        actuarial = Money(Decimal("5000000"), "IDR")
        net = Money(Decimal("20000000"), "IDR")  # liability
        current_service = Money(Decimal("10000000"), "IDR")
        past_service = Money(Decimal("2000000"), "IDR")
        interest = Money(Decimal("8000000"), "IDR")
        return_assets = Money(Decimal("6000000"), "IDR")
        obligation = IAS19DefinedBenefitObligation(
            present_value_of_obligation=pv,
            fair_value_of_plan_assets=fv,
            actuarial_gains_losses=actuarial,
            net_defined_benefit_liability=net,
            current_service_cost=current_service,
            past_service_cost=past_service,
            interest_cost=interest,
            return_on_plan_assets=return_assets,
        )
        assert obligation.present_value_of_obligation == pv
        assert obligation.net_defined_benefit_liability == net

    def test_to_dict(self):
        obligation = IAS19DefinedBenefitObligation(
            present_value_of_obligation=Money(Decimal("100000000"), "IDR"),
            fair_value_of_plan_assets=Money(Decimal("80000000"), "IDR"),
            actuarial_gains_losses=Money(Decimal("5000000"), "IDR"),
            net_defined_benefit_liability=Money(Decimal("20000000"), "IDR"),
            current_service_cost=Money(Decimal("10000000"), "IDR"),
            past_service_cost=Money(Decimal("2000000"), "IDR"),
            interest_cost=Money(Decimal("8000000"), "IDR"),
            return_on_plan_assets=Money(Decimal("6000000"), "IDR"),
        )
        d = obligation.to_dict()
        assert d["pv_obligation"] == "100000000"
        assert d["fair_value_assets"] == "80000000"
        assert d["actuarial_gains_losses"] == "5000000"
        assert d["net_liability"] == "20000000"
        assert d["current_service"] == "10000000"
        assert d["past_service"] == "2000000"
        assert d["interest_cost"] == "8000000"
        assert d["return_on_assets"] == "6000000"


# ============================================================================
# IAS19EmployeeBenefits tests (including total methods)
# ============================================================================

class TestIAS19EmployeeBenefits:
    def test_total_short_term_liability_empty(self):
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            short_term_benefits=[],
        )
        total = benefits.total_short_term_liability()
        assert total.amount == Decimal("0")
        assert total.currency == "IDR"

    def test_total_short_term_liability(self):
        emp1 = uuid4()
        emp2 = uuid4()
        b1 = IAS19ShortTermBenefit(
            benefit_type="salary",
            amount=Money(Decimal("1000000"), "IDR"),
            payable_date=datetime(2026, 12, 31, tzinfo=UTC),
            employee_id=emp1,
        )
        b2 = IAS19ShortTermBenefit(
            benefit_type="bonus",
            amount=Money(Decimal("500000"), "IDR"),
            payable_date=datetime(2026, 12, 31, tzinfo=UTC),
            employee_id=emp2,
        )
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            short_term_benefits=[b1, b2],
        )
        total = benefits.total_short_term_liability()
        assert total.amount == Decimal("1500000")
        assert total.currency == "IDR"

    def test_total_defined_contribution_payable_empty(self):
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            defined_contribution_plans=[],
        )
        total = benefits.total_defined_contribution_payable()
        assert total.amount == Decimal("0")
        assert total.currency == "IDR"

    def test_total_defined_contribution_payable(self):
        plan1 = IAS19DefinedContributionPlan(
            plan_id=uuid4(),
            plan_name="Plan A",
            contribution_rate_employee=Decimal("2"),
            contribution_rate_employer=Decimal("5"),
            contributed_amount_ytd=Money(Decimal("1000000"), "IDR"),
            payable_amount=Money(Decimal("200000"), "IDR"),
        )
        plan2 = IAS19DefinedContributionPlan(
            plan_id=uuid4(),
            plan_name="Plan B",
            contribution_rate_employee=Decimal("3"),
            contribution_rate_employer=Decimal("6"),
            contributed_amount_ytd=Money(Decimal("2000000"), "IDR"),
            payable_amount=Money(Decimal("300000"), "IDR"),
        )
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            defined_contribution_plans=[plan1, plan2],
        )
        total = benefits.total_defined_contribution_payable()
        assert total.amount == Decimal("500000")
        assert total.currency == "IDR"

    def test_to_dict_includes_aggregates(self):
        emp = uuid4()
        b = IAS19ShortTermBenefit(
            benefit_type="salary",
            amount=Money(Decimal("1000000"), "IDR"),
            payable_date=datetime(2026, 12, 31, tzinfo=UTC),
            employee_id=emp,
        )
        plan = IAS19DefinedContributionPlan(
            plan_id=uuid4(),
            plan_name="Plan A",
            contribution_rate_employee=Decimal("2"),
            contribution_rate_employer=Decimal("5"),
            contributed_amount_ytd=Money(Decimal("1000000"), "IDR"),
            payable_amount=Money(Decimal("200000"), "IDR"),
        )
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime(2026, 12, 31, tzinfo=UTC),
            short_term_benefits=[b],
            defined_contribution_plans=[plan],
            defined_benefit_obligation=None,
        )
        d = benefits.to_dict()
        assert d["total_short_term_liability"] == "1000000"
        assert d["total_defined_contribution_payable"] == "200000"
        assert "short_term" in d
        assert "defined_contribution" in d
        assert "defined_benefit" in d and d["defined_benefit"] is None


# ============================================================================
# IAS19BenefitService tests
# ============================================================================

class TestIAS19BenefitService:
    def test_calculate_short_term_benefit_expense(self):
        gross = Money(Decimal("10000000"), "IDR")
        bonus = Money(Decimal("2000000"), "IDR")
        leave = Money(Decimal("500000"), "IDR")
        total = IAS19BenefitService.calculate_short_term_benefit_expense(gross, bonus, leave)
        assert total.amount == Decimal("12500000")
        assert total.currency == "IDR"

    def test_calculate_defined_contribution_expense(self):
        salary = Money(Decimal("10000000"), "IDR")
        employer_rate = Decimal("5")  # 5%
        expense = IAS19BenefitService.calculate_defined_contribution_expense(salary, employer_rate)
        assert expense.amount == Decimal("500000")  # 10,000,000 * 5/100
        assert expense.currency == "IDR"

    def test_project_defined_benefit_obligation(self):
        current_obligation = Money(Decimal("100000000"), "IDR")
        service_cost = Money(Decimal("10000000"), "IDR")
        interest_rate = Decimal("5")  # 5% per year
        years = 3
        projected = IAS19BenefitService.project_defined_benefit_obligation(
            current_obligation, service_cost, interest_rate, years
        )
        # Future value = current * (1+0.05)^3 = 100,000,000 * 1.157625 = 115,762,500
        # plus service cost * years = 10,000,000 * 3 = 30,000,000
        expected = Decimal("145762500")
        assert projected.amount == expected
        assert projected.currency == "IDR"


# ============================================================================
# IAS19ValidationResult tests (including add_warning)
# ============================================================================

class TestIAS19ValidationResult:
    def test_add_error(self):
        result = IAS19ValidationResult(is_compliant=True)
        result.add_error("Error 1")
        assert result.errors == ["Error 1"]
        assert result.is_compliant is False

    def test_add_warning(self):
        result = IAS19ValidationResult(is_compliant=True)
        result.add_warning("Warning 1")
        assert result.warnings == ["Warning 1"]
        assert result.is_compliant is True  # warnings don't affect compliance

    def test_merge(self):
        result1 = IAS19ValidationResult(is_compliant=True)
        result1.add_error("E1")
        result1.add_warning("W1")
        result2 = IAS19ValidationResult(is_compliant=True)
        result2.add_error("E2")
        merged = result1.merge(result2)
        assert merged.is_compliant is False
        assert merged.errors == ["E1", "E2"]
        assert merged.warnings == ["W1"]

    def test_merge_compliant(self):
        r1 = IAS19ValidationResult(is_compliant=True)
        r2 = IAS19ValidationResult(is_compliant=True)
        merged = r1.merge(r2)
        assert merged.is_compliant is True
        assert merged.errors == []
        assert merged.warnings == []


# ============================================================================
# IAS19Rules tests
# ============================================================================

class TestIAS19Rules:
    def test_validate_defined_benefit_disclosure_full(self):
        result = IAS19Rules.validate_defined_benefit_disclosure(
            has_actuarial_assumptions=True,
            has_sensitivity_analysis=True,
        )
        assert result.is_compliant is True
        assert result.errors == []
        assert result.warnings == []

    def test_validate_defined_benefit_disclosure_missing_assumptions(self):
        result = IAS19Rules.validate_defined_benefit_disclosure(
            has_actuarial_assumptions=False,
            has_sensitivity_analysis=True,
        )
        assert result.is_compliant is False
        assert "Actuarial assumptions for defined benefit plan must be disclosed" in result.errors
        assert result.warnings == []

    def test_validate_defined_benefit_disclosure_missing_sensitivity(self):
        result = IAS19Rules.validate_defined_benefit_disclosure(
            has_actuarial_assumptions=True,
            has_sensitivity_analysis=False,
        )
        assert result.is_compliant is True
        assert result.errors == []
        assert "Sensitivity analysis for defined benefit plan recommended" in result.warnings


# ============================================================================
# IAS19Validator tests
# ============================================================================

class TestIAS19Validator:
    @pytest.fixture
    def validator(self):
        return IAS19Validator()

    def test_validate_benefits_no_defined_benefit(self, validator):
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            short_term_benefits=[],
            defined_contribution_plans=[],
            defined_benefit_obligation=None,
        )
        result = validator.validate_benefits(benefits)
        assert result.is_compliant is True
        assert result.errors == []
        assert result.warnings == []

    def test_validate_benefits_with_defined_benefit(self, validator):
        obligation = IAS19DefinedBenefitObligation(
            present_value_of_obligation=Money(Decimal("100000000"), "IDR"),
            fair_value_of_plan_assets=Money(Decimal("80000000"), "IDR"),
            actuarial_gains_losses=Money(Decimal("0"), "IDR"),
            net_defined_benefit_liability=Money(Decimal("20000000"), "IDR"),
            current_service_cost=Money(Decimal("0"), "IDR"),
            past_service_cost=Money(Decimal("0"), "IDR"),
            interest_cost=Money(Decimal("0"), "IDR"),
            return_on_plan_assets=Money(Decimal("0"), "IDR"),
        )
        benefits = IAS19EmployeeBenefits(
            benefits_id=uuid4(),
            entity_id=uuid4(),
            reporting_date=datetime.now(UTC),
            defined_benefit_obligation=obligation,
        )
        result = validator.validate_benefits(benefits)
        # validate_defined_benefit_disclosure is called with True, True -> full compliant
        assert result.is_compliant is True
        assert result.errors == []
        assert result.warnings == []

    def test_get_requirements_summary(self, validator):
        summary = validator.get_requirements_summary()
        assert "short_term" in summary
        assert "defined_contribution" in summary
        assert "defined_benefit" in summary
        assert "actuarial_gains_losses" in summary
        assert "termination_benefits" in summary


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_ias19_validator():
    v1 = get_ias19_validator()
    v2 = get_ias19_validator()
    assert v1 is v2
    assert isinstance(v1, IAS19Validator)