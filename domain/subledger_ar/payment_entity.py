#!/usr/bin/env python3
"""
Module: payment_entity.py
Layer: Domain / Subledger AR
Responsibility: Entitas pembayaran masuk.

Metode yang ditambahkan:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Business: allocate_to_invoice, confirm, refund, is_fully_allocated.
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
class PaymentStatus(Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    ALLOCATED = "allocated"
    FAILED = "failed"
    REFUNDED = "refunded"

    def can_allocate(self) -> bool:
        return self in (PaymentStatus.CONFIRMED, PaymentStatus.PENDING)

    def can_confirm(self) -> bool:
        return self == PaymentStatus.PENDING

    def can_refund(self) -> bool:
        return self in (PaymentStatus.CONFIRMED, PaymentStatus.ALLOCATED)


class PaymentMethod(Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    CHECK = "check"
    DIGITAL_WALLET = "digital_wallet"
    OTHER = "other"


# === 2. PAYMENT ENTITY ===
@dataclass
class PaymentEntity:
    payment_id: UUID
    payment_number: str
    customer_id: UUID
    customer_name: str
    payment_date: datetime
    amount: Decimal
    currency: str
    payment_method: PaymentMethod
    status: PaymentStatus
    allocated_to_invoice_id: UUID | None = None
    allocated_amount: Decimal = Decimal(0)
    reference_number: str | None = None
    bank_reference: str | None = None
    notes: str = ""
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
            raise ValueError(f"Payment amount must be positive: {self.amount}")
        if self.allocated_amount < 0:
            raise ValueError("Allocated amount cannot be negative")
        if self.allocated_amount > self.amount:
            raise ValueError(
                f"Allocated amount {self.allocated_amount} exceeds payment amount {self.amount}"
            )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "payment_id": str(self.payment_id),
            "payment_number": self.payment_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "allocated_amount": str(self.allocated_amount),
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
                "payment_id": str(self.payment_id),
                "details": details,
            }
        )

    # ==================== BUSINESS METHODS ====================
    def is_fully_allocated(self) -> bool:
        return self.allocated_amount >= self.amount

    def allocate_to_invoice(self, invoice_id: UUID, amount: Decimal) -> PaymentEntity:
        if amount <= 0:
            raise ValueError("Allocation amount must be positive")
        if not self.status.can_allocate():
            raise ValueError(f"Cannot allocate payment in status {self.status.value}")
        new_allocated = self.allocated_amount + amount
        if new_allocated > self.amount:
            raise ValueError(
                f"Allocation amount {amount} exceeds remaining payment {self.amount - self.allocated_amount}"
            )
        new_status = PaymentStatus.ALLOCATED if new_allocated >= self.amount else self.status
        new_payment = self._copy()
        new_payment.allocated_to_invoice_id = invoice_id
        new_payment.allocated_amount = new_allocated
        new_payment.status = new_status
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit(
            "ALLOCATE_TO_INVOICE", "system", {"invoice_id": str(invoice_id), "amount": str(amount)}
        )
        return new_payment

    def confirm(self, confirmed_by: str) -> PaymentEntity:
        if not self.status.can_confirm():
            raise ValueError(f"Cannot confirm payment in status {self.status.value}")
        new_payment = self._copy()
        new_payment.status = PaymentStatus.CONFIRMED
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("CONFIRM", confirmed_by, {})
        return new_payment

    def refund(self, refunded_by: str, reason: str) -> PaymentEntity:
        if not self.status.can_refund():
            raise ValueError(f"Cannot refund payment in status {self.status.value}")
        new_payment = self._copy()
        new_payment.status = PaymentStatus.REFUNDED
        new_payment.notes = f"{self.notes}\nRefunded: {reason}"
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("REFUND", refunded_by, {"reason": reason})
        return new_payment

    def to_money(self) -> Money:
        return Money(self.amount, self.currency)

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> PaymentEntity:
        self._record_audit("CREATE", created_by, {"payment_number": self.payment_number})
        return self

    def update(self, updated_by: str, **kwargs) -> PaymentEntity:
        if self.status not in (PaymentStatus.PENDING, PaymentStatus.CONFIRMED):
            raise ValueError(f"Cannot update payment in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in (
                "payment_id",
                "created_at",
                "created_by",
                "version",
                "allocated_amount",
                "allocated_to_invoice_id",
            ):
                data[key] = value
        new_payment = self._copy()
        if "payment_number" in kwargs:
            new_payment.payment_number = kwargs["payment_number"]
        if "reference_number" in kwargs:
            new_payment.reference_number = kwargs["reference_number"]
        if "bank_reference" in kwargs:
            new_payment.bank_reference = kwargs["bank_reference"]
        if "notes" in kwargs:
            new_payment.notes = kwargs["notes"]
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_payment

    def delete(self, deleted_by: str, reason: str | None = None) -> PaymentEntity:
        if self.status != PaymentStatus.PENDING and self.status != PaymentStatus.FAILED:
            raise ValueError(f"Cannot delete payment in status {self.status.value}")
        new_payment = self._copy()
        new_payment.status = PaymentStatus.FAILED
        new_payment.notes = f"{self.notes}\nDeleted: {reason}"
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_payment

    def restore(self, restored_by: str) -> PaymentEntity:
        if self.status != PaymentStatus.FAILED:
            raise ValueError(f"Cannot restore payment in status {self.status.value}")
        new_payment = self._copy()
        new_payment.status = PaymentStatus.PENDING
        new_payment.allocated_amount = Decimal(0)
        new_payment.allocated_to_invoice_id = None
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("RESTORE", restored_by, {})
        return new_payment

    def activate(self, activated_by: str) -> PaymentEntity:
        if self.status == PaymentStatus.CONFIRMED:
            return self
        if self.status != PaymentStatus.PENDING:
            raise ValueError(f"Cannot activate payment in status {self.status.value}")
        return self.confirm(activated_by)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> PaymentEntity:
        if self.status == PaymentStatus.PENDING:
            return self
        if self.status != PaymentStatus.CONFIRMED:
            raise ValueError(f"Cannot deactivate payment in status {self.status.value}")
        new_payment = self._copy()
        new_payment.status = PaymentStatus.PENDING
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_payment

    def lock(self, locked_by: str, reason: str) -> PaymentEntity:
        new_payment = self._copy()
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("LOCK", locked_by, {"reason": reason})
        return new_payment

    def unlock(self, unlocked_by: str) -> PaymentEntity:
        new_payment = self._copy()
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("UNLOCK", unlocked_by, {})
        return new_payment

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        if self.allocated_to_invoice_id and self.allocated_amount == 0:
            errors.append("Allocated to invoice but allocated amount is zero")
        if self.allocated_amount > 0 and not self.allocated_to_invoice_id:
            errors.append("Allocated amount > 0 but no invoice specified")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "payment_id": str(self.payment_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_id": str(self.payment_id),
            "payment_number": self.payment_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method.value,
            "status": self.status.value,
            "allocated_to_invoice_id": str(self.allocated_to_invoice_id)
            if self.allocated_to_invoice_id
            else None,
            "allocated_amount": str(self.allocated_amount),
            "reference_number": self.reference_number,
            "bank_reference": self.bank_reference,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PaymentEntity:
        instance = cls(
            payment_id=UUID(data["payment_id"]),
            payment_number=data["payment_number"],
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            payment_date=datetime.fromisoformat(data["payment_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            payment_method=PaymentMethod(data["payment_method"]),
            status=PaymentStatus(data["status"]),
            allocated_to_invoice_id=UUID(data["allocated_to_invoice_id"])
            if data.get("allocated_to_invoice_id")
            else None,
            allocated_amount=Decimal(data.get("allocated_amount", "0")),
            reference_number=data.get("reference_number"),
            bank_reference=data.get("bank_reference"),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )
        return instance

    def clone(self) -> PaymentEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = PaymentEntity(
            payment_id=new_id,
            payment_number=f"{self.payment_number}_COPY",
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            payment_date=now,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=PaymentStatus.PENDING,
            allocated_to_invoice_id=None,
            allocated_amount=Decimal(0),
            reference_number=self.reference_number,
            bank_reference=self.bank_reference,
            notes=f"Cloned from {self.payment_number}",
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.payment_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "payment_id": str(self.payment_id),
            "payment_number": self.payment_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "allocated_amount": str(self.allocated_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> PaymentEntity:
        new_payment = self._copy()
        new_payment.updated_at = datetime.now(UTC)
        new_payment.version = self.version + 1
        new_payment._record_audit("TOUCH", touched_by, {})
        return new_payment

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> PaymentEntity:
        return PaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=self.status,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=self.reference_number,
            bank_reference=self.bank_reference,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# === ALIAS UNTUK KOMPATIBILITAS ===
ARPayment = PaymentEntity
ARPaymentStatus = PaymentStatus
ARPaymentMethod = PaymentMethod


# === 3. PAYMENT REPOSITORY PROTOCOL ===
class PaymentRepository:
    async def get_by_id(self, payment_id: UUID, legal_entity_id: UUID) -> PaymentEntity | None:
        raise NotImplementedError

    async def get_by_customer(
        self,
        customer_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[PaymentEntity]:
        raise NotImplementedError

    async def get_unallocated(self, legal_entity_id: UUID) -> list[PaymentEntity]:
        raise NotImplementedError

    async def save(self, payment: PaymentEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, payment_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    # Repository standard methods
    async def add(self, payment: PaymentEntity, legal_entity_id: UUID) -> None:
        await self.save(payment, legal_entity_id)

    async def update(self, payment: PaymentEntity, legal_entity_id: UUID) -> None:
        await self.save(payment, legal_entity_id)

    async def exists(self, payment_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PaymentEntity]:
        raise NotImplementedError

    async def search(self, legal_entity_id: UUID, criteria: dict[str, Any]) -> list[PaymentEntity]:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[PaymentEntity]:
        raise NotImplementedError

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[PaymentEntity], int]:
        raise NotImplementedError


# === 4. EXPORTS ===
__all__ = [
    "ARPayment",
    "ARPaymentMethod",
    "ARPaymentStatus",
    "PaymentEntity",
    "PaymentMethod",
    "PaymentRepository",
    "PaymentStatus",
]
