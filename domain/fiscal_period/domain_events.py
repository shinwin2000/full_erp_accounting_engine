#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Fiscal Period
Responsibility: Domain events untuk Fiscal Period aggregate.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

from domain.fiscal_period.aggregate_root import PeriodStatus, PeriodType

logger = logging.getLogger(__name__)


# ============================================================================
# Domain Event Type Enum
# ============================================================================


class DomainEventType(Enum):
    PERIOD_OPENED = "period_opened"
    PERIOD_LOCKED = "period_locked"
    PERIOD_CLOSED = "period_closed"
    PERIOD_REOPENED = "period_reopened"
    PERIOD_CREATED = "period_created"
    PERIOD_UPDATED = "period_updated"
    PERIOD_STATUS_CHANGED = "period_status_changed"

    def display_name(self) -> str:
        names = {
            DomainEventType.PERIOD_OPENED: "Period Opened",
            DomainEventType.PERIOD_LOCKED: "Period Locked",
            DomainEventType.PERIOD_CLOSED: "Period Closed",
            DomainEventType.PERIOD_REOPENED: "Period Reopened",
            DomainEventType.PERIOD_CREATED: "Period Created",
            DomainEventType.PERIOD_UPDATED: "Period Updated",
            DomainEventType.PERIOD_STATUS_CHANGED: "Period Status Changed",
        }
        return names.get(self, self.value)


# ============================================================================
# Base Domain Event Class
# ============================================================================


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di Fiscal Period.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (default "FiscalPeriod").
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
            aggregate_type=data.get("aggregate_type", "FiscalPeriod"),
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
class PeriodCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika periode fiskal baru dibuat.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_type: Tipe periode (bulanan/tahunan).
        period_number: Nomor periode (1-12 untuk bulanan, 1 untuk tahunan).
        year: Tahun periode.
        start_date: Tanggal mulai periode.
        end_date: Tanggal akhir periode.
        status: Status awal periode.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        created_by: User ID pembuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_type: PeriodType,
        period_number: int,
        year: int,
        start_date: datetime,
        end_date: datetime,
        status: PeriodStatus,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        created_by: str = "",
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_type": period_type.value if hasattr(period_type, "value") else str(period_type),
            "period_number": period_number,
            "year": year,
            "start_date": start_date.isoformat()
            if hasattr(start_date, "isoformat")
            else str(start_date),
            "end_date": end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date),
            "status": status.value if hasattr(status, "value") else str(status),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_CREATED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodOpenedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika periode fiskal dibuka.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_display: Representasi periode (misal "2024-01").
        opened_by: User ID yang membuka.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        previous_status: Status sebelumnya (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_display: str,
        opened_by: str,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        previous_status: PeriodStatus | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_display": period_display,
            "opened_by": opened_by,
            "previous_status": previous_status.value
            if previous_status and hasattr(previous_status, "value")
            else (str(previous_status) if previous_status else None),
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_OPENED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodLockedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika periode fiskal dikunci.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_display: Representasi periode.
        locked_by: User ID yang mengunci.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_display: str,
        locked_by: str,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_display": period_display,
            "locked_by": locked_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_LOCKED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodClosedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika periode fiskal ditutup.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_display: Representasi periode.
        closed_by: User ID yang menutup.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_display: str,
        closed_by: str,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_display": period_display,
            "closed_by": closed_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_CLOSED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodReopenedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika periode fiskal dibuka kembali.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_display: Representasi periode.
        reopened_by: User ID yang membuka kembali.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        reason: Alasan pembukaan kembali (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_display: str,
        reopened_by: str,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        reason: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_display": period_display,
            "reopened_by": reopened_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_REOPENED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika data periode fiskal diperbarui.

    Attributes:
        legal_entity_id: ID entitas legal.
        period_display: Representasi periode.
        changes: Dictionary perubahan field.
        updated_by: User ID pengubah.
        aggregate_id: ID agregat (opsional, default dari legal_entity_id).
        aggregate_version: Versi agregat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
    def __init__(
        self,
        legal_entity_id: UUID,
        period_display: str,
        changes: dict[str, Any],
        updated_by: str,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "period_display": period_display,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_UPDATED,
            aggregate_id=aggregate_id or legal_entity_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass(frozen=True)
class PeriodStatusChangedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika status periode fiskal berubah.

    Attributes:
        aggregate_id: ID agregat (opsional, default dari period_id).
        aggregate_version: Versi agregat.
        old_status: Status lama.
        new_status: Status baru.
        changed_by: User ID pengubah (default "system").
        reason: Alasan perubahan status (opsional).
        metadata: Metadata tambahan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
        **kwargs: Parameter tambahan (period_id, old_status, new_status, changed_by, dll).
    """
    def __init__(
        self,
        aggregate_id: UUID | None = None,
        aggregate_version: int = 1,
        old_status: PeriodStatus | None = None,
        new_status: PeriodStatus | None = None,
        changed_by: str | None = None,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        **kwargs,
    ):
        target_aggregate_id = aggregate_id or kwargs.get("period_id") or uuid4()
        actual_old_status = old_status or kwargs.get("old_status")
        actual_new_status = new_status or kwargs.get("new_status")
        actual_changed_by = changed_by or kwargs.get("changed_by") or "system"

        event_data = {
            "old_status": actual_old_status.value
            if hasattr(actual_old_status, "value")
            else str(actual_old_status),
            "new_status": actual_new_status.value
            if hasattr(actual_new_status, "value")
            else str(actual_new_status),
            "changed_by": actual_changed_by,
            "reason": reason or kwargs.get("reason"),
            "metadata": metadata or kwargs.get("metadata") or {},
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.PERIOD_STATUS_CHANGED,
            aggregate_id=target_aggregate_id,
            aggregate_type="FiscalPeriod",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ============================================================================
# Domain Event Publisher
# ============================================================================


class DomainEventPublisher:
    """
    Publisher untuk domain event Fiscal Period.
    Menyimpan event yang dipublikasikan untuk keperluan testing atau replay.
    """
    _published_events: ClassVar[list[DomainEvent]] = []

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


# ============================================================================
# Helper Functions
# ============================================================================


def deserialize_domain_event(json_str: str) -> DomainEvent:
    """
    Deserialize JSON string menjadi DomainEvent.

    Args:
        json_str: String JSON.

    Returns:
        DomainEvent: Objek event.
    """
    data = json.loads(json_str)
    event_type = DomainEventType(data["event_type"])
    return DomainEvent.from_dict(data)


def serialize_domain_event(event: DomainEvent) -> str:
    """
    Serialize DomainEvent menjadi JSON string.

    Args:
        event: DomainEvent yang akan diserialisasi.

    Returns:
        str: String JSON.
    """
    return event.to_json()


__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "PeriodClosedEvent",
    "PeriodCreatedEvent",
    "PeriodLockedEvent",
    "PeriodOpenedEvent",
    "PeriodReopenedEvent",
    "PeriodStatusChangedEvent",
    "PeriodUpdatedEvent",
    "deserialize_domain_event",
    "serialize_domain_event",
]
