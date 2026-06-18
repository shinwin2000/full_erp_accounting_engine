#!/usr/bin/env python3
"""
Module: cost_card_projection.py
Layer: 6 - Domain / Manufacturing
Responsibility: Cost card projection (read model).

Defines the read model projection for cost cards that provides
summarized production cost information per work order for analysis
and reporting.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- domain.manufacturing.cost_card_entity (CostCardEntity, CostCardStatus)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every cost card projection is immutable and derived from events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domain.manufacturing.cost_card_entity import CostCardEntity, CostCardStatus

logger = logging.getLogger(__name__)


# ============================================================================
# Cost Card Projection (Read Model)
# ============================================================================


@dataclass(frozen=True)
class CostCardProjection:
    """
    Cost card projection (read model, immutable).

    Business context:
    Provides a summarized view of production costs per work order
    for efficiency analysis and management reporting.

    This projection is derived from CostCardEntity and is optimized
    for querying and reporting. It contains denormalized fields
    and pre-calculated metrics.

    Attributes:
        cost_card_id: Unique identifier (matches CostCardEntity).
        work_order_id: Associated work order ID.
        work_order_number: Work order number (denormalized).
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        planned_quantity: Quantity planned for production.
        completed_quantity: Quantity actually completed.
        completion_rate: Percentage of completion (0-100).
        material_cost: Total material cost.
        labor_cost: Total labor cost.
        overhead_cost: Total overhead cost.
        total_cost: Total cost (material + labor + overhead).
        unit_cost: Average cost per completed unit.
        status: Cost card status.
        material_cost_per_unit: Material cost per completed unit.
        labor_cost_per_unit: Labor cost per completed unit.
        overhead_cost_per_unit: Overhead cost per completed unit.
        entry_count: Number of individual cost entries.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
    """

    cost_card_id: UUID
    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    planned_quantity: Decimal
    completed_quantity: Decimal
    completion_rate: float
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    unit_cost: Decimal
    status: CostCardStatus
    material_cost_per_unit: Decimal
    labor_cost_per_unit: Decimal
    overhead_cost_per_unit: Decimal
    entry_count: int
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        """Validate projection invariants."""
        if self.planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive: {self.planned_quantity}")
        if self.completed_quantity < 0:
            raise ValueError("Completed quantity cannot be negative")
        if self.completed_quantity > self.planned_quantity:
            raise ValueError(
                f"Completed quantity {self.completed_quantity} exceeds planned {self.planned_quantity}"
            )
        if not (0 <= self.completion_rate <= 100):
            raise ValueError(f"Completion rate must be between 0 and 100: {self.completion_rate}")
        if self.total_cost < 0:
            raise ValueError(f"Total cost cannot be negative: {self.total_cost}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        # Validate that unit costs are consistent
        if self.completed_quantity > 0:
            expected_unit = self.total_cost / self.completed_quantity
            if abs(self.unit_cost - expected_unit) > Decimal("0.01"):
                raise ValueError(f"Unit cost mismatch: {self.unit_cost} vs {expected_unit}")
            expected_material_per_unit = self.material_cost / self.completed_quantity
            if abs(self.material_cost_per_unit - expected_material_per_unit) > Decimal("0.01"):
                raise ValueError(
                    f"Material cost per unit mismatch: {self.material_cost_per_unit} vs {expected_material_per_unit}"
                )
            expected_labor_per_unit = self.labor_cost / self.completed_quantity
            if abs(self.labor_cost_per_unit - expected_labor_per_unit) > Decimal("0.01"):
                raise ValueError(
                    f"Labor cost per unit mismatch: {self.labor_cost_per_unit} vs {expected_labor_per_unit}"
                )
            expected_overhead_per_unit = self.overhead_cost / self.completed_quantity
            if abs(self.overhead_cost_per_unit - expected_overhead_per_unit) > Decimal("0.01"):
                raise ValueError(
                    f"Overhead cost per unit mismatch: {self.overhead_cost_per_unit} vs {expected_overhead_per_unit}"
                )

    # ------------------------------------------------------------------------
    # Factory method from CostCardEntity
    # ------------------------------------------------------------------------

    @classmethod
    def from_cost_card(cls, cost_card: CostCardEntity) -> CostCardProjection:
        """
        Create a projection from a CostCardEntity.

        Args:
            cost_card: The source CostCardEntity.

        Returns:
            CostCardProjection with all calculated fields.
        """
        completed_qty = cost_card.completed_quantity
        if completed_qty > 0:
            material_per_unit = cost_card.material_cost / completed_qty
            labor_per_unit = cost_card.labor_cost / completed_qty
            overhead_per_unit = cost_card.overhead_cost / completed_qty
        else:
            material_per_unit = Decimal(0)
            labor_per_unit = Decimal(0)
            overhead_per_unit = Decimal(0)

        completion_rate = (
            float(completed_qty / cost_card.planned_quantity * 100)
            if cost_card.planned_quantity > 0
            else 0.0
        )

        return cls(
            cost_card_id=cost_card.cost_card_id,
            work_order_id=cost_card.work_order_id,
            work_order_number=cost_card.work_order_number,
            product_id=cost_card.product_id,
            product_code=cost_card.product_code,
            product_name=cost_card.product_name,
            planned_quantity=cost_card.planned_quantity,
            completed_quantity=completed_qty,
            completion_rate=completion_rate,
            material_cost=cost_card.material_cost,
            labor_cost=cost_card.labor_cost,
            overhead_cost=cost_card.overhead_cost,
            total_cost=cost_card.total_cost,
            unit_cost=cost_card.unit_cost,
            status=cost_card.status,
            material_cost_per_unit=material_per_unit,
            labor_cost_per_unit=labor_per_unit,
            overhead_cost_per_unit=overhead_per_unit,
            entry_count=len(cost_card.entries),
            created_at=cost_card.created_at,
            updated_at=cost_card.updated_at,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def get_remaining_quantity(self) -> Decimal:
        """Return quantity still to be produced."""
        return self.planned_quantity - self.completed_quantity

    def is_completed(self) -> bool:
        """Return True if all planned units are completed."""
        return self.completed_quantity >= self.planned_quantity

    def is_over_budget(self, standard_cost: Decimal) -> bool:
        """Return True if actual unit cost exceeds standard cost."""
        return self.unit_cost > standard_cost

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "cost_card_id": str(self.cost_card_id),
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "planned_quantity": str(self.planned_quantity),
            "completed_quantity": str(self.completed_quantity),
            "remaining_quantity": str(self.get_remaining_quantity()),
            "completion_rate": self.completion_rate,
            "material_cost": str(self.material_cost),
            "labor_cost": str(self.labor_cost),
            "overhead_cost": str(self.overhead_cost),
            "total_cost": str(self.total_cost),
            "unit_cost": str(self.unit_cost),
            "status": self.status.value,
            "material_cost_per_unit": str(self.material_cost_per_unit),
            "labor_cost_per_unit": str(self.labor_cost_per_unit),
            "overhead_cost_per_unit": str(self.overhead_cost_per_unit),
            "entry_count": self.entry_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ============================================================================
# Cost Card Projection Repository Protocol
# ============================================================================


class CostCardProjectionRepository:
    """
    Repository protocol for CostCardProjection (read model).

    This is a separate repository from CostCardRepository because
    projections are stored in a different database (read-optimized).
    """

    async def get_by_id(
        self, cost_card_id: UUID, legal_entity_id: UUID
    ) -> CostCardProjection | None:
        """Retrieve a projection by its ID."""
        raise NotImplementedError

    async def get_by_work_order(
        self, work_order_id: UUID, legal_entity_id: UUID
    ) -> CostCardProjection | None:
        """Retrieve a projection by work order ID."""
        raise NotImplementedError

    async def get_by_product(
        self,
        product_id: UUID,
        legal_entity_id: UUID,
        status: CostCardStatus | None = None,
        limit: int = 50,
    ) -> list[CostCardProjection]:
        """Retrieve projections for a product, optionally filtered by status."""
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
        product_id: UUID | None = None,
    ) -> list[CostCardProjection]:
        """Retrieve projections within a date range (based on updated_at)."""
        raise NotImplementedError

    async def get_open_cost_cards(self, legal_entity_id: UUID) -> list[CostCardProjection]:
        """Retrieve all open (not yet closed) cost cards."""
        raise NotImplementedError

    async def save(self, projection: CostCardProjection, legal_entity_id: UUID) -> None:
        """Persist a projection (upsert)."""
        raise NotImplementedError

    async def delete(self, cost_card_id: UUID, legal_entity_id: UUID) -> None:
        """Delete a projection."""
        raise NotImplementedError


# ============================================================================
# Cost Card Summary (Aggregate Read Model)
# ============================================================================


@dataclass(frozen=True)
class CostCardSummary:
    """
    Summary of cost cards for a product or period (aggregate read model).

    Business context:
    Provides aggregated production cost data for management analysis
    and reporting, such as total cost, average unit cost, and completion
    statistics for a product over a specific time period.

    Attributes:
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        period_start: Start of the period.
        period_end: End of the period.
        total_work_orders: Number of work orders in the period.
        total_planned_quantity: Sum of planned quantities.
        total_completed_quantity: Sum of completed quantities.
        total_material_cost: Sum of material costs.
        total_labor_cost: Sum of labor costs.
        total_overhead_cost: Sum of overhead costs.
        total_cost: Sum of total costs.
        average_unit_cost: Weighted average unit cost.
        average_material_cost_per_unit: Weighted average material cost per unit.
        average_labor_cost_per_unit: Weighted average labor cost per unit.
        average_overhead_cost_per_unit: Weighted average overhead cost per unit.
    """

    product_id: UUID
    product_code: str
    product_name: str
    period_start: datetime
    period_end: datetime
    total_work_orders: int
    total_planned_quantity: Decimal
    total_completed_quantity: Decimal
    total_material_cost: Decimal
    total_labor_cost: Decimal
    total_overhead_cost: Decimal
    total_cost: Decimal
    average_unit_cost: Decimal
    average_material_cost_per_unit: Decimal
    average_labor_cost_per_unit: Decimal
    average_overhead_cost_per_unit: Decimal

    def __post_init__(self) -> None:
        if self.total_planned_quantity < 0:
            raise ValueError("Total planned quantity cannot be negative")
        if self.total_completed_quantity < 0:
            raise ValueError("Total completed quantity cannot be negative")
        if self.total_cost < 0:
            raise ValueError("Total cost cannot be negative")
        if self.period_start.tzinfo is None or self.period_end.tzinfo is None:
            raise ValueError("Period dates must be timezone-aware")
        if self.period_end <= self.period_start:
            raise ValueError("Period end must be after period start")

    # ------------------------------------------------------------------------
    # Factory method from projections list
    # ------------------------------------------------------------------------

    @classmethod
    def from_projections(
        cls,
        projections: list[CostCardProjection],
        product_id: UUID,
        product_code: str,
        product_name: str,
        period_start: datetime,
        period_end: datetime,
    ) -> CostCardSummary:
        """
        Create a summary from a list of projections.

        Args:
            projections: List of CostCardProjection within the period.
            product_id: Product ID.
            product_code: Product code.
            product_name: Product name.
            period_start: Start of period.
            period_end: End of period.

        Returns:
            CostCardSummary with aggregated values.
        """
        total_planned = Decimal(0)
        total_completed = Decimal(0)
        total_material = Decimal(0)
        total_labor = Decimal(0)
        total_overhead = Decimal(0)
        total_cost = Decimal(0)

        for p in projections:
            total_planned += p.planned_quantity
            total_completed += p.completed_quantity
            total_material += p.material_cost
            total_labor += p.labor_cost
            total_overhead += p.overhead_cost
            total_cost += p.total_cost

        # Calculate weighted averages
        if total_completed > 0:
            avg_unit = total_cost / total_completed
            avg_material = total_material / total_completed
            avg_labor = total_labor / total_completed
            avg_overhead = total_overhead / total_completed
        else:
            avg_unit = Decimal(0)
            avg_material = Decimal(0)
            avg_labor = Decimal(0)
            avg_overhead = Decimal(0)

        return cls(
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            period_start=period_start,
            period_end=period_end,
            total_work_orders=len(projections),
            total_planned_quantity=total_planned,
            total_completed_quantity=total_completed,
            total_material_cost=total_material,
            total_labor_cost=total_labor,
            total_overhead_cost=total_overhead,
            total_cost=total_cost,
            average_unit_cost=avg_unit,
            average_material_cost_per_unit=avg_material,
            average_labor_cost_per_unit=avg_labor,
            average_overhead_cost_per_unit=avg_overhead,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def get_completion_rate(self) -> float:
        """Return overall completion rate (0-100)."""
        if self.total_planned_quantity == 0:
            return 0.0
        return float(self.total_completed_quantity / self.total_planned_quantity * 100)

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_work_orders": self.total_work_orders,
            "total_planned_quantity": str(self.total_planned_quantity),
            "total_completed_quantity": str(self.total_completed_quantity),
            "completion_rate": self.get_completion_rate(),
            "total_material_cost": str(self.total_material_cost),
            "total_labor_cost": str(self.total_labor_cost),
            "total_overhead_cost": str(self.total_overhead_cost),
            "total_cost": str(self.total_cost),
            "average_unit_cost": str(self.average_unit_cost),
            "average_material_cost_per_unit": str(self.average_material_cost_per_unit),
            "average_labor_cost_per_unit": str(self.average_labor_cost_per_unit),
            "average_overhead_cost_per_unit": str(self.average_overhead_cost_per_unit),
        }


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "CostCardProjection",
    "CostCardProjectionRepository",
    "CostCardSummary",
]
