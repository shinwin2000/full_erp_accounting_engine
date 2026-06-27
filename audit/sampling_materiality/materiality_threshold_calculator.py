#!/usr/bin/env python3
"""
Module: materiality_threshold_calculator.py
Layer: Audit (Sampling Materiality)
Responsibility: Menghitung threshold materialitas untuk audit berdasarkan standar
               auditing (ISA 320, PSAK). Materialitas digunakan untuk menentukan
               signifikansi kesalahan dalam populasi audit. Mendukung perhitungan
               untuk overall materiality, performance materiality, dan clearly
               trivial threshold.
Dependencies:
- decimal, math, logging
- config.loader_yaml (lazy import)
- infrastructure.telemetry.structured_json_logging (lazy import)
Audit: Perhitungan materialitas dicatat untuk audit trail keputusan auditor.
"""

from __future__ import annotations

import importlib
import math
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Any

# ============================================================================
# CONSTANTS
# ============================================================================

_logger = None


def _get_logger():
    """Lazy logger initialization from structured logging."""
    global _logger
    if _logger is None:
        mod = importlib.import_module("infrastructure.telemetry.structured_json_logging")
        get_logger_func = mod.get_logger
        _logger = get_logger_func(__name__)
    return _logger


def _load_config(config_path: str) -> dict[str, Any]:
    """Lazy load config from YAML."""
    try:
        mod = importlib.import_module("config.loader_yaml")
        load_yaml_config = mod.load_yaml_config
        config = load_yaml_config(config_path)
        return config.get("materiality", {})
    except Exception:
        return {}


class MaterialityBasis(str, Enum):
    """Basis perhitungan materialitas."""

    TOTAL_ASSETS = "total_assets"
    TOTAL_REVENUE = "total_revenue"
    TOTAL_EQUITY = "total_equity"
    PROFIT_BEFORE_TAX = "profit_before_tax"
    GROSS_PROFIT = "gross_profit"
    CUSTOM = "custom"


# Default percentage ranges per basis (ISA 320 guidance)
DEFAULT_PERCENTAGES = {
    MaterialityBasis.TOTAL_ASSETS: (0.5, 2.0),  # 0.5% - 2% of total assets
    MaterialityBasis.TOTAL_REVENUE: (0.5, 2.0),  # 0.5% - 2% of revenue
    MaterialityBasis.TOTAL_EQUITY: (1.0, 5.0),  # 1% - 5% of equity
    MaterialityBasis.PROFIT_BEFORE_TAX: (5.0, 10.0),  # 5% - 10% of profit before tax
    MaterialityBasis.GROSS_PROFIT: (1.0, 5.0),  # 1% - 5% of gross profit
}

DEFAULT_PERFORMANCE_MATERIALITY_PERCENT = 75.0  # 75% of overall materiality
DEFAULT_CLEARLY_TRIVIAL_PERCENT = 5.0  # 5% of overall materiality


# ============================================================================
# EXCEPTIONS
# ============================================================================


class MaterialityError(Exception):
    """Base exception untuk materiality calculator."""

    pass


class InvalidBasisError(MaterialityError):
    """Basis materialitas tidak valid."""

    pass


# ============================================================================
# MATERIALITY THRESHOLD CALCULATOR
# ============================================================================


