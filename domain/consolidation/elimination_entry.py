#!/usr/bin/env python3
"""
Module: elimination_entry.py
Layer: Domain / Consolidation
Responsibility: Jurnal eliminasi untuk konsolidasi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


@dataclass
class EliminationEntry:
    """Entitas jurnal eliminasi dengan semua method dasar."""

    id: UUID
    account_code: str
    debit: Decimal
    credit: Decimal
    description: str
    from_entity_id: UUID | None = None
    to_entity_id: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    # Tracking
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._record_audit("CREATE", self.created_by, {})

    def _validate(self) -> None:
        if self.debit > 0 and self.credit > 0:
            raise ValueError("Elimination entry cannot have both debit and credit")
        if self.debit == 0 and self.credit == 0:
            raise ValueError("Elimination entry must have non-zero amount")
        self.debit = self.debit.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        self.credit = self.credit.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if not self.account_code or len(self.account_code.strip()) < 1:
            raise ValueError("Account code is required")
        if not self.description:
            raise ValueError("Description is required")

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        entry = {
            "action": action,
            "performed_by": performed_by,
            "timestamp": datetime.now(UTC).isoformat(),
            "version": self.version,
            "elimination_id": str(self.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> EliminationEntry:
        self._record_audit(
            "CREATE", created_by, {"account_code": self.account_code, "amount": str(self.amount)}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> EliminationEntry:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_entry = self.from_dict(data)
        new_entry.created_at = self.created_at
        new_entry.created_by = self.created_by
        new_entry.version = self.version + 1
        new_entry._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entry

    def delete(self, deleted_by: str, reason: str | None = None) -> EliminationEntry:
        new_entry = self._copy()
        new_entry._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entry

    def restore(self, restored_by: str) -> EliminationEntry:
        new_entry = self._copy()
        new_entry._record_audit("RESTORE", restored_by, {})
        return new_entry

    def activate(self, activated_by: str) -> EliminationEntry:
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> EliminationEntry:
        return self

    def lock(self, locked_by: str, reason: str) -> EliminationEntry:
        return self

    def unlock(self, unlocked_by: str) -> EliminationEntry:
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except ValueError as e:
            errors.append(str(e))
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "elimination_id": str(self.id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_code": self.account_code,
            "debit": str(self.debit),
            "credit": str(self.credit),
            "description": self.description,
            "from_entity_id": str(self.from_entity_id) if self.from_entity_id else None,
            "to_entity_id": str(self.to_entity_id) if self.to_entity_id else None,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "amount": str(self.amount),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EliminationEntry:
        return cls(
            id=UUID(data["id"]),
            account_code=data["account_code"],
            debit=Decimal(data["debit"]),
            credit=Decimal(data["credit"]),
            description=data["description"],
            from_entity_id=UUID(data["from_entity_id"]) if data.get("from_entity_id") else None,
            to_entity_id=UUID(data["to_entity_id"]) if data.get("to_entity_id") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def clone(self) -> EliminationEntry:
        new_id = uuid4()
        cloned = self._copy()
        object.__setattr__(cloned, "id", new_id)
        cloned.created_at = datetime.now(UTC)
        cloned.created_by = self.created_by
        cloned.version = 1
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "elimination_id": str(self.id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> EliminationEntry:
        new_entry = self._copy()
        new_entry._record_audit("TOUCH", touched_by, {})
        return new_entry

    @property
    def amount(self) -> Decimal:
        return (self.debit - self.credit).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    @property
    def is_debit(self) -> bool:
        return self.debit > 0

    @property
    def is_credit(self) -> bool:
        return self.credit > 0

    def reverse(self, reversed_by: str, reason: str | None = None) -> EliminationEntry:
        """Buat jurnal eliminasi kebalikannya."""
        return EliminationEntry(
            id=uuid4(),
            account_code=self.account_code,
            debit=self.credit,
            credit=self.debit,
            description=f"Reversal of {self.id}: {reason or 'Adjustment'}",
            from_entity_id=self.to_entity_id,
            to_entity_id=self.from_entity_id,
            created_by=reversed_by,
        )

    def _copy(self) -> EliminationEntry:
        return EliminationEntry(
            id=self.id,
            account_code=self.account_code,
            debit=self.debit,
            credit=self.credit,
            description=self.description,
            from_entity_id=self.from_entity_id,
            to_entity_id=self.to_entity_id,
            created_at=self.created_at,
            created_by=self.created_by,
            version=self.version,
        )


__all__ = ["EliminationEntry"]
