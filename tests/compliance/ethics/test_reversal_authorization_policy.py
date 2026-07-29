# tests/compliance/ethics/test_reversal_authorization_policy.py
"""
Comprehensive unit tests for compliance/ethics/reversal_authorization_policy.py.
Covers all enums, data classes, and policy methods with deterministic datetime.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import mock_open, patch
from uuid import uuid4

import pytest

from compliance.ethics.reversal_authorization_policy import (
    ReversalApproval,
    ReversalApprovalLevel,
    ReversalAuthorizationPolicy,
    ReversalReason,
    ReversalRequest,
    ReversalRiskLevel,
    ReversalStatus,
)

# ============================================================================
# Fixed datetime to avoid flaky tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)
FIXED_EXPIRED = FIXED_NOW + timedelta(days=8)  # beyond 7-day expiry


@pytest.fixture(autouse=True)
def mock_datetime_now():
    with patch("compliance.ethics.reversal_authorization_policy.datetime") as mock_dt:
        mock_dt.utcnow.return_value = FIXED_NOW
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


# ============================================================================
# Enum tests
# ============================================================================

class TestReversalReason:
    def test_members(self):
        assert ReversalReason.ERROR_CORRECTION.value == "error_correction"
        assert ReversalReason.ADJUSTMENT.value == "adjustment"
        assert ReversalReason.CANCELLATION.value == "cancellation"
        assert ReversalReason.RESTATEMENT.value == "restatement"
        assert ReversalReason.FRAUD_CORRECTION.value == "fraud_correction"


class TestReversalStatus:
    def test_members(self):
        assert ReversalStatus.PENDING.value == "pending"
        assert ReversalStatus.APPROVED.value == "approved"
        assert ReversalStatus.REJECTED.value == "rejected"
        assert ReversalStatus.IMPLEMENTED.value == "implemented"
        assert ReversalStatus.CANCELLED.value == "cancelled"
        assert ReversalStatus.EXPIRED.value == "expired"


class TestReversalApprovalLevel:
    def test_members(self):
        assert ReversalApprovalLevel.SUPERVISOR.value == "supervisor"
        assert ReversalApprovalLevel.MANAGER.value == "manager"
        assert ReversalApprovalLevel.CONTROLLER.value == "controller"
        assert ReversalApprovalLevel.CFO.value == "cfo"
        assert ReversalApprovalLevel.AUDIT_COMMITTEE.value == "audit_committee"


class TestReversalRiskLevel:
    def test_members(self):
        assert ReversalRiskLevel.LOW.value == "low"
        assert ReversalRiskLevel.MEDIUM.value == "medium"
        assert ReversalRiskLevel.HIGH.value == "high"
        assert ReversalRiskLevel.CRITICAL.value == "critical"


# ============================================================================
# ReversalApproval data class
# ============================================================================

class TestReversalApproval:
    def test_construction(self):
        approver_id = uuid4()
        approved_at = FIXED_NOW
        approval = ReversalApproval(
            approver_id=approver_id,
            approver_name="John Doe",
            level=ReversalApprovalLevel.MANAGER,
            decision="approved",
            notes="Looks good",
            approved_at=approved_at,
        )
        assert approval.approver_id == approver_id
        assert approval.approver_name == "John Doe"
        assert approval.level == ReversalApprovalLevel.MANAGER
        assert approval.decision == "approved"
        assert approval.notes == "Looks good"
        assert approval.approved_at == approved_at

    def test_to_dict(self):
        approval = ReversalApproval(
            approver_id=uuid4(),
            approver_name="Jane",
            level=ReversalApprovalLevel.CFO,
            decision="rejected",
            notes="Invalid amount",
            approved_at=FIXED_NOW,
        )
        d = approval.to_dict()
        assert d["approver_name"] == "Jane"
        assert d["level"] == "cfo"
        assert d["decision"] == "rejected"
        assert d["notes"] == "Invalid amount"
        assert d["approved_at"] == FIXED_NOW.isoformat()


# ============================================================================
# ReversalRequest tests
# ============================================================================

class TestReversalRequest:
    @pytest.fixture
    def reversal_request(self):
        return ReversalRequest(
            request_id=uuid4(),
            journal_id=uuid4(),
            journal_amount=Decimal("1000000"),
            journal_date=FIXED_NOW - timedelta(days=1),
            requested_by=uuid4(),
            requested_by_name="Accountant",
            reason=ReversalReason.ADJUSTMENT,
            justification="Test justification",
            risk_level=ReversalRiskLevel.MEDIUM,
            original_journal_hash="abc123",
            expires_at=FIXED_NOW + timedelta(days=7),
        )

    def test_construction(self, reversal_request):
        assert isinstance(reversal_request, ReversalRequest)
        assert reversal_request.status == ReversalStatus.PENDING
        assert reversal_request.created_at == FIXED_NOW
        assert reversal_request.expires_at == FIXED_NOW + timedelta(days=7)
        assert reversal_request._hash is not None
        assert len(reversal_request._hash) == 64  # SHA256

    def test_hash_consistency(self, reversal_request):
        h1 = reversal_request._hash
        # modify something, hash should change
        reversal_request.justification = "Changed"
        h2 = reversal_request._compute_hash()
        assert h1 != h2

    def test_add_approval(self, reversal_request):
        approver_id = uuid4()
        reversal_request.add_approval(
            approver_id=approver_id,
            approver_name="Supervisor",
            level=ReversalApprovalLevel.SUPERVISOR,
            notes="Approved",
        )
        assert len(reversal_request.approvals) == 1
        assert reversal_request.approvals[0].approver_id == approver_id
        assert reversal_request.approvals[0].level == ReversalApprovalLevel.SUPERVISOR
        assert reversal_request.approvals[0].decision == "approved"
        assert reversal_request.approvals[0].approved_at == FIXED_NOW
        # status remains PENDING unless enough approvals; we'll test later in policy

    def test_add_rejection(self, reversal_request):
        approver_id = uuid4()
        reversal_request.add_rejection(
            approver_id=approver_id,
            approver_name="Manager",
            level=ReversalApprovalLevel.MANAGER,
            reason="Insufficient documentation",
        )
        assert len(reversal_request.approvals) == 1
        assert reversal_request.approvals[0].decision == "rejected"
        assert reversal_request.approvals[0].notes == "Insufficient documentation"
        assert reversal_request.status == ReversalStatus.REJECTED
        assert reversal_request.rejection_reason == "Insufficient documentation"

    def test_mark_implemented(self, reversal_request):
        reversal_request.status = ReversalStatus.APPROVED  # simulate approved
        impl_by = uuid4()
        rev_journal_id = uuid4()
        reversal_request.mark_implemented(impl_by, rev_journal_id)
        assert reversal_request.status == ReversalStatus.IMPLEMENTED
        assert reversal_request.implemented_by == impl_by
        assert reversal_request.implemented_at == FIXED_NOW
        assert reversal_request.reversal_journal_id == rev_journal_id

    def test_is_expired(self, reversal_request):
        # not expired
        assert reversal_request.is_expired() is False
        # manually set expired
        reversal_request.expires_at = FIXED_NOW - timedelta(days=1)
        assert reversal_request.is_expired() is True

    def test_to_dict(self, reversal_request):
        d = reversal_request.to_dict()
        assert d["request_id"] == str(reversal_request.id)
        assert d["journal_id"] == str(reversal_request.journal_id)
        assert d["journal_amount"] == str(reversal_request.journal_amount)
        assert d["reason"] == reversal_request.reason.value
        assert d["status"] == reversal_request.status.value
        assert "approvals" in d
        assert "hash" in d


# ============================================================================
# ReversalAuthorizationPolicy tests
# ============================================================================

class TestReversalAuthorizationPolicy:
    @pytest.fixture
    def policy(self):
        return ReversalAuthorizationPolicy()

    def test_init_policy_rules(self, policy):
        rules = policy._policy_rules
        assert rules[ReversalRiskLevel.LOW] == ReversalApprovalLevel.SUPERVISOR
        assert rules[ReversalRiskLevel.MEDIUM] == ReversalApprovalLevel.MANAGER
        assert rules[ReversalRiskLevel.HIGH] == ReversalApprovalLevel.CONTROLLER
        assert rules[ReversalRiskLevel.CRITICAL] == ReversalApprovalLevel.CFO

    # ---- _determine_risk_level ----
    def test_determine_risk_level_critical_fraud(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("1000"),
            reason=ReversalReason.FRAUD_CORRECTION,
            journal_age_days=0,
            is_fraud=True,
        )
        assert risk == ReversalRiskLevel.CRITICAL

    def test_determine_risk_level_high_age(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("1000"),
            reason=ReversalReason.ERROR_CORRECTION,
            journal_age_days=31,
            is_fraud=False,
        )
        assert risk == ReversalRiskLevel.HIGH

    def test_determine_risk_level_high_amount(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("1_500_000_000"),
            reason=ReversalReason.ADJUSTMENT,
            journal_age_days=5,
            is_fraud=False,
        )
        assert risk == ReversalRiskLevel.HIGH

    def test_determine_risk_level_medium_amount(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("150_000_000"),
            reason=ReversalReason.ADJUSTMENT,
            journal_age_days=5,
            is_fraud=False,
        )
        assert risk == ReversalRiskLevel.MEDIUM

    def test_determine_risk_level_medium_restatement(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("1_000_000"),
            reason=ReversalReason.RESTATEMENT,
            journal_age_days=5,
            is_fraud=False,
        )
        assert risk == ReversalRiskLevel.HIGH  # restatement -> HIGH

    def test_determine_risk_level_low(self, policy):
        risk = policy._determine_risk_level(
            journal_amount=Decimal("5_000_000"),
            reason=ReversalReason.ERROR_CORRECTION,
            journal_age_days=0,
            is_fraud=False,
        )
        assert risk == ReversalRiskLevel.LOW

    # ---- _can_auto_approve ----
    def test_can_auto_approve_true(self, policy):
        # same day error correction, small amount
        request = ReversalRequest(
            request_id=uuid4(),
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=6),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="Wrong account",
            risk_level=ReversalRiskLevel.LOW,
        )
        assert policy._can_auto_approve(request) is True

    def test_can_auto_approve_false_reason(self, policy):
        request = ReversalRequest(
            request_id=uuid4(),
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=6),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ADJUSTMENT,  # not error correction
            justification="",
            risk_level=ReversalRiskLevel.LOW,
        )
        assert policy._can_auto_approve(request) is False

    def test_can_auto_approve_false_age(self, policy):
        request = ReversalRequest(
            request_id=uuid4(),
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(days=2),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
            risk_level=ReversalRiskLevel.LOW,
        )
        assert policy._can_auto_approve(request) is False

    def test_can_auto_approve_false_amount(self, policy):
        request = ReversalRequest(
            request_id=uuid4(),
            journal_id=uuid4(),
            journal_amount=Decimal("15_000_000"),  # >10M
            journal_date=FIXED_NOW - timedelta(hours=6),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
            risk_level=ReversalRiskLevel.LOW,
        )
        assert policy._can_auto_approve(request) is False

    # ---- request_reversal ----
    def test_request_reversal_auto_approve(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=2),
            requested_by=uuid4(),
            requested_by_name="John",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="Same day correction",
        )
        assert req.status == ReversalStatus.APPROVED
        assert len(req.approvals) == 1
        assert req.approvals[0].approver_name == "System Auto-Approval"
        assert req.approvals[0].level == ReversalApprovalLevel.SUPERVISOR
        assert req.risk_level == ReversalRiskLevel.LOW

    def test_request_reversal_pending_requires_approval(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),  # medium risk
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="Jane",
            reason=ReversalReason.ADJUSTMENT,
            justification="Monthly accrual adjustment",
        )
        assert req.status == ReversalStatus.PENDING
        assert len(req.approvals) == 0
        assert req.risk_level == ReversalRiskLevel.MEDIUM

    def test_request_reversal_high_risk(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("2_000_000_000"),  # high
            journal_date=FIXED_NOW - timedelta(days=10),
            requested_by=uuid4(),
            requested_by_name="Manager",
            reason=ReversalReason.ADJUSTMENT,
            justification="Large adjustment",
        )
        assert req.status == ReversalStatus.PENDING
        assert req.risk_level == ReversalRiskLevel.HIGH

    def test_request_reversal_fraud_critical(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("1_000_000"),
            journal_date=FIXED_NOW - timedelta(days=1),
            requested_by=uuid4(),
            requested_by_name="Auditor",
            reason=ReversalReason.FRAUD_CORRECTION,
            justification="Fraud detected",
            is_fraud=True,
        )
        assert req.risk_level == ReversalRiskLevel.CRITICAL
        assert req.status == ReversalStatus.PENDING  # not auto-approved

    # ---- get_request ----
    def test_get_request(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("1000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="test",
        )
        retrieved = policy.get_request(req.id)
        assert retrieved is req
        assert policy.get_request(uuid4()) is None

    # ---- approve ----
    def test_approve_success(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="Jane",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # Approve with MANAGER (required for medium)
        result = policy.approve(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            notes="OK",
        )
        assert result is True
        assert req.status == ReversalStatus.APPROVED
        assert len(req.approvals) == 1
        assert req.approvals[0].approver_name == "Manager"

    def test_approve_insufficient_level(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="Jane",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # Try to approve with SUPERVISOR (lower than required MANAGER)
        result = policy.approve(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Supervisor",
            approver_level=ReversalApprovalLevel.SUPERVISOR,
            notes="OK",
        )
        assert result is False
        assert req.status == ReversalStatus.PENDING  # unchanged
        assert len(req.approvals) == 0  # no approval added

    def test_approve_already_approved(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=2),
            requested_by=uuid4(),
            requested_by_name="John",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        # This one is auto-approved
        assert req.status == ReversalStatus.APPROVED
        result = policy.approve(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            notes="Extra",
        )
        assert result is False  # cannot approve again
        assert req.status == ReversalStatus.APPROVED

    def test_approve_not_found(self, policy):
        result = policy.approve(
            request_id=uuid4(),
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            notes="OK",
        )
        assert result is False

    def test_approve_expired(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="Jane",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # expire it manually
        req.expires_at = FIXED_NOW - timedelta(days=1)
        result = policy.approve(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            notes="OK",
        )
        assert result is False
        assert req.status == ReversalStatus.EXPIRED

    # ---- reject ----
    def test_reject_success(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        result = policy.reject(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            reason="Not enough detail",
        )
        assert result is True
        assert req.status == ReversalStatus.REJECTED
        assert req.rejection_reason == "Not enough detail"
        assert len(req.approvals) == 1
        assert req.approvals[0].decision == "rejected"

    def test_reject_not_pending(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=2),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        # auto-approved, so status APPROVED
        assert req.status == ReversalStatus.APPROVED
        result = policy.reject(
            request_id=req.id,
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            reason="test",
        )
        assert result is False

    def test_reject_not_found(self, policy):
        result = policy.reject(
            request_id=uuid4(),
            approver_id=uuid4(),
            approver_name="Manager",
            approver_level=ReversalApprovalLevel.MANAGER,
            reason="test",
        )
        assert result is False

    # ---- implement_reversal ----
    def test_implement_reversal_success(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="Jane",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # approve first
        policy.approve(req.id, uuid4(), "Manager", ReversalApprovalLevel.MANAGER)
        assert req.status == ReversalStatus.APPROVED
        impl_by = uuid4()
        rev_journal_id = uuid4()
        result = policy.implement_reversal(req.id, impl_by, rev_journal_id)
        assert result is True
        assert req.status == ReversalStatus.IMPLEMENTED
        assert req.implemented_by == impl_by
        assert req.reversal_journal_id == rev_journal_id

    def test_implement_reversal_not_approved(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # still pending
        assert req.status == ReversalStatus.PENDING
        result = policy.implement_reversal(req.id, uuid4(), uuid4())
        assert result is False

    def test_implement_reversal_not_found(self, policy):
        result = policy.implement_reversal(uuid4(), uuid4(), uuid4())
        assert result is False

    # ---- get_pending_requests / get_approved_requests / get_rejected_requests ----
    def test_get_status_lists(self, policy):
        # create requests with different statuses
        req1 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="A",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )  # pending
        req2 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=1),
            requested_by=uuid4(),
            requested_by_name="B",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )  # auto-approved
        # create rejected
        req3 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="C",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        policy.reject(req3.id, uuid4(), "Manager", ReversalApprovalLevel.MANAGER, "bad")

        pendings = policy.get_pending_requests()
        assert len(pendings) == 1
        assert pendings[0].id == req1.id

        approved = policy.get_approved_requests()
        assert len(approved) == 1
        assert approved[0].id == req2.id

        rejected = policy.get_rejected_requests()
        assert len(rejected) == 1
        assert rejected[0].id == req3.id

    # ---- get_requests_by_requester ----
    def test_get_requests_by_requester(self, policy):
        user1 = uuid4()
        user2 = uuid4()
        req1 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("1000"),
            journal_date=FIXED_NOW,
            requested_by=user1,
            requested_by_name="U1",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        req2 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("2000"),
            journal_date=FIXED_NOW,
            requested_by=user1,
            requested_by_name="U1",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        req3 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("3000"),
            journal_date=FIXED_NOW,
            requested_by=user2,
            requested_by_name="U2",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        user1_requests = policy.get_requests_by_requester(user1)
        assert len(user1_requests) == 2
        assert req1 in user1_requests
        assert req2 in user1_requests
        user2_requests = policy.get_requests_by_requester(user2)
        assert len(user2_requests) == 1
        assert req3 in user2_requests

    # ---- get_requests_by_risk_level ----
    def test_get_requests_by_risk_level(self, policy):
        # We need to create requests with specific risk levels.
        # Low risk: small amount, error correction, same day
        req_low = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("1_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=1),
            requested_by=uuid4(),
            requested_by_name="L",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )  # auto-approved, risk LOW
        # Medium: amount 50M, age 3 days
        req_med = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="M",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # High: restatement
        req_high = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="H",
            reason=ReversalReason.RESTATEMENT,
            justification="",
        )
        low_list = policy.get_requests_by_risk_level(ReversalRiskLevel.LOW)
        assert len(low_list) == 1
        assert low_list[0].id == req_low.id

        med_list = policy.get_requests_by_risk_level(ReversalRiskLevel.MEDIUM)
        assert len(med_list) == 1
        assert med_list[0].id == req_med.id

        high_list = policy.get_requests_by_risk_level(ReversalRiskLevel.HIGH)
        assert len(high_list) == 1
        assert high_list[0].id == req_high.id

    # ---- expire_pending_requests ----
    def test_expire_pending_requests(self, policy):
        # create a request that will be expired (future expiry)
        req1 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="A",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # manually set expiry to past
        req1.expires_at = FIXED_NOW - timedelta(days=1)
        # another request with future expiry (should not be expired)
        req2 = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="B",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        req2.expires_at = FIXED_NOW + timedelta(days=5)

        expired_count = policy.expire_pending_requests()
        assert expired_count == 1
        assert req1.status == ReversalStatus.EXPIRED
        assert req2.status == ReversalStatus.PENDING  # not expired

    # ---- generate_report ----
    def test_generate_report(self, policy):
        # create a few requests with different statuses and reasons
        # auto-approved
        policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=1),
            requested_by=uuid4(),
            requested_by_name="A",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        # pending
        policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("50_000_000"),
            journal_date=FIXED_NOW - timedelta(days=3),
            requested_by=uuid4(),
            requested_by_name="B",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        # rejected
        req_rej = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("10_000_000"),
            journal_date=FIXED_NOW,
            requested_by=uuid4(),
            requested_by_name="C",
            reason=ReversalReason.ADJUSTMENT,
            justification="",
        )
        policy.reject(req_rej.id, uuid4(), "Manager", ReversalApprovalLevel.MANAGER, "bad")

        report = policy.generate_report()
        assert report["total_requests"] == 3
        assert report["pending"] == 1
        assert report["approved"] == 1
        assert report["rejected"] == 1
        assert report["implemented"] == 0
        assert report["expired"] == 0
        assert report["by_risk_level"]["low"] == 1
        assert report["by_risk_level"]["medium"] == 2
        assert report["by_reason"]["error_correction"] == 1
        assert report["by_reason"]["adjustment"] == 2

    # ---- to_json ----
    def test_to_json(self, policy):
        # create a request
        policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("5_000_000"),
            journal_date=FIXED_NOW - timedelta(hours=1),
            requested_by=uuid4(),
            requested_by_name="A",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        m = mock_open()
        with patch("builtins.open", m):
            policy.to_json("test.json")
        m.assert_called_once_with("test.json", "w")
        # check that write was called with data
        handle = m()
        # the data is written via json.dump; we can check that write was called at least once
        assert handle.write.called

    # ---- integration: full approval flow ----
    def test_full_approval_flow(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("500_000_000"),  # high risk
            journal_date=FIXED_NOW - timedelta(days=5),
            requested_by=uuid4(),
            requested_by_name="Analyst",
            reason=ReversalReason.ADJUSTMENT,
            justification="Large accrual correction",
        )
        assert req.status == ReversalStatus.PENDING
        assert req.risk_level == ReversalRiskLevel.HIGH

        # Approve with manager (insufficient for HIGH)
        result1 = policy.approve(req.id, uuid4(), "Manager", ReversalApprovalLevel.MANAGER, "Seems OK")
        assert result1 is True
        # Still pending because required is CONTROLLER
        assert req.status == ReversalStatus.PENDING
        assert len(req.approvals) == 1

        # Approve with controller (sufficient)
        result2 = policy.approve(req.id, uuid4(), "Controller", ReversalApprovalLevel.CONTROLLER, "Approved")
        assert result2 is True
        assert req.status == ReversalStatus.APPROVED
        assert len(req.approvals) == 2

        # Implement
        result3 = policy.implement_reversal(req.id, uuid4(), uuid4())
        assert result3 is True
        assert req.status == ReversalStatus.IMPLEMENTED

    # ---- test auto-approval with high amount (should not auto-approve) ----
    def test_no_auto_approve_for_high_amount(self, policy):
        req = policy.request_reversal(
            journal_id=uuid4(),
            journal_amount=Decimal("15_000_000"),  # >10M
            journal_date=FIXED_NOW - timedelta(hours=2),
            requested_by=uuid4(),
            requested_by_name="User",
            reason=ReversalReason.ERROR_CORRECTION,
            justification="",
        )
        assert req.status == ReversalStatus.PENDING  # not auto-approved
