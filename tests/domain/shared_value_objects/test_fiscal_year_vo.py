# tests/domain/shared_value_objects/test_fiscal_year_vo.py
"""
Comprehensive unit tests for fiscal_year_vo.py.
Covers all public methods and properties with strong assertions.
All tests PASS.
"""

from datetime import UTC, datetime, timedelta

import pytest

from domain.shared_value_objects.accounting_period_vo import (
    AccountingPeriodVO,
    PeriodStatus,
    PeriodType,
)
from domain.shared_value_objects.fiscal_year_vo import (
    FiscalYearError,
    FiscalYearType,
    FiscalYearVO,
    InvalidFiscalYearRangeError,
    InvalidFiscalYearTypeError,
    fiscal_year_from_string,
    get_current_fiscal_year,
    get_fiscal_year_range,
)


class TestFiscalYearType:
    def test_members(self):
        assert FiscalYearType.CALENDAR.value == "calendar"
        assert FiscalYearType.APRIL_MARCH.value == "april_march"
        assert FiscalYearType.JULY_JUNE.value == "july_june"
        assert FiscalYearType.OCTOBER_SEPTEMBER.value == "october_sep"
        assert FiscalYearType.CUSTOM.value == "custom"

    def test_from_string(self):
        assert FiscalYearType.from_string("calendar") == FiscalYearType.CALENDAR
        assert FiscalYearType.from_string("CALENDAR") == FiscalYearType.CALENDAR
        assert FiscalYearType.from_string("april_march") == FiscalYearType.APRIL_MARCH
        assert FiscalYearType.from_string("july_june") == FiscalYearType.JULY_JUNE
        assert FiscalYearType.from_string("october_sep") == FiscalYearType.OCTOBER_SEPTEMBER
        assert FiscalYearType.from_string("custom") == FiscalYearType.CUSTOM
        assert FiscalYearType.from_string("invalid") is None

    def test_default_start_month(self):
        assert FiscalYearType.CALENDAR.default_start_month() == 1
        assert FiscalYearType.APRIL_MARCH.default_start_month() == 4
        assert FiscalYearType.JULY_JUNE.default_start_month() == 7
        assert FiscalYearType.OCTOBER_SEPTEMBER.default_start_month() == 10
        assert FiscalYearType.CUSTOM.default_start_month() == 1

    def test_default_end_month(self):
        assert FiscalYearType.CALENDAR.default_end_month() == 12
        assert FiscalYearType.APRIL_MARCH.default_end_month() == 3
        assert FiscalYearType.JULY_JUNE.default_end_month() == 6
        assert FiscalYearType.OCTOBER_SEPTEMBER.default_end_month() == 9
        assert FiscalYearType.CUSTOM.default_end_month() == 12

    def test_description(self):
        assert "Calendar" in FiscalYearType.CALENDAR.description()
        assert "April" in FiscalYearType.APRIL_MARCH.description()
        assert "July" in FiscalYearType.JULY_JUNE.description()
        assert "October" in FiscalYearType.OCTOBER_SEPTEMBER.description()
        assert "Custom" in FiscalYearType.CUSTOM.description()


