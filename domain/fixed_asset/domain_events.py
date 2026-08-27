#!/usr/bin/env python3
"""
Module: domain_events.py

Layer: Domain / Fixed Asset

Responsibility:
    Domain events for Fixed Asset aggregate.

    Defines all domain events emitted by Fixed Asset aggregates:
    - Asset acquisition, update, depreciation posting
    - Revaluation, disposal, transfer
    - Impairment recognition, fully depreciated status

    Events are immutable value objects used for event sourcing,
    integration with other bounded contexts (general ledger, tax, reporting),
    and building read models (projections).

Business rules:
    - Events are immutable value objects.
    - Each event contains aggregate_id, aggregate_version, timestamp, event data.
    - Events can be serialized to/from JSON for persistence and messaging.
    - Correlation_id and causation_id support event tracing.

Dependencies:
    - Python standard library (uuid, datetime, dataclass, json, enum)
    - domain.fixed_asset.asset_entity (FixedAsset, AssetStatus, AssetType)
    - domain.fixed_asset.depreciation_schedule_engine (DepreciationMethod)

Audit:
    All events are part of the immutable audit trail.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.fixed_asset.asset_entity import FixedAsset

# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    """Types of domain events in Fixed Asset context."""

    ASSET_ACQUIRED = "asset_acquired"
    ASSET_UPDATED = "asset_updated"
    ASSET_DEPRECIATION_POSTED = "asset_depreciation_posted"
    ASSET_REVALUATED = "asset_revaluated"
    ASSET_DISPOSED = "asset_disposed"
    ASSET_TRANSFERRED = "asset_transferred"
    ASSET_IMPAIRED = "asset_impaired"
    ASSET_IMPAIRMENT_REVERSED = "asset_impairment_reversed"
    ASSET_FULLY_DEPRECIATED = "asset_fully_depreciated"
    ASSET_GROUP_CREATED = "asset_group_created"
    ASSET_GROUP_UPDATED = "asset_group_updated"

    def is_asset_event(self) -> bool:
        """Check if event relates to a single asset."""
        asset_events = {
            DomainEventType.ASSET_ACQUIRED,
            DomainEventType.ASSET_UPDATED,
            DomainEventType.ASSET_DEPRECIATION_POSTED,
            DomainEventType.ASSET_REVALUATED,
            DomainEventType.ASSET_DISPOSED,
            DomainEventType.ASSET_TRANSFERRED,
            DomainEventType.ASSET_IMPAIRED,
            DomainEventType.ASSET_IMPAIRMENT_REVERSED,
            DomainEventType.ASSET_FULLY_DEPRECIATED,
        }
        return self in asset_events

    def is_group_event(self) -> bool:
        """Check if event relates to an asset group."""
        return self in (DomainEventType.ASSET_GROUP_CREATED, DomainEventType.ASSET_GROUP_UPDATED)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass
class DomainEvent:
    """
    Base class for all domain events in Fixed Asset context.

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
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")

    def to_dict(self) -> dict[str, Any]:
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
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
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
        return cls.from_dict(json.loads(json_str))


# ============================================================================
# Asset Acquisition Event
# ============================================================================


@dataclass
class AssetAcquiredEvent(DomainEvent):
    """Emitted when a new fixed asset is acquired."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        acquired_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "asset_type": asset.asset_type.value,
            "asset_type_display": asset.asset_type.display_name(),
            "status": asset.status.value,
            "acquisition_date": asset.acquisition_date.isoformat(),
            "acquisition_cost": str(asset.acquisition_cost),
            "salvage_value": str(asset.salvage_value),
            "useful_life_years": asset.useful_life_years,
            "depreciation_method": asset.depreciation_method.value
            if hasattr(asset.depreciation_method, "value")
            else str(asset.depreciation_method),
            "currency": asset.currency,
            "location": asset.location,
            "category": asset.category,
            "acquired_by": acquired_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_ACQUIRED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Update Event
# ============================================================================


@dataclass
class AssetUpdatedEvent(DomainEvent):
    """Emitted when an asset is updated (name, description, location, etc.)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Depreciation Event
# ============================================================================


@dataclass
class AssetDepreciationPostedEvent(DomainEvent):
    """Emitted when depreciation is posted for an asset."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        period: str,
        amount: Decimal,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "period": period,
            "depreciation_amount": str(amount),
            "accumulated_depreciation_before": str(asset.accumulated_depreciation - amount),
            "accumulated_depreciation_after": str(asset.accumulated_depreciation),
            "nbv_before": str(asset.net_book_value + amount),
            "nbv_after": str(asset.net_book_value),
            "posted_by": posted_by,
            "is_fully_depreciated_after": asset.is_fully_depreciated,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_DEPRECIATION_POSTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Revaluation Event
# ============================================================================


@dataclass
class AssetRevaluatedEvent(DomainEvent):
    """Emitted when an asset is revalued."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        old_value: Decimal,
        new_value: Decimal,
        revaluation_surplus: Decimal,
        revaluation_method: str,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "revaluation_surplus": str(revaluation_surplus),
            "revaluation_method": revaluation_method,
            "approved_by": approved_by,
            "new_nbv": str(asset.net_book_value),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_REVALUATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Disposal Event
# ============================================================================


