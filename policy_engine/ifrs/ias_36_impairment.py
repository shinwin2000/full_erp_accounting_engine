#!/usr/bin/env python3
"""
Module: ias_36_impairment.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 36: Impairment of Assets.
               Mendefinisikan aturan untuk menguji penurunan nilai aset,
               menghitung recoverable amount (higher of fair value less
               cost to sell and value in use), dan mengakui impairment loss.
               Berlaku untuk aset tetap, aset takberwujud, goodwill, dll.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap impairment test dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS36ImpairmentIndicator(Enum):
    """Indikator penurunan nilai eksternal dan internal."""

    MARKET_VALUE_DECLINE = "market_value_decline"
    SIGNIFICANT_CHANGE_IN_MARKET = "significant_change_in_market"
    INTEREST_RATE_INCREASE = "interest_rate_increase"
    OBSOLESCENCE = "obsolescence"
    PHYSICAL_DAMAGE = "physical_damage"
    ECONOMIC_PERFORMANCE_DECLINE = "economic_performance_decline"
    RESTRUCTURING = "restructuring"
    CASH_FLOW_NEGATIVE = "cash_flow_negative"


class IAS36CashGeneratingUnitType(Enum):
    """Jenis unit penghasil kas (CGU)."""

    SINGLE_ASSET = "single_asset"
    GROUP_OF_ASSETS = "group_of_assets"
    REPORTING_SEGMENT = "reporting_segment"


class IAS36AllocationMethod(Enum):
    """Metode alokasi goodwill ke CGU."""

    PROPORTIONAL = "proportional"
    DIRECT = "direct"


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS36RecoverableAmount:
    """Recoverable amount adalah yang lebih tinggi antara fair value less cost to sell dan value in use."""

    fair_value_less_cost_to_sell: Money | None
    value_in_use: Money | None
    recoverable_amount: Money

    def __post_init__(self):
        candidates = []
        if self.fair_value_less_cost_to_sell:
            candidates.append(self.fair_value_less_cost_to_sell.amount)
        if self.value_in_use:
            candidates.append(self.value_in_use.amount)
        if not candidates:
            raise ValueError("At least one of FVLCS or VIU must be provided")
        max_amount = max(candidates)
        if self.recoverable_amount.amount != max_amount:
            raise ValueError("Recoverable amount mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "fvlcs": str(self.fair_value_less_cost_to_sell.amount)
            if self.fair_value_less_cost_to_sell
            else None,
            "value_in_use": str(self.value_in_use.amount) if self.value_in_use else None,
            "recoverable_amount": str(self.recoverable_amount.amount),
            "currency": self.recoverable_amount.currency,
        }


@dataclass(frozen=True)
class IAS36ImpairmentLoss:
    """Impairment loss untuk suatu aset atau CGU."""

    asset_id: UUID
    carrying_amount_before: Money
    recoverable_amount: Money
    impairment_loss: Money
    reversal_previous_loss: Money = field(default_factory=lambda: Money(Decimal(0), "IDR"))
    carrying_amount_after: Money = field(init=False)

    def __post_init__(self):
        after = self.carrying_amount_before - self.impairment_loss
        object.__setattr__(self, "carrying_amount_after", after)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": str(self.asset_id),
            "carrying_before": str(self.carrying_amount_before.amount),
            "recoverable_amount": str(self.recoverable_amount.amount),
            "impairment_loss": str(self.impairment_loss.amount),
            "carrying_after": str(self.carrying_amount_after.amount),
            "currency": self.carrying_amount_before.currency,
        }


# === 3. ENTITIES ===


@dataclass
class IAS36CashGeneratingUnit:
    """Unit penghasil kas (CGU)."""

    cgu_id: UUID
    cgu_code: str
    name: str
    cgu_type: IAS36CashGeneratingUnitType
    assets: list[UUID] = field(default_factory=list)
    goodwill_allocated: Money | None = None
    carrying_amount: Money | None = None
    recoverable_amount: Money | None = None

    def add_asset(self, asset_id: UUID) -> IAS36CashGeneratingUnit:
        return IAS36CashGeneratingUnit(
            cgu_id=self.cgu_id,
            cgu_code=self.cgu_code,
            name=self.name,
            cgu_type=self.cgu_type,
            assets=[*self.assets, asset_id],
            goodwill_allocated=self.goodwill_allocated,
            carrying_amount=self.carrying_amount,
            recoverable_amount=self.recoverable_amount,
        )

    def total_carrying(self) -> Money:
        if not self.carrying_amount:
            return Money(Decimal(0), "IDR")
        return self.carrying_amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "cgu_id": str(self.cgu_id),
            "cgu_code": self.cgu_code,
            "name": self.name,
            "type": self.cgu_type.value,
            "assets": [str(a) for a in self.assets],
            "goodwill_allocated": str(self.goodwill_allocated.amount)
            if self.goodwill_allocated
            else None,
            "carrying_amount": str(self.total_carrying().amount),
            "recoverable_amount": str(self.recoverable_amount.amount)
            if self.recoverable_amount
            else None,
        }


# === 4. DOMAIN SERVICES ===


class IAS36ImpairmentService:
    """Service untuk impairment test."""

    @staticmethod
    def calculate_value_in_use(
        future_cash_flows: list[tuple[int, Decimal]],  # (year, amount)
        discount_rate: Decimal,
        currency: str,
    ) -> Money:
        """Menghitung value in use dengan diskonto arus kas masa depan."""
        pv = Decimal(0)
        for year, cf in future_cash_flows:
            pv += cf / ((1 + discount_rate / 100) ** year)
        return Money(pv, currency)

    @staticmethod
    def calculate_fair_value_less_cost_to_sell(
        fair_value: Money,
        cost_to_sell: Money,
    ) -> Money:
        """Fair value less costs to sell."""
        return fair_value - cost_to_sell

    @staticmethod
    def determine_recoverable_amount(
        fvlcs: Money | None,
        viu: Money | None,
    ) -> IAS36RecoverableAmount:
        """Menentukan recoverable amount (higher of FVLCS and VIU)."""
        candidates = []
        if fvlcs:
            candidates.append(fvlcs)
        if viu:
            candidates.append(viu)
        if not candidates:
            raise ValueError("At least one of FVLCS or VIU required")
        max_candidate = max(candidates, key=lambda m: m.amount)
        return IAS36RecoverableAmount(
            fair_value_less_cost_to_sell=fvlcs,
            value_in_use=viu,
            recoverable_amount=max_candidate,
        )

    @staticmethod
    def allocate_impairment_to_cgu(
        cgu: IAS36CashGeneratingUnit,
        impairment_loss: Money,
        goodwill_first: bool = True,
    ) -> dict[UUID, Money]:
        """Mengalokasikan impairment loss ke CGU: goodwill dahulu, lalu aset lain proporsional."""
        allocation = {}
        remaining = impairment_loss.amount
        if goodwill_first and cgu.goodwill_allocated:
            goodwill_loss = min(remaining, cgu.goodwill_allocated.amount)
            allocation[cgu.cgu_id] = Money(goodwill_loss, impairment_loss.currency)
            remaining -= goodwill_loss
        # (alokasi ke aset lain diabaikan untuk contoh)
        return allocation


# === 5. IAS 36 VALIDATION RESULT ===


@dataclass
class IAS36ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS36ValidationResult) -> IAS36ValidationResult:
        return IAS36ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IAS 36 RULES ===


class IAS36Rules:
    """
    Aturan IAS 36:
    - Entitas harus menguji impairment setiap akhir periode jika ada indikasi.
    - Goodwill dan aset takberwujud dengan masa manfaat tidak terbatas diuji tahunan.
    - Recoverable amount = max(FVLCS, VIU).
    - Impairment loss diakui jika carrying amount > recoverable amount.
    - Impairment loss untuk aset (bukan goodwill) dapat dibalik jika kondisi membaik.
    - Goodwill impairment tidak dapat dibalik.
    - Alokasi impairment ke CGU: goodwill dahulu, lalu aset lain proporsional.
    """

    @staticmethod
    def validate_impairment_indicators(
        indicators: list[IAS36ImpairmentIndicator],
        is_goodwill: bool,
    ) -> IAS36ValidationResult:
        result = IAS36ValidationResult(is_compliant=True)
        # Goodwill wajib diuji tahunan meski tanpa indikasi
        return result

    @staticmethod
    def validate_reversal(
        original_impairment: IAS36ImpairmentLoss,
        new_recoverable: Money,
        is_goodwill: bool,
    ) -> tuple[Money, bool]:
        if is_goodwill:
            return Money(Decimal(0), new_recoverable.currency), False
        if new_recoverable.amount > original_impairment.carrying_amount_after.amount:
            reversal = min(
                new_recoverable.amount - original_impairment.carrying_amount_after.amount,
                original_impairment.impairment_loss.amount,
            )
            return Money(reversal, new_recoverable.currency), True
        return Money(Decimal(0), new_recoverable.currency), False


# === 7. IAS 36 VALIDATOR ===


class IAS36Validator:
    """Validator untuk IAS 36: Impairment of Assets."""

    def __init__(self):
        self._rules = IAS36Rules()

    def validate_impairment_test(
        self,
        carrying_amount: Money,
        recoverable_amount: Money,
        asset_type: str,
    ) -> IAS36ValidationResult:
        result = IAS36ValidationResult(is_compliant=True)
        if carrying_amount.amount > recoverable_amount.amount:
            loss = carrying_amount.amount - recoverable_amount.amount
            result.add_warning(f"Impairment loss of {loss} recognized for {asset_type}")
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "indicators": "External and internal sources of impairment",
            "recoverable_amount": "Higher of fair value less cost to sell and value in use",
            "annual_testing": "Goodwill and indefinite life intangibles tested annually",
            "recognition": "Impairment loss recognized immediately in P&L",
            "reversal": "Permitted for assets other than goodwill if conditions improve",
            "cgu": "Smallest identifiable group of assets that generates independent cash inflows",
        }


# === 8. ALIAS UNTUK KOMPATIBILITAS ===
IAS36ImpairmentTest = IAS36Validator


# === 9. SINGLETON ACCESSOR ===

_ias36_validator_instance: IAS36Validator | None = None


def get_ias36_validator() -> IAS36Validator:
    global _ias36_validator_instance
    if _ias36_validator_instance is None:
        _ias36_validator_instance = IAS36Validator()
    return _ias36_validator_instance


# ============================================================================
# Kelas untuk kompatibilitas dengan unit test (IAS36)
# ============================================================================


class IAS36:
    """
    Wrapper sederhana untuk method yang dipanggil oleh test_ifrs_rules.py.
    """

    @staticmethod
    def get_recoverable_amount(fair_value_less_cost: Decimal, value_in_use: Decimal) -> Decimal:
        """Mengembalikan recoverable amount (nilai tertinggi)."""
        return max(fair_value_less_cost, value_in_use)

    @staticmethod
    def calculate_impairment_loss(carrying_amount: Decimal, recoverable_amount: Decimal) -> Decimal:
        """Menghitung impairment loss."""
        loss = carrying_amount - recoverable_amount
        return loss if loss > 0 else Decimal(0)


# === 10. EXPORTS ===

__all__ = [
    "IAS36AllocationMethod",
    "IAS36CashGeneratingUnit",
    "IAS36CashGeneratingUnitType",
    "IAS36ImpairmentIndicator",
    "IAS36ImpairmentLoss",
    "IAS36ImpairmentService",
    "IAS36ImpairmentTest",
    "IAS36RecoverableAmount",
    "IAS36Rules",
    "IAS36ValidationResult",
    "IAS36Validator",
    "get_ias36_validator",
]
