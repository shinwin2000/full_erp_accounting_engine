#!/usr/bin/env python3
"""
Module: invariants.py
Layer: Domain / UMKM Simplified
Responsibility: Invariant rules for UMKM transactions.

Metode entity dasar untuk InvariantResult dan enforcer.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from domain.umkm_simplified.simplified_journal_entity import (
    SimplifiedJournalEntity,
    TransactionType,
)

logger = logging.getLogger(__name__)


# === 1. INVARIANT RESULT ===
class InvariantResult:
    def __init__(self, is_valid: bool = True, errors: list[str] = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []
        self._snapshots: list[dict[str, Any]] = []

    def add_error(self, error: str) -> None:
        self.errors.append(error)
        self.is_valid = False
        self._record_audit("ADD_ERROR", "system", {"error": error})

    def merge(self, other: InvariantResult) -> InvariantResult:
        if not other.is_valid:
            self.is_valid = False
            self.errors.extend(other.errors)
        return self

    def __bool__(self) -> bool:
        return self.is_valid

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"is_valid": self.is_valid, "errors": self.errors, "version": self._version}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InvariantResult:
        instance = cls(data.get("is_valid", True), data.get("errors", []))
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> InvariantResult:
        new = InvariantResult(self.is_valid, self.errors.copy())
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
        }

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> InvariantResult:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self


# === 2. UMKM INVARIANTS ===
class UMKMInvariants:
    @staticmethod
    def validate_amount(amount: Decimal) -> InvariantResult:
        result = InvariantResult(True)
        if amount <= 0:
            result.add_error(f"Amount must be positive: {amount}")
        return result

    @staticmethod
    def validate_cash_balance(
        new_balance: Decimal, transaction_amount: Decimal, transaction_type: TransactionType
    ) -> InvariantResult:
        result = InvariantResult(True)
        if transaction_type == TransactionType.EXPENSE and new_balance < 0:
            result.add_error(f"Insufficient cash balance: would become {new_balance}")
        return result

    @staticmethod
    def validate_journal_number(journal_number: str, existing_numbers: set[str]) -> InvariantResult:
        result = InvariantResult(True)
        if len(journal_number) < 3:
            result.add_error("Journal number too short (min 3 characters)")
        if journal_number in existing_numbers:
            result.add_error(f"Journal number {journal_number} already exists")
        return result

    @staticmethod
    def validate_category(category: str) -> InvariantResult:
        result = InvariantResult(True)
        if not category or len(category.strip()) < 2:
            result.add_error("Category is required (min 2 characters)")
        return result

    @staticmethod
    def validate_transaction_date(
        transaction_date: datetime, current_date: datetime | None = None
    ) -> InvariantResult:
        result = InvariantResult(True)
        if current_date is None:
            current_date = datetime.now(UTC)
        if transaction_date > current_date:
            result.add_error("Transaction date cannot be in the future")
        return result


# === 3. UMKM INVARIANT ENFORCER ===
class UMKMInvariantEnforcer:
    def __init__(self, journal_number_checker: callable = None):
        self._journal_number_checker = journal_number_checker or (lambda: set())
        self._invariants = UMKMInvariants()
        self._version = 1
        self._audit_trail: list[dict[str, Any]] = []

    async def enforce_create_journal(self, journal: SimplifiedJournalEntity) -> InvariantResult:
        result = InvariantResult(True)
        result.merge(self._invariants.validate_amount(journal.amount))
        result.merge(self._invariants.validate_category(journal.category))
        result.merge(self._invariants.validate_transaction_date(journal.transaction_date))
        existing_numbers = await self._journal_number_checker()
        result.merge(
            self._invariants.validate_journal_number(journal.journal_number, existing_numbers)
        )
        self._record_audit(
            "ENFORCE_CREATE_JOURNAL", "system", {"journal_number": journal.journal_number}
        )
        return result

    def enforce_cash_balance(
        self, current_balance: Decimal, transaction: SimplifiedJournalEntity
    ) -> InvariantResult:
        new_balance = current_balance
        if transaction.transaction_type == TransactionType.EXPENSE:
            new_balance -= transaction.amount
        elif transaction.transaction_type == TransactionType.INCOME:
            new_balance += transaction.amount
        return self._invariants.validate_cash_balance(
            new_balance, transaction.amount, transaction.transaction_type
        )

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]):
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self._version,
                "details": details,
            }
        )

    def validate(self) -> dict[str, Any]:
        return {"is_valid": True, "errors": []}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._version, "type": "UMKMInvariantEnforcer"}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UMKMInvariantEnforcer:
        instance = cls()
        instance._version = data.get("version", 1)
        return instance

    def clone(self) -> UMKMInvariantEnforcer:
        new = UMKMInvariantEnforcer(self._journal_number_checker)
        new._version = self._version + 1
        return new

    def snapshot(self) -> dict[str, Any]:
        return {"version": self._version, "type": "UMKMInvariantEnforcer"}

    def version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> UMKMInvariantEnforcer:
        self._version += 1
        self._record_audit("TOUCH", touched_by, {})
        return self

    def reset(self) -> None:
        self._version = 1
        self._audit_trail = []


__all__ = ["InvariantResult", "UMKMInvariantEnforcer", "UMKMInvariants"]
