#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Intangible Asset
Responsibility: Domain events untuk aset tak berwujud dengan semua method event.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.intangible_asset.asset_entity import (
    IntangibleAssetEntity,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    """Tipe domain event untuk Intangible Asset."""

    ASSET_ACQUIRED = "asset_acquired"
    ASSET_UPDATED = "asset_updated"
    ASSET_AMORTIZATION_POSTED = "asset_amortization_posted"
    ASSET_IMPAIRED = "asset_impaired"
    ASSET_IMPAIRMENT_REVERSED = "asset_impairment_reversed"
    ASSET_DISPOSED = "asset_disposed"
    ASSET_FULLY_AMORTIZED = "asset_fully_amortized"
    ASSET_REVALUATED = "asset_revaluated"
    ASSET_TRANSFERRED = "asset_transferred"

    def display_name(self) -> str:
        names = {
            DomainEventType.ASSET_ACQUIRED: "Asset Acquired",
            DomainEventType.ASSET_UPDATED: "Asset Updated",
            DomainEventType.ASSET_AMORTIZATION_POSTED: "Amortization Posted",
            DomainEventType.ASSET_IMPAIRED: "Asset Impaired",
            DomainEventType.ASSET_IMPAIRMENT_REVERSED: "Impairment Reversed",
            DomainEventType.ASSET_DISPOSED: "Asset Disposed",
            DomainEventType.ASSET_FULLY_AMORTIZED: "Fully Amortized",
            DomainEventType.ASSET_REVALUATED: "Asset Revaluated",
            DomainEventType.ASSET_TRANSFERRED: "Asset Transferred",
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
            aggregate_type=data.get("aggregate_type", "IntangibleAsset"),
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
class IntangibleAssetAcquiredEvent(DomainEvent):
    """Event ketika aset tak berwujud baru diperoleh."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        acquired_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "asset_type": asset.asset_type.value,
            "acquisition_date": asset.acquisition_date.isoformat(),
            "cost": str(asset.cost),
            "currency": asset.currency,
            "residual_value": str(asset.residual_value),
            "useful_life_years": asset.useful_life_years,
            "amortization_method": asset.amortization_method.value,
            "has_indefinite_life": asset.has_indefinite_life,
            "acquired_by": acquired_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_ACQUIRED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetUpdatedEvent(DomainEvent):
    """Event ketika aset tak berwujud diperbarui."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        changes: dict[str, Any],
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetAmortizationPostedEvent(DomainEvent):
    """Event ketika amortisasi aset tak berwujud diposting."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        period: str,
        amount: Decimal,
        posted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "period": period,
            "amortization_amount": str(amount),
            "accumulated_amortization_before": str(asset.accumulated_amortization - amount),
            "accumulated_amortization_after": str(asset.accumulated_amortization),
            "nbv_before": str(asset.nbv + amount),
            "nbv_after": str(asset.nbv),
            "posted_by": posted_by,
            "is_fully_amortized_after": asset.is_fully_amortized,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_AMORTIZATION_POSTED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetImpairedEvent(DomainEvent):
    """Event ketika aset tak berwujud mengalami penurunan nilai."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        impairment_loss: Decimal,
        impaired_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "impairment_loss": str(impairment_loss),
            "nbv_before": str(asset.nbv + impairment_loss),
            "nbv_after": str(asset.nbv),
            "cost_before": str(asset.cost + impairment_loss),
            "cost_after": str(asset.cost),
            "impaired_by": impaired_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_IMPAIRED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetImpairmentReversedEvent(DomainEvent):
    """Event ketika penurunan nilai aset tak berwujud dipulihkan."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        reversal_amount: Decimal,
        reversed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "reversal_amount": str(reversal_amount),
            "nbv_before": str(asset.nbv - reversal_amount),
            "nbv_after": str(asset.nbv),
            "cost_before": str(asset.cost - reversal_amount),
            "cost_after": str(asset.cost),
            "reversed_by": reversed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_IMPAIRMENT_REVERSED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetDisposedEvent(DomainEvent):
    """Event ketika aset tak berwujud dihapus/dijual."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        disposal_date: datetime,
        proceeds: Decimal,
        gain_loss: Decimal,
        disposed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "disposal_date": disposal_date.isoformat(),
            "proceeds": str(proceeds),
            "nbv_at_disposal": str(asset.nbv),
            "gain_loss": str(gain_loss),
            "is_gain": gain_loss > 0,
            "is_loss": gain_loss < 0,
            "disposed_by": disposed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_DISPOSED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetFullyAmortizedEvent(DomainEvent):
    """Event ketika aset tak berwujud telah habis diamortisasi."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "cost": str(asset.cost),
            "residual_value": str(asset.residual_value),
            "accumulated_amortization": str(asset.accumulated_amortization),
            "final_nbv": str(asset.nbv),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_FULLY_AMORTIZED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetRevaluatedEvent(DomainEvent):
    """Event ketika aset tak berwujud direvaluasi."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
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
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "revaluation_surplus": str(revaluation_surplus),
            "revaluation_method": revaluation_method,
            "approved_by": approved_by,
            "new_nbv": str(asset.nbv),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_REVALUATED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class IntangibleAssetTransferredEvent(DomainEvent):
    """Event ketika aset tak berwujud ditransfer."""

    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        asset: IntangibleAssetEntity,
        from_legal_entity_id: UUID,
        to_legal_entity_id: UUID,
        transferred_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "asset_id": str(asset.asset_id),
            "asset_code": asset.asset_code,
            "asset_name": asset.asset_name,
            "from_legal_entity_id": str(from_legal_entity_id),
            "to_legal_entity_id": str(to_legal_entity_id),
            "transferred_by": transferred_by,
            "transfer_date": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.ASSET_TRANSFERRED,
            aggregate_id=aggregate_id,
            aggregate_type="IntangibleAsset",
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

IntangibleAssetAcquired = IntangibleAssetAcquiredEvent
IntangibleAssetUpdated = IntangibleAssetUpdatedEvent
IntangibleAssetAmortizationPosted = IntangibleAssetAmortizationPostedEvent
IntangibleAssetImpaired = IntangibleAssetImpairedEvent
IntangibleAssetImpairmentReversed = IntangibleAssetImpairmentReversedEvent
IntangibleAssetDisposed = IntangibleAssetDisposedEvent
IntangibleAssetFullyAmortized = IntangibleAssetFullyAmortizedEvent
IntangibleAssetRevaluated = IntangibleAssetRevaluatedEvent
IntangibleAssetTransferred = IntangibleAssetTransferredEvent


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        cls._published_events.append(event)
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

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
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    data = json.loads(json_str)
    event_type = DomainEventType(data["event_type"])
    return DomainEvent.from_dict(data)


def serialize_domain_event(event: DomainEvent) -> str:
    return event.to_json()


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "IntangibleAssetAcquired",
    "IntangibleAssetAcquiredEvent",
    "IntangibleAssetAmortizationPosted",
    "IntangibleAssetAmortizationPostedEvent",
    "IntangibleAssetDisposed",
    "IntangibleAssetDisposedEvent",
    "IntangibleAssetFullyAmortized",
    "IntangibleAssetFullyAmortizedEvent",
    "IntangibleAssetImpaired",
    "IntangibleAssetImpairedEvent",
    "IntangibleAssetImpairmentReversed",
    "IntangibleAssetImpairmentReversedEvent",
    "IntangibleAssetRevaluated",
    "IntangibleAssetRevaluatedEvent",
    "IntangibleAssetTransferred",
    "IntangibleAssetTransferredEvent",
    "IntangibleAssetUpdated",
    "IntangibleAssetUpdatedEvent",
    "deserialize_domain_event",
    "serialize_domain_event",
]
