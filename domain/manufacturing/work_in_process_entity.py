#!/usr/bin/env python3
"""
Module: work_in_process_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Work in Process (WIP) entity.

Defines the Work in Process entity that records production costs incurred
for work orders that are not yet completed (not yet finished goods).

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every WIP change is recorded via immutable updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.manufacturing.cost_element_enum import CostElement

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class WIPStatus(Enum):
    """Work in Process status."""

    OPEN = "open"  # Still in process
    CLOSED = "closed"  # Completed (moved to finished goods)
    ADJUSTED = "adjusted"  # Adjusted (cost correction)


# ============================================================================
# WIP Cost Component (Value Object)
# ============================================================================


@dataclass(frozen=True)
class WIPCostComponent:
    """
    Cost component within WIP (immutable value object).

    Attributes:
        cost_element: Type of cost (material, labor, overhead).
        amount: Cost amount.
        quantity: Quantity associated with this cost.
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
# Work in Process Entity
# ============================================================================


@dataclass(frozen=True)
class WorkInProcessEntity:
    """
    Work in Process entity (immutable).

    Business context:
    Records production costs incurred for work orders that are not yet finished,
    including raw materials, labor, and overhead applied.

    Invariants:
    - quantity_started = quantity_remaining + quantity_completed
    - All quantities and costs must be non-negative
    - total_cost must equal sum of material, labor, overhead costs

    Attributes:
        wip_id: Unique identifier.
        work_order_id: Associated work order ID.
        work_order_number: Work order number (denormalized).
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        quantity_started: Quantity that has been started.
        quantity_remaining: Quantity still in process (not yet completed).
        quantity_completed: Quantity already completed and moved to FG.
        material_cost: Accumulated material cost.
        labor_cost: Accumulated labor cost.
        overhead_cost: Accumulated overhead cost.
        total_cost: Total cost (material + labor + overhead).
        status: WIP status.
        last_update_date: Date of last cost update.
        cost_components: Detailed list of cost component entries.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created this WIP record.
        version: Optimistic concurrency version.
    """

    wip_id: UUID
    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    quantity_started: Decimal
    quantity_remaining: Decimal
    quantity_completed: Decimal
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    status: WIPStatus
    last_update_date: datetime
    cost_components: list[WIPCostComponent] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate WIP invariants."""
        if self.quantity_started <= 0:
            raise ValueError(f"Quantity started must be positive: {self.quantity_started}")
        if self.quantity_remaining < 0:
            raise ValueError("Quantity remaining cannot be negative")
        if self.quantity_completed < 0:
            raise ValueError("Quantity completed cannot be negative")
        if abs(
            self.quantity_started - (self.quantity_remaining + self.quantity_completed)
        ) > Decimal("0.0001"):
            raise ValueError(
                f"Quantity mismatch: started={self.quantity_started}, "
                f"remaining={self.quantity_remaining}, completed={self.quantity_completed}"
            )
        if abs(
            self.total_cost - (self.material_cost + self.labor_cost + self.overhead_cost)
        ) > Decimal("0.01"):
            raise ValueError(f"Total cost mismatch: {self.total_cost} vs sum of components")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.last_update_date.tzinfo is None:
            raise ValueError("last_update_date must be timezone-aware")

    # ------------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        work_order_id: UUID,
        work_order_number: str,
        product_id: UUID,
        product_code: str,
        product_name: str,
        quantity_started: Decimal,
        created_by: str = "system",
    ) -> WorkInProcessEntity:
        """Create a new WIP entry when production starts."""
        if quantity_started <= 0:
            raise ValueError(f"Quantity started must be positive: {quantity_started}")

        now = datetime.now(UTC)
        return cls(
            wip_id=uuid4(),
            work_order_id=work_order_id,
            work_order_number=work_order_number,
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            quantity_started=quantity_started,
            quantity_remaining=quantity_started,
            quantity_completed=Decimal(0),
            material_cost=Decimal(0),
            labor_cost=Decimal(0),
            overhead_cost=Decimal(0),
            total_cost=Decimal(0),
            status=WIPStatus.OPEN,
            last_update_date=now,
            cost_components=[],
            created_at=now,
            updated_at=now,
            created_by=created_by,
            version=1,
        )

    # ------------------------------------------------------------------------
    # Cost addition methods (return new instance)
    # ------------------------------------------------------------------------

    def add_material_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        added_by: str = "system",
    ) -> WorkInProcessEntity:
        """Add material cost to WIP."""
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        new_material = self.material_cost + amount
        new_total = self.total_cost + amount

        new_component = WIPCostComponent(
            cost_element=CostElement.MATERIAL,
            amount=amount,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        new_components = self.cost_components + [new_component]

        return WorkInProcessEntity(
            wip_id=self.wip_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            quantity_started=self.quantity_started,
            quantity_remaining=self.quantity_remaining,
            quantity_completed=self.quantity_completed,
            material_cost=new_material,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=new_total,
            status=self.status,
            last_update_date=datetime.now(UTC),
            cost_components=new_components,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def add_labor_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        added_by: str = "system",
    ) -> WorkInProcessEntity:
        """Add labor cost to WIP."""
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        new_labor = self.labor_cost + amount
        new_total = self.total_cost + amount

        new_component = WIPCostComponent(
            cost_element=CostElement.LABOR,
            amount=amount,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        new_components = self.cost_components + [new_component]

        return WorkInProcessEntity(
            wip_id=self.wip_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            quantity_started=self.quantity_started,
            quantity_remaining=self.quantity_remaining,
            quantity_completed=self.quantity_completed,
            material_cost=self.material_cost,
            labor_cost=new_labor,
            overhead_cost=self.overhead_cost,
            total_cost=new_total,
            status=self.status,
            last_update_date=datetime.now(UTC),
            cost_components=new_components,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def add_overhead_cost(
        self,
        amount: Decimal,
        quantity: Decimal,
        unit_cost: Decimal,
        added_by: str = "system",
    ) -> WorkInProcessEntity:
        """Add overhead cost to WIP."""
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        new_overhead = self.overhead_cost + amount
        new_total = self.total_cost + amount

        new_component = WIPCostComponent(
            cost_element=CostElement.OVERHEAD,
            amount=amount,
            quantity=quantity,
            unit_cost=unit_cost,
        )
        new_components = self.cost_components + [new_component]

        return WorkInProcessEntity(
            wip_id=self.wip_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            quantity_started=self.quantity_started,
            quantity_remaining=self.quantity_remaining,
            quantity_completed=self.quantity_completed,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=new_overhead,
            total_cost=new_total,
            status=self.status,
            last_update_date=datetime.now(UTC),
            cost_components=new_components,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Completion and adjustment methods
    # ------------------------------------------------------------------------

    def complete_units(self, quantity_completed: Decimal) -> WorkInProcessEntity:
        """
        Move completed units from WIP to finished goods.

        Args:
            quantity_completed: Number of units completed in this batch.

        Returns:
            New WIP entity with updated quantities.

        Raises:
            ValueError: If quantity_completed exceeds quantity_remaining.
        """
        if quantity_completed <= 0:
            raise ValueError("Quantity completed must be positive")
        if quantity_completed > self.quantity_remaining:
            raise ValueError(
                f"Cannot complete {quantity_completed} units, only {self.quantity_remaining} remaining"
            )

        new_remaining = self.quantity_remaining - quantity_completed
        new_completed = self.quantity_completed + quantity_completed
        new_status = WIPStatus.CLOSED if new_remaining == 0 else self.status

        return WorkInProcessEntity(
            wip_id=self.wip_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            quantity_started=self.quantity_started,
            quantity_remaining=new_remaining,
            quantity_completed=new_completed,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            status=new_status,
            last_update_date=datetime.now(UTC),
            cost_components=self.cost_components,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def adjust_cost(
        self, new_total_cost: Decimal, reason: str, adjusted_by: str
    ) -> WorkInProcessEntity:
        """
        Adjust total WIP cost (e.g., for correction).

        Args:
            new_total_cost: New total cost (must be non-negative).
            reason: Reason for adjustment.
            adjusted_by: User who performed adjustment.

        Returns:
            New WIP entity with adjusted total cost.
        """
        if new_total_cost < 0:
            raise ValueError("Total cost cannot be negative")

        # Proportional allocation of adjustment to cost components
        if self.total_cost > 0:
            ratio = new_total_cost / self.total_cost
            new_material = self.material_cost * ratio
            new_labor = self.labor_cost * ratio
            new_overhead = self.overhead_cost * ratio
        else:
            new_material = Decimal(0)
            new_labor = Decimal(0)
            new_overhead = Decimal(0)

        # Add adjustment note as a cost component
        adjustment_component = WIPCostComponent(
            cost_element=CostElement.OTHER,
            amount=new_total_cost - self.total_cost,
            quantity=Decimal(0),
            unit_cost=Decimal(0),
        )
        new_components = self.cost_components + [adjustment_component]

        return WorkInProcessEntity(
            wip_id=self.wip_id,
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            quantity_started=self.quantity_started,
            quantity_remaining=self.quantity_remaining,
            quantity_completed=self.quantity_completed,
            material_cost=new_material,
            labor_cost=new_labor,
            overhead_cost=new_overhead,
            total_cost=new_total_cost,
            status=WIPStatus.ADJUSTED,
            last_update_date=datetime.now(UTC),
            cost_components=new_components,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=adjusted_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def get_unit_cost(self) -> Decimal:
        """Return average cost per unit started."""
        if self.quantity_started == 0:
            return Decimal(0)
        return self.total_cost / self.quantity_started

    def get_remaining_value(self) -> Decimal:
        """Return the value of remaining WIP (based on quantity remaining proportion)."""
        if self.quantity_started == 0:
            return Decimal(0)
        return self.total_cost * (self.quantity_remaining / self.quantity_started)

    def get_completed_value(self) -> Decimal:
        """Return the value of completed units (cost transferred to FG)."""
        if self.quantity_started == 0:
            return Decimal(0)
        return self.total_cost * (self.quantity_completed / self.quantity_started)

    def get_completion_percentage(self) -> float:
        """Return percentage of units completed (0-100)."""
        if self.quantity_started == 0:
            return 0.0
        return float(self.quantity_completed / self.quantity_started * 100)

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "wip_id": str(self.wip_id),
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "quantity_started": str(self.quantity_started),
            "quantity_remaining": str(self.quantity_remaining),
            "quantity_completed": str(self.quantity_completed),
            "completion_percentage": self.get_completion_percentage(),
            "material_cost": str(self.material_cost),
            "labor_cost": str(self.labor_cost),
            "overhead_cost": str(self.overhead_cost),
            "total_cost": str(self.total_cost),
            "unit_cost": str(self.get_unit_cost()),
            "remaining_value": str(self.get_remaining_value()),
            "status": self.status.value,
            "last_update_date": self.last_update_date.isoformat(),
            "cost_components": [c.to_dict() for c in self.cost_components],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }


# ============================================================================
# Work in Process Repository Protocol
# ============================================================================


class WorkInProcessRepository:
    """Repository protocol for WorkInProcessEntity."""

    async def get_by_id(self, wip_id: UUID, legal_entity_id: UUID) -> WorkInProcessEntity | None:
        raise NotImplementedError

    async def get_by_work_order(
        self, work_order_id: UUID, legal_entity_id: UUID
    ) -> WorkInProcessEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self,
        product_id: UUID,
        legal_entity_id: UUID,
        status: WIPStatus | None = None,
    ) -> list[WorkInProcessEntity]:
        raise NotImplementedError

    async def get_open_wip(self, legal_entity_id: UUID) -> list[WorkInProcessEntity]:
        raise NotImplementedError

    async def save(self, wip: WorkInProcessEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, wip_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports (including alias for backward compatibility)
# ============================================================================

# Alias to match import name used in service_manufacturing.py
WorkInProcess = WorkInProcessEntity

__all__ = [
    "WIPCostComponent",
    "WIPStatus",
    "WorkInProcess",  # Added alias
    "WorkInProcessEntity",
    "WorkInProcessRepository",
]
