#!/usr/bin/env python3
"""
Module: invoice_entity.py
Layer: 6 - Domain / Subledger AP
Responsibility: Entitas faktur dari pemasok.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.shared_value_objects.money_vo import Money

logger = logging.getLogger(__name__)


class APInvoiceStatus(Enum):
    DRAFT = "draft"
    RECEIVED = "received"
    VERIFIED = "verified"
    PARTIALLY_PAID = "partial"
    FULLY_PAID = "paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> APInvoiceStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class APInvoiceType(Enum):
    STANDARD = "standard"
    CREDIT = "credit"
    DEBIT = "debit"
    PREPAYMENT = "prepayment"

    @classmethod
    def from_string(cls, value: str) -> APInvoiceType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.STANDARD


@dataclass
class APInvoiceLine:
    id: UUID
    description: str
    quantity: Decimal
    unit_price: Money
    tax_rate: Decimal
    discount_percent: Decimal
    account_code: str
    total_amount: Money
    purchase_order_line_id: UUID | None = None
    goods_receipt_line_id: UUID | None = None
    tax_amount: Decimal = Decimal(0)
    discount_amount: Decimal = Decimal(0)
    currency: str = "IDR"

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError(f"Quantity must be positive: {self.quantity}")
        if self.unit_price.amount < 0:
            raise ValueError(f"Unit price cannot be negative: {self.unit_price.amount}")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError(f"Tax rate must be between 0 and 100: {self.tax_rate}")
        if self.discount_percent < 0 or self.discount_percent > 100:
            raise ValueError(f"Discount percent must be between 0 and 100: {self.discount_percent}")
        if len(self.account_code) < 3:
            raise ValueError(f"Account code must be at least 3 characters: {self.account_code}")
        if self.unit_price.currency != self.currency:
            raise ValueError(f"Currency mismatch: {self.unit_price.currency} vs {self.currency}")

    @property
    def subtotal(self) -> Decimal:
        return self.quantity * self.unit_price.amount

    @property
    def discount_amount_calc(self) -> Decimal:
        return self.subtotal * (self.discount_percent / Decimal(100))

    @property
    def taxable_amount(self) -> Decimal:
        return self.subtotal - self.discount_amount_calc

    @property
    def tax_amount_calc(self) -> Decimal:
        return self.taxable_amount * (self.tax_rate / Decimal(100))

    @property
    def line_total(self) -> Decimal:
        return self.taxable_amount + self.tax_amount_calc

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "description": self.description,
            "quantity": str(self.quantity),
            "unit_price": str(self.unit_price.amount),
            "currency": self.unit_price.currency,
            "tax_rate": str(self.tax_rate),
            "discount_percent": str(self.discount_percent),
            "account_code": self.account_code,
            "total_amount": str(self.total_amount.amount),
            "purchase_order_line_id": str(self.purchase_order_line_id)
            if self.purchase_order_line_id
            else None,
            "goods_receipt_line_id": str(self.goods_receipt_line_id)
            if self.goods_receipt_line_id
            else None,
            "subtotal": str(self.subtotal),
            "tax_amount": str(self.tax_amount),
            "discount_amount": str(self.discount_amount),
            "line_total": str(self.line_total),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APInvoiceLine:
        return cls(
            id=UUID(data["id"]),
            description=data["description"],
            quantity=Decimal(data["quantity"]),
            unit_price=Money(Decimal(data["unit_price"]), data.get("currency", "IDR")),
            tax_rate=Decimal(data["tax_rate"]),
            discount_percent=Decimal(data["discount_percent"]),
            account_code=data["account_code"],
            total_amount=Money(Decimal(data["total_amount"]), data.get("currency", "IDR")),
            purchase_order_line_id=UUID(data["purchase_order_line_id"])
            if data.get("purchase_order_line_id")
            else None,
            goods_receipt_line_id=UUID(data["goods_receipt_line_id"])
            if data.get("goods_receipt_line_id")
            else None,
            tax_amount=Decimal(data.get("tax_amount", "0")),
            discount_amount=Decimal(data.get("discount_amount", "0")),
            currency=data.get("currency", "IDR"),
        )


@dataclass
class APInvoiceEntity:
    invoice_id: UUID
    invoice_number: str
    invoice_type: APInvoiceType
    vendor_id: UUID
    vendor_name: str
    invoice_date: datetime
    due_date: datetime
    amount: Decimal
    currency: str
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: APInvoiceStatus
    description: str
    purchase_order_id: UUID | None = None
    goods_receipt_id: UUID | None = None
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    discount_amount: Decimal = Decimal(0)
    withholding_tax_amount: Decimal = Decimal(0)
    lines: list[APInvoiceLine] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Invoice amount must be positive: {self.amount}")
        if self.due_date <= self.invoice_date:
            raise ValueError("Due date must be after invoice date")
        if self.paid_amount < 0:
            raise ValueError(f"Paid amount cannot be negative: {self.paid_amount}")
        if self.outstanding_amount < 0:
            raise ValueError(f"Outstanding amount cannot be negative: {self.outstanding_amount}")
        if abs(self.paid_amount + self.outstanding_amount - self.amount) > Decimal("0.01"):
            raise ValueError(
                f"Amount mismatch: {self.amount} != {self.paid_amount} + {self.outstanding_amount}"
            )
        if self.invoice_date.tzinfo is None:
            self.invoice_date = self.invoice_date.replace(tzinfo=UTC)
        if self.due_date.tzinfo is None:
            self.due_date = self.due_date.replace(tzinfo=UTC)
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=UTC)
        if self.updated_at.tzinfo is None:
            self.updated_at = self.updated_at.replace(tzinfo=UTC)
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")

    def _record_audit(self, action: str, user_id: str, details: dict | None = None) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "user_id": user_id,
                "details": details or {},
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def is_overdue(self, as_of: datetime | None = None) -> bool:
        if self.status in (APInvoiceStatus.FULLY_PAID, APInvoiceStatus.CANCELLED):
            return False
        as_of = as_of or datetime.now(UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        return as_of > self.due_date

    def days_overdue(self, as_of: datetime | None = None) -> int:
        if not self.is_overdue(as_of):
            return 0
        as_of = as_of or datetime.now(UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        return (as_of - self.due_date).days

    def add_line(self, line: APInvoiceLine, added_by: str) -> APInvoiceEntity:
        new_lines = self.lines + [line]
        # Recalculate totals from lines
        new_amount = sum(l.line_total for l in new_lines)
        self._record_audit("line_added", added_by, {"line_id": str(line.id)})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=new_amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=new_amount - self.paid_amount,
            status=self.status,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=new_lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=added_by,
            version=self.version + 1,
        )

    def remove_line(self, line_id: UUID, removed_by: str) -> APInvoiceEntity:
        line_to_remove = next((l for l in self.lines if l.id == line_id), None)
        if not line_to_remove:
            raise ValueError(f"Line {line_id} not found")
        new_lines = [l for l in self.lines if l.id != line_id]
        new_amount = sum(l.line_total for l in new_lines)
        self._record_audit("line_removed", removed_by, {"line_id": str(line_id)})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=new_amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=new_amount - self.paid_amount,
            status=self.status,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=new_lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=removed_by,
            version=self.version + 1,
        )

    def record_payment(self, amount: Decimal, payment_id: UUID) -> APInvoiceEntity:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        new_paid = self.paid_amount + amount
        new_outstanding = self.amount - new_paid
        if new_outstanding < -Decimal("0.01"):
            raise ValueError(
                f"Payment amount {amount} exceeds outstanding {self.outstanding_amount}"
            )
        new_outstanding = max(Decimal(0), new_outstanding)
        new_status = (
            APInvoiceStatus.FULLY_PAID if new_outstanding <= 0 else APInvoiceStatus.PARTIALLY_PAID
        )
        self._record_audit(
            "payment_recorded",
            self.created_by,
            {"payment_id": str(payment_id), "amount": str(amount)},
        )
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=new_paid,
            outstanding_amount=new_outstanding,
            status=new_status,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def receive(self, received_by: str) -> APInvoiceEntity:
        if self.status != APInvoiceStatus.DRAFT:
            raise ValueError(f"Cannot receive invoice in status {self.status.value}")
        self._record_audit("received", received_by, {})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=APInvoiceStatus.RECEIVED,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=received_by,
            version=self.version + 1,
        )

    def verify(self, verified_by: str) -> APInvoiceEntity:
        if self.status != APInvoiceStatus.RECEIVED:
            raise ValueError(f"Cannot verify invoice in status {self.status.value}")
        self._record_audit("verified", verified_by, {})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=APInvoiceStatus.VERIFIED,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=verified_by,
            version=self.version + 1,
        )

    def dispute(self, disputed_by: str, reason: str) -> APInvoiceEntity:
        if self.status not in (APInvoiceStatus.RECEIVED, APInvoiceStatus.VERIFIED):
            raise ValueError(f"Cannot dispute invoice in status {self.status.value}")
        self._record_audit("disputed", disputed_by, {"reason": reason})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=APInvoiceStatus.DISPUTED,
            description=f"{self.description}\nDisputed: {reason}",
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=disputed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> APInvoiceEntity:
        if self.status not in (
            APInvoiceStatus.DRAFT,
            APInvoiceStatus.RECEIVED,
            APInvoiceStatus.DISPUTED,
        ):
            raise ValueError(f"Cannot cancel invoice in status {self.status.value}")
        self._record_audit("cancelled", cancelled_by, {"reason": reason})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=APInvoiceStatus.CANCELLED,
            description=f"{self.description}\nCancelled: {reason}",
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    def mark_overdue(self) -> APInvoiceEntity:
        if self.status in (APInvoiceStatus.FULLY_PAID, APInvoiceStatus.CANCELLED):
            raise ValueError(f"Cannot mark invoice as overdue in status {self.status.value}")
        self._record_audit("marked_overdue", "system", {})
        return APInvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            invoice_date=self.invoice_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=APInvoiceStatus.OVERDUE,
            description=self.description,
            purchase_order_id=self.purchase_order_id,
            goods_receipt_id=self.goods_receipt_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            withholding_tax_amount=self.withholding_tax_amount,
            lines=self.lines,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "invoice_type": self.invoice_type.value,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "invoice_date": self.invoice_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "paid_amount": str(self.paid_amount),
            "outstanding_amount": str(self.outstanding_amount),
            "status": self.status.value,
            "description": self.description,
            "purchase_order_id": str(self.purchase_order_id) if self.purchase_order_id else None,
            "goods_receipt_id": str(self.goods_receipt_id) if self.goods_receipt_id else None,
            "tax_amount": str(self.tax_amount),
            "tax_rate": str(self.tax_rate),
            "discount_amount": str(self.discount_amount),
            "withholding_tax_amount": str(self.withholding_tax_amount),
            "lines": [line.to_dict() for line in self.lines],
            "is_overdue": self.is_overdue(),
            "days_overdue": self.days_overdue(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APInvoiceEntity:
        lines = [APInvoiceLine.from_dict(line) for line in data.get("lines", [])]
        return cls(
            invoice_id=UUID(data["invoice_id"]),
            invoice_number=data["invoice_number"],
            invoice_type=APInvoiceType.from_string(data["invoice_type"]),
            vendor_id=UUID(data["vendor_id"]),
            vendor_name=data["vendor_name"],
            invoice_date=datetime.fromisoformat(data["invoice_date"]),
            due_date=datetime.fromisoformat(data["due_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            paid_amount=Decimal(data.get("paid_amount", "0")),
            outstanding_amount=Decimal(data["outstanding_amount"]),
            status=APInvoiceStatus.from_string(data["status"]),
            description=data["description"],
            purchase_order_id=UUID(data["purchase_order_id"])
            if data.get("purchase_order_id")
            else None,
            goods_receipt_id=UUID(data["goods_receipt_id"])
            if data.get("goods_receipt_id")
            else None,
            tax_amount=Decimal(data.get("tax_amount", "0")),
            tax_rate=Decimal(data.get("tax_rate", "11")),
            discount_amount=Decimal(data.get("discount_amount", "0")),
            withholding_tax_amount=Decimal(data.get("withholding_tax_amount", "0")),
            lines=lines,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        invoice_number: str,
        invoice_type: APInvoiceType,
        vendor_id: UUID,
        vendor_name: str,
        invoice_date: datetime,
        due_date: datetime,
        amount: Decimal,
        currency: str,
        created_by: str,
        description: str = "",
        purchase_order_id: UUID | None = None,
    ) -> APInvoiceEntity:
        return cls(
            invoice_id=uuid4(),
            invoice_number=invoice_number,
            invoice_type=invoice_type,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            invoice_date=invoice_date,
            due_date=due_date,
            amount=amount,
            currency=currency,
            paid_amount=Decimal(0),
            outstanding_amount=amount,
            status=APInvoiceStatus.DRAFT,
            description=description,
            purchase_order_id=purchase_order_id,
            created_by=created_by,
        )


APInvoice = APInvoiceEntity


class APInvoiceRepository:
    async def get_by_id(self, invoice_id: UUID, legal_entity_id: UUID) -> APInvoiceEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, invoice_number: str, legal_entity_id: UUID
    ) -> APInvoiceEntity | None:
        raise NotImplementedError

    async def get_by_vendor(
        self, vendor_id: UUID, legal_entity_id: UUID, status: APInvoiceStatus | None = None
    ) -> list[APInvoiceEntity]:
        raise NotImplementedError

    async def get_by_po(
        self, purchase_order_id: UUID, legal_entity_id: UUID
    ) -> list[APInvoiceEntity]:
        raise NotImplementedError

    async def get_overdue(
        self, legal_entity_id: UUID, as_of: datetime | None = None
    ) -> list[APInvoiceEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[APInvoiceEntity]:
        raise NotImplementedError

    async def save(self, invoice: APInvoiceEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, invoice_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "APInvoice",
    "APInvoiceEntity",
    "APInvoiceLine",
    "APInvoiceRepository",
    "APInvoiceStatus",
    "APInvoiceType",
]
