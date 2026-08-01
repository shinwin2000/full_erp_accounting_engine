# test_tax_withholding_engine.py
# Comprehensive tests for tax_withholding_engine.py

from decimal import Decimal

import pytest

from domain.customer_supplier_employee.employee_ptkp_status_vo import (
    EmployeePTKPStatusVO,
    MaritalStatus,
)
from domain.payroll.tax_withholding_engine import TaxWithholdingEngine

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def engine():
    """Return a fresh TaxWithholdingEngine instance."""
    return TaxWithholdingEngine()


@pytest.fixture
def ptkp_tk0():
    """Single, no dependents."""
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.SINGLE,
        dependents=0,
        spouse_income_combined=False,
    )


@pytest.fixture
def ptkp_tk1():
    """Single, 1 dependent."""
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.SINGLE,
        dependents=1,
        spouse_income_combined=False,
    )


@pytest.fixture
def ptkp_k0():
    """Married, no dependents."""
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.MARRIED,
        dependents=0,
        spouse_income_combined=False,
    )


@pytest.fixture
def ptkp_k2():
    """Married, 2 dependents."""
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.MARRIED,
        dependents=2,
        spouse_income_combined=False,
    )


@pytest.fixture
def ptkp_kb0():
    """Married combined income, no dependents."""
    return EmployeePTKPStatusVO(
        marital_status=MaritalStatus.MARRIED_COMBINED,
        dependents=0,
        spouse_income_combined=True,
    )


# ============================================================================
# Tests for PTKP Helpers
# ============================================================================

class TestGetPtkpAmount:
    def test_ptkp_tk0(self, engine, ptkp_tk0):
        assert engine.get_ptkp_amount(ptkp_tk0) == Decimal("54000000")

    def test_ptkp_tk1(self, engine, ptkp_tk1):
        assert engine.get_ptkp_amount(ptkp_tk1) == Decimal("58500000")

    def test_ptkp_k0(self, engine, ptkp_k0):
        assert engine.get_ptkp_amount(ptkp_k0) == Decimal("58500000")

    def test_ptkp_k2(self, engine, ptkp_k2):
        assert engine.get_ptkp_amount(ptkp_k2) == Decimal("67500000")

    def test_ptkp_kb0(self, engine, ptkp_kb0):
        assert engine.get_ptkp_amount(ptkp_kb0) == Decimal("63000000")

    def test_unknown_status_fallback(self, engine):
        # Create a status that doesn't map (should fallback to TK/0 amount)
        EmployeePTKPStatusVO(
            marital_status=MaritalStatus.SINGLE,
            dependents=5,  # invalid, but we bypass validation? Actually validation prevents >3.
            spouse_income_combined=False,
        )
        # But dependents 5 would raise on construction. So we use a valid but non-existent combo? Not possible.
        # Instead, we can test that get_ptkp_amount handles a key not in dict.
        # Since we can't create invalid status easily, we'll mock or rely on the method's fallback.
        # We'll just ensure that a key not in the dict returns the default.
        # We can create a status with a weird combination that doesn't exist.
        # Actually all combos 0-3 exist. So we can't easily test fallback.
        # We'll trust the fallback is 54000000.
        # For safety, we can patch the dict temporarily.
        orig = engine._ptkp_amounts
        engine._ptkp_amounts = {}
        try:
            assert engine.get_ptkp_amount(ptkp_tk0) == Decimal("54000000")
        finally:
            engine._ptkp_amounts = orig


# ============================================================================
# Tests for Annual Tax Calculation
# ============================================================================

