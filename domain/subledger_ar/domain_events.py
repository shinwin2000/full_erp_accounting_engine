#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: Domain / Subledger AR
Responsibility: Event: InvoiceIssued, PaymentReceived, CreditNoteApplied, dll.

Metode yang ditambahkan:
- Untuk DomainEvent: event_id, occurred_at, aggregate_id, aggregate_type,
  to_dict, from_dict, serialize, deserialize, validate, clone, snapshot, version,
  audit_trail, touch.
- Untuk DomainEventPublisher: publish, publish_many (dengan fallback storage),
  add, save, get_events, clear, get_statistics, reset.
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

from domain.subledger_ar.credit_note_entity import CreditNoteEntity
from domain.subledger_ar.debit_note_entity import DebitNoteEntity
from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus
from domain.subledger_ar.payment_entity import PaymentEntity

logger = logging.getLogger(__name__)


# === 1. DOMAIN EVENT TYPE ENUM ===
class DomainEventType(Enum):
    INVOICE_ISSUED = "invoice_issued"
    INVOICE_APPROVED = "invoice_approved"
    INVOICE_PAID = "invoice_paid"
    INVOICE_PARTIALLY_PAID = "invoice_partially_paid"
    INVOICE_OVERDUE = "invoice_overdue"
    INVOICE_WRITTEN_OFF = "invoice_written_off"
    INVOICE_CANCELLED = "invoice_cancelled"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_ALLOCATED = "payment_allocated"
    PAYMENT_REFUNDED = "payment_refunded"
    CREDIT_NOTE_ISSUED = "credit_note_issued"
    CREDIT_NOTE_APPLIED = "credit_note_applied"
    DEBIT_NOTE_ISSUED = "debit_note_issued"
    DEBIT_NOTE_APPLIED = "debit_note_applied"
    CUSTOMER_CREDIT_LIMIT_CHANGED = "customer_credit_limit_changed"
    CUSTOMER_RISK_RATING_CHANGED = "customer_risk_rating_changed"
    BAD_DEBT_PROVISION_RECORDED = "bad_debt_provision_recorded"

    def display_name(self) -> str:
        names = {
            DomainEventType.INVOICE_ISSUED: "Invoice Issued",
            DomainEventType.INVOICE_APPROVED: "Invoice Approved",
            DomainEventType.INVOICE_PAID: "Invoice Paid",
            DomainEventType.INVOICE_PARTIALLY_PAID: "Invoice Partially Paid",
            DomainEventType.INVOICE_OVERDUE: "Invoice Overdue",
            DomainEventType.INVOICE_WRITTEN_OFF: "Invoice Written Off",
            DomainEventType.INVOICE_CANCELLED: "Invoice Cancelled",
            DomainEventType.PAYMENT_RECEIVED: "Payment Received",
            DomainEventType.PAYMENT_ALLOCATED: "Payment Allocated",
            DomainEventType.PAYMENT_REFUNDED: "Payment Refunded",
            DomainEventType.CREDIT_NOTE_ISSUED: "Credit Note Issued",
            DomainEventType.CREDIT_NOTE_APPLIED: "Credit Note Applied",
            DomainEventType.DEBIT_NOTE_ISSUED: "Debit Note Issued",
            DomainEventType.DEBIT_NOTE_APPLIED: "Debit Note Applied",
            DomainEventType.CUSTOMER_CREDIT_LIMIT_CHANGED: "Customer Credit Limit Changed",
            DomainEventType.CUSTOMER_RISK_RATING_CHANGED: "Customer Risk Rating Changed",
            DomainEventType.BAD_DEBT_PROVISION_RECORDED: "Bad Debt Provision Recorded",
        }
        return names.get(self, self.value)


