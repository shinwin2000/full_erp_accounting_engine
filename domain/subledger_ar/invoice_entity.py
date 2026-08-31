#!/usr/bin/env python3
"""
Module: invoice_entity.py
Layer: Domain / Subledger AR
Responsibility: Entitas faktur penjualan kredit dan item baris faktur (Invoice Line).

Metode yang ditambahkan:
- Entity dasar untuk InvoiceLineEntity: validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Entity dasar untuk InvoiceEntity: create, update, delete, restore, activate, deactivate,
  lock, unlock, validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Business: record_payment, apply_credit_note, write_off, cancel, is_overdue, days_overdue.
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


# === 1. CONSTANTS & ENUMS ===
class InvoiceStatus(Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partial"
    FULLY_PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"
    CANCELLED = "cancelled"

    def can_edit(self) -> bool:
        return self in (InvoiceStatus.DRAFT, InvoiceStatus.ISSUED)

    def can_cancel(self) -> bool:
        return self in (InvoiceStatus.DRAFT, InvoiceStatus.ISSUED)

    def can_record_payment(self) -> bool:
        return self in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID)


class InvoiceType(Enum):
    STANDARD = "standard"
    CREDIT = "credit"
    DEBIT = "debit"
    PROFORMA = "proforma"


# === 2. INVOICE LINE ENTITY ===
@dataclass
class InvoiceLineEntity:
    id: UUID
    description: str
    quantity: Decimal
    unit_price: Money
    tax_rate: Decimal
    discount_percent: Decimal
    account_code: str
    total_amount: Money

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _version: int = 1

    def __post_init__(self):
        if self.quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if self.discount_percent < 0 or self.discount_percent > 100:
            raise ValueError("Discount percent must be between 0 and 100")
        if self.tax_rate < 0 or self.tax_rate > 100:
            raise ValueError("Tax rate must be between 0 and 100")
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "id": str(self.id),
            "description": self.description[:50],
            "quantity": str(self.quantity),
            "total_amount": str(self.total_amount.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "line_id": str(self.id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if self.quantity <= 0:
            errors.append("Quantity must be positive")
        if self.unit_price.amount <= 0:
            errors.append("Unit price must be positive")
        if not self.account_code:
            errors.append("Account code is required")
        if self.total_amount.amount != self.quantity * self.unit_price.amount * (
            1 - self.discount_percent / 100
        ) * (1 + self.tax_rate / 100):
            errors.append("Total amount calculation mismatch")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "description": self.description,
            "quantity": str(self.quantity),
            "unit_price": self.unit_price.to_dict(),
            "tax_rate": str(self.tax_rate),
            "discount_percent": str(self.discount_percent),
            "account_code": self.account_code,
            "total_amount": self.total_amount.to_dict(),
            "version": self._version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvoiceLineEntity:
        unit_price = Money.from_dict(data["unit_price"])
        total_amount = Money.from_dict(data["total_amount"])
        return cls(
            id=UUID(data["id"]),
            description=data["description"],
            quantity=Decimal(data["quantity"]),
            unit_price=unit_price,
            tax_rate=Decimal(data["tax_rate"]),
            discount_percent=Decimal(data["discount_percent"]),
            account_code=data["account_code"],
            total_amount=total_amount,
        )

    def clone(self) -> InvoiceLineEntity:
        new_id = uuid4()
        cloned = InvoiceLineEntity(
            id=new_id,
            description=self.description,
            quantity=self.quantity,
            unit_price=Money(self.unit_price.amount, self.unit_price.currency),
            tax_rate=self.tax_rate,
            discount_percent=self.discount_percent,
            account_code=self.account_code,
            total_amount=Money(self.total_amount.amount, self.total_amount.currency),
        )
        cloned._version = self._version + 1
        cloned._record_audit("CLONE", "system", {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "id": str(self.id),
            "description": self.description[:50],
            "quantity": str(self.quantity),
            "total_amount": str(self.total_amount.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvoiceLineEntity:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 3. INVOICE ENTITY ===
@dataclass
class InvoiceEntity:
    invoice_id: UUID
    invoice_number: str
    invoice_type: InvoiceType
    customer_id: UUID
    customer_name: str
    issue_date: datetime
    due_date: datetime
    amount: Decimal
    currency: str
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: InvoiceStatus
    description: str
    sales_order_id: UUID | None = None
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    discount_amount: Decimal = Decimal(0)
    lines: list[InvoiceLineEntity] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # Fields untuk audit
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Invoice amount must be positive: {self.amount}")
        if self.due_date <= self.issue_date:
            raise ValueError("Due date must be after issue date")
        if self.paid_amount < 0 or self.outstanding_amount < 0:
            raise ValueError("Paid amount and outstanding amount cannot be negative")
        if self.paid_amount > self.amount:
            raise ValueError(f"Paid amount {self.paid_amount} exceeds invoice amount {self.amount}")
        if self.tax_amount < 0:
            raise ValueError("Tax amount cannot be negative")
        if self.discount_amount < 0 or self.discount_amount > self.amount:
            raise ValueError("Discount amount invalid")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "outstanding": str(self.outstanding_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "invoice_id": str(self.invoice_id),
                "details": details,
            }
        )

    # ==================== BUSINESS METHODS ====================
    def is_overdue(self, as_of: datetime | None = None) -> bool:
        if self.status in (
            InvoiceStatus.FULLY_PAID,
            InvoiceStatus.WRITTEN_OFF,
            InvoiceStatus.CANCELLED,
        ):
            return False
        as_of = as_of or datetime.now(UTC)
        return as_of > self.due_date

    def days_overdue(self, as_of: datetime | None = None) -> int:
        if not self.is_overdue(as_of):
            return 0
        as_of = as_of or datetime.now(UTC)
        return (as_of - self.due_date).days

    def record_payment(self, amount: Decimal, payment_id: UUID) -> InvoiceEntity:
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        if not self.status.can_record_payment():
            raise ValueError(f"Cannot record payment for invoice in status {self.status.value}")
        new_paid = self.paid_amount + amount
        new_outstanding = self.amount - new_paid
        if new_outstanding < 0:
            raise ValueError(
                f"Payment amount {amount} exceeds outstanding {self.outstanding_amount}"
            )
        new_status = (
            InvoiceStatus.FULLY_PAID if new_outstanding <= 0 else InvoiceStatus.PARTIALLY_PAID
        )
        new_invoice = self._copy()
        new_invoice.paid_amount = new_paid
        new_invoice.outstanding_amount = new_outstanding
        new_invoice.status = new_status
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit(
            "RECORD_PAYMENT", "system", {"payment_id": str(payment_id), "amount": str(amount)}
        )
        return new_invoice

    def apply_credit_note(self, amount: Decimal) -> InvoiceEntity:
        if amount <= 0:
            raise ValueError("Credit note amount must be positive")
        new_outstanding = self.outstanding_amount - amount
        if new_outstanding < 0:
            raise ValueError(
                f"Credit note amount {amount} exceeds outstanding {self.outstanding_amount}"
            )
        new_invoice = self._copy()
        new_invoice.outstanding_amount = new_outstanding
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("APPLY_CREDIT_NOTE", "system", {"amount": str(amount)})
        return new_invoice

    def write_off(self, written_off_by: str, reason: str) -> InvoiceEntity:
        if self.status not in (
            InvoiceStatus.ISSUED,
            InvoiceStatus.PARTIALLY_PAID,
            InvoiceStatus.OVERDUE,
        ):
            raise ValueError(f"Cannot write off invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.outstanding_amount = Decimal(0)
        new_invoice.status = InvoiceStatus.WRITTEN_OFF
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("WRITE_OFF", written_off_by, {"reason": reason})
        return new_invoice

    def cancel(self, cancelled_by: str, reason: str) -> InvoiceEntity:
        if not self.status.can_cancel():
            raise ValueError(f"Cannot cancel invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.status = InvoiceStatus.CANCELLED
        new_invoice.description = f"{self.description}\nCancelled: {reason}"
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_invoice

    def to_money(self) -> Money:
        return Money(self.amount, self.currency)

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> InvoiceEntity:
        self._record_audit("CREATE", created_by, {"invoice_number": self.invoice_number})
        return self

    def update(self, updated_by: str, **kwargs) -> InvoiceEntity:
        if not self.status.can_edit():
            raise ValueError(f"Cannot update invoice in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("invoice_id", "created_at", "created_by", "version", "lines"):
                data[key] = value
        new_invoice = self._copy()
        if "invoice_number" in kwargs:
            new_invoice.invoice_number = kwargs["invoice_number"]
        if "description" in kwargs:
            new_invoice.description = kwargs["description"]
        if "due_date" in kwargs:
            new_invoice.due_date = kwargs["due_date"]
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_invoice

    def delete(self, deleted_by: str, reason: str | None = None) -> InvoiceEntity:
        if self.status != InvoiceStatus.CANCELLED and self.status != InvoiceStatus.DRAFT:
            raise ValueError(f"Cannot delete invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.status = InvoiceStatus.CANCELLED
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_invoice

    def restore(self, restored_by: str) -> InvoiceEntity:
        if self.status != InvoiceStatus.CANCELLED:
            raise ValueError(f"Cannot restore invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.status = InvoiceStatus.DRAFT
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("RESTORE", restored_by, {})
        return new_invoice

    def activate(self, activated_by: str) -> InvoiceEntity:
        if self.status == InvoiceStatus.ISSUED:
            return self
        if self.status != InvoiceStatus.DRAFT:
            raise ValueError(f"Cannot activate invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.status = InvoiceStatus.ISSUED
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("ACTIVATE", activated_by, {})
        return new_invoice

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> InvoiceEntity:
        if self.status == InvoiceStatus.DRAFT:
            return self
        if self.status != InvoiceStatus.ISSUED:
            raise ValueError(f"Cannot deactivate invoice in status {self.status.value}")
        new_invoice = self._copy()
        new_invoice.status = InvoiceStatus.DRAFT
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_invoice

    def lock(self, locked_by: str, reason: str) -> InvoiceEntity:
        new_invoice = self._copy()
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("LOCK", locked_by, {"reason": reason})
        return new_invoice

    def unlock(self, unlocked_by: str) -> InvoiceEntity:
        new_invoice = self._copy()
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("UNLOCK", unlocked_by, {})
        return new_invoice

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        for line in self.lines:
            res = line.validate()
            if not res["is_valid"]:
                errors.extend([f"Line {line.id}: {e}" for e in res["errors"]])
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "invoice_id": str(self.invoice_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "invoice_type": self.invoice_type.value,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "issue_date": self.issue_date.isoformat(),
            "due_date": self.due_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "paid_amount": str(self.paid_amount),
            "outstanding_amount": str(self.outstanding_amount),
            "status": self.status.value,
            "description": self.description,
            "sales_order_id": str(self.sales_order_id) if self.sales_order_id else None,
            "tax_amount": str(self.tax_amount),
            "tax_rate": str(self.tax_rate),
            "discount_amount": str(self.discount_amount),
            "lines": [line.to_dict() for line in self.lines],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvoiceEntity:
        lines = [InvoiceLineEntity.from_dict(line) for line in data.get("lines", [])]
        instance = cls(
            invoice_id=UUID(data["invoice_id"]),
            invoice_number=data["invoice_number"],
            invoice_type=InvoiceType(data["invoice_type"]),
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            issue_date=datetime.fromisoformat(data["issue_date"]),
            due_date=datetime.fromisoformat(data["due_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            paid_amount=Decimal(data["paid_amount"]),
            outstanding_amount=Decimal(data["outstanding_amount"]),
            status=InvoiceStatus(data["status"]),
            description=data.get("description", ""),
            sales_order_id=UUID(data["sales_order_id"]) if data.get("sales_order_id") else None,
            tax_amount=Decimal(data.get("tax_amount", "0")),
            tax_rate=Decimal(data.get("tax_rate", "11")),
            discount_amount=Decimal(data.get("discount_amount", "0")),
            lines=lines,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )
        return instance

    def clone(self) -> InvoiceEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        new_lines = [line.clone() for line in self.lines]
        cloned = InvoiceEntity(
            invoice_id=new_id,
            invoice_number=f"{self.invoice_number}_COPY",
            invoice_type=self.invoice_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            issue_date=now,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=Decimal(0),
            outstanding_amount=self.amount,
            status=InvoiceStatus.DRAFT,
            description=f"Cloned from {self.invoice_number}",
            sales_order_id=self.sales_order_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            lines=new_lines,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.invoice_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "outstanding": str(self.outstanding_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvoiceEntity:
        new_invoice = self._copy()
        new_invoice.updated_at = datetime.now(UTC)
        new_invoice.version = self.version + 1
        new_invoice._record_audit("TOUCH", touched_by, {})
        return new_invoice

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> InvoiceEntity:
        return InvoiceEntity(
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            invoice_type=self.invoice_type,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            issue_date=self.issue_date,
            due_date=self.due_date,
            amount=self.amount,
            currency=self.currency,
            paid_amount=self.paid_amount,
            outstanding_amount=self.outstanding_amount,
            status=self.status,
            description=self.description,
            sales_order_id=self.sales_order_id,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            discount_amount=self.discount_amount,
            lines=self.lines.copy(),
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# === ALIAS UNTUK KOMPATIBILITAS ===
ARInvoice = InvoiceEntity
ARInvoiceStatus = InvoiceStatus
ARInvoiceType = InvoiceType
ARInvoiceLine = InvoiceLineEntity


# === 4. INVOICE REPOSITORY PROTOCOL ===
class InvoiceRepository:
    async def get_by_id(self, invoice_id: UUID, legal_entity_id: UUID) -> InvoiceEntity | None:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID, status: InvoiceStatus | None = None
    ) -> list[InvoiceEntity]:
        raise NotImplementedError

    async def get_overdue(self, legal_entity_id: UUID, as_of: datetime) -> list[InvoiceEntity]:
        raise NotImplementedError

    async def save(self, invoice: InvoiceEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, invoice_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    # Repository standard methods
    async def add(self, invoice: InvoiceEntity, legal_entity_id: UUID) -> None:
        await self.save(invoice, legal_entity_id)

    async def update(self, invoice: InvoiceEntity, legal_entity_id: UUID) -> None:
        await self.save(invoice, legal_entity_id)

    async def exists(self, invoice_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[InvoiceEntity]:
        raise NotImplementedError

    async def search(self, legal_entity_id: UUID, criteria: dict[str, Any]) -> list[InvoiceEntity]:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[InvoiceEntity]:
        raise NotImplementedError

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[InvoiceEntity], int]:
        offset = (page - 1) * per_page
        items = await self.list_all(legal_entity_id, limit=per_page, offset=offset)
        total = await self.count(legal_entity_id)
        return items, total


# === 5. EXPORTS ===
__all__ = [
    "ARInvoice",
    "ARInvoiceLine",
    "ARInvoiceStatus",
    "ARInvoiceType",
    "InvoiceEntity",
    "InvoiceLineEntity",
    "InvoiceRepository",
    "InvoiceStatus",
    "InvoiceType",
]
