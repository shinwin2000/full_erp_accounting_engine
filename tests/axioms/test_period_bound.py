#!/usr/bin/env python3
"""
tests/unit/test_period_bound.py
Test untuk axioms/period_bound.py
Mencakup: AccountingPeriod, FiscalYearDefinition, PeriodBoundViolation,
PeriodBoundValidator, PeriodBoundAxiom
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from axioms.period_bound import (
    AccountingPeriod,
    FiscalYearDefinition,
    PeriodBoundAxiom,
    PeriodBoundValidator,
    PeriodBoundViolation,
    PeriodBoundViolationError,
    PeriodBoundViolationSeverity,
    PeriodStatus,
    PeriodType,
    create_accounting_period,
    generate_monthly_periods,
    generate_quarterly_periods,
    get_period_bound_axiom,
)


class TestAccountingPeriod:
    def test_create_valid_period(self):
        """Test creation of valid AccountingPeriod."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, 23, 59, 59, 999999, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
            is_budget_period=False,
        )
        assert period.fiscal_year == 2026
        assert period.period_number == 1
        assert period.period_type == PeriodType.MONTHLY
        assert period.status == PeriodStatus.OPEN
        assert period.cryptographic_hash != ""

    def test_validate_start_before_end(self):
        """Test validation rejects start >= end."""
        start = datetime(2026, 1, 31, tzinfo=UTC)
        end = datetime(2026, 1, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Start.*>= end"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=1,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.FUTURE,
            )

    def test_validate_period_number_range(self):
        """Test validation rejects period number out of range."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        with pytest.raises(ValueError, match="Invalid period number"):
            AccountingPeriod(
                period_id=uuid.uuid4(),
                fiscal_year=2026,
                period_number=14,
                period_type=PeriodType.MONTHLY,
                start_date=start,
                end_date=end,
                status=PeriodStatus.FUTURE,
            )

    def test_contains_checks_date(self):
        """Test contains checks if date is within period."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        assert period.contains(datetime(2026, 1, 15, tzinfo=UTC))
        assert not period.contains(datetime(2026, 2, 1, tzinfo=UTC))
        assert not period.contains(datetime(2025, 12, 31, tzinfo=UTC))

    def test_is_open_for_posting(self):
        """Test is_open_for_posting checks status."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        assert period.is_open_for_posting()

        closed = period.close("admin")
        assert not closed.is_open_for_posting()

    def test_close_period(self):
        """Test close changes status to CLOSED."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        closed = period.close("admin")
        assert closed.status == PeriodStatus.CLOSED
        assert closed.closed_by == "admin"
        assert closed.closed_at is not None

    def test_reopen_period(self):
        """Test reopen changes status to OPEN."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.CLOSED,
        )
        reopened = period.reopen("admin", "Need correction")
        assert reopened.status == PeriodStatus.OPEN
        assert reopened.closed_at is None
        assert reopened.closed_by is None

    def test_lock_period(self):
        """Test lock changes status to LOCKED."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        locked = period.lock("admin", "Review")
        assert locked.status == PeriodStatus.LOCKED
        assert locked.locked_by == "admin"
        assert locked.locked_at is not None

    def test_unlock_period(self):
        """Test unlock changes status to OPEN."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.LOCKED,
        )
        unlocked = period.unlock("admin")
        assert unlocked.status == PeriodStatus.OPEN
        assert unlocked.locked_at is None
        assert unlocked.locked_by is None

    def test_update_creates_new_version(self):
        """Test update creates new instance with incremented version."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.FUTURE,
        )
        updated = period.update("admin", status=PeriodStatus.OPEN)
        assert updated.status == PeriodStatus.OPEN
        assert updated.version == period.version + 1


