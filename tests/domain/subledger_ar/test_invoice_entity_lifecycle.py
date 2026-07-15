"""
tests/domain/subledger_ar/test_invoice_entity_lifecycle.py
==============================================================
Menutupi fungsi status-mutation ASLI di domain/subledger_ar/invoice_entity.py.
Diverifikasi manual sebelum menulis test ini -- tidak ditemukan bug guard
seperti di journal/tax_transaction (semua predikat can_edit/can_cancel/
can_record_payment dipakai konsisten oleh method mutasinya).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.subledger_ar.invoice_entity import InvoiceEntity, InvoiceStatus, InvoiceType


def _draft_invoice(**overrides) -> InvoiceEntity:
    defaults = dict(
        invoice_id=uuid4(), invoice_number="INV-TEST-0001", invoice_type=InvoiceType.STANDARD,
        customer_id=uuid4(), customer_name="PT Pelanggan Test", issue_date=date.today(),
        due_date=date.today() + timedelta(days=30), amount=Decimal("1000000"), currency="IDR",
        paid_amount=Decimal("0"), outstanding_amount=Decimal("1000000"),
        status=InvoiceStatus.DRAFT, description="invoice test",
    )
    defaults.update(overrides)
    return InvoiceEntity(**defaults)


class TestInvoiceHappyPathLifecycle:
    def test_activate_moves_draft_to_issued(self):
        inv = _draft_invoice()
        issued = inv.activate(activated_by="u1")
        assert issued.status == InvoiceStatus.ISSUED

    def test_record_partial_payment_moves_issued_to_partially_paid(self):
        inv = _draft_invoice().activate(activated_by="u1")
        partial = inv.record_payment(amount=Decimal("400000"), payment_id=uuid4())
        assert partial.status == InvoiceStatus.PARTIALLY_PAID
        assert partial.outstanding_amount == Decimal("600000")

    def test_record_full_payment_moves_to_fully_paid(self):
        inv = _draft_invoice().activate(activated_by="u1")
        paid = inv.record_payment(amount=Decimal("1000000"), payment_id=uuid4())
        assert paid.status == InvoiceStatus.FULLY_PAID
        assert paid.outstanding_amount == Decimal("0")

    def test_record_payment_in_two_installments_reaches_fully_paid(self):
        inv = _draft_invoice().activate(activated_by="u1")
        inv = inv.record_payment(amount=Decimal("400000"), payment_id=uuid4())
        assert inv.status == InvoiceStatus.PARTIALLY_PAID
        inv = inv.record_payment(amount=Decimal("600000"), payment_id=uuid4())
        assert inv.status == InvoiceStatus.FULLY_PAID

    def test_write_off_moves_issued_to_written_off(self):
        inv = _draft_invoice().activate(activated_by="u1")
        written_off = inv.write_off(written_off_by="u1", reason="piutang macet")
        assert written_off.status == InvoiceStatus.WRITTEN_OFF
        assert written_off.outstanding_amount == Decimal("0")

    def test_write_off_moves_partially_paid_to_written_off(self):
        inv = (
            _draft_invoice()
            .activate(activated_by="u1")
            .record_payment(amount=Decimal("400000"), payment_id=uuid4())
        )
        written_off = inv.write_off(written_off_by="u1", reason="sisa tidak tertagih")
        assert written_off.status == InvoiceStatus.WRITTEN_OFF

    def test_cancel_moves_draft_to_cancelled(self):
        inv = _draft_invoice()
        cancelled = inv.cancel(cancelled_by="u1", reason="salah input")
        assert cancelled.status == InvoiceStatus.CANCELLED

    def test_cancel_moves_issued_to_cancelled(self):
        inv = _draft_invoice().activate(activated_by="u1")
        cancelled = inv.cancel(cancelled_by="u1", reason="dibatalkan customer")
        assert cancelled.status == InvoiceStatus.CANCELLED

    def test_delete_then_restore_round_trip(self):
        inv = _draft_invoice()
        deleted = inv.delete(deleted_by="u1", reason="test hapus")
        assert deleted.status == InvoiceStatus.CANCELLED
        restored = deleted.restore(restored_by="u1")
        assert restored.status == InvoiceStatus.DRAFT


class TestInvoiceIllegalTransitions:
    def test_cannot_record_payment_on_draft_invoice(self):
        inv = _draft_invoice()
        with pytest.raises(ValueError, match="Cannot record payment"):
            inv.record_payment(amount=Decimal("100000"), payment_id=uuid4())

    def test_cannot_record_payment_exceeding_outstanding(self):
        inv = _draft_invoice().activate(activated_by="u1")
        with pytest.raises(ValueError, match="exceeds outstanding"):
            inv.record_payment(amount=Decimal("9999999"), payment_id=uuid4())

    def test_cannot_cancel_a_fully_paid_invoice(self):
        inv = _draft_invoice().activate(activated_by="u1").record_payment(
            amount=Decimal("1000000"), payment_id=uuid4()
        )
        with pytest.raises(ValueError, match="Cannot cancel"):
            inv.cancel(cancelled_by="u1", reason="test")

    def test_cannot_write_off_a_draft_invoice(self):
        inv = _draft_invoice()
        with pytest.raises(ValueError, match="Cannot write off"):
            inv.write_off(written_off_by="u1", reason="test")

    def test_cannot_restore_a_non_cancelled_invoice(self):
        inv = _draft_invoice().activate(activated_by="u1")
        with pytest.raises(ValueError, match="Cannot restore"):
            inv.restore(restored_by="u1")

    def test_cannot_update_a_fully_paid_invoice(self):
        inv = _draft_invoice().activate(activated_by="u1").record_payment(
            amount=Decimal("1000000"), payment_id=uuid4()
        )
        with pytest.raises(ValueError, match="Cannot update"):
            inv.update(updated_by="u1", description="ubah deskripsi")
