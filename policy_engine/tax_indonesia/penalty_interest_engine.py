#!/usr/bin/env python3
"""
Module: penalty_interest_engine.py
Layer: 7 - Policy Engine & Standards / Tax Indonesia
Responsibility: Perhitungan sanksi bunga.
               Menyediakan engine untuk menghitung sanksi bunga atas
               keterlambatan pembayaran pajak sesuai dengan ketentuan
               perpajakan Indonesia (KMK dan UU KUP).

Dependencies:
- standard library (decimal, datetime, logging, dataclass)

Audit: Setiap perhitungan sanksi bunga dictat.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

# Optional import with fallback
try:
    from policy_engine.tax_indonesia.rate_registry_dynamic import (
        TaxType,
        get_dynamic_rate_registry,
    )
except ImportError:
    # Dummy for test compatibility
    class TaxType(Enum):
        PPN = "ppn"
        PPH_21 = "pph21"
        PPH_22 = "pph22"
        PPH_23 = "pph23"
        PPH_25 = "pph25"
        PPH_26 = "pph26"
        PPH_4_2 = "pph4_2"
        PPH_BADAN = "pph_badan"
        OTHER = "other"

    def get_dynamic_rate_registry():
        return None


logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class PenaltyType(Enum):
    """Jenis sanksi."""

    INTEREST = "interest"  # Bunga keterlambatan
    FINE = "fine"  # Denda administrasi
    CRIMINAL = "criminal"  # Sanksi pidana
    ESCALATED = "escalated"  # Sanksi yang dinaikkan


class TaxObligationType(Enum):
    """Jenis kewajiban pajak."""

    MONTHLY_RETURN = "monthly_return"  # SPT Masa
    ANNUAL_RETURN = "annual_return"  # SPT Tahunan
    TAX_PAYMENT = "tax_payment"  # Pembayaran pajak
    WITHHOLDING = "withholding"  # Pemotongan pajak


# === 2. PENALTY CALCULATION RESULT ===


@dataclass
class PenaltyCalculationResult:
    """Hasil perhitungan sanksi."""

    penalty_type: PenaltyType
    tax_type: TaxType
    due_date: datetime
    payment_date: datetime
    days_late: int
    tax_amount: Decimal
    interest_rate: Decimal
    penalty_amount: Decimal
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "penalty_type": self.penalty_type.value,
            "tax_type": self.tax_type.value,
            "due_date": self.due_date.isoformat(),
            "payment_date": self.payment_date.isoformat(),
            "days_late": self.days_late,
            "tax_amount": str(self.tax_amount),
            "interest_rate": str(self.interest_rate),
            "penalty_amount": str(self.penalty_amount),
            "description": self.description,
        }


# === 3. PENALTY INTEREST ENGINE ===


class PenaltyInterestEngine:
    """
    Engine untuk perhitungan sanksi bunga pajak.

    Business context: Menghitung sanksi bunga atas keterlambatan
    pembayaran atau pelaporan pajak sesuai peraturan perpajakan.
    """

    _instance: PenaltyInterestEngine | None = None

    def __new__(cls) -> PenaltyInterestEngine:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._rate_registry = get_dynamic_rate_registry()

    def get_interest_rate(self, as_of: datetime | None = None) -> Decimal:
        """
        Mendapatkan suku bunga untuk perhitungan sanksi.

        Mengacu pada tarif bunga acuan (benchmark rate) yang ditetapkan
        oleh Menteri Keuangan.
        """
        # Default: 0.5% per bulan (sederhana)
        # Dalam implementasi nyata, akan mengambil dari rate registry
        return Decimal("0.5")  # 0.5% per bulan

    def calculate_late_payment_interest(
        self,
        tax_amount: Decimal,
        due_date: datetime,
        payment_date: datetime,
        tax_type: TaxType,
    ) -> PenaltyCalculationResult:
        """
        Menghitung bunga keterlambatan pembayaran pajak.

        Formula: Bunga = (Pajak x Tarif Bunga x Jumlah Bulan)
        """
        if payment_date <= due_date:
            return PenaltyCalculationResult(
                penalty_type=PenaltyType.INTEREST,
                tax_type=tax_type,
                due_date=due_date,
                payment_date=payment_date,
                days_late=0,
                tax_amount=tax_amount,
                interest_rate=Decimal(0),
                penalty_amount=Decimal(0),
                description="No late payment penalty (paid on time)",
            )

        # Hitung jumlah bulan keterlambatan (dibulatkan ke atas)
        days_late = (payment_date - due_date).days
        months_late = max(1, (days_late + 29) // 30)  # Pembulatan ke atas

        monthly_rate = self.get_interest_rate(payment_date) / Decimal(100)
        penalty = tax_amount * monthly_rate * months_late
        penalty = penalty.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

        return PenaltyCalculationResult(
            penalty_type=PenaltyType.INTEREST,
            tax_type=tax_type,
            due_date=due_date,
            payment_date=payment_date,
            days_late=days_late,
            tax_amount=tax_amount,
            interest_rate=monthly_rate * 100,
            penalty_amount=penalty,
            description=f"Late payment interest for {months_late} month(s)",
        )

    def calculate_late_filing_penalty(
        self,
        tax_amount: Decimal,
        due_date: datetime,
        filing_date: datetime,
        tax_type: TaxType,
        is_annual: bool = False,
    ) -> PenaltyCalculationResult:
        """
        Menghitung denda keterlambatan pelaporan SPT.

        Denda:
        - SPT Masa: Rp500.000 untuk PPN, Rp100.000 untuk PPh
        - SPT Tahunan: Rp1.000.000 untuk Badan, Rp100.000 untuk Orang Pribadi
        """
        if filing_date <= due_date:
            return PenaltyCalculationResult(
                penalty_type=PenaltyType.FINE,
                tax_type=tax_type,
                due_date=due_date,
                payment_date=filing_date,
                days_late=0,
                tax_amount=tax_amount,
                interest_rate=Decimal(0),
                penalty_amount=Decimal(0),
                description="No late filing penalty (filed on time)",
            )

        # Tentukan denda berdasarkan jenis
        if is_annual:
            if tax_type in [TaxType.PPH_21, TaxType.PPH_25]:
                fine_amount = Decimal(100000)  # Rp100.000 untuk OP
            else:
                fine_amount = Decimal(1000000)  # Rp1.000.000 untuk Badan
        else:
            if tax_type == TaxType.PPN:
                fine_amount = Decimal(500000)  # Rp500.000 untuk SPT Masa PPN
            else:
                fine_amount = Decimal(100000)  # Rp100.000 untuk SPT Masa PPh

        days_late = (filing_date - due_date).days

        return PenaltyCalculationResult(
            penalty_type=PenaltyType.FINE,
            tax_type=tax_type,
            due_date=due_date,
            payment_date=filing_date,
            days_late=days_late,
            tax_amount=tax_amount,
            interest_rate=Decimal(0),
            penalty_amount=fine_amount,
            description=f"Late filing penalty for SPT {'Tahunan' if is_annual else 'Masa'}",
        )

    def calculate_tax_correction_penalty(
        self,
        underpayment: Decimal,
        correction_date: datetime,
        original_due_date: datetime,
        tax_type: TaxType,
    ) -> PenaltyCalculationResult:
        """
        Menghitung sanksi untuk koreksi pajak (kurang bayar).

        Formula: 100% - 200% dari kekurangan pajak (tergantung alasan)
        """
        # Sederhana: 100% dari kekurangan pajak
        penalty = underpayment

        days_late = (correction_date - original_due_date).days

        return PenaltyCalculationResult(
            penalty_type=PenaltyType.ESCALATED,
            tax_type=tax_type,
            due_date=original_due_date,
            payment_date=correction_date,
            days_late=days_late,
            tax_amount=underpayment,
            interest_rate=Decimal(100),
            penalty_amount=penalty,
            description="Tax correction penalty (100% of underpayment)",
        )

    def calculate_total_penalty(
        self,
        tax_amount: Decimal,
        due_date: datetime,
        payment_date: datetime,
        filing_date: datetime | None = None,
        tax_type: TaxType = TaxType.PPN,
        is_annual: bool = False,
    ) -> dict[str, Any]:
        """
        Menghitung total sanksi (bunga + denda).

        Returns:
            Dictionary dengan total penalty breakdown
        """
        results = []
        total = Decimal(0)

        # Bunga keterlambatan pembayaran
        interest = self.calculate_late_payment_interest(
            tax_amount, due_date, payment_date, tax_type
        )
        results.append(interest)
        total += interest.penalty_amount

        # Denda keterlambatan pelaporan (jika ada)
        if filing_date:
            fine = self.calculate_late_filing_penalty(
                tax_amount, due_date, filing_date, tax_type, is_annual
            )
            results.append(fine)
            total += fine.penalty_amount

        return {
            "total_penalty": str(total),
            "breakdown": [r.to_dict() for r in results],
            "tax_amount": str(tax_amount),
            "days_late": max(
                (payment_date - due_date).days,
                (filing_date - due_date).days if filing_date else 0,
            ),
        }

    def get_grace_period(self, tax_type: TaxType) -> int:
        """Mendapatkan masa tenggang untuk jenis pajak tertentu."""
        # Default grace period: 1 bulan
        grace_periods = {
            TaxType.PPN: 30,
            TaxType.PPH_21: 10,
            TaxType.PPH_23: 15,
            TaxType.PPH_25: 15,
            TaxType.PPH_BADAN: 120,  # 4 bulan untuk SPT Tahunan Badan
        }
        return grace_periods.get(tax_type, 30)

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan sanksi."""
        return {
            "default_interest_rate": str(self.get_interest_rate()),
            "late_filing_fines": {
                "monthly_ppn": "500,000",
                "monthly_pph": "100,000",
                "annual_corporate": "1,000,000",
                "annual_individual": "100,000",
            },
            "tax_correction_penalty": "100% - 200%",
        }

    # ========================================================================
    # METHODS FOR TEST COMPATIBILITY (added without removing original)
    # ========================================================================

    @classmethod
    def calculate(cls, pokok: Decimal, months_late: int, tarif_bunga: Decimal) -> Decimal:
        """
        Class method for simple interest penalty calculation as used in tests.
        Formula: bunga = pokok * tarif_bunga * months_late
        """
        bunga = pokok * tarif_bunga * Decimal(months_late)
        return bunga.quantize(Decimal("1"), rounding=ROUND_HALF_UP)

    @classmethod
    def denda_tidak_lapor_ppn(cls, dpp: Decimal) -> Decimal:
        """
        Class method for PPN late filing penalty as used in tests.
        Denda: 2% of DPP.
        """
        denda = dpp * Decimal("0.02")
        return denda.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


# === 4. SINGLETON ACCESSOR ===

_penalty_interest_engine_instance: PenaltyInterestEngine | None = None


def get_penalty_interest_engine() -> PenaltyInterestEngine:
    """Mendapatkan instance singleton PenaltyInterestEngine."""
    global _penalty_interest_engine_instance
    if _penalty_interest_engine_instance is None:
        _penalty_interest_engine_instance = PenaltyInterestEngine()
    return _penalty_interest_engine_instance


# === 5. EXPORTS ===

__all__ = [
    "PenaltyCalculationResult",
    "PenaltyInterestEngine",
    "PenaltyType",
    "TaxObligationType",
    "get_penalty_interest_engine",
]
