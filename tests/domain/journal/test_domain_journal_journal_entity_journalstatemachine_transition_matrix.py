"""
AUTO-GENERATED oleh tools/generate_state_transition_tests.py — JANGAN edit
manual kecuali Anda tahu konsekuensinya (lihat header file generator untuk
alasan kenapa test ini di-snapshot, bukan dihitung ulang secara dinamis).

Sumber   : domain/journal/journal_entity.py
Enum     : JournalStatus
Pemilik can_transition: JournalStateMachine (external_staticmethod)

Regenerate setelah mengubah aturan transisi di source:
    python tools/generate_state_transition_tests.py --only domain_journal_journal_entity --force
"""

from __future__ import annotations

import pytest

from domain.journal.journal_entity import JournalStateMachine, JournalStatus
from tests._helpers.state_machine_kit import (
    assert_no_self_transition,
    assert_transition_matrix,
)

_ALL_STATUSES = list(JournalStatus)

# Snapshot matriks transisi yang di-generate dari eksekusi kode ASLI pada saat
# generate dijalankan. True = transisi diperbolehkan, False = tidak.
_EXPECTED_MATRIX: dict[tuple[JournalStatus, JournalStatus], bool] = {
    (JournalStatus.DRAFT, JournalStatus.DRAFT): False,
    (JournalStatus.DRAFT, JournalStatus.SUBMITTED): True,
    (JournalStatus.DRAFT, JournalStatus.APPROVED): False,
    (JournalStatus.DRAFT, JournalStatus.REJECTED): False,
    (JournalStatus.DRAFT, JournalStatus.POSTED): False,
    (JournalStatus.DRAFT, JournalStatus.REVERSED): False,
    (JournalStatus.DRAFT, JournalStatus.ARCHIVED): True,
    (JournalStatus.DRAFT, JournalStatus.CANCELLED): True,
    (JournalStatus.SUBMITTED, JournalStatus.DRAFT): True,
    (JournalStatus.SUBMITTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.SUBMITTED, JournalStatus.APPROVED): True,
    (JournalStatus.SUBMITTED, JournalStatus.REJECTED): True,
    (JournalStatus.SUBMITTED, JournalStatus.POSTED): False,
    (JournalStatus.SUBMITTED, JournalStatus.REVERSED): False,
    (JournalStatus.SUBMITTED, JournalStatus.ARCHIVED): False,
    (JournalStatus.SUBMITTED, JournalStatus.CANCELLED): True,
    (JournalStatus.APPROVED, JournalStatus.DRAFT): True,
    (JournalStatus.APPROVED, JournalStatus.SUBMITTED): False,
    (JournalStatus.APPROVED, JournalStatus.APPROVED): False,
    (JournalStatus.APPROVED, JournalStatus.REJECTED): True,
    (JournalStatus.APPROVED, JournalStatus.POSTED): True,
    (JournalStatus.APPROVED, JournalStatus.REVERSED): False,
    (JournalStatus.APPROVED, JournalStatus.ARCHIVED): False,
    (JournalStatus.APPROVED, JournalStatus.CANCELLED): False,
    (JournalStatus.REJECTED, JournalStatus.DRAFT): True,
    (JournalStatus.REJECTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.REJECTED, JournalStatus.APPROVED): False,
    (JournalStatus.REJECTED, JournalStatus.REJECTED): False,
    (JournalStatus.REJECTED, JournalStatus.POSTED): False,
    (JournalStatus.REJECTED, JournalStatus.REVERSED): False,
    (JournalStatus.REJECTED, JournalStatus.ARCHIVED): True,
    (JournalStatus.REJECTED, JournalStatus.CANCELLED): False,
    (JournalStatus.POSTED, JournalStatus.DRAFT): False,
    (JournalStatus.POSTED, JournalStatus.SUBMITTED): False,
    (JournalStatus.POSTED, JournalStatus.APPROVED): False,
    (JournalStatus.POSTED, JournalStatus.REJECTED): False,
    (JournalStatus.POSTED, JournalStatus.POSTED): False,
    (JournalStatus.POSTED, JournalStatus.REVERSED): True,
    (JournalStatus.POSTED, JournalStatus.ARCHIVED): True,
    (JournalStatus.POSTED, JournalStatus.CANCELLED): False,
    (JournalStatus.REVERSED, JournalStatus.DRAFT): False,
    (JournalStatus.REVERSED, JournalStatus.SUBMITTED): False,
    (JournalStatus.REVERSED, JournalStatus.APPROVED): False,
    (JournalStatus.REVERSED, JournalStatus.REJECTED): False,
    (JournalStatus.REVERSED, JournalStatus.POSTED): False,
    (JournalStatus.REVERSED, JournalStatus.REVERSED): False,
    (JournalStatus.REVERSED, JournalStatus.ARCHIVED): True,
    (JournalStatus.REVERSED, JournalStatus.CANCELLED): False,
    (JournalStatus.ARCHIVED, JournalStatus.DRAFT): False,
    (JournalStatus.ARCHIVED, JournalStatus.SUBMITTED): False,
    (JournalStatus.ARCHIVED, JournalStatus.APPROVED): False,
    (JournalStatus.ARCHIVED, JournalStatus.REJECTED): True,
    (JournalStatus.ARCHIVED, JournalStatus.POSTED): True,
    (JournalStatus.ARCHIVED, JournalStatus.REVERSED): False,
    (JournalStatus.ARCHIVED, JournalStatus.ARCHIVED): False,
    (JournalStatus.ARCHIVED, JournalStatus.CANCELLED): False,
    (JournalStatus.CANCELLED, JournalStatus.DRAFT): False,
    (JournalStatus.CANCELLED, JournalStatus.SUBMITTED): False,
    (JournalStatus.CANCELLED, JournalStatus.APPROVED): False,
    (JournalStatus.CANCELLED, JournalStatus.REJECTED): False,
    (JournalStatus.CANCELLED, JournalStatus.POSTED): False,
    (JournalStatus.CANCELLED, JournalStatus.REVERSED): False,
    (JournalStatus.CANCELLED, JournalStatus.ARCHIVED): False,
    (JournalStatus.CANCELLED, JournalStatus.CANCELLED): False,
}


def _call_domain_journal_journal_entity(frm: JournalStatus, to: JournalStatus) -> bool:
    """Wrapper tipis ke pemanggilan asli, supaya kit generik bisa dipakai."""
    return JournalStateMachine.can_transition(frm, to)


def test_domain_journal_journal_entity_full_transition_matrix():
    """Menutupi SELURUH 64 pasangan (8 status x 8 status)
    dari state machine JournalStatus, termasuk semua jalur invalid
    (negative path)."""
    assert_transition_matrix(_EXPECTED_MATRIX, _call_domain_journal_journal_entity)


@pytest.mark.parametrize("status", _ALL_STATUSES, ids=lambda s: s.name)
def test_domain_journal_journal_entity_no_self_transition(status):
    """Invariant umum: status tidak boleh 'bertransisi' ke dirinya sendiri.
    Kalau ada status yang MEMANG boleh (mis. DRAFT -> DRAFT untuk auto-save),
    tambahkan ke allowed_self_transitions di bawah dan jelaskan alasannya."""
    allowed_self_transitions: set[JournalStatus] = set()
    assert_no_self_transition([status], _call_domain_journal_journal_entity, allowed_self_transitions)
