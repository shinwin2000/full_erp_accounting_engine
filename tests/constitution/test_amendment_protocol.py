#!/usr/bin/env python3
"""
tests/unit/test_amendment_protocol.py
Test untuk constitution/amendment_protocol.py
Mencakup: AmendmentProposal, AmendmentVoteRecord, AmendmentExecutionRecord,
AmendmentReviewComment, AmendmentProtocol, AmendmentProtocolService
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from constitution.amendment_protocol import (
    AmendmentConflictError,
    AmendmentExecutionRecord,
    AmendmentExpiredError,
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
from constitution.supreme_law import ConstitutionalPrinciple, ConstitutionalRule, ConstitutionalSeverity, SovereigntyLevel


class TestAmendmentProposal:
    def test_create_valid_proposal(self):
        """Test creation of valid AmendmentProposal."""
        now = datetime.now(UTC)
        proposal = AmendmentProposal(
            proposal_id=uuid.uuid4(),
            amendment_type=AmendmentType.ADD_RULE,
            justification="Need to add rule",
            impact_assessment="Low",
            proposed_by="admin",
            proposed_at=now,
            migration_strategy=MigrationStrategy.IMMEDIATE,
            migration_plan="Apply immediately",
            rollback_plan="Revert changes",
            requires_emergency=False,
            urgency=AmendmentUrgency.ROUTINE,
            status=AmendmentStatus.DRAFT,
            version="1.0",
            expires_at=now + timedelta(days=30),
        )
        assert proposal.amendment_type == AmendmentType.ADD_RULE
        assert proposal.proposed_by == "admin"
        assert proposal.status == AmendmentStatus.DRAFT
        assert not proposal.is_expired()
        assert proposal.can_be_processed()
        assert proposal.version() == 1

    def test_validate_requires_target_rule_for_modify(self):
        """Test validation requires target_rule_id for MODIFY_RULE."""
        now = datetime.now(UTC)
        with pytest.raises(AmendmentProtocolError, match="target_rule_id required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.MODIFY_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=now,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                target_rule_id=None,  # Missing
            )

    def test_validate_requires_new_rule_for_add(self):
        """Test validation requires new_rule for ADD_RULE."""
        now = datetime.now(UTC)
        with pytest.raises(AmendmentProtocolError, match="new_rule required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=now,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=False,
                urgency=AmendmentUrgency.ROUTINE,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=None,  # Missing
            )

    def test_validate_requires_emergency_reason(self):
        """Test validation requires emergency_reason when requires_emergency."""
        now = datetime.now(UTC)
        with pytest.raises(AmendmentProtocolError, match="emergency_reason required"):
            AmendmentProposal(
                proposal_id=uuid.uuid4(),
                amendment_type=AmendmentType.ADD_RULE,
                justification="test",
                impact_assessment="test",
                proposed_by="admin",
                proposed_at=now,
                migration_strategy=MigrationStrategy.IMMEDIATE,
                migration_plan="",
                rollback_plan="",
                requires_emergency=True,
                emergency_reason=None,  # Missing
                urgency=AmendmentUrgency.EMERGENCY,
                status=AmendmentStatus.DRAFT,
                version="1.0",
                new_rule=ConstitutionalRule(
                    rule_id=uuid.uuid4(),
                    principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
                    statement="test",
                    sovereignty=SovereigntyLevel.ABSOLUTE,
                    severity_on_violation=ConstitutionalSeverity.CRITICAL,
                    effective_from=now,
                    created_by="test",
                    created_at=now,
                    approved_by=["a", "b", "c"],
                ),
            )

    def test_update_creates_new_version(self):
        """Test update creates new instance with incremented version."""
        now = datetime.now(UTC)
        proposal = AmendmentProposal(
            proposal_id=uuid.uuid4(),
            amendment_type=AmendmentType.ADD_RULE,
            justification="Original",
            impact_assessment="test",
            proposed_by="admin",
            proposed_at=now,
            migration_strategy=MigrationStrategy.IMMEDIATE,
            migration_plan="",
            rollback_plan="",
            requires_emergency=False,
            urgency=AmendmentUrgency.ROUTINE,
            status=AmendmentStatus.DRAFT,
            version="1.0",
        )
        updated = proposal.update("admin", justification="Updated justification")
        assert updated.justification == "Updated justification"
        assert updated.version() == 2

    def test_update_not_allowed_after_submission(self):
        """Test update not allowed when status is not DRAFT or UNDER_REVIEW."""
        now = datetime.now(UTC)
        proposal = AmendmentProposal(
            proposal_id=uuid.uuid4(),
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="test",
            proposed_by="admin",
            proposed_at=now,
            migration_strategy=MigrationStrategy.IMMEDIATE,
            migration_plan="",
            rollback_plan="",
            requires_emergency=False,
            urgency=AmendmentUrgency.ROUTINE,
            status=AmendmentStatus.APPROVED,
            version="1.0",
        )
        with pytest.raises(AmendmentProtocolError):
            proposal.update("admin", justification="Should fail")

    def test_activate_moves_to_under_review(self):
        """Test activate changes status to UNDER_REVIEW."""
        now = datetime.now(UTC)
        proposal = AmendmentProposal(
            proposal_id=uuid.uuid4(),
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="test",
            proposed_by="admin",
            proposed_at=now,
            migration_strategy=MigrationStrategy.IMMEDIATE,
            migration_plan="",
            rollback_plan="",
            requires_emergency=False,
            urgency=AmendmentUrgency.ROUTINE,
            status=AmendmentStatus.DRAFT,
            version="1.0",
        )
        activated = proposal.activate("admin")
        assert activated.status == AmendmentStatus.UNDER_REVIEW

    def test_is_expired(self):
        """Test is_expired checks expiry."""
        now = datetime.now(UTC)
        proposal = AmendmentProposal(
            proposal_id=uuid.uuid4(),
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="test",
            proposed_by="admin",
            proposed_at=now,
            migration_strategy=MigrationStrategy.IMMEDIATE,
            migration_plan="",
            rollback_plan="",
            requires_emergency=False,
            urgency=AmendmentUrgency.ROUTINE,
            status=AmendmentStatus.DRAFT,
            version="1.0",
            expires_at=now - timedelta(days=1),
        )
        assert proposal.is_expired()
        assert not proposal.can_be_processed()


class TestAmendmentVoteRecord:
    def test_create_valid_vote(self):
        """Test creation of valid AmendmentVoteRecord."""
        now = datetime.now(UTC)
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="committee_member",
            vote=AmendmentVote.APPROVE,
            voted_at=now,
            cryptographic_signature="sig123",
            comment="Looks good",
        )
        assert vote.voter_id == "committee_member"
        assert vote.vote == AmendmentVote.APPROVE
        assert vote.is_approval()
        assert vote.comment == "Looks good"

    def test_is_approval(self):
        """Test is_approval returns correct boolean."""
        approve = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="s",
        )
        reject = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.REJECT,
            voted_at=datetime.now(UTC),
            cryptographic_signature="s",
        )
        assert approve.is_approval()
        assert not reject.is_approval()


class TestAmendmentExecutionRecord:
    def test_create_valid_execution(self):
        """Test creation of valid AmendmentExecutionRecord."""
        now = datetime.now(UTC)
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=now,
            executed_by="admin",
            previous_state_hash="prev_hash",
            new_state_hash="new_hash",
            migration_log=["Step 1", "Step 2"],
            success=True,
            rollback_executed=False,
        )
        assert execution.success
        assert len(execution.migration_log) == 2
        assert execution.version == 1


class TestAmendmentReviewComment:
    def test_create_valid_comment(self):
        """Test creation of valid AmendmentReviewComment."""
        now = datetime.now(UTC)
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="reviewer1",
            comment="Need to clarify impact",
            commented_at=now,
            is_required_change=True,
        )
        assert comment.reviewer_id == "reviewer1"
        assert comment.is_required_change


class TestAmendmentProtocol:
    def test_initialization(self):
        """Test AmendmentProtocol initialization."""
        protocol = AmendmentProtocol()
        assert protocol.protocol_version == "1.0.0"
        assert len(protocol.committee_members) == 5
        assert len(protocol.proposals) == 0

    def test_submit_proposal_success(self):
        """Test submit_proposal creates proposal."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
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

    def test_submit_proposal_conflict_detection(self):
        """Test submit_proposal detects conflicts."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        # First proposal
        protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="First",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        # Second proposal with same principle
        rule2 = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test2",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        with pytest.raises(AmendmentConflictError):
            protocol.submit_proposal(
                amendment_type=AmendmentType.ADD_RULE,
                justification="Second",
                impact_assessment="Low",
                proposed_by="admin",
                new_rule=rule2,
            )

    def test_submit_for_review(self):
        """Test submit_for_review changes status."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        updated = protocol.submit_for_review(proposal.proposal_id, "admin")
        assert updated.status == AmendmentStatus.UNDER_REVIEW

    def test_submit_for_review_not_by_proposer(self):
        """Test submit_for_review only allows proposer."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        with pytest.raises(AmendmentProtocolError, match="Only proposer"):
            protocol.submit_for_review(proposal.proposal_id, "other_user")

    def test_cast_vote(self):
        """Test cast_vote records vote."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        protocol.submit_for_review(proposal.proposal_id, "admin")
        vote = protocol.cast_vote(
            proposal.proposal_id,
            "ceo",
            AmendmentVote.APPROVE,
            "Approved",
        )
        assert vote is not None
        assert vote.vote == AmendmentVote.APPROVE
        votes = protocol.get_votes(proposal.proposal_id)
        assert len(votes) == 1

    def test_cast_vote_not_committee_member(self):
        """Test cast_vote rejects non-committee member."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        protocol.submit_for_review(proposal.proposal_id, "admin")
        with pytest.raises(InsufficientApprovalError, match="not a committee member"):
            protocol.cast_vote(
                proposal.proposal_id,
                "non_member",
                AmendmentVote.APPROVE,
            )

    def test_check_approval_status(self):
        """Test check_approval_status returns status."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        protocol.submit_for_review(proposal.proposal_id, "admin")
        # Cast some votes
        protocol.cast_vote(proposal.proposal_id, "ceo", AmendmentVote.APPROVE)
        protocol.cast_vote(proposal.proposal_id, "cfo", AmendmentVote.APPROVE)
        status = protocol.check_approval_status(proposal.proposal_id)
        assert status["status"] in ("approved", "pending")

    def test_execute_amendment_success(self):
        """Test execute_amendment executes successfully."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.IMMUTABILITY,
            statement="New immutability rule",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="Add immutability rule",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        protocol.submit_for_review(proposal.proposal_id, "admin")

        # Get enough approvals
        for member in ["ceo", "cfo", "audit_committee_chair"]:
            protocol.cast_vote(proposal.proposal_id, member, AmendmentVote.APPROVE)

        status = protocol.check_approval_status(proposal.proposal_id)
        assert status["status"] == "approved"

        def state_hasher():
            return "fake_hash"

        execution = protocol.execute_amendment(
            proposal.proposal_id,
            "admin",
            state_hasher=state_hasher,
        )
        assert execution.success

    def test_execute_amendment_not_approved(self):
        """Test execute_amendment rejects non-approved proposal."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        protocol.submit_for_review(proposal.proposal_id, "admin")
        # No votes, so not approved
        with pytest.raises(InsufficientApprovalError):
            protocol.execute_amendment(proposal.proposal_id, "admin")

    def test_add_review_comment(self):
        """Test add_review_comment adds comment."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
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

    def test_expire_old_proposals(self):
        """Test expire_old_proposals expires old proposals."""
        protocol = AmendmentProtocol()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        # Create proposal that expires immediately
        proposal = protocol.submit_proposal(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
            expires_in_days=0,
        )
        # Should be expired already
        expired_count = protocol.expire_old_proposals()
        assert expired_count >= 1
        updated = protocol.get_proposal(proposal.proposal_id)
        assert updated.status == AmendmentStatus.EXPIRED

    def test_get_statistics(self):
        """Test get_statistics returns summary."""
        protocol = AmendmentProtocol()
        stats = protocol.get_statistics()
        assert "total_proposals" in stats
        assert "active_proposals" in stats


class TestAmendmentProtocolService:
    def test_singleton(self):
        """Test AmendmentProtocolService is singleton."""
        svc1 = AmendmentProtocolService()
        svc2 = AmendmentProtocolService()
        assert svc1 is svc2

    @patch("constitution.amendment_protocol.get_sovereignty_guardian")
    def test_propose_amendment(self, mock_get_guardian):
        """Test propose_amendment delegates to protocol."""
        mock_guardian = MagicMock()
        mock_guardian.is_system_operational.return_value = True
        mock_get_guardian.return_value = mock_guardian

        svc = AmendmentProtocolService()
        now = datetime.now(UTC)
        rule = ConstitutionalRule(
            rule_id=uuid.uuid4(),
            principle=ConstitutionalPrinciple.DOUBLE_ENTRY,
            statement="test",
            sovereignty=SovereigntyLevel.ABSOLUTE,
            severity_on_violation=ConstitutionalSeverity.CRITICAL,
            effective_from=now,
            created_by="test",
            created_at=now,
            approved_by=["a", "b", "c"],
        )
        proposal = svc.propose_amendment(
            amendment_type=AmendmentType.ADD_RULE,
            justification="test",
            impact_assessment="Low",
            proposed_by="admin",
            new_rule=rule,
        )
        assert proposal is not None

    def test_add_committee_member(self):
        """Test add_committee_member adds member."""
        svc = AmendmentProtocolService()
        original_count = len(svc.get_protocol().committee_members)
        svc.add_committee_member("new_member", "ceo")
        assert len(svc.get_protocol().committee_members) == original_count + 1

    def test_remove_committee_member(self):
        """Test remove_committee_member removes member."""
        svc = AmendmentProtocolService()
        original_count = len(svc.get_protocol().committee_members)
        svc.remove_committee_member("audit_committee_chair", "ceo")
        assert len(svc.get_protocol().committee_members) == original_count - 1

    def test_get_amendment_protocol_singleton(self):
        """Test get_amendment_protocol returns singleton."""
        svc1 = get_amendment_protocol()
        svc2 = get_amendment_protocol()
        assert svc1 is svc2

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_proposal() -> AmendmentProposal:
    now = datetime.now(UTC)
    rule = ConstitutionalRule(
        rule_id=uuid.uuid4(),
        principle=ConstitutionalPrinciple.IMMUTABILITY,
        statement="Test rule",
        sovereignty=SovereigntyLevel.ORDINARY,
        severity_on_violation=ConstitutionalSeverity.MEDIUM,
        effective_from=now,
        created_by="tester",
        created_at=now,
        approved_by=["a", "b"],
    )
    return AmendmentProposal(
        proposal_id=uuid.uuid4(),
        amendment_type=AmendmentType.ADD_RULE,
        justification="Test justification",
        impact_assessment="Low",
        proposed_by="admin",
        proposed_at=now,
        migration_strategy=MigrationStrategy.IMMEDIATE,
        migration_plan="",
        rollback_plan="",
        requires_emergency=False,
        urgency=AmendmentUrgency.ROUTINE,
        status=AmendmentStatus.DRAFT,
        version="1.0",
        new_rule=rule,
        expires_at=now + timedelta(days=30),
    )


class TestAmendmentProposalLifecycle:
    def test_create_returns_self(self):
        proposal = create_test_proposal()
        result = proposal.create("admin")
        assert result is proposal

    def test_activate_moves_to_under_review(self):
        proposal = create_test_proposal()
        activated = proposal.activate("admin")
        assert activated.status == AmendmentStatus.UNDER_REVIEW

    def test_deactivate_returns_to_draft(self):
        proposal = create_test_proposal()
        activated = proposal.activate("admin")
        deactivated = activated.deactivate("admin")
        assert deactivated.status == AmendmentStatus.DRAFT

    def test_lock_returns_self(self):
        proposal = create_test_proposal()
        result = proposal.lock("admin", "test")
        assert result is proposal

    def test_unlock_returns_self(self):
        proposal = create_test_proposal()
        result = proposal.unlock("admin")
        assert result is proposal

    def test_validate_returns_valid(self):
        proposal = create_test_proposal()
        result = proposal.validate()
        assert result["is_valid"]


class TestAmendmentVoteRecordLifecycle:
    def test_create_returns_self(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.create("admin")
        assert result is vote

    def test_activate_returns_self(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.activate("admin")
        assert result is vote

    def test_deactivate_returns_self(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.deactivate("admin")
        assert result is vote

    def test_lock_returns_self(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.lock("admin", "test")
        assert result is vote

    def test_unlock_returns_self(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.unlock("admin")
        assert result is vote

    def test_validate_returns_valid(self):
        vote = AmendmentVoteRecord(
            vote_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            voter_id="a",
            vote=AmendmentVote.APPROVE,
            voted_at=datetime.now(UTC),
            cryptographic_signature="sig",
        )
        result = vote.validate()
        assert result["is_valid"]


class TestAmendmentExecutionRecordLifecycle:
    def test_create_returns_self(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.create("admin")
        assert result is execution

    def test_activate_returns_self(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.activate("admin")
        assert result is execution

    def test_deactivate_returns_self(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.deactivate("admin")
        assert result is execution

    def test_lock_returns_self(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.lock("admin", "test")
        assert result is execution

    def test_unlock_returns_self(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.unlock("admin")
        assert result is execution

    def test_validate_returns_valid(self):
        execution = AmendmentExecutionRecord(
            execution_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            executed_at=datetime.now(UTC),
            executed_by="admin",
            previous_state_hash="prev",
            new_state_hash="new",
            migration_log=[],
            success=True,
            rollback_executed=False,
        )
        result = execution.validate()
        assert result["is_valid"]


class TestAmendmentReviewCommentLifecycle:
    def test_create_returns_self(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.create("admin")
        assert result is comment

    def test_activate_returns_self(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.activate("admin")
        assert result is comment

    def test_deactivate_returns_self(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.deactivate("admin")
        assert result is comment

    def test_lock_returns_self(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.lock("admin", "test")
        assert result is comment

    def test_unlock_returns_self(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.unlock("admin")
        assert result is comment

    def test_validate_returns_valid(self):
        comment = AmendmentReviewComment(
            comment_id=uuid.uuid4(),
            proposal_id=uuid.uuid4(),
            reviewer_id="a",
            comment="test",
            commented_at=datetime.now(UTC),
            is_required_change=False,
        )
        result = comment.validate()
        assert result["is_valid"]