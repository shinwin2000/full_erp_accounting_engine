# test_psak_24_employee_benefits.py
# Comprehensive tests for policy_engine/psak/psak_24_employee_benefits.py

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from policy_engine.psak.psak_24_employee_benefits import (
    ActuarialValuationError,
    PlanNotFoundError,
    PSAK24ActuarialAssumption,
    PSAK24ActuarialMethod,
    PSAK24ActuarialService,
    PSAK24BenefitType,
    PSAK24ComplianceLevel,
    PSAK24DefinedBenefitObligation,
    PSAK24DefinedContributionPlan,
    PSAK24EmployeeBenefitsSummary,
    PSAK24Error,
    PSAK24PlanType,
    PSAK24Rules,
    PSAK24ShortTermBenefit,
    PSAK24TerminationBenefit,
    PSAK24ValidationResult,
    PSAK24Validator,
    PSAK24ValuationFrequency,
    get_psak24_validator,
)


# -------------------- Fixtures --------------------
@pytest.fixture
def sample_short_term_benefit():
    return PSAK24ShortTermBenefit(
        benefit_id=uuid4(),
        employee_id=uuid4(),
        employee_name="John Doe",
        benefit_type="salary",
        amount=Decimal("15000000"),
        currency="IDR",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        payable_date=date(2026, 2, 5),
        is_accrued=True,
        notes="Monthly salary",
    )


@pytest.fixture
def sample_dc_plan():
    return PSAK24DefinedContributionPlan(
        plan_id=uuid4(),
        plan_name="BPJS JHT",
        plan_number="BPJS-001",
        contribution_rate_employee=Decimal("2"),
        contribution_rate_employer=Decimal("3.7"),
        contribution_amount_ytd_employee=Decimal("1000000"),
        contribution_amount_ytd_employer=Decimal("1850000"),
        payable_employee=Decimal("50000"),
        payable_employer=Decimal("92500"),
        currency="IDR",
        notes="",
    )


@pytest.fixture
def sample_actuarial_assumptions():
    return PSAK24ActuarialAssumption(
        discount_rate=Decimal("7.5"),
        future_salary_increase_rate=Decimal("6"),
        pension_increase_rate=Decimal("3"),
        mortality_table="TMI IV",
        employee_turnover_rate=Decimal("5"),
        retirement_age=56,
    )


@pytest.fixture
def sample_db_obligation(sample_actuarial_assumptions):
    return PSAK24DefinedBenefitObligation(
        obligation_id=uuid4(),
        plan_id=uuid4(),
        valuation_date=date(2026, 12, 31),
        present_value_of_obligation=Decimal("5000000000"),
        fair_value_of_plan_assets=Decimal("3000000000"),
        net_defined_benefit_liability=Decimal("2000000000"),
        current_service_cost=Decimal("200000000"),
        past_service_cost=Decimal("0"),
        interest_cost=Decimal("250000000"),
        actuarial_gains_losses=Decimal("30000000"),
        return_on_plan_assets=Decimal("150000000"),
        contributions_paid=Decimal("100000000"),
        benefits_paid=Decimal("50000000"),
        actuarial_assumptions=sample_actuarial_assumptions,
        valuation_performed_by="Kantor Aktuaria ABC",
        next_valuation_date=date(2027, 12, 31),
        notes="",
    )


@pytest.fixture
def sample_termination_benefit():
    return PSAK24TerminationBenefit(
        benefit_id=uuid4(),
        employee_id=uuid4(),
        employee_name="Jane Smith",
        termination_date=date(2026, 9, 30),
        years_of_service=12,
        last_salary=Decimal("20000000"),
        severance_pay=Decimal("300000000"),
        compensation_for_leave=Decimal("20000000"),
        other_benefits=Decimal("0"),
        total_amount=Decimal("320000000"),
        currency="IDR",
        is_accrued=True,
        approved_by=uuid4(),
        approval_date=date(2026, 10, 1),
        notes="",
    )


