#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Budget
Responsibility: Domain events untuk budget dengan semua method event dasar.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

# ============================================================================
# EVENT TYPE ENUM
# ============================================================================


class BudgetEventType(Enum):
    """Jenis event budget."""
    BUDGET_CREATED = "budget_created"
    BUDGET_SUBMITTED = "budget_submitted"
    BUDGET_APPROVED = "budget_approved"
    BUDGET_REJECTED = "budget_rejected"
    BUDGET_ACTIVATED = "budget_activated"
    BUDGET_LOCKED = "budget_locked"
    BUDGET_UNLOCKED = "budget_unlocked"
    BUDGET_ARCHIVED = "budget_archived"
    BUDGET_CLOSED = "budget_closed"
    BUDGET_CANCELLED = "budget_cancelled"
    BUDGET_LINE_ADDED = "budget_line_added"
    BUDGET_LINE_ADJUSTED = "budget_line_adjusted"
    BUDGET_LINE_REMOVED = "budget_line_removed"
    BUDGET_STATUS_CHANGED = "budget_status_changed"
    BUDGET_REVISED = "budget_revised"


# ============================================================================
# BASE DOMAIN EVENT
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base domain event dengan semua required methods.
    """

    event_id: UUID
    event_type: BudgetEventType
    aggregate_id: UUID
    aggregate_type: str = "Budget"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=BudgetEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "Budget"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            version=data.get("version", 1),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        data = json.loads(json_str)
        return cls.from_dict(data)

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# CONCRETE EVENTS
# ============================================================================


@dataclass(frozen=True)
class BudgetCreated(DomainEvent):
    """Event ketika budget baru dibuat."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        budget_name: str,
        fiscal_year: int,
        created_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "budget_name": budget_name,
            "fiscal_year": fiscal_year,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CREATED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetSubmitted(DomainEvent):
    """Event ketika budget disubmit."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        submitted_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "submitted_by": submitted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_SUBMITTED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetApproved(DomainEvent):
    """Event ketika budget disetujui."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        approved_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_APPROVED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetRejected(DomainEvent):
    """Event ketika budget ditolak."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        reason: str,
        rejected_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "reason": reason,
            "rejected_by": rejected_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_REJECTED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetActivated(DomainEvent):
    """Event ketika budget diaktifkan."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        activated_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "activated_by": activated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_ACTIVATED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetLocked(DomainEvent):
    """Event ketika budget dikunci."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        locked_by: str | None = None,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "locked_by": locked_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LOCKED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetUnlocked(DomainEvent):
    """Event ketika budget dibuka kuncinya."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        unlocked_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "unlocked_by": unlocked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_UNLOCKED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetArchived(DomainEvent):
    """Event ketika budget diarsipkan."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        archived_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "archived_by": archived_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_ARCHIVED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetClosed(DomainEvent):
    """Event ketika budget ditutup."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        closed_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "closed_by": closed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CLOSED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetCancelled(DomainEvent):
    """Event ketika budget dibatalkan."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        cancelled_by: str | None = None,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "cancelled_by": cancelled_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CANCELLED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetLineAdded(DomainEvent):
    """Event ketika line ditambahkan ke budget."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        account_code: str,
        amount: Decimal,
        added_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "account_code": account_code,
            "amount": str(amount),
            "added_by": added_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_ADDED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetLineAdjusted(DomainEvent):
    """Event ketika line budget diadjust."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        account_code: str,
        old_amount: Decimal,
        new_amount: Decimal,
        adjusted_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "account_code": account_code,
            "old_amount": str(old_amount),
            "new_amount": str(new_amount),
            "adjusted_by": adjusted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_ADJUSTED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetLineRemoved(DomainEvent):
    """Event ketika line budget dihapus."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        account_code: str,
        amount: Decimal,
        removed_by: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "account_code": account_code,
            "amount": str(amount),
            "removed_by": removed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_REMOVED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetStatusChanged(DomainEvent):
    """Event ketika status budget berubah."""

    def __init__(
        self,
        budget_id: UUID,
        old_status: str,
        new_status: str,
        changed_by: UUID | None = None,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "old_status": old_status,
            "new_status": new_status,
            "changed_by": str(changed_by) if changed_by else None,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_STATUS_CHANGED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or (str(changed_by) if changed_by else None),
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


@dataclass(frozen=True)
class BudgetRevised(DomainEvent):
    """Event ketika budget direvisi."""

    def __init__(
        self,
        budget_id: UUID,
        budget_code: str,
        old_version: int,
        new_version: int,
        revision_reason: str,
        revised_by: UUID | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_code": budget_code,
            "old_version": old_version,
            "new_version": new_version,
            "revision_reason": revision_reason,
            "revised_by": str(revised_by) if revised_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_REVISED,
            aggregate_id=aggregate_id or budget_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id or (str(revised_by) if revised_by else None),
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=aggregate_version,
        )


# ============================================================================
# ALIASES UNTUK KOMPATIBILITAS (tanpa suffix "Event")
# ============================================================================

# Nama-nama ini untuk kompatibilitas dengan kode lama yang mengimpor tanpa suffix
BudgetCreatedEvent = BudgetCreated
BudgetSubmittedEvent = BudgetSubmitted
BudgetApprovedEvent = BudgetApproved
BudgetRejectedEvent = BudgetRejected
BudgetActivatedEvent = BudgetActivated
BudgetLockedEvent = BudgetLocked
BudgetUnlockedEvent = BudgetUnlocked
BudgetArchivedEvent = BudgetArchived
BudgetClosedEvent = BudgetClosed
BudgetCancelledEvent = BudgetCancelled
BudgetLineAddedEvent = BudgetLineAdded
BudgetLineAdjustedEvent = BudgetLineAdjusted
BudgetLineRemovedEvent = BudgetLineRemoved
BudgetStatusChangedEvent = BudgetStatusChanged
BudgetRevisedEvent = BudgetRevised

# Untuk kompatibilitas dengan import yang menggunakan nama tanpa "Event" (seperti "BudgetApproved")
BudgetCreated = BudgetCreated
BudgetSubmitted = BudgetSubmitted
BudgetApproved = BudgetApproved
BudgetRejected = BudgetRejected
BudgetActivated = BudgetActivated
BudgetLocked = BudgetLocked
BudgetUnlocked = BudgetUnlocked
BudgetArchived = BudgetArchived
BudgetClosed = BudgetClosed
BudgetCancelled = BudgetCancelled
BudgetLineAdded = BudgetLineAdded
BudgetLineAdjusted = BudgetLineAdjusted
BudgetLineRemoved = BudgetLineRemoved
BudgetStatusChanged = BudgetStatusChanged
BudgetRevised = BudgetRevised


# ============================================================================
# EVENT PUBLISHER
# ============================================================================


class BudgetEventPublisher:
    """Publisher untuk budget domain events."""

    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)
        import logging
        logging.getLogger(__name__).info(
            f"Published event: {event.event_type.value} for budget {event.aggregate_id}"
        )

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        for event in events:
            await cls.publish(event)

    @classmethod
    def get_published_events(cls) -> list[DomainEvent]:
        return cls._published_events.copy()

    @classmethod
    def clear(cls) -> None:
        cls._published_events.clear()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Event classes (tanpa suffix)
    "BudgetActivated",
    # Event classes (dengan suffix "Event")
    "BudgetActivatedEvent",
    "BudgetApproved",
    "BudgetApprovedEvent",
    "BudgetArchived",
    "BudgetArchivedEvent",
    "BudgetCancelled",
    "BudgetCancelledEvent",
    "BudgetClosed",
    "BudgetClosedEvent",
    "BudgetCreated",
    "BudgetCreatedEvent",
    "BudgetEventPublisher",
    "BudgetEventType",
    "BudgetLineAdded",
    "BudgetLineAddedEvent",
    "BudgetLineAdjusted",
    "BudgetLineAdjustedEvent",
    "BudgetLineRemoved",
    "BudgetLineRemovedEvent",
    "BudgetLocked",
    "BudgetLockedEvent",
    "BudgetRejected",
    "BudgetRejectedEvent",
    "BudgetRevised",
    "BudgetRevisedEvent",
    "BudgetStatusChanged",
    "BudgetStatusChangedEvent",
    "BudgetSubmitted",
    "BudgetSubmittedEvent",
    "BudgetUnlocked",
    "BudgetUnlockedEvent",
    # Base
    "DomainEvent",
]
