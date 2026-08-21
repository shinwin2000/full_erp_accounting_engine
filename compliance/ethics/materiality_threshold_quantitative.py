#!/usr/bin/env python3
"""
Module: materiality_threshold_quantitative.py
Layer: Compliance / Ethics

Responsibility:
    Ambang batas materialitas berdasarkan persentase terhadap laporan keuangan,
    sesuai PSAK 25 dan praktik audit. Mendukung perhitungan benchmark (laba, aset,
    ekuitas, pendapatan), toleransi kesalahan, multiple materiality levels
    (planning materiality, performance materiality, clearly trivial threshold),
    serta sensitivity analysis.

Dependencies:
    - datetime, decimal, enum, typing, json, hashlib, logging

Audit:
    Setiap perhitungan materialitas dicatat dengan timestamp dan hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import ClassVar

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================
class MaterialityType(Enum):
    PLANNING_MATERIALITY = "planning_materiality"
    PERFORMANCE_MATERIALITY = "performance_materiality"
    CLEARLY_TRIVIAL = "clearly_trivial"
    SPECIFIC_MATERIALITY = "specific_materiality"


class BenchmarkType(Enum):
    REVENUE = "revenue"
    TOTAL_ASSETS = "total_assets"
    TOTAL_EQUITY = "total_equity"
    PROFIT_BEFORE_TAX = "profit_before_tax"
    NET_PROFIT = "net_profit"
    GROSS_PROFIT = "gross_profit"
    OPERATING_CASH_FLOW = "operating_cash_flow"


# ============================================================================
# Data Classes
# ============================================================================
class MaterialityThreshold:
    def __init__(
        self,
        materiality_type: MaterialityType,
        benchmark: BenchmarkType,
        benchmark_value: Decimal,
        percentage: Decimal,
        threshold_value: Decimal,
        calculated_at: datetime,
        calculated_by: str,
    ):
        self.materiality_type = materiality_type
        self.benchmark = benchmark
        self.benchmark_value = benchmark_value
        self.percentage = percentage
        self.threshold_value = threshold_value
        self.calculated_at = calculated_at
        self.calculated_by = calculated_by
        self._hash = self._compute_hash()

    def _compute_hash(self) -> str:
        data = {
            "type": self.materiality_type.value,
            "benchmark": self.benchmark.value,
            "percentage": str(self.percentage),
            "threshold": str(self.threshold_value),
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "materiality_type": self.materiality_type.value,
            "benchmark": self.benchmark.value,
            "benchmark_value": str(self.benchmark_value),
            "percentage": float(self.percentage),
            "threshold_value": str(self.threshold_value),
            "calculated_at": self.calculated_at.isoformat(),
            "calculated_by": self.calculated_by,
            "hash": self._hash,
        }


class MaterialityAssessment:
    def __init__(self, error_amount: Decimal, threshold: MaterialityThreshold):
        self.error_amount = error_amount
        self.threshold = threshold
        self.is_material = error_amount >= threshold.threshold_value
        self.percentage_of_threshold = (
            (error_amount / threshold.threshold_value * 100).quantize(Decimal("0.01"))
            if threshold.threshold_value != 0
            else Decimal("0")
        )
        self.assessed_at = datetime.utcnow()

    def to_dict(self) -> dict:
        return {
            "error_amount": str(self.error_amount),
            "threshold": str(self.threshold.threshold_value),
            "is_material": self.is_material,
            "percentage_of_threshold": float(self.percentage_of_threshold),
        }


# ============================================================================
# QuantitativeMateriality Core
# ============================================================================
class QuantitativeMateriality:
    """
    Perhitungan materialitas kuantitatif berdasarkan benchmark keuangan.
    """

    DEFAULT_PERCENTAGES: ClassVar[dict[BenchmarkType, Decimal]] = {
        BenchmarkType.REVENUE: Decimal("0.005"),  # 0.5%
        BenchmarkType.TOTAL_ASSETS: Decimal("0.005"),  # 0.5%
        BenchmarkType.TOTAL_EQUITY: Decimal("0.01"),  # 1%
        BenchmarkType.PROFIT_BEFORE_TAX: Decimal("0.05"),  # 5%
        BenchmarkType.NET_PROFIT: Decimal("0.05"),  # 5%
        BenchmarkType.GROSS_PROFIT: Decimal("0.03"),  # 3%
        BenchmarkType.OPERATING_CASH_FLOW: Decimal("0.05"),  # 5%
    }

    PERFORMANCE_MATERIALITY_FACTOR: ClassVar[Decimal] = Decimal("0.75")  # 75% of planning materiality
    CLEARLY_TRIVIAL_FACTOR: ClassVar[Decimal] = Decimal("0.05")  # 5% of planning materiality

    def __init__(self, custom_percentages: dict[BenchmarkType, Decimal] | None = None):
        self._percentages = custom_percentages or self.DEFAULT_PERCENTAGES.copy()
        self._calculations: list[MaterialityThreshold] = []

    def set_percentage(self, benchmark: BenchmarkType, percentage: Decimal) -> None:
        if percentage < 0 or percentage > 1:
            raise ValueError(f"Percentage must be between 0 and 1, got {percentage}")
        self._percentages[benchmark] = percentage

    def get_benchmark_value(
        self, financial_data: dict[BenchmarkType, Decimal], benchmark: BenchmarkType
    ) -> Decimal:
        value = financial_data.get(benchmark, Decimal("0"))
        if value < 0:
            # Use absolute value for loss scenarios; typical audit: 5% of absolute value
            return abs(value)
        return value

    def calculate_planning_materiality(
        self,
        financial_data: dict[BenchmarkType, Decimal],
        primary_benchmark: BenchmarkType = BenchmarkType.PROFIT_BEFORE_TAX,
        fallback_benchmark: BenchmarkType = BenchmarkType.TOTAL_ASSETS,
        calculated_by: str = "system",
    ) -> MaterialityThreshold:
        """
        Hitung overall planning materiality (materialitas perencanaan).
        """
        primary_value = self.get_benchmark_value(financial_data, primary_benchmark)
        if primary_value > 0:
            benchmark = primary_benchmark
            benchmark_value = primary_value
        else:
            benchmark = fallback_benchmark
            benchmark_value = self.get_benchmark_value(financial_data, fallback_benchmark)
            if benchmark_value == 0:
                raise ValueError("No valid benchmark with positive value found")

        percentage = self._percentages[benchmark]
        threshold = (benchmark_value * percentage).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)

        threshold_obj = MaterialityThreshold(
            materiality_type=MaterialityType.PLANNING_MATERIALITY,
            benchmark=benchmark,
            benchmark_value=benchmark_value,
            percentage=percentage,
            threshold_value=threshold,
            calculated_at=datetime.utcnow(),
            calculated_by=calculated_by,
        )
        self._calculations.append(threshold_obj)
        return threshold_obj

    def calculate_performance_materiality(
        self,
        planning_materiality: MaterialityThreshold,
        calculated_by: str = "system",
    ) -> MaterialityThreshold:
        """
        Hitung performance materiality (75% dari planning materiality).
        """
        threshold_value = (
            planning_materiality.threshold_value * self.PERFORMANCE_MATERIALITY_FACTOR
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        threshold_obj = MaterialityThreshold(
            materiality_type=MaterialityType.PERFORMANCE_MATERIALITY,
            benchmark=planning_materiality.benchmark,
            benchmark_value=planning_materiality.benchmark_value,
            percentage=planning_materiality.percentage * self.PERFORMANCE_MATERIALITY_FACTOR,
            threshold_value=threshold_value,
            calculated_at=datetime.utcnow(),
            calculated_by=calculated_by,
        )
        self._calculations.append(threshold_obj)
        return threshold_obj

    def calculate_clearly_trivial_threshold(
        self,
        planning_materiality: MaterialityThreshold,
        calculated_by: str = "system",
    ) -> MaterialityThreshold:
        """
        Hitung clearly trivial threshold (5% dari planning materiality).
        """
        threshold_value = (
            planning_materiality.threshold_value * self.CLEARLY_TRIVIAL_FACTOR
        ).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        threshold_obj = MaterialityThreshold(
            materiality_type=MaterialityType.CLEARLY_TRIVIAL,
            benchmark=planning_materiality.benchmark,
            benchmark_value=planning_materiality.benchmark_value,
            percentage=planning_materiality.percentage * self.CLEARLY_TRIVIAL_FACTOR,
            threshold_value=threshold_value,
            calculated_at=datetime.utcnow(),
            calculated_by=calculated_by,
        )
        self._calculations.append(threshold_obj)
        return threshold_obj

    def calculate_specific_materiality(
        self,
        benchmark: BenchmarkType,
        benchmark_value: Decimal,
        percentage: Decimal | None = None,
        calculated_by: str = "system",
    ) -> MaterialityThreshold:
        """
        Hitung materialitas untuk akun atau kelas transaksi spesifik.
        """
        pct = percentage or self._percentages.get(benchmark, Decimal("0.01"))
        threshold = (benchmark_value * pct).quantize(Decimal("0"), rounding=ROUND_HALF_EVEN)
        threshold_obj = MaterialityThreshold(
            materiality_type=MaterialityType.SPECIFIC_MATERIALITY,
            benchmark=benchmark,
            benchmark_value=benchmark_value,
            percentage=pct,
            threshold_value=threshold,
            calculated_at=datetime.utcnow(),
            calculated_by=calculated_by,
        )
        self._calculations.append(threshold_obj)
        return threshold_obj

    def assess_error(
        self,
        error_amount: Decimal,
        threshold: MaterialityThreshold,
    ) -> MaterialityAssessment:
        return MaterialityAssessment(error_amount, threshold)

    def is_material(
        self,
        error_amount: Decimal,
        financial_data: dict[BenchmarkType, Decimal],
        primary_benchmark: BenchmarkType = BenchmarkType.PROFIT_BEFORE_TAX,
        fallback_benchmark: BenchmarkType = BenchmarkType.TOTAL_ASSETS,
    ) -> tuple[bool, MaterialityThreshold]:
        """
        Convenience method: hitung planning materiality lalu bandingkan dengan error.
        """
        planning = self.calculate_planning_materiality(
            financial_data, primary_benchmark, fallback_benchmark
        )
        assessment = self.assess_error(error_amount, planning)
        return assessment.is_material, planning

    def get_all_calculations(self) -> list[MaterialityThreshold]:
        return self._calculations

    def sensitivity_analysis(
        self,
        financial_data: dict[BenchmarkType, Decimal],
        percentage_variations: list[Decimal] | None = None,
    ) -> dict:
        """
        Analisis sensitivitas terhadap perubahan persentase benchmark.
        """
        if percentage_variations is None:
            percentage_variations = [
                Decimal("0.002"),
                Decimal("0.005"),
                Decimal("0.01"),
                Decimal("0.02"),
            ]
        # FIX: tambahkan anotasi tipe untuk menghindari error mypy
        results: dict[str, float | None] = {}
        for pct in percentage_variations:
            temp_percentages = self._percentages.copy()
            for bm in [
                BenchmarkType.PROFIT_BEFORE_TAX,
                BenchmarkType.REVENUE,
                BenchmarkType.TOTAL_ASSETS,
            ]:
                temp_percentages[bm] = pct
            temp = QuantitativeMateriality(custom_percentages=temp_percentages)
            try:
                mat = temp.calculate_planning_materiality(financial_data)
                results[str(pct)] = float(mat.threshold_value)
            except ValueError:
                results[str(pct)] = None
        return results

    def generate_report(self) -> dict:
        total = len(self._calculations)
        if total == 0:
            return {"total_calculations": 0}
        by_type = {
            t.value: len([c for c in self._calculations if c.materiality_type == t])
            for t in MaterialityType
        }
        return {
            "total_calculations": total,
            "by_type": by_type,
            "latest": self._calculations[-1].to_dict() if self._calculations else None,
        }

    def to_json(self, file_path: str) -> None:
        data = {
            "report": self.generate_report(),
            "calculations": [c.to_dict() for c in self._calculations],
        }
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)


# ============================================================================
# Demo
# ============================================================================
if __name__ == "__main__":
    qm = QuantitativeMateriality()
    financials = {
        BenchmarkType.PROFIT_BEFORE_TAX: Decimal("100_000_000_000"),
        BenchmarkType.REVENUE: Decimal("500_000_000_000"),
        BenchmarkType.TOTAL_ASSETS: Decimal("800_000_000_000"),
        BenchmarkType.TOTAL_EQUITY: Decimal("300_000_000_000"),
    }
    planning = qm.calculate_planning_materiality(financials)
    print(f"Planning materiality: {planning.threshold_value:,.0f}")

    performance = qm.calculate_performance_materiality(planning)
    print(f"Performance materiality: {performance.threshold_value:,.0f}")

    trivial = qm.calculate_clearly_trivial_threshold(planning)
    print(f"Clearly trivial: {trivial.threshold_value:,.0f}")

    error = Decimal("2_000_000_000")
    assessment = qm.assess_error(error, planning)
    print(
        f"Error {error:,.0f} is material? {assessment.is_material} ({assessment.percentage_of_threshold:.2f}% of threshold)"
    )

    sensitivity = qm.sensitivity_analysis(financials)
    print("Sensitivity:", sensitivity)

    qm.to_json("quantitative_materiality.json")
