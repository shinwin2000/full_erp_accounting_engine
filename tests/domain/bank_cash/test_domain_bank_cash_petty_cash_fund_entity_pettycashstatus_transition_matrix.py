"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/petty_cash_fund_entity.py
Enum     : PettyCashStatus
Pemilik can_transition: PettyCashStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_petty_cash_fund_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.petty_cash_fund_entity import PettyCashStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(PettyCashStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[PettyCashStatus, PettyCashStatus], bool] = {
    (PettyCashStatus.ACTIVE, PettyCashStatus.ACTIVE): False,
    (PettyCashStatus.ACTIVE, PettyCashStatus.DEPLETED): True,
    (PettyCashStatus.ACTIVE, PettyCashStatus.SUSPENDED): True,
    (PettyCashStatus.ACTIVE, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.ACTIVE, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.ACTIVE, PettyCashStatus.FROZEN): True,
    (PettyCashStatus.ACTIVE, PettyCashStatus.UNDER_AUDIT): False,
    (PettyCashStatus.DEPLETED, PettyCashStatus.ACTIVE): True,
    (PettyCashStatus.DEPLETED, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.DEPLETED, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.DEPLETED, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.DEPLETED, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.DEPLETED, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.DEPLETED, PettyCashStatus.UNDER_AUDIT): False,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.ACTIVE): True,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.SUSPENDED, PettyCashStatus.UNDER_AUDIT): True,
    (PettyCashStatus.CLOSED, PettyCashStatus.ACTIVE): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.CLOSED): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.CLOSED, PettyCashStatus.UNDER_AUDIT): False,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.ACTIVE): True,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.PENDING_APPROVAL, PettyCashStatus.UNDER_AUDIT): False,
    (PettyCashStatus.FROZEN, PettyCashStatus.ACTIVE): True,
    (PettyCashStatus.FROZEN, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.FROZEN, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.FROZEN, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.FROZEN, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.FROZEN, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.FROZEN, PettyCashStatus.UNDER_AUDIT): False,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.ACTIVE): True,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.DEPLETED): False,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.SUSPENDED): False,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.CLOSED): True,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.PENDING_APPROVAL): False,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.FROZEN): False,
    (PettyCashStatus.UNDER_AUDIT, PettyCashStatus.UNDER_AUDIT): False,
}


def _call_domain_bank_cash_petty_cash_fund_entity(frm: PettyCashStatus, to: PettyCashStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return PettyCashStatus.can_transition(frm, to)


def test_domain_bank_cash_petty_cash_fund_entity_full_transition_matrix():
    """Menutupi SELURUH 49 pasangan (7 status x 7 status)
    dari state machine PettyCashStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_petty_cash_fund_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_petty_cash_fund_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[PettyCashStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_petty_cash_fund_entity, allowed_self_transitions)
