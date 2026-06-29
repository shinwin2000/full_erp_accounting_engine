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
# Event Type Enum
# ============================================================================


class BudgetEventType(Enum):
    BUDGET_CREATED = "budget_created"
    BUDGET_APPROVED = "budget_approved"
    BUDGET_REJECTED = "budget_rejected"
    BUDGET_REVISED = "budget_revised"
    BUDGET_CANCELLED = "budget_cancelled"
    BUDGET_CLOSED = "budget_closed"
    BUDGET_ARCHIVED = "budget_archived"
    BUDGET_LINE_ADDED = "budget_line_added"
    BUDGET_LINE_REMOVED = "budget_line_removed"
    BUDGET_LINE_ADJUSTED = "budget_line_adjusted"
    BUDGET_STATUS_CHANGED = "budget_status_changed"


# ============================================================================
# Base Domain Event
# ============================================================================


@dataclass
class DomainEvent:
    """Base domain event with all required methods."""

    event_id: UUID
    event_type: BudgetEventType
    aggregate_id: UUID
    aggregate_type: str = "Budget"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: UUID | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Create event from dictionary."""
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=BudgetEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "Budget"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            version=data.get("version", 1),
        )

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)

    def serialize(self) -> bytes:
        """Serialize to bytes."""
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        """Deserialize from bytes."""
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# Concrete Events
# ============================================================================


@dataclass
class BudgetCreated(DomainEvent):
    """Event emitted when budget is created."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        budget_name: str,
        fiscal_year: int,
        user_id: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "budget_name": budget_name,
            "fiscal_year": fiscal_year,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CREATED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetApproved(DomainEvent):
    """Event emitted when budget is approved."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        approved_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "approved_by": str(approved_by) if approved_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_APPROVED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=approved_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetRejected(DomainEvent):
    """Event emitted when budget is rejected."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        rejected_by: UUID | None = None,
        reason: str | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "rejected_by": str(rejected_by) if rejected_by else None,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_REJECTED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=rejected_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetRevised(DomainEvent):
    """Event emitted when budget is revised."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        version: int,
        revision_reason: str,
        revised_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "version": version,
            "revision_reason": revision_reason,
            "revised_by": str(revised_by) if revised_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_REVISED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=revised_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
            version=version,
        )


@dataclass
class BudgetCancelled(DomainEvent):
    """Event emitted when budget is cancelled."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        cancelled_by: UUID | None = None,
        reason: str | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "cancelled_by": str(cancelled_by) if cancelled_by else None,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CANCELLED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=cancelled_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetClosed(DomainEvent):
    """Event emitted when budget is closed."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        closed_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "closed_by": str(closed_by) if closed_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_CLOSED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=closed_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetArchived(DomainEvent):
    """Event emitted when budget is archived."""

    def __init__(
        self,
        budget_id: UUID,
        budget_number: str,
        archived_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "budget_number": budget_number,
            "archived_by": str(archived_by) if archived_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_ARCHIVED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=archived_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetLineAdded(DomainEvent):
    """Event emitted when a budget line is added."""

    def __init__(
        self,
        budget_id: UUID,
        line_id: UUID,
        account_code: str,
        period: str,
        amount: Decimal,
        added_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "line_id": str(line_id),
            "account_code": account_code,
            "period": period,
            "amount": str(amount),
            "added_by": str(added_by) if added_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_ADDED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=added_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetLineRemoved(DomainEvent):
    """Event emitted when a budget line is removed."""

    def __init__(
        self,
        budget_id: UUID,
        line_id: UUID,
        removed_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "line_id": str(line_id),
            "removed_by": str(removed_by) if removed_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_REMOVED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=removed_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetLineAdjusted(DomainEvent):
    """Event emitted when actual amount is recorded for a budget line."""

    def __init__(
        self,
        budget_id: UUID,
        line_id: UUID,
        actual_amount: Decimal,
        recorded_by: UUID | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "budget_id": str(budget_id),
            "line_id": str(line_id),
            "actual_amount": str(actual_amount),
            "recorded_by": str(recorded_by) if recorded_by else None,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=BudgetEventType.BUDGET_LINE_ADJUSTED,
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=recorded_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class BudgetStatusChanged(DomainEvent):
    """Event emitted when budget status changes."""

    def __init__(
        self,
        budget_id: UUID,
        old_status: str,
        new_status: str,
        changed_by: UUID | None = None,
        reason: str | None = None,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
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
            aggregate_id=budget_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=changed_by,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Event Publisher
# ============================================================================


class BudgetEventPublisher:
    """Publisher for budget domain events."""

    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publish an event."""
        cls._published_events.append(event)
        # In real implementation, send to message broker
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
# ALIAS UNTUK KOMPATIBILITAS DENGAN ROUTER
# Router mengimpor dengan suffix "Event"
# ============================================================================

BudgetApprovedEvent = BudgetApproved
BudgetApprovedEvent.__name__ = "BudgetApprovedEvent"

BudgetRejectedEvent = BudgetRejected
BudgetRejectedEvent.__name__ = "BudgetRejectedEvent"

BudgetRevisedEvent = BudgetRevised
BudgetRevisedEvent.__name__ = "BudgetRevisedEvent"

BudgetCancelledEvent = BudgetCancelled
BudgetCancelledEvent.__name__ = "BudgetCancelledEvent"

BudgetClosedEvent = BudgetClosed
BudgetClosedEvent.__name__ = "BudgetClosedEvent"

BudgetArchivedEvent = BudgetArchived
BudgetArchivedEvent.__name__ = "BudgetArchivedEvent"

BudgetCreatedEvent = BudgetCreated
BudgetCreatedEvent.__name__ = "BudgetCreatedEvent"

BudgetLineAddedEvent = BudgetLineAdded
BudgetLineAddedEvent.__name__ = "BudgetLineAddedEvent"

BudgetLineRemovedEvent = BudgetLineRemoved
BudgetLineRemovedEvent.__name__ = "BudgetLineRemovedEvent"

BudgetLineAdjustedEvent = BudgetLineAdjusted
BudgetLineAdjustedEvent.__name__ = "BudgetLineAdjustedEvent"

BudgetStatusChangedEvent = BudgetStatusChanged
BudgetStatusChangedEvent.__name__ = "BudgetStatusChangedEvent"


# ============================================================================
# Exports
# ============================================================================

__all__ = [
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
    "BudgetRejected",
    "BudgetRejectedEvent",
    "BudgetRevised",
    "BudgetRevisedEvent",
    "BudgetStatusChanged",
    "BudgetStatusChangedEvent",
    "DomainEvent",
]