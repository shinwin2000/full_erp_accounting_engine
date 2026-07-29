#!/usr/bin/env python3
"""
tests/constitution/test_enforcement_engine.py
Comprehensive tests for constitution/enforcement_engine.py

Covers:
- Enums: EnforcementResult, EnforcementStage, EnforcementMode
- Exceptions: EnforcementError, EnforcementRejectedError, EnforcementCatastrophicError
- Data classes: EnforcementReport, EnforcementContext
- EnforcementPipeline: all private methods including mapping functions, invariant/forbidden context builders
- EnforcementEngine: all public methods including convenience methods, history, statistics, emergency_bypass
- Singleton: get_enforcement_engine
- All edge cases, negative paths, and warning scenarios
- No flaky datetime (mocked)
- No duplicate test code (parametrized where appropriate)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from constitution.enforcement_engine import (
    EnforcementCatastrophicError,
    EnforcementContext,
    EnforcementEngine,
    EnforcementError,
    EnforcementMode,
    EnforcementPipeline,
    EnforcementRejectedError,
    EnforcementReport,
    EnforcementResult,
    EnforcementStage,
    get_enforcement_engine,
)
from constitution.sovereignty_declaration import SovereigntyDomain, SovereigntyStatus

# =============================================================================
# Fixtures and Helpers
# =============================================================================

FIXED_DATETIME = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now to return fixed datetime."""
    with patch("constitution.enforcement_engine.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_DATETIME
        mock_dt.utcnow.return_value = FIXED_DATETIME
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_context() -> EnforcementContext:
    return EnforcementContext(
        operation_id=MagicMock(),
        operation_type="JOURNAL_POST",
        user_id="user123",
        user_roles=["MAKER", "APPROVER"],
        legal_entity_id=MagicMock(),
        period_id=MagicMock(),
        transaction_id=MagicMock(),
        source="test",
        data={
            "total_debit": Decimal("1000"),
            "total_credit": Decimal("1000"),
            "transaction_date": FIXED_DATETIME,
            "period_status": "OPEN",
            "amount": Decimal("1000"),
            "cash_balance": Decimal("5000"),
            "proposed_cash_change": Decimal("-1000"),
            "current_quantity": Decimal("10"),
            "proposed_quantity_change": Decimal("-2"),
            "approvers": ["CFO", "CEO"],
            "period_start": FIXED_DATETIME - timedelta(days=30),
            "period_end": FIXED_DATETIME + timedelta(days=30),
            "allow_overdraft": False,
            "overdraft_limit": Decimal("0"),
            "current_state": {},
            "calculated_tax": Decimal("1000"),
            "reported_tax": Decimal("1000"),
        },
        is_amendment=False,
        mode=EnforcementMode.NORMAL,
    )


@pytest.fixture
def pipeline():
    return EnforcementPipeline()


@pytest.fixture
def engine():
    return EnforcementEngine()


# =============================================================================
# Enums
# =============================================================================

class TestEnums:
    def test_enforcement_result(self):
        assert EnforcementResult.PASS.name == "PASS"
        assert EnforcementResult.REJECTED.name == "REJECTED"
        assert EnforcementResult.REQUIRE_APPROVAL.name == "REQUIRE_APPROVAL"
        assert EnforcementResult.DEFERRED.name == "DEFERRED"
        assert EnforcementResult.CATASTROPHIC.name == "CATASTROPHIC"
        assert isinstance(EnforcementResult.PASS, EnforcementResult)

    def test_enforcement_stage(self):
        assert EnforcementStage.PREFLIGHT.name == "PREFLIGHT"
        assert EnforcementStage.CONSTITUTION_CHECK.name == "CONSTITUTION_CHECK"
        assert EnforcementStage.SOVEREIGNTY_CHECK.name == "SOVEREIGNTY_CHECK"
        assert EnforcementStage.INVARIANT_CHECK.name == "INVARIANT_CHECK"
        assert EnforcementStage.FORBIDDEN_STATE_CHECK.name == "FORBIDDEN_STATE_CHECK"
        assert EnforcementStage.VERSION_LOCK_CHECK.name == "VERSION_LOCK_CHECK"
        assert EnforcementStage.AMENDMENT_CHECK.name == "AMENDMENT_CHECK"
        assert EnforcementStage.DUAL_APPROVAL.name == "DUAL_APPROVAL"
        assert EnforcementStage.FINAL_APPROVAL.name == "FINAL_APPROVAL"
        assert isinstance(EnforcementStage.PREFLIGHT, EnforcementStage)

    def test_enforcement_mode(self):
        assert EnforcementMode.NORMAL.name == "NORMAL"
        assert EnforcementMode.AUDIT.name == "AUDIT"
        assert EnforcementMode.EMERGENCY.name == "EMERGENCY"
        assert EnforcementMode.MAINTENANCE.name == "MAINTENANCE"
        assert isinstance(EnforcementMode.NORMAL, EnforcementMode)


# =============================================================================
# Exceptions
# =============================================================================

class TestExceptions:
    def test_enforcement_error(self):
        with pytest.raises(EnforcementError):
            raise EnforcementError("test")

    def test_enforcement_rejected_error(self):
        with pytest.raises(EnforcementRejectedError, match="PREFLIGHT") as exc:
            raise EnforcementRejectedError(EnforcementStage.PREFLIGHT, "bad")
        assert exc.value.stage == EnforcementStage.PREFLIGHT
        assert exc.value.reason == "bad"

    def test_enforcement_catastrophic_error(self):
        with pytest.raises(EnforcementCatastrophicError):
            raise EnforcementCatastrophicError("boom")


# =============================================================================
# Data Classes
# =============================================================================

class TestEnforcementReport:
    def test_creation(self):
        report = EnforcementReport(
            report_id=MagicMock(),
            operation_id=MagicMock(),
            operation_type="JOURNAL_POST",
            timestamp=FIXED_DATETIME,
            stages_passed=[EnforcementStage.PREFLIGHT],
            stages_failed=[],
            final_result=EnforcementResult.PASS,
            rejection_reason=None,
            required_approvers=[],
            execution_time_ms=10.5,
            constitutional_hash="",
            mode=EnforcementMode.NORMAL,
            warning_count=0,
            warnings=[],
        )
        assert report.is_passed() is True
        assert report.compute_hash() != ""
        d = report.to_dict()
        assert d["operation_type"] == "JOURNAL_POST"
        assert d["final_result"] == "PASS"
        assert d["stages_passed"] == ["PREFLIGHT"]

    def test_is_passed_false(self):
        report = EnforcementReport(
            report_id=MagicMock(),
            operation_id=MagicMock(),
            operation_type="TEST",
            timestamp=FIXED_DATETIME,
            stages_passed=[],
            stages_failed=[(EnforcementStage.PREFLIGHT, "bad")],
            final_result=EnforcementResult.REJECTED,
            rejection_reason="bad",
            required_approvers=[],
            execution_time_ms=1.0,
            constitutional_hash="",
        )
        assert report.is_passed() is False


class TestEnforcementContext:
    def test_creation(self):
        ctx = EnforcementContext(
            operation_id=MagicMock(),
            operation_type="JOURNAL_POST",
            user_id="user",
            user_roles=["role"],
            legal_entity_id=MagicMock(),
            period_id=MagicMock(),
            transaction_id=MagicMock(),
            source="source",
            data={"a": 1},
            is_amendment=True,
            amendment_proposal_id=MagicMock(),
            mode=EnforcementMode.AUDIT,
            idempotency_key="key",
        )
        assert ctx.operation_type == "JOURNAL_POST"
        assert ctx.is_amendment is True
        assert ctx.mode == EnforcementMode.AUDIT
        assert ctx.idempotency_key == "key"


# =============================================================================
# EnforcementPipeline - Tests for all private methods
# =============================================================================

class TestEnforcementPipelinePrivateMethods:
    """Tests for the private helper methods in EnforcementPipeline."""

    @pytest.fixture
    def pipeline(self):
        return EnforcementPipeline()

    # ---- _build_pipeline (indirectly tested) ----
    def test_build_pipeline(self, pipeline):
        # Pipeline already built in __init__
        assert len(pipeline._stages) == 9
        stage_names = [s[0] for s in pipeline._stages]
        expected = [
            EnforcementStage.PREFLIGHT,
            EnforcementStage.CONSTITUTION_CHECK,
            EnforcementStage.SOVEREIGNTY_CHECK,
            EnforcementStage.VERSION_LOCK_CHECK,
            EnforcementStage.AMENDMENT_CHECK,
            EnforcementStage.INVARIANT_CHECK,
            EnforcementStage.FORBIDDEN_STATE_CHECK,
            EnforcementStage.DUAL_APPROVAL,
            EnforcementStage.FINAL_APPROVAL,
        ]
        assert stage_names == expected

    # ---- _get_relevant_principles ----
    @pytest.mark.parametrize("op_type,expected_count", [
        ("JOURNAL_POST", 4),
        ("JOURNAL_REVERSE", 4),
        ("ADJUSTING_ENTRY", 4),
        ("PERIOD_CLOSE", 3),
        ("PERIOD_REOPEN", 3),
        ("USER_LOGIN", 3),
        ("ROLE_ASSIGN", 3),
        ("TAX_SUBMISSION", 3),
        ("CORETAX_SUBMIT", 3),
        ("CONSTITUTION_AMENDMENT", 2),
        ("UNKNOWN", 3),
    ])
    def test_get_relevant_principles(self, pipeline, op_type, expected_count):
        principles = pipeline._get_relevant_principles(op_type)
        assert len(principles) == expected_count
        # Should return list of ConstitutionalPrinciple enums
        from constitution.supreme_law import ConstitutionalPrinciple
        for p in principles:
            assert isinstance(p, ConstitutionalPrinciple)

    # ---- _infer_domain_from_operation ----
    @pytest.mark.parametrize("op_type,expected_domain", [
        ("JOURNAL_POST", SovereigntyDomain.GENERAL_LEDGER),
        ("JOURNAL_REVERSE", SovereigntyDomain.GENERAL_LEDGER),
        ("ADJUSTING_ENTRY", SovereigntyDomain.GENERAL_LEDGER),
        ("PERIOD_CLOSE", SovereigntyDomain.PERIOD_CONTROL),
        ("PERIOD_REOPEN", SovereigntyDomain.PERIOD_CONTROL),
        ("AR_PAYMENT", SovereigntyDomain.SUBLEDGER_AR),
        ("AP_PAYMENT", SovereigntyDomain.SUBLEDGER_AP),
        ("GOODS_ISSUE", SovereigntyDomain.INVENTORY),
        ("GOODS_RECEIPT", SovereigntyDomain.INVENTORY),
        ("TAX_SUBMISSION", SovereigntyDomain.TAX),
        ("CORETAX_SUBMIT", SovereigntyDomain.TAX),
        ("USER_LOGIN", SovereigntyDomain.USER_ACCESS),
        ("ROLE_ASSIGN", SovereigntyDomain.USER_ACCESS),
        ("PERMISSION_CHANGE", SovereigntyDomain.USER_ACCESS),
        ("CONSTITUTION_AMENDMENT", SovereigntyDomain.CONSITUTION_ITSELF),
        ("VERSION_UPGRADE", SovereigntyDomain.CONSITUTION_ITSELF),
        ("UNKNOWN", SovereigntyDomain.GENERAL_LEDGER),
    ])
    def test_infer_domain_from_operation(self, pipeline, op_type, expected_domain):
        domain = pipeline._infer_domain_from_operation(op_type)
        assert domain == expected_domain

    # ---- _infer_operation_type ----
    @pytest.mark.parametrize("op_type,expected", [
        ("JOURNAL_POST", "CREATE"),
        ("SUBMIT_TAX", "CREATE"),
        ("CREATE_INVOICE", "CREATE"),
        ("JOURNAL_REVERSE", "UPDATE"),
        ("MODIFY_PERIOD", "UPDATE"),
        ("UPDATE_ROLE", "UPDATE"),
        ("DELETE_RECORD", "DELETE"),
        ("REPEAL_AMENDMENT", "DELETE"),
        ("READ_DATA", "READ"),
        ("GET_REPORT", "READ"),
        ("PERIOD_CLOSE", "CLOSE"),
        ("SYSTEM_FREEZE", "CLOSE"),
        ("SOMETHING_ELSE", "WRITE"),
    ])
    def test_infer_operation_type(self, pipeline, op_type, expected):
        inferred = pipeline._infer_operation_type(op_type)
        assert inferred == expected

    # ---- _get_relevant_invariants ----
    @pytest.mark.parametrize("op_type,data,expected_contains", [
        ("JOURNAL_POST", {}, ["DOUBLE_ENTRY_BALANCE", "PERIOD_INTEGRITY", "CURRENCY_CONSISTENCY"]),
        ("ADJUSTING_ENTRY", {}, ["DOUBLE_ENTRY_BALANCE", "PERIOD_INTEGRITY", "CURRENCY_CONSISTENCY"]),
        ("JOURNAL_REVERSE", {}, ["DOUBLE_ENTRY_BALANCE", "PERIOD_INTEGRITY", "CONSERVATION_OF_VALUE"]),
        ("PERIOD_CLOSE", {}, ["PERIOD_INTEGRITY", "PERIOD_CLOSURE_FINALITY", "ACCOUNTING_EQUATION"]),
        ("CASH_DISBURSEMENT", {}, ["NON_NEGATIVE_CASH", "TIME_MONOTONICITY"]),
        ("CASH_RECEIPT", {}, ["NON_NEGATIVE_CASH", "TIME_MONOTONICITY"]),
        ("GOODS_ISSUE", {}, ["NON_NEGATIVE_INVENTORY"]),
        ("GOODS_RECEIPT", {}, ["NON_NEGATIVE_INVENTORY"]),
        ("AR_PAYMENT", {}, ["NON_NEGATIVE_RECEIVABLE"]),
        ("AP_PAYMENT", {}, ["NON_NEGATIVE_PAYABLE"]),
        ("TAX_SUBMISSION", {}, ["TAX_CONSISTENCY"]),
        ("CORETAX_SUBMIT", {}, ["TAX_CONSISTENCY"]),
        ("OTHER", {}, ["TIME_MONOTONICITY"]),
    ])
    def test_get_relevant_invariants(self, pipeline, op_type, data, expected_contains):
        inv_types = pipeline._get_relevant_invariants(op_type, data)
        inv_names = [inv.name for inv in inv_types]
        for expected in expected_contains:
            assert expected in inv_names

    # ---- _build_invariant_context ----
    @pytest.mark.parametrize("inv_type,expected_keys", [
        ("DOUBLE_ENTRY_BALANCE", ["total_debit", "total_credit"]),
        ("PERIOD_INTEGRITY", ["transaction_date", "period_start", "period_end", "period_status"]),
        ("NON_NEGATIVE_CASH", ["cash_balance", "proposed_change", "allow_overdraft", "overdraft_limit"]),
        ("NON_NEGATIVE_INVENTORY", ["quantity", "proposed_change", "item_id", "warehouse_id"]),
        ("TIME_MONOTONICITY", ["transaction_time", "legal_entity_id", "user_id"]),
    ])
    def test_build_invariant_context(self, pipeline, sample_context, inv_type, expected_keys):
        from constitution.constitutional_invariants import InvariantType
        inv_type_enum = getattr(InvariantType, inv_type)
        context = pipeline._build_invariant_context(sample_context, inv_type_enum)
        for key in expected_keys:
            assert key in context

    def test_build_invariant_context_period_integrity(self, pipeline, sample_context):
        from constitution.constitutional_invariants import InvariantType
        context = pipeline._build_invariant_context(sample_context, InvariantType.PERIOD_INTEGRITY)
        assert context["transaction_date"] == sample_context.data["transaction_date"]
        assert context["period_start"] == sample_context.data["period_start"]
        assert context["period_end"] == sample_context.data["period_end"]
        assert context["period_status"] == "OPEN"

    def test_build_invariant_context_non_negative_cash_defaults(self, pipeline, sample_context):
        from constitution.constitutional_invariants import InvariantType
        sample_context.data.pop("allow_overdraft", None)
        sample_context.data.pop("overdraft_limit", None)
        context = pipeline._build_invariant_context(sample_context, InvariantType.NON_NEGATIVE_CASH)
        assert context["allow_overdraft"] is False
        assert context["overdraft_limit"] == Decimal("0")

    # ---- _get_relevant_forbidden_categories ----
    @pytest.mark.parametrize("op_type,expected_categories", [
        ("JOURNAL_POST", ["IMBALANCED_JOURNAL"]),
        ("JOURNAL_REVERSE", ["IMBALANCED_JOURNAL"]),
        ("ADJUSTING_ENTRY", ["IMBALANCED_JOURNAL"]),
        ("CASH_DISBURSEMENT", ["NEGATIVE_CASH"]),
        ("CASH_WITHDRAWAL", ["NEGATIVE_CASH"]),
        ("GOODS_ISSUE", ["NEGATIVE_INVENTORY"]),
        ("AR_PAYMENT", ["NEGATIVE_RECEIVABLE"]),
        ("AP_PAYMENT", ["NEGATIVE_PAYABLE"]),
        ("PERIOD_CLOSE", ["PERIOD_CLOSURE_VIOLATION"]),
        ("BACKDATED_POSTING", ["BACKDATED_TRANSACTION"]),
        ("TAX_SUBMISSION", ["TAX_MISMATCH"]),
        ("UNKNOWN", []),
    ])
    def test_get_relevant_forbidden_categories(self, pipeline, op_type, expected_categories):
        categories = pipeline._get_relevant_forbidden_categories(op_type)
        cat_names = [c.name for c in categories]
        assert set(cat_names) == set(expected_categories)

    # ---- _build_forbidden_context ----
    @pytest.mark.parametrize("category,expected_keys", [
        ("NEGATIVE_CASH", ["current_balance", "proposed_change", "allow_overdraft", "overdraft_limit"]),
        ("NEGATIVE_INVENTORY", ["current_quantity", "proposed_change", "allow_backorder"]),
        ("IMBALANCED_JOURNAL", ["total_debit", "total_credit", "tolerance"]),
        ("BACKDATED_TRANSACTION", ["transaction_date", "current_period_start", "max_backdate_days"]),
        ("PERIOD_CLOSURE_VIOLATION", ["period_status", "transaction_date", "period_start", "period_end"]),
        ("TAX_MISMATCH", ["calculated_tax", "reported_tax"]),
    ])
    def test_build_forbidden_context(self, pipeline, sample_context, category, expected_keys):
        from constitution.forbidden_states import ForbiddenStateCategory
        cat_enum = getattr(ForbiddenStateCategory, category)
        context = pipeline._build_forbidden_context(sample_context, cat_enum)
        if context is not None:
            for key in expected_keys:
                assert key in context

    def test_build_forbidden_context_unknown_returns_none(self, pipeline, sample_context):
        from constitution.forbidden_states import ForbiddenStateCategory
        context = pipeline._build_forbidden_context(sample_context, ForbiddenStateCategory.NEGATIVE_RECEIVABLE)
        assert context is None


# =============================================================================
# EnforcementPipeline - Public execute and checks
# =============================================================================

class TestEnforcementPipelineChecks:
    @pytest.fixture
    def pipeline(self):
        return EnforcementPipeline()

    # ---- PREFLIGHT ----
    def test_check_preflight_pass(self, pipeline, sample_context):
        valid, msg, warnings = pipeline._check_preflight(sample_context)
        assert valid is True
        assert msg == "Preflight check passed"
        assert warnings == []

    def test_check_preflight_missing_operation_id(self, pipeline, sample_context):
        sample_context.operation_id = None
        valid, msg, _ = pipeline._check_preflight(sample_context)
        assert valid is False
        assert "Operation ID is required" in msg

    def test_check_preflight_unknown_operation_type(self, pipeline, sample_context):
        sample_context.operation_type = "UNKNOWN"
        valid, msg, warnings = pipeline._check_preflight(sample_context)
        assert valid is True
        assert any("Unknown operation type" in w for w in warnings)

    def test_check_preflight_idempotency_key_too_long(self, pipeline, sample_context):
        sample_context.idempotency_key = "a" * 300
        valid, msg, warnings = pipeline._check_preflight(sample_context)
        assert valid is True
        assert any("exceeds 255" in w for w in warnings)

    # ---- CONSTITUTION CHECK ----
    def test_check_constitution_pass(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_law.enforce.return_value = None
            mock_get.return_value = mock_law
            valid, msg, warnings = pipeline._check_constitution(sample_context)
            assert valid is True
            assert msg == "Constitution check passed"
            assert warnings == []
            mock_law.enforce.assert_called()

    def test_check_constitution_violation(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            from constitution.supreme_law import ConstitutionalViolationError
            mock_law.enforce.side_effect = ConstitutionalViolationError("bad")
            mock_get.return_value = mock_law
            valid, msg, _ = pipeline._check_constitution(sample_context)
            assert valid is False
            assert "Constitutional violation" in msg

    def test_check_constitution_warning(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_law.enforce.side_effect = Exception("warning")
            mock_get.return_value = mock_law
            valid, msg, warnings = pipeline._check_constitution(sample_context)
            assert valid is True
            assert any("warning" in w for w in warnings)

    # ---- SOVEREIGNTY CHECK ----
    def test_check_sovereignty_pass(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_sovereignty_guardian") as mock_get:
            mock_guardian = MagicMock()
            mock_guardian.guard.return_value = None
            mock_get.return_value = mock_guardian
            valid, msg, _ = pipeline._check_sovereignty(sample_context)
            assert valid is True
            assert msg == "Sovereignty check passed"
            mock_guardian.guard.assert_called_once()

    def test_check_sovereignty_fail(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_sovereignty_guardian") as mock_get:
            mock_guardian = MagicMock()
            mock_guardian.guard.side_effect = Exception("sovereignty violation")
            mock_get.return_value = mock_guardian
            valid, msg, _ = pipeline._check_sovereignty(sample_context)
            assert valid is False
            assert "sovereignty violation" in msg

    # ---- VERSION LOCK CHECK ----
    def test_check_version_lock_unlocked(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_version_lock_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_status.return_value = {"current_state": "UNLOCKED"}
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_version_lock(sample_context)
            assert valid is True
            assert "Version lock check passed" in msg

    def test_check_version_lock_frozen_allows_audit(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_version_lock_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_status.return_value = {"current_state": "FROZEN"}
            mock_get.return_value = mock_service
            sample_context.operation_type = "AUDIT_CORRECTION"
            valid, msg, warnings = pipeline._check_version_lock(sample_context)
            assert valid is True
            assert any("FROZEN" in w for w in warnings)

    def test_check_version_lock_frozen_blocks_other(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_version_lock_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_status.return_value = {"current_state": "FROZEN"}
            mock_get.return_value = mock_service
            sample_context.operation_type = "JOURNAL_POST"
            valid, msg, _ = pipeline._check_version_lock(sample_context)
            assert valid is False
            assert "FROZEN" in msg

    def test_check_version_lock_locked_allows_amendment(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_version_lock_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_status.return_value = {"current_state": "LOCKED"}
            mock_get.return_value = mock_service
            sample_context.is_amendment = True
            sample_context.operation_type = "CONSTITUTION_AMENDMENT"
            valid, msg, _ = pipeline._check_version_lock(sample_context)
            assert valid is True

    def test_check_version_lock_locked_blocks_other(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_version_lock_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_status.return_value = {"current_state": "LOCKED"}
            mock_get.return_value = mock_service
            sample_context.is_amendment = False
            sample_context.operation_type = "JOURNAL_POST"
            valid, msg, _ = pipeline._check_version_lock(sample_context)
            assert valid is False
            assert "LOCKED" in msg

    # ---- AMENDMENT CHECK ----
    def test_check_amendment_not_amendment(self, pipeline, sample_context):
        sample_context.operation_type = "JOURNAL_POST"
        valid, msg, _ = pipeline._check_amendment_status(sample_context)
        assert valid is True
        assert "No amendment involved" in msg

    def test_check_amendment_missing_proposal(self, pipeline, sample_context):
        sample_context.operation_type = "CONSTITUTION_AMENDMENT"
        sample_context.amendment_proposal_id = None
        valid, msg, _ = pipeline._check_amendment_status(sample_context)
        assert valid is False
        assert "Amendment proposal ID required" in msg

    def test_check_amendment_not_approved(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_amendment_protocol") as mock_get:
            mock_protocol = MagicMock()
            mock_protocol.get_proposal_status.return_value = {"approval_status": {"status": "pending"}}
            mock_get.return_value = mock_protocol
            sample_context.operation_type = "CONSTITUTION_AMENDMENT"
            sample_context.amendment_proposal_id = MagicMock()
            valid, msg, _ = pipeline._check_amendment_status(sample_context)
            assert valid is False
            assert "not approved" in msg

    def test_check_amendment_approved(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_amendment_protocol") as mock_get:
            mock_protocol = MagicMock()
            mock_protocol.get_proposal_status.return_value = {"approval_status": {"status": "approved"}}
            mock_get.return_value = mock_protocol
            sample_context.operation_type = "CONSTITUTION_AMENDMENT"
            sample_context.amendment_proposal_id = MagicMock()
            valid, msg, _ = pipeline._check_amendment_status(sample_context)
            assert valid is True
            assert "Amendment check passed" in msg

    # ---- INVARIANTS ----
    def test_check_invariants_pass(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_constitutional_invariants_service") as mock_get:
            mock_service = MagicMock()
            mock_service.validate.return_value = (True, None)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_invariants(sample_context)
            assert valid is True
            assert "Invariant check passed" in msg

    def test_check_invariants_critical_fail(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_constitutional_invariants_service") as mock_get:
            mock_service = MagicMock()
            from constitution.constitutional_invariants import InvariantSeverity
            violation = MagicMock()
            violation.severity = InvariantSeverity.CRITICAL
            violation.message = "Critical violation"
            mock_service.validate.return_value = (False, violation)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_invariants(sample_context)
            assert valid is False
            assert "Critical invariant violation" in msg

    def test_check_invariants_catastrophic_fail(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_constitutional_invariants_service") as mock_get:
            mock_service = MagicMock()
            from constitution.constitutional_invariants import InvariantSeverity
            violation = MagicMock()
            violation.severity = InvariantSeverity.CATASTROPHIC
            violation.message = "Catastrophic"
            mock_service.validate.return_value = (False, violation)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_invariants(sample_context)
            assert valid is False
            assert "CATASTROPHIC" in msg

    def test_check_invariants_warning(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_constitutional_invariants_service") as mock_get:
            mock_service = MagicMock()
            from constitution.constitutional_invariants import InvariantSeverity
            violation = MagicMock()
            violation.severity = InvariantSeverity.WARNING
            violation.message = "Warning"
            mock_service.validate.return_value = (False, violation)
            mock_get.return_value = mock_service
            valid, msg, warnings = pipeline._check_invariants(sample_context)
            assert valid is True
            assert any("Warning" in w for w in warnings)

    # ---- FORBIDDEN STATES ----
    def test_check_forbidden_pass(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_forbidden_states_service") as mock_get:
            mock_service = MagicMock()
            mock_service.get_registry.return_value.check.return_value = (False, None, None)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_forbidden_states(sample_context)
            assert valid is True

    def test_check_forbidden_critical(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_forbidden_states_service") as mock_get:
            mock_service = MagicMock()
            from constitution.forbidden_states import ForbiddenStateSeverity
            detection = MagicMock()
            detection.severity = ForbiddenStateSeverity.CRITICAL
            detection.category = MagicMock()
            mock_service.get_registry.return_value.check.return_value = (True, detection, None)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_forbidden_states(sample_context)
            assert valid is False
            assert "Critical forbidden state" in msg

    def test_check_forbidden_catastrophic(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_forbidden_states_service") as mock_get:
            mock_service = MagicMock()
            from constitution.forbidden_states import ForbiddenStateSeverity
            detection = MagicMock()
            detection.severity = ForbiddenStateSeverity.CATASTROPHIC
            detection.category = MagicMock()
            mock_service.get_registry.return_value.check.return_value = (True, detection, None)
            mock_get.return_value = mock_service
            valid, msg, _ = pipeline._check_forbidden_states(sample_context)
            assert valid is False
            assert "CATASTROPHIC" in msg

    def test_check_forbidden_warning_and_reject(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_forbidden_states_service") as mock_get:
            mock_service = MagicMock()
            detection = MagicMock()
            detection.severity = ForbiddenStateSeverity.WARNING
            detection.category = MagicMock()
            from constitution.forbidden_states import ForbiddenStateAction
            mock_service.get_registry.return_value.check.return_value = (True, detection, ForbiddenStateAction.REJECT)
            mock_get.return_value = mock_service
            valid, msg, warnings = pipeline._check_forbidden_states(sample_context)
            assert valid is False
            assert "Forbidden state:" in msg

    # ---- DUAL APPROVAL ----
    def test_check_dual_approval_large_amount(self, pipeline, sample_context):
        sample_context.data["amount"] = Decimal("1500000000")
        sample_context.data["approvers"] = ["CFO", "CEO"]
        valid, msg, _ = pipeline._check_dual_approval(sample_context)
        assert valid is True

    def test_check_dual_approval_large_amount_no_approvers(self, pipeline, sample_context):
        sample_context.data["amount"] = Decimal("1500000000")
        sample_context.data["approvers"] = ["CFO"]
        valid, msg, _ = pipeline._check_dual_approval(sample_context)
        assert valid is False
        assert "requires dual approval" in msg

    def test_check_dual_approval_period_close(self, pipeline, sample_context):
        sample_context.operation_type = "PERIOD_CLOSE"
        sample_context.data["approvers"] = ["FINANCE_MANAGER", "AUDITOR"]
        valid, msg, _ = pipeline._check_dual_approval(sample_context)
        assert valid is True

    def test_check_dual_approval_period_close_missing(self, pipeline, sample_context):
        sample_context.operation_type = "PERIOD_CLOSE"
        sample_context.data["approvers"] = ["FINANCE_MANAGER"]
        valid, msg, _ = pipeline._check_dual_approval(sample_context)
        assert valid is False
        assert "requires approval from Finance Manager and Auditor" in msg

    # ---- FINAL APPROVAL ----
    @pytest.mark.parametrize("amount,roles,expected_valid", [
        (Decimal("1e10"), {"CFO", "CEO"}, True),
        (Decimal("1e10"), {"CFO"}, False),
        (Decimal("5e8"), {"CFO", "FINANCE_MANAGER"}, True),
        (Decimal("5e8"), {"ACCOUNTANT"}, False),
        (Decimal("4e7"), {"FINANCE_MANAGER"}, True),
        (Decimal("4e7"), {"ACCOUNTANT"}, True),
    ])
    def test_check_final_approval(self, pipeline, sample_context, amount, roles, expected_valid):
        sample_context.user_roles = list(roles)
        sample_context.data["amount"] = amount
        valid, msg, warnings = pipeline._check_final_approval(sample_context)
        assert valid == expected_valid
        if not expected_valid:
            assert "requires" in msg

    def test_check_final_approval_maker_approver_warning(self, pipeline, sample_context):
        sample_context.user_roles = ["MAKER"]
        sample_context.data["amount"] = Decimal("1e8")
        valid, msg, warnings = pipeline._check_final_approval(sample_context)
        assert valid is True
        assert any("Maker-approver conflict" in w for w in warnings)

    # ---- EXECUTE ----
    def test_execute_all_pass(self, pipeline, sample_context):
        report = pipeline.execute(sample_context)
        assert report.final_result == EnforcementResult.PASS
        assert len(report.stages_passed) == 9
        assert report.stages_failed == []
        assert report.rejection_reason is None
        assert report.execution_time_ms > 0
        assert report.compute_hash() != ""

    def test_execute_fails_at_preflight(self, pipeline, sample_context):
        sample_context.operation_id = None
        report = pipeline.execute(sample_context)
        assert report.final_result == EnforcementResult.REJECTED
        assert report.stages_passed == []
        assert len(report.stages_failed) == 1
        assert report.stages_failed[0][0] == EnforcementStage.PREFLIGHT
        assert "Operation ID is required" in report.rejection_reason

    def test_execute_requires_approval(self, pipeline, sample_context):
        sample_context.data["amount"] = Decimal("1e10")
        sample_context.data["approvers"] = ["CFO"]
        report = pipeline.execute(sample_context)
        assert report.final_result == EnforcementResult.REQUIRE_APPROVAL
        assert report.stages_failed[-1][0] == EnforcementStage.DUAL_APPROVAL

    def test_execute_catastrophic_from_invariants(self, pipeline, sample_context):
        with patch("constitution.enforcement_engine.get_constitutional_invariants_service") as mock_get:
            mock_service = MagicMock()
            from constitution.constitutional_invariants import InvariantSeverity
            violation = MagicMock()
            violation.severity = InvariantSeverity.CATASTROPHIC
            violation.message = "Catastrophic"
            mock_service.validate.return_value = (False, violation)
            mock_get.return_value = mock_service
            report = pipeline.execute(sample_context)
            assert report.final_result == EnforcementResult.CATASTROPHIC
            assert "CATASTROPHIC" in report.rejection_reason

    def test_execute_exception_handling(self, pipeline, sample_context):
        with patch.object(pipeline, "_check_preflight", side_effect=Exception("Boom")):
            report = pipeline.execute(sample_context)
            assert report.final_result == EnforcementResult.CATASTROPHIC
            assert "Exception" in report.rejection_reason


# =============================================================================
# EnforcementEngine
# =============================================================================

class TestEnforcementEngine:
    def test_singleton(self):
        e1 = EnforcementEngine()
        e2 = EnforcementEngine()
        assert e1 is e2

    def test_enforce_pass(self, engine, sample_context):
        with patch.object(engine._pipeline, "execute") as mock_execute:
            report = EnforcementReport(
                report_id=MagicMock(),
                operation_id=sample_context.operation_id,
                operation_type="JOURNAL_POST",
                timestamp=FIXED_DATETIME,
                stages_passed=[EnforcementStage.PREFLIGHT],
                stages_failed=[],
                final_result=EnforcementResult.PASS,
                rejection_reason=None,
                required_approvers=[],
                execution_time_ms=1.0,
                constitutional_hash="hash",
            )
            mock_execute.return_value = report
            result = engine.enforce(sample_context)
            assert result == report
            assert len(engine._report_history) == 1
            assert engine._report_history[0] == report

    def test_enforce_rejected_raises(self, engine, sample_context):
        with patch.object(engine._pipeline, "execute") as mock_execute:
            report = EnforcementReport(
                report_id=MagicMock(),
                operation_id=sample_context.operation_id,
                operation_type="JOURNAL_POST",
                timestamp=FIXED_DATETIME,
                stages_passed=[],
                stages_failed=[(EnforcementStage.PREFLIGHT, "bad")],
                final_result=EnforcementResult.REJECTED,
                rejection_reason="bad",
                required_approvers=[],
                execution_time_ms=1.0,
                constitutional_hash="hash",
            )
            mock_execute.return_value = report
            with pytest.raises(EnforcementRejectedError, match="bad") as exc:
                engine.enforce(sample_context)
            assert exc.value.stage == EnforcementStage.PREFLIGHT

    def test_enforce_catastrophic_raises(self, engine, sample_context):
        with patch.object(engine._pipeline, "execute") as mock_execute:
            report = EnforcementReport(
                report_id=MagicMock(),
                operation_id=sample_context.operation_id,
                operation_type="JOURNAL_POST",
                timestamp=FIXED_DATETIME,
                stages_passed=[],
                stages_failed=[(EnforcementStage.PREFLIGHT, "cat")],
                final_result=EnforcementResult.CATASTROPHIC,
                rejection_reason="cat",
                required_approvers=[],
                execution_time_ms=1.0,
                constitutional_hash="hash",
            )
            mock_execute.return_value = report
            with pytest.raises(EnforcementCatastrophicError, match="cat"):
                engine.enforce(sample_context)

    # ---- Convenience enforcement methods ----
    def test_enforce_journal_posting(self, engine):
        with patch.object(engine, "enforce") as mock_enforce:
            report = MagicMock()
            mock_enforce.return_value = report
            op_id = MagicMock()
            result = engine.enforce_journal_posting(
                operation_id=op_id,
                total_debit=Decimal("100"),
                total_credit=Decimal("100"),
                transaction_date=FIXED_DATETIME,
                legal_entity_id=MagicMock(),
                period_id=MagicMock(),
                user_id="user",
                user_roles=["MAKER"],
                source="test",
                amount=Decimal("100"),
                data={"period_status": "OPEN"},
            )
            assert result == report
            call_args = mock_enforce.call_args[0][0]
            assert call_args.operation_type == "JOURNAL_POST"
            assert call_args.data["total_debit"] == Decimal("100")
            assert call_args.data["total_credit"] == Decimal("100")

    def test_enforce_period_close(self, engine):
        with patch.object(engine, "enforce") as mock_enforce:
            report = MagicMock()
            mock_enforce.return_value = report
            op_id = MagicMock()
            period_id = MagicMock()
            result = engine.enforce_period_close(
                operation_id=op_id,
                period_id=period_id,
                legal_entity_id=MagicMock(),
                user_id="user",
                user_roles=["MANAGER"],
                approvers=["AUDITOR"],
                source="test",
                data={},
            )
            assert result == report
            call_args = mock_enforce.call_args[0][0]
            assert call_args.operation_type == "PERIOD_CLOSE"
            assert call_args.data["period_id"] == period_id
            assert call_args.data["approvers"] == ["AUDITOR"]

    def test_enforce_cash_disbursement(self, engine):
        with patch.object(engine, "enforce") as mock_enforce:
            report = MagicMock()
            mock_enforce.return_value = report
            op_id = MagicMock()
            result = engine.enforce_cash_disbursement(
                operation_id=op_id,
                current_balance=Decimal("5000"),
                proposed_change=Decimal("-1000"),
                legal_entity_id=MagicMock(),
                user_id="user",
                user_roles=["MAKER"],
                allow_overdraft=True,
                overdraft_limit=Decimal("1000"),
                source="test",
                data={},
            )
            assert result == report
            call_args = mock_enforce.call_args[0][0]
            assert call_args.operation_type == "CASH_DISBURSEMENT"
            assert call_args.data["cash_balance"] == Decimal("5000")
            assert call_args.data["proposed_cash_change"] == Decimal("-1000")
            assert call_args.data["allow_overdraft"] is True

    def test_enforce_ar_payment(self, engine):
        with patch.object(engine, "enforce") as mock_enforce:
            report = MagicMock()
            mock_enforce.return_value = report
            op_id = MagicMock()
            result = engine.enforce_ar_payment(
                operation_id=op_id,
                current_receivable=Decimal("2000"),
                proposed_payment=Decimal("-500"),
                legal_entity_id=MagicMock(),
                customer_id="CUST1",
                user_id="user",
                user_roles=["MAKER"],
                source="test",
                data={},
            )
            assert result == report
            call_args = mock_enforce.call_args[0][0]
            assert call_args.operation_type == "AR_PAYMENT"
            assert call_args.data["receivable_balance"] == Decimal("2000")
            assert call_args.data["proposed_payment"] == Decimal("-500")

    def test_enforce_tax_submission(self, engine):
        with patch.object(engine, "enforce") as mock_enforce:
            report = MagicMock()
            mock_enforce.return_value = report
            op_id = MagicMock()
            result = engine.enforce_tax_submission(
                operation_id=op_id,
                calculated_tax=Decimal("1000"),
                reported_tax=Decimal("1000"),
                tax_period="2026-01",
                legal_entity_id=MagicMock(),
                user_id="user",
                user_roles=["TAX_OFFICER"],
                source="test",
                data={},
            )
            assert result == report
            call_args = mock_enforce.call_args[0][0]
            assert call_args.operation_type == "TAX_SUBMISSION"
            assert call_args.data["calculated_tax"] == Decimal("1000")
            assert call_args.data["reported_tax"] == Decimal("1000")

    # ---- Report history and statistics ----
    def test_get_report_history(self, engine, sample_context):
        with patch.object(engine._pipeline, "execute") as mock_execute:
            for i in range(3):
                report = EnforcementReport(
                    report_id=MagicMock(),
                    operation_id=sample_context.operation_id,
                    operation_type="JOURNAL_POST" if i % 2 == 0 else "PERIOD_CLOSE",
                    timestamp=FIXED_DATETIME,
                    stages_passed=[EnforcementStage.PREFLIGHT],
                    stages_failed=[],
                    final_result=EnforcementResult.PASS if i % 2 == 0 else EnforcementResult.REJECTED,
                    rejection_reason=None if i % 2 == 0 else "bad",
                    required_approvers=[],
                    execution_time_ms=1.0,
                    constitutional_hash="hash",
                )
                mock_execute.return_value = report
                engine.enforce(sample_context)
        all_reports = engine.get_report_history(limit=10)
        assert len(all_reports) == 3
        failed = engine.get_report_history(limit=10, only_failed=True)
        assert len(failed) == 1
        journal = engine.get_report_history(limit=10, operation_type="JOURNAL_POST")
        assert len(journal) == 2

    def test_get_statistics(self, engine, sample_context):
        stats = engine.get_statistics()
        assert stats["total"] == 0
        with patch.object(engine._pipeline, "execute") as mock_execute:
            for i in range(5):
                result = EnforcementResult.PASS if i < 3 else EnforcementResult.REJECTED
                report = EnforcementReport(
                    report_id=MagicMock(),
                    operation_id=sample_context.operation_id,
                    operation_type="JOURNAL_POST" if i % 2 == 0 else "PERIOD_CLOSE",
                    timestamp=FIXED_DATETIME,
                    stages_passed=[EnforcementStage.PREFLIGHT],
                    stages_failed=[],
                    final_result=result,
                    rejection_reason=None if result == EnforcementResult.PASS else "bad",
                    required_approvers=[],
                    execution_time_ms=float(i+1)*0.5,
                    constitutional_hash="hash",
                )
                mock_execute.return_value = report
                engine.enforce(sample_context)
        stats2 = engine.get_statistics()
        assert stats2["total_enforcements"] == 5
        assert stats2["passed"] == 3
        assert stats2["rejected"] == 2
        assert stats2["by_operation_type"]["JOURNAL_POST"] >= 2
        assert stats2["by_operation_type"]["PERIOD_CLOSE"] >= 2
        assert stats2["pass_rate"] == 0.6
        assert stats2["avg_execution_time_ms"] > 0

    # ---- Emergency bypass ----
    def test_emergency_bypass_requires_two_authorizers(self, engine):
        with patch("constitution.enforcement_engine.get_sovereignty_guardian") as mock_get:
            mock_guardian = MagicMock()
            mock_guardian.get_current_status.return_value = SovereigntyStatus.EMERGENCY_LOCKDOWN
            mock_get.return_value = mock_guardian
            with pytest.raises(ValueError, match="at least 2 authorizers"):
                engine.emergency_bypass(
                    operation_id=MagicMock(),
                    operation_type="JOURNAL_POST",
                    data={},
                    user_id="user",
                    authorized_by=["only_one"],
                    reason="test",
                )

    def test_emergency_bypass_not_in_emergency(self, engine):
        with patch("constitution.enforcement_engine.get_sovereignty_guardian") as mock_get:
            mock_guardian = MagicMock()
            mock_guardian.get_current_status.return_value = SovereigntyStatus.NORMAL
            mock_get.return_value = mock_guardian
            with pytest.raises(ValueError, match="only allowed during EMERGENCY_LOCKDOWN"):
                engine.emergency_bypass(
                    operation_id=MagicMock(),
                    operation_type="JOURNAL_POST",
                    data={},
                    user_id="user",
                    authorized_by=["a", "b"],
                    reason="test",
                )

    def test_emergency_bypass_success(self, engine):
        with patch("constitution.enforcement_engine.get_sovereignty_guardian") as mock_get:
            mock_guardian = MagicMock()
            mock_guardian.get_current_status.return_value = SovereigntyStatus.EMERGENCY_LOCKDOWN
            mock_get.return_value = mock_guardian
            with patch.object(engine._pipeline, "execute") as mock_execute:
                report = EnforcementReport(
                    report_id=MagicMock(),
                    operation_id=MagicMock(),
                    operation_type="JOURNAL_POST",
                    timestamp=FIXED_DATETIME,
                    stages_passed=[EnforcementStage.PREFLIGHT],
                    stages_failed=[],
                    final_result=EnforcementResult.PASS,
                    rejection_reason=None,
                    required_approvers=[],
                    execution_time_ms=1.0,
                    constitutional_hash="",
                )
                mock_execute.return_value = report
                op_id = MagicMock()
                result = engine.emergency_bypass(
                    operation_id=op_id,
                    operation_type="JOURNAL_POST",
                    data={"a": 1},
                    user_id="user",
                    authorized_by=["admin1", "admin2"],
                    reason="urgent",
                )
                assert result.final_result == EnforcementResult.PASS
                assert result.mode == EnforcementMode.EMERGENCY
                assert any("EMERGENCY BYPASS" in w for w in result.warnings)
                assert "admin1" in result.required_approvers
                assert len(engine._report_history) == 1


# =============================================================================
# Module-level function
# =============================================================================

def test_get_enforcement_engine_singleton():
    e1 = get_enforcement_engine()
    e2 = get_enforcement_engine()
    assert e1 is e2
    assert isinstance(e1, EnforcementEngine)
