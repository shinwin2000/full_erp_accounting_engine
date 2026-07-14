"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/cash_book_entity.py
Enum     : CashBookStatus
Pemilik can_transition: CashBookStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_cash_book_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.cash_book_entity import CashBookStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(CashBookStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[CashBookStatus, CashBookStatus], bool] = {
    (CashBookStatus.ACTIVE, CashBookStatus.ACTIVE): False,
    (CashBookStatus.ACTIVE, CashBookStatus.CLOSED): True,
    (CashBookStatus.ACTIVE, CashBookStatus.ARCHIVED): False,
    (CashBookStatus.ACTIVE, CashBookStatus.FROZEN): True,
    (CashBookStatus.ACTIVE, CashBookStatus.SUSPENDED): True,
    (CashBookStatus.ACTIVE, CashBookStatus.PENDING_ACTIVATION): False,
    (CashBookStatus.CLOSED, CashBookStatus.ACTIVE): False,
    (CashBookStatus.CLOSED, CashBookStatus.CLOSED): False,
    (CashBookStatus.CLOSED, CashBookStatus.ARCHIVED): True,
    (CashBookStatus.CLOSED, CashBookStatus.FROZEN): False,
    (CashBookStatus.CLOSED, CashBookStatus.SUSPENDED): False,
    (CashBookStatus.CLOSED, CashBookStatus.PENDING_ACTIVATION): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.ACTIVE): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.CLOSED): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.ARCHIVED): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.FROZEN): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.SUSPENDED): False,
    (CashBookStatus.ARCHIVED, CashBookStatus.PENDING_ACTIVATION): False,
    (CashBookStatus.FROZEN, CashBookStatus.ACTIVE): True,
    (CashBookStatus.FROZEN, CashBookStatus.CLOSED): True,
    (CashBookStatus.FROZEN, CashBookStatus.ARCHIVED): False,
    (CashBookStatus.FROZEN, CashBookStatus.FROZEN): False,
    (CashBookStatus.FROZEN, CashBookStatus.SUSPENDED): False,
    (CashBookStatus.FROZEN, CashBookStatus.PENDING_ACTIVATION): False,
    (CashBookStatus.SUSPENDED, CashBookStatus.ACTIVE): True,
    (CashBookStatus.SUSPENDED, CashBookStatus.CLOSED): True,
    (CashBookStatus.SUSPENDED, CashBookStatus.ARCHIVED): False,
    (CashBookStatus.SUSPENDED, CashBookStatus.FROZEN): False,
    (CashBookStatus.SUSPENDED, CashBookStatus.SUSPENDED): False,
    (CashBookStatus.SUSPENDED, CashBookStatus.PENDING_ACTIVATION): False,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.ACTIVE): True,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.CLOSED): True,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.ARCHIVED): False,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.FROZEN): False,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.SUSPENDED): False,
    (CashBookStatus.PENDING_ACTIVATION, CashBookStatus.PENDING_ACTIVATION): False,
}


def _call_domain_bank_cash_cash_book_entity(frm: CashBookStatus, to: CashBookStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return CashBookStatus.can_transition(frm, to)


def test_domain_bank_cash_cash_book_entity_full_transition_matrix():
    """Menutupi SELURUH 36 pasangan (6 status x 6 status)
    dari state machine CashBookStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_cash_book_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_cash_book_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[CashBookStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_cash_book_entity, allowed_self_transitions)
