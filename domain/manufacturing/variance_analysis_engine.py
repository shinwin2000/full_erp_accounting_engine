#!/usr/bin/env python3
"""
Module: variance_analysis_engine.py
Layer: 6 - Domain / Manufacturing
Responsibility: Variance analysis between actual and standard costs.

Provides an engine to calculate and analyze variances between actual
production costs and standard costs, including material variance,
labor variance, and overhead variance.

Dependencies:
- Python standard library (decimal, logging, dataclasses, enum)
- domain.manufacturing.work_order_entity (WorkOrderEntity)
- domain.manufacturing.standard_cost_entity (StandardCostEntity)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every variance analysis result is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.standard_cost_entity import StandardCostEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class VarianceType(Enum):
    """Type of variance."""

    FAVORABLE = "favorable"  # Actual < Standard (good)
    UNFAVORABLE = "unfavorable"  # Actual > Standard (bad)


# ============================================================================
# Variance Component (Value Object)
# ============================================================================


@dataclass(frozen=True)
class VarianceComponent:
    """
    Individual variance component (immutable).

    Attributes:
        cost_element: Which cost element this variance belongs to.
        variance_type: Favorable or unfavorable.
        standard_cost: Standard cost amount.
        actual_cost: Actual cost amount.
        variance_amount: Absolute difference.
        variance_percentage: Percentage difference (0-100).
        description: Human-readable explanation.
    """

    cost_element: CostElement
    variance_type: VarianceType
    standard_cost: Decimal
    actual_cost: Decimal
    variance_amount: Decimal
    variance_percentage: float
    description: str

    def __post_init__(self) -> None:
        if self.variance_amount < 0:
            raise ValueError(f"Variance amount cannot be negative: {self.variance_amount}")
        if not (0 <= self.variance_percentage <= 100):
            raise ValueError(
                f"Variance percentage must be between 0 and 100: {self.variance_percentage}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_element": self.cost_element.value,
            "variance_type": self.variance_type.value,
            "standard_cost": str(self.standard_cost),
            "actual_cost": str(self.actual_cost),
            "variance_amount": str(self.variance_amount),
            "variance_percentage": self.variance_percentage,
            "description": self.description,
        }


# ============================================================================
# Variance Analysis Result
# ============================================================================


@dataclass(frozen=True)
class VarianceAnalysisResult:
    """
    Complete variance analysis result for a work order (immutable).

    Attributes:
        work_order_id: Work order ID.
        work_order_number: Work order number.
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        quantity_produced: Quantity completed.
        standard_cost_total: Total standard cost for quantity produced.
        actual_cost_total: Total actual cost incurred.
        total_variance: Absolute difference.
        total_variance_type: Favorable or unfavorable overall.
        components: List of variance components (material, labor, overhead).
        material_price_variance: Optional detailed price variance.
        material_usage_variance: Optional detailed usage variance.
        labor_rate_variance: Optional detailed rate variance.
        labor_efficiency_variance: Optional detailed efficiency variance.
        overhead_volume_variance: Optional volume variance.
        overhead_spending_variance: Optional spending variance.
    """

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    quantity_produced: Decimal
    standard_cost_total: Decimal
    actual_cost_total: Decimal
    total_variance: Decimal
    total_variance_type: VarianceType
    components: list[VarianceComponent] = field(default_factory=list)
    material_price_variance: Decimal | None = None
    material_usage_variance: Decimal | None = None
    labor_rate_variance: Decimal | None = None
    labor_efficiency_variance: Decimal | None = None
    overhead_volume_variance: Decimal | None = None
    overhead_spending_variance: Decimal | None = None

    def __post_init__(self) -> None:
        if self.quantity_produced < 0:
            raise ValueError(f"Quantity produced cannot be negative: {self.quantity_produced}")
        if self.standard_cost_total < 0:
            raise ValueError(f"Standard cost total cannot be negative: {self.standard_cost_total}")
        if self.actual_cost_total < 0:
            raise ValueError(f"Actual cost total cannot be negative: {self.actual_cost_total}")
        if self.total_variance < 0:
            raise ValueError(f"Total variance cannot be negative: {self.total_variance}")

    @property
    def variance_percentage(self) -> float:
        """Calculate variance percentage relative to standard cost."""
        if self.standard_cost_total == 0:
            return 0.0
        return float(self.total_variance / self.standard_cost_total * 100)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "quantity_produced": str(self.quantity_produced),
            "standard_cost_total": str(self.standard_cost_total),
            "actual_cost_total": str(self.actual_cost_total),
            "total_variance": str(self.total_variance),
            "total_variance_type": self.total_variance_type.value,
            "variance_percentage": self.variance_percentage,
            "components": [c.to_dict() for c in self.components],
            "material_price_variance": str(self.material_price_variance)
            if self.material_price_variance is not None
            else None,
            "material_usage_variance": str(self.material_usage_variance)
            if self.material_usage_variance is not None
            else None,
            "labor_rate_variance": str(self.labor_rate_variance)
            if self.labor_rate_variance is not None
            else None,
            "labor_efficiency_variance": str(self.labor_efficiency_variance)
            if self.labor_efficiency_variance is not None
            else None,
            "overhead_volume_variance": str(self.overhead_volume_variance)
            if self.overhead_volume_variance is not None
            else None,
            "overhead_spending_variance": str(self.overhead_spending_variance)
            if self.overhead_spending_variance is not None
            else None,
        }


# ============================================================================
# Variance Analysis Engine
# ============================================================================


class VarianceAnalysisEngine:
    """
    Engine for analyzing production cost variances.

    Business context:
    Compares actual costs with standard costs to identify inefficiencies.
    Supports material, labor, and overhead variances with detailed breakdowns.
    """

    def __init__(self):
        self._analysis_history: list[VarianceAnalysisResult] = []

    # ------------------------------------------------------------------------
    # Main analysis method
    # ------------------------------------------------------------------------

    def analyze_variance(
        self,
        work_order: WorkOrderEntity,
        actual_material_cost: Decimal,
        actual_labor_cost: Decimal,
        actual_overhead_cost: Decimal,
        standard_cost: StandardCostEntity | None = None,
    ) -> VarianceAnalysisResult:
        """
        Perform full variance analysis for a work order.

        Args:
            work_order: Work order entity.
            actual_material_cost: Actual material cost incurred.
            actual_labor_cost: Actual labor cost incurred.
            actual_overhead_cost: Actual overhead cost incurred.
            standard_cost: Optional standard cost entity. If not provided,
                          uses work_order's standard cost fields.

        Returns:
            VarianceAnalysisResult with all variances.

        Raises:
            ValueError: If work_order has no completed quantity.
        """
        if work_order.completed_quantity <= 0:
            raise ValueError(f"Work order {work_order.work_order_number} has no completed units")

        # Determine standard costs
        if standard_cost:
            std_material = standard_cost.material_cost * work_order.completed_quantity
            std_labor = standard_cost.labor_cost * work_order.completed_quantity
            std_overhead = standard_cost.overhead_cost * work_order.completed_quantity
            std_total = standard_cost.total_cost * work_order.completed_quantity
        else:
            std_material = work_order.material_standard_cost * work_order.completed_quantity
            std_labor = work_order.labor_standard_cost * work_order.completed_quantity
            std_overhead = work_order.overhead_standard_cost * work_order.completed_quantity
            std_total = (
                work_order.material_standard_cost
                + work_order.labor_standard_cost
                + work_order.overhead_standard_cost
            ) * work_order.completed_quantity

        actual_total = actual_material_cost + actual_labor_cost + actual_overhead_cost
        total_variance = abs(actual_total - std_total)
        total_variance_type = (
            VarianceType.UNFAVORABLE if actual_total > std_total else VarianceType.FAVORABLE
        )

        # Build component variances
        components = []

        # Material variance
        material_variance = actual_material_cost - std_material
        material_type = (
            VarianceType.UNFAVORABLE if material_variance > 0 else VarianceType.FAVORABLE
        )
        components.append(
            VarianceComponent(
                cost_element=CostElement.MATERIAL,
                variance_type=material_type,
                standard_cost=std_material,
                actual_cost=actual_material_cost,
                variance_amount=abs(material_variance),
                variance_percentage=self._calc_percentage(abs(material_variance), std_material),
                description=f"Material variance: {material_type.value}",
            )
        )

        # Labor variance
        labor_variance = actual_labor_cost - std_labor
        labor_type = VarianceType.UNFAVORABLE if labor_variance > 0 else VarianceType.FAVORABLE
        components.append(
            VarianceComponent(
                cost_element=CostElement.LABOR,
                variance_type=labor_type,
                standard_cost=std_labor,
                actual_cost=actual_labor_cost,
                variance_amount=abs(labor_variance),
                variance_percentage=self._calc_percentage(abs(labor_variance), std_labor),
                description=f"Labor variance: {labor_type.value}",
            )
        )

        # Overhead variance
        overhead_variance = actual_overhead_cost - std_overhead
        overhead_type = (
            VarianceType.UNFAVORABLE if overhead_variance > 0 else VarianceType.FAVORABLE
        )
        components.append(
            VarianceComponent(
                cost_element=CostElement.OVERHEAD,
                variance_type=overhead_type,
                standard_cost=std_overhead,
                actual_cost=actual_overhead_cost,
                variance_amount=abs(overhead_variance),
                variance_percentage=self._calc_percentage(abs(overhead_variance), std_overhead),
                description=f"Overhead variance: {overhead_type.value}",
            )
        )

        result = VarianceAnalysisResult(
            work_order_id=work_order.work_order_id,
            work_order_number=work_order.work_order_number,
            product_id=work_order.product_id,
            product_code=work_order.product_code,
            product_name=work_order.product_name,
            quantity_produced=work_order.completed_quantity,
            standard_cost_total=std_total,
            actual_cost_total=actual_total,
            total_variance=total_variance,
            total_variance_type=total_variance_type,
            components=components,
        )

        self._analysis_history.append(result)
        return result

    @staticmethod
    def _calc_percentage(variance_amount: Decimal, base: Decimal) -> float:
        """Calculate variance percentage safely."""
        if base == 0:
            return 0.0
        return float(variance_amount / base * 100)

    # ------------------------------------------------------------------------
    # Detailed variance calculations
    # ------------------------------------------------------------------------

    def calculate_material_variance(
        self,
        standard_price: Decimal,
        actual_price: Decimal,
        standard_quantity: Decimal,
        actual_quantity: Decimal,
    ) -> dict[str, Decimal]:
        """
        Calculate material price variance and usage variance.

        Formulas:
            Price Variance = (Actual Price - Standard Price) x Actual Quantity
            Usage Variance = (Actual Quantity - Standard Quantity) x Standard Price

        Args:
            standard_price: Standard price per unit of material.
            actual_price: Actual price paid per unit.
            standard_quantity: Standard quantity allowed for actual output.
            actual_quantity: Actual quantity used.

        Returns:
            Dictionary with keys: price_variance, usage_variance, total_variance.
            Positive variance is unfavorable (actual > standard).
        """
        price_variance = (actual_price - standard_price) * actual_quantity
        usage_variance = (actual_quantity - standard_quantity) * standard_price
        total_variance = price_variance + usage_variance

        return {
            "price_variance": price_variance,
            "usage_variance": usage_variance,
            "total_variance": total_variance,
        }

    def calculate_labor_variance(
        self,
        standard_rate: Decimal,
        actual_rate: Decimal,
        standard_hours: Decimal,
        actual_hours: Decimal,
    ) -> dict[str, Decimal]:
        """
        Calculate labor rate variance and efficiency variance.

        Formulas:
            Rate Variance = (Actual Rate - Standard Rate) x Actual Hours
            Efficiency Variance = (Actual Hours - Standard Hours) x Standard Rate

        Args:
            standard_rate: Standard labor rate per hour.
            actual_rate: Actual labor rate paid per hour.
            standard_hours: Standard hours allowed for actual output.
            actual_hours: Actual hours worked.

        Returns:
            Dictionary with keys: rate_variance, efficiency_variance, total_variance.
        """
        rate_variance = (actual_rate - standard_rate) * actual_hours
        efficiency_variance = (actual_hours - standard_hours) * standard_rate
        total_variance = rate_variance + efficiency_variance

        return {
            "rate_variance": rate_variance,
            "efficiency_variance": efficiency_variance,
            "total_variance": total_variance,
        }

    def calculate_overhead_variance(
        self,
        applied_overhead: Decimal,
        actual_overhead: Decimal,
        budgeted_overhead: Decimal,
        standard_hours: Decimal,
        actual_hours: Decimal,
    ) -> dict[str, Decimal]:
        """
        Calculate overhead variances (volume and spending).

        Formulas:
            Volume Variance = Applied Overhead - Budgeted Overhead
            Spending Variance = Budgeted Overhead - Actual Overhead

        Args:
            applied_overhead: Overhead applied to production (based on standard rate).
            actual_overhead: Actual overhead incurred.
            budgeted_overhead: Budgeted overhead for actual hours.
            standard_hours: Standard hours allowed for actual output.
            actual_hours: Actual hours worked.

        Returns:
            Dictionary with keys: volume_variance, spending_variance, total_variance.
            Positive variances are unfavorable (actual > applied/budgeted).
        """
        volume_variance = applied_overhead - budgeted_overhead
        spending_variance = budgeted_overhead - actual_overhead
        total_variance = volume_variance + spending_variance

        return {
            "volume_variance": volume_variance,
            "spending_variance": spending_variance,
            "total_variance": total_variance,
        }

    # ------------------------------------------------------------------------
    # History and reporting
    # ------------------------------------------------------------------------

    def get_analysis_history(
        self, work_order_id: UUID | None = None, limit: int = 100
    ) -> list[VarianceAnalysisResult]:
        """Retrieve previous variance analysis results."""
        if work_order_id:
            filtered = [r for r in self._analysis_history if r.work_order_id == work_order_id]
            return filtered[-limit:]
        return self._analysis_history[-limit:]

    def get_summary_statistics(self) -> dict[str, Any]:
        """
        Calculate aggregate statistics across all analyses.

        Returns:
            Dictionary with total analyses, total quantity, average variance percentage,
            and breakdown by variance type.
        """
        if not self._analysis_history:
            return {"total_analyses": 0}

        total_analyses = len(self._analysis_history)
        total_quantity = sum(r.quantity_produced for r in self._analysis_history)
        favorable_count = sum(
            1 for r in self._analysis_history if r.total_variance_type == VarianceType.FAVORABLE
        )
        unfavorable_count = total_analyses - favorable_count

        weighted_avg_variance_pct = Decimal(0)
        for r in self._analysis_history:
            weighted_avg_variance_pct += Decimal(r.variance_percentage) * r.quantity_produced
        if total_quantity > 0:
            weighted_avg_variance_pct /= total_quantity

        return {
            "total_analyses": total_analyses,
            "total_quantity_produced": str(total_quantity),
            "favorable_analyses": favorable_count,
            "unfavorable_analyses": unfavorable_count,
            "average_variance_percentage": float(weighted_avg_variance_pct),
            "favorable_rate": favorable_count / total_analyses if total_analyses else 0,
        }

    def reset(self) -> None:
        """Clear analysis history."""
        self._analysis_history = []


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "VarianceAnalysisEngine",
    "VarianceAnalysisResult",
    "VarianceComponent",
    "VarianceType",
]
