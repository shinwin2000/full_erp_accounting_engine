#!/usr/bin/env python3
"""
Module: test_immutable_laws.py

Layer: Tests / Unit / Kernel

Responsibility:
    Comprehensive unit tests for immutable laws enforcement with real code implementation.
    Covers all enforcer classes and their methods: check, enforce, to_dict, from_dict,
    clone, snapshot, version, audit_trail, touch, validate.
    Uses mocked datetime to avoid flakiness.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from kernel.immutable_laws import (
    AssetExistenceEnforcer,
    AssetExistenceError,
    AuditTrailCompletenessEnforcer,
    AuditTrailCompletenessError,
    BaseEnforcer,
    DualApprovalEnforcer,
    DualApprovalError,
    EvidenceMandateEnforcer,
    EvidenceMandateError,
    FairValueMeasurementEnforcer,
    FairValueMeasurementError,
    GLSupremacyEnforcer,
    GLSupremacyError,
    ImmutabilityEnforcer,
    ImmutabilityError,
    NoRetroactivePolicyEnforcer,
    NoRetroactivePolicyError,
    PeriodClosureEnforcer,
    PeriodClosureError,
    ReversalConstraintEnforcer,
    ReversalConstraintError,
    SegregationOfDutiesEnforcer,
    SegregationOfDutiesError,
    TraceabilityEnforcer,
    TraceabilityError,
)

# =============================================================================
# Fixtures
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0)
FIXED_DATE = date(2026, 1, 15)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now and date.today to return fixed values."""
    with patch("kernel.immutable_laws.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture(autouse=True)
def mock_date_today():
    """Mock date.today to return fixed date."""
    with patch("kernel.immutable_laws.date") as mock_date:
        mock_date.today.return_value = FIXED_DATE
        yield mock_date


# =============================================================================
# BaseEnforcer tests
# =============================================================================


class TestBaseEnforcer:
    def test_init(self):
        enforcer = BaseEnforcer("test")
        assert enforcer.name == "test"
        assert enforcer._version == 1
        assert enforcer._audit_trail == []
        assert enforcer._snapshots == []

    def test_validate(self):
        enforcer = BaseEnforcer("test")
        result = enforcer.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []

        enforcer.name = ""
        result = enforcer.validate()
        assert result["is_valid"] is False
        assert "Enforcer name is required" in result["errors"]

    def test_to_dict(self):
        enforcer = BaseEnforcer("test")
        d = enforcer.to_dict()
        assert d["name"] == "test"
        assert d["version"] == 1

    def test_from_dict(self):
        data = {"name": "restored", "version": 5}
        enforcer = BaseEnforcer.from_dict(data)
        assert enforcer.name == "restored"
        assert enforcer._version == 5

    def test_clone(self):
        enforcer = BaseEnforcer("original")
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned.name == enforcer.name
        assert cloned._version == enforcer._version + 1

    def test_snapshot(self):
        enforcer = BaseEnforcer("test")
        snap = enforcer.snapshot()
        assert snap["name"] == "test"
        assert snap["version"] == 1
        assert "timestamp" in snap

    def test_version(self):
        enforcer = BaseEnforcer("test")
        assert enforcer.version() == 1
        enforcer._version = 5
        assert enforcer.version() == 5

    def test_audit_trail(self):
        enforcer = BaseEnforcer("test")
        assert enforcer.audit_trail() == []
        enforcer.touch("admin")
        trail = enforcer.audit_trail()
        assert len(trail) == 1
        assert trail[0]["action"] == "TOUCH"
        assert trail[0]["performed_by"] == "admin"

    def test_touch(self):
        enforcer = BaseEnforcer("test")
        old_version = enforcer._version
        enforcer.touch("user")
        assert enforcer._version == old_version + 1
        assert enforcer._audit_trail[-1]["action"] == "TOUCH"

    def test_record_audit(self):
        enforcer = BaseEnforcer("test")
        enforcer._record_audit("TEST", "user", {"data": 1})
        assert len(enforcer._audit_trail) == 1
        entry = enforcer._audit_trail[0]
        assert entry["action"] == "TEST"
        assert entry["performed_by"] == "user"
        assert entry["details"] == {"data": 1}

    def test_check_default(self):
        enforcer = BaseEnforcer("test")
        assert enforcer.check({}) == []

    def test_enforce_default(self):
        enforcer = BaseEnforcer("test")
        enforcer.enforce({})  # Should not raise


# =============================================================================
# ImmutabilityEnforcer
# =============================================================================


class TestImmutabilityEnforcer:
    def test_init(self):
        enforcer = ImmutabilityEnforcer()
        assert enforcer.name == "immutability_enforcer"
        assert enforcer._immutable_events == set()

    def test_enforce_modification_raises(self):
        enforcer = ImmutabilityEnforcer()
        event = {"id": "evt-1"}
        enforcer.enforce_creation(event)
        with pytest.raises(ImmutabilityError, match="Cannot modify immutable event"):
            enforcer.enforce_modification(event)

    def test_enforce_creation_adds_to_set(self):
        enforcer = ImmutabilityEnforcer()
        event = {"id": "evt-2"}
        enforcer.enforce_creation(event)
        assert "evt-2" in enforcer._immutable_events
        assert len(enforcer._audit_trail) == 1
        assert enforcer._audit_trail[0]["action"] == "ENFORCE_CREATION"

    def test_check_returns_errors(self):
        enforcer = ImmutabilityEnforcer()
        enforcer._immutable_events.add("evt-1")
        errors = enforcer.check({"event_id": "evt-1"})
        assert len(errors) == 1
        assert "immutable" in errors[0]
        errors = enforcer.check({"event_id": "evt-2"})
        assert errors == []

    def test_enforce_raises_if_check_fails(self):
        enforcer = ImmutabilityEnforcer()
        enforcer._immutable_events.add("evt-1")
        with pytest.raises(ImmutabilityError, match="immutable"):
            enforcer.enforce({"event_id": "evt-1"})

    def test_to_dict_includes_state(self):
        enforcer = ImmutabilityEnforcer()
        enforcer._immutable_events = {"a", "b"}
        d = enforcer.to_dict()
        assert d["immutable_events"] == ["a", "b"]

    def test_from_dict_restores_state(self):
        data = {"version": 3, "immutable_events": ["x", "y"]}
        enforcer = ImmutabilityEnforcer.from_dict(data)
        assert enforcer._version == 3
        assert enforcer._immutable_events == {"x", "y"}

    def test_clone_copies_state(self):
        enforcer = ImmutabilityEnforcer()
        enforcer._immutable_events = {"a", "b"}
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned._immutable_events == {"a", "b"}
        assert cloned._version == enforcer._version + 1
        # Ensure mutation doesn't affect original
        cloned._immutable_events.add("c")
        assert "c" not in enforcer._immutable_events

    def test_snapshot_counts_events(self):
        enforcer = ImmutabilityEnforcer()
        enforcer._immutable_events = {"a", "b", "c"}
        snap = enforcer.snapshot()
        assert snap["immutable_events_count"] == 3


# =============================================================================
# EvidenceMandateEnforcer
# =============================================================================


class TestEvidenceMandateEnforcer:
    def test_init(self):
        enforcer = EvidenceMandateEnforcer()
        assert enforcer.name == "evidence_mandate_enforcer"
        assert "WRITE_OFF" in enforcer._mandatory_transaction_types

    def test_check_valid_with_evidence(self):
        enforcer = EvidenceMandateEnforcer()
        context = {"type": "WRITE_OFF", "attachments": [{"id": "doc1"}]}
        assert enforcer.check(context) == []

    def test_check_invalid_without_evidence(self):
        enforcer = EvidenceMandateEnforcer()
        context = {"type": "WRITE_OFF", "attachments": []}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "supporting evidence" in errors[0]

    def test_check_non_mandatory_type(self):
        enforcer = EvidenceMandateEnforcer()
        context = {"type": "PURCHASE", "attachments": []}
        assert enforcer.check(context) == []

    def test_enforce_raises_if_check_fails(self):
        enforcer = EvidenceMandateEnforcer()
        context = {"type": "ADJUSTMENT", "attachments": []}
        with pytest.raises(EvidenceMandateError, match="evidence"):
            enforcer.enforce(context)

    def test_to_dict_includes_types(self):
        enforcer = EvidenceMandateEnforcer()
        d = enforcer.to_dict()
        assert d["mandatory_transaction_types"] == enforcer._mandatory_transaction_types

    def test_from_dict_restores_types(self):
        data = {"version": 2, "mandatory_transaction_types": ["X", "Y"]}
        enforcer = EvidenceMandateEnforcer.from_dict(data)
        assert enforcer._version == 2
        assert enforcer._mandatory_transaction_types == ["X", "Y"]

    def test_clone_copies_types(self):
        enforcer = EvidenceMandateEnforcer()
        original_types = enforcer._mandatory_transaction_types.copy()
        cloned = enforcer.clone()
        assert cloned is not enforcer
        assert cloned._mandatory_transaction_types == original_types
        assert cloned._version == enforcer._version + 1


# =============================================================================
# DualApprovalEnforcer
# =============================================================================


class TestDualApprovalEnforcer:
    def test_init(self):
        enforcer = DualApprovalEnforcer()
        assert "JOURNAL" in enforcer._require_dual_approval_for

    def test_check_valid_two_approvers(self):
        enforcer = DualApprovalEnforcer()
        context = {
            "transaction_type": "JOURNAL",
            "approvals": [{"approver": "user1"}, {"approver": "user2"}],
        }
        assert enforcer.check(context) == []

    def test_check_requires_two_approvers(self):
        enforcer = DualApprovalEnforcer()
        context = {"transaction_type": "JOURNAL", "approvals": [{"approver": "user1"}]}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "requires two approvals" in errors[0]

    def test_check_approvers_must_be_different(self):
        enforcer = DualApprovalEnforcer()
        context = {
            "transaction_type": "JOURNAL",
            "approvals": [{"approver": "user1"}, {"approver": "user1"}],
        }
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Approvers must be different" in errors[0]

    def test_check_non_dual_type_passes(self):
        enforcer = DualApprovalEnforcer()
        context = {"transaction_type": "PURCHASE", "approvals": []}
        assert enforcer.check(context) == []

    def test_enforce_raises_on_violation(self):
        enforcer = DualApprovalEnforcer()
        context = {"transaction_type": "PAYMENT", "approvals": [{"approver": "u1"}]}
        with pytest.raises(DualApprovalError, match="requires two approvals"):
            enforcer.enforce(context)

    def test_to_dict_from_dict_clone(self):
        enforcer = DualApprovalEnforcer()
        d = enforcer.to_dict()
        assert "require_dual_approval_for" in d
        restored = DualApprovalEnforcer.from_dict(d)
        assert restored._require_dual_approval_for == enforcer._require_dual_approval_for
        cloned = enforcer.clone()
        assert cloned._version == enforcer._version + 1


# =============================================================================
# ReversalConstraintEnforcer
# =============================================================================


class TestReversalConstraintEnforcer:
    def test_check_allows_reversal_in_open_current_period(self):
        enforcer = ReversalConstraintEnforcer()
        context = {
            "period": "2026-01",
            "current_period": "2026-01",
            "period_status": "open",
        }
        assert enforcer.check(context) == []

    def test_check_blocks_reversal_in_closed_period(self):
        enforcer = ReversalConstraintEnforcer()
        context = {
            "period": "2026-01",
            "current_period": "2026-01",
            "period_status": "closed",
        }
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Reversal not allowed in closed period" in errors[0]

    def test_check_blocks_reversal_in_different_period(self):
        enforcer = ReversalConstraintEnforcer()
        context = {
            "period": "2025-12",
            "current_period": "2026-01",
            "period_status": "open",
        }
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Reversal only allowed in current period" in errors[0]

    def test_enforce_raises_on_violation(self):
        enforcer = ReversalConstraintEnforcer()
        context = {"period": "2026-01", "current_period": "2026-01", "period_status": "closed"}
        with pytest.raises(ReversalConstraintError, match="not allowed in closed period"):
            enforcer.enforce(context)


# =============================================================================
# TraceabilityEnforcer
# =============================================================================


class TestTraceabilityEnforcer:
    def test_check_passes_with_causation_id(self):
        enforcer = TraceabilityEnforcer()
        context = {"causation_id": "cause-123"}
        assert enforcer.check(context) == []

    def test_check_passes_with_source_document_id(self):
        enforcer = TraceabilityEnforcer()
        context = {"source_document_id": "doc-456"}
        assert enforcer.check(context) == []

    def test_check_fails_without_traceability(self):
        enforcer = TraceabilityEnforcer()
        context = {}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Missing causation_id or source_document_id" in errors[0]

    def test_enforce_raises_on_missing(self):
        enforcer = TraceabilityEnforcer()
        with pytest.raises(TraceabilityError, match="Missing causation_id"):
            enforcer.enforce({})


# =============================================================================
# PeriodClosureEnforcer
# =============================================================================


class TestPeriodClosureEnforcer:
    def test_check_allows_posting_to_open_current_period(self):
        enforcer = PeriodClosureEnforcer()
        context = {
            "period": "2026-01",
            "current_period": "2026-01",
            "period_status": "open",
        }
        assert enforcer.check(context) == []

    def test_check_blocks_posting_to_closed_period(self):
        enforcer = PeriodClosureEnforcer()
        context = {
            "period": "2025-12",
            "current_period": "2026-01",
            "period_status": "closed",
        }
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Cannot post to closed period 2025-12" in errors[0]

    def test_check_blocks_posting_to_locked_period(self):
        enforcer = PeriodClosureEnforcer()
        context = {
            "period": "2026-01",
            "current_period": "2026-01",
            "period_status": "locked",
        }
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Period 2026-01 is locked" in errors[0]

    def test_enforce_raises_on_violation(self):
        enforcer = PeriodClosureEnforcer()
        context = {"period": "2025-12", "current_period": "2026-01", "period_status": "closed"}
        with pytest.raises(PeriodClosureError, match="Cannot post to closed period"):
            enforcer.enforce(context)


# =============================================================================
# GLSupremacyEnforcer
# =============================================================================


class TestGLSupremacyEnforcer:
    def test_check_passes_with_gl_entries(self):
        enforcer = GLSupremacyEnforcer()
        context = {"gl_entries": [{"account": "1000", "amount": 100}]}
        assert enforcer.check(context) == []

    def test_check_fails_without_gl_entries(self):
        enforcer = GLSupremacyEnforcer()
        context = {"requires_gl": True, "gl_entries": []}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Missing GL entry" in errors[0]

    def test_check_skips_if_requires_gl_false(self):
        enforcer = GLSupremacyEnforcer()
        context = {"requires_gl": False, "gl_entries": []}
        assert enforcer.check(context) == []

    def test_enforce_raises_on_missing(self):
        enforcer = GLSupremacyEnforcer()
        context = {"requires_gl": True, "gl_entries": []}
        with pytest.raises(GLSupremacyError, match="Missing GL entry"):
            enforcer.enforce(context)


# =============================================================================
# SegregationOfDutiesEnforcer
# =============================================================================


class TestSegregationOfDutiesEnforcer:
    def test_check_passes_with_different_users(self):
        enforcer = SegregationOfDutiesEnforcer()
        context = {"created_by": "user_a", "approved_by": "user_b"}
        assert enforcer.check(context) == []

    def test_check_detects_creator_and_approver_same(self):
        enforcer = SegregationOfDutiesEnforcer()
        context = {"created_by": "user_x", "approved_by": "user_x"}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Same user cannot create and approve" in errors[0]

    def test_check_detects_creator_and_poster_same(self):
        enforcer = SegregationOfDutiesEnforcer()
        context = {"created_by": "user_y", "posted_by": "user_y"}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Same user cannot create and post" in errors[0]

    def test_enforce_raises_on_violation(self):
        enforcer = SegregationOfDutiesEnforcer()
        context = {"created_by": "same", "approved_by": "same"}
        with pytest.raises(SegregationOfDutiesError, match="Same user cannot create and approve"):
            enforcer.enforce(context)


# =============================================================================
# NoRetroactivePolicyEnforcer
# =============================================================================


class TestNoRetroactivePolicyEnforcer:
    def test_check_allows_current_date(self):
        enforcer = NoRetroactivePolicyEnforcer()
        context = {"effective_date": FIXED_DATE, "current_date": FIXED_DATE}
        assert enforcer.check(context) == []

    def test_check_blocks_retroactive(self):
        enforcer = NoRetroactivePolicyEnforcer()
        past = FIXED_DATE - timedelta(days=10)
        context = {"effective_date": past, "current_date": FIXED_DATE}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Cannot apply policy change retroactively" in errors[0]

    def test_enforce_raises_on_retroactive(self):
        enforcer = NoRetroactivePolicyEnforcer()
        past = FIXED_DATE - timedelta(days=10)
        context = {"effective_date": past, "current_date": FIXED_DATE}
        with pytest.raises(NoRetroactivePolicyError, match="Cannot apply policy change retroactively"):
            enforcer.enforce(context)


# =============================================================================
# AuditTrailCompletenessEnforcer
# =============================================================================


class TestAuditTrailCompletenessEnforcer:
    def test_check_passes_with_valid_audit_records(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {
            "audit_records": [
                {"timestamp": "2026-01-01T00:00:00", "action": "CREATE"},
                {"timestamp": "2026-01-02T00:00:00", "action": "UPDATE"},
            ]
        }
        assert enforcer.check(context) == []

    def test_check_fails_without_audit_records(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {"requires_audit": True, "audit_records": []}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Missing audit trail records" in errors[0]

    def test_check_fails_on_missing_timestamp(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {"audit_records": [{"action": "CREATE"}]}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Audit record missing timestamp" in errors[0]

    def test_check_fails_on_missing_action(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {"audit_records": [{"timestamp": "2026-01-01"}]}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Audit record missing action" in errors[0]

    def test_enforce_raises_on_missing_audit(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {"requires_audit": True, "audit_records": []}
        with pytest.raises(AuditTrailCompletenessError, match="Missing audit trail records"):
            enforcer.enforce(context)


# =============================================================================
# AssetExistenceEnforcer
# =============================================================================


class TestAssetExistenceEnforcer:
    def test_register_asset(self):
        enforcer = AssetExistenceEnforcer()
        asset_id = "asset-1"
        enforcer.register_asset(asset_id)
        assert asset_id in enforcer._asset_register

    def test_check_passes_for_registered_asset(self):
        enforcer = AssetExistenceEnforcer()
        asset_id = "asset-2"
        enforcer.register_asset(asset_id)
        context = {"asset_id": asset_id}
        assert enforcer.check(context) == []

    def test_check_fails_for_unregistered_asset(self):
        enforcer = AssetExistenceEnforcer()
        context = {"asset_id": "unknown"}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "not found in asset register" in errors[0]

    def test_enforce_raises_on_unregistered(self):
        enforcer = AssetExistenceEnforcer()
        context = {"asset_id": "unknown"}
        with pytest.raises(AssetExistenceError, match="not found"):
            enforcer.enforce(context)

    def test_to_dict_includes_register(self):
        enforcer = AssetExistenceEnforcer()
        enforcer.register_asset("a")
        enforcer.register_asset("b")
        d = enforcer.to_dict()
        assert d["asset_register"] == ["a", "b"]

    def test_from_dict_restores_register(self):
        data = {"version": 2, "asset_register": ["x", "y"]}
        enforcer = AssetExistenceEnforcer.from_dict(data)
        assert enforcer._version == 2
        assert enforcer._asset_register == {"x", "y"}

    def test_clone_copies_register(self):
        enforcer = AssetExistenceEnforcer()
        enforcer.register_asset("a")
        cloned = enforcer.clone()
        assert cloned._asset_register == {"a"}
        assert cloned._version == enforcer._version + 1


# =============================================================================
# FairValueMeasurementEnforcer
# =============================================================================


class TestFairValueMeasurementEnforcer:
    def test_check_passes_with_fair_value_for_required_type(self):
        enforcer = FairValueMeasurementEnforcer()
        context = {"asset_type": "derivative", "fair_value": Decimal("100.50")}
        assert enforcer.check(context) == []

    def test_check_fails_without_fair_value_for_required_type(self):
        enforcer = FairValueMeasurementEnforcer()
        context = {"asset_type": "investment_property", "fair_value": None}
        errors = enforcer.check(context)
        assert len(errors) == 1
        assert "Fair value required" in errors[0]

    def test_check_passes_for_non_required_type(self):
        enforcer = FairValueMeasurementEnforcer()
        context = {"asset_type": "cash", "fair_value": None}
        assert enforcer.check(context) == []

    def test_enforce_raises_on_missing_fair_value(self):
        enforcer = FairValueMeasurementEnforcer()
        context = {"asset_type": "financial_instrument", "fair_value": None}
        with pytest.raises(FairValueMeasurementError, match="Fair value required"):
            enforcer.enforce(context)

    def test_to_dict_includes_types(self):
        enforcer = FairValueMeasurementEnforcer()
        d = enforcer.to_dict()
        assert d["fair_value_asset_types"] == enforcer._fair_value_asset_types

    def test_from_dict_restores_types(self):
        data = {"version": 2, "fair_value_asset_types": ["type1", "type2"]}
        enforcer = FairValueMeasurementEnforcer.from_dict(data)
        assert enforcer._version == 2
        assert enforcer._fair_value_asset_types == ["type1", "type2"]

    def test_clone_copies_types(self):
        enforcer = FairValueMeasurementEnforcer()
        cloned = enforcer.clone()
        assert cloned._fair_value_asset_types == enforcer._fair_value_asset_types
        assert cloned._version == enforcer._version + 1


# =============================================================================
# Async enforce methods (matching original test style)
# =============================================================================

# These are the equivalent of the original test's async wrappers for enforce methods.
# We keep them to demonstrate the async usage, but they are essentially the same as sync.

@pytest.mark.asyncio
class TestAsyncEnforceMethods:
    async def test_enforce_immutability(self):
        enforcer = ImmutabilityEnforcer()
        event = {"id": "evt-1"}
        enforcer.enforce_creation(event)
        # Now enforcing modification should raise
        with pytest.raises(ImmutabilityError):
            await asyncio.to_thread(enforcer.enforce_modification, event)

    async def test_enforce_evidence_mandate(self):
        enforcer = EvidenceMandateEnforcer()
        context = {"type": "WRITE_OFF", "attachments": []}
        with pytest.raises(EvidenceMandateError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_dual_approval(self):
        enforcer = DualApprovalEnforcer()
        context = {"transaction_type": "JOURNAL", "approvals": [{"approver": "u1"}]}
        with pytest.raises(DualApprovalError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_reversal_constraint(self):
        enforcer = ReversalConstraintEnforcer()
        context = {"period": "2026-01", "current_period": "2026-01", "period_status": "closed"}
        with pytest.raises(ReversalConstraintError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_traceability(self):
        enforcer = TraceabilityEnforcer()
        context = {}
        with pytest.raises(TraceabilityError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_period_closure(self):
        enforcer = PeriodClosureEnforcer()
        context = {"period": "2025-12", "current_period": "2026-01", "period_status": "closed"}
        with pytest.raises(PeriodClosureError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_gl_supremacy(self):
        enforcer = GLSupremacyEnforcer()
        context = {"requires_gl": True, "gl_entries": []}
        with pytest.raises(GLSupremacyError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_sod(self):
        enforcer = SegregationOfDutiesEnforcer()
        context = {"created_by": "same", "approved_by": "same"}
        with pytest.raises(SegregationOfDutiesError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_no_retroactive(self):
        enforcer = NoRetroactivePolicyEnforcer()
        past = FIXED_DATE - timedelta(days=10)
        context = {"effective_date": past, "current_date": FIXED_DATE}
        with pytest.raises(NoRetroactivePolicyError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_audit_trail(self):
        enforcer = AuditTrailCompletenessEnforcer()
        context = {"requires_audit": True, "audit_records": []}
        with pytest.raises(AuditTrailCompletenessError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_asset_existence(self):
        enforcer = AssetExistenceEnforcer()
        context = {"asset_id": "unknown"}
        with pytest.raises(AssetExistenceError):
            await asyncio.to_thread(enforcer.enforce, context)

    async def test_enforce_fair_value(self):
        enforcer = FairValueMeasurementEnforcer()
        context = {"asset_type": "derivative", "fair_value": None}
        with pytest.raises(FairValueMeasurementError):
            await asyncio.to_thread(enforcer.enforce, context)