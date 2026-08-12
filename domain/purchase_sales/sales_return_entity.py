#!/usr/bin/env python3
"""
Module: sales_return_entity.py
Layer: 6 - Domain / Purchase & Sales
Responsibility: Sales return entity.

Defines the sales return entity to record goods returned from customers
due to defects, damage, or order mismatch.

Dependencies:
- Python standard library (uuid, datetime, decimal, logging, dataclasses)

Audit: Every sales return is recorded.
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


class SalesReturnStatus(Enum):
    """Sales return status."""

    DRAFT = "draft"
    APPROVED = "approved"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SalesReturnReason(Enum):
    """Reason for sales return."""

    DEFECTIVE = "defective"
    DAMAGED = "damaged"
    WRONG_ITEM = "wrong_item"
    EXCESS_QUANTITY = "excess"
    EXPIRED = "expired"
    CUSTOMER_CANCELLATION = "cancellation"
    QUALITY_ISSUE = "quality_issue"


# ============================================================================
# Sales Return Item (Value Object)
# ============================================================================


@dataclass(frozen=True)
class SalesReturnItem:
    """
    Item within a sales return (immutable value object).

    Attributes:
        item_id: Item ID.
        item_code: Item code.
        item_name: Item name.
        invoice_id: Reference to the sales invoice ID.
        invoice_item_id: Reference to the invoice item ID (optional).
        quantity: Quantity being returned.
        unit_price: Unit price from invoice.
        reason: Return reason.
        condition: Condition of returned goods.
        notes: Additional notes.
    """

    item_id: UUID
    item_code: str
    item_name: str
    invoice_id: UUID
    invoice_item_id: UUID | None
    quantity: Decimal
    unit_price: Decimal
    reason: SalesReturnReason
    condition: str = "RETURNED"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price}")
        if self.condition not in ("RETURNED", "DAMAGED", "EXPIRED"):
            raise ValueError(f"Invalid condition: {self.condition}")

    @property
    def total_amount(self) -> Decimal:
        """Total amount for this returned item."""
        return self.quantity * self.unit_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": str(self.item_id),
            "item_code": self.item_code,
            "item_name": self.item_name,
            "invoice_id": str(self.invoice_id),
            "invoice_item_id": str(self.invoice_item_id) if self.invoice_item_id else None,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price),
            "total_amount": str(self.total_amount),
            "reason": self.reason.value,
            "condition": self.condition,
            "notes": self.notes,
        }


# ============================================================================
# Sales Return Entity (Immutable)
# ============================================================================


@dataclass(frozen=True)
class SalesReturnEntity:
    """
    Sales return entity (immutable).

    Business context:
    Records goods returned from customers and adjusts the related accounts receivable.

    Attributes:
        return_id: Unique identifier.
        return_number: Human-readable return number.
        invoice_id: Reference to the sales invoice.
        invoice_number: Invoice number (denormalized).
        customer_id: Customer ID.
        customer_name: Customer name.
        return_date: Date of return.
        status: Return status.
        items: List of returned items.
        total_amount: Total amount of the return.
        credit_note_number: Credit note number issued to customer.
        approved_by: User who approved the return.
        approved_at: Approval timestamp.
        completed_by: User who completed the return.
        completed_at: Completion timestamp.
        notes: Additional notes.
        created_at: Creation timestamp.
        updated_at: Last update timestamp.
        created_by: User who created.
        version: Optimistic concurrency version.
    """

    return_id: UUID
    return_number: str
    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    return_date: datetime
    status: SalesReturnStatus
    items: list[SalesReturnItem] = field(default_factory=list)
    total_amount: Decimal = Decimal(0)
    credit_note_number: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    completed_by: str | None = None
    completed_at: datetime | None = None
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate return invariants."""
        if len(self.return_number.strip()) < 3:
            raise ValueError("Return number must be at least 3 characters")
        if self.return_date.tzinfo is None:
            raise ValueError("return_date must be timezone-aware")
        if self.total_amount < 0:
            raise ValueError(f"Total amount cannot be negative: {self.total_amount}")
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")
        if self.approved_at and self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        if self.completed_at and self.completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        # Validate total amount matches items sum
        items_total = sum(item.total_amount for item in self.items)
        if abs(self.total_amount - items_total) > Decimal("0.01"):
            raise ValueError(
                f"Total amount {self.total_amount} does not match items total {items_total}"
            )

    # ------------------------------------------------------------------------
    # Item management (return new instance)
    # ------------------------------------------------------------------------

    def add_item(self, item: SalesReturnItem, added_by: str) -> SalesReturnEntity:
        """Add an item to the return."""
        new_items = [*list(self.items), item]
        new_total = sum(i.total_amount for i in new_items)
        return SalesReturnEntity(
            return_id=self.return_id,
            return_number=self.return_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            return_date=self.return_date,
            status=self.status,
            items=new_items,
            total_amount=new_total,
            credit_note_number=self.credit_note_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_item(self, item_id: UUID, removed_by: str) -> SalesReturnEntity:
        """Remove an item from the return."""
        new_items = [i for i in self.items if i.item_id != item_id]
        new_total = sum(i.total_amount for i in new_items)
        return SalesReturnEntity(
            return_id=self.return_id,
            return_number=self.return_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            return_date=self.return_date,
            status=self.status,
            items=new_items,
            total_amount=new_total,
            credit_note_number=self.credit_note_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    # ------------------------------------------------------------------------
    # Status transitions
    # ------------------------------------------------------------------------

    def approve(self, approved_by: str) -> SalesReturnEntity:
        """Approve the return (DRAFT -> APPROVED)."""
        if self.status != SalesReturnStatus.DRAFT:
            raise ValueError(f"Cannot approve return in status {self.status.value}")
        return SalesReturnEntity(
            return_id=self.return_id,
            return_number=self.return_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            return_date=self.return_date,
            status=SalesReturnStatus.APPROVED,
            items=self.items,
            total_amount=self.total_amount,
            credit_note_number=self.credit_note_number,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            completed_by=self.completed_by,
            completed_at=self.completed_at,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=approved_by,
            version=self.version + 1,
        )

    def complete(
        self, completed_by: str, credit_note_number: str | None = None
    ) -> SalesReturnEntity:
        """Complete the return (APPROVED -> COMPLETED)."""
        if self.status != SalesReturnStatus.APPROVED:
            raise ValueError(f"Cannot complete return in status {self.status.value}")
        new_credit_note = credit_note_number or self.credit_note_number
        return SalesReturnEntity(
            return_id=self.return_id,
            return_number=self.return_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            return_date=self.return_date,
            status=SalesReturnStatus.COMPLETED,
            items=self.items,
            total_amount=self.total_amount,
            credit_note_number=new_credit_note,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=completed_by,
            completed_at=datetime.now(UTC),
            notes=self.notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=completed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> SalesReturnEntity:
        """Cancel the return."""
        if self.status in (SalesReturnStatus.COMPLETED, SalesReturnStatus.CANCELLED):
            raise ValueError(f"Cannot cancel return in status {self.status.value}")
        new_notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        return SalesReturnEntity(
            return_id=self.return_id,
            return_number=self.return_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            return_date=self.return_date,
            status=SalesReturnStatus.CANCELLED,
            items=self.items,
            total_amount=self.total_amount,
            credit_note_number=self.credit_note_number,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            completed_by=self.completed_by,
            completed_at=self.completed_at,
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
            "return_id": str(self.return_id),
            "return_number": self.return_number,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "return_date": self.return_date.isoformat(),
            "status": self.status.value,
            "total_amount": str(self.total_amount),
            "items": [item.to_dict() for item in self.items],
            "credit_note_number": self.credit_note_number,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "completed_by": self.completed_by,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


# ============================================================================
# Repository Protocol
# ============================================================================


class SalesReturnRepository:
    """Repository protocol for SalesReturnEntity."""

    async def get_by_id(self, return_id: UUID, legal_entity_id: UUID) -> SalesReturnEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, return_number: str, legal_entity_id: UUID
    ) -> SalesReturnEntity | None:
        raise NotImplementedError

    async def get_by_invoice(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> list[SalesReturnEntity]:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[SalesReturnEntity]:
        raise NotImplementedError

    async def save(self, return_entity: SalesReturnEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, return_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "SalesReturnEntity",
    "SalesReturnItem",
    "SalesReturnReason",
    "SalesReturnRepository",
    "SalesReturnStatus",
]
