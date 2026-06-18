#!/usr/bin/env python3
"""
Module: simplified_journal_entity.py
Layer: Domain / UMKM Simplified
Responsibility: Jurnal entri sederhana untuk UMKM.

Metode yang ditambahkan:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Business: delete, update_amount, update_description (sudah ada), is_income, is_expense.
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


# === 1. ENUMS (ditambahkan method display_name) ===
class TransactionType(Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"

    def display_name(self) -> str:
        return {"income": "Pendapatan", "expense": "Pengeluaran", "transfer": "Transfer"}.get(
            self.value, self.value
        )


class PaymentMethod(Enum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    QRIS = "qris"
    E_WALLET = "e_wallet"
    CREDIT = "credit"

    def display_name(self) -> str:
        return {
            "cash": "Tunai",
            "bank_transfer": "Transfer Bank",
            "qris": "QRIS",
            "e_wallet": "Dompet Digital",
            "credit": "Kredit",
        }.get(self.value, self.value)


class JournalStatus(Enum):
    ACTIVE = "active"
    DELETED = "deleted"

    def can_edit(self) -> bool:
        return self == JournalStatus.ACTIVE


# === 2. SIMPLIFIED JOURNAL ENTITY ===
@dataclass
class SimplifiedJournalEntity:
    journal_id: UUID
    journal_number: str
    transaction_type: TransactionType
    amount: Decimal
    description: str
    transaction_date: datetime
    category: str
    payment_method: PaymentMethod
    status: JournalStatus
    reference_number: str | None = None
    customer_name: str | None = None
    supplier_name: str | None = None
    notes: str = ""
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

    def _validate(self):
        if not self.journal_number or len(self.journal_number.strip()) < 3:
            raise ValueError("Journal number must be at least 3 characters")
        if self.amount <= 0:
            raise ValueError(f"Amount must be positive: {self.amount}")
        if not self.category:
            raise ValueError("Category is required")
        if self.transaction_date.tzinfo is None:
            object.__setattr__(self, "transaction_date", self.transaction_date.replace(tzinfo=UTC))
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self.version,
                "journal_id": str(self.journal_id),
                "journal_number": self.journal_number,
                "status": self.status.value,
                "amount": str(self.amount),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "journal_id": str(self.journal_id),
                "details": details,
            }
        )

    # ==================== BUSINESS METHODS (asli) ====================
    def is_income(self) -> bool:
        return self.transaction_type == TransactionType.INCOME

    def is_expense(self) -> bool:
        return self.transaction_type == TransactionType.EXPENSE

    def delete(self, deleted_by: str) -> SimplifiedJournalEntity:
        """Soft delete jurnal."""
        if self.status != JournalStatus.ACTIVE:
            raise ValueError(f"Cannot delete journal in status {self.status.value}")
        new = self._copy()
        new.status = JournalStatus.DELETED
        new.notes = f"{self.notes}\nDeleted by {deleted_by}"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("DELETE", deleted_by, {})
        return new

    def update_amount(self, new_amount: Decimal, updated_by: str) -> SimplifiedJournalEntity:
        if new_amount <= 0:
            raise ValueError(f"Amount must be positive: {new_amount}")
        if not self.status.can_edit():
            raise ValueError(f"Cannot update amount in status {self.status.value}")
        new = self._copy()
        new.amount = new_amount
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit(
            "UPDATE_AMOUNT",
            updated_by,
            {"old_amount": str(self.amount), "new_amount": str(new_amount)},
        )
        return new

    def update_description(self, new_description: str, updated_by: str) -> SimplifiedJournalEntity:
        if not self.status.can_edit():
            raise ValueError(f"Cannot update description in status {self.status.value}")
        new = self._copy()
        new.description = new_description
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UPDATE_DESCRIPTION", updated_by, {"new_description": new_description})
        return new

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> SimplifiedJournalEntity:
        self._record_audit("CREATE", created_by, {"journal_number": self.journal_number})
        return self

    def update(self, updated_by: str, **kwargs) -> SimplifiedJournalEntity:
        if not self.status.can_edit():
            raise ValueError(f"Cannot update journal in status {self.status.value}")
        new = self._copy()
        for key, value in kwargs.items():
            if key not in (
                "journal_id",
                "created_at",
                "created_by",
                "version",
                "_audit_trail",
                "_snapshots",
            ):
                setattr(new, key, value)
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new

    def restore(self, restored_by: str) -> SimplifiedJournalEntity:
        if self.status != JournalStatus.DELETED:
            raise ValueError(f"Cannot restore journal in status {self.status.value}")
        new = self._copy()
        new.status = JournalStatus.ACTIVE
        new.notes = f"{self.notes}\nRestored by {restored_by}"
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("RESTORE", restored_by, {})
        return new

    def activate(self, activated_by: str) -> SimplifiedJournalEntity:
        if self.status == JournalStatus.ACTIVE:
            return self
        if self.status != JournalStatus.DELETED:
            raise ValueError(f"Cannot activate journal in status {self.status.value}")
        return self.restore(activated_by)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> SimplifiedJournalEntity:
        if self.status != JournalStatus.ACTIVE:
            return self
        return self.delete(deactivated_by)

    def lock(self, locked_by: str, reason: str) -> SimplifiedJournalEntity:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("LOCK", locked_by, {"reason": reason})
        return new

    def unlock(self, unlocked_by: str) -> SimplifiedJournalEntity:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("UNLOCK", unlocked_by, {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "journal_id": str(self.journal_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "transaction_type": self.transaction_type.value,
            "amount": str(self.amount),
            "description": self.description,
            "transaction_date": self.transaction_date.isoformat(),
            "category": self.category,
            "payment_method": self.payment_method.value,
            "status": self.status.value,
            "reference_number": self.reference_number,
            "customer_name": self.customer_name,
            "supplier_name": self.supplier_name,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimplifiedJournalEntity:
        instance = cls(
            journal_id=UUID(data["journal_id"]),
            journal_number=data["journal_number"],
            transaction_type=TransactionType(data["transaction_type"]),
            amount=Decimal(data["amount"]),
            description=data["description"],
            transaction_date=datetime.fromisoformat(data["transaction_date"]),
            category=data["category"],
            payment_method=PaymentMethod(data["payment_method"]),
            status=JournalStatus(data["status"]),
            reference_number=data.get("reference_number"),
            customer_name=data.get("customer_name"),
            supplier_name=data.get("supplier_name"),
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )
        return instance

    def clone(self) -> SimplifiedJournalEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = self._copy()
        cloned.journal_id = new_id
        cloned.journal_number = f"{self.journal_number}_COPY"
        cloned.status = JournalStatus.ACTIVE
        cloned.created_at = now
        cloned.updated_at = now
        cloned.version = 1
        cloned._audit_trail = []
        cloned._snapshots = []
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.journal_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "journal_id": str(self.journal_id),
            "journal_number": self.journal_number,
            "status": self.status.value,
            "amount": str(self.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> SimplifiedJournalEntity:
        new = self._copy()
        new.updated_at = datetime.now(UTC)
        new.version += 1
        new._record_audit("TOUCH", touched_by, {})
        return new

    # ==================== PRIVATE HELPERS ====================
    def _copy(self) -> SimplifiedJournalEntity:
        return SimplifiedJournalEntity(
            journal_id=self.journal_id,
            journal_number=self.journal_number,
            transaction_type=self.transaction_type,
            amount=self.amount,
            description=self.description,
            transaction_date=self.transaction_date,
            category=self.category,
            payment_method=self.payment_method,
            status=self.status,
            reference_number=self.reference_number,
            customer_name=self.customer_name,
            supplier_name=self.supplier_name,
            notes=self.notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
        )


# === 3. ALIAS ===
SimplifiedJournal = SimplifiedJournalEntity


# === 4. REPOSITORY PROTOCOL (dengan standard methods) ===
class SimplifiedJournalRepository:
    async def get_by_id(
        self, journal_id: UUID, legal_entity_id: UUID
    ) -> SimplifiedJournalEntity | None:
        raise NotImplementedError

    async def get_by_number(
        self, journal_number: str, legal_entity_id: UUID
    ) -> SimplifiedJournalEntity | None:
        raise NotImplementedError

    async def get_by_category(
        self,
        category: str,
        legal_entity_id: UUID,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[SimplifiedJournalEntity]:
        raise NotImplementedError

    async def save(self, journal: SimplifiedJournalEntity, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    async def delete(self, journal_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError

    # Standard repository methods
    async def add(self, journal: SimplifiedJournalEntity, legal_entity_id: UUID) -> None:
        await self.save(journal, legal_entity_id)

    async def update(self, journal: SimplifiedJournalEntity, legal_entity_id: UUID) -> None:
        await self.save(journal, legal_entity_id)

    async def exists(self, journal_id: UUID, legal_entity_id: UUID) -> bool:
        raise NotImplementedError

    async def get_all(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SimplifiedJournalEntity]:
        raise NotImplementedError

    async def search(
        self, legal_entity_id: UUID, criteria: dict[str, Any]
    ) -> list[SimplifiedJournalEntity]:
        raise NotImplementedError

    async def count(self, legal_entity_id: UUID) -> int:
        raise NotImplementedError

    async def list(
        self, legal_entity_id: UUID, limit: int = 100, offset: int = 0
    ) -> list[SimplifiedJournalEntity]:
        raise NotImplementedError

    async def paginate(
        self, legal_entity_id: UUID, page: int = 1, per_page: int = 20
    ) -> tuple[list[SimplifiedJournalEntity], int]:
        raise NotImplementedError


# === 5. EXPORTS ===
__all__ = [
    "JournalStatus",
    "PaymentMethod",
    "SimplifiedJournal",
    "SimplifiedJournalEntity",
    "SimplifiedJournalRepository",
    "TransactionType",
]
