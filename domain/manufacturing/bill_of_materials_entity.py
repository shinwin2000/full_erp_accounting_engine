#!/usr/bin/env python3
"""
Module: bill_of_materials_entity.py
Layer: 6 - Domain / Manufacturing
Responsibility: Bill of Materials (BOM) entity.
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


class BOMType(Enum):
    """Bill of Materials type."""

    SINGLE_LEVEL = "single_level"
    MULTI_LEVEL = "multi_level"
    PLANNING = "planning"

    @classmethod
    def from_string(cls, value: str) -> BOMType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.SINGLE_LEVEL


class BOMStatus(Enum):
    """BOM status."""

    DRAFT = "draft"
    ACTIVE = "active"
    OBSOLETE = "obsolete"

    @classmethod
    def from_string(cls, value: str) -> BOMStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


@dataclass(frozen=True)
class BOMItem:
    """
    Item within a Bill of Materials (immutable value object).

    Attributes:
        item_id: Unique identifier.
        item_code: Code of the component.
        item_name: Name of the component.
        quantity: Quantity required per assembly unit.
        unit_of_measure: Unit of measure (e.g., kg, pcs, liter).
        unit_cost: Cost per unit of the component.
        scrap_percentage: Expected scrap percentage (0-100).
        cost_element: Cost element classification.
        sub_bom_id: Optional reference to a sub-BOM for multi-level BOM.
        notes: Additional notes.
    """

    item_id: UUID
    item_code: str
    item_name: str
    quantity: Decimal
    unit_of_measure: str
    unit_cost: Decimal
    scrap_percentage: Decimal = Decimal(0)
    cost_element: CostElement = CostElement.MATERIAL
    sub_bom_id: UUID | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if not (0 <= self.scrap_percentage <= 100):
            raise ValueError(f"Scrap percentage must be between 0 and 100: {self.scrap_percentage}")
        if not self.item_code or len(self.item_code.strip()) < 2:
            raise ValueError("Item code must be at least 2 characters")
        if not self.item_name or len(self.item_name.strip()) < 2:
            raise ValueError("Item name must be at least 2 characters")
        if not self.unit_of_measure or len(self.unit_of_measure.strip()) < 1:
            raise ValueError("Unit of measure cannot be empty")

    @property
    def total_cost(self) -> Decimal:
        """Calculate total cost including scrap factor."""
        effective_quantity = self.quantity * (Decimal(1) + self.scrap_percentage / Decimal(100))
        return effective_quantity * self.unit_cost

    @property
    def effective_quantity(self) -> Decimal:
        """Calculate effective quantity including scrap."""
        return self.quantity * (Decimal(1) + self.scrap_percentage / Decimal(100))

    def clone(self) -> BOMItem:
        """Create a copy of this BOM item."""
        return BOMItem(
            item_id=uuid4(),
            item_code=self.item_code,
            item_name=self.item_name,
            quantity=self.quantity,
            unit_of_measure=self.unit_of_measure,
            unit_cost=self.unit_cost,
            scrap_percentage=self.scrap_percentage,
            cost_element=self.cost_element,
            sub_bom_id=self.sub_bom_id,
            notes=self.notes,
        )

    def normalize(self) -> BOMItem:
        """Normalize the BOM item (trim strings, round decimals)."""
        return BOMItem(
            item_id=self.item_id,
            item_code=self.item_code.strip().upper(),
            item_name=self.item_name.strip().title(),
            quantity=self.quantity.quantize(Decimal("0.001")),
            unit_of_measure=self.unit_of_measure.strip().lower(),
            unit_cost=self.unit_cost.quantize(Decimal("0.01")),
            scrap_percentage=self.scrap_percentage.quantize(Decimal("0.01")),
            cost_element=self.cost_element,
            sub_bom_id=self.sub_bom_id,
            notes=self.notes.strip() if self.notes else "",  # ensure str, not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "quantity": str(self.quantity),
            "unit_of_measure": self.unit_of_measure,
            "unit_cost": str(self.unit_cost),
            "scrap_percentage": str(self.scrap_percentage),
            "cost_element": self.cost_element.value,
            "sub_bom_id": str(self.sub_bom_id) if self.sub_bom_id else None,
            "total_cost": str(self.total_cost),
            "effective_quantity": str(self.effective_quantity),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BOMItem:
        # Ensure cost_element is never None
        cost_element_raw = data.get("cost_element", "material")
        cost_element = CostElement.from_string(cost_element_raw)
        if cost_element is None:
            cost_element = CostElement.MATERIAL

        return cls(
            item_id=UUID(data["item_id"]) if data.get("item_id") else uuid4(),
            item_code=data["item_code"],
            item_name=data["item_name"],
            quantity=Decimal(data["quantity"]),
            unit_of_measure=data["unit_of_measure"],
            unit_cost=Decimal(data["unit_cost"]),
            scrap_percentage=Decimal(data.get("scrap_percentage", "0")),
            cost_element=cost_element,
            sub_bom_id=UUID(data["sub_bom_id"]) if data.get("sub_bom_id") else None,
            notes=data.get("notes", ""),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BOMItem):
            return False
        return self.item_id == other.item_id

    def __hash__(self) -> int:
        return hash(self.item_id)


@dataclass(frozen=True)
class BillOfMaterialsEntity:
    """
    Bill of Materials entity (immutable).

    Business context:
    Defines product structure: which components and how many are needed
    to produce one unit of finished product.
    """

    bom_id: UUID
    bom_code: str
    product_id: UUID
    product_code: str
    product_name: str
    version: int
    quantity_per_assembly: Decimal
    unit_of_measure: str
    items: list[BOMItem] = field(default_factory=list)
    status: BOMStatus = BOMStatus.DRAFT
    routing_id: UUID | None = None
    effective_date: datetime | None = None
    expiry_date: datetime | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version_counter: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if len(self.bom_code.strip()) < 3:
            raise ValueError("BOM code must be at least 3 characters")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.quantity_per_assembly <= 0:
            raise ValueError(
                f"Quantity per assembly must be positive: {self.quantity_per_assembly}"
            )
        if self.version_counter < 1:
            raise ValueError(f"Version counter must be >= 1: {self.version_counter}")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        if self.updated_at.tzinfo is None:
            raise ValueError("updated_at must be timezone-aware")
        if self.effective_date and self.effective_date.tzinfo is None:
            raise ValueError("effective_date must be timezone-aware")
        if self.expiry_date and self.expiry_date.tzinfo is None:
            raise ValueError("expiry_date must be timezone-aware")

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version_counter,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== COST CALCULATION ====================

    def get_total_material_cost(self) -> Decimal:
        """Sum of material costs from all items."""
        total = Decimal(0)
        for item in self.items:
            if item.cost_element == CostElement.MATERIAL:
                total += item.total_cost
        return total

    def get_total_labor_cost(self) -> Decimal:
        """Sum of labor costs from all items."""
        total = Decimal(0)
        for item in self.items:
            if item.cost_element == CostElement.LABOR:
                total += item.total_cost
        return total

    def get_total_overhead_cost(self) -> Decimal:
        """Sum of overhead costs from all items."""
        total = Decimal(0)
        for item in self.items:
            if item.cost_element == CostElement.OVERHEAD:
                total += item.total_cost
        return total

    def get_total_cost(self) -> Decimal:
        """Total standard cost per unit of product."""
        total = Decimal(0)
        for item in self.items:
            total += item.total_cost
        return total

    def get_cost_by_element(self, element: CostElement) -> Decimal:
        """Get total cost for a specific cost element."""
        total = Decimal(0)
        for item in self.items:
            if item.cost_element == element:
                total += item.total_cost
        return total

    def get_item_count(self) -> int:
        """Get number of items in BOM."""
        return len(self.items)

    def get_effective_quantity(self) -> Decimal:
        """Get total effective quantity including scrap for all items."""
        total = Decimal(0)
        for item in self.items:
            total += item.effective_quantity
        return total

    # ==================== ITEM MANAGEMENT ====================

    def add_item(self, item: BOMItem, added_by: str) -> BillOfMaterialsEntity:
        """Add a component to the BOM."""
        if item.item_id in [i.item_id for i in self.items]:
            raise ValueError(f"Item {item.item_id} already exists in BOM")
        new_items = [*self.items, item]
        self._record_audit(
            "item_added", added_by, {"item_id": str(item.item_id), "item_code": item.item_code}
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=self.status,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version_counter=self.version_counter + 1,
        )

    def add_items_batch(self, items: list[BOMItem], added_by: str) -> BillOfMaterialsEntity:
        """Add multiple components to the BOM."""
        result = self
        for item in items:
            result = result.add_item(item, added_by)
        return result

    def remove_item(self, item_id: UUID, removed_by: str) -> BillOfMaterialsEntity:
        """Remove a component from the BOM."""
        item_to_remove = next((i for i in self.items if i.item_id == item_id), None)
        if not item_to_remove:
            raise ValueError(f"Item {item_id} not found in BOM")
        new_items = [i for i in self.items if i.item_id != item_id]
        self._record_audit(
            "item_removed",
            removed_by,
            {"item_id": str(item_id), "item_code": item_to_remove.item_code},
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=self.status,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version_counter=self.version_counter + 1,
        )

    def update_item_quantity(
        self, item_id: UUID, new_quantity: Decimal, updated_by: str
    ) -> BillOfMaterialsEntity:
        """Update the quantity of an existing component."""
        if new_quantity <= 0:
            raise ValueError("Quantity must be positive")
        new_items = []
        old_item = None
        for item in self.items:
            if item.item_id == item_id:
                old_item = item
                new_item = BOMItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=new_quantity,
                    unit_of_measure=item.unit_of_measure,
                    unit_cost=item.unit_cost,
                    scrap_percentage=item.scrap_percentage,
                    cost_element=item.cost_element,
                    sub_bom_id=item.sub_bom_id,
                    notes=item.notes,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        if not old_item:
            raise ValueError(f"Item {item_id} not found in BOM")
        self._record_audit(
            "item_quantity_updated",
            updated_by,
            {
                "item_id": str(item_id),
                "old_quantity": str(old_item.quantity),
                "new_quantity": str(new_quantity),
            },
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=self.status,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    def update_item_unit_cost(
        self, item_id: UUID, new_unit_cost: Decimal, updated_by: str
    ) -> BillOfMaterialsEntity:
        """Update the unit cost of an existing component."""
        if new_unit_cost < 0:
            raise ValueError("Unit cost cannot be negative")
        new_items = []
        old_item = None
        for item in self.items:
            if item.item_id == item_id:
                old_item = item
                new_item = BOMItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_of_measure=item.unit_of_measure,
                    unit_cost=new_unit_cost,
                    scrap_percentage=item.scrap_percentage,
                    cost_element=item.cost_element,
                    sub_bom_id=item.sub_bom_id,
                    notes=item.notes,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        if not old_item:
            raise ValueError(f"Item {item_id} not found in BOM")
        self._record_audit(
            "item_cost_updated",
            updated_by,
            {
                "item_id": str(item_id),
                "old_cost": str(old_item.unit_cost),
                "new_cost": str(new_unit_cost),
            },
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=self.status,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    def update_item_scrap(
        self, item_id: UUID, new_scrap_percentage: Decimal, updated_by: str
    ) -> BillOfMaterialsEntity:
        """Update the scrap percentage of an existing component."""
        if not (0 <= new_scrap_percentage <= 100):
            raise ValueError("Scrap percentage must be between 0 and 100")
        new_items = []
        old_item = None
        for item in self.items:
            if item.item_id == item_id:
                old_item = item
                new_item = BOMItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_of_measure=item.unit_of_measure,
                    unit_cost=item.unit_cost,
                    scrap_percentage=new_scrap_percentage,
                    cost_element=item.cost_element,
                    sub_bom_id=item.sub_bom_id,
                    notes=item.notes,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        if not old_item:
            raise ValueError(f"Item {item_id} not found in BOM")
        self._record_audit(
            "item_scrap_updated",
            updated_by,
            {
                "item_id": str(item_id),
                "old_scrap": str(old_item.scrap_percentage),
                "new_scrap": str(new_scrap_percentage),
            },
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=self.status,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    # ==================== STATUS TRANSITIONS ====================

    def activate(self, activated_by: str) -> BillOfMaterialsEntity:
        """Activate the BOM (set status to ACTIVE and effective date to now)."""
        if self.status != BOMStatus.DRAFT:
            raise ValueError(f"Cannot activate BOM in status {self.status.value}")
        if not self.items:
            raise ValueError("Cannot activate BOM with no items")
        self._record_audit("activated", activated_by, {})
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=self.items,
            status=BOMStatus.ACTIVE,
            routing_id=self.routing_id,
            effective_date=datetime.now(UTC),
            expiry_date=self.expiry_date,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=activated_by,
            version_counter=self.version_counter + 1,
        )

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> BillOfMaterialsEntity:
        """Deactivate the BOM (set status to DRAFT and clear effective date)."""
        if self.status != BOMStatus.ACTIVE:
            raise ValueError(f"Cannot deactivate BOM in status {self.status.value}")
        self._record_audit("deactivated", deactivated_by, {"reason": reason})
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=self.items,
            status=BOMStatus.DRAFT,
            routing_id=self.routing_id,
            effective_date=None,
            expiry_date=None,
            notes=f"{self.notes}\nDeactivated: {reason}" if reason else self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=deactivated_by,
            version_counter=self.version_counter + 1,
        )

    def obsoleted(self, obsoleted_by: str, reason: str) -> BillOfMaterialsEntity:
        """Mark the BOM as obsolete."""
        self._record_audit("obsoleted", obsoleted_by, {"reason": reason})
        new_notes = f"{self.notes}\nObsoleted: {reason}" if self.notes else f"Obsoleted: {reason}"
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=self.version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=self.items,
            status=BOMStatus.OBSOLETE,
            routing_id=self.routing_id,
            effective_date=self.effective_date,
            expiry_date=datetime.now(UTC),
            notes=new_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=obsoleted_by,
            version_counter=self.version_counter + 1,
        )

    def increment_version(self, new_version: int, updated_by: str) -> BillOfMaterialsEntity:
        """Create a new version of this BOM (preserves items, updates version number)."""
        if new_version <= self.version:
            raise ValueError(
                f"New version {new_version} must be greater than current version {self.version}"
            )
        self._record_audit(
            "version_incremented",
            updated_by,
            {"old_version": self.version, "new_version": new_version},
        )
        return BillOfMaterialsEntity(
            bom_id=self.bom_id,
            bom_code=self.bom_code,
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=new_version,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=self.items,
            status=BOMStatus.DRAFT,
            routing_id=self.routing_id,
            effective_date=None,
            expiry_date=None,
            notes=f"Version {new_version} created from v{self.version}",
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version_counter=self.version_counter + 1,
        )

    # ==================== VALIDATION ====================

    def validate(self) -> list[str]:
        """Validate BOM invariants."""
        errors = []
        if not self.items:
            errors.append("BOM must have at least one component")
        if self.quantity_per_assembly <= 0:
            errors.append("Quantity per assembly must be positive")
        # Check for duplicate item codes
        item_codes = [item.item_code for item in self.items]
        duplicates = {code for code in item_codes if item_codes.count(code) > 1}
        if duplicates:
            errors.append(f"Duplicate item codes found: {duplicates}")
        # Check for zero or negative quantities
        for item in self.items:
            if item.quantity <= 0:
                errors.append(f"Item {item.item_code} has non-positive quantity: {item.quantity}")
        return errors

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        """Create a snapshot of current BOM state."""
        return {
            "bom_id": str(self.bom_id),
            "bom_code": self.bom_code,
            "product_id": str(self.product_id),
            "version": self.version,
            "status": self.status.value,
            "total_cost": str(self.get_total_cost()),
            "item_count": len(self.items),
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ==================== CLONE ====================

    def clone(self) -> BillOfMaterialsEntity:
        """Create a copy of this BOM as a new draft."""
        new_items = [item.clone() for item in self.items]
        self._record_audit("cloned", "system", {"source_id": str(self.bom_id)})
        return BillOfMaterialsEntity(
            bom_id=uuid4(),
            bom_code=f"COPY-{self.bom_code}",
            product_id=self.product_id,
            product_code=self.product_code,
            product_name=self.product_name,
            version=1,
            quantity_per_assembly=self.quantity_per_assembly,
            unit_of_measure=self.unit_of_measure,
            items=new_items,
            status=BOMStatus.DRAFT,
            routing_id=self.routing_id,
            effective_date=None,
            expiry_date=None,
            notes=f"Copy of BOM {self.bom_code} v{self.version}",
            created_by=self.created_by,
        )

    # ==================== QUERY METHODS ====================

    def is_active_at(self, date: datetime) -> bool:
        """Return True if BOM is active on the given date."""
        return (
            self.status == BOMStatus.ACTIVE
            and (self.effective_date is None or date >= self.effective_date)
            and (self.expiry_date is None or date <= self.expiry_date)
        )

    def get_item_by_id(self, item_id: UUID) -> BOMItem | None:
        """Get an item by its ID."""
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    def get_item_by_code(self, item_code: str) -> BOMItem | None:
        """Get an item by its code."""
        for item in self.items:
            if item.item_code == item_code:
                return item
        return None

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of the BOM."""
        return {
            "bom_code": self.bom_code,
            "product_name": self.product_name,
            "version": self.version,
            "status": self.status.value,
            "total_cost": str(self.get_total_cost()),
            "total_material_cost": str(self.get_total_material_cost()),
            "total_labor_cost": str(self.get_total_labor_cost()),
            "total_overhead_cost": str(self.get_total_overhead_cost()),
            "item_count": len(self.items),
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
        }

    # ==================== DICTIONARY METHODS ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "bom_id": str(self.bom_id),
            "bom_code": self.bom_code,
            "product_id": str(self.product_id),
            "product_code": self.product_code,
            "product_name": self.product_name,
            "version": self.version,
            "quantity_per_assembly": str(self.quantity_per_assembly),
            "unit_of_measure": self.unit_of_measure,
            "items": [item.to_dict() for item in self.items],
            "total_material_cost": str(self.get_total_material_cost()),
            "total_labor_cost": str(self.get_total_labor_cost()),
            "total_overhead_cost": str(self.get_total_overhead_cost()),
            "total_cost": str(self.get_total_cost()),
            "status": self.status.value,
            "routing_id": str(self.routing_id) if self.routing_id else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version_counter": self.version_counter,
            "summary": self.get_summary(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BillOfMaterialsEntity:
        items = [BOMItem.from_dict(item_data) for item_data in data.get("items", [])]
        return cls(
            bom_id=UUID(data["bom_id"]),
            bom_code=data["bom_code"],
            product_id=UUID(data["product_id"]),
            product_code=data["product_code"],
            product_name=data["product_name"],
            version=data["version"],
            quantity_per_assembly=Decimal(data["quantity_per_assembly"]),
            unit_of_measure=data["unit_of_measure"],
            items=items,
            status=BOMStatus.from_string(data["status"]),
            routing_id=UUID(data["routing_id"]) if data.get("routing_id") else None,
            effective_date=datetime.fromisoformat(data["effective_date"])
            if data.get("effective_date")
            else None,
            expiry_date=datetime.fromisoformat(data["expiry_date"])
            if data.get("expiry_date")
            else None,
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version_counter=data.get("version_counter", 1),
        )


# ==================== REPOSITORY PROTOCOL ====================


class BillOfMaterialsRepository:
    async def get_by_id(self, bom_id: UUID, legal_entity_id: UUID) -> BillOfMaterialsEntity | None:
        raise NotImplementedError

    async def get_by_code(
        self, bom_code: str, legal_entity_id: UUID
    ) -> BillOfMaterialsEntity | None:
        raise NotImplementedError

    async def get_by_product(
        self, product_id: UUID, legal_entity_id: UUID, effective_date: datetime | None = None
    ) -> BillOfMaterialsEntity | None:
        raise NotImplementedError

    async def get_active_bom(
        self, product_id: UUID, legal_entity_id: UUID, as_of_date: datetime | None = None
    ) -> BillOfMaterialsEntity | None:
        raise NotImplementedError

    async def list_by_product(
        self, product_id: UUID, legal_entity_id: UUID, status: BOMStatus | None = None
    ) -> list[BillOfMaterialsEntity]:
        raise NotImplementedError

    async def save(self, bom: BillOfMaterialsEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, bom_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def exists(self, bom_code: str, legal_entity_id: UUID) -> bool:
        raise NotImplementedError


# ==================== ALIAS ====================

BillOfMaterials = BillOfMaterialsEntity

__all__ = [
    "BOMItem",
    "BOMStatus",
    "BOMType",
    "BillOfMaterials",
    "BillOfMaterialsEntity",
    "BillOfMaterialsRepository",
]
