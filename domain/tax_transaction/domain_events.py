#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Tax Transaction
Responsibility: Domain events for tax transactions: Faktur submitted, approved, etc.

Metode yang ditambahkan:
- Untuk DomainEvent: event_id, occurred_at, aggregate_id, aggregate_type,
  to_dict, from_dict, serialize, deserialize, validate, clone, snapshot, version,
  audit_trail, touch.
- Untuk DomainEventPublisher: publish, publish_many, add, save, get_events, clear,
  get_statistics, reset.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


# === 1. DOMAIN EVENT TYPE ENUM ===
class DomainEventType(Enum):
    FAKTUR_SUBMITTED = "faktur_submitted"
    FAKTUR_APPROVED = "faktur_approved"
    FAKTUR_REJECTED = "faktur_rejected"
    FAKTUR_CANCELLED = "faktur_cancelled"
    SPT_SUBMITTED = "spt_submitted"
    SPT_APPROVED = "spt_approved"
    SPT_REJECTED = "spt_rejected"
    BUPOT_SUBMITTED = "bupot_submitted"
    BUPOT_APPROVED = "bupot_approved"
    METERAI_USED = "meterai_used"
    METERAI_EXPIRED = "meterai_expired"

    def display_name(self) -> str:
        names = {
            DomainEventType.FAKTUR_SUBMITTED: "Faktur Submitted",
            DomainEventType.FAKTUR_APPROVED: "Faktur Approved",
            DomainEventType.FAKTUR_REJECTED: "Faktur Rejected",
            DomainEventType.FAKTUR_CANCELLED: "Faktur Cancelled",
            DomainEventType.SPT_SUBMITTED: "SPT Submitted",
            DomainEventType.SPT_APPROVED: "SPT Approved",
            DomainEventType.SPT_REJECTED: "SPT Rejected",
            DomainEventType.BUPOT_SUBMITTED: "e-Bupot Submitted",
            DomainEventType.BUPOT_APPROVED: "e-Bupot Approved",
            DomainEventType.METERAI_USED: "e-Meterai Used",
            DomainEventType.METERAI_EXPIRED: "e-Meterai Expired",
        }
        return names.get(self, self.value)


