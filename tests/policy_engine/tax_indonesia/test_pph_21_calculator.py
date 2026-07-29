# tests/policy_engine/tax_indonesia/test_pph_21_calculator.py
"""
Comprehensive unit tests for policy_engine/tax_indonesia/pph_21_calculator.py.
Covers all enums, result dataclass, calculator methods (including class methods),
and module-level functions. Uses Decimal with proper assertions.
"""

from decimal import Decimal

import pytest

from policy_engine.tax_indonesia.pph_21_calculator import (
    PPh21CalculationResult,
    PPh21Calculator,
    PPh21Type,
    get_pph21_calculator,
    hitung_pph21,
)

# ============================================================================
# Dummy PTKP Status class (replicates the fallback)
# ============================================================================

class DummyPTKPStatus:
    def __init__(self, status_code: str = "TK/0"):
        self._status_code = status_code

    def get_status_code(self) -> str:
        return self._status_code


# ============================================================================
# Enum Tests
# ============================================================================

class TestPPh21Type:
    def test_members(self):
        assert PPh21Type.MONTHLY.value == "monthly"
        assert PPh21Type.ANNUAL.value == "annual"
        assert PPh21Type.FINAL.value == "final"
        assert PPh21Type.SEVERANCE.value == "severance"


# ============================================================================
# PPh21CalculationResult Tests
# ============================================================================

class TestPPh21CalculationResult:
    def test_construction(self):
        result = PPh21CalculationResult(
            period="2026-01",
            gross_income=Decimal("10000000"),
            deductions=Decimal("500000"),
            net_income=Decimal("9500000"),
            ptkp_amount=Decimal("54000000"),
            taxable_income=Decimal("0"),
            tax_amount=Decimal("0"),
            tax_rate=Decimal("0"),
            pph21_type=PPh21Type.MONTHLY,
            details={"test": "value"},
        )
        assert result.period == "2026-01"
        assert result.gross_income == Decimal("10000000")
        assert result.deductions == Decimal("500000")
        assert result.pph21_type == PPh21Type.MONTHLY
        assert result.details["test"] == "value"

    def test_to_dict(self):
        result = PPh21CalculationResult(
            period="ANNUAL",
            gross_income=Decimal("100000000"),
            deductions=Decimal("5000000"),
            net_income=Decimal("95000000"),
            ptkp_amount=Decimal("54000000"),
            taxable_income=Decimal("41000000"),
            tax_amount=Decimal("2050000"),
            tax_rate=Decimal("2.05"),
            pph21_type=PPh21Type.ANNUAL,
        )
        d = result.to_dict()
        assert d["period"] == "ANNUAL"
        assert d["gross_income"] == "100000000"
        assert d["tax_amount"] == "2050000"
        assert d["pph21_type"] == "annual"
        assert "details" in d


# ============================================================================
# PPh21Calculator Tests
# ============================================================================

