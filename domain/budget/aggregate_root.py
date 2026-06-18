#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Budget
Responsibility: Budget aggregate root dengan semua method dasar entity dan aggregate root.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any, ClassVar, Self
from uuid import UUID, uuid4

from .domain_events import (
    BudgetApproved,
    BudgetCreated,
    BudgetLineAdjusted,
    BudgetLineRemoved,
    BudgetRevised,
    BudgetStatusChanged,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Enums
# ============================================================================


class BudgetStatus(Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISED = "revised"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"
    CLOSED = "closed"
    ON_HOLD = "on_hold"

    @classmethod
    def can_transition(cls, from_status: BudgetStatus, to_status: BudgetStatus) -> bool:
        allowed = {
            cls.DRAFT: {cls.SUBMITTED, cls.CANCELLED},
            cls.SUBMITTED: {cls.APPROVED, cls.REJECTED, cls.ON_HOLD},
            cls.APPROVED: {cls.REVISED, cls.CLOSED, cls.ARCHIVED},
            cls.REVISED: {cls.APPROVED, cls.CANCELLED},
            cls.REJECTED: {cls.DRAFT},
            cls.ON_HOLD: {cls.SUBMITTED, cls.CANCELLED},
            cls.CANCELLED: set(),
            cls.CLOSED: {cls.ARCHIVED},
            cls.ARCHIVED: set(),
        }
        return to_status in allowed.get(from_status, set())


class BudgetPeriod(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMESTER = "semester"
    YEARLY = "yearly"
    CUSTOM = "custom"


# ============================================================================
# Value Objects
# ============================================================================


@dataclass(frozen=True)
class BudgetLineItem:
    """Budget line item for an account/period."""

    line_id: UUID
    account_code: str
    account_id: UUID | None
    period: str  # e.g., "2025-01" for monthly, "2025-Q1" for quarterly
    amount: Decimal
    actual_amount: Decimal = Decimal(0)
    description: str = ""
    notes: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def variance(self) -> Decimal:
        return (self.actual_amount - self.amount).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        )

    @property
    def variance_absolute(self) -> Decimal:
        return abs(self.variance)

    @property
    def variance_percentage(self) -> float:
        if self.amount == 0:
            return 0.0 if self.actual_amount == 0 else 100.0
        return float(abs((self.actual_amount - self.amount) / self.amount * 100))

    @property
    def is_favorable(self, is_revenue_account: bool = False) -> bool:
        """Favorable if expense actual < budget, or revenue actual > budget."""
        if is_revenue_account:
            return self.actual_amount > self.amount
        return self.actual_amount < self.amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": str(self.line_id),
            "account_code": self.account_code,
            "account_id": str(self.account_id) if self.account_id else None,
            "period": self.period,
            "amount": str(self.amount),
            "actual_amount": str(self.actual_amount),
            "variance": str(self.variance),
            "variance_percentage": self.variance_percentage,
            "description": self.description,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            line_id=UUID(data["line_id"]),
            account_code=data["account_code"],
            account_id=UUID(data["account_id"]) if data.get("account_id") else None,
            period=data["period"],
            amount=Decimal(data["amount"]),
            actual_amount=Decimal(data.get("actual_amount", "0")),
            description=data.get("description", ""),
            notes=data.get("notes"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
        )


@dataclass
class BudgetLine:
    """Mutable budget line for internal use."""

    line_id: UUID
    account_code: str
    account_id: UUID | None
    period: str
    amount: Decimal
    actual_amount: Decimal = Decimal(0)
    description: str = ""

    @property
    def variance(self) -> Decimal:
        return self.actual_amount - self.amount

    def to_line_item(self) -> BudgetLineItem:
        return BudgetLineItem(
            line_id=self.line_id,
            account_code=self.account_code,
            account_id=self.account_id,
            period=self.period,
            amount=self.amount,
            actual_amount=self.actual_amount,
            description=self.description,
        )


# ============================================================================
# Budget Aggregate Root (Immutable Base)
# ============================================================================


@dataclass(frozen=True)
class Budget:
    """Immutable budget aggregate root."""

    id: UUID
    legal_entity_id: UUID
    name: str
    year: int
    status: BudgetStatus
    lines: list[BudgetLineItem]
    created_by: UUID
    created_at: datetime
    updated_at: datetime | None = None
    updated_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    rejected_by: UUID | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    closed_by: UUID | None = None
    closed_at: datetime | None = None
    archived_by: UUID | None = None
    archived_at: datetime | None = None
    version: int = 1
    description: str = ""
    period_type: BudgetPeriod = BudgetPeriod.YEARLY
    start_date: date | None = None
    end_date: date | None = None
    currency: str = "IDR"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure amounts are quantized
        object.__setattr__(self, "lines", [line for line in self.lines])
        for line in self.lines:
            object.__setattr__(
                line, "amount", line.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            )
            object.__setattr__(
                line,
                "actual_amount",
                line.actual_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "name": self.name,
            "year": self.year,
            "status": self.status.value,
            "lines": [line.to_dict() for line in self.lines],
            "created_by": str(self.created_by),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejection_reason": self.rejection_reason,
            "closed_by": str(self.closed_by) if self.closed_by else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "archived_by": str(self.archived_by) if self.archived_by else None,
            "archived_at": self.archived_at.isoformat() if self.archived_at else None,
            "version": self.version,
            "description": self.description,
            "period_type": self.period_type.value,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "currency": self.currency,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        lines = [BudgetLineItem.from_dict(line_data) for line_data in data.get("lines", [])]
        return cls(
            id=UUID(data["id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            name=data["name"],
            year=data["year"],
            status=BudgetStatus(data["status"]),
            lines=lines,
            created_by=UUID(data["created_by"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"])
            if data.get("approved_at")
            else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"])
            if data.get("rejected_at")
            else None,
            rejection_reason=data.get("rejection_reason"),
            closed_by=UUID(data["closed_by"]) if data.get("closed_by") else None,
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            archived_by=UUID(data["archived_by"]) if data.get("archived_by") else None,
            archived_at=datetime.fromisoformat(data["archived_at"])
            if data.get("archived_at")
            else None,
            version=data.get("version", 1),
            description=data.get("description", ""),
            period_type=BudgetPeriod(data.get("period_type", "yearly")),
            start_date=date.fromisoformat(data["start_date"]) if data.get("start_date") else None,
            end_date=date.fromisoformat(data["end_date"]) if data.get("end_date") else None,
            currency=data.get("currency", "IDR"),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


# ============================================================================
# Budget Aggregate Wrapper (Stateful for mutations)
# ============================================================================


class BudgetAggregate:
    """
    Mutable aggregate wrapper that holds a Budget and allows state changes
    producing new budget instances (event sourcing style).
    """

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _events: list[Any] = []

    def __init__(self, budget: Budget, version: int = 1):
        self._budget = budget
        self._version = version
        self._events = []
        self._take_snapshot()

    @property
    def budget(self) -> Budget:
        return self._budget

    @property
    def version(self) -> int:
        return self._version

    @property
    def id(self) -> UUID:
        return self._budget.id

    # ==================== ENTITY DASAR METHODS ====================

    @classmethod
    def create(
        cls,
        id: UUID,
        legal_entity_id: UUID,
        name: str,
        year: int,
        lines: list[BudgetLine],
        created_by: UUID,
        description: str = "",
        period_type: BudgetPeriod = BudgetPeriod.YEARLY,
        start_date: date | None = None,
        end_date: date | None = None,
        currency: str = "IDR",
    ) -> Self:
        """Create a new budget aggregate."""
        line_items = [line.to_line_item() for line in lines]
        budget = Budget(
            id=id,
            legal_entity_id=legal_entity_id,
            name=name,
            year=year,
            status=BudgetStatus.DRAFT,
            lines=line_items,
            created_by=created_by,
            created_at=datetime.now(UTC),
            version=1,
            description=description,
            period_type=period_type,
            start_date=start_date or date(year, 1, 1),
            end_date=end_date or date(year, 12, 31),
            currency=currency,
        )
        instance = cls(budget, version=1)
        instance._record_audit("CREATE", str(created_by), {"name": name, "year": year})
        instance._register_event(
            BudgetCreated(
                budget_id=id,
                budget_number=name,
                budget_name=name,
                fiscal_year=year,
                user_id=created_by,
                occurred_at=datetime.now(UTC),
            )
        )
        return instance

    def update(self, updated_by: UUID, **kwargs) -> Self:
        """Update budget attributes."""
        if self._budget.status not in (BudgetStatus.DRAFT, BudgetStatus.REJECTED):
            raise ValueError(f"Cannot update budget in status {self._budget.status.value}")

        data = self._budget.to_dict()
        for key, value in kwargs.items():
            if key in data and key not in ("id", "created_at", "created_by", "version", "lines"):
                data[key] = value

        new_budget = Budget.from_dict(data)
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = updated_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("UPDATE", str(updated_by), {"changes": kwargs})
        return self

    def delete(self, deleted_by: UUID, reason: str | None = None) -> Self:
        """Soft delete budget (cancel)."""
        if self._budget.status in (BudgetStatus.APPROVED, BudgetStatus.CLOSED):
            raise ValueError(f"Cannot delete budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.CANCELLED
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = deleted_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("DELETE", str(deleted_by), {"reason": reason})
        return self

    def restore(self, restored_by: UUID) -> Self:
        """Restore cancelled budget."""
        if self._budget.status != BudgetStatus.CANCELLED:
            raise ValueError(f"Cannot restore budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.DRAFT
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = restored_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("RESTORE", str(restored_by), {})
        return self

    def activate(self, activated_by: UUID) -> Self:
        """Submit budget for approval."""
        if self._budget.status != BudgetStatus.DRAFT:
            raise ValueError(f"Cannot activate budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.SUBMITTED
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = activated_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("ACTIVATE", str(activated_by), {})
        return self

    def deactivate(self, deactivated_by: UUID, reason: str | None = None) -> Self:
        """Reject or return to draft."""
        if self._budget.status != BudgetStatus.SUBMITTED:
            raise ValueError(f"Cannot deactivate budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.DRAFT
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = deactivated_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("DEACTIVATE", str(deactivated_by), {"reason": reason})
        return self

    def lock(self, locked_by: UUID, reason: str) -> Self:
        """Put budget on hold."""
        if self._budget.status not in (BudgetStatus.DRAFT, BudgetStatus.SUBMITTED):
            raise ValueError(f"Cannot lock budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.ON_HOLD
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = locked_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("LOCK", str(locked_by), {"reason": reason})
        return self

    def unlock(self, unlocked_by: UUID) -> Self:
        """Release hold."""
        if self._budget.status != BudgetStatus.ON_HOLD:
            raise ValueError(f"Cannot unlock budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.DRAFT
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = unlocked_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("UNLOCK", str(unlocked_by), {})
        return self

    def validate(self) -> dict[str, Any]:
        """Validate all invariants."""
        errors = []
        warnings = []

        if not self._budget.name or len(self._budget.name.strip()) < 3:
            errors.append("Budget name must be at least 3 characters")

        if self._budget.year < 2000 or self._budget.year > 2100:
            errors.append(f"Invalid budget year: {self._budget.year}")

        if not self._budget.lines:
            warnings.append("Budget has no line items")

        total_budget = sum(line.amount for line in self._budget.lines)
        if total_budget == 0:
            warnings.append("Total budget amount is zero")

        # Check for duplicate account+period
        seen = set()
        for line in self._budget.lines:
            key = (line.account_code, line.period)
            if key in seen:
                errors.append(
                    f"Duplicate budget line for account {line.account_code} period {line.period}"
                )
            seen.add(key)

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "budget_id": str(self._budget.id),
            "version": self._version,
        }

    def to_dict(self) -> dict[str, Any]:
        return self._budget.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        budget = Budget.from_dict(data)
        return cls(budget, version=budget.version)

    def clone(self, new_name: str | None = None, new_year: int | None = None) -> Self:
        """Clone budget with new ID."""
        new_id = uuid4()
        new_name = new_name or f"{self._budget.name} (COPY)"
        new_year = new_year or self._budget.year

        new_lines = []
        for line in self._budget.lines:
            new_lines.append(
                BudgetLine(
                    line_id=uuid4(),
                    account_code=line.account_code,
                    account_id=line.account_id,
                    period=line.period,
                    amount=line.amount,
                    actual_amount=Decimal(0),
                    description=line.description,
                )
            )

        return self.create(
            id=new_id,
            legal_entity_id=self._budget.legal_entity_id,
            name=new_name,
            year=new_year,
            lines=new_lines,
            created_by=self._budget.created_by,
            description=f"Cloned from {self._budget.name}",
            period_type=self._budget.period_type,
            start_date=self._budget.start_date,
            end_date=self._budget.end_date,
            currency=self._budget.currency,
        )

    def snapshot(self) -> dict[str, Any]:
        """Get current snapshot."""
        return {
            "version": self._version,
            "budget_id": str(self._budget.id),
            "status": self._budget.status.value,
            "total_budget": str(sum(line.amount for line in self._budget.lines)),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self._version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: UUID) -> Self:
        """Update timestamp without changes."""
        new_budget = self._copy_budget()
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = touched_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("TOUCH", str(touched_by), {})
        return self

    # ==================== AGGREGATE ROOT METHODS ====================

    def add_child(self, line: BudgetLine, added_by: UUID) -> Self:
        """Add budget line item."""
        if self._budget.status not in (BudgetStatus.DRAFT, BudgetStatus.REVISED):
            raise ValueError(f"Cannot add line in status {self._budget.status.value}")

        # Check for duplicate
        for existing in self._budget.lines:
            if existing.account_code == line.account_code and existing.period == line.period:
                raise ValueError(
                    f"Line already exists for account {line.account_code} period {line.period}"
                )

        new_lines = list(self._budget.lines) + [line.to_line_item()]
        new_budget = self._copy_budget()
        new_budget.lines = new_lines
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = added_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit(
            "ADD_LINE",
            str(added_by),
            {"account": line.account_code, "period": line.period, "amount": str(line.amount)},
        )
        return self

    def remove_child(self, line_id: UUID, removed_by: UUID) -> Self:
        """Remove budget line item."""
        if self._budget.status not in (BudgetStatus.DRAFT, BudgetStatus.REVISED):
            raise ValueError(f"Cannot remove line in status {self._budget.status.value}")

        new_lines = [line for line in self._budget.lines if line.line_id != line_id]
        if len(new_lines) == len(self._budget.lines):
            raise ValueError(f"Line {line_id} not found")

        new_budget = self._copy_budget()
        new_budget.lines = new_lines
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = removed_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("REMOVE_LINE", str(removed_by), {"line_id": str(line_id)})
        self._register_event(
            BudgetLineRemoved(
                budget_id=self._budget.id,
                line_id=line_id,
                removed_by=removed_by,
                occurred_at=datetime.now(UTC),
            )
        )
        return self

    def can_approve(self) -> bool:
        return self._budget.status == BudgetStatus.SUBMITTED

    def approve(self, approved_by: UUID) -> Self:
        """Approve the budget."""
        if not self.can_approve():
            raise ValueError(f"Cannot approve budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.APPROVED
        new_budget.approved_by = approved_by
        new_budget.approved_at = datetime.now(UTC)
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = approved_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("APPROVE", str(approved_by), {})
        self._register_event(
            BudgetApproved(
                budget_id=self._budget.id,
                budget_number=self._budget.name,
                approved_by=approved_by,
                occurred_at=datetime.now(UTC),
            )
        )
        return self

    def can_reject(self) -> bool:
        return self._budget.status == BudgetStatus.SUBMITTED

    def reject(self, rejected_by: UUID, reason: str) -> Self:
        """Reject the budget."""
        if not self.can_reject():
            raise ValueError(f"Cannot reject budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.REJECTED
        new_budget.rejected_by = rejected_by
        new_budget.rejected_at = datetime.now(UTC)
        new_budget.rejection_reason = reason
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = rejected_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("REJECT", str(rejected_by), {"reason": reason})
        self._register_event(
            BudgetStatusChanged(
                budget_id=self._budget.id,
                old_status=BudgetStatus.SUBMITTED.value,
                new_status=BudgetStatus.REJECTED.value,
                changed_by=rejected_by,
                reason=reason,
                occurred_at=datetime.now(UTC),
            )
        )
        return self

    def can_cancel(self) -> bool:
        return self._budget.status in (
            BudgetStatus.DRAFT,
            BudgetStatus.SUBMITTED,
            BudgetStatus.APPROVED,
        )

    def cancel(self, cancelled_by: UUID, reason: str) -> Self:
        """Cancel the budget."""
        if not self.can_cancel():
            raise ValueError(f"Cannot cancel budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.CANCELLED
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = cancelled_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("CANCEL", str(cancelled_by), {"reason": reason})
        return self

    def can_reverse(self) -> bool:
        return self._budget.status == BudgetStatus.CANCELLED

    def reverse(self, reversed_by: UUID, reason: str) -> Self:
        """Reverse cancellation (restore)."""
        if not self.can_reverse():
            raise ValueError(f"Cannot reverse budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.DRAFT
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = reversed_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("REVERSE", str(reversed_by), {"reason": reason})
        return self

    def can_close(self) -> bool:
        return self._budget.status == BudgetStatus.APPROVED

    def close(self, closed_by: UUID) -> Self:
        """Close the budget (end of period)."""
        if not self.can_close():
            raise ValueError(f"Cannot close budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.CLOSED
        new_budget.closed_by = closed_by
        new_budget.closed_at = datetime.now(UTC)
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = closed_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("CLOSE", str(closed_by), {})
        return self

    def can_reopen(self) -> bool:
        return self._budget.status == BudgetStatus.CLOSED

    def reopen(self, reopened_by: UUID, reason: str) -> Self:
        """Reopen closed budget."""
        if not self.can_reopen():
            raise ValueError(f"Cannot reopen budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.APPROVED
        new_budget.closed_by = None
        new_budget.closed_at = None
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = reopened_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("REOPEN", str(reopened_by), {"reason": reason})
        return self

    def can_archive(self) -> bool:
        return self._budget.status in (BudgetStatus.CLOSED, BudgetStatus.APPROVED)

    def archive(self, archived_by: UUID) -> Self:
        """Archive budget."""
        if not self.can_archive():
            raise ValueError(f"Cannot archive budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.ARCHIVED
        new_budget.archived_by = archived_by
        new_budget.archived_at = datetime.now(UTC)
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = archived_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("ARCHIVE", str(archived_by), {})
        return self

    def can_unarchive(self) -> bool:
        return self._budget.status == BudgetStatus.ARCHIVED

    def unarchive(self, unarchived_by: UUID) -> Self:
        """Unarchive budget."""
        if not self.can_unarchive():
            raise ValueError(f"Cannot unarchive budget in status {self._budget.status.value}")

        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.CLOSED
        new_budget.archived_by = None
        new_budget.archived_at = None
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = unarchived_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("UNARCHIVE", str(unarchived_by), {})
        return self

    # ==================== EVENT METHODS ====================

    def register_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    def _register_event(self, event: Any) -> None:
        self._events.append(event)

    # ==================== BUDGET SPECIFIC METHODS ====================

    def revise(self, revised_by: UUID, new_lines: list[BudgetLine], reason: str) -> Self:
        """Revise budget with new lines."""
        if self._budget.status != BudgetStatus.APPROVED:
            raise ValueError(f"Cannot revise budget in status {self._budget.status.value}")

        line_items = [line.to_line_item() for line in new_lines]
        new_budget = self._copy_budget()
        new_budget.status = BudgetStatus.REVISED
        new_budget.lines = line_items
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = revised_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit("REVISE", str(revised_by), {"reason": reason})
        self._register_event(
            BudgetRevised(
                budget_id=self._budget.id,
                budget_number=self._budget.name,
                version=self._budget.version,
                revision_reason=reason,
                revised_by=revised_by,
                occurred_at=datetime.now(UTC),
            )
        )
        return self

    def record_actual(
        self, account_code: str, period: str, amount: Decimal, recorded_by: UUID
    ) -> Self:
        """Record actual amount for a specific account and period."""
        lines = list(self._budget.lines)
        found = False
        for i, line in enumerate(lines):
            if line.account_code == account_code and line.period == period:
                new_line = BudgetLineItem(
                    line_id=line.line_id,
                    account_code=line.account_code,
                    account_id=line.account_id,
                    period=line.period,
                    amount=line.amount,
                    actual_amount=amount,
                    description=line.description,
                    notes=line.notes,
                    created_at=line.created_at,
                )
                lines[i] = new_line
                found = True
                break
        if not found:
            raise ValueError(f"No budget line found for account {account_code} period {period}")

        new_budget = self._copy_budget()
        new_budget.lines = lines
        new_budget.updated_at = datetime.now(UTC)
        new_budget.updated_by = recorded_by
        new_budget.version = self._budget.version + 1

        self._budget = new_budget
        self._version += 1
        self._take_snapshot()
        self._record_audit(
            "RECORD_ACTUAL",
            str(recorded_by),
            {"account": account_code, "period": period, "amount": str(amount)},
        )
        self._register_event(
            BudgetLineAdjusted(
                budget_id=self._budget.id,
                line_id=lines[i].line_id,
                actual_amount=amount,
                recorded_by=recorded_by,
                occurred_at=datetime.now(UTC),
            )
        )
        return self

    def get_total_budget(self) -> Decimal:
        return sum(line.amount for line in self._budget.lines)

    def get_total_actual(self) -> Decimal:
        return sum(line.actual_amount for line in self._budget.lines)

    def get_total_variance(self) -> Decimal:
        return self.get_total_actual() - self.get_total_budget()

    def get_variance_percentage(self) -> float:
        total_budget = self.get_total_budget()
        if total_budget == 0:
            return 0.0
        return float(abs(self.get_total_variance()) / total_budget * 100)

    def get_lines_by_period(self, period: str) -> list[BudgetLineItem]:
        return [line for line in self._budget.lines if line.period == period]

    def get_lines_by_account(self, account_code: str) -> list[BudgetLineItem]:
        return [line for line in self._budget.lines if line.account_code == account_code]

    def get_favorable_lines(self, is_revenue_account: callable = None) -> list[BudgetLineItem]:
        """Get lines with favorable variance."""
        favorable = []
        for line in self._budget.lines:
            is_revenue = False
            if is_revenue_account:
                is_revenue = is_revenue_account(line.account_code)
            if line.is_favorable(is_revenue):
                favorable.append(line)
        return favorable

    def get_unfavorable_lines(self, is_revenue_account: callable = None) -> list[BudgetLineItem]:
        """Get lines with unfavorable variance."""
        unfavorable = []
        for line in self._budget.lines:
            is_revenue = False
            if is_revenue_account:
                is_revenue = is_revenue_account(line.account_code)
            if not line.is_favorable(is_revenue):
                unfavorable.append(line)
        return unfavorable

    # ==================== PRIVATE METHODS ====================

    def _copy_budget(self) -> Budget:
        """Create a copy of current budget."""
        return Budget(
            id=self._budget.id,
            legal_entity_id=self._budget.legal_entity_id,
            name=self._budget.name,
            year=self._budget.year,
            status=self._budget.status,
            lines=list(self._budget.lines),
            created_by=self._budget.created_by,
            created_at=self._budget.created_at,
            updated_at=self._budget.updated_at,
            updated_by=self._budget.updated_by,
            approved_by=self._budget.approved_by,
            approved_at=self._budget.approved_at,
            rejected_by=self._budget.rejected_by,
            rejected_at=self._budget.rejected_at,
            rejection_reason=self._budget.rejection_reason,
            closed_by=self._budget.closed_by,
            closed_at=self._budget.closed_at,
            archived_by=self._budget.archived_by,
            archived_at=self._budget.archived_at,
            version=self._budget.version,
            description=self._budget.description,
            period_type=self._budget.period_type,
            start_date=self._budget.start_date,
            end_date=self._budget.end_date,
            currency=self._budget.currency,
            tags=self._budget.tags.copy(),
            metadata=self._budget.metadata.copy(),
        )

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "budget_id": str(self._budget.id),
            "status": self._budget.status.value,
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
            "version": self._version,
            "budget_id": str(self._budget.id),
            "details": details,
        }
        self._audit_trail.append(entry)


# ============================================================================
# Repository Interface (Real Implementation)
# ============================================================================


class BudgetRepository:
    """In-memory repository for BudgetAggregate."""

    _storage: ClassVar[dict[UUID, BudgetAggregate]] = {}

    async def get_by_id(self, budget_id: UUID) -> BudgetAggregate | None:
        return self._storage.get(budget_id)

    async def get_by_name(self, name: str, legal_entity_id: UUID) -> BudgetAggregate | None:
        for agg in self._storage.values():
            if agg.budget.name == name and agg.budget.legal_entity_id == legal_entity_id:
                return agg
        return None

    async def get_by_year(self, year: int, legal_entity_id: UUID) -> list[BudgetAggregate]:
        return [
            agg
            for agg in self._storage.values()
            if agg.budget.year == year and agg.budget.legal_entity_id == legal_entity_id
        ]

    async def get_by_status(
        self, status: BudgetStatus, legal_entity_id: UUID
    ) -> list[BudgetAggregate]:
        return [
            agg
            for agg in self._storage.values()
            if agg.budget.status == status and agg.budget.legal_entity_id == legal_entity_id
        ]

    async def get_all(self, legal_entity_id: UUID) -> list[BudgetAggregate]:
        return [
            agg for agg in self._storage.values() if agg.budget.legal_entity_id == legal_entity_id
        ]

    async def exists(self, budget_id: UUID) -> bool:
        return budget_id in self._storage

    async def count(self, legal_entity_id: UUID) -> int:
        return len(
            [agg for agg in self._storage.values() if agg.budget.legal_entity_id == legal_entity_id]
        )

    async def save(self, aggregate: BudgetAggregate) -> None:
        self._storage[aggregate.id] = aggregate

    async def delete(self, budget_id: UUID) -> None:
        if budget_id in self._storage:
            del self._storage[budget_id]

    async def clear(self) -> None:
        self._storage.clear()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "Budget",
    "BudgetAggregate",
    "BudgetLine",
    "BudgetLineItem",
    "BudgetPeriod",
    "BudgetRepository",
    "BudgetStatus",
]
