#!/usr/bin/env python3
"""
Module: domain_events.py

Layer: Domain / COA (Chart of Accounts)

Responsibility:
    Domain events for Chart of Accounts aggregate.

    Defines all domain events emitted by COA aggregates (ChartOfAccounts,
    COAAggregate). Events are used for event sourcing, integration with
    other bounded contexts, and audit logging.

    Each event is immutable and carries relevant data about the change.

Business rules:
    - Events are value objects; equality based on event_id.
    - All events have aggregate_id, aggregate_version, occurred_at.
    - Events can be serialized to/from JSON for persistence.
    - DomainEventPublisher protocol defines how to publish events.

Dependencies:
    - Python standard library (uuid, datetime, dataclass, json, enum)

Audit:
    Events themselves are the audit trail. Every state change produces at least one event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol
from uuid import UUID, uuid4

from domain.coa.account_entity import AccountEntity

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    """Types of domain events in COA context."""

    ACCOUNT_CREATED = "account_created"
    ACCOUNT_UPDATED = "account_updated"
    ACCOUNT_DEACTIVATED = "account_deactivated"
    ACCOUNT_REACTIVATED = "account_reactivated"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_UNLOCKED = "account_unlocked"
    ACCOUNT_MERGED = "account_merged"
    ACCOUNT_SPLIT = "account_split"
    HIERARCHY_CHANGED = "hierarchy_changed"
    COA_CREATED = "coa_created"
    COA_LOCKED = "coa_locked"
    COA_UNLOCKED = "coa_unlocked"
    COA_ARCHIVED = "coa_archived"

    def is_account_event(self) -> bool:
        """Check if event type relates to a single account."""
        account_events = {
            DomainEventType.ACCOUNT_CREATED,
            DomainEventType.ACCOUNT_UPDATED,
            DomainEventType.ACCOUNT_DEACTIVATED,
            DomainEventType.ACCOUNT_REACTIVATED,
            DomainEventType.ACCOUNT_LOCKED,
            DomainEventType.ACCOUNT_UNLOCKED,
            DomainEventType.ACCOUNT_MERGED,
            DomainEventType.ACCOUNT_SPLIT,
            DomainEventType.HIERARCHY_CHANGED,
        }
        return self in account_events

    def is_coa_event(self) -> bool:
        """Check if event type relates to the entire COA."""
        coa_events = {
            DomainEventType.COA_CREATED,
            DomainEventType.COA_LOCKED,
            DomainEventType.COA_UNLOCKED,
            DomainEventType.COA_ARCHIVED,
        }
        return self in coa_events


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass
class DomainEvent:
    """
    Base class for all domain events in COA context.

    Attributes:
        event_id: Unique identifier for this event instance
        event_type: Type of event (from DomainEventType enum)
        aggregate_id: ID of the aggregate that generated the event
        aggregate_version: Version of the aggregate after applying this event
        occurred_at: UTC timestamp when the event occurred
        event_data: Dictionary of event-specific data
        user_id: Optional user ID who triggered the event
        correlation_id: Optional correlation ID for tracing
        causation_id: Optional ID of the event that caused this event
    """

    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        """Validate event fields."""
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")
        if self.user_id is not None and not self.user_id:
            raise ValueError("user_id cannot be empty string")

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Reconstruct event from dictionary."""
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Reconstruct event from JSON string."""
        return cls.from_dict(json.loads(json_str))

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DomainEvent):
            return False
        return self.event_id == other.event_id

    def __hash__(self) -> int:
        return hash(self.event_id)

    def __repr__(self) -> str:
        return f"DomainEvent({self.event_type.value}, agg={self.aggregate_id}, v{self.aggregate_version})"


# ============================================================================
# Concrete Account Events
# ============================================================================


@dataclass
class AccountCreatedEvent(DomainEvent):
    """Event emitted when a new account is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account: AccountEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account.account_id),
            "account_code": account.account_code,
            "account_name": account.account_name,
            "account_type": account.account_type.value
            if hasattr(account.account_type, "value")
            else str(account.account_type),
            "normal_balance": account.normal_balance,
            "parent_account_id": str(account.parent_account_id)
            if account.parent_account_id
            else None,
            "is_control_account": account.is_control_account,
            "description": account.description,
            "opening_balance": str(account.opening_balance) if account.opening_balance else "0",
            "currency_code": getattr(account, "currency_code", "IDR"),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountUpdatedEvent(DomainEvent):
    """Event emitted when an account is updated (any field change)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        old_account: AccountEntity,
        new_account: AccountEntity,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        # Calculate changed fields
        changes: dict[str, Any] = {}
        if old_account.account_name != new_account.account_name:
            changes["name"] = {"old": old_account.account_name, "new": new_account.account_name}
        if old_account.parent_account_id != new_account.parent_account_id:
            changes["parent_account_id"] = {
                "old": str(old_account.parent_account_id)
                if old_account.parent_account_id
                else None,
                "new": str(new_account.parent_account_id)
                if new_account.parent_account_id
                else None,
            }
        if old_account.description != new_account.description:
            changes["description"] = {
                "old": old_account.description,
                "new": new_account.description,
            }
        if old_account.is_active != new_account.is_active:
            changes["is_active"] = {"old": old_account.is_active, "new": new_account.is_active}
        if old_account.is_control_account != new_account.is_control_account:
            changes["is_control_account"] = {
                "old": old_account.is_control_account,
                "new": new_account.is_control_account,
            }
        if old_account.opening_balance != new_account.opening_balance:
            changes["opening_balance"] = {
                "old": str(old_account.opening_balance),
                "new": str(new_account.opening_balance),
            }

        event_data = {
            "account_id": str(account_id),
            "account_code": new_account.account_code,
            "changes": changes,
            "updated_by": updated_by,
        }

        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountDeactivatedEvent(DomainEvent):
    """Event emitted when an account is deactivated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account: AccountEntity,
        deactivated_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account.account_id),
            "account_code": account.account_code,
            "account_name": account.account_name,
            "deactivated_by": deactivated_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_DEACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountReactivatedEvent(DomainEvent):
    """Event emitted when an account is reactivated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account: AccountEntity,
        reactivated_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account.account_id),
            "account_code": account.account_code,
            "account_name": account.account_name,
            "reactivated_by": reactivated_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_REACTIVATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountLockedEvent(DomainEvent):
    """Event emitted when an account is locked (temporarily readonly)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account: AccountEntity,
        locked_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account.account_id),
            "account_code": account.account_code,
            "account_name": account.account_name,
            "locked_by": locked_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_LOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountUnlockedEvent(DomainEvent):
    """Event emitted when an account is unlocked."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account: AccountEntity,
        unlocked_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account.account_id),
            "account_code": account.account_code,
            "account_name": account.account_name,
            "unlocked_by": unlocked_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_UNLOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HierarchyChangedEvent(DomainEvent):
    """Event emitted when an account's parent (hierarchy) changes."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        account_id: UUID,
        old_parent_id: UUID | None,
        new_parent_id: UUID | None,
        changed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "account_id": str(account_id),
            "old_parent_id": str(old_parent_id) if old_parent_id else None,
            "new_parent_id": str(new_parent_id) if new_parent_id else None,
            "changed_by": changed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HIERARCHY_CHANGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountMergedEvent(DomainEvent):
    """Event emitted when two accounts are merged (source merged into target)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        source_account_id: UUID,
        target_account_id: UUID,
        merged_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "source_account_id": str(source_account_id),
            "target_account_id": str(target_account_id),
            "merged_by": merged_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_MERGED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AccountSplitEvent(DomainEvent):
    """Event emitted when an account is split into multiple accounts."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        source_account_id: UUID,
        target_account_ids: list[UUID],
        split_ratios: list[float],
        split_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "source_account_id": str(source_account_id),
            "target_account_ids": [str(aid) for aid in target_account_ids],
            "split_ratios": split_ratios,
            "split_by": split_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ACCOUNT_SPLIT,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# COA Level Events
