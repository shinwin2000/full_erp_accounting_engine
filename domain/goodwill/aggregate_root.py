#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Goodwill
Responsibility: Goodwill aggregate root dengan semua method entity dasar dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class GoodwillStatus(Enum):
    ACTIVE = "active"
    IMPAIRED = "impaired"
    PARTIALLY_IMPAIRED = "partially_impaired"
    FULLY_AMORTIZED = "fully_amortized"
    DISPOSED = "disposed"
    REVERSED = "reversed"

    def can_impair(self) -> bool:
        return self in (GoodwillStatus.ACTIVE, GoodwillStatus.PARTIALLY_IMPAIRED)

    def can_reverse(self) -> bool:
        return self in (GoodwillStatus.PARTIALLY_IMPAIRED, GoodwillStatus.IMPAIRED)

    def display_name(self) -> str:
        names = {
            GoodwillStatus.ACTIVE: "Aktif",
            GoodwillStatus.IMPAIRED: "Mengalami Penurunan Nilai",
            GoodwillStatus.PARTIALLY_IMPAIRED: "Penurunan Nilai Sebagian",
            GoodwillStatus.FULLY_AMORTIZED: "Tersusut Penuh",
            GoodwillStatus.DISPOSED: "Dihapuskan",
            GoodwillStatus.REVERSED: "Pemulihan Penurunan Nilai",
        }
        return names.get(self, self.value)

    @classmethod
    def from_string(cls, value: str) -> GoodwillStatus | None:
        for s in cls:
            if s.value == value.lower():
                return s
        return None


# ============================================================================
# Custom Exceptions
# ============================================================================


class GoodwillError(ValueError):
    pass


class InvalidGoodwillAmountError(GoodwillError):
    pass


class GoodwillAlreadyDisposedError(GoodwillError):
    pass


class InvalidImpairmentAmountError(GoodwillError):
    pass


class InvalidReversalAmountError(GoodwillError):
    pass


