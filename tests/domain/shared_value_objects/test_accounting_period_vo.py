# tests/domain/shared_value_objects/test_accounting_period_vo.py
"""
Comprehensive unit tests for domain/shared_value_objects/accounting_period_vo.py.
Covers all methods including factories, properties, business logic, and helpers.
All datetime is mocked to avoid flakiness.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from domain.shared_value_objects.accounting_period_vo import (
    AccountingPeriodVO,
    PeriodStatus,
    PeriodType,
    current_accounting_period,
    parse_period_range,
)

# ============================================================================
# Fixed datetime to avoid flaky tests
# ============================================================================

FIXED_NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def mock_datetime_now():
    """Mock datetime.now in accounting_period_vo to fixed time."""
    with patch("domain.shared_value_objects.accounting_period_vo.datetime") as mock_dt:
        mock_dt.now.return_value = FIXED_NOW
        mock_dt.UTC = UTC
        yield mock_dt


# ============================================================================
# Enum tests
# ============================================================================

class TestPeriodStatus:
    def test_members(self):
        assert PeriodStatus.DRAFT.value == "draft"
        assert PeriodStatus.OPEN.value == "open"
        assert PeriodStatus.LOCKED.value == "locked"
        assert PeriodStatus.CLOSED.value == "closed"

    def test_from_string(self):
        assert PeriodStatus.from_string("draft") == PeriodStatus.DRAFT
        assert PeriodStatus.from_string("OPEN") == PeriodStatus.OPEN
        assert PeriodStatus.from_string("Locked") == PeriodStatus.LOCKED
        assert PeriodStatus.from_string("CLOSED") == PeriodStatus.CLOSED
        with pytest.raises(ValueError, match="Invalid period status"):
            PeriodStatus.from_string("unknown")

    def test_can_post(self):
        assert PeriodStatus.OPEN.can_post() is True
        assert PeriodStatus.DRAFT.can_post() is False
        assert PeriodStatus.LOCKED.can_post() is False
        assert PeriodStatus.CLOSED.can_post() is False
        # idempotency_key parameter is accepted but has no effect
        assert PeriodStatus.OPEN.can_post("key") is True

    def test_can_adjust(self):
        assert PeriodStatus.OPEN.can_adjust() is True
        assert PeriodStatus.LOCKED.can_adjust() is True
        assert PeriodStatus.DRAFT.can_adjust() is False
        assert PeriodStatus.CLOSED.can_adjust() is False

    def test_can_close(self):
        assert PeriodStatus.OPEN.can_close() is True
        assert PeriodStatus.LOCKED.can_close() is True
        assert PeriodStatus.DRAFT.can_close() is True
        assert PeriodStatus.CLOSED.can_close() is False

    def test_can_open(self):
        assert PeriodStatus.DRAFT.can_open() is True
        assert PeriodStatus.CLOSED.can_open() is True
        assert PeriodStatus.OPEN.can_open() is False
        assert PeriodStatus.LOCKED.can_open() is False


class TestPeriodType:
    def test_members(self):
        assert PeriodType.MONTHLY.value == "monthly"
        assert PeriodType.QUARTERLY.value == "quarterly"
        assert PeriodType.YEARLY.value == "yearly"


# ============================================================================
# AccountingPeriodVO tests
# ============================================================================

class TestAccountingPeriodVO:
    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    def test_from_month(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        assert period.fiscal_year == 2026
        assert period.period_number == 7
        assert period.period_type == PeriodType.MONTHLY
        assert period.start_date == datetime(2026, 7, 1, tzinfo=UTC)
        assert period.end_date == datetime(2026, 8, 1, tzinfo=UTC)
        assert period.status == PeriodStatus.OPEN
        assert period.period_name == "Juli 2026"

        # With custom status
        period2 = AccountingPeriodVO.from_month(2026, 12, PeriodStatus.LOCKED)
        assert period2.end_date == datetime(2027, 1, 1, tzinfo=UTC)
        assert period2.status == PeriodStatus.LOCKED

        # With idempotency key (no effect)
        period3 = AccountingPeriodVO.from_month(2026, 1, idempotency_key="test-key")
        assert period3.period_number == 1

        # Invalid month
        with pytest.raises(ValueError, match="Monthly period number must be 1-12"):
            AccountingPeriodVO.from_month(2026, 13)

    def test_from_quarter(self):
        period = AccountingPeriodVO.from_quarter(2026, 2)
        assert period.fiscal_year == 2026
        assert period.period_number == 2
        assert period.period_type == PeriodType.QUARTERLY
        assert period.start_date == datetime(2026, 4, 1, tzinfo=UTC)
        assert period.end_date == datetime(2026, 7, 1, tzinfo=UTC)
        assert period.period_name == "Q2 2026"

        # Q4
        period2 = AccountingPeriodVO.from_quarter(2026, 4)
        assert period2.end_date == datetime(2027, 1, 1, tzinfo=UTC)

        # With custom status
        period3 = AccountingPeriodVO.from_quarter(2026, 1, PeriodStatus.CLOSED, closed_by="user")
        assert period3.status == PeriodStatus.CLOSED

        # Invalid quarter
        with pytest.raises(ValueError, match="Quarterly period number must be 1-4"):
            AccountingPeriodVO.from_quarter(2026, 5)

    def test_from_year(self):
        period = AccountingPeriodVO.from_year(2026)
        assert period.fiscal_year == 2026
        assert period.period_number == 1
        assert period.period_type == PeriodType.YEARLY
        assert period.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert period.end_date == datetime(2027, 1, 1, tzinfo=UTC)
        assert period.period_name == "FY 2026"

        # With custom status
        period2 = AccountingPeriodVO.from_year(2026, PeriodStatus.CLOSED, closed_by="user")
        assert period2.status == PeriodStatus.CLOSED

    def test_from_custom(self):
        start = datetime(2026, 7, 15, tzinfo=UTC)
        end = datetime(2026, 8, 15, tzinfo=UTC)
        period = AccountingPeriodVO.from_custom(start, end)
        assert period.fiscal_year == 2026
        assert period.period_number == 0
        assert period.period_type == PeriodType.MONTHLY
        assert period.start_date == start
        assert period.end_date == end
        assert period.status == PeriodStatus.OPEN

        # With non-UTC datetime (should be normalized)
        start_naive = datetime(2026, 7, 15)
        end_naive = datetime(2026, 8, 15)
        period2 = AccountingPeriodVO.from_custom(start_naive, end_naive)
        assert period2.start_date.tzinfo == UTC
        assert period2.end_date.tzinfo == UTC

    def test_from_string_monthly(self):
        period = AccountingPeriodVO.from_string("2026-07")
        assert period.fiscal_year == 2026
        assert period.period_number == 7
        assert period.period_type == PeriodType.MONTHLY
        assert period.period_name == "Juli 2026"

        # With spaces
        period2 = AccountingPeriodVO.from_string(" 2026-01 ")
        assert period2.period_number == 1

    def test_from_string_quarterly(self):
        period = AccountingPeriodVO.from_string("2026-Q2")
        assert period.fiscal_year == 2026
        assert period.period_number == 2
        assert period.period_type == PeriodType.QUARTERLY
        assert period.period_name == "Q2 2026"

        # With spaces and lowercase
        period2 = AccountingPeriodVO.from_string(" 2026-q3 ")
        assert period2.period_number == 3

    def test_from_string_yearly(self):
        period = AccountingPeriodVO.from_string("2026")
        assert period.fiscal_year == 2026
        assert period.period_number == 1
        assert period.period_type == PeriodType.YEARLY
        assert period.period_name == "FY 2026"

    def test_from_string_invalid(self):
        with pytest.raises(ValueError):
            AccountingPeriodVO.from_string("invalid")

    # ------------------------------------------------------------------------
    # Construction validation
    # ------------------------------------------------------------------------

    def test_construction_valid(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        period = AccountingPeriodVO(
            fiscal_year=2026,
            period_number=7,
            start_date=start,
            end_date=end,
            status=PeriodStatus.OPEN,
            period_type=PeriodType.MONTHLY,
        )
        assert period.fiscal_year == 2026
        assert period.start_date == start

    def test_construction_start_after_end(self):
        start = datetime(2026, 8, 1, tzinfo=UTC)
        end = datetime(2026, 7, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="start_date must be before end_date"):
            AccountingPeriodVO(
                fiscal_year=2026,
                period_number=7,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
            )

    def test_construction_closed_without_closed_by(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Closed period must have closed_by"):
            AccountingPeriodVO(
                fiscal_year=2026,
                period_number=7,
                start_date=start,
                end_date=end,
                status=PeriodStatus.CLOSED,
            )

    def test_construction_closed_without_closed_at(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Closed period must have closed_at"):
            AccountingPeriodVO(
                fiscal_year=2026,
                period_number=7,
                start_date=start,
                end_date=end,
                status=PeriodStatus.CLOSED,
                closed_by="user",
            )

    def test_construction_non_closed_with_closed_by(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Non-closed period cannot have closed_by"):
            AccountingPeriodVO(
                fiscal_year=2026,
                period_number=7,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
                closed_by="user",
            )

    def test_construction_invalid_period_type(self):
        start = datetime(2026, 7, 1, tzinfo=UTC)
        end = datetime(2026, 8, 1, tzinfo=UTC)
        with pytest.raises(ValueError, match="Unknown period type"):
            AccountingPeriodVO(
                fiscal_year=2026,
                period_number=7,
                start_date=start,
                end_date=end,
                status=PeriodStatus.OPEN,
                period_type="invalid",  # type: ignore
            )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    def test_period_name_monthly(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        assert period.period_name == "Juli 2026"
        period2 = AccountingPeriodVO.from_month(2026, 1)
        assert period2.period_name == "Januari 2026"
        period3 = AccountingPeriodVO.from_month(2026, 12)
        assert period3.period_name == "Desember 2026"

    def test_period_name_quarterly(self):
        period = AccountingPeriodVO.from_quarter(2026, 2)
        assert period.period_name == "Q2 2026"

    def test_period_name_yearly(self):
        period = AccountingPeriodVO.from_year(2026)
        assert period.period_name == "FY 2026"

    def test_status_properties(self):
        period_open = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.OPEN)
        assert period_open.is_open is True
        assert period_open.is_locked is False
        assert period_open.is_closed is False
        assert period_open.is_draft is False

        period_locked = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.LOCKED)
        assert period_locked.is_open is False
        assert period_locked.is_locked is True
        assert period_locked.is_closed is False
        assert period_locked.is_draft is False

        period_closed = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.CLOSED, closed_by="user", closed_at=FIXED_NOW)
        assert period_closed.is_open is False
        assert period_closed.is_locked is False
        assert period_closed.is_closed is True
        assert period_closed.is_draft is False

        period_draft = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.DRAFT)
        assert period_draft.is_open is False
        assert period_draft.is_locked is False
        assert period_draft.is_closed is False
        assert period_draft.is_draft is True

    def test_duration_days(self):
        period = AccountingPeriodVO.from_month(2026, 1)  # 31 days
        assert period.duration_days == 31
        period2 = AccountingPeriodVO.from_month(2026, 2)  # 28 days
        assert period2.duration_days == 28
        period3 = AccountingPeriodVO.from_year(2026)  # 365 days
        assert period3.duration_days == 365

    def test_duration_seconds(self):
        period = AccountingPeriodVO.from_month(2026, 1)
        assert period.duration_seconds == 31 * 24 * 3600

    def test_next_period_monthly(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        next_p = period.next_period
        assert next_p is not None
        assert next_p.fiscal_year == 2026
        assert next_p.period_number == 8
        assert next_p.period_type == PeriodType.MONTHLY

        # December -> next year January
        period2 = AccountingPeriodVO.from_month(2026, 12)
        next_p2 = period2.next_period
        assert next_p2 is not None
        assert next_p2.fiscal_year == 2027
        assert next_p2.period_number == 1

        # Year > 2100 returns None
        period3 = AccountingPeriodVO.from_month(2101, 1)
        next_p3 = period3.next_period
        assert next_p3 is None

    def test_next_period_quarterly(self):
        period = AccountingPeriodVO.from_quarter(2026, 2)
        next_p = period.next_period
        assert next_p is not None
        assert next_p.period_number == 3

        # Q4 -> next year Q1
        period2 = AccountingPeriodVO.from_quarter(2026, 4)
        next_p2 = period2.next_period
        assert next_p2.fiscal_year == 2027
        assert next_p2.period_number == 1

    def test_next_period_yearly(self):
        period = AccountingPeriodVO.from_year(2026)
        next_p = period.next_period
        assert next_p is not None
        assert next_p.fiscal_year == 2027

        # Year > 2100 returns None
        period2 = AccountingPeriodVO.from_year(2101)
        next_p2 = period2.next_period
        assert next_p2 is None

    def test_previous_period_monthly(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        prev_p = period.previous_period
        assert prev_p is not None
        assert prev_p.fiscal_year == 2026
        assert prev_p.period_number == 6

        # January -> previous year December
        period2 = AccountingPeriodVO.from_month(2026, 1)
        prev_p2 = period2.previous_period
        assert prev_p2 is not None
        assert prev_p2.fiscal_year == 2025
        assert prev_p2.period_number == 12

        # Year < 1970 returns None
        period3 = AccountingPeriodVO.from_month(1969, 1)
        prev_p3 = period3.previous_period
        assert prev_p3 is None

    def test_previous_period_quarterly(self):
        period = AccountingPeriodVO.from_quarter(2026, 2)
        prev_p = period.previous_period
        assert prev_p is not None
        assert prev_p.period_number == 1

        # Q1 -> previous year Q4
        period2 = AccountingPeriodVO.from_quarter(2026, 1)
        prev_p2 = period2.previous_period
        assert prev_p2.fiscal_year == 2025
        assert prev_p2.period_number == 4

    def test_previous_period_yearly(self):
        period = AccountingPeriodVO.from_year(2026)
        prev_p = period.previous_period
        assert prev_p is not None
        assert prev_p.fiscal_year == 2025

    def test_as_tuple(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        assert period.as_tuple == (2026, 7, "monthly")

        period2 = AccountingPeriodVO.from_quarter(2026, 2)
        assert period2.as_tuple == (2026, 2, "quarterly")

        period3 = AccountingPeriodVO.from_year(2026)
        assert period3.as_tuple == (2026, 1, "yearly")

    # ------------------------------------------------------------------------
    # Business logic methods
    # ------------------------------------------------------------------------

    def test_contains(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        # Inside period
        dt = datetime(2026, 7, 15, tzinfo=UTC)
        assert period.contains(dt) is True
        # Start inclusive
        dt2 = datetime(2026, 7, 1, tzinfo=UTC)
        assert period.contains(dt2) is True
        # End exclusive
        dt3 = datetime(2026, 8, 1, tzinfo=UTC)
        assert period.contains(dt3) is False
        # Before start
        dt4 = datetime(2026, 6, 30, tzinfo=UTC)
        assert period.contains(dt4) is False
        # After end
        dt5 = datetime(2026, 8, 2, tzinfo=UTC)
        assert period.contains(dt5) is False
        # Naive datetime
        dt_naive = datetime(2026, 7, 15)
        assert period.contains(dt_naive) is True

    def test_contains_date_alias(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        dt = datetime(2026, 7, 15, tzinfo=UTC)
        assert period.contains_date(dt) is True

    def test_overlaps(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)  # 7/1 - 8/1
        p2 = AccountingPeriodVO.from_month(2026, 7)  # same
        assert p1.overlaps(p2) is True

        p3 = AccountingPeriodVO.from_month(2026, 6)  # 6/1 - 7/1
        assert p1.overlaps(p3) is True  # shares boundary (7/1)

        p4 = AccountingPeriodVO.from_month(2026, 8)  # 8/1 - 9/1
        assert p1.overlaps(p4) is True  # shares boundary (8/1)

        p5 = AccountingPeriodVO.from_month(2026, 5)  # 5/1 - 6/1
        assert p1.overlaps(p5) is False

        p6 = AccountingPeriodVO.from_month(2026, 9)  # 9/1 - 10/1
        assert p1.overlaps(p6) is False

    def test_close(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        closed = period.close("user123")
        assert closed is not period
        assert closed.status == PeriodStatus.CLOSED
        assert closed.closed_by == "user123"
        assert closed.closed_at == FIXED_NOW

        # Closed period close returns self (idempotent)
        closed2 = closed.close("other")
        assert closed2 is closed

        # With custom closed_at
        custom_closed_at = datetime(2026, 7, 31, tzinfo=UTC)
        closed3 = period.close("user", custom_closed_at)
        assert closed3.closed_at == custom_closed_at

    def test_lock(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        locked = period.lock("user")
        assert locked is not period
        assert locked.status == PeriodStatus.LOCKED
        assert locked.period_type == PeriodType.MONTHLY

        # Lock already locked returns self (idempotent)
        locked2 = locked.lock("other")
        assert locked2 is locked

        # Cannot lock closed
        closed = period.close("user")
        with pytest.raises(ValueError, match="Cannot lock a closed period"):
            closed.lock("user")

    def test_unlock(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        locked = period.lock("user")
        unlocked = locked.unlock()
        assert unlocked is not locked
        assert unlocked.status == PeriodStatus.OPEN

        # Unlock already open returns self (idempotent)
        unlocked2 = unlocked.unlock()
        assert unlocked2 is unlocked

        # Cannot unlock closed
        closed = period.close("user")
        with pytest.raises(ValueError, match="Cannot unlock a closed period"):
            closed.unlock()

    def test_open(self):
        # DRAFT -> OPEN
        draft = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.DRAFT)
        opened = draft.open("user")
        assert opened is not draft
        assert opened.status == PeriodStatus.OPEN

        # CLOSED -> OPEN
        closed = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.CLOSED, closed_by="user", closed_at=FIXED_NOW)
        reopened = closed.open("user")
        assert reopened is not closed
        assert reopened.status == PeriodStatus.OPEN
        assert reopened.closed_by is None
        assert reopened.closed_at is None

        # OPEN -> OPEN (idempotent)
        period = AccountingPeriodVO.from_month(2026, 7)
        opened2 = period.open("user")
        assert opened2 is period

        # Invalid status
        locked = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.LOCKED)
        with pytest.raises(ValueError, match="Cannot open period with status locked"):
            locked.open("user")

    def test_with_status(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        # OPEN -> LOCKED
        locked = period.with_status(PeriodStatus.LOCKED, "user")
        assert locked.status == PeriodStatus.LOCKED

        # LOCKED -> OPEN
        reopened = locked.with_status(PeriodStatus.OPEN)
        assert reopened.status == PeriodStatus.OPEN

        # OPEN -> CLOSED
        closed = period.with_status(PeriodStatus.CLOSED, "user")
        assert closed.status == PeriodStatus.CLOSED
        assert closed.closed_by == "user"

        # CLOSED -> DRAFT
        draft = closed.with_status(PeriodStatus.DRAFT)
        assert draft.status == PeriodStatus.DRAFT

        # Same status (idempotent)
        same = period.with_status(PeriodStatus.OPEN)
        assert same is period

        # Unknown status
        with pytest.raises(ValueError, match="Unknown status"):
            period.with_status("invalid")  # type: ignore

    # ------------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------------

    def test_is_same_period(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)
        p2 = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.CLOSED, closed_by="user", closed_at=FIXED_NOW)
        assert p1.is_same_period(p2) is True
        assert p2.is_same_period(p1) is True

        p3 = AccountingPeriodVO.from_month(2026, 8)
        assert p1.is_same_period(p3) is False

        p4 = AccountingPeriodVO.from_quarter(2026, 2)
        assert p1.is_same_period(p4) is False

    def test_is_before(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)   # 7/1 - 8/1
        p2 = AccountingPeriodVO.from_month(2026, 8)   # 8/1 - 9/1
        assert p1.is_before(p2) is True   # ends at 8/1, other starts at 8/1
        assert p2.is_before(p1) is False

        p3 = AccountingPeriodVO.from_month(2026, 6)   # 6/1 - 7/1
        assert p1.is_before(p3) is False  # p1 starts at 7/1, p3 ends at 7/1

    def test_is_after(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)   # 7/1 - 8/1
        p2 = AccountingPeriodVO.from_month(2026, 6)   # 6/1 - 7/1
        assert p1.is_after(p2) is True   # starts at 7/1, other ends at 7/1
        assert p2.is_after(p1) is False

        p3 = AccountingPeriodVO.from_month(2026, 8)   # 8/1 - 9/1
        assert p1.is_after(p3) is False  # p1 ends at 8/1, other starts at 8/1

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def test_to_dict(self):
        period = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.OPEN)
        d = period.to_dict()
        assert d["fiscal_year"] == 2026
        assert d["period_number"] == 7
        assert d["period_name"] == "Juli 2026"
        assert d["status"] == "open"
        assert d["period_type"] == "monthly"
        assert d["duration_days"] == 31
        assert "start_date" in d
        assert "end_date" in d

        # Closed period
        closed = period.close("user")
        d2 = closed.to_dict()
        assert d2["closed_by"] == "user"
        assert d2["closed_at"] is not None

    def test_from_dict(self):
        data = {
            "fiscal_year": 2026,
            "period_number": 7,
            "start_date": "2026-07-01T00:00:00+00:00",
            "end_date": "2026-08-01T00:00:00+00:00",
            "status": "open",
            "period_type": "monthly",
            "closed_by": None,
            "closed_at": None,
        }
        period = AccountingPeriodVO.from_dict(data)
        assert period.fiscal_year == 2026
        assert period.period_number == 7
        assert period.status == PeriodStatus.OPEN

        # With closed data
        data2 = data.copy()
        data2["status"] = "closed"
        data2["closed_by"] = "user"
        data2["closed_at"] = "2026-07-31T12:00:00+00:00"
        period2 = AccountingPeriodVO.from_dict(data2)
        assert period2.status == PeriodStatus.CLOSED
        assert period2.closed_by == "user"

    def test_to_db_format(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        db = period.to_db_format()
        assert db["fiscal_year"] == 2026
        assert db["period_number"] == 7
        assert db["period_type"] == "monthly"
        assert db["status"] == "open"
        assert db["start_date"] == period.start_date
        assert db["end_date"] == period.end_date

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def test_str(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        assert str(period) == "Juli 2026 (open)"
        closed = period.close("user")
        assert str(closed) == "Juli 2026 (closed)"

    def test_repr(self):
        period = AccountingPeriodVO.from_month(2026, 7)
        assert repr(period) == "AccountingPeriodVO('Juli 2026', status=open)"

    def test_equality(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)
        p2 = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.CLOSED, closed_by="user", closed_at=FIXED_NOW)
        assert p1 == p2  # equality ignores status

        p3 = AccountingPeriodVO.from_month(2026, 8)
        assert p1 != p3

        p4 = AccountingPeriodVO.from_quarter(2026, 2)
        assert p1 != p4

        assert p1 != "string"

    def test_hash(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)
        p2 = AccountingPeriodVO.from_month(2026, 7, PeriodStatus.CLOSED, closed_by="user", closed_at=FIXED_NOW)
        assert hash(p1) == hash(p2)

        p3 = AccountingPeriodVO.from_month(2026, 8)
        assert hash(p1) != hash(p3)

    def test_lt(self):
        p1 = AccountingPeriodVO.from_month(2026, 7)
        p2 = AccountingPeriodVO.from_month(2026, 8)
        p3 = AccountingPeriodVO.from_month(2025, 12)
        assert p3 < p1 < p2
        assert p1 < p2
        assert p2 > p1


# ============================================================================
# Helper function tests
# ============================================================================

def test_current_accounting_period():
    period = current_accounting_period()
    assert period.fiscal_year == 2026
    assert period.period_number == 7
    assert period.period_type == PeriodType.MONTHLY
    assert period.status == PeriodStatus.OPEN


def test_parse_period_range_same_type():
    start = AccountingPeriodVO.from_month(2026, 7)
    end = AccountingPeriodVO.from_month(2026, 10)
    result = parse_period_range(start, end)
    assert len(result) == 4
    assert result[0] == start
    assert result[1] == AccountingPeriodVO.from_month(2026, 8)
    assert result[2] == AccountingPeriodVO.from_month(2026, 9)
    assert result[3] == end

    # Single period
    result2 = parse_period_range(start, start)
    assert len(result2) == 1
    assert result2[0] == start


def test_parse_period_range_different_types_raises():
    start = AccountingPeriodVO.from_month(2026, 7)
    end = AccountingPeriodVO.from_quarter(2026, 2)
    with pytest.raises(ValueError, match="Period types must match"):
        parse_period_range(start, end)


def test_parse_period_range_start_after_end_raises():
    start = AccountingPeriodVO.from_month(2026, 10)
    end = AccountingPeriodVO.from_month(2026, 7)
    with pytest.raises(ValueError, match="Start period must be before or equal to end period"):
        parse_period_range(start, end)


def test_parse_period_range_year_boundary():
    start = AccountingPeriodVO.from_month(2026, 11)
    end = AccountingPeriodVO.from_month(2027, 1)
    result = parse_period_range(start, end)
    assert len(result) == 3
    assert result[0] == AccountingPeriodVO.from_month(2026, 11)
    assert result[1] == AccountingPeriodVO.from_month(2026, 12)
    assert result[2] == AccountingPeriodVO.from_month(2027, 1)


def test_parse_period_range_quarterly():
    start = AccountingPeriodVO.from_quarter(2026, 1)
    end = AccountingPeriodVO.from_quarter(2026, 3)
    result = parse_period_range(start, end)
    assert len(result) == 3
    assert result[0] == start
    assert result[1] == AccountingPeriodVO.from_quarter(2026, 2)
    assert result[2] == end


def test_parse_period_range_yearly():
    start = AccountingPeriodVO.from_year(2026)
    end = AccountingPeriodVO.from_year(2028)
    result = parse_period_range(start, end)
    assert len(result) == 3
    assert result[0] == AccountingPeriodVO.from_year(2026)
    assert result[1] == AccountingPeriodVO.from_year(2027)
    assert result[2] == AccountingPeriodVO.from_year(2028)
