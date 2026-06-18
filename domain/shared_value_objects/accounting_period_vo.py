#!/usr/bin/env python3
"""
Module: accounting_period_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for accounting period (fiscal month/quarter/year). Immutable.
    Provides validation, status transitions (open/locked/closed), date containment,
    period arithmetic, and serialization.

Business rules:
    - Period number must be valid for type: monthly (1-12), quarterly (1-4), yearly (1)
    - Start date must be before end date; all datetimes are timezone-aware UTC.
    - Status transitions: OPEN → LOCKED → CLOSED (irreversible). Closed period cannot be unlocked.
    - Closing requires closed_by user ID and closed_at timestamp.
    - Locked period allows adjustments but no new postings.
    - Periods are comparable and hashable.

Audit:
    Every status change should be logged by the caller. This value object is pure.

Dependencies:
    - datetime, dataclass, enum, typing (stdlib)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

# ============================================================================
# Enums
# ============================================================================


class PeriodStatus(Enum):
    """Status of an accounting period."""

    OPEN = "open"  # Can post and adjust
    LOCKED = "locked"  # Cannot post new entries, but adjustments allowed
    CLOSED = "closed"  # No changes allowed; period is finalized

    def can_post(self) -> bool:
        """Return True if new journal entries can be posted."""
        return self == PeriodStatus.OPEN

    def can_adjust(self) -> bool:
        """Return True if adjusting entries are allowed."""
        return self in (PeriodStatus.OPEN, PeriodStatus.LOCKED)

    def can_close(self) -> bool:
        """Return True if the period can be closed (must be OPEN or LOCKED)."""
        return self != PeriodStatus.CLOSED

    @classmethod
    def from_string(cls, value: str) -> PeriodStatus:
        """Parse status from string (case-insensitive)."""
        value_lower = value.lower()
        for status in cls:
            if status.value == value_lower:
                return status
        raise ValueError(f"Invalid period status: {value}")


class PeriodType(Enum):
    """Type of accounting period (monthly, quarterly, yearly)."""

    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


# ============================================================================
# Value Object: AccountingPeriodVO
# ============================================================================


@dataclass(frozen=True)
class AccountingPeriodVO:
    """
    Immutable value object representing an accounting period.

    Attributes:
        fiscal_year: Fiscal year (e.g., 2024)
        period_number: For monthly: 1-12; quarterly: 1-4; yearly: 1
        start_date: UTC datetime when the period begins (inclusive)
        end_date: UTC datetime when the period ends (exclusive)
        status: PeriodStatus.OPEN, LOCKED, or CLOSED
        period_type: PeriodType (default MONTHLY)
        closed_by: User ID or system that closed the period (if closed)
        closed_at: UTC timestamp when period was closed (if closed)

    Examples:
        >>> period = AccountingPeriodVO.from_month(2024, 1)
        >>> period.period_name
        'Januari 2024'
        >>> period.is_open
        True
        >>> closed = period.close("user_123")
        >>> closed.status == PeriodStatus.CLOSED
        True
    """

    fiscal_year: int
    period_number: int
    start_date: datetime
    end_date: datetime
    status: PeriodStatus = PeriodStatus.OPEN
    period_type: PeriodType = PeriodType.MONTHLY
    closed_by: str | None = None
    closed_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate and normalize the accounting period."""
        # Validate period number based on type
        if self.period_type == PeriodType.MONTHLY:
            if not (1 <= self.period_number <= 12):
                raise ValueError(f"Monthly period number must be 1-12, got {self.period_number}")
        elif self.period_type == PeriodType.QUARTERLY:
            if not (1 <= self.period_number <= 4):
                raise ValueError(f"Quarterly period number must be 1-4, got {self.period_number}")
        elif self.period_type == PeriodType.YEARLY:
            if self.period_number != 1:
                raise ValueError(f"Yearly period number must be 1, got {self.period_number}")
        else:
            raise ValueError(f"Unknown period type: {self.period_type}")

        # Normalize datetimes to UTC
        if self.start_date.tzinfo is None:
            object.__setattr__(self, "start_date", self.start_date.replace(tzinfo=UTC))
        if self.end_date.tzinfo is None:
            object.__setattr__(self, "end_date", self.end_date.replace(tzinfo=UTC))
        if self.closed_at and self.closed_at.tzinfo is None:
            object.__setattr__(self, "closed_at", self.closed_at.replace(tzinfo=UTC))

        if self.start_date >= self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) must be before end_date ({self.end_date})"
            )

        # Status consistency
        if self.status == PeriodStatus.CLOSED:
            if not self.closed_by:
                raise ValueError("Closed period must have closed_by")
            if not self.closed_at:
                raise ValueError("Closed period must have closed_at")
        else:
            if self.closed_by or self.closed_at:
                raise ValueError("Non-closed period cannot have closed_by/closed_at")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def from_month(
        cls, year: int, month: int, status: PeriodStatus = PeriodStatus.OPEN
    ) -> AccountingPeriodVO:
        """
        Create a monthly period.

        Args:
            year: Gregorian year
            month: 1-12
            status: Initial status (default OPEN)

        Returns:
            AccountingPeriodVO from first day of month to first day of next month.
        """
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC)
        return cls(
            fiscal_year=year,
            period_number=month,
            start_date=start,
            end_date=end,
            status=status,
            period_type=PeriodType.MONTHLY,
        )

    @classmethod
    def from_quarter(
        cls, year: int, quarter: int, status: PeriodStatus = PeriodStatus.OPEN
    ) -> AccountingPeriodVO:
        """
        Create a quarterly period (calendar quarters).

        Args:
            year: Gregorian year
            quarter: 1-4
            status: Initial status
        """
        start_month = (quarter - 1) * 3 + 1
        start = datetime(year, start_month, 1, tzinfo=UTC)
        if quarter == 4:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end_month = start_month + 3
            end = datetime(year, end_month, 1, tzinfo=UTC)
        return cls(
            fiscal_year=year,
            period_number=quarter,
            start_date=start,
            end_date=end,
            status=status,
            period_type=PeriodType.QUARTERLY,
        )

    @classmethod
    def from_year(cls, year: int, status: PeriodStatus = PeriodStatus.OPEN) -> AccountingPeriodVO:
        """Create a yearly period (calendar year)."""
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
        return cls(
            fiscal_year=year,
            period_number=1,
            start_date=start,
            end_date=end,
            status=status,
            period_type=PeriodType.YEARLY,
        )

    @classmethod
    def from_custom(
        cls, start_date: datetime, end_date: datetime, status: PeriodStatus = PeriodStatus.OPEN
    ) -> AccountingPeriodVO:
        """
        Create a custom period from arbitrary start/end dates.
        Period type is set to MONTHLY, period_number = 0.
        """
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=UTC)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=UTC)
        fiscal_year = start_date.year
        return cls(
            fiscal_year=fiscal_year,
            period_number=0,
            start_date=start_date,
            end_date=end_date,
            status=status,
            period_type=PeriodType.MONTHLY,  # fallback
        )

    @classmethod
    def from_string(cls, period_str: str) -> AccountingPeriodVO:
        """
        Parse period from common string formats.

        Supported formats:
            - "2024-01" (year-month) -> monthly period
            - "2024-Q1" -> quarterly period
            - "2024" -> yearly period
        """
        period_str = period_str.strip().upper()
        if "-Q" in period_str:
            # Quarterly format: 2024-Q1
            parts = period_str.split("-Q")
            year = int(parts[0])
            quarter = int(parts[1])
            return cls.from_quarter(year, quarter)
        elif "-" in period_str:
            # Monthly format: 2024-01
            parts = period_str.split("-")
            year = int(parts[0])
            month = int(parts[1])
            return cls.from_month(year, month)
        else:
            # Yearly format
            year = int(period_str)
            return cls.from_year(year)

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def period_name(self) -> str:
        """Human-readable name (e.g., 'Januari 2024', 'Q1 2024', 'FY 2024')."""
        if self.period_type == PeriodType.MONTHLY:
            month_names = [
                "Januari",
                "Februari",
                "Maret",
                "April",
                "Mei",
                "Juni",
                "Juli",
                "Agustus",
                "September",
                "Oktober",
                "November",
                "Desember",
            ]
            return f"{month_names[self.period_number - 1]} {self.fiscal_year}"
        elif self.period_type == PeriodType.QUARTERLY:
            return f"Q{self.period_number} {self.fiscal_year}"
        else:
            return f"FY {self.fiscal_year}"

    @property
    def is_open(self) -> bool:
        return self.status == PeriodStatus.OPEN

    @property
    def is_locked(self) -> bool:
        return self.status == PeriodStatus.LOCKED

    @property
    def is_closed(self) -> bool:
        return self.status == PeriodStatus.CLOSED

    @property
    def duration_days(self) -> int:
        """Number of days in the period (floor)."""
        return (self.end_date - self.start_date).days

    @property
    def duration_seconds(self) -> float:
        """Total seconds in the period."""
        return (self.end_date - self.start_date).total_seconds()

    @property
    def next_period(self) -> AccountingPeriodVO | None:
        """
        Return the next consecutive period of the same type.
        Returns None if the period would exceed reasonable bounds (year > 2100).
        """
        if self.fiscal_year > 2100:
            return None
        if self.period_type == PeriodType.MONTHLY:
            if self.period_number == 12:
                return AccountingPeriodVO.from_month(self.fiscal_year + 1, 1, self.status)
            else:
                return AccountingPeriodVO.from_month(
                    self.fiscal_year, self.period_number + 1, self.status
                )
        elif self.period_type == PeriodType.QUARTERLY:
            if self.period_number == 4:
                return AccountingPeriodVO.from_quarter(self.fiscal_year + 1, 1, self.status)
            else:
                return AccountingPeriodVO.from_quarter(
                    self.fiscal_year, self.period_number + 1, self.status
                )
        elif self.period_type == PeriodType.YEARLY:
            return AccountingPeriodVO.from_year(self.fiscal_year + 1, self.status)
        return None

    @property
    def previous_period(self) -> AccountingPeriodVO | None:
        """Return the previous consecutive period of the same type."""
        if self.fiscal_year < 1970:
            return None
        if self.period_type == PeriodType.MONTHLY:
            if self.period_number == 1:
                return AccountingPeriodVO.from_month(self.fiscal_year - 1, 12, self.status)
            else:
                return AccountingPeriodVO.from_month(
                    self.fiscal_year, self.period_number - 1, self.status
                )
        elif self.period_type == PeriodType.QUARTERLY:
            if self.period_number == 1:
                return AccountingPeriodVO.from_quarter(self.fiscal_year - 1, 4, self.status)
            else:
                return AccountingPeriodVO.from_quarter(
                    self.fiscal_year, self.period_number - 1, self.status
                )
        elif self.period_type == PeriodType.YEARLY:
            return AccountingPeriodVO.from_year(self.fiscal_year - 1, self.status)
        return None

    @property
    def as_tuple(self) -> tuple[int, int, str]:
        """Return (fiscal_year, period_number, period_type) as tuple for sorting."""
        return (self.fiscal_year, self.period_number, self.period_type.value)

    # ------------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------------

    def contains(self, dt: datetime) -> bool:
        """Check if the given datetime falls within this period (start inclusive, end exclusive)."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return self.start_date <= dt < self.end_date

    def contains_date(self, d: datetime) -> bool:
        """Alias for contains()."""
        return self.contains(d)

    def overlaps(self, other: AccountingPeriodVO) -> bool:
        """Check if this period overlaps with another period."""
        return self.start_date < other.end_date and other.start_date < self.end_date

    def close(self, closed_by: str, closed_at: datetime | None = None) -> AccountingPeriodVO:
        """
        Close the period. Returns a new closed period.
        Raises ValueError if period is already closed.
        """
        if self.is_closed:
            raise ValueError(f"Period {self.period_name} is already closed")
        if closed_at is None:
            closed_at = datetime.now(UTC)
        elif closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=UTC)
        return AccountingPeriodVO(
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            start_date=self.start_date,
            end_date=self.end_date,
            status=PeriodStatus.CLOSED,
            period_type=self.period_type,
            closed_by=closed_by,
            closed_at=closed_at,
        )

    def lock(self, locked_by: str) -> AccountingPeriodVO:
        """
        Lock the period. Returns a new locked period.
        Cannot lock a closed period.
        """
        if self.is_closed:
            raise ValueError(f"Cannot lock a closed period: {self.period_name}")
        if self.is_locked:
            return self  # already locked
        return AccountingPeriodVO(
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            start_date=self.start_date,
            end_date=self.end_date,
            status=PeriodStatus.LOCKED,
            period_type=self.period_type,
        )

    def unlock(self) -> AccountingPeriodVO:
        """
        Unlock a locked period (back to OPEN).
        Cannot unlock a closed period.
        """
        if self.is_closed:
            raise ValueError(f"Cannot unlock a closed period: {self.period_name}")
        if self.is_open:
            return self
        return AccountingPeriodVO(
            fiscal_year=self.fiscal_year,
            period_number=self.period_number,
            start_date=self.start_date,
            end_date=self.end_date,
            status=PeriodStatus.OPEN,
            period_type=self.period_type,
        )

    def with_status(
        self, new_status: PeriodStatus, changed_by: str | None = None
    ) -> AccountingPeriodVO:
        """
        Change the status of the period. Convenience method.
        If new_status is CLOSED, changed_by is required.
        """
        if new_status == PeriodStatus.CLOSED:
            return self.close(changed_by or "system")
        elif new_status == PeriodStatus.LOCKED:
            return self.lock(changed_by or "system")
        elif new_status == PeriodStatus.OPEN:
            return self.unlock()
        else:
            raise ValueError(f"Unknown status: {new_status}")

    # ------------------------------------------------------------------------
    # Comparison helpers
    # ------------------------------------------------------------------------

    def is_same_period(self, other: AccountingPeriodVO) -> bool:
        """Check if two periods represent the same time range (ignoring status)."""
        return (
            self.fiscal_year == other.fiscal_year
            and self.period_number == other.period_number
            and self.period_type == other.period_type
        )

    def is_before(self, other: AccountingPeriodVO) -> bool:
        """Check if this period ends before the other starts."""
        return self.end_date <= other.start_date

    def is_after(self, other: AccountingPeriodVO) -> bool:
        """Check if this period starts after the other ends."""
        return self.start_date >= other.end_date

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
            "period_name": self.period_name,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "status": self.status.value,
            "period_type": self.period_type.value,
            "closed_by": self.closed_by,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "duration_days": self.duration_days,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountingPeriodVO:
        """Reconstruct from dict."""
        start = datetime.fromisoformat(data["start_date"])
        end = datetime.fromisoformat(data["end_date"])
        status = PeriodStatus.from_string(data["status"])
        period_type = PeriodType(data.get("period_type", "monthly"))
        closed_by = data.get("closed_by")
        closed_at = datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None
        return cls(
            fiscal_year=data["fiscal_year"],
            period_number=data["period_number"],
            start_date=start,
            end_date=end,
            status=status,
            period_type=period_type,
            closed_by=closed_by,
            closed_at=closed_at,
        )

    def to_db_format(self) -> dict[str, Any]:
        """Convert to format suitable for database storage."""
        return {
            "fiscal_year": self.fiscal_year,
            "period_number": self.period_number,
            "period_type": self.period_type.value,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": self.status.value,
            "closed_by": self.closed_by,
            "closed_at": self.closed_at,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.period_name} ({self.status.value})"

    def __repr__(self) -> str:
        return f"AccountingPeriodVO('{self.period_name}', status={self.status.value})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AccountingPeriodVO):
            return False
        return (
            self.fiscal_year == other.fiscal_year
            and self.period_number == other.period_number
            and self.period_type == other.period_type
        )

    def __hash__(self) -> int:
        return hash((self.fiscal_year, self.period_number, self.period_type))

    def __lt__(self, other: AccountingPeriodVO) -> bool:
        """Compare periods chronologically."""
        if self.fiscal_year != other.fiscal_year:
            return self.fiscal_year < other.fiscal_year
        return self.period_number < other.period_number


# ============================================================================
# Type alias for convenience
# ============================================================================

AccountingPeriod = AccountingPeriodVO


# ============================================================================
# Helper functions
# ============================================================================


def current_accounting_period() -> AccountingPeriodVO:
    """Return the accounting period for the current month."""
    now = datetime.now(UTC)
    return AccountingPeriodVO.from_month(now.year, now.month)


def parse_period_range(
    start_period: AccountingPeriodVO, end_period: AccountingPeriodVO
) -> list[AccountingPeriodVO]:
    """
    Return a list of consecutive periods from start_period to end_period (inclusive).
    Both periods must be of the same type.
    """
    if start_period.period_type != end_period.period_type:
        raise ValueError("Period types must match")
    if start_period > end_period:
        raise ValueError("Start period must be before or equal to end period")
    result = []
    current = start_period
    while current <= end_period:
        result.append(current)
        nxt = current.next_period
        if nxt is None:
            break
        current = nxt
    return result


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "AccountingPeriod",
    "AccountingPeriodVO",
    "PeriodStatus",
    "PeriodType",
    "current_accounting_period",
    "parse_period_range",
]
