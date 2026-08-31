#!/usr/bin/env python3
"""
Module: sales_delivery_note_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Sales delivery note entity (surat jalan).

Defines the Sales Delivery Note entity that records shipment of goods
to customers against a Sales Order.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every delivery is recorded.
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


class DeliveryStatus(Enum):
    """Delivery note status."""

    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


# ============================================================================
# Delivery Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class DeliveryItem:
    """
    Item within a delivery note (immutable value object).

    Attributes:
        item_id: Item ID.
        item_code: Item code.
        item_name: Item name.
        so_item_id: Reference to the SO item ID.
        quantity: Quantity being delivered.
        unit_price: Unit price from SO.
        unit_of_measure: Unit of measure.
        batch_number: Optional batch/lot number.
        expiry_date: Optional expiry date.
    """

    item_id: UUID
    item_code: str
    item_name: str
    so_item_id: UUID
    quantity: Decimal
    unit_price: Decimal
    unit_of_measure: str = "PCS"
    batch_number: str | None = None
    expiry_date: datetime | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price}")
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
            "so_item_id": str(self.so_item_id),
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "total_amount": str(self.total_amount),
            "unit_of_measure": self.unit_of_measure,
            "batch_number": self.batch_number,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
        }


# ============================================================================
# Sales Delivery Note Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class SalesDeliveryNoteEntity:
    """
    Sales Delivery Note entity (immutable).

    Business context:
    Records shipment of goods to a customer, including quantity,
    batch numbers, and shipping information.

    Attributes:
        delivery_id: Unique identifier.
        delivery_number: Human-readable delivery number.
        so_id: Reference Sales Order ID.
        so_number: SO number (denormalized).
        customer_id: Customer ID.
        customer_name: Customer name.
        delivery_date: Date of delivery/shipment.
        status: Delivery status.
        items: List of delivery items.
        warehouse_id: Warehouse from which goods were shipped.
        warehouse_name: Warehouse name (denormalized).
        shipped_by: User who shipped the goods.
        received_by: Person who received the goods (customer side).
        received_at: Timestamp of receipt.
        tracking_number: Courier tracking number.
        courier_name: Name of courier service.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    delivery_id: UUID
    delivery_number: str
    so_id: UUID
    so_number: str
    customer_id: UUID
    customer_name: str
    delivery_date: datetime
    status: DeliveryStatus
    items: list[DeliveryItem] = field(default_factory=list)
    warehouse_id: UUID | None = None
    warehouse_name: str | None = None
    shipped_by: str = ""
    received_by: str | None = None
    received_at: datetime | None = None
    tracking_number: str | None = None
    courier_name: str | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate delivery note invariants."""
        if len(self.delivery_number.strip()) < 3:
            raise ValueError("Delivery number must be at least 3 characters")
        if self.delivery_date.tzinfo is None:
            raise ValueError("delivery_date must be timezone-aware")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.received_at and self.received_at.tzinfo is None:
            raise ValueError("received_at must be timezone-aware")
        # Check for duplicate item IDs
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("Duplicate item IDs found in delivery items")

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    @property
    def total_amount(self) -> Decimal:
        """Total value of all items."""
        return sum((item.total_amount for item in self.items), Decimal(0))

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def add_item(self, item: DeliveryItem, added_by: str) -> SalesDeliveryNoteEntity:
        """Add an item to the delivery note."""
        new_items = [*list(self.items), item]
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=self.status,
            items=new_items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=self.shipped_by,
            received_by=self.received_by,
            received_at=self.received_at,
            tracking_number=self.tracking_number,
            courier_name=self.courier_name,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> SalesDeliveryNoteEntity:
        """Remove an item from the delivery note."""
        new_items = [i for i in self.items if i.item_id != item_id]
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=self.status,
            items=new_items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=self.shipped_by,
            received_by=self.received_by,
            received_at=self.received_at,
            tracking_number=self.tracking_number,
            courier_name=self.courier_name,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def confirm(self, confirmed_by: str) -> SalesDeliveryNoteEntity:
        """Confirm the delivery note (DRAFT -> CONFIRMED)."""
        if self.status != DeliveryStatus.DRAFT:
            raise ValueError(f"Cannot confirm delivery note in status {self.status.value}")
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=DeliveryStatus.CONFIRMED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=confirmed_by,
            received_by=self.received_by,
            received_at=self.received_at,
            tracking_number=self.tracking_number,
            courier_name=self.courier_name,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=confirmed_by,
            version=self.version + 1,
        )

    def ship(
        self,
        shipped_by: str,
        tracking_number: str | None = None,
        courier_name: str | None = None,
    ) -> SalesDeliveryNoteEntity:
        """Mark delivery as shipped (CONFIRMED -> SHIPPED)."""
        if self.status != DeliveryStatus.CONFIRMED:
            raise ValueError(f"Cannot ship delivery note in status {self.status.value}")
        new_tracking = tracking_number or self.tracking_number
        new_courier = courier_name or self.courier_name
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=DeliveryStatus.SHIPPED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=shipped_by,
            received_by=self.received_by,
            received_at=self.received_at,
            tracking_number=new_tracking,
            courier_name=new_courier,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=shipped_by,
            version=self.version + 1,
        )

    def deliver(self, received_by: str) -> SalesDeliveryNoteEntity:
        """Mark delivery as received by customer (SHIPPED -> DELIVERED)."""
        if self.status != DeliveryStatus.SHIPPED:
            raise ValueError(f"Cannot mark as delivered in status {self.status.value}")
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=DeliveryStatus.DELIVERED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=self.shipped_by,
            received_by=received_by,
            received_at=datetime.now(UTC),
            tracking_number=self.tracking_number,
            courier_name=self.courier_name,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=received_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> SalesDeliveryNoteEntity:
        """Cancel the delivery note."""
        if self.status in (DeliveryStatus.DELIVERED, DeliveryStatus.CANCELLED):
            raise ValueError(f"Cannot cancel delivery note in status {self.status.value}")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return SalesDeliveryNoteEntity(
            delivery_id=self.delivery_id,
            delivery_number=self.delivery_number,
            so_id=self.so_id,
            so_number=self.so_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            delivery_date=self.delivery_date,
            status=DeliveryStatus.CANCELLED,
            items=self.items,
            warehouse_id=self.warehouse_id,
            warehouse_name=self.warehouse_name,
            shipped_by=self.shipped_by,
            received_by=self.received_by,
            received_at=self.received_at,
            tracking_number=self.tracking_number,
            courier_name=self.courier_name,
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
            "delivery_id": str(self.delivery_id),
            "delivery_number": self.delivery_number,
            "so_id": str(self.so_id),
            "so_number": self.so_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "delivery_date": self.delivery_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "items": [item.to_dict() for item in self.items],
            "warehouse_id": str(self.warehouse_id) if self.warehouse_id else None,
            "warehouse_name": self.warehouse_name,
            "shipped_by": self.shipped_by,
            "received_by": self.received_by,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "tracking_number": self.tracking_number,
            "courier_name": self.courier_name,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class SalesDeliveryNoteRepository:
    """Repository protocol for SalesDeliveryNoteEntity."""

    async def get_by_id(
        self, delivery_id: UUID, legal_entity_id: UUID
    ) -> SalesDeliveryNoteEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, delivery_number: str, legal_entity_id: UUID
    ) -> SalesDeliveryNoteEntity | None:
        raise NotImplementedError

    async def get_by_so(self, so_id: UUID, legal_entity_id: UUID) -> list[SalesDeliveryNoteEntity]:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[SalesDeliveryNoteEntity]:
        raise NotImplementedError

    async def save(self, delivery: SalesDeliveryNoteEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, delivery_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DeliveryItem",
    "DeliveryStatus",
    "SalesDeliveryNoteEntity",
    "SalesDeliveryNoteRepository",
]
