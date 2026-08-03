# tests/domain/reality/test_effective_date_vo.py
"""
Unit tests for effective_date_vo.py.
Covers all public methods with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta

import pytest

from domain.reality.effective_date_vo import (
    EffectiveDate,
    EffectiveDateConstraint,
    EffectiveDateFactory,
    EffectiveDateType,
)

# ============================================================================
# Helper
# ============================================================================

def make_dt(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


# ============================================================================
# Test Enums
# ============================================================================

class TestEffectiveDateType:
    def test_members(self):
        assert EffectiveDateType.TRANSACTION_DATE.name == "TRANSACTION_DATE"
        assert EffectiveDateType.RECOGNITION_DATE.name == "RECOGNITION_DATE"
        assert EffectiveDateType.SETTLEMENT_DATE.name == "SETTLEMENT_DATE"
        assert EffectiveDateType.DELIVERY_DATE.name == "DELIVERY_DATE"
        assert EffectiveDateType.CONTRACT_DATE.name == "CONTRACT_DATE"
        assert EffectiveDateType.INVOICE_DATE.name == "INVOICE_DATE"
        assert EffectiveDateType.DUE_DATE.name == "DUE_DATE"
        assert EffectiveDateType.PERIOD_START.name == "PERIOD_START"
        assert EffectiveDateType.PERIOD_END.name == "PERIOD_END"


class TestEffectiveDateConstraint:
    def test_members(self):
        assert EffectiveDateConstraint.NO_CONSTRAINT.name == "NO_CONSTRAINT"
        assert EffectiveDateConstraint.NOT_IN_FUTURE.name == "NOT_IN_FUTURE"
        assert EffectiveDateConstraint.NOT_IN_PAST.name == "NOT_IN_PAST"
        assert EffectiveDateConstraint.WITHIN_PERIOD.name == "WITHIN_PERIOD"
        assert EffectiveDateConstraint.WITHIN_FISCAL_YEAR.name == "WITHIN_FISCAL_YEAR"
        assert EffectiveDateConstraint.AFTER_LAST_TRANSACTION.name == "AFTER_LAST_TRANSACTION"


# ============================================================================
# Test EffectiveDate Construction
# ============================================================================

class TestEffectiveDateConstruction:
    def test_construction(self):
        dt = make_dt(2026, 1, 15, 10, 30)
        eff = EffectiveDate(
            date=dt,
            date_type=EffectiveDateType.TRANSACTION_DATE,
            source="test",
            justification="testing",
        )
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.TRANSACTION_DATE
        assert eff.source == "test"
        assert eff.justification == "testing"

    def test_timezone_normalization(self):
        naive = datetime(2026, 1, 1, 12, 0)
        eff = EffectiveDate(
            date=naive,
            date_type=EffectiveDateType.TRANSACTION_DATE,
            source="test",
        )
        assert eff.date.tzinfo is not None
        assert eff.date == naive.replace(tzinfo=UTC)

    def test_empty_source_raises(self):
        with pytest.raises(ValueError, match="Source cannot be empty"):
            EffectiveDate(
                date=datetime.now(UTC),
                date_type=EffectiveDateType.TRANSACTION_DATE,
                source="",
            )


# ============================================================================
# Test Factory Methods
# ============================================================================

class TestEffectiveDateFactoryMethods:
    def test_from_user_input(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDate.from_user_input(dt, EffectiveDateType.INVOICE_DATE, "justification")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.INVOICE_DATE
        assert eff.source == "user_input"
        assert eff.justification == "justification"

    def test_from_user_input_without_justification(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDate.from_user_input(dt, EffectiveDateType.TRANSACTION_DATE)
        assert eff.justification is None

    def test_from_system(self):
        before = datetime.now(UTC)
        eff = EffectiveDate.from_system(EffectiveDateType.RECOGNITION_DATE)
        after = datetime.now(UTC)
        assert before <= eff.date <= after
        assert eff.date_type == EffectiveDateType.RECOGNITION_DATE
        assert eff.source == "system"

    def test_from_api(self):
        dt = make_dt(2026, 7, 1)
        eff = EffectiveDate.from_api(dt, EffectiveDateType.SETTLEMENT_DATE, "bank_api")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.SETTLEMENT_DATE
        assert eff.source == "api:bank_api"


# ============================================================================
# Test Validation
# ============================================================================

class TestEffectiveDateValidation:
    def test_not_in_future_within_tolerance(self):
        now = make_dt(2026, 1, 15)
        future = now + timedelta(days=3)
        eff = EffectiveDate(future, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(EffectiveDateConstraint.NOT_IN_FUTURE, reference_date=now, tolerance_days=5)
        assert valid is True
        assert msg is None

    def test_not_in_future_exceeds_tolerance(self):
        now = make_dt(2026, 1, 15)
        future = now + timedelta(days=10)
        eff = EffectiveDate(future, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(EffectiveDateConstraint.NOT_IN_FUTURE, reference_date=now, tolerance_days=5)
        assert valid is False
        assert "days in the future" in msg

    def test_not_in_past_within_tolerance(self):
        now = make_dt(2026, 1, 15)
        past = now - timedelta(days=3)
        eff = EffectiveDate(past, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(EffectiveDateConstraint.NOT_IN_PAST, reference_date=now, tolerance_days=5)
        assert valid is True
        assert msg is None

    def test_not_in_past_exceeds_tolerance(self):
        now = make_dt(2026, 1, 15)
        past = now - timedelta(days=10)
        eff = EffectiveDate(past, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(EffectiveDateConstraint.NOT_IN_PAST, reference_date=now, tolerance_days=5)
        assert valid is False
        assert "days in the past" in msg

    def test_within_period_valid(self):
        start = make_dt(2026, 1, 1)
        end = make_dt(2026, 1, 31)
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.WITHIN_PERIOD,
            period_start=start,
            period_end=end,
        )
        assert valid is True
        assert msg is None

    def test_within_period_before_start(self):
        start = make_dt(2026, 1, 1)
        end = make_dt(2026, 1, 31)
        dt = make_dt(2025, 12, 31)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.WITHIN_PERIOD,
            period_start=start,
            period_end=end,
        )
        assert valid is False
        assert "before period start" in msg

    def test_within_period_after_end(self):
        start = make_dt(2026, 1, 1)
        end = make_dt(2026, 1, 31)
        dt = make_dt(2026, 2, 1)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.WITHIN_PERIOD,
            period_start=start,
            period_end=end,
        )
        assert valid is False
        assert "after period end" in msg

    def test_within_period_missing_params_raises(self):
        eff = EffectiveDate(datetime.now(UTC), EffectiveDateType.TRANSACTION_DATE, "test")
        with pytest.raises(ValueError, match="period_start and period_end are required"):
            eff.validate(EffectiveDateConstraint.WITHIN_PERIOD)

    def test_within_fiscal_year_valid(self):
        start = make_dt(2026, 1, 1)
        end = make_dt(2026, 12, 31)
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, _msg = eff.validate(
            EffectiveDateConstraint.WITHIN_FISCAL_YEAR,
            fiscal_year_start=start,
            fiscal_year_end=end,
        )
        assert valid is True

    def test_within_fiscal_year_before_start(self):
        start = make_dt(2026, 1, 1)
        end = make_dt(2026, 12, 31)
        dt = make_dt(2025, 12, 31)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.WITHIN_FISCAL_YEAR,
            fiscal_year_start=start,
            fiscal_year_end=end,
        )
        assert valid is False
        assert "before fiscal year start" in msg

    def test_within_fiscal_year_missing_params_raises(self):
        eff = EffectiveDate(datetime.now(UTC), EffectiveDateType.TRANSACTION_DATE, "test")
        with pytest.raises(ValueError, match="fiscal_year_start and fiscal_year_end are required"):
            eff.validate(EffectiveDateConstraint.WITHIN_FISCAL_YEAR)

    def test_after_last_transaction_valid(self):
        last_tx = make_dt(2026, 1, 10)
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.AFTER_LAST_TRANSACTION,
            reference_date=last_tx,
        )
        assert valid is True
        assert msg is None

    def test_after_last_transaction_invalid(self):
        last_tx = make_dt(2026, 1, 20)
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(
            EffectiveDateConstraint.AFTER_LAST_TRANSACTION,
            reference_date=last_tx,
        )
        assert valid is False
        assert "before last transaction date" in msg

    def test_after_last_transaction_missing_reference_raises(self):
        eff = EffectiveDate(datetime.now(UTC), EffectiveDateType.TRANSACTION_DATE, "test")
        with pytest.raises(ValueError, match="reference_date is required"):
            eff.validate(EffectiveDateConstraint.AFTER_LAST_TRANSACTION)

    def test_no_constraint_always_valid(self):
        dt = make_dt(2026, 1, 1)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        valid, msg = eff.validate(EffectiveDateConstraint.NO_CONSTRAINT)
        assert valid is True
        assert msg is None


# ============================================================================
# Test Conversion Methods
# ============================================================================

class TestConversionMethods:
    def test_to_period_key(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_period_key() == "2026-06"

    def test_to_fiscal_year_key(self):
        dt = make_dt(2026, 12, 31)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_fiscal_year_key() == "2026"

    def test_to_quarter_key(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_quarter_key() == "2026-Q2"

        dt2 = make_dt(2026, 12, 1)
        eff2 = EffectiveDate(dt2, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff2.to_quarter_key() == "2026-Q4"


# ============================================================================
# Test Business Day / Holiday Methods
# ============================================================================

class TestBusinessDayMethods:
    def test_is_weekend_saturday(self):
        # 2026-01-03 is Saturday
        dt = make_dt(2026, 1, 3)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.is_weekend() is True

    def test_is_weekend_sunday(self):
        # 2026-01-04 is Sunday
        dt = make_dt(2026, 1, 4)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.is_weekend() is True

    def test_is_weekend_weekday(self):
        # 2026-01-05 is Monday
        dt = make_dt(2026, 1, 5)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.is_weekend() is False

    def test_is_public_holiday_empty(self):
        dt = make_dt(2026, 1, 1)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.is_public_holiday() is False

    def test_is_public_holiday_with_calendar(self):
        dt = make_dt(2026, 1, 1)
        holidays = {dt.date()}
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.is_public_holiday(holidays) is True

    def test_adjust_to_business_day_weekend(self):
        # 2026-01-03 Saturday -> should adjust to 2026-01-05 Monday (since 4 is Sunday)
        dt = make_dt(2026, 1, 3)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        adjusted = eff.adjust_to_business_day()
        assert adjusted.date == make_dt(2026, 1, 5)
        assert adjusted.source == "adjusted_from_test"
        assert "Adjusted from" in adjusted.justification

    def test_adjust_to_business_day_weekday(self):
        dt = make_dt(2026, 1, 5)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        adjusted = eff.adjust_to_business_day()
        assert adjusted is eff  # no change

    def test_adjust_to_business_day_with_holidays(self):
        # 2026-01-01 is holiday, 2026-01-02 is Friday (business day)
        dt = make_dt(2026, 1, 1)
        holidays = {dt.date()}
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        adjusted = eff.adjust_to_business_day(holidays)
        assert adjusted.date == make_dt(2026, 1, 2)


# ============================================================================
# Test Date Comparison Methods
# ============================================================================

class TestComparisonMethods:
    def test_days_until(self):
        dt1 = make_dt(2026, 1, 1)
        dt2 = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt1, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.days_until(dt2) == 14

    def test_days_since(self):
        dt1 = make_dt(2026, 1, 15)
        dt2 = make_dt(2026, 1, 1)
        eff = EffectiveDate(dt1, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.days_since(dt2) == 14

    def test_is_before(self):
        dt1 = make_dt(2026, 1, 1)
        dt2 = make_dt(2026, 1, 15)
        eff1 = EffectiveDate(dt1, EffectiveDateType.TRANSACTION_DATE, "test")
        eff2 = EffectiveDate(dt2, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff1.is_before(eff2) is True
        assert eff2.is_before(eff1) is False

    def test_is_after(self):
        dt1 = make_dt(2026, 1, 1)
        dt2 = make_dt(2026, 1, 15)
        eff1 = EffectiveDate(dt1, EffectiveDateType.TRANSACTION_DATE, "test")
        eff2 = EffectiveDate(dt2, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff2.is_after(eff1) is True
        assert eff1.is_after(eff2) is False

    def test_is_same_day(self):
        dt = make_dt(2026, 1, 15, 10, 0)
        dt2 = make_dt(2026, 1, 15, 20, 0)
        eff1 = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        eff2 = EffectiveDate(dt2, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff1.is_same_day(eff2) is True

        eff3 = EffectiveDate(make_dt(2026, 1, 16), EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff1.is_same_day(eff3) is False


# ============================================================================
# Test Serialization / Output
# ============================================================================

class TestSerializationMethods:
    def test_to_iso(self):
        dt = make_dt(2026, 1, 15, 10, 30)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_iso() == "2026-01-15T10:30:00+00:00"

    def test_to_date_string(self):
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_date_string() == "2026-01-15"

    def test_to_datetime(self):
        dt = make_dt(2026, 1, 15, 10, 30)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        assert eff.to_datetime() == dt

    def test_to_dict(self):
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(
            date=dt,
            date_type=EffectiveDateType.TRANSACTION_DATE,
            source="test",
            justification="just",
        )
        d = eff.to_dict()
        assert d["date"] == dt.isoformat()
        assert d["date_type"] == "TRANSACTION_DATE"
        assert d["source"] == "test"
        assert d["justification"] == "just"

    def test_repr(self):
        dt = make_dt(2026, 1, 15)
        eff = EffectiveDate(dt, EffectiveDateType.TRANSACTION_DATE, "test")
        repr_str = repr(eff)
        assert "EffectiveDate" in repr_str
        assert "TRANSACTION_DATE" in repr_str
        assert "source=test" in repr_str


# ============================================================================
# Test EffectiveDateFactory
# ============================================================================

class TestEffectiveDateFactory:
    def test_for_transaction_with_user_input(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_transaction(datetime.now(UTC), user_input=dt)
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.TRANSACTION_DATE
        assert eff.source == "user_input"

    def test_for_transaction_without_user_input(self):
        before = datetime.now(UTC)
        eff = EffectiveDateFactory.for_transaction(datetime.now(UTC))
        after = datetime.now(UTC)
        assert before <= eff.date <= after
        assert eff.date_type == EffectiveDateType.TRANSACTION_DATE
        assert eff.source == "system"

    def test_for_invoice(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_invoice(dt)
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.INVOICE_DATE
        assert eff.source == "user_input"

    def test_for_payment_user_input(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_payment(dt, source="user_input")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.SETTLEMENT_DATE
        assert eff.source == "user_input"

    def test_for_payment_api(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_payment(dt, source="bank")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.SETTLEMENT_DATE
        assert eff.source == "api:bank"

    def test_for_delivery_user_input(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_delivery(dt, source="user_input")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.DELIVERY_DATE
        assert eff.source == "user_input"

    def test_for_delivery_system(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_delivery(dt, source="system")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.DELIVERY_DATE
        assert eff.source == "api:system"

    def test_for_due_date(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_due_date(dt, source="contract")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.DUE_DATE
        assert eff.source == "api:contract"

    def test_for_recognition(self):
        dt = make_dt(2026, 6, 15)
        eff = EffectiveDateFactory.for_recognition(dt, source="accounting")
        assert eff.date == dt
        assert eff.date_type == EffectiveDateType.RECOGNITION_DATE
        assert eff.source == "api:accounting"