class TestFiscalYearDefinition:
    def test_create_valid_fiscal_year(self):
        """Test creation of valid FiscalYearDefinition."""
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        assert fy.year_name == "FY2026"
        assert fy.start_month == 1
        assert fy.version == 1
        assert fy.cryptographic_hash != ""

    def test_validate_start_month_range(self):
        """Test validation rejects invalid start month."""
        with pytest.raises(ValueError, match="Invalid start month"):
            FiscalYearDefinition(
                fiscal_year_id=uuid.uuid4(),
                legal_entity_id=uuid.uuid4(),
                year_name="FY2026",
                start_month=13,
                start_day=1,
            )

    def test_add_periods_and_get_period_for_date(self):
        """Test get_period_for_date returns correct period."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
            periods=[period],
        )
        result = fy.get_period_for_date(datetime(2026, 1, 15, tzinfo=UTC))
        assert result is not None
        assert result.period_id == period.period_id

        result = fy.get_period_for_date(datetime(2026, 2, 1, tzinfo=UTC))
        assert result is None

    def test_get_open_periods(self):
        """Test get_open_periods returns only open periods."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        open_period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        closed_period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=2,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.CLOSED,
        )
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
            periods=[open_period, closed_period],
        )
        open_periods = fy.get_open_periods()
        assert len(open_periods) == 1
        assert open_periods[0].period_id == open_period.period_id


class TestPeriodBoundViolation:
    def test_create_valid_violation(self):
        """Test creation of valid PeriodBoundViolation."""
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="CLOSED",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.CRITICAL,
            message="Cannot post to closed period",
            was_blocked=True,
            user_id=uuid.uuid4(),
            module="journal",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        assert violation.severity == PeriodBoundViolationSeverity.CRITICAL
        assert violation.was_blocked
        assert violation.cryptographic_hash != ""

    def test_grant_override(self):
        """Test grant_override marks override granted."""
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="CLOSED",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.CRITICAL,
            message="test",
            was_blocked=True,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        granted = violation.grant_override("admin")
        assert granted.override_granted
        assert granted.override_by == "admin"


class TestPeriodBoundValidator:
    def test_validate_transaction_period_valid(self):
        """Test validate_transaction_period passes for valid transaction."""
        now = datetime.now(UTC)
        start = now - timedelta(days=1)
        end = now + timedelta(days=1)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=now,
            target_period=period,
            transaction_id=uuid.uuid4(),
        )
        assert is_valid
        assert violation is None

    def test_validate_transaction_period_future(self):
        """Test validate_transaction_period blocks future dates."""
        now = datetime.now(UTC)
        start = now - timedelta(days=30)
        end = now + timedelta(days=30)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        future_date = now + timedelta(days=20)
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=future_date,
            target_period=period,
            transaction_id=uuid.uuid4(),
            allow_future_posting=False,
            max_future_days=7,
        )
        assert not is_valid
        assert violation is not None
        assert "days ahead" in violation.message

    def test_validate_transaction_period_closed(self):
        """Test validate_transaction_period blocks closed period."""
        now = datetime.now(UTC)
        start = now - timedelta(days=10)
        end = now - timedelta(days=1)
        period = AccountingPeriod(
            period_id=uuid.uuid4(),
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.CLOSED,
        )
        is_valid, violation, hint = PeriodBoundValidator.validate_transaction_period(
            transaction_date=now - timedelta(days=5),
            target_period=period,
            transaction_id=uuid.uuid4(),
        )
        assert not is_valid
        assert violation is not None
        assert violation.severity == PeriodBoundViolationSeverity.CRITICAL


