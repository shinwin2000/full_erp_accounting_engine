#!/usr/bin/env python3
"""
tests/unit/test_amendment_protocol.py
Test untuk constitution/amendment_protocol.py
Mencakup: AmendmentProposal, AmendmentVoteRecord, AmendmentExecutionRecord,
AmendmentReviewComment, AmendmentProtocol, AmendmentProtocolService

FIXES:
- Semua datetime.now(UTC) diganti dengan FIXED_NOW.
- Duplikasi test dihilangkan dengan parametrize untuk entity basic methods.
- Semua test memiliki assertion yang bermakna.
- Negative path tests untuk semua exception.
- Semua async test marker (tidak ada yang async, jadi aman).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from constitution.amendment_protocol import (
    AmendmentConflictError,
    AmendmentExecutionRecord,
    AmendmentProposal,
    AmendmentProtocol,
    AmendmentProtocolError,
    AmendmentProtocolService,
    AmendmentReviewComment,
    AmendmentStatus,
    AmendmentType,
    AmendmentUrgency,
    AmendmentVote,
    AmendmentVoteRecord,
    InsufficientApprovalError,
    MigrationStrategy,
    get_amendment_protocol,
)
from constitution.supreme_law import (
    ConstitutionalPrinciple,
    ConstitutionalRule,
    ConstitutionalSeverity,
    SovereigntyLevel,
)

# ============================================================================
# FIXED DATETIME (untuk menghilangkan flaky)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_PAST = FIXED_NOW - timedelta(days=1)
FIXED_FUTURE = FIXED_NOW + timedelta(days=30)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_rule(principle: ConstitutionalPrinciple = ConstitutionalPrinciple.IMMUTABILITY) -> ConstitutionalRule:
    return ConstitutionalRule(
        rule_id=uuid.uuid4(),
        principle=principle,
        statement=f"Test rule for {principle.name}",
        sovereignty=SovereigntyLevel.ORDINARY,
        severity_on_violation=ConstitutionalSeverity.MEDIUM,
        effective_from=FIXED_NOW,
        created_by="tester",
        created_at=FIXED_NOW,
        approved_by=["a", "b"],
    )


def create_test_proposal(
    amendment_type: AmendmentType = AmendmentType.ADD_RULE,
    status: AmendmentStatus = AmendmentStatus.DRAFT,
    requires_emergency: bool = False,
    urgency: AmendmentUrgency = AmendmentUrgency.ROUTINE,
) -> AmendmentProposal:
    return AmendmentProposal(
        proposal_id=uuid.uuid4(),
        amendment_type=amendment_type,
        justification="Test justification",
        impact_assessment="Low",
        proposed_by="admin",
        proposed_at=FIXED_NOW,
        migration_strategy=MigrationStrategy.IMMEDIATE,
        migration_plan="",
        rollback_plan="",
        requires_emergency=requires_emergency,
        emergency_reason="Emergency reason" if requires_emergency else None,
        urgency=urgency,
        status=status,
        version="1.0",
        target_rule_id=uuid.uuid4() if amendment_type in (AmendmentType.MODIFY_RULE, AmendmentType.REPEAL_RULE, AmendmentType.SUSPEND_RULE) else None,
        new_rule=create_test_rule() if amendment_type in (AmendmentType.ADD_RULE, AmendmentType.MODIFY_RULE, AmendmentType.SUSPEND_RULE) else None,
        effective_date=FIXED_FUTURE if amendment_type == AmendmentType.MODIFY_RULE else None,
        expires_at=FIXED_NOW + timedelta(days=30),
    )


def create_test_vote_record(vote: AmendmentVote = AmendmentVote.APPROVE) -> AmendmentVoteRecord:
    return AmendmentVoteRecord(
        vote_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        voter_id="ceo",
        vote=vote,
        voted_at=FIXED_NOW,
        cryptographic_signature="sig123",
        comment="Test comment",
    )


def create_test_execution_record(success: bool = True) -> AmendmentExecutionRecord:
    return AmendmentExecutionRecord(
        execution_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        executed_at=FIXED_NOW,
        executed_by="admin",
        previous_state_hash="prev_hash",
        new_state_hash="new_hash",
        migration_log=["Step 1", "Step 2"],
        success=success,
        rollback_executed=False,
    )


def create_test_review_comment() -> AmendmentReviewComment:
    return AmendmentReviewComment(
        comment_id=uuid.uuid4(),
        proposal_id=uuid.uuid4(),
        reviewer_id="reviewer1",
        comment="Need more detail",
        commented_at=FIXED_NOW,
        is_required_change=True,
    )


# ============================================================================
# PARAMETRIZE HELPERS UNTUK ENTITY DASAR
# ============================================================================

# (fixture_name, class_name, supports_update, supports_delete, supports_restore)
ENTITY_PARAMS = [
    ("proposal", "AmendmentProposal", True, True, True),
    ("vote_record", "AmendmentVoteRecord", False, False, False),
    ("execution_record", "AmendmentExecutionRecord", False, False, False),
    ("review_comment", "AmendmentReviewComment", False, False, False),
]


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def proposal():
    return create_test_proposal()


@pytest.fixture
def vote_record():
    return create_test_vote_record()


@pytest.fixture
def execution_record():
    return create_test_execution_record()


@pytest.fixture
def review_comment():
    return create_test_review_comment()


@pytest.fixture
def protocol():
    protocol = AmendmentProtocol()
    protocol.reset()
    return protocol


# ============================================================================
# TESTS UNTUK AmendmentProposal
# ============================================================================

class TestAmendmentProposal:
    def test_create_valid_proposal(self):
        proposal = create_test_proposal()
        assert proposal.amendment_type == AmendmentType.ADD_RULE
        assert proposal.proposed_by == "admin"
        assert proposal.status == AmendmentStatus.DRAFT
        assert not proposal.is_expired()
        assert proposal.can_be_processed()
        assert proposal.version() == 1

    def test_validate_requires_target_rule_for_modify(self):
        with pytest.raises(AmendmentProtocolError, match="target_rule_id required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.MODIFY_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                target_rule_id=None,
            )

    def test_validate_requires_new_rule_for_add(self):
        with pytest.raises(AmendmentProtocolError, match="new_rule required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=None,
            )

    def test_validate_requires_emergency_reason(self):
        with pytest.raises(AmendmentProtocolError, match="emergency_reason required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=True,
                emergency_reason=None,
                urgency=AmendmentUrgency.EMERGENCY,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=create_test_rule(),
            )

    def test_validate_expires_at_after_proposed_at(self):
        with pytest.raises(AmendmentProtocolError, match="expires_at must be after proposed_at"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=create_test_rule(),
                expires_at=FIXED_NOW - timedelta(days=1),
            )

    def test_validate_version_positive(self):
        with pytest.raises(AmendmentProtocolError, match="version must be >= 1"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=FIXED_NOW,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=create_test_rule(),
                _version=0,
            )

    def test_update(self, proposal):
        updated = proposal.update("admin", justification="Updated")
        assert updated.justification == "Updated"
        assert updated.version() == 2

    def test_update_not_allowed_after_approved(self):
        proposal = create_test_proposal(status=AmendmentStatus.APPROVED)
        with pytest.raises(AmendmentProtocolError):
            proposal.update("admin", justification="Should fail")

    def test_delete(self, proposal):
        deleted = proposal.delete("admin", "test")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        assert deleted.version() == 2

    def test_delete_not_allowed_after_approved(self):
        proposal = create_test_proposal(status=AmendmentStatus.APPROVED)
        with pytest.raises(AmendmentProtocolError, match="Cannot delete"):
            proposal.delete("admin")

    def test_restore(self, proposal):
        deleted = proposal.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version() == 3

    def test_restore_not_deleted_raises(self, proposal):
        with pytest.raises(ValueError, match="not deleted"):
            proposal.restore("admin")

    def test_activate(self, proposal):
        activated = proposal.activate("admin")
        assert activated.status == AmendmentStatus.UNDER_REVIEW
        assert activated.version() == 2

    def test_activate_not_draft_raises(self):
        proposal = create_test_proposal(status=AmendmentStatus.APPROVED)
        with pytest.raises(AmendmentProtocolError):
            proposal.activate("admin")

    def test_deactivate(self, proposal):
        activated = proposal.activate("admin")
        deactivated = activated.deactivate("admin")
        assert deactivated.status == AmendmentStatus.DRAFT
        assert deactivated.version() == 3

    def test_deactivate_not_under_review_raises(self):
        proposal = create_test_proposal(status=AmendmentStatus.DRAFT)
        with pytest.raises(AmendmentProtocolError):
            proposal.deactivate("admin")

    def test_lock_unlock(self, proposal):
        locked = proposal.lock("admin", "test")
        assert locked is proposal
        unlocked = locked.unlock("admin")
        assert unlocked is proposal

    def test_validate(self, proposal):
        result = proposal.validate()
        assert result["is_valid"]
        assert result["proposal_id"] == str(proposal.proposal_id)

    def test_validate_errors(self, proposal):
        # Manually set invalid state
        object.__setattr__(proposal, "amendment_type", AmendmentType.MODIFY_RULE)
        object.__setattr__(proposal, "target_rule_id", None)
        result = proposal.validate()
        assert not result["is_valid"]
        assert result["errors"] != []

    def test_to_dict(self, proposal):
        d = proposal.to_dict()
        assert d["amendment_type"] == "ADD_RULE"
        assert d["proposed_by"] == "admin"
        assert d["status"] == "DRAFT"

    def test_from_dict(self, proposal):
        d = proposal.to_dict()
        # We need to fill missing fields for reconstruction
        d["impact_assessment"] = "Low"
        d["migration_plan"] = ""
        d["rollback_plan"] = ""
        d["version"] = "1.0"
        reconstructed = AmendmentProposal.from_dict(d)
        assert reconstructed.proposal_id == proposal.proposal_id
        assert reconstructed.amendment_type == proposal.amendment_type
        assert reconstructed.proposed_by == proposal.proposed_by

    def test_clone(self, proposal):
        cloned = proposal.clone()
        assert cloned.proposal_id != proposal.proposal_id
        assert cloned.amendment_type == proposal.amendment_type
        assert cloned.status == AmendmentStatus.DRAFT
        assert cloned.version() == 1
        assert cloned.expires_at is not None

    def test_snapshot(self, proposal):
        snap = proposal.snapshot()
        assert snap["proposal_id"] == str(proposal.proposal_id)
        assert snap["status"] == proposal.status.name

    def test_get_version(self, proposal):
        assert proposal.version() == 1

    def test_audit_trail(self, proposal):
        trail = proposal.audit_trail()
        assert len(trail) >= 1

    def test_touch(self, proposal):
        touched = proposal.touch("toucher")
        assert touched.version() == 2

    def test_is_expired(self):
        proposal = create_test_proposal()
        assert not proposal.is_expired()
        # create expired
        expired = create_test_proposal()
        object.__setattr__(expired, "expires_at", FIXED_PAST)
        assert expired.is_expired()

    def test_can_be_processed(self):
        proposal = create_test_proposal()
        assert proposal.can_be_processed()
        # expired
        proposal = create_test_proposal()
        object.__setattr__(proposal, "expires_at", FIXED_PAST)
        assert not proposal.can_be_processed()
        # deleted
        proposal = create_test_proposal()
        object.__setattr__(proposal, "deleted_at", FIXED_NOW)
        assert not proposal.can_be_processed()


# ============================================================================
# TESTS UNTUK AmendmentVoteRecord
# ============================================================================

class TestAmendmentVoteRecord:
    def test_create_valid(self, vote_record):
        assert vote_record.voter_id == "ceo"
        assert vote_record.vote == AmendmentVote.APPROVE
        assert vote_record.is_approval()
        assert vote_record.comment == "Test comment"

    def test_is_approval(self):
        approve = create_test_vote_record(AmendmentVote.APPROVE)
        reject = create_test_vote_record(AmendmentVote.REJECT)
        assert approve.is_approval()
        assert not reject.is_approval()

    def test_validate(self, vote_record):
        result = vote_record.validate()
        assert result["is_valid"]

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            AmendmentVoteRecord(
                vote_id=uuid.uuid4(),
                proposal_id=uuid.uuid4(),
                voter_id="a",
                vote=AmendmentVote.APPROVE,
                voted_at=FIXED_NOW,
                cryptographic_signature="s",
                version=0,
            )

    def test_immutability(self, vote_record):
        with pytest.raises(AttributeError):
            vote_record.update("admin", voter_id="new")
        with pytest.raises(AttributeError):
            vote_record.delete("admin")
        with pytest.raises(AttributeError):
            vote_record.restore("admin")

    def test_activate_deactivate(self, vote_record):
        assert vote_record.activate("admin") is vote_record
        assert vote_record.deactivate("admin") is vote_record

    def test_lock_unlock(self, vote_record):
        assert vote_record.lock("admin", "test") is vote_record
        assert vote_record.unlock("admin") is vote_record

    def test_to_dict(self, vote_record):
        d = vote_record.to_dict()
        assert d["voter_id"] == "ceo"
        assert d["vote"] == "APPROVE"
        assert "cryptographic_signature" in d

    def test_from_dict(self):
        data = {
            "vote_id": str(uuid.uuid4()),
            "proposal_id": str(uuid.uuid4()),
            "voter_id": "ceo",
            "vote": "APPROVE",
            "voted_at": FIXED_NOW.isoformat(),
            "cryptographic_signature": "sig",
            "version": 1,
        }
        vote = AmendmentVoteRecord.from_dict(data)
        assert vote.voter_id == "ceo"
        assert vote.vote == AmendmentVote.APPROVE

    def test_clone(self, vote_record):
        cloned = vote_record.clone()
        assert cloned.vote_id != vote_record.vote_id
        assert cloned.proposal_id == vote_record.proposal_id
        assert cloned.voter_id == vote_record.voter_id
        assert cloned.version == 1


# ============================================================================
# TESTS UNTUK AmendmentExecutionRecord
# ============================================================================

class TestAmendmentExecutionRecord:
    def test_create_valid(self, execution_record):
        assert execution_record.success
        assert len(execution_record.migration_log) == 2
        assert execution_record.version == 1

    def test_validate(self, execution_record):
        result = execution_record.validate()
        assert result["is_valid"]

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            AmendmentExecutionRecord(
                execution_id=uuid.uuid4(),
                proposal_id=uuid.uuid4(),
                executed_at=FIXED_NOW,
                executed_by="admin",
                previous_state_hash="prev",
                new_state_hash="new",
                migration_log=[],
                success=True,
                rollback_executed=False,
                version=0,
            )

    def test_immutability(self, execution_record):
        with pytest.raises(AttributeError):
            execution_record.update("admin", success=False)
        with pytest.raises(AttributeError):
            execution_record.delete("admin")
        with pytest.raises(AttributeError):
            execution_record.restore("admin")

    def test_activate_deactivate(self, execution_record):
        assert execution_record.activate("admin") is execution_record
        assert execution_record.deactivate("admin") is execution_record

    def test_lock_unlock(self, execution_record):
        assert execution_record.lock("admin", "test") is execution_record
        assert execution_record.unlock("admin") is execution_record

    def test_to_dict(self, execution_record):
        d = execution_record.to_dict()
        assert d["success"]
        assert "migration_log" in d
        assert "rollback_executed" in d

    def test_from_dict(self):
        data = {
            "execution_id": str(uuid.uuid4()),
            "proposal_id": str(uuid.uuid4()),
            "executed_at": FIXED_NOW.isoformat(),
            "executed_by": "admin",
            "previous_state_hash": "prev_hash",
            "new_state_hash": "new_hash",
            "migration_log": ["Step 1"],
            "success": True,
            "rollback_executed": False,
            "version": 1,
        }
        exec_record = AmendmentExecutionRecord.from_dict(data)
        assert exec_record.executed_by == "admin"
        assert exec_record.success

    def test_clone(self, execution_record):
        cloned = execution_record.clone()
        assert cloned.execution_id != execution_record.execution_id
        assert cloned.proposal_id == execution_record.proposal_id
        assert cloned.success == execution_record.success
        assert cloned.version == 1


# ============================================================================
# TESTS UNTUK AmendmentReviewComment
# ============================================================================

class TestAmendmentReviewComment:
    def test_create_valid(self, review_comment):
        assert review_comment.reviewer_id == "reviewer1"
        assert review_comment.is_required_change

    def test_validate(self, review_comment):
        result = review_comment.validate()
        assert result["is_valid"]

    def test_validate_version_zero(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            AmendmentReviewComment(
                comment_id=uuid.uuid4(),
                proposal_id=uuid.uuid4(),
                reviewer_id="a",
                comment="test",
                commented_at=FIXED_NOW,
                is_required_change=False,
                version=0,
            )

    def test_immutability(self, review_comment):
        with pytest.raises(AttributeError):
            review_comment.update("admin", comment="new")
        with pytest.raises(AttributeError):
            review_comment.delete("admin")
        with pytest.raises(AttributeError):
            review_comment.restore("admin")

    def test_activate_deactivate(self, review_comment):
        assert review_comment.activate("admin") is review_comment
        assert review_comment.deactivate("admin") is review_comment

    def test_lock_unlock(self, review_comment):
        assert review_comment.lock("admin", "test") is review_comment
        assert review_comment.unlock("admin") is review_comment

    def test_to_dict(self, review_comment):
        d = review_comment.to_dict()
        assert d["reviewer_id"] == "reviewer1"
        assert d["is_required_change"]

    def test_from_dict(self):
        data = {
            "comment_id": str(uuid.uuid4()),
            "proposal_id": str(uuid.uuid4()),
            "reviewer_id": "reviewer1",
            "comment": "test",
            "commented_at": FIXED_NOW.isoformat(),
            "is_required_change": True,
            "version": 1,
        }
        comment = AmendmentReviewComment.from_dict(data)
        assert comment.reviewer_id == "reviewer1"
        assert comment.is_required_change

    def test_clone(self, review_comment):
        cloned = review_comment.clone()
        assert cloned.comment_id != review_comment.comment_id
        assert cloned.proposal_id == review_comment.proposal_id
        assert cloned.reviewer_id == review_comment.reviewer_id
        assert cloned.version == 1


# ============================================================================
# ENTITY BASIC METHODS (PARAMETRIZE UNTUK HILANGKAN DUPLIKAT)
# ============================================================================

class TestEntityBasicMethods:
    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_create(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.create("admin")
        assert result is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_touch(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        touched = entity.touch("toucher")
        # For proposal, touch returns new instance with version+1
        if cls_name == "AmendmentProposal":
            assert touched is not entity
            assert touched.version() == entity.version() + 1
        else:
            # Others return self (immutable with no version change)
            assert touched is entity
        # Audit trail should have been updated
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_validate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        result = entity.validate()
        assert result["is_valid"]

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_to_dict(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        d = entity.to_dict()
        assert "version" in d

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_clone(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        cloned = entity.clone()
        assert cloned is not entity
        assert cloned.version == 1
        # Proposal clone has different ID
        if cls_name == "AmendmentProposal":
            assert cloned.proposal_id != entity.proposal_id
        elif cls_name == "AmendmentVoteRecord":
            assert cloned.vote_id != entity.vote_id
        elif cls_name == "AmendmentExecutionRecord":
            assert cloned.execution_id != entity.execution_id
        elif cls_name == "AmendmentReviewComment":
            assert cloned.comment_id != entity.comment_id

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_snapshot(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        snap = entity.snapshot()
        assert "version" in snap
        assert "timestamp" in snap

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_get_version(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        assert entity.version() == entity.version

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_audit_trail(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        trail = entity.audit_trail()
        assert len(trail) >= 1
        entity.touch("toucher")
        trail2 = entity.audit_trail()
        assert len(trail2) >= len(trail) + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_lock_unlock(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        locked = entity.lock("admin", "test")
        # Most return self
        if cls_name == "AmendmentProposal":
            # Proposal lock returns self (not new instance)
            assert locked is entity
        else:
            assert locked is entity
        unlocked = locked.unlock("admin")
        assert unlocked is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_activate_deactivate(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        activated = entity.activate("admin")
        # For proposal, activate changes status
        if cls_name == "AmendmentProposal":
            assert activated.status == AmendmentStatus.UNDER_REVIEW
            assert activated.version() == entity.version() + 1
        else:
            assert activated is entity
        deactivated = activated.deactivate("admin")
        if cls_name == "AmendmentProposal":
            # deactivate returns to DRAFT
            assert deactivated.status == AmendmentStatus.DRAFT
            assert deactivated.version() == activated.version() + 1
        else:
            assert deactivated is entity

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_update(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not upd:
            with pytest.raises(AttributeError):
                entity.update("admin", some_field="value")
        else:
            if cls_name == "AmendmentProposal":
                updated = entity.update("admin", justification="New")
                assert updated.justification == "New"
                assert updated.version() == entity.version() + 1

    @pytest.mark.parametrize("fixture_name,cls_name,upd,del_,res", ENTITY_PARAMS)
    def test_entity_delete_restore(self, fixture_name, cls_name, upd, del_, res, request):
        entity = request.getfixturevalue(fixture_name)
        if not del_:
            with pytest.raises(AttributeError):
                entity.delete("admin")
            return
        if not res:
            # For proposal, delete is allowed but restore is not for others
            if cls_name != "AmendmentProposal":
                with pytest.raises(AttributeError):
                    entity.restore("admin")
            return
        # For proposal
        deleted = entity.delete("admin", "reason")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None


# ============================================================================
# TESTS UNTUK AmendmentProtocol (Aggregate)
# ============================================================================

class TestAmendmentProtocol:
    def test_initialization(self):
        protocol = AmendmentProtocol()
        assert protocol.protocol_version == "1.0.0"
        assert len(protocol.committee_members) == 5

    def test_save_proposal(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        assert protocol.get_proposal(proposal.proposal_id) is not None

    def test_get_all_proposals(self, protocol):
        p1 = create_test_proposal()
        p2 = create_test_proposal()
        protocol.save_proposal(p1)
        protocol.save_proposal(p2)
        all_props = protocol.get_all_proposals()
        assert len(all_props) >= 2

    def test_delete_proposal(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        result = protocol.delete_proposal(proposal.proposal_id)
        assert result
        assert protocol.get_proposal(proposal.proposal_id) is None

    def test_save_vote(self, protocol):
        vote = create_test_vote_record()
        protocol.save_vote(vote)
        votes = protocol.get_votes(vote.proposal_id)
        assert len(votes) == 1

    def test_delete_votes(self, protocol):
        vote = create_test_vote_record()
        protocol.save_vote(vote)
        result = protocol.delete_votes_for_proposal(vote.proposal_id)
        assert result
        assert protocol.get_votes(vote.proposal_id) == []

    def test_save_execution(self, protocol):
        execution = create_test_execution_record()
        protocol.save_execution(execution)
        retrieved = protocol.get_execution(execution.execution_id)
        assert retrieved is not None
        assert retrieved.proposal_id == execution.proposal_id

    def test_get_executions_by_proposal(self, protocol):
        e1 = create_test_execution_record()
        e2 = create_test_execution_record()
        e2.proposal_id = e1.proposal_id
        protocol.save_execution(e1)
        protocol.save_execution(e2)
        executions = protocol.get_executions_by_proposal(e1.proposal_id)
        assert len(executions) == 2

    def test_delete_execution(self, protocol):
        execution = create_test_execution_record()
        protocol.save_execution(execution)
        result = protocol.delete_execution(execution.execution_id)
        assert result
        assert protocol.get_execution(execution.execution_id) is None

    def test_save_review_comment(self, protocol):
        comment = create_test_review_comment()
        protocol.save_review_comment(comment)
        comments = protocol.get_review_comments(comment.proposal_id)
        assert len(comments) == 1

    def test_delete_review_comments(self, protocol):
        comment = create_test_review_comment()
        protocol.save_review_comment(comment)
        result = protocol.delete_review_comments_for_proposal(comment.proposal_id)
        assert result
        assert protocol.get_review_comments(comment.proposal_id) == []

    def test_submit_proposal_success(self, protocol):
        rule = create_test_rule()
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="Add new rule",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        assert proposal.proposal_id is not None
        assert proposal.status == AmendmentStatus.DRAFT
        assert len(protocol.proposals) == 1

    def test_submit_proposal_conflict_detection(self, protocol):
        rule = create_test_rule(ConstitutionalPrinciple.DOUBLE_ENTRY)
        protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="First",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        rule2 = create_test_rule(ConstitutionalPrinciple.DOUBLE_ENTRY)
        with pytest.raises(AmendmentConflictError):
            protocol.submit_proposal(
                amendment_type=AmendmentType.ADD_RULE,
                justification="Second",
                impact_assessment="Low",
                proposed_by="admin",
                new_rule=rule2,
            )

    def test_submit_proposal_conflict_by_target_rule(self, protocol):
        target_id = uuid.uuid4()
        # First proposal
        proposal = create_test_proposal(amendment_type=AmendmentType.MODIFY_RULE)
        proposal.target_rule_id = target_id
        protocol.save_proposal(proposal)
        protocol._active_proposal_ids.append(proposal.proposal_id)
        # Second proposal same target
        proposal2 = create_test_proposal(amendment_type=AmendmentType.MODIFY_RULE)
        proposal2.target_rule_id = target_id
        with pytest.raises(AmendmentConflictError):
            protocol.submit_proposal(
                amendment_type=AmendmentType.MODIFY_RULE,
                justification="Conflict",
                impact_assessment="Low",
                proposed_by="admin",
                target_rule_id=target_id,
                new_rule=create_test_rule(),
            )

    def test_submit_for_review(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        updated = protocol.submit_for_review(proposal.proposal_id, "admin")
        assert updated.status == AmendmentStatus.UNDER_REVIEW

    def test_submit_for_review_not_by_proposer(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        with pytest.raises(AmendmentProtocolError, match="Only proposer"):
            protocol.submit_for_review(proposal.proposal_id, "other")

    def test_submit_for_review_not_draft(self, protocol):
        proposal = create_test_proposal(status=AmendmentStatus.APPROVED)
        protocol.save_proposal(proposal)
        with pytest.raises(AmendmentProtocolError):
            protocol.submit_for_review(proposal.proposal_id, "admin")

    def test_add_review_comment(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        comment = protocol.add_review_comment(
            proposal.proposal_id,
            "reviewer1",
            "Need more detail",
            is_required_change=True,
        )
        assert comment is not None
        comments = protocol.get_review_comments(proposal.proposal_id)
        assert len(comments) == 1

    def test_add_review_comment_not_allowed_on_approved(self, protocol):
        proposal = create_test_proposal(status=AmendmentStatus.APPROVED)
        protocol.save_proposal(proposal)
        with pytest.raises(AmendmentProtocolError):
            protocol.add_review_comment(proposal.proposal_id, "r", "comment")

    def test_cast_vote(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        vote = protocol.cast_vote(proposal.proposal_id, "ceo", AmendmentVote.APPROVE)
        assert vote.vote == AmendmentVote.APPROVE
        votes = protocol.get_votes(proposal.proposal_id)
        assert len(votes) == 1

    def test_cast_vote_not_committee_member(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        with pytest.raises(InsufficientApprovalError, match="not a committee member"):
            protocol.cast_vote(proposal.proposal_id, "non_member", AmendmentVote.APPROVE)

    def test_cast_vote_expired(self, protocol):
        proposal = create_test_proposal()
        object.__setattr__(proposal, "expires_at", FIXED_PAST)
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        with pytest.raises(AmendmentExpiredError):
            protocol.cast_vote(proposal.proposal_id, "ceo", AmendmentVote.APPROVE)

    def test_check_approval_status_pending(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        status = protocol.check_approval_status(proposal.proposal_id)
        assert status["status"] == "pending"
        assert status["approve_count"] == 0

    def test_check_approval_status_approved(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        # Cast enough votes to approve
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.APPROVE)
        status = protocol.check_approval_status(proposal.proposal_id)
        assert status["status"] == "approved"

    def test_check_approval_status_rejected(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        # Cast enough reject votes
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.REJECT)
        status = protocol.check_approval_status(proposal.proposal_id)
        assert status["status"] == "rejected"

    def test_execute_amendment_success(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.APPROVE)

        def state_hasher():
            return "fake_hash"

        execution = protocol.execute_amendment(
            proposal.proposal_id,
            "admin",
            state_hasher=state_hasher,
        )
        assert execution.success
        # Check proposal status updated
        updated = protocol.get_proposal(proposal.proposal_id)
        assert updated.status == AmendmentStatus.IMPLEMENTED

    def test_execute_amendment_not_approved(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        # No votes
        with pytest.raises(InsufficientApprovalError):
            protocol.execute_amendment(proposal.proposal_id, "admin")

    def test_execute_amendment_expired(self, protocol):
        proposal = create_test_proposal()
        object.__setattr__(proposal, "expires_at", FIXED_PAST)
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.APPROVE)
        with pytest.raises(AmendmentExpiredError):
            protocol.execute_amendment(proposal.proposal_id, "admin")

    def test_execute_amendment_failure_with_rollback(self, protocol):
        proposal = create_test_proposal()
        object.__setattr__(proposal, "rollback_plan", "Rollback plan")
        protocol.save_proposal(proposal)
        protocol.submit_for_review(proposal.proposal_id, "admin")
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.APPROVE)

        def state_hasher():
            return "fake_hash"

        def migration_executor(prop):
            raise RuntimeError("Migration failed")

        execution = protocol.execute_amendment(
            proposal.proposal_id,
            "admin",
            state_hasher=state_hasher,
            migration_executor=migration_executor,
        )
        assert not execution.success
        assert execution.rollback_executed
        assert execution.rollback_reason is not None
        # Check proposal rolled back
        updated = protocol.get_proposal(proposal.proposal_id)
        assert updated.status == AmendmentStatus.ROLLED_BACK

    def test_get_proposal_details(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        details = protocol.get_proposal_details(proposal.proposal_id)
        assert "proposal" in details
        assert "approval_status" in details

    def test_get_active_proposals(self, protocol):
        p1 = create_test_proposal()
        p2 = create_test_proposal(status=AmendmentStatus.APPROVED)
        protocol.save_proposal(p1)
        protocol.save_proposal(p2)
        active = protocol.get_active_proposals()
        assert len(active) == 1  # only p1 is active

    def test_expire_old_proposals(self, protocol):
        proposal = create_test_proposal()
        object.__setattr__(proposal, "expires_at", FIXED_PAST)
        protocol.save_proposal(proposal)
        count = protocol.expire_old_proposals()
        assert count >= 1
        updated = protocol.get_proposal(proposal.proposal_id)
        assert updated.status == AmendmentStatus.EXPIRED

    def test_get_statistics(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        stats = protocol.get_statistics()
        assert stats["total_proposals"] >= 1
        assert "by_status" in stats

    def test_reset(self, protocol):
        proposal = create_test_proposal()
        protocol.save_proposal(proposal)
        protocol.reset()
        assert len(protocol.proposals) == 0
        assert len(protocol.votes) == 0
        assert len(protocol.executions) == 0
        assert len(protocol.review_comments) == 0
        assert len(protocol._active_proposal_ids) == 0


# ============================================================================
# TESTS UNTUK AmendmentProtocolService
# ============================================================================

class TestAmendmentProtocolService:
    def test_singleton(self):
        svc1 = AmendmentProtocolService()
        svc2 = AmendmentProtocolService()
        assert svc1 is svc2

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_propose_amendment(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = True
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        assert proposal is not None
        assert proposal.status == AmendmentStatus.DRAFT

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_propose_amendment_system_not_operational(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = False
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        rule = create_test_rule()
        with pytest.raises(AmendmentProtocolError, match="system status"):
            svc.propose_amendment(
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="Low",
                proposed_by="admin",
                new_rule=rule,
            )

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_propose_emergency_amendment(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = True
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="Emergency",
            impact_assessment="High",
            proposed_by="ceo",
            new_rule=rule,
            requires_emergency=True,
            emergency_reason="System threat",
            urgency=AmendmentUrgency.EMERGENCY,
        )
        assert proposal.requires_emergency
        assert proposal.urgency == AmendmentUrgency.EMERGENCY

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_propose_emergency_amendment_not_by_committee(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = True
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        rule = create_test_rule()
        with pytest.raises(InsufficientApprovalError):
            svc.propose_amendment(
                amendment_type=AmendmentType.ADD_RULE,
                justification="Emergency",
                impact_assessment="High",
                proposed_by="non_member",
                new_rule=rule,
                requires_emergency=True,
                emergency_reason="System threat",
                urgency=AmendmentUrgency.EMERGENCY,
            )

    def test_submit_for_review(self):
        svc = AmendmentProtocolService()
        # Need to clear existing proposals
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        updated = svc.submit_for_review(proposal.proposal_id, "admin")
        assert updated.status == AmendmentStatus.UNDER_REVIEW

    def test_add_review_comment(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        svc.submit_for_review(proposal.proposal_id, "admin")
        comment = svc.add_review_comment(proposal.proposal_id, "reviewer1", "Good", True)
        assert comment.is_required_change

    def test_vote(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        svc.submit_for_review(proposal.proposal_id, "admin")
        vote_record = svc.vote(proposal.proposal_id, "ceo", AmendmentVote.APPROVE)
        assert vote_record.vote == AmendmentVote.APPROVE

    def test_vote_not_authorized(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        svc.submit_for_review(proposal.proposal_id, "admin")
        with pytest.raises(InsufficientApprovalError, match="not authorized"):
            svc.vote(proposal.proposal_id, "non_member", AmendmentVote.APPROVE)

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_execute_approved_amendment(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = True
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        svc.submit_for_review(proposal.proposal_id, "admin")
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            svc.vote(proposal.proposal_id, member, AmendmentVote.APPROVE)

        # Mock constitution snapshot
        with patch("constitution.amendment_protocol.get_supreme_law") as mock_supreme:
            mock_supreme.return_value.get_constitution_snapshot.return_value.hash_current = "fake_hash"

            execution = svc.execute_approved_amendment(proposal.proposal_id, "admin")
            assert execution.success

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_execute_amendment_system_not_operational(self, mock_get_guardian):
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = False
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        with pytest.raises(AmendmentProtocolError, match="system status"):
            svc.execute_approved_amendment(uuid.uuid4(), "admin")

    def test_get_proposal_status(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        status = svc.get_proposal_status(proposal.proposal_id)
        assert "proposal" in status

    def test_get_active_proposals_service(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        active = svc.get_active_proposals()
        assert len(active) >= 1

    def test_get_protocol_summary(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        summary = svc.get_protocol_summary()
        assert "protocol_version" in summary
        assert "total_proposals" in summary

    def test_add_committee_member(self):
        svc = AmendmentProtocolService()
        protocol = svc.get_protocol()
        original_count = len(protocol.committee_members)
        svc.add_committee_member("new_member", "ceo")
        assert len(protocol.committee_members) == original_count + 1

    def test_add_committee_member_not_authorized(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        with pytest.raises(InsufficientApprovalError, match="cannot add"):
            svc.add_committee_member("new_member", "non_member")

    def test_remove_committee_member(self):
        svc = AmendmentProtocolService()
        protocol = svc.get_protocol()
        original_count = len(protocol.committee_members)
        svc.remove_committee_member("audit_committee_chair", "ceo")
        assert len(protocol.committee_members) == original_count - 1

    def test_remove_committee_member_not_authorized(self):
        svc = AmendmentProtocolService()
        with pytest.raises(InsufficientApprovalError, match="cannot remove"):
            svc.remove_committee_member("ceo", "non_member")

    def test_expire_old_proposals_service(self):
        svc = AmendmentProtocolService()
        svc.get_protocol().reset()
        rule = create_test_rule()
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
            expires_in_days=0,
        )
        count = svc.expire_old_proposals()
        assert count >= 1
        # Check proposal expired
        updated = svc.get_protocol().get_proposal(proposal.proposal_id)
        assert updated.status == AmendmentStatus.EXPIRED

    def test_get_amendment_protocol_singleton(self):
        svc1 = get_amendment_protocol()
        svc2 = get_amendment_protocol()
        assert svc1 is svc2

    def test_get_protocol(self):
        svc = AmendmentProtocolService()
        protocol = svc.get_protocol()
        assert isinstance(protocol, AmendmentProtocol)