class MaterialityThresholdCalculator:
    """
    Kalkulator threshold materialitas audit.

    Fitur:
    - Menghitung overall materiality berdasarkan basis yang dipilih
    - Menghitung performance materiality (untuk sampling)
    - Menghitung clearly trivial threshold
    - Mendukung custom basis dan persentase
    - Menyimpan history perhitungan untuk audit trail
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = _load_config(config_path)
        self._history: list = []

    def _round_to_materiality(self, value: Decimal) -> Decimal:
        """Membulatkan nilai ke angka signifikan material (misal: 100,000)."""
        if value == 0:
            return Decimal(0)
        # Tentukan faktor pembulatan berdasarkan magnitude
        magnitude = 10 ** (math.floor(math.log10(float(abs(value)))) - 2)
        magnitude = max(magnitude, 1)
        return (value / magnitude).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * Decimal(
            magnitude
        )

    def calculate_overall_materiality(
        self,
        basis_value: Decimal,
        basis_type: MaterialityBasis,
        custom_percentage: float | None = None,
    ) -> Decimal:
        """
        Menghitung overall materiality.

        Args:
            basis_value: Nilai basis (total aset, revenue, dll.)
            basis_type: Jenis basis materialitas
            custom_percentage: Persentase kustom (override default range)

        Returns:
            Overall materiality (rounded)
        """
        if basis_value <= 0:
            raise MaterialityError(f"Basis value must be positive, got {basis_value}")

        # Tentukan persentase
        if custom_percentage is not None:
            percentage = Decimal(str(custom_percentage)) / Decimal(100)
        else:
            min_pct, max_pct = DEFAULT_PERCENTAGES.get(basis_type, (0.5, 2.0))
            # Gunakan mid-point atau bisa disesuaikan dengan risk assessment
            percentage = Decimal(str((min_pct + max_pct) / 2)) / Decimal(100)

        overall = basis_value * percentage
        rounded = self._round_to_materiality(overall)

        # Simpan ke history
        self._history.append(
            {
                "calculation_type": "overall",
                "basis_type": basis_type.value,
                "basis_value": float(basis_value),
                "percentage": float(percentage * 100),
                "result": float(rounded),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        logger = _get_logger()
        logger.info(
            f"Overall materiality calculated: {rounded:,.2f} based on {basis_type.value} = {basis_value:,.2f}"
        )
        return rounded

    def calculate_performance_materiality(
        self, overall_materiality: Decimal, percentage: float | None = None
    ) -> Decimal:
        """
        Menghitung performance materiality (untuk sampling).
        Performance materiality lebih rendah dari overall materiality
        untuk mengurangi risiko deteksi.
        """
        if overall_materiality <= 0:
            raise MaterialityError(
                f"Overall materiality must be positive, got {overall_materiality}"
            )

        pct = percentage or self.config.get(
            "performance_materiality_percent", DEFAULT_PERFORMANCE_MATERIALITY_PERCENT
        )
        performance = overall_materiality * Decimal(str(pct)) / Decimal(100)
        rounded = self._round_to_materiality(performance)

        self._history.append(
            {
                "calculation_type": "performance",
                "overall_materiality": float(overall_materiality),
                "percentage": pct,
                "result": float(rounded),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        logger = _get_logger()
        logger.info(f"Performance materiality calculated: {rounded:,.2f} ({pct}% of overall)")
        return rounded

    def calculate_clearly_trivial_threshold(
        self, overall_materiality: Decimal, percentage: float | None = None
    ) -> Decimal:
        """
        Menghitung clearly trivial threshold (posting threshold).
        Kesalahan di bawah threshold ini dianggap tidak material secara individual.
        """
        if overall_materiality <= 0:
            raise MaterialityError(
                f"Overall materiality must be positive, got {overall_materiality}"
            )

        pct = percentage or self.config.get(
            "clearly_trivial_percent", DEFAULT_CLEARLY_TRIVIAL_PERCENT
        )
        trivial = overall_materiality * Decimal(str(pct)) / Decimal(100)
        # Tidak perlu rounding agresif karena ini batas bawah
        rounded = trivial.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        self._history.append(
            {
                "calculation_type": "clearly_trivial",
                "overall_materiality": float(overall_materiality),
                "percentage": pct,
                "result": float(rounded),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

        logger = _get_logger()
        logger.info(f"Clearly trivial threshold calculated: {rounded:,.2f} ({pct}% of overall)")
        return rounded

    def calculate_all_thresholds(
        self,
        basis_value: Decimal,
        basis_type: MaterialityBasis,
        custom_overall_pct: float | None = None,
        performance_pct: float | None = None,
        trivial_pct: float | None = None,
    ) -> dict[str, Decimal]:
        """
        Menghitung semua threshold materialitas sekaligus.

        Returns:
            Dictionary dengan keys: overall, performance, clearly_trivial
        """
        overall = self.calculate_overall_materiality(basis_value, basis_type, custom_overall_pct)
        performance = self.calculate_performance_materiality(overall, performance_pct)
        trivial = self.calculate_clearly_trivial_threshold(overall, trivial_pct)

        return {
            "overall_materiality": overall,
            "performance_materiality": performance,
            "clearly_trivial_threshold": trivial,
        }

    def is_material(self, error_amount: Decimal, materiality_threshold: Decimal) -> bool:
        """
        Mengevaluasi apakah suatu kesalahan material.
        """
        return abs(error_amount) >= materiality_threshold

    def is_trivial(self, error_amount: Decimal, trivial_threshold: Decimal) -> bool:
        """
        Mengevaluasi apakah suatu kesalahan trivial (tidak perlu dikoreksi).
        """
        return abs(error_amount) < trivial_threshold

    def get_history(self, limit: int = 20) -> list:
        """Mendapatkan history perhitungan materialitas."""
        return self._history[-limit:]

    def clear_history(self) -> None:
        """Menghapus history."""
        self._history.clear()
        logger = _get_logger()
        logger.info("Materiality calculation history cleared")


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_materiality_calculator: MaterialityThresholdCalculator | None = None


def get_materiality_calculator() -> MaterialityThresholdCalculator:
    """Get singleton instance of MaterialityThresholdCalculator."""
    global _materiality_calculator
    if _materiality_calculator is None:
        _materiality_calculator = MaterialityThresholdCalculator()
    return _materiality_calculator


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "InvalidBasisError",
    "MaterialityBasis",
    "MaterialityError",
    "MaterialityThresholdCalculator",
    "get_materiality_calculator",
]
