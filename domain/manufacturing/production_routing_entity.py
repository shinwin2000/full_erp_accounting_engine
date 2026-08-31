#!/usr/bin/env python3
"""
Module: production_routing_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Production routing (sequence of operations).

Defines the production routing entity which specifies the order of operations,
work centers, and standard times required to produce a product.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every routing change is recorded via immutable updates.
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


class RoutingStatus(Enum):
    """Routing status."""

    DRAFT = "draft"
    ACTIVE = "active"
    OBSOLETE = "obsolete"


# ============================================================================
# Routing Operation (Value Object) - also aliased as RoutingStep
# ============================================================================


@dataclass(frozen=True)
class RoutingOperation:
    """
    Operation within a production routing (immutable value object).

    Business context:
    Represents one step in the production process, including work center,
    setup and run times, and labor/machine costs.

    Attributes:
        operation_id: Unique identifier.
        operation_code: Human-readable code.
        operation_name: Name of the operation.
        sequence: Order of execution (ascending).
        work_center_id: ID of the work center.
        work_center_name: Name of the work center.
        setup_time_hours: Setup time in hours (per batch).
        run_time_per_unit_hours: Run time per unit in hours.
        labor_cost_per_hour: Labor cost per hour.
        machine_cost_per_hour: Machine cost per hour.
        fixed_cost: Fixed cost per batch.
        description: Optional description.
    """

    operation_id: UUID
    operation_code: str
    operation_name: str
    sequence: int
    work_center_id: UUID
    work_center_name: str
    setup_time_hours: Decimal
    run_time_per_unit_hours: Decimal
    labor_cost_per_hour: Decimal
    machine_cost_per_hour: Decimal
    fixed_cost: Decimal = Decimal(0)
    description: str = ""

    def __post_init__(self) -> None:
        """Validate operation invariants."""
        if self.sequence < 0:
            raise ValueError(f"Sequence must be non-negative: {self.sequence}")
        if self.setup_time_hours < 0:
            raise ValueError(f"Setup time cannot be negative: {self.setup_time_hours}")
        if self.run_time_per_unit_hours < 0:
            raise ValueError(f"Run time cannot be negative: {self.run_time_per_unit_hours}")
        if self.labor_cost_per_hour < 0:
            raise ValueError(f"Labor cost per hour cannot be negative: {self.labor_cost_per_hour}")
        if self.machine_cost_per_hour < 0:
            raise ValueError(
                f"Machine cost per hour cannot be negative: {self.machine_cost_per_hour}"
            )
        if self.fixed_cost < 0:
            raise ValueError(f"Fixed cost cannot be negative: {self.fixed_cost}")

    def get_total_labor_cost(self, quantity: Decimal) -> Decimal:
        """Calculate total labor cost for a given quantity."""
        total_hours = self.setup_time_hours + (self.run_time_per_unit_hours * quantity)
        return total_hours * self.labor_cost_per_hour

    def get_total_machine_cost(self, quantity: Decimal) -> Decimal:
        """Calculate total machine cost for a given quantity."""
        total_hours = self.setup_time_hours + (self.run_time_per_unit_hours * quantity)
        return total_hours * self.machine_cost_per_hour

    def get_total_cost(self, quantity: Decimal) -> Decimal:
        """Calculate total cost for this operation (labor + machine + fixed)."""
        return (
            self.get_total_labor_cost(quantity)
            + self.get_total_machine_cost(quantity)
            + self.fixed_cost
        )

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "operation_id": str(self.operation_id),
            "operation_code": self.operation_code,
            "operation_name": self.operation_name,
            "sequence": self.sequence,
            "work_center_id": str(self.work_center_id),
            "work_center_name": self.work_center_name,
            "setup_time_hours": str(self.setup_time_hours),
            "run_time_per_unit_hours": str(self.run_time_per_unit_hours),
            "labor_cost_per_hour": str(self.labor_cost_per_hour),
            "machine_cost_per_hour": str(self.machine_cost_per_hour),
            "fixed_cost": str(self.fixed_cost),
            "description": self.description,
        }


# Alias for backward compatibility with code expecting RoutingStep
RoutingStep = RoutingOperation


# ============================================================================
# Production Routing Entity
# ============================================================================


@dataclass(frozen=True)
class ProductionRoutingEntity:
    """
    Production routing entity (immutable).

    Business context:
    Defines the sequence of production operations for a product,
    including work centers and standard times.

    Attributes:
        routing_id: Unique identifier.
        routing_code: Human-readable code.
        product_id: ID of the product.
        product_code: Product code.
        product_name: Product name.
        version: Version number.
        operations: List of RoutingOperation (sorted by sequence).
        status: Routing status.
        effective_date: Date when routing becomes effective.
        expiry_date: Date when routing expires.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version_counter: Optimistic concurrency counter.
    """

    routing_id: UUID
    routing_code: str
    product_id: UUID
    product_code: str
    product_name: str
    version: int
    operations: list[RoutingOperation] = field(default_factory=list)
    status: RoutingStatus = RoutingStatus.DRAFT
    effective_date: datetime | None = None
    expiry_date: datetime | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version_counter: int = 1

    def __post_init__(self) -> None:
        """Validate routing invariants."""
        if len(self.routing_code.strip()) < 3:
            raise ValueError("Routing code must be at least 3 characters")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.version_counter < 1:
            raise ValueError(f"Version counter must be >= 1: {self.version_counter}")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        # Check for duplicate sequence numbers
        sequences = [op.sequence for op in self.operations]
        if len(sequences) != len(set(sequences)):
            raise ValueError("Duplicate sequence numbers found in operations")

    # ------------------------------------------------------------------------
    # Cost calculation methods
    # ------------------------------------------------------------------------

    def get_total_setup_time(self) -> Decimal:
        """Total setup time across all operations (hours)."""
        return sum((op.setup_time_hours for op in self.operations), Decimal(0))

    def get_total_run_time_per_unit(self) -> Decimal:
        """Total run time per unit across all operations (hours)."""
        return sum((op.run_time_per_unit_hours for op in self.operations), Decimal(0))

    def get_total_labor_cost(self, quantity: Decimal) -> Decimal:
        """Total labor cost for producing the given quantity."""
        return sum((op.get_total_labor_cost(quantity) for op in self.operations), Decimal(0))

    def get_total_machine_cost(self, quantity: Decimal) -> Decimal:
        """Total machine cost for producing the given quantity."""
        return sum((op.get_total_machine_cost(quantity) for op in self.operations), Decimal(0))

    def get_total_routing_cost(self, quantity: Decimal) -> Decimal:
        """Total routing cost (labor + machine + fixed) for the given quantity."""
        return sum((op.get_total_cost(quantity) for op in self.operations), Decimal(0))

    def get_cost_per_unit(self, quantity: Decimal) -> Decimal:
        """Average routing cost per unit for the given quantity."""
        if quantity <= 0:
            return Decimal(0)
        return self.get_total_routing_cost(quantity) / quantity

    # ------------------------------------------------------------------------
    # Operation management (return new instance)
    # ------------------------------------------------------------------------

    def _sort_operations(self, ops: list[RoutingOperation]) -> list[RoutingOperation]:
        """Return operations sorted by sequence."""
        return sorted(ops, key=lambda op: op.sequence)

    def add_operation(self, operation: RoutingOperation, added_by: str) -> ProductionRoutingEntity:
        """Add an operation to the routing."""
        new_ops = self._sort_operations([*self.operations, operation])
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            operations=new_ops,
            status=self.status,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version_counter=self.version_counter + 1,
        )

    def remove_operation(self, operation_id: UUID, removed_by: str) -> ProductionRoutingEntity:
        """Remove an operation from the routing."""
        new_ops = [op for op in self.operations if op.operation_id != operation_id]
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            operations=new_ops,
            status=self.status,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version_counter=self.version_counter + 1,
        )

    def update_operation(
        self,
        operation_id: UUID,
        new_setup_time: Decimal | None = None,
        new_run_time: Decimal | None = None,
        new_labor_rate: Decimal | None = None,
        new_machine_rate: Decimal | None = None,
        new_fixed_cost: Decimal | None = None,
        updated_by: str = "system",
    ) -> ProductionRoutingEntity:
        """Update specific fields of an operation."""
        new_ops = []
        for op in self.operations:
            if op.operation_id == operation_id:
                new_op = RoutingOperation(
                    operation_id=op.operation_id,
                    operation_code=op.operation_code,
                    operation_name=op.operation_name,
                    sequence=op.sequence,
                    work_center_id=op.work_center_id,
                    work_center_name=op.work_center_name,
                    setup_time_hours=new_setup_time
                    if new_setup_time is not None
                    else op.setup_time_hours,
                    run_time_per_unit_hours=new_run_time
                    if new_run_time is not None
                    else op.run_time_per_unit_hours,
                    labor_cost_per_hour=new_labor_rate
                    if new_labor_rate is not None
                    else op.labor_cost_per_hour,
                    machine_cost_per_hour=new_machine_rate
                    if new_machine_rate is not None
                    else op.machine_cost_per_hour,
                    fixed_cost=new_fixed_cost if new_fixed_cost is not None else op.fixed_cost,
                    description=op.description,
                )
                new_ops.append(new_op)
            else:
                new_ops.append(op)
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            operations=new_ops,
            status=self.status,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def activate(self, activated_by: str) -> ProductionRoutingEntity:
        """Activate the routing."""
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            operations=self.operations,
            status=RoutingStatus.ACTIVE,
            effective_date=datetime.now(UTC),
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version_counter=self.version_counter + 1,
        )

    def obsoleted(self, obsoleted_by: str, reason: str) -> ProductionRoutingEntity:
        """Mark the routing as obsolete."""
        new_notes = f"{self.notes}\nObsoleted: {reason}" if self.notes else f"Obsoleted: {reason}"
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            operations=self.operations,
            status=RoutingStatus.OBSOLETE,
            effective_date=self.effective_date,
            expiry_date=datetime.now(UTC),
            notes=new_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=obsoleted_by,
            version_counter=self.version_counter + 1,
        )

    def increment_version(self, new_version: int, updated_by: str) -> ProductionRoutingEntity:
        """Create a new draft version of this routing."""
        return ProductionRoutingEntity(
            routing_id=self.routing_id,
            routing_code=self.routing_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=new_version,
            operations=self.operations,
            status=RoutingStatus.DRAFT,
            effective_date=None,
            expiry_date=None,
            notes=f"Version {new_version} created from v{self.version}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def is_active_at(self, date: datetime) -> bool:
        """Return True if routing is active on the given date."""
        return (
            self.status == RoutingStatus.ACTIVE
            and (self.effective_date is None or date >= self.effective_date)
            and (self.expiry_date is None or date <= self.expiry_date)
        )

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "routing_id": str(self.routing_id),
            "routing_code": self.routing_code,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "version": self.version,
            "operations": [op.to_dict() for op in self.operations],
            "total_setup_time": str(self.get_total_setup_time()),
            "total_run_time_per_unit": str(self.get_total_run_time_per_unit()),
            "status": self.status.value,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version_counter": self.version_counter,
        }


# ============================================================================
# Production Routing Repository Protocol
# ============================================================================


class ProductionRoutingRepository:
    """Repository protocol for ProductionRoutingEntity."""

    async def get_by_id(
        self, routing_id: UUID, legal_entity_id: UUID
    ) -> ProductionRoutingEntity | None:
        raise NotImplementedError

    async def get_by_code(
        self, routing_code: str, legal_entity_id: UUID
    ) -> ProductionRoutingEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self,
        product_id: UUID,
        legal_entity_id: UUID,
        effective_date: datetime | None = None,
    ) -> ProductionRoutingEntity | None:
        raise NotImplementedError

    async def save(self, routing: ProductionRoutingEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, routing_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports (including alias for backward compatibility)
# ============================================================================

# Aliases
ProductionRouting = ProductionRoutingEntity

__all__ = [
    "ProductionRouting",
    "ProductionRoutingEntity",
    "ProductionRoutingRepository",
    "RoutingOperation",
    "RoutingStatus",
    "RoutingStep",
]