@pytest.fixture
def sample_summary(sample_short_term_benefit, sample_dc_plan, sample_db_obligation, sample_termination_benefit):
    return PSAK24EmployeeBenefitsSummary(
        summary_id=uuid4(),
        entity_id=uuid4(),
        entity_name="PT ABC",
        reporting_date=date(2026, 12, 31),
        short_term_benefits=[sample_short_term_benefit],
        defined_contribution_plans=[sample_dc_plan],
        defined_benefit_obligations=[sample_db_obligation],
        termination_benefits=[sample_termination_benefit],
    )


@pytest.fixture
def validator():
    return PSAK24Validator()


# -------------------- Tests for Enums --------------------
class TestEnums:
    def test_benefit_type(self):
        assert PSAK24BenefitType.SHORT_TERM.value == "jangka_pendek"
        assert PSAK24BenefitType.POST_EMPLOYMENT.value == "pasca_kerja"
        assert PSAK24BenefitType.OTHER_LONG_TERM.value == "jangka_panjang_lain"
        assert PSAK24BenefitType.TERMINATION.value == "pemutusan_kerja"

    def test_plan_type(self):
        assert PSAK24PlanType.DEFINED_CONTRIBUTION.value == "iuran_pasti"
        assert PSAK24PlanType.DEFINED_BENEFIT.value == "manfaat_pasti"

    def test_actuarial_method(self):
        assert PSAK24ActuarialMethod.PROJECTED_UNIT_CREDIT.value == "proyeksi_unit_kredit"
        assert PSAK24ActuarialMethod.ATTRIBUTION_METHOD.value == "atribusi"

    def test_valuation_frequency(self):
        assert PSAK24ValuationFrequency.ANNUALLY.value == "tahunan"
        assert PSAK24ValuationFrequency.EVERY_3_YEARS.value == "3_tahun"
        assert PSAK24ValuationFrequency.EVERY_5_YEARS.value == "5_tahun"

    def test_compliance_level(self):
        assert PSAK24ComplianceLevel.FULL.value == "penuh"
        assert PSAK24ComplianceLevel.SUBSTANTIAL.value == "substansial"
        assert PSAK24ComplianceLevel.PARTIAL.value == "sebagian"
        assert PSAK24ComplianceLevel.NON_COMPLIANT.value == "tidak_patuh"


# -------------------- Tests for Exceptions --------------------
class TestExceptions:
    def test_psak24_error(self):
        with pytest.raises(PSAK24Error):
            raise PSAK24Error("error")

    def test_actuarial_valuation_error(self):
        with pytest.raises(ActuarialValuationError):
            raise ActuarialValuationError("valuation error")

    def test_plan_not_found_error(self):
        with pytest.raises(PlanNotFoundError):
            raise PlanNotFoundError("plan not found")


# -------------------- Tests for Data Classes --------------------
class TestPSAK24ShortTermBenefit:
    def test_construction(self, sample_short_term_benefit):
        assert sample_short_term_benefit.benefit_type == "salary"
        assert sample_short_term_benefit.amount == Decimal("15000000")
        assert sample_short_term_benefit.is_accrued is True

    def test_to_dict(self, sample_short_term_benefit):
        d = sample_short_term_benefit.to_dict()
        assert d["benefit_id"] == str(sample_short_term_benefit.benefit_id)
        assert d["employee_name"] == "John Doe"
        assert d["amount"] == "15000000"
        assert d["is_accrued"] is True


class TestPSAK24DefinedContributionPlan:
    def test_construction(self, sample_dc_plan):
        assert sample_dc_plan.contribution_rate_employee == Decimal("2")
        assert sample_dc_plan.contribution_amount_ytd_employee == Decimal("1000000")

    def test_total_contribution_ytd(self, sample_dc_plan):
        total = sample_dc_plan.total_contribution_ytd()
        assert total == Decimal("2850000")  # 1,000,000 + 1,850,000

    def test_total_payable(self, sample_dc_plan):
        total = sample_dc_plan.total_payable()
        assert total == Decimal("142500")  # 50,000 + 92,500

    def test_to_dict(self, sample_dc_plan):
        d = sample_dc_plan.to_dict()
        assert d["plan_id"] == str(sample_dc_plan.plan_id)
        assert d["employee_rate"] == "2"
        assert d["total_ytd"] == "2850000"
        assert d["total_payable"] == "142500"


