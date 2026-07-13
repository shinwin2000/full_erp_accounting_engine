#!/usr/bin/env python3
"""
Module: company_tax_profile_vo.py
Layer: 6 - Domain / Legal Entity
Responsibility: Value object profil pajak perusahaan (PKP, tarif).

Perbaikan presisi:
    - Mengganti float() dengan str() pada nilai persentase di to_dict() untuk
      menghindari kehilangan presisi dan memenuhi aturan MNY-003.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from domain.shared_value_objects.percentage_vo import Percentage


class TaxRegime(Enum):
    GENERAL = "general"
    FINAL = "final"
    GROSS_UP = "gross_up"
    WITHHOLDING = "withholding"

    @classmethod
    def from_string(cls, value: str) -> TaxRegime:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.GENERAL


class TaxPaymentMethod(Enum):
    MONTHLY_INSTALLMENT = "monthly"
    ANNUAL_LUMP_SUM = "annual"
    WITHHOLDING = "withholding"

    @classmethod
    def from_string(cls, value: str) -> TaxPaymentMethod:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.MONTHLY_INSTALLMENT


@dataclass(frozen=True)
class CompanyTaxProfileVO:
    is_pkp: bool
    tax_regime: TaxRegime
    corporate_income_tax_rate: Percentage
    vat_rate: Percentage
    vat_collection_method: str = "output"
    income_tax_article: str | None = None
    tax_bracket: str | None = None
    payment_method: TaxPaymentMethod = TaxPaymentMethod.MONTHLY_INSTALLMENT
    annual_return_deadline_month: int = 4

    def __post_init__(self) -> None:
        if self.corporate_income_tax_rate.value < 0 or self.corporate_income_tax_rate.value > 100:
            raise ValueError("Corporate income tax rate must be between 0 and 100")
        if self.vat_rate.value < 0 or self.vat_rate.value > 100:
            raise ValueError("VAT rate must be between 0 and 100")
        if not (1 <= self.annual_return_deadline_month <= 12):
            raise ValueError("Annual return deadline month must be between 1 and 12")

    def effective_income_tax_rate(self) -> Percentage:
        if self.tax_regime == TaxRegime.FINAL:
            return Percentage(Decimal("0.5"))
        elif self.tax_regime == TaxRegime.GROSS_UP:
            return Percentage(self.corporate_income_tax_rate.value + Decimal("10"))
        return self.corporate_income_tax_rate

    def effective_vat_rate(self) -> Percentage:
        if not self.is_pkp:
            return Percentage(Decimal("0"))
        return self.vat_rate

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_pkp": self.is_pkp,
            "tax_regime": self.tax_regime.value,
            "corporate_income_tax_rate": str(self.corporate_income_tax_rate.value),
            "vat_rate": str(self.vat_rate.value),
            "vat_collection_method": self.vat_collection_method,
            "income_tax_article": self.income_tax_article,
            "tax_bracket": self.tax_bracket,
            "payment_method": self.payment_method.value,
            "annual_return_deadline_month": self.annual_return_deadline_month,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanyTaxProfileVO:
        return cls(
            is_pkp=data["is_pkp"],
            tax_regime=TaxRegime.from_string(data["tax_regime"]),
            corporate_income_tax_rate=Percentage(Decimal(str(data["corporate_income_tax_rate"]))),
            vat_rate=Percentage(Decimal(str(data["vat_rate"]))),
            vat_collection_method=data.get("vat_collection_method", "output"),
            income_tax_article=data.get("income_tax_article"),
            tax_bracket=data.get("tax_bracket"),
            payment_method=TaxPaymentMethod.from_string(data.get("payment_method", "monthly")),
            annual_return_deadline_month=data.get("annual_return_deadline_month", 4),
        )

    def normalize(self) -> CompanyTaxProfileVO:
        return CompanyTaxProfileVO(
            is_pkp=self.is_pkp,
            tax_regime=self.tax_regime,
            corporate_income_tax_rate=self.corporate_income_tax_rate.normalize(),
            vat_rate=self.vat_rate.normalize(),
            vat_collection_method=self.vat_collection_method.strip().lower(),
            income_tax_article=self.income_tax_article.strip().upper()
            if self.income_tax_article
            else None,
            tax_bracket=self.tax_bracket.strip() if self.tax_bracket else None,
            payment_method=self.payment_method,
            annual_return_deadline_month=self.annual_return_deadline_month,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CompanyTaxProfileVO):
            return False
        return (
            self.is_pkp == other.is_pkp
            and self.tax_regime == other.tax_regime
            and self.corporate_income_tax_rate == other.corporate_income_tax_rate
            and self.vat_rate == other.vat_rate
        )

    def __hash__(self) -> int:
        return hash((self.is_pkp, self.tax_regime, self.corporate_income_tax_rate, self.vat_rate))


CompanyTaxProfile = CompanyTaxProfileVO

__all__ = [
    "CompanyTaxProfile",
    "CompanyTaxProfileVO",
    "TaxPaymentMethod",
    "TaxRegime",
]
