"""
tests/domain/subledger_ar/test_credit_debit_note_entity_lifecycle.py
========================================================================
Menutupi fungsi status-mutation ASLI di domain/subledger_ar/credit_note_entity.py
dan domain/subledger_ar/debit_note_entity.py. Diverifikasi manual -- tidak
ditemukan bug guard di kedua file ini.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.subledger_ar.credit_note_entity import CreditNoteEntity, CreditNoteStatus
from domain.subledger_ar.debit_note_entity import DebitNoteEntity, DebitNoteStatus


def _draft_credit_note(**overrides) -> CreditNoteEntity:
    defaults = {
        "credit_note_id": uuid4(), "credit_note_number": "CN-TEST-0001", "invoice_id": uuid4(),
        "invoice_number": "INV-TEST-0001", "customer_id": uuid4(), "customer_name": "PT Pelanggan Test",
        "issue_date": date.today(), "amount": Decimal("100000"), "currency": "IDR",
        "reason": "retur barang", "status": CreditNoteStatus.DRAFT, "description": "credit note test",
    }
    defaults.update(overrides)
    return CreditNoteEntity(**defaults)


def _draft_debit_note(**overrides) -> DebitNoteEntity:
    defaults = {
        "debit_note_id": uuid4(), "debit_note_number": "DN-TEST-0001", "invoice_id": uuid4(),
        "invoice_number": "INV-TEST-0001", "customer_id": uuid4(), "customer_name": "PT Pelanggan Test",
        "issue_date": date.today(), "amount": Decimal("50000"), "currency": "IDR",
        "reason": "biaya tambahan", "status": DebitNoteStatus.DRAFT, "description": "debit note test",
    }
    defaults.update(overrides)
    return DebitNoteEntity(**defaults)


class TestCreditNoteLifecycle:
    def test_activate_moves_draft_to_issued(self):
        cn = _draft_credit_note()
        issued = cn.activate(activated_by="u1")
        assert issued.status == CreditNoteStatus.ISSUED

    def test_apply_moves_issued_to_applied(self):
        cn = _draft_credit_note().activate(activated_by="u1")
        applied = cn.apply(applied_by="u1")
        assert applied.status == CreditNoteStatus.APPLIED

    def test_cancel_moves_issued_to_cancelled(self):
        cn = _draft_credit_note().activate(activated_by="u1")
        cancelled = cn.cancel(cancelled_by="u1", reason="salah terbit")
        assert cancelled.status == CreditNoteStatus.CANCELLED

    def test_cannot_apply_a_draft_credit_note(self):
        cn = _draft_credit_note()
        with pytest.raises(ValueError, match="Cannot apply"):
            cn.apply(applied_by="u1")

    def test_cannot_apply_an_already_applied_credit_note(self):
        cn = _draft_credit_note().activate(activated_by="u1").apply(applied_by="u1")
        with pytest.raises(ValueError, match="Cannot apply"):
            cn.apply(applied_by="u1")

    def test_cannot_cancel_an_applied_credit_note(self):
        cn = _draft_credit_note().activate(activated_by="u1").apply(applied_by="u1")
        with pytest.raises(ValueError, match="Cannot cancel"):
            cn.cancel(cancelled_by="u1", reason="test")


class TestDebitNoteLifecycle:
    def test_activate_moves_draft_to_issued(self):
        dn = _draft_debit_note()
        issued = dn.activate(activated_by="u1")
        assert issued.status == DebitNoteStatus.ISSUED

    def test_apply_moves_issued_to_applied(self):
        dn = _draft_debit_note().activate(activated_by="u1")
        applied = dn.apply(applied_by="u1")
        assert applied.status == DebitNoteStatus.APPLIED

    def test_cancel_moves_draft_to_cancelled(self):
        dn = _draft_debit_note()
        cancelled = dn.cancel(cancelled_by="u1", reason="salah input")
        assert cancelled.status == DebitNoteStatus.CANCELLED

    def test_cannot_apply_a_draft_debit_note(self):
        dn = _draft_debit_note()
        with pytest.raises(ValueError, match="Cannot apply"):
            dn.apply(applied_by="u1")

    def test_cannot_cancel_an_applied_debit_note(self):
        dn = _draft_debit_note().activate(activated_by="u1").apply(applied_by="u1")
        with pytest.raises(ValueError, match="Cannot cancel"):
            dn.cancel(cancelled_by="u1", reason="test")
