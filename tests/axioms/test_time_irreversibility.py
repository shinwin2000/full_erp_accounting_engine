#!/usr/bin/env python3
"""
tests/unit/test_time_irreversibility.py
Test untuk axioms/time_irreversibility.py
Mencakup: TimeBoundary, TransactionTimestamp, TimeIrreversibilityViolation,
TimeIrreversibilityValidator, TimeIrreversibilityAxiom, helper functions
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from axioms.time_irreversibility import (
    TimeBoundary,
    TimeIrreversibilityAxiom,
    TimeIrreversibilityError,
    TimeIrreversibilityValidator,
    TimeIrreversibilityViolation,
    TimeIrreversibilityViolationError,
    TimeIrreversibilityViolationSeverity,
    TransactionTimeContext,
    TransactionTimestamp,
    create_time_boundary,
    create_transaction_timestamp,
    get_time_irreversibility_axiom,
)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_boundary(
    start_offset_days: int = -15,
    end_offset_days: int = 15,
    is_closed: bool = False,
    is_locked: bool = False,
) -> TimeBoundary:
    now = datetime.now(UTC)
    start = now + timedelta(days=start_offset_days)
    end = now + timedelta(days=end_offset_days)
    return TimeBoundary(
        period_id=uuid.uuid4(),
        period_name="Test Period",
        fiscal_year=2026,
        period_number=1,
        start_date=start,
        end_date=end,
        is_closed=is_closed,
        is_locked=is_locked,
    )


def create_test_timestamp(
    effective_date: datetime | None = None,
    posting_date: datetime | None = None,
    approval_date: datetime | None = None,
    settlement_date: datetime | None = None,
) -> TransactionTimestamp:
    now = datetime.now(UTC)
    if effective_date is None:
        effective_date = now - timedelta(days=1)
    if posting_date is None:
        posting_date = now
    return TransactionTimestamp(
        transaction_id=uuid.uuid4(),
        effective_date=effective_date,
        posting_date=posting_date,
        approval_date=approval_date,
        settlement_date=settlement_date,
        created_at=now - timedelta(days=2),
        created_by="tester",
    )


def create_test_violation() -> TimeIrreversibilityViolation:
    now = datetime.now(UTC)
    return TimeIrreversibilityViolation(
        violation_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        attempted_effective_date=now - timedelta(days=10),
        current_period_start=now - timedelta(days=15),
        current_period_end=now + timedelta(days=15),
        last_transaction_date=now - timedelta(days=5),
        period_status="OPEN",
        backdate_days=10,
        severity=TimeIrreversibilityViolationSeverity.HIGH,
        message="Test violation",
        user_id="user123",
        module="test_module",
        detected_at=now,
        is_blocked=True,
        override_granted=False,
        override_by=None,
        override_reason=None,
    )


# ============================================================================
# TESTS FOR TimeBoundary
# ============================================================================

class TestTimeBoundary:
    def test_create_valid_boundary(self):
        boundary = create_test_boundary()
        assert boundary.period_id is not None
        assert boundary.period_name == "Test Period"
        assert boundary.fiscal_year == 2026
        assert boundary.period_number == 1
        assert boundary.is_closed is False
        assert boundary.is_locked is False
        assert boundary.version == 1
        assert boundary.cryptographic_hash != ""

    def test_validate_start_before_end(self):
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Start date must be before end date"):
            TimeBoundary(
                period_id=uuid.uuid4(),
                period_name="Invalid",
                fiscal_year=2026,
                period_number=1,
                start_date=now + timedelta(days=10),
                end_date=now - timedelta(days=10),
                is_closed=False,
                is_locked=False,
            )

    def test_contains_checks_date(self):
        boundary = create_test_boundary()
        now = datetime.now(UTC)
        assert boundary.contains(now) is True
        assert boundary.contains(now - timedelta(days=20)) is False
        assert boundary.contains(now + timedelta(days=20)) is False

    def test_is_modifiable(self):
        boundary = create_test_boundary()
        assert boundary.is_modifiable() is True

        closed = boundary.update("admin", is_closed=True)
        assert closed.is_modifiable() is False

        locked = boundary.update("admin", is_locked=True)
        assert locked.is_modifiable() is False

    def test_update_creates_new_version(self):
        boundary = create_test_boundary()
        updated = boundary.update("admin", period_name="Updated Period")
        assert updated.period_name == "Updated Period"
        assert updated.version == boundary.version + 1

    def test_delete_marks_deleted(self):
        boundary = create_test_boundary()
        deleted = boundary.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == boundary.version + 1

    def test_restore_recovers_deleted(self):
        boundary = create_test_boundary()
        deleted = boundary.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        boundary = create_test_boundary()
        with pytest.raises(ValueError, match="Not deleted"):
            boundary.restore("admin")

    def test_activate_returns_self(self):
        boundary = create_test_boundary()
        activated = boundary.activate("admin")
        assert activated is boundary

    def test_deactivate_returns_self(self):
        boundary = create_test_boundary()
        deactivated = boundary.deactivate("admin")
        assert deactivated is boundary

    def test_lock_sets_locked(self):
        boundary = create_test_boundary()
        locked = boundary.lock("admin", "test")
        assert locked.is_locked is True
        assert locked.locked_by == "admin"
        assert locked.locked_at is not None
        assert locked.version == boundary.version + 1

    def test_lock_already_locked_returns_self(self):
        boundary = create_test_boundary()
        locked = boundary.lock("admin", "test")
        again = locked.lock("admin2", "again")
        assert again is locked

    def test_unlock_sets_unlocked(self):
        boundary = create_test_boundary()
        locked = boundary.lock("admin", "test")
        unlocked = locked.unlock("admin")
        assert unlocked.is_locked is False
        assert unlocked.locked_at is None
        assert unlocked.locked_by is None
        assert unlocked.version == locked.version + 1

    def test_unlock_already_unlocked_returns_self(self):
        boundary = create_test_boundary()
        unlocked = boundary.unlock("admin")
        assert unlocked is boundary

    def test_validate_returns_valid(self):
        boundary = create_test_boundary()
        result = boundary.validate()
        assert result["is_valid"] is True
        assert result["period_id"] == str(boundary.period_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        boundary = create_test_boundary()
        object.__setattr__(boundary, "cryptographic_hash", "fake")
        result = boundary.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        boundary = create_test_boundary()
        d = boundary.to_dict()
        assert d["period_name"] == "Test Period"
        assert d["fiscal_year"] == 2026
        assert d["period_number"] == 1
        assert d["is_closed"] is False
        assert "period_id" in d

    def test_from_dict_reconstructs(self):
        boundary = create_test_boundary()
        d = boundary.to_dict()
        reconstructed = TimeBoundary.from_dict(d)
        assert reconstructed.period_id == boundary.period_id
        assert reconstructed.period_name == boundary.period_name
        assert reconstructed.fiscal_year == boundary.fiscal_year
        assert reconstructed.period_number == boundary.period_number

    def test_clone_creates_new_instance(self):
        boundary = create_test_boundary()
        cloned = boundary.clone()
        assert cloned.period_id != boundary.period_id
        assert cloned.period_name == boundary.period_name + "_COPY"
        assert cloned.is_closed is False
        assert cloned.is_locked is False
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        boundary = create_test_boundary()
        snap = boundary.snapshot()
        assert snap["period_id"] == str(boundary.period_id)
        assert snap["is_closed"] == boundary.is_closed
        assert "timestamp" in snap

    def test_get_version(self):
        boundary = create_test_boundary()
        assert boundary.get_version() == 1

    def test_audit_trail_records_actions(self):
        boundary = create_test_boundary()
        assert len(boundary.audit_trail()) >= 1
        boundary.touch("toucher")
        trail = boundary.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        boundary = create_test_boundary()
        touched = boundary.touch("toucher")
        assert touched.version == boundary.version + 1


# ============================================================================
# TESTS FOR TransactionTimestamp
# ============================================================================

class TestTransactionTimestamp:
    def test_create_valid_timestamp(self):
        timestamp = create_test_timestamp()
        assert timestamp.transaction_id is not None
        assert timestamp.effective_date is not None
        assert timestamp.posting_date is not None
        assert timestamp.created_by == "tester"
        assert timestamp.version == 1
        assert timestamp.cryptographic_hash != ""

    def test_validate_requires_timezone(self):
        # Should not raise if timezone is set
        timestamp = create_test_timestamp()
        # Timezone is already UTC

    def test_update_raises(self):
        timestamp = create_test_timestamp()
        with pytest.raises(AttributeError):
            timestamp.update("admin", effective_date=datetime.now(UTC))

    def test_delete_marks_deleted(self):
        timestamp = create_test_timestamp()
        deleted = timestamp.delete("admin", "test")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == timestamp.version + 1

    def test_restore_recovers_deleted(self):
        timestamp = create_test_timestamp()
        deleted = timestamp.delete("admin", "test")
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1

    def test_restore_not_deleted_raises(self):
        timestamp = create_test_timestamp()
        with pytest.raises(ValueError, match="Not deleted"):
            timestamp.restore("admin")

    def test_activate_returns_self(self):
        timestamp = create_test_timestamp()
        activated = timestamp.activate("admin")
        assert activated is timestamp

    def test_deactivate_returns_self(self):
        timestamp = create_test_timestamp()
        deactivated = timestamp.deactivate("admin")
        assert deactivated is timestamp

    def test_lock_returns_self(self):
        timestamp = create_test_timestamp()
        locked = timestamp.lock("admin", "test")
        assert locked is timestamp

    def test_unlock_returns_self(self):
        timestamp = create_test_timestamp()
        unlocked = timestamp.unlock("admin")
        assert unlocked is timestamp

    def test_validate_returns_valid(self):
        timestamp = create_test_timestamp()
        result = timestamp.validate()
        assert result["is_valid"] is True
        assert result["transaction_id"] == str(timestamp.transaction_id)

    def test_validate_returns_errors_on_hash_mismatch(self):
        timestamp = create_test_timestamp()
        object.__setattr__(timestamp, "cryptographic_hash", "fake")
        result = timestamp.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]

    def test_to_dict_contains_fields(self):
        timestamp = create_test_timestamp()
        d = timestamp.to_dict()
        assert d["created_by"] == "tester"
        assert "effective_date" in d
        assert "posting_date" in d
        assert "transaction_id" in d

    def test_from_dict_reconstructs(self):
        timestamp = create_test_timestamp()
        d = timestamp.to_dict()
        reconstructed = TransactionTimestamp.from_dict(d)
        assert reconstructed.transaction_id == timestamp.transaction_id
        assert reconstructed.effective_date == timestamp.effective_date
        assert reconstructed.posting_date == timestamp.posting_date
        assert reconstructed.created_by == timestamp.created_by

    def test_clone_creates_new_instance(self):
        timestamp = create_test_timestamp()
        cloned = timestamp.clone()
        assert cloned.transaction_id != timestamp.transaction_id
        assert cloned.effective_date == timestamp.effective_date
        assert cloned.posting_date == timestamp.posting_date
        assert cloned.version == 1

    def test_snapshot_returns_summary(self):
        timestamp = create_test_timestamp()
        snap = timestamp.snapshot()
        assert snap["transaction_id"] == str(timestamp.transaction_id)
        assert "effective_date" in snap

    def test_get_version(self):
        timestamp = create_test_timestamp()
        assert timestamp.get_version() == 1

    def test_audit_trail_records_actions(self):
        timestamp = create_test_timestamp()
        assert len(timestamp.audit_trail()) >= 1
        timestamp.touch("toucher")
        trail = timestamp.audit_trail()
        assert len(trail) >= 2
        assert trail[-1]["action"] == "TOUCH"

    def test_touch_increments_version(self):
        timestamp = create_test_timestamp()
        touched = timestamp.touch("toucher")
        assert touched.version == timestamp.version + 1

    def test_get_time_difference(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now - timedelta(days=5),
            posting_date=now,
            approval_date=now - timedelta(days=3),
            settlement_date=now + timedelta(days=2),
            created_at=now - timedelta(days=7),
            created_by="tester",
        )
        diff = ts.get_time_difference(TransactionTimeContext.EFFECTIVE, TransactionTimeContext.POSTING)
        assert diff == timedelta(days=-5)

    def test_get_time_difference_missing_context_raises(self):
        ts = create_test_timestamp(approval_date=None)
        with pytest.raises(ValueError, match="Missing datetime"):
            ts.get_time_difference(TransactionTimeContext.EFFECTIVE, TransactionTimeContext.APPROVAL)

    def test_is_chronological_valid(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now - timedelta(days=3),
            posting_date=now - timedelta(days=2),
            approval_date=now - timedelta(days=1),
            settlement_date=now,
            created_at=now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is True
        assert violations == []

    def test_is_chronological_invalid_effective_after_posting(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now,
            posting_date=now - timedelta(days=1),
            approval_date=now - timedelta(days=2),
            settlement_date=now + timedelta(days=1),
            created_at=now - timedelta(days=3),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is False
        assert any("Effective" in v for v in violations)

    def test_get_backdate_days(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now - timedelta(days=10),
            posting_date=now,
            approval_date=None,
            settlement_date=None,
            created_at=now - timedelta(days=11),
            created_by="tester",
        )
        assert ts.get_backdate_days(now) == 10
        assert ts.get_backdate_days() >= 10


# ============================================================================
# TESTS FOR TimeIrreversibilityViolation
# ============================================================================

class TestTimeIrreversibilityViolation:
    def test_create_valid_violation(self):
        violation = create_test_violation()
        assert violation.violation_id is not None
        assert violation.transaction_id is not None
        assert violation.backdate_days == 10
        assert violation.severity == TimeIrreversibilityViolationSeverity.HIGH
        assert violation.is_blocked is True
        assert violation.override_granted is False
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_validate_returns_valid(self):
        violation = create_test_violation()
        result = violation.validate()
        assert result["is_valid"] is True

    def test_validate_returns_errors_on_hash_mismatch(self):
        violation = create_test_violation()
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert result["is_valid"] is False
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
        assert d["severity"] == "HIGH"
        assert d["backdate_days"] == 10
        assert d["is_blocked"] is True
        assert d["override_granted"] is False
        assert "violation_id" in d

    def test_from_dict_reconstructs(self):
        violation = create_test_violation()
        d = violation.to_dict()
        reconstructed = TimeIrreversibilityViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.transaction_id == violation.transaction_id
        assert reconstructed.severity == violation.severity
        assert reconstructed.backdate_days == violation.backdate_days

    def test_clone_creates_new_instance(self):
        violation = create_test_violation()
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.transaction_id == violation.transaction_id
        assert cloned.override_granted is False
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

    def test_resolve_grants_override(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "Override reason")
        assert resolved.override_granted is True
        assert resolved.override_by == "admin"
        assert resolved.override_reason == "Override reason"
        assert resolved.version == violation.version + 1

    def test_resolve_already_overridden_raises(self):
        violation = create_test_violation()
        resolved = violation.resolve("admin", "test")
        with pytest.raises(ValueError, match="Already overridden"):
            resolved.resolve("admin2", "again")


# ============================================================================
# TESTS FOR TimeIrreversibilityValidator
# ============================================================================

class TestTimeIrreversibilityValidator:
    def test_validate_effective_date_valid(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary()
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=now,
            current_period=boundary,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violation is None

    def test_validate_effective_date_closed_period(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-30, end_offset_days=-1, is_closed=True)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=now - timedelta(days=5),
                current_period=boundary,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CATASTROPHIC

    def test_validate_effective_date_locked_period(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(is_locked=True)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=now,
                current_period=boundary,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CRITICAL

    def test_validate_effective_date_backdate_exceeds_limit(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-30, end_offset_days=30)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=now - timedelta(days=20),
                current_period=boundary,
                max_backdate_days=10,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.backdate_days == 20

    def test_validate_effective_date_backdate_within_tolerance(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-2, end_offset_days=30)
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=now - timedelta(days=1),
            current_period=boundary,
            max_backdate_days=10,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violation is None

    def test_validate_effective_date_future_posting_blocked(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-30, end_offset_days=30)
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=now + timedelta(days=30),
            current_period=boundary,
            transaction_id=uuid.uuid4(),
            allow_future_posting=False,
        )
        assert is_valid is True  # Not blocked, just warning
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.MEDIUM

    def test_validate_effective_date_last_transaction_backdate(self):
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-30, end_offset_days=30)
        last_date = now - timedelta(days=2)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=now - timedelta(days=10),
                current_period=boundary,
                last_transaction_date=last_date,
                max_backdate_days=5,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.backdate_days == 8  # 10 - 2

    def test_validate_chronological_order_valid(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now - timedelta(days=3),
            posting_date=now - timedelta(days=2),
            approval_date=now - timedelta(days=1),
            settlement_date=now,
            created_at=now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
            timestamp=ts,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violations == []

    def test_validate_chronological_order_invalid(self):
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now,
            posting_date=now - timedelta(days=1),
            approval_date=now - timedelta(days=2),
            settlement_date=now + timedelta(days=1),
            created_at=now - timedelta(days=3),
            created_by="tester",
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
                timestamp=ts,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert len(violations) > 0


# ============================================================================
# TESTS FOR TimeIrreversibilityAxiom
# ============================================================================

class TestTimeIrreversibilityAxiom:
    def test_singleton(self):
        axiom1 = TimeIrreversibilityAxiom()
        axiom2 = TimeIrreversibilityAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_time_boundary(self):
        axiom = TimeIrreversibilityAxiom()
        boundary = create_test_boundary()
        axiom.save_time_boundary(boundary)
        retrieved = axiom.get_time_boundary(boundary.period_id)
        assert retrieved is not None
        assert retrieved.period_id == boundary.period_id

    def test_get_all_time_boundaries(self):
        axiom = TimeIrreversibilityAxiom()
        b1 = create_test_boundary()
        b2 = create_test_boundary()
        axiom.save_time_boundary(b1)
        axiom.save_time_boundary(b2)
        boundaries = axiom.get_all_time_boundaries()
        assert len(boundaries) >= 2

    def test_delete_time_boundary(self):
        axiom = TimeIrreversibilityAxiom()
        boundary = create_test_boundary()
        axiom.save_time_boundary(boundary)
        result = axiom.delete_time_boundary(boundary.period_id)
        assert result is True
        assert axiom.get_time_boundary(boundary.period_id) is None

    def test_save_and_get_transaction_timestamp(self):
        axiom = TimeIrreversibilityAxiom()
        timestamp = create_test_timestamp()
        axiom.save_transaction_timestamp(timestamp)
        retrieved = axiom.get_transaction_timestamp(timestamp.transaction_id)
        assert retrieved is not None
        assert retrieved.transaction_id == timestamp.transaction_id

    def test_delete_transaction_timestamp(self):
        axiom = TimeIrreversibilityAxiom()
        timestamp = create_test_timestamp()
        axiom.save_transaction_timestamp(timestamp)
        result = axiom.delete_transaction_timestamp(timestamp.transaction_id)
        assert result is True
        assert axiom.get_transaction_timestamp(timestamp.transaction_id) is None

    def test_save_and_get_violations(self):
        axiom = TimeIrreversibilityAxiom()
        violation = create_test_violation()
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_severity(self):
        axiom = TimeIrreversibilityAxiom()
        v1 = create_test_violation()
        v1.severity = TimeIrreversibilityViolationSeverity.LOW
        v2 = create_test_violation()
        v2.severity = TimeIrreversibilityViolationSeverity.CRITICAL
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(min_severity=TimeIrreversibilityViolationSeverity.HIGH)
        assert all(v.severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value for v in result)

    def test_get_violations_filter_blocked(self):
        axiom = TimeIrreversibilityAxiom()
        v1 = create_test_violation()
        v1.is_blocked = True
        v2 = create_test_violation()
        v2.is_blocked = False
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(only_blocked=True)
        assert all(v.is_blocked is True for v in result)

    def test_register_time_boundary(self):
        axiom = TimeIrreversibilityAxiom()
        boundary = create_test_boundary()
        axiom.register_time_boundary(boundary)
        assert axiom.get_time_boundary(boundary.period_id) is not None

    def test_get_current_period(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-5, end_offset_days=5)
        axiom.save_time_boundary(boundary)
        current = axiom.get_current_period(now)
        assert current is not None
        assert current.period_id == boundary.period_id

    def test_get_current_period_no_match(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-20, end_offset_days=-10)
        axiom.save_time_boundary(boundary)
        current = axiom.get_current_period(now)
        assert current is None

    def test_record_transaction_timestamp(self):
        axiom = TimeIrreversibilityAxiom()
        timestamp = create_test_timestamp()
        axiom.record_transaction_timestamp(timestamp)
        retrieved = axiom.get_transaction_timestamp(timestamp.transaction_id)
        assert retrieved is not None

    def test_get_last_transaction_date(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        timestamp = create_test_timestamp(effective_date=now - timedelta(days=1))
        axiom.record_transaction_timestamp(timestamp)
        last_date = axiom.get_last_transaction_date()
        assert last_date is not None

    def test_enforce_effective_date_valid(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        boundary = create_test_boundary()
        axiom.save_time_boundary(boundary)
        is_valid, violation = axiom.enforce_effective_date(
            effective_date=now,
            period_id=boundary.period_id,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violation is None

    def test_enforce_effective_date_backdate_with_override(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        boundary = create_test_boundary(start_offset_days=-30, end_offset_days=30)
        axiom.save_time_boundary(boundary)
        is_valid, violation = axiom.enforce_effective_date(
            effective_date=now - timedelta(days=20),
            period_id=boundary.period_id,
            transaction_id=uuid.uuid4(),
            max_backdate_days=10,
            raise_on_violation=False,
            allow_override=True,
            override_by="admin",
            override_reason="Need backdate",
        )
        # Since violation exists and override is allowed, it should be granted
        assert is_valid is True
        if violation:
            assert violation.override_granted is True

    def test_enforce_effective_date_no_period_raises(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        with pytest.raises(TimeIrreversibilityViolationError):
            axiom.enforce_effective_date(
                effective_date=now,
                period_id=uuid.uuid4(),  # Non-existent period
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )

    def test_enforce_chronological_order_valid(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now - timedelta(days=3),
            posting_date=now - timedelta(days=2),
            approval_date=now - timedelta(days=1),
            settlement_date=now,
            created_at=now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = axiom.enforce_chronological_order(
            timestamp=ts,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violations == []

    def test_enforce_chronological_order_invalid_raises(self):
        axiom = TimeIrreversibilityAxiom()
        now = datetime.now(UTC)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=now,
            posting_date=now - timedelta(days=1),
            approval_date=now - timedelta(days=2),
            settlement_date=now + timedelta(days=1),
            created_at=now - timedelta(days=3),
            created_by="tester",
        )
        with pytest.raises(TimeIrreversibilityViolationError):
            axiom.enforce_chronological_order(
                timestamp=ts,
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )

    def test_get_statistics(self):
        axiom = TimeIrreversibilityAxiom()
        boundary = create_test_boundary()
        axiom.save_time_boundary(boundary)
        timestamp = create_test_timestamp()
        axiom.save_transaction_timestamp(timestamp)
        stats = axiom.get_statistics()
        assert stats["total_time_boundaries"] >= 1
        assert stats["total_transaction_timestamps"] >= 1
        assert "total_violations" in stats
        assert "blocked_count" in stats
        assert "overridden_count" in stats

    def test_reset(self):
        axiom = TimeIrreversibilityAxiom()
        boundary = create_test_boundary()
        axiom.save_time_boundary(boundary)
        timestamp = create_test_timestamp()
        axiom.save_transaction_timestamp(timestamp)
        axiom.reset()
        assert len(axiom._time_boundaries) == 0
        assert len(axiom._transaction_timestamps) == 0
        assert len(axiom._violation_history) == 0


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_time_boundary(self):
        period_id = uuid.uuid4()
        now = datetime.now(UTC)
        start = now - timedelta(days=10)
        end = now + timedelta(days=10)
        boundary = create_time_boundary(
            period_id=period_id,
            period_name="Test",
            fiscal_year=2026,
            period_number=1,
            start_date=start,
            end_date=end,
            is_closed=True,
            closed_at=now,
            closed_by="admin",
            locked_at=now,
            locked_by="admin",
        )
        assert boundary.period_id == period_id
        assert boundary.period_name == "Test"
        assert boundary.is_closed is True
        assert boundary.closed_by == "admin"
        assert boundary.locked_by == "admin"

    def test_create_transaction_timestamp(self):
        transaction_id = uuid.uuid4()
        now = datetime.now(UTC)
        eff = now - timedelta(days=1)
        timestamp = create_transaction_timestamp(
            transaction_id=transaction_id,
            effective_date=eff,
            posting_date=now,
            approval_date=now + timedelta(days=1),
            settlement_date=now + timedelta(days=2),
            created_by="admin",
        )
        assert timestamp.transaction_id == transaction_id
        assert timestamp.effective_date == eff
        assert timestamp.posting_date == now
        assert timestamp.approval_date is not None
        assert timestamp.created_by == "admin"

    def test_create_transaction_timestamp_posting_default(self):
        transaction_id = uuid.uuid4()
        now = datetime.now(UTC)
        eff = now - timedelta(days=1)
        timestamp = create_transaction_timestamp(
            transaction_id=transaction_id,
            effective_date=eff,
        )
        assert timestamp.posting_date is not None
        assert timestamp.created_by == "system"

    def test_get_time_irreversibility_axiom_singleton(self):
        axiom1 = get_time_irreversibility_axiom()
        axiom2 = get_time_irreversibility_axiom()
        assert axiom1 is axiom2