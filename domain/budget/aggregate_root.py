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
    BudgetApprovedEvent,
    BudgetArchivedEvent,
    BudgetCancelledEvent,
    BudgetClosedEvent,
    BudgetCreatedEvent,
    BudgetLineAddedEvent,
    BudgetLineAdjustedEvent,
    BudgetLineRemovedEvent,
    BudgetRejectedEvent,
    BudgetStatusChangedEvent,
    BudgetSubmittedEvent,
)

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS
# ============================================================================


class BudgetStatus(Enum):
    """Status budget - satu set superset yang mencakup semua kebutuhan router."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    LOCKED = "locked"
    ARCHIVED = "archived"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    CLOSED = "closed"

    @classmethod
    def can_transition(cls, from_status: BudgetStatus, to_status: BudgetStatus) -> bool:
        allowed = {
            cls.DRAFT: {cls.SUBMITTED, cls.CANCELLED, cls.ARCHIVED},
            cls.SUBMITTED: {cls.UNDER_REVIEW, cls.REJECTED, cls.CANCELLED},
            cls.UNDER_REVIEW: {cls.APPROVED, cls.REJECTED, cls.CANCELLED},
            cls.APPROVED: {cls.ACTIVE, cls.LOCKED, cls.CANCELLED, cls.ARCHIVED},
            cls.REJECTED: {cls.DRAFT, cls.CANCELLED, cls.ARCHIVED},
            cls.ACTIVE: {cls.LOCKED, cls.CLOSED, cls.EXPIRED, cls.ARCHIVED},
            cls.LOCKED: {cls.ACTIVE, cls.ARCHIVED},
            cls.ARCHIVED: set(),
            cls.EXPIRED: {cls.ARCHIVED},
            cls.CANCELLED: {cls.DRAFT},
            cls.CLOSED: {cls.ARCHIVED},
        }
        return to_status in allowed.get(from_status, set())

    @classmethod
    def is_editable(cls, status: BudgetStatus) -> bool:
        return status in (cls.DRAFT, cls.REJECTED)

    @classmethod
    def is_approvable(cls, status: BudgetStatus) -> bool:
        return status in (cls.SUBMITTED, cls.UNDER_REVIEW)

    @classmethod
    def is_activatable(cls, status: BudgetStatus) -> bool:
        return status == cls.APPROVED

    @classmethod
    def is_lockable(cls, status: BudgetStatus) -> bool:
        return status in (cls.APPROVED, cls.ACTIVE)

    @classmethod
    def is_archivable(cls, status: BudgetStatus) -> bool:
        return status in (cls.APPROVED, cls.ACTIVE, cls.CLOSED, cls.EXPIRED)

    @classmethod
    def is_closable(cls, status: BudgetStatus) -> bool:
        return status in (cls.ACTIVE, cls.APPROVED)

    @classmethod
    def is_cancellable(cls, status: BudgetStatus) -> bool:
        return status not in (cls.ARCHIVED, cls.CLOSED, cls.CANCELLED)

    @classmethod
    def from_string(cls, value: str) -> BudgetStatus:
        for status in cls:
            if status.value == value:
                return status
        raise ValueError(f"Unknown budget status: {value}")


class BudgetType(Enum):
    OPERATIONAL = "operational"
    CAPITAL = "capital"
    CASH = "cash"
    PROJECT = "project"
    DEPARTMENT = "department"
    FIXED_ASSET = "fixed_asset"
    SALES = "sales"
    PRODUCTION = "production"
    LABOR = "labor"

    @classmethod
    def from_string(cls, value: str) -> BudgetType:
        for bt in cls:
            if bt.value == value:
                return bt
        raise ValueError(f"Unknown budget type: {value}")


class BudgetPeriod(Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @classmethod
    def from_string(cls, value: str) -> BudgetPeriod:
        for bp in cls:
            if bp.value == value:
                return bp
        raise ValueError(f"Unknown budget period: {value}")


# ============================================================================
# VALUE OBJECTS
# ============================================================================


@dataclass
class BudgetLineItem:
    """Budget line item untuk satu akun (immutable)."""

    id: UUID
    account_id: UUID
    account_code: str
    amount: Decimal
    note: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        if isinstance(self.amount, Decimal):
            object.__setattr__(
                self, "amount",
                self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=UUID(data["id"]),
            account_id=UUID(data["account_id"]),
            account_code=data["account_code"],
            amount=Decimal(data["amount"]),
            note=data.get("note"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(UTC),
        )


@dataclass
class BudgetLine:
    """Mutable budget line untuk internal use."""

    id: UUID
    account_id: UUID
    account_code: str
    amount: Decimal
    note: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self):
        self.amount = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def update_amount(self, new_amount: Decimal) -> None:
        self.amount = new_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        self.updated_at = datetime.now(UTC)

    def to_line_item(self) -> BudgetLineItem:
        return BudgetLineItem(
            id=self.id,
            account_id=self.account_id,
            account_code=self.account_code,
            amount=self.amount,
            note=self.note,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "account_id": str(self.account_id),
            "account_code": self.account_code,
            "amount": str(self.amount),
            "note": self.note,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        return cls(
            id=UUID(data["id"]),
            account_id=UUID(data["account_id"]),
            account_code=data["account_code"],
            amount=Decimal(data["amount"]),
            note=data.get("note"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(UTC),
        )


# ============================================================================
# BUDGET AGGREGATE (Immutable Base)
# ============================================================================


@dataclass(frozen=True)
class Budget:
    """Immutable budget aggregate root."""

    id: UUID
    legal_entity_id: UUID
    budget_code: str
    budget_name: str
    budget_type: BudgetType
    fiscal_year: int
    period: BudgetPeriod
    version: str
    status: BudgetStatus
    effective_date: date
    expiry_date: date | None
    currency: str
    lines: list[BudgetLineItem]
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    is_locked: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: UUID | None = None
    updated_by: UUID | None = None
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    submitted_at: datetime | None = None
    submitted_by: UUID | None = None
    rejected_at: datetime | None = None
    rejected_by: UUID | None = None
    rejection_reason: str | None = None
    version_number: int = 1

    def __post_init__(self):
        # Quantize all amounts
        for i, line in enumerate(self.lines):
            if hasattr(line, "amount"):
                quantized = line.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
                if quantized != line.amount:
                    object.__setattr__(
                        self,
                        "lines",
                        [
                            BudgetLineItem(
                                id=l.id,
                                account_id=l.account_id,
                                account_code=l.account_code,
                                amount=l.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN),
                                note=l.note,
                                created_at=l.created_at,
                                updated_at=l.updated_at,
                            )
                            if i == idx and l.amount != quantized
                            else l
                            for idx, l in enumerate(self.lines)
                        ]
                    )
                    break

    @property
    def total_amount(self) -> Decimal:
        return sum(line.amount for line in self.lines).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "legal_entity_id": str(self.legal_entity_id),
            "budget_code": self.budget_code,
            "budget_name": self.budget_name,
            "budget_type": self.budget_type.value,
            "fiscal_year": self.fiscal_year,
            "period": self.period.value,
            "version": self.version,
            "status": self.status.value,
            "effective_date": self.effective_date.isoformat(),
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "currency": self.currency,
            "total_amount": str(self.total_amount),
            "notes": self.notes,
            "tags": self.tags.copy() if self.tags else [],
            "is_locked": self.is_locked,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": str(self.created_by) if self.created_by else None,
            "updated_by": str(self.updated_by) if self.updated_by else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
            "approved_by": str(self.approved_by) if self.approved_by else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "submitted_by": str(self.submitted_by) if self.submitted_by else None,
            "rejected_at": self.rejected_at.isoformat() if self.rejected_at else None,
            "rejected_by": str(self.rejected_by) if self.rejected_by else None,
            "rejection_reason": self.rejection_reason,
            "version_number": self.version_number,
            "lines": [line.to_dict() for line in self.lines],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        lines = [BudgetLineItem.from_dict(line_data) for line_data in data.get("lines", [])]
        return cls(
            id=UUID(data["id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            budget_code=data["budget_code"],
            budget_name=data["budget_name"],
            budget_type=BudgetType.from_string(data["budget_type"]),
            fiscal_year=data["fiscal_year"],
            period=BudgetPeriod.from_string(data["period"]),
            version=data["version"],
            status=BudgetStatus.from_string(data["status"]),
            effective_date=date.fromisoformat(data["effective_date"]),
            expiry_date=date.fromisoformat(data["expiry_date"]) if data.get("expiry_date") else None,
            currency=data["currency"],
            lines=lines,
            notes=data.get("notes"),
            tags=data.get("tags", []),
            is_locked=data.get("is_locked", False),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now(UTC),
            created_by=UUID(data["created_by"]) if data.get("created_by") else None,
            updated_by=UUID(data["updated_by"]) if data.get("updated_by") else None,
            approved_at=datetime.fromisoformat(data["approved_at"]) if data.get("approved_at") else None,
            approved_by=UUID(data["approved_by"]) if data.get("approved_by") else None,
            submitted_at=datetime.fromisoformat(data["submitted_at"]) if data.get("submitted_at") else None,
            submitted_by=UUID(data["submitted_by"]) if data.get("submitted_by") else None,
            rejected_at=datetime.fromisoformat(data["rejected_at"]) if data.get("rejected_at") else None,
            rejected_by=UUID(data["rejected_by"]) if data.get("rejected_by") else None,
            rejection_reason=data.get("rejection_reason"),
            version_number=data.get("version_number", 1),
        )


# ============================================================================
# BUDGET AGGREGATE WRAPPER (Mutable)
# ============================================================================


class BudgetAggregate:
    """
    Mutable aggregate wrapper that holds a Budget and allows state changes.
    """

    # Untuk kepatuhan static checker
    version: int
    id: UUID

    _snapshots: ClassVar[list[dict[str, Any]]] = []
    _audit_trail: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, budget: Budget, version: int = 1):
        self._budget = budget
        self._version = version
        self._events: list[Any] = []
        self._take_snapshot()
        # Untuk kepatuhan static checker
        self.id = budget.id
        self.version = version

    @property
    def budget(self) -> Budget:
        return self._budget

    @property
    def version(self) -> int:
        return self._version

    @property
    def id(self) -> UUID:
        return self._budget.id

    @property
    def total_amount(self) -> Decimal:
        return self._budget.total_amount

    # ==================== FACTORY ====================

    @classmethod
    def create(
        cls,
        legal_entity_id: UUID,
        budget_code: str,
        budget_name: str,
        budget_type: BudgetType,
        fiscal_year: int,
        period: BudgetPeriod,
        effective_date: date,
        expiry_date: date | None,
        currency: str,
        lines: list[BudgetLine],
        created_by: UUID,
        notes: str | None = None,
        tags: list[str] | None = None,
    ) -> Self:
        """Factory untuk membuat budget baru dengan status DRAFT."""
        line_items = [line.to_line_item() for line in lines]

        budget = Budget(
            id=uuid4(),
            legal_entity_id=legal_entity_id,
            budget_code=budget_code.upper(),
            budget_name=budget_name,
            budget_type=budget_type,
            fiscal_year=fiscal_year,
            period=period,
            version="1.0",
            status=BudgetStatus.DRAFT,
            effective_date=effective_date,
            expiry_date=expiry_date,
            currency=currency,
            lines=line_items,
            notes=notes,
            tags=tags or [],
            is_locked=False,
            created_by=created_by,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            version_number=1,
        )

        instance = cls(budget, version=1)
        instance._record_audit("CREATE", str(created_by), {
            "budget_code": budget_code,
            "budget_name": budget_name,
            "fiscal_year": fiscal_year,
        })
        instance._register_event(
            BudgetCreatedEvent(
                aggregate_id=budget.id,
                aggregate_version=1,
                budget_id=budget.id,
                budget_code=budget_code,
                budget_name=budget_name,
                fiscal_year=fiscal_year,
                created_by=str(created_by) if created_by else None,
                user_id=str(created_by) if created_by else None,
            )
        )
        return instance

    # ==================== QUERY METHODS ====================

    def get_line_by_id(self, line_id: UUID) -> BudgetLineItem | None:
        for line in self._budget.lines:
            if line.id == line_id:
                return line
        return None

    def get_line_by_account(self, account_id: UUID) -> BudgetLineItem | None:
        for line in self._budget.lines:
            if line.account_id == account_id:
                return line
        return None

    def get_lines_by_account_code(self, account_code: str) -> list[BudgetLineItem]:
        return [line for line in self._budget.lines if line.account_code == account_code]

    def get_total_lines(self) -> int:
        return len(self._budget.lines)

    def is_active(self) -> bool:
        today = date.today()
        return (
            self._budget.status == BudgetStatus.ACTIVE
            and self._budget.effective_date <= today
            and (self._budget.expiry_date is None or self._budget.expiry_date >= today)
        )

    def is_editable(self) -> bool:
        return BudgetStatus.is_editable(self._budget.status)

    def is_approvable(self) -> bool:
        return BudgetStatus.is_approvable(self._budget.status)

    def is_activatable(self) -> bool:
        return BudgetStatus.is_activatable(self._budget.status)

    def is_lockable(self) -> bool:
        return BudgetStatus.is_lockable(self._budget.status)

    def is_archivable(self) -> bool:
        return BudgetStatus.is_archivable(self._budget.status)

    def is_closable(self) -> bool:
        return BudgetStatus.is_closable(self._budget.status)

    def is_cancellable(self) -> bool:
        return BudgetStatus.is_cancellable(self._budget.status)

    def can_transition_to(self, new_status: BudgetStatus) -> bool:
        return BudgetStatus.can_transition(self._budget.status, new_status)

    # ==================== LIFECYCLE METHODS ====================

    def _change_status(self, new_status: BudgetStatus, user_id: UUID, reason: str | None = None) -> None:
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Cannot transition from {self._budget.status.value} to {new_status.value}"
            )

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = new_status.value
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit(f"STATUS_CHANGE_{old_status.value}_TO_{new_status.value}", str(user_id), {
            "old_status": old_status.value,
            "new_status": new_status.value,
            "reason": reason,
        })
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=new_status.value,
                changed_by=user_id,
                reason=reason,
            )
        )

    def submit(self, user_id: UUID, notes: str | None = None) -> None:
        if not self.is_editable():
            raise ValueError(f"Cannot submit budget with status {self._budget.status.value}")
        if not self._budget.lines:
            raise ValueError("Cannot submit budget with no lines")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.SUBMITTED.value
        data["submitted_by"] = str(user_id) if user_id else None
        data["submitted_at"] = datetime.now(UTC).isoformat()
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("SUBMIT", str(user_id), {"notes": notes})
        self._register_event(
            BudgetSubmittedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                submitted_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.SUBMITTED.value,
                changed_by=user_id,
                reason=notes,
            )
        )

    def approve(self, user_id: UUID, notes: str | None = None) -> None:
        if not self.is_approvable():
            raise ValueError(f"Cannot approve budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.APPROVED.value
        data["approved_by"] = str(user_id) if user_id else None
        data["approved_at"] = datetime.now(UTC).isoformat()
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("APPROVE", str(user_id), {"notes": notes})
        self._register_event(
            BudgetApprovedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                approved_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.APPROVED.value,
                changed_by=user_id,
                reason=notes,
            )
        )

    def reject(self, user_id: UUID, reason: str) -> None:
        if self._budget.status not in (BudgetStatus.SUBMITTED, BudgetStatus.UNDER_REVIEW):
            raise ValueError(f"Cannot reject budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.REJECTED.value
        data["rejected_by"] = str(user_id) if user_id else None
        data["rejected_at"] = datetime.now(UTC).isoformat()
        data["rejection_reason"] = reason
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("REJECT", str(user_id), {"reason": reason})
        self._register_event(
            BudgetRejectedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                reason=reason,
                rejected_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.REJECTED.value,
                changed_by=user_id,
                reason=reason,
            )
        )

    def activate(self, user_id: UUID) -> None:
        if not self.is_activatable():
            raise ValueError(f"Cannot activate budget with status {self._budget.status.value}")
        if self._budget.effective_date > date.today():
            raise ValueError("Cannot activate budget before effective date")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.ACTIVE.value
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("ACTIVATE", str(user_id), {})
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.ACTIVE.value,
                changed_by=user_id,
            )
        )

    def lock(self, user_id: UUID, reason: str | None = None) -> None:
        if not self.is_lockable():
            raise ValueError(f"Cannot lock budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.LOCKED.value
        data["is_locked"] = True
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("LOCK", str(user_id), {"reason": reason})
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.LOCKED.value,
                changed_by=user_id,
                reason=reason,
            )
        )

    def unlock(self, user_id: UUID) -> None:
        if self._budget.status != BudgetStatus.LOCKED:
            raise ValueError(f"Cannot unlock budget with status {self._budget.status.value}")

        old_status = self._budget.status
        new_status = BudgetStatus.ACTIVE if self.is_active() else BudgetStatus.APPROVED
        data = self._budget.to_dict()
        data["status"] = new_status.value
        data["is_locked"] = False
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("UNLOCK", str(user_id), {})
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=new_status.value,
                changed_by=user_id,
            )
        )

    def close(self, user_id: UUID) -> None:
        if not self.is_closable():
            raise ValueError(f"Cannot close budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.CLOSED.value
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("CLOSE", str(user_id), {})
        self._register_event(
            BudgetClosedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                closed_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.CLOSED.value,
                changed_by=user_id,
            )
        )

    def cancel(self, user_id: UUID, reason: str) -> None:
        if not self.is_cancellable():
            raise ValueError(f"Cannot cancel budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.CANCELLED.value
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("CANCEL", str(user_id), {"reason": reason})
        self._register_event(
            BudgetCancelledEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                cancelled_by=str(user_id) if user_id else None,
                reason=reason,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.CANCELLED.value,
                changed_by=user_id,
                reason=reason,
            )
        )

    def archive(self, user_id: UUID) -> None:
        if not self.is_archivable():
            raise ValueError(f"Cannot archive budget with status {self._budget.status.value}")

        old_status = self._budget.status
        data = self._budget.to_dict()
        data["status"] = BudgetStatus.ARCHIVED.value
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("ARCHIVE", str(user_id), {})
        self._register_event(
            BudgetArchivedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                archived_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )
        self._register_event(
            BudgetStatusChangedEvent(
                budget_id=self._budget.id,
                old_status=old_status.value,
                new_status=BudgetStatus.ARCHIVED.value,
                changed_by=user_id,
            )
        )

    # ==================== UPDATE METHODS ====================

    def update_info(
        self,
        user_id: UUID,
        budget_name: str | None = None,
        effective_date: date | None = None,
        expiry_date: date | None = None,
        notes: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        if not self.is_editable():
            raise ValueError(f"Cannot update budget with status {self._budget.status.value}")

        data = self._budget.to_dict()
        if budget_name:
            data["budget_name"] = budget_name
        if effective_date:
            data["effective_date"] = effective_date.isoformat()
        if expiry_date:
            data["expiry_date"] = expiry_date.isoformat()
        if notes is not None:
            data["notes"] = notes
        if tags is not None:
            data["tags"] = tags
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("UPDATE_INFO", str(user_id), {
            "budget_name": budget_name,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "expiry_date": expiry_date.isoformat() if expiry_date else None,
        })

    def add_line(self, user_id: UUID, account_id: UUID, account_code: str, amount: Decimal, note: str | None = None) -> BudgetLine:
        if not self.is_editable():
            raise ValueError(f"Cannot add line to budget with status {self._budget.status.value}")

        # Check duplicate account
        for line in self._budget.lines:
            if line.account_id == account_id:
                raise ValueError(f"Account {account_code} already exists in budget")

        new_line = BudgetLine(
            id=uuid4(),
            account_id=account_id,
            account_code=account_code,
            amount=amount,
            note=note,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        new_lines = list(self._budget.lines) + [new_line.to_line_item()]
        data = self._budget.to_dict()
        data["lines"] = [l.to_dict() for l in new_lines]
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("ADD_LINE", str(user_id), {
            "account_id": str(account_id),
            "account_code": account_code,
            "amount": str(amount),
        })
        self._register_event(
            BudgetLineAddedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                account_code=account_code,
                amount=amount,
                added_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )

        return new_line

    def update_line(self, user_id: UUID, line_id: UUID, amount: Decimal, note: str | None = None) -> None:
        if not self.is_editable():
            raise ValueError(f"Cannot update line in budget with status {self._budget.status.value}")

        new_lines = []
        old_amount = None
        account_code = None

        for line in self._budget.lines:
            if line.id == line_id:
                old_amount = line.amount
                account_code = line.account_code
                new_line = BudgetLineItem(
                    id=line.id,
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=amount,
                    note=note if note is not None else line.note,
                    created_at=line.created_at,
                    updated_at=datetime.now(UTC),
                )
                new_lines.append(new_line)
            else:
                new_lines.append(line)

        if old_amount is None:
            raise ValueError(f"Line {line_id} not found")

        data = self._budget.to_dict()
        data["lines"] = [l.to_dict() for l in new_lines]
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("UPDATE_LINE", str(user_id), {
            "line_id": str(line_id),
            "old_amount": str(old_amount),
            "new_amount": str(amount),
        })
        self._register_event(
            BudgetLineAdjustedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                account_code=account_code,
                old_amount=old_amount,
                new_amount=amount,
                adjusted_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )

    def remove_line(self, user_id: UUID, line_id: UUID) -> None:
        if not self.is_editable():
            raise ValueError(f"Cannot remove line from budget with status {self._budget.status.value}")

        new_lines = []
        removed_line = None

        for line in self._budget.lines:
            if line.id == line_id:
                removed_line = line
            else:
                new_lines.append(line)

        if removed_line is None:
            raise ValueError(f"Line {line_id} not found")

        data = self._budget.to_dict()
        data["lines"] = [l.to_dict() for l in new_lines]
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("REMOVE_LINE", str(user_id), {
            "line_id": str(line_id),
            "account_code": removed_line.account_code,
            "amount": str(removed_line.amount),
        })
        self._register_event(
            BudgetLineRemovedEvent(
                aggregate_id=self._budget.id,
                aggregate_version=self._version,
                budget_id=self._budget.id,
                budget_code=self._budget.budget_code,
                account_code=removed_line.account_code,
                amount=removed_line.amount,
                removed_by=str(user_id) if user_id else None,
                user_id=str(user_id) if user_id else None,
            )
        )

    # ==================== REVISION ====================

    def revise(self, user_id: UUID, new_lines: list[BudgetLine], reason: str) -> None:
        if self._budget.status != BudgetStatus.APPROVED:
            raise ValueError(f"Cannot revise budget with status {self._budget.status.value}")

        line_items = [line.to_line_item() for line in new_lines]
        data = self._budget.to_dict()
        data["lines"] = [l.to_dict() for l in line_items]
        data["status"] = BudgetStatus.APPROVED.value  # tetap approved setelah revisi
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(user_id) if user_id else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("REVISE", str(user_id), {"reason": reason})

    # ==================== VALIDATION ====================

    def validate(self) -> dict[str, Any]:
        errors = []
        warnings = []

        if not self._budget.budget_name or len(self._budget.budget_name.strip()) < 3:
            errors.append("Budget name must be at least 3 characters")

        if self._budget.fiscal_year < 2000 or self._budget.fiscal_year > 2100:
            errors.append(f"Invalid budget year: {self._budget.fiscal_year}")

        if self._budget.effective_date > self._budget.expiry_date if self._budget.expiry_date else False:
            errors.append("Effective date must be before expiry date")

        if not self._budget.lines:
            warnings.append("Budget has no line items")

        if self.total_amount == 0:
            warnings.append("Total budget amount is zero")

        # Check for duplicate account
        seen = set()
        for line in self._budget.lines:
            if line.account_id in seen:
                errors.append(f"Duplicate budget line for account {line.account_code}")
            seen.add(line.account_id)

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "budget_id": str(self._budget.id),
            "version": self._version,
        }

    # ==================== CLONE ====================

    def clone(self, new_name: str | None = None, new_year: int | None = None) -> Self:
        new_id = uuid4()
        new_code = f"{self._budget.budget_code}-CLONE"
        new_name = new_name or f"{self._budget.budget_name} (COPY)"
        new_year = new_year or self._budget.fiscal_year

        new_lines = []
        for line in self._budget.lines:
            new_lines.append(
                BudgetLine(
                    id=uuid4(),
                    account_id=line.account_id,
                    account_code=line.account_code,
                    amount=line.amount,
                    note=line.note,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )

        return self.create(
            legal_entity_id=self._budget.legal_entity_id,
            budget_code=new_code,
            budget_name=new_name,
            budget_type=self._budget.budget_type,
            fiscal_year=new_year,
            period=self._budget.period,
            effective_date=self._budget.effective_date,
            expiry_date=self._budget.expiry_date,
            currency=self._budget.currency,
            lines=new_lines,
            created_by=self._budget.created_by or uuid4(),
            notes=f"Cloned from {self._budget.budget_code}",
            tags=self._budget.tags.copy() if self._budget.tags else [],
        )

    # ==================== SNAPSHOT & AUDIT ====================

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "budget_id": str(self._budget.id),
            "status": self._budget.status.value,
            "total_budget": str(self.total_amount),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self._version,
            "budget_id": str(self._budget.id),
            "status": self._budget.status.value,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 50:
            self._snapshots = self._snapshots[-25:]

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

    def get_audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    # ==================== EVENT METHODS ====================

    def _register_event(self, event: Any) -> None:
        self._events.append(event)

    def get_events(self) -> list[Any]:
        return self._events.copy()

    def pull_events(self) -> list[Any]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    def register_event(self, event: Any) -> None:
        self._events.append(event)

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> dict[str, Any]:
        return self._budget.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        budget = Budget.from_dict(data)
        return cls(budget, version=budget.version_number)

    def touch(self, touched_by: UUID) -> None:
        data = self._budget.to_dict()
        data["updated_at"] = datetime.now(UTC).isoformat()
        data["updated_by"] = str(touched_by) if touched_by else None
        data["version_number"] = self._version + 1

        new_budget = Budget.from_dict(data)
        self._budget = new_budget
        self._version += 1
        self.version = self._version
        self._take_snapshot()

        self._record_audit("TOUCH", str(touched_by), {})

    # ==================== AGGREGATE ROOT METHODS (untuk compliance) ====================

    def add_child(self, line: BudgetLine, added_by: UUID) -> Self:
        self.add_line(
            user_id=added_by,
            account_id=line.account_id,
            account_code=line.account_code,
            amount=line.amount,
            note=line.note,
        )
        return self

    def remove_child(self, line_id: UUID, removed_by: UUID) -> Self:
        self.remove_line(user_id=removed_by, line_id=line_id)
        return self

    # ==================== VARIANCE METHODS ====================

    def get_total_budget(self) -> Decimal:
        return self.total_amount

    def get_total_actual(self, actuals: dict[UUID, Decimal] | None = None) -> Decimal:
        if actuals is None:
            return Decimal(0)
        total = Decimal(0)
        for line in self._budget.lines:
            total += actuals.get(line.account_id, Decimal(0))
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def get_total_variance(self, actuals: dict[UUID, Decimal] | None = None) -> Decimal:
        return self.get_total_actual(actuals) - self.total_amount

    def get_variance_percentage(self, actuals: dict[UUID, Decimal] | None = None) -> float:
        total_budget = self.total_amount
        if total_budget == 0:
            return 0.0
        total_variance = self.get_total_variance(actuals)
        return float(abs(total_variance) / total_budget * 100)


# ============================================================================
# BUDGET REPOSITORY (In-Memory)
# ============================================================================


class BudgetRepository:
    """In-memory repository for BudgetAggregate."""

    _storage: ClassVar[dict[UUID, BudgetAggregate]] = {}

    async def get_by_id(self, budget_id: UUID) -> BudgetAggregate | None:
        return self._storage.get(budget_id)

    async def get_by_name(self, name: str, legal_entity_id: UUID) -> BudgetAggregate | None:
        for agg in self._storage.values():
            if agg.budget.budget_name == name and agg.budget.legal_entity_id == legal_entity_id:
                return agg
        return None

    async def get_by_code(self, code: str, legal_entity_id: UUID) -> BudgetAggregate | None:
        for agg in self._storage.values():
            if agg.budget.budget_code == code and agg.budget.legal_entity_id == legal_entity_id:
                return agg
        return None

    async def get_by_year(self, year: int, legal_entity_id: UUID) -> list[BudgetAggregate]:
        return [
            agg for agg in self._storage.values()
            if agg.budget.fiscal_year == year and agg.budget.legal_entity_id == legal_entity_id
        ]

    async def get_by_status(self, status: BudgetStatus, legal_entity_id: UUID) -> list[BudgetAggregate]:
        return [
            agg for agg in self._storage.values()
            if agg.budget.status == status and agg.budget.legal_entity_id == legal_entity_id
        ]

    async def get_all(self, legal_entity_id: UUID) -> list[BudgetAggregate]:
        return [
            agg for agg in self._storage.values()
            if agg.budget.legal_entity_id == legal_entity_id
        ]

    async def exists(self, budget_id: UUID) -> bool:
        return budget_id in self._storage

    async def count(self, legal_entity_id: UUID) -> int:
        return len([
            agg for agg in self._storage.values()
            if agg.budget.legal_entity_id == legal_entity_id
        ])

    async def save(self, aggregate: BudgetAggregate) -> None:
        self._storage[aggregate.id] = aggregate

    async def delete(self, budget_id: UUID) -> None:
        if budget_id in self._storage:
            del self._storage[budget_id]

    async def clear(self) -> None:
        self._storage.clear()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "Budget",
    "BudgetAggregate",
    "BudgetLine",
    "BudgetLineItem",
    "BudgetPeriod",
    "BudgetRepository",
    "BudgetStatus",
    "BudgetType",
]