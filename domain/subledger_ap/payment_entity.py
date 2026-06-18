#!/usr/bin/env python3
"""
Module: payment_entity.py
Layer: 6 - Domain / Subledger AP
Responsibility: Entitas pembayaran keluar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class APPaymentStatus(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    PROCESSED = "processed"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> APPaymentStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.PENDING


class APPaymentMethod(Enum):
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    CHECK = "check"
    GIRO = "giro"
    WIRE_TRANSFER = "wire_transfer"
    ONLINE_PAYMENT = "online_payment"

    @classmethod
    def from_string(cls, value: str) -> APPaymentMethod:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.BANK_TRANSFER


@dataclass
class APPaymentEntity:
    payment_id: UUID
    payment_number: str
    vendor_id: UUID
    vendor_name: str
    payment_date: datetime
    amount: Decimal
    currency: str
    payment_method: APPaymentMethod
    status: APPaymentStatus
    allocated_to_invoice_id: UUID | None = None
    allocated_amount: Decimal = Decimal(0)
    reference_number: str | None = None
    bank_account_from: str | None = None
    bank_account_to: str | None = None
    notes: str = ""
    approved_by: str | None = None
    approved_at: datetime | None = None
    processed_by: str | None = None
    processed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Payment amount must be positive: {self.amount}")
        if self.allocated_amount < 0:
            raise ValueError(f"Allocated amount cannot be negative: {self.allocated_amount}")
        if self.allocated_amount > self.amount + Decimal("0.01"):
            raise ValueError(
                f"Allocated amount {self.allocated_amount} exceeds payment amount {self.amount}"
            )
        if self.payment_date.tzinfo is None:
            self.payment_date = self.payment_date.replace(tzinfo=UTC)
        if self.approved_at and self.approved_at.tzinfo is None:
            self.approved_at = self.approved_at.replace(tzinfo=UTC)
        if self.processed_at and self.processed_at.tzinfo is None:
            self.processed_at = self.processed_at.replace(tzinfo=UTC)
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

    def is_fully_allocated(self) -> bool:
        return self.allocated_amount >= self.amount

    def get_remaining_amount(self) -> Decimal:
        return self.amount - self.allocated_amount

    def allocate_to_invoice(self, invoice_id: UUID, amount: Decimal) -> APPaymentEntity:
        if amount <= 0:
            raise ValueError("Allocation amount must be positive")
        new_allocated = self.allocated_amount + amount
        if new_allocated > self.amount + Decimal("0.01"):
            raise ValueError(
                f"Allocation amount {amount} exceeds remaining payment {self.get_remaining_amount()}"
            )
        self._record_audit(
            "allocated", self.created_by, {"invoice_id": str(invoice_id), "amount": str(amount)}
        )
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=self.status,
            allocated_to_invoice_id=invoice_id,
            allocated_amount=new_allocated,
            reference_number=self.reference_number,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=self.notes,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def approve(self, approved_by: str) -> APPaymentEntity:
        if self.status != APPaymentStatus.PENDING:
            raise ValueError(f"Cannot approve payment in status {self.status.value}")
        self._record_audit("approved", approved_by, {})
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=APPaymentStatus.APPROVED,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=self.reference_number,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=self.notes,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def process(self, processed_by: str, reference: str | None = None) -> APPaymentEntity:
        if self.status != APPaymentStatus.APPROVED:
            raise ValueError(f"Cannot process payment in status {self.status.value}")
        self._record_audit("processed", processed_by, {"reference": reference})
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=APPaymentStatus.PROCESSED,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=reference or self.reference_number,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=self.notes,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            processed_by=processed_by,
            processed_at=datetime.now(UTC),
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=self.created_by,
            version=self.version + 1,
        )

    def confirm(self, confirmed_by: str, bank_reference: str) -> APPaymentEntity:
        if self.status != APPaymentStatus.PROCESSED:
            raise ValueError(f"Cannot confirm payment in status {self.status.value}")
        self._record_audit("confirmed", confirmed_by, {"bank_reference": bank_reference})
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=APPaymentStatus.CONFIRMED,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=bank_reference,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=self.notes,
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=confirmed_by,
            version=self.version + 1,
        )

    def fail(self, failed_by: str, reason: str) -> APPaymentEntity:
        if self.status not in (
            APPaymentStatus.PENDING,
            APPaymentStatus.APPROVED,
            APPaymentStatus.PROCESSED,
        ):
            raise ValueError(f"Cannot fail payment in status {self.status.value}")
        self._record_audit("failed", failed_by, {"reason": reason})
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=APPaymentStatus.FAILED,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=self.reference_number,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=f"{self.notes}\nFailed: {reason}",
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=failed_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> APPaymentEntity:
        if self.status not in (APPaymentStatus.PENDING, APPaymentStatus.APPROVED):
            raise ValueError(f"Cannot cancel payment in status {self.status.value}")
        self._record_audit("cancelled", cancelled_by, {"reason": reason})
        return APPaymentEntity(
            payment_id=self.payment_id,
            payment_number=self.payment_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            payment_date=self.payment_date,
            amount=self.amount,
            currency=self.currency,
            payment_method=self.payment_method,
            status=APPaymentStatus.CANCELLED,
            allocated_to_invoice_id=self.allocated_to_invoice_id,
            allocated_amount=self.allocated_amount,
            reference_number=self.reference_number,
            bank_account_from=self.bank_account_from,
            bank_account_to=self.bank_account_to,
            notes=f"{self.notes}\nCancelled: {reason}",
            approved_by=self.approved_by,
            approved_at=self.approved_at,
            processed_by=self.processed_by,
            processed_at=self.processed_at,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "payment_id": str(self.payment_id),
            "payment_number": self.payment_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "payment_date": self.payment_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "payment_method": self.payment_method.value,
            "status": self.status.value,
            "allocated_to_invoice_id": str(self.allocated_to_invoice_id)
            if self.allocated_to_invoice_id
            else None,
            "allocated_amount": str(self.allocated_amount),
            "remaining_amount": str(self.get_remaining_amount()),
            "is_fully_allocated": self.is_fully_allocated(),
            "reference_number": self.reference_number,
            "bank_account_from": self.bank_account_from,
            "bank_account_to": self.bank_account_to,
            "notes": self.notes,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "processed_by": self.processed_by,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APPaymentEntity:
        return cls(
            payment_id=UUID(data["payment_id"]),
            payment_number=data["payment_number"],
            vendor_id=UUID(data["vendor_id"]),
            vendor_name=data["vendor_name"],
            payment_date=datetime.fromisoformat(data["payment_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            payment_method=APPaymentMethod.from_string(data["payment_method"]),
            status=APPaymentStatus.from_string(data["status"]),
            allocated_to_invoice_id=UUID(data["allocated_to_invoice_id"])
            if data.get("allocated_to_invoice_id")
            else None,
            allocated_amount=Decimal(data.get("allocated_amount", "0")),
            reference_number=data.get("reference_number"),
            bank_account_from=data.get("bank_account_from"),
            bank_account_to=data.get("bank_account_to"),
            notes=data.get("notes", ""),
            approved_by=data.get("approved_by"),
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            processed_by=data.get("processed_by"),
            processed_at=datetime.fromisoformat(data["processed_at"])
            if data.get("processed_at")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        payment_number: str,
        vendor_id: UUID,
        vendor_name: str,
        payment_date: datetime,
        amount: Decimal,
        currency: str,
        payment_method: APPaymentMethod,
        created_by: str,
        bank_account_from: str | None = None,
        bank_account_to: str | None = None,
        notes: str = "",
    ) -> APPaymentEntity:
        return cls(
            payment_id=uuid4(),
            payment_number=payment_number,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            payment_date=payment_date,
            amount=amount,
            currency=currency,
            payment_method=payment_method,
            status=APPaymentStatus.PENDING,
            bank_account_from=bank_account_from,
            bank_account_to=bank_account_to,
            notes=notes,
            created_by=created_by,
        )


APPayment = APPaymentEntity


class APPaymentRepository:
    async def get_by_id(self, payment_id: UUID, legal_entity_id: UUID) -> APPaymentEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, payment_number: str, legal_entity_id: UUID
    ) -> APPaymentEntity | None:
        raise NotImplementedError

    async def get_by_vendor(
        self,
        vendor_id: UUID,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[APPaymentEntity]:
        raise NotImplementedError

    async def get_pending_approval(self, legal_entity_id: UUID) -> list[APPaymentEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[APPaymentEntity]:
        raise NotImplementedError

    async def save(self, payment: APPaymentEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, payment_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "APPayment",
    "APPaymentEntity",
    "APPaymentMethod",
    "APPaymentRepository",
    "APPaymentStatus",
]
