#!/usr/bin/env python3
"""
Module: purchase_order_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Purchase Order (PO) entity.

Defines the Purchase Order entity used to order goods or services from suppliers.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every PO change is recorded via immutable updates.
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


class POStatus(Enum):
    """Purchase Order status."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    PARTIALLY_RECEIVED = "partial"
    FULLY_RECEIVED = "fully_received"
    CANCELLED = "cancelled"
    CLOSED = "closed"


class POType(Enum):
    """Purchase Order type."""

    STANDARD = "standard"
    BLANKET = "blanket"
    CONTRACT = "contract"
    RUSH = "rush"


# ============================================================================
# PO Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class POItem:
    """
    Item within a Purchase Order (immutable value object).

    Attributes:
        item_id: Unique identifier for the item.
        item_code: Item code.
        item_name: Item name.
        quantity: Ordered quantity.
        unit_price: Price per unit.
        discount_percentage: Discount percentage (0-100).
        tax_rate: Tax rate (e.g., 11 for PPN).
        received_quantity: Quantity already received.
        unit_of_measure: Unit of measure (e.g., PCS, KG).
        expected_delivery_date: Expected delivery date from supplier.
    """

    item_id: UUID
    item_code: str
    item_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    received_quantity: Decimal = Decimal(0)
    unit_of_measure: str = "PCS"
    expected_delivery_date: datetime | None = None

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
        if self.received_quantity < 0:
            raise ValueError(f"Received quantity cannot be negative: {self.received_quantity}")
        if self.received_quantity > self.quantity:
            raise ValueError(
                f"Received quantity {self.received_quantity} exceeds ordered quantity {self.quantity}"
            )
        if self.expected_delivery_date and self.expected_delivery_date.tzinfo is None:
            raise ValueError("expected_delivery_date must be timezone-aware")

    @property
    def subtotal(self) -> Decimal:
        """Subtotal before discount."""
        return self.quantity * self.unit_price

    @property
    def discount_amount(self) -> Decimal:
        """Discount amount."""
        return self.subtotal * (self.discount_percentage / Decimal(100))

    @property
    def net_amount(self) -> Decimal:
        """Amount after discount."""
        return self.subtotal - self.discount_amount

    @property
    def tax_amount(self) -> Decimal:
        """Tax amount (PPN)."""
        return self.net_amount * (self.tax_rate / Decimal(100))

    @property
    def total_amount(self) -> Decimal:
        """Total amount (after discount + tax)."""
        return self.net_amount + self.tax_amount

    @property
    def remaining_quantity(self) -> Decimal:
        """Quantity not yet received."""
        return self.quantity - self.received_quantity

    def to_dict(self) -> dict[str, Any]:
        """Return dictionary representation."""
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "discount_percentage": str(self.discount_percentage),
            "tax_rate": str(self.tax_rate),
            "received_quantity": str(self.received_quantity),
            "remaining_quantity": str(self.remaining_quantity),
            "subtotal": str(self.subtotal),
            "net_amount": str(self.net_amount),
            "tax_amount": str(self.tax_amount),
            "total_amount": str(self.total_amount),
            "unit_of_measure": self.unit_of_measure,
            "expected_delivery_date": self.expected_delivery_date.isoformat()
            if self.expected_delivery_date
            else None,
        }


