# tests/compliance/ethics/test_correction_doctrine_engine.py
"""
Comprehensive tests for compliance/ethics/correction_doctrine_engine.py.

Covers:
- Enums: CorrectionMethod, CorrectionStatus
- CorrectionRecord: construction, approve, reject, implement, to_dict, hash, exceptions
- CorrectionDoctrineEngine:
  - __init__, set_financial_benchmarks
  - determine_correction_method (with materiality, error types)
  - classify_and_correct
  - submit_for_approval, approve_correction, reject_correction, implement_correction
  - get_corrections (with filters)
  - get_impact_on_retained_earnings
  - get_restatement_required
  - generate_report, to_json
  - correct_prior_period_error (test compatibility)
- Edge cases: invalid status transitions, missing records, date filters
- Exception: ProfessionalJudgmentError tested via pytest.raises
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from compliance.ethics.correction_doctrine_engine import (
    CorrectionDoctrineEngine,
    CorrectionMethod,
    CorrectionRecord,
    CorrectionStatus,
)

# Import ProfessionalJudgmentError from the module (with fallback if needed)
try:
    from compliance.ethics.correction_doctrine_engine import ProfessionalJudgmentError
except ImportError:
    # Define a dummy exception for test if import fails
    class ProfessionalJudgmentError(Exception):
        pass


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def user_id() -> UUID:
    return uuid4()


@pytest.fixture
def engine():
    """CorrectionDoctrineEngine with default financial benchmarks."""
    return CorrectionDoctrineEngine(
        company_revenue=Decimal("500_000_000_000"),
        total_assets=Decimal("800_000_000_000"),
        equity=Decimal("300_000_000_000"),
    )


@pytest.fixture
def sample_correction(engine, user_id):
    """A sample correction record created via classify_and_correct."""
    correction = engine.classify_and_correct(
        error_description="Revenue misclassification",
        original_amount=Decimal("100_000_000"),
        corrected_amount=Decimal("150_000_000"),
        affected_periods=["2025-03"],
        proposed_by=user_id,
        intentional=False,
        policy_change=False,
        estimate_change=False,
        justification="Reclassification for correct presentation",
    )
    return correction


# ============================================================================
# Tests for Enums
# ============================================================================

class TestCorrectionMethod:
    def test_members(self):
        assert CorrectionMethod.RETROSPECTIVE_RESTATEMENT.value == "retrospective_restatement"
        assert CorrectionMethod.PROSPECTIVE_APPLICATION.value == "prospective_application"
        assert CorrectionMethod.CURRENT_PERIOD_ADJUSTMENT.value == "current_period_adjustment"


class TestCorrectionStatus:
    def test_members(self):
        assert CorrectionStatus.DRAFT.value == "draft"
        assert CorrectionStatus.SUBMITTED.value == "submitted"
        assert CorrectionStatus.APPROVED.value == "approved"
        assert CorrectionStatus.IMPLEMENTED.value == "implemented"
        assert CorrectionStatus.REJECTED.value == "rejected"


# ============================================================================
# Tests for CorrectionRecord
# ============================================================================

class TestCorrectionRecord:
    def test_construction(self, user_id):
        error_id = uuid4()
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=error_id,
            error_type=MagicMock(value="error_in_applying_policies"),
            error_description="Test error",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
        )
        assert record.id is not None
        assert record.status == CorrectionStatus.DRAFT
        assert record._hash != ""
        assert record.created_at is not None

    def test_approve_success(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.SUBMITTED,
        )
        record.approve(user_id)
        assert record.status == CorrectionStatus.APPROVED
        assert record.approved_by == user_id
        assert record.approved_at is not None

    def test_approve_fails_if_not_submitted(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.DRAFT,
        )
        with pytest.raises(ProfessionalJudgmentError, match="Cannot approve correction in status draft"):
            record.approve(user_id)

    def test_reject_success(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.SUBMITTED,
        )
        record.reject(user_id, "Insufficient justification")
        assert record.status == CorrectionStatus.REJECTED
        assert record.rejection_reason == "Insufficient justification"

    def test_reject_fails_if_not_submitted(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.DRAFT,
        )
        with pytest.raises(ProfessionalJudgmentError, match="Cannot reject correction in status draft"):
            record.reject(user_id, "reason")

    def test_implement_success(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.APPROVED,
        )
        record.implement(user_id, "Journal posted")
        assert record.status == CorrectionStatus.IMPLEMENTED
        assert record.implementation_notes == "Journal posted"
        assert record.implemented_at is not None

    def test_implement_fails_if_not_approved(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error"),
            error_description="Test",
            correction_method=CorrectionMethod.RETROSPECTIVE_RESTATEMENT,
            original_amount=Decimal("100"),
            corrected_amount=Decimal("120"),
            impact_on_retained_earnings=Decimal("20"),
            affected_periods=["2025-01"],
            justification="Test",
            proposed_by=user_id,
            status=CorrectionStatus.SUBMITTED,
        )
        with pytest.raises(ProfessionalJudgmentError, match="Cannot implement correction in status submitted"):
            record.implement(user_id)

    def test_to_dict(self, user_id):
        record = CorrectionRecord(
            correction_id=uuid4(),
            error_id=uuid4(),
            error_type=MagicMock(value="error_type"),
            error_description="Test error",
            correction_method=CorrectionMethod.PROSPECTIVE_APPLICATION,
            original_amount=Decimal("1000"),
            corrected_amount=Decimal("1200"),
            impact_on_retained_earnings=Decimal("200"),
            affected_periods=["2025-01", "2025-02"],
            justification="Justification text",
            proposed_by=user_id,
            status=CorrectionStatus.DRAFT,
        )
        d = record.to_dict()
        assert d["error_description"] == "Test error"
        assert d["correction_method"] == "prospective_application"
        assert d["original_amount"] == "1000"
        assert d["impact_on_retained_earnings"] == "200"
        assert d["justification"] == "Justification text"
        assert "hash" in d


# ============================================================================
# Tests for CorrectionDoctrineEngine
# ============================================================================

class TestCorrectionDoctrineEngine:
    def test_init(self):
        engine = CorrectionDoctrineEngine(
            company_revenue=Decimal("1000"),
            total_assets=Decimal("2000"),
            equity=Decimal("500"),
        )
        assert engine._company_revenue == Decimal("1000")
        assert engine._total_assets == Decimal("2000")
        assert engine._equity == Decimal("500")
        assert engine._corrections == []
        assert engine._pending_approvals == []

    def test_set_financial_benchmarks(self, engine):
        engine.set_financial_benchmarks(
            revenue=Decimal("10"),
            total_assets=Decimal("20"),
            equity=Decimal("5"),
        )
        assert engine._company_revenue == Decimal("10")
        assert engine._total_assets == Decimal("20")
        assert engine._equity == Decimal("5")

    # ---- determine_correction_method ----

    def test_determine_correction_method_policy_change_material(self, engine):
        # Mock materiality to return True
        with patch.object(engine._quant_materiality, 'is_material', return_value=True):
            method = engine.determine_correction_method(
                error_type=MagicMock(value="change_in_accounting_policy"),
                error_amount=Decimal("100"),
                base_amount=Decimal("1000"),
            )
            assert method == CorrectionMethod.RETROSPECTIVE_RESTATEMENT

    def test_determine_correction_method_policy_change_immaterial(self, engine):
        with patch.object(engine._quant_materiality, 'is_material', return_value=False):
            method = engine.determine_correction_method(
                error_type=MagicMock(value="change_in_accounting_policy"),
                error_amount=Decimal("10"),
                base_amount=Decimal("1000"),
            )
            assert method == CorrectionMethod.PROSPECTIVE_APPLICATION

    def test_determine_correction_method_estimate_change(self, engine):
        method = engine.determine_correction_method(
            error_type=MagicMock(value="change_in_accounting_estimate"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
        )
        assert method == CorrectionMethod.PROSPECTIVE_APPLICATION

    def test_determine_correction_method_error_in_applying_policies(self, engine):
        method = engine.determine_correction_method(
            error_type=MagicMock(value="error_in_applying_policies"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
        )
        assert method == CorrectionMethod.RETROSPECTIVE_RESTATEMENT

    def test_determine_correction_method_fraud(self, engine):
        method = engine.determine_correction_method(
            error_type=MagicMock(value="fraud"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
        )
        assert method == CorrectionMethod.RETROSPECTIVE_RESTATEMENT

    def test_determine_correction_method_other(self, engine):
        method = engine.determine_correction_method(
            error_type=MagicMock(value="other"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
        )
        assert method == CorrectionMethod.CURRENT_PERIOD_ADJUSTMENT

    def test_determine_correction_method_with_explicit_materiality(self, engine):
        # When is_material is passed explicitly, it should override default
        method = engine.determine_correction_method(
            error_type=MagicMock(value="change_in_accounting_policy"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
            is_material=False,
        )
        assert method == CorrectionMethod.PROSPECTIVE_APPLICATION

        method2 = engine.determine_correction_method(
            error_type=MagicMock(value="change_in_accounting_policy"),
            error_amount=Decimal("100"),
            base_amount=Decimal("1000"),
            is_material=True,
        )
        assert method2 == CorrectionMethod.RETROSPECTIVE_RESTATEMENT

    # ---- classify_and_correct ----

    def test_classify_and_correct(self, engine, user_id):
        correction = engine.classify_and_correct(
            error_description="Revenue misclassification",
            original_amount=Decimal("100_000_000"),
            corrected_amount=Decimal("150_000_000"),
            affected_periods=["2025-03", "2025-04"],
            proposed_by=user_id,
            intentional=False,
            policy_change=False,
            estimate_change=False,
            justification="Reclassification",
        )
        assert correction.id is not None
        assert correction.error_description == "Revenue misclassification"
        assert correction.method is not None
        assert correction.impact == Decimal("50_000_000")
        assert correction.status == CorrectionStatus.DRAFT
        assert correction in engine._corrections

    # ---- submit_for_approval ----

    def test_submit_for_approval_success(self, engine, sample_correction, user_id):
        result = engine.submit_for_approval(sample_correction.id, user_id)
        assert result is True
        assert sample_correction.status == CorrectionStatus.SUBMITTED
        assert sample_correction.id in engine._pending_approvals

    def test_submit_for_approval_fails_if_not_draft(self, engine, sample_correction, user_id):
        # First submit
        engine.submit_for_approval(sample_correction.id, user_id)
        # Try submit again
        result = engine.submit_for_approval(sample_correction.id, user_id)
        assert result is False

    def test_submit_for_approval_not_found(self, engine, user_id):
        result = engine.submit_for_approval(uuid4(), user_id)
        assert result is False

    # ---- approve_correction ----

    def test_approve_correction_success(self, engine, sample_correction, user_id):
        engine.submit_for_approval(sample_correction.id, user_id)
        result = engine.approve_correction(sample_correction.id, user_id)
        assert result is True
        assert sample_correction.status == CorrectionStatus.APPROVED
        assert sample_correction.id not in engine._pending_approvals

    def test_approve_correction_fails_if_not_submitted(self, engine, sample_correction, user_id):
        # Still DRAFT
        result = engine.approve_correction(sample_correction.id, user_id)
        assert result is False

    def test_approve_correction_not_found(self, engine, user_id):
        result = engine.approve_correction(uuid4(), user_id)
        assert result is False

    # ---- reject_correction ----

    def test_reject_correction_success(self, engine, sample_correction, user_id):
        engine.submit_for_approval(sample_correction.id, user_id)
        result = engine.reject_correction(sample_correction.id, user_id, "Invalid")
        assert result is True
        assert sample_correction.status == CorrectionStatus.REJECTED
        assert sample_correction.rejection_reason == "Invalid"
        assert sample_correction.id not in engine._pending_approvals

    def test_reject_correction_fails_if_not_submitted(self, engine, sample_correction, user_id):
        result = engine.reject_correction(sample_correction.id, user_id, "No")
        assert result is False

    def test_reject_correction_not_found(self, engine, user_id):
        result = engine.reject_correction(uuid4(), user_id, "No")
        assert result is False

    # ---- implement_correction ----

    def test_implement_correction_success(self, engine, sample_correction, user_id):
        engine.submit_for_approval(sample_correction.id, user_id)
        engine.approve_correction(sample_correction.id, user_id)
        result = engine.implement_correction(sample_correction.id, user_id, "Posted")
        assert result is True
        assert sample_correction.status == CorrectionStatus.IMPLEMENTED
        assert sample_correction.implementation_notes == "Posted"

    def test_implement_correction_fails_if_not_approved(self, engine, sample_correction, user_id):
        engine.submit_for_approval(sample_correction.id, user_id)
        # Still SUBMITTED, not approved
        result = engine.implement_correction(sample_correction.id, user_id, "Skip")
        assert result is False

    def test_implement_correction_not_found(self, engine, user_id):
        result = engine.implement_correction(uuid4(), user_id, "Skip")
        assert result is False

    # ---- get_corrections ----

    def test_get_corrections_no_filters(self, engine, sample_correction):
        corrections = engine.get_corrections()
        assert len(corrections) == 1
        assert corrections[0].id == sample_correction.id

    def test_get_corrections_by_status(self, engine, sample_correction, user_id):
        engine.submit_for_approval(sample_correction.id, user_id)
        corrections = engine.get_corrections(status=CorrectionStatus.SUBMITTED)
        assert len(corrections) == 1
        assert corrections[0].status == CorrectionStatus.SUBMITTED

        corrections2 = engine.get_corrections(status=CorrectionStatus.DRAFT)
        assert len(corrections2) == 0

    def test_get_corrections_by_error_type(self, engine, sample_correction):
        # Mock error_type value to match
        sample_correction.error_type = MagicMock(value="error_in_applying_policies")
        corrections = engine.get_corrections(error_type=sample_correction.error_type)
        assert len(corrections) == 1

    def test_get_corrections_by_date_range(self, engine, sample_correction):
        now = datetime.now(UTC)
        from_date = now - timedelta(days=1)
        to_date = now + timedelta(days=1)
        corrections = engine.get_corrections(from_date=from_date, to_date=to_date)
        assert len(corrections) == 1

        # Too early
        from_date2 = now + timedelta(days=2)
        corrections2 = engine.get_corrections(from_date=from_date2)
        assert len(corrections2) == 0

    # ---- get_impact_on_retained_earnings ----

    def test_get_impact_on_retained_earnings(self, engine, sample_correction, user_id):
        # Submit, approve, implement
        engine.submit_for_approval(sample_correction.id, user_id)
        engine.approve_correction(sample_correction.id, user_id)
        engine.implement_correction(sample_correction.id, user_id)
        # Get impact as of today
        impact = engine.get_impact_on_retained_earnings(date.today())
        assert impact == Decimal("50_000_000.00")  # 150M - 100M

        # Before implementation date (should be 0)
        before_date = date.today() - timedelta(days=1)
        impact2 = engine.get_impact_on_retained_earnings(before_date)
        assert impact2 == Decimal("0.00")

    def test_get_impact_on_retained_earnings_with_multiple_corrections(self, engine, user_id):
        # Create two corrections with different impacts
        c1 = engine.classify_and_correct("Error1", Decimal("1000"), Decimal("1200"), ["2025-01"], user_id)
        c2 = engine.classify_and_correct("Error2", Decimal("2000"), Decimal("2500"), ["2025-02"], user_id)
        # Implement both
        engine.submit_for_approval(c1.id, user_id)
        engine.approve_correction(c1.id, user_id)
        engine.implement_correction(c1.id, user_id)
        engine.submit_for_approval(c2.id, user_id)
        engine.approve_correction(c2.id, user_id)
        engine.implement_correction(c2.id, user_id)
        impact = engine.get_impact_on_retained_earnings(date.today())
        expected = (1200 - 1000) + (2500 - 2000)  # 200 + 500 = 700
        assert impact == Decimal("700.00")

    # ---- get_restatement_required ----

    def test_get_restatement_required(self, engine, sample_correction, user_id):
        # Correction should be retrospective restatement (since it's error_in_applying_policies)
        # Implement it
        engine.submit_for_approval(sample_correction.id, user_id)
        engine.approve_correction(sample_correction.id, user_id)
        engine.implement_correction(sample_correction.id, user_id)
        restatements = engine.get_restatement_required()
        assert len(restatements) == 1
        assert restatements[0].id == sample_correction.id

        # Another correction with prospective method should not appear
        c2 = engine.classify_and_correct(
            "Estimate change",
            Decimal("1000"),
            Decimal("1100"),
            ["2025-03"],
            user_id,
            estimate_change=True,
        )
        engine.submit_for_approval(c2.id, user_id)
        engine.approve_correction(c2.id, user_id)
        engine.implement_correction(c2.id, user_id)
        restatements2 = engine.get_restatement_required()
        assert len(restatements2) == 1  # Only the first one

    # ---- generate_report ----

    def test_generate_report(self, engine, sample_correction, user_id):
        report = engine.generate_report()
        assert report["total_corrections"] == 1
        assert report["pending_approvals"] == 0
        assert report["implemented"] == 0
        assert report["total_impact_on_retained_earnings"] == "0"
        assert report["by_status"]["draft"] == 1
        assert report["by_method"]["retrospective_restatement"] >= 1
        assert report["restatements_required"] == 0

        # Submit and approve
        engine.submit_for_approval(sample_correction.id, user_id)
        engine.approve_correction(sample_correction.id, user_id)
        engine.implement_correction(sample_correction.id, user_id)
        report2 = engine.generate_report()
        assert report2["implemented"] == 1
        assert report2["total_impact_on_retained_earnings"] == "50000000"
        assert report2["restatements_required"] == 1

    # ---- to_json ----

    def test_to_json(self, engine, sample_correction, user_id):
        # Submit and implement to have some data
        engine.submit_for_approval(sample_correction.id, user_id)
        engine.approve_correction(sample_correction.id, user_id)
        engine.implement_correction(sample_correction.id, user_id)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            file_path = f.name
        try:
            engine.to_json(file_path)
            with open(file_path, "r") as f:
                data = json.load(f)
            assert "report" in data
            assert "corrections" in data
            assert len(data["corrections"]) == 1
            assert data["corrections"][0]["id"] == str(sample_correction.id)
            assert data["corrections"][0]["status"] == "implemented"
        finally:
            import os
            os.unlink(file_path)

    # ---- correct_prior_period_error (test compatibility) ----

    def test_correct_prior_period_error(self, engine):
        result = engine.correct_prior_period_error(
            error_amount=Decimal("5000"),
            original_period="2024-12",
            correction_period="2025-01",
        )
        assert isinstance(result, SimpleNamespace)
        assert result.retained_earnings_adjustment == Decimal("5000")
        assert result.disclosure_required is True