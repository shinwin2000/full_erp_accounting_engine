"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/bank_cash/bank_transfer_entity.py
Enum     : TransferStatus
Pemilik can_transition: TransferStatus (enum_classmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_bank_cash_bank_transfer_entity --force
"""

from __future__ import annotations

import pytest

from domain.bank_cash.bank_transfer_entity import TransferStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(TransferStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[TransferStatus, TransferStatus], bool] = {
    (TransferStatus.DRAFT, TransferStatus.DRAFT): False,
    (TransferStatus.DRAFT, TransferStatus.SUBMITTED): True,
    (TransferStatus.DRAFT, TransferStatus.PENDING): False,
    (TransferStatus.DRAFT, TransferStatus.PROCESSING): False,
    (TransferStatus.DRAFT, TransferStatus.COMPLETED): False,
    (TransferStatus.DRAFT, TransferStatus.FAILED): False,
    (TransferStatus.DRAFT, TransferStatus.CANCELLED): True,
    (TransferStatus.DRAFT, TransferStatus.REJECTED): False,
    (TransferStatus.DRAFT, TransferStatus.REVERSED): False,
    (TransferStatus.SUBMITTED, TransferStatus.DRAFT): False,
    (TransferStatus.SUBMITTED, TransferStatus.SUBMITTED): False,
    (TransferStatus.SUBMITTED, TransferStatus.PENDING): True,
    (TransferStatus.SUBMITTED, TransferStatus.PROCESSING): False,
    (TransferStatus.SUBMITTED, TransferStatus.COMPLETED): False,
    (TransferStatus.SUBMITTED, TransferStatus.FAILED): False,
    (TransferStatus.SUBMITTED, TransferStatus.CANCELLED): True,
    (TransferStatus.SUBMITTED, TransferStatus.REJECTED): True,
    (TransferStatus.SUBMITTED, TransferStatus.REVERSED): False,
    (TransferStatus.PENDING, TransferStatus.DRAFT): False,
    (TransferStatus.PENDING, TransferStatus.SUBMITTED): False,
    (TransferStatus.PENDING, TransferStatus.PENDING): False,
    (TransferStatus.PENDING, TransferStatus.PROCESSING): True,
    (TransferStatus.PENDING, TransferStatus.COMPLETED): False,
    (TransferStatus.PENDING, TransferStatus.FAILED): True,
    (TransferStatus.PENDING, TransferStatus.CANCELLED): True,
    (TransferStatus.PENDING, TransferStatus.REJECTED): False,
    (TransferStatus.PENDING, TransferStatus.REVERSED): False,
    (TransferStatus.PROCESSING, TransferStatus.DRAFT): False,
    (TransferStatus.PROCESSING, TransferStatus.SUBMITTED): False,
    (TransferStatus.PROCESSING, TransferStatus.PENDING): False,
    (TransferStatus.PROCESSING, TransferStatus.PROCESSING): False,
    (TransferStatus.PROCESSING, TransferStatus.COMPLETED): True,
    (TransferStatus.PROCESSING, TransferStatus.FAILED): True,
    (TransferStatus.PROCESSING, TransferStatus.CANCELLED): False,
    (TransferStatus.PROCESSING, TransferStatus.REJECTED): False,
    (TransferStatus.PROCESSING, TransferStatus.REVERSED): False,
    (TransferStatus.COMPLETED, TransferStatus.DRAFT): False,
    (TransferStatus.COMPLETED, TransferStatus.SUBMITTED): False,
    (TransferStatus.COMPLETED, TransferStatus.PENDING): False,
    (TransferStatus.COMPLETED, TransferStatus.PROCESSING): False,
    (TransferStatus.COMPLETED, TransferStatus.COMPLETED): False,
    (TransferStatus.COMPLETED, TransferStatus.FAILED): False,
    (TransferStatus.COMPLETED, TransferStatus.CANCELLED): False,
    (TransferStatus.COMPLETED, TransferStatus.REJECTED): False,
    (TransferStatus.COMPLETED, TransferStatus.REVERSED): True,
    (TransferStatus.FAILED, TransferStatus.DRAFT): True,
    (TransferStatus.FAILED, TransferStatus.SUBMITTED): False,
    (TransferStatus.FAILED, TransferStatus.PENDING): False,
    (TransferStatus.FAILED, TransferStatus.PROCESSING): False,
    (TransferStatus.FAILED, TransferStatus.COMPLETED): False,
    (TransferStatus.FAILED, TransferStatus.FAILED): False,
    (TransferStatus.FAILED, TransferStatus.CANCELLED): False,
    (TransferStatus.FAILED, TransferStatus.REJECTED): False,
    (TransferStatus.FAILED, TransferStatus.REVERSED): False,
    (TransferStatus.CANCELLED, TransferStatus.DRAFT): False,
    (TransferStatus.CANCELLED, TransferStatus.SUBMITTED): False,
    (TransferStatus.CANCELLED, TransferStatus.PENDING): False,
    (TransferStatus.CANCELLED, TransferStatus.PROCESSING): False,
    (TransferStatus.CANCELLED, TransferStatus.COMPLETED): False,
    (TransferStatus.CANCELLED, TransferStatus.FAILED): False,
    (TransferStatus.CANCELLED, TransferStatus.CANCELLED): False,
    (TransferStatus.CANCELLED, TransferStatus.REJECTED): False,
    (TransferStatus.CANCELLED, TransferStatus.REVERSED): False,
    (TransferStatus.REJECTED, TransferStatus.DRAFT): True,
    (TransferStatus.REJECTED, TransferStatus.SUBMITTED): False,
    (TransferStatus.REJECTED, TransferStatus.PENDING): False,
    (TransferStatus.REJECTED, TransferStatus.PROCESSING): False,
    (TransferStatus.REJECTED, TransferStatus.COMPLETED): False,
    (TransferStatus.REJECTED, TransferStatus.FAILED): False,
    (TransferStatus.REJECTED, TransferStatus.CANCELLED): False,
    (TransferStatus.REJECTED, TransferStatus.REJECTED): False,
    (TransferStatus.REJECTED, TransferStatus.REVERSED): False,
    (TransferStatus.REVERSED, TransferStatus.DRAFT): False,
    (TransferStatus.REVERSED, TransferStatus.SUBMITTED): False,
    (TransferStatus.REVERSED, TransferStatus.PENDING): False,
    (TransferStatus.REVERSED, TransferStatus.PROCESSING): False,
    (TransferStatus.REVERSED, TransferStatus.COMPLETED): False,
    (TransferStatus.REVERSED, TransferStatus.FAILED): False,
    (TransferStatus.REVERSED, TransferStatus.CANCELLED): False,
    (TransferStatus.REVERSED, TransferStatus.REJECTED): False,
    (TransferStatus.REVERSED, TransferStatus.REVERSED): False,
}


def _call_domain_bank_cash_bank_transfer_entity(frm: TransferStatus, to: TransferStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return TransferStatus.can_transition(frm, to)


def test_domain_bank_cash_bank_transfer_entity_full_transition_matrix():
    """Menutupi SELURUH 81 pasangan (9 status x 9 status)
    dari state machine TransferStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_bank_cash_bank_transfer_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_bank_cash_bank_transfer_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[TransferStatus] = set()
    assert_no_self_transition([status], _call_domain_bank_cash_bank_transfer_entity, allowed_self_transitions)
