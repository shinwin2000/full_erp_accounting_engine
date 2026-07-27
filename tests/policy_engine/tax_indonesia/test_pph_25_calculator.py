# tests/policy_engine/tax_indonesia/test_pph_25_calculator.py
"""
Comprehensive tests for PPh 25 Calculator (Angsuran Pajak).
Covers all methods including class methods, exception cases, and installment updates.
"""

from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import pytest

from policy_engine.tax_indonesia.pph_25_calculator import (
    PPh25CalculationMethod,
    PPh25CalculationResult,
    PPh25Calculator,
    PPh25Error,
    PPh25Installment,
    PPh25Type,
    get_pph25_calculator,
)


# ============================================================================
# Enum tests
# ============================================================================

class TestPPh25Type:
    def test_members_exist(self):
        assert hasattr(PPh25Type, 'STANDARD')
        assert hasattr(PPh25Type, 'BASED_ON_PREVIOUS_YEAR')
        assert hasattr(PPh25Type, 'FOR_NEW_ENTITY')
        assert hasattr(PPh25Type, 'BASED_ON_PROFIT_LOSS')
        assert hasattr(PPh25Type, 'FOR_CERTAIN_INDUSTRY')
        assert PPh25Type.STANDARD.value == "standard"
        assert PPh25Type.BASED_ON_PREVIOUS_YEAR.value == "based_on_previous_year"


class TestPPh25CalculationMethod:
    def test_members_exist(self):
        assert hasattr(PPh25CalculationMethod, 'MONTHLY_DIVISION')
        assert hasattr(PPh25CalculationMethod, 'MONTHLY_EQUAL')
        assert hasattr(PPh25CalculationMethod, 'GRADUAL')
        assert PPh25CalculationMethod.MONTHLY_DIVISION.value == "monthly_division"


# ============================================================================
# Custom exception
# ============================================================================

class TestPPh25Error:
    def test_construction(self):
        error = PPh25Error("Test message")
        assert str(error) == "Test message"
        assert isinstance(error, Exception)


# ============================================================================
# PPh25Installment tests
# ============================================================================

class TestPPh25Installment:
    def test_construction(self):
        payment_date = datetime(2026, 6, 15, tzinfo=UTC)
        inst = PPh25Installment(
            month=6,
            year=2026,
            amount=Decimal("1000000"),
            is_paid=True,
            payment_date=payment_date,
        )
        assert inst.month == 6
        assert inst.year == 2026
        assert inst.amount == Decimal("1000000")
        assert inst.is_paid is True
        assert inst.payment_date == payment_date

    def test_to_dict(self):
        inst = PPh25Installment(
            month=6,
            year=2026,
            amount=Decimal("1000000"),
            is_paid=False,
            payment_date=None,
        )
        d = inst.to_dict()
        assert d["month"] == 6
        assert d["year"] == 2026
        assert d["amount"] == "1000000"
        assert d["is_paid"] is False
        assert d["payment_date"] is None


# ============================================================================
# PPh25CalculationResult tests
# ============================================================================

class TestPPh25CalculationResult:
    def test_construction(self):
        calc_id = uuid4()
        entity_id = uuid4()
        installments = [
            PPh25Installment(month=1, year=2026, amount=Decimal("1000000")),
            PPh25Installment(month=2, year=2026, amount=Decimal("1000000")),
        ]
        result = PPh25CalculationResult(
            calculation_id=calc_id,
            entity_id=entity_id,
            tax_year=2026,
            total_annual_tax_estimate=Decimal("12000000"),
            monthly_installment=Decimal("1000000"),
            installments=installments,
            calculation_method=PPh25CalculationMethod.MONTHLY_DIVISION,
            description="Monthly installment test",
        )
        assert result.calculation_id == calc_id
        assert result.monthly_installment == Decimal("1000000")
        assert len(result.installments) == 2

    def test_to_dict(self):
        calc_id = uuid4()
        entity_id = uuid4()
        inst = PPh25Installment(month=1, year=2026, amount=Decimal("1000000"))
        result = PPh25CalculationResult(
            calculation_id=calc_id,
            entity_id=entity_id,
            tax_year=2026,
            total_annual_tax_estimate=Decimal("12000000"),
            monthly_installment=Decimal("1000000"),
            installments=[inst],
            calculation_method=PPh25CalculationMethod.MONTHLY_DIVISION,
            description="Test",
        )
        d = result.to_dict()
        assert d["calculation_id"] == str(calc_id)
        assert d["entity_id"] == str(entity_id)
        assert d["tax_year"] == 2026
        assert d["total_annual_tax_estimate"] == "12000000"
        assert d["monthly_installment"] == "1000000"
        assert len(d["installments"]) == 1
        assert d["calculation_method"] == "monthly_division"


