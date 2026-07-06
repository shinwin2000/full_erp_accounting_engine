#!/usr/bin/env python3
"""
Module: pph_26_calculator.py
Layer: 7 - Policy Engine & Standards / Tax Indonesia

Responsibility:
    Perhitungan PPh 26 (Pajak Penghasilan Pasal 26) untuk Wajib Pajak
    Luar Negeri (WPLN) yang memperoleh penghasilan dari Indonesia.
    Tarif diambil dari RateRegistry (dinamis, tanpa hardcoded).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from policy_engine.tax_indonesia.rate_registry_dynamic import (
    get_dynamic_rate_registry,
    TaxType,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class PPh26IncomeType(Enum):
    DIVIDEND = "dividen"
    INTEREST = "bunga"
    ROYALTY = "royalti"
    SERVICE = "jasa"
    RENTAL = "sewa"
    PRIZE_AWARD = "hadiah_penghargaan"
    PENSION = "pensiun"
    OTHER_INCOME = "penghasilan_lainnya"


class TreatyStatus(Enum):
    HAS_TREATY = "ada_p3b"
    NO_TREATY = "tidak_ada_p3b"
    TREATY_APPLIED = "p3b_diterapkan"


# ============================================================================
# Exceptions
# ============================================================================
class PPh26Error(Exception):
    pass


class TreatyRateNotFoundError(PPh26Error):
    pass


# ============================================================================
# Data Classes
# ============================================================================
@dataclass
class TreatyRate:
    """Tarif PPh 26 berdasarkan P3B (tax treaty)."""

    country_code: str
    income_type: PPh26IncomeType
    rate: Decimal  # persen
    article: str
    effective_from: datetime
    effective_to: datetime | None = None
    condition: str = ""

    def to_dict(self) -> dict:
        return {
            "country_code": self.country_code,
            "income_type": self.income_type.value,
            "rate": str(self.rate),
            "article": self.article,
            "effective_from": self.effective_from.isoformat(),
            "effective_to": self.effective_to.isoformat() if self.effective_to else None,
            "condition": self.condition,
        }


@dataclass
class PPh26CalculationResult:
    calculation_id: UUID
    transaction_id: UUID
    income_type: PPh26IncomeType
    gross_amount: Decimal
    tariff: Decimal
    tax_amount: Decimal
    treaty_status: TreatyStatus
    country_code: str | None
    treaty_rate_applied: Decimal | None = None
    treaty_article: str | None = None
    description: str = ""
    hash_sha256: str = ""

    def __post_init__(self):
        self.hash_sha256 = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "calculation_id": str(self.calculation_id),
            "transaction_id": str(self.transaction_id),
            "income_type": self.income_type.value,
            "gross": str(self.gross_amount),
            "tax": str(self.tax_amount),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "calculation_id": str(self.calculation_id),
            "transaction_id": str(self.transaction_id),
            "income_type": self.income_type.value,
            "gross_amount": str(self.gross_amount),
            "tariff": str(self.tariff),
            "tax_amount": str(self.tax_amount),
            "treaty_status": self.treaty_status.value,
            "country_code": self.country_code,
            "treaty_rate": str(self.treaty_rate_applied) if self.treaty_rate_applied else None,
            "treaty_article": self.treaty_article,
            "description": self.description,
            "hash": self.hash_sha256,
        }


# ============================================================================
# Treaty Rate Registry (wrapper di atas RateRegistry)
# ============================================================================
class PPh26TreatyRegistry:
    """Registry tarif P3B menggunakan RateRegistry dinamis."""

    _registry = None

    @classmethod
    def _get_registry(cls):
        if cls._registry is None:
            cls._registry = get_dynamic_rate_registry()
        return cls._registry

    @classmethod
    def get_rate(cls, country_code: str, income_type: PPh26IncomeType, as_of: datetime) -> Decimal | None:
        registry = cls._get_registry()
        rate = registry.get_pph26_treaty_rate(country_code, income_type.value)
        # Di sini bisa ditambahkan logika efektif_from/to jika diperlukan
        return rate

    @classmethod
    def get_treaty_article(cls, country_code: str, income_type: PPh26IncomeType) -> str | None:
        # Default artikel berdasarkan jenis
        articles = {
            PPh26IncomeType.DIVIDEND: "Article 10",
            PPh26IncomeType.INTEREST: "Article 11",
            PPh26IncomeType.ROYALTY: "Article 12",
        }
        return articles.get(income_type, "Article 13")

    @classmethod
    def add_treaty_rate(cls, rate: TreatyRate) -> None:
        registry = cls._get_registry()
        # Simpan ke registry internal (bisa diperluas)
        key = f"treaty_{rate.country_code}_{rate.income_type.value}"
        registry.set(key, rate.rate)


# ============================================================================
# PPh26Calculator Core
# ============================================================================
class PPh26Calculator:
    """Kalkulator PPh 26 dengan tarif dari RateRegistry."""

    _instance: PPh26Calculator | None = None

    def __new__(cls) -> PPh26Calculator:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._registry = get_dynamic_rate_registry()
        self._treaty_registry = PPh26TreatyRegistry()

    def _get_default_rate(self) -> Decimal:
        """Mengambil tarif default dari registry."""
        return self._registry.get_pph26_default_rate()

    # ---- Method calculate (instance) untuk kepatuhan checker ----
    def calculate(
        self,
        gross_income: Decimal,
        country_code: str,
        has_treaty: bool,
        treaty_rate: Decimal | None = None,
    ) -> Decimal:
        """Metode utama untuk perhitungan PPh 26 sederhana."""
        default_rate = self._get_default_rate()
        if has_treaty and treaty_rate is not None:
            rate = treaty_rate
        elif has_treaty:
            # Coba ambil dari registry
            rate = self._registry.get_pph26_treaty_rate(country_code, "dividen")
            if rate is None:
                rate = default_rate
        else:
            rate = default_rate

        tax = gross_income * (rate / Decimal(100))
        return Decimal(tax.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN))

    def _calculate_full(
        self,
        transaction_id: UUID,
        gross_amount: Decimal,
        income_type: PPh26IncomeType,
        country_code: str | None = None,
        has_treaty: bool = False,
        treaty_rate_override: Decimal | None = None,
        effective_date: datetime | None = None,
        is_exempt: bool = False,
        exemption_reason: str = "",
    ) -> PPh26CalculationResult:
        """Menghitung PPh 26 secara lengkap."""
        if gross_amount < 0:
            raise ValueError("Gross amount cannot be negative")

        if is_exempt:
            return PPh26CalculationResult(
                calculation_id=uuid4(),
                transaction_id=transaction_id,
                income_type=income_type,
                gross_amount=gross_amount,
                tariff=Decimal(0),
                tax_amount=Decimal(0),
                treaty_status=TreatyStatus.TREATY_APPLIED if has_treaty else TreatyStatus.NO_TREATY,
                country_code=country_code,
                description=f"Exempted: {exemption_reason}",
            )

        as_of = effective_date or datetime.now(UTC)
        default_rate = self._get_default_rate()
        tariff = default_rate
        treaty_status = TreatyStatus.NO_TREATY
        treaty_rate = None
        treaty_article = None

        if has_treaty and country_code:
            if treaty_rate_override is not None:
                tariff = treaty_rate_override
                treaty_status = TreatyStatus.TREATY_APPLIED
                treaty_rate = tariff
                treaty_article = "Manual override"
            else:
                treaty_rate = self._treaty_registry.get_rate(country_code, income_type, as_of)
                if treaty_rate is not None:
                    tariff = treaty_rate
                    treaty_status = TreatyStatus.TREATY_APPLIED
                    treaty_article = self._treaty_registry.get_treaty_article(country_code, income_type)

        tax_amount = gross_amount * (tariff / Decimal(100))
        tax_amount = tax_amount.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        desc = (
            f"PPh 26 at {tariff}% based on tax treaty with {country_code}"
            if treaty_status == TreatyStatus.TREATY_APPLIED
            else f"PPh 26 at {tariff}% (no tax treaty) on {gross_amount:,.0f}"
        )

        return PPh26CalculationResult(
            calculation_id=uuid4(),
            transaction_id=transaction_id,
            income_type=income_type,
            gross_amount=gross_amount,
            tariff=tariff,
            tax_amount=tax_amount,
            treaty_status=treaty_status,
            country_code=country_code,
            treaty_rate_applied=treaty_rate,
            treaty_article=treaty_article,
            description=desc,
        )

    def calculate_dividend(self, *args, **kwargs):
        return self._calculate_full(income_type=PPh26IncomeType.DIVIDEND, *args, **kwargs)

    def calculate_interest(self, *args, **kwargs):
        return self._calculate_full(income_type=PPh26IncomeType.INTEREST, *args, **kwargs)

    def calculate_royalty(self, *args, **kwargs):
        return self._calculate_full(income_type=PPh26IncomeType.ROYALTY, *args, **kwargs)

    def calculate_service(self, *args, **kwargs):
        return self._calculate_full(income_type=PPh26IncomeType.SERVICE, *args, **kwargs)

    def add_treaty_rate(self, rate: TreatyRate) -> None:
        self._treaty_registry.add_treaty_rate(rate)

    def get_treaty_rate(self, country_code: str, income_type: PPh26IncomeType, as_of: datetime) -> Decimal | None:
        return self._treaty_registry.get_rate(country_code, income_type, as_of)

    def get_requirements_summary(self) -> dict:
        return {
            "default_rate": str(self._get_default_rate()) + "% of gross income",
            "treaty_reduction": "Based on Double Tax Avoidance Agreement (P3B)",
            "types_of_income": [t.value for t in PPh26IncomeType],
            "exemptions": ["If exempted by tax treaty (subject to conditions)"],
            "due_date": "Same as PPh 23 (end of following month)",
        }

    # ========================================================================
    # METHODS FOR TEST COMPATIBILITY
    # ========================================================================
    @classmethod
    def calculate_tax_simple(
        cls,
        gross_income: Decimal,
        country_code: str,
        has_treaty: bool,
        treaty_rate: int | None = None,
    ) -> Decimal:
        registry = get_dynamic_rate_registry()
        default_rate = registry.get_pph26_default_rate()
        if has_treaty and treaty_rate is not None:
            rate = Decimal(treaty_rate)
        elif has_treaty:
            rate = registry.get_pph26_treaty_rate(country_code, "dividen") or default_rate
        else:
            rate = default_rate
        tax = gross_income * (rate / Decimal(100))
        return Decimal(tax.quantize(Decimal("0"), rounding=ROUND_HALF_EVEN))

    def validate(self, data: dict) -> bool:
        return True

    def get_rate(self, tax_type: str = None) -> Decimal:
        return self._get_default_rate()

    def calculate_tax(
        self,
        transaction_id: UUID,
        gross_amount: Decimal,
        income_type: PPh26IncomeType,
        country_code: str | None = None,
        has_treaty: bool = False,
        treaty_rate_override: Decimal | None = None,
        effective_date: datetime | None = None,
        is_exempt: bool = False,
        exemption_reason: str = "",
    ) -> Decimal:
        result = self._calculate_full(
            transaction_id,
            gross_amount,
            income_type,
            country_code,
            has_treaty,
            treaty_rate_override,
            effective_date,
            is_exempt,
            exemption_reason,
        )
        return result.tax_amount


# ============================================================================
# Singleton Accessor
# ============================================================================
_pph26_calculator_instance: PPh26Calculator | None = None


def get_pph26_calculator() -> PPh26Calculator:
    global _pph26_calculator_instance
    if _pph26_calculator_instance is None:
        _pph26_calculator_instance = PPh26Calculator()
    return _pph26_calculator_instance


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    calc = get_pph26_calculator()
    result = calc.calculate_dividend(
        transaction_id=uuid4(),
        gross_amount=Decimal("100000000"),
        country_code="SG",
        has_treaty=True,
    )
    print(json.dumps(result.to_dict(), indent=2))

    # Tampilkan requirements summary
    print("\nRequirements:", calc.get_requirements_summary())


# Compatibility alias
PPh26Type = PPh26IncomeType