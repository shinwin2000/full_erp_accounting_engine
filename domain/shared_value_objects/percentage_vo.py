#!/usr/bin/env python3
"""
Module: percentage_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for percentage values (0% to 100%). Immutable.
    Represents a percentage with validation, arithmetic, conversion to decimal,
    and calculation of percentage of a given amount.

Business rules:
    - Percentage must be between 0 and 100 inclusive.
    - Stored as Decimal with up to 4 decimal places (e.g., 12.3456%).
    - Operations: addition, subtraction, multiplication, division, comparison.
    - Percentage arithmetic respects bounds (result clamped to [0,100]).
    - Provides conversion to factor (0.0 to 1.0) for calculations.
    - Zero and hundred singletons for efficiency.

Dependencies:
    - decimal, dataclass, typing (stdlib)

Audit:
    Pure value object; no I/O. Caller may log percentage usage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

# ============================================================================
# Custom Exceptions
# ============================================================================


class PercentageError(ValueError):
    """Base exception for percentage errors."""

    pass


class InvalidPercentageError(PercentageError):
    """Raised when percentage value is out of [0,100] range."""

    pass


# ============================================================================
# Value Object: PercentageVO
# ============================================================================


@dataclass(frozen=True)
class PercentageVO:
    """
    Immutable value object for percentage (0% to 100%).

    Attributes:
        value: Decimal percentage value (0-100)

    Examples:
        >>> p = PercentageVO(Decimal('12.5'))
        >>> p.as_decimal()
        Decimal('0.125')
        >>> p.calculate(Decimal('1000'))
        Decimal('125.00')
        >>> p + PercentageVO(Decimal('10'))
        PercentageVO('22.50')
        >>> PercentageVO.zero()
        PercentageVO('0')
    """

    value: Decimal

    # Class constants
    PRECISION: int = 4  # Decimal places for storage
    ROUNDING = ROUND_HALF_EVEN
    MAX_PERCENT: Decimal = Decimal("100")
    MIN_PERCENT: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        """Validate and normalize percentage value."""
        # Validate type and range
        if not isinstance(self.value, Decimal):
            raise InvalidPercentageError(f"Value must be Decimal, got {type(self.value)}")

        # Normalize to PRECISION decimal places
        quantize = Decimal(f"1.{'0' * self.PRECISION}")
        normalized = self.value.quantize(quantize, rounding=self.ROUNDING)
        object.__setattr__(self, "value", normalized)

        # Check bounds
        if normalized < self.MIN_PERCENT or normalized > self.MAX_PERCENT:
            raise InvalidPercentageError(
                f"Percentage must be between {self.MIN_PERCENT} and {self.MAX_PERCENT}, got {normalized}"
            )

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def of(cls, value: Decimal | int | str) -> PercentageVO:
        """
        Create PercentageVO from various numeric types.

        Args:
            value: Decimal, int, or string (e.g., '12.34')
        """
        if isinstance(value, float):
            value = Decimal(str(value))
        elif isinstance(value, int) or isinstance(value, str):
            value = Decimal(value)
        elif not isinstance(value, Decimal):
            raise InvalidPercentageError(f"Unsupported type: {type(value)}")
        return cls(value)

    @classmethod
    def zero(cls) -> PercentageVO:
        """Return 0%."""
        return cls(cls.MIN_PERCENT)

    @classmethod
    def hundred(cls) -> PercentageVO:
        """Return 100%."""
        return cls(cls.MAX_PERCENT)

    @classmethod
    def from_decimal_factor(cls, factor: Decimal | float | int | str) -> PercentageVO:
        """
        Create PercentageVO from a decimal factor (0.0 to 1.0).

        Example: factor 0.125 -> 12.5%
        """
        if isinstance(factor, float):
            factor = Decimal(str(factor))
        elif isinstance(factor, int) or isinstance(factor, str):
            factor = Decimal(factor)
        elif not isinstance(factor, Decimal):
            raise InvalidPercentageError(f"Unsupported factor type: {type(factor)}")
        if factor < 0 or factor > 1:
            raise InvalidPercentageError(f"Factor must be between 0 and 1, got {factor}")
        return cls(factor * cls.MAX_PERCENT)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PercentageVO:
        """Reconstruct from dictionary."""
        return cls.of(data["value"])

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def as_decimal(self) -> Decimal:
        """Return the percentage as a decimal factor (0.0 to 1.0)."""
        return self.value / self.MAX_PERCENT

    @property
    def as_float(self) -> float:
        """Return as float (warning: precision loss)."""
        return float(self.value)

    @property
    def is_zero(self) -> bool:
        """Check if percentage is 0%."""
        return self.value == self.MIN_PERCENT

    @property
    def is_hundred(self) -> bool:
        """Check if percentage is 100%."""
        return self.value == self.MAX_PERCENT

    @property
    def is_positive(self) -> bool:
        """Check if percentage > 0%."""
        return self.value > self.MIN_PERCENT

    @property
    def is_negative(self) -> bool:
        """Percentage cannot be negative (always False)."""
        return False

    # ------------------------------------------------------------------------
    # Arithmetic Operations (with bounds)
    # ------------------------------------------------------------------------

    def add(self, other: PercentageVO) -> PercentageVO:
        """Add two percentages (result clamped to [0,100])."""
        result = self.value + other.value
        if result > self.MAX_PERCENT:
            result = self.MAX_PERCENT
        if result < self.MIN_PERCENT:
            result = self.MIN_PERCENT
        return PercentageVO(result)

    def subtract(self, other: PercentageVO) -> PercentageVO:
        """Subtract two percentages (result clamped to [0,100])."""
        result = self.value - other.value
        if result > self.MAX_PERCENT:
            result = self.MAX_PERCENT
        if result < self.MIN_PERCENT:
            result = self.MIN_PERCENT
        return PercentageVO(result)

    def multiply(self, factor: Decimal | float | int) -> PercentageVO:
        """
        Multiply percentage by a scalar factor (result clamped to [0,100]).
        Useful for scaling a percentage.
        """
        if isinstance(factor, float):
            factor = Decimal(str(factor))
        elif isinstance(factor, int):
            factor = Decimal(factor)
        elif not isinstance(factor, Decimal):
            raise InvalidPercentageError(f"Factor must be numeric, got {type(factor)}")
        result = self.value * factor
        if result > self.MAX_PERCENT:
            result = self.MAX_PERCENT
        if result < self.MIN_PERCENT:
            result = self.MIN_PERCENT
        return PercentageVO(result)

    def divide(self, divisor: Decimal | float | int) -> PercentageVO:
        """
        Divide percentage by a scalar divisor (result clamped to [0,100]).
        """
        if isinstance(divisor, float):
            divisor = Decimal(str(divisor))
        elif isinstance(divisor, int):
            divisor = Decimal(divisor)
        elif not isinstance(divisor, Decimal):
            raise InvalidPercentageError(f"Divisor must be numeric, got {type(divisor)}")
        if divisor == 0:
            raise PercentageError("Division by zero")
        result = self.value / divisor
        if result > self.MAX_PERCENT:
            result = self.MAX_PERCENT
        if result < self.MIN_PERCENT:
            result = self.MIN_PERCENT
        return PercentageVO(result)

    def __add__(self, other: PercentageVO) -> PercentageVO:
        return self.add(other)

    def __sub__(self, other: PercentageVO) -> PercentageVO:
        return self.subtract(other)

    def __mul__(self, factor: Decimal | float | int) -> PercentageVO:
        return self.multiply(factor)

    def __truediv__(self, divisor: Decimal | float | int) -> PercentageVO:
        return self.divide(divisor)

    def __rmul__(self, factor: Decimal | float | int) -> PercentageVO:
        return self.multiply(factor)

    # ------------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------------

    def compare(self, other: PercentageVO) -> int:
        """Return -1 if self < other, 0 if equal, 1 if self > other."""
        if self.value < other.value:
            return -1
        elif self.value > other.value:
            return 1
        else:
            return 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PercentageVO):
            return False
        return self.value == other.value

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other: PercentageVO) -> bool:
        return self.value < other.value

    def __le__(self, other: PercentageVO) -> bool:
        return self.value <= other.value

    def __gt__(self, other: PercentageVO) -> bool:
        return self.value > other.value

    def __ge__(self, other: PercentageVO) -> bool:
        return self.value >= other.value

    def __hash__(self) -> int:
        return hash(self.value)

    # ------------------------------------------------------------------------
    # Business Logic
    # ------------------------------------------------------------------------

    def calculate(self, amount: Decimal, rounding: int = 2) -> Decimal:
        """
        Calculate the percentage of a given amount.

        Args:
            amount: The base amount (Decimal)
            rounding: Number of decimal places to round the result (default 2)

        Returns:
            Decimal result = amount * (value / 100), rounded to specified places.
        """
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        result = amount * self.as_decimal
        quantize = Decimal(f"1.{'0' * rounding}") if rounding > 0 else Decimal("1")
        return result.quantize(quantize, rounding=self.ROUNDING)

    def calculate_on_money(self, money: Money) -> Money:
        """
        Calculate percentage of a Money amount. Returns new Money in same currency.
        This requires the Money class (imported dynamically to avoid circular import).
        """
        from domain.shared_value_objects.money_vo import Money

        new_amount = self.calculate(money.amount, money.decimal_places)
        return Money(new_amount, money.currency)

    def apply_to(self, amount: Decimal) -> Decimal:
        """Alias for calculate()."""
        return self.calculate(amount)

    def inverse(self) -> PercentageVO:
        """
        Return the complement percentage (100% - self).
        For example, 30% inverse is 70%.
        """
        return PercentageVO(self.MAX_PERCENT - self.value)

    def clamped(
        self, min_pct: PercentageVO | None = None, max_pct: PercentageVO | None = None
    ) -> PercentageVO:
        """Return a new percentage clamped to optional min and max bounds."""
        result = self.value
        if min_pct is not None:
            if result < min_pct.value:
                result = min_pct.value
        if max_pct is not None:
            if result > max_pct.value:
                result = max_pct.value
        return PercentageVO(result)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "value": str(self.value),
            "as_decimal": str(self.as_decimal),
            "is_zero": self.is_zero,
            "is_hundred": self.is_hundred,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "percentage": self.value,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        # Remove trailing zeros for display
        normalized = self.value.normalize()
        # If it's an integer, show without decimal
        if normalized == normalized.to_integral():
            return f"{int(normalized)}%"
        else:
            # Show with up to PRECISION decimals, but strip trailing zeros
            formatted = f"{normalized:.{self.PRECISION}f}".rstrip("0").rstrip(".")
            return f"{formatted}%"

    def __repr__(self) -> str:
        return f"PercentageVO('{self.value}')"


# ============================================================================
# Helper Functions
# ============================================================================


def sum_percentages(percentages: list[PercentageVO]) -> PercentageVO:
    """Sum a list of percentages (result clamped to 0-100)."""
    if not percentages:
        return PercentageVO.zero()
    total = Decimal("0")
    for p in percentages:
        total += p.value
    return PercentageVO(min(total, PercentageVO.MAX_PERCENT))


def average_percentage(percentages: list[PercentageVO]) -> PercentageVO:
    """Calculate average of percentages."""
    if not percentages:
        raise PercentageError("Cannot average empty list")
    total = sum(p.value for p in percentages)
    avg = total / len(percentages)
    return PercentageVO(avg)


def weighted_average_percentage(
    values: list[PercentageVO], weights: list[Decimal | int | float]
) -> PercentageVO:
    """
    Calculate weighted average of percentages.

    Args:
        values: List of PercentageVO objects
        weights: Corresponding weights (will be normalized to sum 1)

    Returns:
        Weighted average percentage.
    """
    if not values or len(values) != len(weights):
        raise PercentageError("Values and weights must have same length and be non-empty")
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for p, w in zip(values, weights):
        if isinstance(w, float):
            w = Decimal(str(w))
        elif isinstance(w, int):
            w = Decimal(w)
        elif not isinstance(w, Decimal):
            raise PercentageError(f"Weight must be numeric, got {type(w)}")
        if w < 0:
            raise PercentageError("Weights must be non-negative")
        total_weight += w
        weighted_sum += p.value * w
    if total_weight == 0:
        raise PercentageError("Total weight cannot be zero")
    result = weighted_sum / total_weight
    return PercentageVO(result)


def percentage_difference(old: PercentageVO, new: PercentageVO) -> Decimal:
    """
    Calculate absolute difference between two percentages.
    Returns Decimal (not PercentageVO) because difference can be negative.
    """
    return new.value - old.value


def percentage_change(old: Decimal, new: Decimal) -> PercentageVO:
    """
    Calculate percentage change from old value to new value.
    Example: old=100, new=120 => 20%
    """
    if old == 0:
        raise PercentageError("Cannot calculate percentage change from zero")
    change = (new - old) / old * PercentageVO.MAX_PERCENT
    return PercentageVO(change)


# ============================================================================
# ALIAS FOR SERVICE LAYER (short name)
# ============================================================================

Percentage = PercentageVO


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvalidPercentageError",
    "Percentage",  # alias for service
    "PercentageError",
    "PercentageVO",
    "average_percentage",
    "percentage_change",
    "percentage_difference",
    "sum_percentages",
    "weighted_average_percentage",
]