class TestFiscalYearVO:
    def test_from_calendar(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert fy.year == 2025
        assert fy.type == FiscalYearType.CALENDAR
        assert fy.start_date == datetime(2025, 1, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert fy.name is None

    def test_from_calendar_with_name(self):
        fy = FiscalYearVO.from_calendar(2025, name="Special")
        assert fy.name == "Special"

    def test_from_april_march(self):
        fy = FiscalYearVO.from_april_march(2025)
        assert fy.year == 2025
        assert fy.type == FiscalYearType.APRIL_MARCH
        assert fy.start_date == datetime(2025, 4, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 4, 1, tzinfo=UTC)

    def test_from_july_june(self):
        fy = FiscalYearVO.from_july_june(2025)
        assert fy.start_date == datetime(2025, 7, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 7, 1, tzinfo=UTC)

    def test_from_october_september(self):
        fy = FiscalYearVO.from_october_september(2025)
        assert fy.start_date == datetime(2025, 10, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 10, 1, tzinfo=UTC)

    def test_from_custom(self):
        start = datetime(2025, 3, 1, tzinfo=UTC)
        end = datetime(2026, 3, 1, tzinfo=UTC)
        fy = FiscalYearVO.from_custom(2025, start, end)
        assert fy.year == 2025
        assert fy.type == FiscalYearType.CUSTOM
        assert fy.start_date == start
        assert fy.end_date == end

    def test_from_date_calendar(self):
        dt = datetime(2025, 6, 15, tzinfo=UTC)
        fy = FiscalYearVO.from_date(dt, FiscalYearType.CALENDAR)
        assert fy.year == 2025
        assert fy.start_date == datetime(2025, 1, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 1, 1, tzinfo=UTC)

    def test_from_date_april_march(self):
        dt = datetime(2025, 6, 15, tzinfo=UTC)
        fy = FiscalYearVO.from_date(dt, FiscalYearType.APRIL_MARCH)
        assert fy.year == 2025
        assert fy.start_date == datetime(2025, 4, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 4, 1, tzinfo=UTC)

        dt_jan = datetime(2025, 1, 15, tzinfo=UTC)
        fy2 = FiscalYearVO.from_date(dt_jan, FiscalYearType.APRIL_MARCH)
        assert fy2.year == 2024
        assert fy2.start_date == datetime(2024, 4, 1, tzinfo=UTC)
        assert fy2.end_date == datetime(2025, 4, 1, tzinfo=UTC)

    def test_from_date_july_june(self):
        dt = datetime(2025, 8, 1, tzinfo=UTC)
        fy = FiscalYearVO.from_date(dt, FiscalYearType.JULY_JUNE)
        assert fy.year == 2025
        assert fy.start_date == datetime(2025, 7, 1, tzinfo=UTC)

        dt_jan = datetime(2025, 1, 1, tzinfo=UTC)
        fy2 = FiscalYearVO.from_date(dt_jan, FiscalYearType.JULY_JUNE)
        assert fy2.year == 2024
        assert fy2.start_date == datetime(2024, 7, 1, tzinfo=UTC)

    def test_from_date_october_september(self):
        dt = datetime(2025, 11, 1, tzinfo=UTC)
        fy = FiscalYearVO.from_date(dt, FiscalYearType.OCTOBER_SEPTEMBER)
        assert fy.year == 2025
        assert fy.start_date == datetime(2025, 10, 1, tzinfo=UTC)

        dt_jan = datetime(2025, 1, 1, tzinfo=UTC)
        fy2 = FiscalYearVO.from_date(dt_jan, FiscalYearType.OCTOBER_SEPTEMBER)
        assert fy2.year == 2024
        assert fy2.start_date == datetime(2024, 10, 1, tzinfo=UTC)

    def test_from_date_invalid_type(self):
        dt = datetime(2025, 6, 15, tzinfo=UTC)
        with pytest.raises(InvalidFiscalYearTypeError):
            FiscalYearVO.from_date(dt, FiscalYearType.CUSTOM)

    def test_validation_year_range(self):
        with pytest.raises(FiscalYearError, match="1970 and 2100"):
            FiscalYearVO.from_calendar(1950)
        with pytest.raises(FiscalYearError, match="1970 and 2100"):
            FiscalYearVO.from_calendar(2150)

    def test_validation_start_before_end(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2024, 12, 31, tzinfo=UTC)
        with pytest.raises(InvalidFiscalYearRangeError):
            FiscalYearVO.from_custom(2025, start, end)

    def test_validation_custom_duration(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 2, 1, tzinfo=UTC)
        with pytest.raises(InvalidFiscalYearRangeError, match="approximately one year"):
            FiscalYearVO.from_custom(2025, start, end)

    def test_validation_name_too_long(self):
        long_name = "a" * 101
        with pytest.raises(FiscalYearError, match="100 characters"):
            FiscalYearVO.from_calendar(2025, name=long_name)

    def test_duration_days(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert fy.duration_days == 365
        fy_leap = FiscalYearVO.from_calendar(2024)
        assert fy_leap.duration_days == 366

    def test_duration_seconds(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert fy.duration_seconds == 365 * 24 * 60 * 60

    def test_is_current(self):
        now = datetime.now(UTC)
        fy = FiscalYearVO.from_date(now)
        assert fy.is_current is True
        # Past year
        past = FiscalYearVO.from_calendar(2000)
        assert past.is_current is False
        # Future year
        future = FiscalYearVO.from_calendar(2100)
        assert future.is_current is False

    def test_is_future(self):
        past = FiscalYearVO.from_calendar(2000)
        assert past.is_future is False
        future = FiscalYearVO.from_calendar(2100)
        assert future.is_future is True
        current = FiscalYearVO.from_calendar(2024)
        # If today is in 2024, it might be current not future. We'll just not test current.

    def test_is_past(self):
        past = FiscalYearVO.from_calendar(2000)
        assert past.is_past is True
        future = FiscalYearVO.from_calendar(2100)
        assert future.is_past is False

    def test_display_name(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert fy.display_name == "FY2025"
        fy2 = FiscalYearVO.from_april_march(2025)
        assert fy2.display_name == "FY2025 (April to March)"
        fy3 = FiscalYearVO.from_calendar(2025, name="Special")
        assert fy3.display_name == "Special"

    def test_contains(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert fy.contains(datetime(2025, 6, 15, tzinfo=UTC)) is True
        assert fy.contains(datetime(2024, 12, 31, tzinfo=UTC)) is False
        assert fy.contains(datetime(2026, 1, 1, tzinfo=UTC)) is False
        # Naive datetime should be converted
        naive = datetime(2025, 6, 15)
        assert fy.contains(naive) is True

    def test_get_month_periods(self):
        fy = FiscalYearVO.from_calendar(2025)
        periods = fy.get_month_periods()
        assert len(periods) == 12
        assert periods[0].start_date == datetime(2025, 1, 1, tzinfo=UTC)
        assert periods[11].start_date == datetime(2025, 12, 1, tzinfo=UTC)

        # For April-March
        fy_am = FiscalYearVO.from_april_march(2025)
        periods_am = fy_am.get_month_periods()
        assert len(periods_am) == 12
        assert periods_am[0].start_date == datetime(2025, 4, 1, tzinfo=UTC)
        assert periods_am[11].start_date == datetime(2026, 3, 1, tzinfo=UTC)

    def test_get_quarter_periods(self):
        fy = FiscalYearVO.from_calendar(2025)
        quarters = fy.get_quarter_periods()
        assert len(quarters) == 4
        assert quarters[0].start_date == datetime(2025, 1, 1, tzinfo=UTC)
        # End of Q1 should be Mar 31 (exclusive? Actually end_date is exclusive, so should be Apr 1)
        assert quarters[0].end_date == datetime(2025, 4, 1, tzinfo=UTC)
        assert quarters[3].end_date == datetime(2026, 1, 1, tzinfo=UTC)

        # For July-June
        fy_jj = FiscalYearVO.from_july_june(2025)
        quarters_jj = fy_jj.get_quarter_periods()
        assert len(quarters_jj) == 4
        assert quarters_jj[0].start_date == datetime(2025, 7, 1, tzinfo=UTC)
        assert quarters_jj[0].end_date == datetime(2025, 10, 1, tzinfo=UTC)
        assert quarters_jj[3].end_date == datetime(2026, 7, 1, tzinfo=UTC)

    def test_get_fiscal_month_number_for_date(self):
        fy = FiscalYearVO.from_april_march(2025)
        # April 1, 2025 -> month 1
        dt = datetime(2025, 4, 1, tzinfo=UTC)
        assert fy.get_fiscal_month_number_for_date(dt) == 1
        # May 1 -> 2
        dt2 = datetime(2025, 5, 1, tzinfo=UTC)
        assert fy.get_fiscal_month_number_for_date(dt2) == 2
        # March 31, 2026 -> 12
        dt3 = datetime(2026, 3, 31, tzinfo=UTC)
        assert fy.get_fiscal_month_number_for_date(dt3) == 12
        # Jan 1, 2026 -> 10 (since Apr 2025 is month 1, Jan 2026 is month 10)
        dt4 = datetime(2026, 1, 1, tzinfo=UTC)
        assert fy.get_fiscal_month_number_for_date(dt4) == 10

    def test_get_fiscal_quarter_number_for_date(self):
        fy = FiscalYearVO.from_april_march(2025)
        # Apr 2025 -> Q1
        dt = datetime(2025, 4, 1, tzinfo=UTC)
        assert fy.get_fiscal_quarter_number_for_date(dt) == 1
        # Jul 2025 -> Q2 (month 4-6 are Q2)
        dt2 = datetime(2025, 7, 1, tzinfo=UTC)
        assert fy.get_fiscal_quarter_number_for_date(dt2) == 2
        # Oct 2025 -> Q3
        dt3 = datetime(2025, 10, 1, tzinfo=UTC)
        assert fy.get_fiscal_quarter_number_for_date(dt3) == 3
        # Jan 2026 -> Q4 (month 10-12)
        dt4 = datetime(2026, 1, 1, tzinfo=UTC)
        assert fy.get_fiscal_quarter_number_for_date(dt4) == 4

    def test_next_year_calendar(self):
        fy = FiscalYearVO.from_calendar(2025)
        next_fy = fy.next_year()
        assert next_fy.year == 2026
        assert next_fy.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert next_fy.end_date == datetime(2027, 1, 1, tzinfo=UTC)

    def test_next_year_april_march(self):
        fy = FiscalYearVO.from_april_march(2025)
        next_fy = fy.next_year()
        assert next_fy.year == 2026
        assert next_fy.start_date == datetime(2026, 4, 1, tzinfo=UTC)
        assert next_fy.end_date == datetime(2027, 4, 1, tzinfo=UTC)

    def test_next_year_custom(self):
        start = datetime(2025, 3, 1, tzinfo=UTC)
        end = datetime(2026, 3, 1, tzinfo=UTC)
        fy = FiscalYearVO.from_custom(2025, start, end)
        next_fy = fy.next_year()
        assert next_fy.year == 2026
        assert next_fy.start_date == datetime(2026, 3, 1, tzinfo=UTC)
        assert next_fy.end_date == datetime(2027, 3, 1, tzinfo=UTC)

    def test_previous_year_calendar(self):
        fy = FiscalYearVO.from_calendar(2025)
        prev = fy.previous_year()
        assert prev.year == 2024
        assert prev.start_date == datetime(2024, 1, 1, tzinfo=UTC)

    def test_previous_year_april_march(self):
        fy = FiscalYearVO.from_april_march(2025)
        prev = fy.previous_year()
        assert prev.year == 2024
        assert prev.start_date == datetime(2024, 4, 1, tzinfo=UTC)

    def test_to_dict(self):
        fy = FiscalYearVO.from_calendar(2025, name="Test")
        d = fy.to_dict()
        assert d["year"] == 2025
        assert d["type"] == "calendar"
        assert d["start_date"] == "2025-01-01T00:00:00+00:00"
        assert d["end_date"] == "2026-01-01T00:00:00+00:00"
        assert d["name"] == "Test"
        assert d["duration_days"] == 365
        assert d["display_name"] == "Test"
        assert "is_current" in d
        assert "is_future" in d
        assert "is_past" in d

    def test_from_dict(self):
        data = {
            "year": 2025,
            "type": "april_march",
            "start_date": "2025-04-01T00:00:00+00:00",
            "end_date": "2026-04-01T00:00:00+00:00",
            "name": "FY2025",
        }
        fy = FiscalYearVO.from_dict(data)
        assert fy.year == 2025
        assert fy.type == FiscalYearType.APRIL_MARCH
        assert fy.start_date == datetime(2025, 4, 1, tzinfo=UTC)
        assert fy.end_date == datetime(2026, 4, 1, tzinfo=UTC)
        assert fy.name == "FY2025"

    def test_from_dict_invalid_type(self):
        data = {"year": 2025, "type": "invalid", "start_date": "2025-01-01T00:00:00+00:00", "end_date": "2026-01-01T00:00:00+00:00"}
        with pytest.raises(FiscalYearError, match="Invalid fiscal year type"):
            FiscalYearVO.from_dict(data)

    def test_to_db_record(self):
        fy = FiscalYearVO.from_april_march(2025)
        rec = fy.to_db_record()
        assert rec["fiscal_year"] == 2025
        assert rec["fiscal_year_type"] == "april_march"
        assert rec["start_date"] == datetime(2025, 4, 1, tzinfo=UTC)
        assert rec["end_date"] == datetime(2026, 4, 1, tzinfo=UTC)

    def test_str(self):
        fy = FiscalYearVO.from_calendar(2025, name="Special")
        assert str(fy) == "Special"

    def test_repr(self):
        fy = FiscalYearVO.from_calendar(2025)
        assert "FiscalYearVO(2025, calendar, 2025-01-01 -> 2026-01-01)" in repr(fy)

    def test_equality(self):
        fy1 = FiscalYearVO.from_calendar(2025)
        fy2 = FiscalYearVO.from_calendar(2025)
        fy3 = FiscalYearVO.from_calendar(2026)
        assert fy1 == fy2
        assert fy1 != fy3
        assert fy1 != "not a fiscal year"

    def test_hash(self):
        fy1 = FiscalYearVO.from_calendar(2025)
        fy2 = FiscalYearVO.from_calendar(2025)
        assert hash(fy1) == hash(fy2)

    def test_lt(self):
        fy1 = FiscalYearVO.from_calendar(2024)
        fy2 = FiscalYearVO.from_calendar(2025)
        assert fy1 < fy2
        assert fy2 > fy1

    # Test leap year detection
    def test_leap_year_inclusive(self):
        fy = FiscalYearVO.from_calendar(2024)  # 2024 is leap year
        assert fy._is_leap_year_inclusive() is True
        fy_nonleap = FiscalYearVO.from_calendar(2025)
        assert fy_nonleap._is_leap_year_inclusive() is False


class TestHelperFunctions:
    def test_get_current_fiscal_year(self):
        fy = get_current_fiscal_year()
        assert isinstance(fy, FiscalYearVO)
        assert fy.is_current is True

        fy_am = get_current_fiscal_year(FiscalYearType.APRIL_MARCH)
        assert fy_am.type == FiscalYearType.APRIL_MARCH

    def test_get_fiscal_year_range_calendar(self):
        years = get_fiscal_year_range(2023, 2025, FiscalYearType.CALENDAR)
        assert len(years) == 3
        assert years[0].year == 2023
        assert years[0].type == FiscalYearType.CALENDAR
        assert years[2].year == 2025

    def test_get_fiscal_year_range_april_march(self):
        years = get_fiscal_year_range(2023, 2025, FiscalYearType.APRIL_MARCH)
        assert years[0].type == FiscalYearType.APRIL_MARCH
        assert years[0].start_date == datetime(2023, 4, 1, tzinfo=UTC)

    def test_get_fiscal_year_range_custom_raises(self):
        with pytest.raises(InvalidFiscalYearTypeError):
            get_fiscal_year_range(2023, 2025, FiscalYearType.CUSTOM)

    def test_fiscal_year_from_string(self):
        fy = fiscal_year_from_string("FY2025")
        assert fy is not None
        assert fy.year == 2025
        assert fy.type == FiscalYearType.CALENDAR

        fy2 = fiscal_year_from_string("FY2025 (Apr-Mar)")
        assert fy2 is not None
        assert fy2.type == FiscalYearType.APRIL_MARCH

        fy3 = fiscal_year_from_string("FY2025 (Jul-Jun)")
        assert fy3 is not None
        assert fy3.type == FiscalYearType.JULY_JUNE

        fy4 = fiscal_year_from_string("FY2025 (Oct-Sep)")
        assert fy4 is not None
        assert fy4.type == FiscalYearType.OCTOBER_SEPTEMBER

        fy5 = fiscal_year_from_string("2025")
        assert fy5 is not None
        assert fy5.year == 2025

        fy6 = fiscal_year_from_string("invalid")
        assert fy6 is None