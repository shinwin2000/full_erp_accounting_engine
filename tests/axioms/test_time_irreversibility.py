#!/usr/bin/env python3
"""
tests/unit/test_time_irreversibility.py
Test untuk axioms/time_irreversibility.py
Mencakup: TimeBoundary, TransactionTimestamp, TimeIrreversibilityViolation,
TimeIrreversibilityValidator, TimeIrreversibilityAxiom, helper functions

FIXES:
- Semua datetime.now(UTC) diganti dengan FIXED_NOW untuk menghilangkan flaky.
- Test kosong 'test_validate_requires_timezone' dihapus/diganti dengan assertion.
- Duplikasi struktural dihilangkan dengan menggunakan parametrize untuk method umum.
- Semua test memiliki assertion yang bermakna.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from axioms.time_irreversibility import (
    TimeBoundary,
    TimeIrreversibilityAxiom,
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
# FIXED DATETIME (untuk menghindari flaky tests)
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


# ============================================================================
# TESTS FOR TimeBoundary (specific methods)
# ============================================================================

class TestTimeBoundarySpecific:
    def test_validate_start_before_end(self, fixed_now):
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

    def test_contains_checks_date(self, boundary, fixed_now):
        assert boundary.contains(fixed_now)
        assert not boundary.contains(fixed_now - timedelta(days=20))
        assert not boundary.contains(fixed_now + timedelta(days=20))

    def test_is_modifiable(self, boundary):
        assert boundary.is_modifiable()
        closed = boundary.update("admin", is_closed=True)
        assert not closed.is_modifiable()
        locked = boundary.update("admin", is_locked=True)
        assert not locked.is_modifiable()

    def test_lock_already_locked_returns_self(self, boundary):
        locked = boundary.lock("admin", "test")
        again = locked.lock("admin2", "again")
        assert again is locked

    def test_unlock_already_unlocked_returns_self(self, boundary):
        unlocked = boundary.unlock("admin")
        assert unlocked is boundary

    def test_restore_not_deleted_raises(self, boundary):
        with pytest.raises(ValueError, match="Not deleted"):
            boundary.restore("admin")

    def test_update_creates_new_version(self, boundary):
        updated = boundary.update("admin", period_name="Updated Period")
        assert updated.period_name == "Updated Period"
        assert updated.version == boundary.version + 1


# ============================================================================
# TESTS FOR TransactionTimestamp (specific methods)
# ============================================================================

class TestTransactionTimestampSpecific:
    def test_update_raises(self, timestamp):
        with pytest.raises(AttributeError):
            timestamp.update("admin", effective_date=FIXED_NOW)

    def test_restore_not_deleted_raises(self, timestamp):
        with pytest.raises(ValueError, match="Not deleted"):
            timestamp.restore("admin")

    def test_get_time_difference(self, timestamp):
        diff = timestamp.get_time_difference(
            TransactionTimeContext.EFFECTIVE,
            TransactionTimeContext.POSTING
        )
        # effective = now-1, posting = now => diff = -1 day
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
        assert is_valid
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
        assert not is_valid
        assert any("Effective" in v for v in violations)

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
        # default reference = now, but we mock to fixed to avoid flaky
        with patch("axioms.time_irreversibility.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            assert ts.get_backdate_days() == 10


# ============================================================================
# TESTS FOR TimeIrreversibilityViolation (specific methods)
# ============================================================================

class TestTimeIrreversibilityViolationSpecific:
    def test_update_raises(self, violation):
        with pytest.raises(AttributeError):
            violation.update("admin", message="new")

    def test_delete_raises(self, violation):
        with pytest.raises(AttributeError):
            violation.delete("admin")

    def test_restore_raises(self, violation):
        with pytest.raises(AttributeError):
            violation.restore("admin")

    def test_resolve_grants_override(self, violation):
        resolved = violation.resolve("admin", "Override reason")
        assert resolved.override_granted
        assert resolved.override_by == "admin"
        assert resolved.override_reason == "Override reason"
        assert resolved.version == violation.version + 1

    def test_resolve_already_overridden_raises(self, violation):
        resolved = violation.resolve("admin", "test")
        with pytest.raises(ValueError, match="Already overridden"):
            resolved.resolve("admin2", "again")


# ============================================================================
# COMMON ENTITY TESTS (parametrized untuk menghilangkan duplikasi)
# ============================================================================

# Parameter untuk entity test: (fixture_name, class_name, is_supports_update, is_supports_delete)
ENTITY_PARAMS = [
    ("boundary", "TimeBoundary", True, True),
    ("timestamp", "TransactionTimestamp", False, True),
    ("violation", "TimeIrreversibilityViolation", False, False),
]


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_delete(entity_fixture, cls_name, supports_update, supports_delete, request):
    if not supports_delete:
        pytest.skip(f"{cls_name} does not support delete")
    entity = request.getfixturevalue(entity_fixture)
    deleted = entity.delete("admin", "test")
    assert deleted.deleted_at is not None
    assert deleted.deleted_by == "admin"
    assert deleted.version == entity.version + 1


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_restore(entity_fixture, cls_name, supports_update, supports_delete, request):
    if not supports_delete:
        pytest.skip(f"{cls_name} does not support delete/restore")
    entity = request.getfixturevalue(entity_fixture)
    deleted = entity.delete("admin", "test")
    restored = deleted.restore("admin")
    assert restored.deleted_at is None
    assert restored.deleted_by is None
    assert restored.version == deleted.version + 1


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_activate(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    activated = entity.activate("admin")
    # activate returns self (or new instance?) But in code, activate returns self.
    assert activated is entity or activated == entity


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_deactivate(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    deactivated = entity.deactivate("admin")
    assert deactivated is entity


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_lock(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    locked = entity.lock("admin", "test")
    if hasattr(locked, "is_locked"):
        assert locked.is_locked
        assert locked.locked_by == "admin"
        assert locked.locked_at is not None
        assert locked.version == entity.version + 1
    else:
        # violation/timestamp lock returns self
        assert locked is entity


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_unlock(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    if hasattr(entity, "is_locked"):
        locked = entity.lock("admin", "test")
        unlocked = locked.unlock("admin")
        assert not unlocked.is_locked
        assert unlocked.locked_at is None
        assert unlocked.locked_by is None
        assert unlocked.version == locked.version + 1
    else:
        # violation/timestamp unlock returns self
        unlocked = entity.unlock("admin")
        assert unlocked is entity


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_validate(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    result = entity.validate()
    assert result["is_valid"]
    assert "version" in result
    # verify hash mismatch
    original_hash = entity.cryptographic_hash
    object.__setattr__(entity, "cryptographic_hash", "fake")
    result2 = entity.validate()
    assert not result2["is_valid"]
    assert "Hash mismatch" in result2["errors"]
    # restore hash untuk test lain
    object.__setattr__(entity, "cryptographic_hash", original_hash)


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_to_dict(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    d = entity.to_dict()
    assert "version" in d
    assert "deleted_at" in d
    assert "deleted_by" in d


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_from_dict(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    d = entity.to_dict()
    # Determine class
    if cls_name == "TimeBoundary":
        reconstructed = TimeBoundary.from_dict(d)
    elif cls_name == "TransactionTimestamp":
        reconstructed = TransactionTimestamp.from_dict(d)
    elif cls_name == "TimeIrreversibilityViolation":
        reconstructed = TimeIrreversibilityViolation.from_dict(d)
    else:
        pytest.fail(f"Unknown class {cls_name}")
    # Check ID field (different names)
    if hasattr(entity, "period_id"):
        assert reconstructed.period_id == entity.period_id
    elif hasattr(entity, "transaction_id"):
        assert reconstructed.transaction_id == entity.transaction_id
    elif hasattr(entity, "violation_id"):
        assert reconstructed.violation_id == entity.violation_id
    assert reconstructed.version == entity.version


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_clone(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    cloned = entity.clone()
    assert cloned is not entity
    assert cloned.version == 1
    # ID berbeda
    if hasattr(entity, "period_id"):
        assert cloned.period_id != entity.period_id
    elif hasattr(entity, "transaction_id"):
        assert cloned.transaction_id != entity.transaction_id
    elif hasattr(entity, "violation_id"):
        assert cloned.violation_id != entity.violation_id


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_snapshot(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    snap = entity.snapshot()
    assert "version" in snap
    assert "timestamp" in snap
    if hasattr(entity, "period_id"):
        assert snap["period_id"] == str(entity.period_id)
    elif hasattr(entity, "transaction_id"):
        assert snap["transaction_id"] == str(entity.transaction_id)
    elif hasattr(entity, "violation_id"):
        assert snap["violation_id"] == str(entity.violation_id)


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_get_version(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    assert entity.get_version() == entity.version


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_audit_trail(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    trail = entity.audit_trail()
    assert len(trail) >= 1
    # touch
    entity.touch("toucher")
    trail2 = entity.audit_trail()
    assert len(trail2) >= len(trail) + 1
    assert trail2[-1]["action"] == "TOUCH"


@pytest.mark.parametrize("entity_fixture,cls_name,supports_update,supports_delete", ENTITY_PARAMS)
def test_entity_touch(entity_fixture, cls_name, supports_update, supports_delete, request):
    entity = request.getfixturevalue(entity_fixture)
    old_version = entity.version
    touched = entity.touch("toucher")
    # Some entities return a new instance with version+1
    if touched is not entity:
        assert touched.version == old_version + 1
        assert touched is not entity
    else:
        # violation.touch does not increment version? Actually violation.touch increments? It records audit but not version.
        # We can just check that audit trail recorded.
        trail = entity.audit_trail()
        assert trail[-1]["action"] == "TOUCH"


# ============================================================================
# TESTS FOR TimeIrreversibilityValidator
# ============================================================================

class TestTimeIrreversibilityValidator:
    @pytest.fixture
    def boundary_open(self, fixed_now):
        return TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Open",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=30),
            end_date=fixed_now + timedelta(days=30),
            is_closed=False,
            is_locked=False,
        )

    def test_validate_effective_date_valid(self, boundary_open, fixed_now):
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now,
            current_period=boundary_open,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid
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
        assert not is_valid
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CATASTROPHIC

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
        assert not is_valid
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.CRITICAL

    def test_validate_effective_date_backdate_exceeds_limit(self, boundary_open, fixed_now):
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now - timedelta(days=20),
                current_period=boundary_open,
                max_backdate_days=10,
                transaction_id=uuid.uuid4(),
            )
        assert not is_valid
        assert violation is not None
        assert violation.backdate_days == 20

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
        assert is_valid
        assert violation is None

    def test_validate_effective_date_future_posting_blocked(self, boundary_open, fixed_now):
        is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
            effective_date=fixed_now + timedelta(days=30),
            current_period=boundary_open,
            transaction_id=uuid.uuid4(),
            allow_future_posting=False,
        )
        assert is_valid  # Not blocked, just warning
        assert violation is not None
        assert violation.severity == TimeIrreversibilityViolationSeverity.MEDIUM

    def test_validate_effective_date_last_transaction_backdate(self, boundary_open, fixed_now):
        last_date = fixed_now - timedelta(days=2)
        with patch("axioms.time_irreversibility.TimeIrreversibilityValidator._notify_constitution"):
            is_valid, violation = TimeIrreversibilityValidator.validate_effective_date(
                effective_date=fixed_now - timedelta(days=10),
                current_period=boundary_open,
                last_transaction_date=last_date,
                max_backdate_days=5,
                transaction_id=uuid.uuid4(),
            )
        assert not is_valid
        assert violation is not None
        assert violation.backdate_days == 8  # 10 - 2

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
        is_valid, violations = TimeIrreversibilityValidator.validate_chronological_order(
            timestamp=ts,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid
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
        assert not is_valid
        assert len(violations) > 0


# ============================================================================
# TESTS FOR TimeIrreversibilityAxiom
# ============================================================================

class TestTimeIrreversibilityAxiom:
    @pytest.fixture
    def axiom(self):
        # Reset singleton for clean state
        instance = TimeIrreversibilityAxiom()
        instance.reset()
        return instance

    @pytest.fixture
    def boundary(self, fixed_now):
        return TimeBoundary(
            period_id=uuid.uuid4(),
            period_name="Test",
            fiscal_year=2026,
            period_number=1,
            start_date=fixed_now - timedelta(days=15),
            end_date=fixed_now + timedelta(days=15),
            is_closed=False,
            is_locked=False,
        )

    @pytest.fixture
    def timestamp(self, fixed_now):
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
    def violation(self, fixed_now):
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

    def test_singleton(self):
        axiom1 = TimeIrreversibilityAxiom()
        axiom2 = TimeIrreversibilityAxiom()
        assert axiom1 is axiom2

    def test_save_and_get_time_boundary(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        retrieved = axiom.get_time_boundary(boundary.period_id)
        assert retrieved is not None
        assert retrieved.period_id == boundary.period_id

    def test_get_all_time_boundaries(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        boundaries = axiom.get_all_time_boundaries()
        assert len(boundaries) >= 1

    def test_delete_time_boundary(self, axiom, boundary):
        axiom.save_time_boundary(boundary)
        result = axiom.delete_time_boundary(boundary.period_id)
        assert result
        assert axiom.get_time_boundary(boundary.period_id) is None

    def test_save_and_get_transaction_timestamp(self, axiom, timestamp):
        axiom.save_transaction_timestamp(timestamp)
        retrieved = axiom.get_transaction_timestamp(timestamp.transaction_id)
        assert retrieved is not None
        assert retrieved.transaction_id == timestamp.transaction_id

    def test_delete_transaction_timestamp(self, axiom, timestamp):
        axiom.save_transaction_timestamp(timestamp)
        result = axiom.delete_transaction_timestamp(timestamp.transaction_id)
        assert result
        assert axiom.get_transaction_timestamp(timestamp.transaction_id) is None

    def test_save_and_get_violations(self, axiom, violation):
        axiom.save_violation(violation)
        violations = axiom.get_violations()
        assert len(violations) >= 1
        found = next((v for v in violations if v.violation_id == violation.violation_id), None)
        assert found is not None

    def test_get_violations_filter_by_severity(self, axiom):
        v1 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=FIXED_NOW - timedelta(days=5),
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.LOW,
            message="Low",
            user_id=None,
            module="test",
            detected_at=FIXED_NOW,
            is_blocked=False,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        v2 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=FIXED_NOW - timedelta(days=5),
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.CRITICAL,
            message="Critical",
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
        result = axiom.get_violations(min_severity=TimeIrreversibilityViolationSeverity.HIGH)
        assert all(v.severity.value >= TimeIrreversibilityViolationSeverity.HIGH.value for v in result)

    def test_get_violations_filter_blocked(self, axiom):
        v1 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=FIXED_NOW - timedelta(days=5),
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.MEDIUM,
            message="Blocked",
            user_id=None,
            module="test",
            detected_at=FIXED_NOW,
            is_blocked=True,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        v2 = TimeIrreversibilityViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            attempted_effective_date=FIXED_NOW - timedelta(days=10),
            current_period_start=FIXED_NOW - timedelta(days=15),
            current_period_end=FIXED_NOW + timedelta(days=15),
            last_transaction_date=FIXED_NOW - timedelta(days=5),
            period_status="OPEN",
            backdate_days=10,
            severity=TimeIrreversibilityViolationSeverity.LOW,
            message="Not blocked",
            user_id=None,
            module="test",
            detected_at=FIXED_NOW,
            is_blocked=False,
            override_granted=False,
            override_by=None,
            override_reason=None,
        )
        axiom.save_violation(v1)
        axiom.save_violation(v2)
        result = axiom.get_violations(only_blocked=True)
        assert all(v.is_blocked for v in result)

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

    def test_get_last_transaction_date(self, axiom, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now - timedelta(days=1),
            posting_date=fixed_now,
            approval_date=None,
            settlement_date=None,
            created_at=fixed_now - timedelta(days=2),
            created_by="tester",
        )
        axiom.record_transaction_timestamp(ts)
        last_date = axiom.get_last_transaction_date()
        assert last_date is not None
        assert last_date == fixed_now - timedelta(days=1)

    def test_enforce_effective_date_valid(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
        is_valid, violation = axiom.enforce_effective_date(
            effective_date=fixed_now,
            period_id=boundary.period_id,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid
        assert violation is None

    def test_enforce_effective_date_backdate_with_override(self, axiom, boundary, fixed_now):
        axiom.save_time_boundary(boundary)
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
        assert is_valid
        if violation:
            assert violation.override_granted

    def test_enforce_effective_date_no_period_raises(self, axiom, fixed_now):
        with pytest.raises(TimeIrreversibilityViolationError):
            axiom.enforce_effective_date(
                effective_date=fixed_now,
                period_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
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
        assert is_valid
        assert violations == []

    def test_enforce_chronological_order_invalid_raises(self, axiom, fixed_now):
        ts = TransactionTimestamp(
            transaction_id=uuid.uuid4(),
            effective_date=fixed_now,
            posting_date=fixed_now - timedelta(days=1),
            approval_date=fixed_now - timedelta(days=2),
            settlement_date=fixed_now + timedelta(days=1),
            created_at=fixed_now - timedelta(days=3),
            created_by="tester",
        )
        with pytest.raises(TimeIrreversibilityViolationError):
            axiom.enforce_chronological_order(
                timestamp=ts,
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )

    def test_get_statistics(self, axiom, boundary, timestamp):
        axiom.save_time_boundary(boundary)
        axiom.save_transaction_timestamp(timestamp)
        stats = axiom.get_statistics()
        assert stats["total_time_boundaries"] >= 1
        assert stats["total_transaction_timestamps"] >= 1
        assert "total_violations" in stats
        assert "blocked_count" in stats
        assert "overridden_count" in stats

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
            locked_by="admin",
        )
        assert boundary.period_id == period_id
        assert boundary.period_name == "Test"
        assert boundary.is_closed
        assert boundary.closed_by == "admin"
        assert boundary.locked_by == "admin"

    def test_create_transaction_timestamp(self, fixed_now):
        transaction_id = uuid.uuid4()
        eff = fixed_now - timedelta(days=1)
        timestamp = create_transaction_timestamp(
            transaction_id=transaction_id,
            effective_date=eff,
            posting_date=fixed_now,
            approval_date=fixed_now + timedelta(days=1),
            settlement_date=fixed_now + timedelta(days=2),
            created_by="admin",
        )
        assert timestamp.transaction_id == transaction_id
        assert timestamp.effective_date == eff
        assert timestamp.posting_date == fixed_now
        assert timestamp.approval_date is not None
        assert timestamp.created_by == "admin"

    def test_create_transaction_timestamp_posting_default(self, fixed_now):
        transaction_id = uuid.uuid4()
        eff = fixed_now - timedelta(days=1)
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
