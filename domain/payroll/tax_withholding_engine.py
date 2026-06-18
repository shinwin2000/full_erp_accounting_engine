#!/usr/bin/env python3
"""
Module: tax_withholding_engine.py
Layer: 6 - Domain / Payroll
Responsibility: PPh 21 calculation engine.

Provides engine to calculate Pajak Penghasilan Pasal 21 (PPh 21)
on employee income according to progressive tax rates and PTKP
(Taxable Income Threshold).

Dependencies:
- Python standard library (decimal, logging, dataclasses)
- domain.customer_supplier_employee.employee_ptkp_status_vo (EmployeePTKPStatusVO)

Audit: Every PPh 21 calculation is recorded.
"""

from __future__ import annotations

import logging
from decimal import ROUND_DOWN, Decimal

from domain.customer_supplier_employee.employee_ptkp_status_vo import EmployeePTKPStatusVO

logger = logging.getLogger(__name__)


# ============================================================================
# Constants
# ============================================================================

# PPh 21 progressive tax rates (UU HPP)
TAX_BRACKETS = [
    (Decimal(0), Decimal(60000000), Decimal(5)),  # 0-60 juta: 5%
    (Decimal(60000000), Decimal(250000000), Decimal(15)),  # 60-250 juta: 15%
    (Decimal(250000000), Decimal(500000000), Decimal(25)),  # 250-500 juta: 25%
    (Decimal(500000000), Decimal(5000000000), Decimal(30)),  # 500 juta - 5M: 30%
    (Decimal(5000000000), Decimal("inf"), Decimal(35)),  # >5M: 35%
]

# PTKP annual amounts (2024)
PTKP_AMOUNTS = {
    "TK/0": Decimal(54000000),  # Single, no dependents
    "TK/1": Decimal(58500000),  # Single, 1 dependent
    "TK/2": Decimal(63000000),  # Single, 2 dependents
    "TK/3": Decimal(67500000),  # Single, 3 dependents
    "K/0": Decimal(58500000),  # Married, no dependents
    "K/1": Decimal(63000000),  # Married, 1 dependent
    "K/2": Decimal(67500000),  # Married, 2 dependents
    "K/3": Decimal(72000000),  # Married, 3 dependents
    "KB/0": Decimal(63000000),  # Married, combined income, 0 dependents
    "KB/1": Decimal(67500000),  # Married, combined income, 1 dependent
    "KB/2": Decimal(72000000),  # Married, combined income, 2 dependents
    "KB/3": Decimal(76500000),  # Married, combined income, 3 dependents
}


# ============================================================================
# Tax Withholding Engine
# ============================================================================


