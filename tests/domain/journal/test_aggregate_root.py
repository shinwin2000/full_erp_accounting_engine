"""
Tests for domain/journal/aggregate_root.py (Journal aggregate root)

Covers construction/validation, properties, segregation-of-duties checks,
lock/unlock, line management, metadata updates, validate(), clone(),
snapshot(), (de)serialization, and the JournalRepository protocol.

======================================================================
KNOWN BUGS IN THE SOURCE (verified by direct execution, documented here
on purpose instead of silently working around them):

BUG-JOURNAL-001 — every state-transition method that is NOT `submit()`
(i.e. approve, reject, post, reverse, void, archive, unarchive) calls
`self._ensure_editable(<op>)` as its very first guard. `_ensure_editable`
only allows DRAFT/REJECTED status (`can_edit()`), so calling any of these
methods from the status they are actually meant to run from (SUBMITTED,
APPROVED, POSTED, ARCHIVED, ...) raises
`ValueError("Cannot <op>: journal is in status <status>")` before the
method's own status check ever runs. In the current code, only
`submit()` (DRAFT -> SUBMITTED) and `void()` from DRAFT can ever pass
this guard — and `void()` from DRAFT fails for a second, independent
reason (BUG-JOURNAL-002 below). Practically: approve/reject/post/reverse/
archive/unarchive can never succeed today.

BUG-JOURNAL-002 — `void()` accepts a `reason` parameter but never passes
it to `JournalStateMachine.validate_transition(...)`. The DRAFT/SUBMITTED
-> CANCELLED transition rule has `requires_reason=True`, so
`validate_transition` always reports "Reason is required for this
transition" regardless of what `reason` the caller supplied.

BUG-JOURNAL-003 — `unlock()` calls `self._ensure_editable("unlock")`
first, which raises "journal is locked" whenever `_is_locked` is True —
including when the *correct* locking user calls it. The subsequent
`if self._locked_by != user_id` check is therefore unreachable dead
code: a locked journal can never be unlocked via `unlock()`, by anyone.

These tests pin down the *current* behaviour so regressions are caught
and so a future fix is validated by an explicit, intentional test update
(not a silent behaviour change slipping through).
======================================================================
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from domain.journal.aggregate_root import Journal, JournalAggregate, JournalRepository
from domain.journal.journal_entity import JournalStatus, JournalType
from domain.journal.journal_line_vo import JournalLineVO, JournalSide


# ============================================================================
# Fixtures / builders
# ============================================================================


def make_lines(legal_entity_id, journal_id=None, debit=Decimal("100"), credit=Decimal("100")):
    jid = journal_id or uuid4()
    lines = []
    if debit > 0:
        lines.append(
            JournalLineVO.create_debit(jid, uuid4(), "1000", "Cash", debit, "debit line", legal_entity_id)
        )
    if credit > 0:
        lines.append(
            JournalLineVO.create_credit(jid, uuid4(), "4000", "Revenue", credit, "credit line", legal_entity_id)
        )
    return lines


def make_journal(status=JournalStatus.DRAFT, **overrides):
    legal_entity_id = overrides.pop("legal_entity_id", uuid4())
    journal_id = overrides.pop("journal_id", uuid4())
    lines = overrides.pop("lines", None)
    debit = overrides.pop("debit", Decimal("100"))
    credit = overrides.pop("credit", Decimal("100"))
    if lines is None:
        lines = make_lines(legal_entity_id, journal_id, debit=debit, credit=credit)
    now = datetime.now(UTC)
    defaults = dict(
        journal_id=journal_id,
        journal_number="JRN-001",
        journal_type=JournalType.GENERAL,
        transaction_date=now,
        posting_date=None,
        description="Test journal",
        lines=lines,
        legal_entity_id=legal_entity_id,
        status=status,
        created_by="user_a",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Journal(**defaults)


@pytest.fixture
def legal_entity_id():
    return uuid4()


# ============================================================================
# Construction & invariants
# ============================================================================


class TestJournalConstruction:
    def test_valid_balanced_journal_constructs(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.is_balanced()
        assert journal.total_debit == Decimal("100")
        assert journal.total_credit == Decimal("100")

    def test_unbalanced_lines_raise(self, legal_entity_id):
        lines = make_lines(legal_entity_id, debit=Decimal("100"), credit=Decimal("50"))
        with pytest.raises(ValueError, match="not balanced"):
            make_journal(legal_entity_id=legal_entity_id, lines=lines)

    def test_line_with_mismatched_legal_entity_raises(self, legal_entity_id):
        other_entity = uuid4()
        journal_id = uuid4()
        lines = [
            JournalLineVO.create_debit(journal_id, uuid4(), "1000", "Cash", Decimal("100"), "debit", legal_entity_id),
            JournalLineVO.create_credit(journal_id, uuid4(), "4000", "Rev", Decimal("100"), "credit", other_entity),
        ]
        with pytest.raises(ValueError, match="different legal_entity_id"):
            make_journal(legal_entity_id=legal_entity_id, journal_id=journal_id, lines=lines)

    def test_short_journal_number_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="at least 3 characters"):
            make_journal(legal_entity_id=legal_entity_id, journal_number="JR")

    def test_short_description_raises(self, legal_entity_id):
        with pytest.raises(ValueError, match="at least 2 characters"):
            make_journal(legal_entity_id=legal_entity_id, description="x")

    def test_journal_aggregate_alias(self):
        assert JournalAggregate is Journal


# ============================================================================
# Properties
# ============================================================================


class TestJournalProperties:
    def test_total_debit_and_credit(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id, debit=Decimal("250"), credit=Decimal("250"))
        assert journal.total_debit == Decimal("250")
        assert journal.total_credit == Decimal("250")

    def test_difference_is_zero_when_balanced(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.difference == Decimal("0")

    def test_version_starts_at_1(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.version == 1

    def test_is_locked_defaults_false(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.is_locked is False

    def test_audit_trail_starts_empty(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.audit_trail == []

    def test_is_editable_true_for_draft(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        assert journal.is_editable is True

    def test_is_editable_false_for_posted(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        assert journal.is_editable is False

    def test_is_balanced_within_tolerance(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.is_balanced(tolerance=Decimal("0.0001")) is True

    def test_is_posted(self, legal_entity_id):
        assert make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id).is_posted() is True
        assert make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id).is_posted() is False

    def test_is_reversed_false_by_default(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.is_reversed() is False

    def test_is_reversed_true_when_reversal_journal_id_set(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id, reversal_journal_id=uuid4())
        assert journal.is_reversed() is True


# ============================================================================
# Segregation of duties / can_* permission checks
# ============================================================================


class TestJournalCanChecks:
    def test_can_approve_false_when_not_submitted(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        assert journal.can_approve("someone_else") is False

    def test_can_approve_false_for_creator_segregation_of_duties(self, legal_entity_id):
        journal = make_journal(
            status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id, created_by="user_a",
        )
        assert journal.can_approve("user_a") is False

    def test_can_approve_true_for_different_user(self, legal_entity_id):
        journal = make_journal(
            status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id, created_by="user_a",
        )
        assert journal.can_approve("user_b") is True

    def test_can_post_true_only_when_approved(self, legal_entity_id):
        assert make_journal(status=JournalStatus.APPROVED, legal_entity_id=legal_entity_id).can_post("x") is True
        assert make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id).can_post("x") is False

    def test_can_reverse_true_only_when_posted(self, legal_entity_id):
        assert make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id).can_reverse() is True
        assert make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id).can_reverse() is False

    def test_can_edit_true_for_draft_and_rejected(self, legal_entity_id):
        assert make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id).can_edit() is True
        assert make_journal(status=JournalStatus.REJECTED, legal_entity_id=legal_entity_id).can_edit() is True
        assert make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id).can_edit() is False

    def test_can_delete_only_draft(self, legal_entity_id):
        assert make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id).can_delete() is True
        assert make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id).can_delete() is False


# ============================================================================
# submit() — the one transition that actually works end-to-end
# ============================================================================


class TestSubmit:
    def test_submit_from_draft_succeeds(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        submitted = journal.submit("user_a")
        assert submitted.status == JournalStatus.SUBMITTED
        assert submitted.version == journal.version + 1
        assert submitted is not journal  # new immutable-style instance

    def test_submit_from_non_draft_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot submit"):
            journal.submit("user_a")

    def test_submit_records_audit_trail(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        submitted = journal.submit("user_a")
        assert submitted.audit_trail == []  # audit is recorded on the ORIGINAL, pre-copy instance
        assert journal.audit_trail[-1]["action"] == "submitted"


# ============================================================================
# BUG-JOURNAL-001 — approve/reject/post/reverse/archive/unarchive are
# all currently broken by the _ensure_editable() guard ordering bug.
# ============================================================================


class TestKnownWorkflowBugJournal001:
    """
    These tests intentionally assert the CURRENT (buggy) behaviour of
    aggregate_root.py. See module docstring for BUG-JOURNAL-001 details.
    If the source is fixed (e.g. by removing the erroneous
    `_ensure_editable()` call from these methods, or making `can_edit()`
    aware of the operation being performed), these tests must be updated
    to assert the *successful* transition instead.
    """

    def test_approve_from_submitted_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot approve: journal is in status submitted"):
            journal.approve("user_b")

    def test_reject_from_submitted_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot reject: journal is in status submitted"):
            journal.reject("user_b", "insufficient support")

    def test_post_from_approved_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.APPROVED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot post: journal is in status approved"):
            journal.post("user_c")

    def test_reverse_from_posted_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot reverse: journal is in status posted"):
            journal.reverse("user_d", uuid4(), "correction")

    def test_archive_from_posted_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot archive: journal is in status posted"):
            journal.archive("user_f")

    def test_unarchive_from_archived_currently_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.ARCHIVED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot unarchive: journal is in status archived"):
            journal.unarchive("user_g")

    def test_void_from_submitted_currently_raises_due_to_ensure_editable(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.SUBMITTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Cannot void: journal is in status submitted"):
            journal.void("user_e", "created by mistake")


class TestKnownWorkflowBugJournal002:
    """See BUG-JOURNAL-002 in the module docstring: `reason` is accepted
    but never forwarded to the state-machine validation, so void() from
    DRAFT (the one status that passes the _ensure_editable guard) still
    fails, always with a reason-required error -- no matter what reason
    string is passed."""

    def test_void_from_draft_fails_even_with_a_reason(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="Reason is required for this transition"):
            journal.void("user_e", "created by mistake")


# ============================================================================
# BUG-JOURNAL-003 — unlock() can never succeed once locked
# ============================================================================


class TestLockUnlock:
    def test_lock_succeeds_from_draft(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        locked = journal.lock("user_a", reason="year-end freeze")
        assert locked.is_locked is True
        assert locked.version == journal.version + 1

    def test_double_lock_raises(self, legal_entity_id):
        """Note: the second lock() call is actually rejected by
        `_ensure_editable("lock")` (because `_is_locked` is already True),
        not by the explicit `if self._is_locked: raise ValueError("Journal
        is already locked...")` check further down in lock() -- that
        explicit check is unreachable dead code, same bug family as
        BUG-JOURNAL-003."""
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        locked = journal.lock("user_a")
        with pytest.raises(ValueError, match="Cannot lock: journal is locked by user_a"):
            locked.lock("user_b")

    def test_unlock_when_not_locked_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not locked"):
            journal.unlock("user_a")

    def test_unlock_by_correct_user_currently_raises(self, legal_entity_id):
        """BUG-JOURNAL-003: even the user who locked the journal cannot
        unlock it, because `_ensure_editable("unlock")` raises before the
        method's own locked_by == user_id check is ever reached."""
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        locked = journal.lock("user_a")
        with pytest.raises(ValueError, match="Cannot unlock: journal is locked"):
            locked.unlock("user_a")

    def test_unlock_by_wrong_user_also_currently_raises_with_same_message(self, legal_entity_id):
        """Confirms the wrong-user branch is unreachable dead code today:
        the error message is identical to the correct-user case."""
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        locked = journal.lock("user_a")
        with pytest.raises(ValueError, match="Cannot unlock: journal is locked"):
            locked.unlock("someone_else")


