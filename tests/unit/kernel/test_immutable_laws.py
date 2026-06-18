#!/usr/bin/env python3

"""
Module: test_immutable_laws.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk immutable laws enforcement.

Dependencies:
    - kernel/immutable_laws/*.py
    - pytest

Audit:
    Tests harus lulus 100% sebelum deployment.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest

from kernel.immutable_laws.asset_existence_enforcer import AssetExistenceEnforcer
from kernel.immutable_laws.audit_trail_completeness_enforcer import AuditTrailCompletenessEnforcer
from kernel.immutable_laws.dual_approval_enforcer import DualApprovalEnforcer
from kernel.immutable_laws.evidence_mandate_enforcer import EvidenceMandateEnforcer
from kernel.immutable_laws.fair_value_measurement_enforcer import FairValueMeasurementEnforcer
from kernel.immutable_laws.gl_supremacy_enforcer import GLSupremacyEnforcer
from kernel.immutable_laws.immutability_enforcer import ImmutabilityEnforcer
from kernel.immutable_laws.no_retroactive_policy_enforcer import NoRetroactivePolicyEnforcer
from kernel.immutable_laws.period_closure_enforcer import PeriodClosureEnforcer
from kernel.immutable_laws.reversal_constraint_enforcer import ReversalConstraintEnforcer
from kernel.immutable_laws.segregation_of_duties_enforcer import SegregationOfDutiesEnforcer
from kernel.immutable_laws.traceability_enforcer import TraceabilityEnforcer


class TestImmutabilityEnforcer:
    """Test suite untuk ImmutabilityEnforcer."""

    @pytest.fixture
    def immutability_enforcer(self):
        return ImmutabilityEnforcer()

    def test_immutable_event_cannot_be_modified(self, immutability_enforcer):
        event = {"id": uuid4(), "data": "original", "hash": "abc123"}
        # Should raise error if trying to modify
        with pytest.raises(PermissionError, match="immutable"):
            immutability_enforcer.enforce_modification(event)

    def test_new_event_passes(self, immutability_enforcer):
        event = {"id": uuid4(), "data": "new"}
        # No error for new events
        immutability_enforcer.enforce_creation(event)


class TestEvidenceMandateEnforcer:
    """Test suite untuk EvidenceMandateEnforcer."""

    @pytest.fixture
    def evidence_enforcer(self):
        return EvidenceMandateEnforcer()

    def test_transaction_with_evidence_passes(self, evidence_enforcer):
        context = {"transaction_id": uuid4(), "attachments": ["file1.pdf", "file2.jpg"]}
        errors = evidence_enforcer.check(context)
        assert len(errors) == 0

    def test_transaction_without_evidence_fails(self, evidence_enforcer):
        context = {"transaction_id": uuid4(), "attachments": []}
        errors = evidence_enforcer.check(context)
        assert len(errors) == 1
        assert "evidence" in errors[0].lower()


class TestDualApprovalEnforcer:
    """Test suite untuk DualApprovalEnforcer."""

    @pytest.fixture
    def dual_approval_enforcer(self):
        return DualApprovalEnforcer()

    def test_journal_requires_two_approvals(self, dual_approval_enforcer):
        context = {
            "journal_id": uuid4(),
            "approvals": [{"approver_id": uuid4(), "timestamp": datetime.utcnow()}],
        }
        errors = dual_approval_enforcer.check(context)
        assert len(errors) == 1  # need second approval
        context["approvals"].append({"approver_id": uuid4(), "timestamp": datetime.utcnow()})
        errors = dual_approval_enforcer.check(context)
        assert len(errors) == 0

    def test_approvers_must_be_different(self, dual_approval_enforcer):
        same_user = uuid4()
        context = {
            "journal_id": uuid4(),
            "approvals": [
                {"approver_id": same_user, "timestamp": datetime.utcnow()},
                {"approver_id": same_user, "timestamp": datetime.utcnow()},
            ],
        }
        errors = dual_approval_enforcer.check(context)
        assert len(errors) == 1
        assert "different" in errors[0].lower()


class TestReversalConstraintEnforcer:
    """Test suite untuk ReversalConstraintEnforcer."""

    @pytest.fixture
    def reversal_enforcer(self):
        return ReversalConstraintEnforcer()

    def test_reversal_allowed_within_period(self, reversal_enforcer):
        context = {
            "original_journal_date": date(2025, 3, 1),
            "reversal_date": date(2025, 3, 15),
            "period_status": "OPEN",
        }
        errors = reversal_enforcer.check(context)
        assert len(errors) == 0

    def test_reversal_disallowed_in_closed_period(self, reversal_enforcer):
        context = {
            "original_journal_date": date(2024, 12, 1),
            "reversal_date": date(2025, 3, 15),
            "period_status": "CLOSED",
        }
        errors = reversal_enforcer.check(context)
        assert len(errors) == 1


class TestTraceabilityEnforcer:
    """Test suite untuk TraceabilityEnforcer."""

    @pytest.fixture
    def traceability_enforcer(self):
        return TraceabilityEnforcer()

    def test_transaction_has_causation_id_passes(self, traceability_enforcer):
        context = {"transaction_id": uuid4(), "causation_id": uuid4()}
        errors = traceability_enforcer.check(context)
        assert len(errors) == 0

    def test_missing_causation_id_fails(self, traceability_enforcer):
        context = {"transaction_id": uuid4()}
        errors = traceability_enforcer.check(context)
        assert len(errors) == 1


class TestPeriodClosureEnforcer:
    """Test suite untuk PeriodClosureEnforcer."""

    @pytest.fixture
    def period_closure_enforcer(self):
        return PeriodClosureEnforcer()

    def test_transaction_in_open_period_passes(self, period_closure_enforcer):
        context = {"period": "2025-03", "period_status": "OPEN"}
        errors = period_closure_enforcer.check(context)
        assert len(errors) == 0

    def test_transaction_in_closed_period_fails(self, period_closure_enforcer):
        context = {"period": "2024-12", "period_status": "CLOSED"}
        errors = period_closure_enforcer.check(context)
        assert len(errors) == 1


class TestGLSupremacyEnforcer:
    """Test suite untuk GLSupremacyEnforcer."""

    @pytest.fixture
    def gl_supremacy_enforcer(self):
        return GLSupremacyEnforcer()

    def test_gl_entry_exists_for_subledger(self, gl_supremacy_enforcer, mocker):
        mock_gl = mocker.MagicMock()
        mock_gl.check_gl_entry_exists.return_value = True
        gl_supremacy_enforcer._gl_service = mock_gl
        context = {"subledger_entry_id": uuid4()}
        errors = gl_supremacy_enforcer.check(context)
        assert len(errors) == 0

    def test_missing_gl_entry_fails(self, gl_supremacy_enforcer, mocker):
        mock_gl = mocker.MagicMock()
        mock_gl.check_gl_entry_exists.return_value = False
        gl_supremacy_enforcer._gl_service = mock_gl
        context = {"subledger_entry_id": uuid4()}
        errors = gl_supremacy_enforcer.check(context)
        assert len(errors) == 1


class TestSegregationOfDutiesEnforcer:
    """Test suite untuk SegregationOfDutiesEnforcer."""

    @pytest.fixture
    def sod_enforcer(self):
        return SegregationOfDutiesEnforcer()

    def test_no_sod_violation_passes(self, sod_enforcer, mocker):
        mock_sod = mocker.MagicMock()
        mock_sod.check_violation.return_value = False
        sod_enforcer._sod_service = mock_sod
        context = {"user_id": uuid4(), "action": "CREATE_JOURNAL"}
        errors = sod_enforcer.check(context)
        assert len(errors) == 0

    def test_sod_violation_fails(self, sod_enforcer, mocker):
        mock_sod = mocker.MagicMock()
        mock_sod.check_violation.return_value = True
        sod_enforcer._sod_service = mock_sod
        context = {"user_id": uuid4(), "action": "CREATE_JOURNAL"}
        errors = sod_enforcer.check(context)
        assert len(errors) == 1


class TestNoRetroactivePolicyEnforcer:
    """Test suite untuk NoRetroactivePolicyEnforcer."""

    @pytest.fixture
    def retroactive_enforcer(self):
        return NoRetroactivePolicyEnforcer()

    def test_current_period_change_passes(self, retroactive_enforcer):
        context = {"effective_date": date.today(), "policy_effective_date": date.today()}
        errors = retroactive_enforcer.check(context)
        assert len(errors) == 0

    def test_retroactive_change_fails(self, retroactive_enforcer):
        context = {"effective_date": date(2024, 1, 1), "policy_effective_date": date.today()}
        errors = retroactive_enforcer.check(context)
        assert len(errors) == 1


class TestAuditTrailCompletenessEnforcer:
    """Test suite untuk AuditTrailCompletenessEnforcer."""

    @pytest.fixture
    def audit_trail_enforcer(self):
        return AuditTrailCompletenessEnforcer()

    def test_complete_audit_trail_passes(self, audit_trail_enforcer, mocker):
        mock_audit = mocker.MagicMock()
        mock_audit.check_completeness.return_value = True
        audit_trail_enforcer._audit_service = mock_audit
        context = {"transaction_id": uuid4()}
        errors = audit_trail_enforcer.check(context)
        assert len(errors) == 0

    def test_missing_audit_records_fails(self, audit_trail_enforcer, mocker):
        mock_audit = mocker.MagicMock()
        mock_audit.check_completeness.return_value = False
        audit_trail_enforcer._audit_service = mock_audit
        context = {"transaction_id": uuid4()}
        errors = audit_trail_enforcer.check(context)
        assert len(errors) == 1


class TestAssetExistenceEnforcer:
    """Test suite untuk AssetExistenceEnforcer."""

    @pytest.fixture
    def asset_existence_enforcer(self):
        return AssetExistenceEnforcer()

    def test_asset_exists_passes(self, asset_existence_enforcer, mocker):
        mock_asset = mocker.MagicMock()
        mock_asset.check_existence.return_value = True
        asset_existence_enforcer._asset_service = mock_asset
        context = {"asset_id": uuid4()}
        errors = asset_existence_enforcer.check(context)
        assert len(errors) == 0

    def test_asset_not_found_fails(self, asset_existence_enforcer, mocker):
        mock_asset = mocker.MagicMock()
        mock_asset.check_existence.return_value = False
        asset_existence_enforcer._asset_service = mock_asset
        context = {"asset_id": uuid4()}
        errors = asset_existence_enforcer.check(context)
        assert len(errors) == 1


class TestFairValueMeasurementEnforcer:
    """Test suite untuk FairValueMeasurementEnforcer."""

    @pytest.fixture
    def fair_value_enforcer(self):
        return FairValueMeasurementEnforcer()

    def test_fair_value_required_for_certain_assets(self, fair_value_enforcer, mocker):
        mock_fv = mocker.MagicMock()
        mock_fv.is_fair_value_required.return_value = True
        mock_fv.has_fair_value.return_value = True
        fair_value_enforcer._fair_value_service = mock_fv
        context = {"asset_id": uuid4(), "asset_type": "FINANCIAL_INSTRUMENT"}
        errors = fair_value_enforcer.check(context)
        assert len(errors) == 0

    def test_missing_fair_value_fails(self, fair_value_enforcer, mocker):
        mock_fv = mocker.MagicMock()
        mock_fv.is_fair_value_required.return_value = True
        mock_fv.has_fair_value.return_value = False
        fair_value_enforcer._fair_value_service = mock_fv
        context = {"asset_id": uuid4(), "asset_type": "FINANCIAL_INSTRUMENT"}
        errors = fair_value_enforcer.check(context)
        assert len(errors) == 1


if __name__ == "__main__":
    pytest.main([__file__])
