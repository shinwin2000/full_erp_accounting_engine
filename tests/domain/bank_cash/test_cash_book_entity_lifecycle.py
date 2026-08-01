"""
tests/domain/bank_cash/test_cash_book_entity_lifecycle.py
=============================================================
Menutupi fungsi status-mutation ASLI di domain/bank_cash/cash_book_entity.py.

TEMUAN (didokumentasikan, BELUM diputuskan/di-fix -- sama pola dengan
CashReceiptEntity.verify() sebelumnya):
--------------------------------------------------------------------
Tabel resmi `CashBookStatus.can_transition()` menyatakan SUSPENDED -> {ACTIVE,
CLOSED} valid. Tapi `activate()` cuma menerima status PENDING_ACTIVATION --
TIDAK ADA method yang bisa mengembalikan cash book dari SUSPENDED ke ACTIVE.
Begitu `deactivate()` dipanggil, cash book itu macet di SUSPENDED sampai
di-`delete()` (paksa ke CLOSED). Perlu keputusan: apakah `activate()`
seharusnya juga menerima SUSPENDED, atau perlu method terpisah semacam
`reactivate()`.

CATATAN TAMBAHAN (bukan bug, cuma observasi):
`freeze()`/`unfreeze()` dan `lock()`/`unlock()` melakukan hal yang PERSIS
sama (ACTIVE <-> FROZEN) -- kemungkinan nama method yang redundan/legacy,
tidak berbahaya tapi bisa membingungkan.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.cash_book_entity import CashBookEntity, CashBookStatus


def _pending_cash_book(**overrides) -> CashBookEntity:
    defaults = {
        "cash_book_id": uuid4(), "cash_book_code": "CB-TEST-001", "cash_book_name": "Kas Kecil Test",
        "legal_entity_id": uuid4(), "currency": "IDR", "opening_balance": Decimal("0"),
        "current_balance": Decimal("0"), "total_receipts": Decimal("0"), "total_disbursements": Decimal("0"),
        "status": CashBookStatus.PENDING_ACTIVATION, "last_updated": datetime.now(UTC),
    }
    defaults.update(overrides)
    return CashBookEntity(**defaults)


class TestCashBookReachableLifecycle:
    def test_activate_moves_pending_to_active(self):
        cb = _pending_cash_book()
        active = cb.activate(activated_by="admin1")
        assert active.status == CashBookStatus.ACTIVE

    def test_lock_moves_active_to_frozen(self):
        cb = _pending_cash_book().activate(activated_by="admin1")
        locked = cb.lock(locked_by="admin1", reason="audit tahunan")
        assert locked.status == CashBookStatus.FROZEN

    def test_unlock_moves_frozen_to_active(self):
        cb = _pending_cash_book().activate(activated_by="admin1").lock(locked_by="admin1", reason="audit")
        unlocked = cb.unlock(unlocked_by="admin1")
        assert unlocked.status == CashBookStatus.ACTIVE

    def test_deactivate_moves_active_to_suspended(self):
        cb = _pending_cash_book().activate(activated_by="admin1")
        suspended = cb.deactivate(deactivated_by="admin1", reason="cabang tutup sementara")
        assert suspended.status == CashBookStatus.SUSPENDED

    def test_close_permanent_moves_active_to_closed(self):
        cb = _pending_cash_book().activate(activated_by="admin1")
        closed = cb.close_permanent(closed_by="admin1")
        assert closed.status == CashBookStatus.CLOSED

    def test_archive_moves_closed_to_archived(self):
        cb = _pending_cash_book().activate(activated_by="admin1").close_permanent(closed_by="admin1")
        archived = cb.archive(archived_by="admin1")
        assert archived.status == CashBookStatus.ARCHIVED

    def test_delete_forces_status_to_closed_when_balance_zero(self):
        cb = _pending_cash_book().activate(activated_by="admin1")
        deleted = cb.delete(deleted_by="admin1", reason="cash book tidak dipakai lagi")
        assert deleted.status == CashBookStatus.CLOSED


class TestCashBookSuspendedReactivationIsCurrentlyUnreachable:
    """KARAKTERISASI gap (lihat catatan di header file)."""

    def test_activate_after_deactivate_currently_raises(self):
        cb = _pending_cash_book().activate(activated_by="admin1").deactivate(
            deactivated_by="admin1", reason="test"
        )
        with pytest.raises(ValueError, match="Cannot activate cash book in status suspended"):
            cb.activate(activated_by="admin1")


class TestCashBookIllegalTransitions:
    def test_cannot_lock_a_pending_activation_cash_book(self):
        cb = _pending_cash_book()
        with pytest.raises(ValueError, match="Cannot lock"):
            cb.lock(locked_by="admin1", reason="test")

    def test_cannot_delete_with_non_zero_balance(self):
        cb = _pending_cash_book(current_balance=Decimal("50000")).activate(activated_by="admin1")
        with pytest.raises(ValueError, match="non-zero balance"):
            cb.delete(deleted_by="admin1")

    def test_cannot_close_permanent_with_non_zero_balance(self):
        cb = _pending_cash_book(current_balance=Decimal("50000")).activate(activated_by="admin1")
        with pytest.raises(ValueError, match="non-zero balance"):
            cb.close_permanent(closed_by="admin1")

    def test_cannot_unarchive_directly_after_archive_is_actually_allowed(self):
        """Bukan illegal transition -- ini justru mengonfirmasi bahwa
        unarchive() BEKERJA meskipun tabel can_transition() bilang ARCHIVED
        seharusnya status terminal (allowed[ARCHIVED] == set()). Ada
        ketidaksesuaian antara tabel deklaratif dan implementasi method;
        dilaporkan terpisah, test ini cuma mencatat perilaku aktualnya."""
        cb = (
            _pending_cash_book()
            .activate(activated_by="admin1")
            .close_permanent(closed_by="admin1")
            .archive(archived_by="admin1")
        )
        unarchived = cb.unarchive(unarchived_by="admin1")
        assert unarchived.status == CashBookStatus.CLOSED
        assert CashBookStatus.can_transition(CashBookStatus.ARCHIVED, CashBookStatus.CLOSED) is False, (
            "Kalau assertion ini mulai gagal, berarti tabel can_transition() sudah "
            "diperbarui untuk mengizinkan ARCHIVED->CLOSED -- generate ulang "
            "test_domain_bank_cash_cash_book_entity_cashbookstatus_transition_matrix.py"
        )
