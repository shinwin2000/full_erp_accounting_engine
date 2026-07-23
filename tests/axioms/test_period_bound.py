#!/usr/bin/env python3
"""
tests/unit/test_period_bound.py
Comprehensive tests for axioms/period_bound.py

Covers:
- All enums and exceptions
- All data classes: AccountingPeriod, FiscalYearDefinition, PeriodBoundViolation
- PeriodBoundValidator (all methods)
- PeriodBoundAxiom (all repository and business methods)
- Helper functions
- Edge cases and negative paths
- No flaky tests (mocked datetime)
- No duplicate test code (parametrized where appropriate)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from axioms.period_bound import (
    AccountingPeriod,
    FiscalYearDefinition,
    PeriodBoundAxiom,
    PeriodBoundError,
    PeriodBoundValidator,
    PeriodBoundViolation,
    PeriodBoundViolationError,
    PeriodBoundViolationSeverity,
    PeriodClosedError,
    PeriodNotFoundError,
    PeriodStatus,
    PeriodType,
    create_accounting_period,
    generate_monthly_periods,
    generate_quarterly_periods,
    get_period_bound_axiom,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def fixed_now():
    """Return a fixed datetime for deterministic tests."""
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime(fixed_now):
    """Mock datetime.now and datetime.utcnow to return fixed_now for the module under test."""
    with patch("axioms.period_bound.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.utcnow.return_value = fixed_now
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        yield mock_dt


@pytest.fixture
def sample_period(fixed_now) -> AccountingPeriod:
    start = fixed_now - timedelta(days=15)
    end = fixed_now + timedelta(days=15)
    return AccountingPeriod(
        period_id=uuid.uuid4(),
        fiscal_year=2026,
        period_number=1,
        period_type=PeriodType.MONTHLY,
        start_date=start,
        end_date=end,
        status=PeriodStatus.OPEN,
        is_budget_period=False,
    )


@pytest.fixture
def sample_fiscal_year(fixed_now) -> FiscalYearDefinition:
    return FiscalYearDefinition(
        fiscal_year_id=uuid.uuid4(),
        legal_entity_id=uuid.uuid4(),
        year_name="FY2026",
        start_month=1,
        start_day=1,
    )


@pytest.fixture
def sample_violation(fixed_now) -> PeriodBoundViolation:
    return PeriodBoundViolation(
        violation_id=uuid.uuid4(),
        transaction_id=uuid.uuid4(),
        transaction_date=fixed_now,
        target_period_id=uuid.uuid4(),
        period_status="OPEN",
        attempted_operation="POST",
        severity=PeriodBoundViolationSeverity.MEDIUM,
        message="Test violation",
        was_blocked=False,
        user_id=uuid.uuid4(),
        module="journal",
        detected_at=fixed_now,
        override_granted=False,
        override_by=None,
    )


# =============================================================================
# Tests for Enums
# =============================================================================

class TestEnums:
    def test_period_status(self):
        assert PeriodStatus.FUTURE is not None
        assert PeriodStatus.OPEN is not None
        assert PeriodStatus.LOCKED is not None
        assert PeriodStatus.CLOSED is not None
        assert PeriodStatus.ARCHIVED is not None

    def test_period_type(self):
        assert PeriodType.MONTHLY is not None
        assert PeriodType.QUARTERLY is not None
        assert PeriodType.YEARLY is not None
        assert PeriodType.CUSTOM is not None

    def test_period_bound_violation_severity(self):
        assert PeriodBoundViolationSeverity.CATASTROPHIC.value == 100
        assert PeriodBoundViolationSeverity.CRITICAL.value == 80
        assert PeriodBoundViolationSeverity.HIGH.value == 60
        assert PeriodBoundViolationSeverity.MEDIUM.value == 40
        assert PeriodBoundViolationSeverity.LOW.value == 20
        assert PeriodBoundViolationSeverity.INFO.value == 0


# =============================================================================
# Tests for Exceptions
# =============================================================================

class TestExceptions:
    def test_period_bound_error(self):
        with pytest.raises(PeriodBoundError):
            raise PeriodBoundError("test")

    def test_period_not_found_error(self):
        with pytest.raises(PeriodNotFoundError):
            raise PeriodNotFoundError("not found")

    def test_period_closed_error(self):
        with pytest.raises(PeriodClosedError):
            raise PeriodClosedError("closed")

    def test_period_bound_violation_error(self):
        with pytest.raises(PeriodBoundViolationError) as exc:
            raise PeriodBoundViolationError(
                "violation",
                transaction_id=uuid.uuid4(),
                period_id=uuid.uuid4(),
                period_status="CLOSED",
                severity=PeriodBoundViolationSeverity.CRITICAL,
            )
        assert "violation" in str(exc.value)
        assert exc.value.severity == PeriodBoundViolationSeverity.CRITICAL


# =============================================================================
# Tests for AccountingPeriod
# =============================================================================

class TestAccountingPeriod:
    def test_create_valid(self, sample_period):
        assert sample_period.fiscal_year == 2026
        assert sample_period.period_number == 1
        assert sample_period.period_type == PeriodType.MONTHLY
        assert sample_period.status == PeriodStatus.OPEN
        assert sample_period.cryptographic_hash != ""
        assert sample_period.version == 1

    def test_validate_invalid_start_after_end(self):
        start = datetime(2026, 1, 15, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Start.*>= end"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=1,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
            )

    def test_validate_invalid_period_number(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        with pytest.raises(ValueError, match="Invalid period number"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=0,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
            )
        with pytest.raises(ValueError, match="Invalid period number"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=14,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
            )

    def test_validate_invalid_version(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        with pytest.raises(ValueError, match="Version must be >= 1"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=1,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
                version=0,
            )

    def test_ensure_hash_creates_hash(self, sample_period):
        assert sample_period.cryptographic_hash != ""

    def test_compute_hash_consistent(self, sample_period):
        h1 = sample_period.compute_hash()
        h2 = sample_period.compute_hash()
        assert h1 == h2

    def test_contains(self, sample_period):
        mid = sample_period.start_date + (sample_period.end_date - sample_period.start_date) / 2
        assert sample_period.contains(mid) is True
        before = sample_period.start_date - timedelta(days=1)
        assert sample_period.contains(before) is False
        after = sample_period.end_date + timedelta(days=1)
        assert sample_period.contains(after) is False

    def test_is_open_for_posting(self, sample_period):
        assert sample_period.is_open_for_posting() is True
        closed = sample_period.close("admin")
        assert closed.is_open_for_posting() is False
        # Budget period with allow_budget=True
        budget = sample_period.update("system", is_budget_period=True)
        assert budget.is_open_for_posting(allow_budget=True) is True
        assert budget.is_open_for_posting(allow_budget=False) is False

    def test_can_adjust(self, sample_period):
        assert sample_period.can_adjust() is True
        locked = sample_period.lock("admin", "test")
        assert locked.can_adjust() is True
        closed = sample_period.close("admin")
        assert closed.can_adjust() is False

    def test_can_read(self, sample_period):
        assert sample_period.can_read() is True
        future = sample_period.update("system", status=PeriodStatus.FUTURE)
        assert future.can_read() is False

    def test_close(self, sample_period):
        closed = sample_period.close("admin")
        assert closed.status == PeriodStatus.CLOSED
        assert closed.closed_at is not None
        assert closed.closed_by == "admin"
        assert closed.version == sample_period.version + 1
        # Already closed raises PeriodClosedError
        with pytest.raises(PeriodClosedError):
            closed.close("admin")

    def test_reopen(self, sample_period):
        closed = sample_period.close("admin")
        reopened = closed.reopen("admin", "correction")
        assert reopened.status == PeriodStatus.OPEN
        assert reopened.closed_at is None
        assert reopened.closed_by is None
        assert reopened.version == closed.version + 1
        # Reopen already open raises
        with pytest.raises(ValueError, match="already open"):
            sample_period.reopen("admin", "no")

    def test_lock(self, sample_period):
        locked = sample_period.lock("admin", "review")
        assert locked.status == PeriodStatus.LOCKED
        assert locked.locked_at is not None
        assert locked.locked_by == "admin"
        assert locked.version == sample_period.version + 1
        # Lock already locked returns self
        locked2 = locked.lock("admin", "again")
        assert locked2 is locked
        # Lock closed raises
        closed = sample_period.close("admin")
        with pytest.raises(ValueError, match="Cannot lock"):
            closed.lock("admin", "no")

    def test_unlock(self, sample_period):
        locked = sample_period.lock("admin", "review")
        unlocked = locked.unlock("admin")
        assert unlocked.status == PeriodStatus.OPEN
        assert unlocked.locked_at is None
        assert unlocked.locked_by is None
        assert unlocked.version == locked.version + 1
        # Unlock open raises
        with pytest.raises(ValueError, match="Cannot unlock"):
            sample_period.unlock("admin")

    def test_archive(self, sample_period):
        archived = sample_period.archive("admin")
        assert archived.status == PeriodStatus.ARCHIVED
        assert archived.version == sample_period.version + 1
        # Archive already archived returns self
        archived2 = archived.archive("admin")
        assert archived2 is archived

    def test_update(self, sample_period):
        updated = sample_period.update("admin", status=PeriodStatus.LOCKED, is_budget_period=True)
        assert updated.status == PeriodStatus.LOCKED
        assert updated.is_budget_period is True
        assert updated.version == sample_period.version + 1
        # Cannot update immutable fields
        updated2 = sample_period.update("admin", period_id=uuid.uuid4())
        assert updated2.period_id == sample_period.period_id

    def test_delete_and_restore(self, sample_period):
        deleted = sample_period.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == sample_period.version + 1
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1
        # Restore not deleted raises
        with pytest.raises(ValueError, match="Not deleted"):
            sample_period.restore("admin")

    def test_activate(self, sample_period):
        # Already open returns self
        assert sample_period.activate("admin") is sample_period
        future = sample_period.update("admin", status=PeriodStatus.FUTURE)
        activated = future.activate("admin")
        assert activated.status == PeriodStatus.OPEN
        assert activated.version == future.version + 1

    def test_deactivate(self, sample_period):
        # Future status returns self
        future = sample_period.update("admin", status=PeriodStatus.FUTURE)
        assert future.deactivate("admin") is future
        deactivated = sample_period.deactivate("admin", "reason")
        assert deactivated.status == PeriodStatus.FUTURE
        assert deactivated.version == sample_period.version + 1

    def test_validate(self, sample_period):
        result = sample_period.validate()
        assert result["is_valid"] is True
        # Tamper hash
        object.__setattr__(sample_period, "cryptographic_hash", "fake")
        result2 = sample_period.validate()
        assert result2["is_valid"] is False
        assert "Hash mismatch" in result2["errors"]

    def test_to_dict(self, sample_period):
        d = sample_period.to_dict()
        assert d["period_id"] == str(sample_period.period_id)
        assert d["fiscal_year"] == 2026
        assert d["period_type"] == "MONTHLY"
        assert d["status"] == "OPEN"

    def test_from_dict_roundtrip(self, sample_period):
        d = sample_period.to_dict()
        reconstructed = AccountingPeriod.from_dict(d)
        assert reconstructed.period_id == sample_period.period_id
        assert reconstructed.fiscal_year == sample_period.fiscal_year
        assert reconstructed.period_number == sample_period.period_number
        assert reconstructed.status == sample_period.status
        assert reconstructed.version == sample_period.version

    def test_clone(self, sample_period):
        cloned = sample_period.clone()
        assert cloned.period_id != sample_period.period_id
        assert cloned.fiscal_year == sample_period.fiscal_year
        assert cloned.period_number == sample_period.period_number
        assert cloned.status == PeriodStatus.FUTURE
        assert cloned.version == 1

    def test_snapshot(self, sample_period):
        snap = sample_period.snapshot()
        assert snap["version"] == sample_period.version
        assert snap["period_id"] == str(sample_period.period_id)
        assert snap["status"] == "OPEN"

    def test_get_version(self, sample_period):
        assert sample_period.get_version() == 1

    def test_audit_trail(self, sample_period):
        trail = sample_period.audit_trail()
        assert len(trail) >= 1  # at least CREATE entry
        sample_period.touch("admin")
        trail2 = sample_period.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_period):
        touched = sample_period.touch("admin")
        assert touched.version == sample_period.version + 1
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)


# =============================================================================
# Tests for FiscalYearDefinition
# =============================================================================

class TestFiscalYearDefinition:
    def test_create_valid(self, sample_fiscal_year):
        assert sample_fiscal_year.year_name == "FY2026"
        assert sample_fiscal_year.start_month == 1
        assert sample_fiscal_year.version == 1
        assert sample_fiscal_year.cryptographic_hash != ""

    def test_validate_invalid_start_month(self):
        with pytest.raises(ValueError, match="Invalid start month"):
            FiscalYearDefinition(
                fiscal_year_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                year_name="FY2026",
                start_month=13,
                start_day=1,
            )

    def test_validate_invalid_version(self):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            FiscalYearDefinition(
                fiscal_year_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                year_name="FY2026",
                start_month=1,
                start_day=1,
                version=0,
            )

    def test_ensure_hash_creates_hash(self, sample_fiscal_year):
        assert sample_fiscal_year.cryptographic_hash != ""

    def test_compute_hash_consistent(self, sample_fiscal_year):
        h1 = sample_fiscal_year.compute_hash()
        h2 = sample_fiscal_year.compute_hash()
        assert h1 == h2

    def test_add_period_changes_hash(self, sample_fiscal_year, sample_period):
        h1 = sample_fiscal_year.compute_hash()
        sample_fiscal_year.periods.append(sample_period)
        h2 = sample_fiscal_year.compute_hash()
        assert h1 != h2

    def test_get_period_for_date(self, sample_fiscal_year, sample_period):
        sample_fiscal_year.periods.append(sample_period)
        mid = sample_period.start_date + (sample_period.end_date - sample_period.start_date) / 2
        found = sample_fiscal_year.get_period_for_date(mid)
        assert found is not None
        assert found.period_id == sample_period.period_id
        before = sample_period.start_date - timedelta(days=1)
        assert sample_fiscal_year.get_period_for_date(before) is None

    def test_get_open_periods(self, sample_fiscal_year, sample_period):
        sample_fiscal_year.periods.append(sample_period)
        closed = sample_period.close("admin")
        sample_fiscal_year.periods.append(closed)
        open_periods = sample_fiscal_year.get_open_periods()
        assert len(open_periods) == 1
        assert open_periods[0].period_id == sample_period.period_id

    def test_get_period_by_number(self, sample_fiscal_year, sample_period):
        sample_fiscal_year.periods.append(sample_period)
        found = sample_fiscal_year.get_period_by_number(1)
        assert found is not None
        assert found.period_id == sample_period.period_id
        assert sample_fiscal_year.get_period_by_number(99) is None

    def test_update(self, sample_fiscal_year):
        updated = sample_fiscal_year.update("admin", year_name="FY2027", start_month=2)
        assert updated.year_name == "FY2027"
        assert updated.start_month == 2
        assert updated.version == sample_fiscal_year.version + 1
        # Cannot update immutable fields
        updated2 = sample_fiscal_year.update("admin", fiscal_year_id=uuid.uuid4())
        assert updated2.fiscal_year_id == sample_fiscal_year.fiscal_year_id

    def test_delete_and_restore(self, sample_fiscal_year):
        deleted = sample_fiscal_year.delete("admin", "reason")
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == "admin"
        assert deleted.version == sample_fiscal_year.version + 1
        restored = deleted.restore("admin")
        assert restored.deleted_at is None
        assert restored.deleted_by is None
        assert restored.version == deleted.version + 1
        # Restore not deleted raises
        with pytest.raises(ValueError, match="Not deleted"):
            sample_fiscal_year.restore("admin")

    def test_activate_deactivate(self, sample_fiscal_year):
        assert sample_fiscal_year.activate("admin") is sample_fiscal_year
        assert sample_fiscal_year.deactivate("admin") is sample_fiscal_year

    def test_lock_unlock(self, sample_fiscal_year):
        assert sample_fiscal_year.lock("admin", "test") is sample_fiscal_year
        assert sample_fiscal_year.unlock("admin") is sample_fiscal_year

    def test_validate(self, sample_fiscal_year):
        result = sample_fiscal_year.validate()
        assert result["is_valid"] is True
        object.__setattr__(sample_fiscal_year, "cryptographic_hash", "fake")
        result2 = sample_fiscal_year.validate()
        assert result2["is_valid"] is False
        assert "Hash mismatch" in result2["errors"]

    def test_to_dict(self, sample_fiscal_year):
        d = sample_fiscal_year.to_dict()
        assert d["fiscal_year_id"] == str(sample_fiscal_year.fiscal_year_id)
        assert d["year_name"] == "FY2026"
        assert d["start_month"] == 1

    def test_from_dict_roundtrip(self, sample_fiscal_year):
        d = sample_fiscal_year.to_dict()
        reconstructed = FiscalYearDefinition.from_dict(d)
        assert reconstructed.fiscal_year_id == sample_fiscal_year.fiscal_year_id
        assert reconstructed.year_name == sample_fiscal_year.year_name
        assert reconstructed.start_month == sample_fiscal_year.start_month
        assert reconstructed.version == sample_fiscal_year.version

    def test_clone(self, sample_fiscal_year):
        cloned = sample_fiscal_year.clone()
        assert cloned.fiscal_year_id != sample_fiscal_year.fiscal_year_id
        assert cloned.year_name == "FY2026_COPY"
        assert cloned.version == 1

    def test_snapshot(self, sample_fiscal_year):
        snap = sample_fiscal_year.snapshot()
        assert snap["version"] == sample_fiscal_year.version
        assert snap["fiscal_year_id"] == str(sample_fiscal_year.fiscal_year_id)

    def test_audit_trail(self, sample_fiscal_year):
        trail = sample_fiscal_year.audit_trail()
        assert len(trail) >= 1
        sample_fiscal_year.touch("admin")
        trail2 = sample_fiscal_year.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_fiscal_year):
        touched = sample_fiscal_year.touch("admin")
        assert touched.version == sample_fiscal_year.version + 1


# =============================================================================
# Tests for PeriodBoundViolation
# =============================================================================

class TestPeriodBoundViolation:
    def test_create_valid(self, sample_violation):
        assert sample_violation.severity == PeriodBoundViolationSeverity.MEDIUM
        assert sample_violation.was_blocked is False
        assert sample_violation.cryptographic_hash != ""
        assert sample_violation.version == 1

    def test_validate_invalid_version(self, fixed_now):
        with pytest.raises(ValueError, match="Version must be >= 1"):
            PeriodBoundViolation(
                violation_id=uuid.uuid4(),
                transaction_id=uuid.uuid4(),
                transaction_date=fixed_now,
                target_period_id=uuid.uuid4(),
                period_status="OPEN",
                attempted_operation="POST",
                severity=PeriodBoundViolationSeverity.MEDIUM,
                message="test",
                was_blocked=False,
                user_id=None,
                module="test",
                detected_at=fixed_now,
                override_granted=False,
                override_by=None,
                version=0,
            )

    def test_ensure_hash_creates_hash(self, sample_violation):
        assert sample_violation.cryptographic_hash != ""

    def test_compute_hash_consistent(self, sample_violation):
        h1 = sample_violation.compute_hash()
        h2 = sample_violation.compute_hash()
        assert h1 == h2

    def test_grant_override(self, sample_violation):
        granted = sample_violation.grant_override("admin")
        assert granted.override_granted is True
        assert granted.override_by == "admin"
        assert granted.version == sample_violation.version + 1
        # Already granted returns self
        granted2 = granted.grant_override("admin2")
        assert granted2 is granted

    def test_validate(self, sample_violation):
        result = sample_violation.validate()
        assert result["is_valid"] is True
        object.__setattr__(sample_violation, "cryptographic_hash", "fake")
        result2 = sample_violation.validate()
        assert result2["is_valid"] is False
        assert "Hash mismatch" in result2["errors"]

    def test_to_dict(self, sample_violation):
        d = sample_violation.to_dict()
        assert d["violation_id"] == str(sample_violation.violation_id)
        assert d["severity"] == "MEDIUM"
        assert d["was_blocked"] is False

    def test_from_dict_roundtrip(self, sample_violation):
        d = sample_violation.to_dict()
        reconstructed = PeriodBoundViolation.from_dict(d)
        assert reconstructed.violation_id == sample_violation.violation_id
        assert reconstructed.severity == sample_violation.severity
        assert reconstructed.was_blocked == sample_violation.was_blocked
        assert reconstructed.version == sample_violation.version

    def test_clone(self, sample_violation):
        cloned = sample_violation.clone()
        assert cloned.violation_id != sample_violation.violation_id
        assert cloned.override_granted is False
        assert cloned.version == 1

    def test_snapshot(self, sample_violation):
        snap = sample_violation.snapshot()
        assert snap["version"] == sample_violation.version
        assert snap["violation_id"] == str(sample_violation.violation_id)

    def test_audit_trail(self, sample_violation):
        trail = sample_violation.audit_trail()
        assert len(trail) >= 1
        sample_violation.touch("admin")
        trail2 = sample_violation.audit_trail()
        assert len(trail2) >= 2
        assert trail2[-1]["action"] == "TOUCH"

    def test_touch(self, sample_violation):
        touched = sample_violation.touch("admin")
        assert touched is sample_violation  # touch returns self, does not increment version
        trail = touched.audit_trail()
        assert any(entry["action"] == "TOUCH" for entry in trail)

    def test_immutable_methods_raise(self, sample_violation):
        with pytest.raises(AttributeError):
            sample_violation.update("admin", key="value")
        with pytest.raises(AttributeError):
            sample_violation.delete("admin")
        with pytest.raises(AttributeError):
            sample_violation.restore("admin")

    def test_activate_deactivate(self, sample_violation):
        assert sample_violation.activate("admin") is sample_violation
        assert sample_violation.deactivate("admin") is sample_violation

    def test_lock_unlock(self, sample_violation):
        assert sample_violation.lock("admin", "test") is sample_violation
        assert sample_violation.unlock("admin") is sample_violation


# =============================================================================
# Tests for PeriodBoundValidator
# =============================================================================

class TestPeriodBoundValidator:
    def test_determine_severity_by_status(self):
        assert PeriodBoundValidator._determine_severity_by_status(PeriodStatus.CLOSED) == PeriodBoundViolationSeverity.CRITICAL
        assert PeriodBoundValidator._determine_severity_by_status(PeriodStatus.LOCKED) == PeriodBoundViolationSeverity.HIGH
        assert PeriodBoundValidator._determine_severity_by_status(PeriodStatus.FUTURE) == PeriodBoundViolationSeverity.MEDIUM
        assert PeriodBoundValidator._determine_severity_by_status(PeriodStatus.FUTURE, is_budget=True) == PeriodBoundViolationSeverity.LOW
        assert PeriodBoundValidator._determine_severity_by_status(PeriodStatus.OPEN) == PeriodBoundViolationSeverity.LOW

    def test_create_violation(self, fixed_now):
        tx_id = uuid.uuid4()
        period_id = uuid.uuid4()
        user_id = uuid.uuid4()
        violation = PeriodBoundValidator._create_violation(
            transaction_id=tx_id,
            transaction_date=fixed_now,
            target_period_id=period_id,
            period_status="CLOSED",
            attempted_op="POST",
            severity=PeriodBoundViolationSeverity.CRITICAL,
            message="test",
            was_blocked=True,
            user_id=user_id,
            module="journal",
        )
        assert violation.transaction_id == tx_id
        assert violation.target_period_id == period_id
        assert violation.severity == PeriodBoundViolationSeverity.CRITICAL
        assert violation.was_blocked is True
        assert violation.user_id == user_id
        assert violation.module == "journal"

    def test_validate_transaction_period_valid(self, sample_period):
        tx_date = sample_period.start_date + (sample_period.end_date - sample_period.start_date) / 2
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=tx_date,
            target_period=sample_period,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is True
        assert violation is None
        assert hint is None

    def test_validate_transaction_period_outside(self, sample_period):
        outside = sample_period.end_date + timedelta(days=1)
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=outside,
            target_period=sample_period,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == PeriodBoundViolationSeverity.HIGH
        assert "outside period" in violation.message

    def test_validate_transaction_period_closed(self, sample_period):
        closed = sample_period.close("admin")
        tx_date = closed.start_date + (closed.end_date - closed.start_date) / 2
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=tx_date,
            target_period=closed,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == PeriodBoundViolationSeverity.CRITICAL
        assert "status CLOSED" in violation.message

    def test_validate_transaction_period_future_too_far(self, sample_period, fixed_now):
        future = fixed_now + timedelta(days=10)
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=future,
            target_period=sample_period,
            transaction_id=uuid.uuid4(),
            allow_future_posting=False,
            max_future_days=5,
        )
        assert is_valid is False
        assert violation is not None
        assert "days ahead" in violation.message

    def test_validate_transaction_period_future_allowed(self, sample_period, fixed_now):
        future = fixed_now + timedelta(days=3)
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=future,
            target_period=sample_period,
            transaction_id=uuid.uuid4(),
            allow_future_posting=True,
            max_future_days=5,
        )
        assert is_valid is True
        assert violation is None

    def test_notify_constitution(self, sample_violation):
        with patch("axioms.period_bound.get_supreme_law") as mock_get:
            mock_law = MagicMock()
            mock_get.return_value = mock_law
            PeriodBoundValidator._notify_constitution(sample_violation)
            mock_law.check_violation.assert_called_once()


# =============================================================================
# Tests for PeriodBoundAxiom
# =============================================================================

class TestPeriodBoundAxiom:
    def test_singleton(self):
        a1 = PeriodBoundAxiom()
        a2 = PeriodBoundAxiom()
        assert a1 is a2

    def test_initialization(self):
        axiom = PeriodBoundAxiom()
        assert axiom._fiscal_years == {}
        assert axiom._periods == {}
        assert axiom._violation_history == []

    def test_save_and_get_fiscal_year(self, sample_fiscal_year):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        retrieved = axiom.get_fiscal_year(sample_fiscal_year.fiscal_year_id)
        assert retrieved is not None
        assert retrieved.fiscal_year_id == sample_fiscal_year.fiscal_year_id
        assert retrieved.year_name == sample_fiscal_year.year_name

    def test_get_all_fiscal_years(self, sample_fiscal_year):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        all_fy = axiom.get_all_fiscal_years()
        assert len(all_fy) == 1
        assert all_fy[0].fiscal_year_id == sample_fiscal_year.fiscal_year_id
        # Filter by legal_entity_id
        le_id = sample_fiscal_year.legal_entity_id
        filtered = axiom.get_all_fiscal_years(legal_entity_id=le_id)
        assert len(filtered) == 1
        filtered2 = axiom.get_all_fiscal_years(legal_entity_id=uuid.uuid4())
        assert len(filtered2) == 0

    def test_delete_fiscal_year(self, sample_fiscal_year):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        assert axiom.delete_fiscal_year(sample_fiscal_year.fiscal_year_id) is True
        assert axiom.get_fiscal_year(sample_fiscal_year.fiscal_year_id) is None
        assert axiom.delete_fiscal_year(uuid.uuid4()) is False

    def test_save_and_get_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        retrieved = axiom.get_period(sample_period.period_id)
        assert retrieved is not None
        assert retrieved.period_id == sample_period.period_id

    def test_get_all_periods(self, sample_period, sample_fiscal_year):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        all_periods = axiom.get_all_periods()
        assert len(all_periods) == 1
        assert all_periods[0].period_id == sample_period.period_id
        # Filter by legal_entity_id requires relationship with fiscal year
        # Add period to fiscal year
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        filtered = axiom.get_all_periods(legal_entity_id=sample_fiscal_year.legal_entity_id)
        assert len(filtered) == 1
        filtered2 = axiom.get_all_periods(legal_entity_id=uuid.uuid4())
        assert len(filtered2) == 0

    def test_delete_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        assert axiom.delete_period(sample_period.period_id) is True
        assert axiom.get_period(sample_period.period_id) is None
        assert axiom.delete_period(uuid.uuid4()) is False

    def test_define_fiscal_year(self):
        axiom = PeriodBoundAxiom()
        le_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=le_id,
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        assert fy.fiscal_year_id is not None
        assert fy.legal_entity_id == le_id
        assert fy.year_name == "FY2026"
        assert fy.start_month == 1
        assert fy.start_day == 1
        assert fy in axiom._fiscal_years.values()

    def test_add_period(self, sample_fiscal_year, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        axiom.add_period(sample_fiscal_year.fiscal_year_id, sample_period)
        updated_fy = axiom.get_fiscal_year(sample_fiscal_year.fiscal_year_id)
        assert len(updated_fy.periods) == 1
        assert updated_fy.periods[0].period_id == sample_period.period_id
        # Period also saved
        assert axiom.get_period(sample_period.period_id) is not None
        # Add to non-existent raises
        with pytest.raises(PeriodBoundError, match="not found"):
            axiom.add_period(uuid.uuid4(), sample_period)

    def test_get_period_for_date(self, sample_fiscal_year, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        mid = sample_period.start_date + (sample_period.end_date - sample_period.start_date) / 2
        found = axiom.get_period_for_date(sample_fiscal_year.legal_entity_id, mid)
        assert found is not None
        assert found.period_id == sample_period.period_id
        before = sample_period.start_date - timedelta(days=1)
        assert axiom.get_period_for_date(sample_fiscal_year.legal_entity_id, before) is None
        # Different legal entity
        assert axiom.get_period_for_date(uuid.uuid4(), mid) is None

    def test_get_current_period(self, sample_fiscal_year, sample_period, fixed_now):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        current = axiom.get_current_period(sample_fiscal_year.legal_entity_id)
        assert current is not None
        assert current.period_id == sample_period.period_id

    def test_close_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        closed = axiom.close_period(sample_period.period_id, "admin")
        assert closed.status == PeriodStatus.CLOSED
        assert axiom.get_period(sample_period.period_id).status == PeriodStatus.CLOSED
        # Close already closed raises
        with pytest.raises(PeriodClosedError):
            axiom.close_period(sample_period.period_id, "admin")
        # Non-existent raises
        with pytest.raises(PeriodBoundError):
            axiom.close_period(uuid.uuid4(), "admin")

    def test_lock_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        locked = axiom.lock_period(sample_period.period_id, "admin")
        assert locked.status == PeriodStatus.LOCKED
        assert axiom.get_period(sample_period.period_id).status == PeriodStatus.LOCKED
        # Non-existent raises
        with pytest.raises(PeriodBoundError):
            axiom.lock_period(uuid.uuid4(), "admin")

    def test_reopen_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        closed = axiom.close_period(sample_period.period_id, "admin")
        reopened = axiom.reopen_period(sample_period.period_id, "admin", "reason")
        assert reopened.status == PeriodStatus.OPEN
        assert axiom.get_period(sample_period.period_id).status == PeriodStatus.OPEN
        # Non-existent raises
        with pytest.raises(PeriodBoundError):
            axiom.reopen_period(uuid.uuid4(), "admin", "reason")

    def test_archive_period(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        archived = axiom.archive_period(sample_period.period_id, "admin")
        assert archived.status == PeriodStatus.ARCHIVED
        assert axiom.get_period(sample_period.period_id).status == PeriodStatus.ARCHIVED
        # Non-existent raises
        with pytest.raises(PeriodBoundError):
            axiom.archive_period(uuid.uuid4(), "admin")

    def test_get_open_periods(self, sample_fiscal_year, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        open_periods = axiom.get_open_periods(sample_fiscal_year.legal_entity_id)
        assert len(open_periods) == 1
        # Add closed period
        closed = sample_period.close("admin")
        sample_fiscal_year.periods.append(closed)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        open_periods2 = axiom.get_open_periods(sample_fiscal_year.legal_entity_id)
        assert len(open_periods2) == 1  # only the open one

    def test_get_period_sequence(self, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        # Single period
        seq = axiom.get_period_sequence(sample_period.period_id)
        assert len(seq) == 1
        assert seq[0].period_id == sample_period.period_id
        # Non-existent
        seq2 = axiom.get_period_sequence(uuid.uuid4())
        assert seq2 == []
        # With previous and next
        prev = sample_period.clone()
        prev.period_id = uuid.uuid4()
        prev.period_number = 0
        sample_period.previous_period_id = prev.period_id
        nxt = sample_period.clone()
        nxt.period_id = uuid.uuid4()
        nxt.period_number = 2
        sample_period.next_period_id = nxt.period_id
        axiom.save_period(prev)
        axiom.save_period(nxt)
        seq3 = axiom.get_period_sequence(sample_period.period_id)
        assert len(seq3) == 3
        assert seq3[0].period_id == prev.period_id
        assert seq3[1].period_id == sample_period.period_id
        assert seq3[2].period_id == nxt.period_id

    def test_enforce_transaction_period_valid(self, sample_fiscal_year, sample_period, fixed_now):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        tx_date = sample_period.start_date + (sample_period.end_date - sample_period.start_date) / 2
        is_valid, violation, period = axiom.enforce_transaction_period(
            transaction_date=tx_date,
            legal_entity_id=sample_fiscal_year.legal_entity_id,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is True
        assert violation is None
        assert period is not None
        assert period.period_id == sample_period.period_id

    def test_enforce_transaction_period_violation_raises(self, sample_fiscal_year, sample_period):
        axiom = PeriodBoundAxiom()
        axiom.save_fiscal_year(sample_fiscal_year)
        sample_fiscal_year.periods.append(sample_period)
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        closed = sample_period.close("admin")
        sample_fiscal_year.periods = [closed]  # replace with closed
        axiom._fiscal_years[sample_fiscal_year.fiscal_year_id] = sample_fiscal_year
        tx_date = closed.start_date + (closed.end_date - closed.start_date) / 2
        with pytest.raises(PeriodBoundViolationError):
            axiom.enforce_transaction_period(
                transaction_date=tx_date,
                legal_entity_id=sample_fiscal_year.legal_entity_id,
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )

    def test_enforce_transaction_period_no_period(self, fixed_now):
        axiom = PeriodBoundAxiom()
        # No fiscal year defined
        is_valid, violation, period = axiom.enforce_transaction_period(
            transaction_date=fixed_now,
            legal_entity_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid is False
        assert violation is not None
        assert violation.severity == PeriodBoundViolationSeverity.CATASTROPHIC
        assert "No period" in violation.message
        assert period is None

    def test_save_violation_and_get_violations(self, sample_violation):
        axiom = PeriodBoundAxiom()
        axiom.save_violation(sample_violation)
        violations = axiom.get_violations()
        assert len(violations) == 1
        assert violations[0].violation_id == sample_violation.violation_id
        # Filter by severity
        severe = axiom.get_violations(min_severity=PeriodBoundViolationSeverity.HIGH)
        assert len(severe) == 0
        # Filter by period_id
        by_period = axiom.get_violations(period_id=sample_violation.target_period_id)
        assert len(by_period) == 1
        # Filter by transaction_id
        by_tx = axiom.get_violations(transaction_id=sample_violation.transaction_id)
        assert len(by_tx) == 1

    def test_get_statistics(self, sample_period, sample_violation):
        axiom = PeriodBoundAxiom()
        axiom.save_period(sample_period)
        axiom.save_violation(sample_violation)
        stats = axiom.get_statistics()
        assert stats["total_fiscal_years"] == 0
        assert stats["total_periods"] == 1
        assert stats["total_violations"] == 1
        assert stats["periods_by_status"]["OPEN"] == 1
        assert stats["periods_by_status"]["CLOSED"] == 0
        assert stats["periods_by_status"]["LOCKED"] == 0

    def test_reset(self):
        axiom = PeriodBoundAxiom()
        axiom.save_period(AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=datetime(2026,1,1,tzinfo=UTC),
            end_date=datetime(2026,1,31,tzinfo=UTC),
            status=PeriodStatus.OPEN,
        ))
        axiom.reset()
        assert axiom._fiscal_years == {}
        assert axiom._periods == {}
        assert axiom._violation_history == []

    def test_resolve_violation_returns_none(self):
        axiom = PeriodBoundAxiom()
        assert axiom.resolve_violation(uuid.uuid4(), "admin") is None


# =============================================================================
# Tests for Helper Functions
# =============================================================================

class TestHelpers:
    def test_create_accounting_period(self, fixed_now):
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=fixed_now,
            end_date=fixed_now + timedelta(days=1),
            status=PeriodStatus.OPEN,
            is_budget_period=True,
        )
        assert period.fiscal_year == 2026
        assert period.period_number == 1
        assert period.period_type == PeriodType.MONTHLY
        assert period.status == PeriodStatus.OPEN
        assert period.is_budget_period is True

    def test_generate_monthly_periods(self):
        periods = generate_monthly_periods(2026, 1, 2026)
        assert len(periods) == 12
        assert periods[0].period_number == 1
        assert periods[0].period_type == PeriodType.MONTHLY
        assert periods[0].status == PeriodStatus.OPEN
        for i in range(1, 12):
            assert periods[i].status == PeriodStatus.FUTURE
        # Check dates: Jan 1 to Jan 31 23:59:59
        assert periods[0].start_date.month == 1
        assert periods[0].start_date.day == 1
        assert periods[0].end_date.month == 1
        assert periods[0].end_date.day == 31
        assert periods[0].end_date.hour == 23
        assert periods[0].end_date.minute == 59
        assert periods[0].end_date.second == 59

    def test_generate_quarterly_periods(self):
        periods = generate_quarterly_periods(2026, 1)
        assert len(periods) == 4
        assert periods[0].period_number == 1
        assert periods[0].period_type == PeriodType.QUARTERLY
        assert periods[0].status == PeriodStatus.OPEN
        for i in range(1, 4):
            assert periods[i].status == PeriodStatus.FUTURE
        # Check quarters: Q1 Jan-Mar, Q2 Apr-Jun, etc.
        assert periods[0].start_date.month == 1
        assert periods[0].start_date.day == 1
        assert periods[0].end_date.month == 3
        assert periods[0].end_date.day == 31
        assert periods[1].start_date.month == 4
        assert periods[1].end_date.month == 6

    def test_get_period_bound_axiom_singleton(self):
        a1 = get_period_bound_axiom()
        a2 = get_period_bound_axiom()
        assert a1 is a2
        assert isinstance(a1, PeriodBoundAxiom)