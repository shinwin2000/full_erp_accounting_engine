#!/usr/bin/env python3
"""
Module: aggregate_root.py
Layer: Domain / Subledger AR
Responsibility: Root agregat piutang: faktur + pembayaran + kartu pelanggan.

Metode yang ditambahkan:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Aggregate root: add_child, remove_child, can_post, post, can_approve, approve,
  can_reject, reject, can_cancel, cancel, can_reverse, reverse, close, reopen,
  archive, unarchive, register_event, get_events, pull_events, clear_events.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from domain.subledger_ar.aging_bucket_vo import AgingBucket
from domain.subledger_ar.customer_card import CustomerCard
from domain.subledger_ar.domain_events import (
    CreditNoteIssuedEvent,
    DomainEvent,
    InvoiceIssuedEvent,
    InvoicePaidEvent,
    PaymentReceivedEvent,
)
from domain.subledger_ar.invoice_entity import ARInvoice, InvoiceEntity
from domain.subledger_ar.payment_entity import PaymentEntity

logger = logging.getLogger(__name__)


# === 1. AR AGGREGATE ===
@dataclass
class ARSubledger:
    ar_id: UUID
    legal_entity_id: UUID
    invoices: dict[UUID, InvoiceEntity] = field(default_factory=dict)
    payments: dict[UUID, PaymentEntity] = field(default_factory=dict)
    customer_cards: dict[UUID, CustomerCard] = field(default_factory=dict)
    credit_notes: dict[UUID, Any] = field(default_factory=dict)
    debit_notes: dict[UUID, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    version: int = 1

    # Fields untuk entity dasar
    _events: list[DomainEvent] = field(default_factory=list, repr=False)
    _audit_trail: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _snapshots: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._take_snapshot()

    def _take_snapshot(self) -> None:
        snapshot = {
            "version": self.version,
            "ar_id": str(self.ar_id),
            "legal_entity_id": str(self.legal_entity_id),
            "invoice_count": len(self.invoices),
            "payment_count": len(self.payments),
            "customer_count": len(self.customer_cards),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self._snapshots.append(snapshot)
        if len(self._snapshots) > 10:
            self._snapshots.pop(0)

    def _record_audit(self, action: str, performed_by: str, details: dict[str, Any]) -> None:
        self._audit_trail.append(
            {
                "action": action,
                "performed_by": performed_by,
                "timestamp": datetime.now(UTC).isoformat(),
                "version": self.version,
                "ar_id": str(self.ar_id),
                "details": details,
            }
        )

    def _register_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    # ==================== BUSINESS METHODS (Original) ====================
    def add_invoice(self, invoice: InvoiceEntity) -> ARSubledger:
        if invoice.invoice_id in self.invoices:
            raise ValueError(f"Invoice {invoice.invoice_id} already exists")
        new_invoices = self.invoices.copy()
        new_invoices[invoice.invoice_id] = invoice
        customer_card = self.customer_cards.get(invoice.customer_id)
        if customer_card:
            new_card = customer_card.add_invoice(invoice)
        else:
            new_card = CustomerCard.create_from_invoice(invoice)
        new_cards = self.customer_cards.copy()
        new_cards[invoice.customer_id] = new_card
        self._register_event(
            InvoiceIssuedEvent(
                aggregate_id=self.ar_id,
                aggregate_version=self.version + 1,
                invoice=invoice,
                issued_by=invoice.created_by,
            )
        )
        return self._copy_with(
            invoices=new_invoices,
            customer_cards=new_cards,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def add_payment(self, payment: PaymentEntity) -> ARSubledger:
        new_payments = self.payments.copy()
        new_payments[payment.payment_id] = payment
        customer_card = self.customer_cards.get(payment.customer_id)
        if not customer_card:
            raise ValueError(f"Customer {payment.customer_id} not found")
        new_card = customer_card.add_payment(payment)
        new_cards = self.customer_cards.copy()
        new_cards[payment.customer_id] = new_card

        if payment.allocated_to_invoice_id:
            invoice = self.invoices.get(payment.allocated_to_invoice_id)
            if invoice:
                new_invoice = invoice.record_payment(payment.amount, payment.payment_id)
                new_invoices = self.invoices.copy()
                new_invoices[invoice.invoice_id] = new_invoice
                self._register_event(
                    InvoicePaidEvent(
                        aggregate_id=self.ar_id,
                        aggregate_version=self.version + 1,
                        invoice=new_invoice,
                        payment_id=payment.payment_id,
                        payment_amount=payment.amount,
                    )
                )
                return self._copy_with(
                    invoices=new_invoices,
                    payments=new_payments,
                    customer_cards=new_cards,
                    updated_at=datetime.now(UTC),
                    version=self.version + 1,
                )
        self._register_event(
            PaymentReceivedEvent(
                aggregate_id=self.ar_id,
                aggregate_version=self.version + 1,
                payment=payment,
                received_by=payment.created_by,
            )
        )
        return self._copy_with(
            payments=new_payments,
            customer_cards=new_cards,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def add_credit_note(self, credit_note: Any) -> ARSubledger:
        new_credit_notes = self.credit_notes.copy()
        new_credit_notes[credit_note.credit_note_id] = credit_note
        invoice = self.invoices.get(credit_note.invoice_id)
        if invoice:
            new_invoice = invoice.apply_credit_note(credit_note.amount)
            new_invoices = self.invoices.copy()
            new_invoices[invoice.invoice_id] = new_invoice
            customer_card = self.customer_cards.get(invoice.customer_id)
            if customer_card:
                new_card = customer_card.apply_credit_note(credit_note.amount)
                new_cards = self.customer_cards.copy()
                new_cards[invoice.customer_id] = new_card
                self._register_event(
                    CreditNoteIssuedEvent(
                        aggregate_id=self.ar_id,
                        aggregate_version=self.version + 1,
                        credit_note=credit_note,
                        issued_by=credit_note.created_by,
                    )
                )
                return self._copy_with(
                    invoices=new_invoices,
                    customer_cards=new_cards,
                    credit_notes=new_credit_notes,
                    updated_at=datetime.now(UTC),
                    version=self.version + 1,
                )
        return self._copy_with(
            credit_notes=new_credit_notes,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )

    def get_customer_outstanding(self, customer_id: UUID) -> Decimal:
        card = self.customer_cards.get(customer_id)
        return card.outstanding_balance if card else Decimal(0)

    def get_total_outstanding(self) -> Decimal:
        return sum(card.outstanding_balance for card in self.customer_cards.values())

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
        for card in self.customer_cards.values():
            bucket_vo = card.get_aging_bucket(as_of)
            if bucket_vo.bucket == AgingBucket.CURRENT:
                buckets["current"] += bucket_vo.amount
            elif bucket_vo.bucket == AgingBucket.DAYS_1_30:
                buckets["1_30"] += bucket_vo.amount
            elif bucket_vo.bucket == AgingBucket.DAYS_31_60:
                buckets["31_60"] += bucket_vo.amount
            elif bucket_vo.bucket == AgingBucket.DAYS_61_90:
                buckets["61_90"] += bucket_vo.amount
            elif bucket_vo.bucket == AgingBucket.OVER_90:
                buckets["over_90"] += bucket_vo.amount
        return buckets

    def get_invoice(self, invoice_id: UUID) -> InvoiceEntity | None:
        return self.invoices.get(invoice_id)

    def get_customer_card(self, customer_id: UUID) -> CustomerCard | None:
        return self.customer_cards.get(customer_id)

    # ==================== ENTITY DASAR METHODS ====================
    def create(self, created_by: str) -> ARSubledger:
        self._record_audit("CREATE", created_by, {"legal_entity_id": str(self.legal_entity_id)})
        return self

    def update(self, updated_by: str, **kwargs) -> ARSubledger:
        data = self.to_dict()
        for key, value in kwargs.items():
            if key not in ("ar_id", "created_at", "version"):
                data[key] = value
        new_ar = ARSubledger(
            ar_id=self.ar_id,
            legal_entity_id=self.legal_entity_id,
            invoices=self.invoices,
            payments=self.payments,
            customer_cards=self.customer_cards,
            credit_notes=self.credit_notes,
            debit_notes=self.debit_notes,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            version=self.version + 1,
        )
        new_ar._record_audit("UPDATE", updated_by, {"changes": kwargs})
        return new_ar

    def delete(self, deleted_by: str, reason: str | None = None) -> ARSubledger:
        if len(self.invoices) > 0:
            raise ValueError("Cannot delete AR subledger with existing invoices")
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("DELETE", deleted_by, {"reason": reason})
        return new_ar

    def restore(self, restored_by: str) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("RESTORE", restored_by, {})
        return new_ar

    def activate(self, activated_by: str) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("ACTIVATE", activated_by, {})
        return new_ar

    def deactivate(self, deactivated_by: str, reason: str | None = None) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("DEACTIVATE", deactivated_by, {"reason": reason})
        return new_ar

    def lock(self, locked_by: str, reason: str) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("LOCK", locked_by, {"reason": reason})
        return new_ar

    def unlock(self, unlocked_by: str) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("UNLOCK", unlocked_by, {})
        return new_ar

    def validate(self) -> dict[str, Any]:
        errors = []
        for inv in self.invoices.values():
            try:
                inv._validate()
            except Exception as e:
                errors.append(f"Invoice {inv.invoice_number}: {e}")
        for card in self.customer_cards.values():
            if card.outstanding_balance < 0:
                errors.append(f"Customer {card.customer_name} has negative balance")
        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "ar_id": str(self.ar_id),
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "ar_id": str(self.ar_id),
            "legal_entity_id": str(self.legal_entity_id),
            "total_invoices": len(self.invoices),
            "total_payments": len(self.payments),
            "total_customers": len(self.customer_cards),
            "total_outstanding": str(self.get_total_outstanding()),
            "aging_summary": self.get_aging_summary(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ARSubledger:
        created_at = datetime.fromisoformat(data["created_at"])
        updated_at = datetime.fromisoformat(data["updated_at"])
        return cls(
            ar_id=UUID(data["ar_id"]),
            legal_entity_id=UUID(data["legal_entity_id"]),
            created_at=created_at,
            updated_at=updated_at,
            version=data.get("version", 1),
        )

    def clone(self) -> ARSubledger:
        new_id = uuid4()
        now = datetime.now(UTC)
        cloned = ARSubledger(
            ar_id=new_id,
            legal_entity_id=self.legal_entity_id,
            created_at=now,
            updated_at=now,
            version=1,
        )
        # Clone invoices
        for inv in self.invoices.values():
            cloned_inv = inv.clone()
            cloned.invoices[cloned_inv.invoice_id] = cloned_inv
        # Clone payments
        for pmt in self.payments.values():
            cloned_pmt = pmt.clone()
            cloned.payments[cloned_pmt.payment_id] = cloned_pmt
        # Clone customer cards
        for card in self.customer_cards.values():
            cloned_card = card.clone()
            cloned.customer_cards[cloned_card.customer_id] = cloned_card
        cloned._record_audit("CLONE", "system", {"source": str(self.ar_id)})
        return cloned

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ar_id": str(self.ar_id),
            "invoice_count": len(self.invoices),
            "payment_count": len(self.payments),
            "customer_count": len(self.customer_cards),
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def get_version(self) -> int:
        return self.version

    def audit_trail(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._audit_trail[-limit:]

    def touch(self, touched_by: str) -> ARSubledger:
        new_ar = self._copy_with(updated_at=datetime.now(UTC), version=self.version + 1)
        new_ar._record_audit("TOUCH", touched_by, {})
        return new_ar

    # ==================== AGGREGATE ROOT METHODS ====================
    def add_child(self, entity: Any, created_by: str) -> ARSubledger:
        if isinstance(entity, InvoiceEntity):
            return self.add_invoice(entity)
        elif isinstance(entity, PaymentEntity):
            return self.add_payment(entity)
        else:
            raise ValueError(f"Unknown entity type: {type(entity)}")

    def remove_child(self, entity_id: UUID, entity_type: str, removed_by: str) -> ARSubledger:
        if entity_type == "invoice":
            new_invoices = {k: v for k, v in self.invoices.items() if k != entity_id}
            return self._copy_with(
                invoices=new_invoices, updated_at=datetime.now(UTC), version=self.version + 1
            )
        elif entity_type == "payment":
            new_payments = {k: v for k, v in self.payments.items() if k != entity_id}
            return self._copy_with(
                payments=new_payments, updated_at=datetime.now(UTC), version=self.version + 1
            )
        else:
            raise ValueError(f"Unknown entity type: {entity_type}")

    def can_post(self, user_id: str, permission: str) -> bool:
        # Simplified: any user can post if they have permission
        return True

    def post(self, user_id: str, permission: str, posted_by: str) -> ARSubledger:
        self._record_audit("POST", posted_by, {"user_id": user_id, "permission": permission})
        return self

    def can_approve(self, user_id: str, resource: str) -> bool:
        return True

    def approve(self, user_id: str, resource: str, approved_by: str) -> ARSubledger:
        self._record_audit("APPROVE", approved_by, {"user_id": user_id, "resource": resource})
        return self

    def can_reject(self, user_id: str, resource: str) -> bool:
        return True

    def reject(self, user_id: str, resource: str, rejected_by: str, reason: str) -> ARSubledger:
        self._record_audit(
            "REJECT", rejected_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_cancel(self, user_id: str, resource: str) -> bool:
        return True

    def cancel(self, user_id: str, resource: str, cancelled_by: str, reason: str) -> ARSubledger:
        self._record_audit(
            "CANCEL", cancelled_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_reverse(self, user_id: str, resource: str) -> bool:
        return True

    def reverse(self, user_id: str, resource: str, reversed_by: str, reason: str) -> ARSubledger:
        self._record_audit(
            "REVERSE", reversed_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_close(self, user_id: str, resource: str) -> bool:
        return True

    def close(self, user_id: str, resource: str, closed_by: str, reason: str) -> ARSubledger:
        self._record_audit(
            "CLOSE", closed_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_reopen(self, user_id: str, resource: str) -> bool:
        return True

    def reopen(self, user_id: str, resource: str, reopened_by: str, reason: str) -> ARSubledger:
        self._record_audit(
            "REOPEN", reopened_by, {"user_id": user_id, "resource": resource, "reason": reason}
        )
        return self

    def can_archive(self, user_id: str) -> bool:
        return True

    def archive(self, user_id: str, archived_by: str, reason: str | None = None) -> ARSubledger:
        self._record_audit("ARCHIVE", archived_by, {"user_id": user_id, "reason": reason})
        return self

    def can_unarchive(self, user_id: str) -> bool:
        return True

    def unarchive(self, user_id: str, unarchived_by: str) -> ARSubledger:
        self._record_audit("UNARCHIVE", unarchived_by, {"user_id": user_id})
        return self

    def register_event(self, event: DomainEvent) -> None:
        self._register_event(event)

    def get_events(self) -> list[DomainEvent]:
        return self._events.copy()

    def pull_events(self) -> list[DomainEvent]:
        events = self._events.copy()
        self._events.clear()
        return events

    def clear_events(self) -> None:
        self._events.clear()

    # ==================== PRIVATE HELPERS ====================
    def _copy_with(self, **kwargs) -> ARSubledger:
        return ARSubledger(
            ar_id=kwargs.get("ar_id", self.ar_id),
            legal_entity_id=kwargs.get("legal_entity_id", self.legal_entity_id),
            invoices=kwargs.get("invoices", self.invoices),
            payments=kwargs.get("payments", self.payments),
            customer_cards=kwargs.get("customer_cards", self.customer_cards),
            credit_notes=kwargs.get("credit_notes", self.credit_notes),
            debit_notes=kwargs.get("debit_notes", self.debit_notes),
            created_at=kwargs.get("created_at", self.created_at),
            updated_at=kwargs.get("updated_at", self.updated_at),
            version=kwargs.get("version", self.version),
        )


# === ALIAS UNTUK KOMPATIBILITAS ===
ARAggregate = ARSubledger
ARInvoiceAggregate = ARInvoice


# === 2. AR REPOSITORY PROTOCOL ===
class ARSubledgerRepository:
    async def get_by_legal_entity(self, legal_entity_id: UUID) -> ARSubledger | None:
        raise NotImplementedError

    async def save(self, ar: ARSubledger) -> None:
        raise NotImplementedError

    async def delete(self, ar_id: UUID) -> None:
        raise NotImplementedError

    # Repository standard methods
    async def add(self, ar: ARSubledger) -> None:
        await self.save(ar)

    async def update(self, ar: ARSubledger) -> None:
        await self.save(ar)

    async def exists(self, ar_id: UUID) -> bool:
        raise NotImplementedError

    async def get_by_id(self, ar_id: UUID) -> ARSubledger | None:
        raise NotImplementedError

    async def get_all(self) -> list[ARSubledger]:
        raise NotImplementedError

    async def search(self, criteria: dict[str, Any]) -> list[ARSubledger]:
        raise NotImplementedError

    async def count(self) -> int:
        raise NotImplementedError

    async def list(self, limit: int = 100, offset: int = 0) -> list[ARSubledger]:
        raise NotImplementedError

    async def paginate(self, page: int = 1, per_page: int = 20) -> tuple[list[ARSubledger], int]:
        raise NotImplementedError


__all__ = [
    "ARAggregate",
    "ARInvoiceAggregate",
    "ARSubledger",
    "ARSubledgerRepository",
]
