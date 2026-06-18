#!/usr/bin/env python3
"""
Package: domain.subledger_ar
Layer: Domain / Subledger AR

Account Receivable (AR) subledger domain layer.

Ekspos semua entitas, aggregate root, value object, event, invariant, repository,
dan utility functions untuk manajemen piutang (faktur, pembayaran, credit note,
debit note, kartu pelanggan, aging, dan penyisihan piutang tak tertagih).

Fitur lengkap sesuai standar ERP:
- Entity dasar: create, update, delete, restore, activate, deactivate, lock, unlock,
  validate, to_dict, from_dict, clone, snapshot, version, audit_trail, touch.
- Aggregate root: add_child, remove_child, can_post, post, can_approve, approve,
  can_reject, reject, can_cancel, cancel, can_reverse, reverse, close, reopen,
  archive, unarchive, register_event, get_events, pull_events, clear_events.
- Domain event: event_id, occurred_at, aggregate_id, aggregate_type, to_dict, from_dict,
  serialize, deserialize.
- Repository interface: add, save, update, delete, exists, get_by_id, get_by_code,
  get_all, search, count, list, paginate.
- Audit trail, snapshot, versioning.
"""

from __future__ import annotations

__version__ = "1.0.0"


# Lazy import untuk menghindari circular import
def __getattr__(name):
    if name == "ARSubledger" or name == "ARAggregate":
        from domain.subledger_ar.aggregate_root import ARAggregate, ARSubledger

        return ARSubledger if name == "ARSubledger" else ARAggregate
    if name == "ARSubledgerRepository":
        from domain.subledger_ar.aggregate_root import ARSubledgerRepository

        return ARSubledgerRepository
    if name == "AgingBucket" or name == "AgingBucketVO" or name == "AgingSummary":
        from domain.subledger_ar.aging_bucket_vo import AgingBucket, AgingBucketVO, AgingSummary

        return {
            "AgingBucket": AgingBucket,
            "AgingBucketVO": AgingBucketVO,
            "AgingSummary": AgingSummary,
        }[name]
    if name == "AgingCalculator" or name == "ARAgingBucketCalculator":
        from domain.subledger_ar.aging_bucket_vo import AgingCalculator, ARAgingBucketCalculator

        return AgingCalculator if name == "AgingCalculator" else ARAgingBucketCalculator
    if name == "BadDebtProvisionEngine":
        from domain.subledger_ar.bad_debt_provision_engine import BadDebtProvisionEngine

        return BadDebtProvisionEngine
    if name == "ProvisionMethod" or name == "ProvisionRate":
        from domain.subledger_ar.bad_debt_provision_engine import ProvisionMethod, ProvisionRate

        return {"ProvisionMethod": ProvisionMethod, "ProvisionRate": ProvisionRate}[name]
    if name == "CreditNoteEntity" or name == "ARCreditNote":
        from domain.subledger_ar.credit_note_entity import ARCreditNote, CreditNoteEntity

        return CreditNoteEntity if name == "CreditNoteEntity" else ARCreditNote
    if name == "CreditNoteStatus" or name == "CreditNoteReason":
        from domain.subledger_ar.credit_note_entity import CreditNoteReason, CreditNoteStatus

        return {"CreditNoteStatus": CreditNoteStatus, "CreditNoteReason": CreditNoteReason}[name]
    if name == "CreditNoteRepository":
        from domain.subledger_ar.credit_note_entity import CreditNoteRepository

        return CreditNoteRepository
    if name == "CustomerCard":
        from domain.subledger_ar.customer_card import CustomerCard

        return CustomerCard
    if name == "CustomerCardRepository":
        from domain.subledger_ar.customer_card import CustomerCardRepository

        return CustomerCardRepository
    if name == "DebitNoteEntity" or name == "ARDebitNote":
        from domain.subledger_ar.debit_note_entity import ARDebitNote, DebitNoteEntity

        return DebitNoteEntity if name == "DebitNoteEntity" else ARDebitNote
    if name == "DebitNoteStatus" or name == "DebitNoteReason":
        from domain.subledger_ar.debit_note_entity import DebitNoteReason, DebitNoteStatus

        return {"DebitNoteStatus": DebitNoteStatus, "DebitNoteReason": DebitNoteReason}[name]
    if name == "DebitNoteRepository":
        from domain.subledger_ar.debit_note_entity import DebitNoteRepository

        return DebitNoteRepository
    if name == "DomainEvent" or name == "DomainEventType" or name == "DomainEventPublisher":
        from domain.subledger_ar.domain_events import (
            DomainEvent,
            DomainEventPublisher,
            DomainEventType,
        )

        return {
            "DomainEvent": DomainEvent,
            "DomainEventType": DomainEventType,
            "DomainEventPublisher": DomainEventPublisher,
        }[name]
    if name.startswith("Invoice") or name.startswith("ARInvoice"):
        from domain.subledger_ar.invoice_entity import (
            ARInvoice,
            ARInvoiceLine,
            ARInvoiceStatus,
            ARInvoiceType,
            InvoiceEntity,
            InvoiceLineEntity,
            InvoiceStatus,
            InvoiceType,
        )

        mapping = {
            "InvoiceEntity": InvoiceEntity,
            "InvoiceStatus": InvoiceStatus,
            "InvoiceType": InvoiceType,
            "InvoiceLineEntity": InvoiceLineEntity,
            "ARInvoice": ARInvoice,
            "ARInvoiceStatus": ARInvoiceStatus,
            "ARInvoiceType": ARInvoiceType,
            "ARInvoiceLine": ARInvoiceLine,
        }
        return mapping[name]
    if name == "InvoiceRepository":
        from domain.subledger_ar.invoice_entity import InvoiceRepository

        return InvoiceRepository
    if name.startswith("Payment") or name.startswith("ARPayment"):
        from domain.subledger_ar.payment_entity import (
            ARPayment,
            ARPaymentMethod,
            ARPaymentStatus,
            PaymentEntity,
            PaymentMethod,
            PaymentStatus,
        )

        mapping = {
            "PaymentEntity": PaymentEntity,
            "PaymentStatus": PaymentStatus,
            "PaymentMethod": PaymentMethod,
            "ARPayment": ARPayment,
            "ARPaymentStatus": ARPaymentStatus,
            "ARPaymentMethod": ARPaymentMethod,
        }
        return mapping[name]
    if name == "PaymentRepository":
        from domain.subledger_ar.payment_entity import PaymentRepository

        return PaymentRepository
    if name == "ARInvariants" or name == "ARInvariantEnforcer" or name == "ARInvariantsValidator":
        from domain.subledger_ar.invariants import (
            ARInvariantEnforcer,
            ARInvariants,
            ARInvariantsValidator,
        )

        return {
            "ARInvariants": ARInvariants,
            "ARInvariantEnforcer": ARInvariantEnforcer,
            "ARInvariantsValidator": ARInvariantsValidator,
        }[name]
    if name == "InvariantResult":
        from domain.subledger_ar.invariants import InvariantResult

        return InvariantResult
    raise AttributeError(f"module {__name__} has no attribute {name}")


