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
from dataclasses import dataclass
from datetime import UTC, datetime
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
    INVOICE_APPROVED = "invoice_approved"          # added
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
        }
        return names.get(self, self.value)


# === 2. BASE DOMAIN EVENT CLASS (dengan entity dasar) ===
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

    # Fields untuk audit dan snapshot
    _audit_trail: ClassVar[list[dict[str, Any]]] = []
    _snapshots: ClassVar[list[dict[str, Any]]] = []

    def __post_init__(self):
        if self.aggregate_version < 1:
            raise ValueError("aggregate_version must be >= 1")
        if self.occurred_at.tzinfo is None:
            object.__setattr__(self, "occurred_at", self.occurred_at.replace(tzinfo=UTC))

    # ==================== METODA ENTITY DASAR ====================
    def validate(self) -> dict[str, Any]:
        errors = []
        if not isinstance(self.event_type, DomainEventType):
            errors.append("Invalid event_type")
        if self.aggregate_version < 1:
            errors.append("aggregate_version must be >= 1")
        return {"is_valid": len(errors) == 0, "errors": errors}

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
            aggregate_type=data.get("aggregate_type", "ARSubledger"),
            aggregate_version=data["aggregate_version"],
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            event_data=data.get("event_data", {}),
            user_id=data.get("user_id"),
            correlation_id=data.get("correlation_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> DomainEvent:
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))

    def clone(self) -> DomainEvent:
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
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_version": self.aggregate_version,
            "occurred_at": self.occurred_at.isoformat(),
        }

    def version(self) -> int:
        return 1  # Events are immutable

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> DomainEvent:
        return self.clone()


# === 3. CONCRETE EVENT CLASSES ===
@dataclass
class InvoiceIssuedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceApprovedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class InvoicePaidEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class InvoicePartiallyPaidEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_PARTIALLY_PAID,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceCancelledEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class InvoiceWrittenOffEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.INVOICE_WRITTEN_OFF,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PaymentReceivedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.PAYMENT_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class PaymentAllocatedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.PAYMENT_ALLOCATED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class CreditNoteIssuedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.CREDIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class CreditNoteAppliedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.CREDIT_NOTE_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


@dataclass
class DebitNoteIssuedEvent(DomainEvent):
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
            event_id=uuid4(),
            event_type=DomainEventType.DEBIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_type="ARSubledger",
            aggregate_version=aggregate_version,
            occurred_at=datetime.now(UTC),
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
        )


# === 4. DOMAIN EVENT PUBLISHER (dengan repository interface) ===
class DomainEventPublisher:
    _published_events: ClassVar[list[DomainEvent]] = []
    _max_history: ClassVar[int] = 10000

    @classmethod
    async def publish(cls, event: DomainEvent) -> None:
        """Publish a single domain event."""
        cls._published_events.append(event)
        if len(cls._published_events) > cls._max_history:
            cls._published_events = cls._published_events[-cls._max_history :]
        logger.info(f"Published event: {event.event_type.value} for aggregate {event.aggregate_id}")

    @classmethod
    async def publish_many(cls, events: list[DomainEvent]) -> None:
        """Publish multiple domain events."""
        for event in events:
            await cls.publish(event)

    # Repository interface methods
    @classmethod
    async def add(cls, event: DomainEvent) -> None:
        """Alias for publish."""
        await cls.publish(event)

    @classmethod
    async def save(cls, event: DomainEvent) -> None:
        """Alias for publish."""
        await cls.publish(event)

    @classmethod
    async def get_events(
        cls, limit: int = 100, event_type: DomainEventType | None = None
    ) -> list[DomainEvent]:
        """Get published events with optional filter."""
        events = cls._published_events[-limit:] if limit > 0 else cls._published_events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return events

    @classmethod
    async def clear(cls) -> None:
        """Clear all published events."""
        cls._published_events.clear()

    @classmethod
    def get_statistics(cls) -> dict[str, Any]:
        """Get statistics about published events."""
        by_type = {}
        for event in cls._published_events:
            by_type[event.event_type.value] = by_type.get(event.event_type.value, 0) + 1
        return {
            "total_events": len(cls._published_events),
            "by_event_type": by_type,
            "max_history": cls._max_history,
        }

    @classmethod
    def reset(cls) -> None:
        """Reset publisher (for testing)."""
        cls._published_events.clear()

    @classmethod
    def set_max_history(cls, max_history: int) -> None:
        """Set maximum number of events to keep."""
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
ARPaymentVoided = PaymentAllocatedEvent  # placeholder
ARCreditNoteIssued = CreditNoteIssuedEvent
ARDebitNoteIssued = DebitNoteIssuedEvent
BadDebtProvisionRecorded = None  # will be added separately


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
]
