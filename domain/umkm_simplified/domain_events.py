#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / UMKM Simplified
Responsibility: Domain events untuk transaksi UMKM.

Metode entity dasar untuk DomainEvent.
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

from domain.umkm_simplified.simplified_journal_entity import SimplifiedJournalEntity

logger = logging.getLogger(__name__)


class DomainEventType(Enum):
    TRANSACTION_CREATED = "transaction_created"
    TRANSACTION_UPDATED = "transaction_updated"
    TRANSACTION_DELETED = "transaction_deleted"
    TAX_CALCULATED = "tax_calculated"
    TRANSACTION_RECORDED = "transaction_recorded"


@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di UMKM Simplified.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
    """
    event_id: UUID
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    occurred_at: datetime
    event_data: dict[str, Any]
    user_id: str | None = None
    correlation_id: str | None = None

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    def validate(self) -> dict[str, Any]:
        """Validasi event."""
        errors = []
        if not isinstance(self.event_type, DomainEventType):
            errors.append("Invalid event_type")
        if self.aggregate_version < 1:
            errors.append("aggregate_version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
            "event_data": self.event_data,
            "user_id": self.user_id,
            "correlation_id": self.correlation_id,
        }

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def serialize(self) -> bytes:
        """Serialize to bytes."""
        return self.to_json().encode("utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DomainEvent:
        """Create event from dictionary."""
        return cls(
            event_id=UUID(data["event_id"]),
            event_type=DomainEventType(data["event_type"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Create event from JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        """Deserialize from bytes."""
        return cls.from_json(data.decode("utf-8"))

    def clone(self) -> DomainEvent:
        """Clone event with new event_id and occurred_at."""
        return DomainEvent(
            event_id=uuid4(),
            event_type=self.event_type,
            aggregate_id=self.aggregate_id,
            aggregate_version=self.aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=self.event_data.copy(),
            user_id=self.user_id,
            correlation_id=self.correlation_id,
        )

    def snapshot(self) -> dict[str, Any]:
        """Create snapshot of event."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "occurred_at": self.occurred_at.isoformat(),
        }

    def version(self) -> int:
        """Get version (events are immutable, returns 1)."""
        return 1

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get audit trail entries (limited)."""
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DomainEvent:
        """Touch event (returns clone)."""
        return self.clone()


# Concrete events (sama seperti sebelumnya, hanya menggunakan super().__init__)
@dataclass(frozen=True)
class TransactionCreatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika transaksi UMKM baru dibuat.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        transaction: Entity SimplifiedJournalEntity.
        created_by: User ID pembuat.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction: SimplifiedJournalEntity,
        created_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "journal_id": str(transaction.journal_id),
            "journal_number": transaction.journal_number,
            "transaction_type": transaction.transaction_type.value,
            "amount": str(transaction.amount),
            "description": transaction.description,
            "category": transaction.category,
            "payment_method": transaction.payment_method.value,
            "transaction_date": transaction.transaction_date.isoformat(),
            "created_by": created_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TRANSACTION_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class TransactionUpdatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika transaksi UMKM diubah.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        old_transaction: Entity lama.
        new_transaction: Entity baru.
        updated_by: User ID pengubah.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        old_transaction: SimplifiedJournalEntity,
        new_transaction: SimplifiedJournalEntity,
        updated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        changes = []
        if old_transaction.amount != new_transaction.amount:
            changes.append(f"amount: {old_transaction.amount} -> {new_transaction.amount}")
        if old_transaction.description != new_transaction.description:
            changes.append("description changed")
        if old_transaction.category != new_transaction.category:
            changes.append(f"category: {old_transaction.category} -> {new_transaction.category}")
        event_data = {
            "journal_id": str(new_transaction.journal_id),
            "journal_number": new_transaction.journal_number,
            "changes": changes,
            "updated_by": updated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TRANSACTION_UPDATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class TransactionDeletedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika transaksi UMKM dihapus.

    Attributes:
        aggregate_id: ID agregat transaksi.
        aggregate_version: Versi agregat.
        transaction: Entity SimplifiedJournalEntity.
        deleted_by: User ID penghapus.
        reason: Alasan penghapusan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        transaction: SimplifiedJournalEntity,
        deleted_by: str,
        reason: str = "",
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "journal_id": str(transaction.journal_id),
            "journal_number": transaction.journal_number,
            "transaction_type": transaction.transaction_type.value,
            "amount": str(transaction.amount),
            "deleted_by": deleted_by,
            "reason": reason,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TRANSACTION_DELETED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class TaxCalculatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika pajak UMKM dihitung.

    Attributes:
        aggregate_id: ID agregat perhitungan pajak.
        aggregate_version: Versi agregat.
        period: Periode pajak.
        total_revenue: Total pendapatan.
        tax_amount: Jumlah pajak.
        tax_rate: Tarif pajak.
        calculated_by: User ID penghitung.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        period: str,
        total_revenue: Decimal,
        tax_amount: Decimal,
        tax_rate: Decimal,
        calculated_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "period": period,
            "total_revenue": str(total_revenue),
            "tax_amount": str(tax_amount),
            "tax_rate": str(tax_rate),
            "calculated_by": calculated_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TAX_CALCULATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class TransactionRecordedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika transaksi UMKM dicatat (simple).

    Attributes:
        transaction_id: ID transaksi.
        amount: Jumlah transaksi.
        transaction_type: Jenis transaksi.
        user_id: User ID pencatat.
        occurred_at: Waktu kejadian.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        transaction_id: UUID,
        amount: Decimal,
        transaction_type: str,
        user_id: UUID,
        occurred_at: datetime,
        correlation_id: str | None = None,
    ):
        event_data = {
            "transaction_id": str(transaction_id),
            "amount": str(amount),
            "transaction_type": transaction_type,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.TRANSACTION_RECORDED,
            aggregate_id=transaction_id,
            aggregate_version=1,
            occurred_at=occurred_at,
            event_data=event_data,
            user_id=str(user_id),
            correlation_id=correlation_id,
        )


class DomainEventPublisher:
    """
    Publisher untuk domain event UMKM Simplified.
    Menyimpan event yang dipublikasikan untuk keperluan testing atau replay.
    """
    _published_events: ClassVar[list[DomainEvent]] = []
    _max_history: ClassVar[int] = 10000

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """
        Publikasikan satu event.

        Args:
            event: DomainEvent yang akan dipublikasikan.
        """
        cls._published_events.append(event)
        if len(cls._published_events) > cls._max_history:
            cls._published_events = cls._published_events[-cls._max_history :]
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        """
        Publikasikan banyak event.

        Args:
            events: List DomainEvent yang akan dipublikasikan.
        """
        for event in events:
            await cls.publish(event)

    @classmethod
    async def add(cls, event: DomainEvent) -> None:
        """Alias untuk publish."""
        await cls.publish(event)

    @classmethod
    async def save(cls, event: DomainEvent) -> None:
        """Alias untuk publish."""
        await cls.publish(event)

    @classmethod
    async def get_events(
        cls, limit: int = 100, event_type: DomainEventType | None = None
    ) -> list[DomainEvent]:
        """
        Dapatkan event yang sudah dipublikasikan dengan filter opsional.

        Args:
            limit: Jumlah maksimum event.
            event_type: Filter berdasarkan tipe event (opsional).

        Returns:
            List[DomainEvent]: Daftar event.
        """
        events = cls._published_events[-limit:] if limit > 0 else cls._published_events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events

    @classmethod
    async def clear(cls) -> None:
        """Hapus semua event yang sudah dipublikasikan."""
        cls._published_events.clear()

    @classmethod
    def get_statistics(cls) -> dict[str, Any]:
        """
        Dapatkan statistik event yang sudah dipublikasikan.

        Returns:
            dict: Statistik dengan total dan breakdown per tipe event.
        """
        by_type: dict[str, int] = {}
        for event in cls._published_events:
            by_type[event.event_type.value] = by_type.get(event.event_type.value, 0) + 1
        return {
            "total_events": len(cls._published_events),
            "by_event_type": by_type,
            "max_history": cls._max_history,
        }

    @classmethod
    def reset(cls) -> None:
        """Reset publisher (untuk testing)."""
        cls._published_events.clear()


TransactionRecorded = TransactionRecordedEvent


__all__ = [
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "TaxCalculatedEvent",
    "TransactionCreatedEvent",
    "TransactionDeletedEvent",
    "TransactionRecorded",
    "TransactionRecordedEvent",
    "TransactionUpdatedEvent",
]