# ============================================================================
# Line management
# ============================================================================


class TestLineManagement:
    def test_add_line_to_an_already_balanced_journal_always_raises(self, legal_entity_id):
        """
        Because __post_init__ enforces balance at construction time, any
        existing Journal already has total_debit == total_credit. Adding a
        single new one-sided line (debit-only or credit-only, amount > 0)
        can therefore never keep the journal balanced -- it necessarily
        shifts one side by the new line's amount. In practice, add_line()
        can only ever succeed as part of a larger workflow that replaces
        multiple lines at once (which this method does not support), so it
        always raises for a standalone call on a valid journal.
        """
        journal = make_journal(legal_entity_id=legal_entity_id)
        new_line = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "5000", "Expense", Decimal("50"), "extra debit", legal_entity_id
        )
        with pytest.raises(ValueError, match="would be unbalanced"):
            journal.add_line(new_line)

    def test_remove_line_not_found_raises(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="not found"):
            journal.remove_line(uuid4())

    def test_remove_line_that_unbalances_raises(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        debit_line_id = journal.lines[0].line_id
        with pytest.raises(ValueError, match="would be unbalanced"):
            journal.remove_line(debit_line_id)

    def test_update_line_not_found_raises(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        replacement = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "1000", "Cash", Decimal("100"), "not found test", legal_entity_id
        )
        with pytest.raises(ValueError, match="not found"):
            journal.update_line(uuid4(), replacement, "user_a")

    def test_update_line_that_unbalances_raises(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        debit_line_id = journal.lines[0].line_id
        replacement = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "1000", "Cash", Decimal("999"), "changed", legal_entity_id
        )
        with pytest.raises(ValueError, match="would be unbalanced"):
            journal.update_line(debit_line_id, replacement, "user_a")

    def test_update_line_balanced_succeeds(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        debit_line_id = journal.lines[0].line_id
        replacement = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "1000", "Cash Renamed", Decimal("100"), "changed", legal_entity_id
        )
        updated = journal.update_line(debit_line_id, replacement, "user_a")
        assert updated.is_balanced()
        assert any(l.account_name == "Cash Renamed" for l in updated.lines)

    def test_update_line_on_posted_journal_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        replacement = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "1000", "Cash", Decimal("100"), "not found test", legal_entity_id
        )
        with pytest.raises(ValueError, match="immutable"):
            journal.update_line(journal.lines[0].line_id, replacement, "user_a")


