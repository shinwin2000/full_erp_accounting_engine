# tests/domain/journal/test_aggregate_root.py
"""
Comprehensive unit tests for domain/journal/aggregate_root.py.
Covers all public methods, negative paths, edge cases, and uses mocking for datetime.
Includes explicit tests for private methods to ensure full coverage.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from domain.journal.aggregate_root import Journal, JournalRepository
from domain.journal.journal_entity import JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLineVO, JournalSide

# ============================================================================
# Fixed datetime to avoid flakiness
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("domain.journal.aggregate_root.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Helper functions
# ============================================================================

def create_line(
    account_id: UUID | None = None,
    account_code: str = "1100",
    account_name: str = "Cash",
    side: JournalSide = JournalSide.DEBIT,
    amount: Decimal = Decimal("1000"),
    description: str = "Test line",
    legal_entity_id: UUID | None = None,
    cost_center: str | None = None,
    department: str | None = None,
    project_id: UUID | None = None,
    customer_id: UUID | None = None,
    supplier_id: UUID | None = None,
    employee_id: UUID | None = None,
) -> JournalLineVO:
    if account_id is None:
        account_id = uuid4()
    if legal_entity_id is None:
        legal_entity_id = uuid4()
    return JournalLineVO(
        line_id=uuid4(),
        journal_id=uuid4(),  # will be overwritten when added
        account_id=account_id,
        account_code=account_code,
        account_name=account_name,
        side=side,
        amount=amount,
        description=description,
        legal_entity_id=legal_entity_id,
        cost_center=cost_center,
        department=department,
        project_id=project_id,
        customer_id=customer_id,
        supplier_id=supplier_id,
        employee_id=employee_id,
    )


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def legal_entity_id():
    return uuid4()


@pytest.fixture
def sample_lines(legal_entity_id):
    return [
        create_line(
            account_code="1100",
            account_name="Cash",
            side=JournalSide.DEBIT,
            amount=Decimal("1000"),
            legal_entity_id=legal_entity_id,
        ),
        create_line(
            account_code="2100",
            account_name="Accounts Payable",
            side=JournalSide.CREDIT,
            amount=Decimal("1000"),
            legal_entity_id=legal_entity_id,
        ),
    ]


@pytest.fixture
def sample_journal(legal_entity_id, sample_lines):
    return Journal(
        journal_id=uuid4(),
        journal_number="JRN-2026-001",
        journal_type=JournalType.GENERAL,
        transaction_date=FIXED_NOW,
        posting_date=None,
        description="Test journal",
        lines=sample_lines,
        legal_entity_id=legal_entity_id,
        status=JournalStatus.DRAFT,
        created_by="user1",
        created_at=FIXED_NOW,
        updated_at=FIXED_NOW,
        approved_by=[],
        approved_at=None,
        posted_by=None,
        posted_at=None,
        reversed_by=None,
        reversed_at=None,
        reversal_of=None,
        reversal_journal_id=None,
        reference="REF-001",
        source_system="ERP",
        _version=1,
        _audit_trail=[],
        _snapshots=[],
        _is_locked=False,
        _locked_by=None,
        _locked_at=None,
    )


@pytest.fixture
def submitted_journal(sample_journal):
    return sample_journal.submit("user1")


@pytest.fixture
def approved_journal(submitted_journal):
    return submitted_journal.approve("approver1")


# ============================================================================
# Tests for construction and validation
# ============================================================================

class TestConstruction:
    def test_valid_construction(self, sample_journal):
        assert sample_journal.journal_id is not None
        assert sample_journal.journal_number == "JRN-2026-001"
        assert sample_journal.status == JournalStatus.DRAFT
        assert sample_journal.total_debit == Decimal("1000")
        assert sample_journal.total_credit == Decimal("1000")
        assert sample_journal.is_balanced() is True
        assert sample_journal.difference == Decimal("0")
        assert sample_journal.version == 1
        assert sample_journal.is_locked is False

    def test_unbalanced_raises(self, legal_entity_id):
        debit = create_line(side=JournalSide.DEBIT, amount=Decimal("1000"), legal_entity_id=legal_entity_id)
        credit = create_line(side=JournalSide.CREDIT, amount=Decimal("500"), legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not balanced"):
            Journal(
                journal_id=uuid4(),
                journal_number="JRN-001",
                journal_type=JournalType.GENERAL,
                transaction_date=FIXED_NOW,
                posting_date=None,
                description="Test",
                lines=[debit, credit],
                legal_entity_id=legal_entity_id,
                status=JournalStatus.DRAFT,
                created_by="user",
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )

    def test_short_journal_number_raises(self, legal_entity_id, sample_lines):
        with pytest.raises(ValueError, match="at least 3 characters"):
            Journal(
                journal_id=uuid4(),
                journal_number="AB",
                journal_type=JournalType.GENERAL,
                transaction_date=FIXED_NOW,
                posting_date=None,
                description="Test",
                lines=sample_lines,
                legal_entity_id=legal_entity_id,
                status=JournalStatus.DRAFT,
                created_by="user",
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )

    def test_short_description_raises(self, legal_entity_id, sample_lines):
        with pytest.raises(ValueError, match="at least 2 characters"):
            Journal(
                journal_id=uuid4(),
                journal_number="JRN-001",
                journal_type=JournalType.GENERAL,
                transaction_date=FIXED_NOW,
                posting_date=None,
                description="A",
                lines=sample_lines,
                legal_entity_id=legal_entity_id,
                status=JournalStatus.DRAFT,
                created_by="user",
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )

    def test_line_legal_entity_mismatch_raises(self, legal_entity_id):
        other_legal = uuid4()
        debit = create_line(side=JournalSide.DEBIT, amount=Decimal("1000"), legal_entity_id=other_legal)
        credit = create_line(side=JournalSide.CREDIT, amount=Decimal("1000"), legal_entity_id=other_legal)
        with pytest.raises(ValueError, match="different legal_entity_id"):
            Journal(
                journal_id=uuid4(),
                journal_number="JRN-001",
                journal_type=JournalType.GENERAL,
                transaction_date=FIXED_NOW,
                posting_date=None,
                description="Test",
                lines=[debit, credit],
                legal_entity_id=legal_entity_id,
                status=JournalStatus.DRAFT,
                created_by="user",
                created_at=FIXED_NOW,
                updated_at=FIXED_NOW,
            )


# ============================================================================
# Tests for properties
# ============================================================================

class TestProperties:
    def test_total_debit_credit(self, sample_journal):
        assert sample_journal.total_debit == Decimal("1000")
        assert sample_journal.total_credit == Decimal("1000")
        assert sample_journal.difference == Decimal("0")

    def test_version(self, sample_journal):
        assert sample_journal.version == 1

    def test_is_locked(self, sample_journal):
        assert sample_journal.is_locked is False

    def test_audit_trail(self, sample_journal):
        assert sample_journal.audit_trail == []
        sample_journal._record_audit_trail("test", {"a": 1})
        trail = sample_journal.audit_trail
        assert len(trail) == 1
        assert trail[0]["action"] == "test"
        assert trail[0]["details"] == {"a": 1}
        assert trail[0]["version"] == 1

    def test_is_editable_draft(self, sample_journal):
        assert sample_journal.is_editable is True

    def test_is_editable_rejected(self, sample_journal):
        rejected = sample_journal.submit("user1").reject("approver1", "reason")
        assert rejected.is_editable is True

    def test_is_editable_posted(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        assert posted.is_editable is False

    def test_is_editable_submitted(self, sample_journal):
        submitted = sample_journal.submit("user1")
        assert submitted.is_editable is False


# ============================================================================
# Tests for state transitions
# ============================================================================

class TestStateTransitions:
    def test_submit_success(self, sample_journal):
        submitted = sample_journal.submit("user1")
        assert submitted.status == JournalStatus.SUBMITTED
        assert submitted._version == 2
        assert submitted.updated_at == FIXED_NOW
        trail = submitted.get_audit_trail()
        assert any(entry["action"] == "submitted" for entry in trail)

    def test_submit_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="locked"):
            locked.submit("user1")

    def test_submit_not_draft_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        with pytest.raises(ValueError, match="Cannot submit journal in status submitted"):
            submitted.submit("user1")

    def test_submit_unbalanced_raises(self, sample_journal):
        # Add an extra debit line to make unbalanced
        extra = create_line(side=JournalSide.DEBIT, amount=Decimal("100"), legal_entity_id=sample_journal.legal_entity_id)
        journal = sample_journal.add_line(extra)  # This will become unbalanced
        with pytest.raises(ValueError, match="unbalanced"):
            journal.submit("user1")

    def test_approve_success(self, sample_journal):
        submitted = sample_journal.submit("user1")
        approved = submitted.approve("approver1")
        assert approved.status == JournalStatus.APPROVED
        assert approved.approved_by == ["approver1"]
        assert approved.approved_at == FIXED_NOW
        assert approved._version == 3
        trail = approved.get_audit_trail()
        assert any(entry["action"] == "approved" for entry in trail)

    def test_approve_by_creator_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        with pytest.raises(ValueError, match="Maker cannot approve own journal"):
            submitted.approve("user1")

    def test_approve_not_submitted_raises(self, sample_journal):
        with pytest.raises(ValueError, match="Cannot approve journal in status draft"):
            sample_journal.approve("approver1")

    def test_approve_locked_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        locked = submitted.lock("approver1")
        with pytest.raises(ValueError, match="locked"):
            locked.approve("approver1")

    def test_reject_success(self, sample_journal):
        submitted = sample_journal.submit("user1")
        rejected = submitted.reject("approver1", "Wrong amount")
        assert rejected.status == JournalStatus.REJECTED
        assert "Rejected: Wrong amount" in rejected.description
        assert rejected._version == 3
        trail = rejected.get_audit_trail()
        assert any(entry["action"] == "rejected" for entry in trail)

    def test_reject_not_submitted_raises(self, sample_journal):
        with pytest.raises(ValueError, match="Cannot reject journal in status draft"):
            sample_journal.reject("approver1", "reason")

    def test_reject_locked_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        locked = submitted.lock("approver1")
        with pytest.raises(ValueError, match="locked"):
            locked.reject("approver1", "reason")

    def test_post_success(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        assert posted.status == JournalStatus.POSTED
        assert posted.posting_date == FIXED_NOW
        assert posted.posted_by == "poster1"
        assert posted.posted_at == FIXED_NOW
        assert posted._version == 4
        trail = posted.get_audit_trail()
        assert any(entry["action"] == "posted" for entry in trail)

    def test_post_not_approved_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        with pytest.raises(ValueError, match="Cannot post journal in status submitted"):
            submitted.post("poster1")

    def test_post_locked_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        approved = submitted.approve("approver1")
        locked = approved.lock("poster1")
        with pytest.raises(ValueError, match="locked"):
            locked.post("poster1")

    def test_reverse_success(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        reversal_id = uuid4()
        reversed_journal = posted.reverse("reverser1", reversal_id, "Error")
        assert reversed_journal.status == JournalStatus.REVERSED
        assert reversed_journal.reversal_of == posted.journal_id
        assert reversed_journal.reversal_journal_id == reversal_id
        assert reversed_journal.reversed_by == "reverser1"
        assert reversed_journal.reversed_at == FIXED_NOW
        assert reversed_journal._version == 5
        trail = reversed_journal.get_audit_trail()
        assert any(entry["action"] == "reversed" for entry in trail)

    def test_reverse_not_posted_raises(self, sample_journal):
        with pytest.raises(ValueError, match="Cannot reverse journal in status draft"):
            sample_journal.reverse("reverser1", uuid4(), "reason")

    def test_reverse_locked_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        locked = posted.lock("reverser1")
        with pytest.raises(ValueError, match="locked"):
            locked.reverse("reverser1", uuid4(), "reason")

    def test_void_draft_success(self, sample_journal):
        voided = sample_journal.void("manager1", "Cancel")
        assert voided.status == JournalStatus.CANCELLED
        assert "Voided: Cancel" in voided.description
        assert voided._version == 2
        trail = voided.get_audit_trail()
        assert any(entry["action"] == "voided" for entry in trail)

    def test_void_submitted_success(self, sample_journal):
        submitted = sample_journal.submit("user1")
        voided = submitted.void("manager1", "Cancel")
        assert voided.status == JournalStatus.CANCELLED

    def test_void_approved_raises(self, sample_journal):
        approved = sample_journal.submit("user1").approve("approver1")
        with pytest.raises(ValueError, match="Cannot void journal in status approved"):
            approved.void("manager1", "reason")

    def test_void_locked_raises(self, sample_journal):
        locked = sample_journal.lock("manager1")
        with pytest.raises(ValueError, match="locked"):
            locked.void("manager1", "reason")

    def test_archive_posted_success(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        archived = posted.archive("archiver1")
        assert archived.status == JournalStatus.ARCHIVED
        assert archived._version == 5
        trail = archived.get_audit_trail()
        assert any(entry["action"] == "archived" for entry in trail)

    def test_archive_rejected_success(self, sample_journal):
        rejected = sample_journal.submit("user1").reject("approver1", "reason")
        archived = rejected.archive("archiver1")
        assert archived.status == JournalStatus.ARCHIVED

    def test_archive_draft_raises(self, sample_journal):
        with pytest.raises(ValueError, match="Cannot archive journal in status draft"):
            sample_journal.archive("archiver1")

    def test_archive_locked_raises(self, sample_journal):
        locked = sample_journal.lock("archiver1")
        with pytest.raises(ValueError, match="locked"):
            locked.archive("archiver1")

    def test_unarchive_success(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        archived = posted.archive("archiver1")
        unarchived = archived.unarchive("unarchiver1")
        assert unarchived.status == JournalStatus.POSTED
        assert unarchived._version == 6
        trail = unarchived.get_audit_trail()
        assert any(entry["action"] == "unarchived" for entry in trail)

    def test_unarchive_not_archived_raises(self, sample_journal):
        with pytest.raises(ValueError, match="Cannot unarchive journal in status draft"):
            sample_journal.unarchive("user1")

    def test_unarchive_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="locked"):
            locked.unarchive("user1")


# ============================================================================
# Tests for lock/unlock
# ============================================================================

class TestLockUnlock:
    def test_lock_success(self, sample_journal):
        locked = sample_journal.lock("user1", "Editing")
        assert locked.is_locked is True
        assert locked._locked_by == "user1"
        assert locked._locked_at == FIXED_NOW
        assert locked._version == 2
        trail = locked.get_audit_trail()
        assert any(entry["action"] == "locked" for entry in trail)

    def test_lock_already_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="already locked"):
            locked.lock("user2")

    def test_lock_not_editable_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        with pytest.raises(ValueError, match="Cannot lock: journal is in status submitted"):
            submitted.lock("user1")

    def test_lock_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        with pytest.raises(ValueError, match="Cannot lock: journal has been posted"):
            posted.lock("user1")

    def test_unlock_success(self, sample_journal):
        locked = sample_journal.lock("user1")
        unlocked = locked.unlock("user1")
        assert unlocked.is_locked is False
        assert unlocked._locked_by is None
        assert unlocked._locked_at is None
        assert unlocked._version == 3
        trail = unlocked.get_audit_trail()
        assert any(entry["action"] == "unlocked" for entry in trail)

    def test_unlock_not_locked_raises(self, sample_journal):
        with pytest.raises(ValueError, match="not locked"):
            sample_journal.unlock("user1")

    def test_unlock_by_different_user_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="cannot unlock by"):
            locked.unlock("user2")


# ============================================================================
# Tests for line management
# ============================================================================

class TestLineManagement:
    def test_add_line_success(self, sample_journal, legal_entity_id):
        # Add debit and credit to keep balance
        debit_line = create_line(
            account_code="1200", account_name="Bank",
            side=JournalSide.DEBIT, amount=Decimal("500"),
            legal_entity_id=legal_entity_id,
        )
        credit_line = create_line(
            account_code="2100", account_name="AP",
            side=JournalSide.CREDIT, amount=Decimal("500"),
            legal_entity_id=legal_entity_id,
        )
        journal = sample_journal.add_line(debit_line)
        journal = journal.add_line(credit_line)
        assert len(journal.lines) == 4
        assert journal.total_debit == Decimal("1500")
        assert journal.total_credit == Decimal("1500")
        assert journal._version == 3
        trail = journal.get_audit_trail()
        assert any(entry["action"] == "line_added" for entry in trail)

    def test_add_line_unbalanced_raises(self, sample_journal, legal_entity_id):
        new_line = create_line(side=JournalSide.DEBIT, amount=Decimal("500"), legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Journal would be unbalanced"):
            sample_journal.add_line(new_line)

    def test_add_line_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        debit = create_line(side=JournalSide.DEBIT, amount=Decimal("500"), legal_entity_id=sample_journal.legal_entity_id)
        create_line(side=JournalSide.CREDIT, amount=Decimal("500"), legal_entity_id=sample_journal.legal_entity_id)
        with pytest.raises(ValueError, match="locked"):
            locked.add_line(debit)

    def test_add_line_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        new_line = create_line(side=JournalSide.CREDIT, amount=Decimal("500"), legal_entity_id=sample_journal.legal_entity_id)
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted.add_line(new_line)

    def test_remove_line_raises_if_unbalanced(self, sample_journal):
        # With only two lines (one debit, one credit), removing either line breaks balance.
        line_id = sample_journal.lines[0].line_id
        with pytest.raises(ValueError, match="Journal would be unbalanced"):
            sample_journal.remove_line(line_id)

    def test_remove_line_not_found(self, sample_journal):
        with pytest.raises(ValueError, match="not found"):
            sample_journal.remove_line(uuid4())

    def test_remove_line_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        line_id = sample_journal.lines[0].line_id
        with pytest.raises(ValueError, match="locked"):
            locked.remove_line(line_id)

    def test_remove_line_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        line_id = posted.lines[0].line_id
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted.remove_line(line_id)

    def test_update_line_success(self, sample_journal):
        # Update both debit and credit lines to keep balance
        debit_id = sample_journal.lines[0].line_id
        credit_id = sample_journal.lines[1].line_id
        old_debit = sample_journal.lines[0]
        old_credit = sample_journal.lines[1]
        new_debit = JournalLineVO(
            line_id=debit_id,
            journal_id=sample_journal.journal_id,
            account_id=old_debit.account_id,
            account_code=old_debit.account_code,
            account_name=old_debit.account_name,
            side=old_debit.side,
            amount=Decimal("1500"),
            description=old_debit.description,
            legal_entity_id=old_debit.legal_entity_id,
            cost_center=old_debit.cost_center,
            department=old_debit.department,
            project_id=old_debit.project_id,
            customer_id=old_debit.customer_id,
            supplier_id=old_debit.supplier_id,
            employee_id=old_debit.employee_id,
        )
        new_credit = JournalLineVO(
            line_id=credit_id,
            journal_id=sample_journal.journal_id,
            account_id=old_credit.account_id,
            account_code=old_credit.account_code,
            account_name=old_credit.account_name,
            side=old_credit.side,
            amount=Decimal("1500"),
            description=old_credit.description,
            legal_entity_id=old_credit.legal_entity_id,
            cost_center=old_credit.cost_center,
            department=old_credit.department,
            project_id=old_credit.project_id,
            customer_id=old_credit.customer_id,
            supplier_id=old_credit.supplier_id,
            employee_id=old_credit.employee_id,
        )
        journal = sample_journal.update_line(debit_id, new_debit, "user1")
        journal = journal.update_line(credit_id, new_credit, "user1")
        assert journal.lines[0].amount == Decimal("1500")
        assert journal.lines[1].amount == Decimal("1500")
        assert journal.total_debit == Decimal("1500")
        assert journal.total_credit == Decimal("1500")
        assert journal._version == 3
        trail = journal.get_audit_trail()
        assert any(entry["action"] == "line_updated" for entry in trail)

    def test_update_line_not_found(self, sample_journal):
        new_line = sample_journal.lines[0]
        with pytest.raises(ValueError, match="not found"):
            sample_journal.update_line(uuid4(), new_line, "user1")

    def test_update_line_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        line = sample_journal.lines[0]
        with pytest.raises(ValueError, match="locked"):
            locked.update_line(line.line_id, line, "user1")

    def test_update_line_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        line = posted.lines[0]
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted.update_line(line.line_id, line, "user1")

    def test_update_line_unbalanced_raises(self, sample_journal):
        debit_id = sample_journal.lines[0].line_id
        old_debit = sample_journal.lines[0]
        new_debit = JournalLineVO(
            line_id=debit_id,
            journal_id=sample_journal.journal_id,
            account_id=old_debit.account_id,
            account_code=old_debit.account_code,
            account_name=old_debit.account_name,
            side=old_debit.side,
            amount=Decimal("2000"),
            description=old_debit.description,
            legal_entity_id=old_debit.legal_entity_id,
            cost_center=old_debit.cost_center,
            department=old_debit.department,
            project_id=old_debit.project_id,
            customer_id=old_debit.customer_id,
            supplier_id=old_debit.supplier_id,
            employee_id=old_debit.employee_id,
        )
        with pytest.raises(ValueError, match="Journal would be unbalanced"):
            sample_journal.update_line(debit_id, new_debit, "user1")


# ============================================================================
# Tests for metadata update
# ============================================================================

class TestMetadataUpdate:
    def test_update_metadata_success(self, sample_journal):
        new_desc = "Updated description"
        new_ref = "NEW-REF"
        new_date = FIXED_NOW + timedelta(days=1)
        updated = sample_journal.update_metadata(
            updated_by="user1",
            description=new_desc,
            reference=new_ref,
            transaction_date=new_date,
        )
        assert updated.description == new_desc
        assert updated.reference == new_ref
        assert updated.transaction_date == new_date
        assert updated._version == 2
        trail = updated.get_audit_trail()
        assert any(entry["action"] == "metadata_updated" for entry in trail)

    def test_update_metadata_no_changes(self, sample_journal):
        updated = sample_journal.update_metadata(updated_by="user1")
        assert updated is sample_journal

    def test_update_metadata_invalid_description(self, sample_journal):
        with pytest.raises(ValueError, match="at least 2 characters"):
            sample_journal.update_metadata("user1", description="A")

    def test_update_metadata_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="locked"):
            locked.update_metadata("user1", description="New")

    def test_update_metadata_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted.update_metadata("user1", description="New")


# ============================================================================
# Tests for validation and audit trail
# ============================================================================

class TestValidationAudit:
    def test_validate_valid(self, sample_journal):
        errors = sample_journal.validate()
        assert errors == []

    def test_validate_unbalanced(self, sample_journal):
        # Can't create unbalanced journal due to constructor validation, but we can test the validate method directly? We can't, because construction prevents it.
        # We'll test the validate method on a journal that has no lines? It will pass balance check but fail line count.
        journal = Journal(
            journal_id=uuid4(),
            journal_number="JRN-002",
            journal_type=JournalType.GENERAL,
            transaction_date=FIXED_NOW,
            posting_date=None,
            description="Test",
            lines=[],
            legal_entity_id=sample_journal.legal_entity_id,
            status=JournalStatus.DRAFT,
            created_by="user",
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
        errors = journal.validate()
        assert "at least one line" in errors

    def test_validate_invalid_line_amount(self, sample_journal):
        # Create a journal with a line that has negative amount
        le_id = sample_journal.legal_entity_id
        debit = create_line(side=JournalSide.DEBIT, amount=Decimal("-100"), legal_entity_id=le_id)
        credit = create_line(side=JournalSide.CREDIT, amount=Decimal("-100"), legal_entity_id=le_id)
        # But negative amounts are not validated at construction, only in validate().
        # However, construction only checks balance, not line amount validity.
        journal = Journal(
            journal_id=uuid4(),
            journal_number="JRN-003",
            journal_type=JournalType.GENERAL,
            transaction_date=FIXED_NOW,
            posting_date=None,
            description="Test",
            lines=[debit, credit],
            legal_entity_id=le_id,
            status=JournalStatus.DRAFT,
            created_by="user",
            created_at=FIXED_NOW,
            updated_at=FIXED_NOW,
        )
        errors = journal.validate()
        assert any("invalid amount" in e for e in errors)

    def test_audit_trail_recorded(self, sample_journal):
        sample_journal._record_audit_trail("test", {"a": 1})
        trail = sample_journal.get_audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "test"
        assert trail[0]["details"] == {"a": 1}
        assert trail[0]["version"] == 1

    def test_clear_audit_trail(self, sample_journal):
        sample_journal._record_audit_trail("test", {})
        sample_journal.clear_audit_trail()
        assert sample_journal.get_audit_trail() == []


# ============================================================================
# Tests for snapshot and clone
# ============================================================================

class TestSnapshotClone:
    def test_snapshot(self, sample_journal):
        snap = sample_journal.snapshot()
        assert snap["aggregate_id"] == str(sample_journal.journal_id)
        assert snap["aggregate_type"] == "Journal"
        assert snap["version"] == 1
        assert "timestamp" in snap
        assert "state" in snap
        assert snap["state"]["journal_number"] == "JRN-2026-001"
        assert snap["hash"] is not None
        trail = sample_journal.get_audit_trail()
        assert any(entry["action"] == "snapshot_created" for entry in trail)

    def test_restore_from_snapshot(self, sample_journal):
        snap = sample_journal.snapshot()
        sample_journal.restore_from_snapshot(snap)
        trail = sample_journal.get_audit_trail()
        assert any(entry["action"] == "restored_from_snapshot" for entry in trail)

    def test_restore_from_snapshot_wrong_aggregate(self, sample_journal):
        snap = sample_journal.snapshot()
        snap["aggregate_id"] = str(uuid4())
        with pytest.raises(ValueError, match="Snapshot belongs to different aggregate"):
            sample_journal.restore_from_snapshot(snap)

    def test_clone_success(self, sample_journal):
        cloned = sample_journal.clone()
        assert cloned.journal_id != sample_journal.journal_id
        assert cloned.journal_number == f"COPY-{sample_journal.journal_number}"
        assert cloned.status == JournalStatus.DRAFT
        assert cloned._version == 1
        assert cloned.description == f"Copy of: {sample_journal.description}"
        assert len(cloned.lines) == len(sample_journal.lines)
        for line in cloned.lines:
            assert line.journal_id == cloned.journal_id
        trail = sample_journal.get_audit_trail()
        assert any(entry["action"] == "cloned" for entry in trail)

    def test_clone_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="locked"):
            locked.clone()

    def test_clone_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted.clone()


# ============================================================================
# Tests for serialization
# ============================================================================

class TestSerialization:
    def test_to_dict(self, sample_journal):
        d = sample_journal.to_dict()
        assert d["journal_id"] == str(sample_journal.journal_id)
        assert d["journal_number"] == "JRN-2026-001"
        assert d["journal_type"] == "general"
        assert d["status"] == "draft"
        assert d["total_debit"] == "1000"
        assert d["total_credit"] == "1000"
        assert d["version"] == 1
        assert "lines" in d
        assert len(d["lines"]) == 2
        assert d["is_locked"] is False

    def test_from_dict(self, sample_journal):
        d = sample_journal.to_dict()
        # Need to reconstruct properly with ISO strings
        d["transaction_date"] = sample_journal.transaction_date.isoformat()
        d["created_at"] = sample_journal.created_at.isoformat()
        d["updated_at"] = sample_journal.updated_at.isoformat()
        # Lines need to be in dict format with proper fields
        lines_dict = []
        for line in sample_journal.lines:
            ld = {
                "line_id": str(line.line_id),
                "account_id": str(line.account_id),
                "account_code": line.account_code,
                "account_name": line.account_name,
                "side": line.side.value,
                "amount": str(line.amount),
                "description": line.description,
                "cost_center": line.cost_center,
                "department": line.department,
                "project_id": str(line.project_id) if line.project_id else None,
                "customer_id": str(line.customer_id) if line.customer_id else None,
                "supplier_id": str(line.supplier_id) if line.supplier_id else None,
                "employee_id": str(line.employee_id) if line.employee_id else None,
            }
            lines_dict.append(ld)
        d["lines"] = lines_dict
        journal = Journal.from_dict(d)
        assert journal.journal_id == sample_journal.journal_id
        assert journal.journal_number == sample_journal.journal_number
        assert journal.status == sample_journal.status
        assert journal.total_debit == sample_journal.total_debit
        assert journal.total_credit == sample_journal.total_credit
        assert journal._version == sample_journal._version


# ============================================================================
# Tests for permission methods
# ============================================================================

class TestPermissionMethods:
    def test_can_approve_segregation(self, sample_journal):
        submitted = sample_journal.submit("user1")
        assert submitted.can_approve("approver1") is True
        assert submitted.can_approve("user1") is False  # creator

    def test_can_post(self, sample_journal):
        submitted = sample_journal.submit("user1")
        approved = submitted.approve("approver1")
        assert approved.can_post("poster1") is True
        assert submitted.can_post("poster1") is False

    def test_can_reverse(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        assert posted.can_reverse() is True
        assert sample_journal.can_reverse() is False

    def test_can_edit(self, sample_journal):
        assert sample_journal.can_edit() is True
        submitted = sample_journal.submit("user1")
        assert submitted.can_edit() is False
        rejected = submitted.reject("approver1", "reason")
        assert rejected.can_edit() is True

    def test_can_delete(self, sample_journal):
        assert sample_journal.can_delete() is True
        submitted = sample_journal.submit("user1")
        assert submitted.can_delete() is False

    def test_is_balanced_tolerance(self, sample_journal):
        assert sample_journal.is_balanced() is True


# ============================================================================
# Tests for JournalRepository interface
# ============================================================================

@pytest.mark.asyncio
class TestJournalRepository:
    def test_abstract_methods_raise(self):
        repo = JournalRepository()
        with pytest.raises(NotImplementedError):
            repo.get_by_id(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_number("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.get_by_date_range(uuid4(), FIXED_NOW, FIXED_NOW)
        with pytest.raises(NotImplementedError):
            repo.get_by_status(uuid4(), JournalStatus.DRAFT)
        with pytest.raises(NotImplementedError):
            repo.get_pending_approval(uuid4())
        with pytest.raises(NotImplementedError):
            repo.save(MagicMock())
        with pytest.raises(NotImplementedError):
            repo.delete(uuid4(), uuid4())
        with pytest.raises(NotImplementedError):
            repo.exists("", uuid4())
        with pytest.raises(NotImplementedError):
            repo.count(uuid4())


# ============================================================================
# Explicit tests for private methods (with assertions)
# ============================================================================

class TestPrivateMethods:
    def test_ensure_editable_when_locked_raises(self, sample_journal):
        locked = sample_journal.lock("user1")
        with pytest.raises(ValueError, match="locked"):
            locked._ensure_editable("test_operation")

    def test_ensure_editable_when_not_editable_raises(self, sample_journal):
        submitted = sample_journal.submit("user1")
        with pytest.raises(ValueError, match="Cannot test_operation: journal is in status submitted"):
            submitted._ensure_editable("test_operation")

    def test_ensure_editable_when_editable_succeeds(self, sample_journal):
        # Should not raise
        try:
            sample_journal._ensure_editable("test_operation")
        except Exception:
            pytest.fail("_ensure_editable raised an exception when it should not")
        # Assert that the method executed without raising (implicit pass, but we add an assertion)
        assert True

    def test_ensure_not_posted_when_posted_raises(self, sample_journal):
        posted = sample_journal.submit("user1").approve("approver1").post("poster1")
        with pytest.raises(ValueError, match="posted and is immutable"):
            posted._ensure_not_posted("test_operation")

    def test_ensure_not_posted_when_not_posted_succeeds(self, sample_journal):
        # Should not raise
        try:
            sample_journal._ensure_not_posted("test_operation")
        except Exception:
            pytest.fail("_ensure_not_posted raised an exception when it should not")
        assert True

    def test_ensure_balanced_lines_with_balanced_lines_succeeds(self, sample_journal):
        # Should not raise
        try:
            sample_journal._ensure_balanced_lines(sample_journal.lines)
        except Exception:
            pytest.fail("_ensure_balanced_lines raised an exception when it should not")
        assert True

    def test_ensure_balanced_lines_with_unbalanced_lines_raises(self, sample_journal, legal_entity_id):
        unbalanced_lines = [
            create_line(side=JournalSide.DEBIT, amount=Decimal("1000"), legal_entity_id=legal_entity_id),
            create_line(side=JournalSide.CREDIT, amount=Decimal("500"), legal_entity_id=legal_entity_id),
        ]
        with pytest.raises(ValueError, match="Journal would be unbalanced"):
            sample_journal._ensure_balanced_lines(unbalanced_lines)

    def test_ensure_balanced_lines_with_tolerance_check(self, sample_journal, legal_entity_id):
        # Difference of 0.005 is within tolerance of 0.01? Actually the tolerance is 0.01.
        # Difference of 0.01 is allowed? The check uses Decimal("0.01") tolerance.
        unbalanced_lines = [
            create_line(side=JournalSide.DEBIT, amount=Decimal("1000.00"), legal_entity_id=legal_entity_id),
            create_line(side=JournalSide.CREDIT, amount=Decimal("999.99"), legal_entity_id=legal_entity_id),
        ]
        # Difference is 0.01, which is <= 0.01, so it should not raise.
        # Should not raise
        try:
            sample_journal._ensure_balanced_lines(unbalanced_lines)
        except Exception:
            pytest.fail("_ensure_balanced_lines raised an exception when difference is within tolerance")
        assert True

    def test_ensure_balanced_lines_raises_on_large_difference(self, sample_journal, legal_entity_id):
        # Difference of 0.02 is > 0.01, so it should raise.
        unbalanced_lines = [
            create_line(side=JournalSide.DEBIT, amount=Decimal("1000.02"), legal_entity_id=legal_entity_id),
            create_line(side=JournalSide.CREDIT, amount=Decimal("1000.00"), legal_entity_id=legal_entity_id),
        ]
        with pytest.raises(ValueError, match="Journal would be unbalanced"):
            sample_journal._ensure_balanced_lines(unbalanced_lines)
