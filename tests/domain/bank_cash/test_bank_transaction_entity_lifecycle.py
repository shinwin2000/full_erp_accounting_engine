"""
tests/domain/bank_cash/test_bank_transaction_entity_lifecycle.py
====================================================================
Menutupi fungsi status-mutation ASLI di domain/bank_cash/bank_transaction_entity.py.

TEMUAN PALING SERIUS DI BATCH INI -- COMPLIANCE CHECK PALSU
--------------------------------------------------------------
`mark_as_reconciled()` punya blok kode yang secara eksplisit dikomentari
sendiri oleh penulisnya sebagai dummy:

    # ---- GL vs SUBLEDGER RECONCILIATION CHECK (dummy) ----
    # This is a placeholder to satisfy the static analyzer that expects
    # reconciliation check on this method.
    _gl_balance = Decimal(0)
    _subledger_balance = Decimal(0)
    if _gl_balance != _subledger_balance:
        logger.warning(...)

Kedua variabel di-hardcode ke 0, jadi `_gl_balance != _subledger_balance`
TIDAK PERNAH True -- method ini MENGAKU melakukan verifikasi rekonsiliasi
GL vs subledger padahal tidak pernah benar-benar membandingkan apapun.
Untuk sistem akuntansi ber-kepatuhan SOX/PSAK, ini adalah compliance
control yang PALSU: kalau ada auditor atau checker lain yang melihat
"mark_as_reconciled() melakukan pengecekan GL vs subledger" sebagai bukti
kontrol berjalan, itu klaim yang tidak benar.

Saya TIDAK mengisi logic rekonisiliasi sungguhan di sini karena itu perlu
akses ke GL balance & subledger balance yang sesungguhnya (lewat repository/
port, di luar cakupan domain entity murni ini) -- itu keputusan desain yang
perlu Anda ambil. Test di bawah ini mendokumentasikan perilaku SAAT INI
secara eksplisit (bukan mengasumsikan bahwa check-nya beneran jalan).

TEMUAN KECIL TAMBAHAN:
`TransactionStatus.RECONCILED` ada di enum, tapi `mark_as_reconciled()`
TIDAK PERNAH mengubah `.status` menjadi RECONCILED -- cuma set flag boolean
`is_reconciled = True`, status tetap apa adanya (CLEARED/COMPLETED). Kalau
memang By design begitu (reconciled dilacak lewat flag, bukan status),
enum value RECONCILED kemungkinan dead code yang bisa dibersihkan.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.bank_transaction_entity import (
    BankTransactionEntity,
    TransactionStatus,
    TransactionType,
)


def _pending_transaction(**overrides) -> BankTransactionEntity:
    defaults = {
        "transaction_id": uuid4(), "legal_entity_id": uuid4(), "bank_account_id": uuid4(),
        "transaction_date": date.today(), "amount": Decimal("750000"), "transaction_type": TransactionType.DEPOSIT,
        "description": "setoran tunai test", "reference_number": "REF-TEST-001", "counterparty_name": None,
        "counterparty_account": None, "status": TransactionStatus.PENDING, "is_reconciled": False,
        "created_by": uuid4(), "created_at": datetime.now(UTC), "reconciled_at": None,
    }
    defaults.update(overrides)
    return BankTransactionEntity(**defaults)


class TestBankTransactionHappyPathLifecycle:
    def test_mark_as_completed_moves_pending_to_completed(self):
        tx = _pending_transaction()
        completed = tx.mark_as_completed(completed_by=uuid4())
        assert completed.status == TransactionStatus.COMPLETED

    def test_mark_as_cleared_moves_completed_to_cleared(self):
        tx = _pending_transaction().mark_as_completed(completed_by=uuid4())
        cleared = tx.mark_as_cleared(cleared_by="ops1")
        assert cleared.status == TransactionStatus.CLEARED

    def test_mark_as_reconciled_sets_flag_from_cleared(self):
        tx = (
            _pending_transaction()
            .mark_as_completed(completed_by=uuid4())
            .mark_as_cleared(cleared_by="ops1")
        )
        reconciled = tx.mark_as_reconciled(reconciled_by=uuid4())
        assert reconciled.is_reconciled is True
        assert reconciled.reconciled_at is not None

    def test_mark_as_reconciled_also_allowed_directly_from_completed(self):
        tx = _pending_transaction().mark_as_completed(completed_by=uuid4())
        reconciled = tx.mark_as_reconciled(reconciled_by=uuid4())
        assert reconciled.is_reconciled is True

    def test_cancel_moves_pending_to_cancelled(self):
        tx = _pending_transaction()
        cancelled = tx.cancel(cancelled_by=uuid4(), reason="salah input jumlah")
        assert cancelled.status == TransactionStatus.CANCELLED

    def test_reject_moves_pending_to_rejected(self):
        tx = _pending_transaction()
        rejected = tx.reject(rejected_by=uuid4(), reason="tidak sesuai bukti transfer")
        assert rejected.status == TransactionStatus.REJECTED


class TestBankTransactionReconciliationCheckIsCurrentlyADummy:
    """KARAKTERISASI TEMUAN (lihat catatan panjang di header file). Test ini
    membuktikan bahwa mark_as_reconciled() akan tetap 'berhasil' walaupun GL
    dan subledger balance seharusnya TIDAK match -- karena checknya memang
    tidak pernah membandingkan nilai sungguhan. Kalau suatu saat reconciliation
    check ini diimplementasikan sungguhan dan method mulai bisa raise/reject
    pada mismatch, test ini akan butuh diperbarui (itu progress yang bagus,
    bukan regresi)."""

    def test_mark_as_reconciled_never_fails_regardless_of_actual_balances(self):
        tx = (
            _pending_transaction(amount=Decimal("999999999"))  # nominal ekstrem
            .mark_as_completed(completed_by=uuid4())
            .mark_as_cleared(cleared_by="ops1")
        )
        # Tidak ada cara dari luar untuk membuat GL vs subledger "mismatch"
        # supaya method ini menolak -- karena keduanya di-hardcode ke 0.
        reconciled = tx.mark_as_reconciled(reconciled_by=uuid4())
        assert reconciled.is_reconciled is True

    def test_mark_as_reconciled_does_not_change_status_to_reconciled_enum_value(self):
        """Mendokumentasikan bahwa TransactionStatus.RECONCILED tidak pernah
        benar-benar dipakai oleh method ini (lihat catatan header)."""
        tx = (
            _pending_transaction()
            .mark_as_completed(completed_by=uuid4())
            .mark_as_cleared(cleared_by="ops1")
        )
        reconciled = tx.mark_as_reconciled(reconciled_by=uuid4())
        assert reconciled.status == TransactionStatus.CLEARED
        assert reconciled.status != TransactionStatus.RECONCILED


class TestBankTransactionIllegalTransitions:
    def test_cannot_complete_an_already_completed_transaction(self):
        tx = _pending_transaction().mark_as_completed(completed_by=uuid4())
        with pytest.raises(ValueError, match="Cannot complete"):
            tx.mark_as_completed(completed_by=uuid4())

    def test_cannot_clear_a_pending_transaction_directly(self):
        tx = _pending_transaction()
        with pytest.raises(ValueError, match="Cannot clear"):
            tx.mark_as_cleared(cleared_by="ops1")

    def test_cannot_reconcile_a_pending_transaction(self):
        tx = _pending_transaction()
        with pytest.raises(ValueError, match="Cannot reconcile"):
            tx.mark_as_reconciled(reconciled_by=uuid4())

    def test_cannot_cancel_a_completed_transaction(self):
        tx = _pending_transaction().mark_as_completed(completed_by=uuid4())
        with pytest.raises(ValueError, match="Cannot cancel"):
            tx.cancel(cancelled_by=uuid4(), reason="test")

    def test_cannot_reject_a_completed_transaction(self):
        tx = _pending_transaction().mark_as_completed(completed_by=uuid4())
        with pytest.raises(ValueError, match="Cannot reject"):
            tx.reject(rejected_by=uuid4(), reason="test")
