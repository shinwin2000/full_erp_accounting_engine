#!/usr/bin/env python3
"""
Module: impairment_tester.py
Layer: Domain / Goodwill
Responsibility: Goodwill impairment testing logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class ImpairmentTestError(ValueError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class ImpairmentTestResult:
    is_impaired: bool
    impairment_loss: Decimal
    recoverable_amount: Decimal
    carrying_amount: Decimal
    cgu_code: str | None = None

    @property
    def impairment_percentage(self) -> float:
        if self.carrying_amount == 0:
            return 0.0
        return float(self.impairment_loss / self.carrying_amount * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_impaired": self.is_impaired,
            "impairment_loss": str(self.impairment_loss),
            "recoverable_amount": str(self.recoverable_amount),
            "carrying_amount": str(self.carrying_amount),
            "cgu_code": self.cgu_code,
            "impairment_percentage": self.impairment_percentage,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImpairmentTestResult:
        return cls(
            is_impaired=data["is_impaired"],
            impairment_loss=Decimal(data["impairment_loss"]),
            recoverable_amount=Decimal(data["recoverable_amount"]),
            carrying_amount=Decimal(data["carrying_amount"]),
            cgu_code=data.get("cgu_code"),
        )


@dataclass(frozen=True)
class CGUAllocation:
    cgu_code: str
    allocated_goodwill: Decimal
    recoverable_amount: Decimal | None = None
    impairment_loss: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "cgu_code": self.cgu_code,
            "allocated_goodwill": str(self.allocated_goodwill),
            "recoverable_amount": str(self.recoverable_amount) if self.recoverable_amount else None,
            "impairment_loss": str(self.impairment_loss) if self.impairment_loss else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CGUAllocation:
        return cls(
            cgu_code=data["cgu_code"],
            allocated_goodwill=Decimal(data["allocated_goodwill"]),
            recoverable_amount=Decimal(data["recoverable_amount"])
            if data.get("recoverable_amount")
            else None,
            impairment_loss=Decimal(data["impairment_loss"])
            if data.get("impairment_loss")
            else None,
        )


# ============================================================================
# GoodwillImpairmentTester
# ============================================================================


class GoodwillImpairmentTester:
    """Performs impairment calculations for goodwill (PSAK 48 / IAS 36)."""

    def __init__(self):
        self._test_history: list[ImpairmentTestResult] = []

    def calculate_impairment_loss(
        self, carrying_amount: Decimal, recoverable_amount: Decimal
    ) -> tuple[Decimal, bool]:
        """
        Calculate impairment loss if recoverable amount < carrying amount.

        Args:
            carrying_amount: Current carrying amount (NBV)
            recoverable_amount: Recoverable amount (higher of FVLCS and VIU)

        Returns:
            (impairment_loss, is_impaired)
        """
        carrying = carrying_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        recoverable = recoverable_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

        if recoverable < carrying:
            loss = (carrying - recoverable).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            return loss, True
        return Decimal("0"), False

    def test_impairment(
        self,
        carrying_amount: Decimal,
        recoverable_amount: Decimal,
        cgu_code: str | None = None,
    ) -> ImpairmentTestResult:
        """Test impairment for a single CGU or total goodwill."""
        loss, is_impaired = self.calculate_impairment_loss(carrying_amount, recoverable_amount)
        result = ImpairmentTestResult(
            is_impaired=is_impaired,
            impairment_loss=loss,
            recoverable_amount=recoverable_amount,
            carrying_amount=carrying_amount,
            cgu_code=cgu_code,
        )
        self._test_history.append(result)
        return result

    def allocate_impairment_to_cgus(
        self,
        total_impairment: Decimal,
        cgu_allocations: list[tuple[str, Decimal]],
        tolerance: Decimal = Decimal("0.01"),
    ) -> dict[str, Decimal]:
        """
        Allocate impairment loss across CGUs on a pro-rata basis (IAS 36).

        Args:
            total_impairment: Total impairment loss to allocate
            cgu_allocations: List of (cgu_code, allocated_goodwill)
            tolerance: Tolerance for rounding adjustment

        Returns:
            Dictionary mapping cgu_code -> allocated impairment
        """
        total_allocated = sum(amt for _, amt in cgu_allocations)
        if total_allocated == 0:
            return {}

        result = {}
        remaining = total_impairment

        for cgu_code, allocated in cgu_allocations:
            portion = (allocated / total_allocated) * total_impairment
            result[cgu_code] = portion.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            remaining -= result[cgu_code]

        # Adjust for rounding (add remainder to first CGU)
        if abs(remaining) > tolerance and result:
            first_key = next(iter(result))
            result[first_key] += remaining
            result[first_key] = result[first_key].quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )

        return result

    def test_impairment_for_cgus(
        self,
        cgus: list[CGUAllocation],
    ) -> tuple[Decimal, dict[str, Decimal]]:
        """
        Test impairment for multiple CGUs and allocate total impairment.

        Args:
            cgus: List of CGUAllocation objects

        Returns:
            (total_impairment, allocation_map)
        """
        total_impairment = Decimal("0")
        allocations = []

        for cgu in cgus:
            if cgu.recoverable_amount is None:
                continue
            loss, is_impaired = self.calculate_impairment_loss(
                cgu.allocated_goodwill, cgu.recoverable_amount
            )
            if is_impaired:
                total_impairment += loss
                allocations.append((cgu.cgu_code, cgu.allocated_goodwill))

        if total_impairment == 0:
            return Decimal("0"), {}

        allocation_map = self.allocate_impairment_to_cgus(total_impairment, allocations)
        return total_impairment, allocation_map

    def get_test_history(self, limit: int = 50) -> list[ImpairmentTestResult]:
        """Get test history."""
        return self._test_history[-limit:]

    def get_last_test(self) -> ImpairmentTestResult | None:
        """Get the most recent test result."""
        return self._test_history[-1] if self._test_history else None

    def clear_history(self) -> None:
        """Clear test history."""
        self._test_history = []

    def calculate_remaining_impairment_capacity(
        self, carrying_amount: Decimal, impairment_loss_total: Decimal, amount: Decimal
    ) -> Decimal:
        """Calculate remaining impairment capacity."""
        return min(amount, carrying_amount)

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics."""
        total_tests = len(self._test_history)
        impaired_count = len([t for t in self._test_history if t.is_impaired])
        total_impairment = sum(t.impairment_loss for t in self._test_history)

        return {
            "total_tests": total_tests,
            "impaired_count": impaired_count,
            "no_impairment_count": total_tests - impaired_count,
            "total_impairment_loss": str(total_impairment),
            "avg_impairment": str(total_impairment / total_tests) if total_tests > 0 else "0",
        }


__all__ = [
    "CGUAllocation",
    "GoodwillImpairmentTester",
    "ImpairmentTestError",
    "ImpairmentTestResult",
]