class TestPSAK24ActuarialAssumption:
    def test_construction(self, sample_actuarial_assumptions):
        assert sample_actuarial_assumptions.discount_rate == Decimal("7.5")
        assert sample_actuarial_assumptions.retirement_age == 56

    def test_to_dict(self, sample_actuarial_assumptions):
        d = sample_actuarial_assumptions.to_dict()
        assert d["discount_rate"] == "7.5"
        assert d["retirement_age"] == 56
        assert d["mortality_table"] == "TMI IV"


class TestPSAK24DefinedBenefitObligation:
    def test_construction(self, sample_db_obligation):
        assert sample_db_obligation.present_value_of_obligation == Decimal("5000000000")
        assert sample_db_obligation.net_defined_benefit_liability == Decimal("2000000000")

    def test_surplus_deficit(self, sample_db_obligation):
        # assets - obligation = 3B - 5B = -2B (deficit)
        assert sample_db_obligation.surplus_deficit() == Decimal("-2000000000")

    def test_to_dict(self, sample_db_obligation):
        d = sample_db_obligation.to_dict()
        assert d["obligation_id"] == str(sample_db_obligation.obligation_id)
        assert d["surplus_deficit"] == "-2000000000"
        assert "assumptions" in d
        assert d["valuator"] == "Kantor Aktuaria ABC"


class TestPSAK24TerminationBenefit:
    def test_construction(self, sample_termination_benefit):
        assert sample_termination_benefit.years_of_service == 12
        assert sample_termination_benefit.total_amount == Decimal("320000000")

    def test_to_dict(self, sample_termination_benefit):
        d = sample_termination_benefit.to_dict()
        assert d["benefit_id"] == str(sample_termination_benefit.benefit_id)
        assert d["total"] == "320000000"
        assert d["approved_by"] == str(sample_termination_benefit.approved_by)


class TestPSAK24EmployeeBenefitsSummary:
    def test_construction(self, sample_summary):
        assert len(sample_summary.short_term_benefits) == 1
        assert len(sample_summary.defined_contribution_plans) == 1
        assert len(sample_summary.defined_benefit_obligations) == 1
        assert len(sample_summary.termination_benefits) == 1

    def test_total_short_term_liability(self, sample_summary):
        # Only one benefit with amount 15,000,000 and accrued = True
        assert sample_summary.total_short_term_liability() == Decimal("15000000")

    def test_total_defined_contribution_payable(self, sample_summary):
        # Total payable = 142,500
        assert sample_summary.total_defined_contribution_payable() == Decimal("142500")

    def test_total_defined_benefit_liability(self, sample_summary):
        # Net liability = 2,000,000,000
        assert sample_summary.total_defined_benefit_liability() == Decimal("2000000000")

    def test_total_termination_liability(self, sample_summary):
        # Total amount 320,000,000, accrued=True
        assert sample_summary.total_termination_liability() == Decimal("320000000")

    def test_total_employee_benefits_liability(self, sample_summary):
        expected = Decimal("15000000") + Decimal("142500") + Decimal("2000000000") + Decimal("320000000")
        assert sample_summary.total_employee_benefits_liability() == expected

    def test_to_dict(self, sample_summary):
        d = sample_summary.to_dict()
        assert d["entity_name"] == "PT ABC"
        assert d["reporting_date"] == "2026-12-31"
        assert len(d["short_term"]) == 1
        assert d["total_short_term"] == "15000000"
        assert d["total_dc_payable"] == "142500"
        assert d["total_db_liability"] == "2000000000"
        assert d["total_termination"] == "320000000"


