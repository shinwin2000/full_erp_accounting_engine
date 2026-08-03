#!/usr/bin/env python3
"""
Module: audit_sampling_statistical.py
Layer: Audit (Sampling Materiality)
Responsibility: Implementasi statistical sampling untuk audit. Menentukan ukuran
               sampel berdasarkan populasi, confidence level, expected error,
               dan tolerable error. Mendukung metode random sampling, systematic
               sampling, dan stratified sampling. Juga menyediakan fungsi untuk
               mengekstrapolasi error dari sampel ke populasi.
Dependencies:
- math, random, decimal, logging
- config.loader_yaml (lazy import)
- infrastructure.telemetry.structured_json_logging (lazy import)
Audit: Sampling methodology dicatat untuk audit trail dan review oleh auditor.

Perbaikan presisi:
    - Menggunakan Decimal untuk semua perhitungan margin dan error projection.
    - Menghilangkan konversi float -> Decimal yang tidak aman.
    - Menggunakan Decimal.sqrt() untuk akurasi.
"""

from __future__ import annotations

import importlib
import math
import random
from decimal import Decimal
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
        return config.get("sampling", {})
    except Exception:
        return {}


class SamplingMethod(str, Enum):
    """Metode sampling yang didukung."""

    RANDOM = "random"
    SYSTEMATIC = "systematic"
    STRATIFIED = "stratified"
    MONETARY_UNIT = "monetary_unit"  # MUS


class SamplingConfidenceLevel:
    """Z-scores untuk confidence level umum."""

    CONFIDENCE_90 = 1.645
    CONFIDENCE_95 = 1.96
    CONFIDENCE_99 = 2.576


# Default parameters
DEFAULT_CONFIDENCE_LEVEL = 95  # 95%
DEFAULT_EXPECTED_ERROR_PERCENT = 1.0  # 1%
DEFAULT_TOLERABLE_ERROR_PERCENT = 5.0  # 5%
DEFAULT_POPULATION_SIZE_FOR_INFINITE = 10000


# ============================================================================
# EXCEPTIONS
# ============================================================================


class SamplingError(Exception):
    """Base exception untuk sampling."""

    pass


class InvalidSamplingMethodError(SamplingError):
    """Metode sampling tidak valid."""

    pass


class InvalidPopulationError(SamplingError):
    """Populasi tidak valid."""

    pass


# ============================================================================
# STATISTICAL SAMPLING ENGINE
# ============================================================================