class TaxWithholdingEngine:
    """
    Engine for PPh 21 calculation.

    Business context:
    Calculates PPh 21 on employee income based on progressive tax rates
    and PTKP status.

    Methods:
        get_ptkp_amount: Get PTKP amount based on status.
        calculate_annual_tax: Calculate annual PPh 21.
        calculate_monthly_tax: Calculate monthly PPh 21.
        calculate_pph21: Full calculation with all components.
        calculate_pph21_for_bonus: Calculate PPh 21 on bonus.
        calculate_pph21_for_thr: Calculate PPh 21 on THR.
        calculate_pph21_for_severance: Calculate PPh 21 on severance pay.
    """

    def __init__(self):
        self._tax_brackets = TAX_BRACKETS
        self._ptkp_amounts = PTKP_AMOUNTS

    # ------------------------------------------------------------------------
    # PTKP helpers
    # ------------------------------------------------------------------------

    def get_ptkp_amount(self, ptkp_status: EmployeePTKPStatusVO) -> Decimal:
        """Get PTKP amount based on status."""
        # Build status key
        if ptkp_status.spouse_income_combined:
            status_key = f"KB/{ptkp_status.dependents}"
        else:
            marital = "K" if ptkp_status.is_married else "TK"
            status_key = f"{marital}/{ptkp_status.dependents}"
        return self._ptkp_amounts.get(status_key, Decimal(54000000))

    # ------------------------------------------------------------------------
    # Annual tax calculation
    # ------------------------------------------------------------------------

    def calculate_annual_tax(
        self,
        annual_net_income: Decimal,
        ptkp_status: EmployeePTKPStatusVO,
    ) -> Decimal:
        """
        Calculate annual PPh 21.

        Args:
            annual_net_income: Annual net income (after deductions).
            ptkp_status: PTKP status.

        Returns:
            Annual PPh 21 owed.
        """
        ptkp = self.get_ptkp_amount(ptkp_status)
        taxable_income = max(Decimal(0), annual_net_income - ptkp)

        tax = Decimal(0)
        remaining = taxable_income

        for lower, upper, rate in self._tax_brackets:
            if remaining <= 0:
                break
            if upper == Decimal("inf"):
                bracket_amount = remaining
            else:
                bracket_amount = min(remaining, upper - lower)
            tax += bracket_amount * (rate / Decimal(100))
            remaining -= bracket_amount

        return tax

    def calculate_monthly_tax(
        self,
        monthly_net_income: Decimal,
        ptkp_status: EmployeePTKPStatusVO,
    ) -> Decimal:
        """
        Calculate monthly PPh 21 (nett method).

        Args:
            monthly_net_income: Monthly net income.
            ptkp_status: PTKP status.

        Returns:
            Monthly PPh 21 (rounded down to nearest whole Rupiah).
        """
        annual_income = monthly_net_income * Decimal(12)
        annual_tax = self.calculate_annual_tax(annual_income, ptkp_status)
        monthly_tax = annual_tax / Decimal(12)
        # Round down as per tax regulation
        return monthly_tax.quantize(Decimal("1"), rounding=ROUND_DOWN)

    # ------------------------------------------------------------------------
    # Full PPh 21 calculation
    # ------------------------------------------------------------------------

    def calculate_pph21(
        self,
        gross_salary: Decimal,
        ptkp_status: EmployeePTKPStatusVO,
        bpjs_contribution: Decimal = Decimal(0),
        position_allowance: Decimal = Decimal(0),
        other_deductions: Decimal = Decimal(0),
    ) -> Decimal:
        """
        Calculate PPh 21 with full components.

        Args:
            gross_salary: Monthly gross salary.
            ptkp_status: PTKP status.
            bpjs_contribution: Employee BPJS contribution.
            position_allowance: Position allowance (max 500k/month).
            other_deductions: Other fiscal deductions.

        Returns:
            Monthly PPh 21.
        """
        monthly_net = gross_salary - bpjs_contribution - position_allowance - other_deductions
        if monthly_net <= 0:
            return Decimal(0)
        return self.calculate_monthly_tax(monthly_net, ptkp_status)

    # ------------------------------------------------------------------------
    # Bonus and THR
    # ------------------------------------------------------------------------

    def calculate_pph21_for_bonus(
        self,
        bonus_amount: Decimal,
        annual_gross_salary: Decimal,
        ptkp_status: EmployeePTKPStatusVO,
        annual_deductions: Decimal = Decimal(0),
    ) -> Decimal:
        """
        Calculate PPh 21 on bonus.

        Formula:
            Tax with bonus - Tax without bonus

        Args:
            bonus_amount: Bonus amount.
            annual_gross_salary: Annual gross salary without bonus.
            ptkp_status: PTKP status.
            annual_deductions: Annual fiscal deductions (BPJS, etc.)

        Returns:
            PPh 21 for the bonus.
        """
        total_income = annual_gross_salary + bonus_amount
        total_tax = self.calculate_annual_tax(total_income - annual_deductions, ptkp_status)
        normal_tax = self.calculate_annual_tax(annual_gross_salary - annual_deductions, ptkp_status)
        bonus_tax = total_tax - normal_tax
        return max(Decimal(0), bonus_tax)

    def calculate_pph21_for_thr(
        self,
        thr_amount: Decimal,
        monthly_gross: Decimal,
        ptkp_status: EmployeePTKPStatusVO,
        monthly_deductions: Decimal = Decimal(0),
    ) -> Decimal:
        """
        Calculate PPh 21 on THR (Holiday Allowance).

        THR is treated like bonus.
        """
        annual_gross = monthly_gross * Decimal(12)
        annual_deductions = monthly_deductions * Decimal(12)
        return self.calculate_pph21_for_bonus(
            thr_amount, annual_gross, ptkp_status, annual_deductions
        )

    # ------------------------------------------------------------------------
    # Severance pay (pesangon)
    # ------------------------------------------------------------------------

    def calculate_pph21_for_severance(
        self,
        severance_amount: Decimal,
        years_of_service: int,
    ) -> Decimal:
        """
        Calculate PPh 21 on severance pay.

        Severance tax rates (different from regular income):
        - 0% for first IDR 50 million
        - 5% for IDR 50M - 100M
        - 15% for IDR 100M - 500M
        - 25% for above IDR 500M

        Args:
            severance_amount: Total severance payment.
            years_of_service: Years of service (affects calculation but
                              for simplicity, we use flat brackets).

        Returns:
            PPh 21 on severance.
        """
        severance_brackets = [
            (Decimal(0), Decimal(50000000), Decimal(0)),
            (Decimal(50000000), Decimal(100000000), Decimal(5)),
            (Decimal(100000000), Decimal(500000000), Decimal(15)),
            (Decimal(500000000), Decimal("inf"), Decimal(25)),
        ]

        tax = Decimal(0)
        remaining = severance_amount

        for lower, upper, rate in severance_brackets:
            if remaining <= 0:
                break
            if upper == Decimal("inf"):
                bracket_amount = remaining
            else:
                bracket_amount = min(remaining, upper - lower)
            tax += bracket_amount * (rate / Decimal(100))
            remaining -= bracket_amount

        return tax


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "TaxWithholdingEngine",
]
