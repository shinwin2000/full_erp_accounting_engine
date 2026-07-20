#!/usr/bin/env python3
"""
tests/unit/test_going_concern.py
Test untuk axioms/going_concern.py
Mencakup: GoingConcernAssessment, GoingConcernEvent, GoingConcernViolation,
GoingConcernValidator, GoingConcernAxiom, helper functions
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

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_assessment(
    legal_entity_id: uuid.UUID | None = None,
    status: GoingConcernStatus = GoingConcernStatus.HEALTHY,
    indicators: list[GoingConcernIndicator] | None = None,
) -> GoingConcernAssessment:
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
        financial_horizon_months=12,
        next_assessment_due=now + timedelta(days=180),
        approved_by=["approver1", "approver2"],
        scope=GoingConcernAssessmentScope.INDIVIDUAL,
        is_mandatory_disclosure=False,
    )


def create_test_event(
    legal_entity_id: uuid.UUID | None = None,
    previous_status: GoingConcernStatus = GoingConcernStatus.HEALTHY,
    new_status: GoingConcernStatus = GoingConcernStatus.CAUTION,
) -> GoingConcernEvent:
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


def create_test_violation() -> GoingConcernViolation:
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


# ============================================================================
# TESTS FOR GoingConcernAssessment
# ============================================================================

class TestGoingConcernAssessment:
    def test_create_valid_assessment(self):
        assessment = create_test_assessment()
        assert assessment.assessment_id is not None
        assert assessment.legal_entity_id is not None
        assert assessment.status == GoingConcernStatus.HEALTHY
        assert assessment.financial_horizon_months == 12
        assert not assessment.is_mandatory_disclosure
        assert assessment.version == 1
        assert assessment.cryptographic_hash != ""

    def test_validate_horizon_at_least_12_months(self):
        with pytest.raises(ValueError, match="Horizon must be >= 12 months"):
            create_test_assessment(financial_horizon_months=6)

    def test_requires_disclosure_for_uncertain_or_negative(self):
        healthy = create_test_assessment(status=GoingConcernStatus.HEALTHY)
        assert not healthy.requires_disclosure()

        uncertain = create_test_assessment(status=GoingConcernStatus.UNCERTAIN)
        assert uncertain.requires_disclosure()

        negative = create_test_assessment(status=GoingConcernStatus.NEGATIVE)
        assert negative.requires_disclosure()

    def test_is_expired_handles_next_assessment_due(self):
        now = datetime.now(UTC)
        assessment = create_test_assessment()
        assessment.next_assessment_due = now - timedelta(days=1)
        assert assessment.is_expired(now)

        assessment.next_assessment_due = now + timedelta(days=1)
        assert not assessment.is_expired(now)

    def test_update_creates_new_version(self):
        assessment = create_test_assessment()
        updated = assessment.update("admin", assessment_notes="Updated notes")
        assert updated.assessment_notes == "Updated notes"
        assert updated.version == assessment.version + 1

    def test_delete_marks_deleted(self):
        assessment = create_test_assessment()
        deleted = assessment.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == assessment.version + 1

    def test_restore_recovers_deleted(self):
        assessment = create_test_assessment()
        deleted = assessment.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        assessment = create_test_assessment()
        with pytest.raises(ValueError, match="Assessment not deleted"):
            assessment.restore("admin")

    def test_activate_returns_self(self):
        assessment = create_test_assessment()
        activated = assessment.activate("admin")
        assert activated is assessment

    def test_deactivate_returns_self(self):
        assessment = create_test_assessment()
        deactivated = assessment.deactivate("admin")
        assert deactivated is assessment

    def test_lock_returns_self(self):
        assessment = create_test_assessment()
        locked = assessment.lock("admin", "test")
        assert locked is assessment

    def test_unlock_returns_self(self):
        assessment = create_test_assessment()
        unlocked = assessment.unlock("admin")
        assert unlocked is assessment

    def test_validate_returns_valid(self):
        assessment = create_test_assessment()
        result = assessment.validate()
        assert result["is_valid"]
        assert result["assessment_id"] == str(assessment.assessment_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        assessment = create_test_assessment()
        object.__setattr__(assessment, "cryptographic_hash", "fake")
        result = assessment.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        assessment = create_test_assessment()
        d = assessment.to_dict()
        assert d["status"] == "HEALTHY"
        assert d["financial_horizon_months"] == 12
        assert not d["is_mandatory_disclosure"]
        assert "assessment_id" in d

    def test_from_dict_reconstructs(self):
        assessment = create_test_assessment()
        d = assessment.to_dict()
        reconstructed = GoingConcernAssessment.from_dict(d)
        assert reconstructed.assessment_id == assessment.assessment_id
        assert reconstructed.legal_entity_id == assessment.legal_entity_id
        assert reconstructed.status == assessment.status
        assert reconstructed.financial_horizon_months == assessment.financial_horizon_months

    def test_clone_creates_new_instance(self):
        assessment = create_test_assessment()
        cloned = assessment.clone()
        assert cloned.assessment_id != assessment.assessment_id
        assert cloned.legal_entity_id == assessment.legal_entity_id
        assert cloned.status == GoingConcernStatus.HEALTHY
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        assessment = create_test_assessment()
        snap = assessment.snapshot()
        assert snap["assessment_id"] == str(assessment.assessment_id)
        assert snap["status"] == assessment.status.name

    def test_get_version(self):
        assessment = create_test_assessment()
        assert assessment.get_version() == 1

    def test_audit_trail_records_actions(self):
        assessment = create_test_assessment()
        assert len(assessment.audit_trail()) >= 1
        assessment.touch("toucher")
        trail = assessment.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        assessment = create_test_assessment()
        touched = assessment.touch("toucher")
        assert touched.version == assessment.version + 1


# ============================================================================
# TESTS FOR GoingConcernEvent
# ============================================================================

class TestGoingConcernEvent:
    def test_create_valid_event(self):
        event = create_test_event()
        assert event.event_id is not None
        assert event.legal_entity_id is not None
        assert event.previous_status == GoingConcernStatus.HEALTHY
        assert event.new_status == GoingConcernStatus.CAUTION
        assert event.version == 1
        assert event.cryptographic_hash != ""

    def test_update_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.update("admin", trigger_reason="new")

    def test_delete_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.delete("admin")

    def test_restore_raises(self):
        event = create_test_event()
        with pytest.raises(AttributeError):
            event.restore("admin")

    def test_activate_returns_self(self):
        event = create_test_event()
        activated = event.activate("admin")
        assert activated is event

    def test_deactivate_returns_self(self):
        event = create_test_event()
        deactivated = event.deactivate("admin")
        assert deactivated is event

    def test_lock_returns_self(self):
        event = create_test_event()
        locked = event.lock("admin", "test")
        assert locked is event

    def test_unlock_returns_self(self):
        event = create_test_event()
        unlocked = event.unlock("admin")
        assert unlocked is event

    def test_validate_returns_valid(self):
        event = create_test_event()
        result = event.validate()
        assert result["is_valid"]
        assert result["event_id"] == str(event.event_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        event = create_test_event()
        object.__setattr__(event, "cryptographic_hash", "fake")
        result = event.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        event = create_test_event()
        d = event.to_dict()
        assert d["previous_status"] == "HEALTHY"
        assert d["new_status"] == "CAUTION"
        assert d["trigger_reason"] == "Test trigger"
        assert "event_id" in d

    def test_from_dict_reconstructs(self):
        event = create_test_event()
        d = event.to_dict()
        reconstructed = GoingConcernEvent.from_dict(d)
        assert reconstructed.event_id == event.event_id
        assert reconstructed.legal_entity_id == event.legal_entity_id
        assert reconstructed.previous_status == event.previous_status
        assert reconstructed.new_status == event.new_status

    def test_clone_creates_new_instance(self):
        event = create_test_event()
        cloned = event.clone()
        assert cloned.event_id != event.event_id
        assert cloned.legal_entity_id == event.legal_entity_id
        assert cloned.previous_status == event.previous_status
        assert cloned.new_status == event.new_status
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        event = create_test_event()
        snap = event.snapshot()
        assert snap["event_id"] == str(event.event_id)
        assert snap["new_status"] == event.new_status.name

    def test_get_version(self):
        event = create_test_event()
        assert event.get_version() == 1

    def test_audit_trail_records(self):
        event = create_test_event()
        assert len(event.audit_trail()) >= 1
        event.touch("toucher")
        trail = event.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR GoingConcernViolation
# ============================================================================

class TestGoingConcernViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.legal_entity_id is not None
        assert violation.violation_type == "MISSING_ASSESSMENT"
        assert violation.severity == GoingConcernSeverity.HIGH
        assert not violation.resolved
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"]

    def test_validate_returns_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert not result["is_valid"]
        assert "Hash mismatch" in result["errors"]

    def test_update_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")

    def test_delete_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.delete("admin")

    def test_restore_raises(self):
        violation = create_test_violation()
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_activate_returns_self(self):
        violation = create_test_violation()
        activated = violation.activate("admin")
        assert activated is violation

    def test_deactivate_returns_self(self):
        violation = create_test_violation()
        deactivated = violation.deactivate("admin")
        assert deactivated is violation

    def test_lock_returns_self(self):
        violation = create_test_violation()
        locked = violation.lock("admin", "test")
        assert locked is violation

    def test_unlock_returns_self(self):
        violation = create_test_violation()
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_to_dict_contains_fields(self):
        violation = create_test_violation()
        d = violation.to_dict()
        assert d["violation_type"] == "MISSING_ASSESSMENT"
        assert d["severity"] == "HIGH"
        assert not d["resolved"]
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = GoingConcernViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.legal_entity_id == violation.legal_entity_id
        assert reconstructed.violation_type == violation.violation_type
        assert reconstructed.severity == violation.severity

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.legal_entity_id == violation.legal_entity_id
        assert not cloned.resolved
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        violation = create_test_violation()
        snap = violation.snapshot()
        assert snap["violation_id"] == str(violation.violation_id)
        assert snap["severity"] == violation.severity.name

    def test_get_version(self):
        violation = create_test_violation()
        assert violation.get_version() == 1

    def test_audit_trail_records(self):
        violation = create_test_violation()
        assert len(violation.audit_trail()) >= 1
        violation.touch("toucher")
        trail = violation.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_resolve_marks_resolved(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Performed assessment")
        assert resolved.resolved
        assert resolved.resolved_at is not None
        assert resolved.resolved_by == "admin"
        assert resolved.resolution_action == "Performed assessment"
        assert resolved.version == violation.version + 1

    def test_resolve_already_resolved_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Fixed")
        with pytest.raises(ValueError, match="Already resolved"):
            resolved.resolve("admin2", "Again")


# ============================================================================
# TESTS FOR GoingConcernValidator
# ============================================================================

class TestGoingConcernValidator:
    def test_validate_assessment_timeliness_no_assessment(self):
        legal_entity_id = uuid.uuid4()
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

    def test_validate_assessment_timeliness_expired(self):
        legal_entity_id = uuid.uuid4()
        now = datetime.now(UTC)
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = now - timedelta(days=10)
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
                legal_entity_id=legal_entity_id,
                last_assessment=assessment,
                current_date=now,
            )
        assert not is_valid
        assert violation is not None
        assert violation.violation_type == "EXPIRED_ASSESSMENT"
        assert "overdue" in violation.message

    def test_validate_assessment_timeliness_valid(self):
        legal_entity_id = uuid.uuid4()
        now = datetime.now(UTC)
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = now + timedelta(days=30)
        is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
            legal_entity_id=legal_entity_id,
            last_assessment=assessment,
            current_date=now,
        )
        assert is_valid
        assert violation is None
        assert hint is None

    def test_validate_assessment_timeliness_warning_before_expiry(self, caplog):
        legal_entity_id = uuid.uuid4()
        now = datetime.now(UTC)
        assessment = create_test_assessment(legal_entity_id=legal_entity_id)
        assessment.next_assessment_due = now + timedelta(days=15)
        with caplog.at_level("WARNING"):
            is_valid, violation, hint = GoingConcernValidator.validate_assessment_timeliness(
                legal_entity_id=legal_entity_id,
                last_assessment=assessment,
                current_date=now,
            )
        assert is_valid
        assert violation is None
        assert "expires in" in caplog.text


# ============================================================================
# TESTS FOR GoingConcernAxiom
# ============================================================================

class TestGoingConcernAxiom:
    def test_singleton(self):
        axiom1 = GoingConcernAxiom()
        axiom2 = GoingConcernAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_assessment(self):
        axiom = GoingConcernAxiom()
        assessment = create_test_assessment()
        axiom.save_assessment(assessment)
        retrieved = axiom.get_assessment(assessment.legal_entity_id)
        assert retrieved is not None
        assert retrieved.assessment_id == assessment.assessment_id

    def test_get_assessment_history(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        a1 = create_test_assessment(legal_entity_id=entity_id)
        a2 = create_test_assessment(legal_entity_id=entity_id)
        axiom.save_assessment(a1)
        axiom.save_assessment(a2)
        history = axiom.get_assessment_history(legal_entity_id=entity_id)
        assert len(history) >= 2

    def test_delete_assessment(self):
        axiom = GoingConcernAxiom()
        assessment = create_test_assessment()
        axiom.save_assessment(assessment)
        result = axiom.delete_assessment(assessment.legal_entity_id)
        assert result
        assert axiom.get_assessment(assessment.legal_entity_id) is None

    def test_save_and_get_events(self):
        axiom = GoingConcernAxiom()
        event = create_test_event()
        axiom.save_event(event)
        events = axiom.get_events()
        assert len(events) >= 1
        found = next((e for e in events if e.event_id == event.event_id), None)
        assert found is not None

    def test_get_events_filter_by_entity(self):
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

    def test_get_events_filter_by_since(self):
        axiom = GoingConcernAxiom()
        now = datetime.now(UTC)
        e1 = create_test_event()
        e1.event_date = now - timedelta(days=10)
        e2 = create_test_event()
        e2.event_date = now - timedelta(days=5)
        axiom.save_event(e1)
        axiom.save_event(e2)
        results = axiom.get_events(since=now - timedelta(days=7))
        assert len(results) >= 1

    def test_delete_event(self):
        axiom = GoingConcernAxiom()
        event = create_test_event()
        axiom.save_event(event)
        result = axiom.delete_event(event.event_id)
        assert result
        events = axiom.get_events()
        assert all(e.event_id != event.event_id for e in events)

    def test_save_and_get_violations(self):
        axiom = GoingConcernAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_entity(self):
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

    def test_get_violations_unresolved_only(self):
        axiom = GoingConcernAxiom()
        v1 = create_test_violation()
        v1.resolved = True
        v2 = create_test_violation()
        v2.resolved = False
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        results = axiom.get_violations(unresolved_only=True)
        assert all(not v.resolved for v in results)

    def test_resolve_violation(self):
        axiom = GoingConcernAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        resolved = axiom.resolve_violation(violation.violation_id, "admin", "Fixed")
        assert resolved is not None
        assert resolved.resolved
        assert resolved.resolved_by == "admin"

    def test_resolve_violation_not_found(self):
        axiom = GoingConcernAxiom()
        result = axiom.resolve_violation(uuid.uuid4(), "admin", "Fixed")
        assert result is None

    def test_perform_assessment_healthy(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        assessment = axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[],
            mitigating_factors=["Strong cash position"],
            assessment_notes="Healthy assessment",
            financial_horizon_months=12,
        )
        assert assessment is not None
        assert assessment.status == GoingConcernStatus.HEALTHY
        assert not assessment.is_mandatory_disclosure
        retrieved = axiom.get_assessment(entity_id)
        assert retrieved is not None

    def test_perform_assessment_uncertain_requires_approvers(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with pytest.raises(GoingConcernAssessmentError, match="requires at least 2 approvers"):
            axiom.perform_assessment(
                legal_entity_id=entity_id,
                assessed_by="tester",
                indicators=[
                    GoingConcernIndicator.NEGATIVE_EQUITY,
                    GoingConcernIndicator.RECURRING_LOSSES,
                ],
                mitigating_factors=["Parent company support"],
                assessment_notes="Uncertain assessment",
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
            assessment_notes="Uncertain assessment",
            approved_by=["approver1", "approver2"],
        )
        assert assessment is not None
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
        )
        events = axiom.get_events(legal_entity_id=entity_id)
        assert len(events) >= 1
        assert events[-1].previous_status == GoingConcernStatus.HEALTHY
        assert events[-1].new_status == GoingConcernStatus.CAUTION

    def test_get_entities_with_concern(self):
        axiom = GoingConcernAxiom()
        entity1 = uuid.uuid4()
        entity2 = uuid.uuid4()
        entity3 = uuid.uuid4()

        axiom.perform_assessment(
            legal_entity_id=entity1,
            assessed_by="tester",
            indicators=[],
            mitigating_factors=[],
            assessment_notes="Healthy",
        )
        axiom.perform_assessment(
            legal_entity_id=entity2,
            assessed_by="tester",
            indicators=[GoingConcernIndicator.RECURRING_LOSSES],
            mitigating_factors=[],
            assessment_notes="Caution",
            approved_by=["a", "b"],
        )
        axiom.perform_assessment(
            legal_entity_id=entity3,
            assessed_by="tester",
            indicators=[GoingConcernIndicator.NEGATIVE_EQUITY, GoingConcernIndicator.DEFAULT_ON_LOANS],
            mitigating_factors=[],
            assessment_notes="Negative",
            approved_by=["a", "b"],
        )

        concerned = axiom.get_entities_with_concern()
        assert entity2 in concerned
        assert entity3 in concerned
        assert entity1 not in concerned

    def test_enforce_passes_for_healthy_entity(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        axiom.perform_assessment(
            legal_entity_id=entity_id,
            assessed_by="tester",
            indicators=[],
            mitigating_factors=[],
            assessment_notes="Healthy",
        )
        is_valid, violation = axiom.enforce(
            legal_entity_id=entity_id,
            transaction_type="FINANCIAL_STATEMENT",
            context={"period_end": datetime.now(UTC)},
            raise_on_violation=False,
        )
        assert is_valid
        assert violation is None

    def test_enforce_fails_for_entity_without_assessment(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            is_valid, violation = axiom.enforce(
                legal_entity_id=entity_id,
                transaction_type="FINANCIAL_STATEMENT",
                context={},
                raise_on_violation=False,
            )
        assert not is_valid
        assert violation is not None

    def test_enforce_raises_for_major_transaction_without_assessment(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        with patch("axioms.going_concern.GoingConcernValidator._notify_constitution"):
            with pytest.raises(GoingConcernViolationError):
                axiom.enforce(
                    legal_entity_id=entity_id,
                    transaction_type="NEW_LOAN",
                    context={},
                    raise_on_violation=True,
                )

    def test_determine_status_healthy(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status([], ["Mitigating factor"])
        assert status == GoingConcernStatus.HEALTHY

    def test_determine_status_caution_with_significant_indicator(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status(
            [GoingConcernIndicator.RECURRING_LOSSES],
            [],
        )
        assert status == GoingConcernStatus.CAUTION

    def test_determine_status_uncertain_with_critical_indicator_no_mitigation(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status(
            [GoingConcernIndicator.NEGATIVE_EQUITY],
            [],
        )
        assert status == GoingConcernStatus.UNCERTAIN

    def test_determine_status_caution_with_critical_indicator_and_mitigation(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status(
            [GoingConcernIndicator.NEGATIVE_EQUITY],
            ["Parent company support", "Equity injection planned"],
        )
        assert status == GoingConcernStatus.CAUTION

    def test_determine_status_negative_with_multiple_critical(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status(
            [
                GoingConcernIndicator.NEGATIVE_EQUITY,
                GoingConcernIndicator.DEFAULT_ON_LOANS,
            ],
            [],
        )
        assert status == GoingConcernStatus.NEGATIVE

    def test_determine_status_uncertain_with_three_significant(self):
        axiom = GoingConcernAxiom()
        status = axiom._determine_status(
            [
                GoingConcernIndicator.RECURRING_LOSSES,
                GoingConcernIndicator.NEGATIVE_OPERATING_CASH_FLOW,
                GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER,
            ],
            [],
        )
        assert status == GoingConcernStatus.UNCERTAIN

    def test_get_statistics(self):
        axiom = GoingConcernAxiom()
        entity_id = uuid.uuid4()
        assessment = create_test_assessment(legal_entity_id=entity_id)
        axiom.save_assessment(assessment)
        event = create_test_event(legal_entity_id=entity_id)
        axiom.save_event(event)
        violation = create_test_violation()
        axiom.save_violation(violation)

        stats = axiom.get_statistics()
        assert stats["entities_with_assessment"] >= 1
        assert stats["total_assessments"] >= 1
        assert stats["total_events"] >= 1
        assert stats["total_violations"] >= 1
        assert "status_distribution" in stats
        assert "entities_requiring_disclosure" in stats
        assert "expired_assessments" in stats

    def test_reset(self):
        axiom = GoingConcernAxiom()
        assessment = create_test_assessment()
        axiom.save_assessment(assessment)
        event = create_test_event()
        axiom.save_event(event)
        axiom.reset()
        assert len(axiom._assessments) == 0
        assert len(axiom._assessment_history) == 0
        assert len(axiom._events) == 0
        assert len(axiom._violations) == 0


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_going_concern_indicator_from_string(self):
        assert create_going_concern_indicator_from_string("NEGATIVE_EQUITY") == GoingConcernIndicator.NEGATIVE_EQUITY
        assert create_going_concern_indicator_from_string("RECURRING_LOSSES") == GoingConcernIndicator.RECURRING_LOSSES
        assert create_going_concern_indicator_from_string("NEGATIVE_OPERATING_CASH_FLOW") == GoingConcernIndicator.NEGATIVE_OPERATING_CASH_FLOW
        assert create_going_concern_indicator_from_string("DEFAULT_ON_LOANS") == GoingConcernIndicator.DEFAULT_ON_LOANS
        assert create_going_concern_indicator_from_string("LIQUIDITY_RATIO_BELOW_THRESHOLD") == GoingConcernIndicator.LIQUIDITY_RATIO_BELOW_THRESHOLD
        assert create_going_concern_indicator_from_string("WORKING_CAPITAL_DEFICIT") == GoingConcernIndicator.WORKING_CAPITAL_DEFICIT
        assert create_going_concern_indicator_from_string("LOSS_OF_KEY_MANAGEMENT") == GoingConcernIndicator.LOSS_OF_KEY_MANAGEMENT
        assert create_going_concern_indicator_from_string("LOSS_OF_MAJOR_CUSTOMER") == GoingConcernIndicator.LOSS_OF_MAJOR_CUSTOMER
        assert create_going_concern_indicator_from_string("LOSS_OF_MAJOR_SUPPLIER") == GoingConcernIndicator.LOSS_OF_MAJOR_SUPPLIER
        assert create_going_concern_indicator_from_string("LABOR_DISPUTES") == GoingConcernIndicator.LABOR_DISPUTES
        assert create_going_concern_indicator_from_string("TECHNOLOGICAL_OBSOLESCENCE") == GoingConcernIndicator.TECHNOLOGICAL_OBSOLESCENCE
        assert create_going_concern_indicator_from_string("LEGAL_PROCEEDINGS") == GoingConcernIndicator.LEGAL_PROCEEDINGS
        assert create_going_concern_indicator_from_string("REGULATORY_SANCTIONS") == GoingConcernIndicator.REGULATORY_SANCTIONS
        assert create_going_concern_indicator_from_string("LICENSE_REVOCATION") == GoingConcernIndicator.LICENSE_REVOCATION
        assert create_going_concern_indicator_from_string("VIOLATION_OF_DEBT_COVENANTS") == GoingConcernIndicator.VIOLATION_OF_DEBT_COVENANTS
        assert create_going_concern_indicator_from_string("NATURAL_DISASTER") == GoingConcernIndicator.NATURAL_DISASTER
        assert create_going_concern_indicator_from_string("MARKET_DOWNTURN_SEVERE") == GoingConcernIndicator.MARKET_DOWNTURN_SEVERE
        assert create_going_concern_indicator_from_string("PARENT_COMPANY_DISTRESS") == GoingConcernIndicator.PARENT_COMPANY_DISTRESS
        assert create_going_concern_indicator_from_string("LOSS_OF_FINANCING") == GoingConcernIndicator.LOSS_OF_FINANCING
        assert create_going_concern_indicator_from_string("unknown") == GoingConcernIndicator.LIQUIDITY_RATIO_BELOW_THRESHOLD

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