class TestPSAK24ValidationResult:
    def test_initialization(self):
        result = PSAK24ValidationResult(
            is_compliant=True,
            compliance_level=PSAK24ComplianceLevel.FULL,
            errors=[],
            warnings=[],
        )
        assert result.is_compliant is True
        assert result.compliance_level == PSAK24ComplianceLevel.FULL
        assert result.hash_sha256 != ""

    def test_add_error(self):
        result = PSAK24ValidationResult(is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL)
        result.add_error("Error message")
        assert result.is_compliant is False
        assert result.compliance_level == PSAK24ComplianceLevel.NON_COMPLIANT
        assert "Error message" in result.errors

    def test_add_warning(self):
        result = PSAK24ValidationResult(is_compliant=True, compliance_level=PSAK24ComplianceLevel.FULL)
        result.add_warning("Warning message")
        assert result.is_compliant is True  # warnings don't make it non-compliant
        assert result.compliance_level == PSAK24ComplianceLevel.SUBSTANTIAL
        assert "Warning message" in result.warnings
        # Adding another warning keeps SUBSTANTIAL
        result.add_warning("Second")
        assert result.compliance_level == PSAK24ComplianceLevel.SUBSTANTIAL

    def test_to_dict(self):
        result = PSAK24ValidationResult(
            is_compliant=False,
            compliance_level=PSAK24ComplianceLevel.NON_COMPLIANT,
            errors=["e1", "e2"],
            warnings=["w1"],
        )
        d = result.to_dict()
        assert d["is_compliant"] is False
        assert d["compliance_level"] == "tidak_patuh"
        assert d["errors"] == ["e1", "e2"]
        assert d["warnings"] == ["w1"]
        assert "hash" in d


# -------------------- Tests for PSAK24ActuarialService --------------------
class TestPSAK24ActuarialService:
    def test_calculate_present_value_factor(self):
        # rate=10%, years=1 => 1/(1.1) = 0.9091
        factor = PSAK24ActuarialService.calculate_present_value_factor(Decimal("10"), 1)
        assert factor == Decimal("0.9090909090909090909090909091")  # close
        # years=0 => 1
        assert PSAK24ActuarialService.calculate_present_value_factor(Decimal("10"), 0) == Decimal(1)

    def test_projected_unit_credit(self):
        current_salary = Decimal("10000000")
        years_to_retirement = 20
        salary_growth = Decimal("6")
        discount = Decimal("7.5")
        factor = Decimal("0.02")  # 2% benefit formula
        pv = PSAK24ActuarialService.projected_unit_credit(
            current_salary, years_to_retirement, salary_growth, discount, factor
        )
        # Should be a positive Decimal
        assert pv > Decimal(0)
        # With mortality factor = 0.5, should be half
        pv2 = PSAK24ActuarialService.projected_unit_credit(
            current_salary, years_to_retirement, salary_growth, discount, factor, Decimal("0.5")
        )
        assert pv2 == (pv / 2).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

    def test_calculate_current_service_cost(self):
        benefit_pv = Decimal("1000000")
        # years_worked=1, total_years=20 => cost = 1,000,000 * 1/20 = 50,000
        cost = PSAK24ActuarialService.calculate_current_service_cost(benefit_pv, 1, 20)
        assert cost == Decimal("50000")
        # total_years=0 => 0
        cost2 = PSAK24ActuarialService.calculate_current_service_cost(benefit_pv, 5, 0)
        assert cost2 == Decimal(0)

    def test_compute_interest_cost(self):
        obligation = Decimal("1000000")
        rate = Decimal("7.5")
        interest = PSAK24ActuarialService.compute_interest_cost(obligation, rate)
        assert interest == Decimal("75000")  # 1,000,000 * 7.5%

    def test_compute_return_on_plan_assets(self):
        assets = Decimal("2000000")
        rate = Decimal("6")
        ret = PSAK24ActuarialService.compute_return_on_plan_assets(assets, rate)
        assert ret == Decimal("120000")  # 2,000,000 * 6%


# -------------------- Tests for PSAK24Rules --------------------
class TestPSAK24Rules:
    def test_validate_actuarial_assumptions_valid(self, sample_actuarial_assumptions):
        result = PSAK24Rules.validate_actuarial_assumptions(sample_actuarial_assumptions)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK24ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []

    def test_validate_actuarial_assumptions_warnings(self):
        assumptions = PSAK24ActuarialAssumption(
            discount_rate=Decimal("25"),  # out of range
            future_salary_increase_rate=Decimal("30"),  # out of range
            pension_increase_rate=Decimal("5"),
            mortality_table="TMI",
            employee_turnover_rate=Decimal("5"),
            retirement_age=45,  # out of range
        )
        result = PSAK24Rules.validate_actuarial_assumptions(assumptions)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK24ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) >= 2
        assert any("di luar kisaran" in w for w in result.warnings)
        assert any("Usia pensiun" in w for w in result.warnings)

    def test_validate_plan_asset_negative(self, sample_dc_plan, sample_db_obligation):
        sample_db_obligation.fair_value_of_plan_assets = Decimal("-100")
        result = PSAK24Rules.validate_plan_asset(sample_dc_plan, sample_db_obligation)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK24ComplianceLevel.NON_COMPLIANT
        assert "nilai negatif" in result.errors[0]

    def test_validate_disclosure(self):
        result = PSAK24Rules.validate_disclosure(Decimal("1000"), Decimal("0"))
        assert result.is_compliant is True
        assert result.compliance_level == PSAK24ComplianceLevel.SUBSTANTIAL
        assert "tidak ada aset program" in result.warnings[0]
        # With assets > 0
        result2 = PSAK24Rules.validate_disclosure(Decimal("1000"), Decimal("500"))
        assert result2.compliance_level == PSAK24ComplianceLevel.FULL
        assert result2.warnings == []


