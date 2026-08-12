#!/usr/bin/env python3
"""
Module: sales_order_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Sales Order (SO) entity.

Defines the Sales Order entity used to record customer orders for goods or services.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every SO change is recorded via immutable updates.
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


class SOStatus(Enum):
    """Sales Order status."""

    DRAFT = "draft"
    APPROVED = "approved"
    PARTIALLY_DELIVERED = "partial"
    FULLY_DELIVERED = "fully_delivered"
    INVOICED = "invoiced"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class SOType(Enum):
    """Sales Order type."""

    STANDARD = "standard"
    RUSH = "rush"
    BACKORDER = "backorder"
    CONSIGNMENT = "consignment"


# ============================================================================
# SO Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class SOItem:
    """
    Item within a Sales Order (immutable value object).

    Attributes:
        item_id: Unique identifier for the item.
        item_code: Item code.
        item_name: Item name.
        quantity: Ordered quantity.
        unit_price: Price per unit.
        discount_percentage: Discount percentage (0-100).
        tax_rate: Tax rate (e.g., 11 for PPN).
        delivered_quantity: Quantity already delivered.
        unit_of_measure: Unit of measure (e.g., PCS, KG).
    """

    item_id: UUID
    item_code: str
    item_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    delivered_quantity: Decimal = Decimal(0)
    unit_of_measure: str = "PCS"

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price}")
        if not (0 <= self.discount_percentage <= 100):
            raise ValueError(
                f"Discount percentage must be between 0 and 100: {self.discount_percentage}"
            )
        if not (0 <= self.tax_rate <= 100):
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")
        if self.delivered_quantity < 0:
            raise ValueError(f"Delivered quantity cannot be negative: {self.delivered_quantity}")
        if self.delivered_quantity > self.quantity:
            raise ValueError(
                f"Delivered quantity {self.delivered_quantity} exceeds ordered quantity {self.quantity}"
            )

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> Decimal:
        return self.subtotal * (self.discount_percentage / Decimal(100))

    @property
    def net_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        return self.net_amount * (self.tax_rate / Decimal(100))

    @property
    def total_amount(self) -> Decimal:
        return self.net_amount + self.tax_amount

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.delivered_quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "discount_percentage": str(self.discount_percentage),
            "tax_rate": str(self.tax_rate),
            "delivered_quantity": str(self.delivered_quantity),
            "remaining_quantity": str(self.remaining_quantity),
            "subtotal": str(self.subtotal),
            "net_amount": str(self.net_amount),
            "tax_amount": str(self.tax_amount),
            "total_amount": str(self.total_amount),
            "unit_of_measure": self.unit_of_measure,
        }


# ============================================================================
# Sales Order Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class SalesOrderEntity:
    """
    Sales Order entity (immutable).

    Business context:
    Represents a customer order for goods or services.

    Attributes:
        so_id: Unique identifier.
        so_number: Human-readable SO number.
        so_type: Type of SO (standard, rush, backorder, consignment).
        customer_id: Customer ID.
        customer_name: Customer name (denormalized).
        order_date: Date the order was created.
        requested_delivery_date: Customer's requested delivery date.
        status: Current SO status.
        items: List of SOItem.
        currency: Currency code (e.g., IDR, USD).
        shipping_address: Shipping address (optional).
        billing_address: Billing address (optional).
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    so_id: UUID
    so_number: str
    so_type: SOType
    customer_id: UUID
    customer_name: str
    order_date: datetime
    requested_delivery_date: datetime
    status: SOStatus
    items: list[SOItem] = field(default_factory=list)
    currency: str = "IDR"
    shipping_address: str | None = None
    billing_address: str | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate SO invariants."""
        if len(self.so_number.strip()) < 3:
            raise ValueError("SO number must be at least 3 characters")
        if self.requested_delivery_date <= self.order_date:
            raise ValueError("Requested delivery date must be after order date")
        if self.currency not in ("IDR", "USD", "EUR", "SGD"):
            raise ValueError(f"Unsupported currency: {self.currency}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.order_date.tzinfo is None or self.requested_delivery_date.tzinfo is None:
            raise ValueError("Dates must be timezone-aware")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        # Validate no duplicate item IDs
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("Duplicate item IDs found in SO items")

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    @property
    def total_amount(self) -> Decimal:
        """Total SO amount (sum of all items' total_amount)."""
        return sum(item.total_amount for item in self.items)

    @property
    def total_delivered_amount(self) -> Decimal:
        """Total value of goods already delivered (proportional)."""
        total = Decimal(0)
        for item in self.items:
            if item.quantity > 0:
                delivered_ratio = item.delivered_quantity / item.quantity
                total += item.total_amount * delivered_ratio
        return total

    def is_fully_delivered(self) -> bool:
        """Check if all items have been fully delivered."""
        return all(item.delivered_quantity >= item.quantity for item in self.items)

    def is_overdue(self, as_of: datetime | None = None) -> bool:
        """Check if SO is past the requested delivery date and not fully delivered."""
        if self.status in (
            SOStatus.FULLY_DELIVERED,
            SOStatus.INVOICED,
            SOStatus.CLOSED,
            SOStatus.CANCELLED,
        ):
            return False
        check_date = as_of or datetime.now(UTC)
        return check_date > self.requested_delivery_date

    def get_item(self, item_id: UUID) -> SOItem | None:
        """Get item by ID."""
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def add_item(self, item: SOItem, added_by: str) -> SalesOrderEntity:
        """Add a new item to the SO."""
        new_items = [*list(self.items), item]
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> SalesOrderEntity:
        """Remove an item from the SO."""
        new_items = [i for i in self.items if i.item_id != item_id]
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def update_item_quantity(
        self, item_id: UUID, new_quantity: Decimal, updated_by: str
    ) -> SalesOrderEntity:
        """Update quantity of an existing item."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                if new_quantity < item.delivered_quantity:
                    raise ValueError(
                        f"New quantity {new_quantity} cannot be less than already delivered {item.delivered_quantity}"
                    )
                new_item = SOItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=new_quantity,
                    unit_price=item.unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    delivered_quantity=item.delivered_quantity,
                    unit_of_measure=item.unit_of_measure,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_item_unit_price(
        self, item_id: UUID, new_unit_price: Decimal, updated_by: str
    ) -> SalesOrderEntity:
        """Update unit price of an existing item."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                new_item = SOItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_price=new_unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    delivered_quantity=item.delivered_quantity,
                    unit_of_measure=item.unit_of_measure,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_delivered_quantity(
        self, item_id: UUID, additional_delivered: Decimal, updated_by: str
    ) -> SalesOrderEntity:
        """Increase delivered quantity for an item (called when goods are delivered)."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                new_delivered = item.delivered_quantity + additional_delivered
                if new_delivered > item.quantity:
                    raise ValueError(
                        f"Delivered quantity {new_delivered} exceeds ordered quantity {item.quantity}"
                    )
                new_item = SOItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    delivered_quantity=new_delivered,
                    unit_of_measure=item.unit_of_measure,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def approve(self, approved_by: str) -> SalesOrderEntity:
        """Approve SO (DRAFT -> APPROVED)."""
        if self.status != SOStatus.DRAFT:
            raise ValueError(f"Cannot approve SO in status {self.status.value}")
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=SOStatus.APPROVED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=approved_by,
            version=self.version + 1,
        )

    def deliver(self) -> SalesOrderEntity:
        """Update SO status based on delivered quantities. Called after delivery note."""
        if self.is_fully_delivered():
            new_status = SOStatus.FULLY_DELIVERED
        else:
            new_status = SOStatus.PARTIALLY_DELIVERED
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=new_status,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def invoice(self, invoiced_by: str) -> SalesOrderEntity:
        """Mark SO as invoiced (FULLY_DELIVERED -> INVOICED)."""
        if self.status != SOStatus.FULLY_DELIVERED:
            raise ValueError(f"Cannot invoice SO in status {self.status.value}")
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=SOStatus.INVOICED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=invoiced_by,
            version=self.version + 1,
        )

    def close(self, closed_by: str) -> SalesOrderEntity:
        """Close SO (INVOICED -> CLOSED)."""
        if self.status != SOStatus.INVOICED:
            raise ValueError(f"Cannot close SO in status {self.status.value}")
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=SOStatus.CLOSED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=closed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> SalesOrderEntity:
        """Cancel SO (if not fully delivered or invoiced)."""
        if self.status in (SOStatus.FULLY_DELIVERED, SOStatus.INVOICED, SOStatus.CLOSED):
            raise ValueError(f"Cannot cancel SO in status {self.status.value}")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return SalesOrderEntity(
            so_id=self.so_id,
            so_number=self.so_number,
            so_type=self.so_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            order_date=self.order_date,
            requested_delivery_date=self.requested_delivery_date,
            status=SOStatus.CANCELLED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
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
        """Return dictionary representation."""
        return {
            "so_id": str(self.so_id),
            "so_number": self.so_number,
            "so_type": self.so_type.value,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "order_date": self.order_date.isoformat(),
            "requested_delivery_date": self.requested_delivery_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "total_delivered_amount": str(self.total_delivered_amount),
            "items": [item.to_dict() for item in self.items],
            "currency": self.currency,
            "is_overdue": self.is_overdue(),
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class SalesOrderEntityRepository:
    """Repository protocol for SalesOrderEntity."""

    async def get_by_id(self, so_id: UUID, legal_entity_id: UUID) -> SalesOrderEntity | None:
        raise NotImplementedError

    async def get_by_number(self, so_number: str, legal_entity_id: UUID) -> SalesOrderEntity | None:
        raise NotImplementedError

    async def get_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        status: SOStatus | None = None,
    ) -> list[SalesOrderEntity]:
        raise NotImplementedError

    async def get_overdue(
        self, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> list[SalesOrderEntity]:
        raise NotImplementedError

    async def save(self, so: SalesOrderEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, so_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "SOItem",
    "SOStatus",
    "SOType",
    "SalesOrderEntity",
    "SalesOrderEntityRepository",
]