# === 2. BASE DOMAIN EVENT CLASS (dengan entity dasar) ===
@dataclass(frozen=True)
class DomainEvent:
    """
    Base class untuk semua domain event di Subledger AR.

    Attributes:
        event_type: Jenis event (DomainEventType).
        aggregate_id: UUID agregat yang terkait.
        aggregate_type: Tipe agregat (default "ARSubledger").
        aggregate_version: Versi agregat saat event terjadi.
        event_id: UUID unik event (default auto-generated).
        occurred_at: Waktu kejadian (UTC).
        event_data: Data payload event.
        user_id: ID pengguna yang memicu event (opsional).
        correlation_id: ID korelasi untuk tracing (opsional).
    """
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_type: str
    aggregate_version: int
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None

    # Fields untuk audit dan snapshot
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self) -> None:
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    # ==================== METODA ENTITY DASAR ====================
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
            "aggregate_type": self.aggregate_type,
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
            aggregate_type=data.get("aggregate_type", "ARSubledger"),
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
            aggregate_type=self.aggregate_type,
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
class InvoiceIssuedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR diterbitkan.

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        issued_by: User ID penerbit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "customer_id": str(invoice.customer_id),
            "customer_name": invoice.customer_name,
            "amount": str(invoice.amount),
            "currency": invoice.currency,
            "due_date": invoice.due_date.isoformat(),
            "issued_by": issued_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class InvoiceApprovedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR disetujui.

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        approved_by: User ID yang menyetujui.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "approved_by": approved_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class InvoicePaidEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR dilunasi.

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        payment_id: ID pembayaran.
        payment_amount: Jumlah pembayaran.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        payment_id: UUID,
        payment_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "payment_id": str(payment_id),
            "payment_amount": str(payment_amount),
            "final_status": InvoiceStatus.FULLY_PAID.value,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class InvoicePartiallyPaidEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR dibayar sebagian.

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        payment_id: ID pembayaran.
        payment_amount: Jumlah pembayaran.
        remaining_amount: Sisa tagihan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        payment_id: UUID,
        payment_amount: Decimal,
        remaining_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "payment_id": str(payment_id),
            "payment_amount": str(payment_amount),
            "remaining_amount": str(remaining_amount),
            "status": InvoiceStatus.PARTIALLY_PAID.value,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_PARTIALLY_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class InvoiceCancelledEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR dibatalkan.

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        reason: Alasan pembatalan.
        cancelled_by: User ID pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class InvoiceWrittenOffEvent(DomainEvent):
    """
    Event yang diterbitkan ketika invoice AR dihapusbukukan (write-off).

    Attributes:
        aggregate_id: ID agregat invoice.
        aggregate_version: Versi agregat.
        invoice: Entity Invoice.
        reason: Alasan write-off.
        amount: Jumlah yang di-write-off.
        written_off_by: User ID yang melakukan write-off.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: InvoiceEntity,
        reason: str,
        amount: Decimal,
        written_off_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "reason": reason,
            "amount": str(amount),
            "written_off_by": written_off_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_WRITTEN_OFF,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class PaymentReceivedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika pembayaran AR diterima.

    Attributes:
        aggregate_id: ID agregat payment.
        aggregate_version: Versi agregat.
        payment: Entity Payment.
        received_by: User ID penerima.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: PaymentEntity,
        received_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "customer_id": str(payment.customer_id),
            "customer_name": payment.customer_name,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "payment_method": payment.payment_method.value,
            "received_by": received_by,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class PaymentAllocatedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika pembayaran AR dialokasikan ke invoice.

    Attributes:
        aggregate_id: ID agregat payment.
        aggregate_version: Versi agregat.
        payment: Entity Payment.
        invoice_id: ID invoice.
        allocated_amount: Jumlah yang dialokasikan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: PaymentEntity,
        invoice_id: UUID,
        allocated_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "invoice_id": str(invoice_id),
            "allocated_amount": str(allocated_amount),
            "remaining_unallocated": str(payment.amount - allocated_amount),
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_ALLOCATED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class CreditNoteIssuedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika credit note AR diterbitkan.

    Attributes:
        aggregate_id: ID agregat credit note.
        aggregate_version: Versi agregat.
        credit_note: Entity CreditNote.
        issued_by: User ID penerbit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note: CreditNoteEntity,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note.credit_note_id),
            "credit_note_number": credit_note.credit_note_number,
            "invoice_id": str(credit_note.invoice_id),
            "customer_id": str(credit_note.customer_id),
            "amount": str(credit_note.amount),
            "reason": credit_note.reason.value,
            "issued_by": issued_by,
        }
        super().__init__(
            event_type=DomainEventType.CREDIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class CreditNoteAppliedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika credit note AR diterapkan ke invoice.

    Attributes:
        aggregate_id: ID agregat credit note.
        aggregate_version: Versi agregat.
        credit_note: Entity CreditNote.
        invoice_id: ID invoice.
        applied_amount: Jumlah yang diterapkan.
        applied_by: User ID penerap.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note: CreditNoteEntity,
        invoice_id: UUID,
        applied_amount: Decimal,
        applied_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note.credit_note_id),
            "credit_note_number": credit_note.credit_note_number,
            "invoice_id": str(invoice_id),
            "applied_amount": str(applied_amount),
            "applied_by": applied_by,
        }
        super().__init__(
            event_type=DomainEventType.CREDIT_NOTE_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class DebitNoteIssuedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika debit note AR diterbitkan.

    Attributes:
        aggregate_id: ID agregat debit note.
        aggregate_version: Versi agregat.
        debit_note: Entity DebitNote.
        issued_by: User ID penerbit.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note: DebitNoteEntity,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note.debit_note_id),
            "debit_note_number": debit_note.debit_note_number,
            "invoice_id": str(debit_note.invoice_id),
            "customer_id": str(debit_note.customer_id),
            "amount": str(debit_note.amount),
            "reason": debit_note.reason.value,
            "issued_by": issued_by,
        }
        super().__init__(
            event_type=DomainEventType.DEBIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class PaymentVoidedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika pembayaran AR dibatalkan/dihapus.

    Attributes:
        aggregate_id: ID agregat payment.
        aggregate_version: Versi agregat.
        payment_number: Nomor pembayaran.
        reason: Alasan pembatalan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment_number: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "payment_number": payment_number,
            "reason": reason,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_REFUNDED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True)
class BadDebtProvisionRecordedEvent(DomainEvent):
    """
    Event yang diterbitkan ketika pencadangan piutang tak tertagih (bad debt provision) dicatat.

    Attributes:
        aggregate_id: ID agregat pencadangan.
        aggregate_version: Versi agregat.
        legal_entity_id: ID entitas legal.
        as_of_date: Tanggal pencadangan.
        total_receivables: Total piutang.
        provision_amount: Jumlah pencadangan.
        user_id: (opsional) ID pengguna yang memicu event.
        correlation_id: (opsional) ID korelasi.
    """
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        as_of_date: date,
        total_receivables: Decimal,
        provision_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "as_of_date": as_of_date.isoformat(),
            "total_receivables": str(total_receivables),
            "provision_amount": str(provision_amount),
        }
        super().__init__(
            event_type=DomainEventType.BAD_DEBT_PROVISION_RECORDED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 4. DOMAIN EVENT PUBLISHER (dengan repository interface) ===
class DomainEventPublisher:
    """
    Publisher untuk domain event Subledger AR.
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

    # Repository interface methods
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


