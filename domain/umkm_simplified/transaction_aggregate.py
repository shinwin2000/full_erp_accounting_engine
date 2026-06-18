#!/usr/bin/env python3
"""
Module: transaction_aggregate.py
Layer: Domain / UMKM Simplified
Responsibility: Aggregate root untuk transaksi UMKM.

Metode entity dasar dan aggregate root lengkap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.umkm_simplified.domain_events import DomainEvent, TransactionCreatedEvent
from domain.umkm_simplified.simplified_journal_entity import (
    SimplifiedJournalEntity,
    TransactionType,
)

logger = logging.getLogger(__name__)


class UMKMStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


@dataclass
class UMKMTransactionAggregate:
    aggregate_id: UUID
    legal_entity_id: UUID
    business_name: str
    status: UMKMStatus
    journals: dict[UUID, SimplifiedJournalEntity] = field(default_factory=dict)
    cash_balance: Decimal = Decimal(0)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self):
        self._snapshots.append(
            {
                "version": self.version,
                "aggregate_id": str(self.aggregate_id),
                "business_name": self.business_name,
                "cash_balance": str(self.cash_balance),
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
                "aggregate_id": str(self.aggregate_id),
                "details": details,
            }
        )

    def _register_event(self, event: DomainEvent):
        self._events.append(event)

    # ==================== BUSINESS METHODS (asli) ====================
    def add_transaction(self, journal: SimplifiedJournalEntity) -> UMKMTransactionAggregate:
        if journal.journal_id in self.journals:
            raise ValueError(f"Transaction {journal.journal_id} already exists")
        if journal.transaction_type == TransactionType.EXPENSE:
            new_balance = self.cash_balance - journal.amount
            if new_balance < 0:
                raise ValueError(
                    f"Insufficient cash balance: {self.cash_balance} < {journal.amount}"
                )
        new_journals = self.journals.copy()
        new_journals[journal.journal_id] = journal
        new_balance = self.cash_balance
        if journal.transaction_type == TransactionType.INCOME:
            new_balance += journal.amount
        elif journal.transaction_type == TransactionType.EXPENSE:
            new_balance -= journal.amount
        self._register_event(
            TransactionCreatedEvent(
                self.aggregate_id, self.version + 1, journal, journal.created_by
            )
        )
        return self._copy_with(
            journals=new_journals, cash_balance=new_balance, version=self.version + 1
        )

    def update_transaction(self, journal: SimplifiedJournalEntity) -> UMKMTransactionAggregate:
        if journal.journal_id not in self.journals:
            raise ValueError(f"Transaction {journal.journal_id} not found")
        old_journal = self.journals[journal.journal_id]
        temp_balance = self.cash_balance
        if old_journal.transaction_type == TransactionType.INCOME:
            temp_balance -= old_journal.amount
        elif old_journal.transaction_type == TransactionType.EXPENSE:
            temp_balance += old_journal.amount
        if journal.transaction_type == TransactionType.INCOME:
            temp_balance += journal.amount
        elif journal.transaction_type == TransactionType.EXPENSE:
            if temp_balance - journal.amount < 0:
                raise ValueError("Insufficient cash balance after update")
            temp_balance -= journal.amount
        new_journals = self.journals.copy()
        new_journals[journal.journal_id] = journal
        return self._copy_with(
            journals=new_journals, cash_balance=temp_balance, version=self.version + 1
        )

    def delete_transaction(self, journal_id: UUID, deleted_by: str) -> UMKMTransactionAggregate:
        if journal_id not in self.journals:
            raise ValueError(f"Transaction {journal_id} not found")
        journal = self.journals[journal_id]
        new_balance = self.cash_balance
        if journal.transaction_type == TransactionType.INCOME:
            new_balance -= journal.amount
        elif journal.transaction_type == TransactionType.EXPENSE:
            new_balance += journal.amount
        new_journals = self.journals.copy()
        deleted_journal = journal.delete(deleted_by)
        new_journals[journal_id] = deleted_journal
        return self._copy_with(
            journals=new_journals, cash_balance=new_balance, version=self.version + 1
        )

    def get_transactions_by_date_range(
        self, from_date: datetime, to_date: datetime
    ) -> list[SimplifiedJournalEntity]:
        return [
            j
            for j in self.journals.values()
            if from_date <= j.transaction_date <= to_date and j.status.value != "deleted"
        ]

    def get_income_total(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> Decimal:
        total = Decimal(0)
        for j in self.journals.values():
            if j.status.value == "deleted":
                continue
            if from_date and j.transaction_date < from_date:
                continue
            if to_date and j.transaction_date > to_date:
                continue
            if j.transaction_type == TransactionType.INCOME:
                total += j.amount
        return total

    def get_expense_total(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> Decimal:
        total = Decimal(0)
        for j in self.journals.values():
            if j.status.value == "deleted":
                continue
            if from_date and j.transaction_date < from_date:
                continue
            if to_date and j.transaction_date > to_date:
                continue
            if j.transaction_type == TransactionType.EXPENSE:
                total += j.amount
        return total

    def get_profit_loss(self, from_date: datetime, to_date: datetime) -> Decimal:
        return self.get_income_total(from_date, to_date) - self.get_expense_total(
            from_date, to_date
        )

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> UMKMTransactionAggregate:
        self._record_audit("CREATE", created_by, {"business_name": self.business_name})
        return self

    def update(self, updated_by: str, **kwargs) -> UMKMTransactionAggregate:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in (
                "aggregate_id",
                "created_at",
                "version",
                "_events",
                "_audit_trail",
                "_snapshots",
            ):
                data[key] = value
        new = self._copy_with(
            business_name=data.get("business_name", self.business_name),
            status=UMKMStatus(data.get("status", self.status.value)),
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new

    def delete(self, deleted_by: str, reason: str | None = None) -> UMKMTransactionAggregate:
        new = self._copy_with(
            status=UMKMStatus.INACTIVE, updated_at=datetime.now(UTC), version=self.version + 1
        )
        new._record_audit("DELETE", deleted_by, {"reason": reason})
        return new

    def restore(self, restored_by: str) -> UMKMTransactionAggregate:
        if self.status != UMKMStatus.INACTIVE:
            raise ValueError("Cannot restore active aggregate")
        new = self._copy_with(
            status=UMKMStatus.ACTIVE, updated_at=datetime.now(UTC), version=self.version + 1
        )
        new._record_audit("RESTORE", restored_by, {})
        return new

    def activate(self, activated_by: str) -> UMKMTransactionAggregate:
        if self.status == UMKMStatus.ACTIVE:
            return self
        return self.restore(activated_by)

    def deactivate(
        self, deactivated_by: str, reason: str | None = None
    ) -> UMKMTransactionAggregate:
        if self.status == UMKMStatus.INACTIVE:
            return self
        return self.delete(deactivated_by, reason)

    def lock(self, locked_by: str, reason: str) -> UMKMTransactionAggregate:
        new = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new._record_audit("LOCK", locked_by, {"reason": reason})
        return new

    def unlock(self, unlocked_by: str) -> UMKMTransactionAggregate:
        new = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new._record_audit("UNLOCK", unlocked_by, {})
        return new

    def validate(self) -> dict[str, Any]:
        errors = []
        if self.cash_balance < 0:
            errors.append("Cash balance cannot be negative")
        for j in self.journals.values():
            res = j.validate()
            if not res["is_valid"]:
                errors.extend([f"Journal {j.journal_number}: {e}" for e in res["errors"]])
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "aggregate_id": str(self.aggregate_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": str(self.aggregate_id),
            "legal_entity_id": str(self.legal_entity_id),
            "business_name": self.business_name,
            "status": self.status.value,
            "cash_balance": str(self.cash_balance),
            "total_transactions": len(self.journals),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UMKMTransactionAggregate:
        return cls(
            aggregate_id=UUID(data["aggregate_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            business_name=data["business_name"],
            status=UMKMStatus(data.get("status", "active")),
            cash_balance=Decimal(data.get("cash_balance", "0")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
        )

    def clone(self) -> UMKMTransactionAggregate:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = UMKMTransactionAggregate(
            aggregate_id=new_id,
            legal_entity_id=self.legal_entity_id,
            business_name=f"{self.business_name}_COPY",
            status=UMKMStatus.ACTIVE,
            journals={},
            cash_balance=Decimal(0),
            created_at=now,
            updated_at=now,
            version=1,
        )
        cloned._record_audit("CLONE", "system", {"source": str(self.aggregate_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "aggregate_id": str(self.aggregate_id),
            "business_name": self.business_name,
            "cash_balance": str(self.cash_balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> UMKMTransactionAggregate:
        new = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new._record_audit("TOUCH", touched_by, {})
        return new

    # ==================== AGGREGATE ROOT METHODS ====================
    def add_child(self, entity: Any, created_by: str) -> UMKMTransactionAggregate:
        if isinstance(entity, SimplifiedJournalEntity):
            return self.add_transaction(entity)
        raise ValueError(f"Cannot add child of type {type(entity)}")

    def remove_child(
        self, entity_id: UUID, entity_type: str, removed_by: str
    ) -> UMKMTransactionAggregate:
        if entity_type == "journal":
            return self.delete_transaction(entity_id, removed_by)
        raise ValueError(f"Unknown entity type: {entity_type}")

    def can_post(self, user_id: str, permission: str) -> bool:
        return True

    def post(self, user_id: str, permission: str, posted_by: str) -> UMKMTransactionAggregate:
        self._record_audit("POST", posted_by, {"user_id": user_id, "permission": permission})
        return self

    def can_approve(self, user_id: str, resource: str) -> bool:
        return True

    def approve(self, user_id: str, resource: str, approved_by: str) -> UMKMTransactionAggregate:
        self._record_audit("APPROVE", approved_by, {"user_id": user_id, "resource": resource})
        return self

    def can_reject(self, user_id: str, resource: str) -> bool:
        return True

    def reject(
        self, user_id: str, resource: str, rejected_by: str, reason: str
    ) -> UMKMTransactionAggregate:
        self._record_audit(
            "REJECT", rejected_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_cancel(self, user_id: str, resource: str) -> bool:
        return True

    def cancel(
        self, user_id: str, resource: str, cancelled_by: str, reason: str
    ) -> UMKMTransactionAggregate:
        self._record_audit(
            "CANCEL", cancelled_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_reverse(self, user_id: str, resource: str) -> bool:
        return False

    def reverse(
        self, user_id: str, resource: str, reversed_by: str, reason: str
    ) -> UMKMTransactionAggregate:
        raise NotImplementedError("Reverse not supported for UMKM aggregate")

    def can_close(self, user_id: str, resource: str) -> bool:
        return True

    def close(
        self, user_id: str, resource: str, closed_by: str, reason: str
    ) -> UMKMTransactionAggregate:
        return self.deactivate(closed_by, reason)

    def can_reopen(self, user_id: str, resource: str) -> bool:
        return self.status == UMKMStatus.INACTIVE

    def reopen(
        self, user_id: str, resource: str, reopened_by: str, reason: str
    ) -> UMKMTransactionAggregate:
        return self.activate(reopened_by)

    def can_archive(self, user_id: str) -> bool:
        return True

    def archive(
        self, user_id: str, archived_by: str, reason: str | None = None
    ) -> UMKMTransactionAggregate:
        return self.delete(archived_by, reason)

    def can_unarchive(self, user_id: str) -> bool:
        return self.status == UMKMStatus.INACTIVE

    def unarchive(self, user_id: str, unarchived_by: str) -> UMKMTransactionAggregate:
        return self.restore(unarchived_by)

    def register_event(self, event: DomainEvent) -> None:
        self._register_event(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== PRIVATE ====================
    def _copy_with(self, **kwargs) -> UMKMTransactionAggregate:
        return UMKMTransactionAggregate(
            aggregate_id=kwargs.get("aggregate_id", self.aggregate_id),
            legal_entity_id=kwargs.get("legal_entity_id", self.legal_entity_id),
            business_name=kwargs.get("business_name", self.business_name),
            status=kwargs.get("status", self.status),
            journals=kwargs.get("journals", self.journals),
            cash_balance=kwargs.get("cash_balance", self.cash_balance),
            created_at=kwargs.get("created_at", self.created_at),
            updated_at=kwargs.get("updated_at", self.updated_at),
            version=kwargs.get("version", self.version),
        )


__all__ = ["UMKMStatus", "UMKMTransactionAggregate"]
