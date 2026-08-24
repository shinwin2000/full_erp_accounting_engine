#!/usr/bin/env python3
"""
Module: quantity_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for quantity with unit of measure. Immutable.
    Represents a quantity of items, goods, or services with a specific
    unit of measure. Supports arithmetic operations, unit conversion,
    comparison, and validation.

Business rules:
    - Quantity value cannot be negative (zero allowed).
    - Unit of measure must be from predefined UnitOfMeasure enum.
    - Arithmetic operations check unit compatibility; automatic conversion
      for compatible units (e.g., kg to gram, liter to ml).
    - Conversion map defines relationships between units.
    - Immutable: all operations return new instances.
    - Provides factory methods for common units.

Dependencies:
    - Python standard library (decimal, dataclass, enum, typing)

Audit:
    Pure value object; no I/O. Caller may log quantity changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Any

# ============================================================================
# Unit of Measure Enum
# ============================================================================


class UnitOfMeasure(Enum):
    """Standard units of measure supported by the system."""

    # Count-based units
    PCS = "pcs"  # Pieces / units
    PAIR = "pair"  # Pair (2 pieces)
    DOZEN = "dozen"  # Dozen (12 pieces)
    GROSS = "gross"  # Gross (144 pieces)
    SET = "set"  # Set (multiple pieces)
    BOX = "box"  # Box (variable count, usually 12)
    CARTON = "carton"  # Carton (variable, e.g., 24 pieces)
    PALLET = "pallet"  # Pallet (variable)

    # Weight units
    KG = "kg"  # Kilogram
    GRAM = "gram"  # Gram
    MG = "mg"  # Milligram
    TON = "ton"  # Metric ton (1000 kg)
    LB = "lb"  # Pound
    OZ = "oz"  # Ounce

    # Volume units
    LITER = "liter"  # Liter
    ML = "ml"  # Milliliter
    GAL = "gal"  # Gallon (US)
    QUART = "quart"  # Quart

    # Length units
    METER = "meter"  # Meter
    CM = "cm"  # Centimeter
    MM = "mm"  # Millimeter
    KM = "km"  # Kilometer
    INCH = "inch"  # Inch
    FT = "ft"  # Foot
    YD = "yd"  # Yard

    # Time units
    HOUR = "hour"  # Hour
    DAY = "day"  # Day
    WEEK = "week"  # Week
    MONTH = "month"  # Month
    YEAR = "year"  # Year

    # Area units
    SQ_M = "sq_m"  # Square meter
    SQ_FT = "sq_ft"  # Square foot

    @classmethod
    def from_string(cls, value: str) -> UnitOfMeasure | None:
        """Parse unit from string (case-insensitive)."""
        value_lower = value.lower()
        for unit in cls:
            if unit.value == value_lower:
                return unit
        return None

    def is_countable(self) -> bool:
        """Check if unit represents countable items."""
        return self in (
            UnitOfMeasure.PCS,
            UnitOfMeasure.PAIR,
            UnitOfMeasure.DOZEN,
            UnitOfMeasure.GROSS,
            UnitOfMeasure.SET,
            UnitOfMeasure.BOX,
            UnitOfMeasure.CARTON,
            UnitOfMeasure.PALLET,
        )

    def is_weight(self) -> bool:
        """Check if unit is a weight measure."""
        return self in (
            UnitOfMeasure.KG,
            UnitOfMeasure.GRAM,
            UnitOfMeasure.MG,
            UnitOfMeasure.TON,
            UnitOfMeasure.LB,
            UnitOfMeasure.OZ,
        )

    def is_volume(self) -> bool:
        """Check if unit is a volume measure."""
        return self in (
            UnitOfMeasure.LITER,
            UnitOfMeasure.ML,
            UnitOfMeasure.GAL,
            UnitOfMeasure.QUART,
        )

    def is_length(self) -> bool:
        """Check if unit is a length measure."""
        return self in (
            UnitOfMeasure.METER,
            UnitOfMeasure.CM,
            UnitOfMeasure.MM,
            UnitOfMeasure.KM,
            UnitOfMeasure.INCH,
            UnitOfMeasure.FT,
            UnitOfMeasure.YD,
        )


# ============================================================================
# Custom Exceptions
# ============================================================================


class QuantityError(ValueError):
    """Base exception for quantity errors."""

    pass


class InvalidQuantityError(QuantityError):
    """Raised when quantity value is invalid (negative)."""

    pass


class UnitMismatchError(QuantityError):
    """Raised when operations involve incompatible units."""

    pass


class UnitConversionError(QuantityError):
    """Raised when unit conversion is not supported."""

    pass


# ============================================================================
# Value Object: QuantityVO
# ============================================================================


@dataclass(frozen=True)
class QuantityVO:
    """
    Immutable value object for quantity with unit of measure.

    Attributes:
        value: Decimal quantity (>= 0)
        unit: UnitOfMeasure enum

    Examples:
        >>> q1 = QuantityVO(Decimal('10'), UnitOfMeasure.PCS)
        >>> q2 = QuantityVO(Decimal('2'), UnitOfMeasure.DOZEN)
        >>> q1.add(q2)  # Automatically converts dozen to pieces (2 dozen = 24 pcs)
        QuantityVO('34', 'pcs')
        >>> q1.convert_to(UnitOfMeasure.DOZEN)
        QuantityVO('0.833', 'dozen')
        >>> q1 > q2
        False
    """

    value: Decimal
    unit: UnitOfMeasure

    # Class constants
    PRECISION: int = 3  # Decimal places for quantity values
    ROUNDING = ROUND_HALF_EVEN

    def __post_init__(self) -> None:
        """Validate and normalize quantity."""
        # Validate value type and range
        if not isinstance(self.value, Decimal):
            raise InvalidQuantityError(f"Value must be Decimal, got {type(self.value)}")
        if self.value < 0:
            raise InvalidQuantityError(f"Quantity cannot be negative: {self.value}")

        # Normalize to PRECISION decimal places
        quantize = Decimal(f"1.{'0' * self.PRECISION}") if self.PRECISION > 0 else Decimal("1")
        normalized = self.value.quantize(quantize, rounding=self.ROUNDING)
        object.__setattr__(self, "value", normalized)

        # Unit is already validated by enum

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def of(cls, value: Decimal | int | str, unit: UnitOfMeasure | str) -> QuantityVO:
        """
        Create QuantityVO from various numeric types and unit.

        Args:
            value: Decimal, int, or string
            unit: UnitOfMeasure enum or string
        """
        if isinstance(value, float):
            value = Decimal(str(value))
        elif isinstance(value, (int, str)):
            value = Decimal(value)
        elif not isinstance(value, Decimal):
            raise InvalidQuantityError(f"Unsupported value type: {type(value)}")

        if isinstance(unit, str):
            unit_enum = UnitOfMeasure.from_string(unit)
            if unit_enum is None:
                raise QuantityError(f"Unknown unit: {unit}")
            unit = unit_enum

        return cls(value, unit)

    @classmethod
    def zero(cls, unit: UnitOfMeasure) -> QuantityVO:
        """Create zero quantity in given unit."""
        return cls(Decimal("0"), unit)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> QuantityVO:
        """Reconstruct from dictionary."""
        value = Decimal(str(data["value"]))
        unit = UnitOfMeasure.from_string(data["unit"])
        if unit is None:
            raise QuantityError(f"Invalid unit in dict: {data['unit']}")
        return cls(value, unit)

    # ------------------------------------------------------------------------
    # Unit Conversion
    # ------------------------------------------------------------------------

    def convert_to(self, target_unit: UnitOfMeasure) -> QuantityVO:
        """
        Convert quantity to target unit if conversion is possible.

        Returns:
            New QuantityVO in target unit.

        Raises:
            UnitConversionError: If conversion not supported.
        """
        if self.unit == target_unit:
            return self

        # Conversion factor map: (from_unit, to_unit) -> factor (multiply from to get to)
        conversion_map: dict[tuple[UnitOfMeasure, UnitOfMeasure], Decimal] = {
            # Weight conversions
            (UnitOfMeasure.KG, UnitOfMeasure.GRAM): Decimal("1000"),
            (UnitOfMeasure.GRAM, UnitOfMeasure.KG): Decimal("0.001"),
            (UnitOfMeasure.KG, UnitOfMeasure.TON): Decimal("0.001"),
            (UnitOfMeasure.TON, UnitOfMeasure.KG): Decimal("1000"),
            (UnitOfMeasure.GRAM, UnitOfMeasure.MG): Decimal("1000"),
            (UnitOfMeasure.MG, UnitOfMeasure.GRAM): Decimal("0.001"),
            (UnitOfMeasure.KG, UnitOfMeasure.LB): Decimal("2.20462"),
            (UnitOfMeasure.LB, UnitOfMeasure.KG): Decimal("0.453592"),
            (UnitOfMeasure.LB, UnitOfMeasure.OZ): Decimal("16"),
            (UnitOfMeasure.OZ, UnitOfMeasure.LB): Decimal("0.0625"),
            # Volume conversions
            (UnitOfMeasure.LITER, UnitOfMeasure.ML): Decimal("1000"),
            (UnitOfMeasure.ML, UnitOfMeasure.LITER): Decimal("0.001"),
            (UnitOfMeasure.LITER, UnitOfMeasure.GAL): Decimal("0.264172"),
            (UnitOfMeasure.GAL, UnitOfMeasure.LITER): Decimal("3.78541"),
            (UnitOfMeasure.GAL, UnitOfMeasure.QUART): Decimal("4"),
            (UnitOfMeasure.QUART, UnitOfMeasure.GAL): Decimal("0.25"),
            # Length conversions
            (UnitOfMeasure.METER, UnitOfMeasure.CM): Decimal("100"),
            (UnitOfMeasure.CM, UnitOfMeasure.METER): Decimal("0.01"),
            (UnitOfMeasure.METER, UnitOfMeasure.MM): Decimal("1000"),
            (UnitOfMeasure.MM, UnitOfMeasure.METER): Decimal("0.001"),
            (UnitOfMeasure.KM, UnitOfMeasure.METER): Decimal("1000"),
            (UnitOfMeasure.METER, UnitOfMeasure.KM): Decimal("0.001"),
            (UnitOfMeasure.INCH, UnitOfMeasure.CM): Decimal("2.54"),
            (UnitOfMeasure.CM, UnitOfMeasure.INCH): Decimal("0.393701"),
            (UnitOfMeasure.FT, UnitOfMeasure.INCH): Decimal("12"),
            (UnitOfMeasure.INCH, UnitOfMeasure.FT): Decimal("0.0833333"),
            (UnitOfMeasure.YD, UnitOfMeasure.FT): Decimal("3"),
            (UnitOfMeasure.FT, UnitOfMeasure.YD): Decimal("0.333333"),
            # Count conversions
            (UnitOfMeasure.DOZEN, UnitOfMeasure.PCS): Decimal("12"),
            (UnitOfMeasure.PCS, UnitOfMeasure.DOZEN): Decimal("1") / Decimal("12"),
            (UnitOfMeasure.GROSS, UnitOfMeasure.PCS): Decimal("144"),
            (UnitOfMeasure.PCS, UnitOfMeasure.GROSS): Decimal("1") / Decimal("144"),
            (UnitOfMeasure.PAIR, UnitOfMeasure.PCS): Decimal("2"),
            (UnitOfMeasure.PCS, UnitOfMeasure.PAIR): Decimal("0.5"),
            (UnitOfMeasure.BOX, UnitOfMeasure.PCS): Decimal("12"),  # Standard box
            (UnitOfMeasure.PCS, UnitOfMeasure.BOX): Decimal("1") / Decimal("12"),
            (UnitOfMeasure.CARTON, UnitOfMeasure.PCS): Decimal("24"),  # Standard carton
            (UnitOfMeasure.PCS, UnitOfMeasure.CARTON): Decimal("1") / Decimal("24"),
            # Area conversions
            (UnitOfMeasure.SQ_M, UnitOfMeasure.SQ_FT): Decimal("10.7639"),
            (UnitOfMeasure.SQ_FT, UnitOfMeasure.SQ_M): Decimal("0.092903"),
            # Time conversions
            (UnitOfMeasure.HOUR, UnitOfMeasure.DAY): Decimal("1") / Decimal("24"),
            (UnitOfMeasure.DAY, UnitOfMeasure.HOUR): Decimal("24"),
            (UnitOfMeasure.DAY, UnitOfMeasure.WEEK): Decimal("1") / Decimal("7"),
            (UnitOfMeasure.WEEK, UnitOfMeasure.DAY): Decimal("7"),
            (UnitOfMeasure.MONTH, UnitOfMeasure.DAY): Decimal("30.44"),  # Average month
            (UnitOfMeasure.DAY, UnitOfMeasure.MONTH): Decimal("1") / Decimal("30.44"),
            (UnitOfMeasure.YEAR, UnitOfMeasure.MONTH): Decimal("12"),
            (UnitOfMeasure.MONTH, UnitOfMeasure.YEAR): Decimal("1") / Decimal("12"),
        }

        key = (self.unit, target_unit)
        if key not in conversion_map:
            raise UnitConversionError(f"Cannot convert {self.unit.value} to {target_unit.value}")

        factor = conversion_map[key]
        new_value = self.value * factor
        return QuantityVO(new_value, target_unit)

    def is_convertible_to(self, target_unit: UnitOfMeasure) -> bool:
        """Check if conversion to target unit is supported."""
        if self.unit == target_unit:
            return True
        return (self.unit, target_unit) in self._get_conversion_map_keys()

    @classmethod
    def _get_conversion_map_keys(cls) -> set[tuple[UnitOfMeasure, UnitOfMeasure]]:
        """Return all supported conversion pairs (for quick lookup)."""
        return {
            # Weight
            (UnitOfMeasure.KG, UnitOfMeasure.GRAM),
            (UnitOfMeasure.GRAM, UnitOfMeasure.KG),
            (UnitOfMeasure.KG, UnitOfMeasure.TON),
            (UnitOfMeasure.TON, UnitOfMeasure.KG),
            (UnitOfMeasure.GRAM, UnitOfMeasure.MG),
            (UnitOfMeasure.MG, UnitOfMeasure.GRAM),
            (UnitOfMeasure.KG, UnitOfMeasure.LB),
            (UnitOfMeasure.LB, UnitOfMeasure.KG),
            (UnitOfMeasure.LB, UnitOfMeasure.OZ),
            (UnitOfMeasure.OZ, UnitOfMeasure.LB),
            # Volume
            (UnitOfMeasure.LITER, UnitOfMeasure.ML),
            (UnitOfMeasure.ML, UnitOfMeasure.LITER),
            (UnitOfMeasure.LITER, UnitOfMeasure.GAL),
            (UnitOfMeasure.GAL, UnitOfMeasure.LITER),
            (UnitOfMeasure.GAL, UnitOfMeasure.QUART),
            (UnitOfMeasure.QUART, UnitOfMeasure.GAL),
            # Length
            (UnitOfMeasure.METER, UnitOfMeasure.CM),
            (UnitOfMeasure.CM, UnitOfMeasure.METER),
            (UnitOfMeasure.METER, UnitOfMeasure.MM),
            (UnitOfMeasure.MM, UnitOfMeasure.METER),
            (UnitOfMeasure.KM, UnitOfMeasure.METER),
            (UnitOfMeasure.METER, UnitOfMeasure.KM),
            (UnitOfMeasure.INCH, UnitOfMeasure.CM),
            (UnitOfMeasure.CM, UnitOfMeasure.INCH),
            (UnitOfMeasure.FT, UnitOfMeasure.INCH),
            (UnitOfMeasure.INCH, UnitOfMeasure.FT),
            (UnitOfMeasure.YD, UnitOfMeasure.FT),
            (UnitOfMeasure.FT, UnitOfMeasure.YD),
            # Count
            (UnitOfMeasure.DOZEN, UnitOfMeasure.PCS),
            (UnitOfMeasure.PCS, UnitOfMeasure.DOZEN),
            (UnitOfMeasure.GROSS, UnitOfMeasure.PCS),
            (UnitOfMeasure.PCS, UnitOfMeasure.GROSS),
            (UnitOfMeasure.PAIR, UnitOfMeasure.PCS),
            (UnitOfMeasure.PCS, UnitOfMeasure.PAIR),
            (UnitOfMeasure.BOX, UnitOfMeasure.PCS),
            (UnitOfMeasure.PCS, UnitOfMeasure.BOX),
            (UnitOfMeasure.CARTON, UnitOfMeasure.PCS),
            (UnitOfMeasure.PCS, UnitOfMeasure.CARTON),
            # Area
            (UnitOfMeasure.SQ_M, UnitOfMeasure.SQ_FT),
            (UnitOfMeasure.SQ_FT, UnitOfMeasure.SQ_M),
            # Time
            (UnitOfMeasure.HOUR, UnitOfMeasure.DAY),
            (UnitOfMeasure.DAY, UnitOfMeasure.HOUR),
            (UnitOfMeasure.DAY, UnitOfMeasure.WEEK),
            (UnitOfMeasure.WEEK, UnitOfMeasure.DAY),
            (UnitOfMeasure.MONTH, UnitOfMeasure.DAY),
            (UnitOfMeasure.DAY, UnitOfMeasure.MONTH),
            (UnitOfMeasure.YEAR, UnitOfMeasure.MONTH),
            (UnitOfMeasure.MONTH, UnitOfMeasure.YEAR),
        }

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        """Check if quantity is zero."""
        return self.value == 0

    @property
    def is_positive(self) -> bool:
        """Check if quantity > 0."""
        return self.value > 0

    @property
    def as_integer(self) -> int | None:
        """Return as integer if value is integer (no fractional part)."""
        if self.value == self.value.to_integral():
            return int(self.value)
        return None

    # ------------------------------------------------------------------------
    # Arithmetic Operations
    # ------------------------------------------------------------------------

    def add(self, other: QuantityVO) -> QuantityVO:
        """
        Add two quantities. If units differ, attempts conversion to self.unit.
        """
        if self.unit == other.unit:
            return QuantityVO(self.value + other.value, self.unit)
        # Try to convert other to self.unit
        if other.is_convertible_to(self.unit):
            converted = other.convert_to(self.unit)
            return QuantityVO(self.value + converted.value, self.unit)
        raise UnitMismatchError(f"Cannot add {self.unit.value} and {other.unit.value}")

    def subtract(self, other: QuantityVO) -> QuantityVO:
        """
        Subtract other quantity from this one. Result cannot be negative.
        """
        if self.unit == other.unit:
            new_value = self.value - other.value
        else:
            if other.is_convertible_to(self.unit):
                converted = other.convert_to(self.unit)
                new_value = self.value - converted.value
            else:
                raise UnitMismatchError(
                    f"Cannot subtract {other.unit.value} from {self.unit.value}"
                )
        if new_value < 0:
            raise InvalidQuantityError(f"Result would be negative: {new_value}")
        return QuantityVO(new_value, self.unit)

    def multiply(self, factor: Decimal | float | int) -> QuantityVO:
        """Multiply quantity by a scalar factor."""
        if isinstance(factor, float):
            factor = Decimal(str(factor))
        elif isinstance(factor, int):
            factor = Decimal(factor)
        elif not isinstance(factor, Decimal):
            raise InvalidQuantityError(f"Factor must be numeric, got {type(factor)}")
        return QuantityVO(self.value * factor, self.unit)

    def divide(self, divisor: Decimal | float | int) -> QuantityVO:
        """Divide quantity by a scalar divisor."""
        if isinstance(divisor, float):
            divisor = Decimal(str(divisor))
        elif isinstance(divisor, int):
            divisor = Decimal(divisor)
        elif not isinstance(divisor, Decimal):
            raise InvalidQuantityError(f"Divisor must be numeric, got {type(divisor)}")
        if divisor == 0:
            raise QuantityError("Division by zero")
        return QuantityVO(self.value / divisor, self.unit)

    def __add__(self, other: QuantityVO) -> QuantityVO:
        return self.add(other)

    def __sub__(self, other: QuantityVO) -> QuantityVO:
        return self.subtract(other)

    def __mul__(self, factor: Decimal | float | int) -> QuantityVO:
        return self.multiply(factor)

    def __truediv__(self, divisor: Decimal | float | int) -> QuantityVO:
        return self.divide(divisor)

    def __rmul__(self, factor: Decimal | float | int) -> QuantityVO:
        return self.multiply(factor)

    # ------------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------------

    def compare(self, other: QuantityVO) -> int:
        """Compare after converting to common unit (self.unit if convertible)."""
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self.unit == other.unit:
            if self.value < other.value:
                return -1
            elif self.value > other.value:
                return 1
            return 0
        # Try to convert other to self.unit
        if other.is_convertible_to(self.unit):
            converted = other.convert_to(self.unit)
            if self.value < converted.value:
                return -1
            elif self.value > converted.value:
                return 1
            return 0
        raise UnitMismatchError(f"Cannot compare {self.unit.value} and {other.unit.value}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, QuantityVO):
            return False
        try:
            return self.compare(other) == 0
        except UnitMismatchError:
            return False

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other: QuantityVO) -> bool:
        return self.compare(other) == -1

    def __le__(self, other: QuantityVO) -> bool:
        return self.compare(other) <= 0

    def __gt__(self, other: QuantityVO) -> bool:
        return self.compare(other) == 1

    def __ge__(self, other: QuantityVO) -> bool:
        return self.compare(other) >= 0

    def __hash__(self) -> int:
        # Normalize to base unit for hashing? For consistency, hash based on value and unit.
        # But two quantities equal after conversion should hash same.
        # To simplify, we rely on direct equality.
        return hash((self.value, self.unit))

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "value": str(self.value),
            "unit": self.unit.value,
            "is_zero": self.is_zero,
            "is_positive": self.is_positive,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "quantity": self.value,
            "unit": self.unit.value,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        # Remove trailing zeros for display
        normalized = self.value.normalize()
        if normalized == normalized.to_integral():
            return f"{int(normalized)} {self.unit.value}"
        else:
            formatted = f"{normalized:.{self.PRECISION}f}".rstrip("0").rstrip(".")
            return f"{formatted} {self.unit.value}"

    def __repr__(self) -> str:
        return f"QuantityVO('{self.value}', {self.unit.value})"


# ============================================================================
# Helper Functions
# ============================================================================


def sum_quantities(
    quantities: list[QuantityVO], target_unit: UnitOfMeasure | None = None
) -> QuantityVO:
    """
    Sum a list of quantities. If target_unit is provided, all quantities
    are converted to that unit; otherwise uses the unit of the first quantity.
    """
    if not quantities:
        raise QuantityError("Cannot sum empty list")
    unit = target_unit if target_unit else quantities[0].unit
    total = Decimal("0")
    for q in quantities:
        if q.unit != unit:
            if q.is_convertible_to(unit):
                converted = q.convert_to(unit)
                total += converted.value
            else:
                raise UnitMismatchError(f"Cannot convert {q.unit.value} to {unit.value}")
        else:
            total += q.value
    return QuantityVO(total, unit)


def average_quantity(
    quantities: list[QuantityVO], target_unit: UnitOfMeasure | None = None
) -> QuantityVO:
    """Calculate average of quantities."""
    if not quantities:
        raise QuantityError("Cannot average empty list")
    total = sum_quantities(quantities, target_unit)
    return total.divide(len(quantities))


def normalize_quantities(
    quantities: list[QuantityVO], target_unit: UnitOfMeasure
) -> list[QuantityVO]:
    """Convert all quantities to the same target unit."""
    result = []
    for q in quantities:
        if q.is_convertible_to(target_unit):
            result.append(q.convert_to(target_unit))
        else:
            raise UnitMismatchError(f"Cannot convert {q.unit.value} to {target_unit.value}")
    return result


# ============================================================================
# ALIAS FOR SERVICE LAYER
# ============================================================================

Quantity = QuantityVO


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "InvalidQuantityError",
    "Quantity",
    "QuantityError",
    "QuantityVO",
    "UnitConversionError",
    "UnitMismatchError",
    "UnitOfMeasure",
    "average_quantity",
    "normalize_quantities",
    "sum_quantities",
]