class TestPeriodBoundAxiom:
    def test_singleton(self):
        """Test PeriodBoundAxiom is singleton."""
        axiom1 = PeriodBoundAxiom()
        axiom2 = PeriodBoundAxiom()
        assert axiom1 is axiom2

    def test_define_fiscal_year(self):
        """Test define_fiscal_year creates fiscal year."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        assert fy.year_name == "FY2026"
        assert len(axiom.get_all_fiscal_years(legal_entity_id)) >= 1

    def test_add_period_to_fiscal_year(self):
        """Test add_period adds period to fiscal year."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        retrieved = axiom.get_period(period.period_id)
        assert retrieved is not None

    def test_get_period_for_date(self):
        """Test get_period_for_date returns correct period."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        result = axiom.get_period_for_date(legal_entity_id, datetime(2026, 1, 15, tzinfo=UTC))
        assert result is not None
        assert result.period_id == period.period_id

    def test_close_period(self):
        """Test close_period closes period."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        closed = axiom.close_period(period.period_id, "admin")
        assert closed.status == PeriodStatus.CLOSED

    def test_lock_period(self):
        """Test lock_period locks period."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        locked = axiom.lock_period(period.period_id, "admin")
        assert locked.status == PeriodStatus.LOCKED

    def test_reopen_period(self):
        """Test reopen_period reopens closed period."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        closed = axiom.close_period(period.period_id, "admin")
        reopened = axiom.reopen_period(period.period_id, "admin", "Need correction")
        assert reopened.status == PeriodStatus.OPEN

    def test_enforce_transaction_period_passes(self):
        """Test enforce_transaction_period passes for valid transaction."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        is_valid, violation, target = axiom.enforce_transaction_period(
            transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
            legal_entity_id=legal_entity_id,
            transaction_id=uuid.uuid4(),
            raise_on_violation=False,
        )
        assert is_valid
        assert violation is None
        assert target is not None

    def test_enforce_transaction_period_raises_for_closed(self):
        """Test enforce_transaction_period raises for closed period."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        period = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
        )
        axiom.add_period(fy.fiscal_year_id, period)
        axiom.close_period(period.period_id, "admin")
        with pytest.raises(PeriodBoundViolationError):
            axiom.enforce_transaction_period(
                transaction_date=datetime(2026, 1, 15, tzinfo=UTC),
                legal_entity_id=legal_entity_id,
                transaction_id=uuid.uuid4(),
                raise_on_violation=True,
            )

    def test_get_open_periods(self):
        """Test get_open_periods returns open periods."""
        axiom = PeriodBoundAxiom()
        legal_entity_id = uuid.uuid4()
        fy = axiom.define_fiscal_year(
            legal_entity_id=legal_entity_id,
            year_name="FY2026",
            start_month=1,
        )
        start1 = datetime(2026, 1, 1, tzinfo=UTC)
        end1 = datetime(2026, 1, 31, tzinfo=UTC)
        period1 = create_accounting_period(
            fiscal_year=2026,
            period_number=1,
            period_type=PeriodType.MONTHLY,
            start_date=start1,
            end_date=end1,
            status=PeriodStatus.OPEN,
        )
        start2 = datetime(2026, 2, 1, tzinfo=UTC)
        end2 = datetime(2026, 2, 28, tzinfo=UTC)
        period2 = create_accounting_period(
            fiscal_year=2026,
            period_number=2,
            period_type=PeriodType.MONTHLY,
            start_date=start2,
            end_date=end2,
            status=PeriodStatus.CLOSED,
        )
        axiom.add_period(fy.fiscal_year_id, period1)
        axiom.add_period(fy.fiscal_year_id, period2)
        open_periods = axiom.get_open_periods(legal_entity_id)
        assert len(open_periods) == 1
        assert open_periods[0].period_id == period1.period_id

    def test_get_statistics(self):
        """Test get_statistics returns summary."""
        axiom = PeriodBoundAxiom()
        stats = axiom.get_statistics()
        assert "total_fiscal_years" in stats
        assert "total_periods" in stats

    def test_generate_monthly_periods(self):
        """Test generate_monthly_periods creates 12 periods."""
        periods = generate_monthly_periods(2026, 1, 2026)
        assert len(periods) == 12
        assert periods[0].period_number == 1
        assert periods[0].period_type == PeriodType.MONTHLY
        assert periods[0].status == PeriodStatus.OPEN

    def test_generate_quarterly_periods(self):
        """Test generate_quarterly_periods creates 4 periods."""
        periods = generate_quarterly_periods(2026, 1)
        assert len(periods) == 4
        assert periods[0].period_type == PeriodType.QUARTERLY
        assert periods[0].status == PeriodStatus.OPEN

    def test_get_period_bound_axiom_singleton(self):
        """Test get_period_bound_axiom returns singleton."""
        axiom1 = get_period_bound_axiom()
        axiom2 = get_period_bound_axiom()
        assert axiom1 is axiom2


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_test_period() -> AccountingPeriod:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 31, 23, 59, 59, tzinfo=UTC)
    return AccountingPeriod(
        period_id=uuid.uuid4(),
        fiscal_year=2026,
        period_number=1,
        period_type=PeriodType.MONTHLY,
        start_date=start,
        end_date=end,
        status=PeriodStatus.OPEN,
    )