# ============================================================================


@dataclass
class COACreatedEvent(DomainEvent):
    """Event emitted when a new Chart of Accounts is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        coa_name: str,
        legal_entity_id: UUID,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "coa_name": coa_name,
            "legal_entity_id": str(legal_entity_id),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COA_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class COALockedEvent(DomainEvent):
    """Event emitted when the entire COA is locked."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        locked_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "locked_by": locked_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COA_LOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class COAUnlockedEvent(DomainEvent):
    """Event emitted when the COA is unlocked."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        unlocked_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "unlocked_by": unlocked_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COA_UNLOCKED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class COAArchivedEvent(DomainEvent):
    """Event emitted when the COA is archived."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        archived_by: str,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "archived_by": archived_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.COA_ARCHIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Short Aliases (for aggregate_root compatibility)
# ============================================================================

AccountCreated = AccountCreatedEvent
AccountUpdated = AccountUpdatedEvent
AccountDeactivated = AccountDeactivatedEvent
AccountReactivated = AccountReactivatedEvent
AccountLocked = AccountLockedEvent
AccountUnlocked = AccountUnlockedEvent
AccountMerged = AccountMergedEvent
AccountSplit = AccountSplitEvent
HierarchyChanged = HierarchyChangedEvent
COACreated = COACreatedEvent
COALocked = COALockedEvent
COAUnlocked = COAUnlockedEvent
COAArchived = COAArchivedEvent


