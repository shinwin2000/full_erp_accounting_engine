#!/usr/bin/env python3
"""
Module: impairment_tester.py

Layer: Domain / Fixed Asset

Responsibility:
    Engine for asset impairment testing (PSAK 48 / IAS 36).

    Provides functionality to identify impairment indicators, calculate
    recoverable amount (fair value less costs to sell and value in use),
    recognize impairment losses, and track impairment test history.

Business rules:
    - Impairment exists when carrying amount > recoverable amount.
    - Recoverable amount = max(FVLCS, VIU).
    - FVLCS = fair value - selling costs.
    - VIU = present value of future cash flows.
    - Impairment loss = carrying amount - recoverable amount.
    - Impairment loss reduces net book value and increases accumulated impairment.
    - Impairment reversal is allowed under certain conditions (PSAK 48 permits).
    - Each impairment test is recorded with indicators and results.

Dependencies:
    - Python standard library (decimal, datetime, logging, uuid)
    - domain.fixed_asset.asset_entity (FixedAsset) for TYPE_CHECKING

Audit:
    Every impairment test should be logged; results recorded for audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from domain.fixed_asset.asset_entity import FixedAsset

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class ImpairmentTestResult(Enum):
    """Result of impairment test."""

    NO_IMPAIRMENT = "no_impairment"  # Tidak ada penurunan nilai
    IMPAIRED = "impaired"  # Mengalami penurunan nilai
    REVERSAL = "reversal"  # Pembalikan penurunan nilai

    def display_name(self) -> str:
        names = {
            ImpairmentTestResult.NO_IMPAIRMENT: "Tidak Ada Penurunan Nilai",
            ImpairmentTestResult.IMPAIRED: "Mengalami Penurunan Nilai",
            ImpairmentTestResult.REVERSAL: "Pembalikan Penurunan Nilai",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> ImpairmentTestResult | None:
        for r in cls:
            if r.value == value.lower():
                return r
        return None


class ImpairmentIndicator(Enum):
    """Indicators of potential impairment (PSAK 48 / IAS 36)."""

    # External indicators
    MARKET_DECLINE = "market_decline"  # Penurunan nilai pasar
    ECONOMIC_DOWNTURN = "economic_downturn"  # Resesi ekonomi
    REGULATORY_CHANGE = "regulatory_change"  # Perubahan regulasi
    INTEREST_RATE_INCREASE = "interest_rate_increase"  # Kenaikan suku bunga
    TECHNOLOGY_OBSOLESCENCE = "technology_obsolescence"  # Keusangan teknologi

    # Internal indicators
    OBSOLESCENCE = "obsolescence"  # Usang
    PHYSICAL_DAMAGE = "physical_damage"  # Kerusakan fisik
    IDLE_ASSET = "idle_asset"  # Aset tidak digunakan
    POOR_PERFORMANCE = "poor_performance"  # Kinerja buruk
    CASH_FLOW_NEGATIVE = "cash_flow_negative"  # Arus kas negatif
    DISPOSAL_PLAN = "disposal_plan"  # Rencana pelepasan
    RESTRUCTURING = "restructuring"  # Restrukturisasi

    def display_name(self) -> str:
        names = {
            ImpairmentIndicator.MARKET_DECLINE: "Penurunan Nilai Pasar",
            ImpairmentIndicator.ECONOMIC_DOWNTURN: "Resesi Ekonomi",
            ImpairmentIndicator.REGULATORY_CHANGE: "Perubahan Regulasi",
            ImpairmentIndicator.INTEREST_RATE_INCREASE: "Kenaikan Suku Bunga",
            ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE: "Keusangan Teknologi",
            ImpairmentIndicator.OBSOLESCENCE: "Usang",
            ImpairmentIndicator.PHYSICAL_DAMAGE: "Kerusakan Fisik",
            ImpairmentIndicator.IDLE_ASSET: "Tidak Digunakan",
            ImpairmentIndicator.POOR_PERFORMANCE: "Kinerja Buruk",
            ImpairmentIndicator.CASH_FLOW_NEGATIVE: "Arus Kas Negatif",
            ImpairmentIndicator.DISPOSAL_PLAN: "Rencana Pelepasan",
            ImpairmentIndicator.RESTRUCTURING: "Restrukturisasi",
        }
        return names.get(self, self.value)

    def is_external(self) -> bool:
        """Check if indicator is external."""
        external = {
            ImpairmentIndicator.MARKET_DECLINE,
            ImpairmentIndicator.ECONOMIC_DOWNTURN,
            ImpairmentIndicator.REGULATORY_CHANGE,
            ImpairmentIndicator.INTEREST_RATE_INCREASE,
            ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE,
        }
        return self in external

    def is_internal(self) -> bool:
        """Check if indicator is internal."""
        return not self.is_external()

    @classmethod
    def from_string(cls, value: str) -> ImpairmentIndicator | None:
        for i in cls:
            if i.value == value.lower():
                return i
        return None


class ImpairmentTestMethod(Enum):
    """Method used to determine recoverable amount."""

    FAIR_VALUE_LESS_COSTS = "fvlcs"  # Fair value less costs to sell
    VALUE_IN_USE = "viu"  # Value in use (DCF)
    MARKET_APPROACH = "market"  # Market approach
    INCOME_APPROACH = "income"  # Income approach
    COST_APPROACH = "cost"  # Cost approach

    def display_name(self) -> str:
        names = {
            ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS: "Nilai Wajar - Biaya Jual",
            ImpairmentTestMethod.VALUE_IN_USE: "Nilai Pakai",
            ImpairmentTestMethod.MARKET_APPROACH: "Pendekatan Pasar",
            ImpairmentTestMethod.INCOME_APPROACH: "Pendekatan Pendapatan",
            ImpairmentTestMethod.COST_APPROACH: "Pendekatan Biaya",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> ImpairmentTestMethod | None:
        for m in cls:
            if m.value == value.lower():
                return m
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class ImpairmentTestError(ValueError):
    """Base exception for impairment test errors."""

    pass


class InvalidRecoverableAmountError(ImpairmentTestError):
    """Raised when recoverable amount is invalid."""

    pass


class ImpairmentTestNotFoundError(ImpairmentTestError):
    """Raised when test not found in history."""

    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class ImpairmentTest:
    """
    Immutable record of an impairment test.

    Attributes:
        test_id: Unique identifier
        asset_id: Asset being tested
        asset_code: Asset code
        asset_name: Asset name
        test_date: Date of test
        carrying_amount: Carrying amount (NBV) before test
        recoverable_amount: Recoverable amount (higher of FVLCS and VIU)
        impairment_loss: Recognized impairment loss (positive)
        previous_impairment_loss: Impairment loss from previous test
        reversal_amount: Reversal amount (if impairment reversed)
        result: Test result (NO_IMPAIRMENT, IMPAIRED, REVERSAL)
        indicators: List of impairment indicators present
        method: Method used to determine recoverable amount
        assumptions: Key assumptions used (e.g., discount rate, growth rate)
        notes: Additional notes
        tested_by: User who performed the test
        created_at: Timestamp
    """

    test_id: UUID
    asset_id: UUID
    asset_code: str
    asset_name: str
    test_date: date
    carrying_amount: Decimal
    recoverable_amount: Decimal
    impairment_loss: Decimal
    previous_impairment_loss: Decimal
    reversal_amount: Decimal
    result: ImpairmentTestResult
    indicators: list[ImpairmentIndicator]
    method: ImpairmentTestMethod
    assumptions: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    tested_by: str = "system"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Validate impairment test data."""
        if self.carrying_amount < 0:
            raise ImpairmentTestError("Carrying amount cannot be negative")
        if self.recoverable_amount < 0:
            raise ImpairmentTestError("Recoverable amount cannot be negative")
        if self.impairment_loss < 0:
            raise ImpairmentTestError("Impairment loss cannot be negative")
        if self.reversal_amount < 0:
            raise ImpairmentTestError("Reversal amount cannot be negative")
        if self.impairment_loss > self.carrying_amount:
            raise ImpairmentTestError("Impairment loss cannot exceed carrying amount")
        if self.test_date > date.today():
            raise ImpairmentTestError("Test date cannot be in the future")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": str(self.test_id),
            "asset_id": str(self.asset_id),
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "test_date": self.test_date.isoformat(),
            "carrying_amount": str(self.carrying_amount),
            "recoverable_amount": str(self.recoverable_amount),
            "impairment_loss": str(self.impairment_loss),
            "previous_impairment_loss": str(self.previous_impairment_loss),
            "reversal_amount": str(self.reversal_amount),
            "result": self.result.value,
            "result_display": self.result.display_name(),
            "indicators": [i.value for i in self.indicators],
            "method": self.method.value,
            "method_display": self.method.display_name(),
            "assumptions": self.assumptions,
            "notes": self.notes,
            "tested_by": self.tested_by,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ImpairmentTest:
        result = ImpairmentTestResult.from_string(data["result"])
        if result is None:
            raise ImpairmentTestError(f"Invalid result: {data['result']}")
        method = ImpairmentTestMethod.from_string(data["method"])
        if method is None:
            raise ImpairmentTestError(f"Invalid method: {data['method']}")
        indicators = []
        for i_str in data.get("indicators", []):
            ind = ImpairmentIndicator.from_string(i_str)
            if ind:
                indicators.append(ind)
        return cls(
            test_id=UUID(data["test_id"]) if isinstance(data["test_id"], str) else data["test_id"],
            asset_id=UUID(data["asset_id"])
            if isinstance(data["asset_id"], str)
            else data["asset_id"],
            asset_code=data["asset_code"],
            asset_name=data["asset_name"],
            test_date=date.fromisoformat(data["test_date"]),
            carrying_amount=Decimal(str(data["carrying_amount"])),
            recoverable_amount=Decimal(str(data["recoverable_amount"])),
            impairment_loss=Decimal(str(data["impairment_loss"])),
            previous_impairment_loss=Decimal(str(data.get("previous_impairment_loss", 0))),
            reversal_amount=Decimal(str(data.get("reversal_amount", 0))),
            result=result,
            indicators=indicators,
            method=method,
            assumptions=data.get("assumptions", {}),
            notes=data.get("notes", ""),
            tested_by=data.get("tested_by", "system"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================================
# ImpairmentTester Engine
# ============================================================================


class ImpairmentTester:
    """
    Engine for testing asset impairment.

    Usage:
        tester = ImpairmentTester()
        indicators = tester.identify_indicators(asset, market_price=1000000)
        recoverable = tester.calculate_recoverable_amount(asset, fvlcs=900000, discount_rate=0.1)
        test = tester.test_impairment(asset, recoverable_amount=recoverable, indicators=indicators)
        if test.result == ImpairmentTestResult.IMPAIRED:
            asset = asset.recognize_impairment(test.impairment_loss, tested_by, indicators)
    """

    def __init__(self):
        self._test_history: list[ImpairmentTest] = []
        self._default_discount_rate = Decimal("0.10")  # 10% default

    # ------------------------------------------------------------------------
    # Indicator Identification
    # ------------------------------------------------------------------------

    def identify_indicators(
        self,
        asset: FixedAsset,
        market_price: Decimal | None = None,
        is_idle: bool = False,
        physical_damage: bool = False,
        poor_performance: bool = False,
        cash_flow_negative: bool = False,
        disposal_planned: bool = False,
        economic_downturn: bool = False,
        regulatory_change: bool = False,
        technology_obsolescence: bool = False,
    ) -> list[ImpairmentIndicator]:
        """
        Identify impairment indicators present for the asset.

        Args:
            asset: Fixed asset being tested
            market_price: Current market price (if available)
            is_idle: Whether asset is idle
            physical_damage: Whether asset has physical damage
            poor_performance: Whether asset shows poor operational performance
            cash_flow_negative: Whether cash flows are negative
            disposal_planned: Whether disposal is planned
            economic_downturn: Whether economic downturn affects the asset
            regulatory_change: Whether regulatory change affects the asset
            technology_obsolescence: Whether technology is becoming obsolete

        Returns:
            List of impairment indicators
        """
        indicators = []

        # External indicators
        if economic_downturn:
            indicators.append(ImpairmentIndicator.ECONOMIC_DOWNTURN)
        if regulatory_change:
            indicators.append(ImpairmentIndicator.REGULATORY_CHANGE)
        if technology_obsolescence:
            indicators.append(ImpairmentIndicator.TECHNOLOGY_OBSOLESCENCE)

        # Market decline
        if market_price is not None and market_price < asset.net_book_value:
            indicators.append(ImpairmentIndicator.MARKET_DECLINE)

        # Internal indicators
        if is_idle or asset.status == AssetStatus.IDLE:
            indicators.append(ImpairmentIndicator.IDLE_ASSET)
        if physical_damage:
            indicators.append(ImpairmentIndicator.PHYSICAL_DAMAGE)
        if poor_performance:
            indicators.append(ImpairmentIndicator.POOR_PERFORMANCE)
        if cash_flow_negative:
            indicators.append(ImpairmentIndicator.CASH_FLOW_NEGATIVE)
        if disposal_planned:
            indicators.append(ImpairmentIndicator.DISPOSAL_PLAN)

        # Obsolescence check: asset fully depreciated but still in use? Or technology obsolete
        if asset.is_fully_depreciated and asset.status == AssetStatus.ACTIVE:
            indicators.append(ImpairmentIndicator.OBSOLESCENCE)

        return indicators

    # ------------------------------------------------------------------------
    # Recoverable Amount Calculation
    # ------------------------------------------------------------------------

    def calculate_fair_value_less_costs_to_sell(
        self,
        asset: FixedAsset,
        fair_value: Decimal | None = None,
        selling_costs: Decimal = Decimal("0"),
    ) -> Decimal:
        """
        Calculate Fair Value Less Costs to Sell (FVLCS).

        Args:
            asset: Fixed asset
            fair_value: Fair value (market price). If None, uses NBV as proxy.
            selling_costs: Costs to sell (e.g., commission, legal fees)

        Returns:
            FVLCS as Decimal
        """
        if fair_value is None:
            # Fallback: use net book value as proxy
            fair_value = asset.net_book_value
        if not isinstance(fair_value, Decimal):
            fair_value = Decimal(str(fair_value))
        if not isinstance(selling_costs, Decimal):
            selling_costs = Decimal(str(selling_costs))
        if selling_costs < 0:
            raise InvalidRecoverableAmountError("Selling costs cannot be negative")
        result = fair_value - selling_costs
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_value_in_use(
        self,
        asset: FixedAsset,
        projected_cash_flows: list[Decimal],
        discount_rate: Decimal | None = None,
        growth_rate: Decimal = Decimal("0"),
        terminal_value: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate Value in Use (VIU) using discounted cash flow.

        Args:
            asset: Fixed asset
            projected_cash_flows: List of projected annual cash flows
            discount_rate: Discount rate (e.g., 0.10 for 10%). Default 10%.
            growth_rate: Perpetual growth rate for terminal value
            terminal_value: Optional terminal value (if not provided, calculated)

        Returns:
            Present value as Decimal
        """
        if discount_rate is None:
            discount_rate = self._default_discount_rate
        if not isinstance(discount_rate, Decimal):
            discount_rate = Decimal(str(discount_rate))
        if discount_rate < 0 or discount_rate > 1:
            raise InvalidRecoverableAmountError(
                f"Discount rate must be between 0 and 1, got {discount_rate}"
            )

        if not projected_cash_flows:
            # No projections, use asset's net cash flow estimate
            # Simplified: use annual depreciation + net income proxy
            return asset.net_book_value

        present_value = Decimal("0")
        for i, cf in enumerate(projected_cash_flows):
            year = i + 1
            discount_factor = Decimal(1) / ((Decimal(1) + discount_rate) ** year)
            present_value += cf * discount_factor

        # Add terminal value
        if terminal_value is not None:
            terminal_discount = Decimal(1) / (
                (Decimal(1) + discount_rate) ** len(projected_cash_flows)
            )
            present_value += terminal_value * terminal_discount
        elif growth_rate > 0 and projected_cash_flows:
            last_cf = projected_cash_flows[-1]
            terminal = last_cf * (Decimal(1) + growth_rate) / (discount_rate - growth_rate)
            terminal_discount = Decimal(1) / (
                (Decimal(1) + discount_rate) ** len(projected_cash_flows)
            )
            present_value += terminal * terminal_discount

        return present_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_recoverable_amount(
        self,
        asset: FixedAsset,
        fvlcs: Decimal | None = None,
        value_in_use: Decimal | None = None,
        fair_value: Decimal | None = None,
        selling_costs: Decimal = Decimal("0"),
        projected_cash_flows: list[Decimal] | None = None,
        discount_rate: Decimal | None = None,
    ) -> Decimal:
        """
        Calculate recoverable amount (higher of FVLCS and VIU).

        Args:
            asset: Fixed asset
            fvlcs: Pre-calculated FVLCS (if provided, used directly)
            value_in_use: Pre-calculated VIU (if provided, used directly)
            fair_value: Fair value (for FVLCS calculation)
            selling_costs: Selling costs (for FVLCS)
            projected_cash_flows: Cash flows (for VIU)
            discount_rate: Discount rate (for VIU)

        Returns:
            Recoverable amount
        """
        if fvlcs is None:
            fvlcs = self.calculate_fair_value_less_costs_to_sell(asset, fair_value, selling_costs)
        if value_in_use is None:
            if projected_cash_flows is None:
                projected_cash_flows = []
            value_in_use = self.calculate_value_in_use(asset, projected_cash_flows, discount_rate)

        recoverable = max(fvlcs, value_in_use)
        return recoverable.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ------------------------------------------------------------------------
    # Impairment Test Execution
    # ------------------------------------------------------------------------

    def test_impairment(
        self,
        asset: FixedAsset,
        recoverable_amount: Decimal | None = None,
        indicators: list[ImpairmentIndicator] | None = None,
        method: ImpairmentTestMethod = ImpairmentTestMethod.FAIR_VALUE_LESS_COSTS,
        assumptions: dict[str, Any] | None = None,
        notes: str = "",
        tested_by: str = "system",
        test_date: date | None = None,
    ) -> ImpairmentTest:
        """
        Perform impairment test on an asset.

        Args:
            asset: Fixed asset
            recoverable_amount: Pre-calculated recoverable amount (if None, calculates)
            indicators: List of indicators (if None, identifies)
            method: Method used to determine recoverable amount
            assumptions: Key assumptions (discount rate, growth rate, etc.)
            notes: Additional notes
            tested_by: User performing the test
            test_date: Date of test (defaults to today)

        Returns:
            ImpairmentTest record
        """
        if test_date is None:
            test_date = date.today()
        if indicators is None:
            indicators = self.identify_indicators(asset)
        if recoverable_amount is None:
            recoverable_amount = self.calculate_recoverable_amount(asset)
        if assumptions is None:
            assumptions = {}

        carrying = asset.net_book_value
        previous_impairment = asset.accumulated_impairment

        # Calculate impairment loss
        if carrying > recoverable_amount:
            impairment_loss = carrying - recoverable_amount
            result = ImpairmentTestResult.IMPAIRED
            reversal_amount = Decimal("0")
        elif carrying < recoverable_amount and previous_impairment > 0:
            # Possible reversal
            impairment_loss = Decimal("0")
            reversal_amount = min(previous_impairment, recoverable_amount - carrying)
            result = (
                ImpairmentTestResult.REVERSAL
                if reversal_amount > 0
                else ImpairmentTestResult.NO_IMPAIRMENT
            )
        else:
            impairment_loss = Decimal("0")
            reversal_amount = Decimal("0")
            result = ImpairmentTestResult.NO_IMPAIRMENT

        test = ImpairmentTest(
            test_id=uuid4(),
            asset_id=asset.id,
            asset_code=asset.asset_code,
            asset_name=asset.name,
            test_date=test_date,
            carrying_amount=carrying,
            recoverable_amount=recoverable_amount,
            impairment_loss=impairment_loss,
            previous_impairment_loss=previous_impairment,
            reversal_amount=reversal_amount,
            result=result,
            indicators=indicators,
            method=method,
            assumptions=assumptions,
            notes=notes,
            tested_by=tested_by,
        )

        self._test_history.append(test)
        logger.info(
            f"Impairment test for {asset.asset_code}: result={result.value}, "
            f"carrying={carrying}, recoverable={recoverable_amount}, loss={impairment_loss}"
        )
        return test

    def test_cash_generating_unit(
        self,
        assets: list[FixedAsset],
        cgu_name: str,
        recoverable_amount_cgu: Decimal,
        indicators: list[ImpairmentIndicator] | None = None,
        method: ImpairmentTestMethod = ImpairmentTestMethod.VALUE_IN_USE,
        assumptions: dict[str, Any] | None = None,
        tested_by: str = "system",
    ) -> list[ImpairmentTest]:
        """
        Test impairment for a Cash Generating Unit (CGU).
        Allocates impairment loss proportionally to assets in the CGU.

        Args:
            assets: List of assets in the CGU
            cgu_name: Name of the CGU
            recoverable_amount_cgu: Recoverable amount of the CGU
            indicators: Indicators (applied to all assets)
            method: Method used
            assumptions: Assumptions
            tested_by: User

        Returns:
            List of ImpairmentTest records for each asset
        """
        if not assets:
            return []
        total_carrying = sum(a.net_book_value for a in assets)
        if total_carrying <= recoverable_amount_cgu:
            # No impairment
            tests = []
            for asset in assets:
                test = self.test_impairment(
                    asset,
                    recoverable_amount=asset.net_book_value,
                    indicators=indicators,
                    method=method,
                    assumptions=assumptions,
                    notes=f"Part of CGU '{cgu_name}' - no impairment",
                    tested_by=tested_by,
                )
                tests.append(test)
            return tests

        # Impairment exists
        total_impairment = total_carrying - recoverable_amount_cgu
        tests = []
        remaining_impairment = total_impairment

        # Allocate impairment proportionally to NBV
        for asset in assets:
            if asset.net_book_value == 0:
                continue
            proportion = asset.net_book_value / total_carrying
            allocated_impairment = total_impairment * proportion
            allocated_impairment = allocated_impairment.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_EVEN
            )

            recoverable = asset.net_book_value - allocated_impairment
            if recoverable < 0:
                recoverable = Decimal("0")
                allocated_impairment = asset.net_book_value

            test = self.test_impairment(
                asset,
                recoverable_amount=recoverable,
                indicators=indicators,
                method=method,
                assumptions=assumptions,
                notes=f"Part of CGU '{cgu_name}' - impairment allocation",
                tested_by=tested_by,
            )
            tests.append(test)
            remaining_impairment -= allocated_impairment

        # Adjust for rounding
        if remaining_impairment > 0:
            # Add to the asset with largest NBV
            max_asset_idx = max(range(len(assets)), key=lambda i: assets[i].net_book_value)
            tests[max_asset_idx] = self.test_impairment(
                assets[max_asset_idx],
                recoverable_amount=assets[max_asset_idx].net_book_value - remaining_impairment,
                indicators=indicators,
                method=method,
                assumptions=assumptions,
                notes=f"Part of CGU '{cgu_name}' - rounding adjustment",
                tested_by=tested_by,
            )

        return tests

    # ------------------------------------------------------------------------
    # History Management
    # ------------------------------------------------------------------------

    def get_test_history(
        self, asset_id: UUID | None = None, limit: int = 50
    ) -> list[ImpairmentTest]:
        """Get impairment test history."""
        if asset_id:
            filtered = [t for t in self._test_history if t.asset_id == asset_id]
            return filtered[-limit:]
        return self._test_history[-limit:]

    def get_latest_test(self, asset_id: UUID) -> ImpairmentTest | None:
        """Get the most recent impairment test for an asset."""
        tests = self.get_test_history(asset_id, limit=1)
        return tests[0] if tests else None

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics of impairment tests."""
        total_tests = len(self._test_history)
        impaired_count = len(
            [t for t in self._test_history if t.result == ImpairmentTestResult.IMPAIRED]
        )
        reversal_count = len(
            [t for t in self._test_history if t.result == ImpairmentTestResult.REVERSAL]
        )
        total_impairment = sum(t.impairment_loss for t in self._test_history)
        total_reversal = sum(t.reversal_amount for t in self._test_history)

        return {
            "total_tests": total_tests,
            "impaired_count": impaired_count,
            "reversal_count": reversal_count,
            "no_impairment_count": total_tests - impaired_count - reversal_count,
            "total_impairment_loss": str(total_impairment),
            "total_reversal_amount": str(total_reversal),
            "net_impairment": str(total_impairment - total_reversal),
        }

    def clear_history(self) -> None:
        """Clear test history (for testing)."""
        self._test_history = []


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_present_value(
    future_amount: Decimal,
    discount_rate: Decimal,
    years: int,
) -> Decimal:
    """Calculate present value of a future amount."""
    factor = Decimal(1) / ((Decimal(1) + discount_rate) ** years)
    return (future_amount * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def calculate_impairment_percentage(
    carrying_amount: Decimal,
    recoverable_amount: Decimal,
) -> Decimal:
    """Calculate impairment as percentage of carrying amount."""
    if carrying_amount == 0:
        return Decimal("0")
    loss = max(Decimal("0"), carrying_amount - recoverable_amount)
    return (loss / carrying_amount * Decimal("100")).quantize(Decimal("0.01"))


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ImpairmentIndicator",
    "ImpairmentTest",
    "ImpairmentTestError",
    "ImpairmentTestMethod",
    "ImpairmentTestNotFoundError",
    "ImpairmentTestResult",
    "ImpairmentTester",
    "InvalidRecoverableAmountError",
    "calculate_impairment_percentage",
    "calculate_present_value",
]