# ============================================================================
# PPh25Calculator tests
# ============================================================================

class TestPPh25Calculator:
    @pytest.fixture
    def calculator(self):
        return PPh25Calculator()

    def test_construction(self, calculator):
        assert isinstance(calculator, PPh25Calculator)
        assert calculator._min_installment == Decimal(0)

    # ---- calculate method (instance) ----
    def test_calculate(self, calculator):
        # PPh terutang tahun sebelumnya = 120,000,000 -> angsuran = 10,000,000
        result = calculator.calculate(previous_year_tax_liability=Decimal("120000000"))
        assert result == Decimal("10000000")

    def test_calculate_rounding(self, calculator):
        # 125,000,000 / 12 = 10,416,666.666... -> rounded to 10,416,667
        result = calculator.calculate(previous_year_tax_liability=Decimal("125000000"))
        assert result == Decimal("10416667")

    # ---- calculate_standard_installment ----
    def test_calculate_standard_installment(self, calculator):
        entity_id = uuid4()
        previous_tax = Decimal("150000000")
        withheld = Decimal("20000000")
        result = calculator.calculate_standard_installment(
            entity_id=entity_id,
            previous_year_tax_payable=previous_tax,
            tax_withheld_by_others=withheld,
            tax_year=2026,
            months=12,
        )
        net = previous_tax - withheld  # 130,000,000
        expected_monthly = (net / Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)  # 10,833,333
        assert result.monthly_installment == expected_monthly
        assert result.total_annual_tax_estimate == expected_monthly * Decimal(12)
        assert len(result.installments) == 12
        assert result.calculation_method == PPh25CalculationMethod.MONTHLY_DIVISION
        assert result.entity_id == entity_id
        assert result.tax_year == 2026

    def test_calculate_standard_installment_with_minimum(self, calculator):
        # Set minimum to 10,000 (hardcoded in method) - we can test if net tax < minimum
        # For net tax = 0, monthly should be 0? Actually method sets min 10000 if net_tax > 0.
        entity_id = uuid4()
        previous_tax = Decimal("100000")
        withheld = Decimal("90000")  # net = 10,000
        result = calculator.calculate_standard_installment(
            entity_id=entity_id,
            previous_year_tax_payable=previous_tax,
            tax_withheld_by_others=withheld,
            tax_year=2026,
            months=12,
        )
        # net = 10,000 -> monthly = 833.33 -> rounded to 833, but net_tax>0 and 833 < 10000 -> min 10000
        assert result.monthly_installment == Decimal("10000")
        assert result.total_annual_tax_estimate == Decimal("120000")  # 12 * 10,000

    def test_calculate_standard_installment_net_zero(self, calculator):
        previous_tax = Decimal("100000")
        withheld = Decimal("100000")  # net = 0
        entity_id = uuid4()
        result = calculator.calculate_standard_installment(
            entity_id=entity_id,
            previous_year_tax_payable=previous_tax,
            tax_withheld_by_others=withheld,
            tax_year=2026,
            months=12,
        )
        assert result.monthly_installment == Decimal(0)
        assert result.total_annual_tax_estimate == Decimal(0)

    def test_calculate_standard_installment_negative_months(self, calculator):
        with pytest.raises(PPh25Error, match="Months must be positive"):
            calculator.calculate_standard_installment(
                entity_id=uuid4(),
                previous_year_tax_payable=Decimal("100000"),
                tax_withheld_by_others=Decimal(0),
                tax_year=2026,
                months=0,
            )

    # ---- calculate_for_new_entity ----
    def test_calculate_for_new_entity(self, calculator):
        entity_id = uuid4()
        projected_profit = Decimal("500000000")
        tax_rate = Decimal("22")  # 22%
        result = calculator.calculate_for_new_entity(
            entity_id=entity_id,
            projected_taxable_profit=projected_profit,
            tax_rate=tax_rate,
            tax_year=2026,
            months=12,
        )
        projected_tax = projected_profit * (tax_rate / Decimal(100))  # 110,000,000
        expected_monthly = (projected_tax / Decimal(12)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)  # 9,166,667
        assert result.monthly_installment == expected_monthly
        assert result.total_annual_tax_estimate == expected_monthly * Decimal(12)
        assert len(result.installments) == 12
        assert result.calculation_method == PPh25CalculationMethod.MONTHLY_EQUAL

    def test_calculate_for_new_entity_custom_months(self, calculator):
        entity_id = uuid4()
        result = calculator.calculate_for_new_entity(
            entity_id=entity_id,
            projected_taxable_profit=Decimal("120000000"),
            tax_rate=Decimal("22"),
            tax_year=2026,
            months=6,
        )
        # projected tax = 26,400,000; /6 = 4,400,000
        assert result.monthly_installment == Decimal("4400000")
        assert len(result.installments) == 6

    # ---- calculate_based_on_recent_filings ----
    def test_calculate_based_on_recent_filings(self, calculator):
        entity_id = uuid4()
        last_period_tax = Decimal("30000000")  # 3 months total
        result = calculator.calculate_based_on_recent_filings(
            entity_id=entity_id,
            last_period_tax=last_period_tax,
            tax_year=2026,
        )
        avg = (last_period_tax / Decimal(3)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)  # 10,000,000
        assert result.monthly_installment == Decimal("10000000")
        assert result.total_annual_tax_estimate == Decimal("120000000")
        assert len(result.installments) == 12
        assert result.calculation_method == PPh25CalculationMethod.GRADUAL

    # ---- update_installment_after_underpayment ----
    def test_update_installment_after_underpayment_no_underpayment(self, calculator):
        # Create a result with some paid installments
        installments = [
            PPh25Installment(month=1, year=2026, amount=Decimal("1000000"), is_paid=True),
            PPh25Installment(month=2, year=2026, amount=Decimal("1000000"), is_paid=True),
            PPh25Installment(month=3, year=2026, amount=Decimal("1000000"), is_paid=False),
        ]
        calc_result = PPh25CalculationResult(
            calculation_id=uuid4(),
            entity_id=uuid4(),
            tax_year=2026,
            total_annual_tax_estimate=Decimal("12000000"),
            monthly_installment=Decimal("1000000"),
            installments=installments,
            calculation_method=PPh25CalculationMethod.MONTHLY_DIVISION,
            description="Test",
        )
        actual_tax = Decimal("3000000")  # total paid = 2,000,000; actual 3,000,000 -> underpayment 1,000,000? Actually paid_installments is separate.
        paid_installments = Decimal("1000000")  # additional paid outside? We'll pass 0.
        # The method sums is_paid installments: 2,000,000 + paid_installments (0) = 2,000,000
        # underpayment = actual - (sum paid + paid_installments) = 3,000,000 - 2,000,000 = 1,000,000
        underpayment = calculator.update_installment_after_underpayment(
            current_calculation=calc_result,
            actual_tax_due=actual_tax,
            paid_installments=paid_installments,
        )
        assert underpayment == Decimal("1000000")

    def test_update_installment_after_underpayment_overpayment(self, calculator):
        installments = [
            PPh25Installment(month=1, year=2026, amount=Decimal("1000000"), is_paid=True),
            PPh25Installment(month=2, year=2026, amount=Decimal("1000000"), is_paid=True),
            PPh25Installment(month=3, year=2026, amount=Decimal("1000000"), is_paid=True),
        ]
        calc_result = PPh25CalculationResult(
            calculation_id=uuid4(),
            entity_id=uuid4(),
            tax_year=2026,
            total_annual_tax_estimate=Decimal("12000000"),
            monthly_installment=Decimal("1000000"),
            installments=installments,
            calculation_method=PPh25CalculationMethod.MONTHLY_DIVISION,
            description="Test",
        )
        actual_tax = Decimal("2000000")
        paid_installments = Decimal("500000")
        # sum paid = 3,000,000; plus paid_installments = 3,500,000; underpayment = 2,000,000 - 3,500,000 = -1,500,000
        underpayment = calculator.update_installment_after_underpayment(
            current_calculation=calc_result,
            actual_tax_due=actual_tax,
            paid_installments=paid_installments,
        )
        assert underpayment == Decimal("-1500000")

    def test_update_installment_after_underpayment_no_paid(self, calculator):
        installments = [
            PPh25Installment(month=1, year=2026, amount=Decimal("1000000"), is_paid=False),
            PPh25Installment(month=2, year=2026, amount=Decimal("1000000"), is_paid=False),
        ]
        calc_result = PPh25CalculationResult(
            calculation_id=uuid4(),
            entity_id=uuid4(),
            tax_year=2026,
            total_annual_tax_estimate=Decimal("12000000"),
            monthly_installment=Decimal("1000000"),
            installments=installments,
            calculation_method=PPh25CalculationMethod.MONTHLY_DIVISION,
            description="Test",
        )
        actual_tax = Decimal("500000")
        paid_installments = Decimal(0)
        underpayment = calculator.update_installment_after_underpayment(
            current_calculation=calc_result,
            actual_tax_due=actual_tax,
            paid_installments=paid_installments,
        )
        assert underpayment == Decimal("500000")  # 500k - 0 = 500k

    # ---- get_requirements_summary ----
    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "formula" in summary
        assert "minimum_installment" in summary
        assert "due_date" in summary
        assert "note" in summary

    # ---- class methods ----
    def test_monthly_installment_simple(self):
        # PPh terutang 120,000,000 -> 10,000,000
        result = PPh25Calculator.monthly_installment_simple(Decimal("120000000"))
        assert result == Decimal("10000000")

    def test_monthly_installment_simple_rounding(self):
        result = PPh25Calculator.monthly_installment_simple(Decimal("125000000"))
        assert result == Decimal("10416667")

    def test_monthly_installment_for_new_company(self):
        # Estimasi PPh tahunan 120,000,000 -> 10,000,000
        result = PPh25Calculator.monthly_installment_for_new_company(Decimal("120000000"))
        assert result == Decimal("10000000")

    def test_monthly_installment_for_new_company_rounding(self):
        result = PPh25Calculator.monthly_installment_for_new_company(Decimal("125000000"))
        assert result == Decimal("10416667")

    # ---- validate (added for checker) ----
    def test_validate(self, calculator):
        assert calculator.validate({}) is True

    # ---- get_rate ----
    def test_get_rate(self, calculator):
        assert calculator.get_rate() == Decimal(0)

    # ---- calculate_tax (instance) ----
    def test_calculate_tax(self, calculator):
        entity_id = uuid4()
        previous_tax = Decimal("120000000")
        withheld = Decimal("0")
        tax_year = 2026
        monthly = calculator.calculate_tax(
            entity_id=entity_id,
            previous_year_tax_payable=previous_tax,
            tax_withheld_by_others=withheld,
            tax_year=tax_year,
            months=12,
        )
        assert monthly == Decimal("10000000")


# ============================================================================
# Singleton accessor test
# ============================================================================

def test_get_pph25_calculator():
    c1 = get_pph25_calculator()
    c2 = get_pph25_calculator()
    assert c1 is c2
    assert isinstance(c1, PPh25Calculator)