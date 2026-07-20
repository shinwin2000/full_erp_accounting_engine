"""
tests/domain/bank_cash/test_bank_transfer_entity_lifecycle.py
================================================================
Menutupi fungsi status-mutation ASLI di domain/bank_cash/bank_transfer_entity.py
(submit, approve, reject, process, complete, fail, cancel, reverse).

Berbeda dengan domain/journal/aggregate_root.py, entity ini TIDAK memakai
guard generik yang salah pasang -- setiap method punya predikat can_X()
sendiri yang konsisten dengan status yang disyaratkan. Diverifikasi manual
sebelum menulis test ini (lihat riwayat percakapan) -- tidak ditemukan bug
sejenis _ensure_editable di sini.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.bank_cash.bank_transfer_entity import (
    BankTransferEntity,
    TransferStatus,
    TransferType,
)


def _draft_transfer(**overrides) -> BankTransferEntity:
    defaults = dict(
        transfer_id=uuid4(), transfer_number="TRF-TEST-0001", transfer_type=TransferType.INTERNAL,
        from_account_id=uuid4(), from_account_number="1110000111",
        to_account_id=uuid4(), to_account_number="2220000222",
        to_bank_code=None, to_bank_name=None, to_account_name="Penerima Test",
        amount=Decimal("500000"), currency="IDR", transfer_date=date.today(), value_date=None,
        status=TransferStatus.DRAFT,
    )
    defaults.update(overrides)
    return BankTransferEntity(**defaults)


class TestBankTransferHappyPathLifecycle:
    def test_submit_moves_draft_to_submitted(self):
        transfer = _draft_transfer()
        submitted = transfer.submit(submitted_by=uuid4())
        assert submitted.status == TransferStatus.SUBMITTED
        assert submitted.submitted_at is not None
        # immutability: instance asli tidak berubah
        assert transfer.status == TransferStatus.DRAFT

    def test_approve_at_required_level_moves_to_pending(self):
        transfer = _draft_transfer(approval_level_required=1).submit(submitted_by=uuid4())
        approved = transfer.approve(level=1, approved_by=uuid4())
        assert approved.status == TransferStatus.PENDING
        assert approved.approved_by is not None

    def test_approve_below_required_level_keeps_status(self):
        """Kalau approval_level_required=2 dan baru approve level 1, status
        HARUS tetap belum PENDING (masih menunggu approval level berikutnya)."""
        transfer = _draft_transfer(approval_level_required=2).submit(submitted_by=uuid4())
        partially_approved = transfer.approve(level=1, approved_by=uuid4())
        assert partially_approved.status == TransferStatus.SUBMITTED
        assert partially_approved.current_approval_level == 1

    def test_process_moves_pending_to_processing(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
        )
        processing = transfer.process(processed_by=uuid4())
        assert processing.status == TransferStatus.PROCESSING

    def test_complete_moves_processing_to_completed(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
            .process(processed_by=uuid4())
        )
        completed = transfer.complete(completed_by=uuid4())
        assert completed.status == TransferStatus.COMPLETED
        assert completed.completed_at is not None

    def test_reverse_moves_completed_to_reversed(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
            .process(processed_by=uuid4())
            .complete(completed_by=uuid4())
        )
        reversed_transfer = transfer.reverse(reversed_by=uuid4(), reason="salah input nominal")
        assert reversed_transfer.status == TransferStatus.REVERSED
        assert reversed_transfer.reversal_transfer_id is not None


class TestBankTransferRejectionAndFailurePaths:
    def test_reject_moves_submitted_to_rejected(self):
        transfer = _draft_transfer().submit(submitted_by=uuid4())
        rejected = transfer.reject(rejected_by=uuid4(), reason="rekening tujuan tidak valid")
        assert rejected.status == TransferStatus.REJECTED
        assert rejected.rejection_reason == "rekening tujuan tidak valid"

    def test_fail_moves_processing_to_failed(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
            .process(processed_by=uuid4())
        )
        failed = transfer.fail(failed_by=uuid4(), reason="bank tujuan menolak", failure_code="BANK_REJECT")
        assert failed.status == TransferStatus.FAILED
        assert failed.failure_code == "BANK_REJECT"

    def test_cancel_moves_draft_to_cancelled(self):
        transfer = _draft_transfer()
        cancelled = transfer.cancel(cancelled_by=uuid4(), reason="dibatalkan oleh maker")
        assert cancelled.status == TransferStatus.CANCELLED


class TestBankTransferIllegalTransitions:
    def test_cannot_approve_a_draft_transfer_directly(self):
        transfer = _draft_transfer()
        with pytest.raises(ValueError, match="Cannot approve"):
            transfer.approve(level=1, approved_by=uuid4())

    def test_cannot_complete_a_transfer_that_is_not_processing(self):
        transfer = _draft_transfer().submit(submitted_by=uuid4())
        with pytest.raises(ValueError, match="Cannot complete"):
            transfer.complete(completed_by=uuid4())

    def test_cannot_reverse_a_transfer_that_is_not_completed(self):
        transfer = _draft_transfer().submit(submitted_by=uuid4())
        with pytest.raises(ValueError, match="Cannot reverse"):
            transfer.reverse(reversed_by=uuid4(), reason="test")

    def test_cannot_cancel_a_completed_transfer(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
            .process(processed_by=uuid4())
            .complete(completed_by=uuid4())
        )
        with pytest.raises(ValueError, match="Cannot cancel"):
            transfer.cancel(cancelled_by=uuid4(), reason="test")

    def test_cannot_reverse_twice(self):
        transfer = (
            _draft_transfer(approval_level_required=1)
            .submit(submitted_by=uuid4())
            .approve(level=1, approved_by=uuid4())
            .process(processed_by=uuid4())
            .complete(completed_by=uuid4())
            .reverse(reversed_by=uuid4(), reason="koreksi")
        )
        with pytest.raises(ValueError, match="Cannot reverse"):
            transfer.reverse(reversed_by=uuid4(), reason="reversal ganda")
