#!/usr/bin/env python3
"""
Module: work_order_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Production work order entity.

Defines work order as an instruction to produce a quantity of finished goods
based on a specific BOM and routing.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- No domain dependencies (uses only standard library)

Audit: Every work order change is recorded via immutable updates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class WorkOrderStatus(Enum):
    """Status of a work order."""

    DRAFT = "draft"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partial"
    CANCELLED = "cancelled"


class WorkOrderPriority(Enum):
    """Priority level for work order scheduling."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class WorkOrderType(Enum):
    """Type of work order."""

    PRODUCTION = "production"  # Standard production order
    MAINTENANCE = "maintenance"  # Maintenance work order
    SAMPLE = "sample"  # Sample/prototype production
    REPAIR = "repair"  # Repair order
    SUBASSEMBLY = "subassembly"  # Subassembly production

    def display_name(self) -> str:
        names = {
            WorkOrderType.PRODUCTION: "Produksi",
            WorkOrderType.MAINTENANCE: "Pemeliharaan",
            WorkOrderType.SAMPLE: "Sample",
            WorkOrderType.REPAIR: "Perbaikan",
            WorkOrderType.SUBASSEMBLY: "Subasembli",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> WorkOrderType | None:
        for t in cls:
            if t.value == value.lower():
                return t
        return None


# ============================================================================
# Work Order Entity
# ============================================================================


@dataclass(frozen=True)
class WorkOrderEntity:
    """
    Production work order entity (immutable).

    Business context:
    Represents a command to produce a specific quantity of a product.

    Attributes:
        work_order_id: Unique identifier.
        work_order_number: Human-readable number.
        product_id: ID of the product to produce.
        product_code: Product code.
        product_name: Product name.
        bom_id: Bill of Materials ID.
        bom_version: Version of BOM used.
        planned_quantity: Quantity to produce.
        completed_quantity: Quantity already completed.
        status: Current status.
        priority: Scheduling priority.
        work_order_type: Type of work order.
        planned_start_date: Planned start date.
        planned_end_date: Planned end date.
        actual_start_date: Actual start date (if started).
        actual_end_date: Actual completion date (if finished).
        routing_id: Optional production routing ID.
        cost_center: Optional cost center.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
        material_standard_cost: Standard material cost per unit (from BOM).
        labor_standard_cost: Standard labor cost per unit (from routing).
        overhead_standard_cost: Standard overhead cost per unit (from allocation).
        material_actual_cost: Actual material cost incurred.
        labor_actual_cost: Actual labor cost incurred.
        overhead_actual_cost: Actual overhead cost incurred.
    """

    work_order_id: UUID
    work_order_number: str
    product_id: UUID
    product_code: str
    product_name: str
    bom_id: UUID
    bom_version: int
    planned_quantity: Decimal
    completed_quantity: Decimal
    status: WorkOrderStatus
    priority: WorkOrderPriority
    planned_start_date: datetime
    planned_end_date: datetime
    actual_start_date: datetime | None = None
    actual_end_date: datetime | None = None
    routing_id: UUID | None = None
    cost_center: str | None = None
    notes: str = ""
    work_order_type: WorkOrderType = WorkOrderType.PRODUCTION
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    material_standard_cost: Decimal = Decimal(0)
    labor_standard_cost: Decimal = Decimal(0)
    overhead_standard_cost: Decimal = Decimal(0)
    material_actual_cost: Decimal = Decimal(0)
    labor_actual_cost: Decimal = Decimal(0)
    overhead_actual_cost: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        """Validate work order invariants."""
        if len(self.work_order_number.strip()) < 3:
            raise ValueError("Work order number must be at least 3 characters")
        if self.planned_quantity <= 0:
            raise ValueError(f"Planned quantity must be positive: {self.planned_quantity}")
        if self.completed_quantity < 0:
            raise ValueError("Completed quantity cannot be negative")
        if self.completed_quantity > self.planned_quantity:
            raise ValueError(
                f"Completed quantity {self.completed_quantity} exceeds planned {self.planned_quantity}"
            )
        if self.planned_end_date <= self.planned_start_date:
            raise ValueError("Planned end date must be after planned start date")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1, got {self.version}")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")

    # ------------------------------------------------------------------------
    # Business logic methods (return new instance)
    # ------------------------------------------------------------------------

    def start_production(self, started_by: str) -> WorkOrderEntity:
        """Change status to IN_PROGRESS and set actual start date."""
        if self.status != WorkOrderStatus.APPROVED:
            raise ValueError(f"Cannot start production in status {self.status.value}")
        return WorkOrderEntity(
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            bom_id=self.bom_id,
            bom_version=self.bom_version,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            status=WorkOrderStatus.IN_PROGRESS,
            priority=self.priority,
            planned_start_date=self.planned_start_date,
            planned_end_date=self.planned_end_date,
            actual_start_date=datetime.now(UTC),
            actual_end_date=self.actual_end_date,
            routing_id=self.routing_id,
            cost_center=self.cost_center,
            notes=self.notes,
            work_order_type=self.work_order_type,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=started_by,
            version=self.version + 1,
            material_standard_cost=self.material_standard_cost,
            labor_standard_cost=self.labor_standard_cost,
            overhead_standard_cost=self.overhead_standard_cost,
            material_actual_cost=self.material_actual_cost,
            labor_actual_cost=self.labor_actual_cost,
            overhead_actual_cost=self.overhead_actual_cost,
        )

    def complete_production(
        self, completed_quantity: Decimal, completed_by: str
    ) -> WorkOrderEntity:
        """Record completion of a batch."""
        if self.status != WorkOrderStatus.IN_PROGRESS:
            raise ValueError(f"Cannot complete production in status {self.status.value}")
        new_completed = self.completed_quantity + completed_quantity
        if new_completed > self.planned_quantity:
            raise ValueError(
                f"Completed quantity {new_completed} exceeds planned {self.planned_quantity}"
            )
        new_status = (
            WorkOrderStatus.COMPLETED
            if new_completed >= self.planned_quantity
            else WorkOrderStatus.PARTIALLY_COMPLETED
        )
        return WorkOrderEntity(
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            bom_id=self.bom_id,
            bom_version=self.bom_version,
            planned_quantity=self.planned_quantity,
            completed_quantity=new_completed,
            status=new_status,
            priority=self.priority,
            planned_start_date=self.planned_start_date,
            planned_end_date=self.planned_end_date,
            actual_start_date=self.actual_start_date,
            actual_end_date=datetime.now(UTC)
            if new_status == WorkOrderStatus.COMPLETED
            else self.actual_end_date,
            routing_id=self.routing_id,
            cost_center=self.cost_center,
            notes=self.notes,
            work_order_type=self.work_order_type,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=completed_by,
            version=self.version + 1,
            material_standard_cost=self.material_standard_cost,
            labor_standard_cost=self.labor_standard_cost,
            overhead_standard_cost=self.overhead_standard_cost,
            material_actual_cost=self.material_actual_cost,
            labor_actual_cost=self.labor_actual_cost,
            overhead_actual_cost=self.overhead_actual_cost,
        )

    def approve(self, approved_by: str) -> WorkOrderEntity:
        """Approve work order (DRAFT -> APPROVED)."""
        if self.status != WorkOrderStatus.DRAFT:
            raise ValueError(f"Cannot approve work order in status {self.status.value}")
        return WorkOrderEntity(
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            bom_id=self.bom_id,
            bom_version=self.bom_version,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            status=WorkOrderStatus.APPROVED,
            priority=self.priority,
            planned_start_date=self.planned_start_date,
            planned_end_date=self.planned_end_date,
            actual_start_date=self.actual_start_date,
            actual_end_date=self.actual_end_date,
            routing_id=self.routing_id,
            cost_center=self.cost_center,
            notes=self.notes,
            work_order_type=self.work_order_type,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=approved_by,
            version=self.version + 1,
            material_standard_cost=self.material_standard_cost,
            labor_standard_cost=self.labor_standard_cost,
            overhead_standard_cost=self.overhead_standard_cost,
            material_actual_cost=self.material_actual_cost,
            labor_actual_cost=self.labor_actual_cost,
            overhead_actual_cost=self.overhead_actual_cost,
        )

    def cancel(self, cancelled_by: str, reason: str) -> WorkOrderEntity:
        """Cancel the work order."""
        if self.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            raise ValueError(f"Cannot cancel work order in status {self.status.value}")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return WorkOrderEntity(
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            bom_id=self.bom_id,
            bom_version=self.bom_version,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            status=WorkOrderStatus.CANCELLED,
            priority=self.priority,
            planned_start_date=self.planned_start_date,
            planned_end_date=self.planned_end_date,
            actual_start_date=self.actual_start_date,
            actual_end_date=self.actual_end_date,
            routing_id=self.routing_id,
            cost_center=self.cost_center,
            notes=new_notes,
            work_order_type=self.work_order_type,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
            material_standard_cost=self.material_standard_cost,
            labor_standard_cost=self.labor_standard_cost,
            overhead_standard_cost=self.overhead_standard_cost,
            material_actual_cost=self.material_actual_cost,
            labor_actual_cost=self.labor_actual_cost,
            overhead_actual_cost=self.overhead_actual_cost,
        )

    def update_actual_costs(
        self,
        material_actual: Decimal | None = None,
        labor_actual: Decimal | None = None,
        overhead_actual: Decimal | None = None,
        updated_by: str = "system",
    ) -> WorkOrderEntity:
        """Update actual costs incurred."""
        new_material = material_actual if material_actual is not None else self.material_actual_cost
        new_labor = labor_actual if labor_actual is not None else self.labor_actual_cost
        new_overhead = overhead_actual if overhead_actual is not None else self.overhead_actual_cost
        return WorkOrderEntity(
            work_order_id=self.work_order_id,
            work_order_number=self.work_order_number,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            bom_id=self.bom_id,
            bom_version=self.bom_version,
            planned_quantity=self.planned_quantity,
            completed_quantity=self.completed_quantity,
            status=self.status,
            priority=self.priority,
            planned_start_date=self.planned_start_date,
            planned_end_date=self.planned_end_date,
            actual_start_date=self.actual_start_date,
            actual_end_date=self.actual_end_date,
            routing_id=self.routing_id,
            cost_center=self.cost_center,
            notes=self.notes,
            work_order_type=self.work_order_type,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
            material_standard_cost=self.material_standard_cost,
            labor_standard_cost=self.labor_standard_cost,
            overhead_standard_cost=self.overhead_standard_cost,
            material_actual_cost=new_material,
            labor_actual_cost=new_labor,
            overhead_actual_cost=new_overhead,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def is_completed(self) -> bool:
        """Return True if work order is fully completed."""
        return (
            self.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.PARTIALLY_COMPLETED)
            or self.completed_quantity >= self.planned_quantity
        )

    def is_overdue(self, as_of: datetime | None = None) -> bool:
        """Return True if work order is past its planned end date and not finished."""
        if self.status in (WorkOrderStatus.COMPLETED, WorkOrderStatus.CANCELLED):
            return False
        check_date = as_of or datetime.now(UTC)
        return check_date > self.planned_end_date

    def get_remaining_quantity(self) -> Decimal:
        """Return quantity still to produce."""
        return self.planned_quantity - self.completed_quantity

    def get_completion_percentage(self) -> float:
        """Return completion percentage (0-100)."""
        if self.planned_quantity == 0:
            return 0.0
        return float(self.completed_quantity / self.planned_quantity * 100)

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "work_order_id": str(self.work_order_id),
            "work_order_number": self.work_order_number,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "planned_quantity": str(self.planned_quantity),
            "completed_quantity": str(self.completed_quantity),
            "remaining_quantity": str(self.get_remaining_quantity()),
            "completion_percentage": self.get_completion_percentage(),
            "status": self.status.value,
            "priority": self.priority.value,
            "work_order_type": self.work_order_type.value,
            "planned_start_date": self.planned_start_date.isoformat(),
            "planned_end_date": self.planned_end_date.isoformat(),
            "actual_start_date": self.actual_start_date.isoformat()
            if self.actual_start_date
            else None,
            "actual_end_date": self.actual_end_date.isoformat() if self.actual_end_date else None,
            "is_overdue": self.is_overdue(),
            "material_standard_cost": str(self.material_standard_cost),
            "labor_standard_cost": str(self.labor_standard_cost),
            "overhead_standard_cost": str(self.overhead_standard_cost),
            "material_actual_cost": str(self.material_actual_cost),
            "labor_actual_cost": str(self.labor_actual_cost),
            "overhead_actual_cost": str(self.overhead_actual_cost),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Work Order Repository Protocol
# ============================================================================


class WorkOrderRepository:
    """Repository protocol for WorkOrderEntity."""

    async def get_by_id(self, work_order_id: UUID, legal_entity_id: UUID) -> WorkOrderEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, work_order_number: str, legal_entity_id: UUID
    ) -> WorkOrderEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self,
        product_id: UUID,
        legal_entity_id: UUID,
        status: WorkOrderStatus | None = None,
    ) -> list[WorkOrderEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self,
        legal_entity_id: UUID,
        from_date: datetime,
        to_date: datetime,
    ) -> list[WorkOrderEntity]:
        raise NotImplementedError

    async def save(self, work_order: WorkOrderEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, work_order_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================
WorkOrder = WorkOrderEntity

__all__ = [
    "WorkOrder",
    "WorkOrderEntity",
    "WorkOrderPriority",
    "WorkOrderRepository",
    "WorkOrderStatus",
    "WorkOrderType",
]
