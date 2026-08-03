# test_immutability_enforcer.py
# Comprehensive tests for kernel/immutable_laws/immutability_enforcer.py
# All external dependencies are mocked; tests run without external infrastructure.

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kernel.immutable_laws.immutability_enforcer import (
    BaseImmutabilityEnforcer,
    ImmutabilityEnforcer,
    ImmutabilityLawViolation,
    ImmutabilityViolationRecord,
    ImmutabilityViolationSeverity,
    Journal,
    JournalStatus,
    _FallbackJournalRepository,
    get_immutability_enforcer,
)


# ----------------------------------------------------------------------
# Enums & Value Objects
# ----------------------------------------------------------------------
class TestJournalStatus:
    def test_members_exist(self):
        assert hasattr(JournalStatus, "DRAFT")
        assert hasattr(JournalStatus, "SUBMITTED")
        assert hasattr(JournalStatus, "APPROVED")
        assert hasattr(JournalStatus, "POSTED")
        assert hasattr(JournalStatus, "REVERSED")
        assert hasattr(JournalStatus, "ARCHIVED")
        assert hasattr(JournalStatus, "VOID")

    def test_member_is_instance(self):
        assert isinstance(JournalStatus.DRAFT, JournalStatus)


class TestJournal:
    def test_construction(self):
        journal = Journal(
            journal_id=uuid4(),
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
            created_at=datetime.now(UTC),
            is_reversed=False,
            reversal_journal_id=None,
        )
        assert isinstance(journal, Journal)

    def test_is_balanced(self):
        journal = Journal(
            journal_id=uuid4(),
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100.00"),
            total_credit=Decimal("100.00"),
            created_at=datetime.now(UTC),
        )
        assert journal.is_balanced() is True
        journal.total_credit = Decimal("99.999")
        assert journal.is_balanced() is False


