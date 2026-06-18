# inventory_request.py - Hardened version with complete implementation

#!/usr/bin/env python3
"""
Module: inventory_request.py
Layer: Application / DTO Objects
Responsibility: Data Transfer Objects for Inventory Management requests.

Fitur:
- Item management (create, update)
- Stock movement (in/out/adjustment)
- Stock opname (physical count)
- Inter-warehouse transfer
- COGS calculation
- Inventory valuation
- Low stock alerts
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class CreateItemRequestDTO:
    """Request DTO for creating a new inventory item."""

    legal_entity_id: UUID
    sku: str
    name: str
    description: str | None = None
    item_type: str = "finished_good"
    uom: str = "pcs"
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    minimum_stock: Decimal | None = None
    standard_cost: Decimal = Decimal(0)
    selling_price: Decimal = Decimal(0)
    warehouse_code: str | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.sku or len(self.sku.strip()) < 3:
            raise ValueError("SKU must be at least 3 characters")
        if not self.name:
            raise ValueError("Item name is required")
        valid_item_types = [
            "raw_material",
            "work_in_progress",
            "finished_good",
            "packaging",
            "spare_part",
        ]
        if self.item_type not in valid_item_types:
            raise ValueError(f"Invalid item_type: {self.item_type}")
        if self.reorder_point is not None and self.reorder_point < 0:
            raise ValueError(f"Reorder point cannot be negative: {self.reorder_point}")
        if self.safety_stock is not None and self.safety_stock < 0:
            raise ValueError(f"Safety stock cannot be negative: {self.safety_stock}")
        if self.standard_cost < 0:
            raise ValueError(f"Standard cost cannot be negative: {self.standard_cost}")
        if self.selling_price < 0:
            raise ValueError(f"Selling price cannot be negative: {self.selling_price}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "uom": self.uom,
            "category": self.category,
            "brand": self.brand,
            "reorder_point": str(self.reorder_point) if self.reorder_point else None,
            "safety_stock": str(self.safety_stock) if self.safety_stock else None,
            "maximum_stock": str(self.maximum_stock) if self.maximum_stock else None,
            "minimum_stock": str(self.minimum_stock) if self.minimum_stock else None,
            "standard_cost": str(self.standard_cost),
            "selling_price": str(self.selling_price),
            "warehouse_code": self.warehouse_code,
            "is_active": self.is_active,
        }


@dataclass(kw_only=True)
class UpdateItemRequestDTO:
    """Request DTO for updating an existing item."""

    item_id: UUID
    name: str | None = None
    description: str | None = None
    category: str | None = None
    brand: str | None = None
    reorder_point: Decimal | None = None
    safety_stock: Decimal | None = None
    standard_cost: Decimal | None = None
    selling_price: Decimal | None = None
    minimum_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    is_active: bool | None = None

    def __post_init__(self) -> None:
        if not any(
            [
                self.name,
                self.description,
                self.category,
                self.brand,
                self.reorder_point,
                self.safety_stock,
                self.standard_cost,
                self.selling_price,
                self.minimum_stock,
                self.maximum_stock,
                self.is_active is not None,
            ]
        ):
            raise ValueError("At least one field to update must be provided")
        if self.name and len(self.name.strip()) < 2:
            raise ValueError("Item name must be at least 2 characters")
        if self.reorder_point is not None and self.reorder_point < 0:
            raise ValueError(f"Reorder point cannot be negative: {self.reorder_point}")
        if self.safety_stock is not None and self.safety_stock < 0:
            raise ValueError(f"Safety stock cannot be negative: {self.safety_stock}")

    def to_dict(self) -> dict[str, Any]:
        result = {"item_id": str(self.item_id)}
        if self.name is not None:
            result["name"] = self.name
        if self.description is not None:
            result["description"] = self.description
        if self.category is not None:
            result["category"] = self.category
        if self.brand is not None:
            result["brand"] = self.brand
        if self.reorder_point is not None:
            result["reorder_point"] = str(self.reorder_point)
        if self.safety_stock is not None:
            result["safety_stock"] = str(self.safety_stock)
        if self.standard_cost is not None:
            result["standard_cost"] = str(self.standard_cost)
        if self.selling_price is not None:
            result["selling_price"] = str(self.selling_price)
        if self.minimum_stock is not None:
            result["minimum_stock"] = str(self.minimum_stock)
        if self.maximum_stock is not None:
            result["maximum_stock"] = str(self.maximum_stock)
        if self.is_active is not None:
            result["is_active"] = self.is_active
        return result


@dataclass(kw_only=True)
class StockMovementRequestDTO:
    """Request DTO for stock movement (in/out/adjustment)."""

    legal_entity_id: UUID
    item_id: UUID
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal | None = None
    reference_document_type: str | None = None
    reference_document_number: str | None = None
    movement_date: date | None = None
    warehouse_code: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        valid_movement_types = [
            "IN",
            "OUT",
            "ADJUSTMENT_IN",
            "ADJUSTMENT_OUT",
            "TRANSFER_IN",
            "TRANSFER_OUT",
        ]
        if self.movement_type not in valid_movement_types:
            raise ValueError(f"Invalid movement_type: {self.movement_type}")
        if self.unit_cost is not None and self.unit_cost < 0:
            raise ValueError(f"Unit cost cannot be negative: {self.unit_cost}")
        if self.movement_date is None:
            from datetime import date

            object.__setattr__(self, "movement_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "item_id": str(self.item_id),
            "movement_type": self.movement_type,
            "quantity": str(self.quantity),
            "unit_cost": str(self.unit_cost) if self.unit_cost else None,
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "movement_date": self.movement_date.isoformat(),
            "warehouse_code": self.warehouse_code,
            "notes": self.notes,
        }


@dataclass(kw_only=True)
class StockOpnameRequestDTO:
    """Request DTO for stock opname (physical count)."""

    legal_entity_id: UUID
    item_id: UUID
    physical_quantity: Decimal
    opname_date: date | None = None
    notes: str | None = None
    counted_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.physical_quantity < 0:
            raise ValueError(f"Physical quantity cannot be negative: {self.physical_quantity}")
        if self.opname_date is None:
            from datetime import date

            object.__setattr__(self, "opname_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "item_id": str(self.item_id),
            "physical_quantity": str(self.physical_quantity),
            "opname_date": self.opname_date.isoformat(),
            "notes": self.notes,
            "counted_by": str(self.counted_by) if self.counted_by else None,
        }


@dataclass(kw_only=True)
class TransferRequestDTO:
    """Request DTO for inter-warehouse transfer."""

    legal_entity_id: UUID
    item_id: UUID
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    transfer_date: date | None = None
    notes: str | None = None
    requested_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.from_warehouse == self.to_warehouse:
            raise ValueError("Source and destination warehouses cannot be the same")
        if self.transfer_date is None:
            from datetime import date

            object.__setattr__(self, "transfer_date", date.today())

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "item_id": str(self.item_id),
            "from_warehouse": self.from_warehouse,
            "to_warehouse": self.to_warehouse,
            "quantity": str(self.quantity),
            "transfer_date": self.transfer_date.isoformat(),
            "notes": self.notes,
            "requested_by": str(self.requested_by) if self.requested_by else None,
        }


@dataclass(kw_only=True)
class COGSCalculationRequestDTO:
    """Request DTO for COGS calculation over a period."""

    legal_entity_id: UUID
    period_start: date
    period_end: date

    def __post_init__(self) -> None:
        if self.period_start >= self.period_end:
            raise ValueError("period_start must be before period_end")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
        }


@dataclass(kw_only=True)
class InventoryValuationRequestDTO:
    """Request DTO for inventory valuation as of a date."""

    legal_entity_id: UUID
    as_of_date: date
    warehouse_code: str | None = None
    valuation_method: str = "FIFO"  # FIFO, LIFO, AVERAGE, STANDARD

    def __post_init__(self) -> None:
        valid_methods = ["FIFO", "LIFO", "AVERAGE", "STANDARD"]
        if self.valuation_method.upper() not in valid_methods:
            raise ValueError(f"Invalid valuation_method: {self.valuation_method}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "warehouse_code": self.warehouse_code,
            "valuation_method": self.valuation_method,
        }


@dataclass(kw_only=True)
class LowStockAlertQueryDTO:
    """Query DTO for low stock alerts."""

    legal_entity_id: UUID
    warehouse_code: str | None = None
    include_zero_stock: bool = False
    threshold_percentage: Decimal = Decimal(
        20
    )  # Alert when stock below reorder point by this percentage

    def __post_init__(self) -> None:
        if self.threshold_percentage < 0 or self.threshold_percentage > 100:
            raise ValueError(
                f"threshold_percentage must be between 0 and 100: {self.threshold_percentage}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "warehouse_code": self.warehouse_code,
            "include_zero_stock": self.include_zero_stock,
            "threshold_percentage": str(self.threshold_percentage),
        }


# Aliases for router compatibility
ItemCreateRequest = CreateItemRequestDTO
ItemUpdateRequest = UpdateItemRequestDTO
StockMovementRequest = StockMovementRequestDTO
StockOpnameRequest = StockOpnameRequestDTO
InterWarehouseTransferRequest = TransferRequestDTO
COGSCalculationRequest = COGSCalculationRequestDTO
InventoryValuationRequest = InventoryValuationRequestDTO
LowStockAlertQuery = LowStockAlertQueryDTO


__all__ = [
    "COGSCalculationRequest",
    "COGSCalculationRequestDTO",
    "CreateItemRequestDTO",
    "InterWarehouseTransferRequest",
    "InventoryValuationRequest",
    "InventoryValuationRequestDTO",
    "ItemCreateRequest",
    "ItemUpdateRequest",
    "LowStockAlertQuery",
    "LowStockAlertQueryDTO",
    "StockMovementRequest",
    "StockMovementRequestDTO",
    "StockOpnameRequest",
    "StockOpnameRequestDTO",
    "TransferRequestDTO",
    "UpdateItemRequestDTO",
]
