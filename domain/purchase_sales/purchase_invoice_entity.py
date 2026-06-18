#!/usr/bin/env python3
"""
Module: purchase_invoice_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Purchase invoice entity.

Defines the purchase invoice entity received from suppliers for billing
of goods or services purchased.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every purchase invoice change is recorded.
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


class PurchaseInvoiceStatus(Enum):
    """Purchase invoice status."""

    DRAFT = "draft"
    RECEIVED = "received"
    VERIFIED = "verified"
    APPROVED = "approved"
    PAID = "paid"
    CANCELLED = "cancelled"
    DISPUTED = "disputed"


class PurchaseInvoiceType(Enum):
    """Purchase invoice type."""

    STANDARD = "standard"
    CREDIT_NOTE = "credit_note"
    DEBIT_NOTE = "debit_note"


# ============================================================================
# Purchase Invoice Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class PurchaseInvoiceItem:
    """
    Item within a purchase invoice (immutable value object).

    Attributes:
        item_id: Item ID.
        item_code: Item code.
        item_name: Item name.
        po_item_id: Reference to PO item ID (optional).
        quantity: Quantity billed.
        unit_price: Unit price.
        discount_percentage: Discount percentage (0-100).
        tax_rate: Tax rate (e.g., 11 for PPN).
        unit_of_measure: Unit of measure.
    """

    item_id: UUID
    item_code: str
    item_name: str
    po_item_id: UUID | None
    quantity: Decimal
    unit_price: Decimal
    discount_percentage: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "po_item_id": str(self.po_item_id) if self.po_item_id else None,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "discount_percentage": str(self.discount_percentage),
            "tax_rate": str(self.tax_rate),
            "subtotal": str(self.subtotal),
            "discount_amount": str(self.discount_amount),
            "net_amount": str(self.net_amount),
            "tax_amount": str(self.tax_amount),
            "total_amount": str(self.total_amount),
            "unit_of_measure": self.unit_of_measure,
        }


# ============================================================================
# Purchase Invoice Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class PurchaseInvoiceEntity:
    """
    Purchase invoice entity (immutable).

    Business context:
    Represents a bill from a supplier for goods or services purchased.

    Attributes:
        invoice_id: Unique identifier.
        invoice_number: Human-readable invoice number.
        invoice_type: Type (standard, credit note, debit note).
        po_id: Reference PO ID (optional).
        po_number: PO number (denormalized).
        supplier_id: Supplier ID.
        supplier_name: Supplier name.
        invoice_date: Invoice date.
        due_date: Payment due date.
        status: Invoice status.
        items: List of invoice items.
        currency: Currency code.
        tax_amount: Total tax amount (can be manually set or calculated).
        discount_amount: Total discount amount.
        shipping_cost: Shipping cost.
        other_costs: Other miscellaneous costs.
        total_amount: Grand total.
        paid_amount: Amount already paid.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    invoice_id: UUID
    invoice_number: str
    invoice_type: PurchaseInvoiceType
    po_id: UUID | None
    po_number: str | None
    supplier_id: UUID
    supplier_name: str
    invoice_date: datetime
    due_date: datetime
    status: PurchaseInvoiceStatus
    items: list[PurchaseInvoiceItem] = field(default_factory=list)
    currency: str = "IDR"
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    shipping_cost: Decimal = Decimal(0)
    other_costs: Decimal = Decimal(0)
    total_amount: Decimal = Decimal(0)
    paid_amount: Decimal = Decimal(0)
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate invoice invariants."""
        if len(self.invoice_number.strip()) < 3:
            raise ValueError("Invoice number must be at least 3 characters")
        if self.due_date <= self.invoice_date:
            raise ValueError("Due date must be after invoice date")
        if self.currency not in ("IDR", "USD", "EUR", "SGD"):
            raise ValueError(f"Unsupported currency: {self.currency}")
        if self.paid_amount < 0:
            raise ValueError(f"Paid amount cannot be negative: {self.paid_amount}")
        if self.paid_amount > self.total_amount:
            raise ValueError(
                f"Paid amount {self.paid_amount} exceeds total amount {self.total_amount}"
            )
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.invoice_date.tzinfo is None or self.due_date.tzinfo is None:
            raise ValueError("Dates must be timezone-aware")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ------------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------------

    @property
    def outstanding_amount(self) -> Decimal:
        """Remaining amount to be paid."""
        return self.total_amount - self.paid_amount

    @property
    def is_overdue(self) -> bool:
        """Check if invoice is past due date and not fully paid."""
        if self.status in (PurchaseInvoiceStatus.PAID, PurchaseInvoiceStatus.CANCELLED):
            return False
        return datetime.now(UTC) > self.due_date

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def _recalculate_total(self) -> Decimal:
        """Recalculate total from items plus shipping/other minus discount."""
        items_total = sum(item.total_amount for item in self.items)
        return items_total + self.shipping_cost + self.other_costs - self.discount_amount

    def add_item(self, item: PurchaseInvoiceItem, added_by: str) -> PurchaseInvoiceEntity:
        """Add an item to the invoice."""
        new_items = list(self.items) + [item]
        new_total = self._recalculate_total()
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=new_total,
            paid_amount=self.paid_amount,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> PurchaseInvoiceEntity:
        """Remove an item from the invoice."""
        new_items = [i for i in self.items if i.item_id != item_id]
        new_total = self._recalculate_total()
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=self.status,
            items=new_items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=new_total,
            paid_amount=self.paid_amount,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def receive(self, received_by: str) -> PurchaseInvoiceEntity:
        """Mark invoice as received from supplier (DRAFT -> RECEIVED)."""
        if self.status != PurchaseInvoiceStatus.DRAFT:
            raise ValueError(f"Cannot receive invoice in status {self.status.value}")
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=PurchaseInvoiceStatus.RECEIVED,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=self.paid_amount,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=received_by,
            version=self.version + 1,
        )

    def verify(self, verified_by: str) -> PurchaseInvoiceEntity:
        """Verify invoice (3-way match with PO and GRN)."""
        if self.status != PurchaseInvoiceStatus.RECEIVED:
            raise ValueError(f"Cannot verify invoice in status {self.status.value}")
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=PurchaseInvoiceStatus.VERIFIED,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=self.paid_amount,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=verified_by,
            version=self.version + 1,
        )

    def approve(self, approved_by: str) -> PurchaseInvoiceEntity:
        """Approve invoice for payment (VERIFIED -> APPROVED)."""
        if self.status != PurchaseInvoiceStatus.VERIFIED:
            raise ValueError(f"Cannot approve invoice in status {self.status.value}")
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=PurchaseInvoiceStatus.APPROVED,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=self.paid_amount,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=approved_by,
            version=self.version + 1,
        )

    def record_payment(
        self, amount: Decimal, payment_id: UUID, paid_by: str
    ) -> PurchaseInvoiceEntity:
        """Record a payment against this invoice."""
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        new_paid = self.paid_amount + amount
        if new_paid > self.total_amount:
            raise ValueError(
                f"Payment amount {amount} would exceed outstanding {self.outstanding_amount}"
            )
        new_status = PurchaseInvoiceStatus.PAID if new_paid >= self.total_amount else self.status
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=new_status,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=new_paid,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=paid_by,
            version=self.version + 1,
        )

    def dispute(self, disputed_by: str, reason: str) -> PurchaseInvoiceEntity:
        """Mark invoice as disputed."""
        if self.status in (PurchaseInvoiceStatus.PAID, PurchaseInvoiceStatus.CANCELLED):
            raise ValueError(f"Cannot dispute invoice in status {self.status.value}")
        new_notes = f"{self.notes}\nDisputed: {reason}" if self.notes else f"Disputed: {reason}"
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=PurchaseInvoiceStatus.DISPUTED,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=self.paid_amount,
            notes=new_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=disputed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> PurchaseInvoiceEntity:
        """Cancel the invoice."""
        if self.status == PurchaseInvoiceStatus.PAID:
            raise ValueError("Cannot cancel paid invoice")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return PurchaseInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            po_id=self.po_id,
            po_number=self.po_number,
            supplier_id=self.supplier_id,
            supplier_name=self.supplier_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            status=PurchaseInvoiceStatus.CANCELLED,
            items=self.items,
            currency=self.currency,
            tax_amount=self.tax_amount,
            discount_amount=self.discount_amount,
            shipping_cost=self.shipping_cost,
            other_costs=self.other_costs,
            total_amount=self.total_amount,
            paid_amount=self.paid_amount,
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
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "invoice_type": self.invoice_type.value,
            "po_id": str(self.po_id) if self.po_id else None,
            "po_number": self.po_number,
            "supplier_id": str(self.supplier_id),
            "supplier_name": self.supplier_name,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "paid_amount": str(self.paid_amount),
            "outstanding_amount": str(self.outstanding_amount),
            "is_overdue": self.is_overdue,
            "items": [item.to_dict() for item in self.items],
            "currency": self.currency,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class PurchaseInvoiceRepository:
    """Repository protocol for PurchaseInvoiceEntity."""

    async def get_by_id(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> PurchaseInvoiceEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, invoice_number: str, legal_entity_id: UUID
    ) -> PurchaseInvoiceEntity | None:
        raise NotImplementedError

    async def get_by_supplier(
        self,
        supplier_id: UUID,
        legal_entity_id: UUID,
        status: PurchaseInvoiceStatus | None = None,
    ) -> list[PurchaseInvoiceEntity]:
        raise NotImplementedError

    async def get_by_po(self, po_id: UUID, legal_entity_id: UUID) -> list[PurchaseInvoiceEntity]:
        raise NotImplementedError

    async def save(self, invoice: PurchaseInvoiceEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, invoice_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "PurchaseInvoiceEntity",
    "PurchaseInvoiceItem",
    "PurchaseInvoiceRepository",
    "PurchaseInvoiceStatus",
    "PurchaseInvoiceType",
]
