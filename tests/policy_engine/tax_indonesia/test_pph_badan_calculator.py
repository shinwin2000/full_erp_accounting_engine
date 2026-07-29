# test_pph_badan_calculator.py
# ==============================
# Comprehensive tests for PPh Badan Calculator.
# Covers all public methods and edge cases.

from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

import pytest

from policy_engine.tax_indonesia.pph_badan_calculator import (
    PPhBadanCalculationResult,
    PPhBadanCalculator,
    PPhBadanComponents,
    PPhBadanError,
    PPhBadanFiscalYear,
    PPhBadanType,
    get_pph_badan_calculator,
)


# ----------------------------------------------------------------------
# Tests for Enums
# ----------------------------------------------------------------------
class TestPPhBadanType:
    def test_members_exist(self):
        assert hasattr(PPhBadanType, "STANDARD")
        assert hasattr(PPhBadanType, "REDUCED_RATE")
        assert hasattr(PPhBadanType, "FINAL")
        assert hasattr(PPhBadanType, "GROSS_UP")

    def test_member_is_instance(self):
        assert isinstance(PPhBadanType.STANDARD, PPhBadanType)


class TestPPhBadanFiscalYear:
    def test_members_exist(self):
        assert hasattr(PPhBadanFiscalYear, "CALENDAR")
        assert hasattr(PPhBadanFiscalYear, "APRIL_MARCH")
        assert hasattr(PPhBadanFiscalYear, "CUSTOM")

    def test_member_is_instance(self):
        assert isinstance(PPhBadanFiscalYear.CALENDAR, PPhBadanFiscalYear)


# ----------------------------------------------------------------------
# Tests for Custom Exception
# ----------------------------------------------------------------------
class TestPPhBadanError:
    def test_construction(self):
        error = PPhBadanError("test message")
        assert isinstance(error, PPhBadanError)
        assert str(error) == "test message"


# ----------------------------------------------------------------------
# Tests for Value Object: PPhBadanComponents
# ----------------------------------------------------------------------
class TestPPhBadanComponents:
    def test_construction_success(self):
        kwargs = {
            "gross_revenue": Decimal("1000.00"),
            "cost_of_goods_sold": Decimal("400.00"),
            "operating_expenses": Decimal("200.00"),
            "non_operating_income": Decimal("50.00"),
            "non_operating_expenses": Decimal("30.00"),
            "taxable_income": Decimal("420.00"),
            "tax_credits": Decimal("20.00"),
            "final_tax": Decimal("10.00"),
            "tax_rate": Decimal("22"),
            "total_tax_payable": Decimal("82.40"),
            "effective_rate": Decimal("19.619"),
        }
        components = PPhBadanComponents(**kwargs)
        assert components.gross_revenue == kwargs["gross_revenue"]
        assert components.taxable_income == kwargs["taxable_income"]

    def test_frozen(self):
        components = PPhBadanComponents(
            gross_revenue=Decimal(0),
            cost_of_goods_sold=Decimal(0),
            operating_expenses=Decimal(0),
            non_operating_income=Decimal(0),
            non_operating_expenses=Decimal(0),
            taxable_income=Decimal(0),
            tax_credits=Decimal(0),
            final_tax=Decimal(0),
            tax_rate=Decimal(0),
            total_tax_payable=Decimal(0),
            effective_rate=Decimal(0),
        )
        with pytest.raises(Exception):
            components.gross_revenue = Decimal(100)  # dataclass frozen


# ----------------------------------------------------------------------
# Tests for Value Object: PPhBadanCalculationResult
# ----------------------------------------------------------------------
class TestPPhBadanCalculationResult:
    def test_construction_success(self):
        components = PPhBadanComponents(
            gross_revenue=Decimal("1000"),
            cost_of_goods_sold=Decimal("400"),
            operating_expenses=Decimal("200"),
            non_operating_income=Decimal("50"),
            non_operating_expenses=Decimal("30"),
            taxable_income=Decimal("420"),
            tax_credits=Decimal("20"),
            final_tax=Decimal("10"),
            tax_rate=Decimal("22"),
            total_tax_payable=Decimal("82.40"),
            effective_rate=Decimal("19.619"),
        )
        calc_id = uuid4()
        entity_id = uuid4()
        result = PPhBadanCalculationResult(
            calculation_id=calc_id,
            entity_id=entity_id,
            tax_year=2025,
            components=components,
            description="Test calculation",
        )
        assert result.calculation_id == calc_id
        assert result.entity_id == entity_id
        assert result.tax_year == 2025
        assert result.components == components
        assert result.description == "Test calculation"

    def test_to_dict(self):
        components = PPhBadanComponents(
            gross_revenue=Decimal("1000"),
            cost_of_goods_sold=Decimal("400"),
            operating_expenses=Decimal("200"),
            non_operating_income=Decimal("50"),
            non_operating_expenses=Decimal("30"),
            taxable_income=Decimal("420"),
            tax_credits=Decimal("20"),
            final_tax=Decimal("10"),
            tax_rate=Decimal("22"),
            total_tax_payable=Decimal("82.40"),
            effective_rate=Decimal("19.619"),
        )
        calc_id = uuid4()
        entity_id = uuid4()
        result = PPhBadanCalculationResult(
            calculation_id=calc_id,
            entity_id=entity_id,
            tax_year=2025,
            components=components,
            description="Test",
        )
        d = result.to_dict()
        assert d["calculation_id"] == str(calc_id)
        assert d["entity_id"] == str(entity_id)
        assert d["tax_year"] == 2025
        assert d["gross_revenue"] == "1000"
        assert d["total_tax_payable"] == "82.40"


