#!/usr/bin/env python3
"""
tests/axioms/test_going_concern.py
Comprehensive tests for axioms/going_concern.py

Covers:
- GoingConcernAssessment, GoingConcernEvent, GoingConcernViolation
- GoingConcernValidator, GoingConcernAxiom
- Helper functions
- All edge cases, negative paths, and exceptions
- No flaky datetime usage (using fixed datetime fixture)
- No duplicate test code (merged using parametrize)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from axioms.going_concern import (
    GoingConcernAssessment,
    GoingConcernAssessmentError,
    GoingConcernAssessmentScope,
    GoingConcernAxiom,
    GoingConcernEvent,
    GoingConcernIndicator,
    GoingConcernSeverity,
    GoingConcernStatus,
    GoingConcernValidator,
    GoingConcernViolation,
    GoingConcernViolationError,
    create_going_concern_indicator_from_string,
    get_going_concern_axiom,
    get_going_concern_severity_from_status,
)

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_now():
    """Return a fixed datetime for deterministic tests."""
    return datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    """Patch datetime.now and datetime.utcnow to return fixed_now."""
    with patch("axioms.going_concern.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def legal_entity_id():
    return uuid.uuid4()


@pytest.fixture
def sample_assessment(legal_entity_id, fixed_now) -> GoingConcernAssessment:
    return GoingConcernAssessment(
        assessment_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        assessment_date=fixed_now,
        assessed_by="tester",
        status=GoingConcernStatus.HEALTHY,
        indicators=[],
        mitigating_factors=["Diversified revenue", "Strong balance sheet"],
        assessment_notes="Test assessment",
        financial_horizon_months=12,
        next_assessment_due=fixed_now + timedelta(days=180),
        approved_by=["approver1", "approver2"],
        scope=GoingConcernAssessmentScope.INDIVIDUAL,
        is_mandatory_disclosure=False,
        version=1,
    )


@pytest.fixture
def sample_event(legal_entity_id, fixed_now) -> GoingConcernEvent:
    return GoingConcernEvent(
        event_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        previous_status=GoingConcernStatus.HEALTHY,
        new_status=GoingConcernStatus.CAUTION,
        event_date=fixed_now,
        triggered_by="tester",
        trigger_reason="Test trigger",
        supporting_documents=["doc1.pdf"],
        reported_to_audit_committee=True,
        reported_at=fixed_now,
        version=1,
    )


@pytest.fixture
def sample_violation(legal_entity_id, fixed_now) -> GoingConcernViolation:
    return GoingConcernViolation(
        violation_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        violation_type="MISSING_ASSESSMENT",
        severity=GoingConcernSeverity.HIGH,
        message="Test violation",
        detected_at=fixed_now,
        detected_by="tester",
        resolved=False,
        resolved_at=None,
        resolved_by=None,
        resolution_action=None,
        version=1,
    )


# =============================================================================
# Tests for GoingConcernAssessment
# =============================================================================

class TestGoingConcernAssessment:
    def test_create_valid(self, sample_assessment):
        assert sample_assessment.assessment_id is not None
        assert sample_assessment.legal_entity_id is not None
        assert sample_assessment.status == GoingConcernStatus.HEALTHY
        assert sample_assessment.financial_horizon_months == 12
        assert not sample_assessment.is_mandatory_disclosure
        assert sample_assessment.version == 1
        assert sample_assessment.cryptographic_hash != ""

    def test_validate_horizon_less_than_12_raises(self):
        with pytest.raises(ValueError, match="Horizon must be >= 12 months"):
            create_test_assessment(financial_horizon_months=6)

    def test_requires_disclosure(self):
        assert not create_test_assessment(status=GoingConcernStatus.HEALTHY).requires_disclosure()
        assert create_test_assessment(status=GoingConcernStatus.UNCERTAIN).requires_disclosure()
        assert create_test_assessment(status=GoingConcernStatus.NEGATIVE).requires_disclosure()

    def test_is_expired(self, fixed_now, sample_assessment):
        sample_assessment.next_assessment_due = fixed_now - timedelta(days=1)
        assert sample_assessment.is_expired(fixed_now) is True

        sample_assessment.next_assessment_due = fixed_now + timedelta(days=1)
        assert sample_assessment.is_expired(fixed_now) is False

    def test_update_creates_new_version(self, sample_assessment):
        updated = sample_assessment.update("admin", assessment_notes="Updated notes")
        assert updated.assessment_notes == "Updated notes"
        assert updated.version == sample_assessment.version + 1
        assert updated._audit_trail[-1]["action"] == "UPDATE"

    def test_delete_restore(self, sample_assessment):
        deleted = sample_assessment.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == sample_assessment.version + 1

        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

        with pytest.raises(ValueError, match="Assessment not deleted"):
            sample_assessment.restore("admin")

    def test_validate(self, sample_assessment):
        result = sample_assessment.validate()
        assert result["is_valid"] is True
        assert result["assessment_id"] == str(sample_assessment.assessment_id)

        object.__setattr__(sample_assessment, "cryptographic_hash", "fake")
        result = sample_assessment.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_from_dict(self, sample_assessment):
        d = sample_assessment.to_dict()
        reconstructed = GoingConcernAssessment.from_dict(d)
        assert reconstructed.assessment_id == sample_assessment.assessment_id
        assert reconstructed.legal_entity_id == sample_assessment.legal_entity_id
        assert reconstructed.status == sample_assessment.status
        assert reconstructed.financial_horizon_months == sample_assessment.financial_horizon_months

    def test_clone(self, sample_assessment):
        cloned = sample_assessment.clone()
        assert cloned.assessment_id != sample_assessment.assessment_id
        assert cloned.legal_entity_id == sample_assessment.legal_entity_id
        assert cloned.status == GoingConcernStatus.HEALTHY
        assert cloned.version == 1

    def test_snapshot_audit_trail_touch(self, sample_assessment):
        snap = sample_assessment.snapshot()
        assert snap["assessment_id"] == str(sample_assessment.assessment_id)
        assert snap["status"] == sample_assessment.status.name

        assert sample_assessment.get_version() == 1
        assert len(sample_assessment.audit_trail()) >= 1
        touched = sample_assessment.touch("toucher")
        assert touched.version == sample_assessment.version + 1
        trail = touched.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for GoingConcernEvent
# =============================================================================

class TestGoingConcernEvent:
    def test_create_valid(self, sample_event):
        assert sample_event.event_id is not None
        assert sample_event.legal_entity_id is not None
        assert sample_event.previous_status == GoingConcernStatus.HEALTHY
        assert sample_event.new_status == GoingConcernStatus.CAUTION
        assert sample_event.version == 1
        assert sample_event.cryptographic_hash != ""

    def test_immutable_methods_raise(self, sample_event):
        with pytest.raises(AttributeError):
            sample_event.update("admin", trigger_reason="new")
        with pytest.raises(AttributeError):
            sample_event.delete("admin")
        with pytest.raises(AttributeError):
            sample_event.restore("admin")

    def test_validate(self, sample_event):
        result = sample_event.validate()
        assert result["is_valid"] is True
        assert result["event_id"] == str(sample_event.event_id)

        object.__setattr__(sample_event, "cryptographic_hash", "fake")
        result = sample_event.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_from_dict(self, sample_event):
        d = sample_event.to_dict()
        reconstructed = GoingConcernEvent.from_dict(d)
        assert reconstructed.event_id == sample_event.event_id
        assert reconstructed.legal_entity_id == sample_event.legal_entity_id
        assert reconstructed.previous_status == sample_event.previous_status
        assert reconstructed.new_status == sample_event.new_status

    def test_clone(self, sample_event):
        cloned = sample_event.clone()
        assert cloned.event_id != sample_event.event_id
        assert cloned.legal_entity_id == sample_event.legal_entity_id
        assert cloned.previous_status == sample_event.previous_status
        assert cloned.new_status == sample_event.new_status
        assert cloned.version == 1

    def test_snapshot_audit_trail_touch(self, sample_event):
        snap = sample_event.snapshot()
        assert snap["event_id"] == str(sample_event.event_id)
        assert snap["new_status"] == sample_event.new_status.name

        assert sample_event.get_version() == 1
        assert len(sample_event.audit_trail()) >= 1
        sample_event.touch("toucher")
        trail = sample_event.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for GoingConcernViolation
# =============================================================================

class TestGoingConcernViolation:
    def test_create_valid(self, sample_violation):
        assert sample_violation.violation_id is not None
        assert sample_violation.legal_entity_id is not None
        assert sample_violation.violation_type == "MISSING_ASSESSMENT"
        assert sample_violation.severity == GoingConcernSeverity.HIGH
        assert not sample_violation.resolved
        assert sample_violation.version == 1
        assert sample_violation.cryptographic_hash != ""

    def test_validate(self, sample_violation):
        result = sample_violation.validate()
        assert result["is_valid"] is True

        object.__setattr__(sample_violation, "cryptographic_hash", "fake")
        result = sample_violation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_immutable_methods_raise(self, sample_violation):
        with pytest.raises(AttributeError):
            sample_violation.update("admin", message="new")
        with pytest.raises(AttributeError):
            sample_violation.delete("admin")
        with pytest.raises(AttributeError):
            sample_violation.restore("admin")

    def test_to_dict_from_dict(self, sample_violation):
        d = sample_violation.to_dict()
        reconstructed = GoingConcernViolation.from_dict(d)
        assert reconstructed.violation_id == sample_violation.violation_id
        assert reconstructed.legal_entity_id == sample_violation.legal_entity_id
        assert reconstructed.violation_type == sample_violation.violation_type
        assert reconstructed.severity == sample_violation.severity

    def test_clone(self, sample_violation):
        cloned = sample_violation.clone()
        assert cloned.violation_id != sample_violation.violation_id
        assert cloned.legal_entity_id == sample_violation.legal_entity_id
        assert not cloned.resolved
        assert cloned.version == 1

    def test_resolve(self, sample_violation):
        resolved = sample_violation.resolve("admin", "Performed assessment")
        assert resolved.resolved is True
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "Performed assessment"
        assert resolved.version == sample_violation.version + 1

        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")

    def test_snapshot_audit_trail_touch(self, sample_violation):
        snap = sample_violation.snapshot()
        assert snap["violation_id"] == str(sample_violation.violation_id)
        assert snap["severity"] == sample_violation.severity.name

        assert sample_violation.get_version() == 1
        assert len(sample_violation.audit_trail()) >= 1
        sample_violation.touch("toucher")
        trail = sample_violation.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"


# =============================================================================
# Tests for GoingConcernValidator
# =============================================================================

class TestGoingConcernValidator:
    def test_validate_assessment_timeliness_no_assessment(self, legal_entity_id):
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
                legal_entity_id=legal_entity_id,
                last_assessment=None,
            )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "MISSING_ASSESSMENT"
        assert violation.severity == GoingConcernSeverity.HIGH
        assert hint == "Perform initial assessment immediately"

    def test_validate_assessment_timeliness_expired(self, fixed_now, legal_entity_id):
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = fixed_now - timedelta(days=10)
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
                legal_entity_id=legal_entity_id,
                last_assessment=assessment,
                current_date=fixed_now,
            )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "EXPIRED_ASSESSMENT"
        assert "overdue" in violation.message

    def test_validate_assessment_timeliness_valid(self, fixed_now, legal_entity_id):
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = fixed_now + timedelta(days=30)
        is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
            legal_entity_id=legal_entity_id,
            last_assessment=assessment,
            current_date=fixed_now,
        )
        assert is_valid
        assert violation is None
        assert hint is None

    def test_validate_assessment_timeliness_warning(self, caplog, fixed_now, legal_entity_id):
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = fixed_now + timedelta(days=15)
        with caplog.at_level("WARNING"):
            is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
                legal_entity_id=legal_entity_id,
                last_assessment=assessment,
                current_date=fixed_now,
            )
        assert is_valid
        assert violation is None
        assert "expires in" in caplog.text


# =============================================================================
# Tests for GoingConcernAxiom
# =============================================================================

class TestGoingConcernAxiom:
    def test_singleton(self):
        axiom1 = GoingConcernAxiom()
        axiom2 = GoingConcernAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_assessment(self, sample_assessment):
        axiom = GoingConcernAxiom()
        axiom.save_assessment(sample_assessment)
        retrieved = axiom.get_assessment(sample_assessment.legal_entity_id)
        assert retrieved is not None
        assert retrieved.assessment_id == sample_assessment.assessment_id

    def test_get_assessment_history(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        a1 = create_test_assessment(legal_entity_id=entity_id)
        a2 = create_test_assessment(legal_entity_id=entity_id)
        axiom.save_assessment(a1)
        axiom.save_assessment(a2)
        history = axiom.get_assessment_history(legal_entity_id=entity_id)
        assert len(history) >= 2

    def test_delete_assessment(self, sample_assessment):
        axiom = GoingConcernAxiom()
        axiom.save_assessment(sample_assessment)
        result = axiom.delete_assessment(sample_assessment.legal_entity_id)
        assert result is True
        assert axiom.get_assessment(sample_assessment.legal_entity_id) is None

    def test_save_and_get_events(self, sample_event):
        axiom = GoingConcernAxiom()
        axiom.save_event(sample_event)
        events = axiom.get_events()
        found = next((e for e in events if e.event_id == sample_event.event_id), None)
        assert found is not None

    def test_get_events_filter(self, sample_event):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        e1 = create_test_event(legal_entity_id=entity_id)
        e2 = create_test_event(legal_entity_id=entity_id)
        e3 = create_test_event(legal_entity_id=uuid.uuid4())
        axiom.save_event(e1)
        axiom.save_event(e2)
        axiom.save_event(e3)
        results = axiom.get_events(legal_entity_id=entity_id)
        assert len(results) == 2

    def test_get_events_filter_by_since(self, fixed_now, sample_event):
        axiom = GoingConcernAxiom()
        e1 = create_test_event()
        e1.event_date = fixed_now - timedelta(days=10)
        e2 = create_test_event()
        e2.event_date = fixed_now - timedelta(days=5)
        axiom.save_event(e1)
        axiom.save_event(e2)
        results = axiom.get_events(since=fixed_now - timedelta(days=7))
        assert len(results) == 1
        assert results[0].event_id == e2.event_id

    def test_delete_event(self, sample_event):
        axiom = GoingConcernAxiom()
        axiom.save_event(sample_event)
        result = axiom.delete_event(sample_event.event_id)
        assert result is True
        events = axiom.get_events()
        assert all(e.event_id != sample_event.event_id for e in events)

    def test_save_and_get_violations(self, sample_violation):
        axiom = GoingConcernAxiom()
        axiom.save_violation(sample_violation)
        violations = axiom.get_violations()
        found = next((v for v in violations if v.violation_id == sample_violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        v1 = create_test_violation()
        v1.legal_entity_id = entity_id
        v2 = create_test_violation()
        v2.legal_entity_id = entity_id
        v3 = create_test_violation()
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        axiom.save_violation(v3)
        results = axiom.get_violations(legal_entity_id=entity_id)
        assert len(results) == 2

        v1.resolved = True
        v2.resolved = False
        results_unresolved = axiom.get_violations(unresolved_only=True)
        assert len(results_unresolved) == 1
        assert not results_unresolved[0].resolved

    def test_resolve_violation(self, sample_violation):
        axiom = GoingConcernAxiom()
        axiom.save_violation(sample_violation)
        resolved = axiom.resolve_violation(sample_violation.violation_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"

        result = axiom.resolve_violation(uuid.uuid4(), "admin", "Fixed")
        assert result is None

        # Already resolved
        axiom.resolve_violation(sample_violation.violation_id, "admin2", "Again")
        result2 = axiom.resolve_violation(sample_violation.violation_id, "admin3", "Again")
        assert result2 is None

    def test_perform_assessment_healthy(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        assessment = axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[],
            mitigating_factors=["Strong cash position"],
            assessment_notes="Healthy",
            financial_horizon_months=12,
        )
        assert assessment.status == GoingConcernStatus.HEALTHY
        assert not assessment.is_mandatory_disclosure
        assert axiom.get_assessment(entity_id) is not None

    def test_perform_assessment_uncertain_requires_approvers(self):
        axiom = GoingConcernAxiom()
        with pytest.raises(GoingConcernAssessmentError, match="requires at least 2 approvers"):
            axiom.perform_assessment(
                legal_entity_id=uuid.uuid4(),
                assessed_by="tester",
                indicators=[
                    GoingConcernIndicator.NEGATIVE_EQUITY,
                    GoingConcernIndicator.RECURRING_LOSSES,
                ],
                mitigating_factors=["Parent company support"],
                assessment_notes="Uncertain",
                approved_by=["only_one"],
            )

    def test_perform_assessment_uncertain_with_approvers(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        assessment = axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[
                GoingConcernIndicator.NEGATIVE_EQUITY,
                GoingConcernIndicator.RECURRING_LOSSES,
            ],
            mitigating_factors=["Parent company support"],
            assessment_notes="Uncertain",
            approved_by=["approver1", "approver2"],
        )
        assert assessment.status in (GoingConcernStatus.UNCERTAIN, GoingConcernStatus.CAUTION)

    def test_perform_assessment_creates_event_on_status_change(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        a1 = axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[],
            mitigating_factors=["Strong"],
            assessment_notes="Healthy",
        )
        assert a1.status == GoingConcernStatus.HEALTHY

        a2 = axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER],
            mitigating_factors=[],
            assessment_notes="Caution",
            approved_by=["a", "b"],
        )
        events = axiom.get_events(legal_entity_id=entity_id)
        assert len(events) >= 1
        assert events[-1].previous_status == GoingConcernStatus.HEALTHY
        assert events[-1].new_status == GoingConcernStatus.CAUTION

    def test_perform_assessment_short_horizon_raises(self):
        axiom = GoingConcernAxiom()
        with pytest.raises(GoingConcernAssessmentError, match="Horizon must be >= 12 months"):
            axiom.perform_assessment(
                legal_entity_id=uuid.uuid4(),
                assessed_by="tester",
                indicators=[],
                mitigating_factors=[],
                assessment_notes="Short horizon",
                financial_horizon_months=6,
            )

    def test_get_entities_with_concern(self):
        axiom = GoingConcernAxiom()
        entity1 = uuid.uuid4()
        entity2 = uuid.uuid4()
        entity3 = uuid.uuid4()

        axiom.perform_assessment(entity1, "tester", [], [], "Healthy")
        axiom.perform_assessment(
            entity2, "tester", [GoingConcernIndicator.RECURRING_LOSSES], [], "Caution",
            approved_by=["a", "b"]
        )
        axiom.perform_assessment(
            entity3, "tester",
            [GoingConcernIndicator.NEGATIVE_EQUITY, GoingConcernIndicator.DEFAULT_ON_LOANS],
            [], "Negative", approved_by=["a", "b"]
        )

        concerned = axiom.get_entities_with_concern()
        assert entity2 in concerned
        assert entity3 in concerned
        assert entity1 not in concerned

    def test_enforce_passes_for_healthy_entity(self, fixed_now):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        axiom.perform_assessment(entity_id, "tester", [], [], "Healthy")
        is_valid, violation = axiom.enforce(
            entity_id, "FINANCIAL_STATEMENT", {"period_end": fixed_now}, raise_on_violation=False
        )
        assert is_valid
        assert violation is None

    def test_enforce_fails_for_entity_without_assessment(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation = axiom.enforce(
                entity_id, "FINANCIAL_STATEMENT", {}, raise_on_violation=False
            )
        assert not is_valid
        assert violation is not None

    def test_enforce_raises_for_major_transaction_without_assessment(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            with pytest.raises(GoingConcernViolationError):
                axiom.enforce(entity_id, "NEW_LOAN", {}, raise_on_violation=True)

    def test_enforce_major_transaction_with_valid_assessment(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        axiom.perform_assessment(entity_id, "tester", [], [], "Healthy")
        is_valid, violation = axiom.enforce(
            entity_id, "NEW_LOAN", {}, raise_on_violation=False
        )
        assert is_valid
        assert violation is None

    def test_enforce_financial_statement_disclosure_timing_fails(self, fixed_now):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        period_end = fixed_now - timedelta(days=5)
        axiom.perform_assessment(
            entity_id, "tester", [GoingConcernIndicator.NEGATIVE_EQUITY], [],
            "Uncertain", approved_by=["a", "b"]
        )
        is_valid, violation = axiom.enforce(
            entity_id, "FINANCIAL_STATEMENT", {"period_end": period_end}, raise_on_violation=False
        )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "DISCLOSURE_TIMING"

    def test_determine_status(self):
        axiom = GoingConcernAxiom()
        assert axiom._determine_status([], ["Mitigating"]) == GoingConcernStatus.HEALTHY
        assert axiom._determine_status([GoingConcernIndicator.RECURRING_LOSSES], []) == GoingConcernStatus.CAUTION
        assert axiom._determine_status([GoingConcernIndicator.NEGATIVE_EQUITY], []) == GoingConcernStatus.UNCERTAIN
        assert axiom._determine_status([GoingConcernIndicator.NEGATIVE_EQUITY], ["Mitigating"]) == GoingConcernStatus.CAUTION
        assert axiom._determine_status(
            [GoingConcernIndicator.NEGATIVE_EQUITY, GoingConcernIndicator.DEFAULT_ON_LOANS], []
        ) == GoingConcernStatus.NEGATIVE
        assert axiom._determine_status(
            [GoingConcernIndicator.RECURRING_LOSSES, GoingConcernIndicator.NEGATIVE_OPERATING_CASH_FLOW,
             GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER], []
        ) == GoingConcernStatus.UNCERTAIN

    def test_get_statistics(self, sample_assessment, sample_event, sample_violation):
        axiom = GoingConcernAxiom()
        axiom.save_assessment(sample_assessment)
        axiom.save_event(sample_event)
        axiom.save_violation(sample_violation)

        stats = axiom.get_statistics()
        assert stats["entities_with_assessment"] >= 1
        assert stats["total_assessments"] >= 1
        assert stats["total_events"] >= 1
        assert stats["total_violations"] >= 1
        assert "status_distribution" in stats

    def test_reset(self, sample_assessment, sample_event):
        axiom = GoingConcernAxiom()
        axiom.save_assessment(sample_assessment)
        axiom.save_event(sample_event)
        axiom.reset()
        assert len(axiom._assessments) == 0
        assert len(axiom._assessment_history) == 0
        assert len(axiom._events) == 0
        assert len(axiom._violations) == 0


# =============================================================================
# Helper Functions
# =============================================================================

def create_test_assessment(
    legal_entity_id=None, status=GoingConcernStatus.HEALTHY, indicators=None,
    financial_horizon_months=12
):
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    if indicators is None:
        indicators = []
    now = datetime.now(UTC)
    return GoingConcernAssessment(
        assessment_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        assessment_date=now,
        assessed_by="tester",
        status=status,
        indicators=indicators,
        mitigating_factors=["Diversified revenue", "Strong balance sheet"],
        assessment_notes="Test assessment",
        financial_horizon_months=financial_horizon_months,
        next_assessment_due=now + timedelta(days=180),
        approved_by=["approver1", "approver2"],
        scope=GoingConcernAssessmentScope.INDIVIDUAL,
        is_mandatory_disclosure=False,
    )


def create_test_event(
    legal_entity_id=None,
    previous_status=GoingConcernStatus.HEALTHY,
    new_status=GoingConcernStatus.CAUTION,
):
    if legal_entity_id is None:
        legal_entity_id = uuid.uuid4()
    return GoingConcernEvent(
        event_id=uuid.uuid4(),
        legal_entity_id=legal_entity_id,
        previous_status=previous_status,
        new_status=new_status,
        event_date=datetime.now(UTC),
        triggered_by="tester",
        trigger_reason="Test trigger",
        supporting_documents=["doc1.pdf"],
        reported_to_audit_committee=True,
        reported_at=datetime.now(UTC),
    )


def create_test_violation():
    return GoingConcernViolation(
        violation_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        violation_type="MISSING_ASSESSMENT",
        severity=GoingConcernSeverity.HIGH,
        message="Test violation",
        detected_at=datetime.now(UTC),
        detected_by="tester",
        resolved=False,
        resolved_at=None,
        resolved_by=None,
        resolution_action=None,
    )


# =============================================================================
# Helper Functions Tests
# =============================================================================

class TestHelperFunctions:
    def test_create_going_concern_indicator_from_string(self):
        assert create_going_concern_indicator_from_string("NEGATIVE_EQUITY") == GoingConcernIndicator.NEGATIVE_EQUITY
        assert create_going_concern_indicator_from_string("RECURRING_LOSSES") == GoingConcernIndicator.RECURRING_LOSSES
        assert create_going_concern_indicator_from_string("UNKNOWN") == GoingConcernIndicator.LIQUIDITY_RATIO_BELOW_THRESHOLD

    def test_get_going_concern_severity_from_status(self):
        assert get_going_concern_severity_from_status(GoingConcernStatus.HEALTHY) == GoingConcernSeverity.INFO
        assert get_going_concern_severity_from_status(GoingConcernStatus.CAUTION) == GoingConcernSeverity.LOW
        assert get_going_concern_severity_from_status(GoingConcernStatus.UNCERTAIN) == GoingConcernSeverity.HIGH
        assert get_going_concern_severity_from_status(GoingConcernStatus.NEGATIVE) == GoingConcernSeverity.CRITICAL
        assert get_going_concern_severity_from_status(GoingConcernStatus.LIQUIDATION) == GoingConcernSeverity.CRITICAL

    def test_get_going_concern_axiom_singleton(self):
        axiom1 = get_going_concern_axiom()
        axiom2 = get_going_concern_axiom()
        assert axiom1 is axiom2


# =============================================================================
# Negative Path Tests - Parametrized for compactness
# =============================================================================

class TestNegativePaths:
    @pytest.mark.parametrize("entity_class, kwargs, error_match", [
        (GoingConcernAssessment, {"version": 0}, "Version must be >= 1"),
        (GoingConcernEvent, {"version": 0}, "Version must be >= 1"),
        (GoingConcernViolation, {"version": 0}, "Version must be >= 1"),
    ])
    def test_invalid_version_raises(self, entity_class, kwargs, error_match):
        base = {
            "assessment_id": uuid.uuid4(),
            "legal_entity_id": uuid.uuid4(),
            "assessment_date": datetime.now(UTC),
            "assessed_by": "tester",
            "status": GoingConcernStatus.HEALTHY,
            "indicators": [],
            "mitigating_factors": [],
            "assessment_notes": "",
            "financial_horizon_months": 12,
            "next_assessment_due": datetime.now(UTC) + timedelta(days=180),
            "approved_by": [],
        }
        if entity_class == GoingConcernEvent:
            base = {
                "event_id": uuid.uuid4(),
                "legal_entity_id": uuid.uuid4(),
                "previous_status": GoingConcernStatus.HEALTHY,
                "new_status": GoingConcernStatus.CAUTION,
                "event_date": datetime.now(UTC),
                "triggered_by": "tester",
                "trigger_reason": "test",
                "supporting_documents": [],
                "reported_to_audit_committee": True,
                "reported_at": None,
            }
        if entity_class == GoingConcernViolation:
            base = {
                "violation_id": uuid.uuid4(),
                "legal_entity_id": uuid.uuid4(),
                "violation_type": "TEST",
                "severity": GoingConcernSeverity.LOW,
                "message": "test",
                "detected_at": datetime.now(UTC),
                "detected_by": "tester",
                "resolved": False,
                "resolved_at": None,
                "resolved_by": None,
                "resolution_action": None,
            }
        base.update(kwargs)
        with pytest.raises(ValueError, match=error_match):
            entity_class(**base)

    def test_perform_assessment_expired_next_due(self, fixed_now):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        assessment = axiom.perform_assessment(entity_id, "tester", [], [], "Healthy")
        assessment.next_assessment_due = fixed_now - timedelta(days=1)
        axiom.save_assessment(assessment)

        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation = axiom.enforce(
                entity_id, "FINANCIAL_STATEMENT", {"period_end": fixed_now}, raise_on_violation=False
            )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "EXPIRED_ASSESSMENT"

    def test_enforce_with_no_assessment_raises(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            with pytest.raises(GoingConcernViolationError):
                axiom.enforce(entity_id, "NEW_LOAN", {}, raise_on_violation=True)

    def test_resolve_violation_returns_none_if_already_resolved(self):
        axiom = GoingConcernAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin", "Fixed")
        assert resolved is not None
        resolved2 = axiom.resolve_violation(violation.violation_id, "admin2", "Again")
        assert resolved2 is None
