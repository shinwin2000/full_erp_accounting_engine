#!/usr/bin/env python3
"""
Module: trial_balance_cube.py
Layer: Domain / Financial Statement
Responsibility: Represent trial balance (neraca saldo) for all accounts.
               Supports grouping by account type, calculating balances,
               validating that total debits equal total credits.
               Immutable object with all entity dasar methods, serialization,
               cloning, snapshot, audit trail.
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


class TrialBalanceError(ValueError):
    pass


class TrialBalanceNotBalancedError(TrialBalanceError):
    pass


# ============================================================================
# Value Object: TrialBalanceAccount
# ============================================================================


@dataclass(frozen=True)
class TrialBalanceAccount:
    code: str
    name: str
    opening_debit: Decimal
    opening_credit: Decimal
    movement_debit: Decimal
    movement_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal
    account_type: str | None = None
    normal_balance: str = "debit"

    def __post_init__(self) -> None:
        # Validate amounts
        for field_name in [
            "opening_debit",
            "opening_credit",
            "movement_debit",
            "movement_credit",
            "closing_debit",
            "closing_credit",
        ]:
            val = getattr(self, field_name)
            if not isinstance(val, Decimal):
                object.__setattr__(self, field_name, Decimal(str(val)))
            if val < 0:
                raise TrialBalanceError(f"{field_name} cannot be negative: {val}")
            object.__setattr__(
                self, field_name, val.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            )

        # Validate code and name
        if not self.code or len(self.code.strip()) < 1:
            raise TrialBalanceError("Account code must be non-empty")
        if not self.name or len(self.name.strip()) < 1:
            raise TrialBalanceError("Account name must be non-empty")

        # Validate normal_balance
        if self.normal_balance not in ("debit", "credit"):
            raise TrialBalanceError(f"Invalid normal_balance: {self.normal_balance}")

    @property
    def net_closing_balance(self) -> Decimal:
        return (self.closing_debit - self.closing_credit).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def net_opening_balance(self) -> Decimal:
        return (self.opening_debit - self.opening_credit).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def net_movement(self) -> Decimal:
        return (self.movement_debit - self.movement_credit).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    def is_debit_balance(self) -> bool:
        return self.net_closing_balance > 0

    def is_credit_balance(self) -> bool:
        return self.net_closing_balance < 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "opening_debit": str(self.opening_debit),
            "opening_credit": str(self.opening_credit),
            "movement_debit": str(self.movement_debit),
            "movement_credit": str(self.movement_credit),
            "closing_debit": str(self.closing_debit),
            "closing_credit": str(self.closing_credit),
            "net_closing_balance": str(self.net_closing_balance),
            "account_type": self.account_type,
            "normal_balance": self.normal_balance,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialBalanceAccount:
        return cls(
            code=data["code"],
            name=data["name"],
            opening_debit=Decimal(data.get("opening_debit", "0")),
            opening_credit=Decimal(data.get("opening_credit", "0")),
            movement_debit=Decimal(data.get("movement_debit", "0")),
            movement_credit=Decimal(data.get("movement_credit", "0")),
            closing_debit=Decimal(data.get("closing_debit", "0")),
            closing_credit=Decimal(data.get("closing_credit", "0")),
            account_type=data.get("account_type"),
            normal_balance=data.get("normal_balance", "debit"),
        )


# ============================================================================
# Entity: TrialBalanceCube
# ============================================================================


@dataclass(frozen=True)
class TrialBalanceCube:
    cube_id: UUID
    legal_entity_id: UUID
    period_start: date
    period_end: date
    accounts: list[TrialBalanceAccount] = field(default_factory=list)
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
        # Validate dates
        if self.period_end <= self.period_start:
            raise TrialBalanceError(
                f"Period end {self.period_end} must be after period start {self.period_start}"
            )

        # Validate timestamps
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

        if self.version < 1:
            raise TrialBalanceError("Version must be >= 1")

        # Validate trial balance is balanced
        if not self.is_balanced():
            logger.warning(
                f"Trial balance not balanced: debits={self.total_closing_debit()}, credits={self.total_closing_credit()}"
            )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "cube_id": str(self.cube_id),
            "period": f"{self.period_start.isoformat()} to {self.period_end.isoformat()}",
            "account_count": len(self.accounts),
            "is_balanced": self.is_balanced(),
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
            "cube_id": str(self.cube_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> TrialBalanceCube:
        self._record_audit(
            "CREATE", created_by, {"period": f"{self.period_start} to {self.period_end}"}
        )
        return self

    def update(self, updated_by: str, **kwargs) -> TrialBalanceCube:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("cube_id", "created_at", "created_by", "version"):
                data[key] = value
        new_cube = self.from_dict(data)
        new_cube._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_cube

    def delete(self, deleted_by: str, reason: str | None = None) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_cube

    def restore(self, restored_by: str) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube._record_audit("RESTORE", restored_by, {})
        return new_cube

    def activate(self, activated_by: str) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube._record_audit("ACTIVATE", activated_by, {})
        return new_cube

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_cube

    def lock(self, locked_by: str, reason: str) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube.metadata["locked_by"] = locked_by
        new_cube.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_cube.metadata["lock_reason"] = reason
        new_cube._record_audit("LOCK", locked_by, {"reason": reason})
        return new_cube

    def unlock(self, unlocked_by: str) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube.metadata.pop("locked_by", None)
        new_cube.metadata.pop("locked_at", None)
        new_cube.metadata.pop("lock_reason", None)
        new_cube._record_audit("UNLOCK", unlocked_by, {})
        return new_cube

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._validate()
        except TrialBalanceError as e:
            errors.append(str(e))
        if not self.is_balanced():
            errors.append(
                f"Trial balance not balanced: debits={self.total_closing_debit()}, credits={self.total_closing_credit()}"
            )
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "cube_id": str(self.cube_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cube_id": str(self.cube_id),
            "legal_entity_id": str(self.legal_entity_id),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "accounts": [acc.to_dict() for acc in self.accounts],
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
            "metadata": self.metadata,
            "total_opening_debit": str(self.total_opening_debit()),
            "total_opening_credit": str(self.total_opening_credit()),
            "total_movement_debit": str(self.total_movement_debit()),
            "total_movement_credit": str(self.total_movement_credit()),
            "total_closing_debit": str(self.total_closing_debit()),
            "total_closing_credit": str(self.total_closing_credit()),
            "is_balanced": self.is_balanced(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrialBalanceCube:
        accounts = [TrialBalanceAccount.from_dict(acc) for acc in data.get("accounts", [])]
        return cls(
            cube_id=UUID(data["cube_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            period_start=date.fromisoformat(data["period_start"]),
            period_end=date.fromisoformat(data["period_end"]),
            accounts=accounts,
            description=data.get("description", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> TrialBalanceCube:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = TrialBalanceCube(
            cube_id=new_id,
            legal_entity_id=self.legal_entity_id,
            period_start=self.period_start,
            period_end=self.period_end,
            accounts=[acc for acc in self.accounts],  # Shallow copy of immutable accounts
            description=f"Cloned from {self.cube_id}",
            created_at=now,
            created_by=self.created_by,
            version=1,
        )
        cloned._record_audit("CLONE", self.created_by, {"source": str(self.cube_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "cube_id": str(self.cube_id),
            "period": f"{self.period_start.isoformat()} to {self.period_end.isoformat()}",
            "account_count": len(self.accounts),
            "is_balanced": self.is_balanced(),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> TrialBalanceCube:
        new_cube = self._copy()
        new_cube._record_audit("TOUCH", touched_by, {})
        return new_cube

    # ==================== QUERY METHODS ====================

    def total_opening_debit(self) -> Decimal:
        return sum(acc.opening_debit for acc in self.accounts)

    def total_opening_credit(self) -> Decimal:
        return sum(acc.opening_credit for acc in self.accounts)

    def total_movement_debit(self) -> Decimal:
        return sum(acc.movement_debit for acc in self.accounts)

    def total_movement_credit(self) -> Decimal:
        return sum(acc.movement_credit for acc in self.accounts)

    def total_closing_debit(self) -> Decimal:
        return sum(acc.closing_debit for acc in self.accounts)

    def total_closing_credit(self) -> Decimal:
        return sum(acc.closing_credit for acc in self.accounts)

    def is_balanced(self) -> bool:
        return self.total_closing_debit() == self.total_closing_credit()

    def opening_balance(self) -> dict[str, Decimal]:
        return {acc.code: acc.net_opening_balance for acc in self.accounts}

    def closing_balance(self) -> dict[str, Decimal]:
        return {acc.code: acc.net_closing_balance for acc in self.accounts}

    def get_account_balance(self, account_code: str) -> Decimal:
        for acc in self.accounts:
            if acc.code == account_code:
                return acc.net_closing_balance
        return Decimal("0")

    def get_accounts_by_type(self, account_type: str) -> list[TrialBalanceAccount]:
        return [acc for acc in self.accounts if acc.account_type == account_type]

    def get_debit_balance_accounts(self) -> list[TrialBalanceAccount]:
        return [acc for acc in self.accounts if acc.net_closing_balance > 0]

    def get_credit_balance_accounts(self) -> list[TrialBalanceAccount]:
        return [acc for acc in self.accounts if acc.net_closing_balance < 0]

    def filter_by_code_prefix(self, prefix: str) -> list[TrialBalanceAccount]:
        return [acc for acc in self.accounts if acc.code.startswith(prefix)]

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> TrialBalanceCube:
        return TrialBalanceCube(
            cube_id=self.cube_id,
            legal_entity_id=self.legal_entity_id,
            period_start=self.period_start,
            period_end=self.period_end,
            accounts=self.accounts.copy(),
            description=self.description,
            created_at=self.created_at,
            created_by=self.created_by,
            version=self.version,
            metadata=self.metadata.copy(),
        )


__all__ = [
    "TrialBalanceAccount",
    "TrialBalanceCube",
    "TrialBalanceError",
    "TrialBalanceNotBalancedError",
]
