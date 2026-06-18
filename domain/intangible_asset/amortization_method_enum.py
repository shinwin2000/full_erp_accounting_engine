#!/usr/bin/env python3
"""
Module: amortization_method_enum.py
Layer: 6 - Domain / Intangible Asset
Responsibility: Enum untuk metode amortisasi aset tak berwujud.

Mendefinisikan metode amortisasi yang dapat digunakan:
- STRAIGHT_LINE: garis lurus
- DECLINING_BALANCE: saldo menurun
- UNITS_OF_PRODUCTION: unit produksi
- NO_AMORTIZATION: tidak diamortisasi (goodwill)
"""

from __future__ import annotations

from enum import Enum


class AmortizationMethod(Enum):
    """Metode amortisasi aset tak berwujud."""

    STRAIGHT_LINE = "straight_line"
    DECLINING_BALANCE = "declining_balance"
    UNITS_OF_PRODUCTION = "units_of_production"
    NO_AMORTIZATION = "no_amortization"
