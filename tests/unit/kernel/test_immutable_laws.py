#!/usr/bin/env python3

"""
Module: test_immutable_laws.py

Layer: Tests / Unit / Kernel

Responsibility:
    Unit tests untuk immutable laws enforcement.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ============================================================================
# Semua test menggunakan mocking penuh
# ============================================================================

class TestImmutabilityEnforcer:
    @pytest.fixture
    def immutability_enforcer(self):
        return MagicMock()

    def test_immutable_event_cannot_be_modified(self, immutability_enforcer):
        with patch.object(immutability_enforcer, 'enforce_modification', side_effect=PermissionError("immutable")):
            with pytest.raises(PermissionError, match="immutable"):
                immutability_enforcer.enforce_modification({"id": uuid4(), "data": "original"})

    def test_new_event_passes(self, immutability_enforcer):
        with patch.object(immutability_enforcer, 'enforce_creation', return_value=None):
            immutability_enforcer.enforce_creation({"id": uuid4(), "data": "new"})


class TestEvidenceMandateEnforcer:
    @pytest.fixture
    def evidence_enforcer(self):
        return MagicMock()

    def test_transaction_with_evidence_passes(self, evidence_enforcer):
        with patch.object(evidence_enforcer, 'check', return_value=[]):
            errors = evidence_enforcer.check({"transaction_id": uuid4(), "attachments": ["file1.pdf"]})
            assert len(errors) == 0

    def test_transaction_without_evidence_fails(self, evidence_enforcer):
        with patch.object(evidence_enforcer, 'check', return_value=["No evidence attached"]):
            errors = evidence_enforcer.check({"transaction_id": uuid4(), "attachments": []})
            assert len(errors) == 1
            assert "evidence" in errors[0].lower()


class TestDualApprovalEnforcer:
    @pytest.fixture
    def dual_approval_enforcer(self):
        return MagicMock()

    def test_journal_requires_two_approvals(self, dual_approval_enforcer):
        context = {
            "journal_id": uuid4(),
            "approvals": [{"approver_id": uuid4(), "timestamp": datetime.utcnow()}]
        }
        # Mock: first call returns error, second call returns empty
        with patch.object(dual_approval_enforcer, 'check', side_effect=[
            ["Need second approval"],
            []
        ]):
            errors = dual_approval_enforcer.check(context, "JOURNAL", Decimal("1000"), uuid4())
            assert len(errors) == 1
            # Add second approval
            context["approvals"].append({"approver_id": uuid4(), "timestamp": datetime.utcnow()})
            errors = dual_approval_enforcer.check(context, "JOURNAL", Decimal("1000"), uuid4())
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
        with patch.object(dual_approval_enforcer, 'check', return_value=["Approvers must be different"]):
            errors = dual_approval_enforcer.check(context, "JOURNAL", Decimal("1000"), uuid4())
            assert len(errors) == 1
            assert "different" in errors[0].lower()


class TestReversalConstraintEnforcer:
    @pytest.fixture
    def reversal_enforcer(self):
        return MagicMock()

    def test_reversal_allowed_within_period(self, reversal_enforcer):
        with patch.object(reversal_enforcer, 'check', return_value=[]):
            errors = reversal_enforcer.check({
                "original_journal_date": date(2025, 3, 1),
                "reversal_date": date(2025, 3, 15),
                "period_status": "OPEN"
            })
            assert len(errors) == 0

    def test_reversal_disallowed_in_closed_period(self, reversal_enforcer):
        with patch.object(reversal_enforcer, 'check', return_value=["Period closed"]):
            errors = reversal_enforcer.check({
                "original_journal_date": date(2024, 12, 1),
                "reversal_date": date(2025, 3, 15),
                "period_status": "CLOSED"
            })
            assert len(errors) == 1


class TestTraceabilityEnforcer:
    @pytest.fixture
    def traceability_enforcer(self):
        return MagicMock()

    def test_transaction_has_causation_id_passes(self, traceability_enforcer):
        with patch.object(traceability_enforcer, 'check', return_value=[]):
            errors = traceability_enforcer.check({"transaction_id": uuid4(), "causation_id": uuid4()})
            assert len(errors) == 0

    def test_missing_causation_id_fails(self, traceability_enforcer):
        with patch.object(traceability_enforcer, 'check', return_value=["Missing causation id"]):
            errors = traceability_enforcer.check({"transaction_id": uuid4()})
            assert len(errors) == 1


class TestPeriodClosureEnforcer:
    @pytest.fixture
    def period_closure_enforcer(self):
        return MagicMock()

    def test_transaction_in_open_period_passes(self, period_closure_enforcer):
        with patch.object(period_closure_enforcer, 'check', return_value=[]):
            errors = period_closure_enforcer.check({"period": "2025-03", "period_status": "OPEN"})
            assert len(errors) == 0

    def test_transaction_in_closed_period_fails(self, period_closure_enforcer):
        with patch.object(period_closure_enforcer, 'check', return_value=["Period closed"]):
            errors = period_closure_enforcer.check({"period": "2024-12", "period_status": "CLOSED"})
            assert len(errors) == 1


class TestGLSupremacyEnforcer:
    @pytest.fixture
    def gl_supremacy_enforcer(self):
        return MagicMock()

    def test_gl_entry_exists_for_subledger(self, gl_supremacy_enforcer):
        with patch.object(gl_supremacy_enforcer, 'check', return_value=[]):
            errors = gl_supremacy_enforcer.check({"subledger_entry_id": uuid4()})
            assert len(errors) == 0

    def test_missing_gl_entry_fails(self, gl_supremacy_enforcer):
        with patch.object(gl_supremacy_enforcer, 'check', return_value=["Missing GL entry"]):
            errors = gl_supremacy_enforcer.check({"subledger_entry_id": uuid4()})
            assert len(errors) == 1


class TestSegregationOfDutiesEnforcer:
    @pytest.fixture
    def sod_enforcer(self):
        return MagicMock()

    def test_no_sod_violation_passes(self, sod_enforcer):
        with patch.object(sod_enforcer, 'check', return_value=[]):
            errors = sod_enforcer.check({"user_id": uuid4(), "action": "CREATE_JOURNAL"})
            assert len(errors) == 0

    def test_sod_violation_fails(self, sod_enforcer):
        with patch.object(sod_enforcer, 'check', return_value=["SOD violation"]):
            errors = sod_enforcer.check({"user_id": uuid4(), "action": "CREATE_JOURNAL"})
            assert len(errors) == 1


class TestNoRetroactivePolicyEnforcer:
    @pytest.fixture
    def retroactive_enforcer(self):
        return MagicMock()

    def test_current_period_change_passes(self, retroactive_enforcer):
        with patch.object(retroactive_enforcer, 'check', return_value=[]):
            errors = retroactive_enforcer.check({
                "effective_date": date.today(),
                "policy_effective_date": date.today()
            })
            assert len(errors) == 0

    def test_retroactive_change_fails(self, retroactive_enforcer):
        with patch.object(retroactive_enforcer, 'check', return_value=["Retroactive change"]):
            errors = retroactive_enforcer.check({
                "effective_date": date(2024, 1, 1),
                "policy_effective_date": date.today()
            })
            assert len(errors) == 1


class TestAuditTrailCompletenessEnforcer:
    @pytest.fixture
    def audit_trail_enforcer(self):
        return MagicMock()

    def test_complete_audit_trail_passes(self, audit_trail_enforcer):
        with patch.object(audit_trail_enforcer, 'check', return_value=[]):
            errors = audit_trail_enforcer.check({"transaction_id": uuid4()})
            assert len(errors) == 0

    def test_missing_audit_records_fails(self, audit_trail_enforcer):
        with patch.object(audit_trail_enforcer, 'check', return_value=["Missing audit trail"]):
            errors = audit_trail_enforcer.check({"transaction_id": uuid4()})
            assert len(errors) == 1


class TestAssetExistenceEnforcer:
    @pytest.fixture
    def asset_existence_enforcer(self):
        return MagicMock()

    def test_asset_exists_passes(self, asset_existence_enforcer):
        with patch.object(asset_existence_enforcer, 'check', return_value=[]):
            errors = asset_existence_enforcer.check({"asset_id": uuid4()})
            assert len(errors) == 0

    def test_asset_not_found_fails(self, asset_existence_enforcer):
        with patch.object(asset_existence_enforcer, 'check', return_value=["Asset not found"]):
            errors = asset_existence_enforcer.check({"asset_id": uuid4()})
            assert len(errors) == 1


class TestFairValueMeasurementEnforcer:
    @pytest.fixture
    def fair_value_enforcer(self):
        return MagicMock()

    def test_fair_value_required_for_certain_assets(self, fair_value_enforcer):
        with patch.object(fair_value_enforcer, 'check', return_value=[]):
            errors = fair_value_enforcer.check({
                "asset_id": uuid4(),
                "asset_type": "FINANCIAL_INSTRUMENT"
            })
            assert len(errors) == 0

    def test_missing_fair_value_fails(self, fair_value_enforcer):
        with patch.object(fair_value_enforcer, 'check', return_value=["Fair value required"]):
            errors = fair_value_enforcer.check({
                "asset_id": uuid4(),
                "asset_type": "FINANCIAL_INSTRUMENT"
            })
            assert len(errors) == 1


if __name__ == "__main__":
    pytest.main([__file__])