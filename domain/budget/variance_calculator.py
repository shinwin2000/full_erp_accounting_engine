#!/usr/bin/env python3
"""
Module: variance_calculator.py
Layer: Domain / Budget
Responsibility: Variance calculation for budget vs actual dengan berbagai metode.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any


class VarianceType:
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"


@dataclass
class VarianceResult:
    """Result of variance calculation."""

    amount: Decimal
    amount_absolute: Decimal
    percentage: float
    variance_type: str
    budget_amount: Decimal
    actual_amount: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "amount_absolute": str(self.amount_absolute),
            "percentage": self.percentage,
            "variance_type": self.variance_type,
            "budget_amount": str(self.budget_amount),
            "actual_amount": str(self.actual_amount),
        }


class VarianceCalculator:
    """
    Calculate variances between budget and actual amounts.
    Supports expense, revenue, and custom account type determination.
    """

    def __init__(self, is_revenue_account_func: Callable[[str], bool] | None = None):
        """
        Initialize calculator.

        Args:
            is_revenue_account_func: Function that takes account_code and returns True if revenue account.
                                     Default: account code starting with '4' is revenue.
        """
        self._is_revenue_func = is_revenue_account_func or self._default_is_revenue

    @staticmethod
    def _default_is_revenue(account_code: str) -> bool:
        """Default: account codes starting with '4' are revenue accounts."""
        return account_code.startswith("4") if account_code else False

    def calculate(
        self,
        budget_amount: Decimal,
        actual_amount: Decimal,
        account_code: str = "",
    ) -> VarianceResult:
        """
        Calculate variance and determine if favorable/unfavorable.

        For expense accounts: actual < budget = favorable
        For revenue accounts: actual > budget = favorable
        """
        budget_amount = budget_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        actual_amount = actual_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        variance = actual_amount - budget_amount
        variance_abs = abs(variance)

        is_revenue = self._is_revenue_func(account_code)

        if is_revenue:
            is_favorable = variance > 0
        else:
            is_favorable = variance < 0

        variance_type = VarianceType.FAVORABLE if is_favorable else VarianceType.UNFAVORABLE
        percentage = self.percentage_variance(budget_amount, actual_amount)

        return VarianceResult(
            amount=variance,
            amount_absolute=variance_abs,
            percentage=percentage,
            variance_type=variance_type,
            budget_amount=budget_amount,
            actual_amount=actual_amount,
        )

    @staticmethod
    def percentage_variance(budget_amount: Decimal, actual_amount: Decimal) -> float:
        """Calculate percentage variance (absolute)."""
        if budget_amount == 0:
            if actual_amount == 0:
                return 0.0
            return 100.0
        return float(abs((actual_amount - budget_amount) / budget_amount * 100))

    @staticmethod
    def favorable_percentage(
        budget_amount: Decimal, actual_amount: Decimal, is_revenue: bool
    ) -> float:
        """
        Calculate percentage with sign indicating favorable (positive %) or unfavorable (negative %).
        For expense: favorable = actual < budget -> positive % (savings)
        For revenue: favorable = actual > budget -> positive % (excess)
        """
        if budget_amount == 0:
            return 0.0
        variance_pct = (actual_amount - budget_amount) / budget_amount * 100
        if is_revenue:
            # For revenue, positive variance is favorable
            return float(variance_pct)
        else:
            # For expense, negative variance is favorable (savings)
            return float(-variance_pct)

    def calculate_for_lines(
        self,
        lines: list[Any],  # List of objects with budget_amount, actual_amount, account_code
        budget_amount_attr: str = "amount",
        actual_amount_attr: str = "actual_amount",
        account_code_attr: str = "account_code",
    ) -> list[VarianceResult]:
        """Calculate variance for multiple budget lines."""
        results = []
        for line in lines:
            budget = getattr(line, budget_amount_attr, Decimal(0))
            actual = getattr(line, actual_amount_attr, Decimal(0))
            account_code = getattr(line, account_code_attr, "")
            results.append(self.calculate(budget, actual, account_code))
        return results

    def calculate_total_variance(
        self,
        total_budget: Decimal,
        total_actual: Decimal,
    ) -> VarianceResult:
        """Calculate total variance for entire budget."""
        return self.calculate(total_budget, total_actual, account_code="")

    def calculate_spending_variance(
        self,
        budget_amount: Decimal,
        actual_amount: Decimal,
    ) -> Decimal:
        """Simple spending variance (actual - budget)."""
        return (actual_amount - budget_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_efficiency_variance(
        self,
        budget_quantity: Decimal,
        actual_quantity: Decimal,
        standard_price: Decimal,
    ) -> Decimal:
        """Efficiency variance = (actual quantity - budget quantity) * standard price."""
        return ((actual_quantity - budget_quantity) * standard_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def calculate_price_variance(
        self,
        actual_quantity: Decimal,
        budget_price: Decimal,
        actual_price: Decimal,
    ) -> Decimal:
        """Price variance = actual quantity * (actual price - budget price)."""
        return (actual_quantity * (actual_price - budget_price)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def calculate_volume_variance(
        self,
        budget_quantity: Decimal,
        actual_quantity: Decimal,
        budget_price: Decimal,
    ) -> Decimal:
        """Volume variance = (actual quantity - budget quantity) * budget price."""
        return ((actual_quantity - budget_quantity) * budget_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def calculate_mix_variance(
        self,
        actual_quantity: Decimal,
        actual_mix_ratio: float,
        budget_mix_ratio: float,
        budget_price: Decimal,
    ) -> Decimal:
        """Mix variance = actual quantity * (actual mix - budget mix) * budget price."""
        return (
            actual_quantity * Decimal(str(actual_mix_ratio - budget_mix_ratio)) * budget_price
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_yield_variance(
        self,
        actual_quantity: Decimal,
        actual_yield_ratio: float,
        budget_yield_ratio: float,
        budget_price: Decimal,
    ) -> Decimal:
        """Yield variance = actual quantity * (actual yield - budget yield) * budget price."""
        return (
            actual_quantity * Decimal(str(actual_yield_ratio - budget_yield_ratio)) * budget_price
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_analysis_summary(
        self,
        budget_amount: Decimal,
        actual_amount: Decimal,
        account_code: str = "",
    ) -> dict[str, Any]:
        """Get comprehensive variance analysis summary."""
        result = self.calculate(budget_amount, actual_amount, account_code)
        return {
            "budget": str(budget_amount),
            "actual": str(actual_amount),
            "variance": str(result.amount),
            "variance_absolute": str(result.amount_absolute),
            "variance_percentage": result.percentage,
            "variance_type": result.variance_type,
            "is_favorable": result.variance_type == VarianceType.FAVORABLE,
        }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "VarianceCalculator",
    "VarianceResult",
    "VarianceType",
]