class TestAccountingPeriodLifecycle:
    def test_create_returns_self(self):
        period = create_test_period()
        result = period.create("admin")
        assert result is period

    def test_activate_returns_self(self):
        period = create_test_period()
        result = period.activate("admin")
        assert result is period

    def test_deactivate_returns_self(self):
        period = create_test_period()
        result = period.deactivate("admin")
        assert result is period

    def test_lock_returns_self(self):
        period = create_test_period()
        result = period.lock("admin", "test")
        assert result is period

    def test_unlock_returns_self(self):
        period = create_test_period()
        result = period.unlock("admin")
        assert result is period

    def test_validate_returns_valid(self):
        period = create_test_period()
        result = period.validate()
        assert result["is_valid"]

    def test_close_period_changes_status(self):
        period = create_test_period()
        closed = period.close("admin")
        assert closed.status == PeriodStatus.CLOSED

    def test_reopen_period_changes_status(self):
        period = create_test_period()
        closed = period.close("admin")
        reopened = closed.reopen("admin", "correction")
        assert reopened.status == PeriodStatus.OPEN

    def test_archive_period_changes_status(self):
        period = create_test_period()
        archived = period.archive("admin")
        assert archived.status == PeriodStatus.ARCHIVED


class TestFiscalYearDefinitionLifecycle:
    def test_create_returns_self(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.create("admin")
        assert result is fy

    def test_activate_returns_self(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.activate("admin")
        assert result is fy

    def test_deactivate_returns_self(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.deactivate("admin")
        assert result is fy

    def test_lock_returns_self(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.lock("admin", "test")
        assert result is fy

    def test_unlock_returns_self(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.unlock("admin")
        assert result is fy

    def test_validate_returns_valid(self):
        fy = FiscalYearDefinition(
            fiscal_year_id=uuid.uuid4(),
            legal_entity_id=uuid.uuid4(),
            year_name="FY2026",
            start_month=1,
            start_day=1,
        )
        result = fy.validate()
        assert result["is_valid"]


class TestPeriodBoundViolationLifecycle:
    def test_create_returns_self(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.create("admin")
        assert result is violation

    def test_activate_returns_self(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.activate("admin")
        assert result is violation

    def test_deactivate_returns_self(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.deactivate("admin")
        assert result is violation

    def test_lock_returns_self(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.lock("admin", "test")
        assert result is violation

    def test_unlock_returns_self(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.unlock("admin")
        assert result is violation

    def test_validate_returns_valid(self):
        now = datetime.now(UTC)
        violation = PeriodBoundViolation(
            violation_id=uuid.uuid4(),
            transaction_id=uuid.uuid4(),
            transaction_date=now,
            target_period_id=uuid.uuid4(),
            period_status="OPEN",
            attempted_operation="POST",
            severity=PeriodBoundViolationSeverity.MEDIUM,
            message="test",
            was_blocked=False,
            user_id=None,
            module="test",
            detected_at=now,
            override_granted=False,
            override_by=None,
        )
        result = violation.validate()
        assert result["is_valid"]
