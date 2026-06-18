#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Hedge
Responsibility: Domain events untuk hedge accounting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    HEDGE_DESIGNATED = "hedge_designated"
    HEDGE_DISCONTINUED = "hedge_discontinued"
    HEDGE_EFFECTIVENESS_TESTED = "hedge_effectiveness_tested"
    HEDGE_FAIR_VALUE_ADJUSTED = "hedge_fair_value_adjusted"
    HEDGE_AMOUNT_RECLASSIFIED = "hedge_amount_reclassified"
    HEDGE_CANCELLED = "hedge_cancelled"

    def display_name(self) -> str:
        names = {
            DomainEventType.HEDGE_DESIGNATED: "Hedge Designated",
            DomainEventType.HEDGE_DISCONTINUED: "Hedge Discontinued",
            DomainEventType.HEDGE_EFFECTIVENESS_TESTED: "Effectiveness Tested",
            DomainEventType.HEDGE_FAIR_VALUE_ADJUSTED: "Fair Value Adjusted",
            DomainEventType.HEDGE_AMOUNT_RECLASSIFIED: "Amount Reclassified",
            DomainEventType.HEDGE_CANCELLED: "Hedge Cancelled",
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
            aggregate_type=data.get("aggregate_type", "HedgeRelationship"),
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
class HedgeDesignatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        hedge_number: str,
        hedge_type: str,
        legal_entity_id: UUID,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "hedge_number": hedge_number,
            "hedge_type": hedge_type,
            "legal_entity_id": str(legal_entity_id),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_DESIGNATED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HedgeDiscontinuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        hedge_number: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "hedge_number": hedge_number,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_DISCONTINUED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HedgeEffectivenessTestedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        test_date: datetime,
        is_effective: bool,
        ratio: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "test_date": test_date.isoformat(),
            "is_effective": is_effective,
            "ratio": str(ratio),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_EFFECTIVENESS_TESTED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HedgeFairValueAdjustedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        hedge_number: str,
        adjustment_amount: Decimal,
        ineffectiveness: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "hedge_number": hedge_number,
            "adjustment_amount": str(adjustment_amount),
            "ineffectiveness": str(ineffectiveness),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_FAIR_VALUE_ADJUSTED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HedgeAmountReclassifiedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        hedge_number: str,
        reclassified_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "hedge_number": hedge_number,
            "reclassified_amount": str(reclassified_amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_AMOUNT_RECLASSIFIED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class HedgeCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        hedge_id: UUID,
        hedge_number: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "hedge_id": str(hedge_id),
            "hedge_number": hedge_number,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.HEDGE_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="HedgeRelationship",
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

HedgeDesignated = HedgeDesignatedEvent
HedgeDiscontinued = HedgeDiscontinuedEvent
HedgeEffectivenessTested = HedgeEffectivenessTestedEvent
HedgeFairValueAdjusted = HedgeFairValueAdjustedEvent
HedgeAmountReclassified = HedgeAmountReclassifiedEvent
HedgeCancelled = HedgeCancelledEvent


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
    "HedgeAmountReclassified",
    "HedgeAmountReclassifiedEvent",
    "HedgeCancelled",
    "HedgeCancelledEvent",
    "HedgeDesignated",
    "HedgeDesignatedEvent",
    "HedgeDiscontinued",
    "HedgeDiscontinuedEvent",
    "HedgeEffectivenessTested",
    "HedgeEffectivenessTestedEvent",
    "HedgeFairValueAdjusted",
    "HedgeFairValueAdjustedEvent",
]