# ----------------------------------------------------------------------
# Tests for PPhBadanCalculator (core logic)
# ----------------------------------------------------------------------
class TestPPhBadanCalculator:
    @pytest.fixture
    def calculator(self) -> PPhBadanCalculator:
        return PPhBadanCalculator()

    # --- Construction ---
    def test_construction(self, calculator):
        assert isinstance(calculator, PPhBadanCalculator)
        assert calculator._normal_rate == Decimal("22")
        assert calculator._facility_threshold == Decimal("4800000000")

    # --- calculate (instance) ---
    def test_calculate(self, calculator):
        # 22% of 1,000,000 = 220,000
        result = calculator.calculate(
            gross_revenue=Decimal("1000000"), taxable_income=Decimal("1000000")
        )
        assert result == Decimal("220000")

        # Edge: zero income
        result = calculator.calculate(
            gross_revenue=Decimal("0"), taxable_income=Decimal("0")
        )
        assert result == Decimal("0")

        # Rounding: taxable_income 1000 * 22% = 220 (integer)
        result = calculator.calculate(
            gross_revenue=Decimal("1000"), taxable_income=Decimal("1000")
        )
        assert result == Decimal("220")

    # --- set_normal_rate ---
    def test_set_normal_rate(self, calculator):
        assert calculator._normal_rate == Decimal("22")
        calculator.set_normal_rate(Decimal("25"))
        assert calculator._normal_rate == Decimal("25")
        calculator.set_normal_rate(Decimal("22"))  # revert

    # --- get_applicable_rate ---
    def test_get_applicable_rate_below_threshold(self, calculator):
        # Revenue <= 4.8M -> 11%
        revenue = Decimal("4800000000")  # exactly threshold
        rate = calculator.get_applicable_rate(revenue)
        assert rate == Decimal("11")  # 50% of 22

        revenue = Decimal("1000000")
        rate = calculator.get_applicable_rate(revenue)
        assert rate == Decimal("11")

    def test_get_applicable_rate_above_threshold(self, calculator):
        revenue = Decimal("4800000001")
        rate = calculator.get_applicable_rate(revenue)
        assert rate == Decimal("22")

    # --- calculate_taxable_income ---
    def test_calculate_taxable_income_basic(self, calculator):
        gross = Decimal("1000")
        cogs = Decimal("400")
        opex = Decimal("200")
        non_op_inc = Decimal("50")
        non_op_exp = Decimal("30")
        expected = gross - cogs - opex + non_op_inc - non_op_exp  # = 420
        result = calculator.calculate_taxable_income(
            gross, cogs, opex, non_op_inc, non_op_exp
        )
        assert result == expected

    def test_calculate_taxable_income_negative_becomes_zero(self, calculator):
        gross = Decimal("100")
        cogs = Decimal("200")
        opex = Decimal("50")
        result = calculator.calculate_taxable_income(gross, cogs, opex)
        assert result == Decimal(0)

    # --- calculate_tax ---
    def test_calculate_tax_without_gross_revenue_uses_normal_rate(self, calculator):
        taxable = Decimal("1000000")
        components = calculator.calculate_tax(taxable)
        # 22% of 1,000,000 = 220,000
        assert components.tax_rate == Decimal("22")
        assert components.total_tax_payable == Decimal("220000")
        assert components.tax_credits == Decimal(0)
        assert components.final_tax == Decimal(0)

    def test_calculate_tax_with_gross_revenue_facility(self, calculator):
        taxable = Decimal("1000000")
        gross = Decimal("1000000")  # below threshold
        components = calculator.calculate_tax(taxable, gross_revenue=gross)
        # rate should be 11% because gross <= 4.8M
        assert components.tax_rate == Decimal("11")
        assert components.total_tax_payable == Decimal("110000")

    def test_calculate_tax_with_credits_and_final(self, calculator):
        taxable = Decimal("1000000")
        tax_credits = Decimal("50000")
        final_tax = Decimal("10000")
        components = calculator.calculate_tax(
            taxable, tax_credits=tax_credits, final_tax=final_tax
        )
        # tax before credits = 220,000
        # total = 220,000 - 50,000 + 10,000 = 180,000
        assert components.total_tax_payable == Decimal("180000")
        assert components.effective_rate == (Decimal("180000") / Decimal("1000000")) * 100

    def test_calculate_tax_credits_exceed_tax(self, calculator):
        taxable = Decimal("1000000")
        tax_credits = Decimal("300000")  # lebih besar dari 220,000
        components = calculator.calculate_tax(taxable, tax_credits=tax_credits)
        assert components.total_tax_payable == Decimal(0)

    # --- calculate_full ---
    def test_calculate_full(self, calculator):
        entity_id = uuid4()
        tax_year = 2025
        gross_revenue = Decimal("2000000")
        cogs = Decimal("800000")
        opex = Decimal("500000")
        non_op_inc = Decimal("100000")
        non_op_exp = Decimal("20000")
        tax_credits = Decimal("30000")
        final_tax = Decimal("5000")

        result = calculator.calculate_full(
            entity_id=entity_id,
            tax_year=tax_year,
            gross_revenue=gross_revenue,
            cost_of_goods_sold=cogs,
            operating_expenses=opex,
            non_operating_income=non_op_inc,
            non_operating_expenses=non_op_exp,
            tax_credits=tax_credits,
            final_tax=final_tax,
        )

        # Verify result type
        assert isinstance(result, PPhBadanCalculationResult)
        assert result.entity_id == entity_id
        assert result.tax_year == tax_year
        assert result.description == f"PPh Badan calculation for year {tax_year}"

        # Check components
        comp = result.components
        taxable_income = gross_revenue - cogs - opex + non_op_inc - non_op_exp
        assert comp.taxable_income == taxable_income
        # Since gross_revenue <= 4.8M, rate should be 11%
        assert comp.tax_rate == Decimal("11")
        expected_tax = (taxable_income * Decimal("11") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        expected_payable = max(Decimal(0), expected_tax - tax_credits) + final_tax
        assert comp.total_tax_payable == expected_payable

    # --- calculate_installment_25 ---
    def test_calculate_installment_25(self, calculator):
        prev_tax = Decimal("1200000")
        credits = Decimal("200000")
        months = 12
        net = prev_tax - credits  # 1,000,000
        expected = (net / Decimal(months)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        result = calculator.calculate_installment_25(prev_tax, credits, months)
        assert result == expected

        # Custom months
        months = 6
        expected = (net / Decimal(months)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        result = calculator.calculate_installment_25(prev_tax, credits, months)
        assert result == expected

        # If net tax negative -> 0
        result = calculator.calculate_installment_25(Decimal("100"), Decimal("200"), 12)
        assert result == Decimal(0)

    # --- calculate_tax_simple (classmethod) ---
    def test_calculate_tax_simple(self):
        taxable = Decimal("1000000")
        result = PPhBadanCalculator.calculate_tax_simple(
            gross_revenue=Decimal("0"), taxable_income=taxable
        )
        expected = (taxable * Decimal("22") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        assert result == expected

        # Rounding check: taxable 1000 -> 220
        assert PPhBadanCalculator.calculate_tax_simple(
            Decimal("0"), Decimal("1000")
        ) == Decimal("220")

    # --- calculate_with_facility (classmethod) ---
    def test_calculate_with_facility(self):
        taxable = Decimal("1000000")
        result = PPhBadanCalculator.calculate_with_facility(
            gross_revenue=Decimal("1000000"), taxable_income=taxable
        )
        expected = (taxable * Decimal("11") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        assert result == expected

        # With decimal rounding
        taxable = Decimal("1234567")
        expected = (taxable * Decimal("11") / 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        result = PPhBadanCalculator.calculate_with_facility(
            Decimal("1000000"), taxable
        )
        assert result == expected

    # --- get_requirements_summary ---
    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "normal_rate" in summary
        assert summary["normal_rate"] == "22"
        assert summary["facility_rate"] == "11"
        assert summary["facility_threshold"] == "4800000000"
        assert "taxable_income_formula" in summary
        assert "due_date" in summary

    # --- validate & get_rate (added for compatibility) ---
    def test_validate(self, calculator):
        assert calculator.validate({}) is True
        assert calculator.validate({"some": "data"}) is True

    def test_get_rate(self, calculator):
        assert calculator.get_rate() == Decimal("22")
        assert calculator.get_rate("anything") == Decimal("22")


# ----------------------------------------------------------------------
# Tests for Singleton Accessor
# ----------------------------------------------------------------------
def test_get_pph_badan_calculator_singleton():
    instance1 = get_pph_badan_calculator()
    instance2 = get_pph_badan_calculator()
    assert instance1 is instance2
    assert isinstance(instance1, PPhBadanCalculator)
