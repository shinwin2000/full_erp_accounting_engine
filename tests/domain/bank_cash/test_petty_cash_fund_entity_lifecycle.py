"""
tests/domain/bank_cash/test_petty_cash_fund_entity_lifecycle.py
===================================================================
Menutupi fungsi status-mutation ASLI di
domain/bank_cash/petty_cash_fund_entity.py.

TEMUAN (didokumentasikan, TIDAK saya fix -- bukan bug yang bikin fungsi
gagal, tapi tabel deklaratif tidak sinkron dengan implementasi nyata):
--------------------------------------------------------------------------
`activate_suspended()` dan `complete_audit()` bisa menghasilkan status
DEPLETED (kalau current_balance <= replenishment_threshold) -- ini
BERFUNGSI dengan benar. Tapi tabel `PettyCashStatus.can_transition()`
menyatakan:
    SUSPENDED: {ACTIVE, CLOSED, UNDER_AUDIT}       -- tidak ada DEPLETED
    UNDER_AUDIT: {ACTIVE, CLOSED}                   -- tidak ada DEPLETED

Jadi kalau ada bagian lain sistem yang memvalidasi transisi lewat
`can_transition()` sebelum memanggil method ini (mis. di application layer),
transisi SUSPENDED->DEPLETED / UNDER_AUDIT->DEPLETED bisa ditolak duluan
walau method aslinya sanggup melakukannya. Rekomendasi: tambahkan
cls.DEPLETED ke set SUSPENDED dan UNDER_AUDIT di tabel supaya sinkron
dengan kode aslinya, lalu regenerate
test_..._pettycashstatus_transition_matrix.py.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.petty_cash_fund_entity import PettyCashFundEntity, PettyCashStatus


def _pending_petty_cash(**overrides) -> PettyCashFundEntity:
    defaults = dict(
        petty_cash_id=uuid4(), petty_cash_code="PC-TEST-001", petty_cash_name="Kas Kecil Test",
        legal_entity_id=uuid4(), currency="IDR", initial_fund=Decimal("2000000"),
        current_balance=Decimal("2000000"), total_disbursements=Decimal("0"),
        replenishment_threshold=Decimal("1000000"), replenishment_amount=Decimal("2000000"),
        status=PettyCashStatus.PENDING_APPROVAL, custodian_name="Budi Santoso",
    )
    defaults.update(overrides)
    return PettyCashFundEntity(**defaults)


class TestPettyCashHappyPathLifecycle:
    def test_activate_moves_pending_approval_to_active(self):
        pc = _pending_petty_cash()
        active = pc.activate(activated_by="admin1")
        assert active.status == PettyCashStatus.ACTIVE

    def test_lock_moves_active_to_frozen(self):
        pc = _pending_petty_cash().activate(activated_by="admin1")
        locked = pc.lock(locked_by="admin1", reason="dugaan penyalahgunaan")
        assert locked.status == PettyCashStatus.FROZEN

    def test_unlock_moves_frozen_to_active(self):
        pc = _pending_petty_cash().activate(activated_by="admin1").lock(locked_by="admin1", reason="cek")
        unlocked = pc.unlock(unlocked_by="admin1")
        assert unlocked.status == PettyCashStatus.ACTIVE

    def test_suspend_moves_active_to_suspended(self):
        pc = _pending_petty_cash().activate(activated_by="admin1")
        suspended = pc.suspend(suspended_by="admin1", reason="custodian resign")
        assert suspended.status == PettyCashStatus.SUSPENDED

    def test_activate_suspended_with_balance_above_threshold_returns_active(self):
        pc = (
            _pending_petty_cash(current_balance=Decimal("2000000"), replenishment_threshold=Decimal("1000000"))
            .activate(activated_by="admin1")
            .suspend(suspended_by="admin1", reason="test")
        )
        reactivated = pc.activate_suspended(activated_by="admin1")
        assert reactivated.status == PettyCashStatus.ACTIVE

    def test_activate_suspended_with_balance_below_threshold_returns_depleted(self):
        """Regression guard untuk perilaku DEPLETED yang tidak tercermin di
        tabel can_transition() (lihat catatan di header file)."""
        pc = (
            _pending_petty_cash(current_balance=Decimal("500000"), replenishment_threshold=Decimal("1000000"))
            .activate(activated_by="admin1")
            .suspend(suspended_by="admin1", reason="test")
        )
        reactivated = pc.activate_suspended(activated_by="admin1")
        assert reactivated.status == PettyCashStatus.DEPLETED

    def test_mark_under_audit_moves_active_to_under_audit(self):
        pc = _pending_petty_cash().activate(activated_by="admin1")
        audited = pc.mark_under_audit(audited_by="auditor1", reason="audit rutin Q3")
        assert audited.status == PettyCashStatus.UNDER_AUDIT

    def test_complete_audit_returns_to_active_when_balance_sufficient(self):
        pc = (
            _pending_petty_cash(current_balance=Decimal("2000000"), replenishment_threshold=Decimal("1000000"))
            .activate(activated_by="admin1")
            .mark_under_audit(audited_by="auditor1", reason="audit rutin")
        )
        completed = pc.complete_audit(completed_by="auditor1", findings="Sesuai")
        assert completed.status == PettyCashStatus.ACTIVE

    def test_close_moves_active_to_closed_when_balance_matches(self):
        pc = _pending_petty_cash(current_balance=Decimal("0")).activate(activated_by="admin1")
        closed = pc.close(closed_by="admin1", final_balance=Decimal("0"))
        assert closed.status == PettyCashStatus.CLOSED


class TestPettyCashIllegalTransitions:
    def test_cannot_activate_an_already_active_fund(self):
        pc = _pending_petty_cash().activate(activated_by="admin1")
        with pytest.raises(ValueError, match="Cannot activate"):
            pc.activate(activated_by="admin1")

    def test_cannot_suspend_an_already_suspended_fund(self):
        pc = _pending_petty_cash().activate(activated_by="admin1").suspend(suspended_by="a", reason="x")
        with pytest.raises(ValueError, match="already suspended"):
            pc.suspend(suspended_by="a", reason="y")

    def test_cannot_suspend_a_closed_fund(self):
        pc = _pending_petty_cash(current_balance=Decimal("0")).activate(activated_by="admin1").close(
            closed_by="admin1", final_balance=Decimal("0")
        )
        with pytest.raises(ValueError, match="Cannot suspend closed"):
            pc.suspend(suspended_by="a", reason="x")

    def test_cannot_close_an_already_closed_fund(self):
        pc = _pending_petty_cash(current_balance=Decimal("0")).activate(activated_by="admin1").close(
            closed_by="admin1", final_balance=Decimal("0")
        )
        with pytest.raises(ValueError, match="already closed"):
            pc.close(closed_by="admin1")

    def test_cannot_close_with_mismatched_final_balance(self):
        pc = _pending_petty_cash(current_balance=Decimal("500000")).activate(activated_by="admin1")
        with pytest.raises(ValueError, match="does not match current balance"):
            pc.close(closed_by="admin1", final_balance=Decimal("999999"))

    def test_cannot_complete_audit_when_not_under_audit(self):
        pc = _pending_petty_cash().activate(activated_by="admin1")
        with pytest.raises(ValueError, match="Cannot complete audit"):
            pc.complete_audit(completed_by="auditor1")
