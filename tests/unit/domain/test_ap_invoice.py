#!/usr/bin/env python3

"""
Module: test_ap_invoice.py

Unit tests untuk AP Invoice aggregate root.
Menguji pembuatan invoice, pembayaran, credit note, dan invariants.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.shared_value_objects.currency_vo import Currency
from domain.shared_value_objects.document_number_vo import DocumentNumber
from domain.subledger_ap.aggregate_root import APAggregate
from domain.subledger_ap.domain_events import (
    APCreditNoteIssued,
    APDebitNoteIssued,
    APInvoiceApproved,
    APInvoiceCreated,
    APPaymentApplied,
)
from domain.subledger_ap.invoice_entity import APInvoice, APInvoiceStatus, APInvoiceType
from domain.subledger_ap.payment_entity import APPayment, APPaymentMethod, APPaymentStatus


class TestAPInvoiceAggregate:
    """Test suite untuk AP Invoice aggregate."""

    @pytest.fixture
    def valid_invoice_data(self) -> dict:
        """Fixture data invoice valid."""
        return {
            "id": uuid4(),
            "legal_entity_id": uuid4(),
            "invoice_number": DocumentNumber("AP-INV-2025-00001"),
            "vendor_id": uuid4(),
            "vendor_name": "PT Pemasok",
            "invoice_date": date(2025, 3, 1),
            "due_date": date(2025, 3, 31),
            "amount": Decimal("10000000"),
            "paid_amount": Decimal("0"),
            "remaining_amount": Decimal("10000000"),
            "currency": Currency("IDR"),
            "status": APInvoiceStatus.DRAFT,
            "invoice_type": APInvoiceType.STANDARD,
            "tax_amount": Decimal("1100000"),
            "description": "Invoice pembelian",
            "po_number": "PO-001",
            "grn_number": "GRN-001",
            "created_by": uuid4(),
            "created_at": datetime.now(UTC),
        }

    @pytest.fixture
    def valid_payment_data(self) -> dict:
        """Fixture data payment valid."""
        return {
            "id": uuid4(),
            "legal_entity_id": uuid4(),
            "payment_number": DocumentNumber("AP-PYMT-2025-00001"),
            "vendor_id": uuid4(),
            "vendor_name": "PT Pemasok",
            "payment_date": date(2025, 3, 20),
            "amount": Decimal("5000000"),
            "remaining_to_allocate": Decimal("5000000"),
            "payment_method": APPaymentMethod.BANK_TRANSFER,
            "reference_number": "TRF002",
            "bank_account_id": None,
            "status": APPaymentStatus.PENDING,
            "created_by": uuid4(),
            "created_at": datetime.now(UTC),
            "applied_amount": Decimal("0"),
        }

    def test_create_invoice_success(self, valid_invoice_data):
        """Test: Membuat AP invoice baru berhasil."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        assert aggregate.get_invoice(invoice.id) is not None
        assert aggregate.invoice.status == APInvoiceStatus.DRAFT
        # Version after create should be 1 (one event created)
        assert aggregate.version == 1
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], APInvoiceCreated)
        assert events[0].invoice_id == invoice.id

    def test_approve_invoice_success(self, valid_invoice_data):
        """Test: Approve AP invoice berhasil."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.clear_events()
        aggregate.approve(approver_id=uuid4())
        assert aggregate.invoice.status == APInvoiceStatus.VERIFIED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], APInvoiceApproved)

    def test_cancel_invoice_success(self, valid_invoice_data):
        """Test: Cancel AP invoice berhasil."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.clear_events()
        aggregate.cancel(reason="Pesanan dibatalkan", user_id=uuid4())
        assert aggregate.invoice.status == APInvoiceStatus.CANCELLED
        events = aggregate.get_events()
        assert len(events) == 1
        # Cancel event is a custom object, but we check it exists
        assert hasattr(events[0], "invoice_number")

    def test_apply_payment_success(self, valid_invoice_data, valid_payment_data):
        """Test: Apply payment ke invoice berhasil."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        payment = APPayment(**valid_payment_data)
        aggregate.apply_payment(payment_id=payment.id, amount=Decimal("5000000"), user_id=uuid4())
        assert aggregate.invoice.paid_amount == Decimal("5000000")
        assert aggregate.invoice.outstanding_amount == Decimal("5000000")
        assert aggregate.invoice.status == APInvoiceStatus.PARTIALLY_PAID
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], APPaymentApplied)
        assert events[0].amount == Decimal("5000000")

    def test_full_payment_sets_invoice_to_paid(self, valid_invoice_data):
        """Test: Payment lunas mengubah status invoice menjadi PAID."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.apply_payment(payment_id=uuid4(), amount=Decimal("10000000"), user_id=uuid4())
        assert aggregate.invoice.paid_amount == Decimal("10000000")
        assert aggregate.invoice.outstanding_amount == Decimal("0")
        assert aggregate.invoice.status == APInvoiceStatus.FULLY_PAID

    def test_apply_credit_note_success(self, valid_invoice_data):
        """Test: Apply credit note ke invoice berhasil."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        credit_note_id = uuid4()
        aggregate.apply_credit_note(
            credit_note_id=credit_note_id, amount=Decimal("2000000"), user_id=uuid4()
        )
        assert aggregate.invoice.credit_note_amount == Decimal("2000000")
        assert aggregate.invoice.outstanding_amount == Decimal("8000000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], APCreditNoteIssued)

    def test_apply_debit_note_success(self, valid_invoice_data):
        """Test: Apply debit note (meningkatkan tagihan) ke invoice."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.clear_events()
        debit_note_id = uuid4()
        aggregate.apply_debit_note(
            debit_note_id=debit_note_id, amount=Decimal("500000"), user_id=uuid4()
        )
        assert aggregate.invoice.debit_note_amount == Decimal("500000")
        assert aggregate.invoice.outstanding_amount == Decimal("10500000")
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], APDebitNoteIssued)

    def test_three_way_match_validation(self, valid_invoice_data):
        """Test: Three-way matching antara PO, GRN, dan Invoice."""
        # Placeholder test, always passes
        pass

    def test_aging_bucket_calculation(self, valid_invoice_data):
        """Test: Perhitungan aging bucket AP."""
        invoice = APInvoice(**valid_invoice_data)
        as_of_date = date(2025, 4, 1)
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
        """Test: Version increment pada setiap perubahan."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        assert aggregate.version == 1
        aggregate.approve(uuid4())
        assert aggregate.version == 2
        aggregate.apply_payment(uuid4(), Decimal("3000000"), uuid4())
        assert aggregate.version == 3

    def test_reconstruct_from_events(self, valid_invoice_data):
        """Test: Rekonstruksi aggregate dari event stream."""
        invoice = APInvoice(**valid_invoice_data)
        aggregate = APAggregate.create(invoice, user_id=uuid4())
        aggregate.approve(uuid4())
        aggregate.apply_payment(uuid4(), Decimal("4000000"), uuid4())
        events = aggregate.get_events()
        new_agg = APAggregate.reconstruct(events)
        assert new_agg.invoice.id == aggregate.invoice.id
        assert new_agg.invoice.paid_amount == Decimal("4000000")
        assert new_agg.version == aggregate.version
        assert new_agg.get_events() == []


if __name__ == "__main__":
    pytest.main([__file__])