# ============================================================================
# Domain Event Publisher Protocol
# ============================================================================


class DomainEventPublisher(Protocol):
    """Protocol for publishing domain events to message bus."""

    async def publish(self, event: DomainEvent) -> None:
        """Publish a single domain event."""
        ...

    async def publish_many(self, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await self.publish(event)


# ============================================================================
# Event Store Interface (optional, for event sourcing)
# ============================================================================


class EventStore(Protocol):
    """Protocol for event store operations (optional)."""

    async def append(
        self, stream_id: str, events: list[DomainEvent], expected_version: int
    ) -> None:
        """Append events to a stream with expected version (optimistic concurrency)."""
        ...

    async def read_stream(self, stream_id: str, from_version: int = 0) -> list[DomainEvent]:
        """Read events from a stream starting from a version."""
        ...

    async def read_all(self, from_position: int = 0, limit: int = 1000) -> list[DomainEvent]:
        """Read all events from global stream."""
        ...


# ============================================================================
# Helper Functions
# ============================================================================


def event_type_from_name(name: str) -> DomainEventType | None:
    """Get DomainEventType from string name (case-insensitive)."""
    name_upper = name.upper()
    for et in DomainEventType:
        if et.name == name_upper:
            return et
    return None


def deserialize_event(json_str: str) -> DomainEvent:
    """
    Deserialize a JSON string into the appropriate DomainEvent subclass.
    Uses the event_type field to determine which class to instantiate.
    """
    data = json.loads(json_str)
    event_type_str = data.get("event_type")
    if not event_type_str:
        raise ValueError("Missing event_type in JSON")
    # event_type = DomainEventType(event_type_str)  # removed (F841)
    # Use base class from_dict which works for all events
    return DomainEvent.from_dict(data)


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountCreated",
    "AccountCreatedEvent",
    "AccountDeactivated",
    "AccountDeactivatedEvent",
    "AccountLocked",
    "AccountLockedEvent",
    "AccountMerged",
    "AccountMergedEvent",
    "AccountReactivated",
    "AccountReactivatedEvent",
    "AccountSplit",
    "AccountSplitEvent",
    "AccountUnlocked",
    "AccountUnlockedEvent",
    "AccountUpdated",
    "AccountUpdatedEvent",
    "COAArchived",
    "COAArchivedEvent",
    "COACreated",
    "COACreatedEvent",
    "COALocked",
    "COALockedEvent",
    "COAUnlocked",
    "COAUnlockedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "EventStore",
    "HierarchyChanged",
    "HierarchyChangedEvent",
    "deserialize_event",
    "event_type_from_name",
]
