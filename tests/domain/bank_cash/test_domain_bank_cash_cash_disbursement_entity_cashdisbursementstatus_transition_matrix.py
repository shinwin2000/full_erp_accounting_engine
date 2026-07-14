"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/cash_disbursement_entity.py
Enum     : CashDisbursementStatus
Pemilik can_transition: CashDisbursementStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_cash_disbursement_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.cash_disbursement_entity import CashDisbursementStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(CashDisbursementStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[CashDisbursementStatus, CashDisbursementStatus], bool] = {
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.SUBMITTED): True,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.DRAFT, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.PENDING_APPROVAL): True,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.REJECTED): True,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.SUBMITTED, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.APPROVED): True,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.REJECTED): True,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.ON_HOLD): True,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.PENDING_APPROVAL, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.PARTIALLY_PAID): True,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.READY_FOR_PAYMENT): True,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.APPROVED, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.DRAFT): True,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.REJECTED, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.PAID, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.CANCELLED, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.PAID): True,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.PARTIALLY_PAID, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.PENDING_APPROVAL): True,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.CANCELLED): True,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.ON_HOLD, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.ON_HOLD): True,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.PROCESSING): True,
    (CashDisbursementStatus.READY_FOR_PAYMENT, CashDisbursementStatus.FAILED): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.DRAFT): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.PAID): True,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.READY_FOR_PAYMENT): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.PROCESSING, CashDisbursementStatus.FAILED): True,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.DRAFT): True,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.SUBMITTED): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.PENDING_APPROVAL): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.APPROVED): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.REJECTED): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.PAID): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.CANCELLED): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.PARTIALLY_PAID): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.ON_HOLD): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.READY_FOR_PAYMENT): True,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.PROCESSING): False,
    (CashDisbursementStatus.FAILED, CashDisbursementStatus.FAILED): False,
}


def _call_domain_bank_cash_cash_disbursement_entity(frm: CashDisbursementStatus, to: CashDisbursementStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return CashDisbursementStatus.can_transition(frm, to)


def test_domain_bank_cash_cash_disbursement_entity_full_transition_matrix():
    """Menutupi SELURUH 144 pasangan (12 status x 12 status)
    dari state machine CashDisbursementStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_cash_disbursement_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_cash_disbursement_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[CashDisbursementStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_cash_disbursement_entity, allowed_self_transitions)
