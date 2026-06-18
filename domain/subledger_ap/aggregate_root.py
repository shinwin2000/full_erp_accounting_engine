#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: 6 - Domain / Subledger AP
Responsibility: Root agregat hutang: faktur + pembayaran + kartu vendor.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.subledger_ap.aging_bucket_vo import AgingBucket
from domain.subledger_ap.credit_note_entity import APCreditNoteEntity
from domain.subledger_ap.debit_note_entity import APDebitNoteEntity
from domain.subledger_ap.domain_events import (
    CreditNoteAppliedEvent,
    CreditNoteReceivedEvent,
    DebitNoteIssuedEvent,
    DomainEvent,
    InvoiceReceivedEvent,
    PaymentSentEvent,
)
from domain.subledger_ap.invoice_entity import APInvoiceEntity, APInvoiceStatus
from domain.subledger_ap.payment_entity import APPaymentEntity, APPaymentStatus
from domain.subledger_ap.vendor_card import VendorCard

logger = logging.getLogger(__name__)


@dataclass
class APSubledger:
    ap_id: UUID
    legal_entity_id: UUID
    invoices: dict[UUID, APInvoiceEntity] = field(default_factory=dict)
    payments: dict[UUID, APPaymentEntity] = field(default_factory=dict)
    vendor_cards: dict[UUID, VendorCard] = field(default_factory=dict)
    credit_notes: dict[UUID, APCreditNoteEntity] = field(default_factory=dict)
    debit_notes: dict[UUID, APDebitNoteEntity] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict] = field(default_factory=list, repr=False)
    _snapshots: list[dict] = field(default_factory=list, repr=False)
    _is_locked: bool = False
    _locked_by: str | None = None
    _locked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"Version must be >= 1: {self.version}")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Timestamps must be timezone-aware")

    # ==================== PROPERTIES ====================

    @property
    def id(self) -> UUID:
        return self.ap_id

    @property
    def is_locked(self) -> bool:
        return self._is_locked

    @property
    def audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    # ==================== EVENT METHODS ====================

    def _add_event(self, event: DomainEvent) -> None:
        self._events.append(event)
        self._record_audit("event_added", {"event_type": event.event_type.value})

    def clear_events(self) -> None:
        self._events.clear()
        self._record_audit("events_cleared", {})

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pop_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def register_event(self, event: DomainEvent) -> None:
        self._add_event(event)

    # ==================== AUDIT TRAIL ====================

    def _record_audit(self, action: str, details: dict) -> None:
        self._audit_trail.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "action": action,
                "details": details,
                "version": self.version,
            }
        )

    def get_audit_trail(self) -> list[dict]:
        return self._audit_trail.copy()

    def clear_audit_trail(self) -> None:
        self._audit_trail.clear()

    # ==================== SNAPSHOT ====================

    def snapshot(self) -> dict:
        snapshot_data = {
            "aggregate_id": str(self.ap_id),
            "aggregate_type": "APSubledger",
            "version": self.version,
            "timestamp": datetime.now(UTC).isoformat(),
            "state": {
                "legal_entity_id": str(self.legal_entity_id),
                "total_invoices": len(self.invoices),
                "total_payments": len(self.payments),
                "total_vendors": len(self.vendor_cards),
                "total_outstanding": str(self.get_total_outstanding()),
            },
            "hash": self._compute_hash(),
        }
        self._snapshots.append(snapshot_data)
        self._record_audit("snapshot_created", {"version": self.version})
        return snapshot_data

    def restore_from_snapshot(self, snapshot: dict) -> None:
        if snapshot.get("aggregate_id") != str(self.ap_id):
            raise ValueError("Snapshot belongs to different aggregate")
        self._record_audit("restored_from_snapshot", {"snapshot_version": snapshot.get("version")})

    def _compute_hash(self) -> str:
        state_str = json.dumps(
            {
                "id": str(self.ap_id),
                "version": self.version,
                "total_invoices": len(self.invoices),
                "total_payments": len(self.payments),
            },
            sort_keys=True,
        )
        return hashlib.sha256(state_str.encode()).hexdigest()

    # ==================== LOCK / UNLOCK ====================

    def lock(self, user_id: str, reason: str | None = None) -> APSubledger:
        if self._is_locked:
            raise ValueError(f"AP Subledger is already locked by {self._locked_by}")
        self._record_audit("locked", {"user_id": user_id, "reason": reason})
        self._is_locked = True
        self._locked_by = user_id
        self._locked_at = datetime.now(UTC)
        return self

    def unlock(self, user_id: str) -> APSubledger:
        if not self._is_locked:
            raise ValueError("AP Subledger is not locked")
        if self._locked_by != user_id:
            raise ValueError(f"Aggregate locked by {self._locked_by}, cannot unlock by {user_id}")
        self._record_audit("unlocked", {"user_id": user_id})
        self._is_locked = False
        self._locked_by = None
        self._locked_at = None
        return self

    # ==================== VALIDATE ====================

    def validate(self) -> list[str]:
        errors = []
        total_outstanding = Decimal(0)
        for card in self.vendor_cards.values():
            if card.outstanding_balance < 0:
                errors.append(f"Vendor {card.vendor_name} has negative balance")
            total_outstanding += card.outstanding_balance
        if abs(total_outstanding - self.get_total_outstanding()) > Decimal("0.01"):
            errors.append(
                f"Total outstanding mismatch: {total_outstanding} vs {self.get_total_outstanding()}"
            )
        return errors

    # ==================== VERSION ====================

    def get_version(self) -> int:
        return self.version

    def increment_version(self) -> None:
        self.version += 1
        self.updated_at = datetime.now(UTC)
        self._record_audit("version_incremented", {"new_version": self.version})

    # ==================== TOUCH ====================

    def touch(self, user_id: str) -> None:
        self.updated_at = datetime.now(UTC)
        self._record_audit("touched", {"user_id": user_id})

    # ==================== CLONE ====================

    def clone(self) -> APSubledger:
        self._record_audit("cloned", {"source_id": str(self.ap_id)})
        return APSubledger(
            ap_id=uuid4(),
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices.copy(),
            payments=self.payments.copy(),
            vendor_cards=self.vendor_cards.copy(),
            credit_notes=self.credit_notes.copy(),
            debit_notes=self.debit_notes.copy(),
            version=1,
        )

    # ==================== INVOICE MANAGEMENT ====================

    def add_invoice(self, invoice: APInvoiceEntity, created_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot add invoice to locked subledger")
        if invoice.invoice_id in self.invoices:
            raise ValueError(f"Invoice {invoice.invoice_id} already exists")

        new_invoices = self.invoices.copy()
        new_invoices[invoice.invoice_id] = invoice

        vendor_card = self.vendor_cards.get(invoice.vendor_id)
        if vendor_card:
            new_card = vendor_card.add_invoice(invoice)
        else:
            new_card = VendorCard.create_from_invoice(invoice)
            new_card.legal_entity_id = self.legal_entity_id

        new_cards = self.vendor_cards.copy()
        new_cards[invoice.vendor_id] = new_card

        self._add_event(
            InvoiceReceivedEvent(
                aggregate_id=self.ap_id,
                aggregate_version=self.version + 1,
                invoice=invoice,
                received_by=created_by,
            )
        )

        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=new_invoices,
            payments=self.payments,
            vendor_cards=new_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def update_invoice(self, invoice: APInvoiceEntity, updated_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot update invoice in locked subledger")
        if invoice.invoice_id not in self.invoices:
            raise ValueError(f"Invoice {invoice.invoice_id} not found")

        new_invoices = self.invoices.copy()
        new_invoices[invoice.invoice_id] = invoice

        self._record_audit(
            "invoice_updated", {"invoice_id": str(invoice.invoice_id), "updated_by": updated_by}
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=new_invoices,
            payments=self.payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def cancel_invoice(self, invoice_id: UUID, reason: str, cancelled_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot cancel invoice in locked subledger")
        invoice = self.invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        cancelled_invoice = invoice.cancel(cancelled_by, reason)
        new_invoices = self.invoices.copy()
        new_invoices[invoice_id] = cancelled_invoice

        # Update vendor card
        vendor_card = self.vendor_cards.get(invoice.vendor_id)
        if vendor_card:
            # Reverse the invoice amount from vendor card
            new_card = vendor_card.apply_credit_note(
                invoice.amount, invoice_id, invoice.invoice_number
            )
            new_cards = self.vendor_cards.copy()
            new_cards[invoice.vendor_id] = new_card
        else:
            new_cards = self.vendor_cards

        self._record_audit(
            "invoice_cancelled",
            {"invoice_id": str(invoice_id), "reason": reason, "cancelled_by": cancelled_by},
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=new_invoices,
            payments=self.payments,
            vendor_cards=new_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_invoice(self, invoice_id: UUID) -> APInvoiceEntity | None:
        return self.invoices.get(invoice_id)

    def get_invoices_by_vendor(self, vendor_id: UUID) -> list[APInvoiceEntity]:
        return [inv for inv in self.invoices.values() if inv.vendor_id == vendor_id]

    def get_overdue_invoices(self, as_of: datetime | None = None) -> list[APInvoiceEntity]:
        as_of = as_of or datetime.now(UTC)
        return [
            inv
            for inv in self.invoices.values()
            if inv.is_overdue(as_of)
            and inv.status not in (APInvoiceStatus.FULLY_PAID, APInvoiceStatus.CANCELLED)
        ]

    # ==================== PAYMENT MANAGEMENT ====================

    def add_payment(self, payment: APPaymentEntity, created_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot add payment to locked subledger")
        new_payments = self.payments.copy()
        new_payments[payment.payment_id] = payment

        vendor_card = self.vendor_cards.get(payment.vendor_id)
        if not vendor_card:
            raise ValueError(f"Vendor {payment.vendor_id} not found")

        new_card = vendor_card.add_payment(payment)
        new_cards = self.vendor_cards.copy()
        new_cards[payment.vendor_id] = new_card

        # Update invoice if allocated
        if payment.allocated_to_invoice_id:
            invoice = self.invoices.get(payment.allocated_to_invoice_id)
            if invoice:
                new_invoice = invoice.record_payment(payment.allocated_amount, payment.payment_id)
                new_invoices = self.invoices.copy()
                new_invoices[invoice.invoice_id] = new_invoice

                self._add_event(
                    PaymentSentEvent(
                        aggregate_id=self.ap_id,
                        aggregate_version=self.version + 1,
                        payment=payment,
                        sent_by=created_by,
                    )
                )

                self.increment_version()
                return APSubledger(
                    ap_id=self.ap_id,
                    legal_entity_id=self.legal_entity_id,
                    invoices=new_invoices,
                    payments=new_payments,
                    vendor_cards=new_cards,
                    credit_notes=self.credit_notes,
                    debit_notes=self.debit_notes,
                    created_at=self.created_at,
                    updated_at=self.updated_at,
                    version=self.version,
                )

        self._add_event(
            PaymentSentEvent(
                aggregate_id=self.ap_id,
                aggregate_version=self.version + 1,
                payment=payment,
                sent_by=created_by,
            )
        )

        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=new_payments,
            vendor_cards=new_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def approve_payment(self, payment_id: UUID, approved_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot approve payment in locked subledger")
        payment = self.payments.get(payment_id)
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        approved_payment = payment.approve(approved_by)
        new_payments = self.payments.copy()
        new_payments[payment_id] = approved_payment

        self._record_audit(
            "payment_approved", {"payment_id": str(payment_id), "approved_by": approved_by}
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=new_payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def process_payment(
        self, payment_id: UUID, processed_by: str, reference: str | None = None
    ) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot process payment in locked subledger")
        payment = self.payments.get(payment_id)
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        processed_payment = payment.process(processed_by, reference)
        new_payments = self.payments.copy()
        new_payments[payment_id] = processed_payment

        self._record_audit(
            "payment_processed", {"payment_id": str(payment_id), "processed_by": processed_by}
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=new_payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def confirm_payment(
        self, payment_id: UUID, confirmed_by: str, bank_reference: str
    ) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot confirm payment in locked subledger")
        payment = self.payments.get(payment_id)
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        confirmed_payment = payment.confirm(confirmed_by, bank_reference)
        new_payments = self.payments.copy()
        new_payments[payment_id] = confirmed_payment

        self._record_audit(
            "payment_confirmed",
            {
                "payment_id": str(payment_id),
                "confirmed_by": confirmed_by,
                "bank_reference": bank_reference,
            },
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=new_payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def cancel_payment(self, payment_id: UUID, reason: str, cancelled_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot cancel payment in locked subledger")
        payment = self.payments.get(payment_id)
        if not payment:
            raise ValueError(f"Payment {payment_id} not found")

        cancelled_payment = payment.cancel(cancelled_by, reason)
        new_payments = self.payments.copy()
        new_payments[payment_id] = cancelled_payment

        self._record_audit(
            "payment_cancelled",
            {"payment_id": str(payment_id), "reason": reason, "cancelled_by": cancelled_by},
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=new_payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def get_payment(self, payment_id: UUID) -> APPaymentEntity | None:
        return self.payments.get(payment_id)

    def get_pending_payments(self) -> list[APPaymentEntity]:
        return [p for p in self.payments.values() if p.status == APPaymentStatus.PENDING]

    # ==================== CREDIT NOTE MANAGEMENT ====================

    def add_credit_note(self, credit_note: APCreditNoteEntity, created_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot add credit note to locked subledger")
        new_credit_notes = self.credit_notes.copy()
        new_credit_notes[credit_note.credit_note_id] = credit_note

        self._add_event(
            CreditNoteReceivedEvent(
                aggregate_id=self.ap_id,
                aggregate_version=self.version + 1,
                credit_note=credit_note,
                received_by=created_by,
            )
        )

        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=self.payments,
            vendor_cards=self.vendor_cards,
            credit_notes=new_credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def apply_credit_note(
        self, credit_note_id: UUID, invoice_id: UUID, applied_by: str
    ) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot apply credit note in locked subledger")
        credit_note = self.credit_notes.get(credit_note_id)
        if not credit_note:
            raise ValueError(f"Credit note {credit_note_id} not found")
        invoice = self.invoices.get(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")

        applied_credit = credit_note.apply(applied_by)
        new_credit_notes = self.credit_notes.copy()
        new_credit_notes[credit_note_id] = applied_credit

        # Update vendor card
        vendor_card = self.vendor_cards.get(credit_note.vendor_id)
        if vendor_card:
            new_card = vendor_card.apply_credit_note(
                credit_note.amount, credit_note_id, credit_note.credit_note_number
            )
            new_cards = self.vendor_cards.copy()
            new_cards[credit_note.vendor_id] = new_card
        else:
            new_cards = self.vendor_cards

        self._add_event(
            CreditNoteAppliedEvent(
                aggregate_id=self.ap_id,
                aggregate_version=self.version + 1,
                credit_note=credit_note,
                invoice_id=invoice_id,
                applied_amount=credit_note.amount,
                applied_by=applied_by,
            )
        )

        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=self.payments,
            vendor_cards=new_cards,
            credit_notes=new_credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    # ==================== DEBIT NOTE MANAGEMENT ====================

    def add_debit_note(self, debit_note: APDebitNoteEntity, created_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot add debit note to locked subledger")
        new_debit_notes = self.debit_notes.copy()
        new_debit_notes[debit_note.debit_note_id] = debit_note

        self._add_event(
            DebitNoteIssuedEvent(
                aggregate_id=self.ap_id,
                aggregate_version=self.version + 1,
                debit_note=debit_note,
                issued_by=created_by,
            )
        )

        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=self.payments,
            vendor_cards=self.vendor_cards,
            credit_notes=self.credit_notes,
            debit_notes=new_debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    def apply_debit_note(self, debit_note_id: UUID, applied_by: str) -> APSubledger:
        if self._is_locked:
            raise ValueError("Cannot apply debit note in locked subledger")
        debit_note = self.debit_notes.get(debit_note_id)
        if not debit_note:
            raise ValueError(f"Debit note {debit_note_id} not found")

        applied_debit = debit_note.apply(applied_by)
        new_debit_notes = self.debit_notes.copy()
        new_debit_notes[debit_note_id] = applied_debit

        # Update vendor card
        vendor_card = self.vendor_cards.get(debit_note.vendor_id)
        if vendor_card:
            new_card = vendor_card.apply_debit_note(
                debit_note.amount, debit_note_id, debit_note.debit_note_number
            )
            new_cards = self.vendor_cards.copy()
            new_cards[debit_note.vendor_id] = new_card
        else:
            new_cards = self.vendor_cards

        self._record_audit(
            "debit_note_applied", {"debit_note_id": str(debit_note_id), "applied_by": applied_by}
        )
        self.increment_version()
        return APSubledger(
            ap_id=self.ap_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=self.payments,
            vendor_cards=new_cards,
            credit_notes=self.credit_notes,
            debit_notes=new_debit_notes,
            created_at=self.created_at,
            updated_at=self.updated_at,
            version=self.version,
        )

    # ==================== VENDOR CARD MANAGEMENT ====================

    def get_vendor_card(self, vendor_id: UUID) -> VendorCard | None:
        return self.vendor_cards.get(vendor_id)

    def get_vendor_outstanding(self, vendor_id: UUID) -> Decimal:
        card = self.vendor_cards.get(vendor_id)
        return card.outstanding_balance if card else Decimal(0)

    def get_total_outstanding(self) -> Decimal:
        total = Decimal(0)
        for card in self.vendor_cards.values():
            total += card.outstanding_balance
        return total

    # ==================== AGING ANALYSIS ====================

    def get_aging_summary(self, as_of: datetime | None = None) -> dict[str, Decimal]:
        if as_of is None:
            as_of = datetime.now(UTC)
        buckets = {
            "current": Decimal(0),
            "1_30": Decimal(0),
            "31_60": Decimal(0),
            "61_90": Decimal(0),
            "over_90": Decimal(0),
        }
        for card in self.vendor_cards.values():
            bucket = card.get_aging_bucket(as_of)
            if bucket.bucket == AgingBucket.CURRENT:
                buckets["current"] += bucket.amount
            elif bucket.bucket == AgingBucket.DAYS_1_30:
                buckets["1_30"] += bucket.amount
            elif bucket.bucket == AgingBucket.DAYS_31_60:
                buckets["31_60"] += bucket.amount
            elif bucket.bucket == AgingBucket.DAYS_61_90:
                buckets["61_90"] += bucket.amount
            elif bucket.bucket == AgingBucket.OVER_90:
                buckets["over_90"] += bucket.amount
        return buckets

    # ==================== DICTIONARY ====================

    def to_dict(self) -> dict[str, Any]:
        return {
            "ap_id": str(self.ap_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_invoices": len(self.invoices),
            "total_payments": len(self.payments),
            "total_vendors": len(self.vendor_cards),
            "total_outstanding": str(self.get_total_outstanding()),
            "aging_summary": self.get_aging_summary(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
            "is_locked": self._is_locked,
        }

    @classmethod
    def create(cls, legal_entity_id: UUID, created_by: str) -> APSubledger:
        return cls(
            ap_id=uuid4(),
            legal_entity_id=legal_entity_id,
            created_by=created_by,
        )


APAggregate = APSubledger
APInvoiceAggregate = APInvoiceEntity


class APSubledgerRepository:
    async def get_by_legal_entity(self, legal_entity_id: UUID) -> APSubledger | None:
        raise NotImplementedError

    async def get_by_id(self, ap_id: UUID, legal_entity_id: UUID) -> APSubledger | None:
        raise NotImplementedError

    async def save(self, ap: APSubledger) -> None:
        raise NotImplementedError

    async def delete(self, ap_id: UUID, legal_entity_id: UUID) -> None:
        raise NotImplementedError


__all__ = [
    "APAggregate",
    "APInvoiceAggregate",
    "APSubledger",
    "APSubledgerRepository",
]
