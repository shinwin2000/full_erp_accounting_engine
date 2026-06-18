#!/usr/bin/env python3
"""
Module: ias_12_income_taxes.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 12: Income Taxes.
               Mendefinisikan aturan untuk akuntansi pajak penghasilan,
               termasuk pengakuan pajak kini dan pajak tangguhan.
               Aset dan liabilitas pajak tangguhan diakui untuk perbedaan
               temporer antara nilai buku dan dasar pajak.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)

Audit: Setiap perhitungan pajak dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS12TemporaryDifferenceType(Enum):
    """Jenis perbedaan temporer."""

    TAXABLE = "taxable"  # Akan menambah laba kena pajak di masa depan
    DEDUCTIBLE = "deductible"  # Akan mengurangi laba kena pajak di masa depan


class IAS12TaxBase(Enum):
    """Dasar pajak suatu aset atau liabilitas."""

    ASSET_TAX_BASE = "asset_tax_base"
    LIABILITY_TAX_BASE = "liability_tax_base"


# === 2. CUSTOM EXCEPTIONS ===


class IAS12Error(Exception):
    pass


# === 3. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS12CurrentTax:
    """Pajak kini untuk periode."""

    taxable_profit: Decimal
    current_tax_rate: Decimal  # persen
    current_tax_expense: Decimal
    over_under_provision_previous: Decimal = Decimal(0)

    def __post_init__(self):
        if self.current_tax_rate < 0 or self.current_tax_rate > 100:
            raise ValueError("Tax rate must be between 0 and 100")

    def total_expense(self) -> Decimal:
        return self.current_tax_expense + self.over_under_provision_previous

    def to_dict(self) -> dict[str, str]:
        return {
            "taxable_profit": str(self.taxable_profit),
            "tax_rate": str(self.current_tax_rate),
            "current_tax_expense": str(self.current_tax_expense),
            "over_under_provision": str(self.over_under_provision_previous),
            "total": str(self.total_expense()),
        }


@dataclass(frozen=True)
class IAS12TemporaryDifference:
    """Perbedaan temporer antara nilai buku dan dasar pajak."""

    asset_liability_id: UUID
    carrying_amount: Money
    tax_base: Money
    difference_type: IAS12TemporaryDifferenceType
    temporary_difference: Money

    def __post_init__(self):
        if self.carrying_amount.currency != self.tax_base.currency:
            raise ValueError("Currency mismatch between carrying amount and tax base")
        diff = self.carrying_amount - self.tax_base
        if diff.amount != self.temporary_difference.amount:
            raise ValueError("Temporary difference calculation mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_liability_id": str(self.asset_liability_id),
            "carrying_amount": str(self.carrying_amount.amount),
            "tax_base": str(self.tax_base.amount),
            "difference_type": self.difference_type.value,
            "temporary_difference": str(self.temporary_difference.amount),
            "currency": self.carrying_amount.currency,
        }


@dataclass(frozen=True)
class IAS12DeferredTax:
    """Pajak tangguhan."""

    deferred_tax_asset: Money
    deferred_tax_liability: Money
    valuation_allowance: Money  # Cadangan untuk aset pajak tangguhan yang tidak dapat dimanfaatkan
    net_deferred_tax: Money

    def to_dict(self) -> dict[str, str]:
        return {
            "deferred_tax_asset": str(self.deferred_tax_asset.amount),
            "deferred_tax_liability": str(self.deferred_tax_liability.amount),
            "valuation_allowance": str(self.valuation_allowance.amount),
            "net_deferred_tax": str(self.net_deferred_tax.amount),
            "currency": self.deferred_tax_asset.currency,
        }


# === 4. ENTITIES ===


@dataclass
class IAS12TaxPosition:
    """Posisi pajak entitas."""

    tax_position_id: UUID
    entity_id: UUID
    reporting_date: datetime
    current_tax: IAS12CurrentTax
    deferred_tax: IAS12DeferredTax
    taxable_temporary_differences: list[IAS12TemporaryDifference] = field(default_factory=list)
    deductible_temporary_differences: list[IAS12TemporaryDifference] = field(default_factory=list)
    tax_loss_carryforwards: Money = field(default_factory=lambda: Money(Decimal(0), "IDR"))
    tax_credit_carryforwards: Money = field(default_factory=lambda: Money(Decimal(0), "IDR"))

    def total_tax_expense(self) -> Money:
        currency = self.current_tax.total_expense()  # butuh currency
        # Simplified
        return Money(Decimal(self.current_tax.total_expense()), "IDR")

    def effective_tax_rate(self) -> Decimal:
        """Tarif pajak efektif = total tax expense / accounting profit."""
        accounting_profit = Decimal(1000000)  # placeholder
        if accounting_profit == 0:
            return Decimal(0)
        total = self.current_tax.total_expense() + self.deferred_tax.net_deferred_tax.amount
        return (total / accounting_profit) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "tax_position_id": str(self.tax_position_id),
            "entity_id": str(self.entity_id),
            "reporting_date": self.reporting_date.isoformat(),
            "current_tax": self.current_tax.to_dict(),
            "deferred_tax": self.deferred_tax.to_dict(),
            "taxable_temporary_differences": [
                t.to_dict() for t in self.taxable_temporary_differences
            ],
            "deductible_temporary_differences": [
                t.to_dict() for t in self.deductible_temporary_differences
            ],
        }


# === 5. DOMAIN SERVICES ===


class IAS12TaxService:
    """Service untuk perhitungan pajak sesuai IAS 12."""

    @staticmethod
    def calculate_current_tax(
        taxable_profit: Decimal,
        tax_rate: Decimal,
        previous_under_provision: Decimal = Decimal(0),
    ) -> IAS12CurrentTax:
        """Menghitung pajak kini."""
        expense = taxable_profit * (tax_rate / 100)
        return IAS12CurrentTax(
            taxable_profit=taxable_profit,
            current_tax_rate=tax_rate,
            current_tax_expense=expense,
            over_under_provision_previous=previous_under_provision,
        )

    @staticmethod
    def calculate_temporary_difference(
        carrying_amount: Money,
        tax_base: Money,
    ) -> Tuple[Money, IAS12TemporaryDifferenceType]:
        """Menghitung perbedaan temporer."""
        diff = carrying_amount - tax_base
        if diff.amount > 0:
            # Aset: carrying > tax base -> taxable temporary difference
            return diff, IAS12TemporaryDifferenceType.TAXABLE
        elif diff.amount < 0:
            return diff.abs(), IAS12TemporaryDifferenceType.DEDUCTIBLE
        else:
            return Money(Decimal(0), carrying_amount.currency), None

    @staticmethod
    def calculate_deferred_tax(
        taxable_differences: list[IAS12TemporaryDifference],
        deductible_differences: list[IAS12TemporaryDifference],
        tax_rate: Decimal,
        currency: str,
    ) -> IAS12DeferredTax:
        """Menghitung pajak tangguhan."""
        deferred_tax_liability = sum(d.temporary_difference.amount for d in taxable_differences) * (
            tax_rate / 100
        )
        deferred_tax_asset = sum(d.temporary_difference.amount for d in deductible_differences) * (
            tax_rate / 100
        )
        net = deferred_tax_asset - deferred_tax_liability
        valuation_allowance = Decimal(0)
        if deferred_tax_asset > 0:
            # Simplified: assume full valuation if no future profit
            valuation_allowance = deferred_tax_asset
        return IAS12DeferredTax(
            deferred_tax_asset=Money(deferred_tax_asset, currency),
            deferred_tax_liability=Money(deferred_tax_liability, currency),
            valuation_allowance=Money(valuation_allowance, currency),
            net_deferred_tax=Money(net, currency),
        )


# === 6. IAS 12 VALIDATION RESULT ===


@dataclass
class IAS12ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS12ValidationResult) -> IAS12ValidationResult:
        return IAS12ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 7. IAS 12 RULES ===


class IAS12Rules:
    """
    Aturan IAS 12:
    - Pajak kini diakui sebagai liabilitas sebesar estimasi yang belum dibayar.
    - Aset pajak tangguhan diakui untuk deductible temporary differences sepanjang
      kemungkinan besar laba kena pajak akan tersedia.
    - Pajak tangguhan tidak didiskontokan.
    - Tarif pajak yang digunakan adalah tarif yang telah berlaku atau secara substantif berlaku.
    - Perubahan tarif pajak diakui pada periode perubahan.
    """

    @staticmethod
    def validate_deferred_tax_asset_recognition(
        deferred_tax_asset: Money,
        probable_future_taxable_profit: Money,
    ) -> IAS12ValidationResult:
        result = IAS12ValidationResult(is_compliant=True)
        if deferred_tax_asset.amount > probable_future_taxable_profit.amount:
            result.add_warning(
                "Deferred tax asset may not be recoverable; consider valuation allowance"
            )
        return result

    @staticmethod
    def validate_tax_rate_change(
        old_rate: Decimal,
        new_rate: Decimal,
        effective_date: datetime,
        current_date: datetime,
    ) -> IAS12ValidationResult:
        result = IAS12ValidationResult(is_compliant=True)
        if new_rate != old_rate and effective_date <= current_date:
            result.add_warning("Tax rate change effective; deferred tax should be remeasured")
        return result


# === 8. IAS 12 VALIDATOR ===


class IAS12Validator:
    """Validator untuk IAS 12: Income Taxes."""

    def __init__(self):
        self._rules = IAS12Rules()

    def validate_tax_position(self, tax_position: IAS12TaxPosition) -> IAS12ValidationResult:
        result = IAS12ValidationResult(is_compliant=True)
        result.merge(
            self._rules.validate_deferred_tax_asset_recognition(
                tax_position.deferred_tax.deferred_tax_asset,
                Money(
                    Decimal(1000000), tax_position.deferred_tax.deferred_tax_asset.currency
                ),  # placeholder
            )
        )
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "current_tax": "Recognize as liability or asset based on estimated tax payable/recoverable",
            "deferred_tax": "Recognize for all temporary differences",
            "measurement": "Use enacted or substantively enacted tax rates",
            "discounting": "Not permitted",
            "recognition_of_deferred_tax_assets": "Only if probable that future taxable profit will be available",
        }


# === 9. SINGLETON ACCESSOR ===

_ias12_validator_instance: IAS12Validator | None = None


def get_ias12_validator() -> IAS12Validator:
    global _ias12_validator_instance
    if _ias12_validator_instance is None:
        _ias12_validator_instance = IAS12Validator()
    return _ias12_validator_instance


# === 10. EXPORTS ===

__all__ = [
    "IAS12CurrentTax",
    "IAS12DeferredTax",
    "IAS12Rules",
    "IAS12TaxBase",
    "IAS12TaxPosition",
    "IAS12TaxService",
    "IAS12TemporaryDifference",
    "IAS12TemporaryDifferenceType",
    "IAS12ValidationResult",
    "IAS12Validator",
    "get_ias12_validator",
]
