#!/usr/bin/env python3
"""
Module: forex_transaction_entity.py
Layer: Domain / Forex
Responsibility: Entity untuk transaksi valuta asing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.forex.exchange_rate_vo import ExchangeRate

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class ForexTransactionType(Enum):
    REVALUATION = "revaluation"
    SPOT = "spot"
    FORWARD = "forward"
    SWAP = "swap"
    OPTION = "option"
    SETTLEMENT = "settlement"

    def display_name(self) -> str:
        names = {
            ForexTransactionType.REVALUATION: "Revaluasi",
            ForexTransactionType.SPOT: "Spot",
            ForexTransactionType.FORWARD: "Forward",
            ForexTransactionType.SWAP: "Swap",
            ForexTransactionType.OPTION: "Opsi",
            ForexTransactionType.SETTLEMENT: "Penyelesaian",
        }
        return names.get(self, self.value)


class ForexTransactionStatus(Enum):
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    SETTLED = "settled"
    CANCELLED = "cancelled"

    def can_edit(self) -> bool:
        return self == ForexTransactionStatus.DRAFT

    def can_settle(self) -> bool:
        return self == ForexTransactionStatus.CONFIRMED

    def display_name(self) -> str:
        names = {
            ForexTransactionStatus.DRAFT: "Draft",
            ForexTransactionStatus.CONFIRMED: "Dikonfirmasi",
            ForexTransactionStatus.SETTLED: "Diselesaikan",
            ForexTransactionStatus.CANCELLED: "Dibatalkan",
        }
        return names.get(self, self.value)


# ============================================================================
# Custom Exceptions
# ============================================================================


class ForexTransactionError(ValueError):
    pass


# ============================================================================
# Entity: ForexTransaction
# ============================================================================


@dataclass
class ForexTransaction:
    transaction_id: UUID
    legal_entity_id: UUID
    transaction_number: str
    transaction_type: ForexTransactionType
    currency_from: str
    currency_to: str
    amount_from: Decimal
    amount_to: Decimal
    rate: ExchangeRate
    transaction_date: datetime
    settlement_date: datetime | None = None
    status: ForexTransactionStatus = ForexTransactionStatus.DRAFT
    reference: str | None = None
    description: str = ""
    counterparty_id: UUID | None = None
    counterparty_name: str | None = None
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None
    settled_by: str | None = None
    settled_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_reason: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not self.transaction_number or len(self.transaction_number.strip()) < 3:
            raise ForexTransactionError("Transaction number must be at least 3 characters")
        if self.amount_from <= 0:
            raise ForexTransactionError(f"Amount from must be positive: {self.amount_from}")
        if self.amount_to <= 0:
            raise ForexTransactionError(f"Amount to must be positive: {self.amount_to}")
        if self.transaction_date.tzinfo is None:
            object.__setattr__(self, "transaction_date", self.transaction_date.replace(tzinfo=UTC))
        if self.settlement_date and self.settlement_date.tzinfo is None:
            object.__setattr__(self, "settlement_date", self.settlement_date.replace(tzinfo=UTC))
        if self.settlement_date and self.settlement_date < self.transaction_date:
            raise ForexTransactionError(
                f"Settlement date {self.settlement_date} cannot be before transaction date"
            )
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.version < 1:
            raise ForexTransactionError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "transaction_id": str(self.transaction_id),
            "number": self.transaction_number,
            "amount_from": str(self.amount_from),
            "amount_to": str(self.amount_to),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "transaction_id": str(self.transaction_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> ForexTransaction:
        self._record_audit("CREATE", created_by, {"number": self.transaction_number})
        return self

    def update(self, updated_by: str, **kwargs) -> ForexTransaction:
        if not self.status.can_edit():
            raise ForexTransactionError(f"Cannot update transaction in status {self.status.value}")
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("transaction_id", "created_at", "created_by", "version"):
                data[key] = value
        new_tx = self.from_dict(data)
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_tx

    def delete(self, deleted_by: str, reason: str | None = None) -> ForexTransaction:
        if self.status == ForexTransactionStatus.SETTLED:
            raise ForexTransactionError("Cannot delete settled transaction")
        new_tx = self._copy()
        new_tx.status = ForexTransactionStatus.CANCELLED
        new_tx.cancelled_by = deleted_by
        new_tx.cancelled_at = datetime.now(UTC)
        new_tx.cancel_reason = reason or "Deleted by user"
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_tx

    def restore(self, restored_by: str) -> ForexTransaction:
        if self.status != ForexTransactionStatus.CANCELLED:
            raise ForexTransactionError(f"Cannot restore transaction in status {self.status.value}")
        new_tx = self._copy()
        new_tx.status = ForexTransactionStatus.DRAFT
        new_tx.cancelled_by = None
        new_tx.cancelled_at = None
        new_tx.cancel_reason = ""
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("RESTORE", restored_by, {})
        return new_tx

    def activate(self, activated_by: str) -> ForexTransaction:
        if self.status != ForexTransactionStatus.DRAFT:
            raise ForexTransactionError(
                f"Cannot activate transaction in status {self.status.value}"
            )
        return self.confirm(activated_by)

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ForexTransaction:
        if self.status != ForexTransactionStatus.DRAFT:
            raise ForexTransactionError(
                f"Cannot deactivate transaction in status {self.status.value}"
            )
        return self.cancel(deactivated_by, reason or "Deactivated by user")

    def lock(self, locked_by: str, reason: str) -> ForexTransaction:
        new_tx = self._copy()
        new_tx.metadata["locked_by"] = locked_by
        new_tx.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_tx.metadata["lock_reason"] = reason
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("LOCK", locked_by, {"reason": reason})
        return new_tx

    def unlock(self, unlocked_by: str) -> ForexTransaction:
        new_tx = self._copy()
        new_tx.metadata.pop("locked_by", None)
        new_tx.metadata.pop("locked_at", None)
        new_tx.metadata.pop("lock_reason", None)
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("UNLOCK", unlocked_by, {})
        return new_tx

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ForexTransactionError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "transaction_id": str(self.transaction_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": str(self.transaction_id),
            "legal_entity_id": str(self.legal_entity_id),
            "transaction_number": self.transaction_number,
            "transaction_type": self.transaction_type.value,
            "currency_from": self.currency_from,
            "currency_to": self.currency_to,
            "amount_from": str(self.amount_from),
            "amount_to": str(self.amount_to),
            "rate": self.rate.to_dict(),
            "transaction_date": self.transaction_date.isoformat(),
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "status": self.status.value,
            "reference": self.reference,
            "description": self.description,
            "counterparty_id": str(self.counterparty_id) if self.counterparty_id else None,
            "counterparty_name": self.counterparty_name,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "settled_by": self.settled_by,
            "settled_at": self.settled_at.isoformat() if self.settled_at else None,
            "cancelled_by": self.cancelled_by,
            "cancelled_at": self.cancelled_at.isoformat() if self.cancelled_at else None,
            "cancel_reason": self.cancel_reason,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForexTransaction:
        transaction_type = ForexTransactionType(data["transaction_type"])
        status = ForexTransactionStatus(data["status"])
        transaction_date = datetime.fromisoformat(data["transaction_date"])
        settlement_date = (
            datetime.fromisoformat(data["settlement_date"]) if data.get("settlement_date") else None
        )
        confirmed_at = (
            datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None
        )
        settled_at = datetime.fromisoformat(data["settled_at"]) if data.get("settled_at") else None
        cancelled_at = (
            datetime.fromisoformat(data["cancelled_at"]) if data.get("cancelled_at") else None
        )
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        rate = ExchangeRate.from_dict(data["rate"])
        return cls(
            transaction_id=UUID(data["transaction_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            transaction_number=data["transaction_number"],
            transaction_type=transaction_type,
            currency_from=data["currency_from"],
            currency_to=data["currency_to"],
            amount_from=Decimal(data["amount_from"]),
            amount_to=Decimal(data["amount_to"]),
            rate=rate,
            transaction_date=transaction_date,
            settlement_date=settlement_date,
            status=status,
            reference=data.get("reference"),
            description=data.get("description", ""),
            counterparty_id=UUID(data["counterparty_id"]) if data.get("counterparty_id") else None,
            counterparty_name=data.get("counterparty_name"),
            confirmed_by=data.get("confirmed_by"),
            confirmed_at=confirmed_at,
            settled_by=data.get("settled_by"),
            settled_at=settled_at,
            cancelled_by=data.get("cancelled_by"),
            cancelled_at=cancelled_at,
            cancel_reason=data.get("cancel_reason", ""),
            created_at=created_at,
            updated_at=updated_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> ForexTransaction:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = ForexTransaction(
            transaction_id=new_id,
            legal_entity_id=self.legal_entity_id,
            transaction_number=f"{self.transaction_number}_COPY",
            transaction_type=self.transaction_type,
            currency_from=self.currency_from,
            currency_to=self.currency_to,
            amount_from=self.amount_from,
            amount_to=self.amount_to,
            rate=self.rate,
            transaction_date=self.transaction_date,
            settlement_date=self.settlement_date,
            status=ForexTransactionStatus.DRAFT,
            reference=self.reference,
            description=f"Cloned from {self.transaction_number}",
            counterparty_id=self.counterparty_id,
            counterparty_name=self.counterparty_name,
            created_at=now,
            updated_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.transaction_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "transaction_id": str(self.transaction_id),
            "number": self.transaction_number,
            "amount_from": str(self.amount_from),
            "amount_to": str(self.amount_to),
            "status": self.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ForexTransaction:
        new_tx = self._copy()
        new_tx.updated_at = datetime.now(UTC)
        new_tx.version = self.version + 1
        new_tx._record_audit("TOUCH", touched_by, {})
        return new_tx

    # ==================== PROPERTIES ====================

    @property
    def is_draft(self) -> bool:
        return self.status == ForexTransactionStatus.DRAFT

    @property
    def is_confirmed(self) -> bool:
        return self.status == ForexTransactionStatus.CONFIRMED

    @property
    def is_settled(self) -> bool:
        return self.status == ForexTransactionStatus.SETTLED

    @property
    def is_cancelled(self) -> bool:
        return self.status == ForexTransactionStatus.CANCELLED

    @property
    def can_edit(self) -> bool:
        return self.status.can_edit()

    @property
    def can_settle(self) -> bool:
        return self.status.can_settle()

    @property
    def exchange_rate_value(self) -> Decimal:
        return self.amount_to / self.amount_from

    # ==================== BUSINESS METHODS ====================

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        transaction_number: str,
        currency_from: str,
        currency_to: str,
        amount_from: Decimal,
        rate: ExchangeRate,
        transaction_date: datetime | None = None,
        settlement_date: datetime | None = None,
        transaction_type: ForexTransactionType = ForexTransactionType.SPOT,
        created_by: str = "system",
    ) -> ForexTransaction:
        if transaction_date is None:
            transaction_date = datetime.now(UTC)
        amount_to = amount_from * rate.rate
        return cls(
            transaction_id=uuid4(),
            legal_entity_id=legal_entity_id,
            transaction_number=transaction_number,
            transaction_type=transaction_type,
            currency_from=currency_from,
            currency_to=currency_to,
            amount_from=amount_from,
            amount_to=amount_to,
            rate=rate,
            transaction_date=transaction_date,
            settlement_date=settlement_date,
            created_by=created_by,
        )

    def confirm(self, confirmed_by: str) -> ForexTransaction:
        if self.status != ForexTransactionStatus.DRAFT:
            raise ForexTransactionError(f"Cannot confirm transaction in status {self.status.value}")
        now = datetime.now(UTC)
        new_tx = self._copy()
        new_tx.status = ForexTransactionStatus.CONFIRMED
        new_tx.confirmed_by = confirmed_by
        new_tx.confirmed_at = now
        new_tx.updated_at = now
        new_tx.version = self.version + 1
        new_tx._record_audit("CONFIRM", confirmed_by, {})
        return new_tx

    def settle(self, settled_by: str) -> ForexTransaction:
        if not self.can_settle:
            raise ForexTransactionError(f"Cannot settle transaction in status {self.status.value}")
        now = datetime.now(UTC)
        new_tx = self._copy()
        new_tx.status = ForexTransactionStatus.SETTLED
        new_tx.settled_by = settled_by
        new_tx.settled_at = now
        new_tx.updated_at = now
        new_tx.version = self.version + 1
        new_tx._record_audit("SETTLE", settled_by, {})
        return new_tx

    def cancel(self, cancelled_by: str, reason: str) -> ForexTransaction:
        if self.status == ForexTransactionStatus.SETTLED:
            raise ForexTransactionError("Cannot cancel settled transaction")
        now = datetime.now(UTC)
        new_tx = self._copy()
        new_tx.status = ForexTransactionStatus.CANCELLED
        new_tx.cancelled_by = cancelled_by
        new_tx.cancelled_at = now
        new_tx.cancel_reason = reason
        new_tx.updated_at = now
        new_tx.version = self.version + 1
        new_tx._record_audit("CANCEL", cancelled_by, {"reason": reason})
        return new_tx

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> ForexTransaction:
        return ForexTransaction(
            transaction_id=self.transaction_id,
            legal_entity_id=self.legal_entity_id,
            transaction_number=self.transaction_number,
            transaction_type=self.transaction_type,
            currency_from=self.currency_from,
            currency_to=self.currency_to,
            amount_from=self.amount_from,
            amount_to=self.amount_to,
            rate=self.rate,
            transaction_date=self.transaction_date,
            settlement_date=self.settlement_date,
            status=self.status,
            reference=self.reference,
            description=self.description,
            counterparty_id=self.counterparty_id,
            counterparty_name=self.counterparty_name,
            confirmed_by=self.confirmed_by,
            confirmed_at=self.confirmed_at,
            settled_by=self.settled_by,
            settled_at=self.settled_at,
            cancelled_by=self.cancelled_by,
            cancelled_at=self.cancelled_at,
            cancel_reason=self.cancel_reason,
            created_at=self.created_at,
            updated_at=self.updated_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation
# ============================================================================


class ForexTransactionRepository:
    _storage: ClassVar[dict[UUID, dict[UUID, ForexTransaction]]] = {}

    @classmethod
    def _get_storage(cls, legal_entity_id: UUID) -> dict[UUID, ForexTransaction]:
        if legal_entity_id not in cls._storage:
            cls._storage[legal_entity_id] = {}
        return cls._storage[legal_entity_id]

    @classmethod
    async def get_by_id(
        cls, transaction_id: UUID, legal_entity_id: UUID
    ) -> ForexTransaction | None:
        storage = cls._get_storage(legal_entity_id)
        return storage.get(transaction_id)

    @classmethod
    async def get_by_number(
        cls, transaction_number: str, legal_entity_id: UUID
    ) -> ForexTransaction | None:
        storage = cls._get_storage(legal_entity_id)
        for tx in storage.values():
            if tx.transaction_number == transaction_number:
                return tx
        return None

    @classmethod
    async def get_by_status(
        cls, legal_entity_id: UUID, status: ForexTransactionStatus
    ) -> list[ForexTransaction]:
        storage = cls._get_storage(legal_entity_id)
        return [tx for tx in storage.values() if tx.status == status]

    @classmethod
    async def get_by_currency_pair(
        cls, legal_entity_id: UUID, currency_from: str, currency_to: str
    ) -> list[ForexTransaction]:
        storage = cls._get_storage(legal_entity_id)
        return [
            tx
            for tx in storage.values()
            if tx.currency_from == currency_from and tx.currency_to == currency_to
        ]

    @classmethod
    async def get_all(cls, legal_entity_id: UUID) -> list[ForexTransaction]:
        storage = cls._get_storage(legal_entity_id)
        return list(storage.values())

    @classmethod
    async def save(cls, transaction: ForexTransaction, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage[transaction.transaction_id] = transaction

    @classmethod
    async def delete(cls, transaction_id: UUID, legal_entity_id: UUID) -> None:
        storage = cls._get_storage(legal_entity_id)
        storage.pop(transaction_id, None)

    @classmethod
    async def clear(cls, legal_entity_id: UUID) -> None:
        if legal_entity_id in cls._storage:
            cls._storage[legal_entity_id] = {}


__all__ = [
    "ForexTransaction",
    "ForexTransactionError",
    "ForexTransactionRepository",
    "ForexTransactionStatus",
    "ForexTransactionType",
]