# ============================================================================
# Purchase Order Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class PurchaseOrderEntity:
    """
    Purchase Order entity (immutable).

    Business context:
    Represents a purchase order to a supplier for goods or services.

    Attributes:
        po_id: Unique identifier.
        po_number: Human-readable PO number.
        po_type: Type of PO (standard, blanket, contract, rush).
        supplier_id: Supplier ID.
        supplier_name: Supplier name (denormalized).
        order_date: Date the PO was created.
        expected_delivery_date: Expected delivery date from supplier.
        status: Current PO status.
        items: List of POItem.
        currency: Currency code (e.g., IDR, USD).
        shipping_address: Shipping address (optional).
        billing_address: Billing address (optional).
        terms: Payment and delivery terms.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    po_id: UUID
    po_number: str
    po_type: POType
    supplier_id: UUID
    supplier_name: str
    order_date: datetime
    expected_delivery_date: datetime
    status: POStatus
    items: list[POItem] = field(default_factory=list)
    currency: str = "IDR"
    shipping_address: str | None = None
    billing_address: str | None = None
    terms: str | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate PO invariants."""
        if len(self.po_number.strip()) < 3:
            raise ValueError("PO number must be at least 3 characters")
        if self.expected_delivery_date <= self.order_date:
            raise ValueError("Expected delivery date must be after order date")
        if self.currency not in ("IDR", "USD", "EUR", "SGD"):
            raise ValueError(f"Unsupported currency: {self.currency}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.order_date.tzinfo is None or self.expected_delivery_date.tzinfo is None:
            raise ValueError("Dates must be timezone-aware")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        # Validate no duplicate item IDs
        item_ids = {item.item_id for item in self.items}
        if len(item_ids) != len(self.items):
            raise ValueError("Duplicate item IDs found in PO items")

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    @property
    def total_amount(self) -> Decimal:
        """Total PO amount (sum of all items' total_amount)."""
        return sum(item.total_amount for item in self.items)

    @property
    def total_received_amount(self) -> Decimal:
        """Total value of goods already received (proportional)."""
        total = Decimal(0)
        for item in self.items:
            if item.quantity > 0:
                received_ratio = item.received_quantity / item.quantity
                total += item.total_amount * received_ratio
        return total

    def is_fully_received(self) -> bool:
        """Check if all items have been fully received."""
        return all(item.received_quantity >= item.quantity for item in self.items)

    def is_overdue(self, as_of: datetime | None = None) -> bool:
        """Check if PO is past the expected delivery date and not fully received."""
        if self.status in (POStatus.FULLY_RECEIVED, POStatus.CLOSED, POStatus.CANCELLED):
            return False
        check_date = as_of or datetime.now(UTC)
        return check_date > self.expected_delivery_date

    def get_item(self, item_id: UUID) -> POItem | None:
        """Get item by ID."""
        for item in self.items:
            if item.item_id == item_id:
                return item
        return None

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def add_item(self, item: POItem, added_by: str) -> PurchaseOrderEntity:
        """Add a new item to the PO."""
        new_items = list(self.items) + [item]
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> PurchaseOrderEntity:
        """Remove an item from the PO."""
        new_items = [i for i in self.items if i.item_id != item_id]
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def update_item_quantity(
        self, item_id: UUID, new_quantity: Decimal, updated_by: str
    ) -> PurchaseOrderEntity:
        """Update quantity of an existing item."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                if new_quantity < item.received_quantity:
                    raise ValueError(
                        f"New quantity {new_quantity} cannot be less than already received {item.received_quantity}"
                    )
                new_item = POItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=new_quantity,
                    unit_price=item.unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    received_quantity=item.received_quantity,
                    unit_of_measure=item.unit_of_measure,
                    expected_delivery_date=item.expected_delivery_date,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_item_unit_price(
        self, item_id: UUID, new_unit_price: Decimal, updated_by: str
    ) -> PurchaseOrderEntity:
        """Update unit price of an existing item."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                new_item = POItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_price=new_unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    received_quantity=item.received_quantity,
                    unit_of_measure=item.unit_of_measure,
                    expected_delivery_date=item.expected_delivery_date,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    def update_received_quantity(
        self, item_id: UUID, additional_received: Decimal, updated_by: str
    ) -> PurchaseOrderEntity:
        """Increase received quantity for an item (called when goods are received)."""
        new_items = []
        for item in self.items:
            if item.item_id == item_id:
                new_received = item.received_quantity + additional_received
                if new_received > item.quantity:
                    raise ValueError(
                        f"Received quantity {new_received} exceeds ordered quantity {item.quantity}"
                    )
                new_item = POItem(
                    item_id=item.item_id,
                    item_code=item.item_code,
                    item_name=item.item_name,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount_percentage=item.discount_percentage,
                    tax_rate=item.tax_rate,
                    received_quantity=new_received,
                    unit_of_measure=item.unit_of_measure,
                    expected_delivery_date=item.expected_delivery_date,
                )
                new_items.append(new_item)
            else:
                new_items.append(item)
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def submit(self, submitted_by: str) -> PurchaseOrderEntity:
        """Submit PO to supplier (DRAFT -> SUBMITTED)."""
        if self.status != POStatus.DRAFT:
            raise ValueError(f"Cannot submit PO in status {self.status.value}")
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=POStatus.SUBMITTED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=submitted_by,
            version=self.version + 1,
        )

    def approve(self, approved_by: str) -> PurchaseOrderEntity:
        """Approve PO (SUBMITTED -> APPROVED)."""
        if self.status != POStatus.SUBMITTED:
            raise ValueError(f"Cannot approve PO in status {self.status.value}")
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=POStatus.APPROVED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=approved_by,
            version=self.version + 1,
        )

    def receive(self) -> PurchaseOrderEntity:
        """Update PO status based on received quantities. Called after GRN."""
        if self.is_fully_received():
            new_status = POStatus.FULLY_RECEIVED
        else:
            new_status = POStatus.PARTIALLY_RECEIVED
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=new_status,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def close(self, closed_by: str) -> PurchaseOrderEntity:
        """Close PO (FULLY_RECEIVED -> CLOSED)."""
        if self.status != POStatus.FULLY_RECEIVED:
            raise ValueError(f"Cannot close PO in status {self.status.value}")
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=POStatus.CLOSED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=closed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> PurchaseOrderEntity:
        """Cancel PO (if not fully received or closed)."""
        if self.status in (POStatus.FULLY_RECEIVED, POStatus.CLOSED):
            raise ValueError(f"Cannot cancel PO in status {self.status.value}")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return PurchaseOrderEntity(
            po_id=self.po_id,
            po_number=self.po_number,
            po_type=self.po_type,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            order_date=self.order_date,
            expected_delivery_date=self.expected_delivery_date,
            status=POStatus.CANCELLED,
            items=self.items,
            currency=self.currency,
            shipping_address=self.shipping_address,
            billing_address=self.billing_address,
            terms=self.terms,
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
            "po_id": str(self.po_id),
            "po_number": self.po_number,
            "po_type": self.po_type.value,
            "supplier_id": str(self.supplier_id),
            "supplier_name": self.supplier_name,
            "order_date": self.order_date.isoformat(),
            "expected_delivery_date": self.expected_delivery_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "total_received_amount": str(self.total_received_amount),
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


class PurchaseOrderEntityRepository:
    """Repository protocol for PurchaseOrderEntity."""

    async def get_by_id(self, po_id: UUID, legal_entity_id: UUID) -> PurchaseOrderEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, po_number: str, legal_entity_id: UUID
    ) -> PurchaseOrderEntity | None:
        raise NotImplementedError

    async def get_by_supplier(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        status: POStatus | None = None,
    ) -> list[PurchaseOrderEntity]:
        raise NotImplementedError

    async def get_overdue(
        self, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> list[PurchaseOrderEntity]:
        raise NotImplementedError

    async def save(self, po: PurchaseOrderEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, po_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Aliases for backward compatibility / test compatibility
# ============================================================================

# POLine is an alias for POItem, used by some tests (e.g., test_purchase_order_aggregate)
POLine = POItem


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "POItem",
    "POLine",
    "POStatus",
    "POType",
    "PurchaseOrderEntity",
    "PurchaseOrderEntityRepository",
]
