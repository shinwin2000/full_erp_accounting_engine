#!/usr/bin/env python3
"""
Module: standard_cost_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Standard cost per product.

Defines the standard cost entity for a product, used as a benchmark
to measure production efficiency and calculate variances.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)
- domain.manufacturing.cost_element_enum (CostElement)

Audit: Every standard cost change is recorded via immutable updates.
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


class StandardCostStatus(Enum):
    """Standard cost status."""

    DRAFT = "draft"
    ACTIVE = "active"
    OBSOLETE = "obsolete"


# ============================================================================
# Standard Cost Component (Value Object)
# ============================================================================


@dataclass(frozen=True)
class StandardCostComponent:
    """
    Component of standard cost (immutable value object).

    Attributes:
        cost_element: Type of cost.
        amount: Standard cost amount.
        quantity: Optional standard quantity (e.g., kg per unit).
        unit_cost: Optional standard unit cost.
        notes: Additional notes.
    """

    cost_element: CostElement
    amount: Decimal
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError(f"Amount cannot be negative: {self.amount}")
        if self.quantity is not None and self.quantity < 0:
            raise ValueError(f"Quantity cannot be negative: {self.quantity}")
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_element": self.cost_element.value,
            "amount": str(self.amount),
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "unit_cost": str(self.unit_cost) if self.unit_cost is not None else None,
            "notes": self.notes,
        }


# ============================================================================
# Standard Cost Entity
# ============================================================================


@dataclass(frozen=True)
class StandardCostEntity:
    """
    Standard cost entity for a product (immutable).

    Business context:
    Defines the standard cost for one unit of product,
    used as a reference for comparing actual costs and calculating variances.

    Invariants:
    - All cost components must be non-negative.
    - total_cost must equal material_cost + labor_cost + overhead_cost (within 0.01 tolerance).
    - Effective date must be provided and timezone-aware.

    Attributes:
        standard_cost_id: Unique identifier.
        product_id: Product ID.
        product_code: Product code.
        product_name: Product name.
        version: Version number (starts at 1).
        effective_date: Date from which this standard cost is effective.
        material_cost: Standard material cost per unit.
        labor_cost: Standard labor cost per unit.
        overhead_cost: Standard overhead cost per unit.
        total_cost: Total standard cost per unit.
        components: Detailed list of cost components.
        status: Standard cost status.
        expiry_date: Optional expiry date.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version_counter: Optimistic concurrency counter.
    """

    standard_cost_id: UUID
    product_id: UUID
    product_code: str
    product_name: str
    version: int
    effective_date: datetime
    material_cost: Decimal
    labor_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    components: list[StandardCostComponent] = field(default_factory=list)
    status: StandardCostStatus = StandardCostStatus.DRAFT
    expiry_date: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version_counter: int = 1

    def __post_init__(self) -> None:
        """Validate standard cost invariants."""
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.version_counter < 1:
            raise ValueError(f"Version counter must be >= 1: {self.version_counter}")
        if self.material_cost < 0:
            raise ValueError(f"Material cost cannot be negative: {self.material_cost}")
        if self.labor_cost < 0:
            raise ValueError(f"Labor cost cannot be negative: {self.labor_cost}")
        if self.overhead_cost < 0:
            raise ValueError(f"Overhead cost cannot be negative: {self.overhead_cost}")
        # Allow small rounding difference
        calc_total = self.material_cost + self.labor_cost + self.overhead_cost
        diff = abs(self.total_cost - calc_total)
        if diff > Decimal("0.01"):
            raise ValueError(
                f"Total cost mismatch: {self.total_cost} vs sum of components {calc_total}"
            )
        if self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware")
        if self.expiry_date and self.expiry_date.tzinfo is None:
            raise ValueError("expiry_date must be timezone-aware if provided")
        if self.expiry_date and self.expiry_date <= self.effective_date:
            raise ValueError("expiry_date must be after effective_date")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")

    # ------------------------------------------------------------------------
    # Factory method
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        product_id: UUID,
        product_code: str,
        product_name: str,
        material_cost: Decimal,
        labor_cost: Decimal,
        overhead_cost: Decimal,
        effective_date: datetime,
        created_by: str,
    ) -> StandardCostEntity:
        """Create a new standard cost entity."""
        total_cost = material_cost + labor_cost + overhead_cost
        components = [
            StandardCostComponent(
                cost_element=CostElement.MATERIAL,
                amount=material_cost,
            ),
            StandardCostComponent(
                cost_element=CostElement.LABOR,
                amount=labor_cost,
            ),
            StandardCostComponent(
                cost_element=CostElement.OVERHEAD,
                amount=overhead_cost,
            ),
        ]
        return cls(
            standard_cost_id=uuid4(),
            product_id=product_id,
            product_code=product_code,
            product_name=product_name,
            version=1,
            effective_date=effective_date,
            material_cost=material_cost,
            labor_cost=labor_cost,
            overhead_cost=overhead_cost,
            total_cost=total_cost,
            components=components,
            created_by=created_by,
        )

    # ------------------------------------------------------------------------
    # Update methods (return new instance)
    # ------------------------------------------------------------------------

    def update_cost(
        self,
        material_cost: Decimal | None = None,
        labor_cost: Decimal | None = None,
        overhead_cost: Decimal | None = None,
        updated_by: str = "system",
    ) -> StandardCostEntity:
        """Update cost components (creates a new version)."""
        new_material = material_cost if material_cost is not None else self.material_cost
        new_labor = labor_cost if labor_cost is not None else self.labor_cost
        new_overhead = overhead_cost if overhead_cost is not None else self.overhead_cost
        new_total = new_material + new_labor + new_overhead

        # Update components list
        new_components = []
        for comp in self.components:
            if comp.cost_element == CostElement.MATERIAL:
                new_components.append(
                    StandardCostComponent(
                        cost_element=comp.cost_element,
                        amount=new_material,
                        quantity=comp.quantity,
                        unit_cost=comp.unit_cost,
                        notes=comp.notes,
                    )
                )
            elif comp.cost_element == CostElement.LABOR:
                new_components.append(
                    StandardCostComponent(
                        cost_element=comp.cost_element,
                        amount=new_labor,
                        quantity=comp.quantity,
                        unit_cost=comp.unit_cost,
                        notes=comp.notes,
                    )
                )
            elif comp.cost_element == CostElement.OVERHEAD:
                new_components.append(
                    StandardCostComponent(
                        cost_element=comp.cost_element,
                        amount=new_overhead,
                        quantity=comp.quantity,
                        unit_cost=comp.unit_cost,
                        notes=comp.notes,
                    )
                )
            else:
                new_components.append(comp)

        return StandardCostEntity(
            standard_cost_id=self.standard_cost_id,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version + 1,
            effective_date=self.effective_date,
            material_cost=new_material,
            labor_cost=new_labor,
            overhead_cost=new_overhead,
            total_cost=new_total,
            components=new_components,
            status=StandardCostStatus.DRAFT,  # New version starts as DRAFT
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    def update_effective_date(
        self, new_effective_date: datetime, updated_by: str
    ) -> StandardCostEntity:
        """Update the effective date (creates a new version)."""
        return StandardCostEntity(
            standard_cost_id=self.standard_cost_id,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version + 1,
            effective_date=new_effective_date,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            components=self.components,
            status=StandardCostStatus.DRAFT,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def activate(self, activated_by: str) -> StandardCostEntity:
        """Activate this standard cost (DRAFT -> ACTIVE)."""
        if self.status != StandardCostStatus.DRAFT:
            raise ValueError(f"Cannot activate standard cost in status {self.status.value}")
        return StandardCostEntity(
            standard_cost_id=self.standard_cost_id,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            effective_date=self.effective_date,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            components=self.components,
            status=StandardCostStatus.ACTIVE,
            expiry_date=self.expiry_date,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version_counter=self.version_counter + 1,
        )

    def obsoleted(self, obsoleted_by: str, reason: str) -> StandardCostEntity:
        """Mark this standard cost as obsolete."""
        new_notes = f"Obsoleted: {reason}"
        # Add note to components using iterable unpacking
        new_components = [*self.components, StandardCostComponent(
            cost_element=CostElement.OTHER,
            amount=Decimal(0),
            notes=new_notes,
        )]
        return StandardCostEntity(
            standard_cost_id=self.standard_cost_id,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            effective_date=self.effective_date,
            material_cost=self.material_cost,
            labor_cost=self.labor_cost,
            overhead_cost=self.overhead_cost,
            total_cost=self.total_cost,
            components=new_components,
            status=StandardCostStatus.OBSOLETE,
            expiry_date=datetime.now(UTC),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=obsoleted_by,
            version_counter=self.version_counter + 1,
        )

    # ------------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------------

    def is_active_at_date(self, date: datetime) -> bool:
        """Check if this standard cost is active on the given date."""
        return (
            self.status == StandardCostStatus.ACTIVE
            and date >= self.effective_date
            and (self.expiry_date is None or date <= self.expiry_date)
        )

    def get_cost_by_element(self, element: CostElement) -> Decimal:
        """Get the standard cost for a specific cost element."""
        if element == CostElement.MATERIAL:
            return self.material_cost
        elif element == CostElement.LABOR:
            return self.labor_cost
        elif element == CostElement.OVERHEAD:
            return self.overhead_cost
        else:
            # For other elements, search in components
            for comp in self.components:
                if comp.cost_element == element:
                    return comp.amount
            return Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "standard_cost_id": str(self.standard_cost_id),
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "version": self.version,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "material_cost": str(self.material_cost),
            "labor_cost": str(self.labor_cost),
            "overhead_cost": str(self.overhead_cost),
            "total_cost": str(self.total_cost),
            "components": [c.to_dict() for c in self.components],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version_counter": self.version_counter,
        }


# ============================================================================
# Standard Cost Repository Protocol
# ============================================================================


class StandardCostRepository:
    """Repository protocol for StandardCostEntity."""

    async def get_by_id(
        self, standard_cost_id: UUID, legal_entity_id: UUID
    ) -> StandardCostEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self,
        product_id: UUID,
        legal_entity_id: UUID,
        as_of_date: datetime | None = None,
    ) -> StandardCostEntity | None:
        raise NotImplementedError

    async def get_active(
        self, product_id: UUID, legal_entity_id: UUID
    ) -> StandardCostEntity | None:
        raise NotImplementedError

    async def save(self, standard_cost: StandardCostEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, standard_cost_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports (including alias for backward compatibility)
# ============================================================================

# Alias to match import name used in service_manufacturing.py
StandardCost = StandardCostEntity

__all__ = [
    "StandardCost",
    "StandardCostComponent",
    "StandardCostEntity",
    "StandardCostRepository",
    "StandardCostStatus",
]
