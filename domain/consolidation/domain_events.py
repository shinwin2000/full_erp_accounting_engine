#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Consolidation
Responsibility: Domain events untuk proses konsolidasi dengan semua method event.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

# ============================================================================
# Import event dari domain lain yang dibutuhkan oleh router yang salah import
# Ini adalah solusi cepat untuk mengatasi error import
# ============================================================================
from domain.legal_entity.domain_events import (
    LegalEntityCreatedEvent,
    LegalEntityDeactivatedEvent,
    LegalEntityUpdatedEvent,
)

logger = logging.getLogger(__name__)


class ConsolidationEventType(Enum):
    CONSOLIDATION_CREATED = "consolidation_created"
    CONSOLIDATION_STARTED = "consolidation_started"
    CONSOLIDATION_COMPLETED = "consolidation_completed"
    CONSOLIDATION_CANCELLED = "consolidation_cancelled"
    CONSOLIDATION_ARCHIVED = "consolidation_archived"
    INTERCOMPANY_TRANSACTION_DETECTED = "intercompany_transaction_detected"
    ELIMINATION_ENTRY_CREATED = "elimination_entry_created"
    NCI_CALCULATED = "nci_calculated"


@dataclass(frozen=True)
class DomainEvent:
    """
    Base domain event untuk consolidation.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (ConsolidationEventType).
        aggregate_id: UUID agregat.
        aggregate_type: Tipe agregat (default "ConsolidationGroup").
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
        causation_id: ID penyebab event (opsional).
        version: Versi event (default 1).
    """
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


@dataclass(frozen=True)
class ConsolidationCreated(DomainEvent):
    """
    Event yang diterbitkan ketika proses konsolidasi baru dibuat.

    Attributes:
        aggregate_id: ID agregat konsolidasi.
        group_code: Kode grup konsolidasi.
        group_name: Nama grup konsolidasi.
        period: Periode konsolidasi.
        created_by: User ID pembuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class ConsolidationStarted(DomainEvent):
    """
    Event yang diterbitkan ketika proses konsolidasi dimulai.

    Attributes:
        aggregate_id: ID agregat konsolidasi.
        started_by: User ID yang memulai.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class ConsolidationCompleted(DomainEvent):
    """
    Event yang diterbitkan ketika proses konsolidasi selesai.

    Attributes:
        consolidation_id: ID konsolidasi.
        group_entity_id: ID entitas grup.
        period_end_date: Tanggal akhir periode.
        total_eliminations: Total eliminasi.
        total_nci: Total NCI (Non-Controlling Interest).
        user_id: User ID penyelesaian.
        occurred_at: (opsional) Waktu kejadian.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class ConsolidationCancelled(DomainEvent):
    """
    Event yang diterbitkan ketika proses konsolidasi dibatalkan.

    Attributes:
        aggregate_id: ID agregat konsolidasi.
        cancelled_by: User ID pembatalan.
        reason: Alasan pembatalan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class ConsolidationArchived(DomainEvent):
    """
    Event yang diterbitkan ketika proses konsolidasi diarsipkan.

    Attributes:
        aggregate_id: ID agregat konsolidasi.
        archived_by: User ID pengarsip.
        reason: Alasan pengarsipan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class IntercompanyTransactionDetected(DomainEvent):
    """
    Event yang diterbitkan ketika transaksi intercompany terdeteksi.

    Attributes:
        transaction_id: ID transaksi.
        from_entity_id: ID entitas asal.
        to_entity_id: ID entitas tujuan.
        amount: Jumlah transaksi.
        detected_at: Waktu deteksi (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class EliminationEntryCreated(DomainEvent):
    """
    Event yang diterbitkan ketika entry eliminasi dibuat.

    Attributes:
        elimination_id: ID eliminasi.
        account_code: Kode akun.
        amount: Jumlah eliminasi.
        created_at: Waktu pembuatan (opsional).
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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


@dataclass(frozen=True)
class NCICalculated(DomainEvent):
    """
    Event yang diterbitkan ketika NCI (Non-Controlling Interest) dihitung.

    Attributes:
        aggregate_id: ID agregat konsolidasi.
        total_nci: Total NCI.
        calculated_by: User ID penghitung.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
        causation_id: (opsional) ID penyebab.
    """
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
    """
    Publisher untuk domain event Consolidation.
    Menyimpan event yang dipublikasikan untuk keperluan testing atau replay.
    """
    _published_events: ClassVar[list[DomainEvent]] = []

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publikasikan satu event."""
        cls._published_events.append(event)
        logging.getLogger(__name__).info(f"Published event: {event.event_type.value}")

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
# ALIAS UNTUK KOMPATIBILITAS DENGAN ROUTER
# Router mengimpor dengan suffix "Event"
# ============================================================================

# Alias classes dengan suffix Event untuk kompatibilitas
ConsolidationCreatedEvent = ConsolidationCreated
ConsolidationCreatedEvent.__name__ = "ConsolidationCreatedEvent"
"""Alias untuk ConsolidationCreated dengan suffix Event (kompatibilitas router)."""

ConsolidationStartedEvent = ConsolidationStarted
ConsolidationStartedEvent.__name__ = "ConsolidationStartedEvent"
"""Alias untuk ConsolidationStarted dengan suffix Event (kompatibilitas router)."""

ConsolidationCompletedEvent = ConsolidationCompleted
ConsolidationCompletedEvent.__name__ = "ConsolidationCompletedEvent"
"""Alias untuk ConsolidationCompleted dengan suffix Event (kompatibilitas router)."""

ConsolidationCancelledEvent = ConsolidationCancelled
ConsolidationCancelledEvent.__name__ = "ConsolidationCancelledEvent"
"""Alias untuk ConsolidationCancelled dengan suffix Event (kompatibilitas router)."""

ConsolidationArchivedEvent = ConsolidationArchived
ConsolidationArchivedEvent.__name__ = "ConsolidationArchivedEvent"
"""Alias untuk ConsolidationArchived dengan suffix Event (kompatibilitas router)."""

IntercompanyTransactionDetectedEvent = IntercompanyTransactionDetected
IntercompanyTransactionDetectedEvent.__name__ = "IntercompanyTransactionDetectedEvent"
"""Alias untuk IntercompanyTransactionDetected dengan suffix Event (kompatibilitas router)."""

EliminationEntryCreatedEvent = EliminationEntryCreated
EliminationEntryCreatedEvent.__name__ = "EliminationEntryCreatedEvent"
"""Alias untuk EliminationEntryCreated dengan suffix Event (kompatibilitas router)."""

NCICalculatedEvent = NCICalculated
NCICalculatedEvent.__name__ = "NCICalculatedEvent"
"""Alias untuk NCICalculated dengan suffix Event (kompatibilitas router)."""


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    # Original classes
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
    # Alias untuk router
    "ConsolidationCancelledEvent",
    "ConsolidationCompletedEvent",
    "ConsolidationCreatedEvent",
    "ConsolidationStartedEvent",
    "ConsolidationArchivedEvent",
    "EliminationEntryCreatedEvent",
    "IntercompanyTransactionDetectedEvent",
    "NCICalculatedEvent",
    # Event dari domain lain yang dibutuhkan (solusi cepat)
    "LegalEntityCreatedEvent",
    "LegalEntityDeactivatedEvent",
    "LegalEntityUpdatedEvent",
]