class TestCalculateAnnualTax:
    def test_zero_taxable_income(self, engine, ptkp_tk0):
        # Income exactly at PTKP
        tax = engine.calculate_annual_tax(Decimal("54000000"), ptkp_tk0)
        assert tax == Decimal("0")

    def test_income_below_ptkp(self, engine, ptkp_tk0):
        tax = engine.calculate_annual_tax(Decimal("40000000"), ptkp_tk0)
        assert tax == Decimal("0")

    def test_first_bracket_full(self, engine, ptkp_tk0):
        # Taxable income = 60,000,000 (first bracket fully used)
        # Total income = 54,000,000 + 60,000,000 = 114,000,000
        tax = engine.calculate_annual_tax(Decimal("114000000"), ptkp_tk0)
        # 5% of 60,000,000 = 3,000,000
        assert tax == Decimal("3000000")

    def test_second_bracket(self, engine, ptkp_tk0):
        # Taxable income = 100,000,000 (60M at 5%, 40M at 15%)
        total = Decimal("154000000")  # 54M PTKP + 100M taxable
        tax = engine.calculate_annual_tax(total, ptkp_tk0)
        expected = Decimal("60000000") * Decimal("0.05") + Decimal("40000000") * Decimal("0.15")
        assert tax == expected

    def test_third_bracket(self, engine, ptkp_tk0):
        # Taxable income = 300,000,000
        total = Decimal("354000000")
        tax = engine.calculate_annual_tax(total, ptkp_tk0)
        expected = (
            Decimal("60000000") * Decimal("0.05")
            + Decimal("190000000") * Decimal("0.15")  # 250M - 60M
            + Decimal("50000000") * Decimal("0.25")   # 300M - 250M
        )
        assert tax == expected

    def test_high_income(self, engine, ptkp_tk0):
        # Taxable income = 1,000,000,000
        total = Decimal("1054000000")
        tax = engine.calculate_annual_tax(total, ptkp_tk0)
        # Expected: progressive calculation
        # 0-60M: 5% = 3M
        # 60-250M: 15% of 190M = 28.5M
        # 250-500M: 25% of 250M = 62.5M
        # 500M-1B: 30% of 500M = 150M
        # Total = 244M
        expected = Decimal("244000000")
        assert tax == expected


# ============================================================================
# Tests for Monthly Tax Calculation
# ============================================================================

class TestCalculateMonthlyTax:
    def test_monthly_zero_tax(self, engine, ptkp_tk0):
        # Monthly net = 4.5M (annual 54M) => no tax
        monthly_net = Decimal("4500000")
        tax = engine.calculate_monthly_tax(monthly_net, ptkp_tk0)
        assert tax == Decimal("0")

    def test_monthly_tax_rounded_down(self, engine, ptkp_tk0):
        # Annual tax = 3,000,000 / 12 = 250,000 exactly
        monthly_net = Decimal("114000000") / Decimal(12)  # 9,500,000
        tax = engine.calculate_monthly_tax(monthly_net, ptkp_tk0)
        assert tax == Decimal("250000")

    def test_monthly_tax_with_rounding(self, engine, ptkp_tk0):
        # Annual tax = 3,100,000 / 12 = 258,333.333... rounded down to 258,333
        # Need to pick income that gives annual tax 3,100,000
        # Taxable income = 62,000,000 (5% of 60M + 15% of 2M)
        total = Decimal("116000000")  # 54M + 62M
        tax = engine.calculate_monthly_tax(total / Decimal(12), ptkp_tk0)
        expected = Decimal("258333")  # 3,100,000 / 12 = 258333.333 -> 258333
        assert tax == expected


# ============================================================================
# Tests for Full PPh21 Calculation
# ============================================================================

class TestCalculatePph21:
    def test_basic_pph21(self, engine, ptkp_tk0):
        gross = Decimal("10000000")  # 10M gross monthly
        # BPJS: assume 200k
        bpjs = Decimal("200000")
        # Position allowance: 500k
        pos = Decimal("500000")
        tax = engine.calculate_pph21(gross, ptkp_tk0, bpjs, pos, Decimal(0))
        # Net monthly = 10M - 200k - 500k = 9.3M
        # Annual net = 111.6M
        # Taxable income = 111.6M - 54M = 57.6M
        # Tax on 57.6M = 5% of 57.6M = 2.88M annual
        # Monthly = 2.88M / 12 = 240k, rounded down = 240000
        assert tax == Decimal("240000")

    def test_pph21_negative_net(self, engine, ptkp_tk0):
        gross = Decimal("1000000")
        bpjs = Decimal("200000")
        pos = Decimal("500000")
        # net = 300k positive, annual 3.6M below PTKP => tax 0
        tax = engine.calculate_pph21(gross, ptkp_tk0, bpjs, pos, Decimal(0))
        assert tax == Decimal("0")

    def test_pph21_with_other_deductions(self, engine, ptkp_tk0):
        gross = Decimal("15000000")
        bpjs = Decimal("300000")
        pos = Decimal("500000")
        other = Decimal("200000")
        tax = engine.calculate_pph21(gross, ptkp_tk0, bpjs, pos, other)
        # net monthly = 15M - 300k - 500k - 200k = 14M
        # annual = 168M
        # taxable = 168M - 54M = 114M
        # tax = 5% of 60M + 15% of 54M = 3M + 8.1M = 11.1M annual
        # monthly = 925,000
        assert tax == Decimal("925000")