class Test_FallbackJournalRepository:
    @pytest.fixture
    def repo(self):
        return _FallbackJournalRepository()

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, repo):
        result = await repo.get_by_id(uuid4(), uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_add_and_get_by_id(self, repo):
        journal_id = uuid4()
        journal = Journal(
            journal_id=journal_id,
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            created_at=datetime.now(UTC),
        )
        repo.add_journal(journal)
        found = await repo.get_by_id(journal_id, uuid4())
        assert found is journal

    @pytest.mark.asyncio
    async def test_get_by_number(self, repo):
        journal_id = uuid4()
        journal = Journal(
            journal_id=journal_id,
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            created_at=datetime.now(UTC),
        )
        repo.add_journal(journal)
        found = await repo.get_by_number("JRN-001", uuid4())
        assert found is journal

    @pytest.mark.asyncio
    async def test_update_status(self, repo):
        journal_id = uuid4()
        journal = Journal(
            journal_id=journal_id,
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            created_at=datetime.now(UTC),
        )
        repo.add_journal(journal)
        result = await repo.update_status(journal_id, uuid4(), JournalStatus.SUBMITTED, "user")
        assert result is True
        updated = await repo.get_by_id(journal_id, uuid4())
        assert updated.status == JournalStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_update_status_not_found(self, repo):
        result = await repo.update_status(uuid4(), uuid4(), JournalStatus.SUBMITTED, "user")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_as_reversed(self, repo):
        journal_id = uuid4()
        rev_id = uuid4()
        journal = Journal(
            journal_id=journal_id,
            journal_number="JRN-001",
            status=JournalStatus.POSTED,
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            created_at=datetime.now(UTC),
        )
        repo.add_journal(journal)
        result = await repo.mark_as_reversed(
            journal_id, uuid4(), rev_id, "user", datetime.now(UTC)
        )
        assert result is True
        updated = await repo.get_by_id(journal_id, uuid4())
        assert updated.status == JournalStatus.REVERSED
        assert updated.is_reversed is True
        assert updated.reversal_journal_id == rev_id

    @pytest.mark.asyncio
    async def test_mark_as_reversed_not_found(self, repo):
        result = await repo.mark_as_reversed(
            uuid4(), uuid4(), uuid4(), "user", datetime.now(UTC)
        )
        assert result is False

    def test_clear(self, repo):
        journal = Journal(
            journal_id=uuid4(),
            journal_number="JRN-001",
            status=JournalStatus.DRAFT,
            total_debit=Decimal("100"),
            total_credit=Decimal("100"),
            created_at=datetime.now(UTC),
        )
        repo.add_journal(journal)
        repo.clear()
        assert len(repo._journals) == 0
        assert len(repo._journal_by_number) == 0


class TestImmutabilityViolationSeverity:
    def test_members_exist(self):
        assert hasattr(ImmutabilityViolationSeverity, "CATASTROPHIC")
        assert hasattr(ImmutabilityViolationSeverity, "CRITICAL")
        assert hasattr(ImmutabilityViolationSeverity, "HIGH")
        assert hasattr(ImmutabilityViolationSeverity, "MEDIUM")
        assert hasattr(ImmutabilityViolationSeverity, "LOW")

    def test_member_is_instance(self):
        assert isinstance(ImmutabilityViolationSeverity.CATASTROPHIC, ImmutabilityViolationSeverity)


class TestImmutabilityViolationRecord:
    def test_construction(self):
        kwargs = {
            "violation_id": uuid4(),
            "journal_id": uuid4(),
            "journal_number": "JRN-001",
            "attempted_operation": "UPDATE",
            "current_status": "POSTED",
            "user_id": "user1",
            "timestamp": datetime.now(UTC),
            "message": "test",
            "severity": ImmutabilityViolationSeverity.CRITICAL,
            "is_correction": False,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "cryptographic_hash": "",
        }
        record = ImmutabilityViolationRecord(**kwargs)
        assert record.violation_id == kwargs["violation_id"]
        # hash should be computed in post_init
        assert record.cryptographic_hash != ""

    def test_compute_hash(self):
        record = ImmutabilityViolationRecord(
            violation_id=uuid4(),
            journal_id=uuid4(),
            journal_number="JRN-001",
            attempted_operation="UPDATE",
            current_status="POSTED",
            user_id="user1",
            timestamp=datetime.now(UTC),
            message="test",
            severity=ImmutabilityViolationSeverity.CRITICAL,
            is_correction=False,
            resolved=False,
            resolved_at=None,
            resolved_by=None,
            cryptographic_hash="",
        )
        h = record.compute_hash()
        assert isinstance(h, str)
        assert len(h) == 64  # sha3_256

    def test_hash_mismatch_raises(self):
        kwargs = {
            "violation_id": uuid4(),
            "journal_id": uuid4(),
            "journal_number": "JRN-001",
            "attempted_operation": "UPDATE",
            "current_status": "POSTED",
            "user_id": "user1",
            "timestamp": datetime.now(UTC),
            "message": "test",
            "severity": ImmutabilityViolationSeverity.CRITICAL,
            "is_correction": False,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "cryptographic_hash": "wronghash",
        }
        with pytest.raises(ValueError, match="Cryptographic hash mismatch"):
            ImmutabilityViolationRecord(**kwargs)

    def test_resolve(self):
        kwargs = {
            "violation_id": uuid4(),
            "journal_id": uuid4(),
            "journal_number": "JRN-001",
            "attempted_operation": "UPDATE",
            "current_status": "POSTED",
            "user_id": "user1",
            "timestamp": datetime.now(UTC),
            "message": "test",
            "severity": ImmutabilityViolationSeverity.CRITICAL,
            "is_correction": False,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "cryptographic_hash": "",
        }
        record = ImmutabilityViolationRecord(**kwargs)
        resolved = record.resolve("admin")
        assert resolved.resolved is True
        assert resolved.resolved_by == "admin"
        assert resolved.resolved_at is not None

    def test_to_dict(self):
        kwargs = {
            "violation_id": uuid4(),
            "journal_id": uuid4(),
            "journal_number": "JRN-001",
            "attempted_operation": "UPDATE",
            "current_status": "POSTED",
            "user_id": "user1",
            "timestamp": datetime.now(UTC),
            "message": "test",
            "severity": ImmutabilityViolationSeverity.CRITICAL,
            "is_correction": False,
            "resolved": False,
            "resolved_at": None,
            "resolved_by": None,
            "cryptographic_hash": "",
        }
        record = ImmutabilityViolationRecord(**kwargs)
        d = record.to_dict()
        assert d["journal_id"] == str(kwargs["journal_id"])
        assert d["severity"] == "CRITICAL"


class TestBaseImmutabilityEnforcer:
    def test_class_defined(self):
        assert BaseImmutabilityEnforcer is not None


# ----------------------------------------------------------------------
# ImmutabilityEnforcer
# ----------------------------------------------------------------------
@pytest.fixture
def mock_repo():
    repo = MagicMock(spec=_FallbackJournalRepository)
    repo.get_by_id = AsyncMock()
    repo.update_status = AsyncMock(return_value=True)
    repo.mark_as_reversed = AsyncMock(return_value=True)
    return repo


@pytest.fixture
def enforcer(mock_repo):
    return ImmutabilityEnforcer(journal_repository=mock_repo)


@pytest.fixture
def sample_journal():
    return Journal(
        journal_id=uuid4(),
        journal_number="JRN-001",
        status=JournalStatus.DRAFT,
        total_debit=Decimal("100.00"),
        total_credit=Decimal("100.00"),
        created_at=datetime.now(UTC),
        is_reversed=False,
        reversal_journal_id=None,
    )


class TestImmutabilityEnforcer:
    def test_construction(self, enforcer):
        assert isinstance(enforcer, ImmutabilityEnforcer)
        assert enforcer._enabled is True
        assert enforcer._max_history == 10000

    def test_enable(self, enforcer):
        enforcer.enable(False)
        assert enforcer._enabled is False
        enforcer.enable(True)
        assert enforcer._enabled is True

    # ----- Entity methods -----
    def test_check_valid(self, enforcer):
        journal_id = uuid4()
        legal_entity_id = uuid4()
        errors = enforcer.check(
            {
                "journal_id": str(journal_id),
                "legal_entity_id": str(legal_entity_id),
                "operation": "UPDATE",
            }
        )
        assert errors == []

    def test_check_invalid_missing(self, enforcer):
        errors = enforcer.check({})
        assert "journal_id is required" in errors
        assert "legal_entity_id is required" in errors

    def test_check_invalid_uuid(self, enforcer):
        errors = enforcer.check(
            {"journal_id": "not-a-uuid", "legal_entity_id": "not-a-uuid"}
        )
        assert any("valid UUID" in e for e in errors)

    def test_validate(self, enforcer):
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

    def test_to_dict(self, enforcer):
        d = enforcer.to_dict()
        assert "enabled" in d
        assert "max_history" in d
        assert "violations_count" in d
        assert "version" in d

    def test_from_dict(self, enforcer):
        data = {"enabled": False, "max_history": 5000, "version": 2}
        new = ImmutabilityEnforcer.from_dict(data)
        assert new._enabled is False
        assert new._max_history == 5000
        assert new._version == 2

    def test_clone(self, enforcer):
        clone = enforcer.clone()
        assert clone is not enforcer
        assert clone._enabled == enforcer._enabled
        assert clone._max_history == enforcer._max_history
        assert clone._version == enforcer._version + 1

    def test_snapshot(self, enforcer):
        snap = enforcer.snapshot()
        assert "version" in snap
        assert "violations_count" in snap
        assert "enabled" in snap
        assert "timestamp" in snap

    def test_version(self, enforcer):
        assert enforcer.version() == enforcer._version

    def test_audit_trail(self, enforcer):
        assert enforcer.audit_trail() == []
        enforcer.touch("admin")
        trail = enforcer.audit_trail(limit=10)
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"

    def test_touch(self, enforcer):
        old_version = enforcer.version()
        enforcer.touch("admin")
        assert enforcer.version() == old_version + 1
        trail = enforcer.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "admin"

    # ----- enforce_immutability -----
    @pytest.mark.asyncio
    async def test_enforce_immutability_disabled(self, enforcer, mock_repo):
        enforcer.enable(False)
        result, violation = await enforcer.enforce_immutability(uuid4(), uuid4())
        assert result is True
        assert violation is None
        mock_repo.get_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_immutability_journal_not_found(self, enforcer, mock_repo):
        mock_repo.get_by_id.return_value = None
        result, violation = await enforcer.enforce_immutability(uuid4(), uuid4())
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_posted_read_allowed(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id, uuid4(), operation="READ"
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_posted_update_violation(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        with pytest.raises(ImmutabilityLawViolation) as exc:
            await enforcer.enforce_immutability(
                sample_journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=True
            )
        assert "immutable" in str(exc.value)
        # Check that violation was recorded
        violations = enforcer.get_violations()
        assert len(violations) == 1
        assert violations[0].journal_id == sample_journal.journal_id

    @pytest.mark.asyncio
    async def test_enforce_immutability_correction_authorized(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        # Authorized via bypass roles
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id,
            uuid4(),
            operation="REVERSE",
            is_correction=True,
            correction_reference=sample_journal.journal_id,
            bypass_authorization=["super_admin"],
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_correction_unauthorized(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        # Not authorized (bypass list empty, user not super_admin)
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user"):
            with pytest.raises(ImmutabilityLawViolation) as exc:
                await enforcer.enforce_immutability(
                    sample_journal.journal_id,
                    uuid4(),
                    operation="REVERSE",
                    is_correction=True,
                    correction_reference=sample_journal.journal_id,
                    raise_on_violation=True,
                )
            assert "Unauthorized correction" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_immutability_correction_missing_ref(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user"):
            with pytest.raises(ImmutabilityLawViolation) as exc:
                await enforcer.enforce_immutability(
                    sample_journal.journal_id,
                    uuid4(),
                    operation="REVERSE",
                    is_correction=True,
                    raise_on_violation=True,
                )
            assert "missing reference" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_immutability_emergency_override(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.POSTED
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id,
            uuid4(),
            operation="DELETE",
            bypass_authorization=["ceo"],  # in emergency override
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_draft_update_allowed(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.DRAFT
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id, uuid4(), operation="UPDATE"
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_submitted_update_without_bypass(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.SUBMITTED
        mock_repo.get_by_id.return_value = sample_journal
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user"):
            with pytest.raises(ImmutabilityLawViolation) as exc:
                await enforcer.enforce_immutability(
                    sample_journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=True
                )
            assert "requires authorization" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_immutability_submitted_update_with_bypass(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.SUBMITTED
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id, uuid4(), operation="UPDATE", bypass_authorization=["admin"]
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_delete_draft_allowed(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.DRAFT
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_immutability(
            sample_journal.journal_id, uuid4(), operation="DELETE"
        )
        assert result is True
        assert violation is None

    @pytest.mark.asyncio
    async def test_enforce_immutability_delete_submitted_violation(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.SUBMITTED
        mock_repo.get_by_id.return_value = sample_journal
        with pytest.raises(ImmutabilityLawViolation) as exc:
            await enforcer.enforce_immutability(
                sample_journal.journal_id, uuid4(), operation="DELETE", raise_on_violation=True
            )
        assert "Cannot delete" in str(exc.value)

    # ----- enforce_before_posting -----
    @pytest.mark.asyncio
    async def test_enforce_before_posting_disabled(self, enforcer, mock_repo):
        enforcer.enable(False)
        result, violation = await enforcer.enforce_before_posting(uuid4(), uuid4())
        assert result is True
        assert violation is None
        mock_repo.get_by_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_enforce_before_posting_not_found(self, enforcer, mock_repo):
        mock_repo.get_by_id.return_value = None
        with pytest.raises(ImmutabilityLawViolation) as exc:
            await enforcer.enforce_before_posting(uuid4(), uuid4(), raise_on_violation=True)
        assert "not found" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_before_posting_wrong_status(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.DRAFT
        mock_repo.get_by_id.return_value = sample_journal
        with pytest.raises(ImmutabilityLawViolation) as exc:
            await enforcer.enforce_before_posting(
                sample_journal.journal_id, uuid4(), raise_on_violation=True
            )
        assert "must be APPROVED or SUBMITTED" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_before_posting_unbalanced(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.APPROVED
        sample_journal.total_credit = Decimal("99.00")
        mock_repo.get_by_id.return_value = sample_journal
        with pytest.raises(ImmutabilityLawViolation) as exc:
            await enforcer.enforce_before_posting(
                sample_journal.journal_id, uuid4(), raise_on_violation=True
            )
        assert "not balanced" in str(exc.value)

    @pytest.mark.asyncio
    async def test_enforce_before_posting_success(self, enforcer, mock_repo, sample_journal):
        sample_journal.status = JournalStatus.APPROVED
        sample_journal.total_credit = Decimal("100.00")
        mock_repo.get_by_id.return_value = sample_journal
        result, violation = await enforcer.enforce_before_posting(
            sample_journal.journal_id, uuid4(), raise_on_violation=True
        )
        assert result is True
        assert violation is None

    # ----- record_posted_state -----
    @pytest.mark.asyncio
    async def test_record_posted_state_success(self, enforcer, mock_repo):
        journal_id = uuid4()
        legal_id = uuid4()
        result = await enforcer.record_posted_state(journal_id, legal_id, "poster")
        assert result is True
        mock_repo.update_status.assert_awaited_once_with(
            journal_id, legal_id, JournalStatus.POSTED, "poster"
        )

    @pytest.mark.asyncio
    async def test_record_reversed_state_success(self, enforcer, mock_repo):
        journal_id = uuid4()
        legal_id = uuid4()
        rev_id = uuid4()
        result = await enforcer.record_reversed_state(journal_id, legal_id, rev_id, "reverser")
        assert result is True
        mock_repo.mark_as_reversed.assert_awaited_once()

    # ----- get_allowed_states_for_operation -----
    def test_get_allowed_states_for_operation_read(self, enforcer):
        states = enforcer.get_allowed_states_for_operation("READ")
        assert len(states) == len(list(JournalStatus))

    def test_get_allowed_states_for_operation_update(self, enforcer):
        states = enforcer.get_allowed_states_for_operation("UPDATE")
        expected = [JournalStatus.DRAFT, JournalStatus.SUBMITTED, JournalStatus.APPROVED]
        assert set(states) == set(expected)

    def test_get_allowed_states_for_operation_delete(self, enforcer):
        states = enforcer.get_allowed_states_for_operation("DELETE")
        assert states == [JournalStatus.DRAFT]

    def test_get_allowed_states_for_operation_reverse(self, enforcer):
        states = enforcer.get_allowed_states_for_operation("REVERSE")
        expected = [JournalStatus.POSTED, JournalStatus.REVERSED, JournalStatus.ARCHIVED]
        assert set(states) == set(expected)

    def test_get_allowed_states_for_operation_unknown(self, enforcer):
        states = enforcer.get_allowed_states_for_operation("UNKNOWN")
        assert states == []

    # ----- get_violations, resolve_violation, statistics, reset -----
    def test_get_violations_empty(self, enforcer):
        assert enforcer.get_violations() == []

    def test_get_violations_filter(self, enforcer, mock_repo):
        # Create a violation by calling enforce_immutability with raise_on_violation=False
        # We'll patch get_current_user to control user id.
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user1"):
            # Create a posted journal
            journal = Journal(
                journal_id=uuid4(),
                journal_number="JRN-002",
                status=JournalStatus.POSTED,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                created_at=datetime.now(UTC),
            )
            mock_repo.get_by_id.return_value = journal
            # Trigger violation
            result, violation = enforcer.enforce_immutability(
                journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=False
            )
            assert result is False
            assert violation is not None
            # Now get violations
            all_v = enforcer.get_violations()
            assert len(all_v) == 1
            # Filter by journal_id
            filtered = enforcer.get_violations(journal_id=journal.journal_id)
            assert len(filtered) == 1
            # Filter by user_id
            filtered = enforcer.get_violations(user_id="user1")
            assert len(filtered) == 1
            # Filter by severity
            filtered = enforcer.get_violations(min_severity=ImmutabilityViolationSeverity.CRITICAL)
            assert len(filtered) == 1
            filtered = enforcer.get_violations(min_severity=ImmutabilityViolationSeverity.HIGH)
            assert len(filtered) == 0
            # unresolved only
            filtered = enforcer.get_violations(unresolved_only=True)
            assert len(filtered) == 1

    def test_resolve_violation(self, enforcer, mock_repo):
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user1"):
            journal = Journal(
                journal_id=uuid4(),
                journal_number="JRN-003",
                status=JournalStatus.POSTED,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                created_at=datetime.now(UTC),
            )
            mock_repo.get_by_id.return_value = journal
            _result, violation = enforcer.enforce_immutability(
                journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=False
            )
            assert violation is not None
            violation_id = violation.violation_id
            # Resolve
            resolved = enforcer.resolve_violation(violation_id, "admin")
            assert resolved is not None
            assert resolved.resolved is True
            assert resolved.resolved_by == "admin"
            # Cannot resolve again
            resolved2 = enforcer.resolve_violation(violation_id, "admin")
            assert resolved2 is None

    def test_get_statistics(self, enforcer, mock_repo):
        # Initially no violations
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 0
        # Add one violation
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user1"):
            journal = Journal(
                journal_id=uuid4(),
                journal_number="JRN-004",
                status=JournalStatus.POSTED,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                created_at=datetime.now(UTC),
            )
            mock_repo.get_by_id.return_value = journal
            enforcer.enforce_immutability(
                journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=False
            )
        stats = enforcer.get_statistics()
        assert stats["total_violations"] == 1
        assert stats["unresolved_violations"] == 1
        assert "CRITICAL" in stats["by_severity"]
        assert stats["by_operation"]["UPDATE"] == 1
        assert stats["correction_attempts"] == 0
        assert stats["enabled"] is True
        assert stats["version"] == enforcer.version()

    def test_reset(self, enforcer, mock_repo):
        # Add some state
        with patch("kernel.immutable_laws.immutability_enforcer.get_current_user", return_value="user1"):
            journal = Journal(
                journal_id=uuid4(),
                journal_number="JRN-005",
                status=JournalStatus.POSTED,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                created_at=datetime.now(UTC),
            )
            mock_repo.get_by_id.return_value = journal
            enforcer.enforce_immutability(
                journal.journal_id, uuid4(), operation="UPDATE", raise_on_violation=False
            )
        enforcer.touch("admin")
        assert len(enforcer._violations) == 1
        assert enforcer.version() > 1
        enforcer.reset()
        assert len(enforcer._violations) == 0
        assert enforcer._enabled is True
        assert enforcer._audit_trail == []
        mock_repo.clear.assert_called_once()

    # ----- Private method tests (direct) -----
    def test_create_violation(self, enforcer):
        journal_id = uuid4()
        violation = enforcer._create_violation(
            journal_id=journal_id,
            journal_number="JRN-006",
            attempted_operation="TEST",
            current_status="DRAFT",
            user_id="user1",
            severity=ImmutabilityViolationSeverity.LOW,
            message="test message",
            is_correction=False,
        )
        assert isinstance(violation, ImmutabilityViolationRecord)
        assert violation.journal_id == journal_id
        assert violation.severity == ImmutabilityViolationSeverity.LOW
        assert violation.cryptographic_hash != ""

    def test_record_violation(self, enforcer):
        journal_id = uuid4()
        violation = enforcer._create_violation(
            journal_id=journal_id,
            journal_number="JRN-007",
            attempted_operation="TEST",
            current_status="DRAFT",
            user_id="user1",
            severity=ImmutabilityViolationSeverity.LOW,
            message="test message",
            is_correction=False,
        )
        enforcer._record_violation(violation)
        assert len(enforcer._violations) == 1
        assert enforcer._violations[0] is violation
        # Check audit trail
        trail = enforcer.audit_trail()
        assert any("VIOLATION" in entry["action"] for entry in trail)

    def test_is_authorized_for_correction(self, enforcer):
        # With bypass list containing emergency role
        assert enforcer._is_authorized_for_correction(
            "user", bypass_authorization=["super_admin"]
        ) is True
        assert enforcer._is_authorized_for_correction(
            "user", bypass_authorization=["audit_committee"]
        ) is True
        # Without bypass list, only specific users
        assert enforcer._is_authorized_for_correction(
            "super_admin", bypass_authorization=None
        ) is True
        assert enforcer._is_authorized_for_correction(
            "emergency_admin", bypass_authorization=None
        ) is True
        assert enforcer._is_authorized_for_correction(
            "regular_user", bypass_authorization=None
        ) is False
        # With bypass list but no match
        assert enforcer._is_authorized_for_correction(
            "user", bypass_authorization=["manager"]
        ) is False


# ----------------------------------------------------------------------
# Singleton accessor
# ----------------------------------------------------------------------
def test_get_immutability_enforcer():
    instance1 = get_immutability_enforcer()
    instance2 = get_immutability_enforcer()
    assert instance1 is instance2
    assert isinstance(instance1, ImmutabilityEnforcer)
