# tests/domain/fiscal_period/test_invariants.py
"""
Invariants tests – all PASS.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from domain.fiscal_period.aggregate_root import (
    FiscalPeriod,
    FiscalPeriodError,
    InvalidDateRangeError,
    InvalidPeriodNumberError,
    PeriodAlreadyExistsError,
    PeriodStatus,
    PeriodType,
)
from domain.fiscal_period.invariants import (
    FiscalPeriodInvariantEnforcer,
    InvariantResult,
    PeriodCreationValidator,
    can_reopen_period,
    validate_can_close_period,
    validate_can_lock_period,
    validate_can_reopen_period,
    validate_date_range,
    validate_no_overlap,
    validate_period_before_close,
    validate_period_before_lock,
    validate_period_number,
    validate_status_transition,
    validate_version,
    validate_year,
)


def make_period(status=PeriodStatus.DRAFT):
    return FiscalPeriod(
        period_id=uuid4(),
        legal_entity_id=uuid4(),
        period_type=PeriodType.MONTHLY,
        period_number=1,
        year=2026,
        start_date=datetime(2026, 1, 1, tzinfo=UTC),
        end_date=datetime(2026, 1, 31, tzinfo=UTC),
        status=status,
        period="2026-01",
        version=1,
    )


class TestInvariantResult:
    def test_add_error(self):
        r = InvariantResult(is_valid=True)
        r.add_error("e1")
        assert r.is_valid is False
        assert r.errors == ["e1"]

    def test_add_warning(self):
        r = InvariantResult(is_valid=True)
        r.add_warning("w1")
        assert r.is_valid is True
        assert r.warnings == ["w1"]

    def test_merge(self):
        r1 = InvariantResult(is_valid=True)
        r2 = InvariantResult(is_valid=False, errors=["e2"])
        r1.merge(r2)
        assert r1.is_valid is False
        assert r1.errors == ["e2"]

    def test_to_dict(self):
        r = InvariantResult(is_valid=False, errors=["e"], warnings=["w"])
        d = r.to_dict()
        assert d["is_valid"] is False
        assert d["errors"] == ["e"]

    def test_bool(self):
        r = InvariantResult(is_valid=True)
        assert bool(r) is True
        r.add_error("e")
        assert bool(r) is False

    def test_success(self):
        r = InvariantResult.success()
        assert r.is_valid is True

    def test_failure(self):
        r = InvariantResult.failure("e")
        assert r.is_valid is False
        assert r.errors == ["e"]


class TestPeriodCreationValidator:
    def test_valid(self):
        result = PeriodCreationValidator.validate_new_period(
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            legal_entity_id=uuid4(),
            existing_periods=[],
        )
        assert result.is_valid is True

    def test_invalid_period_number(self):
        result = PeriodCreationValidator.validate_new_period(
            period_type=PeriodType.MONTHLY,
            period_number=0,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            legal_entity_id=uuid4(),
            existing_periods=[],
        )
        assert result.is_valid is False
        assert "period number must be" in result.errors[0]

    def test_invalid_date_range(self):
        result = PeriodCreationValidator.validate_new_period(
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 31, tzinfo=UTC),
            end_date=datetime(2026, 1, 1, tzinfo=UTC),
            legal_entity_id=uuid4(),
            existing_periods=[],
        )
        assert result.is_valid is False
        assert "Start date" in result.errors[0]

    def test_overlap(self):
        existing = [make_period()]
        result = PeriodCreationValidator.validate_new_period(
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 15, tzinfo=UTC),
            end_date=datetime(2026, 2, 15, tzinfo=UTC),
            legal_entity_id=existing[0].legal_entity_id,
            existing_periods=existing,
        )
        assert result.is_valid is False
        assert "overlaps" in result.errors[0]


class TestFiscalPeriodInvariantEnforcer:
    @pytest.mark.asyncio
    async def test_enforce_creation_valid(self):
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [])
        result = await enforcer.enforce_creation(
            period_type=PeriodType.MONTHLY,
            period_number=1,
            year=2026,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            legal_entity_id=uuid4(),
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_update_valid(self):
        period = make_period()
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [period])
        result = await enforcer.enforce_update(
            period_id=period.period_id,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 31, tzinfo=UTC),
            legal_entity_id=period.legal_entity_id,
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_status_transition_valid(self):
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [])
        result = await enforcer.enforce_status_transition(
            current_status=PeriodStatus.OPEN,
            new_status=PeriodStatus.LOCKED,
            user_role="accountant",
            has_unposted_transactions=False,
            has_pending_adjustments=False,
            has_open_periods_after=False,
        )
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_status_transition_invalid(self):
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [])
        result = await enforcer.enforce_status_transition(
            current_status=PeriodStatus.DRAFT,
            new_status=PeriodStatus.OPEN,
            user_role="admin",
            has_unposted_transactions=False,
            has_pending_adjustments=False,
            has_open_periods_after=False,
        )
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_enforce_reopen_valid(self):
        period = make_period(status=PeriodStatus.CLOSED)
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [])
        result = await enforcer.enforce_reopen(period=period, user_role="admin")
        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_enforce_reopen_invalid(self):
        period = make_period(status=PeriodStatus.OPEN)
        enforcer = FiscalPeriodInvariantEnforcer(get_existing_periods=lambda: [])
        result = await enforcer.enforce_reopen(period=period, user_role="user")
        assert result.is_valid is False


class TestStandalone:
    def test_validate_period_number_monthly(self):
        result = validate_period_number(PeriodType.MONTHLY, 1)
        assert result.is_valid is True
        result2 = validate_period_number(PeriodType.MONTHLY, 13)
        assert result2.is_valid is False

    def test_validate_date_range(self):
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = datetime(2026, 1, 31, tzinfo=UTC)
        result = validate_date_range(start, end)
        assert result.is_valid is True
        result2 = validate_date_range(end, start)
        assert result2.is_valid is False

    def test_validate_year(self):
        result = validate_year(2026)
        assert result.is_valid is True
        result2 = validate_year(0)
        assert result2.is_valid is False

    def test_validate_version(self):
        result = validate_version(1, 1)
        assert result.is_valid is True
        result2 = validate_version(1, 2)
        assert result2.is_valid is False

    def test_validate_no_overlap(self):
        existing = [make_period()]
        result = validate_no_overlap(
            new_start=datetime(2026, 2, 1, tzinfo=UTC),
            new_end=datetime(2026, 2, 28, tzinfo=UTC),
            existing_periods=existing,
        )
        assert result.is_valid is True
        result2 = validate_no_overlap(
            new_start=datetime(2026, 1, 15, tzinfo=UTC),
            new_end=datetime(2026, 2, 15, tzinfo=UTC),
            existing_periods=existing,
        )
        assert result2.is_valid is False

    def test_validate_no_overlap_exclude(self):
        existing = [make_period()]
        pid = existing[0].period_id
        result = validate_no_overlap(
            new_start=datetime(2026, 1, 15, tzinfo=UTC),
            new_end=datetime(2026, 2, 15, tzinfo=UTC),
            existing_periods=existing,
            exclude_period_id=pid,
        )
        assert result.is_valid is True

    def test_validate_status_transition(self):
        result = validate_status_transition(PeriodStatus.OPEN, PeriodStatus.LOCKED, "accountant")
        assert result.is_valid is True
        result2 = validate_status_transition(PeriodStatus.DRAFT, PeriodStatus.OPEN, "admin")
        assert result2.is_valid is False

    def test_validate_can_close_period(self):
        period = make_period(status=PeriodStatus.LOCKED)
        result = validate_can_close_period(period, False, False)
        assert result.is_valid is True
        result2 = validate_can_close_period(period, True, False)
        assert result2.is_valid is False

    def test_validate_can_lock_period(self):
        period = make_period(status=PeriodStatus.OPEN)
        result = validate_can_lock_period(period, False)
        assert result.is_valid is True
        result2 = validate_can_lock_period(period, True)
        assert result2.is_valid is True
        assert len(result2.warnings) == 1

    def test_validate_can_reopen_period(self):
        period = make_period(status=PeriodStatus.CLOSED)
        result = validate_can_reopen_period(period, "admin")
        assert result.is_valid is True
        period2 = make_period(status=PeriodStatus.OPEN)
        result2 = validate_can_reopen_period(period2, "admin")
        assert result2.is_valid is False

    def test_can_reopen_period(self):
        period = make_period(status=PeriodStatus.CLOSED)
        result = can_reopen_period(period, "admin")
        assert result.is_valid is True
        period2 = make_period(status=PeriodStatus.OPEN)
        result2 = can_reopen_period(period2, "admin")
        assert result2.is_valid is False

    def test_validate_period_before_close(self):
        period = make_period(status=PeriodStatus.LOCKED)
        result = validate_period_before_close(period, False, False)
        assert result.is_valid is True

    def test_validate_period_before_lock(self):
        period = make_period(status=PeriodStatus.OPEN)
        result = validate_period_before_lock(period, False)
        assert result.is_valid is True