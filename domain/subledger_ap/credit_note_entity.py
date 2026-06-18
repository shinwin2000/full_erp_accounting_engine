#!/usr/bin/env python3
"""
Module: credit_note_entity.py
Layer: 6 - Domain / Subledger AP
Responsibility: Nota kredit dari pemasok.
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


class APCreditNoteStatus(Enum):
    DRAFT = "draft"
    RECEIVED = "received"
    APPLIED = "applied"
    CANCELLED = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> APCreditNoteStatus:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.DRAFT


class APCreditNoteReason(Enum):
    GOODS_RETURN = "goods_return"
    PRICE_ADJUSTMENT = "price_adjustment"
    DISCOUNT = "discount"
    CANCELLATION = "cancellation"
    CORRECTION = "correction"
    QUALITY_ISSUE = "quality_issue"

    @classmethod
    def from_string(cls, value: str) -> APCreditNoteReason:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.CORRECTION


@dataclass
class APCreditNoteEntity:
    credit_note_id: UUID
    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    vendor_id: UUID
    vendor_name: str
    issue_date: datetime
    amount: Decimal
    currency: str
    reason: APCreditNoteReason
    status: APCreditNoteStatus
    description: str
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    original_invoice_amount: Decimal | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    _audit_trail: list[dict] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Credit note amount must be positive: {self.amount}")
        if self.original_invoice_amount and self.amount > self.original_invoice_amount:
            raise ValueError(
                f"Credit note amount {self.amount} exceeds invoice amount {self.original_invoice_amount}"
            )
        if self.issue_date.tzinfo is None:
            self.issue_date = self.issue_date.replace(tzinfo=UTC)
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

    def receive(self, received_by: str) -> APCreditNoteEntity:
        if self.status != APCreditNoteStatus.DRAFT:
            raise ValueError(f"Cannot receive credit note in status {self.status.value}")
        self._record_audit("received", received_by, {})
        return APCreditNoteEntity(
            credit_note_id=self.credit_note_id,
            credit_note_number=self.credit_note_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            issue_date=self.issue_date,
            amount=self.amount,
            currency=self.currency,
            reason=self.reason,
            status=APCreditNoteStatus.RECEIVED,
            description=self.description,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            original_invoice_amount=self.original_invoice_amount,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=received_by,
            version=self.version + 1,
        )

    def apply(self, applied_by: str) -> APCreditNoteEntity:
        if self.status != APCreditNoteStatus.RECEIVED:
            raise ValueError(f"Cannot apply credit note in status {self.status.value}")
        self._record_audit("applied", applied_by, {"invoice_id": str(self.invoice_id)})
        return APCreditNoteEntity(
            credit_note_id=self.credit_note_id,
            credit_note_number=self.credit_note_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            issue_date=self.issue_date,
            amount=self.amount,
            currency=self.currency,
            reason=self.reason,
            status=APCreditNoteStatus.APPLIED,
            description=self.description,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            original_invoice_amount=self.original_invoice_amount,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=applied_by,
            version=self.version + 1,
        )

    def cancel(self, cancelled_by: str, reason: str) -> APCreditNoteEntity:
        if self.status not in (APCreditNoteStatus.DRAFT, APCreditNoteStatus.RECEIVED):
            raise ValueError(f"Cannot cancel credit note in status {self.status.value}")
        self._record_audit("cancelled", cancelled_by, {"reason": reason})
        return APCreditNoteEntity(
            credit_note_id=self.credit_note_id,
            credit_note_number=self.credit_note_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            vendor_id=self.vendor_id,
            vendor_name=self.vendor_name,
            issue_date=self.issue_date,
            amount=self.amount,
            currency=self.currency,
            reason=self.reason,
            status=APCreditNoteStatus.CANCELLED,
            description=f"{self.description}\nCancelled: {reason}",
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            original_invoice_amount=self.original_invoice_amount,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=cancelled_by,
            version=self.version + 1,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_note_id": str(self.credit_note_id),
            "credit_note_number": self.credit_note_number,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "vendor_id": str(self.vendor_id),
            "vendor_name": self.vendor_name,
            "issue_date": self.issue_date.isoformat(),
            "amount": str(self.amount),
            "currency": self.currency,
            "reason": self.reason.value,
            "status": self.status.value,
            "description": self.description,
            "tax_amount": str(self.tax_amount),
            "tax_rate": str(self.tax_rate),
            "original_invoice_amount": str(self.original_invoice_amount)
            if self.original_invoice_amount
            else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> APCreditNoteEntity:
        return cls(
            credit_note_id=UUID(data["credit_note_id"]),
            credit_note_number=data["credit_note_number"],
            invoice_id=UUID(data["invoice_id"]),
            invoice_number=data["invoice_number"],
            vendor_id=UUID(data["vendor_id"]),
            vendor_name=data["vendor_name"],
            issue_date=datetime.fromisoformat(data["issue_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            reason=APCreditNoteReason.from_string(data["reason"]),
            status=APCreditNoteStatus.from_string(data["status"]),
            description=data["description"],
            tax_amount=Decimal(data.get("tax_amount", "0")),
            tax_rate=Decimal(data.get("tax_rate", "11")),
            original_invoice_amount=Decimal(data["original_invoice_amount"])
            if data.get("original_invoice_amount")
            else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    @classmethod
    def create(
        cls,
        credit_note_number: str,
        invoice_id: UUID,
        invoice_number: str,
        vendor_id: UUID,
        vendor_name: str,
        issue_date: datetime,
        amount: Decimal,
        currency: str,
        reason: APCreditNoteReason,
        created_by: str,
        description: str = "",
        tax_amount: Decimal = Decimal(0),
        original_invoice_amount: Decimal | None = None,
    ) -> APCreditNoteEntity:
        return cls(
            credit_note_id=uuid4(),
            credit_note_number=credit_note_number,
            invoice_id=invoice_id,
            invoice_number=invoice_number,
            vendor_id=vendor_id,
            vendor_name=vendor_name,
            issue_date=issue_date,
            amount=amount,
            currency=currency,
            reason=reason,
            status=APCreditNoteStatus.DRAFT,
            description=description,
            tax_amount=tax_amount,
            original_invoice_amount=original_invoice_amount,
            created_by=created_by,
        )


APCreditNote = APCreditNoteEntity


class APCreditNoteRepository:
    async def get_by_id(
        self, credit_note_id: UUID, legal_entity_id: UUID
    ) -> APCreditNoteEntity | None:
        raise NotImplementedError

    async def get_by_invoice(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> list[APCreditNoteEntity]:
        raise NotImplementedError

    async def get_by_vendor(
        self, vendor_id: UUID, legal_entity_id: UUID
    ) -> list[APCreditNoteEntity]:
        raise NotImplementedError

    async def get_by_date_range(
        self, legal_entity_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[APCreditNoteEntity]:
        raise NotImplementedError

    async def save(self, credit_note: APCreditNoteEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, credit_note_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "APCreditNote",
    "APCreditNoteEntity",
    "APCreditNoteReason",
    "APCreditNoteRepository",
    "APCreditNoteStatus",
]
