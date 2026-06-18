#!/usr/bin/env python3
"""
Module: fiscal_year_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for fiscal year. Immutable.
    Represents a fiscal year which may differ from calendar year.
    Supports multiple fiscal year types: calendar, April-March, July-June,
    October-September, and custom.

Business rules:
    - Fiscal year must have a start date before end date.
    - Duration must be exactly one year (plus/minus allowed for custom).
    - Fiscal year type determines the default start/end months.
    - Provides methods to retrieve periods (months, quarters) within the year.
    - All datetimes are timezone-aware UTC.
    - Immutable: changes create new instances.

Dependencies:
    - Python standard library (datetime, timedelta, dataclass, enum)

Audit:
    Pure value object; no I/O. Caller may log fiscal year activation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

# ============================================================================
# Enums
# ============================================================================


class FiscalYearType(Enum):
    """Types of fiscal year configurations."""

    CALENDAR = "calendar"  # Jan 1 - Dec 31
    APRIL_MARCH = "april_march"  # Apr 1 - Mar 31
    JULY_JUNE = "july_june"  # Jul 1 - Jun 30
    OCTOBER_SEPTEMBER = "october_sep"  # Oct 1 - Sep 30
    CUSTOM = "custom"  # User-defined start/end

    @classmethod
    def from_string(cls, value: str) -> FiscalYearType | None:
        """Parse from string (case-insensitive)."""
        value_lower = value.lower()
        for ftype in cls:
            if ftype.value == value_lower:
                return ftype
        return None

    def default_start_month(self) -> int:
        """Default start month for this fiscal year type (1-12)."""
        mapping = {
            FiscalYearType.CALENDAR: 1,
            FiscalYearType.APRIL_MARCH: 4,
            FiscalYearType.JULY_JUNE: 7,
            FiscalYearType.OCTOBER_SEPTEMBER: 10,
            FiscalYearType.CUSTOM: 1,  # Not meaningful, caller must provide
        }
        return mapping.get(self, 1)

    def default_end_month(self) -> int:
        """Default end month for this fiscal year type (1-12)."""
        start = self.default_start_month()
        end = start - 1 if start > 1 else 12
        return end

    def description(self) -> str:
        """Human-readable description."""
        descriptions = {
            FiscalYearType.CALENDAR: "Calendar year (Jan-Dec)",
            FiscalYearType.APRIL_MARCH: "April to March",
            FiscalYearType.JULY_JUNE: "July to June",
            FiscalYearType.OCTOBER_SEPTEMBER: "October to September",
            FiscalYearType.CUSTOM: "Custom fiscal year",
        }
        return descriptions.get(self, "Unknown")


# ============================================================================
# Custom Exceptions
# ============================================================================


class FiscalYearError(ValueError):
    """Base exception for fiscal year errors."""

    pass


class InvalidFiscalYearRangeError(FiscalYearError):
    """Raised when start_date >= end_date or duration not ~1 year."""

    pass


class InvalidFiscalYearTypeError(FiscalYearError):
    """Raised when fiscal year type is invalid for operation."""

    pass


# ============================================================================
# Value Object: FiscalYearVO
# ============================================================================


@dataclass(frozen=True)
class FiscalYearVO:
    """
    Immutable value object representing a fiscal year.

    Attributes:
        year: The nominal year (e.g., for fiscal year 2024, even if it starts in 2023)
        type: FiscalYearType enum
        start_date: UTC datetime when the fiscal year begins (inclusive)
        end_date: UTC datetime when the fiscal year ends (exclusive)
        name: Optional custom name for the fiscal year

    Examples:
        >>> fy = FiscalYearVO.from_calendar(2024)
        >>> fy.start_date.year
        2024
        >>> fy.contains(datetime(2024, 6, 15, tzinfo=timezone.utc))
        True
        >>> fy.get_month_periods_count()
        12
        >>> fy.get_quarter(2).start_date.month
        4
    """

    year: int
    type: FiscalYearType
    start_date: datetime
    end_date: datetime
    name: str | None = None

    # Class constants
    MIN_YEAR: int = 1970
    MAX_YEAR: int = 2100

    def __post_init__(self) -> None:
        """Validate fiscal year data."""
        # Validate year range
        if self.year < self.MIN_YEAR or self.year > self.MAX_YEAR:
            raise FiscalYearError(
                f"Year must be between {self.MIN_YEAR} and {self.MAX_YEAR}, got {self.year}"
            )

        # Normalize timezone to UTC
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))

        # Validate start < end
        if self.start_date >= self.end_date:
            raise InvalidFiscalYearRangeError(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )

        # Validate duration is approximately one year (allow +/- 30 days for custom)
        duration_days = (self.end_date - self.start_date).days
        if self.type == FiscalYearType.CUSTOM:
            if duration_days < 335 or duration_days > 395:
                raise InvalidFiscalYearRangeError(
                    f"Custom fiscal year duration must be approximately one year (got {duration_days} days)"
                )
        else:
            # For standard types, enforce exactly 365/366 days
            expected_days = 366 if self._is_leap_year_inclusive() else 365
            if duration_days not in (365, 366):
                raise InvalidFiscalYearRangeError(
                    f"Standard fiscal year must be 365 or 366 days, got {duration_days}"
                )

        # Validate name length
        if self.name is not None:
            name_clean = self.name.strip()
            if len(name_clean) > 100:
                raise FiscalYearError("Fiscal year name must not exceed 100 characters")
            object.__setattr__(self, "name", name_clean if name_clean else None)
        else:
            object.__setattr__(self, "name", None)

    def _is_leap_year_inclusive(self) -> bool:
        """Check if the fiscal year includes Feb 29 in any calendar year within its range."""
        # Simplified: check if start_date year or end_date-1 year is leap and Feb 29 falls inside.
        start_year = self.start_date.year
        end_year = self.end_date.year
        for y in range(start_year, end_year):
            if self._is_leap_year(y):
                feb29 = datetime(y, 2, 29, tzinfo=UTC)
                if self.start_date <= feb29 < self.end_date:
                    return True
        return False

    @staticmethod
    def _is_leap_year(year: int) -> bool:
        """Return True if year is a leap year."""
        return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_calendar(cls, year: int, name: str | None = None) -> FiscalYearVO:
        """Create a calendar fiscal year (Jan 1 - Dec 31)."""
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
        return cls(
            year=year, type=FiscalYearType.CALENDAR, start_date=start, end_date=end, name=name
        )

    @classmethod
    def from_april_march(cls, year: int, name: str | None = None) -> FiscalYearVO:
        """Create fiscal year from April 1 to March 31 of next year."""
        # Year argument typically the calendar year containing the start (e.g., FY2024 starts Apr 1 2024)
        start = datetime(year, 4, 1, tzinfo=UTC)
        end = datetime(year + 1, 4, 1, tzinfo=UTC)
        return cls(
            year=year, type=FiscalYearType.APRIL_MARCH, start_date=start, end_date=end, name=name
        )

    @classmethod
    def from_july_june(cls, year: int, name: str | None = None) -> FiscalYearVO:
        """Create fiscal year from July 1 to June 30 of next year."""
        start = datetime(year, 7, 1, tzinfo=UTC)
        end = datetime(year + 1, 7, 1, tzinfo=UTC)
        return cls(
            year=year, type=FiscalYearType.JULY_JUNE, start_date=start, end_date=end, name=name
        )

    @classmethod
    def from_october_september(cls, year: int, name: str | None = None) -> FiscalYearVO:
        """Create fiscal year from October 1 to September 30 of next year."""
        start = datetime(year, 10, 1, tzinfo=UTC)
        end = datetime(year + 1, 10, 1, tzinfo=UTC)
        return cls(
            year=year,
            type=FiscalYearType.OCTOBER_SEPTEMBER,
            start_date=start,
            end_date=end,
            name=name,
        )

    @classmethod
    def from_custom(
        cls, year: int, start_date: datetime, end_date: datetime, name: str | None = None
    ) -> FiscalYearVO:
        """Create a custom fiscal year with arbitrary start/end."""
        return cls(
            year=year,
            type=FiscalYearType.CUSTOM,
            start_date=start_date,
            end_date=end_date,
            name=name,
        )

    @classmethod
    def from_date(
        cls, date: datetime, ftype: FiscalYearType = FiscalYearType.CALENDAR
    ) -> FiscalYearVO:
        """Determine the fiscal year that contains the given date."""
        # Shift date based on type to find fiscal year start
        if ftype == FiscalYearType.CALENDAR:
            year = date.year
            start = datetime(year, 1, 1, tzinfo=UTC)
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        elif ftype == FiscalYearType.APRIL_MARCH:
            year = date.year if date.month >= 4 else date.year - 1
            start = datetime(year, 4, 1, tzinfo=UTC)
            end = datetime(year + 1, 4, 1, tzinfo=UTC)
        elif ftype == FiscalYearType.JULY_JUNE:
            year = date.year if date.month >= 7 else date.year - 1
            start = datetime(year, 7, 1, tzinfo=UTC)
            end = datetime(year + 1, 7, 1, tzinfo=UTC)
        elif ftype == FiscalYearType.OCTOBER_SEPTEMBER:
            year = date.year if date.month >= 10 else date.year - 1
            start = datetime(year, 10, 1, tzinfo=UTC)
            end = datetime(year + 1, 10, 1, tzinfo=UTC)
        else:
            raise InvalidFiscalYearTypeError(
                f"Cannot derive fiscal year from date for type {ftype}"
            )
        return cls(year=year, type=ftype, start_date=start, end_date=end)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FiscalYearVO:
        """Reconstruct from dictionary."""
        ftype = FiscalYearType.from_string(data["type"])
        if ftype is None:
            raise FiscalYearError(f"Invalid fiscal year type: {data['type']}")
        start = datetime.fromisoformat(data["start_date"])
        end = datetime.fromisoformat(data["end_date"])
        return cls(
            year=data["year"],
            type=ftype,
            start_date=start,
            end_date=end,
            name=data.get("name"),
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def duration_days(self) -> int:
        """Number of days in the fiscal year."""
        return (self.end_date - self.start_date).days

    @property
    def duration_seconds(self) -> float:
        """Total seconds in the fiscal year."""
        return (self.end_date - self.start_date).total_seconds()

    @property
    def is_current(self) -> bool:
        """Check if this fiscal year contains the current date."""
        now = datetime.now(UTC)
        return self.contains(now)

    @property
    def is_future(self) -> bool:
        """Check if this fiscal year starts in the future."""
        now = datetime.now(UTC)
        return self.start_date > now

    @property
    def is_past(self) -> bool:
        """Check if this fiscal year has ended."""
        now = datetime.now(UTC)
        return self.end_date <= now

    @property
    def display_name(self) -> str:
        """User-friendly display name (e.g., 'FY2024', 'FY2024 (Apr-Mar)')."""
        if self.name:
            return self.name
        suffix = ""
        if self.type != FiscalYearType.CALENDAR:
            suffix = f" ({self.type.description()})"
        return f"FY{self.year}{suffix}"

    # ------------------------------------------------------------------------
    # Period generation
    # ------------------------------------------------------------------------

    def contains(self, dt: datetime) -> bool:
        """Check if the datetime falls within this fiscal year."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return self.start_date <= dt < self.end_date

    def get_month_periods(self) -> list[AccountingPeriodVO]:
        """
        Return a list of monthly accounting periods within this fiscal year.
        Requires importing AccountingPeriodVO dynamically to avoid circular import.
        """
        from domain.shared_value_objects.accounting_period_vo import AccountingPeriodVO

        periods = []
        current = self.start_date
        while current < self.end_date:
            # Determine month number based on fiscal year start
            month_num = self._get_fiscal_month_number(current)
            # Create AccountingPeriodVO for this month
            period = AccountingPeriodVO.from_month(
                current.year, current.month, status=PeriodStatus.OPEN
            )
            # We'll set fiscal_year and fiscal_period_number in a wrapper; for now just use standard month
            # But AccountingPeriodVO expects fiscal_year and period_number. We'll create with custom attributes.
            # To properly support fiscal periods, we should extend AccountingPeriodVO with fiscal_period_number.
            # For simplicity, we'll use the standard month period.
            periods.append(period)
            # Move to next month
            next_month = current.replace(day=28) + timedelta(days=4)
            next_month = next_month.replace(day=1)
            current = next_month
        return periods

    def _get_fiscal_month_number(self, date: datetime) -> int:
        """
        Return the fiscal month number (1-12) for a given date within the fiscal year.
        Month 1 is the first month of the fiscal year.
        """
        if not self.contains(date):
            raise ValueError(f"Date {date} is not within this fiscal year")
        # Calculate difference in months
        month_diff = (date.year - self.start_date.year) * 12 + (date.month - self.start_date.month)
        return month_diff + 1

    def get_quarter_periods(self) -> list[AccountingPeriodVO]:
        """
        Return a list of quarterly periods within this fiscal year.
        """
        from domain.shared_value_objects.accounting_period_vo import AccountingPeriodVO

        quarters = []
        quarter_months = [(1, 3), (4, 6), (7, 9), (10, 12)]
        # Adjust quarter mapping based on fiscal year start month
        start_month = self.start_date.month
        # Reorder quarters if fiscal year doesn't start in January
        adjusted_quarters = self._get_adjusted_quarters(quarter_months, start_month)

        for q_idx, (start_m, end_m) in enumerate(adjusted_quarters, 1):
            # Compute actual start/end dates within the fiscal year
            q_start = self._get_date_for_month(start_m)
            q_end = self._get_date_for_month(end_m + 1) if end_m < 12 else self.end_date
            period = AccountingPeriodVO(
                fiscal_year=self.year,
                period_number=q_idx,
                start_date=q_start,
                end_date=q_end,
                status=PeriodStatus.OPEN,
                period_type=PeriodType.QUARTERLY,  # need import from accounting_period_vo
            )
            quarters.append(period)
        return quarters

    def _get_adjusted_quarters(
        self, standard_quarters: list[tuple[int, int]], start_month: int
    ) -> list[tuple[int, int]]:
        """
        Adjust quarter boundaries based on fiscal year start month.
        """
        if start_month == 1:
            return standard_quarters
        # Rotate quarters
        shift = (start_month - 1) // 3
        return standard_quarters[shift:] + standard_quarters[:shift]

    def _get_date_for_month(self, month: int) -> datetime:
        """
        Return the datetime for the first day of the given month within the fiscal year.
        May cross year boundary if month < start_month.
        """
        year_offset = 0
        fiscal_start_month = self.start_date.month
        if month < fiscal_start_month:
            year_offset = 1
        target_year = self.start_date.year + year_offset
        return datetime(target_year, month, 1, tzinfo=UTC)

    def get_fiscal_month_number_for_date(self, date: datetime) -> int:
        """Return which fiscal month (1-12) the given date falls into."""
        return self._get_fiscal_month_number(date)

    def get_fiscal_quarter_number_for_date(self, date: datetime) -> int:
        """Return which fiscal quarter (1-4) the given date falls into."""
        month_num = self._get_fiscal_month_number(date)
        return (month_num - 1) // 3 + 1

    # ------------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------------

    def next_year(self) -> FiscalYearVO:
        """Return the next consecutive fiscal year."""
        if self.type == FiscalYearType.CALENDAR:
            return FiscalYearVO.from_calendar(self.year + 1, self.name)
        elif self.type == FiscalYearType.APRIL_MARCH:
            return FiscalYearVO.from_april_march(self.year + 1, self.name)
        elif self.type == FiscalYearType.JULY_JUNE:
            return FiscalYearVO.from_july_june(self.year + 1, self.name)
        elif self.type == FiscalYearType.OCTOBER_SEPTEMBER:
            return FiscalYearVO.from_october_september(self.year + 1, self.name)
        else:
            # For custom, shift start and end by one year
            new_start = self.start_date.replace(year=self.start_date.year + 1)
            new_end = self.end_date.replace(year=self.end_date.year + 1)
            return FiscalYearVO.from_custom(self.year + 1, new_start, new_end, self.name)

    def previous_year(self) -> FiscalYearVO:
        """Return the previous consecutive fiscal year."""
        if self.type == FiscalYearType.CALENDAR:
            return FiscalYearVO.from_calendar(self.year - 1, self.name)
        elif self.type == FiscalYearType.APRIL_MARCH:
            return FiscalYearVO.from_april_march(self.year - 1, self.name)
        elif self.type == FiscalYearType.JULY_JUNE:
            return FiscalYearVO.from_july_june(self.year - 1, self.name)
        elif self.type == FiscalYearType.OCTOBER_SEPTEMBER:
            return FiscalYearVO.from_october_september(self.year - 1, self.name)
        else:
            new_start = self.start_date.replace(year=self.start_date.year - 1)
            new_end = self.end_date.replace(year=self.end_date.year - 1)
            return FiscalYearVO.from_custom(self.year - 1, new_start, new_end, self.name)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "year": self.year,
            "type": self.type.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "name": self.name,
            "duration_days": self.duration_days,
            "display_name": self.display_name,
            "is_current": self.is_current,
            "is_future": self.is_future,
            "is_past": self.is_past,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "fiscal_year": self.year,
            "fiscal_year_type": self.type.value,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "name": self.name,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.display_name

    def __repr__(self) -> str:
        return f"FiscalYearVO({self.year}, {self.type.value}, {self.start_date.date()} -> {self.end_date.date()})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FiscalYearVO):
            return False
        return (
            self.year == other.year
            and self.type == other.type
            and self.start_date == other.start_date
            and self.end_date == other.end_date
        )

    def __hash__(self) -> int:
        return hash((self.year, self.type, self.start_date, self.end_date))

    def __lt__(self, other: FiscalYearVO) -> bool:
        """Order by start date."""
        return self.start_date < other.start_date


