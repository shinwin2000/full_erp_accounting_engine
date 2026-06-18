#!/usr/bin/env python3

"""
Module: test_journal_aggregate.py

Layer: Tests / Unit / Domain

Responsibility:
    Unit tests untuk Journal aggregate root.
    Menguji pembuatan jurnal, posting, approval, reversal, dan invariants.

Dependencies:
    - domain/journal/aggregate_root.py
    - domain/journal/journal_entity.py
    - domain/journal/journal_line_vo.py
    - domain/journal/state_machine.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.aggregate_root import JournalAggregate
from domain.journal.domain_events import (
    JournalApproved,
    JournalCreated,
    JournalPosted,
    JournalReversed,
    JournalVoided,
)
from domain.journal.journal_entity import JournalEntry, JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLine
from domain.shared_value_objects.accounting_period_vo import AccountingPeriod
from domain.shared_value_objects.document_number_vo import DocumentNumber


class TestJournalAggregate:
    """Test suite untuk JournalAggregate."""

    @pytest.fixture
    def valid_journal_lines(self) -> list[JournalLine]:
        """Fixture lines jurnal yang balance."""
        return [
            JournalLine(
                account_id=uuid4(),
                account_code="1-1000",
                description="Debit kas",
                debit=Decimal("1000000"),
                credit=Decimal("0"),
                cost_center=None,
                department=None,
                tax_code=None,
                project_code=None,
                auxiliary_1=None,
                auxiliary_2=None,
            ),
            JournalLine(
                account_id=uuid4(),
                account_code="4-1000",
                description="Credit pendapatan",
                debit=Decimal("0"),
                credit=Decimal("1000000"),
                cost_center=None,
                department=None,
                tax_code=None,
                project_code=None,
                auxiliary_1=None,
                auxiliary_2=None,
            ),
        ]

    @pytest.fixture
    def valid_journal_entry(self, valid_journal_lines) -> JournalEntry:
        """Fixture jurnal entry valid."""
        return JournalEntry(
            id=uuid4(),
            legal_entity_id=uuid4(),
            journal_number=DocumentNumber("JNL-2025-00001"),
            journal_date=date.today(),
            period=AccountingPeriod(year=2025, month=3),
            description="Jurnal test",
            journal_type=JournalType.MANUAL,
            status=JournalStatus.DRAFT,
            lines=valid_journal_lines,
            created_by=uuid4(),
            created_at=datetime.utcnow(),
            total_debit=Decimal("1000000"),
            total_credit=Decimal("1000000"),
            source_system="test",
            reference_number=None,
            attachment_ids=[],
        )

    def test_create_journal_success(self, valid_journal_entry):
        """Test: Membuat jurnal baru berhasil."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        assert aggregate.journal.id == valid_journal_entry.id
        assert aggregate.journal.status == JournalStatus.DRAFT
        assert aggregate.version == 1
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], JournalCreated)
        assert events[0].journal_id == valid_journal_entry.id

    def test_post_journal_success(self, valid_journal_entry):
        """Test: Posting jurnal berhasil."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.clear_events()
        aggregate.post(user_id=uuid4())
        assert aggregate.journal.status == JournalStatus.POSTED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], JournalPosted)
        assert events[0].journal_id == aggregate.journal.id

    def test_cannot_post_already_posted_journal(self, valid_journal_entry):
        """Test: Tidak bisa posting jurnal yang sudah diposting."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.post(uuid4())
        with pytest.raises(ValueError, match="already posted"):
            aggregate.post(uuid4())

    def test_approve_journal_success(self, valid_journal_entry):
        """Test: Approve jurnal berhasil."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.post(uuid4())
        aggregate.clear_events()
        aggregate.approve(approver_id=uuid4())
        assert aggregate.journal.status == JournalStatus.APPROVED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], JournalApproved)

    def test_cannot_approve_draft_journal(self, valid_journal_entry):
        """Test: Tidak bisa approve jurnal yang masih draft."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        with pytest.raises(ValueError, match="DRAFT"):
            aggregate.approve(uuid4())

    def test_reverse_journal_success(self, valid_journal_entry):
        """Test: Reversal jurnal berhasil."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.post(uuid4())
        aggregate.clear_events()
        reversal_id = uuid4()
        aggregate.mark_reversed(reversal_id, user_id=uuid4())
        assert aggregate.journal.is_reversed is True
        assert aggregate.journal.reversal_journal_id == reversal_id
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], JournalReversed)

    def test_void_journal_success(self, valid_journal_entry):
        """Test: Membatalkan jurnal (void) berhasil."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.clear_events()
        aggregate.void(reason="Test void", user_id=uuid4())
        assert aggregate.journal.status == JournalStatus.VOIDED
        events = aggregate.get_events()
        assert len(events) == 1
        assert isinstance(events[0], JournalVoided)

    def test_cannot_void_posted_journal(self, valid_journal_entry):
        """Test: Tidak bisa void jurnal yang sudah diposting (harus reversal)."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.post(uuid4())
        with pytest.raises(ValueError, match="cannot void a posted journal"):
            aggregate.void("Alasan", uuid4())

    def test_version_increment_on_state_change(self, valid_journal_entry):
        """Test: Version increment setiap perubahan status."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        assert aggregate.version == 1
        aggregate.post(uuid4())
        assert aggregate.version == 2
        aggregate.approve(uuid4())
        assert aggregate.version == 3

    def test_state_machine_transitions(self, valid_journal_entry):
        """Test: State machine transitions."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        # DRAFT -> POSTED
        aggregate.post(uuid4())
        assert aggregate.journal.status == JournalStatus.POSTED
        # POSTED -> APPROVED
        aggregate.approve(uuid4())
        assert aggregate.journal.status == JournalStatus.APPROVED

    def test_cannot_make_invalid_transition(self, valid_journal_entry):
        """Test: Transisi state tidak valid harus ditolak."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        # DRAFT tidak bisa langsung APPROVED
        with pytest.raises(ValueError):
            aggregate.approve(uuid4())

    def test_reconstruct_from_events(self, valid_journal_entry):
        """Test: Rekonstruksi aggregate dari event stream."""
        aggregate = JournalAggregate.create(valid_journal_entry, user_id=uuid4())
        aggregate.post(uuid4())
        events = aggregate.get_events()
        # Simulasi replay
        new_agg = JournalAggregate.reconstruct(events)
        assert new_agg.journal.id == aggregate.journal.id
        assert new_agg.journal.status == JournalStatus.POSTED
        assert new_agg.version == aggregate.version
        assert new_agg.get_events() == []

    def test_total_debit_credit_must_balance(self, valid_journal_entry):
        """Test: Invariant total debit harus sama dengan total credit."""
        # Sudah balance di fixture
        assert valid_journal_entry.total_debit == valid_journal_entry.total_credit
        # Buat entry tidak balance
        with pytest.raises(ValueError, match="not balanced"):
            invalid_lines = valid_journal_entry.lines.copy()
            invalid_lines[0].debit = Decimal("2000000")
            JournalEntry(
                id=uuid4(),
                legal_entity_id=uuid4(),
                journal_number=DocumentNumber("JNL-2025-00002"),
                journal_date=date.today(),
                period=AccountingPeriod(year=2025, month=3),
                description="Jurnal tidak balance",
                journal_type=JournalType.MANUAL,
                status=JournalStatus.DRAFT,
                lines=invalid_lines,
                created_by=uuid4(),
                created_at=datetime.utcnow(),
                total_debit=Decimal("2000000"),
                total_credit=Decimal("1000000"),
                source_system="test",
                reference_number=None,
                attachment_ids=[],
            )


if __name__ == "__main__":
    pytest.main([__file__])
