#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Journal
Responsibility: Domain events for Journal aggregate (Posted, Reversed, Voided, etc.)
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.journal.journal_entity import JournalEntity

# ============================================================================
# CUSTOM EXCEPTIONS FOR EVENT PUBLISHING
# ============================================================================


class EventPublishError(Exception):
    """Base exception for event publishing failures."""

    pass


class EventPublishTimeoutError(EventPublishError):
    """Raised when event publishing times out after maximum retries."""

    pass


class EventPublishUnexpectedError(EventPublishError):
    """Raised when an unexpected error occurs during event publishing."""

    pass


# ============================================================================
# DOMAIN EVENT TYPE ENUM
# ============================================================================


class DomainEventType(Enum):
    """Enumeration of all possible journal domain event types."""

    JOURNAL_CREATED = "journal_created"
    JOURNAL_UPDATED = "journal_updated"
    JOURNAL_SUBMITTED = "journal_submitted"
    JOURNAL_APPROVED = "journal_approved"
    JOURNAL_REJECTED = "journal_rejected"
    JOURNAL_POSTED = "journal_posted"
    JOURNAL_REVERSED = "journal_reversed"
    JOURNAL_VOIDED = "journal_voided"
    JOURNAL_ADJUSTED = "journal_adjusted"
    JOURNAL_ARCHIVED = "journal_archived"
    JOURNAL_CANCELLED = "journal_cancelled"
    JOURNAL_UNARCHIVED = "journal_unarchived"

    @classmethod
    def from_string(cls, value: str) -> DomainEventType:
        """Convert a string to a DomainEventType enum member."""
        normalized = value.lower()
        for member in cls:
            if member.value == normalized:
                return member
        return cls.JOURNAL_CREATED


# ============================================================================
# BASE DOMAIN EVENT
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class for all domain events.

    Attributes:
        event_type: Type of the domain event.
        aggregate_id: UUID of the aggregate root.
        aggregate_version: Version of the aggregate after applying this event.
        event_id: Unique identifier for this event instance (auto-generated).
        occurred_at: Timestamp when the event occurred (UTC).
        event_data: Additional structured data for the event.
        user_id: ID of the user who triggered the event (optional).
        correlation_id: ID to correlate related events in a flow (optional).
        causation_id: ID of the event that caused this one (optional).
    """

    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_json(self) -> str:
        """
        Serialize the event to a JSON string.

        Returns:
            JSON string representation of the event.
        """
        return json.dumps(
            {
                "event_id": str(self.event_id),
                "event_type": self.event_type.value,
                "aggregate_id": str(self.aggregate_id),
                "aggregate_version": self.aggregate_version,
                "occurred_at": self.occurred_at.isoformat(),
                "user_id": self.user_id,
                "correlation_id": self.correlation_id,
                "causation_id": self.causation_id,
                "event_data": self.event_data,
            },
            default=str,
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """
        Deserialize a JSON string back to a DomainEvent.

        Args:
            json_str: JSON string representation of the event.

        Returns:
            A DomainEvent instance.
        """
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType.from_string(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    def serialize(self) -> bytes:
        """
        Serialize the event to bytes (UTF-8 encoded JSON).

        Returns:
            Bytes representation of the event.
        """
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        """
        Deserialize bytes back to a DomainEvent.

        Args:
            data: Bytes representation of the event.

        Returns:
            A DomainEvent instance.
        """
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# CONCRETE JOURNAL EVENTS
# ============================================================================


class JournalCreatedEvent(DomainEvent):
    """Event emitted when a new journal entry is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        lines_count: int,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "journal_type": journal.journal_type.value,
            "transaction_date": journal.transaction_date.isoformat(),
            "description": journal.description,
            "legal_entity_id": str(journal.legal_entity_id),
            "lines_count": lines_count,
            "total_debit": str(journal.total_debit),
            "total_credit": str(journal.total_credit),
            "created_by": created_by,
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalSubmittedEvent(DomainEvent):
    """Event emitted when a journal entry is submitted for approval."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "submitted_by": submitted_by,
            "submitted_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_SUBMITTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalApprovedEvent(DomainEvent):
    """Event emitted when a journal entry is approved."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "approved_by": approved_by,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalRejectedEvent(DomainEvent):
    """Event emitted when a journal entry is rejected."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        rejected_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "rejected_by": rejected_by,
            "reason": reason,
            "rejected_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_REJECTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalPostedEvent(DomainEvent):
    """
    Event emitted when a journal entry is posted to the general ledger.

    This event includes validation to ensure the journal is balanced
    (total_debit == total_credit) before creation.
    """

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        total_debit: Decimal,
        total_credit: Decimal,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        # Domain validation: ensure double-entry balance is maintained
        if total_debit != total_credit:
            raise ValueError(
                f"Unbalanced journal: total_debit {total_debit} != total_credit {total_credit}"
            )
        if total_debit < 0 or total_credit < 0:
            raise ValueError(
                f"Debit and credit must be non-negative: debit={total_debit}, credit={total_credit}"
            )

        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "transaction_date": journal.transaction_date.isoformat(),
            "posting_date": datetime.now(UTC).isoformat(),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "posted_by": posted_by,
            "lines_count": len(getattr(journal, "lines", [])),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_POSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalReversedEvent(DomainEvent):
    """Event emitted when a journal entry is reversed."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        original_journal_id: UUID,
        reversal_journal_id: UUID,
        journal: JournalEntity,
        reversed_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "original_journal_id": str(original_journal_id),
            "reversal_journal_id": str(reversal_journal_id),
            "reversed_by": reversed_by,
            "reason": reason,
            "reversed_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_REVERSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalVoidedEvent(DomainEvent):
    """Event emitted when a journal entry is voided."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        voided_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "voided_by": voided_by,
            "reason": reason,
            "voided_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_VOIDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalAdjustedEvent(DomainEvent):
    """Event emitted when a journal entry is adjusted."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        adjusted_by: str,
        adjustment_reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "adjustment_reason": adjustment_reason,
            "adjusted_by": adjusted_by,
            "adjusted_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_ADJUSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalArchivedEvent(DomainEvent):
    """Event emitted when a journal entry is archived."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        archived_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "archived_by": archived_by,
            "archived_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_ARCHIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalUnarchivedEvent(DomainEvent):
    """Event emitted when a journal entry is unarchived."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        unarchived_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "unarchived_by": unarchived_by,
            "unarchived_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_UNARCHIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


