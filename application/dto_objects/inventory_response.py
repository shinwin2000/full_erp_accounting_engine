#!/usr/bin/env python3

"""
Module: inventory_response.py
Layer: 8 - Application / DTO Objects
Responsibility: Response DTOs untuk Inventory Service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(kw_only=True)
class ItemResponseDTO:
    """Response DTO untuk item."""

    id: UUID
    sku: str
    name: str
    description: str | None
    item_type: str
    uom: str
    current_stock: Decimal
    current_stock_value: Decimal
    average_cost: Decimal
    last_cost: Decimal
    reorder_point: Decimal
    safety_stock: Decimal
    minimum_stock: Decimal | None = None
    maximum_stock: Decimal | None = None
    standard_cost: Decimal
    selling_price: Decimal
    category: str | None
    brand: str | None = None
    warehouse_code: str | None
    status: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    version: int = 1

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at and self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "item_type": self.item_type,
            "uom": self.uom,
            "current_stock": float(self.current_stock),
            "current_stock_value": float(self.current_stock_value),
            "average_cost": float(self.average_cost),
            "last_cost": float(self.last_cost),
            "reorder_point": float(self.reorder_point),
            "safety_stock": float(self.safety_stock),
            "minimum_stock": float(self.minimum_stock) if self.minimum_stock else None,
            "maximum_stock": float(self.maximum_stock) if self.maximum_stock else None,
            "standard_cost": float(self.standard_cost),
            "selling_price": float(self.selling_price),
            "category": self.category,
            "brand": self.brand,
            "warehouse_code": self.warehouse_code,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "version": self.version,
        }

    def is_low_stock(self) -> bool:
        """Check if item is below reorder point."""
        return self.current_stock <= self.reorder_point

    def is_out_of_stock(self) -> bool:
        """Check if item is out of stock."""
        return self.current_stock <= 0

    def get_stock_value(self) -> Decimal:
        """Calculate total stock value."""
        return self.current_stock * self.average_cost


@dataclass(kw_only=True)
class StockMovementResponseDTO:
    """Response DTO untuk stock movement."""

    id: UUID
    item_id: UUID
    sku: str
    movement_type: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    movement_date: date
    reference_document_type: str | None
    reference_document_number: str | None
    warehouse_code: str | None
    notes: str | None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "sku": self.sku,
            "movement_type": self.movement_type,
            "quantity": float(self.quantity),
            "unit_cost": float(self.unit_cost),
            "total_value": float(self.total_value),
            "movement_date": self.movement_date.isoformat(),
            "reference_document_type": self.reference_document_type,
            "reference_document_number": self.reference_document_number,
            "warehouse_code": self.warehouse_code,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
        }

    def is_inbound(self) -> bool:
        """Check if movement is inbound (purchase, return, etc.)."""
        return self.movement_type in ("PURCHASE", "RETURN", "ADJUSTMENT_IN")

    def is_outbound(self) -> bool:
        """Check if movement is outbound (sales, transfer out, etc.)."""
        return self.movement_type in ("SALES", "TRANSFER_OUT", "ADJUSTMENT_OUT")


@dataclass(kw_only=True)
class StockCardResponseDTO:
    """Response DTO untuk stock card entry."""

    date: date
    movement_type: str
    quantity_in: Decimal
    quantity_out: Decimal
    unit_cost: Decimal
    total_value: Decimal
    reference: str | None
    warehouse: str | None
    running_balance: Decimal = Decimal(0)
    running_value: Decimal = Decimal(0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.isoformat(),
            "movement_type": self.movement_type,
            "quantity_in": float(self.quantity_in),
            "quantity_out": float(self.quantity_out),
            "unit_cost": float(self.unit_cost),
            "total_value": float(self.total_value),
            "reference": self.reference,
            "warehouse": self.warehouse,
            "running_balance": float(self.running_balance),
            "running_value": float(self.running_value),
        }

    def net_movement(self) -> Decimal:
        """Calculate net movement (in - out)."""
        return self.quantity_in - self.quantity_out


@dataclass(kw_only=True)
class ValuationReportDTO:
    """Response DTO untuk inventory valuation report."""

    legal_entity_id: UUID
    as_of_date: date
    total_value: Decimal
    total_quantity: Decimal
    items: list[dict[str, Any]]
    valuation_method: str = "FIFO"
    currency: str = "IDR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "total_value": float(self.total_value),
            "total_quantity": float(self.total_quantity),
            "valuation_method": self.valuation_method,
            "currency": self.currency,
            "items": self.items,
        }

    def average_value_per_unit(self) -> Decimal:
        """Calculate average value per unit."""
        if self.total_quantity > 0:
            return self.total_value / self.total_quantity
        return Decimal(0)


@dataclass(kw_only=True)
class StockOpnameResponseDTO:
    """Response DTO untuk stock opname."""

    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    opname_date: date
    system_quantity: Decimal
    physical_quantity: Decimal
    discrepancy: Decimal
    discrepancy_value: Decimal
    notes: str | None
    counted_by: UUID
    counted_by_name: str | None = None
    counted_at: datetime
    approved_at: datetime | None = None
    status: str | None = None
    approved_by: UUID | None = None
    approved_by_name: str | None = None
    adjustment_journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.counted_at.tzinfo is None:
            object.__setattr__(self, "counted_at", self.counted_at.replace(tzinfo=UTC))
        if self.approved_at and self.approved_at.tzinfo is None:
            object.__setattr__(self, "approved_at", self.approved_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "item_name": self.item_name,
            "sku": self.sku,
            "opname_date": self.opname_date.isoformat(),
            "system_quantity": float(self.system_quantity),
            "physical_quantity": float(self.physical_quantity),
            "discrepancy": float(self.discrepancy),
            "discrepancy_value": float(self.discrepancy_value),
            "status": self.status,
            "notes": self.notes,
            "counted_by": str(self.counted_by),
            "counted_by_name": self.counted_by_name,
            "counted_at": self.counted_at.isoformat(),
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_by_name": self.approved_by_name,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "adjustment_journal_id": str(self.adjustment_journal_id)
            if self.adjustment_journal_id
            else None,
        }

    def needs_approval(self) -> bool:
        """Check if opname needs approval."""
        return abs(self.discrepancy) > Decimal(0)

    def is_overage(self) -> bool:
        """Check if opname has overage (physical > system)."""
        return self.physical_quantity > self.system_quantity

    def is_shortage(self) -> bool:
        """Check if opname has shortage (physical < system)."""
        return self.physical_quantity < self.system_quantity


@dataclass(kw_only=True)
class TransferResponseDTO:
    """Response DTO untuk inter-warehouse transfer."""

    id: UUID
    item_id: UUID
    item_name: str
    sku: str
    from_warehouse: str
    to_warehouse: str
    quantity: Decimal
    unit_cost: Decimal
    total_value: Decimal
    transfer_date: date
    notes: str | None
    requested_by: UUID
    requested_by_name: str | None = None
    requested_at: datetime
    completed_by: UUID | None = None
    completed_by_name: str | None = None
    completed_at: datetime | None = None
    status: str | None = None
    transfer_journal_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.requested_at.tzinfo is None:
            object.__setattr__(self, "requested_at", self.requested_at.replace(tzinfo=UTC))
        if self.completed_at and self.completed_at.tzinfo is None:
            object.__setattr__(self, "completed_at", self.completed_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "item_id": str(self.item_id),
            "item_name": self.item_name,
            "sku": self.sku,
            "from_warehouse": self.from_warehouse,
            "to_warehouse": self.to_warehouse,
            "quantity": float(self.quantity),
            "unit_cost": float(self.unit_cost),
            "total_value": float(self.total_value),
            "transfer_date": self.transfer_date.isoformat(),
            "status": self.status,
            "notes": self.notes,
            "requested_by": str(self.requested_by),
            "requested_by_name": self.requested_by_name,
            "requested_at": self.requested_at.isoformat(),
            "completed_by": str(self.completed_by) if self.completed_by else None,
            "completed_by_name": self.completed_by_name,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "transfer_journal_id": str(self.transfer_journal_id)
            if self.transfer_journal_id
            else None,
        }

    def is_completed(self) -> bool:
        """Check if transfer is completed."""
        return self.status == "COMPLETED"

    def is_pending(self) -> bool:
        """Check if transfer is pending."""
        return self.status in ("PENDING", "APPROVED")


@dataclass(kw_only=True)
class InventorySummaryDTO:
    """Response DTO untuk inventory summary."""

    legal_entity_id: UUID
    total_items: int
    active_items: int
    total_stock_quantity: Decimal
    total_stock_value: Decimal
    items_below_reorder: int
    items_out_of_stock: int
    as_of_date: date = field(default_factory=date.today)
    warehouses: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "legal_entity_id": str(self.legal_entity_id),
            "total_items": self.total_items,
            "active_items": self.active_items,
            "total_stock_quantity": float(self.total_stock_quantity),
            "total_stock_value": float(self.total_stock_value),
            "items_below_reorder": self.items_below_reorder,
            "items_out_of_stock": self.items_out_of_stock,
            "as_of_date": self.as_of_date.isoformat(),
            "warehouses": self.warehouses,
        }

    def stock_coverage_days(self, daily_consumption: Decimal = Decimal(0)) -> Decimal:
        """Calculate stock coverage in days."""
        if daily_consumption > 0:
            return self.total_stock_quantity / daily_consumption
        return Decimal(0)


# Add missing field import
from dataclasses import field

__all__ = [
    "InventorySummaryDTO",
    "ItemResponseDTO",
    "StockCardResponseDTO",
    "StockMovementResponseDTO",
    "StockOpnameResponseDTO",
    "TransferResponseDTO",
    "ValuationReportDTO",
]