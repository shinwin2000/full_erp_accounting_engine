#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Goodwill
Responsibility: Domain events untuk goodwill.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    GOODWILL_RECOGNIZED = "goodwill_recognized"
    GOODWILL_IMPAIRED = "goodwill_impaired"
    GOODWILL_AMORTIZED = "goodwill_amortized"
    GOODWILL_IMPAIRMENT_REVERSED = "goodwill_impairment_reversed"
    GOODWILL_DISPOSED = "goodwill_disposed"
    GOODWILL_ALLOCATION_ADDED = "goodwill_allocation_added"
    GOODWILL_ALLOCATION_REMOVED = "goodwill_allocation_removed"

    def display_name(self) -> str:
        names = {
            DomainEventType.GOODWILL_RECOGNIZED: "Goodwill Recognized",
            DomainEventType.GOODWILL_IMPAIRED: "Goodwill Impaired",
            DomainEventType.GOODWILL_AMORTIZED: "Goodwill Amortized",
            DomainEventType.GOODWILL_IMPAIRMENT_REVERSED: "Goodwill Impairment Reversed",
            DomainEventType.GOODWILL_DISPOSED: "Goodwill Disposed",
            DomainEventType.GOODWILL_ALLOCATION_ADDED: "Goodwill Allocation Added",
            DomainEventType.GOODWILL_ALLOCATION_REMOVED: "Goodwill Allocation Removed",
        }
        return names.get(self, self.value)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass
class DomainEvent:
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_type: str
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "Goodwill"),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data["event_data"],
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# Concrete Domain Events
# ============================================================================


@dataclass
class GoodwillRecognizedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        amount: Decimal,
        acquisition_date: date,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
            "amount": str(amount),
            "acquisition_date": acquisition_date.isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_RECOGNIZED,
            aggregate_id=aggregate_id,
            aggregate_type="Goodwill",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class GoodwillImpairedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        impairment_loss: Decimal,
        new_carrying_amount: Decimal,
        recoverable_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
            "impairment_loss": str(impairment_loss),
            "new_carrying_amount": str(new_carrying_amount),
            "recoverable_amount": str(recoverable_amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_IMPAIRED,
            aggregate_id=aggregate_id,
            aggregate_type="Goodwill",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class GoodwillAmortizedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        amortization_amount: Decimal,
        new_carrying_amount: Decimal,
        period: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
            "amortization_amount": str(amortization_amount),
            "new_carrying_amount": str(new_carrying_amount),
            "period": period,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_AMORTIZED,
            aggregate_id=aggregate_id,
            aggregate_type="Goodwill",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class GoodwillImpairmentReversedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        reversal_amount: Decimal,
        new_carrying_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
            "reversal_amount": str(reversal_amount),
            "new_carrying_amount": str(new_carrying_amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_IMPAIRMENT_REVERSED,
            aggregate_id=aggregate_id,
            aggregate_type="Goodwill",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class GoodwillDisposedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        amount: Decimal,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
            "amount": str(amount),
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_DISPOSED,
            aggregate_id=aggregate_id,
            aggregate_type="Goodwill",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Short Aliases (for backward compatibility)
# ============================================================================

GoodwillRecognized = GoodwillRecognizedEvent
GoodwillImpaired = GoodwillImpairedEvent
GoodwillAmortized = GoodwillAmortizedEvent


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    _published_events: list[DomainEvent] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)

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


__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "GoodwillAmortized",
    "GoodwillAmortizedEvent",
    "GoodwillDisposedEvent",
    "GoodwillImpaired",
    "GoodwillImpairedEvent",
    "GoodwillImpairmentReversedEvent",
    "GoodwillRecognized",
    "GoodwillRecognizedEvent",
]
