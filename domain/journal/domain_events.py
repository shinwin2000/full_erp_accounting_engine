#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Journal
Responsibility: Event: JournalPosted, JournalReversed, JournalVoided, dll.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.journal.journal_entity import JournalEntity


class DomainEventType(Enum):
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
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.JOURNAL_CREATED


@dataclass
class DomainEvent:
    # Non-default fields first (required)
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    # Default fields after
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def to_json(self) -> str:
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
        data = json.loads(json_str)
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType.from_string(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ==================== JOURNAL EVENTS ====================


@dataclass
class JournalCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        lines_count: int,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalSubmittedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalRejectedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        rejected_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalPostedEvent(DomainEvent):
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
    ):
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


@dataclass
class JournalReversedEvent(DomainEvent):
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
    ):
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


@dataclass
class JournalVoidedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        voided_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalAdjustedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        adjusted_by: str,
        adjustment_reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalArchivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        archived_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalUnarchivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        unarchived_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


@dataclass
class JournalCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        journal: JournalEntity,
        cancelled_by: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
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


# ==================== ALIASES ====================

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


# ==================== PUBLISHER ====================


class DomainEventPublisher:
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    async def publish_with_retry(self, event: DomainEvent, max_retries: int = 3) -> None:
        import asyncio

        last_error = None
        for attempt in range(max_retries):
            try:
                await self.publish(event)
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(0.1 * (2**attempt))
        raise last_error


__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "JournalAdjusted",
    "JournalAdjustedEvent",
    "JournalApproved",
    "JournalApprovedEvent",
    "JournalArchived",
    "JournalArchivedEvent",
    "JournalCancelled",
    "JournalCancelledEvent",
    "JournalCreated",
    "JournalCreatedEvent",
    "JournalPosted",
    "JournalPostedEvent",
    "JournalRejected",
    "JournalRejectedEvent",
    "JournalReversed",
    "JournalReversedEvent",
    "JournalSubmitted",
    "JournalSubmittedEvent",
    "JournalUnarchived",
    "JournalUnarchivedEvent",
    "JournalVoided",
    "JournalVoidedEvent",
]
