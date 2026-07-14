"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/bank_account_entity.py
Enum     : BankAccountStatus
Pemilik can_transition: BankAccountStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_bank_account_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.bank_account_entity import BankAccountStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(BankAccountStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[BankAccountStatus, BankAccountStatus], bool] = {
    (BankAccountStatus.ACTIVE, BankAccountStatus.ACTIVE): False,
    (BankAccountStatus.ACTIVE, BankAccountStatus.INACTIVE): True,
    (BankAccountStatus.ACTIVE, BankAccountStatus.BLOCKED): True,
    (BankAccountStatus.ACTIVE, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.ACTIVE, BankAccountStatus.DORMANT): True,
    (BankAccountStatus.ACTIVE, BankAccountStatus.FROZEN): True,
    (BankAccountStatus.ACTIVE, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.ACTIVE, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.INACTIVE, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.INACTIVE, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.INACTIVE, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.BLOCKED, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.BLOCKED, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.BLOCKED, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.ACTIVE): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.CLOSED): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.CLOSED, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.DORMANT, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.DORMANT, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.DORMANT, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.FROZEN, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.CLOSED): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.FROZEN, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.BLOCKED): True,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.PENDING_VERIFICATION, BankAccountStatus.SUSPENDED): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.ACTIVE): True,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.INACTIVE): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.BLOCKED): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.CLOSED): True,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.DORMANT): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.FROZEN): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.PENDING_VERIFICATION): False,
    (BankAccountStatus.SUSPENDED, BankAccountStatus.SUSPENDED): False,
}


def _call_domain_bank_cash_bank_account_entity(frm: BankAccountStatus, to: BankAccountStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return BankAccountStatus.can_transition(frm, to)


def test_domain_bank_cash_bank_account_entity_full_transition_matrix():
    """Menutupi SELURUH 64 pasangan (8 status x 8 status)
    dari state machine BankAccountStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_bank_account_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_bank_account_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[BankAccountStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_bank_account_entity, allowed_self_transitions)
