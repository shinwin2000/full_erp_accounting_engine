# tests/compliance/legal/test_legal_override_with_citation.py
"""
Comprehensive tests for compliance/legal/legal_override_with_citation.py.

Covers:
- Enums: OverrideStatus, OverrideRiskLevel, OverrideApprovalLevel
- Exceptions: OverrideError, OverrideNotAllowedError, OverrideNotFoundError
- LegalOverride: construction, approve, reject, revoke, is_active, to_dict, hash
- LegalOverrideWithCitation:
  - _init_allowed_citations (tested via citation info retrieval)
  - _get_citation_info
  - request_override (success, invalid citation)
  - approve_override (success, insufficient level, not found)
  - reject_override, revoke_override
  - is_overridden, get_active_override
  - get_all_overrides, get_pending_overrides, get_expired_overrides
  - expire_pending_overrides
  - generate_report, to_json
- Edge cases: expiry dates, active status, multiple overrides same rule
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest

from compliance.legal.legal_override_with_citation import (
    LegalOverride,
    LegalOverrideWithCitation,
    OverrideApprovalLevel,
    OverrideError,
    OverrideNotAllowedError,
    OverrideNotFoundError,
    OverrideRiskLevel,
    OverrideStatus,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_override():
    """A sample LegalOverride in PENDING status."""
    return LegalOverride(
        override_id=uuid4(),
        rule_id="JOURNAL_POSTING_RULE",
        rule_description="Journal must have approval before posting",
        justification="Emergency year-end adjustment needed",
        legal_citation="PSAK 25 paragraf 12",
        requested_by=uuid4(),
        requested_by_name="Finance Manager",
        risk_level=OverrideRiskLevel.MEDIUM,
        effective_date=date.today(),
        expiry_date=date.today() + timedelta(days=30),
        status=OverrideStatus.PENDING,
    )


@pytest.fixture
def approved_override(sample_override):
    """A sample LegalOverride in APPROVED status."""
    sample_override.approve(
        approver_id=uuid4(),
        approver_name="Compliance Director",
        approval_level=OverrideApprovalLevel.DIRECTOR,
    )
    return sample_override


@pytest.fixture
def expired_override():
    """An override that is already expired."""
    past = date.today() - timedelta(days=10)
    override = LegalOverride(
        override_id=uuid4(),
        rule_id="EXPIRED_RULE",
        rule_description="Expired rule",
        justification="Test",
        legal_citation="SE-11/PJ/2024",
        requested_by=uuid4(),
        requested_by_name="Tester",
        risk_level=OverrideRiskLevel.LOW,
        effective_date=past - timedelta(days=30),
        expiry_date=past,
        status=OverrideStatus.APPROVED,
    )
    return override


@pytest.fixture
def manager():
    """A fresh LegalOverrideWithCitation instance with default allowed citations."""
    return LegalOverrideWithCitation()


# ============================================================================
# Tests for Enums
# ============================================================================

class TestOverrideStatus:
    def test_members(self):
        assert OverrideStatus.PENDING.value == "pending"
        assert OverrideStatus.APPROVED.value == "approved"
        assert OverrideStatus.REJECTED.value == "rejected"
        assert OverrideStatus.EXPIRED.value == "expired"
        assert OverrideStatus.REVOKED.value == "revoked"


class TestOverrideRiskLevel:
    def test_members(self):
        assert OverrideRiskLevel.LOW.value == "low"
        assert OverrideRiskLevel.MEDIUM.value == "medium"
        assert OverrideRiskLevel.HIGH.value == "high"
        assert OverrideRiskLevel.CRITICAL.value == "critical"


class TestOverrideApprovalLevel:
    def test_members(self):
        assert OverrideApprovalLevel.SUPERVISOR.value == "supervisor"
        assert OverrideApprovalLevel.MANAGER.value == "manager"
        assert OverrideApprovalLevel.DIRECTOR.value == "director"
        assert OverrideApprovalLevel.VP.value == "vp"
        assert OverrideApprovalLevel.C_SUITE.value == "c_suite"
        assert OverrideApprovalLevel.BOARD.value == "board"


# ============================================================================
# Tests for Exceptions
# ============================================================================

class TestExceptions:
    def test_override_error(self):
        with pytest.raises(OverrideError, match="test"):
            raise OverrideError("test")

    def test_override_not_allowed_error(self):
        with pytest.raises(OverrideNotAllowedError, match="not allowed"):
            raise OverrideNotAllowedError("not allowed")

    def test_override_not_found_error(self):
        with pytest.raises(OverrideNotFoundError, match="not found"):
            raise OverrideNotFoundError("not found")


# ============================================================================
# Tests for LegalOverride
# ============================================================================

class TestLegalOverride:
    def test_construction(self, sample_override):
        assert sample_override.id is not None
        assert sample_override.rule_id == "JOURNAL_POSTING_RULE"
        assert sample_override.status == OverrideStatus.PENDING
        assert sample_override._hash != ""

    def test_approve_success(self, sample_override):
        approver_id = uuid4()
        sample_override.approve(
            approver_id=approver_id,
            approver_name="Approver",
            approval_level=OverrideApprovalLevel.MANAGER,
        )
        assert sample_override.status == OverrideStatus.APPROVED
        assert sample_override.approved_by == approver_id
        assert sample_override.approved_at is not None
        assert sample_override.approval_level == OverrideApprovalLevel.MANAGER
        # Hash should update
        assert sample_override._hash != ""

    def test_approve_fails_if_not_pending(self, approved_override):
        with pytest.raises(OverrideError, match="Cannot approve override with status approved"):
            approved_override.approve(
                approver_id=uuid4(),
                approver_name="X",
                approval_level=OverrideApprovalLevel.MANAGER,
            )

    def test_reject_success(self, sample_override):
        approver_id = uuid4()
        sample_override.reject(
            approver_id=approver_id,
            approver_name="Rejecter",
            reason="Not justified",
        )
        assert sample_override.status == OverrideStatus.REJECTED
        assert sample_override.rejection_reason == "Not justified"
        assert sample_override.approved_by == approver_id

    def test_reject_fails_if_not_pending(self, approved_override):
        with pytest.raises(OverrideError, match="Cannot reject override with status approved"):
            approved_override.reject(uuid4(), "X", "reason")

    def test_revoke_success(self, approved_override):
        revoked_by = uuid4()
        approved_override.revoke(revoked_by=revoked_by, reason="Policy change")
        assert approved_override.status == OverrideStatus.REVOKED
        assert approved_override._hash != ""

    def test_revoke_fails_if_not_approved(self, sample_override):
        with pytest.raises(OverrideError, match="Cannot revoke override with status pending"):
            sample_override.revoke(uuid4(), "reason")

    def test_is_active(self, sample_override, approved_override, expired_override):
        # PENDING is not active
        assert sample_override.is_active() is False
        # APPROVED within date range is active
        assert approved_override.is_active() is True
        # Expired is not active
        assert expired_override.is_active() is False

        # Test with custom date
        future = date.today() + timedelta(days=60)
        assert approved_override.is_active(as_of=future) is False  # expired

    def test_to_dict(self, sample_override):
        d = sample_override.to_dict()
        assert d["rule_id"] == "JOURNAL_POSTING_RULE"
        assert d["status"] == "pending"
        assert d["legal_citation"] == "PSAK 25 paragraf 12"
        assert "hash" in d

    def test_compute_hash_consistency(self, sample_override):
        h1 = sample_override._compute_hash()
        h2 = sample_override._compute_hash()
        assert h1 == h2
        # Change status should change hash
        sample_override.status = OverrideStatus.APPROVED
        assert sample_override._compute_hash() != h1


# ============================================================================
# Tests for LegalOverrideWithCitation
# ============================================================================

class TestLegalOverrideWithCitation:
    def test_init(self, manager):
        assert manager._overrides == {}
        assert manager._rule_index == {}
        assert len(manager._allowed_citations) > 0

    def test__get_citation_info(self, manager):
        # Valid citation
        info = manager._get_citation_info("PSAK 25 paragraf 12")
        assert info is not None
        assert info["approval_level"] == OverrideApprovalLevel.MANAGER
        assert info["risk"] == OverrideRiskLevel.MEDIUM

        # Invalid citation
        info2 = manager._get_citation_info("Invalid citation")
        assert info2 is None

    def test_request_override_success(self, manager):
        req_id = manager.request_override(
            rule_id="RULE_001",
            rule_description="Test rule",
            justification="Emergency",
            legal_citation="PSAK 25 paragraf 12",
            requested_by=uuid4(),
            requested_by_name="Tester",
            effective_date=date.today(),
            expiry_date=date.today() + timedelta(days=10),
        )
        assert req_id is not None
        override = manager._overrides[req_id]
        assert override.rule_id == "RULE_001"
        assert override.status == OverrideStatus.PENDING
        assert override.risk_level == OverrideRiskLevel.MEDIUM
        # Check index
        assert req_id in manager._rule_index["RULE_001"]

    def test_request_override_invalid_citation(self, manager):
        with pytest.raises(OverrideNotAllowedError, match="not recognized"):
            manager.request_override(
                rule_id="RULE_001",
                rule_description="Test",
                justification="Test",
                legal_citation="Invalid citation",
                requested_by=uuid4(),
                requested_by_name="Tester",
            )

    def test_approve_override_success(self, manager, sample_override):
        # Add override manually
        override_id = sample_override.id
        manager._overrides[override_id] = sample_override
        manager._rule_index.setdefault(sample_override.rule_id, []).append(override_id)

        result = manager.approve_override(
            override_id=override_id,
            approver_id=uuid4(),
            approver_name="Approver",
            approver_level=OverrideApprovalLevel.DIRECTOR,
        )
        assert result is True
        assert sample_override.status == OverrideStatus.APPROVED

    def test_approve_override_insufficient_level(self, manager, sample_override):
        override_id = sample_override.id
        manager._overrides[override_id] = sample_override
        manager._rule_index.setdefault(sample_override.rule_id, []).append(override_id)

        # PSAK 25 requires MANAGER, but we try SUPERVISOR
        with pytest.raises(OverrideNotAllowedError, match="insufficient"):
            manager.approve_override(
                override_id=override_id,
                approver_id=uuid4(),
                approver_name="Supervisor",
                approver_level=OverrideApprovalLevel.SUPERVISOR,
            )

    def test_approve_override_not_found(self, manager):
        with pytest.raises(OverrideNotFoundError, match="not found"):
            manager.approve_override(
                override_id=uuid4(),
                approver_id=uuid4(),
                approver_name="X",
                approver_level=OverrideApprovalLevel.MANAGER,
            )

    def test_reject_override_success(self, manager, sample_override):
        override_id = sample_override.id
        manager._overrides[override_id] = sample_override
        manager._rule_index.setdefault(sample_override.rule_id, []).append(override_id)

        result = manager.reject_override(
            override_id=override_id,
            approver_id=uuid4(),
            approver_name="Rejecter",
            reason="No justification",
        )
        assert result is True
        assert sample_override.status == OverrideStatus.REJECTED

    def test_reject_override_not_found(self, manager):
        result = manager.reject_override(
            override_id=uuid4(),
            approver_id=uuid4(),
            approver_name="X",
            reason="No",
        )
        assert result is False

    def test_revoke_override_success(self, manager, approved_override):
        override_id = approved_override.id
        manager._overrides[override_id] = approved_override
        manager._rule_index.setdefault(approved_override.rule_id, []).append(override_id)

        result = manager.revoke_override(
            override_id=override_id,
            revoked_by=uuid4(),
            reason="Policy update",
        )
        assert result is True
        assert approved_override.status == OverrideStatus.REVOKED

    def test_revoke_override_not_found(self, manager):
        result = manager.revoke_override(
            override_id=uuid4(),
            revoked_by=uuid4(),
            reason="No",
        )
        assert result is False

    def test_is_overridden(self, manager, approved_override):
        rule_id = approved_override.rule_id
        override_id = approved_override.id
        manager._overrides[override_id] = approved_override
        manager._rule_index.setdefault(rule_id, []).append(override_id)

        # Active override exists
        assert manager.is_overridden(rule_id) is True

        # Another rule not overridden
        assert manager.is_overridden("NON_EXISTENT") is False

        # Check with future date (should be False if expired)
        future = date.today() + timedelta(days=60)
        # The override expiry is 30 days from now, so future should be False
        assert manager.is_overridden(rule_id, as_of=future) is False

    def test_get_active_override(self, manager, approved_override):
        rule_id = approved_override.rule_id
        override_id = approved_override.id
        manager._overrides[override_id] = approved_override
        manager._rule_index.setdefault(rule_id, []).append(override_id)

        active = manager.get_active_override(rule_id)
        assert active == approved_override

        # No active for other rule
        assert manager.get_active_override("NON_EXISTENT") is None

    def test_get_all_overrides(self, manager, sample_override, approved_override):
        # Add two overrides
        o1 = sample_override
        o2 = approved_override
        manager._overrides[o1.id] = o1
        manager._overrides[o2.id] = o2
        manager._rule_index.setdefault(o1.rule_id, []).append(o1.id)
        manager._rule_index.setdefault(o2.rule_id, []).append(o2.id)

        all_ov = manager.get_all_overrides()
        assert len(all_ov) == 2

        by_status = manager.get_all_overrides(status=OverrideStatus.APPROVED)
        assert len(by_status) == 1
        assert by_status[0].id == o2.id

    def test_get_pending_overrides(self, manager, sample_override, approved_override):
        o1 = sample_override  # PENDING
        o2 = approved_override  # APPROVED
        manager._overrides[o1.id] = o1
        manager._overrides[o2.id] = o2

        pending = manager.get_pending_overrides()
        assert len(pending) == 1
        assert pending[0].id == o1.id

    def test_get_expired_overrides(self, manager, expired_override):
        # Add an expired override
        manager._overrides[expired_override.id] = expired_override
        expired_list = manager.get_expired_overrides()
        assert len(expired_list) == 1
        assert expired_list[0].id == expired_override.id

        # Approved but not expired should not appear
        active = LegalOverride(
            override_id=uuid4(),
            rule_id="ACTIVE",
            rule_description="Active",
            justification="Test",
            legal_citation="SE-11/PJ/2024",
            requested_by=uuid4(),
            requested_by_name="Tester",
            risk_level=OverrideRiskLevel.LOW,
            effective_date=date.today(),
            expiry_date=date.today() + timedelta(days=30),
            status=OverrideStatus.APPROVED,
        )
        manager._overrides[active.id] = active
        expired_list2 = manager.get_expired_overrides()
        # Still only the expired one
        assert len(expired_list2) == 1

    def test_expire_pending_overrides(self, manager, sample_override):
        # Create a pending override older than threshold
        old_override = LegalOverride(
            override_id=uuid4(),
            rule_id="OLD_RULE",
            rule_description="Old",
            justification="Test",
            legal_citation="SE-11/PJ/2024",
            requested_by=uuid4(),
            requested_by_name="Tester",
            risk_level=OverrideRiskLevel.LOW,
            effective_date=date.today() - timedelta(days=40),
            expiry_date=date.today() + timedelta(days=10),
            status=OverrideStatus.PENDING,
        )
        # Manually set created_at to 40 days ago
        old_override.created_at = datetime.utcnow() - timedelta(days=40)
        manager._overrides[old_override.id] = old_override

        # Add a newer pending override
        new_override = sample_override  # created now
        manager._overrides[new_override.id] = new_override

        count = manager.expire_pending_overrides(days_threshold=30)
        assert count == 1
        assert old_override.status == OverrideStatus.EXPIRED
        assert new_override.status == OverrideStatus.PENDING  # not expired

        # Another call with lower threshold should not affect already expired
        count2 = manager.expire_pending_overrides(days_threshold=10)
        assert count2 == 0  # already expired

    def test_generate_report(self, manager, sample_override, approved_override, expired_override):
        # Add multiple overrides
        o1 = sample_override  # PENDING
        o2 = approved_override  # APPROVED
        o3 = expired_override   # APPROVED but expired
        manager._overrides[o1.id] = o1
        manager._overrides[o2.id] = o2
        manager._overrides[o3.id] = o3

        report = manager.generate_report()
        assert report["total_overrides"] == 3
        assert report["pending"] == 1
        assert report["approved"] == 2
        assert report["rejected"] == 0
        assert report["active"] == 1  # only o2 is active
        assert report["expired"] == 1  # o3
        assert report["by_risk_level"]["medium"] == 1
        assert report["by_risk_level"]["low"] == 1  # o3 has LOW

    def test_to_json(self, manager, sample_override):
        manager._overrides[sample_override.id] = sample_override
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            manager.to_json(file_path)
            with open(file_path) as f:
                data = json.load(f)
            assert "report" in data
            assert "overrides" in data
            assert len(data["overrides"]) == 1
            assert data["overrides"][0]["rule_id"] == "JOURNAL_POSTING_RULE"
        finally:
            import os
            os.unlink(file_path)

    def test__init_allowed_citations(self, manager):
        # Already tested via _get_citation_info, but we can ensure it returns list
        citations = manager._init_allowed_citations()
        assert isinstance(citations, list)
        assert len(citations) > 0
        # Check one citation
        found = False
        for c in citations:
            if c["citation"] == "PSAK 25 paragraf 12":
                found = True
                assert c["approval_level"] == OverrideApprovalLevel.MANAGER
        assert found is True
