#!/usr/bin/env python3
"""
tests/unit/test_double_entry.py
Test untuk axioms/double_entry.py
Mencakup: JournalLine, JournalEntry, DoubleEntryVerificationRecord,
DoubleEntryAxiom, DoubleEntryValidator, helper functions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from axioms.double_entry import (
    DoubleEntryAxiom,
    DoubleEntryValidator,
    DoubleEntryVerificationRecord,
    DoubleEntryViolationError,
    DoubleEntryViolationSeverity,
    InvalidJournalEntryError,
    JournalEntry,
    JournalLine,
    JournalStatus,
    JournalType,
    Side,
    create_credit_line,
    create_debit_line,
    create_journal_line,
    create_journal_line_dict,
    get_double_entry_axiom,
)


# ============================================================================
# Helper Functions
# ============================================================================

def create_test_line(
    journal_id: uuid.UUID | None = None,
    side: Side = Side.DEBIT,
    amount: Decimal = Decimal("100"),
    account_code: str = "1100",
    currency: str = "IDR",
) -> JournalLine:
    if journal_id is None:
        journal_id = uuid.uuid4()
    return JournalLine(
        line_id=uuid.uuid4(),
        journal_id=journal_id,
        account_code=account_code,
        side=side,
        amount=amount,
        currency=currency,
        description="Test line",
        legal_entity_id=uuid.uuid4(),
        cost_center="CC001",
        department="DEPT01",
        project_id=uuid.uuid4(),
        reference="REF001",
    )


def create_test_journal(
    lines: list[JournalLine] | None = None,
    journal_type: JournalType = JournalType.GENERAL,
    status: JournalStatus = JournalStatus.DRAFT,
) -> JournalEntry:
    if lines is None:
        debit_line = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit_line = create_test_line(side=Side.CREDIT, amount=Decimal("1000"))
        lines = [debit_line, credit_line]
        # Ensure lines share same journal_id
        journal_id = uuid.uuid4()
        for line in lines:
            object.__setattr__(line, "journal_id", journal_id)
    else:
        journal_id = lines[0].journal_id
    return JournalEntry(
        journal_id=journal_id,
        journal_number="JRN-202601-000001",
        journal_type=journal_type,
        transaction_date=datetime.now(UTC),
        posting_date=None,
        description="Test journal",
        lines=lines,
        created_by="tester",
        created_at=datetime.now(UTC),
        approved_by=[],
        status=status,
        reference_id=None,
        reversal_of=None,
        reversal_journal_id=None,
    )


def create_test_record(is_balanced: bool = True) -> DoubleEntryVerificationRecord:
    return DoubleEntryVerificationRecord(
        record_id=uuid.uuid4(),
        journal_id=uuid.uuid4(),
        verified_at=datetime.now(UTC),
        verified_by="tester",
        is_balanced=is_balanced,
        total_debit=Decimal("1000"),
        total_credit=Decimal("1000"),
        difference=Decimal("0"),
        tolerance=Decimal("0.0001"),
        severity=DoubleEntryViolationSeverity.INFO,
        violation_message=None,
        journal_type="GENERAL",
        auto_corrected=False,
        auto_correction_applied=None,
        cryptographic_hash="",
    )


# ============================================================================
# Tests for JournalLine
# ============================================================================

class TestJournalLine:
    def test_create_valid_line(self):
        line = create_test_line()
        assert line.line_id is not None
        assert line.journal_id is not None
        assert line.account_code == "1100"
        assert line.side == Side.DEBIT
        assert line.amount == Decimal("100")
        assert line.currency == "IDR"
        assert line.version == 1
        assert line.cryptographic_hash != ""

    def test_validate_amount_positive(self):
        with pytest.raises(InvalidJournalEntryError, match="Amount must be positive"):
            create_test_line(amount=Decimal("-100"))

    def test_validate_account_code_required(self):
        with pytest.raises(InvalidJournalEntryError, match="Account code required"):
            JournalLine(
                line_id=uuid.uuid4(),
                journal_id=uuid.uuid4(),
                account_code="",
                side=Side.DEBIT,
                amount=Decimal("100"),
                currency="IDR",
                description="test",
                legal_entity_id=uuid.uuid4(),
            )

    def test_validate_currency_length(self):
        with pytest.raises(InvalidJournalEntryError, match="Invalid currency"):
            JournalLine(
                line_id=uuid.uuid4(),
                journal_id=uuid.uuid4(),
                account_code="1100",
                side=Side.DEBIT,
                amount=Decimal("100"),
                currency="XX",
                description="test",
                legal_entity_id=uuid.uuid4(),
            )

    def test_private_validate_called(self):
        line = create_test_line()
        result = line.validate()
        assert result["is_valid"] is True
        assert result["line_id"] == str(line.line_id)

    def test_private_ensure_hash_called(self):
        line = create_test_line()
        assert line.cryptographic_hash != ""

    def test_private_take_snapshot_called(self):
        line = create_test_line()
        assert len(line._snapshots) == 1

    def test_private_record_audit_called(self):
        line = create_test_line()
        assert len(line._audit_trail) == 1

    def test_private_copy_called(self):
        line = create_test_line()
        updated = line.update("admin", amount=Decimal("200"))
        assert updated.amount == Decimal("200")

    def test_compute_hash_consistent(self):
        l1 = create_test_line()
        l2 = JournalLine(
            line_id=l1.line_id,
            journal_id=l1.journal_id,
            account_code=l1.account_code,
            side=l1.side,
            amount=l1.amount,
            currency=l1.currency,
            description=l1.description,
            legal_entity_id=l1.legal_entity_id,
            cost_center=l1.cost_center,
            department=l1.department,
            project_id=l1.project_id,
            reference=l1.reference,
        )
        assert l1.compute_hash() == l2.compute_hash()

    def test_update_creates_new_version(self):
        line = create_test_line()
        updated = line.update("admin", amount=Decimal("200"))
        assert updated.amount == Decimal("200")
        assert updated.version == line.version + 1

    def test_update_cannot_change_line_id_and_journal_id(self):
        line = create_test_line()
        original_id = line.line_id
        original_journal = line.journal_id
        updated = line.update("admin", amount=Decimal("200"))
        assert updated.line_id == original_id
        assert updated.journal_id == original_journal

    def test_delete_marks_deleted(self):
        line = create_test_line()
        deleted = line.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == line.version + 1

    def test_restore_recovers_deleted(self):
        line = create_test_line()
        deleted = line.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None

    def test_restore_not_deleted_raises(self):
        line = create_test_line()
        with pytest.raises(ValueError, match="Line not deleted"):
            line.restore("admin")

    def test_activate_returns_self(self):
        line = create_test_line()
        activated = line.activate("admin")
        assert activated is line

    def test_deactivate_returns_self(self):
        line = create_test_line()
        deactivated = line.deactivate("admin")
        assert deactivated is line

    def test_lock_returns_self(self):
        line = create_test_line()
        locked = line.lock("admin", "test")
        assert locked is line

    def test_unlock_returns_self(self):
        line = create_test_line()
        unlocked = line.unlock("admin")
        assert unlocked is line

    def test_create_returns_self(self):
        line = create_test_line()
        result = line.create("admin")
        assert result is line

    def test_validate_errors_on_hash_mismatch(self):
        line = create_test_line()
        object.__setattr__(line, "cryptographic_hash", "fake")
        result = line.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        line = create_test_line()
        d = line.to_dict()
        assert d["account_code"] == "1100"
        assert d["side"] == "debit"
        assert d["amount"] == "100"
        assert d["currency"] == "IDR"

    def test_from_dict_reconstructs(self):
        line = create_test_line()
        d = line.to_dict()
        reconstructed = JournalLine.from_dict(d)
        assert reconstructed.line_id == line.line_id
        assert reconstructed.journal_id == line.journal_id
        assert reconstructed.account_code == line.account_code
        assert reconstructed.side == line.side
        assert reconstructed.amount == line.amount

    def test_clone_creates_new_id(self):
        line = create_test_line()
        cloned = line.clone()
        assert cloned.line_id != line.line_id
        assert cloned.journal_id == line.journal_id
        assert cloned.account_code == line.account_code
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        line = create_test_line()
        snap = line.snapshot()
        assert snap["line_id"] == str(line.line_id)
        assert snap["amount"] == str(line.amount)

    def test_get_version(self):
        line = create_test_line()
        assert line.get_version() == 1

    def test_audit_trail_records(self):
        line = create_test_line()
        assert len(line.audit_trail()) >= 1
        line.touch("toucher")
        trail = line.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        line = create_test_line()
        touched = line.touch("toucher")
        assert touched.version == line.version + 1


# ============================================================================
# Tests for JournalEntry
# ============================================================================

class TestJournalEntry:
    def test_create_valid_journal(self):
        journal = create_test_journal()
        assert journal.journal_id is not None
        assert journal.journal_number == "JRN-202601-000001"
        assert journal.journal_type == JournalType.GENERAL
        assert journal.status == JournalStatus.DRAFT
        assert len(journal.lines) == 2
        assert journal.version == 1
        assert journal.cryptographic_hash != ""

    def test_validate_at_least_one_line(self):
        with pytest.raises(InvalidJournalEntryError, match="at least one line"):
            JournalEntry(
                journal_id=uuid.uuid4(),
                journal_number="JRN-001",
                journal_type=JournalType.GENERAL,
                transaction_date=datetime.now(UTC),
                posting_date=None,
                description="test",
                lines=[],
                created_by="tester",
                created_at=datetime.now(UTC),
                approved_by=[],
                status=JournalStatus.DRAFT,
            )

    def test_validate_line_journal_id_mismatch(self):
        line = create_test_line(journal_id=uuid.uuid4())
        with pytest.raises(InvalidJournalEntryError, match="mismatched journal_id"):
            JournalEntry(
                journal_id=uuid.uuid4(),
                journal_number="JRN-001",
                journal_type=JournalType.GENERAL,
                transaction_date=datetime.now(UTC),
                posting_date=None,
                description="test",
                lines=[line],
                created_by="tester",
                created_at=datetime.now(UTC),
                approved_by=[],
                status=JournalStatus.DRAFT,
            )

    def test_total_debit_and_credit(self):
        journal = create_test_journal()
        assert journal.total_debit == Decimal("1000")
        assert journal.total_credit == Decimal("1000")
        assert journal.difference == Decimal("0")

    def test_is_balanced_true(self):
        journal = create_test_journal()
        assert journal.is_balanced() is True

    def test_is_balanced_false(self):
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("800"))
        journal = create_test_journal(lines=[debit, credit])
        assert journal.is_balanced() is False

    def test_is_posted(self):
        journal = create_test_journal(status=JournalStatus.POSTED)
        assert journal.is_posted() is True
        journal = create_test_journal(status=JournalStatus.DRAFT)
        assert journal.is_posted() is False

    def test_is_mutable(self):
        journal = create_test_journal(status=JournalStatus.DRAFT)
        assert journal.is_mutable() is True
        journal = create_test_journal(status=JournalStatus.SUBMITTED)
        assert journal.is_mutable() is True
        journal = create_test_journal(status=JournalStatus.APPROVED)
        assert journal.is_mutable() is False
        journal = create_test_journal(status=JournalStatus.POSTED)
        assert journal.is_mutable() is False

    def test_update_works_in_mutable_state(self):
        journal = create_test_journal()
        updated = journal.update("admin", description="Updated description")
        assert updated.description == "Updated description"
        assert updated.version == journal.version + 1

    def test_update_fails_in_immutable_state(self):
        journal = create_test_journal(status=JournalStatus.POSTED)
        with pytest.raises(ValueError, match="Cannot update"):
            journal.update("admin", description="Should fail")

    def test_delete_works_in_mutable_state(self):
        journal = create_test_journal()
        deleted = journal.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"

    def test_delete_fails_in_immutable_state(self):
        journal = create_test_journal(status=JournalStatus.POSTED)
        with pytest.raises(ValueError, match="Cannot delete"):
            journal.delete("admin", "test")

    def test_restore_recovers_deleted(self):
        journal = create_test_journal()
        deleted = journal.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None

    def test_restore_not_deleted_raises(self):
        journal = create_test_journal()
        with pytest.raises(ValueError, match="Journal not deleted"):
            journal.restore("admin")

    def test_activate_moves_from_draft_to_submitted(self):
        journal = create_test_journal()
        activated = journal.activate("admin")
        assert activated.status == JournalStatus.SUBMITTED
        assert activated.version == journal.version + 1

    def test_activate_fails_if_not_draft(self):
        journal = create_test_journal(status=JournalStatus.SUBMITTED)
        with pytest.raises(ValueError, match="Cannot activate"):
            journal.activate("admin")

    def test_deactivate_moves_from_submitted_to_draft(self):
        journal = create_test_journal()
        submitted = journal.activate("admin")
        deactivated = submitted.deactivate("admin", "test")
        assert deactivated.status == JournalStatus.DRAFT

    def test_deactivate_fails_if_not_submitted(self):
        journal = create_test_journal(status=JournalStatus.DRAFT)
        with pytest.raises(ValueError, match="Cannot deactivate"):
            journal.deactivate("admin")

    def test_lock_returns_self(self):
        journal = create_test_journal()
        locked = journal.lock("admin", "test")
        assert locked is journal

    def test_unlock_returns_self(self):
        journal = create_test_journal()
        unlocked = journal.unlock("admin")
        assert unlocked is journal

    def test_validate_returns_valid(self):
        journal = create_test_journal()
        result = journal.validate()
        assert result["is_valid"] is True
        assert result["journal_id"] == str(journal.journal_id)

    def test_validate_errors_on_hash_mismatch(self):
        journal = create_test_journal()
        object.__setattr__(journal, "cryptographic_hash", "fake")
        result = journal.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_validate_errors_on_unbalanced(self):
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("800"))
        journal = create_test_journal(lines=[debit, credit])
        result = journal.validate()
        assert result["is_valid"] is False
        assert "Journal not balanced" in " ".join(result["errors"])

    def test_to_dict_contains_fields(self):
        journal = create_test_journal()
        d = journal.to_dict()
        assert d["journal_number"] == "JRN-202601-000001"
        assert d["journal_type"] == "GENERAL"
        assert d["status"] == "DRAFT"
        assert len(d["lines"]) == 2

    def test_from_dict_reconstructs(self):
        journal = create_test_journal()
        d = journal.to_dict()
        reconstructed = JournalEntry.from_dict(d)
        assert reconstructed.journal_id == journal.journal_id
        assert reconstructed.journal_number == journal.journal_number
        assert reconstructed.journal_type == journal.journal_type
        assert reconstructed.status == journal.status
        assert len(reconstructed.lines) == len(journal.lines)

    def test_clone_creates_new_journal(self):
        journal = create_test_journal()
        cloned = journal.clone()
        assert cloned.journal_id != journal.journal_id
        assert cloned.journal_number == journal.journal_number + "_COPY"
        assert cloned.status == JournalStatus.DRAFT
        assert cloned.version == 1
        assert len(cloned.lines) == len(journal.lines)

    def test_snapshot_returns_summary(self):
        journal = create_test_journal()
        snap = journal.snapshot()
        assert snap["journal_id"] == str(journal.journal_id)
        assert snap["journal_number"] == journal.journal_number

    def test_get_version(self):
        journal = create_test_journal()
        assert journal.get_version() == 1

    def test_audit_trail_records(self):
        journal = create_test_journal()
        assert len(journal.audit_trail()) >= 1
        journal.touch("toucher")
        trail = journal.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        journal = create_test_journal()
        touched = journal.touch("toucher")
        assert touched.version == journal.version + 1


# ============================================================================
# Tests for DoubleEntryVerificationRecord
# ============================================================================

class TestDoubleEntryVerificationRecord:
    def test_create_valid_record(self):
        record = create_test_record()
        assert record.record_id is not None
        assert record.journal_id is not None
        assert record.is_balanced is True
        assert record.severity == DoubleEntryViolationSeverity.INFO
        assert record.version == 1
        assert record.cryptographic_hash == ""  # Will be set in __post_init__

    def test_validate_raises_on_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            DoubleEntryVerificationRecord(
                record_id=uuid.uuid4(),
                journal_id=uuid.uuid4(),
                verified_at=datetime.now(UTC),
                verified_by="tester",
                is_balanced=True,
                total_debit=Decimal("1000"),
                total_credit=Decimal("1000"),
                difference=Decimal("0"),
                tolerance=Decimal("0.0001"),
                severity=DoubleEntryViolationSeverity.INFO,
                violation_message=None,
                journal_type="GENERAL",
                auto_corrected=False,
                auto_correction_applied=None,
                cryptographic_hash="",
                version=0,
            )

    def test_compute_hash_consistent(self):
        record = create_test_record()
        # Need to set hash after construction? Actually __post_init__ computes hash.
        # But we need a record with hash set for consistency.
        record = DoubleEntryVerificationRecord(
            record_id=record.record_id,
            journal_id=record.journal_id,
            verified_at=record.verified_at,
            verified_by=record.verified_by,
            is_balanced=record.is_balanced,
            total_debit=record.total_debit,
            total_credit=record.total_credit,
            difference=record.difference,
            tolerance=record.tolerance,
            severity=record.severity,
            violation_message=record.violation_message,
            journal_type=record.journal_type,
            auto_corrected=record.auto_corrected,
            auto_correction_applied=record.auto_correction_applied,
            cryptographic_hash=record.compute_hash(),
        )
        h1 = record.compute_hash()
        h2 = record.compute_hash()
        assert h1 == h2

    def test_update_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.update("admin", is_balanced=False)

    def test_delete_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.delete("admin")

    def test_restore_raises(self):
        record = create_test_record()
        with pytest.raises(AttributeError):
            record.restore("admin")

    def test_activate_returns_self(self):
        record = create_test_record()
        activated = record.activate("admin")
        assert activated is record

    def test_deactivate_returns_self(self):
        record = create_test_record()
        deactivated = record.deactivate("admin")
        assert deactivated is record

    def test_lock_returns_self(self):
        record = create_test_record()
        locked = record.lock("admin", "test")
        assert locked is record

    def test_unlock_returns_self(self):
        record = create_test_record()
        unlocked = record.unlock("admin")
        assert unlocked is record

    def test_create_returns_self(self):
        record = create_test_record()
        result = record.create("admin")
        assert result is record

    def test_validate_returns_valid(self):
        record = create_test_record()
        record.cryptographic_hash = record.compute_hash()
        result = record.validate()
        assert result["is_valid"] is True
        assert result["record_id"] == str(record.record_id)

    def test_validate_errors_on_hash_mismatch(self):
        record = create_test_record()
        record.cryptographic_hash = "fake"
        result = record.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        record = create_test_record()
        record.cryptographic_hash = record.compute_hash()
        d = record.to_dict()
        assert d["is_balanced"] is True
        assert d["total_debit"] == "1000"
        assert d["total_credit"] == "1000"

    def test_from_dict_reconstructs(self):
        record = create_test_record()
        record.cryptographic_hash = record.compute_hash()
        d = record.to_dict()
        reconstructed = DoubleEntryVerificationRecord.from_dict(d)
        assert reconstructed.record_id == record.record_id
        assert reconstructed.journal_id == record.journal_id
        assert reconstructed.is_balanced == record.is_balanced

    def test_clone_creates_new_instance(self):
        record = create_test_record()
        cloned = record.clone()
        assert cloned.record_id != record.record_id
        assert cloned.journal_id == record.journal_id
        assert cloned.is_balanced == record.is_balanced
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        record = create_test_record()
        snap = record.snapshot()
        assert snap["record_id"] == str(record.record_id)
        assert snap["is_balanced"] == record.is_balanced

    def test_get_version(self):
        record = create_test_record()
        assert record.get_version() == 1

    def test_audit_trail_records(self):
        record = create_test_record()
        assert len(record.audit_trail()) >= 1
        record.touch("toucher")
        trail = record.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# Tests for DoubleEntryAxiom
# ============================================================================

class TestDoubleEntryAxiom:
    def test_singleton(self):
        axiom1 = DoubleEntryAxiom()
        axiom2 = DoubleEntryAxiom()
        assert axiom1 is axiom2

    def test_generate_journal_number(self):
        axiom = DoubleEntryAxiom()
        num1 = axiom.generate_journal_number("JRN")
        num2 = axiom.generate_journal_number("JRN")
        assert num1 != num2
        assert num1.startswith("JRN-")
        assert num2.startswith("JRN-")

    def test_create_journal(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("1000"))
        journal = axiom.create_journal(
            journal_type=JournalType.GENERAL,
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit, credit],
            created_by="tester",
        )
        assert journal is not None
        assert journal.journal_id is not None
        assert journal.journal_number is not None
        assert journal.status == JournalStatus.DRAFT
        assert journal.total_debit == Decimal("1000")
        assert journal.total_credit == Decimal("1000")
        # Check it's saved
        retrieved = axiom.get_journal(journal.journal_id)
        assert retrieved is not None
        assert retrieved.journal_id == journal.journal_id

    def test_create_journal_with_custom_number(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("500"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("500"))
        journal = axiom.create_journal(
            journal_type=JournalType.ADJUSTING,
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit, credit],
            created_by="tester",
            journal_number="CUSTOM-001",
        )
        assert journal.journal_number == "CUSTOM-001"

    def test_create_journal_without_lines_raises(self):
        axiom = DoubleEntryAxiom()
        with pytest.raises(InvalidJournalEntryError, match="at least one line"):
            axiom.create_journal(
                journal_type=JournalType.GENERAL,
                transaction_date=datetime.now(UTC),
                description="Test",
                lines=[],
                created_by="tester",
            )

    def test_submit_journal(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("1000"))
        journal = axiom.create_journal(
            journal_type=JournalType.GENERAL,
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit, credit],
            created_by="tester",
        )
        submitted = axiom.submit_journal(journal.journal_id, "admin")
        assert submitted is not None
        assert submitted.status == JournalStatus.SUBMITTED
        # Try submit again -> should fail
        result = axiom.submit_journal(journal.journal_id, "admin")
        assert result is None

    def test_approve_journal(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("1000"))
        journal = axiom.create_journal(
            journal_type=JournalType.GENERAL,
            transaction_date=datetime.now(UTC),
            description="Test",
            lines=[debit, credit],
            created_by="tester",
        )
        axiom.submit_journal(journal.journal_id, "tester")
        approved = axiom.approve_journal(journal.journal_id, "approver")
        assert approved is not None
        assert approved.status == JournalStatus.APPROVED
        assert "approver" in approved.approved_by
        # Try approve again -> should fail
        result = axiom.approve_journal(journal.journal_id, "approver2")
        assert result is None

    def test_save_and_get_journal(self):
        axiom = DoubleEntryAxiom()
        journal = create_test_journal()
        axiom.save_journal(journal)
        retrieved = axiom.get_journal(journal.journal_id)
        assert retrieved is not None
        assert retrieved.journal_id == journal.journal_id

    def test_get_all_journals(self):
        axiom = DoubleEntryAxiom()
        j1 = create_test_journal()
        j2 = create_test_journal()
        axiom.save_journal(j1)
        axiom.save_journal(j2)
        all_j = axiom.get_all_journals()
        assert len(all_j) >= 2

    def test_delete_journal(self):
        axiom = DoubleEntryAxiom()
        journal = create_test_journal()
        axiom.save_journal(journal)
        result = axiom.delete_journal(journal.journal_id)
        assert result is True
        assert axiom.get_journal(journal.journal_id) is None

    def test_save_verification_and_get_verifications(self):
        axiom = DoubleEntryAxiom()
        record = create_test_record()
        axiom.save_verification(record)
        verifications = axiom.get_verifications()
        assert len(verifications) >= 1
        found = next((r for r in verifications if r.record_id == record.record_id), None)
        assert found is not None

    def test_get_verifications_filter_by_journal(self):
        axiom = DoubleEntryAxiom()
        journal_id = uuid.uuid4()
        r1 = create_test_record()
        r1.journal_id = journal_id
        r2 = create_test_record()
        r2.journal_id = journal_id
        r3 = create_test_record()
        axiom.save_verification(r1)
        axiom.save_verification(r2)
        axiom.save_verification(r3)
        result = axiom.get_verifications(journal_id=journal_id)
        assert len(result) == 2
        assert all(r.journal_id == journal_id for r in result)

    def test_get_violations(self):
        axiom = DoubleEntryAxiom()
        # Create balanced and unbalanced records
        r1 = create_test_record(is_balanced=True)
        r2 = create_test_record(is_balanced=False)
        r2.severity = DoubleEntryViolationSeverity.HIGH
        axiom.save_verification(r1)
        axiom.save_verification(r2)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        assert any(not r.is_balanced for r in violations)

    def test_get_violations_filter_by_severity(self):
        axiom = DoubleEntryAxiom()
        r1 = create_test_record(is_balanced=False)
        r1.severity = DoubleEntryViolationSeverity.LOW
        r2 = create_test_record(is_balanced=False)
        r2.severity = DoubleEntryViolationSeverity.CRITICAL
        axiom.save_verification(r1)
        axiom.save_verification(r2)
        result = axiom.get_violations(min_severity=DoubleEntryViolationSeverity.HIGH)
        assert len(result) == 1
        assert result[0].severity == DoubleEntryViolationSeverity.CRITICAL

    def test_enforce_balanced_journal(self):
        axiom = DoubleEntryAxiom()
        journal = create_test_journal()
        is_balanced, record = axiom.enforce(journal, raise_on_violation=False)
        assert is_balanced is True
        assert record is not None
        assert record.is_balanced is True
        # Check record saved
        verifications = axiom.get_verifications(journal_id=journal.journal_id)
        assert len(verifications) >= 1

    def test_enforce_unbalanced_journal(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("800"))
        journal = create_test_journal(lines=[debit, credit])
        is_balanced, record = axiom.enforce(journal, raise_on_violation=False)
        assert is_balanced is False
        assert record is not None
        assert record.is_balanced is False
        assert record.difference == Decimal("200")

    def test_enforce_unbalanced_raises(self):
        axiom = DoubleEntryAxiom()
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("800"))
        journal = create_test_journal(lines=[debit, credit])
        with pytest.raises(DoubleEntryViolationError, match="double entry violation"):
            axiom.enforce(journal, raise_on_violation=True)

    def test_determine_severity_info(self):
        axiom = DoubleEntryAxiom()
        severity = axiom._determine_severity(
            difference=Decimal("0"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("1000"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.INFO

    def test_determine_severity_low(self):
        axiom = DoubleEntryAxiom()
        # ratio > tolerance but < tolerance*10
        severity = axiom._determine_severity(
            difference=Decimal("0.001"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("999.999"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.LOW

    def test_determine_severity_medium(self):
        axiom = DoubleEntryAxiom()
        severity = axiom._determine_severity(
            difference=Decimal("0.01"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("999.99"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.MEDIUM

    def test_determine_severity_high(self):
        axiom = DoubleEntryAxiom()
        severity = axiom._determine_severity(
            difference=Decimal("0.1"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("999.9"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.HIGH

    def test_determine_severity_critical(self):
        axiom = DoubleEntryAxiom()
        severity = axiom._determine_severity(
            difference=Decimal("1"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("999"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.CRITICAL

    def test_determine_severity_catastrophic(self):
        axiom = DoubleEntryAxiom()
        severity = axiom._determine_severity(
            difference=Decimal("20"),
            total_debit=Decimal("1000"),
            total_credit=Decimal("980"),
            tolerance=Decimal("0.0001"),
        )
        assert severity == DoubleEntryViolationSeverity.CATASTROPHIC

    def test_get_statistics(self):
        axiom = DoubleEntryAxiom()
        journal = create_test_journal()
        axiom.save_journal(journal)
        # Add some verifications
        record = create_test_record()
        axiom.save_verification(record)
        stats = axiom.get_statistics()
        assert stats["total_journals"] >= 1
        assert stats["total_verifications"] >= 1
        assert "by_status" in stats

    def test_reset(self):
        axiom = DoubleEntryAxiom()
        journal = create_test_journal()
        axiom.save_journal(journal)
        axiom.reset()
        assert len(axiom._journals) == 0
        assert len(axiom._verification_history) == 0
        assert len(axiom._violation_history) == 0
        assert len(axiom._journal_sequence) == 0


# ============================================================================
# Tests for DoubleEntryValidator
# ============================================================================

class TestDoubleEntryValidator:
    def test_validate_journal_balanced(self):
        journal = create_test_journal()
        is_valid, msg = DoubleEntryValidator.validate_journal(journal)
        assert is_valid is True
        assert msg is None

    def test_validate_journal_unbalanced(self):
        debit = create_test_line(side=Side.DEBIT, amount=Decimal("1000"))
        credit = create_test_line(side=Side.CREDIT, amount=Decimal("800"))
        journal = create_test_journal(lines=[debit, credit])
        is_valid, msg = DoubleEntryValidator.validate_journal(journal)
        assert is_valid is False
        assert "not balanced" in msg

    def test_validate_lines_valid(self):
        lines = [
            create_test_line(side=Side.DEBIT, amount=Decimal("100")),
            create_test_line(side=Side.CREDIT, amount=Decimal("100")),
        ]
        is_valid, msg = DoubleEntryValidator.validate_lines(lines)
        assert is_valid is True
        assert msg is None

    def test_validate_lines_negative_amount(self):
        line = create_test_line(amount=Decimal("-100"))
        is_valid, msg = DoubleEntryValidator.validate_lines([line])
        assert is_valid is False
        assert "non-positive" in msg

    def test_validate_lines_empty_account(self):
        line = create_test_line()
        line.account_code = ""
        is_valid, msg = DoubleEntryValidator.validate_lines([line])
        assert is_valid is False
        assert "empty account" in msg

    def test_validate_balance_balanced(self):
        is_valid, diff = DoubleEntryValidator.validate_balance(
            debit=Decimal("1000"), credit=Decimal("1000")
        )
        assert is_valid is True
        assert diff == Decimal("0")

    def test_validate_balance_unbalanced(self):
        is_valid, diff = DoubleEntryValidator.validate_balance(
            debit=Decimal("1000"), credit=Decimal("800")
        )
        assert is_valid is False
        assert diff == Decimal("200")


# ============================================================================
# Tests for Helper Functions
# ============================================================================

class TestHelpers:
    def test_create_journal_line(self):
        line = create_journal_line(
            account_code="1100",
            side=Side.DEBIT,
            amount=Decimal("100"),
            currency="IDR",
            description="Test",
            legal_entity_id=uuid.uuid4(),
            cost_center="CC01",
            department="DEPT01",
            project_id=uuid.uuid4(),
            reference="REF",
        )
        assert line.account_code == "1100"
        assert line.side == Side.DEBIT
        assert line.amount == Decimal("100")

    def test_create_journal_line_string_side(self):
        line = create_journal_line(
            account_code="1100",
            side="credit",
            amount=Decimal("100"),
        )
        assert line.side == Side.CREDIT

    def test_create_debit_line(self):
        line = create_debit_line(account_code="1100", amount=Decimal("200"))
        assert line.side == Side.DEBIT
        assert line.amount == Decimal("200")

    def test_create_credit_line(self):
        line = create_credit_line(account_code="2100", amount=Decimal("300"))
        assert line.side == Side.CREDIT
        assert line.amount == Decimal("300")

    def test_create_journal_line_dict(self):
        d = create_journal_line_dict(
            account_code="1100",
            side="debit",
            amount=Decimal("100"),
            currency="IDR",
            description="Test",
            legal_entity_id=uuid.uuid4(),
            cost_center="CC01",
        )
        assert d["account_code"] == "1100"
        assert d["side"] == "debit"
        assert d["amount"] == Decimal("100")
        assert d["cost_center"] == "CC01"


# ============================================================================
# Test module-level functions
# ============================================================================

def test_get_double_entry_axiom_returns_singleton():
    axiom1 = get_double_entry_axiom()
    axiom2 = get_double_entry_axiom()
    assert axiom1 is axiom2
    assert isinstance(axiom1, DoubleEntryAxiom)