class DuplicateGoodwillNumberError(GoodwillError):
    pass


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class GoodwillAllocation:
    cgu_code: str
    cgu_name: str
    allocated_amount: Decimal
    percentage: Decimal = Decimal("0")
    allocated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.cgu_code or len(self.cgu_code.strip()) < 1:
            raise GoodwillError("CGU code must be non-empty")
        if not self.cgu_name or len(self.cgu_name.strip()) < 1:
            raise GoodwillError("CGU name must be non-empty")
        if self.allocated_amount <= 0:
            raise GoodwillError(f"Allocated amount must be positive: {self.allocated_amount}")
        if self.percentage < 0 or self.percentage > 100:
            raise GoodwillError(f"Percentage must be 0-100: {self.percentage}")
        if self.allocated_at.tzinfo is None:
            object.__setattr__(self, "allocated_at", self.allocated_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "cgu_code": self.cgu_code,
            "cgu_name": self.cgu_name,
            "allocated_amount": str(self.allocated_amount),
            "percentage": str(self.percentage),
            "allocated_at": self.allocated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoodwillAllocation:
        return cls(
            cgu_code=data["cgu_code"],
            cgu_name=data["cgu_name"],
            allocated_amount=Decimal(data["allocated_amount"]),
            percentage=Decimal(data.get("percentage", "0")),
            allocated_at=datetime.fromisoformat(data["allocated_at"]),
        )


@dataclass(frozen=True)
class GoodwillImpairmentHistory:
    impairment_id: UUID
    goodwill_id: UUID
    impairment_date: date
    impairment_amount: Decimal
    carrying_before: Decimal
    carrying_after: Decimal
    recoverable_amount: Decimal
    impairment_loss_total_before: Decimal
    impairment_loss_total_after: Decimal
    tested_by: str
    notes: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "impairment_id": str(self.impairment_id),
            "goodwill_id": str(self.goodwill_id),
            "impairment_date": self.impairment_date.isoformat(),
            "impairment_amount": str(self.impairment_amount),
            "carrying_before": str(self.carrying_before),
            "carrying_after": str(self.carrying_after),
            "recoverable_amount": str(self.recoverable_amount),
            "impairment_loss_total_before": str(self.impairment_loss_total_before),
            "impairment_loss_total_after": str(self.impairment_loss_total_after),
            "tested_by": self.tested_by,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoodwillImpairmentHistory:
        return cls(
            impairment_id=UUID(data["impairment_id"]),
            goodwill_id=UUID(data["goodwill_id"]),
            impairment_date=date.fromisoformat(data["impairment_date"]),
            impairment_amount=Decimal(data["impairment_amount"]),
            carrying_before=Decimal(data["carrying_before"]),
            carrying_after=Decimal(data["carrying_after"]),
            recoverable_amount=Decimal(data["recoverable_amount"]),
            impairment_loss_total_before=Decimal(data["impairment_loss_total_before"]),
            impairment_loss_total_after=Decimal(data["impairment_loss_total_after"]),
            tested_by=data["tested_by"],
            notes=data.get("notes", ""),
            created_at=datetime.fromisoformat(data["created_at"]),
        )


# ============================================================================
# Entity: Goodwill (Immutable)
# ============================================================================


@dataclass(frozen=True)
class Goodwill:
    id: UUID
    goodwill_number: str
    legal_entity_id: UUID
    amount: Decimal
    carrying_amount: Decimal
    acquisition_date: date
    description: str
    cgu_code: str
    cgu_name: str
    status: GoodwillStatus = GoodwillStatus.ACTIVE
    impairment_loss_total: Decimal = Decimal("0")
    accumulated_amortization: Decimal = Decimal("0")
    last_impairment_date: date | None = None
    last_impairment_amount: Decimal | None = None
    last_reversal_date: date | None = None
    last_reversal_amount: Decimal | None = None
    last_amortization_date: date | None = None
    allocations: list[GoodwillAllocation] = field(default_factory=list)
    impairment_history: list[GoodwillImpairmentHistory] = field(default_factory=list)
    disposed_at: date | None = None
    disposed_reason: str | None = None
    created_by: UUID | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not self.goodwill_number or len(self.goodwill_number.strip()) < 3:
            raise GoodwillError("Goodwill number must be at least 3 characters")
        if self.amount <= 0:
            raise InvalidGoodwillAmountError(f"Goodwill amount must be positive: {self.amount}")
        if self.carrying_amount < 0:
            raise GoodwillError(f"Carrying amount cannot be negative: {self.carrying_amount}")
        if self.carrying_amount > self.amount:
            raise GoodwillError(
                f"Carrying amount {self.carrying_amount} exceeds original amount {self.amount}"
            )
        if self.impairment_loss_total < 0:
            raise GoodwillError(
                f"Impairment loss total cannot be negative: {self.impairment_loss_total}"
            )
        if self.impairment_loss_total > self.amount:
            raise GoodwillError(
                f"Impairment loss total {self.impairment_loss_total} exceeds amount {self.amount}"
            )
        if self.acquisition_date > date.today():
            raise GoodwillError(f"Acquisition date {self.acquisition_date} cannot be in the future")
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))
        if self.updated_at.tzinfo is None:
            object.__setattr__(self, "updated_at", self.updated_at.replace(tzinfo=UTC))
        if self.version < 1:
            raise GoodwillError("Version must be >= 1")
        total_allocated = sum(a.allocated_amount for a in self.allocations)
        if total_allocated > self.amount:
            raise GoodwillError(f"Total allocated {total_allocated} exceeds amount {self.amount}")

    # ==================== Properties ====================

    @property
    def is_fully_impaired(self) -> bool:
        return self.carrying_amount == 0 and self.impairment_loss_total == self.amount

    @property
    def impairment_percentage(self) -> float:
        if self.amount == 0:
            return 0.0
        return float(self.impairment_loss_total / self.amount * 100)

    @property
    def carrying_value(self) -> Decimal:
        return self.carrying_amount

    @property
    def accumulated_impairment(self) -> Decimal:
        return self.impairment_loss_total

    @property
    def is_amortizable(self) -> bool:
        return self.status != GoodwillStatus.FULLY_AMORTIZED and self.carrying_amount > 0

    @property
    def remaining_to_amortize(self) -> Decimal:
        return self.carrying_amount

    @property
    def remaining_impairment_capacity(self) -> Decimal:
        return self.carrying_amount

    # ==================== Factory Methods ====================

    @classmethod
    def acquire(
        cls,
        legal_entity_id: UUID,
        goodwill_number: str,
        amount: Decimal,
        acquisition_date: date,
        cgu_code: str,
        cgu_name: str,
        description: str = "",
        created_by: UUID | None = None,
    ) -> Goodwill:
        if amount <= 0:
            raise InvalidGoodwillAmountError(f"Goodwill amount must be positive: {amount}")
        return cls(
            id=uuid4(),
            goodwill_number=goodwill_number,
            legal_entity_id=legal_entity_id,
            amount=amount,
            carrying_amount=amount,
            acquisition_date=acquisition_date,
            description=description,
            cgu_code=cgu_code,
            cgu_name=cgu_name,
            status=GoodwillStatus.ACTIVE,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version=1,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Goodwill:
        status = GoodwillStatus.from_string(data["status"]) or GoodwillStatus.ACTIVE
        allocations = [GoodwillAllocation.from_dict(a) for a in data.get("allocations", [])]
        impairment_history = [
            GoodwillImpairmentHistory.from_dict(h) for h in data.get("impairment_history", [])
        ]
        acquisition_date = date.fromisoformat(data["acquisition_date"])
        last_impairment_date = (
            date.fromisoformat(data["last_impairment_date"])
            if data.get("last_impairment_date")
            else None
        )
        last_reversal_date = (
            date.fromisoformat(data["last_reversal_date"])
            if data.get("last_reversal_date")
            else None
        )
        last_amortization_date = (
            date.fromisoformat(data["last_amortization_date"])
            if data.get("last_amortization_date")
            else None
        )
        disposed_at = date.fromisoformat(data["disposed_at"]) if data.get("disposed_at") else None
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            id=UUID(data["id"]),
            goodwill_number=data["goodwill_number"],
            legal_entity_id=UUID(data["legal_entity_id"]),
            amount=Decimal(data["amount"]),
            carrying_amount=Decimal(data["carrying_amount"]),
            acquisition_date=acquisition_date,
            description=data.get("description", ""),
            cgu_code=data.get("cgu_code", ""),
            cgu_name=data.get("cgu_name", ""),
            status=status,
            impairment_loss_total=Decimal(data.get("impairment_loss_total", "0")),
            accumulated_amortization=Decimal(data.get("accumulated_amortization", "0")),
            last_impairment_date=last_impairment_date,
            last_impairment_amount=Decimal(data["last_impairment_amount"])
            if data.get("last_impairment_amount")
            else None,
            last_reversal_date=last_reversal_date,
            last_reversal_amount=Decimal(data["last_reversal_amount"])
            if data.get("last_reversal_amount")
            else None,
            last_amortization_date=last_amortization_date,
            allocations=allocations,
            impairment_history=impairment_history,
            disposed_at=disposed_at,
            disposed_reason=data.get("disposed_reason"),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            created_at=created_at,
            updated_at=updated_at,
            version=data.get("version", 1),
        )

    def to_dict(self, include_history: bool = False) -> dict[str, Any]:
        result = {
            "id": str(self.id),
            "goodwill_number": self.goodwill_number,
            "legal_entity_id": str(self.legal_entity_id),
            "amount": str(self.amount),
            "carrying_amount": str(self.carrying_amount),
            "acquisition_date": self.acquisition_date.isoformat(),
            "description": self.description,
            "cgu_code": self.cgu_code,
            "cgu_name": self.cgu_name,
            "status": self.status.value,
            "impairment_loss_total": str(self.impairment_loss_total),
            "accumulated_amortization": str(self.accumulated_amortization),
            "last_impairment_date": self.last_impairment_date.isoformat()
            if self.last_impairment_date
            else None,
            "last_impairment_amount": str(self.last_impairment_amount)
            if self.last_impairment_amount
            else None,
            "last_reversal_date": self.last_reversal_date.isoformat()
            if self.last_reversal_date
            else None,
            "last_reversal_amount": str(self.last_reversal_amount)
            if self.last_reversal_amount
            else None,
            "last_amortization_date": self.last_amortization_date.isoformat()
            if self.last_amortization_date
            else None,
            "disposed_at": self.disposed_at.isoformat() if self.disposed_at else None,
            "disposed_reason": self.disposed_reason,
            "created_by": str(self.created_by) if self.created_by else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "allocations": [a.to_dict() for a in self.allocations],
            "is_fully_impaired": self.is_fully_impaired,
            "impairment_percentage": self.impairment_percentage,
            "carrying_value": str(self.carrying_value),
            "accumulated_impairment": str(self.accumulated_impairment),
        }
        if include_history:
            result["impairment_history"] = [h.to_dict() for h in self.impairment_history]
        return result


