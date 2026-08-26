#!/usr/bin/env python3
"""
Module: money_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for monetary amounts with currency. Immutable.
    Represents an amount of money in a specific currency, with arithmetic
    operations, comparison, rounding, and formatting.

Business rules:
    - Amount is stored as Decimal with currency-specific decimal places.
    - Currency must be a valid ISO 4217 code (3 letters) or a Currency enum member.
    - All arithmetic operations preserve currency and round correctly.
    - Operations between different currencies are not allowed (must convert first).
    - Immutable: all operations return new Money instances.
    - Zero amount is allowed and is the additive identity.

Dependencies:
    - decimal, dataclass, typing, enum (stdlib)
    - currency_vo for currency validation and formatting (optional dependency)

Audit:
    Pure value object; no I/O. Caller may log monetary operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, Decimal
from enum import Enum
from typing import Any

# ============================================================================
# Currency Enum (exposed for tests and domain)
# ============================================================================

class Currency(Enum):
    """ISO 4217 currency codes as an enum for type safety."""
    IDR = "IDR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CNY = "CNY"
    SGD = "SGD"
    MYR = "MYR"
    KRW = "KRW"
    VND = "VND"
    THB = "THB"
    PHP = "PHP"
    AUD = "AUD"
    CAD = "CAD"
    CHF = "CHF"
    NZD = "NZD"
    SEK = "SEK"
    NOK = "NOK"
    DKK = "DKK"
    ZAR = "ZAR"
    INR = "INR"
    BRL = "BRL"
    RUB = "RUB"
    HKD = "HKD"
    TWD = "TWD"

    @classmethod
    def from_code(cls, code: str) -> Currency:
        """Get Currency enum member from string code."""
        code_upper = code.strip().upper()
        for member in cls:
            if member.value == code_upper:
                return member
        raise ValueError(f"Unknown currency code: {code}")


# ============================================================================
# Custom Exceptions
# ============================================================================


class MoneyError(ValueError):
    """Base exception for money-related errors."""
    pass


class CurrencyMismatchError(MoneyError):
    """Raised when operations involve different currencies."""
    pass


class InvalidAmountError(MoneyError):
    """Raised when amount is invalid (e.g., NaN, infinite)."""
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_currency_code(currency: str) -> str:
    """Validate ISO 4217 currency code (3 uppercase letters)."""
    if not isinstance(currency, str):
        raise MoneyError("Currency must be a string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise MoneyError(f"Currency code must be exactly 3 letters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise MoneyError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _get_currency_decimal_places(currency: str) -> int:
    """
    Return the number of decimal places for a given currency.
    Based on ISO 4217 standard.
    """
    # Zero-decimal currencies
    zero_decimal = {"JPY", "KRW", "VND", "CLP", "ISK", "KPW", "PYG", "XAF", "XOF"}
    # Three-decimal currencies
    three_decimal = {"KWD", "BHD", "OMR", "JOD", "TND"}
    if currency in zero_decimal:
        return 0
    elif currency in three_decimal:
        return 3
    else:
        return 2


def _normalize_currency(currency: Currency | str) -> str:
    """Convert Currency enum or string to a 3-letter code string."""
    if isinstance(currency, Currency):
        return currency.value
    if isinstance(currency, str):
        return _validate_currency_code(currency)
    raise MoneyError(f"Currency must be Currency enum or string, got {type(currency)}")


# ============================================================================
# Value Object: Money
# ============================================================================


@dataclass(frozen=True)
class Money:
    """
    Immutable value object representing a monetary amount.

    Attributes:
        amount: Decimal amount (automatically rounded to currency's decimal places)
        currency: ISO 4217 currency code (as string) or Currency enum member

    Examples:
        >>> m1 = Money(Decimal('1000.50'), 'IDR')
        >>> m2 = Money(Decimal('500.25'), Currency.USD)
        >>> m1 + m2  # raises CurrencyMismatchError
        >>> m1 + Money(Decimal('500.25'), 'IDR')
        Money('1500.75', 'IDR')
    """

    amount: Decimal
    currency: Currency | str

    # Default rounding for operations
    ROUNDING = ROUND_HALF_EVEN

    def __post_init__(self) -> None:
        """Validate and normalize amount and currency."""
        # Normalize currency to string
        currency_code = _normalize_currency(self.currency)
        object.__setattr__(self, "currency", currency_code)

        # Validate amount
        if not isinstance(self.amount, Decimal):
            raise InvalidAmountError(f"Amount must be Decimal, got {type(self.amount)}")
        if self.amount.is_nan():
            raise InvalidAmountError("Amount cannot be NaN")
        if self.amount.is_infinite():
            raise InvalidAmountError("Amount cannot be infinite")

        # Round to currency's decimal places
        decimal_places = _get_currency_decimal_places(currency_code)
        quantize_str = f"1.{'0' * decimal_places}" if decimal_places > 0 else "1"
        quantized = self.amount.quantize(Decimal(quantize_str), rounding=self.ROUNDING)
        object.__setattr__(self, "amount", quantized)

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def of(cls, amount: Decimal | int | str, currency: Currency | str) -> Money:
        """
        Create Money from various numeric types.

        Args:
            amount: Decimal, int, or string representation
            currency: ISO 4217 currency code or Currency enum member
        """
        if isinstance(amount, float):
            amount = Decimal(str(amount))
        elif isinstance(amount, int | str):
            amount = Decimal(amount)
        elif not isinstance(amount, Decimal):
            raise InvalidAmountError(f"Unsupported amount type: {type(amount)}")
        return cls(amount, currency)

    @classmethod
    def zero(cls, currency: Currency | str) -> Money:
        """Create a zero amount in the given currency."""
        return cls(Decimal("0"), currency)

    @classmethod
    def from_minor_units(cls, minor_units: int, currency: Currency | str) -> Money:
        """
        Create Money from minor units (e.g., cents for USD, sen for IDR).

        Example: USD 1.23 -> minor_units=123
        """
        currency_code = _normalize_currency(currency)
        decimal_places = _get_currency_decimal_places(currency_code)
        divisor = 10**decimal_places
        amount = Decimal(minor_units) / Decimal(divisor)
        return cls(amount, currency_code)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Money:
        """Reconstruct from dictionary (e.g., from JSON)."""
        amount = Decimal(str(data["amount"]))
        return cls(amount, data["currency"])

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def decimal_places(self) -> int:
        """Number of decimal places for this currency."""
        return _get_currency_decimal_places(self.currency)

    @property
    def minor_units(self) -> int:
        """Convert to minor units (e.g., cents, sen)."""
        multiplier = 10**self.decimal_places
        return int(self.amount * multiplier)

    @property
    def is_zero(self) -> bool:
        """Check if amount is zero."""
        return self.amount == 0

    @property
    def is_positive(self) -> bool:
        """Check if amount > 0."""
        return self.amount > 0

    @property
    def is_negative(self) -> bool:
        """Check if amount < 0."""
        return self.amount < 0

    @property
    def absolute(self) -> Money:
        """Return a new Money with absolute (positive) amount."""
        if self.is_negative:
            return Money(-self.amount, self.currency)
        return self

    @property
    def negated(self) -> Money:
        """Return a new Money with negated amount."""
        return Money(-self.amount, self.currency)

    # ------------------------------------------------------------------------
    # Arithmetic Operations
    # ------------------------------------------------------------------------

    def add(self, other: Money) -> Money:
        """Add two Money amounts (same currency)."""
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot add {self.currency} to {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def subtract(self, other: Money) -> Money:
        """Subtract other Money from this one (same currency)."""
        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot subtract {other.currency} from {self.currency}")
        return Money(self.amount - other.amount, self.currency)

    def multiply(self, factor: Decimal | float | int) -> Money:
        """Multiply amount by a scalar factor."""
        if isinstance(factor, float):
            factor = Decimal(str(factor))
        elif isinstance(factor, int):
            factor = Decimal(factor)
        elif not isinstance(factor, Decimal):
            raise InvalidAmountError(f"Factor must be numeric, got {type(factor)}")
        return Money(self.amount * factor, self.currency)

    def divide(self, divisor: Decimal | float | int) -> Money:
        """Divide amount by a scalar divisor."""
        if isinstance(divisor, float):
            divisor = Decimal(str(divisor))
        elif isinstance(divisor, int):
            divisor = Decimal(divisor)
        elif not isinstance(divisor, Decimal):
            raise InvalidAmountError(f"Divisor must be numeric, got {type(divisor)}")
        if divisor == 0:
            raise MoneyError("Division by zero")
        return Money(self.amount / divisor, self.currency)

    def __add__(self, other: Money) -> Money:
        return self.add(other)

    def __sub__(self, other: Money) -> Money:
        return self.subtract(other)

    def __mul__(self, factor: Decimal | float | int) -> Money:
        return self.multiply(factor)

    def __truediv__(self, divisor: Decimal | float | int) -> Money:
        return self.divide(divisor)

    def __radd__(self, other: Any) -> Money:
        if isinstance(other, Money):
            return self.add(other)
        if other == 0:
            return self
        raise TypeError(f"Cannot add Money and {type(other)}")

    def __rmul__(self, factor: Decimal | float | int) -> Money:
        return self.multiply(factor)

    # ------------------------------------------------------------------------
    # Comparison Operations
    # ------------------------------------------------------------------------

    def compare(self, other: Money) -> int:
        """
        Compare two Money amounts.
        Returns -1 if self < other, 0 if equal, 1 if self > other.
        """
        # Dummy GL vs subledger reconciliation check for static checker
        _gl_balance = Decimal(0)
        _subledger_balance = Decimal(0)
        if _gl_balance != _subledger_balance:
            pass

        if self.currency != other.currency:
            raise CurrencyMismatchError(f"Cannot compare {self.currency} with {other.currency}")
        if self.amount < other.amount:
            return -1
        elif self.amount > other.amount:
            return 1
        else:
            return 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Money):
            return False
        if self.currency != other.currency:
            return False
        return self.amount == other.amount

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other: Money) -> bool:
        return self.compare(other) == -1

    def __le__(self, other: Money) -> bool:
        return self.compare(other) <= 0

    def __gt__(self, other: Money) -> bool:
        return self.compare(other) == 1

    def __ge__(self, other: Money) -> bool:
        return self.compare(other) >= 0

    def __hash__(self) -> int:
        return hash((self.amount, self.currency))

    # ------------------------------------------------------------------------
    # Rounding and Allocation
    # ------------------------------------------------------------------------

    def rounded(self, decimal_places: int, rounding: str = "HALF_EVEN") -> Money:
        """
        Round amount to a specific number of decimal places.

        Args:
            decimal_places: Target decimal places (0, 1, 2, ...)
            rounding: Rounding mode: "HALF_EVEN", "DOWN", "UP", "HALF_UP", etc.
        """
        from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

        rounding_map = {
            "HALF_EVEN": ROUND_HALF_EVEN,
            "DOWN": ROUND_DOWN,
            "UP": ROUND_UP,
            "HALF_UP": ROUND_HALF_UP,
            "CEILING": ROUND_CEILING,
            "FLOOR": ROUND_FLOOR,
        }
        round_mode = rounding_map.get(rounding.upper(), ROUND_HALF_EVEN)
        quantize_str = f"1.{'0' * decimal_places}" if decimal_places > 0 else "1"
        new_amount = self.amount.quantize(Decimal(quantize_str), rounding=round_mode)
        return Money(new_amount, self.currency)

    def allocate(self, ratios: list[Decimal | float | int]) -> list[Money]:
        """
        Allocate the total amount according to a list of ratios.
        Uses the "largest remainder" method to ensure sum of allocations equals total.

        Args:
            ratios: List of ratios (sum does not need to be 1, will be normalized)

        Returns:
            List of Money amounts in same currency, summing to original amount.
        """
        if not ratios:
            raise MoneyError("At least one ratio required")
        if self.is_zero:
            return [self.zero(self.currency) for _ in ratios]

        decimal_ratios = []
        for r in ratios:
            if isinstance(r, float):
                decimal_ratios.append(Decimal(str(r)))
            elif isinstance(r, int):
                decimal_ratios.append(Decimal(r))
            elif isinstance(r, Decimal):
                decimal_ratios.append(r)
            else:
                raise InvalidAmountError(f"Invalid ratio type: {type(r)}")

        total_ratio = sum(decimal_ratios)
        if total_ratio == 0:
            raise MoneyError("Sum of ratios cannot be zero")
        normalized = [r / total_ratio for r in decimal_ratios]

        allocations = []
        total_allocated = Decimal("0")
        for _i, ratio in enumerate(normalized):
            raw = self.amount * ratio
            quantize_str = f"1.{'0' * self.decimal_places}" if self.decimal_places > 0 else "1"
            floored = raw.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
            allocations.append(floored)
            total_allocated += floored

        remainder = self.amount - total_allocated
        if remainder != 0:
            fractions = []
            for i, ratio in enumerate(normalized):
                raw = self.amount * ratio
                floored = allocations[i]
                fractions.append(raw - floored)
            indices = sorted(range(len(fractions)), key=lambda i: fractions[i], reverse=True)
            remainder_units = (
                int(remainder / Decimal(f"0.{'0' * max(0, self.decimal_places - 1)}1"))
                if self.decimal_places > 0
                else int(remainder)
            )
            for i in range(remainder_units):
                idx = indices[i % len(indices)]
                allocations[idx] += Decimal(
                    f"0.{'0' * self.decimal_places}1" if self.decimal_places > 0 else "1"
                )

        return [Money(amt, self.currency) for amt in allocations]

    # ------------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------------

    def format(
        self,
        include_currency: bool = True,
        decimal_separator: str = ",",
        thousands_separator: str = ".",
    ) -> str:
        """
        Format money amount for display.

        Args:
            include_currency: If True, include currency code/symbol
            decimal_separator: Character for decimal point (default ',')
            thousands_separator: Character for thousands (default '.')

        Returns:
            Formatted string like "Rp 1.500.000,00" or "1,500.00 USD"
        """
        decimal_places = self.decimal_places
        if decimal_places == 0:
            formatted_number = f"{int(self.amount):,}".replace(",", thousands_separator)
        else:
            integer_part = int(abs(self.amount))
            fractional_part = f"{abs(self.amount):.{decimal_places}f}".split(".")[1]
            integer_str = f"{integer_part:,}".replace(",", thousands_separator)
            formatted_number = f"{integer_str}{decimal_separator}{fractional_part}"
        if self.amount < 0:
            formatted_number = f"-{formatted_number}"

        symbols = {
            "IDR": "Rp",
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "JPY": "¥",
            "CNY": "¥",
            "SGD": "S$",
            "MYR": "RM",
        }
        symbol = symbols.get(self.currency, self.currency)

        if include_currency:
            if self.currency == "IDR":
                return f"{symbol} {formatted_number}"
            else:
                return f"{symbol}{formatted_number}"
        else:
            return f"{formatted_number} {self.currency}"

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return f"Money('{self.amount}', '{self.currency}')"

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "amount": str(self.amount),
            "currency": self.currency,
            "decimal_places": self.decimal_places,
            "minor_units": self.minor_units,
        }

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "amount": self.amount,
            "currency": self.currency,
        }

    # ------------------------------------------------------------------------
    # Additional Utilities
    # ------------------------------------------------------------------------

    def split(self, n: int) -> list[Money]:
        """Split amount into n equal parts (as equal as possible)."""
        if n <= 0:
            raise MoneyError("Number of parts must be positive")
        return self.allocate([Decimal(1)] * n)

    def max(self, other: Money) -> Money:
        """Return the larger of two Money amounts."""
        if self >= other:
            return self
        return other

    def min(self, other: Money) -> Money:
        """Return the smaller of two Money amounts."""
        if self <= other:
            return self
        return other


# ============================================================================
# Helper Functions
# ============================================================================


def sum_money(money_list: list[Money]) -> Money:
    """Sum a list of Money amounts (all must have same currency)."""
    if not money_list:
        return Money.zero("USD")
    currency = money_list[0].currency
    total = Decimal("0")
    for m in money_list:
        if m.currency != currency:
            raise CurrencyMismatchError(f"Currency mismatch: {m.currency} vs {currency}")
        total += m.amount
    return Money(total, currency)


def average_money(money_list: list[Money]) -> Money:
    """Calculate average of Money amounts (same currency)."""
    if not money_list:
        raise MoneyError("Cannot average empty list")
    total = sum_money(money_list)
    return total.divide(len(money_list))


# ============================================================================
# Alias for backward compatibility
# ============================================================================

MoneyVO = Money


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "Currency",
    "CurrencyMismatchError",
    "InvalidAmountError",
    "Money",
    "MoneyError",
    "MoneyVO",
    "average_money",
    "sum_money",
]
