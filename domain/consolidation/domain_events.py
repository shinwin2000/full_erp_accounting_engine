#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Consolidation
Responsibility: Domain events untuk proses konsolidasi dengan semua method event.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4


class ConsolidationEventType(Enum):
    CONSOLIDATION_CREATED = "consolidation_created"
    CONSOLIDATION_STARTED = "consolidation_started"
    CONSOLIDATION_COMPLETED = "consolidation_completed"
    CONSOLIDATION_CANCELLED = "consolidation_cancelled"
    CONSOLIDATION_ARCHIVED = "consolidation_archived"
    INTERCOMPANY_TRANSACTION_DETECTED = "intercompany_transaction_detected"
    ELIMINATION_ENTRY_CREATED = "elimination_entry_created"
    NCI_CALCULATED = "nci_calculated"


@dataclass
class DomainEvent:
    """Base domain event untuk consolidation."""

    event_id: UUID
    event_type: ConsolidationEventType
    aggregate_id: UUID
    aggregate_type: str = "ConsolidationGroup"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: UUID | None = None
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
            "user_id": str(self.user_id) if self.user_id else None,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=ConsolidationEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "ConsolidationGroup"),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=UUID(data["user_id"]) if data.get("user_id") else None,
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            version=data.get("version", 1),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


@dataclass
class ConsolidationCreated(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        group_code: str,
        group_name: str,
        period: date,
        created_by: UUID,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "group_code": group_code,
            "group_name": group_name,
            "period": period.isoformat(),
            "created_by": str(created_by),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.CONSOLIDATION_CREATED,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class ConsolidationStarted(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        started_by: UUID,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {"started_by": str(started_by)}
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.CONSOLIDATION_STARTED,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class ConsolidationCompleted(DomainEvent):
    def __init__(
        self,
        consolidation_id: UUID,
        group_entity_id: UUID,
        period_end_date: date,
        total_eliminations: Decimal,
        total_nci: Decimal,
        user_id: UUID,
        occurred_at: datetime | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "consolidation_id": str(consolidation_id),
            "group_entity_id": str(group_entity_id),
            "period_end_date": period_end_date.isoformat(),
            "total_eliminations": str(total_eliminations),
            "total_nci": str(total_nci),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.CONSOLIDATION_COMPLETED,
            aggregate_id=consolidation_id,
            occurred_at=occurred_at or datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class ConsolidationCancelled(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        cancelled_by: UUID,
        reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {"cancelled_by": str(cancelled_by), "reason": reason}
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.CONSOLIDATION_CANCELLED,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class ConsolidationArchived(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        archived_by: UUID,
        reason: str | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {"archived_by": str(archived_by), "reason": reason}
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.CONSOLIDATION_ARCHIVED,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntercompanyTransactionDetected(DomainEvent):
    def __init__(
        self,
        transaction_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
        amount: Decimal,
        detected_at: datetime | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "transaction_id": str(transaction_id),
            "from_entity_id": str(from_entity_id),
            "to_entity_id": str(to_entity_id),
            "amount": str(amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.INTERCOMPANY_TRANSACTION_DETECTED,
            aggregate_id=transaction_id,
            occurred_at=detected_at or datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class EliminationEntryCreated(DomainEvent):
    def __init__(
        self,
        elimination_id: UUID,
        account_code: str,
        amount: Decimal,
        created_at: datetime | None = None,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "elimination_id": str(elimination_id),
            "account_code": account_code,
            "amount": str(amount),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.ELIMINATION_ENTRY_CREATED,
            aggregate_id=elimination_id,
            occurred_at=created_at or datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class NCICalculated(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        total_nci: Decimal,
        calculated_by: UUID,
        user_id: UUID | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {"total_nci": str(total_nci), "calculated_by": str(calculated_by)}
        super().__init__(
            event_id=uuid4(),
            event_type=ConsolidationEventType.NCI_CALCULATED,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


class ConsolidationEventPublisher:
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)
        import logging

        logging.getLogger(__name__).info(f"Published event: {event.event_type.value}")

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
    "ConsolidationCancelled",
    "ConsolidationCompleted",
    "ConsolidationCreated",
    "ConsolidationEventPublisher",
    "ConsolidationEventType",
    "ConsolidationStarted",
    "DomainEvent",
    "EliminationEntryCreated",
    "IntercompanyTransactionDetected",
    "NCICalculated",
]