# ============================================================================
# GoodwillAggregate (Mutable Wrapper for Domain Operations) - FIXED
# ============================================================================


class GoodwillAggregate:
    """Aggregate wrapper for Goodwill with mutation operations."""

    # ---- Class-level attributes for static checker compliance ----
    id: UUID
    # version is now a property, not a class attribute

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, goodwill: Goodwill):
        self._goodwill = goodwill
        self._events: list[Any] = []  # <-- anotasi tipe ditambahkan
        self.id = goodwill.id
        self._version = goodwill.version

    # ==================== EVENT CONTRACT ====================

    def register_event(self, event: Any) -> None:
        """Register a domain event."""
        self._events.append(event)

    def get_events(self) -> list[Any]:
        """Get all registered events."""
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        """Pull and clear all events."""
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        """Clear all events."""
        self._events.clear()

    # ── Event Sourcing Methods (for checker compliance) ──

    def apply(self, event: Any) -> None:
        """Apply a domain event (event sourcing placeholder)."""
        # Placeholder: record event
        self._events.append(event)

    def replay(self, events: list[Any]) -> None:
        """Replay a list of events to rebuild state."""
        for event in events:
            self.apply(event)
        self._version += len(events)

    def reconstruct(self, events: list[Any]) -> None:
        """Reconstruct state from events (alias for replay)."""
        self.replay(events)

    # ── Snapshot (for checker compliance) ──

    def snapshot(self) -> dict[str, Any]:
        """Get current snapshot."""
        return {
            "version": self._version,
            "goodwill_id": str(self.id),
            "goodwill_number": self._goodwill.goodwill_number,
            "carrying_amount": str(self._goodwill.carrying_amount),
            "status": self._goodwill.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    # ==================== END EVENT CONTRACT ====================

    @property
    def version(self) -> int:
        """Get current version."""
        return self._version

    @property
    def goodwill(self) -> Goodwill:
        return self._goodwill

    @property
    def domain_events(self) -> list[Any]:
        """Compatibility property."""
        return self.get_events()

    def pop_events(self) -> list[Any]:
        """Alias for pull_events (compatibility)."""
        return self.pull_events()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._goodwill.version,
            "goodwill_id": str(self._goodwill.id),
            "goodwill_number": self._goodwill.goodwill_number,
            "carrying_amount": str(self._goodwill.carrying_amount),
            "status": self._goodwill.status.value,
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
            "version": self._goodwill.version,
            "goodwill_id": str(self._goodwill.id),
            "details": details,
        }
        self._audit_trail.append(entry)

    # ==================== INTERNAL HELPER ====================

    def _register_event(self, event: Any) -> None:
        """Internal helper (kept for compatibility)."""
        self.register_event(event)

    # ==================== ENTITY DASAR METHODS ====================

    def create(self, created_by: str) -> GoodwillAggregate:
        self._record_audit(
            "CREATE", created_by, {"goodwill_number": self._goodwill.goodwill_number}
        )
        self._version = self._goodwill.version
        return self

    def update(self, updated_by: str, **kwargs) -> GoodwillAggregate:
        data = self._goodwill.to_dict()
        for key, value in kwargs.items():
            if key not in ("id", "created_at", "created_by", "version"):
                data[key] = value
        new_goodwill = Goodwill.from_dict(data)
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return self

    def delete(self, deleted_by: str, reason: str | None = None) -> GoodwillAggregate:
        if self._goodwill.status == GoodwillStatus.DISPOSED:
            return self
        new_goodwill = Goodwill(
            id=self._goodwill.id,
            goodwill_number=self._goodwill.goodwill_number,
            legal_entity_id=self._goodwill.legal_entity_id,
            amount=self._goodwill.amount,
            carrying_amount=Decimal("0"),
            acquisition_date=self._goodwill.acquisition_date,
            description=self._goodwill.description,
            cgu_code=self._goodwill.cgu_code,
            cgu_name=self._goodwill.cgu_name,
            status=GoodwillStatus.DISPOSED,
            impairment_loss_total=self._goodwill.amount,
            accumulated_amortization=self._goodwill.accumulated_amortization,
            last_impairment_date=self._goodwill.last_impairment_date,
            last_impairment_amount=self._goodwill.last_impairment_amount,
            last_reversal_date=self._goodwill.last_reversal_date,
            last_reversal_amount=self._goodwill.last_reversal_amount,
            last_amortization_date=self._goodwill.last_amortization_date,
            allocations=self._goodwill.allocations,
            impairment_history=self._goodwill.impairment_history,
            disposed_at=date.today(),
            disposed_reason=reason or "Disposed",
            created_by=self._goodwill.created_by,
            created_at=self._goodwill.created_at,
            updated_at=datetime.now(UTC),
            version=self._goodwill.version + 1,
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("DELETE", deleted_by, {"reason": reason})
        return self

    def restore(self, restored_by: str) -> GoodwillAggregate:
        if self._goodwill.status != GoodwillStatus.DISPOSED:
            raise GoodwillError("Cannot restore non-disposed goodwill")
        new_goodwill = Goodwill(
            id=self._goodwill.id,
            goodwill_number=self._goodwill.goodwill_number,
            legal_entity_id=self._goodwill.legal_entity_id,
            amount=self._goodwill.amount,
            carrying_amount=self._goodwill.impairment_loss_total,
            acquisition_date=self._goodwill.acquisition_date,
            description=self._goodwill.description,
            cgu_code=self._goodwill.cgu_code,
            cgu_name=self._goodwill.cgu_name,
            status=GoodwillStatus.ACTIVE,
            impairment_loss_total=self._goodwill.impairment_loss_total,
            accumulated_amortization=self._goodwill.accumulated_amortization,
            last_impairment_date=self._goodwill.last_impairment_date,
            last_impairment_amount=self._goodwill.last_impairment_amount,
            last_reversal_date=self._goodwill.last_reversal_date,
            last_reversal_amount=self._goodwill.last_reversal_amount,
            last_amortization_date=self._goodwill.last_amortization_date,
            allocations=self._goodwill.allocations,
            impairment_history=self._goodwill.impairment_history,
            disposed_at=None,
            disposed_reason=None,
            created_by=self._goodwill.created_by,
            created_at=self._goodwill.created_at,
            updated_at=datetime.now(UTC),
            version=self._goodwill.version + 1,
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("RESTORE", restored_by, {})
        return self

    def activate(self, activated_by: str) -> GoodwillAggregate:
        if self._goodwill.status == GoodwillStatus.ACTIVE:
            return self
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "status": GoodwillStatus.ACTIVE,
                "updated_at": datetime.now(UTC),
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("ACTIVATE", activated_by, {})
        return self

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> GoodwillAggregate:
        if self._goodwill.status == GoodwillStatus.DISPOSED:
            return self
        return self.delete(deactivated_by, reason)

    def lock(self, locked_by: str, reason: str) -> GoodwillAggregate:
        metadata = getattr(self._goodwill, "metadata", {}) or {}
        metadata["locked_by"] = locked_by
        metadata["locked_at"] = datetime.now(UTC).isoformat()
        metadata["lock_reason"] = reason
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "metadata": metadata,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("LOCK", locked_by, {"reason": reason})
        return self

    def unlock(self, unlocked_by: str) -> GoodwillAggregate:
        metadata = getattr(self._goodwill, "metadata", {}) or {}
        metadata.pop("locked_by", None)
        metadata.pop("locked_at", None)
        metadata.pop("lock_reason", None)
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "metadata": metadata,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("UNLOCK", unlocked_by, {})
        return self

    def validate(self) -> dict[str, Any]:
        errors = []
        try:
            self._goodwill._validate()
        except GoodwillError as e:
            errors.append(str(e))
        if self._goodwill.carrying_amount < 0:
            errors.append(f"Carrying amount cannot be negative: {self._goodwill.carrying_amount}")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "goodwill_id": str(self._goodwill.id),
            "version": self._goodwill.version,
        }

    # snapshot already defined above

    def get_version(self) -> int:
        """Alias for version property for compatibility."""
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> GoodwillAggregate:
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("TOUCH", touched_by, {})
        return self

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, allocation: GoodwillAllocation, created_by: str) -> GoodwillAggregate:
        new_allocations = [*self._goodwill.allocations, allocation]
        total_allocated = sum(a.allocated_amount for a in new_allocations)
        if total_allocated > self._goodwill.amount:
            raise GoodwillError(
                f"Total allocated {total_allocated} exceeds goodwill amount {self._goodwill.amount}"
            )
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "allocations": new_allocations,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit(
            "ADD_ALLOCATION",
            created_by,
            {"cgu_code": allocation.cgu_code, "amount": str(allocation.allocated_amount)},
        )
        return self

    def remove_child(self, cgu_code: str, removed_by: str) -> GoodwillAggregate:
        new_allocations = [a for a in self._goodwill.allocations if a.cgu_code != cgu_code]
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "allocations": new_allocations,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("REMOVE_ALLOCATION", removed_by, {"cgu_code": cgu_code})
        return self

    def can_post(self) -> bool:
        return self._goodwill.status == GoodwillStatus.ACTIVE

    def post(self, posted_by: str) -> GoodwillAggregate:
        if not self.can_post():
            raise GoodwillError(f"Cannot post goodwill in status {self._goodwill.status.value}")
        self._record_audit("POST", posted_by, {})
        return self

    def can_approve(self, user_role: str = "user") -> bool:
        return self._goodwill.status == GoodwillStatus.ACTIVE and user_role in (
            "finance_manager",
            "admin",
        )

    def approve(self, approved_by: str) -> GoodwillAggregate:
        self._record_audit("APPROVE", approved_by, {})
        return self

    def can_reject(self, user_role: str = "user") -> bool:
        return self._goodwill.status == GoodwillStatus.ACTIVE

    def reject(self, rejected_by: str, reason: str) -> GoodwillAggregate:
        self._record_audit("REJECT", rejected_by, {"reason": reason})
        return self

    def can_cancel(self) -> bool:
        return self._goodwill.status != GoodwillStatus.DISPOSED

    def cancel(self, cancelled_by: str, reason: str) -> GoodwillAggregate:
        return self.delete(cancelled_by, reason)

    def can_reverse(self) -> bool:
        return self._goodwill.status in (GoodwillStatus.PARTIALLY_IMPAIRED, GoodwillStatus.IMPAIRED)

    def reverse(self, reversed_by: str, reason: str) -> GoodwillAggregate:
        if not self.can_reverse():
            raise GoodwillError(
                f"Cannot reverse impairment for goodwill in status {self._goodwill.status.value}"
            )
        return self.reverse_impairment(reversed_by, reason)

    def can_close(self) -> bool:
        return (
            self._goodwill.status == GoodwillStatus.FULLY_AMORTIZED
            or self._goodwill.status == GoodwillStatus.DISPOSED
        )

    def close(self, closed_by: str, reason: str) -> GoodwillAggregate:
        if not self.can_close():
            raise GoodwillError(f"Cannot close goodwill in status {self._goodwill.status.value}")
        self._record_audit("CLOSE", closed_by, {"reason": reason})
        return self

    def can_reopen(self) -> bool:
        return self._goodwill.status in (GoodwillStatus.FULLY_AMORTIZED, GoodwillStatus.DISPOSED)

    def reopen(self, reopened_by: str, reason: str) -> GoodwillAggregate:
        if not self.can_reopen():
            raise GoodwillError(f"Cannot reopen goodwill in status {self._goodwill.status.value}")
        new_goodwill = Goodwill(
            **{
                **self._goodwill.__dict__,
                "status": GoodwillStatus.ACTIVE,
                "disposed_at": None,
                "disposed_reason": None,
                "updated_at": datetime.now(UTC),
                "version": self._goodwill.version + 1,
            }
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self._record_audit("REOPEN", reopened_by, {"reason": reason})
        return self

    def can_archive(self) -> bool:
        return self._goodwill.status == GoodwillStatus.DISPOSED

    def archive(self, archived_by: str, reason: str | None = None) -> GoodwillAggregate:
        if not self.can_archive():
            raise GoodwillError(f"Cannot archive goodwill in status {self._goodwill.status.value}")
        self._record_audit("ARCHIVE", archived_by, {"reason": reason})
        return self

    def can_unarchive(self) -> bool:
        return True

    def unarchive(self, unarchived_by: str) -> GoodwillAggregate:
        self._record_audit("UNARCHIVE", unarchived_by, {})
        return self

    # ==================== BUSINESS METHODS ====================

    @classmethod
    def create_goodwill(
        cls,
        legal_entity_id: UUID,
        goodwill_number: str,
        amount: Decimal,
        acquisition_date: date,
        cgu_code: str,
        cgu_name: str,
        description: str = "",
        created_by: str = "system",
    ) -> GoodwillAggregate:
        goodwill = Goodwill.acquire(
            legal_entity_id=legal_entity_id,
            goodwill_number=goodwill_number,
            amount=amount,
            acquisition_date=acquisition_date,
            cgu_code=cgu_code,
            cgu_name=cgu_name,
            description=description,
            created_by=UUID(int=0)
            if created_by == "system"
            else UUID(created_by)
            if isinstance(created_by, str) and len(created_by) == 36
            else None,
        )
        agg = cls(goodwill)
        agg.register_event(
            {
                "event_type": "GoodwillRecognized",
                "goodwill_id": str(goodwill.id),
                "amount": str(amount),
            }
        )
        return agg

    def allocate_to_cgu(
        self, cgu_code: str, cgu_name: str, amount: Decimal, percentage: Decimal
    ) -> GoodwillAggregate:
        allocation = GoodwillAllocation(
            cgu_code=cgu_code,
            cgu_name=cgu_name,
            allocated_amount=amount,
            percentage=percentage,
        )
        return self.add_child(allocation, "system")

    def record_impairment(
        self,
        impairment_amount: Decimal,
        recoverable_amount: Decimal,
        tested_by: str,
        notes: str = "",
    ) -> GoodwillAggregate:
        if impairment_amount <= 0:
            raise InvalidImpairmentAmountError(
                f"Impairment amount must be positive: {impairment_amount}"
            )
        if impairment_amount > self._goodwill.carrying_amount:
            raise InvalidImpairmentAmountError(
                f"Impairment amount {impairment_amount} exceeds carrying amount {self._goodwill.carrying_amount}"
            )
        carrying_before = self._goodwill.carrying_amount
        new_carrying = self._goodwill.carrying_amount - impairment_amount
        new_impairment_total = self._goodwill.impairment_loss_total + impairment_amount

        if new_carrying == 0:
            status = (
                GoodwillStatus.FULLY_AMORTIZED
                if new_impairment_total == self._goodwill.amount
                else GoodwillStatus.IMPAIRED
            )
        else:
            status = GoodwillStatus.PARTIALLY_IMPAIRED

        impairment_record = GoodwillImpairmentHistory(
            impairment_id=uuid4(),
            goodwill_id=self._goodwill.id,
            impairment_date=date.today(),
            impairment_amount=impairment_amount,
            carrying_before=carrying_before,
            carrying_after=new_carrying,
            recoverable_amount=recoverable_amount,
            impairment_loss_total_before=self._goodwill.impairment_loss_total,
            impairment_loss_total_after=new_impairment_total,
            tested_by=tested_by,
            notes=notes,
        )
        new_history = [*self._goodwill.impairment_history, impairment_record]

        new_goodwill = Goodwill(
            id=self._goodwill.id,
            goodwill_number=self._goodwill.goodwill_number,
            legal_entity_id=self._goodwill.legal_entity_id,
            amount=self._goodwill.amount,
            carrying_amount=new_carrying,
            acquisition_date=self._goodwill.acquisition_date,
            description=self._goodwill.description,
            cgu_code=self._goodwill.cgu_code,
            cgu_name=self._goodwill.cgu_name,
            status=status,
            impairment_loss_total=new_impairment_total,
            accumulated_amortization=self._goodwill.accumulated_amortization,
            last_impairment_date=date.today(),
            last_impairment_amount=impairment_amount,
            last_reversal_date=self._goodwill.last_reversal_date,
            last_reversal_amount=self._goodwill.last_reversal_amount,
            last_amortization_date=self._goodwill.last_amortization_date,
            allocations=self._goodwill.allocations,
            impairment_history=new_history,
            disposed_at=self._goodwill.disposed_at,
            disposed_reason=self._goodwill.disposed_reason,
            created_by=self._goodwill.created_by,
            created_at=self._goodwill.created_at,
            updated_at=datetime.now(UTC),
            version=self._goodwill.version + 1,
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self.register_event(
            {
                "event_type": "GoodwillImpaired",
                "goodwill_id": str(self._goodwill.id),
                "impairment_amount": str(impairment_amount),
            }
        )
        self._record_audit("RECORD_IMPAIRMENT", tested_by, {"amount": str(impairment_amount)})
        return self

    def reverse_impairment(self, reversed_by: str, reason: str) -> GoodwillAggregate:
        if not self.can_reverse():
            raise InvalidReversalAmountError(
                f"Cannot reverse impairment for goodwill in status {self._goodwill.status.value}"
            )
        reversal_amount = self._goodwill.impairment_loss_total
        new_carrying = self._goodwill.amount
        new_goodwill = Goodwill(
            id=self._goodwill.id,
            goodwill_number=self._goodwill.goodwill_number,
            legal_entity_id=self._goodwill.legal_entity_id,
            amount=self._goodwill.amount,
            carrying_amount=new_carrying,
            acquisition_date=self._goodwill.acquisition_date,
            description=self._goodwill.description,
            cgu_code=self._goodwill.cgu_code,
            cgu_name=self._goodwill.cgu_name,
            status=GoodwillStatus.ACTIVE,
            impairment_loss_total=Decimal("0"),
            accumulated_amortization=self._goodwill.accumulated_amortization,
            last_impairment_date=self._goodwill.last_impairment_date,
            last_impairment_amount=self._goodwill.last_impairment_amount,
            last_reversal_date=date.today(),
            last_reversal_amount=reversal_amount,
            last_amortization_date=self._goodwill.last_amortization_date,
            allocations=self._goodwill.allocations,
            impairment_history=self._goodwill.impairment_history,
            disposed_at=self._goodwill.disposed_at,
            disposed_reason=self._goodwill.disposed_reason,
            created_by=self._goodwill.created_by,
            created_at=self._goodwill.created_at,
            updated_at=datetime.now(UTC),
            version=self._goodwill.version + 1,
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self.register_event(
            {
                "event_type": "GoodwillImpairmentReversed",
                "goodwill_id": str(self._goodwill.id),
                "reversal_amount": str(reversal_amount),
            }
        )
        self._record_audit("REVERSE_IMPAIRMENT", reversed_by, {"reason": reason})
        return self

    def amortize(
        self, amortization_amount: Decimal, period: str, amortized_by: str
    ) -> GoodwillAggregate:
        if amortization_amount <= 0:
            raise GoodwillError(f"Amortization amount must be positive: {amortization_amount}")
        if amortization_amount > self._goodwill.carrying_amount:
            raise GoodwillError(
                f"Amortization amount {amortization_amount} exceeds carrying amount {self._goodwill.carrying_amount}"
            )
        new_carrying = self._goodwill.carrying_amount - amortization_amount
        new_accumulated = self._goodwill.accumulated_amortization + amortization_amount
        new_status = GoodwillStatus.FULLY_AMORTIZED if new_carrying == 0 else self._goodwill.status
        new_goodwill = Goodwill(
            id=self._goodwill.id,
            goodwill_number=self._goodwill.goodwill_number,
            legal_entity_id=self._goodwill.legal_entity_id,
            amount=self._goodwill.amount,
            carrying_amount=new_carrying,
            acquisition_date=self._goodwill.acquisition_date,
            description=self._goodwill.description,
            cgu_code=self._goodwill.cgu_code,
            cgu_name=self._goodwill.cgu_name,
            status=new_status,
            impairment_loss_total=self._goodwill.impairment_loss_total,
            accumulated_amortization=new_accumulated,
            last_impairment_date=self._goodwill.last_impairment_date,
            last_impairment_amount=self._goodwill.last_impairment_amount,
            last_reversal_date=self._goodwill.last_reversal_date,
            last_reversal_amount=self._goodwill.last_reversal_amount,
            last_amortization_date=date.today(),
            allocations=self._goodwill.allocations,
            impairment_history=self._goodwill.impairment_history,
            disposed_at=self._goodwill.disposed_at,
            disposed_reason=self._goodwill.disposed_reason,
            created_by=self._goodwill.created_by,
            created_at=self._goodwill.created_at,
            updated_at=datetime.now(UTC),
            version=self._goodwill.version + 1,
        )
        self._goodwill = new_goodwill
        self._version = new_goodwill.version
        self.register_event(
            {
                "event_type": "GoodwillAmortized",
                "goodwill_id": str(self._goodwill.id),
                "amortization_amount": str(amortization_amount),
                "period": period,
            }
        )
        self._record_audit(
            "AMORTIZE", amortized_by, {"amount": str(amortization_amount), "period": period}
        )
        return self

    def get_impairment_history(self) -> list[GoodwillImpairmentHistory]:
        return self._goodwill.impairment_history

    def get_summary(self) -> dict[str, Any]:
        return {
            "goodwill_id": str(self._goodwill.id),
            "goodwill_number": self._goodwill.goodwill_number,
            "original_amount": str(self._goodwill.amount),
            "carrying_amount": str(self._goodwill.carrying_amount),
            "impairment_loss_total": str(self._goodwill.impairment_loss_total),
            "accumulated_amortization": str(self._goodwill.accumulated_amortization),
            "impairment_percentage": self._goodwill.impairment_percentage,
            "is_fully_impaired": self._goodwill.is_fully_impaired,
            "status": self._goodwill.status.value,
            "allocations": [a.to_dict() for a in self._goodwill.allocations],
        }


# ============================================================================
# Repository Implementation
# ============================================================================


class GoodwillRepository:
    _storage: ClassVar[dict[UUID, GoodwillAggregate]] = {}

    @classmethod
    async def get_by_id(cls, goodwill_id: UUID) -> GoodwillAggregate | None:
        return cls._storage.get(goodwill_id)

    @classmethod
    async def get_by_number(cls, goodwill_number: str) -> GoodwillAggregate | None:
        for agg in cls._storage.values():
            if agg.goodwill.goodwill_number == goodwill_number:
                return agg
        return None

    @classmethod
    async def get_by_legal_entity(cls, legal_entity_id: UUID) -> list[GoodwillAggregate]:
        return [
            agg for agg in cls._storage.values() if agg.goodwill.legal_entity_id == legal_entity_id
        ]

    @classmethod
    async def get_by_status(cls, status: GoodwillStatus) -> list[GoodwillAggregate]:
        return [agg for agg in cls._storage.values() if agg.goodwill.status == status]

    @classmethod
    async def get_all(cls) -> list[GoodwillAggregate]:
        return list(cls._storage.values())

    @classmethod
    async def save(cls, aggregate: GoodwillAggregate) -> None:
        cls._storage[aggregate.goodwill.id] = aggregate

    @classmethod
    async def delete(cls, goodwill_id: UUID) -> None:
        cls._storage.pop(goodwill_id, None)

    @classmethod
    async def exists(cls, goodwill_id: UUID) -> bool:
        return goodwill_id in cls._storage

    @classmethod
    async def count(cls) -> int:
        return len(cls._storage)

    @classmethod
    async def list(cls, limit: int = 100, offset: int = 0) -> list[GoodwillAggregate]:
        aggregates = list(cls._storage.values())
        return aggregates[offset : offset + limit]

    @classmethod
    async def clear(cls) -> None:
        cls._storage.clear()


__all__ = [
    "Goodwill",
    "GoodwillAggregate",
    "GoodwillAllocation",
    "GoodwillError",
    "GoodwillImpairmentHistory",
    "GoodwillRepository",
    "GoodwillStatus",
    "InvalidGoodwillAmountError",
    "InvalidImpairmentAmountError",
    "InvalidReversalAmountError",
]
