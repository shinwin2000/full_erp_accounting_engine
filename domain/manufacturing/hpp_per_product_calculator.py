#!/usr/bin/env python3
"""
Module: hpp_per_product_calculator.py
Layer: 6 - Domain / Manufacturing
Responsibility: Calculate HPP (Cost of Goods Manufactured) per finished product.

Provides an engine to calculate Harga Pokok Produksi per unit of finished
product based on raw material costs, labor costs, overhead, and work in
process (beginning and ending).

Dependencies:
- Python standard library (decimal, logging, dataclasses, enum, datetime)
- domain.manufacturing.work_order_entity (WorkOrderEntity)
- domain.manufacturing.work_in_process_entity (WorkInProcessEntity)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every HPP calculation is recorded.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from domain.manufacturing.cost_element_enum import CostElement
from domain.manufacturing.work_in_process_entity import WorkInProcessEntity
from domain.manufacturing.work_order_entity import WorkOrderEntity

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class HPPCalculationMethod(Enum):
    """Method used to calculate HPP."""

    JOB_ORDER = "job_order"  # Based on specific job order
    PROCESS_COSTING = "process_costing"  # Process costing (average)
    STANDARD_COSTING = "standard_costing"  # Based on standard costs


# ============================================================================
# HPP Component (Value Object)
# ============================================================================


@dataclass(frozen=True)
class HPPComponent:
    """
    Component of HPP calculation (immutable value object).

    Attributes:
        cost_element: Type of cost (material, labor, overhead).
        amount: Total cost for this component.
        quantity: Quantity produced (units).
        unit_cost: Cost per unit.
    """

    cost_element: CostElement
    amount: Decimal
    quantity: Decimal
    unit_cost: Decimal

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_element": self.cost_element.value,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost),
        }


# ============================================================================
# HPP Calculation Result
# ============================================================================


@dataclass(frozen=True)
class HPPCalculationResult:
    """
    Result of HPP calculation (immutable).

    Attributes:
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        period_start: Start of the period.
        period_end: End of the period.
        units_produced: Total units produced in the period.
        total_material_cost: Total material cost incurred.
        total_labor_cost: Total labor cost incurred.
        total_overhead_cost: Total overhead cost incurred.
        total_production_cost: Total cost of production (incl. WIP adjustments).
        unit_hpp: Cost per unit (HPP per unit).
        opening_wip_value: Value of opening WIP.
        closing_wip_value: Value of closing WIP.
        calculation_method: Method used for calculation.
        components: List of HPP components (material, labor, overhead).
    """

    product_id: UUID
    product_code: str
    product_name: str
    period_start: datetime
    period_end: datetime
    units_produced: Decimal
    total_material_cost: Decimal
    total_labor_cost: Decimal
    total_overhead_cost: Decimal
    total_production_cost: Decimal
    unit_hpp: Decimal
    opening_wip_value: Decimal
    closing_wip_value: Decimal
    calculation_method: HPPCalculationMethod
    components: list[HPPComponent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.units_produced < 0:
            raise ValueError(f"Units produced cannot be negative: {self.units_produced}")
        if self.total_production_cost < 0:
            raise ValueError(
                f"Total production cost cannot be negative: {self.total_production_cost}"
            )
        if self.unit_hpp < 0:
            raise ValueError(f"Unit HPP cannot be negative: {self.unit_hpp}")
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("Period dates must be timezone-aware")
        if self.period_end <= self.period_start:
            raise ValueError("Period end must be after period start")

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "units_produced": str(self.units_produced),
            "total_material_cost": str(self.total_material_cost),
            "total_labor_cost": str(self.total_labor_cost),
            "total_overhead_cost": str(self.total_overhead_cost),
            "total_production_cost": str(self.total_production_cost),
            "unit_hpp": str(self.unit_hpp),
            "opening_wip_value": str(self.opening_wip_value),
            "closing_wip_value": str(self.closing_wip_value),
            "calculation_method": self.calculation_method.value,
            "components": [c.to_dict() for c in self.components],
        }


# ============================================================================
# HPP Per Product Calculator
# ============================================================================


class HPPPerProductCalculator:
    """
    Calculator for HPP (Cost of Goods Manufactured) per product.

    Business context:
    Computes the cost of finished goods produced during a period,
    considering direct materials, direct labor, overhead, and WIP changes.
    Supports job order, process costing, and standard costing methods.
    """

    def __init__(self):
        self._calculation_history: list[HPPCalculationResult] = []

    # ------------------------------------------------------------------------
    # Job Order Method
    # ------------------------------------------------------------------------

    def calculate_job_order(
        self,
        work_order: WorkOrderEntity,
        wip_entry: WorkInProcessEntity | None = None,
    ) -> HPPCalculationResult:
        """
        Calculate HPP using job order costing (specific work order).

        Args:
            work_order: Completed work order.
            wip_entry: Optional WIP entry associated with the work order.

        Returns:
            HPPCalculationResult for this job.

        Raises:
            ValueError: If work order has no completed units.
        """
        if work_order.completed_quantity <= 0:
            raise ValueError(f"Work order {work_order.work_order_number} has no completed units")

        # Use costs from WIP if available, otherwise from work order actual costs
        if wip_entry:
            material_cost = wip_entry.material_cost
            labor_cost = wip_entry.labor_cost
            overhead_cost = wip_entry.overhead_cost
        else:
            material_cost = work_order.material_actual_cost
            labor_cost = work_order.labor_actual_cost
            overhead_cost = work_order.overhead_actual_cost

        total_cost = material_cost + labor_cost + overhead_cost
        unit_hpp = (
            total_cost / work_order.completed_quantity
            if work_order.completed_quantity > 0
            else Decimal(0)
        )

        components = [
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=material_cost,
                quantity=work_order.completed_quantity,
                unit_cost=material_cost / work_order.completed_quantity
                if work_order.completed_quantity > 0
                else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.LABOR,
                amount=labor_cost,
                quantity=work_order.completed_quantity,
                unit_cost=labor_cost / work_order.completed_quantity
                if work_order.completed_quantity > 0
                else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.OVERHEAD,
                amount=overhead_cost,
                quantity=work_order.completed_quantity,
                unit_cost=overhead_cost / work_order.completed_quantity
                if work_order.completed_quantity > 0
                else Decimal(0),
            ),
        ]

        result = HPPCalculationResult(
            product_id=work_order.product_id,
            product_code=work_order.product_code,
            product_name=work_order.product_name,
            period_start=work_order.actual_start_date or work_order.planned_start_date,
            period_end=work_order.actual_end_date or datetime.now(UTC),
            units_produced=work_order.completed_quantity,
            total_material_cost=material_cost,
            total_labor_cost=labor_cost,
            total_overhead_cost=overhead_cost,
            total_production_cost=total_cost,
            unit_hpp=unit_hpp,
            opening_wip_value=Decimal(0),
            closing_wip_value=Decimal(0),
            calculation_method=HPPCalculationMethod.JOB_ORDER,
            components=components,
        )
        self._calculation_history.append(result)
        return result

    # ------------------------------------------------------------------------
    # Process Costing Method
    # ------------------------------------------------------------------------

    def calculate_process_costing(
        self,
        product_id: UUID,
        product_code: str,
        product_name: str,
        period_start: datetime,
        period_end: datetime,
        work_orders: list[WorkOrderEntity],
        opening_wip_value: Decimal = Decimal(0),
        closing_wip_value: Decimal = Decimal(0),
    ) -> HPPCalculationResult:
        """
        Calculate HPP using process costing (aggregate over period).

        Formula:
            Total Production Cost = Material Cost + Labor Cost + Overhead Cost + Opening WIP - Closing WIP
            Unit HPP = Total Production Cost / Total Units Produced

        Args:
            product_id: Product ID.
            product_code: Product code.
            product_name: Product name.
            period_start: Start of the period.
            period_end: End of the period.
            work_orders: List of work orders completed in the period.
            opening_wip_value: Value of opening WIP inventory.
            closing_wip_value: Value of closing WIP inventory.

        Returns:
            HPPCalculationResult with average cost per unit.
        """
        total_material = Decimal(0)
        total_labor = Decimal(0)
        total_overhead = Decimal(0)
        total_units = Decimal(0)

        for wo in work_orders:
            total_material += wo.material_actual_cost
            total_labor += wo.labor_actual_cost
            total_overhead += wo.overhead_actual_cost
            total_units += wo.completed_quantity

        total_cost = total_material + total_labor + total_overhead
        total_production_cost = total_cost + opening_wip_value - closing_wip_value
        unit_hpp = total_production_cost / total_units if total_units > 0 else Decimal(0)

        components = [
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=total_material,
                quantity=total_units,
                unit_cost=total_material / total_units if total_units > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.LABOR,
                amount=total_labor,
                quantity=total_units,
                unit_cost=total_labor / total_units if total_units > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.OVERHEAD,
                amount=total_overhead,
                quantity=total_units,
                unit_cost=total_overhead / total_units if total_units > 0 else Decimal(0),
            ),
        ]

        result = HPPCalculationResult(
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            period_start=period_start,
            period_end=period_end,
            units_produced=total_units,
            total_material_cost=total_material,
            total_labor_cost=total_labor,
            total_overhead_cost=total_overhead,
            total_production_cost=total_production_cost,
            unit_hpp=unit_hpp,
            opening_wip_value=opening_wip_value,
            closing_wip_value=closing_wip_value,
            calculation_method=HPPCalculationMethod.PROCESS_COSTING,
            components=components,
        )
        self._calculation_history.append(result)
        return result

    # ------------------------------------------------------------------------
    # Standard Costing Method
    # ------------------------------------------------------------------------

    def calculate_standard_costing(
        self,
        product_id: UUID,
        product_code: str,
        product_name: str,
        standard_unit_cost: Decimal,
        units_produced: Decimal,
        period_start: datetime,
        period_end: datetime,
        variance_adjustment: Decimal = Decimal(0),
    ) -> HPPCalculationResult:
        """
        Calculate HPP using standard costing.

        Args:
            product_id: Product ID.
            product_code: Product code.
            product_name: Product name.
            standard_unit_cost: Standard cost per unit.
            units_produced: Number of units produced.
            period_start: Start of period.
            period_end: End of period.
            variance_adjustment: Total variance adjustment (positive if unfavorable).

        Returns:
            HPPCalculationResult based on standard costs adjusted for variances.
        """
        total_standard_cost = standard_unit_cost * units_produced
        total_adjusted_cost = total_standard_cost + variance_adjustment
        unit_hpp = total_adjusted_cost / units_produced if units_produced > 0 else Decimal(0)

        # Simplified allocation of total cost to components (proportional to standard)
        # Assuming standard breakdown: material 50%, labor 30%, overhead 20%
        material_ratio = Decimal("0.5")
        labor_ratio = Decimal("0.3")
        overhead_ratio = Decimal("0.2")

        total_material = total_adjusted_cost * material_ratio
        total_labor = total_adjusted_cost * labor_ratio
        total_overhead = total_adjusted_cost * overhead_ratio

        components = [
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=total_material,
                quantity=units_produced,
                unit_cost=total_material / units_produced if units_produced > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.LABOR,
                amount=total_labor,
                quantity=units_produced,
                unit_cost=total_labor / units_produced if units_produced > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.OVERHEAD,
                amount=total_overhead,
                quantity=units_produced,
                unit_cost=total_overhead / units_produced if units_produced > 0 else Decimal(0),
            ),
        ]

        result = HPPCalculationResult(
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            period_start=period_start,
            period_end=period_end,
            units_produced=units_produced,
            total_material_cost=total_material,
            total_labor_cost=total_labor,
            total_overhead_cost=total_overhead,
            total_production_cost=total_adjusted_cost,
            unit_hpp=unit_hpp,
            opening_wip_value=Decimal(0),
            closing_wip_value=Decimal(0),
            calculation_method=HPPCalculationMethod.STANDARD_COSTING,
            components=components,
        )
        self._calculation_history.append(result)
        return result

    # ------------------------------------------------------------------------
    # Flexible calculation with explicit cost components
    # ------------------------------------------------------------------------

    def calculate_with_components(
        self,
        product_id: UUID,
        product_code: str,
        product_name: str,
        period_start: datetime,
        period_end: datetime,
        units_produced: Decimal,
        material_cost: Decimal,
        labor_cost: Decimal,
        overhead_cost: Decimal,
        opening_wip_value: Decimal = Decimal(0),
        closing_wip_value: Decimal = Decimal(0),
        method: HPPCalculationMethod = HPPCalculationMethod.JOB_ORDER,
    ) -> HPPCalculationResult:
        """
        Calculate HPP with explicitly provided cost components.

        Args:
            product_id: Product ID.
            product_code: Product code.
            product_name: Product name.
            period_start: Start of period.
            period_end: End of period.
            units_produced: Units produced.
            material_cost: Total material cost.
            labor_cost: Total labor cost.
            overhead_cost: Total overhead cost.
            opening_wip_value: Opening WIP value.
            closing_wip_value: Closing WIP value.
            method: Calculation method label.

        Returns:
            HPPCalculationResult.
        """
        total_cost = material_cost + labor_cost + overhead_cost
        total_production_cost = total_cost + opening_wip_value - closing_wip_value
        unit_hpp = total_production_cost / units_produced if units_produced > 0 else Decimal(0)

        components = [
            HPPComponent(
                cost_element=CostElement.MATERIAL,
                amount=material_cost,
                quantity=units_produced,
                unit_cost=material_cost / units_produced if units_produced > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.LABOR,
                amount=labor_cost,
                quantity=units_produced,
                unit_cost=labor_cost / units_produced if units_produced > 0 else Decimal(0),
            ),
            HPPComponent(
                cost_element=CostElement.OVERHEAD,
                amount=overhead_cost,
                quantity=units_produced,
                unit_cost=overhead_cost / units_produced if units_produced > 0 else Decimal(0),
            ),
        ]

        result = HPPCalculationResult(
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            period_start=period_start,
            period_end=period_end,
            units_produced=units_produced,
            total_material_cost=material_cost,
            total_labor_cost=labor_cost,
            total_overhead_cost=overhead_cost,
            total_production_cost=total_production_cost,
            unit_hpp=unit_hpp,
            opening_wip_value=opening_wip_value,
            closing_wip_value=closing_wip_value,
            calculation_method=method,
            components=components,
        )
        self._calculation_history.append(result)
        return result

    # ------------------------------------------------------------------------
    # History and reporting
    # ------------------------------------------------------------------------

    def get_calculation_history(
        self,
        product_id: UUID | None = None,
        limit: int = 100,
    ) -> list[HPPCalculationResult]:
        """Retrieve calculation history."""
        if product_id:
            filtered = [r for r in self._calculation_history if r.product_id == product_id]
            return filtered[-limit:]
        return self._calculation_history[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Return summary statistics across all calculations."""
        if not self._calculation_history:
            return {"total_calculations": 0}

        total_calculations = len(self._calculation_history)
        total_units = sum(r.units_produced for r in self._calculation_history)
        weighted_avg_hpp = Decimal(0)
        for r in self._calculation_history:
            weighted_avg_hpp += r.unit_hpp * r.units_produced
        if total_units > 0:
            weighted_avg_hpp /= total_units

        method_counts = {}
        for method in HPPCalculationMethod:
            count = sum(1 for r in self._calculation_history if r.calculation_method == method)
            method_counts[method.value] = count

        return {
            "total_calculations": total_calculations,
            "total_units_produced": str(total_units),
            "weighted_average_unit_hpp": str(weighted_avg_hpp),
            "by_method": method_counts,
        }

    def reset(self) -> None:
        """Clear calculation history."""
        self._calculation_history = []


# ============================================================================
# Exports (including alias for backward compatibility)
# ============================================================================

# Alias to match import name used in service_manufacturing.py
HPPCalculator = HPPPerProductCalculator

__all__ = [
    "HPPCalculationMethod",
    "HPPCalculationResult",
    "HPPCalculator",  # Added alias
    "HPPComponent",
    "HPPPerProductCalculator",
]
