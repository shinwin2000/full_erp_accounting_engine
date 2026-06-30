#!/usr/bin/env python3
"""
Module: goods_receipt_note_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Goods Receipt Note (GRN) entity.

Defines the Goods Receipt Note entity that records receipt of goods
from a supplier against a Purchase Order.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every goods receipt is recorded.
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


class GRNStatus(Enum):
    """Goods Receipt Note status."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


# ============================================================================
# GRN Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class GRNItem:
    """
    Item within a Goods Receipt Note (immutable value object).

    Attributes:
        item_id: Item ID.
        item_code: Item code.
        item_name: Item name.
        po_item_id: Reference to the PO item ID.
        quantity: Quantity received.
        unit_price: Unit price from PO.
        unit_of_measure: Unit of measure.
        batch_number: Optional batch/lot number.
        expiry_date: Optional expiry date.
        condition: Condition of goods (GOOD, DAMAGED, EXPIRED).
    """

    item_id: UUID
    item_code: str
    item_name: str
    po_item_id: UUID
    quantity: Decimal
    unit_price: Decimal
    unit_of_measure: str = "PCS"
    batch_number: str | None = None
    expiry_date: datetime | None = None
    condition: str = "GOOD"

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price}")
        if self.condition not in ("GOOD", "DAMAGED", "EXPIRED"):
            raise ValueError(f"Invalid condition: {self.condition}")
        if self.expiry_date and self.expiry_date.tzinfo is None:
            raise ValueError("expiry_date must be timezone-aware")

    @property
    def total_amount(self) -> Decimal:
        """Total amount for this item."""
        return self.quantity * self.unit_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "po_item_id": str(self.po_item_id),
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "total_amount": str(self.total_amount),
            "unit_of_measure": self.unit_of_measure,
            "batch_number": self.batch_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "condition": self.condition,
        }


# ============================================================================
# Goods Receipt Note Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class GoodsReceiptNoteEntity:
    """
    Goods Receipt Note entity (immutable).

    Business context:
    Records receipt of goods from a supplier, including quantity,
    condition, and batch numbers.

    Attributes:
        grn_id: Unique identifier.
        grn_number: Human-readable GRN number.
        po_id: Reference Purchase Order ID.
        po_number: PO number (denormalized).
        supplier_id: Supplier ID.
        supplier_name: Supplier name.
        receipt_date: Date of receipt.
        status: GRN status.
        items: List of GRNItem.
        warehouse_id: Warehouse where goods were received.
        warehouse_name: Warehouse name (denormalized).
        received_by: User who received the goods.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    grn_id: UUID
    grn_number: str
    po_id: UUID
    po_number: str
    supplier_id: UUID
    supplier_name: str
    receipt_date: datetime
    status: GRNStatus
    items: list[GRNItem] = field(default_factory=list)
    warehouse_id: UUID | None = None
    warehouse_name: str | None = None
    received_by: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate GRN invariants."""
        if len(self.grn_number.strip()) < 3:
            raise ValueError("GRN number must be at least 3 characters")
        if self.receipt_date.tzinfo is None:
            raise ValueError("receipt_date must be timezone-aware")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        # Check for duplicate item IDs
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("Duplicate item IDs found in GRN items")

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    @property
    def total_amount(self) -> Decimal:
        """Total value of all items."""
        return sum(item.total_amount for item in self.items)

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def add_item(self, item: GRNItem, added_by: str) -> GoodsReceiptNoteEntity:
        """Add an item to the GRN."""
        new_items = list(self.items) + [item]
        return GoodsReceiptNoteEntity(
            grn_id=self.grn_id,
            grn_number=self.grn_number,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            receipt_date=self.receipt_date,
            status=self.status,
            items=new_items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            received_by=self.received_by,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> GoodsReceiptNoteEntity:
        """Remove an item from the GRN."""
        new_items = [i for i in self.items if i.item_id != item_id]
        return GoodsReceiptNoteEntity(
            grn_id=self.grn_id,
            grn_number=self.grn_number,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            receipt_date=self.receipt_date,
            status=self.status,
            items=new_items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            received_by=self.received_by,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def confirm(self, confirmed_by: str) -> GoodsReceiptNoteEntity:
        """Confirm the GRN (DRAFT -> CONFIRMED)."""
        if self.status != GRNStatus.DRAFT:
            raise ValueError(f"Cannot confirm GRN in status {self.status.value}")
        return GoodsReceiptNoteEntity(
            grn_id=self.grn_id,
            grn_number=self.grn_number,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            receipt_date=self.receipt_date,
            status=GRNStatus.CONFIRMED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            received_by=confirmed_by,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=confirmed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> GoodsReceiptNoteEntity:
        """Cancel the GRN."""
        if self.status == GRNStatus.CANCELLED:
            raise ValueError("GRN already cancelled")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return GoodsReceiptNoteEntity(
            grn_id=self.grn_id,
            grn_number=self.grn_number,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            receipt_date=self.receipt_date,
            status=GRNStatus.CANCELLED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            received_by=self.received_by,
            notes=new_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "grn_id": str(self.grn_id),
            "grn_number": self.grn_number,
            "po_id": str(self.po_id),
            "po_number": self.po_number,
            "supplier_id": str(self.supplier_id),
            "supplier_name": self.supplier_name,
            "receipt_date": self.receipt_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "items": [item.to_dict() for item in self.items],
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "warehouse_name": self.warehouse_name,
            "received_by": self.received_by,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class GoodsReceiptNoteRepository:
    """Repository protocol for GoodsReceiptNoteEntity."""

    async def get_by_id(self, grn_id: UUID, legal_entity_id: UUID) -> GoodsReceiptNoteEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, grn_number: str, legal_entity_id: UUID
    ) -> GoodsReceiptNoteEntity | None:
        raise NotImplementedError

    async def get_by_po(self, po_id: UUID, legal_entity_id: UUID) -> list[GoodsReceiptNoteEntity]:
        raise NotImplementedError

    async def save(self, grn: GoodsReceiptNoteEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, grn_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# ALIAS FOR BACKWARD COMPATIBILITY
# ============================================================================

# Alias for import compatibility (e.g., "GoodsReceiptNote" used in tests)
GoodsReceiptNote = GoodsReceiptNoteEntity


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "GRNItem",
    "GRNStatus",
    "GoodsReceiptNoteEntity",
    "GoodsReceiptNoteRepository",
    "GoodsReceiptNote",  
]