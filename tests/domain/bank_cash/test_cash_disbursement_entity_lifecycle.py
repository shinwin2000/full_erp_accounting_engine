"""
tests/domain/bank_cash/test_cash_disbursement_entity_lifecycle.py
=====================================================================
Menutupi fungsi status-mutation ASLI di
domain/bank_cash/cash_disbursement_entity.py.

BUG YANG DITEMUKAN & DIPERBAIKI (lihat riwayat percakapan untuk detail):
`can_pay()` sebelumnya mensyaratkan status == READY_FOR_PAYMENT, padahal
`mark_processing()` sudah memindahkan status ke PROCESSING sebelum
`mark_paid()` dipanggil, dan tabel `CashDisbursementStatus.can_transition()`
(sumber kebenaran resmi) secara eksplisit menyatakan PROCESSING -> PAID
valid. Akibatnya `mark_paid()` SELALU gagal setelah `mark_processing()`
dipanggil -- disbursement tidak bisa pernah lunas. Sudah diperbaiki:
can_pay() sekarang mengecek status == PROCESSING.

OPEN QUESTION untuk Anto (BELUM diputuskan, sengaja tidak saya asumsikan):
------------------------------------------------------------------------
Tabel `can_transition()` juga menyatakan `APPROVED -> PARTIALLY_PAID` dan
`PARTIALLY_PAID -> PAID` sebagai transisi valid -- yang menyiratkan alur
pembayaran SEBAGIAN (cicilan) bisa terjadi LANGSUNG dari APPROVED, tanpa
lewat READY_FOR_PAYMENT/PROCESSING. Tapi method `mark_paid()` yang
sesungguhnya cuma bisa dipanggil dari status PROCESSING (via can_pay()),
dan kalau amount yang dibayar kurang dari total, `mark_paid()` akan
memindahkan status ke PARTIALLY_PAID dari PROCESSING -- padahal
PROCESSING -> PARTIALLY_PAID TIDAK ada di tabel resmi (cls.PROCESSING
cuma boleh ke {PAID, FAILED}).

Ini butuh keputusan bisnis: apakah pembayaran cicilan memang harus lewat
PROCESSING (dan tabel `can_transition()` yang perlu ditambah entry
PROCESSING -> PARTIALLY_PAID), atau apakah ada jalur cicilan terpisah yang
belum diimplementasikan? Test skenario pembayaran PENUH (full payment) di
bawah ini sudah 100% aman dan diverifikasi. Skenario PARTIAL payment
sengaja belum ditest sampai ada keputusan, supaya tidak salah
mendokumentasikan perilaku yang mungkin berubah.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.cash_disbursement_entity import (
    CashDisbursementEntity,
    CashDisbursementStatus,
    CashDisbursementType,
)


def _draft_disbursement(**overrides) -> CashDisbursementEntity:
    defaults = dict(
        disbursement_id=uuid4(), disbursement_number="CD-TEST-0001",
        disbursement_type=CashDisbursementType.SUPPLIER_PAYMENT,
        disbursement_date=datetime.now(UTC), amount=Decimal("1000000"), currency="IDR",
        status=CashDisbursementStatus.DRAFT, approval_level_required=1,
    )
    defaults.update(overrides)
    return CashDisbursementEntity(**defaults)


class TestCashDisbursementHappyPathLifecycle:
    def test_submit_with_approval_required_moves_to_pending_approval(self):
        d = _draft_disbursement(approval_level_required=1)
        submitted = d.submit(submitted_by="maker1")
        assert submitted.status == CashDisbursementStatus.PENDING_APPROVAL

    def test_submit_without_approval_required_is_actually_unreachable(self):
        """CATATAN TEMUAN MINOR: submit() punya cabang
        `else: CashDisbursementStatus.APPROVED` untuk kasus
        approval_level_required <= 0, TAPI _validate() mewajibkan
        approval_level_required in (1,2,3,4,5) -- jadi cabang itu dead code,
        tidak pernah bisa tereksekusi lewat constructor publik manapun.
        Bukan bug yang berbahaya (tidak ada jalur produksi yang salah),
        tapi worth dibersihkan supaya kode tidak menyesatkan pembaca."""
        with pytest.raises(ValueError, match="Invalid approval level required"):
            _draft_disbursement(approval_level_required=0)

    def test_approve_at_required_level_moves_to_approved(self):
        d = _draft_disbursement(approval_level_required=1).submit(submitted_by="maker1")
        approved = d.approve(level=1, approver_id=uuid4(), approver_name="checker1")
        assert approved.status == CashDisbursementStatus.APPROVED

    def test_mark_ready_for_payment_moves_approved_to_ready(self):
        d = (
            _draft_disbursement(approval_level_required=1)
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
        )
        ready = d.mark_ready_for_payment(marked_by="treasury1")
        assert ready.status == CashDisbursementStatus.READY_FOR_PAYMENT

    def test_mark_processing_moves_ready_to_processing(self):
        d = (
            _draft_disbursement(approval_level_required=1)
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
            .mark_ready_for_payment(marked_by="treasury1")
        )
        processing = d.mark_processing(processed_by="treasury1")
        assert processing.status == CashDisbursementStatus.PROCESSING

    def test_mark_paid_full_amount_moves_processing_to_paid(self):
        """Regression test untuk bug can_pay() yang sudah diperbaiki:
        sebelum fix ini SELALU raise ValueError di sini."""
        d = (
            _draft_disbursement(approval_level_required=1, amount=Decimal("1000000"))
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
            .mark_ready_for_payment(marked_by="treasury1")
            .mark_processing(processed_by="treasury1")
        )
        paid = d.mark_paid(paid_by="payer1")
        assert paid.status == CashDisbursementStatus.PAID
        assert paid.paid_amount == Decimal("1000000.00")
        assert paid.is_fully_paid()


class TestCashDisbursementRejectionAndFailurePaths:
    def test_reject_moves_pending_approval_to_rejected(self):
        d = _draft_disbursement(approval_level_required=1).submit(submitted_by="maker1")
        rejected = d.reject(rejected_by="checker1", reason="dokumen tidak lengkap")
        assert rejected.status == CashDisbursementStatus.REJECTED

    def test_hold_moves_pending_approval_to_on_hold(self):
        d = _draft_disbursement(approval_level_required=1).submit(submitted_by="maker1")
        held = d.hold(held_by="checker1", reason="menunggu verifikasi vendor")
        assert held.status == CashDisbursementStatus.ON_HOLD

    def test_release_hold_moves_on_hold_to_pending_approval(self):
        d = (
            _draft_disbursement(approval_level_required=1)
            .submit(submitted_by="maker1")
            .hold(held_by="checker1", reason="cek dulu")
        )
        released = d.release_hold(released_by="checker1")
        assert released.status == CashDisbursementStatus.PENDING_APPROVAL

    def test_mark_failed_moves_processing_to_failed(self):
        d = (
            _draft_disbursement(approval_level_required=1)
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
            .mark_ready_for_payment(marked_by="treasury1")
            .mark_processing(processed_by="treasury1")
        )
        failed = d.mark_failed(failed_by="treasury1", reason="saldo bank tidak cukup", failure_code="INSUFFICIENT_FUNDS")
        assert failed.status == CashDisbursementStatus.FAILED

    def test_cancel_moves_draft_to_cancelled(self):
        d = _draft_disbursement()
        cancelled = d.cancel(cancelled_by="maker1", reason="dibatalkan")
        assert cancelled.status == CashDisbursementStatus.CANCELLED


class TestCashDisbursementIllegalTransitions:
    def test_cannot_approve_a_draft_disbursement_directly(self):
        d = _draft_disbursement(approval_level_required=1)
        with pytest.raises(ValueError, match="Cannot approve"):
            d.approve(level=1, approver_id=uuid4(), approver_name="checker1")

    def test_cannot_pay_a_disbursement_that_is_not_processing(self):
        d = (
            _draft_disbursement(approval_level_required=1)
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
        )
        with pytest.raises(ValueError, match="Cannot pay"):
            d.mark_paid(paid_by="payer1")

    def test_cannot_cancel_a_paid_disbursement(self):
        d = (
            _draft_disbursement(approval_level_required=1, amount=Decimal("1000000"))
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
            .mark_ready_for_payment(marked_by="treasury1")
            .mark_processing(processed_by="treasury1")
            .mark_paid(paid_by="payer1")
        )
        with pytest.raises(ValueError, match="Cannot cancel"):
            d.cancel(cancelled_by="x", reason="test")

    def test_cannot_pay_more_than_remaining_amount(self):
        d = (
            _draft_disbursement(approval_level_required=1, amount=Decimal("1000000"))
            .submit(submitted_by="maker1")
            .approve(level=1, approver_id=uuid4(), approver_name="checker1")
            .mark_ready_for_payment(marked_by="treasury1")
            .mark_processing(processed_by="treasury1")
        )
        with pytest.raises(ValueError, match="exceeds remaining"):
            d.mark_paid(paid_by="payer1", paid_amount=Decimal("9999999"))