# === ALIAS UNTUK KOMPATIBILITAS ===
ARInvoiceCreated = InvoiceIssuedEvent
ARInvoiceApproved = InvoiceApprovedEvent
ARInvoicePaid = InvoicePaidEvent
ARInvoiceCancelled = InvoiceCancelledEvent
ARInvoiceWrittenOff = InvoiceWrittenOffEvent
ARPaymentReceived = PaymentReceivedEvent
ARPaymentApplied = PaymentAllocatedEvent
ARPaymentVoided = PaymentVoidedEvent
ARCreditNoteIssued = CreditNoteIssuedEvent
ARDebitNoteIssued = DebitNoteIssuedEvent


# === 5. EXPORTS ===
__all__ = [
    "ARCreditNoteIssued",
    "ARDebitNoteIssued",
    "ARInvoiceApproved",
    "ARInvoiceCancelled",
    "ARInvoiceCreated",
    "ARInvoicePaid",
    "ARInvoiceWrittenOff",
    "ARPaymentApplied",
    "ARPaymentReceived",
    "ARPaymentVoided",
    "BadDebtProvisionRecordedEvent",
    "CreditNoteAppliedEvent",
    "CreditNoteIssuedEvent",
    "DebitNoteIssuedEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoiceIssuedEvent",
    "InvoicePaidEvent",
    "InvoicePartiallyPaidEvent",
    "InvoiceWrittenOffEvent",
    "PaymentAllocatedEvent",
    "PaymentReceivedEvent",
    "PaymentVoidedEvent",
]
