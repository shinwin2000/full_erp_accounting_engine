#!/usr/bin/env python3
"""
Module: ias_21_foreign_exchange.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IAS 21: The Effects of Changes in Foreign Exchange Rates.
               Mendefinisikan aturan untuk transaksi mata uang asing,
               penentuan mata uang fungsional, dan penjabaran laporan
               keuangan entitas asing ke mata uang penyajian.

Dependencies:
- standard library (decimal, datetime, logging, dataclass)
- domain.shared_value_objects.money_vo (Money)
- domain.shared_value_objects.currency_vo (CurrencyVO)
- domain.shared_value_objects.exchange_rate_vo (ExchangeRateVO)

Audit: Setiap transaksi valas dan selisih kurs dictat.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.shared_value_objects.currency_vo import CurrencyCode, CurrencyVO
from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IAS21FunctionalCurrencyIndicators(Enum):
    """Indikator mata uang fungsional."""

    SALES_PRICE_SETTING = "sales_price_setting"
    COMPETITIVE_FORCES = "competitive_forces"
    LABOR_MATERIAL_COSTS = "labor_material_costs"
    FINANCING_CURRENCY = "financing_currency"
    OPERATING_ACTIVITIES = "operating_activities"


class IAS21TranslationMethod(Enum):
    """Metode penjabaran laporan keuangan entitas asing."""

    CLOSING_RATE = "closing_rate"  # Aset & liabilitas: kurs penutup
    TEMPORAL = "temporal"  # Metode temporal (IAS 21)


class IAS21ExchangeDifferenceTreatment(Enum):
    """Perlakuan selisih kurs."""

    RECOGNIZED_IN_PL = "recognized_in_pl"
    RECOGNIZED_IN_OCI = "recognized_in_oci"  # Untuk investasi neto


# === 2. VALUE OBJECTS ===


@dataclass(frozen=True)
class IAS21ForeignCurrencyTransaction:
    """Transaksi dalam mata uang asing."""

    transaction_id: UUID
    date: datetime
    foreign_currency: CurrencyVO
    functional_currency: CurrencyVO
    original_amount: Money
    spot_rate: Decimal
    functional_amount: Money
    settlement_date: datetime | None = None
    settlement_rate: Decimal | None = None
    exchange_difference: Money | None = None

    def __post_init__(self):
        if self.original_amount.currency != self.foreign_currency.code.value:
            raise ValueError("Currency mismatch in original amount")
        if self.functional_amount.currency != self.functional_currency.code.value:
            raise ValueError("Currency mismatch in functional amount")

    def calculate_settlement_difference(self) -> Money:
        if not self.settlement_date or not self.settlement_rate:
            raise ValueError("Settlement date and rate required")
        settled_amount = Money(
            self.original_amount.amount * self.settlement_rate, self.functional_currency.code.value
        )
        diff = settled_amount - self.functional_amount
        return diff

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "date": self.date.isoformat(),
            "foreign_currency": self.foreign_currency.code.value,
            "original_amount": str(self.original_amount.amount),
            "spot_rate": str(self.spot_rate),
            "functional_amount": str(self.functional_amount.amount),
            "functional_currency": self.functional_currency.code.value,
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "exchange_difference": str(self.exchange_difference.amount)
            if self.exchange_difference
            else None,
        }


@dataclass(frozen=True)
class IAS21ForeignOperation:
    """Operasi luar negeri."""

    operation_id: UUID
    operation_name: str
    functional_currency: CurrencyVO
    reporting_currency: CurrencyVO
    net_assets_beginning: Money
    net_assets_end: Money
    cumulative_translation_adjustment: Money

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": str(self.operation_id),
            "operation_name": self.operation_name,
            "functional_currency": self.functional_currency.code.value,
            "reporting_currency": self.reporting_currency.code.value,
            "net_assets_beginning": str(self.net_assets_beginning.amount),
            "net_assets_end": str(self.net_assets_end.amount),
            "cumulative_translation_adjustment": str(self.cumulative_translation_adjustment.amount),
        }


# === 3. ENTITIES ===


@dataclass
class IAS21FunctionalCurrencyAssessment:
    """Penilaian mata uang fungsional."""

    assessment_id: UUID
    entity_id: UUID
    primary_sales_currency: CurrencyVO
    labor_material_currency: CurrencyVO
    financing_currency: CurrencyVO
    operating_currency: CurrencyVO
    determined_functional_currency: CurrencyVO
    assessment_date: datetime
    indicators_used: list[IAS21FunctionalCurrencyIndicators] = field(default_factory=list)

    def __post_init__(self):
        # Validasi bahwa mata uang fungsional adalah salah satu dari indikator dominan
        if self.determined_functional_currency not in [
            self.primary_sales_currency,
            self.labor_material_currency,
            self.financing_currency,
            self.operating_currency,
        ]:
            logger.warning("Functional currency not matching any primary indicator")

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": str(self.assessment_id),
            "entity_id": str(self.entity_id),
            "primary_sales": self.primary_sales_currency.code.value,
            "labor_material": self.labor_material_currency.code.value,
            "financing": self.financing_currency.code.value,
            "operating": self.operating_currency.code.value,
            "determined": self.determined_functional_currency.code.value,
            "assessment_date": self.assessment_date.isoformat(),
            "indicators": [i.value for i in self.indicators_used],
        }


# === 4. DOMAIN SERVICES ===


class IAS21FunctionalCurrencyService:
    """Service penentuan mata uang fungsional."""

    @staticmethod
    def determine_functional_currency(
        primary_sales_currency: CurrencyVO,
        labor_material_currency: CurrencyVO,
        financing_currency: CurrencyVO,
        operating_currency: CurrencyVO,
    ) -> CurrencyVO:
        """
        Menentukan mata uang fungsional berdasarkan faktor dominan.
        Biasanya mata uang yang mempengaruhi harga jual, biaya, pendanaan.
        """
        currencies = [
            primary_sales_currency,
            labor_material_currency,
            financing_currency,
            operating_currency,
        ]
        counter = Counter(c.code for c in currencies)
        most_common = counter.most_common(1)[0][0]
        return CurrencyVO(CurrencyCode(most_common))

    @staticmethod
    def translate_balance_sheet(
        assets_liabilities: dict[str, Money],
        closing_rate: Decimal,
        reporting_currency: CurrencyVO,
    ) -> dict[str, Money]:
        """Menjabarkan aset dan liabilitas dengan kurs penutup."""
        result = {}
        for key, amount in assets_liabilities.items():
            new_amount = amount.amount * closing_rate
            result[key] = Money(new_amount, reporting_currency.code.value)
        return result

    @staticmethod
    def translate_income_statement(
        income_expenses: dict[str, Money],
        average_rate: Decimal,
        reporting_currency: CurrencyVO,
    ) -> dict[str, Money]:
        """Menjabarkan pendapatan dan beban dengan kurs rata-rata."""
        result = {}
        for key, amount in income_expenses.items():
            new_amount = amount.amount * average_rate
            result[key] = Money(new_amount, reporting_currency.code.value)
        return result

    @staticmethod
    def calculate_cumulative_translation_adjustment(
        opening_net_assets: Money,
        closing_net_assets: Money,
        opening_rate: Decimal,
        closing_rate: Decimal,
        average_rate: Decimal,
    ) -> Money:
        """Menghitung penyesuaian translasi kumulatif (CTA) di OCI."""
        cta = (closing_net_assets.amount * (closing_rate - average_rate)) - (
            opening_net_assets.amount * (opening_rate - average_rate)
        )
        return Money(cta, opening_net_assets.currency)


# === 5. IAS 21 VALIDATION RESULT ===


@dataclass
class IAS21ValidationResult:
    is_compliant: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_compliant = False

    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)

    def merge(self, other: IAS21ValidationResult) -> IAS21ValidationResult:
        return IAS21ValidationResult(
            is_compliant=self.is_compliant and other.is_compliant,
            errors=self.errors + other.errors,
            warnings=self.warnings + other.warnings,
        )


# === 6. IAS 21 RULES ===


class IAS21Rules:
    """
    Aturan IAS 21:
    - Mata uang fungsional ditentukan berdasarkan lingkungan ekonomi utama.
    - Perubahan mata uang fungsional hanya jika ada perubahan signifikan dalam
      transaksi dan kondisi.
    - Transaksi mata uang asing dijabarkan ke mata uang fungsional dengan kurs spot.
    - Selisih kurs diakui di laba rugi, kecuali untuk investasi neto.
    - Laporan keuangan entitas asing dijabarkan ke mata uang penyajian dengan
      kurs penutup (aset/liabilitas) dan kurs rata-rata (pendapatan/beban).
    - Selisih translasi diakui di OCI.
    """

    @staticmethod
    def validate_functional_currency_change(
        old_currency: CurrencyVO,
        new_currency: CurrencyVO,
        has_significant_change: bool,
    ) -> IAS21ValidationResult:
        result = IAS21ValidationResult(is_compliant=True)
        if new_currency != old_currency and not has_significant_change:
            result.add_error(
                "Change in functional currency without significant change in transactions/conditions"
            )
        return result

    @staticmethod
    def validate_translation_method(
        method: IAS21TranslationMethod,
        is_hyperinflationary: bool,
    ) -> IAS21ValidationResult:
        result = IAS21ValidationResult(is_compliant=True)
        if is_hyperinflationary and method != IAS21TranslationMethod.TEMPORAL:
            result.add_error("Hyperinflationary economy requires temporal method or restatement")
        return result


# === 7. IAS 21 VALIDATOR ===


class IAS21Validator:
    """Validator untuk IAS 21: Foreign Exchange."""

    def __init__(self):
        self._rules = IAS21Rules()

    def validate_transaction(
        self,
        transaction: IAS21ForeignCurrencyTransaction,
    ) -> IAS21ValidationResult:
        result = IAS21ValidationResult(is_compliant=True)
        if transaction.spot_rate <= 0:
            result.add_error(f"Spot rate must be positive: {transaction.spot_rate}")
        return result

    def validate_functional_currency_assessment(
        self,
        assessment: IAS21FunctionalCurrencyAssessment,
    ) -> IAS21ValidationResult:
        result = IAS21ValidationResult(is_compliant=True)
        if not assessment.indicators_used:
            result.add_warning("No indicators documented for functional currency determination")
        return result

    def get_requirements_summary(self) -> dict[str, Any]:
        return {
            "functional_currency": "Currency of primary economic environment",
            "initial_recognition": "Spot rate at transaction date",
            "subsequent_measurement": "Use closing rate for monetary items",
            "translation_of_foreign_operations": "Assets/liabilities: closing rate; Income/expenses: average rate",
            "exchange_differences": "Recognized in P&L except for net investment in foreign operation (OCI)",
        }


# === 8. SINGLETON ACCESSOR ===

_ias21_validator_instance: IAS21Validator | None = None


def get_ias21_validator() -> IAS21Validator:
    global _ias21_validator_instance
    if _ias21_validator_instance is None:
        _ias21_validator_instance = IAS21Validator()
    return _ias21_validator_instance


# === 9. ALIAS UNTUK KOMPATIBILITAS ===
IAS21FunctionalCurrency = IAS21FunctionalCurrencyAssessment


# === 10. EXPORTS ===

__all__ = [
    "IAS21ExchangeDifferenceTreatment",
    "IAS21ForeignCurrencyTransaction",
    "IAS21ForeignOperation",
    "IAS21FunctionalCurrency",  # alias
    "IAS21FunctionalCurrencyAssessment",
    "IAS21FunctionalCurrencyIndicators",
    "IAS21FunctionalCurrencyService",
    "IAS21Rules",
    "IAS21TranslationMethod",
    "IAS21ValidationResult",
    "IAS21Validator",
    "get_ias21_validator",
]
