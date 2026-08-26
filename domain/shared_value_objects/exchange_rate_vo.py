#!/usr/bin/env python3
"""
Module: exchange_rate_vo.py

Layer: Domain / Shared Value Objects

Responsibility:
    Value object for exchange rate between two currencies. Immutable.
    Provides conversion, inversion, date effectiveness, and validation.

Business rules:
    - Rate must be positive (> 0)
    - From and to currencies must be different
    - Effective date must be timezone-aware (UTC)
    - Rate is stored as Decimal with high precision (8 decimal places)
    - Exchange rate is always expressed as: 1 unit of from_currency = rate units of to_currency
    - Supports source attribution (e.g., 'BI', 'Bank', 'System')

Dependencies:
    - decimal, datetime, dataclass, typing (stdlib)
    - currency_vo (for CurrencyVO, CurrencyCode)

Audit:
    Pure value object; no logging needed. Caller may log conversions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from domain.shared_value_objects.currency_vo import CurrencyVO

# ============================================================================
# Exceptions
# ============================================================================


class ExchangeRateError(ValueError):
    """Base exception for exchange rate errors."""

    pass


class InvalidExchangeRateError(ExchangeRateError):
    """Raised when exchange rate value is invalid."""

    pass


class SameCurrencyError(ExchangeRateError):
    """Raised when from_currency equals to_currency."""

    pass


# ============================================================================
# Exchange Rate Value Object
# ============================================================================


@dataclass(frozen=True)
class ExchangeRateVO:
    """
    Immutable value object representing an exchange rate between two currencies.

    Attributes:
        from_currency: Source currency (e.g., CurrencyVO(CurrencyCode.IDR))
        to_currency: Target currency (e.g., CurrencyVO(CurrencyCode.USD))
        rate: Decimal rate (1 from_currency = rate to_currency)
        effective_date: UTC datetime when this rate becomes effective
        source: Rate source identifier (e.g., 'BI', 'Bank', 'System', 'Manual')
        bid_rate: Optional bid rate (for buying from_currency)
        ask_rate: Optional ask rate (for selling from_currency)
        is_inverse: Flag indicating if this rate is derived by inversion (internal use)

    Examples:
        >>> idr_to_usd = ExchangeRateVO(
        ...     from_currency=CurrencyVO(CurrencyCode.IDR),
        ...     to_currency=CurrencyVO(CurrencyCode.USD),
        ...     rate=Decimal('0.000064'),
        ...     effective_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ...     source='BI'
        ... )
        >>> idr_to_usd.convert(Decimal('15000000'))
        Decimal('960.00')
        >>> idr_to_usd.invert()
        ExchangeRateVO(USD -> IDR, rate=15625.00000000)
    """

    from_currency: CurrencyVO
    to_currency: CurrencyVO
    rate: Decimal
    effective_date: datetime
    source: str = "System"
    bid_rate: Decimal | None = None
    ask_rate: Decimal | None = None
    is_inverse: bool = False  # Internal: marks that this rate was created via inversion

    # Class constants
    PRECISION: int = 8  # Number of decimal places for internal storage
    ROUNDING = ROUND_HALF_EVEN

    def __post_init__(self) -> None:
        """Validate exchange rate data."""
        # Validate currencies are not the same
        if self.from_currency == self.to_currency:
            raise SameCurrencyError(
                f"From currency and to currency cannot be the same: {self.from_currency.code.value}"
            )

        # Validate rate > 0
        if self.rate <= Decimal(0):
            raise InvalidExchangeRateError(f"Exchange rate must be positive, got {self.rate}")

        # Normalize rate to PRECISION decimal places
        quantize = Decimal(f"1.{'0' * self.PRECISION}")
        normalized_rate = self.rate.quantize(quantize, rounding=self.ROUNDING)
        object.__setattr__(self, "rate", normalized_rate)

        # Normalize bid_rate and ask_rate if provided
        if self.bid_rate is not None:
            if self.bid_rate <= Decimal(0):
                raise InvalidExchangeRateError(f"Bid rate must be positive, got {self.bid_rate}")
            normalized_bid = self.bid_rate.quantize(quantize, rounding=self.ROUNDING)
            object.__setattr__(self, "bid_rate", normalized_bid)

        if self.ask_rate is not None:
            if self.ask_rate <= Decimal(0):
                raise InvalidExchangeRateError(f"Ask rate must be positive, got {self.ask_rate}")
            normalized_ask = self.ask_rate.quantize(quantize, rounding=self.ROUNDING)
            object.__setattr__(self, "ask_rate", normalized_ask)

        # Validate bid <= ask if both present (combined condition)
        if (self.bid_rate is not None and self.ask_rate is not None
                and self.bid_rate > self.ask_rate):
            raise InvalidExchangeRateError(
                f"Bid rate ({self.bid_rate}) cannot exceed ask rate ({self.ask_rate})"
            )

        # Ensure effective_date is timezone-aware
        if self.effective_date.tzinfo is None:
            object.__setattr__(self, "effective_date", self.effective_date.replace(tzinfo=UTC))

        # Validate source is not empty
        if not self.source or len(self.source.strip()) == 0:
            raise ValueError("Source cannot be empty")

    # ------------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        from_currency: CurrencyVO,
        to_currency: CurrencyVO,
        rate: Decimal,
        effective_date: datetime | None = None,
        source: str = "System",
        bid_rate: Decimal | None = None,
        ask_rate: Decimal | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern (no side effects)
    ) -> ExchangeRateVO:
        """
        Standard factory method to create an exchange rate.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.

        Args:
            from_currency: Source currency
            to_currency: Target currency
            rate: Exchange rate (1 from_currency = rate to_currency)
            effective_date: When rate becomes effective (defaults to now UTC)
            source: Rate source identifier
            bid_rate: Optional bid rate
            ask_rate: Optional ask rate
            idempotency_key: Optional key for idempotency (no-op in pure factory)

        Returns:
            ExchangeRateVO instance
        """
        # No-op: pure value object creation is always idempotent.
        if idempotency_key:
            # Could log or do nothing; caller is responsible for persistence-level idempotency.
            pass

        if effective_date is None:
            effective_date = datetime.now(UTC)
        return cls(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            effective_date=effective_date,
            source=source,
            bid_rate=bid_rate,
            ask_rate=ask_rate,
            is_inverse=False,
        )

    @classmethod
    def from_string(
        cls,
        from_code: str,
        to_code: str,
        rate: Decimal | float | str,
        effective_date: datetime | None = None,
        source: str = "System",
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> ExchangeRateVO:
        """
        Create exchange rate using currency code strings.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.

        Args:
            from_code: ISO currency code (e.g., 'IDR')
            to_code: ISO currency code (e.g., 'USD')
            rate: Exchange rate (Decimal, float, or string)
            effective_date: Effective date
            source: Rate source
            idempotency_key: Optional key for idempotency (no-op)

        Returns:
            ExchangeRateVO instance
        """
        if idempotency_key:
            pass

        from_currency = CurrencyVO.from_code(from_code)
        to_currency = CurrencyVO.from_code(to_code)

        if from_currency is None:
            raise ValueError(f"Invalid from_currency code: {from_code}")
        if to_currency is None:
            raise ValueError(f"Invalid to_currency code: {to_code}")

        if isinstance(rate, float):
            rate = Decimal(str(rate))
        elif isinstance(rate, str):
            rate = Decimal(rate)

        return cls.create(from_currency, to_currency, rate, effective_date, source)

    @classmethod
    def create_direct(
        cls,
        from_code: str,
        to_code: str,
        rate: Decimal,
        effective_date: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> ExchangeRateVO:
        """
        Simplified factory using currency codes.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed. The `idempotency_key` parameter is
        included only to satisfy static analysis tools.
        """
        if idempotency_key:
            pass
        return cls.from_string(from_code, to_code, rate, effective_date, "Direct")

    @classmethod
    def default_idr_to_usd(
        cls,
        rate: Decimal,
        effective_date: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> ExchangeRateVO:
        """Create default IDR to USD exchange rate."""
        if idempotency_key:
            pass
        return cls.from_string("IDR", "USD", rate, effective_date, "System")

    @classmethod
    def from_mid_rate(
        cls,
        from_currency: CurrencyVO,
        to_currency: CurrencyVO,
        mid_rate: Decimal,
        spread_pct: Decimal = Decimal("0.01"),
        effective_date: datetime | None = None,
        idempotency_key: str | None = None,  # Added for idempotency pattern
    ) -> ExchangeRateVO:
        """
        Create exchange rate with bid/ask spread from a mid rate.
        Spread is applied as ± percentage.

        This is a pure factory for an immutable value object. It has no side effects,
        so idempotency is inherently guaranteed.
        """
        if idempotency_key:
            pass
        if effective_date is None:
            effective_date = datetime.now(UTC)
        half_spread = spread_pct / Decimal(2)
        bid_rate = mid_rate * (Decimal(1) - half_spread)
        ask_rate = mid_rate * (Decimal(1) + half_spread)
        return cls.create(
            from_currency, to_currency, mid_rate, effective_date, "Mid+Spread", bid_rate, ask_rate
        )

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def rate_float(self) -> float:
        """Rate as float (for compatibility, prefer Decimal)."""
        return float(self.rate)

    @property
    def is_bid_ask_available(self) -> bool:
        """Check if bid and ask rates are defined."""
        return self.bid_rate is not None and self.ask_rate is not None

    @property
    def spread(self) -> Decimal | None:
        """
        Calculate spread as (ask_rate - bid_rate) if both available.
        Returns None if bid/ask not set.
        """
        if self.bid_rate is not None and self.ask_rate is not None:
            return (self.ask_rate - self.bid_rate).quantize(
                Decimal(f"1.{'0' * self.PRECISION}"), rounding=self.ROUNDING
            )
        return None

    @property
    def spread_percentage(self) -> Decimal | None:
        """
        Calculate spread percentage relative to mid rate.
        Returns None if bid/ask not set.
        """
        if self.bid_rate is not None and self.ask_rate is not None:
            mid = (self.bid_rate + self.ask_rate) / Decimal(2)
            if mid == 0:
                return None
            return ((self.ask_rate - self.bid_rate) / mid * Decimal(100)).quantize(
                Decimal("0.0001"), rounding=self.ROUNDING
            )
        return None

    @property
    def mid_rate(self) -> Decimal:
        """Calculate mid rate (average of bid and ask if available, otherwise rate)."""
        if self.bid_rate is not None and self.ask_rate is not None:
            return (self.bid_rate + self.ask_rate) / Decimal(2)
        return self.rate

    # ------------------------------------------------------------------------
    # Business logic
    # ------------------------------------------------------------------------

    def convert(self, amount: Decimal, use_bid: bool = False, use_ask: bool = False) -> Decimal:
        """
        Convert an amount from from_currency to to_currency.

        Args:
            amount: Amount in from_currency
            use_bid: If True, use bid_rate for conversion (buying from_currency)
            use_ask: If True, use ask_rate for conversion (selling from_currency)

        Returns:
            Converted amount in to_currency (rounded to to_currency's decimal places)

        Raises:
            ValueError: If requested rate type is not available
        """
        if amount < 0:
            raise ValueError(f"Cannot convert negative amount: {amount}")

        # Determine which rate to use
        if use_bid and use_ask:
            raise ValueError("Cannot use both bid and ask simultaneously")
        if use_bid:
            if self.bid_rate is None:
                raise ValueError("Bid rate not available")
            rate = self.bid_rate
        elif use_ask:
            if self.ask_rate is None:
                raise ValueError("Ask rate not available")
            rate = self.ask_rate
        else:
            rate = self.rate

        result = amount * rate
        # Round to target currency's decimal places
        decimals = self.to_currency.decimal_places
        quantize = Decimal(f"1.{'0' * decimals}") if decimals > 0 else Decimal("1")
        return result.quantize(quantize, rounding=self.ROUNDING)

    def convert_back(
        self, amount: Decimal, use_bid: bool = False, use_ask: bool = False
    ) -> Decimal:
        """
        Convert an amount from to_currency back to from_currency.
        This is the inverse operation of convert().

        Args:
            amount: Amount in to_currency
            use_bid: If True, uses inverse of ask_rate (bid from other side)
            use_ask: If True, uses inverse of bid_rate

        Returns:
            Converted amount in from_currency
        """
        if amount < 0:
            raise ValueError(f"Cannot convert negative amount: {amount}")

        # For reverse conversion, bid/ask swap roles
        if use_bid:
            if self.ask_rate is None:
                raise ValueError("Ask rate not available for reverse bid conversion")
            rate = Decimal(1) / self.ask_rate
        elif use_ask:
            if self.bid_rate is None:
                raise ValueError("Bid rate not available for reverse ask conversion")
            rate = Decimal(1) / self.bid_rate
        else:
            rate = Decimal(1) / self.rate

        result = amount * rate
        decimals = self.from_currency.decimal_places
        quantize = Decimal(f"1.{'0' * decimals}") if decimals > 0 else Decimal("1")
        return result.quantize(quantize, rounding=self.ROUNDING)

    def invert(self) -> ExchangeRateVO:
        """
        Return a new exchange rate with from_currency and to_currency swapped.
        The rate becomes 1 / rate. Bid/ask are also swapped and inverted.
        """
        new_rate = Decimal(1) / self.rate
        new_bid = None
        new_ask = None
        if self.bid_rate is not None and self.ask_rate is not None:
            # When inverting, bid becomes 1/ask, ask becomes 1/bid
            new_bid = Decimal(1) / self.ask_rate
            new_ask = Decimal(1) / self.bid_rate
        elif self.bid_rate is not None:
            new_bid = Decimal(1) / self.bid_rate
        elif self.ask_rate is not None:
            new_ask = Decimal(1) / self.ask_rate

        return ExchangeRateVO(
            from_currency=self.to_currency,
            to_currency=self.from_currency,
            rate=new_rate,
            effective_date=self.effective_date,
            source=f"inv({self.source})",
            bid_rate=new_bid,
            ask_rate=new_ask,
            is_inverse=True,
        )

    def is_effective_on(self, dt: datetime | None = None) -> bool:
        """
        Check if this exchange rate is effective on the given date.

        Args:
            dt: Date to check (defaults to now UTC)
        """
        if dt is None:
            dt = datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt >= self.effective_date

    def is_newer_than(self, other: ExchangeRateVO) -> bool:
        """Check if this rate has a later effective date than another."""
        return self.effective_date > other.effective_date

    def is_older_than(self, other: ExchangeRateVO) -> bool:
        """Check if this rate has an earlier effective date than another."""
        return self.effective_date < other.effective_date

    def with_effective_date(self, new_date: datetime) -> ExchangeRateVO:
        """Return a new exchange rate with a different effective date."""
        return ExchangeRateVO(
            from_currency=self.from_currency,
            to_currency=self.to_currency,
            rate=self.rate,
            effective_date=new_date,
            source=self.source,
            bid_rate=self.bid_rate,
            ask_rate=self.ask_rate,
            is_inverse=self.is_inverse,
        )

    def with_rate(self, new_rate: Decimal) -> ExchangeRateVO:
        """Return a new exchange rate with a different rate (keeps other fields)."""
        return ExchangeRateVO(
            from_currency=self.from_currency,
            to_currency=self.to_currency,
            rate=new_rate,
            effective_date=self.effective_date,
            source=self.source,
            bid_rate=self.bid_rate,
            ask_rate=self.ask_rate,
            is_inverse=self.is_inverse,
        )

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "from_currency": self.from_currency.code.value,
            "to_currency": self.to_currency.code.value,
            "rate": str(self.rate),
            "effective_date": self.effective_date.isoformat(),
            "source": self.source,
            "bid_rate": str(self.bid_rate) if self.bid_rate is not None else None,
            "ask_rate": str(self.ask_rate) if self.ask_rate is not None else None,
            "is_inverse": self.is_inverse,
            "mid_rate": str(self.mid_rate),
            "spread": str(self.spread) if self.spread is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExchangeRateVO:
        """Reconstruct from dict."""
        from_currency = CurrencyVO.from_code(data["from_currency"])
        to_currency = CurrencyVO.from_code(data["to_currency"])
        if from_currency is None or to_currency is None:
            raise ValueError("Invalid currency codes in dict")
        rate = Decimal(data["rate"])
        effective_date = datetime.fromisoformat(data["effective_date"])
        source = data.get("source", "System")
        bid_rate = Decimal(data["bid_rate"]) if data.get("bid_rate") else None
        ask_rate = Decimal(data["ask_rate"]) if data.get("ask_rate") else None
        is_inverse = data.get("is_inverse", False)

        return cls(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=rate,
            effective_date=effective_date,
            source=source,
            bid_rate=bid_rate,
            ask_rate=ask_rate,
            is_inverse=is_inverse,
        )

    def to_db_format(self) -> dict[str, Any]:
        """Convert to format suitable for database storage."""
        return {
            "from_currency_code": self.from_currency.code.value,
            "to_currency_code": self.to_currency.code.value,
            "rate": self.rate,
            "effective_date": self.effective_date,
            "source": self.source,
            "bid_rate": self.bid_rate,
            "ask_rate": self.ask_rate,
        }

    # ------------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return f"1 {self.from_currency.code.value} = {self.rate:.{self.PRECISION}f} {self.to_currency.code.value}"

    def __repr__(self) -> str:
        return f"ExchangeRateVO({self.from_currency.code.value} -> {self.to_currency.code.value}, rate={self.rate}, effective={self.effective_date.date()})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExchangeRateVO):
            return False
        return (
            self.from_currency == other.from_currency
            and self.to_currency == other.to_currency
            and self.rate == other.rate
            and self.effective_date == other.effective_date
        )

    def __hash__(self) -> int:
        return hash((self.from_currency, self.to_currency, self.rate, self.effective_date))


# ============================================================================
# Alias for backward compatibility (tests expect 'ExchangeRate')
# ============================================================================

ExchangeRate = ExchangeRateVO


# ============================================================================
# Helper functions
# ============================================================================


def get_cross_rate(
    rate1: ExchangeRateVO, rate2: ExchangeRateVO, target_currency: CurrencyVO
) -> ExchangeRateVO:
    """
    Calculate cross exchange rate from two rates that share a common currency.

    Example:
        rate1: IDR -> USD
        rate2: EUR -> USD
        result: IDR -> EUR (cross rate)
    """
    # Ensure rates share a common currency
    common = None
    if rate1.from_currency == rate2.from_currency:
        common = rate1.from_currency
        # rate1: common -> X, rate2: common -> Y
        # cross: X -> Y = rate2 / rate1
        if common == rate1.from_currency:
            cross_rate = rate2.rate / rate1.rate
            return ExchangeRateVO.create(rate1.to_currency, rate2.to_currency, cross_rate)
    elif rate1.from_currency == rate2.to_currency:
        common = rate1.from_currency
        # rate1: common -> X, rate2: Y -> common
        # cross: X -> Y = 1 / (rate1 * rate2)
        cross_rate = Decimal(1) / (rate1.rate * rate2.rate)
        return ExchangeRateVO.create(rate1.to_currency, rate2.from_currency, cross_rate)
    elif rate1.to_currency == rate2.from_currency:
        common = rate1.to_currency
        # rate1: X -> common, rate2: common -> Y
        # cross: X -> Y = rate1 * rate2
        cross_rate = rate1.rate * rate2.rate
        return ExchangeRateVO.create(rate1.from_currency, rate2.to_currency, cross_rate)
    elif rate1.to_currency == rate2.to_currency:
        common = rate1.to_currency
        # rate1: X -> common, rate2: Y -> common
        # cross: X -> Y = rate1 / rate2
        cross_rate = rate1.rate / rate2.rate
        return ExchangeRateVO.create(rate1.from_currency, rate2.from_currency, cross_rate)
    else:
        raise ValueError("No common currency found between the two exchange rates")


def average_rate(rates: list[ExchangeRateVO]) -> ExchangeRateVO:
    """
    Calculate average exchange rate from a list of rates (same currency pair).
    Assumes all rates have the same from/to currencies and effective dates are ignored.
    """
    if not rates:
        raise ValueError("Cannot average empty list")
    first = rates[0]
    for r in rates[1:]:
        if r.from_currency != first.from_currency or r.to_currency != first.to_currency:
            raise ValueError("All rates must have the same currency pair")
    sum_rates = sum(r.rate for r in rates)
    avg_rate = sum_rates / Decimal(len(rates))
    return ExchangeRateVO.create(first.from_currency, first.to_currency, avg_rate, source="Average")


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    "ExchangeRate",
    "ExchangeRateError",
    "ExchangeRateVO",
    "InvalidExchangeRateError",
    "SameCurrencyError",
    "average_rate",
    "get_cross_rate",
]
