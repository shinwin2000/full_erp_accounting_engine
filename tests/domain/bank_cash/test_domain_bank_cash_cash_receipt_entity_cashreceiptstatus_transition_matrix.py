"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/cash_receipt_entity.py
Enum     : CashReceiptStatus
Pemilik can_transition: CashReceiptStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_cash_receipt_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.cash_receipt_entity import CashReceiptStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(CashReceiptStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[CashReceiptStatus, CashReceiptStatus], bool] = {
    (CashReceiptStatus.DRAFT, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.SUBMITTED): True,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.CANCELLED): True,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.DRAFT, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.CANCELLED): True,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.REJECTED): True,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.PENDING_VERIFICATION): True,
    (CashReceiptStatus.SUBMITTED, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.CANCELLED): True,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.CONFIRMED, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.CANCELLED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.CANCELLED, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.DRAFT): True,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.CANCELLED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.REJECTED, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.CONFIRMED): True,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.CANCELLED): True,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.PARTIALLY_CONFIRMED, CashReceiptStatus.VERIFIED): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.CONFIRMED): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.CANCELLED): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.REJECTED): True,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.PARTIALLY_CONFIRMED): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.PENDING_VERIFICATION, CashReceiptStatus.VERIFIED): True,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.DRAFT): False,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.SUBMITTED): False,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.CONFIRMED): True,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.CANCELLED): False,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.REJECTED): False,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.PARTIALLY_CONFIRMED): True,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.PENDING_VERIFICATION): False,
    (CashReceiptStatus.VERIFIED, CashReceiptStatus.VERIFIED): False,
}


def _call_domain_bank_cash_cash_receipt_entity(frm: CashReceiptStatus, to: CashReceiptStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return CashReceiptStatus.can_transition(frm, to)


def test_domain_bank_cash_cash_receipt_entity_full_transition_matrix():
    """Menutupi SELURUH 64 pasangan (8 status x 8 status)
    dari state machine CashReceiptStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_cash_receipt_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_cash_receipt_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[CashReceiptStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_cash_receipt_entity, allowed_self_transitions)
