"""
tests/domain/consolidation/test_consolidation_group_lifecycle.py
====================================================================
Menutupi fungsi status-mutation ASLI di domain/consolidation/aggregate_root.py.

DUA BUG DITEMUKAN & DIPERBAIKI di ConsolidationGroup:

1. approve()/reject()/cancel() memanggil can_approve()/can_reject()/
   can_cancel() TANPA argumen role, padahal predikat itu butuh
   user_role dan defaultnya "user" -- yang TIDAK PERNAH cocok dengan role
   yang disyaratkan (finance_manager/admin/auditor). Akibatnya ketiga
   method itu SELALU gagal, untuk role apapun. Diperbaiki dengan
   menambahkan parameter approver_role yang diteruskan ke predikat.

2. approve() memanggil ConsolidationCompleted(...) tapi class itu tidak
   pernah di-import di file ini (ada di domain_events.py) -- NameError
   setiap kali approve() berhasil lolos guard. Diperbaiki dengan
   menambahkan import yang hilang.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

from domain.consolidation.aggregate_root import Company, ConsolidationGroup, ConsolidationStatus
from domain.legal_entity.company_entity import LegalEntityType
from domain.shared_value_objects.npwp_vo import NPWP


def _parent_company() -> Company:
    return Company(
        company_id=uuid4(), legal_entity_id=uuid4(), trade_name="Induk Corp Test",
        legal_name="PT Induk Corp Test", entity_type=LegalEntityType.LIMITED,
        npwp=NPWP("01.234.567.8-901.000"), address="Jl Sudirman", city="Jakarta",
        province="DKI Jakarta", postal_code="12345", country="Indonesia",
    )


def _in_progress_group(**overrides) -> ConsolidationGroup:
    g = ConsolidationGroup(
        group_id=uuid4(), group_code="CG-TEST-001", group_name="Grup Konsolidasi Test",
        parent=_parent_company(), period=date.today(),
    )
    g = g._copy()
    g.status = ConsolidationStatus.IN_PROGRESS
    for k, v in overrides.items():
        setattr(g, k, v)
    return g


class TestConsolidationHappyPathLifecycle:
    def test_approve_with_correct_role_moves_in_progress_to_completed(self):
        """Regression test untuk bug #1 -- sebelum fix ini SELALU raise
        walaupun role-nya benar."""
        g = _in_progress_group()
        approved = g.approve(approved_by="u1", approver_role="finance_manager")
        assert approved.status == ConsolidationStatus.COMPLETED

    def test_approve_registers_consolidation_completed_event(self):
        """Regression test untuk bug #2 -- sebelum fix ini NameError."""
        g = _in_progress_group()
        approved = g.approve(approved_by="u1", approver_role="admin")
        events = approved.get_events()
        assert len(events) >= 1
        assert type(events[-1]).__name__ == "ConsolidationCompleted"

    def test_reject_with_correct_role_moves_in_progress_to_draft(self):
        g = _in_progress_group()
        rejected = g.reject(rejected_by="u1", reason="eliminasi belum lengkap", approver_role="finance_manager")
        assert rejected.status == ConsolidationStatus.DRAFT

    def test_cancel_with_correct_role_moves_in_progress_to_cancelled(self):
        g = _in_progress_group()
        cancelled = g.cancel(cancelled_by="u1", reason="dibatalkan", approver_role="admin")
        assert cancelled.status == ConsolidationStatus.CANCELLED

    def test_reverse_moves_completed_to_reversed(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin")
        reversed_group = g.reverse(reversed_by="u1", reason="salah hitung NCI")
        assert reversed_group.status == ConsolidationStatus.REVERSED

    def test_archive_moves_completed_to_archived(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin")
        archived = g.archive(archived_by="u1")
        assert archived.status == ConsolidationStatus.ARCHIVED

    def test_unarchive_moves_archived_to_completed(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin").archive(archived_by="u1")
        unarchived = g.unarchive(unarchived_by="u1")
        assert unarchived.status == ConsolidationStatus.COMPLETED

    def test_close_moves_completed_to_archived(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin")
        closed = g.close(closed_by="u1")
        assert closed.status == ConsolidationStatus.ARCHIVED

    def test_reopen_moves_archived_to_in_progress(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin").archive(archived_by="u1")
        reopened = g.reopen(reopened_by="u1")
        assert reopened.status == ConsolidationStatus.IN_PROGRESS


class TestConsolidationRoleGatingRegression:
    """Regression khusus bug #1 -- pastikan role yang SALAH/tidak lengkap
    tetap ditolak (memastikan fix tidak membuka celah otorisasi baru)."""

    def test_approve_without_role_still_raises(self):
        g = _in_progress_group()
        with pytest.raises(ValueError, match="Cannot approve"):
            g.approve(approved_by="u1")  # default role "user" -- harus tetap ditolak

    def test_approve_with_wrong_role_raises(self):
        g = _in_progress_group()
        with pytest.raises(ValueError, match="Cannot approve"):
            g.approve(approved_by="u1", approver_role="staff")

    def test_cancel_without_admin_role_raises(self):
        g = _in_progress_group()
        with pytest.raises(ValueError, match="Cannot cancel"):
            g.cancel(cancelled_by="u1", reason="test", approver_role="finance_manager")


class TestConsolidationIllegalTransitions:
    def test_cannot_approve_a_draft_group(self):
        g = ConsolidationGroup(
            group_id=uuid4(), group_code="CG-TEST-002", group_name="Grup Draft",
            parent=_parent_company(), period=date.today(),
        )
        with pytest.raises(ValueError, match="Cannot approve"):
            g.approve(approved_by="u1", approver_role="admin")

    def test_cannot_reverse_a_non_completed_group(self):
        g = _in_progress_group()
        with pytest.raises(ValueError, match="Cannot reverse"):
            g.reverse(reversed_by="u1", reason="test")

    def test_cannot_archive_a_non_completed_group(self):
        g = _in_progress_group()
        with pytest.raises(ValueError, match="Only completed"):
            g.archive(archived_by="u1")

    def test_cannot_reopen_a_non_archived_group(self):
        g = _in_progress_group().approve(approved_by="u1", approver_role="admin")
        with pytest.raises(ValueError, match="Only archived"):
            g.reopen(reopened_by="u1")