class JournalCancelledEvent(DomainEvent):
    """Event emitted when a journal entry is cancelled."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ) -> None:
        event_data = {
            "journal_id": str(journal.journal_id),
            "journal_number": journal.journal_number,
            "cancelled_by": cancelled_by,
            "reason": reason,
            "cancelled_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.JOURNAL_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# ============================================================================
# ALIASES FOR BACKWARDS COMPATIBILITY
# ============================================================================

JournalCreated = JournalCreatedEvent
JournalSubmitted = JournalSubmittedEvent
JournalApproved = JournalApprovedEvent
JournalRejected = JournalRejectedEvent
JournalPosted = JournalPostedEvent
JournalReversed = JournalReversedEvent
JournalVoided = JournalVoidedEvent
JournalAdjusted = JournalAdjustedEvent
JournalArchived = JournalArchivedEvent
JournalUnarchived = JournalUnarchivedEvent
JournalCancelled = JournalCancelledEvent


# ============================================================================
# DOMAIN EVENT PUBLISHER INTERFACE
# ============================================================================


class DomainEventPublisher:
    """
    Abstract interface for publishing domain events.

    Implementations should handle delivery to message brokers, event stores,
    or other event consumers.
    """

    async def publish(self, event: DomainEvent) -> None:
        """
        Publish a single domain event.

        Args:
            event: The domain event to publish.

        Raises:
            EventPublishError: If publishing fails.
        """
        raise NotImplementedError("Subclasses must implement publish()")

    async def publish_many(self, events: list[DomainEvent]) -> None:
        """
        Publish multiple domain events sequentially.

        Args:
            events: List of domain events to publish.

        Raises:
            EventPublishError: If publishing fails for any event.
        """
        for event in events:
            await self.publish(event)

    async def publish_with_retry(
        self,
        event: DomainEvent,
        max_retries: int = 3,
    ) -> None:
        """
        Publish a domain event with exponential backoff retry logic.

        Args:
            event: The domain event to publish.
            max_retries: Maximum number of retry attempts.

        Raises:
            EventPublishTimeoutError: If all retry attempts fail.
            EventPublishUnexpectedError: If an unexpected error occurs.
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                await self.publish(event)
                return
            except (ConnectionError, TimeoutError, OSError) as e:
                # Retry-able network/timeout errors
                last_error = e
                wait_time = 0.1 * (2**attempt)  # Exponential backoff: 0.1, 0.2, 0.4...
                logging.warning(
                    "Event publish attempt %d/%d failed: %s. Retrying in %.2fs",
                    attempt + 1,
                    max_retries,
                    e,
                    wait_time,
                )
                await asyncio.sleep(wait_time)
            except EventPublishError:
                # Custom publish errors: re-raise immediately, do not retry
                # (retry logic should be handled by the caller if desired)
                raise
            except Exception as e:  # pylint: disable=broad-except
                # Unexpected error: log and re-raise as a specific exception
                # This is intentional to catch any unforeseen errors and wrap them.
                logging.error(
                    "Unexpected error during event publish: %s",
                    e,
                    exc_info=True,
                )
                raise EventPublishUnexpectedError(
                    f"Unexpected error publishing event {event.event_id}: {e}"
                ) from e

        # All retries exhausted
        raise EventPublishTimeoutError(
            f"Event publish failed after {max_retries} attempts"
        ) from last_error


# ============================================================================
# MODULE EXPORTS
# ============================================================================

__all__ = [
    # Base classes
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    # Exceptions
    "EventPublishError",
    "EventPublishTimeoutError",
    "EventPublishUnexpectedError",
    # Concrete events
    "JournalCreatedEvent",
    "JournalSubmittedEvent",
    "JournalApprovedEvent",
    "JournalRejectedEvent",
    "JournalPostedEvent",
    "JournalReversedEvent",
    "JournalVoidedEvent",
    "JournalAdjustedEvent",
    "JournalArchivedEvent",
    "JournalUnarchivedEvent",
    "JournalCancelledEvent",
    # Aliases
    "JournalCreated",
    "JournalSubmitted",
    "JournalApproved",
    "JournalRejected",
    "JournalPosted",
    "JournalReversed",
    "JournalVoided",
    "JournalAdjusted",
    "JournalArchived",
    "JournalUnarchived",
    "JournalCancelled",
]