# === 2. BASE DOMAIN EVENT CLASS ===
@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di Tax Transaction.

    Attributes:
        event_id: UUID unik event.
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (default "TaxTransaction").
        aggregate_version: Versi agregat saat event terjadi.
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
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

    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    # ==================== ENTITY DASAR METHODS ====================
    def validate(self) -> dict[str, Any]:
        """Validasi event."""
        errors = []
        if not isinstance(self.event_type, DomainEventType):
            errors.append("Invalid event_type")
        if self.aggregate_version < 1:
            errors.append("aggregate_version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

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
            aggregate_type=data.get("aggregate_type", "TaxTransaction"),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        """Create event dari JSON string."""
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        """Deserialize dari bytes."""
        return cls.from_json(data.decode("utf-8"))

    def clone(self) -> DomainEvent:
        """Clone event dengan event_id dan occurred_at baru."""
        return DomainEvent(
            event_id=uuid4(),
            event_type=self.event_type,
            aggregate_id=self.aggregate_id,
            aggregate_type=self.aggregate_type,
            aggregate_version=self.aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=self.event_data.copy(),
            user_id=self.user_id,
            correlation_id=self.correlation_id,
        )

    def snapshot(self) -> dict[str, Any]:
        """Buat snapshot dari event."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
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


# === 3. CONCRETE EVENT CLASSES ===
@dataclass(frozen=True)
class FakturSubmittedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika Faktur Pajak disubmit.

    Attributes:
        aggregate_id: ID agregat faktur.
        aggregate_version: Versi agregat.
        faktur_number: Nomor faktur.
        submitted_by: User ID yang mensubmit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        faktur_number: str,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "faktur_number": faktur_number,
            "submitted_by": submitted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.FAKTUR_SUBMITTED,
            aggregate_id=aggregate_id,
            aggregate_type="FakturPajak",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class FakturApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika Faktur Pajak disetujui.

    Attributes:
        aggregate_id: ID agregat faktur.
        aggregate_version: Versi agregat.
        faktur_number: Nomor faktur.
        approval_code: Kode approval dari DJP.
        approved_by: User ID yang menyetujui.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        faktur_number: str,
        approval_code: str,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "faktur_number": faktur_number,
            "approval_code": approval_code,
            "approved_by": approved_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.FAKTUR_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="FakturPajak",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class FakturRejectedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika Faktur Pajak ditolak.

    Attributes:
        aggregate_id: ID agregat faktur.
        aggregate_version: Versi agregat.
        faktur_number: Nomor faktur.
        reason: Alasan penolakan.
        rejected_by: User ID yang menolak.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        faktur_number: str,
        reason: str,
        rejected_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "faktur_number": faktur_number,
            "reason": reason,
            "rejected_by": rejected_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.FAKTUR_REJECTED,
            aggregate_id=aggregate_id,
            aggregate_type="FakturPajak",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class SPTSubmittedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika SPT disubmit.

    Attributes:
        aggregate_id: ID agregat SPT.
        aggregate_version: Versi agregat.
        spt_number: Nomor SPT.
        submitted_by: User ID yang mensubmit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        spt_number: str,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "spt_number": spt_number,
            "submitted_by": submitted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SPT_SUBMITTED,
            aggregate_id=aggregate_id,
            aggregate_type="SPTSubmission",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class SPTApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika SPT disetujui.

    Attributes:
        aggregate_id: ID agregat SPT.
        aggregate_version: Versi agregat.
        spt_number: Nomor SPT.
        tracking_id: ID tracking dari DJP.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        spt_number: str,
        tracking_id: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "spt_number": spt_number,
            "tracking_id": tracking_id,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.SPT_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="SPTSubmission",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class BupotSubmittedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika e-Bupot disubmit.

    Attributes:
        aggregate_id: ID agregat Bupot.
        aggregate_version: Versi agregat.
        bupot_number: Nomor Bupot.
        submitted_by: User ID yang mensubmit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bupot_number: str,
        submitted_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "bupot_number": bupot_number,
            "submitted_by": submitted_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BUPOT_SUBMITTED,
            aggregate_id=aggregate_id,
            aggregate_type="Bupot",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class BupotApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika e-Bupot disetujui.

    Attributes:
        aggregate_id: ID agregat Bupot.
        aggregate_version: Versi agregat.
        bupot_number: Nomor Bupot.
        coretax_id: ID dari Coretax.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        bupot_number: str,
        coretax_id: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "bupot_number": bupot_number,
            "coretax_id": coretax_id,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.BUPOT_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="Bupot",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class MeteraiUsedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika e-Meterai digunakan.

    Attributes:
        aggregate_id: ID agregat Meterai.
        aggregate_version: Versi agregat.
        meterai_code: Kode Meterai.
        document_id: ID dokumen.
        used_by: User ID yang menggunakan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        meterai_code: str,
        document_id: str,
        used_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "meterai_code": meterai_code,
            "document_id": document_id,
            "used_by": used_by,
        }
        super().__init__(
            event_id=uuid4(),
            event_type=DomainEventType.METERAI_USED,
            aggregate_id=aggregate_id,
            aggregate_type="EMeterai",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 4. DOMAIN EVENT PUBLISHER ===
class DomainEventPublisher:
    """
    Publisher untuk domain event Tax Transaction.
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
        logger.info(
            f"Published tax event: {event.event_type.value} for aggregate {event.aggregate_id}"
        )

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

    @classmethod
    def set_max_history(cls, max_history: int) -> None:
        """
        Set maksimum jumlah event yang disimpan.

        Args:
            max_history: Jumlah maksimum event.
        """
        cls._max_history = max_history
        if len(cls._published_events) > cls._max_history:
            cls._published_events = cls._published_events[-cls._max_history :]


# === 5. EXPORTS ===
__all__ = [
    "BupotApprovedEvent",
    "BupotSubmittedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "FakturApprovedEvent",
    "FakturRejectedEvent",
    "FakturSubmittedEvent",
    "MeteraiUsedEvent",
    "SPTApprovedEvent",
    "SPTSubmittedEvent",
]
