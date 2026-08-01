#!/usr/bin/env python3
"""
tests/unit/test_time_irreversibility.py
Comprehensive tests for axioms/time_irreversibility.py

Covers:
- TimeBoundary, TransactionTimestamp, TimeIrreversibilityViolation entities
- All entity methods: __post_init__, validate, update/delete/restore, lock/unlock,
  activate/deactivate, clone, snapshot, version, audit_trail, touch,
  to_dict/from_dict, domain methods (contains, is_modifiable, get_time_difference,
  is_chronological, get_backdate_days, resolve)
- TimeIrreversibilityValidator
- TimeIrreversibilityAxiom (singleton, repository, business methods)
- Helper functions: create_time_boundary, create_transaction_timestamp,
  get_time_irreversibility_axiom
- Exception classes
- All edge cases and error conditions
- No flaky datetime (fixed or mocked)
- No duplicate test structures (parametrize used)
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
# FIXED DATETIME (to avoid flakiness)
# ============================================================================

FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
FIXED_DAY = timedelta(days=1)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def fixed_now():
    return FIXED_NOW


@pytest.fixture
def boundary(fixed_now):
    start = fixed_now - timedelta(days=15)
    end = fixed_now + timedelta(days=15)
    return TimeBoundary(
        period_id=uuid.uuid4(),
        period_name="Test Period",
        fiscal_year=2026,
        period_number=1,
        start_date=start,
        end_date=end,
        is_closed=False,
        is_locked=False,
    )


@pytest.fixture
def timestamp(fixed_now):
    return TransactionTimestamp(
        transaction_id=uuid.uuid4(),
        effective_date=fixed_now - timedelta(days=1),
        posting_date=fixed_now,
        approval_date=fixed_now - timedelta(days=1),
        settlement_date=fixed_now + timedelta(days=1),
        created_at=fixed_now - timedelta(days=2),
        created_by="tester",
    )


@pytest.fixture
def violation(fixed_now):
    return TimeIrreversibilityViolation(
        violation_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        attempted_effective_date=fixed_now - timedelta(days=10),
        current_period_start=fixed_now - timedelta(days=15),
        current_period_end=fixed_now + timedelta(days=15),
        last_transaction_date=fixed_now - timedelta(days=5),
        period_status="OPEN",
        backdate_days=10,
        severity=TimeIrreversibilityViolationSeverity.HIGH,
        message="Test violation",
        user_id="user123",
        module="test_module",
        detected_at=fixed_now,
        is_blocked=True,
        override_granted=False,
        override_by=None,
        override_reason=None,
    )


@pytest.fixture
def axiom():
    # Reset singleton for clean state
    instance = TimeIrreversibilityAxiom()
    instance.reset()
    return instance


# ============================================================================
# EXCEPTION CLASSES
# ============================================================================

def test_time_irreversibility_error():
    exc = TimeIrreversibilityError("test")
    assert str(exc) == "test"
    assert isinstance(exc, Exception)


def test_time_irreversibility_violation_error():
    violation = TimeIrreversibilityViolation(
        violation_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        attempted_effective_date=FIXED_NOW,
        current_period_start=FIXED_NOW,
        current_period_end=FIXED_NOW,
        last_transaction_date=None,
        period_status="OPEN",
        backdate_days=0,
        severity=TimeIrreversibilityViolationSeverity.LOW,
        message="test",
        user_id=None,
        module="test",
        detected_at=FIXED_NOW,
        is_blocked=False,
        override_granted=False,
        override_by=None,
        override_reason=None,
    )
    exc = TimeIrreversibilityViolationError("msg", violation)
    assert str(exc) == "msg"
    assert exc.violation is violation


# ============================================================================
# TESTS FOR TimeBoundary
# ============================================================================

class TestTimeBoundary:
    def test_construction_valid(self, boundary, fixed_now):
        assert boundary.period_id is not None
        assert boundary.start_date == fixed_now - timedelta(days=15)
        assert boundary.end_date == fixed_now + timedelta(days=15)
        assert boundary.is_closed is False
        assert boundary.is_locked is False
        assert boundary.version == 1
        assert boundary.cryptographic_hash != ""

    def test_validation_start_before_end(self, fixed_now):
        with pytest.raises(ValueError, match="Start date must be before end date"):
            TimeBoundary(
                period_id=uuid.uuid4(),
                period_name="Invalid",
                fiscal_year=2026,
                period_number=1,
                start_date=fixed_now + timedelta(days=10),
                end_date=fixed_now - timedelta(days=10),
                is_closed=False,
                is_locked=False,
            )

    def test_validation_version_zero_raises(self, fixed_now):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            TimeBoundary(
                period_id=uuid.uuid4(),
                period_name="Test",
                fiscal_year=2026,
                period_number=1,
                start_date=fixed_now - timedelta(days=1),
                end_date=fixed_now + timedelta(days=1),
                is_closed=False,
                is_locked=False,
                version=0,
            )

    def test_compute_hash(self, boundary):
        h1 = boundary.compute_hash()
        h2 = boundary.compute_hash()
        assert h1 == h2
        # Changing a field should change hash
        modified = boundary.update("admin", is_closed=True)
        assert modified.compute_hash() != boundary.compute_hash()

    def test_update(self, boundary):
        updated = boundary.update("admin", period_name="New Name", is_closed=True)
        assert updated.period_name == "New Name"
        assert updated.is_closed is True
        assert updated.version == boundary.version + 1
        assert updated is not boundary
        trail = updated.audit_trail()
        assert trail[-1]["action"] == "UPDATE"

    def test_update_immutable_fields_ignored(self, boundary):
        updated = boundary.update("admin", period_id=uuid.uuid4())
        assert updated.period_id == boundary.period_id

    def test_delete(self, boundary):
        deleted = boundary.delete("admin", "reason")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        assert deleted.version == boundary.version + 1
        trail = deleted.audit_trail()
        assert trail[-1]["action"] == "DELETE"

    def test_restore(self, boundary):
        deleted = boundary.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1
        trail = restored.audit_trail()
        assert trail[-1]["action"] == "RESTORE"

    def test_restore_not_deleted_raises(self, boundary):
        with pytest.raises(ValueError, match="Not deleted"):
            boundary.restore("admin")

    def test_activate(self, boundary):
        activated = boundary.activate("admin")
        assert activated is boundary  # returns self

    def test_deactivate(self, boundary):
        deactivated = boundary.deactivate("admin", "reason")
        assert deactivated is boundary

    def test_lock(self, boundary):
        locked = boundary.lock("admin", "test reason")
        assert locked.is_locked is True
        assert locked.locked_by == "admin"
        assert locked.locked_at == FIXED_NOW
        assert locked.version == boundary.version + 1
        # Lock again should return self
        locked2 = locked.lock("admin2", "again")
        assert locked2 is locked

    def test_unlock(self, boundary):
        locked = boundary.lock("admin", "test")
        unlocked = locked.unlock("admin2")
        assert unlocked.is_locked is False
        assert unlocked.locked_by is None
        assert unlocked.locked_at is None
        assert unlocked.version == locked.version + 1
        # Unlock when already unlocked returns self
        unlocked2 = unlocked.unlock("admin3")
        assert unlocked2 is unlocked

    def test_validate_valid(self, boundary):
        result = boundary.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["period_id"] == str(boundary.period_id)
        assert result["version"] == boundary.version

    def test_validate_hash_mismatch(self, boundary):
        original_hash = boundary.cryptographic_hash
        object.__setattr__(boundary, "cryptographic_hash", "fake")
        result = boundary.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]
        # Restore for other tests
        object.__setattr__(boundary, "cryptographic_hash", original_hash)

    def test_to_dict(self, boundary):
        d = boundary.to_dict()
        assert d["period_id"] == str(boundary.period_id)
        assert d["period_name"] == "Test Period"
        assert d["fiscal_year"] == 2026
        assert d["start_date"] == boundary.start_date.isoformat()
        assert d["is_closed"] is False
        assert d["version"] == 1
        assert "deleted_at" in d

    def test_from_dict(self, boundary):
        d = boundary.to_dict()
        reconstructed = TimeBoundary.from_dict(d)
        assert reconstructed.period_id == boundary.period_id
        assert reconstructed.period_name == boundary.period_name
        assert reconstructed.fiscal_year == boundary.fiscal_year
        assert reconstructed.start_date == boundary.start_date
        assert reconstructed.is_closed == boundary.is_closed
        assert reconstructed.version == boundary.version

    def test_clone(self, boundary):
        cloned = boundary.clone()
        assert cloned.period_id != boundary.period_id
        assert cloned.period_name == boundary.period_name + "_COPY"
        assert cloned.fiscal_year == boundary.fiscal_year
        assert cloned.start_date == boundary.start_date
        assert cloned.is_closed is False
        assert cloned.is_locked is False
        assert cloned.version == 1

    def test_snapshot(self, boundary):
        snap = boundary.snapshot()
        assert snap["version"] == boundary.version
        assert snap["period_id"] == str(boundary.period_id)
        assert "timestamp" in snap

    def test_get_version(self, boundary):
        assert boundary.get_version() == boundary.version

    def test_audit_trail(self, boundary):
        boundary.create("admin")
        trail = boundary.audit_trail()
        assert len(trail) >= 1
        assert trail[0]["action"] == "CREATE"
        boundary.touch("toucher")
        trail2 = boundary.audit_trail()
        assert len(trail2) >= len(trail) + 1
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, boundary):
        touched = boundary.touch("toucher")
        assert touched.version == boundary.version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"
        assert trail[-1]["performed_by"] == "toucher"

    def test_contains(self, boundary, fixed_now):
        assert boundary.contains(fixed_now) is True
        assert boundary.contains(fixed_now - timedelta(days=20)) is False
        assert boundary.contains(fixed_now + timedelta(days=20)) is False
        # Test with naive datetime
        naive = fixed_now.replace(tzinfo=None)
        assert boundary.contains(naive) is True

    def test_is_modifiable(self, boundary):
        assert boundary.is_modifiable() is True
        closed = boundary.update("admin", is_closed=True)
        assert closed.is_modifiable() is False
        locked = boundary.update("admin", is_locked=True)
        assert locked.is_modifiable() is False


# ============================================================================
# TESTS FOR TransactionTimestamp
# ============================================================================

class TestTransactionTimestamp:
    def test_construction_valid(self, timestamp, fixed_now):
        assert timestamp.transaction_id is not None
        assert timestamp.effective_date == fixed_now - timedelta(days=1)
        assert timestamp.posting_date == fixed_now
        assert timestamp.approval_date == fixed_now - timedelta(days=1)
        assert timestamp.settlement_date == fixed_now + timedelta(days=1)
        assert timestamp.version == 1
        assert timestamp.cryptographic_hash != ""

    def test_validation_naive_dates_utc_aware(self, fixed_now):
        naive = fixed_now.replace(tzinfo=None)
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=naive,
            posting_date=naive + timedelta(days=1),
            approval_date=None,
            settlement_date=None,
            created_at=naive,
            created_by="tester",
        )
        assert ts.effective_date.tzinfo == UTC
        assert ts.posting_date.tzinfo == UTC

    def test_validation_version_zero_raises(self, fixed_now):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            TransactionTimestamp(
                transaction_id=uuid.uuid4(),
                effective_date=fixed_now,
                posting_date=fixed_now,
                approval_date=None,
                settlement_date=None,
                created_at=fixed_now,
                created_by="tester",
                version=0,
            )

    def test_compute_hash(self, timestamp):
        h1 = timestamp.compute_hash()
        h2 = timestamp.compute_hash()
        assert h1 == h2

    def test_update_raises(self, timestamp):
        with pytest.raises(AttributeError, match="immutable"):
            timestamp.update("admin", effective_date=FIXED_NOW)

    def test_delete(self, timestamp):
        deleted = timestamp.delete("admin", "reason")
        assert deleted.deleted_at == FIXED_NOW
        assert deleted.deleted_by == "admin"
        assert deleted.version == timestamp.version + 1
        trail = deleted.audit_trail()
        assert trail[-1]["action"] == "DELETE"

    def test_restore(self, timestamp):
        deleted = timestamp.delete("admin")
        restored = deleted.restore("admin2")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1
        trail = restored.audit_trail()
        assert trail[-1]["action"] == "RESTORE"

    def test_restore_not_deleted_raises(self, timestamp):
        with pytest.raises(ValueError, match="Not deleted"):
            timestamp.restore("admin")

    def test_activate(self, timestamp):
        activated = timestamp.activate("admin")
        assert activated is timestamp

    def test_deactivate(self, timestamp):
        deactivated = timestamp.deactivate("admin", "reason")
        assert deactivated is timestamp

    def test_lock(self, timestamp):
        locked = timestamp.lock("admin", "reason")
        assert locked is timestamp

    def test_unlock(self, timestamp):
        unlocked = timestamp.unlock("admin")
        assert unlocked is timestamp

    def test_validate_valid(self, timestamp):
        result = timestamp.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["transaction_id"] == str(timestamp.transaction_id)

    def test_validate_hash_mismatch(self, timestamp):
        original_hash = timestamp.cryptographic_hash
        object.__setattr__(timestamp, "cryptographic_hash", "fake")
        result = timestamp.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]
        object.__setattr__(timestamp, "cryptographic_hash", original_hash)

    def test_to_dict(self, timestamp):
        d = timestamp.to_dict()
        assert d["transaction_id"] == str(timestamp.transaction_id)
        assert d["effective_date"] == timestamp.effective_date.isoformat()
        assert d["posting_date"] == timestamp.posting_date.isoformat()
        assert d["approval_date"] == timestamp.approval_date.isoformat()
        assert d["version"] == 1

    def test_from_dict(self, timestamp):
        d = timestamp.to_dict()
        reconstructed = TransactionTimestamp.from_dict(d)
        assert reconstructed.transaction_id == timestamp.transaction_id
        assert reconstructed.effective_date == timestamp.effective_date
        assert reconstructed.posting_date == timestamp.posting_date
        assert reconstructed.version == timestamp.version

    def test_clone(self, timestamp):
        cloned = timestamp.clone()
        assert cloned.transaction_id != timestamp.transaction_id
        assert cloned.effective_date == timestamp.effective_date
        assert cloned.posting_date == timestamp.posting_date
        assert cloned.version == 1
        assert cloned.created_by == timestamp.created_by

    def test_snapshot(self, timestamp):
        snap = timestamp.snapshot()
        assert snap["version"] == timestamp.version
        assert snap["transaction_id"] == str(timestamp.transaction_id)
        assert "effective_date" in snap

    def test_get_version(self, timestamp):
        assert timestamp.get_version() == timestamp.version

    def test_audit_trail(self, timestamp):
        timestamp.create("admin")
        trail = timestamp.audit_trail()
        assert len(trail) >= 1
        assert trail[0]["action"] == "CREATE"
        timestamp.touch("toucher")
        trail2 = timestamp.audit_trail()
        assert len(trail2) >= len(trail) + 1
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, timestamp):
        touched = timestamp.touch("toucher")
        assert touched.version == timestamp.version + 1
        trail = touched.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_get_time_difference(self, timestamp):
        # effective = now-1, posting = now => diff = -1 day
        diff = timestamp.get_time_difference(TransactionTimeContext.EFFECTIVE, TransactionTimeContext.POSTING)
        assert diff == timedelta(days=-1)

    def test_get_time_difference_missing_context_raises(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=1),
            posting_date=fixed_now,
            approval_date=None,
            settlement_date=None,
            created_at=fixed_now - timedelta(days=2),
            created_by="tester",
        )
        with pytest.raises(ValueError, match="Missing datetime"):
            ts.get_time_difference(TransactionTimeContext.EFFECTIVE, TransactionTimeContext.APPROVAL)

    def test_is_chronological_valid(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=3),
            posting_date=fixed_now - timedelta(days=2),
            approval_date=fixed_now - timedelta(days=1),
            settlement_date=fixed_now,
            created_at=fixed_now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is True
        assert violations == []

    def test_is_chronological_invalid_effective_after_posting(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now,
            posting_date=fixed_now - timedelta(days=1),
            approval_date=fixed_now - timedelta(days=2),
            settlement_date=fixed_now + timedelta(days=1),
            created_at=fixed_now - timedelta(days=3),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is False
        assert any("Effective" in v for v in violations)

    def test_is_chronological_invalid_approval_after_posting(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=3),
            posting_date=fixed_now - timedelta(days=2),
            approval_date=fixed_now,
            settlement_date=None,
            created_at=fixed_now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is False
        assert any("Approval" in v for v in violations)

    def test_is_chronological_invalid_settlement_before_posting(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=3),
            posting_date=fixed_now,
            approval_date=fixed_now - timedelta(days=1),
            settlement_date=fixed_now - timedelta(days=1),
            created_at=fixed_now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = ts.is_chronological()
        assert is_valid is False
        assert any("Posting" in v and "settlement" in v for v in violations)

    def test_get_backdate_days(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=10),
            posting_date=fixed_now,
            approval_date=None,
            settlement_date=None,
            created_at=fixed_now - timedelta(days=11),
            created_by="tester",
        )
        assert ts.get_backdate_days(fixed_now) == 10
        # default reference = now (mocked to fixed)
        with patch("axioms.time_irreversibility.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            assert ts.get_backdate_days() == 10

    def test_get_backdate_days_effective_after_reference(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now + timedelta(days=5),
            posting_date=fixed_now,
            approval_date=None,
            settlement_date=None,
            created_at=fixed_now,
            created_by="tester",
        )
        assert ts.get_backdate_days(fixed_now) == 0


# ============================================================================
# TESTS FOR TimeIrreversibilityViolation
# ============================================================================

class TestTimeIrreversibilityViolation:
    def test_construction_valid(self, violation, fixed_now):
        assert violation.violation_id is not None
        assert violation.transaction_id is not None
        assert violation.attempted_effective_date == fixed_now - timedelta(days=10)
        assert violation.backdate_days == 10
        assert violation.severity == TimeIrreversibilityViolationSeverity.HIGH
        assert violation.is_blocked is True
        assert violation.override_granted is False
        assert violation.version == 1
        assert violation.cryptographic_hash != ""

    def test_validation_version_zero_raises(self, fixed_now):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            TimeIrreversibilityViolation(
                violation_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                attempted_effective_date=fixed_now,
                current_period_start=fixed_now,
                current_period_end=fixed_now,
                last_transaction_date=None,
                period_status="OPEN",
                backdate_days=0,
                severity=TimeIrreversibilityViolationSeverity.LOW,
                message="",
                user_id=None,
                module="test",
                detected_at=fixed_now,
                is_blocked=False,
                override_granted=False,
                override_by=None,
                override_reason=None,
                version=0,
            )

    def test_compute_hash(self, violation):
        h1 = violation.compute_hash()
        h2 = violation.compute_hash()
        assert h1 == h2

    def test_update_raises(self, violation):
        with pytest.raises(AttributeError, match="immutable"):
            violation.update("admin", message="new")

    def test_delete_raises(self, violation):
        with pytest.raises(AttributeError, match="Cannot delete"):
            violation.delete("admin")

    def test_restore_raises(self, violation):
        with pytest.raises(AttributeError, match="Cannot restore"):
            violation.restore("admin")

    def test_activate(self, violation):
        activated = violation.activate("admin")
        assert activated is violation

    def test_deactivate(self, violation):
        deactivated = violation.deactivate("admin", "reason")
        assert deactivated is violation

    def test_lock(self, violation):
        locked = violation.lock("admin", "reason")
        assert locked is violation

    def test_unlock(self, violation):
        unlocked = violation.unlock("admin")
        assert unlocked is violation

    def test_validate_valid(self, violation):
        result = violation.validate()
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert result["violation_id"] == str(violation.violation_id)

    def test_validate_hash_mismatch(self, violation):
        original_hash = violation.cryptographic_hash
        object.__setattr__(violation, "cryptographic_hash", "fake")
        result = violation.validate()
        assert result["is_valid"] is False
        assert "Hash mismatch" in result["errors"]
        object.__setattr__(violation, "cryptographic_hash", original_hash)

    def test_to_dict(self, violation):
        d = violation.to_dict()
        assert d["violation_id"] == str(violation.violation_id)
        assert d["transaction_id"] == str(violation.transaction_id)
        assert d["severity"] == "HIGH"
        assert d["backdate_days"] == 10
        assert d["is_blocked"] is True

    def test_from_dict(self, violation):
        d = violation.to_dict()
        reconstructed = TimeIrreversibilityViolation.from_dict(d)
        assert reconstructed.violation_id == violation.violation_id
        assert reconstructed.transaction_id == violation.transaction_id
        assert reconstructed.severity == violation.severity
        assert reconstructed.backdate_days == violation.backdate_days
        assert reconstructed.version == violation.version

    def test_clone(self, violation):
        cloned = violation.clone()
        assert cloned.violation_id != violation.violation_id
        assert cloned.transaction_id == violation.transaction_id
        assert cloned.backdate_days == violation.backdate_days
        assert cloned.severity == violation.severity
        assert cloned.is_blocked == violation.is_blocked
        assert cloned.override_granted is False
        assert cloned.version == 1

    def test_snapshot(self, violation):
        snap = violation.snapshot()
        assert snap["version"] == violation.version
        assert snap["violation_id"] == str(violation.violation_id)
        assert "severity" in snap

    def test_get_version(self, violation):
        assert violation.get_version() == violation.version

    def test_audit_trail(self, violation):
        violation.create("admin")
        trail = violation.audit_trail()
        assert len(trail) >= 1
        assert trail[0]["action"] == "CREATE"
        violation.touch("toucher")
        trail2 = violation.audit_trail()
        assert len(trail2) >= len(trail) + 1
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, violation):
        # touch does not increment version, but records audit
        old_version = violation.version
        violation.touch("toucher")
        # Note: touch on violation does not increment version, only audit
        assert violation.version == old_version
        trail = violation.audit_trail()
        assert trail[-1]["action"] == "TOUCH"

    def test_resolve(self, violation):
        resolved = violation.resolve("admin", "Override reason")
        assert resolved.override_granted is True
        assert resolved.override_by == "admin"
        assert resolved.override_reason == "Override reason"
        assert resolved.version == violation.version + 1
        trail = resolved.audit_trail()
        assert trail[-1]["action"] == "RESOLVE"
        assert trail[-1]["details"]["reason"] == "Override reason"

    def test_resolve_already_overridden_raises(self, violation):
        resolved = violation.resolve("admin", "test")
        with pytest.raises(ValueError, match="Already overridden"):
            resolved.resolve("admin2", "again")


# ============================================================================
# TESTS FOR TimeIrreversibilityValidator
# ============================================================================

class TestTimeIrreversibilityValidator:
    def test_validate_effective_date_valid(self, boundary, fixed_now):
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now,
            current_period=boundary,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violation is None

    def test_validate_effective_date_closed_period(self, fixed_now):
        boundary = TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Closed",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=30),
            end_date=fixed_now - timedelta(days=1),
            is_closed=True,
            is_locked=False,
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now - timedelta(days=5),
                current_period=boundary,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CATASTROPHIC
        assert violation.is_blocked is True

    def test_validate_effective_date_locked_period(self, fixed_now):
        boundary = TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Locked",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=30),
            end_date=fixed_now + timedelta(days=30),
            is_closed=False,
            is_locked=True,
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now,
                current_period=boundary,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CRITICAL
        assert violation.is_blocked is True

    def test_validate_effective_date_backdate_exceeds_limit(self, boundary, fixed_now):
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now - timedelta(days=20),
                current_period=boundary,
                max_backdate_days=10,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.backdate_days == 20
        assert violation.severity == TimeIrreversibilityViolationSeverity.CRITICAL
        assert violation.is_blocked is True

    def test_validate_effective_date_backdate_within_tolerance(self, fixed_now):
        boundary = TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Open",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=2),
            end_date=fixed_now + timedelta(days=30),
            is_closed=False,
            is_locked=False,
        )
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now - timedelta(days=1),
            current_period=boundary,
            max_backdate_days=10,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violation is None

    def test_validate_effective_date_future_posting_blocked(self, boundary, fixed_now):
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now + timedelta(days=10),
                current_period=boundary,
                transaction_id=uuid.uuid4(),
                allow_future_posting=False,
            )
        # We allow, but violation is created as warning (not blocked)
        assert is_valid is True
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.MEDIUM
        assert violation.is_blocked is False

    def test_validate_effective_date_future_posting_allowed(self, boundary, fixed_now):
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now + timedelta(days=10),
            current_period=boundary,
            transaction_id=uuid.uuid4(),
            allow_future_posting=True,
        )
        assert is_valid is True
        assert violation is None

    def test_validate_effective_date_last_transaction_backdate(self, boundary, fixed_now):
        last_date = fixed_now - timedelta(days=2)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now - timedelta(days=10),
                current_period=boundary,
                last_transaction_date=last_date,
                max_backdate_days=5,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert violation is not None
        assert violation.backdate_days == 8  # 10 - 2
        assert violation.severity == TimeIrreversibilityViolationSeverity.CRITICAL

    def test_validate_effective_date_last_transaction_within_tolerance(self, boundary, fixed_now):
        last_date = fixed_now - timedelta(days=2)
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now - timedelta(days=3),
            current_period=boundary,
            last_transaction_date=last_date,
            max_backdate_days=10,
            transaction_id=uuid.uuid4(),
        )
        # backdate = 1 day (3-2) <= tolerance (TIMEZONE_TOLERANCE_DAYS=1) -> not blocked, valid
        assert is_valid is True
        assert violation is None

    def test_validate_chronological_order_valid(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=3),
            posting_date=fixed_now - timedelta(days=2),
            approval_date=fixed_now - timedelta(days=1),
            settlement_date=fixed_now,
            created_at=fixed_now - timedelta(days=4),
            created_by="tester",
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
                timestamp=ts,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is True
        assert violations == []

    def test_validate_chronological_order_invalid(self, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now,
            posting_date=fixed_now - timedelta(days=1),
            approval_date=fixed_now - timedelta(days=2),
            settlement_date=fixed_now + timedelta(days=1),
            created_at=fixed_now - timedelta(days=3),
            created_by="tester",
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
                timestamp=ts,
                transaction_id=uuid.uuid4(),
            )
        assert is_valid is False
        assert len(violations) > 0
        # Check that each violation is an instance of TimeIrreversibilityViolation
        assert all(isinstance(v, TimeIrreversibilityViolation) for v in violations)

    def test_calc_backdate(self):
        ref = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        eff = datetime(2026, 1, 5, 12, 0, 0, tzinfo=UTC)
        assert TimeIrreversibilityValidator._calc_backdate(eff, ref) == 5
        # eff after ref -> 0
        eff2 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert TimeIrreversibilityValidator._calc_backdate(eff2, ref) == 0
        # naive vs aware
        naive = eff.replace(tzinfo=None)
        assert TimeIrreversibilityValidator._calc_backdate(naive, ref) == 5

    def test_create_violation(self, fixed_now):
        violation = TimeIrreversibilityValidator._create_violation(
            transaction_id=uuid.uuid4(),
            attempted_date=fixed_now - timedelta(days=10),
            period_start=fixed_now - timedelta(days=15),
            period_end=fixed_now + timedelta(days=15),
            last_date=fixed_now - timedelta(days=5),
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.HIGH,
            message="test",
            user_id="user123",
            module="test_module",
            is_blocked=True,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        assert isinstance(violation, TimeIrreversibilityViolation)
        assert violation.transaction_id is not None
        assert violation.backdate_days == 10
        assert violation.severity == TimeIrreversibilityViolationSeverity.HIGH
        assert violation.is_blocked is True

    def test_log_violation(self, violation, caplog):
        import logging
        caplog.set_level(logging.WARNING)
        TimeIrreversibilityValidator._log_violation(violation)
        assert "Time irreversibility" in caplog.text

    def test_notify_constitution(self, violation):
        with patch("axioms.time_irreversibility.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            TimeIrreversibilityValidator._notify_constitution(violation)
            mock_law.check_violation.assert_called_once()


# ============================================================================
# TESTS FOR TimeIrreversibilityAxiom
# ============================================================================

class TestTimeIrreversibilityAxiom:
    def test_singleton(self):
        a1 = TimeIrreversibilityAxiom()
        a2 = TimeIrreversibilityAxiom()
        assert a1 is a2

    def test_save_and_get_time_boundary(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        retrieved = axiom.get_time_boundary(boundary.period_id)
        assert retrieved is not None
        assert retrieved.period_id == boundary.period_id

    def test_get_all_time_boundaries(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        boundaries = axiom.get_all_time_boundaries()
        assert len(boundaries) >= 1
        assert any(b.period_id == boundary.period_id for b in boundaries)

    def test_delete_time_boundary(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        result = axiom.delete_time_boundary(boundary.period_id)
        assert result is True
        assert axiom.get_time_boundary(boundary.period_id) is None

    def test_delete_time_boundary_not_found(self, axiom):
        result = axiom.delete_time_boundary(uuid.uuid4())
        assert result is False

    def test_save_and_get_transaction_timestamp(self, axiom, timestamp):
        axiom.save_transaction_timestamp(timestamp)
        retrieved = axiom.get_transaction_timestamp(timestamp.transaction_id)
        assert retrieved is not None
        assert retrieved.transaction_id == timestamp.transaction_id

    def test_delete_transaction_timestamp(self, axiom, timestamp):
        axiom.save_transaction_timestamp(timestamp)
        result = axiom.delete_transaction_timestamp(timestamp.transaction_id)
        assert result is True
        assert axiom.get_transaction_timestamp(timestamp.transaction_id) is None

    def test_save_violation(self, axiom, violation):
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) == 1
        assert violations[0].violation_id == violation.violation_id

    def test_get_violations_filter(self, axiom, violation):
        # Add multiple violations with different severities
        v1 = violation
        v2 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=None,
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.LOW,
            message="low",
            user_id=None,
            module="test",
            detected_at=FIXED_NOW,
            is_blocked=False,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        v3 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=None,
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.CRITICAL,
            message="critical",
            user_id=None,
            module="test",
            detected_at=FIXED_NOW,
            is_blocked=True,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        axiom.save_violation(v3)

        # min_severity HIGH -> only v1 and v3 (HIGH and CRITICAL)
        result = axiom.get_violations(min_severity=TimeIrreversibilityViolationSeverity.HIGH)
        assert len(result) == 2
        assert all(v.severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value for v in result)

        # only_blocked=True -> only v1 and v3 (both blocked)
        result_blocked = axiom.get_violations(only_blocked=True)
        assert len(result_blocked) == 2
        assert all(v.is_blocked for v in result_blocked)

        # only_blocked=False -> only v2
        result_not_blocked = axiom.get_violations(only_blocked=False)
        assert len(result_not_blocked) == 1
        assert result_not_blocked[0].violation_id == v2.violation_id

        # filter by transaction_id
        result_tx = axiom.get_violations(transaction_id=v1.transaction_id)
        assert len(result_tx) == 1
        assert result_tx[0].violation_id == v1.violation_id

    def test_register_time_boundary(self, axiom, boundary):
        axiom.register_time_boundary(boundary)
        assert axiom.get_time_boundary(boundary.period_id) is not None

    def test_get_current_period(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
        current = axiom.get_current_period(fixed_now)
        assert current is not None
        assert current.period_id == boundary.period_id

    def test_get_current_period_no_match(self, axiom, fixed_now):
        boundary = TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Old",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=20),
            end_date=fixed_now - timedelta(days=10),
            is_closed=False,
            is_locked=False,
        )
        axiom.save_time_boundary(boundary)
        current = axiom.get_current_period(fixed_now)
        assert current is None

    def test_record_transaction_timestamp(self, axiom, timestamp):
        axiom.record_transaction_timestamp(timestamp)
        retrieved = axiom.get_transaction_timestamp(timestamp.transaction_id)
        assert retrieved is not None
        # Also updates last_transaction_date_by_entity
        last = axiom.get_last_transaction_date()
        assert last == timestamp.effective_date

    def test_get_last_transaction_date(self, axiom, timestamp):
        assert axiom.get_last_transaction_date() is None
        axiom.record_transaction_timestamp(timestamp)
        last = axiom.get_last_transaction_date()
        assert last == timestamp.effective_date
        # with legal_entity_id
        le_id = uuid.uuid4()
        key = str(le_id)
        axiom._last_transaction_date_by_entity[key] = FIXED_NOW
        assert axiom.get_last_transaction_date(le_id) == FIXED_NOW

    def test_enforce_effective_date_valid(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
        is_valid, violation = axiom.enforce_effective_date(
            effective_date=fixed_now,
            period_id=boundary.period_id,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violation is None

    def test_enforce_effective_date_backdate_override(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
        # This will be blocked but we allow override
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = axiom.enforce_effective_date(
                effective_date=fixed_now - timedelta(days=20),
                period_id=boundary.period_id,
                transaction_id=uuid.uuid4(),
                max_backdate_days=10,
                raise_on_violation=False,
                allow_override=True,
                override_by="admin",
                override_reason="Need backdate",
            )
        assert is_valid is True
        # Violation should be created but with override granted
        assert violation is not None
        assert violation.override_granted is True
        assert violation.override_by == "admin"
        assert violation.override_reason == "Need backdate"

    def test_enforce_effective_date_no_period_raises(self, axiom, fixed_now):
        with pytest.raises(TimeIrreversibilityViolationError) as exc:
            axiom.enforce_effective_date(
                effective_date=fixed_now,
                period_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )
        assert "No period" in str(exc.value)

    def test_enforce_effective_date_raises_on_critical(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            with pytest.raises(TimeIrreversibilityViolationError):
                axiom.enforce_effective_date(
                    effective_date=fixed_now - timedelta(days=20),
                    period_id=boundary.period_id,
                    transaction_id=uuid.uuid4(),
                    max_backdate_days=10,
                    raise_on_violation=True,
                    allow_override=False,
                )

    def test_enforce_chronological_order_valid(self, axiom, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=3),
            posting_date=fixed_now - timedelta(days=2),
            approval_date=fixed_now - timedelta(days=1),
            settlement_date=fixed_now,
            created_at=fixed_now - timedelta(days=4),
            created_by="tester",
        )
        is_valid, violations = axiom.enforce_chronological_order(
            timestamp=ts,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violations == []

    def test_enforce_chronological_order_raises(self, axiom, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now,
            posting_date=fixed_now - timedelta(days=1),
            approval_date=fixed_now - timedelta(days=2),
            settlement_date=fixed_now + timedelta(days=1),
            created_at=fixed_now - timedelta(days=3),
            created_by="tester",
        )
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            with pytest.raises(TimeIrreversibilityViolationError):
                axiom.enforce_chronological_order(
                    timestamp=ts,
                    transaction_id=uuid.uuid4(),
                    raise_on_violation=True,
                )

    def test_grant_override(self, axiom, violation):
        axiom.save_violation(violation)
        # Call _grant_override directly
        resolved = axiom._grant_override(violation, "admin", "reason")
        assert resolved.override_granted is True
        assert resolved.override_by == "admin"
        # Check stored violation updated
        stored = axiom._violation_history[0]
        assert stored.override_granted is True

    def test_get_statistics(self, axiom, boundary, timestamp, violation):
        axiom.save_time_boundary(boundary)
        axiom.save_transaction_timestamp(timestamp)
        axiom.save_violation(violation)
        stats = axiom.get_statistics()
        assert stats["total_time_boundaries"] >= 1
        assert stats["total_transaction_timestamps"] >= 1
        assert stats["total_violations"] >= 1
        assert stats["blocked_count"] >= 1
        assert stats["overridden_count"] == 0
        assert "by_severity" in stats
        assert "avg_backdate_days" in stats

    def test_reset(self, axiom, boundary, timestamp):
        axiom.save_time_boundary(boundary)
        axiom.save_transaction_timestamp(timestamp)
        axiom.reset()
        assert len(axiom._time_boundaries) == 0
        assert len(axiom._transaction_timestamps) == 0
        assert len(axiom._violation_history) == 0


# ============================================================================
# TESTS FOR HELPER FUNCTIONS
# ============================================================================

class TestHelperFunctions:
    def test_create_time_boundary(self, fixed_now):
        period_id = uuid.uuid4()
        start = fixed_now - timedelta(days=10)
        end = fixed_now + timedelta(days=10)
        boundary = create_time_boundary(
            period_id=period_id,
            period_name="Test",
            fiscal_year=2026,
            period_number=1,
            start_date=start,
            end_date=end,
            is_closed=True,
            closed_at=fixed_now,
            closed_by="admin",
            locked_at=fixed_now,
            locked_by="admin2",
        )
        assert boundary.period_id == period_id
        assert boundary.period_name == "Test"
        assert boundary.is_closed is True
        assert boundary.closed_at == fixed_now
        assert boundary.closed_by == "admin"
        assert boundary.locked_by == "admin2"

    def test_create_transaction_timestamp(self, fixed_now):
        tx_id = uuid.uuid4()
        eff = fixed_now - timedelta(days=1)
        ts = create_transaction_timestamp(
            transaction_id=tx_id,
            effective_date=eff,
            posting_date=fixed_now,
            approval_date=fixed_now + timedelta(days=1),
            settlement_date=fixed_now + timedelta(days=2),
            created_by="creator",
        )
        assert ts.transaction_id == tx_id
        assert ts.effective_date == eff
        assert ts.posting_date == fixed_now
        assert ts.approval_date == fixed_now + timedelta(days=1)
        assert ts.created_by == "creator"
        assert ts.created_at == fixed_now

    def test_create_transaction_timestamp_defaults(self, fixed_now):
        tx_id = uuid.uuid4()
        eff = fixed_now - timedelta(days=1)
        ts = create_transaction_timestamp(
            transaction_id=tx_id,
            effective_date=eff,
        )
        assert ts.posting_date == fixed_now
        assert ts.created_by == "system"

    def test_get_time_irreversibility_axiom_singleton(self):
        a1 = get_time_irreversibility_axiom()
        a2 = get_time_irreversibility_axiom()
        assert a1 is a2
        assert isinstance(a1, TimeIrreversibilityAxiom)