# -------------------- Tests for PSAK24Validator --------------------
class TestPSAK24Validator:
    def test_create_short_term_benefit(self, validator):
        emp_id = uuid4()
        benefit = validator.create_short_term_benefit(
            employee_id=emp_id,
            employee_name="Test",
            benefit_type="bonus",
            amount=Decimal("5000000"),
            currency="IDR",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            payable_date=date(2026, 2, 10),
            notes="Note",
        )
        assert benefit.employee_id == emp_id
        assert benefit.amount == Decimal("5000000")
        assert benefit.benefit_type == "bonus"
        assert benefit.notes == "Note"

    def test_create_defined_contribution_plan(self, validator):
        plan = validator.create_defined_contribution_plan(
            plan_name="Plan A",
            plan_number="PA-001",
            contribution_rate_employee=Decimal("2"),
            contribution_rate_employer=Decimal("3"),
            currency="USD",
            notes="Test",
        )
        assert plan.plan_name == "Plan A"
        assert plan.contribution_amount_ytd_employee == Decimal(0)
        assert plan.payable_employee == Decimal(0)
        assert plan.currency == "USD"

    def test_record_dc_contribution(self, validator, sample_dc_plan):
        # Record contribution with is_payable=True
        updated = validator.record_dc_contribution(
            sample_dc_plan,
            employee_contribution=Decimal("100000"),
            employer_contribution=Decimal("185000"),
            is_payable=True,
        )
        assert updated.contribution_amount_ytd_employee == Decimal("1100000")
        assert updated.contribution_amount_ytd_employer == Decimal("2035000")
        assert updated.payable_employee == Decimal("150000")
        assert updated.payable_employer == Decimal("277500")
        # is_payable=False
        updated2 = validator.record_dc_contribution(
            updated,
            employee_contribution=Decimal("50000"),
            employer_contribution=Decimal("92500"),
            is_payable=False,
        )
        assert updated2.payable_employee == Decimal("150000")  # unchanged
        assert updated2.contribution_amount_ytd_employee == Decimal("1150000")

    def test_create_actuarial_assumptions(self, validator):
        assumptions = validator.create_actuarial_assumptions(
            discount_rate=Decimal("8"),
            salary_increase_rate=Decimal("5"),
            pension_increase_rate=Decimal("2.5"),
            mortality_table="TMI 2020",
            turnover_rate=Decimal("6"),
            retirement_age=58,
        )
        assert assumptions.discount_rate == Decimal("8")
        assert assumptions.retirement_age == 58

    def test_create_defined_benefit_obligation(self, validator, sample_actuarial_assumptions):
        plan_id = uuid4()
        oblig = validator.create_defined_benefit_obligation(
            plan_id=plan_id,
            valuation_date=date(2026, 12, 31),
            present_value_obligation=Decimal("1000000000"),
            fair_value_assets=Decimal("600000000"),
            current_service_cost=Decimal("50000000"),
            past_service_cost=Decimal("10000000"),
            interest_cost=Decimal("40000000"),
            actuarial_gains_losses=Decimal("5000000"),
            return_on_assets=Decimal("20000000"),
            contributions_paid=Decimal("15000000"),
            benefits_paid=Decimal("5000000"),
            assumptions=sample_actuarial_assumptions,
            valuator="Actuary Inc.",
        )
        assert oblig.plan_id == plan_id
        assert oblig.net_defined_benefit_liability == Decimal("400000000")  # 1B - 600M
        assert oblig.actuarial_assumptions == sample_actuarial_assumptions

    def test_create_termination_benefit(self, validator):
        emp_id = uuid4()
        approver = uuid4()
        benefit = validator.create_termination_benefit(
            employee_id=emp_id,
            employee_name="Terminated",
            termination_date=date(2026, 1, 15),
            years_of_service=8,
            last_salary=Decimal("15000000"),
            severance_pay=Decimal("200000000"),
            compensation_for_leave=Decimal("10000000"),
            other_benefits=Decimal("5000000"),
            currency="IDR",
            approved_by=approver,
        )
        assert benefit.employee_id == emp_id
        assert benefit.total_amount == Decimal("215000000")  # 200M + 10M + 5M
        assert benefit.approved_by == approver

    def test_create_summary(self, validator):
        entity_id = uuid4()
        summary = validator.create_summary(
            entity_id=entity_id,
            entity_name="PT XYZ",
            reporting_date=date(2026, 12, 31),
        )
        assert summary.entity_id == entity_id
        assert summary.entity_name == "PT XYZ"
        assert summary.short_term_benefits == []

    def test_add_short_term_benefit(self, validator, sample_summary, sample_short_term_benefit):
        new_benefit = PSAK24ShortTermBenefit(
            benefit_id=uuid4(),
            employee_id=uuid4(),
            employee_name="New",
            benefit_type="bonus",
            amount=Decimal("1000000"),
            currency="IDR",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            payable_date=date(2026, 2, 1),
        )
        new_summary = validator.add_short_term_benefit(sample_summary, new_benefit)
        assert len(new_summary.short_term_benefits) == 2
        assert new_summary.short_term_benefits[-1].benefit_id == new_benefit.benefit_id
        # Other fields unchanged
        assert new_summary.entity_id == sample_summary.entity_id

    def test_add_defined_contribution_plan(self, validator, sample_summary, sample_dc_plan):
        new_plan = PSAK24DefinedContributionPlan(
            plan_id=uuid4(),
            plan_name="Plan B",
            plan_number="B-001",
            contribution_rate_employee=Decimal("1"),
            contribution_rate_employer=Decimal("2"),
            contribution_amount_ytd_employee=Decimal(0),
            contribution_amount_ytd_employer=Decimal(0),
            payable_employee=Decimal(0),
            payable_employer=Decimal(0),
            currency="IDR",
        )
        new_summary = validator.add_defined_contribution_plan(sample_summary, new_plan)
        assert len(new_summary.defined_contribution_plans) == 2
        assert new_summary.defined_contribution_plans[-1].plan_id == new_plan.plan_id

    def test_add_defined_benefit_obligation(self, validator, sample_summary, sample_db_obligation):
        new_oblig = PSAK24DefinedBenefitObligation(
            obligation_id=uuid4(),
            plan_id=uuid4(),
            valuation_date=date(2026, 12, 31),
            present_value_of_obligation=Decimal("500000000"),
            fair_value_of_plan_assets=Decimal("300000000"),
            net_defined_benefit_liability=Decimal("200000000"),
            current_service_cost=Decimal("10000000"),
            past_service_cost=Decimal(0),
            interest_cost=Decimal("5000000"),
            actuarial_gains_losses=Decimal(0),
            return_on_plan_assets=Decimal("2000000"),
            contributions_paid=Decimal(0),
            benefits_paid=Decimal(0),
            actuarial_assumptions=sample_db_obligation.actuarial_assumptions,
            valuation_performed_by="Actuary",
        )
        new_summary = validator.add_defined_benefit_obligation(sample_summary, new_oblig)
        assert len(new_summary.defined_benefit_obligations) == 2
        assert new_summary.defined_benefit_obligations[-1].obligation_id == new_oblig.obligation_id

    def test_add_termination_benefit(self, validator, sample_summary, sample_termination_benefit):
        new_benefit = PSAK24TerminationBenefit(
            benefit_id=uuid4(),
            employee_id=uuid4(),
            employee_name="Term2",
            termination_date=date(2026, 1, 1),
            years_of_service=5,
            last_salary=Decimal("10000000"),
            severance_pay=Decimal("50000000"),
            compensation_for_leave=Decimal("1000000"),
            other_benefits=Decimal(0),
            total_amount=Decimal("51000000"),
            currency="IDR",
        )
        new_summary = validator.add_termination_benefit(sample_summary, new_benefit)
        assert len(new_summary.termination_benefits) == 2

    def test_validate_summary_full_compliant(self, validator, sample_summary):
        # Make assumptions valid
        for ob in sample_summary.defined_benefit_obligations:
            ob.actuarial_assumptions.discount_rate = Decimal("7.5")
            ob.actuarial_assumptions.future_salary_increase_rate = Decimal("6")
            ob.actuarial_assumptions.retirement_age = 56
        result = validator.validate_summary(sample_summary)
        assert result.is_compliant is True
        assert result.compliance_level == PSAK24ComplianceLevel.FULL
        assert result.errors == []
        assert result.warnings == []

    def test_validate_summary_with_warnings(self, validator, sample_summary):
        # Set invalid assumptions
        for ob in sample_summary.defined_benefit_obligations:
            ob.actuarial_assumptions.discount_rate = Decimal("25")  # out of range
        result = validator.validate_summary(sample_summary)
        assert result.is_compliant is True  # warnings only
        assert result.compliance_level == PSAK24ComplianceLevel.SUBSTANTIAL
        assert len(result.warnings) > 0

    def test_validate_summary_with_error(self, validator, sample_summary):
        # Set negative plan assets
        for ob in sample_summary.defined_benefit_obligations:
            ob.fair_value_of_plan_assets = Decimal("-100")
        result = validator.validate_summary(sample_summary)
        assert result.is_compliant is False
        assert result.compliance_level == PSAK24ComplianceLevel.NON_COMPLIANT
        assert len(result.errors) > 0

    def test_get_requirements_summary(self, validator):
        req = validator.get_requirements_summary()
        assert "short_term" in req
        assert "defined_contribution" in req
        assert "defined_benefit" in req
        assert "disclosures" in req
        assert len(req["disclosures"]) >= 5


