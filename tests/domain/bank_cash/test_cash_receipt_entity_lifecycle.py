"""
tests/domain/bank_cash/test_cash_receipt_entity_lifecycle.py
================================================================
Menutupi fungsi status-mutation ASLI di domain/bank_cash/cash_receipt_entity.py.

OPEN QUESTION untuk Anto (BELUM diputuskan, BELUM di-fix, sengaja tidak saya
tebak jawabannya):
--------------------------------------------------------------------------
Tabel resmi `CashReceiptStatus.can_transition()` menyatakan:
    SUBMITTED -> {PENDING_VERIFICATION, REJECTED, CANCELLED}
    PENDING_VERIFICATION -> {VERIFIED, REJECTED}

Tapi method `submit()` yang sesungguhnya memindahkan status ke SUBMITTED,
dan TIDAK ADA method manapun di kelas ini yang memindahkan status dari
SUBMITTED ke PENDING_VERIFICATION. Sementara `verify()` mensyaratkan status
PENDING_VERIFICATION lewat can_verify(). Akibatnya: `verify()` TIDAK PERNAH
bisa dipanggil dengan sukses melalui alur normal manapun -- receipt akan
macet permanen di status SUBMITTED kalau tidak langsung di-reject/cancel.

Kemungkinan penyebab (perlu keputusan bisnis, bukan saya yang menentukan):
  (a) Ada method yang HILANG, mis. `start_verification()`/`queue_for_review()`
      yang seharusnya memindahkan SUBMITTED -> PENDING_VERIFICATION.
  (b) `submit()` seharusnya langsung set status ke PENDING_VERIFICATION,
      bukan SUBMITTED (menghapus state SUBMITTED sebagai state terpisah).
  (c) `can_verify()` seharusnya juga menerima status SUBMITTED.

Sampai ada keputusan, test di bawah ini HANYA menutupi jalur yang benar-benar
bisa dieksekusi hari ini (submit, reject dari SUBMITTED, cancel), dan secara
eksplisit mendokumentasikan kegagalan verify() sebagai regression-guard --
supaya begitu gap ini diperbaiki, test INI akan mengingatkan untuk diupdate
(bukan diam-diam tetap "pass" dan menyembunyikan perbaikannya).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.cash_receipt_entity import (
    CashReceiptEntity,
    CashReceiptStatus,
    CashReceiptType,
)


def _draft_receipt(**overrides) -> CashReceiptEntity:
    defaults = dict(
        receipt_id=uuid4(), receipt_number="CR-TEST-0001",
        receipt_type=CashReceiptType.CUSTOMER_PAYMENT,
        receipt_date=datetime.now(UTC), amount=Decimal("500000"), currency="IDR",
        status=CashReceiptStatus.DRAFT,
    )
    defaults.update(overrides)
    return CashReceiptEntity(**defaults)


class TestCashReceiptReachableLifecycle:
    def test_submit_moves_draft_to_submitted(self):
        receipt = _draft_receipt()
        submitted = receipt.submit(submitted_by="maker1")
        assert submitted.status == CashReceiptStatus.SUBMITTED

    def test_reject_moves_submitted_to_rejected(self):
        receipt = _draft_receipt().submit(submitted_by="maker1")
        rejected = receipt.reject(rejected_by="checker1", reason="bukti transfer tidak jelas")
        assert rejected.status == CashReceiptStatus.REJECTED

    def test_cancel_moves_draft_to_cancelled(self):
        receipt = _draft_receipt()
        cancelled = receipt.cancel(cancelled_by="maker1", reason="salah input")
        assert cancelled.status == CashReceiptStatus.CANCELLED

    def test_cancel_moves_submitted_to_cancelled(self):
        receipt = _draft_receipt().submit(submitted_by="maker1")
        cancelled = receipt.cancel(cancelled_by="maker1", reason="dibatalkan customer")
        assert cancelled.status == CashReceiptStatus.CANCELLED


class TestCashReceiptVerifyIsCurrentlyUnreachable:
    """KARAKTERISASI BUG (lihat catatan di header file). Test ini SENGAJA
    mengharapkan kegagalan -- kalau suatu saat test ini mulai FAIL karena
    verify() tiba-tiba berhasil, itu tandanya gap-nya sudah diperbaiki dan
    file test ini perlu ditulis ulang (bagus!), bukan berarti ada regresi."""

    def test_verify_after_submit_currently_raises(self):
        receipt = _draft_receipt().submit(submitted_by="maker1")
        with pytest.raises(ValueError, match="Cannot verify receipt in status submitted"):
            receipt.verify(verified_by="checker1")


class TestCashReceiptIllegalTransitions:
    def test_cannot_reject_a_draft_receipt_directly(self):
        receipt = _draft_receipt()
        with pytest.raises(ValueError, match="Cannot reject"):
            receipt.reject(rejected_by="checker1", reason="test")

    def test_cannot_confirm_a_draft_receipt_directly(self):
        receipt = _draft_receipt()
        with pytest.raises(ValueError, match="Cannot confirm"):
            receipt.confirm(confirmed_by="checker1")

    def test_cannot_cancel_an_already_cancelled_receipt(self):
        receipt = _draft_receipt().cancel(cancelled_by="x", reason="test")
        with pytest.raises(ValueError, match="Cannot cancel"):
            receipt.cancel(cancelled_by="x", reason="test lagi")