# ============================================================================
# Tests for Bonus and THR
# ============================================================================

class TestCalculatePph21ForBonus:
    def test_bonus_tax_positive(self, engine, ptkp_tk0):
        # Annual gross without bonus = 120M
        # Bonus = 20M
        # Annual deductions = 6M (BPJS etc)
        bonus = Decimal("20000000")
        annual_gross = Decimal("120000000")
        annual_deductions = Decimal("6000000")
        tax = engine.calculate_pph21_for_bonus(bonus, annual_gross, ptkp_tk0, annual_deductions)
        # With bonus: total income 140M, deductions 6M => net 134M, taxable 80M
        # Tax with bonus: 5%*60M + 15%*20M = 3M + 3M = 6M
        # Without bonus: net 114M, taxable 60M, tax = 3M
        # Bonus tax = 3M
        assert tax == Decimal("3000000")

    def test_bonus_tax_zero(self, engine, ptkp_tk0):
        # Bonus too small to push into higher bracket, or income below PTKP
        bonus = Decimal("5000000")
        annual_gross = Decimal("50000000")  # below PTKP
        annual_deductions = Decimal("0")
        tax = engine.calculate_pph21_for_bonus(bonus, annual_gross, ptkp_tk0, annual_deductions)
        # Both with and without bonus: income below PTKP => tax 0
        assert tax == Decimal("0")

    def test_bonus_tax_partial(self, engine, ptkp_tk0):
        # Bonus partially taxed
        bonus = Decimal("10000000")
        annual_gross = Decimal("100000000")  # net = 100M - 0 = 100M, taxable 46M (60M bracket partially)
        # Without bonus: taxable 46M, tax = 2.3M
        # With bonus: taxable 56M, tax = 2.8M
        # Bonus tax = 0.5M
        annual_deductions = Decimal("0")
        tax = engine.calculate_pph21_for_bonus(bonus, annual_gross, ptkp_tk0, annual_deductions)
        assert tax == Decimal("500000")


class TestCalculatePph21ForThr:
    def test_thr_tax_same_as_bonus(self, engine, ptkp_tk0):
        # THR is calculated using bonus formula.
        thr = Decimal("15000000")
        monthly_gross = Decimal("10000000")
        monthly_deductions = Decimal("500000")
        tax = engine.calculate_pph21_for_thr(thr, monthly_gross, ptkp_tk0, monthly_deductions)
        # Equivalent to bonus calculation
        annual_gross = monthly_gross * 12  # 120M
        annual_deductions = monthly_deductions * 12  # 6M
        expected = engine.calculate_pph21_for_bonus(thr, annual_gross, ptkp_tk0, annual_deductions)
        assert tax == expected


# ============================================================================
# Tests for Severance Pay
# ============================================================================

class TestCalculatePph21ForSeverance:
    def test_severance_below_50m(self, engine):
        amount = Decimal("40000000")
        tax = engine.calculate_pph21_for_severance(amount, 5)
        assert tax == Decimal("0")

    def test_severance_50m_to_100m(self, engine):
        amount = Decimal("75000000")
        tax = engine.calculate_pph21_for_severance(amount, 5)
        # First 50M: 0%, remaining 25M: 5% = 1.25M
        assert tax == Decimal("1250000")

    def test_severance_100m_to_500m(self, engine):
        amount = Decimal("200000000")
        tax = engine.calculate_pph21_for_severance(amount, 5)
        # 0-50: 0, 50-100: 5% of 50M = 2.5M, 100-200: 15% of 100M = 15M
        expected = Decimal("2500000") + Decimal("15000000")
        assert tax == expected

    def test_severance_above_500m(self, engine):
        amount = Decimal("600000000")
        tax = engine.calculate_pph21_for_severance(amount, 5)
        # 0-50: 0, 50-100: 2.5M, 100-500: 15% of 400M = 60M, 500-600: 25% of 100M = 25M
        expected = Decimal("2500000") + Decimal("60000000") + Decimal("25000000")
        assert tax == expected

    def test_severance_exact_boundary(self, engine):
        amount = Decimal("50000000")
        tax = engine.calculate_pph21_for_severance(amount, 5)
        assert tax == Decimal("0")

        amount2 = Decimal("100000000")
        tax2 = engine.calculate_pph21_for_severance(amount2, 5)
        # 50M at 5% = 2.5M
        assert tax2 == Decimal("2500000")