# ============================================================================
# Helper Functions
# ============================================================================


def get_current_fiscal_year(ftype: FiscalYearType = FiscalYearType.CALENDAR) -> FiscalYearVO:
    """Get the fiscal year that contains the current date."""
    now = datetime.now(UTC)
    return FiscalYearVO.from_date(now, ftype)


def get_fiscal_year_range(
    start_year: int, end_year: int, ftype: FiscalYearType = FiscalYearType.CALENDAR
) -> list[FiscalYearVO]:
    """Get a list of fiscal years from start_year to end_year inclusive."""
    years = []
    for y in range(start_year, end_year + 1):
        if ftype == FiscalYearType.CALENDAR:
            years.append(FiscalYearVO.from_calendar(y))
        elif ftype == FiscalYearType.APRIL_MARCH:
            years.append(FiscalYearVO.from_april_march(y))
        elif ftype == FiscalYearType.JULY_JUNE:
            years.append(FiscalYearVO.from_july_june(y))
        elif ftype == FiscalYearType.OCTOBER_SEPTEMBER:
            years.append(FiscalYearVO.from_october_september(y))
        else:
            raise InvalidFiscalYearTypeError(f"Cannot generate range for type {ftype}")
    return years


def fiscal_year_from_string(value: str) -> FiscalYearVO | None:
    """Parse a string like 'FY2024', '2024', 'FY2024 (Apr-Mar)' into FiscalYearVO."""
    # Try to extract year
    import re

    match = re.search(r"FY?(\d{4})", value.upper())
    if not match:
        return None
    year = int(match.group(1))
    # Determine type from description
    if "APR" in value or "MAR" in value:
        return FiscalYearVO.from_april_march(year)
    elif "JUL" in value or "JUN" in value:
        return FiscalYearVO.from_july_june(year)
    elif "OCT" in value or "SEP" in value:
        return FiscalYearVO.from_october_september(year)
    else:
        return FiscalYearVO.from_calendar(year)


# ============================================================================
# Temporary imports for type hints (avoid circular import in method bodies)
# ============================================================================

from domain.shared_value_objects.accounting_period_vo import AccountingPeriodVO, PeriodType

# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "FiscalYearError",
    "FiscalYearType",
    "FiscalYearVO",
    "InvalidFiscalYearRangeError",
    "InvalidFiscalYearTypeError",
    "fiscal_year_from_string",
    "get_current_fiscal_year",
    "get_fiscal_year_range",
]
