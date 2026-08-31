#!/usr/bin/env python3
"""
Module: retained_earnings_entity.py
Layer: Domain / Equity & Retained Earnings
Responsibility: Entity untuk retained earnings (laba ditahan) dengan semua method entity dasar.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class RetainedEarningsEntryType(Enum):
    OPENING_BALANCE = "opening_balance"
    NET_INCOME = "net_income"
    NET_LOSS = "net_loss"
    DIVIDEND = "dividend"
    PRIOR_PERIOD_ADJUSTMENT = "adjustment"
    TRANSFER_TO_RESERVE = "transfer_to_reserve"
    TRANSFER_FROM_RESERVE = "transfer_from_reserve"

    def display_name(self) -> str:
        names = {
            RetainedEarningsEntryType.OPENING_BALANCE: "Saldo Awal",
            RetainedEarningsEntryType.NET_INCOME: "Laba Bersih",
            RetainedEarningsEntryType.NET_LOSS: "Rugi Bersih",
            RetainedEarningsEntryType.DIVIDEND: "Dividen",
            RetainedEarningsEntryType.PRIOR_PERIOD_ADJUSTMENT: "Penyesuaian",
            RetainedEarningsEntryType.TRANSFER_TO_RESERVE: "Transfer ke Cadangan",
            RetainedEarningsEntryType.TRANSFER_FROM_RESERVE: "Transfer dari Cadangan",
        }
        return names.get(self, self.value)

    def is_increase(self) -> bool:
        return self in (
            RetainedEarningsEntryType.NET_INCOME,
            RetainedEarningsEntryType.OPENING_BALANCE,
            RetainedEarningsEntryType.TRANSFER_FROM_RESERVE,
        )

    def is_decrease(self) -> bool:
        return self in (
            RetainedEarningsEntryType.NET_LOSS,
            RetainedEarningsEntryType.DIVIDEND,
            RetainedEarningsEntryType.TRANSFER_TO_RESERVE,
        )


class RetainedEarningsPeriod(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"
    CUSTOM = "custom"


# ============================================================================
# Custom Exceptions
# ============================================================================


class RetainedEarningsError(ValueError):
    pass


class InsufficientRetainedEarningsError(RetainedEarningsError):
    pass


class DuplicatePeriodError(RetainedEarningsError):
    pass


# ============================================================================
# Value Object: RetainedEarningsEntry
# ============================================================================


@dataclass(frozen=True)
class RetainedEarningsEntry:
    entry_id: UUID
    period: str
    entry_type: RetainedEarningsEntryType
    net_income: Decimal
    dividends: Decimal
    adjustment: Decimal
    amount: Decimal
    balance_after: Decimal
    description: str
    reference_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"

    def __post_init__(self) -> None:
        if not self.period or len(self.period.strip()) < 4:
            raise RetainedEarningsError("Period must be a non-empty string (e.g., '2024-01')")
        if not isinstance(self.entry_type, RetainedEarningsEntryType):
            raise RetainedEarningsError(f"Invalid entry_type: {self.entry_type}")
        for field_name in ["net_income", "dividends", "adjustment", "amount", "balance_after"]:
            val = getattr(self, field_name)
            if not isinstance(val, Decimal):
                raise RetainedEarningsError(f"{field_name} must be Decimal")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "period": self.period,
            "entry_type": self.entry_type.value,
            "entry_type_display": self.entry_type.display_name(),
            "net_income": str(self.net_income),
            "dividends": str(self.dividends),
            "adjustment": str(self.adjustment),
            "amount": str(self.amount),
            "balance_after": str(self.balance_after),
            "description": self.description,
            "reference_id": self.reference_id,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetainedEarningsEntry:
        entry_type = RetainedEarningsEntryType(data["entry_type"])
        return cls(
            entry_id=UUID(data["entry_id"]),
            period=data["period"],
            entry_type=entry_type,
            net_income=Decimal(str(data.get("net_income", 0))),
            dividends=Decimal(str(data.get("dividends", 0))),
            adjustment=Decimal(str(data.get("adjustment", 0))),
            amount=Decimal(str(data["amount"])),
            balance_after=Decimal(str(data["balance_after"])),
            description=data["description"],
            reference_id=data.get("reference_id"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by", "system"),
        )


# ============================================================================
# Entity: RetainedEarningsEntity
# ============================================================================


@dataclass
class RetainedEarningsEntity:
    retained_earnings_id: UUID
    legal_entity_id: UUID
    opening_balance: Decimal
    current_balance: Decimal
    entries: list[RetainedEarningsEntry] = field(default_factory=list)
    currency: str = "IDR"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        self._validate()
        self._take_snapshot()

    def _validate(self) -> None:
        if not isinstance(self.opening_balance, Decimal):
            object.__setattr__(self, "opening_balance", Decimal(str(self.opening_balance)))
        if not isinstance(self.current_balance, Decimal):
            object.__setattr__(self, "current_balance", Decimal(str(self.current_balance)))
        if not self.currency or len(self.currency) != 3:
            raise RetainedEarningsError(f"Invalid currency: {self.currency}")
        computed = self.opening_balance
        for entry in self.entries:
            computed += entry.amount
        if computed != self.current_balance:
            logger.warning(
                f"Entries sum {computed} does not match current_balance {self.current_balance}"
            )
        if self.version < 1:
            raise RetainedEarningsError("Version must be >= 1")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))

    # ==================== PRIVATE HELPERS ====================

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "retained_earnings_id": str(self.retained_earnings_id),
            "legal_entity_id": str(self.legal_entity_id),
            "balance": str(self.current_balance),
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
            "retained_earnings_id": str(self.retained_earnings_id),
            "details": details,
        }
        self._audit_trail.append(entry)

    def _add_entry(self, entry: RetainedEarningsEntry) -> RetainedEarningsEntity:
        new_balance = self.current_balance + entry.amount
        # RUF005 fix: use iterable unpacking instead of concatenation
        new_entries = [*self.entries, entry]
        return RetainedEarningsEntity(
            retained_earnings_id=self.retained_earnings_id,
            legal_entity_id=self.legal_entity_id,
            opening_balance=self.opening_balance,
            current_balance=new_balance,
            entries=new_entries,
            currency=self.currency,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
            metadata=self.metadata,
        )

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> RetainedEarningsEntity:
        self._record_audit("CREATE", created_by, {"opening_balance": str(self.opening_balance)})
        return self

    def update(self, updated_by: str, **kwargs) -> RetainedEarningsEntity:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("retained_earnings_id", "created_at", "version"):
                data[key] = value
        new_entity = self.from_dict(data)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_entity

    def delete(self, deleted_by: str, reason: str | None = None) -> RetainedEarningsEntity:
        new_entity = self._copy()
        new_entity.entries = []
        new_entity.opening_balance = Decimal("0")
        new_entity.current_balance = Decimal("0")
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_entity

    def restore(self, restored_by: str) -> RetainedEarningsEntity:
        # Restore from backup would require external data; here we just reset to opening
        new_entity = self._copy()
        new_entity.current_balance = self.opening_balance
        new_entity.entries = []
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("RESTORE", restored_by, {})
        return new_entity

    def activate(self, activated_by: str) -> RetainedEarningsEntity:
        # No activation needed for retained earnings
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("ACTIVATE", activated_by, {})
        return new_entity

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> RetainedEarningsEntity:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_entity

    def lock(self, locked_by: str, reason: str) -> RetainedEarningsEntity:
        new_entity = self._copy()
        new_entity.metadata["locked_by"] = locked_by
        new_entity.metadata["locked_at"] = datetime.now(UTC).isoformat()
        new_entity.metadata["lock_reason"] = reason
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("LOCK", locked_by, {"reason": reason})
        return new_entity

    def unlock(self, unlocked_by: str) -> RetainedEarningsEntity:
        new_entity = self._copy()
        new_entity.metadata.pop("locked_by", None)
        new_entity.metadata.pop("locked_at", None)
        new_entity.metadata.pop("lock_reason", None)
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("UNLOCK", unlocked_by, {})
        return new_entity

    def validate(self) -> dict[str, Any]:
        errors = []
        computed = self.opening_balance
        for entry in self.entries:
            computed += entry.amount
        if computed != self.current_balance:
            errors.append(f"Balance mismatch: computed {computed}, current {self.current_balance}")
        if self.current_balance < 0:
            errors.append(f"Negative retained earnings balance: {self.current_balance}")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "retained_earnings_id": str(self.retained_earnings_id),
            "version": self.version,
        }

    def to_dict(self, include_entries: bool = True) -> dict[str, Any]:
        result = {
            "retained_earnings_id": str(self.retained_earnings_id),
            "legal_entity_id": str(self.legal_entity_id),
            "opening_balance": str(self.opening_balance),
            "current_balance": str(self.current_balance),
            "currency": self.currency,
            "total_net_income": str(self.total_net_income),
            "total_net_loss": str(self.total_net_loss),
            "total_dividends": str(self.total_dividends),
            "total_adjustments": str(self.total_adjustments),
            "net_change_period": str(self.net_change_period),
            "is_accumulated_loss": self.is_accumulated_loss,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "entries_count": len(self.entries),
            "metadata": self.metadata,
        }
        if include_entries:
            result["entries"] = [e.to_dict() for e in self.entries]
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetainedEarningsEntity:
        entries = []
        for entry_data in data.get("entries", []):
            entries.append(RetainedEarningsEntry.from_dict(entry_data))
        return cls(
            retained_earnings_id=UUID(data["retained_earnings_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            opening_balance=Decimal(str(data["opening_balance"])),
            current_balance=Decimal(str(data["current_balance"])),
            entries=entries,
            currency=data.get("currency", "IDR"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> RetainedEarningsEntity:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = RetainedEarningsEntity(
            retained_earnings_id=new_id,
            legal_entity_id=self.legal_entity_id,
            opening_balance=self.opening_balance,
            current_balance=self.opening_balance,
            entries=[],
            currency=self.currency,
            created_at=now,
            updated_at=now,
            version=1,
        )
        cloned._record_audit("CLONE", "system", {"source": str(self.retained_earnings_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "retained_earnings_id": str(self.retained_earnings_id),
            "legal_entity_id": str(self.legal_entity_id),
            "balance": str(self.current_balance),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> RetainedEarningsEntity:
        new_entity = self._copy()
        new_entity.updated_at = datetime.now(UTC)
        new_entity.version = self.version + 1
        new_entity._record_audit("TOUCH", touched_by, {})
        return new_entity

    # ==================== PROPERTIES ====================

    @property
    def total_net_income(self) -> Decimal:
        return sum((e.net_income for e in self.entries if e.net_income > 0), Decimal("0"))

    @property
    def total_net_loss(self) -> Decimal:
        return sum((abs(e.net_income) for e in self.entries if e.net_income < 0), Decimal("0"))

    @property
    def total_dividends(self) -> Decimal:
        return sum((e.dividends for e in self.entries), Decimal("0"))

    @property
    def total_adjustments(self) -> Decimal:
        return sum((e.adjustment for e in self.entries), Decimal("0"))

    @property
    def net_change_period(self) -> Decimal:
        return self.current_balance - self.opening_balance

    @property
    def is_accumulated_loss(self) -> bool:
        return self.current_balance < 0

    # ==================== BUSINESS LOGIC ====================

    def add_net_income(
        self,
        net_income: Decimal,
        period: str,
        created_by: str,
        description: str = "",
        reference_id: str | None = None,
    ) -> RetainedEarningsEntity:
        if net_income == 0:
            return self
        entry_type = (
            RetainedEarningsEntryType.NET_INCOME
            if net_income > 0
            else RetainedEarningsEntryType.NET_LOSS
        )
        entry = RetainedEarningsEntry(
            entry_id=uuid4(),
            period=period,
            entry_type=entry_type,
            net_income=net_income,
            dividends=Decimal("0"),
            adjustment=Decimal("0"),
            amount=net_income,
            balance_after=self.current_balance + net_income,
            description=description
            or f"{'Net income' if net_income > 0 else 'Net loss'} for period {period}",
            reference_id=reference_id,
            created_by=created_by,
        )
        new_entity = self._add_entry(entry)
        new_entity._record_audit(
            "ADD_NET_INCOME", created_by, {"period": period, "amount": str(net_income)}
        )
        return new_entity

    def record_dividend(
        self,
        dividend_amount: Decimal,
        period: str,
        created_by: str,
        description: str = "",
        reference_id: str | None = None,
    ) -> RetainedEarningsEntity:
        if dividend_amount <= 0:
            raise RetainedEarningsError("Dividend amount must be positive")
        if dividend_amount > self.current_balance:
            raise InsufficientRetainedEarningsError(
                f"Cannot record dividend of {dividend_amount} when retained earnings is {self.current_balance}"
            )
        entry = RetainedEarningsEntry(
            entry_id=uuid4(),
            period=period,
            entry_type=RetainedEarningsEntryType.DIVIDEND,
            net_income=Decimal("0"),
            dividends=dividend_amount,
            adjustment=Decimal("0"),
            amount=-dividend_amount,
            balance_after=self.current_balance - dividend_amount,
            description=description or f"Dividend payment for period {period}",
            reference_id=reference_id,
            created_by=created_by,
        )
        new_entity = self._add_entry(entry)
        new_entity._record_audit(
            "RECORD_DIVIDEND", created_by, {"period": period, "amount": str(dividend_amount)}
        )
        return new_entity

    def add_prior_period_adjustment(
        self,
        adjustment: Decimal,
        period: str,
        created_by: str,
        description: str = "",
        reference_id: str | None = None,
    ) -> RetainedEarningsEntity:
        if adjustment == 0:
            return self
        entry = RetainedEarningsEntry(
            entry_id=uuid4(),
            period=period,
            entry_type=RetainedEarningsEntryType.PRIOR_PERIOD_ADJUSTMENT,
            net_income=Decimal("0"),
            dividends=Decimal("0"),
            adjustment=adjustment,
            amount=adjustment,
            balance_after=self.current_balance + adjustment,
            description=description or f"Prior period adjustment for {period}",
            reference_id=reference_id,
            created_by=created_by,
        )
        new_entity = self._add_entry(entry)
        new_entity._record_audit(
            "ADD_ADJUSTMENT", created_by, {"period": period, "amount": str(adjustment)}
        )
        return new_entity

    def transfer_to_reserve(
        self, amount: Decimal, period: str, created_by: str, description: str = ""
    ) -> RetainedEarningsEntity:
        if amount <= 0:
            raise RetainedEarningsError("Transfer amount must be positive")
        if amount > self.current_balance:
            raise InsufficientRetainedEarningsError(
                f"Cannot transfer {amount} when retained earnings is {self.current_balance}"
            )
        entry = RetainedEarningsEntry(
            entry_id=uuid4(),
            period=period,
            entry_type=RetainedEarningsEntryType.TRANSFER_TO_RESERVE,
            net_income=Decimal("0"),
            dividends=Decimal("0"),
            adjustment=Decimal("0"),
            amount=-amount,
            balance_after=self.current_balance - amount,
            description=description or f"Transfer to reserve fund - {period}",
            created_by=created_by,
        )
        new_entity = self._add_entry(entry)
        new_entity._record_audit(
            "TRANSFER_TO_RESERVE", created_by, {"period": period, "amount": str(amount)}
        )
        return new_entity

    def transfer_from_reserve(
        self, amount: Decimal, period: str, created_by: str, description: str = ""
    ) -> RetainedEarningsEntity:
        if amount <= 0:
            raise RetainedEarningsError("Transfer amount must be positive")
        entry = RetainedEarningsEntry(
            entry_id=uuid4(),
            period=period,
            entry_type=RetainedEarningsEntryType.TRANSFER_FROM_RESERVE,
            net_income=Decimal("0"),
            dividends=Decimal("0"),
            adjustment=Decimal("0"),
            amount=amount,
            balance_after=self.current_balance + amount,
            description=description or f"Transfer from reserve fund - {period}",
            created_by=created_by,
        )
        new_entity = self._add_entry(entry)
        new_entity._record_audit(
            "TRANSFER_FROM_RESERVE", created_by, {"period": period, "amount": str(amount)}
        )
        return new_entity

    # ==================== QUERY METHODS ====================

    def get_entry_by_period(self, period: str) -> RetainedEarningsEntry | None:
        for entry in self.entries:
            if entry.period == period:
                return entry
        return None

    def get_entries_by_type(
        self, entry_type: RetainedEarningsEntryType
    ) -> list[RetainedEarningsEntry]:
        return [e for e in self.entries if e.entry_type == entry_type]

    def get_entries_by_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> list[RetainedEarningsEntry]:
        return [e for e in self.entries if start_date <= e.created_at <= end_date]

    def get_balance_at_period(self, period: str) -> Decimal:
        balance = self.opening_balance
        for entry in self.entries:
            balance += entry.amount
            if entry.period == period:
                return balance
        return balance

    # ==================== PRIVATE HELPERS ====================

    def _copy(self) -> RetainedEarningsEntity:
        return RetainedEarningsEntity(
            retained_earnings_id=self.retained_earnings_id,
            legal_entity_id=self.legal_entity_id,
            opening_balance=self.opening_balance,
            current_balance=self.current_balance,
            entries=self.entries.copy(),
            currency=self.currency,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
            metadata=self.metadata.copy(),
        )


# ============================================================================
# Repository Implementation (Real)
# ============================================================================


class RetainedEarningsRepository:
    _storage: ClassVar[dict[UUID, RetainedEarningsEntity]] = {}

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> RetainedEarningsEntity | None:
        for re in cls._storage.values():
            if re.legal_entity_id == legal_entity_id:
                return re
        return None

    @classmethod
    async def get_by_id(cls, retained_earnings_id: UUID) -> RetainedEarningsEntity | None:
        return cls._storage.get(retained_earnings_id)

    @classmethod
    async def get_all(cls) -> list[RetainedEarningsEntity]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, retained_earnings: RetainedEarningsEntity) -> None:
        cls._storage[retained_earnings.retained_earnings_id] = retained_earnings

    @classmethod
    async def update(cls, retained_earnings: RetainedEarningsEntity) -> None:
        cls._storage[retained_earnings.retained_earnings_id] = retained_earnings

    @classmethod
    async def delete(cls, retained_earnings_id: UUID) -> None:
        cls._storage.pop(retained_earnings_id, None)

    @classmethod
    async def exists(cls, retained_earnings_id: UUID) -> bool:
        return retained_earnings_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list_all(cls, limit: int = 100, offset: int = 0) -> list[RetainedEarningsEntity]:
        entities = list(cls._storage.values())
        return entities[offset : offset + limit]

    @classmethod
    async def paginate(
        cls, page: int = 1, per_page: int = 20
    ) -> tuple[list[RetainedEarningsEntity], int]:
        entities = list(cls._storage.values())
        total = len(entities)
        start = (page - 1) * per_page
        end = start + per_page
        return entities[start:end], total

    @classmethod
    async def search(
        cls, query: str, fields: list[str] | None = None
    ) -> list[RetainedEarningsEntity]:
        if fields is None:
            fields = ["retained_earnings_id", "legal_entity_id"]
        query_lower = query.lower()
        results = []
        for re in cls._storage.values():
            for field_name in fields:
                value = getattr(re, field_name, "")
                if value and query_lower in str(value).lower():
                    results.append(re)
                    break
        return results

    @classmethod
    async def lock(
        cls, retained_earnings_id: UUID, locked_by: str, reason: str
    ) -> RetainedEarningsEntity:
        re = await cls.get_by_id(retained_earnings_id)
        if not re:
            raise ValueError(f"Retained earnings {retained_earnings_id} not found")
        locked = re.lock(locked_by, reason)
        await cls.save(locked)
        return locked

    @classmethod
    async def unlock(cls, retained_earnings_id: UUID, unlocked_by: str) -> RetainedEarningsEntity:
        re = await cls.get_by_id(retained_earnings_id)
        if not re:
            raise ValueError(f"Retained earnings {retained_earnings_id} not found")
        unlocked = re.unlock(unlocked_by)
        await cls.save(unlocked)
        return unlocked

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_retained_earnings_after_period(
    opening_balance: Decimal, net_income: Decimal, dividends: Decimal
) -> Decimal:
    return opening_balance + net_income - dividends


def format_retained_earnings(balance: Decimal, currency: str = "IDR") -> str:
    return f"{currency} {balance:,.2f}"


__all__ = [
    "DuplicatePeriodError",
    "InsufficientRetainedEarningsError",
    "RetainedEarningsEntity",
    "RetainedEarningsEntry",
    "RetainedEarningsEntryType",
    "RetainedEarningsError",
    "RetainedEarningsPeriod",
    "RetainedEarningsRepository",
    "calculate_retained_earnings_after_period",
    "format_retained_earnings",
]
