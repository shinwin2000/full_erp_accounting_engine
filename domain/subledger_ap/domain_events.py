#!/usr/bin/env python3
"""
Module: domain_events.py
Layer: 6 - Domain / Subledger AP
Responsibility: Event: InvoiceReceived, PaymentSent, CreditNoteApplied.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from domain.subledger_ap.credit_note_entity import APCreditNoteEntity
from domain.subledger_ap.debit_note_entity import APDebitNoteEntity
from domain.subledger_ap.invoice_entity import APInvoiceEntity, APInvoiceStatus
from domain.subledger_ap.payment_entity import APPaymentEntity


class DomainEventType(Enum):
    INVOICE_RECEIVED = "invoice_received"
    INVOICE_VERIFIED = "invoice_verified"
    INVOICE_PAID = "invoice_paid"
    INVOICE_PARTIALLY_PAID = "invoice_partially_paid"
    INVOICE_OVERDUE = "invoice_overdue"
    INVOICE_CANCELLED = "invoice_cancelled"
    INVOICE_DISPUTED = "invoice_disputed"
    PAYMENT_SENT = "payment_sent"
    PAYMENT_APPROVED = "payment_approved"
    PAYMENT_PROCESSED = "payment_processed"
    PAYMENT_CONFIRMED = "payment_confirmed"
    PAYMENT_CANCELLED = "payment_cancelled"
    CREDIT_NOTE_RECEIVED = "credit_note_received"
    CREDIT_NOTE_APPLIED = "credit_note_applied"
    DEBIT_NOTE_ISSUED = "debit_note_issued"
    DEBIT_NOTE_APPLIED = "debit_note_applied"
    THREE_WAY_MATCH_RESULT = "three_way_match_result"
    INVOICE_CREATED = "invoice_created"
    INVOICE_APPROVED = "invoice_approved"
    PAYMENT_MADE = "payment_made"
    PAYMENT_APPLIED = "payment_applied"
    PAYMENT_VOIDED = "payment_voided"
    CREDIT_NOTE_ISSUED = "credit_note_issued"
    DEBIT_NOTE_ISSUED_SERVICE = "debit_note_issued_service"
    PAYMENT_RUN_GENERATED = "payment_run_generated"
    PAYMENT_RUN_EXECUTED = "payment_run_executed"

    @classmethod
    def from_string(cls, value: str) -> DomainEventType:
        for member in cls:
            if member.value == value.lower():
                return member
        return cls.INVOICE_RECEIVED


@dataclass
class DomainEvent:
    # Non-default fields first (required)
    event_type: DomainEventType
    aggregate_id: UUID
    aggregate_version: int
    # Default fields (optional) after
    event_id: UUID = field(default_factory=uuid4)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    event_data: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

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
            event_type=DomainEventType.from_string(data["event_type"]),
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

    def serialize(self) -> bytes:
        return self.to_json().encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> DomainEvent:
        return cls.from_json(data.decode("utf-8"))


# ==================== INVOICE EVENTS ====================


@dataclass
class InvoiceReceivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: APInvoiceEntity,
        received_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "vendor_id": str(invoice.vendor_id),
            "vendor_name": invoice.vendor_name,
            "amount": str(invoice.amount),
            "currency": invoice.currency,
            "due_date": invoice.due_date.isoformat(),
            "received_by": received_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoiceVerifiedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: APInvoiceEntity,
        verified_by: str,
        match_result: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "verified_by": verified_by,
            "match_result": match_result,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_VERIFIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoicePaidEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice: APInvoiceEntity,
        payment_id: UUID,
        payment_amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice.invoice_id),
            "invoice_number": invoice.invoice_number,
            "payment_id": str(payment_id),
            "payment_amount": str(payment_amount),
            "final_status": APInvoiceStatus.FULLY_PAID.value,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_PAID,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoiceCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoiceDisputedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        invoice_number: str,
        reason: str,
        disputed_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "invoice_number": invoice_number,
            "reason": reason,
            "disputed_by": disputed_by,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_DISPUTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoiceCreatedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        invoice_number: str,
        vendor_id: UUID,
        amount: Decimal,
        due_date: datetime,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "invoice_number": invoice_number,
            "vendor_id": str(vendor_id),
            "amount": str(amount),
            "due_date": due_date.isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_CREATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class InvoiceApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_number: str,
        approver_id: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_number": invoice_number,
            "approver_id": approver_id,
        }
        super().__init__(
            event_type=DomainEventType.INVOICE_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== PAYMENT EVENTS ====================


@dataclass
class PaymentSentEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: APPaymentEntity,
        sent_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "vendor_id": str(payment.vendor_id),
            "vendor_name": payment.vendor_name,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "payment_method": payment.payment_method.value,
            "sent_by": sent_by,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_SENT,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentApprovedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: APPaymentEntity,
        approved_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "approved_by": approved_by,
            "approved_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_APPROVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentProcessedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: APPaymentEntity,
        processed_by: str,
        reference_number: str | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "processed_by": processed_by,
            "reference_number": reference_number,
            "processed_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_PROCESSED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentConfirmedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment: APPaymentEntity,
        confirmed_by: str,
        bank_reference: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment.payment_id),
            "payment_number": payment.payment_number,
            "confirmed_by": confirmed_by,
            "bank_reference": bank_reference,
            "confirmed_at": datetime.now(UTC).isoformat(),
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_CONFIRMED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentCancelledEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment_id: UUID,
        payment_number: str,
        reason: str,
        cancelled_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment_id),
            "payment_number": payment_number,
            "reason": reason,
            "cancelled_by": cancelled_by,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_CANCELLED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentMadeEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        amount: Decimal,
        payment_number: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "amount": str(amount),
            "payment_number": payment_number,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_MADE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentAppliedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment_id: UUID,
        invoice_id: UUID,
        amount: Decimal,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_id": str(payment_id),
            "invoice_id": str(invoice_id),
            "amount": str(amount),
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentVoidedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        payment_number: str,
        reason: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "payment_number": payment_number,
            "reason": reason,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_VOIDED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== CREDIT NOTE EVENTS ====================


@dataclass
class CreditNoteReceivedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note: APCreditNoteEntity,
        received_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "credit_note_id": str(credit_note.credit_note_id),
            "credit_note_number": credit_note.credit_note_number,
            "invoice_id": str(credit_note.invoice_id),
            "vendor_id": str(credit_note.vendor_id),
            "amount": str(credit_note.amount),
            "reason": credit_note.reason.value,
            "received_by": received_by,
        }
        super().__init__(
            event_type=DomainEventType.CREDIT_NOTE_RECEIVED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CreditNoteAppliedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        credit_note: APCreditNoteEntity,
        invoice_id: UUID,
        applied_amount: Decimal,
        applied_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
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
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class CreditNoteIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        credit_note_number: str,
        vendor_id: UUID,
        amount: Decimal,
        original_invoice_id: UUID | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "credit_note_number": credit_note_number,
            "vendor_id": str(vendor_id),
            "amount": str(amount),
            "original_invoice_id": str(original_invoice_id) if original_invoice_id else None,
        }
        super().__init__(
            event_type=DomainEventType.CREDIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== DEBIT NOTE EVENTS ====================


@dataclass
class DebitNoteIssuedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note: APDebitNoteEntity,
        issued_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note.debit_note_id),
            "debit_note_number": debit_note.debit_note_number,
            "invoice_id": str(debit_note.invoice_id),
            "vendor_id": str(debit_note.vendor_id),
            "amount": str(debit_note.amount),
            "reason": debit_note.reason.value,
            "issued_by": issued_by,
        }
        super().__init__(
            event_type=DomainEventType.DEBIT_NOTE_ISSUED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class DebitNoteAppliedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        debit_note: APDebitNoteEntity,
        applied_by: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "debit_note_id": str(debit_note.debit_note_id),
            "debit_note_number": debit_note.debit_note_number,
            "applied_by": applied_by,
        }
        super().__init__(
            event_type=DomainEventType.DEBIT_NOTE_APPLIED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class DebitNoteIssuedServiceEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        legal_entity_id: UUID,
        debit_note_number: str,
        vendor_id: UUID,
        amount: Decimal,
        original_invoice_id: UUID | None = None,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "legal_entity_id": str(legal_entity_id),
            "debit_note_number": debit_note_number,
            "vendor_id": str(vendor_id),
            "amount": str(amount),
            "original_invoice_id": str(original_invoice_id) if original_invoice_id else None,
        }
        super().__init__(
            event_type=DomainEventType.DEBIT_NOTE_ISSUED_SERVICE,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== THREE WAY MATCH EVENTS ====================


@dataclass
class ThreeWayMatchResultEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        invoice_id: UUID,
        match_status: str,
        differences: dict[str, Decimal],
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "invoice_id": str(invoice_id),
            "match_status": match_status,
            "differences": {k: str(v) for k, v in differences.items()},
        }
        super().__init__(
            event_type=DomainEventType.THREE_WAY_MATCH_RESULT,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== PAYMENT RUN EVENTS ====================


@dataclass
class PaymentRunGeneratedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        run_number: str,
        total_amount: Decimal,
        payment_count: int,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "run_number": run_number,
            "total_amount": str(total_amount),
            "payment_count": payment_count,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_RUN_GENERATED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


@dataclass
class PaymentRunExecutedEvent(DomainEvent):
    def __init__(
        self,
        aggregate_id: UUID,
        aggregate_version: int,
        run_number: str,
        user_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
    ):
        event_data = {
            "run_number": run_number,
        }
        super().__init__(
            event_type=DomainEventType.PAYMENT_RUN_EXECUTED,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            event_data=event_data,
            user_id=user_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )


# ==================== ALIASES ====================

APInvoiceCreated = InvoiceCreatedEvent
APInvoiceApproved = InvoiceApprovedEvent
APInvoiceCancelled = InvoiceCancelledEvent
APPaymentMade = PaymentMadeEvent
APPaymentApplied = PaymentAppliedEvent
APPaymentVoided = PaymentVoidedEvent
APCreditNoteIssued = CreditNoteIssuedEvent
APDebitNoteIssued = DebitNoteIssuedServiceEvent
APPaymentRunGenerated = PaymentRunGeneratedEvent
APPaymentRunExecuted = PaymentRunExecutedEvent


# ==================== PUBLISHER ====================


class DomainEventPublisher:
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError

    async def publish_many(self, events: list[DomainEvent]) -> None:
        for event in events:
            await self.publish(event)

    async def publish_with_retry(self, event: DomainEvent, max_retries: int = 3) -> None:
        import asyncio

        last_error = None
        for attempt in range(max_retries):
            try:
                await self.publish(event)
                return
            except Exception as e:
                last_error = e
                await asyncio.sleep(0.1 * (2**attempt))
        raise last_error


__all__ = [
    "APCreditNoteIssued",
    "APDebitNoteIssued",
    "APInvoiceApproved",
    "APInvoiceCancelled",
    "APInvoiceCreated",
    "APPaymentApplied",
    "APPaymentMade",
    "APPaymentRunExecuted",
    "APPaymentRunGenerated",
    "APPaymentVoided",
    "CreditNoteAppliedEvent",
    "CreditNoteIssuedEvent",
    "CreditNoteReceivedEvent",
    "DebitNoteAppliedEvent",
    "DebitNoteIssuedEvent",
    "DebitNoteIssuedServiceEvent",
    "DomainEvent",
    "DomainEventPublisher",
    "DomainEventType",
    "InvoiceApprovedEvent",
    "InvoiceCancelledEvent",
    "InvoiceCreatedEvent",
    "InvoiceDisputedEvent",
    "InvoicePaidEvent",
    "InvoiceReceivedEvent",
    "InvoiceVerifiedEvent",
    "PaymentAppliedEvent",
    "PaymentApprovedEvent",
    "PaymentCancelledEvent",
    "PaymentConfirmedEvent",
    "PaymentMadeEvent",
    "PaymentProcessedEvent",
    "PaymentRunExecutedEvent",
    "PaymentRunGeneratedEvent",
    "PaymentSentEvent",
    "PaymentVoidedEvent",
    "ThreeWayMatchResultEvent",
]
