#!/usr/bin/env python3
"""
Module: credit_note_entity.py
Layer: Domain / Subledger AR
Responsibility: Nota kredit (retur/pengurang piutang).

Metode yang ditambahkan:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Business: apply(), cancel()
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
class CreditNoteStatus(Enum):
    DRAFT = "draft"
    ISSUED = "issued"
    APPLIED = "applied"
    CANCELLED = "cancelled"

    def can_apply(self) -> bool:
        return self == CreditNoteStatus.ISSUED

    def can_cancel(self) -> bool:
        return self in (CreditNoteStatus.DRAFT, CreditNoteStatus.ISSUED)

    def can_edit(self) -> bool:
        return self == CreditNoteStatus.DRAFT


class CreditNoteReason(Enum):
    GOODS_RETURN = "goods_return"
    PRICE_ADJUSTMENT = "price_adjustment"
    DISCOUNT = "discount"
    CANCELLATION = "cancellation"
    CORRECTION = "correction"

    def display_name(self) -> str:
        names = {
            CreditNoteReason.GOODS_RETURN: "Retur Barang",
            CreditNoteReason.PRICE_ADJUSTMENT: "Penyesuaian Harga",
            CreditNoteReason.DISCOUNT: "Diskon",
            CreditNoteReason.CANCELLATION: "Pembatalan",
            CreditNoteReason.CORRECTION: "Koreksi",
        }
        return names.get(self, self.value)


# === 2. CREDIT NOTE ENTITY ===
@dataclass
class CreditNoteEntity:
    credit_note_id: UUID
    credit_note_number: str
    invoice_id: UUID
    invoice_number: str
    customer_id: UUID
    customer_name: str
    issue_date: datetime
    amount: Decimal
    currency: str
    reason: CreditNoteReason
    status: CreditNoteStatus
    description: str
    tax_amount: Decimal = Decimal(0)
    tax_rate: Decimal = Decimal(11)
    original_invoice_amount: Decimal | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # Fields untuk audit dan snapshot
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Credit note amount must be positive: {self.amount}")
        if self.original_invoice_amount and self.amount > self.original_invoice_amount:
            raise ValueError(
                f"Credit note amount {self.amount} exceeds invoice amount {self.original_invoice_amount}"
            )
        if self.tax_amount < 0:
            raise ValueError(f"Tax amount cannot be negative: {self.tax_amount}")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "credit_note_id": str(self.credit_note_id),
            "credit_note_number": self.credit_note_number,
            "status": self.status.value,
            "amount": str(self.amount),
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
                "credit_note_id": str(self.credit_note_id),
                "details": details,
            }
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> CreditNoteEntity:
        self._record_audit("CREATE", created_by, {"credit_note_number": self.credit_note_number})
        return self

    def update(self, updated_by: str, **kwargs) -> CreditNoteEntity:
        if not self.status.can_edit():
            raise ValueError(f"Cannot update credit note in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("credit_note_id", "created_at", "created_by", "version"):
                data[key] = value
        new_credit_note = CreditNoteEntity(
            credit_note_id=self.credit_note_id,
            credit_note_number=data.get("credit_note_number", self.credit_note_number),
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            issue_date=data.get("issue_date", self.issue_date),
            amount=Decimal(data.get("amount", self.amount)),
            currency=data.get("currency", self.currency),
            reason=CreditNoteReason(data.get("reason", self.reason.value)),
            status=self.status,
            description=data.get("description", self.description),
            tax_amount=Decimal(data.get("tax_amount", self.tax_amount)),
            tax_rate=Decimal(data.get("tax_rate", self.tax_rate)),
            original_invoice_amount=Decimal(data["original_invoice_amount"])
            if data.get("original_invoice_amount")
            else self.original_invoice_amount,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            created_by=updated_by,
            version=self.version + 1,
        )
        new_credit_note._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_credit_note

    def delete(self, deleted_by: str, reason: str | None = None) -> CreditNoteEntity:
        if self.status == CreditNoteStatus.CANCELLED:
            return self
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.CANCELLED
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_credit_note

    def restore(self, restored_by: str) -> CreditNoteEntity:
        if self.status != CreditNoteStatus.CANCELLED:
            raise ValueError(f"Cannot restore credit note in status {self.status.value}")
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.DRAFT
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("RESTORE", restored_by, {})
        return new_credit_note

    def activate(self, activated_by: str) -> CreditNoteEntity:
        if self.status == CreditNoteStatus.ISSUED:
            return self
        if self.status != CreditNoteStatus.DRAFT:
            raise ValueError(f"Cannot activate credit note in status {self.status.value}")
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.ISSUED
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("ACTIVATE", activated_by, {})
        return new_credit_note

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> CreditNoteEntity:
        if self.status == CreditNoteStatus.DRAFT:
            return self
        if self.status != CreditNoteStatus.ISSUED:
            raise ValueError(f"Cannot deactivate credit note in status {self.status.value}")
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.DRAFT
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_credit_note

    def lock(self, locked_by: str, reason: str) -> CreditNoteEntity:
        new_credit_note = self._copy()
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("LOCK", locked_by, {"reason": reason})
        return new_credit_note

    def unlock(self, unlocked_by: str) -> CreditNoteEntity:
        new_credit_note = self._copy()
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("UNLOCK", unlocked_by, {})
        return new_credit_note

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "credit_note_id": str(self.credit_note_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "credit_note_id": str(self.credit_note_id),
            "credit_note_number": self.credit_note_number,
            "invoice_id": str(self.invoice_id),
            "invoice_number": self.invoice_number,
            "customer_id": str(self.customer_id),
            "customer_name": self.customer_name,
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
    def from_dict(cls, data: dict[str, Any]) -> CreditNoteEntity:
        status = CreditNoteStatus(data["status"])
        reason = CreditNoteReason(data["reason"])
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            credit_note_id=UUID(data["credit_note_id"]),
            credit_note_number=data["credit_note_number"],
            invoice_id=UUID(data["invoice_id"]),
            invoice_number=data["invoice_number"],
            customer_id=UUID(data["customer_id"]),
            customer_name=data["customer_name"],
            issue_date=datetime.fromisoformat(data["issue_date"]),
            amount=Decimal(data["amount"]),
            currency=data["currency"],
            reason=reason,
            status=status,
            description=data.get("description", ""),
            tax_amount=Decimal(data.get("tax_amount", "0")),
            tax_rate=Decimal(data.get("tax_rate", "11")),
            original_invoice_amount=Decimal(data["original_invoice_amount"])
            if data.get("original_invoice_amount")
            else None,
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> CreditNoteEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = CreditNoteEntity(
            credit_note_id=new_id,
            credit_note_number=f"{self.credit_note_number}_COPY",
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            issue_date=now,
            amount=self.amount,
            currency=self.currency,
            reason=self.reason,
            status=CreditNoteStatus.DRAFT,
            description=f"Cloned from {self.credit_note_number}",
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            original_invoice_amount=self.original_invoice_amount,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.credit_note_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "credit_note_id": str(self.credit_note_id),
            "credit_note_number": self.credit_note_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> CreditNoteEntity:
        new_credit_note = self._copy()
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("TOUCH", touched_by, {})
        return new_credit_note

    # ==================== BUSINESS METHODS ====================
    def apply(self, applied_by: str) -> CreditNoteEntity:
        if not self.status.can_apply():
            raise ValueError(f"Cannot apply credit note in status {self.status.value}")
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.APPLIED
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("APPLY", applied_by, {})
        return new_credit_note

    def cancel(self, cancelled_by: str, reason: str) -> CreditNoteEntity:
        if not self.status.can_cancel():
            raise ValueError(f"Cannot cancel credit note in status {self.status.value}")
        new_credit_note = self._copy()
        new_credit_note.status = CreditNoteStatus.CANCELLED
        new_credit_note.description = f"{self.description}\nCancelled: {reason}"
        new_credit_note.updated_at = datetime.now(UTC)
        new_credit_note.version = self.version + 1
        new_credit_note._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_credit_note

    def is_applied(self) -> bool:
        return self.status == CreditNoteStatus.APPLIED

    def is_cancelled(self) -> bool:
        return self.status == CreditNoteStatus.CANCELLED

    def is_draft(self) -> bool:
        return self.status == CreditNoteStatus.DRAFT

    def to_money(self) -> Money:
        return Money(self.amount, self.currency)

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> CreditNoteEntity:
        return CreditNoteEntity(
            credit_note_id=self.credit_note_id,
            credit_note_number=self.credit_note_number,
            invoice_id=self.invoice_id,
            invoice_number=self.invoice_number,
            customer_id=self.customer_id,
            customer_name=self.customer_name,
            issue_date=self.issue_date,
            amount=self.amount,
            currency=self.currency,
            reason=self.reason,
            status=self.status,
            description=self.description,
            tax_amount=self.tax_amount,
            tax_rate=self.tax_rate,
            original_invoice_amount=self.original_invoice_amount,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# === ALIAS UNTUK KOMPATIBILITAS ===
ARCreditNote = CreditNoteEntity
ARCreditNoteStatus = CreditNoteStatus
ARCreditNoteReason = CreditNoteReason


# === 3. CREDIT NOTE REPOSITORY PROTOCOL ===
class CreditNoteRepository:
    async def get_by_id(
        self, credit_note_id: UUID, legal_entity_id: UUID
    ) -> CreditNoteEntity | None:
        raise NotImplementedError

    async def get_by_invoice(
        self, invoice_id: UUID, legal_entity_id: UUID
    ) -> list[CreditNoteEntity]:
        raise NotImplementedError

    async def get_by_customer(
        self, customer_id: UUID, legal_entity_id: UUID
    ) -> list[CreditNoteEntity]:
        raise NotImplementedError

    async def save(self, credit_note: CreditNoteEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, credit_note_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    # Repository standard methods
    async def add(self, credit_note: CreditNoteEntity, legal_entity_id: UUID) -> None:
        await self.save(credit_note, legal_entity_id)

    async def update(self, credit_note: CreditNoteEntity, legal_entity_id: UUID) -> None:
        await self.save(credit_note, legal_entity_id)

    async def exists(self, credit_note_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CreditNoteEntity]:
        raise NotImplementedError

    async def search(
        self, legal_entity_id: UUID, criteria: dict[str, Any]
    ) -> list[CreditNoteEntity]:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[CreditNoteEntity]:
        raise NotImplementedError

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[CreditNoteEntity], int]:
        raise NotImplementedError


# === 4. EXPORTS ===
__all__ = [
    "ARCreditNote",
    "ARCreditNoteReason",
    "ARCreditNoteStatus",
    "CreditNoteEntity",
    "CreditNoteReason",
    "CreditNoteRepository",
    "CreditNoteStatus",
]
