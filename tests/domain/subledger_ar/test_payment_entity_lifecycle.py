"""
tests/domain/subledger_ar/test_payment_entity_lifecycle.py
==============================================================
Menutupi fungsi status-mutation ASLI di domain/subledger_ar/payment_entity.py.
Diverifikasi manual -- tidak ditemukan bug guard di file ini.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.subledger_ar.payment_entity import PaymentEntity, PaymentMethod, PaymentStatus


def _pending_payment(**overrides) -> PaymentEntity:
    defaults = dict(
        payment_id=uuid4(), payment_number="PMT-TEST-0001", customer_id=uuid4(),
        customer_name="PT Pelanggan Test", payment_date=date.today(), amount=Decimal("500000"),
        currency="IDR", payment_method=PaymentMethod.BANK_TRANSFER, status=PaymentStatus.PENDING,
    )
    defaults.update(overrides)
    return PaymentEntity(**defaults)


class TestPaymentHappyPathLifecycle:
    def test_confirm_moves_pending_to_confirmed(self):
        p = _pending_payment()
        confirmed = p.confirm(confirmed_by="u1")
        assert confirmed.status == PaymentStatus.CONFIRMED

    def test_allocate_full_amount_moves_confirmed_to_allocated(self):
        p = _pending_payment().confirm(confirmed_by="u1")
        allocated = p.allocate_to_invoice(invoice_id=uuid4(), amount=Decimal("500000"))
        assert allocated.status == PaymentStatus.ALLOCATED

    def test_allocate_partial_amount_keeps_status(self):
        p = _pending_payment(amount=Decimal("1000000")).confirm(confirmed_by="u1")
        partially_allocated = p.allocate_to_invoice(invoice_id=uuid4(), amount=Decimal("400000"))
        assert partially_allocated.status == PaymentStatus.CONFIRMED
        assert partially_allocated.allocated_amount == Decimal("400000")

    def test_allocate_directly_from_pending_is_allowed(self):
        p = _pending_payment()
        allocated = p.allocate_to_invoice(invoice_id=uuid4(), amount=Decimal("500000"))
        assert allocated.status == PaymentStatus.ALLOCATED

    def test_refund_moves_confirmed_to_refunded(self):
        p = _pending_payment().confirm(confirmed_by="u1")
        refunded = p.refund(refunded_by="u1", reason="pembayaran ganda")
        assert refunded.status == PaymentStatus.REFUNDED

    def test_refund_moves_allocated_to_refunded(self):
        p = (
            _pending_payment()
            .confirm(confirmed_by="u1")
            .allocate_to_invoice(invoice_id=uuid4(), amount=Decimal("500000"))
        )
        refunded = p.refund(refunded_by="u1", reason="invoice dibatalkan")
        assert refunded.status == PaymentStatus.REFUNDED

    def test_delete_then_restore_round_trip(self):
        p = _pending_payment()
        deleted = p.delete(deleted_by="u1", reason="salah input")
        assert deleted.status == PaymentStatus.FAILED
        restored = deleted.restore(restored_by="u1")
        assert restored.status == PaymentStatus.PENDING


class TestPaymentIllegalTransitions:
    def test_cannot_confirm_an_already_confirmed_payment(self):
        p = _pending_payment().confirm(confirmed_by="u1")
        with pytest.raises(ValueError, match="Cannot confirm"):
            p.confirm(confirmed_by="u1")

    def test_cannot_allocate_more_than_payment_amount(self):
        p = _pending_payment(amount=Decimal("500000")).confirm(confirmed_by="u1")
        with pytest.raises(ValueError, match="exceeds remaining"):
            p.allocate_to_invoice(invoice_id=uuid4(), amount=Decimal("999999"))

    def test_cannot_refund_a_pending_payment(self):
        p = _pending_payment()
        with pytest.raises(ValueError, match="Cannot refund"):
            p.refund(refunded_by="u1", reason="test")

    def test_cannot_restore_a_non_failed_payment(self):
        p = _pending_payment().confirm(confirmed_by="u1")
        with pytest.raises(ValueError, match="Cannot restore"):
            p.restore(restored_by="u1")
