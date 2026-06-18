#!/usr/bin/env python3

"""
Module: test_ar_invoice.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk AR Invoice aggregate root.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.shared_value_objects.currency_vo import Currency
from domain.shared_value_objects.document_number_vo import DocumentNumber
from domain.subledger_ar.aggregate_root import ARAggregate
from domain.subledger_ar.domain_events import (
    ARCreditNoteIssued,
    ARInvoiceApproved,
    ARInvoiceCancelled,
    ARInvoiceCreated,
    ARInvoiceWrittenOff,
    ARPaymentApplied,
)
from domain.subledger_ar.invoice_entity import ARInvoice, ARInvoiceStatus, ARInvoiceType
from domain.subledger_ar.payment_entity import ARPayment, ARPaymentMethod, ARPaymentStatus


class TestARInvoiceAggregate:
    @pytest.fixture
    def valid_invoice_data(self) -> dict:
        now = datetime(2025, 3, 1, tzinfo=UTC)
        due = datetime(2025, 3, 31, tzinfo=UTC)
        return {
            "id": uuid4(),
            "legal_entity_id": uuid4(),
            "invoice_number": DocumentNumber("INV-2025-00001"),
            "customer_id": uuid4(),
            "customer_name": "PT Pelanggan",
            "issue_date": now,
            "due_date": due,
            "amount": Decimal("5000000"),
            "paid_amount": Decimal("0"),
            "remaining_amount": Decimal("5000000"),
            "currency": Currency("IDR"),
            "status": ARInvoiceStatus.DRAFT,
            "invoice_type": ARInvoiceType.STANDARD,
            "tax_amount": Decimal("0"),
            "description": "Invoice penjualan",
            "sales_order_id": None,
            "created_by": uuid4(),
            "created_at": datetime.utcnow(),
        }

    @pytest.fixture
    def valid_payment_data(self) -> dict:
        return {
            "id": uuid4(),
            "legal_entity_id": uuid4(),
            "payment_number": DocumentNumber("PYMT-2025-00001"),
            "customer_id": uuid4(),
            "customer_name": "PT Pelanggan",
            "payment_date": datetime(2025, 3, 15, tzinfo=UTC),
            "amount": Decimal("3000000"),
            "remaining_to_allocate": Decimal("3000000"),
            "payment_method": ARPaymentMethod.BANK_TRANSFER,
            "reference_number": "TRF001",
            "bank_account_id": None,
            "status": ARPaymentStatus.PENDING,
            "created_by": uuid4(),
            "created_at": datetime.utcnow(),
            "applied_amount": Decimal("0"),
        }

    def test_create_invoice_success(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        assert aggregate.invoice.id == invoice.id
        assert aggregate.invoice.status == ARInvoiceStatus.DRAFT
        assert aggregate.version == 1
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARInvoiceCreated)
        assert events[0].aggregate_id == invoice.id

    def test_approve_invoice_success(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.clear_events()
        aggregate.approve(approver_id=uuid4())
        assert aggregate.invoice.status == ARInvoiceStatus.APPROVED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARInvoiceApproved)

    def test_cancel_invoice_success(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.clear_events()
        aggregate.cancel(reason="Batal pesanan", user_id=uuid4())
        assert aggregate.invoice.status == ARInvoiceStatus.CANCELLED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARInvoiceCancelled)

    def test_cannot_cancel_approved_invoice(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        with pytest.raises(ValueError, match="Cannot cancel approved invoice"):
            aggregate.cancel("Alasan", uuid4())

    def test_apply_payment_success(self, valid_invoice_data, valid_payment_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        payment = ARPayment(**valid_payment_data)
        aggregate.apply_payment(payment_id=payment.id, amount=Decimal("3000000"), user_id=uuid4())
        # Setelah apply_payment, invoice sudah diperbarui
        assert aggregate.invoice.paid_amount == Decimal("3000000")
        assert aggregate.invoice.remaining_amount == Decimal("2000000")
        assert aggregate.invoice.status == ARInvoiceStatus.PARTIALLY_PAID
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARPaymentApplied)
        assert events[0].amount == Decimal("3000000")

    def test_full_payment_sets_invoice_to_paid(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        aggregate.apply_payment(payment_id=uuid4(), amount=Decimal("5000000"), user_id=uuid4())
        assert aggregate.invoice.paid_amount == Decimal("5000000")
        assert aggregate.invoice.remaining_amount == Decimal("0")
        assert aggregate.invoice.status == ARInvoiceStatus.PAID

    def test_apply_payment_exceeds_invoice_amount_raises_error(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        with pytest.raises(ValueError, match="exceeds remaining amount"):
            aggregate.apply_payment(payment_id=uuid4(), amount=Decimal("6000000"), user_id=uuid4())

    def test_issue_credit_note_success(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        credit_note_id = uuid4()
        aggregate.apply_credit_note(
            credit_note_id=credit_note_id, amount=Decimal("1000000"), user_id=uuid4()
        )
        # Setelah apply_credit_note, remaining_amount sudah berkurang
        assert aggregate.invoice.remaining_amount == Decimal("4000000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARCreditNoteIssued)

    def test_write_off_invoice(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        aggregate.write_off(reason="Tidak tertagih", amount=Decimal("5000000"), user_id=uuid4())
        assert aggregate.invoice.status == ARInvoiceStatus.WRITTEN_OFF
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], ARInvoiceWrittenOff)

    def test_aging_bucket_calculation(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        as_of_date = datetime(2025, 4, 1, tzinfo=UTC)
        days_overdue = (as_of_date - invoice.due_date).days
        assert days_overdue == 1
        if days_overdue <= 30:
            bucket = "1-30 days"
        elif days_overdue <= 60:
            bucket = "31-60 days"
        elif days_overdue <= 90:
            bucket = "61-90 days"
        else:
            bucket = ">90 days"
        assert bucket == "1-30 days"

    def test_version_increment(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        assert aggregate.version == 1
        aggregate.approve(uuid4())
        assert aggregate.version == 2
        aggregate.apply_payment(uuid4(), Decimal("2000000"), uuid4())
        assert aggregate.version == 3

    def test_reconstruct_from_events(self, valid_invoice_data):
        invoice = ARInvoice(**valid_invoice_data)
        aggregate = ARAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.apply_payment(uuid4(), Decimal("2000000"), uuid4())
        events = aggregate.get_events()
        new_agg = ARAggregate.reconstruct(events)
        assert new_agg.invoice.id == aggregate.invoice.id
        assert new_agg.invoice.paid_amount == Decimal("2000000")
        assert new_agg.version == aggregate.version
        assert new_agg.get_events() == []


if __name__ == "__main__":
    pytest.main([__file__])
