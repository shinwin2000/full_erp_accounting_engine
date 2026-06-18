#!/usr/bin/env python3
"""
Module: audit_sampling_engine_materiality_based.py
Layer: Audit (Sampling Materiality)
Responsibility: Mesin sampling yang mengintegrasikan materialitas dengan sampling.
               Menentukan ukuran sampel berdasarkan materialitas, mengevaluasi
               error terhadap threshold materialitas, dan memberikan kesimpulan
               apakah populasi dapat diterima (acceptable) atau tidak.
               Juga mendukung sequential sampling dan stop-or-go decisions.
Dependencies:
- math, decimal, logging, datetime
- audit.sampling_materiality.materiality_threshold_calculator
- audit.sampling_materiality.audit_sampling_statistical
- infrastructure.telemetry.structured_json_logging
Audit: Hasil evaluasi sampling dicatat untuk audit trail.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from audit.sampling_materiality.audit_sampling_statistical import (
    AuditStatisticalSampling,
    get_audit_sampling,
)

# Internal dependencies
from audit.sampling_materiality.materiality_threshold_calculator import (
    MaterialityBasis,
    MaterialityThresholdCalculator,
    get_materiality_calculator,
)
from infrastructure.telemetry.structured_json_logging import get_logger

logger = get_logger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================


class SamplingConclusion(str, Enum):
    ACCEPTABLE = "acceptable"
    CONDITIONALLY_ACCEPTABLE = "conditionally_acceptable"
    UNACCEPTABLE = "unacceptable"
    INCONCLUSIVE = "inconclusive"


# ============================================================================
# EXCEPTIONS
# ============================================================================


class SamplingEngineError(Exception):
    """Base exception untuk sampling engine."""

    pass


# ============================================================================
# MATERIALITY-BASED SAMPLING ENGINE
# ============================================================================


class AuditSamplingEngineMaterialityBased:
    """
    Mesin sampling berbasis materialitas.

    Fitur:
    - Menentukan ukuran sampel berdasarkan materialitas
    - Sequential sampling (stop-or-go)
    - Evaluasi error terhadap materialitas
    - Menentukan apakah populasi acceptable
    - Menghasilkan rekomendasi tindakan audit
    """

    def __init__(self):
        self._materiality_calc: MaterialityThresholdCalculator | None = None
        self._sampling: AuditStatisticalSampling | None = None
        self._current_engagement: dict[str, Any] = {}

    # ------------------------------------------------------------------------
    # Synchronous helpers (no async needed for simple instantiation)
    # ------------------------------------------------------------------------
    def _get_materiality_calc(self) -> MaterialityThresholdCalculator:
        if self._materiality_calc is None:
            self._materiality_calc = get_materiality_calculator()
        return self._materiality_calc

    def _get_sampling(self) -> AuditStatisticalSampling:
        if self._sampling is None:
            self._sampling = get_audit_sampling()
        return self._sampling

    # ------------------------------------------------------------------------
    # Public async methods
    # ------------------------------------------------------------------------
    async def setup_engagement(
        self,
        legal_entity_id: str,
        basis_value: Decimal,
        basis_type: MaterialityBasis,
        population_size: int,
        population_value: Decimal | None = None,
        confidence_level: int = 95,
        expected_error_percent: float = 1.0,
        tolerable_error_percent: float = 5.0,
    ) -> dict[str, Any]:
        """
        Setup engagement audit: hitung materialitas dan target sample size.

        Returns:
            Engagement configuration dictionary
        """
        materiality_calc = self._get_materiality_calc()
        sampling = self._get_sampling()

        # Calculate materiality thresholds
        thresholds = materiality_calc.calculate_all_thresholds(
            basis_value=basis_value, basis_type=basis_type
        )

        overall_materiality = thresholds["overall_materiality"]
        performance_materiality = thresholds["performance_materiality"]
        clearly_trivial = thresholds["clearly_trivial_threshold"]

        # Determine if using monetary unit sampling or attribute sampling
        use_mus = population_value is not None and population_value > 0

        if use_mus:
            sample_size = sampling.calculate_monetary_unit_sample_size(
                population_value=population_value,
                confidence_level=confidence_level,
                expected_error_percent=expected_error_percent,
                tolerable_error_percent=tolerable_error_percent,
            )
        else:
            sample_size = sampling.calculate_sample_size(
                population_size=population_size,
                confidence_level=confidence_level,
                expected_error_percent=expected_error_percent,
                tolerable_error_percent=tolerable_error_percent,
            )

        self._current_engagement = {
            "legal_entity_id": legal_entity_id,
            "basis_value": float(basis_value),
            "basis_type": basis_type.value,
            "population_size": population_size,
            "population_value": float(population_value) if population_value else None,
            "confidence_level": confidence_level,
            "expected_error_percent": expected_error_percent,
            "tolerable_error_percent": tolerable_error_percent,
            "overall_materiality": float(overall_materiality),
            "performance_materiality": float(performance_materiality),
            "clearly_trivial_threshold": float(clearly_trivial),
            "sample_size": sample_size,
            "use_mus": use_mus,
        }

        logger.info(
            f"Audit engagement setup: sample_size={sample_size}, "
            f"performance_materiality={performance_materiality:,.2f}"
        )
        return self._current_engagement

    def evaluate_sample_errors(self, errors: list[Decimal]) -> dict[str, Any]:
        """
        Evaluasi error yang ditemukan dalam sampel terhadap materialitas.

        Args:
            errors: List error amounts (positive values)

        Returns:
            Evaluation results
        """
        if not self._current_engagement:
            raise SamplingEngineError("Engagement not set up. Call setup_engagement first.")

        performance_materiality = Decimal(str(self._current_engagement["performance_materiality"]))
        clearly_trivial = Decimal(str(self._current_engagement["clearly_trivial_threshold"]))
        sample_size = self._current_engagement["sample_size"]

        # Filter trivial errors (below clearly trivial threshold)
        non_trivial_errors = [e for e in errors if e >= clearly_trivial]
        material_errors = [e for e in errors if e >= performance_materiality]

        total_error = sum(errors)
        total_non_trivial_error = sum(non_trivial_errors)

        # Tolerable error in monetary terms (performance materiality scaled by population)
        # For attribute sampling, we use error rate
        if self._current_engagement.get("use_mus"):
            tolerable_error = performance_materiality
        else:
            # For attribute sampling, tolerable error count
            tolerable_error_count = int(
                math.ceil(self._current_engagement["tolerable_error_percent"] / 100.0 * sample_size)
            )

        # Determine conclusion
        if len(material_errors) == 0:
            if total_non_trivial_error <= performance_materiality:
                conclusion = SamplingConclusion.ACCEPTABLE
                recommendation = "Population is acceptable. No further procedures needed."
            else:
                conclusion = SamplingConclusion.CONDITIONALLY_ACCEPTABLE
                recommendation = "Non-trivial errors exceed performance materiality. Consider additional procedures."
        else:
            conclusion = SamplingConclusion.UNACCEPTABLE
            recommendation = f"Material errors found ({len(material_errors)} items). Recommend full population testing or significant adjustment."

        result = {
            "conclusion": conclusion.value,
            "recommendation": recommendation,
            "total_errors": len(errors),
            "total_error_amount": float(total_error),
            "non_trivial_errors": len(non_trivial_errors),
            "non_trivial_error_amount": float(total_non_trivial_error),
            "material_errors": len(material_errors),
            "material_error_amounts": [float(e) for e in material_errors],
            "performance_materiality": float(performance_materiality),
            "clearly_trivial_threshold": float(clearly_trivial),
        }

        if not self._current_engagement.get("use_mus"):
            result["tolerable_error_count"] = tolerable_error_count
            result["error_rate"] = (len(errors) / sample_size) * 100

        return result

    async def sequential_sampling(
        self, sequential_errors: list[Decimal], max_samples: int = 3
    ) -> dict[str, Any]:
        """
        Sequential sampling (stop-or-go): evaluasi setelah setiap batch sampel.

        Args:
            sequential_errors: List error dari sampel secara berurutan
            max_samples: Maksimum iterasi sampling

        Returns:
            Stop-or-go decision after each stage
        """
        if not self._current_engagement:
            raise SamplingEngineError("Engagement not set up.")

        performance_materiality = Decimal(str(self._current_engagement["performance_materiality"]))
        sample_size = self._current_engagement["sample_size"]
        batch_size = max(1, sample_size // max_samples)

        stages = []
        cumulative_errors = []

        for i in range(max_samples):
            start_idx = i * batch_size
            end_idx = min((i + 1) * batch_size, sample_size)
            if start_idx >= len(sequential_errors):
                break

            batch_errors = sequential_errors[start_idx:end_idx]
            cumulative_errors.extend(batch_errors)

            # Evaluate current cumulative errors
            eval_result = self.evaluate_sample_errors(cumulative_errors)

            stage_result = {
                "stage": i + 1,
                "sample_accumulated": len(cumulative_errors),
                "errors_accumulated": len(cumulative_errors),
                "total_error_amount": float(sum(cumulative_errors)),
                "conclusion": eval_result["conclusion"],
                "recommendation": eval_result["recommendation"],
                "stop": eval_result["conclusion"] != SamplingConclusion.INCONCLUSIVE,
            }
            stages.append(stage_result)

            if stage_result["stop"]:
                break

        return {
            "sequential_sampling": True,
            "max_samples": max_samples,
            "batch_size": batch_size,
            "stages": stages,
            "final_conclusion": stages[-1]["conclusion"]
            if stages
            else SamplingConclusion.INCONCLUSIVE.value,
        }

    # ------------------------------------------------------------------------
    # This method is now async to match the await on _get_sampling()
    # ------------------------------------------------------------------------
    async def project_and_conclude(
        self, sample_errors: list[Decimal], population_size: int, confidence_level: int = 95
    ) -> dict[str, Any]:
        """
        Proyeksikan error ke populasi dan berikan kesimpulan.

        Args:
            sample_errors: List error dari sampel
            population_size: Ukuran populasi
            confidence_level: Tingkat kepercayaan untuk proyeksi

        Returns:
            Proyeksi dan kesimpulan
        """
        if not self._current_engagement:
            raise SamplingEngineError("Engagement not set up.")

        sampling = self._get_sampling()  # synchronous call, no await needed

        # Project error
        projection = sampling.project_error(
            sample_errors=sample_errors,
            sample_size=len(sample_errors),
            population_size=population_size,
            confidence_level=confidence_level,
        )

        projected_error = projection["projected_error"]
        upper_bound = projection["upper_bound"]

        performance_materiality = Decimal(str(self._current_engagement["performance_materiality"]))

        if upper_bound <= performance_materiality:
            conclusion = SamplingConclusion.ACCEPTABLE
            recommendation = "Upper bound of projected error is within performance materiality."
        elif projected_error <= performance_materiality < upper_bound:
            conclusion = SamplingConclusion.CONDITIONALLY_ACCEPTABLE
            recommendation = "Projected error is acceptable but upper bound exceeds materiality. Consider additional testing."
        else:
            conclusion = SamplingConclusion.UNACCEPTABLE
            recommendation = (
                "Projected error exceeds materiality. Population likely materially misstated."
            )

        return {
            "conclusion": conclusion.value,
            "recommendation": recommendation,
            "projected_error": float(projected_error),
            "upper_bound": float(upper_bound),
            "margin_of_error": float(projection.get("margin_of_error", 0)),
            "error_rate": projection.get("error_rate", 0),
            "performance_materiality": float(performance_materiality),
            "sample_size": len(sample_errors),
            "population_size": population_size,
        }

    async def generate_sampling_report(self) -> dict[str, Any]:
        """
        Menghasilkan laporan sampling untuk audit file.
        """
        if not self._current_engagement:
            raise SamplingEngineError("No engagement data available.")

        return {
            "engagement_parameters": self._current_engagement,
            "sampling_methodology": "materiality_based",
            "materiality_calculation": {
                "overall": self._current_engagement["overall_materiality"],
                "performance": self._current_engagement["performance_materiality"],
                "clearly_trivial": self._current_engagement["clearly_trivial_threshold"],
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_sampling_engine: AuditSamplingEngineMaterialityBased | None = None


async def get_sampling_engine() -> AuditSamplingEngineMaterialityBased:
    """Get singleton instance of AuditSamplingEngineMaterialityBased."""
    global _sampling_engine
    if _sampling_engine is None:
        _sampling_engine = AuditSamplingEngineMaterialityBased()
    return _sampling_engine


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "AuditSamplingEngineMaterialityBased",
    "SamplingConclusion",
    "SamplingEngineError",
    "get_sampling_engine",
]