@dataclass
class AssetDisposedEvent(DomainEvent):
    """Emitted when an asset is disposed (sold, scrapped, donated, etc.)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        disposal_date: date,
        disposal_type: str,
        proceeds: Decimal,
        gain_loss: Decimal,
        disposed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "disposal_date": disposal_date.isoformat(),
            "disposal_type": disposal_type,
            "proceeds": str(proceeds),
            "nbv_at_disposal": str(asset.net_book_value),
            "gain_loss": str(gain_loss),
            "is_gain": gain_loss > 0,
            "is_loss": gain_loss < 0,
            "disposed_by": disposed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_DISPOSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Transfer Event
# ============================================================================


@dataclass
class AssetTransferredEvent(DomainEvent):
    """Emitted when an asset is transferred (department, location, etc.)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        transfer_type: str,
        source: str,
        destination: str,
        transferred_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "transfer_type": transfer_type,
            "source": source,
            "destination": destination,
            "transfer_date": date.today().isoformat(),
            "transferred_by": transferred_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_TRANSFERRED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Impairment Event
# ============================================================================


@dataclass
class AssetImpairedEvent(DomainEvent):
    """Emitted when an asset is impaired (PSAK 48 / IAS 36)."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        carrying_amount: Decimal,
        recoverable_amount: Decimal,
        impairment_loss: Decimal,
        indicators: list[str],
        tested_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "carrying_amount": str(carrying_amount),
            "recoverable_amount": str(recoverable_amount),
            "impairment_loss": str(impairment_loss),
            "accumulated_impairment": str(asset.accumulated_impairment),
            "indicators": indicators,
            "tested_by": tested_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_IMPAIRED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Impairment Reversal Event
# ============================================================================


@dataclass
class AssetImpairmentReversedEvent(DomainEvent):
    """Emitted when an asset's impairment is reversed."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        previous_impairment: Decimal,
        reversal_amount: Decimal,
        recoverable_amount: Decimal,
        tested_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "previous_impairment": str(previous_impairment),
            "reversal_amount": str(reversal_amount),
            "recoverable_amount": str(recoverable_amount),
            "current_impairment": str(asset.accumulated_impairment),
            "tested_by": tested_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_IMPAIRMENT_REVERSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Fully Depreciated Event
# ============================================================================


@dataclass
class AssetFullyDepreciatedEvent(DomainEvent):
    """Emitted when an asset becomes fully depreciated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: FixedAsset,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.id),
            "asset_code": asset.asset_code,
            "asset_name": asset.name,
            "acquisition_cost": str(asset.acquisition_cost),
            "salvage_value": str(asset.salvage_value),
            "accumulated_depreciation": str(asset.accumulated_depreciation),
            "final_nbv": str(asset.net_book_value),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_FULLY_DEPRECIATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Asset Group Events
# ============================================================================


@dataclass
class AssetGroupCreatedEvent(DomainEvent):
    """Emitted when an asset group is created."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        group_id: UUID,
        group_code: str,
        group_name: str,
        group_type: str,
        parent_group_id: UUID | None,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "group_id": str(group_id),
            "group_code": group_code,
            "group_name": group_name,
            "group_type": group_type,
            "parent_group_id": str(parent_group_id) if parent_group_id else None,
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_GROUP_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class AssetGroupUpdatedEvent(DomainEvent):
    """Emitted when an asset group is updated."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        group_id: UUID,
        group_code: str,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "group_id": str(group_id),
            "group_code": group_code,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_GROUP_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Short Aliases (for backward compatibility with aggregate_root.py and __init__.py)
# ============================================================================

AssetAcquired = AssetAcquiredEvent
AssetUpdated = AssetUpdatedEvent
AssetDepreciated = AssetDepreciationPostedEvent
AssetRevalued = AssetRevaluatedEvent
AssetDisposed = AssetDisposedEvent
AssetTransferred = AssetTransferredEvent
AssetImpaired = AssetImpairedEvent
AssetImpairmentReversed = AssetImpairmentReversedEvent
AssetFullyDepreciated = AssetFullyDepreciatedEvent
AssetGroupCreated = AssetGroupCreatedEvent
AssetGroupUpdated = AssetGroupUpdatedEvent

# ====== TAMBAHAN ALIAS UNTUK MEMENUHI IMPOR DARI __init__.py ======
AssetImpairmentRecognized = (
    AssetImpairedEvent  # Alias untuk yang diimpor sebagai AssetImpairmentRecognized
)


# ============================================================================
# Domain Event Publisher Protocol
# ============================================================================


class DomainEventPublisher:
    """Protocol for publishing domain events to message bus / event store."""

    async def publish(self, event: DomainEvent) -> None:
        """Publish a single domain event."""
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await self.publish(event)


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    """Deserialize JSON string to appropriate DomainEvent subclass."""
    return DomainEvent.from_dict(json.loads(json_str))


def serialize_domain_event(event: DomainEvent) -> str:
    """Serialize domain event to JSON string."""
    return event.to_json()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AssetAcquired",
    "AssetAcquiredEvent",
    "AssetDepreciated",
    "AssetDepreciationPostedEvent",
    "AssetDisposed",
    "AssetDisposedEvent",
    "AssetFullyDepreciated",
    "AssetFullyDepreciatedEvent",
    "AssetGroupCreated",
    "AssetGroupCreatedEvent",
    "AssetGroupUpdated",
    "AssetGroupUpdatedEvent",
    "AssetImpaired",
    "AssetImpairedEvent",
    "AssetImpairmentRecognized",
    "AssetImpairmentReversed",
    "AssetImpairmentReversedEvent",
    "AssetRevaluatedEvent",
    "AssetRevalued",
    "AssetTransferred",
    "AssetTransferredEvent",
    "AssetUpdated",
    "AssetUpdatedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "deserialize_domain_event",
    "serialize_domain_event",
]
