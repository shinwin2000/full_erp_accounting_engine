#!/usr/bin/env python3
"""
Module: exchange_rate_vo.py
Layer: Domain / Forex
Responsibility: Value object untuk kurs valuta asing dengan semua method value object.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# Custom Exceptions
# ============================================================================


class ExchangeRateError(ValueError):
    pass


class InvalidCurrencyError(ExchangeRateError):
    pass


class InvalidRateError(ExchangeRateError):
    pass


class InvalidEffectiveDateError(ExchangeRateError):
    pass


# ============================================================================
# Helper Functions
# ============================================================================


def _validate_currency(currency: str) -> str:
    """Validate ISO 4217 currency code."""
    if not currency or not isinstance(currency, str):
        raise InvalidCurrencyError("Currency must be a non-empty string")
    cleaned = currency.strip().upper()
    if len(cleaned) != 3:
        raise InvalidCurrencyError(f"Currency code must be exactly 3 characters, got '{cleaned}'")
    if not re.match(r"^[A-Z]{3}$", cleaned):
        raise InvalidCurrencyError(f"Currency code must contain only letters, got '{cleaned}'")
    return cleaned


def _validate_rate(rate: Decimal) -> Decimal:
    """Validate exchange rate (positive)."""
    if not isinstance(rate, Decimal):
        try:
            rate = Decimal(str(rate))
        except Exception:
            raise InvalidRateError(f"Invalid rate type: {type(rate)}")
    if rate <= 0:
        raise InvalidRateError(f"Exchange rate must be positive: {rate}")
    return rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def _validate_effective_date(effective_date: date | datetime) -> datetime:
    """Validate effective date (not too far in future)."""
    if isinstance(effective_date, date) and not isinstance(effective_date, datetime):
        effective_date = datetime.combine(effective_date, datetime.min.time())
    if effective_date.tzinfo is None:
        effective_date = effective_date.replace(tzinfo=UTC)
    # Allow future dates but warn
    if effective_date > datetime.now(UTC) + timedelta(days=365):
        logger.warning(f"Effective date {effective_date} is more than one year in the future")
    return effective_date


# ============================================================================
# Value Object: ExchangeRate
# ============================================================================


@dataclass(frozen=True)
class ExchangeRate:
    """
    Immutable value object untuk kurs valuta asing.

    Attributes:
        currency: Kode mata uang (USD, EUR, JPY, dll) dalam mata uang asing
        functional_currency: Mata uang fungsional (default IDR)
        rate: Nilai kurs (1 unit currency = rate functional_currency)
        effective_date: Tanggal efektif kurs
        source: Sumber kurs ('bank', 'coretax', 'manual', 'average')
        is_average: Apakah ini kurs rata-rata (untuk konversi laporan laba rugi)
        created_at: Timestamp pembuatan
        created_by: User pembuat

    Examples:
        >>> rate = ExchangeRate(
        ...     currency="USD",
        ...     rate=Decimal("15500"),
        ...     effective_date=datetime(2024, 12, 31, tzinfo=UTC)
        ... )
        >>> rate.convert(Decimal("1000"))
        Decimal('15500000.00')
        >>> rate.to_dict()
        {...}
    """

    currency: str
    rate: Decimal
    effective_date: datetime
    functional_currency: str = "IDR"
    source: str = "manual"
    is_average: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_by: str = "system"
    version: int = 1

    def __post_init__(self) -> None:
        """Validate exchange rate data."""
        # Validate currency
        normalized_currency = _validate_currency(self.currency)
        if normalized_currency != self.currency:
            object.__setattr__(self, "currency", normalized_currency)

        # Validate functional_currency
        normalized_func = _validate_currency(self.functional_currency)
        if normalized_func != self.functional_currency:
            object.__setattr__(self, "functional_currency", normalized_func)

        # Validate rate
        normalized_rate = _validate_rate(self.rate)
        if normalized_rate != self.rate:
            object.__setattr__(self, "rate", normalized_rate)

        # Validate effective_date
        normalized_date = _validate_effective_date(self.effective_date)
        if normalized_date != self.effective_date:
            object.__setattr__(self, "effective_date", normalized_date)

        # Validate source
        if not self.source or len(self.source.strip()) < 2:
            object.__setattr__(self, "source", "manual")

        # Validate created_at
        if self.created_at.tzinfo is None:
            object.__setattr__(self, "created_at", self.created_at.replace(tzinfo=UTC))

        # Validate version
        if self.version < 1:
            raise ExchangeRateError("Version must be >= 1")

        # Ensure currency and functional_currency are different
        if self.currency == self.functional_currency:
            raise ExchangeRateError(f"Currency {self.currency} cannot equal functional currency")

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    @property
    def rate_as_float(self) -> float:
        """Rate as float."""
        return float(self.rate)

    @property
    def inverse_rate(self) -> Decimal:
        """Inverse rate (1 unit of functional currency = rate inverse in foreign currency)."""
        return (Decimal("1") / self.rate).quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)

    @property
    def display_rate(self) -> str:
        """Formatted rate for display."""
        return f"1 {self.currency} = {self.rate:,.4f} {self.functional_currency}"

    @property
    def effective_date_only(self) -> date:
        """Effective date as date only."""
        return self.effective_date.date()

    @property
    def is_spot_rate(self) -> bool:
        """Check if this is a spot rate (not average)."""
        return not self.is_average

    # ------------------------------------------------------------------------
    # Conversion Methods
    # ------------------------------------------------------------------------

    def convert(self, amount: Decimal) -> Decimal:
        """
        Convert amount from foreign currency to functional currency.

        Args:
            amount: Amount in foreign currency

        Returns:
            Amount in functional currency
        """
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        result = amount * self.rate
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def convert_inverse(self, amount: Decimal) -> Decimal:
        """
        Convert amount from functional currency to foreign currency.

        Args:
            amount: Amount in functional currency

        Returns:
            Amount in foreign currency
        """
        if not isinstance(amount, Decimal):
            amount = Decimal(str(amount))
        result = amount / self.rate
        return result.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    def calculate_gain_loss(self, other: ExchangeRate, balance: Decimal) -> tuple[Decimal, str]:
        """
        Calculate gain/loss between this rate and another rate.

        Args:
            other: Other exchange rate (new rate)
            balance: Balance in foreign currency

        Returns:
            (gain_loss_amount, type) where type is "GAIN", "LOSS", or "NEUTRAL"
        """
        if self.currency != other.currency:
            raise ExchangeRateError(f"Currency mismatch: {self.currency} vs {other.currency}")
        gain_loss = balance * (other.rate - self.rate)
        gain_loss_abs = abs(gain_loss).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
        if gain_loss > 0:
            return gain_loss_abs, "GAIN"
        elif gain_loss < 0:
            return gain_loss_abs, "LOSS"
        else:
            return Decimal("0"), "NEUTRAL"

    def is_effective_on(self, check_date: date | datetime) -> bool:
        """
        Check if this exchange rate is effective on a given date.

        Args:
            check_date: Date to check

        Returns:
            True if effective_date <= check_date
        """
        if isinstance(check_date, date) and not isinstance(check_date, datetime):
            check_date = datetime.combine(check_date, datetime.min.time(), tzinfo=UTC)
        if check_date.tzinfo is None:
            check_date = check_date.replace(tzinfo=UTC)
        return self.effective_date <= check_date

    # ------------------------------------------------------------------------
    # Comparison Methods
    # ------------------------------------------------------------------------

    def is_higher_than(self, other: ExchangeRate) -> bool:
        """Check if this rate is higher than other rate."""
        return self.rate > other.rate

    def is_lower_than(self, other: ExchangeRate) -> bool:
        """Check if this rate is lower than other rate."""
        return self.rate < other.rate

    def percentage_change(self, other: ExchangeRate) -> Decimal:
        """Calculate percentage change from this rate to other rate."""
        if self.rate == 0:
            return Decimal("0")
        change = (other.rate - self.rate) / self.rate * Decimal("100")
        return change.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    # ------------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "currency": self.currency,
            "functional_currency": self.functional_currency,
            "rate": str(self.rate),
            "inverse_rate": str(self.inverse_rate),
            "effective_date": self.effective_date.isoformat(),
            "effective_date_only": self.effective_date_only.isoformat(),
            "source": self.source,
            "is_average": self.is_average,
            "is_spot_rate": self.is_spot_rate,
            "display_rate": self.display_rate,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExchangeRate:
        """Reconstruct from dictionary."""
        effective_date = data["effective_date"]
        if isinstance(effective_date, str):
            effective_date = datetime.fromisoformat(effective_date)
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(UTC)
        return cls(
            currency=data["currency"],
            rate=Decimal(data["rate"]),
            effective_date=effective_date,
            functional_currency=data.get("functional_currency", "IDR"),
            source=data.get("source", "manual"),
            is_average=data.get("is_average", False),
            created_at=created_at,
            created_by=data.get("created_by", "system"),
            version=data.get("version", 1),
        )

    def to_db_record(self) -> dict[str, Any]:
        """Convert to database-friendly format."""
        return {
            "currency": self.currency,
            "functional_currency": self.functional_currency,
            "rate": self.rate,
            "effective_date": self.effective_date,
            "source": self.source,
            "is_average": self.is_average,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "version": self.version,
        }

    # ------------------------------------------------------------------------
    # Dunder Methods
    # ------------------------------------------------------------------------

    def __str__(self) -> str:
        return self.display_rate

    def __repr__(self) -> str:
        return f"ExchangeRate({self.currency}→{self.functional_currency}: {self.rate} as of {self.effective_date.date()})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExchangeRate):
            return False
        return (
            self.currency == other.currency
            and self.functional_currency == other.functional_currency
            and self.rate == other.rate
            and self.effective_date == other.effective_date
        )

    def __hash__(self) -> int:
        return hash((self.currency, self.functional_currency, self.rate, self.effective_date))


# ============================================================================
# Helper Functions
# ============================================================================


def calculate_cross_rate(
    rate1: ExchangeRate, rate2: ExchangeRate, target_currency: str
) -> ExchangeRate:
    """Calculate cross exchange rate between two currencies."""
    if rate1.currency == rate2.currency:
        raise ExchangeRateError("Cannot calculate cross rate between same currency")
    if rate1.functional_currency != rate2.functional_currency:
        raise ExchangeRateError("Both rates must have same functional currency")

    # Convert rate1 to rate2.currency using rate2
    # cross rate = (rate1.rate / rate2.rate) if converting to rate2.currency
    cross_rate_value = rate1.rate / rate2.rate
    return ExchangeRate(
        currency=rate1.currency,
        rate=cross_rate_value,
        effective_date=max(rate1.effective_date, rate2.effective_date),
        functional_currency=target_currency,
        source="cross_calculation",
    )


__all__ = [
    "ExchangeRate",
    "ExchangeRateError",
    "InvalidCurrencyError",
    "InvalidEffectiveDateError",
    "InvalidRateError",
    "calculate_cross_rate",
]
