#!/usr/bin/env python3
"""
Module: date_range_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for date range (start_date - end_date). Immutable.
    Provides operations like containment, overlap, intersection, duration,
    and iteration over dates.

Business rules:
    - start_date must be before end_date.
    - All datetimes are timezone-aware (UTC).
    - The range is half-open: [start, end) by default.
    - Supports closed/open options for containments.

Dependencies:
    - Standard library (datetime, dataclass, typing)

Audit:
    Pure value object; no logging needed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

# ============================================================================
# Date Range Value Object
# ============================================================================


@dataclass(frozen=True)
class DateRangeVO:
    """
    Immutable value object representing a date/time range.

    Attributes:
        start_date: Inclusive start datetime (UTC)
        end_date: Exclusive end datetime (UTC) by default
        inclusive_end: If True, end_date is inclusive (default False)

    Examples:
        >>> range1 = DateRangeVO(
        ...     start_date=datetime(2024,1,1, tzinfo=timezone.utc),
        ...     end_date=datetime(2024,1,31, tzinfo=timezone.utc)
        ... )
        >>> range1.contains(datetime(2024,1,15))
        True
        >>> range1.duration_days()
        30
    """

    start_date: datetime
    end_date: datetime
    inclusive_end: bool = False

    def __post_init__(self) -> None:
        """Validate and normalize dates to UTC."""
        # Normalize to UTC
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))

        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )

        # If inclusive_end, we adjust comparison logic in contains().
        # No need to modify stored values.

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_dates(cls, start: date, end: date, inclusive_end: bool = False) -> DateRangeVO:
        """Create date range from date objects (midnight UTC)."""
        start_dt = datetime(start.year, start.month, start.day, tzinfo=UTC)
        end_dt = datetime(end.year, end.month, end.day, tzinfo=UTC)
        return cls(start_dt, end_dt, inclusive_end)

    @classmethod
    def from_timedelta(
        cls, start: datetime, delta: timedelta, inclusive_end: bool = False
    ) -> DateRangeVO:
        """Create range from start date and duration."""
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        end = start + delta
        return cls(start, end, inclusive_end)

    @classmethod
    def month_of(cls, year: int, month: int) -> DateRangeVO:
        """Create range for a full calendar month."""
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC)
        return cls(start, end, inclusive_end=False)

    @classmethod
    def quarter_of(cls, year: int, quarter: int) -> DateRangeVO:
        """Create range for a calendar quarter."""
        start_month = (quarter - 1) * 3 + 1
        start = datetime(year, start_month, 1, tzinfo=UTC)
        if quarter == 4:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end_month = start_month + 3
            end = datetime(year, end_month, 1, tzinfo=UTC)
        return cls(start, end, inclusive_end=False)

    @classmethod
    def year_of(cls, year: int) -> DateRangeVO:
        """Create range for a calendar year."""
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
        return cls(start, end, inclusive_end=False)

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def duration_seconds(self) -> float:
        """Total seconds in the range."""
        return (self.end_date - self.start_date).total_seconds()

    @property
    def duration_days(self) -> float:
        """Total days (as float)."""
        return self.duration_seconds / 86400.0

    @property
    def duration_days_int(self) -> int:
        """Total whole days (floor)."""
        return (self.end_date - self.start_date).days

    @property
    def is_empty(self) -> bool:
        """Check if the range contains zero duration."""
        return self.start_date == self.end_date

    @property
    def start_as_date(self) -> date:
        """Start date as date object (UTC)."""
        return self.start_date.date()

    @property
    def end_as_date(self) -> date:
        """End date as date object (UTC)."""
        return self.end_date.date()

    # ------------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------------

    def contains(self, dt: datetime) -> bool:
        """Check if datetime is within the range."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if self.inclusive_end:
            return self.start_date <= dt <= self.end_date
        else:
            return self.start_date <= dt < self.end_date

    def contains_date(self, d: date) -> bool:
        """Check if date (at midnight UTC) is within the range."""
        dt = datetime(d.year, d.month, d.day, tzinfo=UTC)
        return self.contains(dt)

    def overlaps(self, other: DateRangeVO) -> bool:
        """Check if this range overlaps with another."""
        # For half-open ranges: overlap if not (self.end <= other.start or other.end <= self.start)
        if self.inclusive_end:
            if other.inclusive_end:
                return not (self.end_date < other.start_date or other.end_date < self.start_date)
            else:
                return not (self.end_date < other.start_date or other.end_date <= self.start_date)
        else:
            if other.inclusive_end:
                return not (self.end_date <= other.start_date or other.end_date < self.start_date)
            else:
                return not (self.end_date <= other.start_date or other.end_date <= self.start_date)

    def intersection(self, other: DateRangeVO) -> DateRangeVO | None:
        """Return the intersection of two ranges, or None if no overlap."""
        if not self.overlaps(other):
            return None
        new_start = max(self.start_date, other.start_date)
        new_end = min(self.end_date, other.end_date)
        # Determine inclusive_end: true only if both ranges are inclusive and the end is exactly the min end
        inc_end = (
            self.inclusive_end
            and other.inclusive_end
            and new_end == min(self.end_date, other.end_date)
        )
        return DateRangeVO(new_start, new_end, inc_end)

    def union(self, other: DateRangeVO) -> DateRangeVO | None:
        """
        Return the smallest range that contains both ranges.
        If ranges are disjoint, returns None.
        """
        if not self.overlaps(other):
            return None
        new_start = min(self.start_date, other.start_date)
        new_end = max(self.end_date, other.end_date)
        inc_end = self.inclusive_end or other.inclusive_end
        return DateRangeVO(new_start, new_end, inc_end)

    def expand(self, delta: timedelta) -> DateRangeVO:
        """Expand the range by delta on both sides."""
        return DateRangeVO(self.start_date - delta, self.end_date + delta, self.inclusive_end)

    def shift(self, delta: timedelta) -> DateRangeVO:
        """Shift the entire range by delta."""
        return DateRangeVO(self.start_date + delta, self.end_date + delta, self.inclusive_end)

    def __iter__(self) -> Iterator[datetime]:
        """Iterate over each day (midnight) within the range (not inclusive of end)."""
        current = self.start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = self.end_date.replace(hour=0, minute=0, second=0, microsecond=0)
        while current < end_day:
            yield current
            current += timedelta(days=1)

    def to_list_of_dates(self) -> list[date]:
        """Return list of dates within the range (exclusive of end)."""
        return [dt.date() for dt in self]

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "inclusive_end": self.inclusive_end,
            "duration_days": self.duration_days,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DateRangeVO:
        """Reconstruct from dict."""
        start = datetime.fromisoformat(data["start_date"])
        end = datetime.fromisoformat(data["end_date"])
        inc = data.get("inclusive_end", False)
        return cls(start, end, inc)

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"[{self.start_date.date()} -> {self.end_date.date()})"

    def __repr__(self) -> str:
        return f"DateRangeVO({self.start_date.isoformat()}, {self.end_date.isoformat()}, inclusive_end={self.inclusive_end})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DateRangeVO):
            return False
        return (
            self.start_date == other.start_date
            and self.end_date == other.end_date
            and self.inclusive_end == other.inclusive_end
        )

    def __hash__(self) -> int:
        return hash((self.start_date, self.end_date, self.inclusive_end))


# ============================================================================
# ALIAS FOR SERVICE LAYER
# ============================================================================

DateRange = DateRangeVO


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "DateRange",
    "DateRangeVO",
]