__all__ = [
    "__version__",
    # Aggregate
    "ARSubledger",
    "ARAggregate",
    "ARSubledgerRepository",
    # Aging
    "AgingBucket",
    "AgingBucketVO",
    "AgingSummary",
    "AgingCalculator",
    "ARAgingBucketCalculator",
    # Bad debt provision
    "BadDebtProvisionEngine",
    "ProvisionMethod",
    "ProvisionRate",
    # Credit note
    "CreditNoteEntity",
    "ARCreditNote",
    "CreditNoteStatus",
    "CreditNoteReason",
    "CreditNoteRepository",
    # Customer card
    "CustomerCard",
    "CustomerCardRepository",
    # Debit note
    "DebitNoteEntity",
    "ARDebitNote",
    "DebitNoteStatus",
    "DebitNoteReason",
    "DebitNoteRepository",
    # Domain events
    "DomainEvent",
    "DomainEventType",
    "DomainEventPublisher",
    # Invoice
    "InvoiceEntity",
    "InvoiceStatus",
    "InvoiceType",
    "InvoiceLineEntity",
    "ARInvoice",
    "ARInvoiceStatus",
    "ARInvoiceType",
    "ARInvoiceLine",
    "InvoiceRepository",
    # Payment
    "PaymentEntity",
    "PaymentStatus",
    "PaymentMethod",
    "ARPayment",
    "ARPaymentStatus",
    "ARPaymentMethod",
    "PaymentRepository",
    # Invariants
    "ARInvariants",
    "ARInvariantEnforcer",
    "ARInvariantsValidator",
    "InvariantResult",
]
