#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Goodwill
Responsibility: Domain events untuk goodwill.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

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
    GOODWILL_UPDATED = "goodwill_updated"

    def display_name(self) -> str:
        names = {
            DomainEventType.GOODWILL_RECOGNIZED: "Goodwill Recognized",
            DomainEventType.GOODWILL_IMPAIRED: "Goodwill Impaired",
            DomainEventType.GOODWILL_AMORTIZED: "Goodwill Amortized",
            DomainEventType.GOODWILL_IMPAIRMENT_REVERSED: "Goodwill Impairment Reversed",
            DomainEventType.GOODWILL_DISPOSED: "Goodwill Disposed",
            DomainEventType.GOODWILL_ALLOCATION_ADDED: "Goodwill Allocation Added",
            DomainEventType.GOODWILL_ALLOCATION_REMOVED: "Goodwill Allocation Removed",
            DomainEventType.GOODWILL_UPDATED: "Goodwill Updated",
        }
        return names.get(self, self.value)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di Goodwill.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (default "Goodwill").
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
    """
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
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert event ke dictionary."""
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
        """Serialize ke JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def serialize(self) -> bytes:
        """Serialize ke bytes."""
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Create event dari dictionary."""
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
        """Create event dari JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        """Deserialize dari bytes."""
        return cls.from_json(data.decode("utf-8"))


# ============================================================================
# Concrete Domain Events
# ============================================================================


@dataclass(frozen=True)
class GoodwillRecognizedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika goodwill baru diakui.

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        amount: Jumlah goodwill yang diakui.
        acquisition_date: Tanggal akuisisi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class GoodwillImpairedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika goodwill mengalami penurunan nilai (impairment).

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        impairment_loss: Jumlah kerugian impairment.
        new_carrying_amount: Nilai tercatat baru.
        recoverable_amount: Jumlah yang dapat dipulihkan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class GoodwillAmortizedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika goodwill diamortisasi.

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        amortization_amount: Jumlah amortisasi.
        new_carrying_amount: Nilai tercatat baru.
        period: Periode amortisasi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class GoodwillImpairmentReversedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika impairment goodwill dibalik.

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        reversal_amount: Jumlah pembalikan impairment.
        new_carrying_amount: Nilai tercatat baru.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class GoodwillDisposedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika goodwill dijual atau dihapus.

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        amount: Jumlah yang di-dispose.
        reason: Alasan disposisi.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class GoodwillUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika data goodwill diperbarui.

    Attributes:
        aggregate_id: ID agregat goodwill.
        aggregate_version: Versi agregat.
        goodwill_id: ID goodwill.
        goodwill_number: Nomor goodwill.
        amount: Jumlah goodwill (opsional).
        acquisition_date: Tanggal akuisisi (opsional).
        useful_life: Masa manfaat (opsional).
        amortization_method: Metode amortisasi (opsional).
        note: Catatan tambahan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        goodwill_id: UUID,
        goodwill_number: str,
        amount: Decimal | None = None,
        acquisition_date: date | None = None,
        useful_life: int | None = None,
        amortization_method: str | None = None,
        note: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "goodwill_id": str(goodwill_id),
            "goodwill_number": goodwill_number,
        }
        if amount is not None:
            event_data["amount"] = str(amount)
        if acquisition_date is not None:
            event_data["acquisition_date"] = acquisition_date.isoformat()
        if useful_life is not None:
            event_data["useful_life"] = useful_life
        if amortization_method is not None:
            event_data["amortization_method"] = amortization_method
        if note is not None:
            event_data["note"] = note

        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.GOODWILL_UPDATED,
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
GoodwillUpdated = GoodwillUpdatedEvent


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    """
    Publisher untuk domain event Goodwill.
    Menyimpan event yang dipublikasikan untuk keperluan testing atau replay.
    """
    _published_events: list[DomainEvent] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publikasikan satu event."""
        cls._published_events.append(event)
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        """Publikasikan banyak event."""
        for event in events:
            await cls.publish(event)

    @classmethod
    def get_published_events(cls) -> list[DomainEvent]:
        """Dapatkan semua event yang sudah dipublikasikan."""
        return cls._published_events.copy()

    @classmethod
    def clear(cls) -> None:
        """Hapus semua event yang sudah dipublikasikan."""
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
    "GoodwillUpdated",
    "GoodwillUpdatedEvent",
]