# -------------------- Tests for Singleton Accessor --------------------
def test_get_psak24_validator():
    v1 = get_psak24_validator()
    v2 = get_psak24_validator()
    assert v1 is v2
    assert isinstance(v1, PSAK24Validator)


# -------------------- Integration Test for Full Workflow --------------------
class TestPSAK24Workflow:
    def test_full_workflow(self, validator):
        # Create summary
        entity_id = uuid4()
        summary = validator.create_summary(entity_id, "PT Workflow", date(2026, 12, 31))

        # Add short-term
        stb = validator.create_short_term_benefit(
            uuid4(), "A", "salary", Decimal("10000000"), "IDR",
            date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 5)
        )
        summary = validator.add_short_term_benefit(summary, stb)

        # Add DC plan
        dc = validator.create_defined_contribution_plan("DC Plan", "DC-001", Decimal("2"), Decimal("3.7"), "IDR")
        dc = validator.record_dc_contribution(dc, Decimal("100000"), Decimal("185000"), True)
        summary = validator.add_defined_contribution_plan(summary, dc)

        # Add DB obligation
        assumptions = validator.create_actuarial_assumptions(
            Decimal("7.5"), Decimal("6"), Decimal("3"), "TMI", Decimal("5"), 56
        )
        db = validator.create_defined_benefit_obligation(
            uuid4(), date(2026, 12, 31), Decimal("1000000000"), Decimal("600000000"),
            Decimal("50000000"), Decimal(0), Decimal("40000000"), Decimal(0),
            Decimal("20000000"), Decimal(0), Decimal(0), assumptions, "Actuary"
        )
        summary = validator.add_defined_benefit_obligation(summary, db)

        # Add termination
        term = validator.create_termination_benefit(
            uuid4(), "B", date(2026, 1, 1), 10, Decimal("20000000"),
            Decimal("200000000"), Decimal("10000000"), Decimal(0), "IDR"
        )
        summary = validator.add_termination_benefit(summary, term)

        # Validate
        result = validator.validate_summary(summary)
        # Should be compliant with warnings (some assumptions may be fine)
        assert result.is_compliant is True
        # Check totals
        assert summary.total_employee_benefits_liberty() > 0  # just sanity
