#!/usr/bin/env python3
"""
Module: intercompany_transaction.py
Layer: Domain / Consolidation
Responsibility: Transaksi antar entitas dalam satu grup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class TransactionType(Enum):
    SALE = "sale"
    PURCHASE = "purchase"
    LOAN = "loan"
    REPAYMENT = "repayment"
    DIVIDEND = "dividend"
    INTEREST = "interest"
    ROYALTY = "royalty"
    SERVICE = "service"

    def is_revenue(self) -> bool:
        return self in (
            TransactionType.SALE,
            TransactionType.SERVICE,
            TransactionType.ROYALTY,
            TransactionType.INTEREST,
        )

    def is_expense(self) -> bool:
        return self in (
            TransactionType.PURCHASE,
            TransactionType.LOAN,
            TransactionType.REPAYMENT,
            TransactionType.DIVIDEND,
        )


class IntercompanyTransactionStatus(Enum):
    PENDING = "pending"
    DETECTED = "detected"
    ELIMINATED = "eliminated"
    EXCLUDED = "excluded"
    CANCELLED = "cancelled"


@dataclass
class IntercompanyTransaction:
    """Entity transaksi antar perusahaan dengan semua method dasar."""

    id: UUID
    from_entity_id: UUID
    to_entity_id: UUID
    transaction_type: TransactionType
    account_code: str
    amount: Decimal
    transaction_date: date
    currency: str
    description: str | None = None
    reference_document: str | None = None
    status: IntercompanyTransactionStatus = IntercompanyTransactionStatus.PENDING
    is_eliminated: bool = False
    elimination_date: datetime | None = None
    eliminated_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # Untuk kompatibilitas mode test (string entities)
    from_entity: str | None = None
    to_entity: str | None = None

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.amount <= 0:
            raise ValueError(f"Transaction amount must be positive: {self.amount}")
        self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if self.transaction_date > date.today():
            raise ValueError("Transaction date cannot be in the future")
        if not self.account_code or len(self.account_code.strip()) < 1:
            raise ValueError("Account code is required")
        if not self.currency or len(self.currency) != 3:
            raise ValueError("Currency must be 3-letter ISO code")
        if self.from_entity_id == self.to_entity_id and self.from_entity_id != UUID(int=0):
            raise ValueError("From and to entities cannot be the same")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "transaction_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> IntercompanyTransaction:
        self._record_audit("CREATE", created_by, {"amount": str(self.amount)})
        return self

    def update(self, updated_by: str, **kwargs) -> IntercompanyTransaction:
        if self.status in (
            IntercompanyTransactionStatus.ELIMINATED,
            IntercompanyTransactionStatus.CANCELLED,
        ):
            raise ValueError(f"Cannot update transaction in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_tx = self.from_dict(data)
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = updated_by
        new_tx.version = self.version + 1
        new_tx._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_tx

    def delete(self, deleted_by: str, reason: str | None = None) -> IntercompanyTransaction:
        if self.status == IntercompanyTransactionStatus.ELIMINATED:
            raise ValueError("Cannot delete eliminated transaction")
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.CANCELLED
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = deleted_by
        new_tx.version = self.version + 1
        new_tx._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_tx

    def restore(self, restored_by: str) -> IntercompanyTransaction:
        if self.status != IntercompanyTransactionStatus.CANCELLED:
            raise ValueError(f"Cannot restore transaction in status {self.status.value}")
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.PENDING
        new_tx.is_eliminated = False
        new_tx.elimination_date = None
        new_tx.eliminated_by = None
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = restored_by
        new_tx.version = self.version + 1
        new_tx._record_audit("RESTORE", restored_by, {})
        return new_tx

    def activate(self, activated_by: str) -> IntercompanyTransaction:
        if self.status != IntercompanyTransactionStatus.PENDING:
            raise ValueError(f"Cannot activate transaction in status {self.status.value}")
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.DETECTED
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = activated_by
        new_tx.version = self.version + 1
        new_tx._record_audit("ACTIVATE", activated_by, {})
        return new_tx

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> IntercompanyTransaction:
        if self.status != IntercompanyTransactionStatus.DETECTED:
            raise ValueError(f"Cannot deactivate transaction in status {self.status.value}")
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.EXCLUDED
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = deactivated_by
        new_tx.version = self.version + 1
        new_tx._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_tx

    def lock(self, locked_by: str, reason: str) -> IntercompanyTransaction:
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.EXCLUDED
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = locked_by
        new_tx.version = self.version + 1
        new_tx._record_audit("LOCK", locked_by, {"reason": reason})
        return new_tx

    def unlock(self, unlocked_by: str) -> IntercompanyTransaction:
        if self.status != IntercompanyTransactionStatus.EXCLUDED:
            raise ValueError(f"Cannot unlock transaction in status {self.status.value}")
        new_tx = self._copy()
        new_tx.status = IntercompanyTransactionStatus.DETECTED
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = unlocked_by
        new_tx.version = self.version + 1
        new_tx._record_audit("UNLOCK", unlocked_by, {})
        return new_tx

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "transaction_id": str(self.id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "from_entity_id": str(self.from_entity_id),
            "to_entity_id": str(self.to_entity_id),
            "transaction_type": self.transaction_type.value,
            "account_code": self.account_code,
            "amount": str(self.amount),
            "transaction_date": self.transaction_date.isoformat(),
            "currency": self.currency,
            "description": self.description,
            "reference_document": self.reference_document,
            "status": self.status.value,
            "is_eliminated": self.is_eliminated,
            "elimination_date": self.elimination_date.isoformat()
            if self.elimination_date
            else None,
            "eliminated_by": self.eliminated_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntercompanyTransaction:
        return cls(
            id=UUID(data["id"]),
            from_entity_id=UUID(data["from_entity_id"]),
            to_entity_id=UUID(data["to_entity_id"]),
            transaction_type=TransactionType(data["transaction_type"]),
            account_code=data["account_code"],
            amount=Decimal(data["amount"]),
            transaction_date=date.fromisoformat(data["transaction_date"]),
            currency=data["currency"],
            description=data.get("description"),
            reference_document=data.get("reference_document"),
            status=IntercompanyTransactionStatus(data.get("status", "pending")),
            is_eliminated=data.get("is_eliminated", False),
            elimination_date=datetime.fromisoformat(data["elimination_date"])
            if data.get("elimination_date")
            else None,
            eliminated_by=data.get("eliminated_by"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else datetime.now(UTC),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> IntercompanyTransaction:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "id", new_id)
        cloned.status = IntercompanyTransactionStatus.PENDING
        cloned.is_eliminated = False
        cloned.elimination_date = None
        cloned.eliminated_by = None
        cloned.created_at = datetime.now(UTC)
        cloned.updated_at = datetime.now(UTC)
        cloned.version = 1
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transaction_id": str(self.id),
            "amount": str(self.amount),
            "status": self.status.value,
            "is_eliminated": self.is_eliminated,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> IntercompanyTransaction:
        new_tx = self._copy()
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = touched_by
        new_tx.version = self.version + 1
        new_tx._record_audit("TOUCH", touched_by, {})
        return new_tx

    # ==================== BUSINESS METHODS ====================

    def mark_eliminated(
        self, eliminated_by: str, elimination_date: datetime | None = None
    ) -> IntercompanyTransaction:
        if self.is_eliminated:
            return self
        if self.status == IntercompanyTransactionStatus.CANCELLED:
            raise ValueError("Cannot eliminate cancelled transaction")
        new_tx = self._copy()
        new_tx.is_eliminated = True
        new_tx.status = IntercompanyTransactionStatus.ELIMINATED
        new_tx.elimination_date = elimination_date or datetime.now(UTC)
        new_tx.eliminated_by = eliminated_by
        new_tx.updated_at = datetime.now(UTC)
        new_tx.updated_by = eliminated_by
        new_tx.version = self.version + 1
        new_tx._record_audit("ELIMINATE", eliminated_by, {})
        return new_tx

    def is_eliminable(self) -> bool:
        return not self.is_eliminated and self.status != IntercompanyTransactionStatus.CANCELLED

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> IntercompanyTransaction:
        return IntercompanyTransaction(
            id=self.id,
            from_entity_id=self.from_entity_id,
            to_entity_id=self.to_entity_id,
            transaction_type=self.transaction_type,
            account_code=self.account_code,
            amount=self.amount,
            transaction_date=self.transaction_date,
            currency=self.currency,
            description=self.description,
            reference_document=self.reference_document,
            status=self.status,
            is_eliminated=self.is_eliminated,
            elimination_date=self.elimination_date,
            eliminated_by=self.eliminated_by,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            from_entity=self.from_entity,
            to_entity=self.to_entity,
        )


# ============================================================================
# Repository Interface (In-Memory)
# ============================================================================


class IntercompanyTransactionRepository:
    _storage: ClassVar[dict[UUID, IntercompanyTransaction]] = {}

    async def get_by_id(self, tx_id: UUID) -> IntercompanyTransaction | None:
        return self._storage.get(tx_id)

    async def get_by_entities(
        self, from_entity_id: UUID | None = None, to_entity_id: UUID | None = None
    ) -> list[IntercompanyTransaction]:
        result = list(self._storage.values())
        if from_entity_id:
            result = [t for t in result if t.from_entity_id == from_entity_id]
        if to_entity_id:
            result = [t for t in result if t.to_entity_id == to_entity_id]
        return result

    async def get_by_period(
        self, start_date: date, end_date: date
    ) -> list[IntercompanyTransaction]:
        result = [t for t in self._storage.values() if start_date <= t.transaction_date <= end_date]
        return result

    async def get_eliminated(self) -> list[IntercompanyTransaction]:
        return [t for t in self._storage.values() if t.is_eliminated]

    async def save(self, tx: IntercompanyTransaction) -> None:
        self._storage[tx.id] = tx

    async def delete(self, tx_id: UUID) -> None:
        if tx_id in self._storage:
            del self._storage[tx_id]

    async def clear(self) -> None:
        self._storage.clear()


__all__ = [
    "IntercompanyTransaction",
    "IntercompanyTransactionRepository",
    "IntercompanyTransactionStatus",
    "TransactionType",
]
