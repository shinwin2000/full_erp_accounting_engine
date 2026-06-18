#!/usr/bin/env python3
"""
Module: ifrs_15_revenue.py
Layer: 7 - Policy Engine & Standards / IFRS
Responsibility: IFRS 15: Revenue from Contracts with Customers.
               Mendefinisikan aturan untuk pengakuan pendapatan sesuai
               IFRS 15, yang identik dengan PSAK 72. Model 5 langkah
               untuk identifikasi kontrak, kewajiban kinerja, harga
               transaksi, alokasi harga, dan pengakuan pendapatan.

Dependencies:
- standard library (decimal, datetime, logging, dataclass, uuid)
- policy_engine.psak.psak_72_revenue (reuse implementation)

Audit: Setiap pengakuan pendapatan sesuai IFRS 15 dictat.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

# Reuse PSAK 72 implementation since IFRS 15 is identical
from policy_engine.psak.psak_72_revenue import (
    ContractWithCustomer,
    PSAK72ValidationResult,
    RevenueRecognitionTiming,
    TransactionPriceAllocation,
    get_psak72_validator,
)

logger = logging.getLogger(__name__)


# === 1. CONSTANTS & ENUMS ===


class IFRS15Step(Enum):
    """5 langkah IFRS 15."""

    STEP_1_IDENTIFY_CONTRACT = "identify_contract"
    STEP_2_IDENTIFY_OBLIGATIONS = "identify_performance_obligations"
    STEP_3_DETERMINE_PRICE = "determine_transaction_price"
    STEP_4_ALLOCATE_PRICE = "allocate_transaction_price"
    STEP_5_RECOGNIZE_REVENUE = "recognize_revenue_when_obligation_satisfied"


# === 2. IFRS 15 VALIDATOR ===


class IFRS15Validator:
    """
    Validator untuk IFRS 15.

    Business context: Memastikan pendapatan diakui sesuai dengan
    model 5 langkah IFRS 15 (identik dengan PSAK 72).
    """

    def __init__(self):
        self._psak72_validator = get_psak72_validator()

    def create_contract(
        self,
        contract_number: str,
        customer_id: UUID,
        customer_name: str,
        total_price: Decimal,
        currency: str = "IDR",
    ) -> ContractWithCustomer:
        """Membuat kontrak baru."""
        return self._psak72_validator.create_contract(
            contract_number, customer_id, customer_name, total_price, currency
        )

    def add_performance_obligation(
        self,
        contract: ContractWithCustomer,
        description: str,
        stand_alone_price: Decimal,
        satisfaction_timing: RevenueRecognitionTiming,
    ) -> ContractWithCustomer:
        """Menambahkan kewajiban kinerja ke kontrak."""
        return self._psak72_validator.add_performance_obligation(
            contract, description, stand_alone_price, satisfaction_timing
        )

    def allocate_prices(
        self,
        contract: ContractWithCustomer,
    ) -> TransactionPriceAllocation:
        """Mengalokasikan harga transaksi."""
        return self._psak72_validator.allocate_prices(contract)

    def recognize_revenue(
        self,
        contract: ContractWithCustomer,
        obligation_id: UUID,
        satisfaction_date: datetime,
        control_transferred: bool = True,
        progress_measure: Decimal | None = None,
    ) -> tuple[ContractWithCustomer, Decimal]:
        """Mengakui pendapatan."""
        return self._psak72_validator.recognize_revenue(
            contract, obligation_id, satisfaction_date, control_transferred, progress_measure
        )

    def validate_contract_compliance(
        self,
        contract: ContractWithCustomer,
    ) -> PSAK72ValidationResult:
        """Memvalidasi kepatuhan kontrak terhadap IFRS 15."""
        return self._psak72_validator.validate_contract_compliance(contract)

    def get_five_steps(self) -> list[str]:
        """Mendapatkan 5 langkah IFRS 15."""
        return [step.value for step in IFRS15Step]

    def get_requirements_summary(self) -> dict[str, Any]:
        """Mendapatkan ringkasan persyaratan IFRS 15."""
        return {
            "five_steps": self.get_five_steps(),
            "revenue_recognition_timing": [t.value for t in RevenueRecognitionTiming],
        }


class IFRS15:
    """
    Static Helper Class untuk IFRS 15.
    Menyediakan interface statis untuk kompatibilitas pengujian fungsional dasar.
    """

    @staticmethod
    def allocate_transaction_price(
        transaction_price: Decimal, standalone_prices: list[Decimal]
    ) -> list[Decimal]:
        """Mengalokasikan harga transaksi secara proporsional berdasarkan harga jual mandiri."""
        total_standalone = sum(standalone_prices)
        if total_standalone == 0:
            return [Decimal("0")] * len(standalone_prices)

        # Alokasi proporsional (Relative Standalone Selling Price Method)
        return [
            (sp / total_standalone * transaction_price).quantize(transaction_price)
            for sp in standalone_prices
        ]

    @staticmethod
    def recognize_over_time(
        asset_has_alternative_use: bool, entity_has_enforceable_right_to_payment: bool
    ) -> bool:
        """
        Kriteria Pengakuan Pendapatan Sepanjang Waktu (Over Time) sesuai IFRS 15 Paragraf 35(c):
        Aset tidak memiliki alternatif penggunaan bagi entitas DAN entitas memiliki hak atas pembayaran
        yang dapat dipaksakan secara hukum atas penyelesaian kinerja hingga tanggal tersebut.
        """
        return not asset_has_alternative_use and entity_has_enforceable_right_to_payment


# === 3. SINGLETON ACCESSOR ===

_ifrs15_validator_instance: IFRS15Validator | None = None


def get_ifrs15_validator() -> IFRS15Validator:
    """Mendapatkan instance singleton IFRS15Validator."""
    global _ifrs15_validator_instance
    if _ifrs15_validator_instance is None:
        _ifrs15_validator_instance = IFRS15Validator()
    return _ifrs15_validator_instance


# === 4. EXPORTS ===

__all__ = [
    "IFRS15",
    "IFRS15Step",
    "IFRS15Validator",
    "get_ifrs15_validator",
]