class AuditStatisticalSampling:
    """
    Mesin sampling statistik untuk audit.

    Fitur:
    - Menentukan ukuran sampel berdasarkan parameter audit
    - Random sampling dengan atau tanpa pengembalian
    - Systematic sampling dengan interval tetap
    - Stratified sampling (kelompok berdasarkan nilai)
    - Monetary Unit Sampling (MUS) untuk populasi moneter
    - Ekstrapolasi error dari sampel ke populasi
    """

    def __init__(self, config_path: str = "config_files/audit_config.yaml"):
        self.config = _load_config(config_path)
        self._last_sample: list | None = None
        self._sampling_params: dict[str, Any] = {}

    def calculate_sample_size(
        self,
        population_size: int,
        confidence_level: int = DEFAULT_CONFIDENCE_LEVEL,
        expected_error_percent: float = DEFAULT_EXPECTED_ERROR_PERCENT,
        tolerable_error_percent: float = DEFAULT_TOLERABLE_ERROR_PERCENT,
        use_finite_correction: bool = True,
    ) -> int:
        """
        Menghitung ukuran sampel yang diperlukan.

        Args:
            population_size: Jumlah total item dalam populasi
            confidence_level: Tingkat kepercayaan (90, 95, atau 99)
            expected_error_percent: Persentase error yang diharapkan
            tolerable_error_percent: Persentase error yang dapat ditoleransi
            use_finite_correction: Gunakan finite population correction

        Returns:
            Ukuran sampel yang disarankan
        """
        if population_size <= 0:
            raise InvalidPopulationError(f"Population size must be positive, got {population_size}")

        # Get z-score
        if confidence_level == 90:
            z = SamplingConfidenceLevel.CONFIDENCE_90
        elif confidence_level == 95:
            z = SamplingConfidenceLevel.CONFIDENCE_95
        elif confidence_level == 99:
            z = SamplingConfidenceLevel.CONFIDENCE_99
        else:
            raise SamplingError(f"Unsupported confidence level: {confidence_level}")

        p = expected_error_percent / 100.0
        d = tolerable_error_percent / 100.0

        # Sample size formula (infinite population)
        sample_size_infinite = (z**2 * p * (1 - p)) / (d**2)
        sample_size = math.ceil(sample_size_infinite)

        # Finite population correction
        if (
            use_finite_correction
            and sample_size > 0
            and population_size < DEFAULT_POPULATION_SIZE_FOR_INFINITE
        ):
            sample_size = math.ceil(sample_size / (1 + (sample_size - 1) / population_size))

        self._sampling_params = {
            "population_size": population_size,
            "confidence_level": confidence_level,
            "expected_error_percent": expected_error_percent,
            "tolerable_error_percent": tolerable_error_percent,
            "sample_size": sample_size,
            "method": "proportion",
        }

        logger = _get_logger()
        logger.info(f"Calculated sample size: {sample_size} from population of {population_size}")
        return sample_size

    def calculate_monetary_unit_sample_size(
        self,
        population_value: Decimal,
        confidence_level: int = DEFAULT_CONFIDENCE_LEVEL,
        expected_error_percent: float = DEFAULT_EXPECTED_ERROR_PERCENT,
        tolerable_error_percent: float = DEFAULT_TOLERABLE_ERROR_PERCENT,
    ) -> int:
        """
        Menghitung ukuran sampel untuk Monetary Unit Sampling (MUS).

        Args:
            population_value: Total nilai populasi (misal: total saldo piutang)
            confidence_level: Tingkat kepercayaan
            expected_error_percent: Persentase error yang diharapkan
            tolerable_error_percent: Persentase error yang dapat ditoleransi

        Returns:
            Ukuran sampel
        """
        if population_value <= 0:
            raise InvalidPopulationError(
                f"Population value must be positive, got {population_value}"
            )

        # MUS menggunakan formula dari AICPA
        if confidence_level == 90:
            reliability_factor = 2.31  # untuk 90% confidence
        elif confidence_level == 95:
            reliability_factor = 3.0  # untuk 95% confidence
        elif confidence_level == 99:
            reliability_factor = 4.61  # untuk 99% confidence
        else:
            reliability_factor = 3.0

        tolerable_misstatement = population_value * Decimal(str(tolerable_error_percent / 100.0))
        expected_misstatement = population_value * Decimal(str(expected_error_percent / 100.0))

        # Sample size = (Reliability Factor * Population Value) / Tolerable Misstatement
        # Gunakan Decimal untuk presisi
        sample_size_numerator = Decimal(reliability_factor) * population_value
        sample_size_denominator = tolerable_misstatement - expected_misstatement
        if sample_size_denominator <= 0:
            raise SamplingError("Tolerable misstatement must exceed expected misstatement")

        # Convert to float only for ceil (then back to int)
        sample_size = math.ceil(float(sample_size_numerator / sample_size_denominator))

        self._sampling_params = {
            "population_value": str(population_value),
            "confidence_level": confidence_level,
            "expected_error_percent": expected_error_percent,
            "tolerable_error_percent": tolerable_error_percent,
            "sample_size": sample_size,
            "method": "monetary_unit",
        }

        logger = _get_logger()
        logger.info(
            f"Calculated MUS sample size: {sample_size} for population value {population_value:,.2f}"
        )
        return sample_size

    def random_sampling(
        self, population: list, sample_size: int, with_replacement: bool = False
    ) -> list:
        """
        Mengambil sampel secara acak dari populasi.

        Args:
            population: List populasi
            sample_size: Jumlah sampel yang diinginkan
            with_replacement: Apakah dengan pengembalian

        Returns:
            List sampel
        """
        if len(population) < sample_size and not with_replacement:
            raise SamplingError(
                f"Population size {len(population)} is less than sample size {sample_size}"
            )

        if with_replacement:
            sample = random.choices(population, k=sample_size)
        else:
            sample = random.sample(population, sample_size)

        self._last_sample = sample
        logger = _get_logger()
        logger.info(
            f"Random sampling: {len(sample)} items selected from population of {len(population)}"
        )
        return sample

    def systematic_sampling(
        self, population: list, sample_size: int, start_index: int | None = None
    ) -> list:
        """
        Mengambil sampel secara sistematis (interval tetap).

        Args:
            population: List populasi
            sample_size: Jumlah sampel yang diinginkan
            start_index: Indeks awal (random jika tidak ditentukan)

        Returns:
            List sampel
        """
        pop_size = len(population)
        if pop_size < sample_size:
            raise SamplingError(
                f"Population size {pop_size} is less than sample size {sample_size}"
            )

        interval = pop_size / sample_size
        if start_index is None:
            start_index = random.randint(0, int(interval) - 1)

        sample = []
        for i in range(sample_size):
            idx = int(start_index + i * interval)
            if idx >= pop_size:
                break
            sample.append(population[idx])

        self._last_sample = sample
        logger = _get_logger()
        logger.info(
            f"Systematic sampling: {len(sample)} items selected with interval {interval:.2f}"
        )
        return sample

    def stratified_sampling(
        self, strata: list[dict], sample_size: int, allocation_method: str = "proportional"
    ) -> dict[str, list]:
        """
        Stratified sampling berdasarkan strata.

        Args:
            strata: List dictionary dengan keys: "name", "items", "weight"
            sample_size: Total ukuran sampel
            allocation_method: "proportional" atau "optimal"

        Returns:
            Dictionary mapping stratum name to sample list
        """
        total_population = sum(len(s["items"]) for s in strata)

        # Alokasi sampel per stratum
        allocation = {}
        for stratum in strata:
            stratum_size = len(stratum["items"])
            if allocation_method == "proportional":
                allocated = round(sample_size * stratum_size / total_population)
            else:  # optimal - alokasi lebih besar ke stratum dengan variansi tinggi
                weight = stratum.get("weight", 1.0)
                allocated = round(sample_size * weight * stratum_size / total_population)
            allocation[stratum["name"]] = max(1, allocated) if stratum_size > 0 else 0

        # Adjust for rounding
        total_allocated = sum(allocation.values())
        if total_allocated != sample_size and total_allocated > 0:
            # Adjust largest stratum
            max_stratum = max(allocation.items(), key=lambda x: x[1])
            allocation[max_stratum[0]] += sample_size - total_allocated

        # Take samples
        result = {}
        for stratum in strata:
            name = stratum["name"]
            items = stratum["items"]
            allocated = allocation.get(name, 0)
            if allocated > 0 and len(items) >= allocated:
                result[name] = random.sample(items, allocated)
            elif allocated > 0:
                result[name] = items
            else:
                result[name] = []

        self._last_sample = result
        logger = _get_logger()
        logger.info(
            f"Stratified sampling: {sample_size} items allocated across {len(strata)} strata"
        )
        return result

    def monetary_unit_sampling(self, items: list[dict], sample_size: int) -> list[dict]:
        """
        Monetary Unit Sampling (MUS) - probability proportional to size.

        Args:
            items: List dictionary dengan keys: "id", "value" (Decimal)
            sample_size: Ukuran sampel

        Returns:
            List item yang terpilih
        """
        if not items:
            return []

        # Calculate cumulative values using Decimal to preserve precision
        cumulative = Decimal(0)
        cum_values = []
        for item in items:
            value = item["value"]
            # Ensure value is Decimal (or convertible)
            if not isinstance(value, Decimal):
                value = Decimal(str(value))
            cumulative += value
            cum_values.append(cumulative)

        total_value = cumulative
        if total_value <= 0:
            raise SamplingError("Total population value must be positive")

        # Convert total_value to float only for interval calculation (required by random.uniform)
        total_value_float = float(total_value)
        interval = total_value_float / sample_size

        # Random start
        start = random.uniform(0, interval)

        selected = []
        selected_indices = set()

        for i in range(sample_size):
            sampling_point = Decimal(str(start + i * interval))
            # Find item containing this sampling point
            for idx, cum_val in enumerate(cum_values):
                if cum_val >= sampling_point and idx not in selected_indices:
                    selected.append(items[idx])
                    selected_indices.add(idx)
                    break

        self._last_sample = selected
        logger = _get_logger()
        logger.info(
            f"Monetary Unit Sampling: {len(selected)} items selected from {len(items)} items"
        )
        return selected

    def project_error(
        self,
        sample_errors: list[Decimal],
        sample_size: int,
        population_size: int,
        confidence_level: int = 95,
    ) -> dict[str, Any]:
        """
        Mengekstrapolasi error dari sampel ke populasi.

        Args:
            sample_errors: List error yang ditemukan di sampel (nilai absolut)
            sample_size: Jumlah sampel yang diambil
            population_size: Jumlah total populasi
            confidence_level: Tingkat kepercayaan untuk confidence interval

        Returns:
            Dictionary dengan proyeksi error, upper bound, dan interval kepercayaan
        """
        if not sample_errors:
            return {
                "projected_error": Decimal(0),
                "error_rate": 0.0,
                "upper_bound": Decimal(0),
                "lower_bound": Decimal(0),
                "confidence_level": confidence_level,
            }

        # Calculate statistics menggunakan Decimal
        total_error = sum(sample_errors)  # Decimal
        avg_error = total_error / len(sample_errors)  # Decimal

        # Project to population
        projected_error = avg_error * population_size / sample_size

        # Calculate variance and standard deviation dengan Decimal
        if len(sample_errors) > 1:
            variance = sum((e - avg_error) ** 2 for e in sample_errors) / (len(sample_errors) - 1)
        else:
            variance = Decimal(0)

        # Standard deviation (Decimal.sqrt() available in Python 3.11+)
        std_dev = variance.sqrt() if variance > 0 else Decimal(0)

        # Standard error
        std_error = std_dev / Decimal(sample_size).sqrt()

        # Z-score for confidence level
        if confidence_level == 90:
            z = Decimal(SamplingConfidenceLevel.CONFIDENCE_90)
        elif confidence_level == 95:
            z = Decimal(SamplingConfidenceLevel.CONFIDENCE_95)
        elif confidence_level == 99:
            z = Decimal(SamplingConfidenceLevel.CONFIDENCE_99)
        else:
            z = Decimal('1.96')

        # Margin of error (semua Decimal)
        margin = z * std_error * Decimal(population_size) / Decimal(sample_size)

        upper_bound = projected_error + margin
        lower_bound = max(Decimal(0), projected_error - margin)

        # Error rate (percentage) - non-moneter, tetap float
        error_rate = (len([e for e in sample_errors if e > 0]) / sample_size) * 100

        result = {
            "projected_error": projected_error,
            "error_rate": error_rate,
            "upper_bound": upper_bound,
            "lower_bound": lower_bound,
            "margin_of_error": margin,
            "confidence_level": confidence_level,
            "sample_size": sample_size,
            "population_size": population_size,
        }

        logger = _get_logger()
        logger.info(
            f"Error projection: projected {projected_error:,.2f}, upper bound {upper_bound:,.2f}"
        )
        return result

    def project_monetary_unit_error(
        self, sample_items: list[dict], population_value: Decimal, sample_size: int
    ) -> dict[str, Any]:
        """
        Mengekstrapolasi error untuk Monetary Unit Sampling.

        Args:
            sample_items: List item sampel dengan keys "value" (Decimal) dan "error_amount" (Decimal)
            population_value: Total nilai populasi
            sample_size: Ukuran sampel

        Returns:
            Proyeksi error dan upper bound
        """
        if not sample_items:
            return {
                "projected_error": Decimal(0),
                "upper_bound": Decimal(0),
                "basic_precision": Decimal(0),
            }

        # Misstatement ratio per item (tainting) - tetap menggunakan Decimal
        tainting = []
        for item in sample_items:
            value = item["value"]
            if not isinstance(value, Decimal):
                value = Decimal(str(value))
            error = item.get("error_amount", Decimal(0))
            if not isinstance(error, Decimal):
                error = Decimal(str(error))

            if value > 0:
                tainting.append(error / value)
            else:
                tainting.append(Decimal(0))

        # Average tainting
        avg_tainting = sum(tainting) / len(tainting)

        # Projected error
        projected_error = avg_tainting * population_value

        # Basic precision (reliability factor at 95% confidence = 3.0)
        reliability_factor = Decimal('3.0')
        sampling_interval = population_value / Decimal(sample_size)
        basic_precision = reliability_factor * sampling_interval

        # Upper bound (incremental allowance)
        # Simplified: upper bound = projected error + basic precision
        upper_bound = projected_error + basic_precision

        return {
            "projected_error": projected_error,
            "upper_bound": upper_bound,
            "basic_precision": basic_precision,
            "sample_size": sample_size,
            "population_value": population_value,
        }

    def get_last_sample(self) -> list | None:
        """Mendapatkan sampel terakhir yang diambil."""
        return self._last_sample

    def get_sampling_params(self) -> dict[str, Any]:
        """Mendapatkan parameter sampling terakhir."""
        return self._sampling_params


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_audit_sampling: AuditStatisticalSampling | None = None


def get_audit_sampling() -> AuditStatisticalSampling:
    """Get singleton instance of AuditStatisticalSampling."""
    global _audit_sampling
    if _audit_sampling is None:
        _audit_sampling = AuditStatisticalSampling()
    return _audit_sampling


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AuditStatisticalSampling",
    "InvalidPopulationError",
    "InvalidSamplingMethodError",
    "SamplingConfidenceLevel",
    "SamplingError",
    "SamplingMethod",
    "get_audit_sampling",
]