# ============================================================================
# update_metadata
# ============================================================================


class TestUpdateMetadata:
    def test_description_change_creates_new_version(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        updated = journal.update_metadata("user_b", description="Updated description")
        assert updated.description == "Updated description"
        assert updated.version == journal.version + 1

    def test_no_changes_returns_same_instance(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        result = journal.update_metadata("user_b")
        assert result is journal

    def test_update_on_posted_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError, match="immutable"):
            journal.update_metadata("user_b", description="new")

    def test_reference_change(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id, reference="OLD")
        updated = journal.update_metadata("user_b", reference="NEW")
        assert updated.reference == "NEW"


# ============================================================================
# validate()
# ============================================================================


class TestValidate:
    def test_valid_journal_has_no_errors(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        assert journal.validate() == []

    def test_unbalanced_state_raises_immediately(self, legal_entity_id):
        # Journal is a mutable (non-frozen) dataclass, so we can mutate
        # `.lines` directly after construction to reach an unbalanced state
        # that bypasses __post_init__'s own guard.
        journal = make_journal(legal_entity_id=legal_entity_id)
        extra = JournalLineVO.create_debit(
            journal.journal_id, uuid4(), "9999", "X", Decimal("1"), "extra unbalance", legal_entity_id
        )
        journal.lines = journal.lines + [extra]
        with pytest.raises(ValueError, match="not balanced"):
            journal.validate()


# ============================================================================
# clone()
# ============================================================================


class TestClone:
    def test_clone_produces_new_id_and_draft_status(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.DRAFT, legal_entity_id=legal_entity_id)
        cloned = journal.clone()
        assert cloned.journal_id != journal.journal_id
        assert cloned.status == JournalStatus.DRAFT
        assert cloned.version == 1
        assert cloned.journal_number == f"COPY-{journal.journal_number}"

    def test_clone_preserves_line_amounts_and_sides(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        cloned = journal.clone()
        assert len(cloned.lines) == len(journal.lines)
        assert cloned.is_balanced()

    def test_clone_from_posted_raises(self, legal_entity_id):
        journal = make_journal(status=JournalStatus.POSTED, legal_entity_id=legal_entity_id)
        with pytest.raises(ValueError):
            journal.clone()


# ============================================================================
# snapshot() / restore_from_snapshot()
# ============================================================================


class TestSnapshot:
    def test_snapshot_contains_expected_keys(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        snap = journal.snapshot()
        assert snap["aggregate_id"] == str(journal.journal_id)
        assert snap["aggregate_type"] == "Journal"
        assert "hash" in snap
        assert snap["state"]["total_debit"] == "100"

    def test_snapshot_records_audit_entry(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        journal.snapshot()
        assert journal.audit_trail[-1]["action"] == "snapshot_created"

    def test_restore_from_snapshot_of_same_aggregate_succeeds(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        snap = journal.snapshot()
        journal.restore_from_snapshot(snap)  # should not raise
        assert journal.audit_trail[-1]["action"] == "restored_from_snapshot"

    def test_restore_from_snapshot_of_different_aggregate_raises(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        fake_snapshot = {"aggregate_id": str(uuid4())}
        with pytest.raises(ValueError, match="different aggregate"):
            journal.restore_from_snapshot(fake_snapshot)


# ============================================================================
# to_dict() / from_dict()
# ============================================================================


class TestSerialization:
    def test_to_dict_contains_expected_fields(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        d = journal.to_dict()
        assert d["journal_number"] == "JRN-001"
        assert d["status"] == "draft"
        assert d["lines_count"] == 2
        assert len(d["lines"]) == 2

    def test_from_dict_round_trip(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id, reference="REF-1")
        d = journal.to_dict()
        restored = Journal.from_dict(d)
        assert restored.journal_id == journal.journal_id
        assert restored.total_debit == journal.total_debit
        assert restored.reference == "REF-1"
        assert len(restored.lines) == len(journal.lines)

    def test_from_dict_defaults_version_to_1(self, legal_entity_id):
        journal = make_journal(legal_entity_id=legal_entity_id)
        d = journal.to_dict()
        del d["version"]
        restored = Journal.from_dict(d)
        assert restored.version == 1


# ============================================================================
# JournalRepository — unimplemented protocol
# ============================================================================


class TestJournalRepository:
    @pytest.fixture
    def repo(self):
        return JournalRepository()

    async def test_get_by_id_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_id(uuid4(), uuid4())

    async def test_get_by_number_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_number("JRN-1", uuid4())

    async def test_get_by_date_range_not_implemented(self, repo):
        now = datetime.now(UTC)
        with pytest.raises(NotImplementedError):
            await repo.get_by_date_range(uuid4(), now - timedelta(days=30), now)

    async def test_get_by_status_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_by_status(uuid4(), JournalStatus.DRAFT)

    async def test_get_pending_approval_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.get_pending_approval(uuid4())

    async def test_save_not_implemented(self, repo, legal_entity_id):
        with pytest.raises(NotImplementedError):
            await repo.save(make_journal(legal_entity_id=legal_entity_id))

    async def test_delete_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.delete(uuid4(), uuid4())

    async def test_exists_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.exists("JRN-1", uuid4())

    async def test_count_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            await repo.count(uuid4())