class TestPPh21Calculator:
    @pytest.fixture
    def calculator(self):
        return PPh21Calculator()

    @pytest.fixture
    def ptkp_tk0(self):
        return DummyPTKPStatus("TK/0")

    @pytest.fixture
    def ptkp_k3(self):
        return DummyPTKPStatus("K/3")

    # ---- calculate (main) ----
    def test_calculate(self, calculator, ptkp_tk0):
        tax = calculator.calculate(annual_gross=Decimal("100000000"), ptkp_status=ptkp_tk0)
        assert isinstance(tax, Decimal)
        # Expected tax for 100M with TK/0: taxable = 46M, tax = 5% of 46M = 2.3M
        assert tax == Decimal("2300000")

    def test_calculate_without_ptkp_default(self, calculator):
        tax = calculator.calculate(annual_gross=Decimal("100000000"))
        # Default TK/0
        assert tax == Decimal("2300000")

    # ---- calculate_annual_tax ----
    def test_calculate_annual_tax_tk0(self, calculator, ptkp_tk0):
        result = calculator.calculate_annual_tax(
            annual_gross=Decimal("100000000"),
            ptkp_status=ptkp_tk0,
            position_allowance=Decimal("0"),
            pension_contribution=Decimal("0"),
        )
        assert result.tax_amount == Decimal("2300000")
        assert result.ptkp_amount == Decimal("54000000")
        assert result.taxable_income == Decimal("46000000")
        assert result.pph21_type == PPh21Type.ANNUAL

    def test_calculate_annual_tax_k3(self, calculator, ptkp_k3):
        result = calculator.calculate_annual_tax(
            annual_gross=Decimal("200000000"),
            ptkp_status=ptkp_k3,
        )
        # PTKP K/3 = 72M, taxable = 128M
        # 60M at 5% = 3M, 68M at 15% = 10.2M, total 13.2M
        assert result.tax_amount == Decimal("13200000")
        assert result.ptkp_amount == Decimal("72000000")

    def test_calculate_annual_tax_with_position_allowance(self, calculator, ptkp_tk0):
        # Position allowance max annual 6M
        result = calculator.calculate_annual_tax(
            annual_gross=Decimal("150000000"),
            ptkp_status=ptkp_tk0,
            position_allowance=Decimal("7000000"),  # exceeds max, capped
            pension_contribution=Decimal("2000000"),
        )
        # Deductions = 6M + 2M = 8M, net = 142M, PTKP=54M, taxable=88M
        # 60M*5%=3M, 28M*15%=4.2M, total=7.2M
        assert result.tax_amount == Decimal("7200000")
        assert result.deductions == Decimal("8000000")
        assert result.details["position_allowance"] == "6000000"

    def test_calculate_annual_tax_zero_income(self, calculator, ptkp_tk0):
        result = calculator.calculate_annual_tax(
            annual_gross=Decimal("0"),
            ptkp_status=ptkp_tk0,
        )
        assert result.tax_amount == Decimal("0")
        assert result.taxable_income == Decimal("0")

    # ---- calculate_monthly_tax ----
    def test_calculate_monthly_tax_non_final(self, calculator, ptkp_tk0):
        result = calculator.calculate_monthly_tax(
            monthly_gross=Decimal("10000000"),
            ptkp_status=ptkp_tk0,
            position_allowance=Decimal("500000"),
            pension_contribution=Decimal("0"),
            is_final_month=False,
        )
        # Annual gross 120M, annual position allowance 6M, net 114M, PTKP 54M, taxable 60M
        # Annual tax = 3M (60M*5%), monthly = 250000
        assert result.tax_amount == Decimal("250000")
        assert result.deductions == Decimal("500000")
        assert result.period == "MONTHLY"
        assert result.pph21_type == PPh21Type.MONTHLY

    def test_calculate_monthly_tax_final_month(self, calculator, ptkp_tk0):
        result = calculator.calculate_monthly_tax(
            monthly_gross=Decimal("10000000"),
            ptkp_status=ptkp_tk0,
            position_allowance=Decimal("500000"),
            pension_contribution=Decimal("0"),
            is_final_month=True,
        )
        # Final month: tax = annual tax = 3M
        assert result.tax_amount == Decimal("3000000")
        assert result.details["is_final_month"] is True

    def test_calculate_monthly_tax_exceeds_position_allowance(self, calculator, ptkp_tk0):
        result = calculator.calculate_monthly_tax(
            monthly_gross=Decimal("10000000"),
            ptkp_status=ptkp_tk0,
            position_allowance=Decimal("600000"),  # exceeds max 500k
            pension_contribution=Decimal("0"),
            is_final_month=False,
        )
        # Should be capped at 500k
        assert result.deductions == Decimal("500000")  # position allowance only

    # ---- calculate_bonus_tax ----
    def test_calculate_bonus_tax(self, calculator, ptkp_tk0):
        result = calculator.calculate_bonus_tax(
            bonus_amount=Decimal("10000000"),
            monthly_gross=Decimal("10000000"),
            ptkp_status=ptkp_tk0,
            ytd_tax_paid=Decimal("0"),
        )
        # Annual without bonus: 120M, with bonus: 130M
        # Tax without: 3M, tax with: taxable 76M? Let's compute:
        # 120M annual -> PTKP 54M -> taxable 66M -> tax = 3M + (6M*15%=0.9M) = 3.9M? Wait:
        # 60M first -> 3M, remaining 6M at 15% -> 0.9M, total 3.9M
        # With bonus: 130M -> taxable 76M -> 60M*5%=3M, 16M*15%=2.4M total 5.4M
        # Bonus tax = 5.4M - 3.9M = 1.5M
        assert result.tax_amount == Decimal("1500000")
        assert result.gross_income == Decimal("10000000")
        assert result.pph21_type == PPh21Type.FINAL

    # ---- calculate_severance_tax ----
    def test_calculate_severance_tax_below_50m(self, calculator):
        result = calculator.calculate_severance_tax(
            severance_amount=Decimal("30000000"),
            years_of_service=5,
        )
        assert result.tax_amount == Decimal("0")
        assert result.pph21_type == PPh21Type.SEVERANCE

    def test_calculate_severance_tax_50_100m(self, calculator):
        result = calculator.calculate_severance_tax(
            severance_amount=Decimal("75000000"),
            years_of_service=5,
        )
        # 50M*0% + 25M*5% = 1.25M
        assert result.tax_amount == Decimal("1250000")

    def test_calculate_severance_tax_100_500m(self, calculator):
        result = calculator.calculate_severance_tax(
            severance_amount=Decimal("250000000"),
            years_of_service=5,
        )
        # 50M*0% + 50M*5% + 150M*15% = 2.5M + 22.5M = 25M
        assert result.tax_amount == Decimal("25000000")

    def test_calculate_severance_tax_above_500m(self, calculator):
        result = calculator.calculate_severance_tax(
            severance_amount=Decimal("600000000"),
            years_of_service=5,
        )
        # 50M*0% + 50M*5% + 400M*15% + 100M*25% = 2.5M + 60M + 25M = 87.5M
        assert result.tax_amount == Decimal("87500000")

    # ---- get_ptkp_amount ----
    def test_get_ptkp_amount(self, calculator, ptkp_tk0):
        assert calculator.get_ptkp_amount(ptkp_tk0) == Decimal("54000000")
        ptkp_k3 = DummyPTKPStatus("K/3")
        assert calculator.get_ptkp_amount(ptkp_k3) == Decimal("72000000")
        # Unknown defaults to TK/0
        unknown = DummyPTKPStatus("UNKNOWN")
        assert calculator.get_ptkp_amount(unknown) == Decimal("54000000")

    # ---- get_tax_brackets ----
    def test_get_tax_brackets(self, calculator):
        brackets = calculator.get_tax_brackets()
        assert len(brackets) == 5
        assert brackets[0]["lower"] == "0"
        assert brackets[0]["upper"] == "60000000"
        assert brackets[0]["rate"] == "5"
        assert brackets[-1]["upper"] == "inf"

    # ---- get_requirements_summary ----
    def test_get_requirements_summary(self, calculator):
        summary = calculator.get_requirements_summary()
        assert "tax_brackets" in summary
        assert "ptkp_rates" in summary
        assert "position_allowance_max_monthly" in summary
        assert summary["position_allowance_max_monthly"] == "500000"
        assert summary["ptkp_rates"]["K/3"] == "72000000"

    # ---- class methods ----
    def test_annual_tax(self):
        tax = PPh21Calculator.annual_tax(Decimal("100000000"), "TK/0")
        assert tax == Decimal("2300000")  # 46M*5%

        tax2 = PPh21Calculator.annual_tax(Decimal("200000000"), "K/3")
        # PTKP 72M -> taxable 128M -> 3M + 10.2M = 13.2M
        assert tax2 == Decimal("13200000")

    def test_monthly_ter(self):
        # Test exact known values
        assert PPh21Calculator.monthly_ter(Decimal("10000000")) == Decimal("200000")  # 2%

        # Test a value from TER table for category A: e.g., 7.5M -> 2.75%? Actually table has values.
        # We'll test a specific entry: 5.5M -> 0.25% of 5.5M = 13,750
        # But because our table has ranges, we need to check a known range.
        # Use 5.6M exactly? The table has (5600000,5800000): 0.50%
        # For category A, 5.6M -> 0.5% => 28,000
        # But our method returns rounded down to integer.
        assert PPh21Calculator.monthly_ter(Decimal("5600000")) == Decimal("28000")  # 0.5% of 5.6M

        # Test a value not in table => 0
        assert PPh21Calculator.monthly_ter(Decimal("100000")) == Decimal("0")

    def test_get_ptkp(self):
        assert PPh21Calculator.get_ptkp("TK/0") == Decimal("54000000")
        assert PPh21Calculator.get_ptkp("K/3") == Decimal("72000000")
        assert PPh21Calculator.get_ptkp("INVALID") == Decimal("54000000")  # default

    def test_nett_salary(self):
        # Gross 10M, K/1 PTKP 63M, BPJS 0
        # Annual gross 120M, PTKP 63M -> taxable 57M -> tax = 2.85M (57M*5%)
        # Monthly tax = 2.85M/12 = 237500
        nett = PPh21Calculator.nett_salary(Decimal("10000000"), "K/1", Decimal("0"))
        expected = Decimal("10000000") - Decimal("237500")  # ~9,762,500
        assert nett == Decimal("9762500")

        # With BPJS
        nett2 = PPh21Calculator.nett_salary(Decimal("10000000"), "K/1", Decimal("300000"))
        expected2 = Decimal("10000000") - Decimal("237500") - Decimal("300000")
        assert nett2 == Decimal("9462500")

    # ---- validate, get_rate, calculate_tax (compatibility) ----
    def test_validate(self, calculator):
        assert calculator.validate({}) is True

    def test_get_rate(self, calculator):
        assert calculator.get_rate() == Decimal("0")
        assert calculator.get_rate("PPH21") == Decimal("0")

    def test_calculate_tax(self, calculator):
        tax = calculator.calculate_tax(Decimal("100000000"), "TK/0")
        assert tax == Decimal("2300000")

    # ---- singleton getter ----
    def test_get_pph21_calculator(self):
        calc1 = get_pph21_calculator()
        calc2 = get_pph21_calculator()
        assert calc1 is calc2
        assert isinstance(calc1, PPh21Calculator)


# ============================================================================
# Module-level function hitung_pph21
# ============================================================================

def test_hitung_pph21():
    tax = hitung_pph21(Decimal("100000000"), "TK/0")
    assert tax == Decimal("2300000")
    tax2 = hitung_pph21(Decimal("200000000"), "K/3")
    assert tax2 == Decimal("13200000")
