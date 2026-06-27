#!/usr/bin/env python3
"""
Module: balance_sheet_snapshot.py
Layer: Domain / Financial Statement
Responsibility: Represent snapshot of balance sheet (neraca) at a given date.
               Immutable object with all entity dasar methods, validation,
               ratio calculations, serialization, cloning, snapshot, audit trail.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class BalanceSheetError(ValueError):
    pass


class BalanceSheetNotBalancedError(BalanceSheetError):
    pass


# ============================================================================
# Balance Sheet Snapshot Entity
# ============================================================================


@dataclass(frozen=True)
class BalanceSheetSnapshot:
    snapshot_id: UUID
    legal_entity_id: UUID
    as_of_date: date
    current_assets: Decimal
    fixed_assets: Decimal
    intangible_assets: Decimal
    total_assets: Decimal
    current_liabilities: Decimal
    long_term_liabilities: Decimal
    total_liabilities: Decimal
    equity: Decimal
    total_liabilities_equity: Decimal
    currency: str = "IDR"
    description: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        # Validate currency
        if not self.currency or len(self.currency) != 3:
            raise BalanceSheetError(f"Invalid currency: {self.currency}")

        # Validate as_of_date
        if self.as_of_date and isinstance(self.as_of_date, str):
            object.__setattr__(self, "as_of_date", date.fromisoformat(self.as_of_date))

        # Validate amounts are Decimal and non-negative
        for field_name in [
            "current_assets",
            "fixed_assets",
            "intangible_assets",
            "total_assets",
            "current_liabilities",
            "long_term_liabilities",
            "total_liabilities",
            "equity",
            "total_liabilities_equity",
        ]:
            val = getattr(self, field_name)
            if not isinstance(val, Decimal):
                object.__setattr__(self, field_name, Decimal(str(val)))
            if val < 0:
                raise BalanceSheetError(f"{field_name} cannot be negative: {val}")
            object.__setattr__(
                self, field_name, val.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            )

        # Validate assets sum
        computed_total = self.current_assets + self.fixed_assets + self.intangible_assets
        if computed_total != self.total_assets:
            raise BalanceSheetError(
                f"Total assets sum mismatch: computed {computed_total} != {self.total_assets}"
            )

        # Validate balance sheet equation
        if self.total_assets != self.total_liabilities_equity:
            raise BalanceSheetNotBalancedError(
                f"Balance sheet not balanced: total_assets={self.total_assets}, "
                f"total_liabilities_equity={self.total_liabilities_equity}"
            )

        # Validate timestamps
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

        if self.version < 1:
            raise BalanceSheetError("Version must be >= 1")

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "snapshot_id": str(self.snapshot_id),
            "as_of_date": self.as_of_date.isoformat(),
            "total_assets": str(self.total_assets),
            "total_liabilities": str(self.total_liabilities),
            "equity": str(self.equity),
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
            "snapshot_id": str(self.snapshot_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> BalanceSheetSnapshot:
        self._record_audit("CREATE", created_by, {"as_of_date": self.as_of_date.isoformat()})
        return self

    def update(self, updated_by: str, **kwargs) -> BalanceSheetSnapshot:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("snapshot_id", "created_at", "created_by", "version"):
                data[key] = value
        new_snapshot = self.from_dict(data)
        new_snapshot._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_snapshot

    def delete(self, deleted_by: str, reason: str | None = None) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_snapshot

    def restore(self, restored_by: str) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot._record_audit("RESTORE", restored_by, {})
        return new_snapshot

    def activate(self, activated_by: str) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot._record_audit("ACTIVATE", activated_by, {})
        return new_snapshot

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_snapshot

    def lock(self, locked_by: str, reason: str) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot.metadata["locked_by"] = locked_by
        new_snapshot.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_snapshot.metadata["lock_reason"] = reason
        new_snapshot._record_audit("LOCK", locked_by, {"reason": reason})
        return new_snapshot

    def unlock(self, unlocked_by: str) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot.metadata.pop("locked_by", None)
        new_snapshot.metadata.pop("locked_at", None)
        new_snapshot.metadata.pop("lock_reason", None)
        new_snapshot._record_audit("UNLOCK", unlocked_by, {})
        return new_snapshot

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except BalanceSheetError as e:
            errors.append(str(e))
        if not self.is_balanced():
            errors.append("Balance sheet is not balanced")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "snapshot_id": str(self.snapshot_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "legal_entity_id": str(self.legal_entity_id),
            "as_of_date": self.as_of_date.isoformat(),
            "current_assets": str(self.current_assets),
            "fixed_assets": str(self.fixed_assets),
            "intangible_assets": str(self.intangible_assets),
            "total_assets": str(self.total_assets),
            "current_liabilities": str(self.current_liabilities),
            "long_term_liabilities": str(self.long_term_liabilities),
            "total_liabilities": str(self.total_liabilities),
            "equity": str(self.equity),
            "total_liabilities_equity": str(self.total_liabilities_equity),
            "currency": self.currency,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
            "working_capital": str(self.working_capital),
            "debt_to_equity_ratio": str(self.debt_to_equity_ratio),
            "equity_ratio": str(self.equity_ratio),
            "is_balanced": self.is_balanced(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BalanceSheetSnapshot:
        return cls(
            snapshot_id=UUID(data["snapshot_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            as_of_date=date.fromisoformat(data["as_of_date"]),
            current_assets=Decimal(data["current_assets"]),
            fixed_assets=Decimal(data["fixed_assets"]),
            intangible_assets=Decimal(data["intangible_assets"]),
            total_assets=Decimal(data["total_assets"]),
            current_liabilities=Decimal(data["current_liabilities"]),
            long_term_liabilities=Decimal(data["long_term_liabilities"]),
            total_liabilities=Decimal(data["total_liabilities"]),
            equity=Decimal(data["equity"]),
            total_liabilities_equity=Decimal(data["total_liabilities_equity"]),
            currency=data.get("currency", "IDR"),
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> BalanceSheetSnapshot:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = BalanceSheetSnapshot(
            snapshot_id=new_id,
            legal_entity_id=self.legal_entity_id,
            as_of_date=self.as_of_date,
            current_assets=self.current_assets,
            fixed_assets=self.fixed_assets,
            intangible_assets=self.intangible_assets,
            total_assets=self.total_assets,
            current_liabilities=self.current_liabilities,
            long_term_liabilities=self.long_term_liabilities,
            total_liabilities=self.total_liabilities,
            equity=self.equity,
            total_liabilities_equity=self.total_liabilities_equity,
            currency=self.currency,
            description=f"Cloned from {self.snapshot_id}",
            created_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.snapshot_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "snapshot_id": str(self.snapshot_id),
            "as_of_date": self.as_of_date.isoformat(),
            "total_assets": str(self.total_assets),
            "total_liabilities": str(self.total_liabilities),
            "equity": str(self.equity),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> BalanceSheetSnapshot:
        new_snapshot = self._copy()
        new_snapshot._record_audit("TOUCH", touched_by, {})
        return new_snapshot

    # ==================== PROPERTIES & RATIOS ====================

    def is_balanced(self) -> bool:
        return self.total_assets == self.total_liabilities_equity

    @property
    def working_capital(self) -> Decimal:
        return (self.current_assets - self.current_liabilities).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def debt_to_equity_ratio(self) -> Decimal:
        if self.equity == 0:
            return Decimal("inf")
        return (self.total_liabilities / self.equity).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def equity_ratio(self) -> Decimal:
        if self.total_assets == 0:
            return Decimal("0")
        return (self.equity / self.total_assets).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    @property
    def current_ratio(self) -> Decimal:
        if self.current_liabilities == 0:
            return Decimal("inf")
        return (self.current_assets / self.current_liabilities).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def quick_ratio(self) -> Decimal:
        if self.current_liabilities == 0:
            return Decimal("inf")
        quick_assets = self.current_assets  # In real implementation, subtract inventory
        return (quick_assets / self.current_liabilities).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> BalanceSheetSnapshot:
        return BalanceSheetSnapshot(
            snapshot_id=self.snapshot_id,
            legal_entity_id=self.legal_entity_id,
            as_of_date=self.as_of_date,
            current_assets=self.current_assets,
            fixed_assets=self.fixed_assets,
            intangible_assets=self.intangible_assets,
            total_assets=self.total_assets,
            current_liabilities=self.current_liabilities,
            long_term_liabilities=self.long_term_liabilities,
            total_liabilities=self.total_liabilities,
            equity=self.equity,
            total_liabilities_equity=self.total_liabilities_equity,
            currency=self.currency,
            description=self.description,
            created_at=self.created_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


__all__ = ["BalanceSheetError", "BalanceSheetNotBalancedError", "BalanceSheetSnapshot"]
